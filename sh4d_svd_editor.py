#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roland SH-4d .SVD Backup / Patch / Pattern / Rhythm Kit Editor & Librarian
Workspace: dawless_project
Supports Roland SVD5 (JP-M) binary database files (e.g. SH4d.SVD).
"""

import os
import sys
import shutil
import struct
import ctypes
import argparse
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

DEFAULT_SVD_PATH = r"C:\Users\orkun\Downloads\SH4d.SVD"


class MIDIOUTCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", ctypes.c_ushort),
        ("wPid", ctypes.c_ushort),
        ("vDriverVersion", ctypes.c_uint),
        ("szPname", ctypes.c_wchar * 32),
        ("wTechnology", ctypes.c_ushort),
        ("wVoices", ctypes.c_ushort),
        ("wNotes", ctypes.c_ushort),
        ("wChannelMask", ctypes.c_ushort),
        ("dwSupport", ctypes.c_uint),
    ]


class WinMMMidiOut:
    """Zero-dependency Windows WinMM Real-Time MIDI Output wrapper."""

    def __init__(self):
        self.winmm = ctypes.windll.winmm if sys.platform == "win32" else None
        self.handle = ctypes.c_void_p(0)
        self.opened_port = None

    def list_ports(self) -> list:
        if not self.winmm:
            return []
        n = self.winmm.midiOutGetNumDevs()
        ports = []
        for i in range(n):
            caps = MIDIOUTCAPSW()
            if self.winmm.midiOutGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
                ports.append((i, caps.szPname))
        return ports

    def open(self, port_idx: int) -> bool:
        self.close()
        if not self.winmm:
            return False
        h = ctypes.c_void_p(0)
        res = self.winmm.midiOutOpen(ctypes.byref(h), port_idx, 0, 0, 0)
        if res == 0:
            self.handle = h
            self.opened_port = port_idx
            return True
        return False

    def close(self):
        if self.winmm and self.handle and self.handle.value:
            self.winmm.midiOutClose(self.handle)
        self.handle = ctypes.c_void_p(0)
        self.opened_port = None

    def send_short(self, status: int, data1: int, data2: int = 0):
        if not (self.winmm and self.handle and self.handle.value):
            return
        msg = (status & 0xFF) | ((data1 & 0x7F) << 8) | ((data2 & 0x7F) << 16)
        self.winmm.midiOutShortMsg(self.handle, msg)

    def send_cc(self, channel_1_16: int, cc: int, value: int):
        ch = max(0, min(15, int(channel_1_16) - 1))
        self.send_short(0xB0 | ch, max(0, min(127, int(cc))), max(0, min(127, int(value))))

    def send_pc(self, channel_1_16: int, msb: int, lsb: int, pc: int):
        self.send_cc(channel_1_16, 0, msb)
        self.send_cc(channel_1_16, 32, lsb)
        ch = max(0, min(15, int(channel_1_16) - 1))
        self.send_short(0xC0 | ch, max(0, min(127, int(pc))), 0)

    def send_note_on(self, channel_1_16: int, note: int, velocity: int = 100):
        ch = max(0, min(15, int(channel_1_16) - 1))
        self.send_short(0x90 | ch, max(0, min(127, int(note))), max(0, min(127, int(velocity))))

    def send_note_off(self, channel_1_16: int, note: int):
        ch = max(0, min(15, int(channel_1_16) - 1))
        self.send_short(0x80 | ch, max(0, min(127, int(note))), 0)

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Standard 26 Drum Key labels on the SH-4d (MIDI Notes 36..61 = C2..C#4)
DRUM_KEY_LABELS = [
    "BD 1 (Kick 1)",       # 36 C2
    "Rim / Side Stick",    # 37 C#2
    "SD 1 (Snare 1)",      # 38 D2
    "Hand Clap",           # 39 D#2
    "SD 2 (Snare 2)",      # 40 E2
    "Low Tom 2",           # 41 F2
    "Closed Hi-Hat",       # 42 F#2
    "Low Tom 1",           # 43 G2
    "Pedal Hi-Hat",        # 44 G#2
    "Mid Tom 2",           # 45 A2
    "Open Hi-Hat",         # 46 A#2
    "Mid Tom 1",           # 47 B2
    "High Tom 2",          # 48 C3
    "Crash Cymbal 1",      # 49 C#3
    "High Tom 1",          # 50 D3
    "Ride Cymbal 1",       # 51 D#3
    "Chinese Cymbal",      # 52 E3
    "Ride Bell",           # 53 F3
    "Tambourine",          # 54 F#3
    "Splash Cymbal",       # 55 G3
    "Cowbell",             # 56 G#3
    "Crash Cymbal 2",      # 57 A3
    "Vibraslap / Perc 1",  # 58 A#3
    "Ride Cymbal 2",       # 59 B3
    "Hi Bongo / Perc 2",   # 60 C4
    "Low Bongo / Perc 3",  # 61 C#4
]


def midi_note_name(note: int) -> str:
    return f"{NOTES[note % 12]}{(note // 12) - 1}"


def read_ascii(buf: bytes, offset: int, length: int = 16) -> str:
    raw = buf[offset : offset + length]
    return raw.decode("ascii", errors="replace").rstrip(" \x00")


def write_ascii(buf: bytearray, offset: int, text: str, length: int = 16):
    clean = text.encode("ascii", errors="ignore")[:length]
    padded = clean.ljust(length, b" ")
    buf[offset : offset + length] = padded


def s8(val: int) -> int:
    return val - 256 if val > 127 else val


def u8_from_s8(val: int) -> int:
    val = max(-128, min(127, int(val)))
    return val + 256 if val < 0 else val


class SH4dSVD:
    """Binary parser and editor for Roland SH-4d .SVD (SVD5 / JP-M) files."""

    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as f:
            self.data = bytearray(f.read())

        if self.data[2:6] != b"SVD5":
            raise ValueError(f"Not a valid SVD5 file (magic={self.data[2:6]!r})")

        self.sections = {}
        for i in range(6):
            off = 16 + i * 16
            tag = self.data[off : off + 4].decode("ascii")
            model = self.data[off + 4 : off + 8].decode("ascii")
            sec_off, sec_len = struct.unpack("<II", self.data[off + 8 : off + 16])
            cnt, item_sz, hdr_sz, res = struct.unpack(
                "<IIII", self.data[sec_off : sec_off + 16]
            )
            self.sections[tag] = {
                "model": model,
                "offset": sec_off,
                "length": sec_len,
                "count": cnt,
                "item_size": item_sz,
                "data_offset": sec_off + hdr_sz,
            }

    # --- SYNTH PATCHES (PATc: 256 slots, 2048 bytes each) ---
    OSC_MODELS = {
        16: "16: SH-4d (4-Osc VA)",
        17: "17: SH-3D (3-Osc + LFO2)",
        18: "18: CHORD",
        19: "19: SH-101",
        20: "20: JUNO-106",
        21: "21: CROSS FM",
        22: "22: SYNC",
        23: "23: DRAWING",
        24: "24: WAVETABLE",
        25: "25: RING",
        26: "26: PCM",
        27: "27: STEP / HARMONIC",
    }

    def get_patch_offset(self, idx: int) -> int:
        sec = self.sections["PATc"]
        return sec["data_offset"] + idx * sec["item_size"]

    def get_patch_name(self, idx: int) -> str:
        off = self.get_patch_offset(idx)
        return read_ascii(self.data, off + 16, 16)

    def set_patch_name(self, idx: int, name: str):
        off = self.get_patch_offset(idx)
        write_ascii(self.data, off + 16, name, 16)

    def get_patch_params(self, idx: int) -> dict:
        off = self.get_patch_offset(idx)
        name = read_ascii(self.data, off + 16, 16)
        osc_model = self.data[off + 0x08]
        patch_level = self.data[off + 0x24]
        mfx_type = self.data[off + 0x50]

        slider1 = self.data[off + 0x0D8]
        slider2 = self.data[off + 0x154]
        slider3 = self.data[off + 0x1D0]
        slider4 = self.data[off + 0x24C]

        cutoff = struct.unpack("<H", self.data[off + 0x100 : off + 0x102])[0]
        flt_env_depth = self.data[off + 0x102]
        resonance = struct.unpack("<H", self.data[off + 0x106 : off + 0x108])[0]

        amp_atk = struct.unpack("<H", self.data[off + 0x328 : off + 0x32A])[0]
        amp_dec = struct.unpack("<H", self.data[off + 0x332 : off + 0x334])[0]
        amp_sus = struct.unpack("<H", self.data[off + 0x334 : off + 0x336])[0]
        amp_rel = struct.unpack("<H", self.data[off + 0x33C : off + 0x33E])[0]

        flt_atk = struct.unpack("<H", self.data[off + 0x38C : off + 0x38E])[0]
        flt_dec = struct.unpack("<H", self.data[off + 0x38E : off + 0x390])[0]
        flt_sus = struct.unpack("<H", self.data[off + 0x390 : off + 0x392])[0]
        flt_rel = struct.unpack("<H", self.data[off + 0x392 : off + 0x394])[0]

        lfo_shape = self.data[off + 0x3FC]
        lfo_rate = struct.unpack("<H", self.data[off + 0x400 : off + 0x402])[0]
        lfo_pitch = s8(self.data[off + 0x40B])
        lfo_flt = s8(self.data[off + 0x40C])
        lfo_amp = s8(self.data[off + 0x40D])

        return {
            "name": name,
            "osc_model": osc_model,
            "osc_model_label": self.OSC_MODELS.get(osc_model, f"{osc_model}: Model"),
            "patch_level": patch_level,
            "mfx_type": mfx_type,
            "slider1": slider1,
            "slider2": slider2,
            "slider3": slider3,
            "slider4": slider4,
            "cutoff": cutoff,
            "resonance": resonance,
            "flt_env_depth": flt_env_depth,
            "amp_atk": amp_atk,
            "amp_dec": amp_dec,
            "amp_sus": amp_sus,
            "amp_rel": amp_rel,
            "flt_atk": flt_atk,
            "flt_dec": flt_dec,
            "flt_sus": flt_sus,
            "flt_rel": flt_rel,
            "lfo_shape": lfo_shape,
            "lfo_rate": lfo_rate,
            "lfo_pitch": lfo_pitch,
            "lfo_flt": lfo_flt,
            "lfo_amp": lfo_amp,
        }

    def set_patch_params(self, idx: int, **kw):
        off = self.get_patch_offset(idx)
        if "name" in kw and kw["name"] is not None:
            write_ascii(self.data, off + 16, str(kw["name"]), 16)
        if "osc_model" in kw and kw["osc_model"] is not None:
            self.data[off + 0x08] = max(0, min(127, int(kw["osc_model"])))
        if "patch_level" in kw and kw["patch_level"] is not None:
            self.data[off + 0x24] = max(0, min(127, int(kw["patch_level"])))
        if "mfx_type" in kw and kw["mfx_type"] is not None:
            self.data[off + 0x50] = max(0, min(127, int(kw["mfx_type"])))

        # 4 Oscillator Sliders
        for s_idx, s_off in enumerate([0x0D8, 0x154, 0x1D0, 0x24C], start=1):
            k = f"slider{s_idx}"
            if k in kw and kw[k] is not None:
                self.data[off + s_off] = max(0, min(127, int(kw[k])))

        # Filter parameters written across all 4 Partials (stride 0x7C = 124)
        for p in range(4):
            p_base = off + 0x100 + p * 0x7C
            if "cutoff" in kw and kw["cutoff"] is not None:
                val = max(0, min(1023, int(kw["cutoff"])))
                self.data[p_base : p_base + 2] = struct.pack("<H", val)
            if "flt_env_depth" in kw and kw["flt_env_depth"] is not None:
                self.data[p_base + 2] = max(0, min(255, int(kw["flt_env_depth"])))
            if "resonance" in kw and kw["resonance"] is not None:
                val = max(0, min(1023, int(kw["resonance"])))
                self.data[p_base + 6 : p_base + 8] = struct.pack("<H", val)

        # Amp ADSR written across all 4 Partials (stride 0x18 = 24)
        for p in range(4):
            a_base = off + 0x328 + p * 0x18
            if "amp_atk" in kw and kw["amp_atk"] is not None:
                self.data[a_base : a_base + 2] = struct.pack("<H", max(0, min(1023, int(kw["amp_atk"]))))
            if "amp_dec" in kw and kw["amp_dec"] is not None:
                self.data[a_base + 10 : a_base + 12] = struct.pack("<H", max(0, min(1023, int(kw["amp_dec"]))))
            if "amp_sus" in kw and kw["amp_sus"] is not None:
                self.data[a_base + 12 : a_base + 14] = struct.pack("<H", max(0, min(1023, int(kw["amp_sus"]))))
            if "amp_rel" in kw and kw["amp_rel"] is not None:
                self.data[a_base + 20 : a_base + 22] = struct.pack("<H", max(0, min(1023, int(kw["amp_rel"]))))

        # Filter ADSR written across all 4 Partials (stride 0x10 = 16)
        for p in range(4):
            f_base = off + 0x388 + p * 0x10
            if "flt_atk" in kw and kw["flt_atk"] is not None:
                self.data[f_base + 4 : f_base + 6] = struct.pack("<H", max(0, min(1023, int(kw["flt_atk"]))))
            if "flt_dec" in kw and kw["flt_dec"] is not None:
                self.data[f_base + 6 : f_base + 8] = struct.pack("<H", max(0, min(1023, int(kw["flt_dec"]))))
            if "flt_sus" in kw and kw["flt_sus"] is not None:
                self.data[f_base + 8 : f_base + 10] = struct.pack("<H", max(0, min(1023, int(kw["flt_sus"]))))
            if "flt_rel" in kw and kw["flt_rel"] is not None:
                self.data[f_base + 10 : f_base + 12] = struct.pack("<H", max(0, min(1023, int(kw["flt_rel"]))))

        # LFO written across all 4 Partials (stride 0x68 = 104)
        for p in range(4):
            l_base = off + 0x3F8 + p * 0x68
            if "lfo_shape" in kw and kw["lfo_shape"] is not None:
                self.data[l_base + 4] = max(0, min(15, int(kw["lfo_shape"])))
            if "lfo_rate" in kw and kw["lfo_rate"] is not None:
                self.data[l_base + 8 : l_base + 10] = struct.pack("<H", max(0, min(1023, int(kw["lfo_rate"]))))
            if "lfo_pitch" in kw and kw["lfo_pitch"] is not None:
                self.data[l_base + 0x13] = u8_from_s8(max(-64, min(63, int(kw["lfo_pitch"]))))
            if "lfo_flt" in kw and kw["lfo_flt"] is not None:
                self.data[l_base + 0x14] = u8_from_s8(max(-64, min(63, int(kw["lfo_flt"]))))
            if "lfo_amp" in kw and kw["lfo_amp"] is not None:
                self.data[l_base + 0x15] = u8_from_s8(max(-64, min(63, int(kw["lfo_amp"]))))

    def get_patch_bytes(self, idx: int) -> bytes:
        off = self.get_patch_offset(idx)
        sz = self.sections["PATc"]["item_size"]
        return bytes(self.data[off : off + sz])

    def set_patch_bytes(self, idx: int, raw: bytes):
        sz = self.sections["PATc"]["item_size"]
        if len(raw) != sz:
            raise ValueError(f"Patch size must be {sz} bytes")
        off = self.get_patch_offset(idx)
        self.data[off : off + sz] = raw

    def swap_patches(self, idx1: int, idx2: int):
        b1 = self.get_patch_bytes(idx1)
        b2 = self.get_patch_bytes(idx2)
        self.set_patch_bytes(idx1, b2)
        self.set_patch_bytes(idx2, b1)

    # --- RHYTHM KITS (RHYa: 64x3328 & RHIa: 64x19008) ---
    def get_rhy_offset(self, kit_idx: int) -> int:
        sec = self.sections["RHYa"]
        return sec["data_offset"] + kit_idx * sec["item_size"]

    def get_rhi_offset(self, kit_idx: int) -> int:
        sec = self.sections["RHIa"]
        return sec["data_offset"] + kit_idx * sec["item_size"]

    def get_kit_name(self, kit_idx: int) -> str:
        return read_ascii(self.data, self.get_rhy_offset(kit_idx), 16)

    def set_kit_name(self, kit_idx: int, name: str):
        write_ascii(self.data, self.get_rhy_offset(kit_idx), name, 16)
        write_ascii(self.data, self.get_rhi_offset(kit_idx), name, 16)

    def get_kit_level(self, kit_idx: int) -> int:
        return self.data[self.get_rhy_offset(kit_idx) + 0x14]

    def set_kit_level(self, kit_idx: int, level: int):
        self.data[self.get_rhy_offset(kit_idx) + 0x14] = max(0, min(127, int(level)))

    def swap_kits(self, idx1: int, idx2: int):
        rhy_sz = self.sections["RHYa"]["item_size"]
        rhi_sz = self.sections["RHIa"]["item_size"]
        o1_a, o2_a = self.get_rhy_offset(idx1), self.get_rhy_offset(idx2)
        o1_i, o2_i = self.get_rhi_offset(idx1), self.get_rhi_offset(idx2)

        tmp_a = bytes(self.data[o1_a : o1_a + rhy_sz])
        self.data[o1_a : o1_a + rhy_sz] = self.data[o2_a : o2_a + rhy_sz]
        self.data[o2_a : o2_a + rhy_sz] = tmp_a

        tmp_i = bytes(self.data[o1_i : o1_i + rhi_sz])
        self.data[o1_i : o1_i + rhi_sz] = self.data[o2_i : o2_i + rhi_sz]
        self.data[o2_i : o2_i + rhi_sz] = tmp_i

    def copy_kit(self, src_idx: int, dst_idx: int):
        rhy_sz = self.sections["RHYa"]["item_size"]
        rhi_sz = self.sections["RHIa"]["item_size"]
        o1_a, o2_a = self.get_rhy_offset(src_idx), self.get_rhy_offset(dst_idx)
        o1_i, o2_i = self.get_rhi_offset(src_idx), self.get_rhi_offset(dst_idx)
        self.data[o2_a : o2_a + rhy_sz] = self.data[o1_a : o1_a + rhy_sz]
        self.data[o2_i : o2_i + rhi_sz] = self.data[o1_i : o1_i + rhi_sz]

    def get_drum_key_params(self, kit_idx: int, key_idx: int) -> dict:
        """
        key_idx: 0..25 corresponding to MIDI Notes 36..61 (Slots 15..40 in 88-key table).
        """
        slot = 15 + key_idx
        midi_note = 21 + slot
        rhy_key_off = self.get_rhy_offset(kit_idx) + 0xA0 + slot * 20
        rhi_key_off = self.get_rhi_offset(kit_idx) + slot * 216

        level = self.data[rhy_key_off + 6]
        pan = s8(self.data[rhy_key_off + 8])
        send = self.data[rhy_key_off + 10]

        wave_id = struct.unpack("<H", self.data[rhi_key_off + 0x20 : rhi_key_off + 0x22])[0]
        pitch_semi = s8(self.data[rhi_key_off + 0x27])
        layer1_lvl = self.data[rhi_key_off + 0x2D]
        cutoff = struct.unpack("<H", self.data[rhi_key_off + 0x8E : rhi_key_off + 0x90])[0]
        resonance = self.data[rhi_key_off + 0x98]
        decay = struct.unpack("<H", self.data[rhi_key_off + 0xD0 : rhi_key_off + 0xD2])[0]

        return {
            "key_idx": key_idx,
            "slot": slot,
            "midi_note": midi_note,
            "note_name": midi_note_name(midi_note),
            "label": DRUM_KEY_LABELS[key_idx] if key_idx < len(DRUM_KEY_LABELS) else f"Key {key_idx+1}",
            "level": level,
            "pan": pan,
            "send": send,
            "wave_id": wave_id,
            "pitch_semi": pitch_semi,
            "layer1_lvl": layer1_lvl,
            "cutoff": cutoff,
            "resonance": resonance,
            "decay": decay,
        }

    def set_drum_key_params(
        self,
        kit_idx: int,
        key_idx: int,
        level=None,
        pan=None,
        pitch_semi=None,
        cutoff=None,
        resonance=None,
        decay=None,
        wave_id=None,
    ):
        slot = 15 + key_idx
        rhy_key_off = self.get_rhy_offset(kit_idx) + 0xA0 + slot * 20
        rhi_key_off = self.get_rhi_offset(kit_idx) + slot * 216

        if level is not None:
            self.data[rhy_key_off + 6] = max(0, min(127, int(level)))
        if pan is not None:
            self.data[rhy_key_off + 8] = u8_from_s8(max(-64, min(63, int(pan))))
        if pitch_semi is not None:
            self.data[rhi_key_off + 0x27] = u8_from_s8(max(-48, min(48, int(pitch_semi))))
        if cutoff is not None:
            val = max(0, min(1023, int(cutoff)))
            self.data[rhi_key_off + 0x8E : rhi_key_off + 0x90] = struct.pack("<H", val)
        if resonance is not None:
            self.data[rhi_key_off + 0x98] = max(0, min(127, int(resonance)))
        if decay is not None:
            val = max(0, min(1023, int(decay)))
            self.data[rhi_key_off + 0xD0 : rhi_key_off + 0xD2] = struct.pack("<H", val)
        if wave_id is not None:
            val = max(0, min(65535, int(wave_id)))
            self.data[rhi_key_off + 0x20 : rhi_key_off + 0x22] = struct.pack("<H", val)

    # --- PATTERNS (PRFd: 128 slots, 18988 bytes each) ---
    def get_pattern_offset(self, pat_idx: int) -> int:
        sec = self.sections["PRFd"]
        return sec["data_offset"] + pat_idx * sec["item_size"]

    def resolve_tone_label(self, msb: int, lsb: int, pc: int) -> str:
        if msb == 87 and lsb in (0, 1):
            u_idx = lsb * 128 + pc
            if 0 <= u_idx < 256:
                bank = (u_idx // 16) + 1
                num = (u_idx % 16) + 1
                return f"User U{bank:02d}-{num:02d}: {self.get_patch_name(u_idx)}"
        elif msb == 86 and lsb == 0:
            if 0 <= pc < 64:
                return f"User Kit #{pc+1:02d}: {self.get_kit_name(pc)}"
        elif msb == 86 and lsb == 64:
            return f"Preset Kit #{pc+1:03d}"
        elif msb == 88:
            return f"Preset Tone (LSB {lsb}, PC {pc+1})"
        return f"MSB {msb} / LSB {lsb} / PC {pc+1}"

    def get_pattern_info(self, pat_idx: int) -> dict:
        off = self.get_pattern_offset(pat_idx)
        name = read_ascii(self.data, off, 16)
        level = self.data[off + 0x10]
        tempo_raw = struct.unpack("<H", self.data[off + 0x12 : off + 0x14])[0]
        tempo_bpm = tempo_raw / 100.0

        parts = []
        part_names = ["Synth 1", "Synth 2", "Synth 3", "Synth 4", "Rhythm"]
        for p in range(5):
            p_off = off + 0x3A + p * 88
            msb = self.data[p_off]
            lsb = self.data[p_off + 1]
            pc = self.data[p_off + 2]
            p_lvl = self.data[p_off + 3]
            p_pan = s8(self.data[p_off + 4])
            parts.append(
                {
                    "part_name": part_names[p],
                    "msb": msb,
                    "lsb": lsb,
                    "pc": pc,
                    "level": p_lvl,
                    "pan": p_pan,
                    "resolved": self.resolve_tone_label(msb, lsb, pc),
                }
            )
        return {
            "index": pat_idx,
            "slot": f"{(pat_idx // 16) + 1}-{(pat_idx % 16) + 1:02d}",
            "name": name,
            "level": level,
            "tempo": tempo_bpm,
            "parts": parts,
        }

    def set_pattern_info(self, pat_idx: int, name=None, tempo=None, level=None, parts=None):
        off = self.get_pattern_offset(pat_idx)
        if name is not None:
            write_ascii(self.data, off, name, 16)
        if level is not None:
            self.data[off + 0x10] = max(0, min(127, int(level)))
        if tempo is not None:
            t_val = max(2000, min(30000, int(round(float(tempo) * 100))))
            self.data[off + 0x12 : off + 0x14] = struct.pack("<H", t_val)
        if parts is not None:
            for p_idx, p_data in enumerate(parts[:5]):
                p_off = off + 0x3A + p_idx * 88
                if "msb" in p_data:
                    self.data[p_off] = max(0, min(127, int(p_data["msb"])))
                if "lsb" in p_data:
                    self.data[p_off + 1] = max(0, min(127, int(p_data["lsb"])))
                if "pc" in p_data:
                    self.data[p_off + 2] = max(0, min(127, int(p_data["pc"])))
                if "level" in p_data:
                    self.data[p_off + 3] = max(0, min(127, int(p_data["level"])))
                if "pan" in p_data:
                    self.data[p_off + 4] = u8_from_s8(max(-64, min(63, int(p_data["pan"]))))

    def swap_patterns(self, idx1: int, idx2: int):
        sz = self.sections["PRFd"]["item_size"]
        o1, o2 = self.get_pattern_offset(idx1), self.get_pattern_offset(idx2)
        tmp = bytes(self.data[o1 : o1 + sz])
        self.data[o1 : o1 + sz] = self.data[o2 : o2 + sz]
        self.data[o2 : o2 + sz] = tmp

    def copy_pattern(self, src_idx: int, dst_idx: int):
        sz = self.sections["PRFd"]["item_size"]
        o1, o2 = self.get_pattern_offset(src_idx), self.get_pattern_offset(dst_idx)
        self.data[o2 : o2 + sz] = self.data[o1 : o1 + sz]

    def save(self, out_path: str = None, make_backup: bool = True) -> str:
        target = out_path or self.path
        if make_backup and os.path.exists(target):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bak_path = f"{target}.{ts}.bak"
            shutil.copy2(target, bak_path)
        with open(target, "wb") as f:
            f.write(self.data)
        return target


class SH4dEditorApp(tk.Tk):
    """Desktop GUI for editing Roland SH-4d .SVD files."""

    def __init__(self, initial_path: str = None):
        super().__init__()
        self.title("Roland SH-4d .SVD Editor & Real-Time MIDI Synth Controller (Dawless Project)")
        self.geometry("1220x780")
        self.svd: SH4dSVD = None
        self.midi = WinMMMidiOut()
        self.live_cc_vars = {}
        self._build_ui()

        if initial_path and os.path.exists(initial_path):
            self.load_svd(initial_path)

    def _build_ui(self):
        # Top toolbar
        top = ttk.Frame(self, padding=8)
        top.pack(fill=tk.X)

        ttk.Button(top, text="📂 Open .SVD...", command=self.on_open).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="💾 Save (.bak)", command=self.on_save).pack(side=tk.LEFT, padx=3)
        ttk.Button(top, text="💾 Save As...", command=self.on_save_as).pack(side=tk.LEFT, padx=3)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)

        # Live MIDI Output Port & Channel selector
        ttk.Label(top, text="⚡ Live MIDI Out:").pack(side=tk.LEFT, padx=(2, 2))
        self.var_midi_port = tk.StringVar()
        ports = self.midi.list_ports()
        port_labels = [f"{idx}: {name}" for idx, name in ports]
        self.cb_midi_port = ttk.Combobox(top, textvariable=self.var_midi_port, values=port_labels, width=24, state="readonly")
        self.cb_midi_port.pack(side=tk.LEFT, padx=2)
        self.cb_midi_port.bind("<<ComboboxSelected>>", self.on_select_midi_port)
        if port_labels:
            # Prefer SH-4d or UMC1820 if present
            best = 0
            for idx, lbl in enumerate(port_labels):
                if any(k in lbl.upper() for k in ("SH-4D", "UMC", "MIDI", "MOTU")):
                    best = idx
                    break
            self.cb_midi_port.current(best)
            self.midi.open(ports[best][0])

        ttk.Label(top, text="Target Ch:").pack(side=tk.LEFT, padx=(6, 2))
        self.var_midi_ch = tk.StringVar(value="8: Synth Part 1 (M08)")
        ch_options = [
            "8: Synth Part 1 (M08)",
            "9: Synth Part 2 (M09)",
            "11: Synth Part 3 (M11)",
            "12: Synth Part 4 (M12)",
            "13: Rhythm Part (M13)",
            "1: Default Part 1 (Ch 1)",
            "2: Default Part 2 (Ch 2)",
            "3: Default Part 3 (Ch 3)",
            "4: Default Part 4 (Ch 4)",
            "10: Default Rhythm (Ch 10)",
        ]
        self.cb_midi_ch = ttk.Combobox(top, textvariable=self.var_midi_ch, values=ch_options, width=21, state="readonly")
        self.cb_midi_ch.pack(side=tk.LEFT, padx=2)
        ttk.Button(top, text="🎹 Test Note", command=self.on_test_note).pack(side=tk.LEFT, padx=4)

        self.lbl_status = ttk.Label(top, text="No file loaded", font=("Segoe UI", 8, "bold"))
        self.lbl_status.pack(side=tk.LEFT, padx=8)

        # Notebook tabs
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._build_live_synth_tab()
        self._build_patches_tab()
        self._build_patterns_tab()
        self._build_rhythm_tab()

    # ---------------- TAB 0: LIVE REAL-TIME MIDI SYNTH CONTROLLER ----------------
    def _build_live_synth_tab(self):
        tab = ttk.Frame(self.nb, padding=10)
        self.nb.add(tab, text="🎛️ 1. Live Real-Time Synth Control (MIDI CC)")

        top_bar = ttk.LabelFrame(tab, text="Real-Time MIDI Program Change & Quick Actions (Sent to Target Ch above)", padding=8)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(top_bar, text="Select User Synth Patch (1..256):").pack(side=tk.LEFT, padx=4)
        self.var_live_pc_slot = tk.StringVar(value="1")
        ttk.Spinbox(top_bar, from_=1, to=256, textvariable=self.var_live_pc_slot, width=6, command=self.on_live_send_user_pc).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(top_bar, text="⚡ Send Program Change (Load User Patch on SH-4d)", command=self.on_live_send_user_pc).pack(
            side=tk.LEFT, padx=6
        )
        ttk.Button(top_bar, text="📤 Send All Sliders Below Now", command=self.on_live_send_all_sliders).pack(side=tk.LEFT, padx=6)
        ttk.Button(top_bar, text="🎹 Play Test Chord", command=self.on_test_note).pack(side=tk.LEFT, padx=6)

        grid_frm = ttk.Frame(tab)
        grid_frm.pack(fill=tk.BOTH, expand=True)

        # 4 Columns of real-time MIDI CC sliders for Roland SH-4d Synth Parts
        groups = [
            (
                "🌊 Oscillator & Mixer CCs",
                [
                    ("OSC Slider 1 (CC#85)", 85, 127),
                    ("OSC Slider 2 (CC#86)", 86, 100),
                    ("OSC Slider 3 (CC#87)", 87, 0),
                    ("OSC Slider 4 (CC#88)", 88, 0),
                    ("OSC Pitch (CC#28)", 28, 64),
                    ("OSC Timbre (CC#77)", 77, 64),
                    ("Part Level (CC#7)", 7, 100),
                    ("Part Pan (CC#10)", 10, 64),
                ],
            ),
            (
                "🎛️ Filter & Filter ADSR CCs",
                [
                    ("Filter Cutoff (CC#74)", 74, 100),
                    ("Filter Resonance (CC#71)", 71, 20),
                    ("Filter Drive (CC#90)", 90, 0),
                    ("Filter Env Depth (CC#81)", 81, 64),
                    ("HPF Cutoff (CC#79)", 79, 0),
                    ("Filter Attack (CC#82)", 82, 10),
                    ("Filter Decay (CC#83)", 83, 64),
                    ("Filter Sustain (CC#29)", 29, 30),
                    ("Filter Release (CC#31)", 31, 40),
                ],
            ),
            (
                "⏳ Amp ADSR & LFO CCs",
                [
                    ("Amp Attack (CC#73)", 73, 0),
                    ("Amp Decay (CC#75)", 75, 80),
                    ("Amp Sustain (CC#30)", 30, 100),
                    ("Amp Release (CC#72)", 72, 30),
                    ("LFO Rate (CC#16)", 16, 64),
                    ("LFO Pitch Depth (CC#18)", 18, 64),
                    ("LFO Filter Depth (CC#19)", 19, 64),
                    ("LFO Amp Depth (CC#20)", 20, 64),
                ],
            ),
            (
                "✨ Effects & Expression CCs",
                [
                    ("Modulation Wheel (CC#1)", 1, 0),
                    ("Portamento Time (CC#5)", 5, 0),
                    ("Expression (CC#11)", 11, 127),
                    ("Reverb Send (CC#91)", 91, 40),
                    ("Chorus Send (CC#93)", 93, 0),
                    ("Delay Send (CC#94)", 94, 20),
                ],
            ),
        ]

        for col_idx, (g_title, items) in enumerate(groups):
            lf = ttk.LabelFrame(grid_frm, text=g_title, padding=8)
            lf.grid(row=0, column=col_idx, sticky="nsew", padx=4, pady=2)
            grid_frm.columnconfigure(col_idx, weight=1)

            for r_idx, (label_txt, cc_num, default_val) in enumerate(items):
                row_f = ttk.Frame(lf)
                row_f.pack(fill=tk.X, pady=3)

                var = tk.IntVar(value=default_val)
                self.live_cc_vars[cc_num] = var

                lbl_top = ttk.Frame(row_f)
                lbl_top.pack(fill=tk.X)
                ttk.Label(lbl_top, text=label_txt, font=("Segoe UI", 8)).pack(side=tk.LEFT)
                val_lbl = ttk.Label(lbl_top, textvariable=var, width=4, anchor=tk.E, font=("Segoe UI", 8, "bold"))
                val_lbl.pack(side=tk.RIGHT)

                def _make_cb(cc=cc_num, v=var):
                    def _on_slide(val_str):
                        ival = int(round(float(val_str)))
                        v.set(ival)
                        self.midi.send_cc(self.get_active_midi_channel(), cc, ival)
                    return _on_slide

                sc = ttk.Scale(row_f, from_=0, to=127, orient=tk.HORIZONTAL, command=_make_cb())
                sc.set(default_val)
                sc.pack(fill=tk.X)

    # ---------------- TAB 1: PATTERNS ----------------
    def _build_patterns_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text="🎵 1. User Patterns (128 Slots - PRFd)")

        left = ttk.Frame(tab)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        cols = ("slot", "name", "tempo", "s1", "s2", "s3", "s4", "rhy")
        self.tree_pat = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        headers = {
            "slot": ("Slot", 55),
            "name": ("Pattern Name", 130),
            "tempo": ("BPM", 65),
            "s1": ("Part 1 (Ch 8)", 145),
            "s2": ("Part 2 (Ch 9)", 145),
            "s3": ("Part 3 (Ch 11)", 145),
            "s4": ("Part 4 (Ch 12)", 145),
            "rhy": ("Rhythm (Ch 13)", 145),
        }
        for c, (txt, w) in headers.items():
            self.tree_pat.heading(c, text=txt)
            self.tree_pat.column(c, width=w, anchor=tk.W)

        sb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree_pat.yview)
        self.tree_pat.configure(yscrollcommand=sb.set)
        self.tree_pat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_pat.bind("<<TreeviewSelect>>", self.on_select_pattern)

        # Right panel: Pattern Editor
        right = ttk.LabelFrame(tab, text="Selected Pattern Editor", padding=10)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        ttk.Label(right, text="Pattern Name (Max 16 Chars):").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.var_pat_name = tk.StringVar()
        ttk.Entry(right, textvariable=self.var_pat_name, width=22).grid(row=0, column=1, pady=3)

        ttk.Label(right, text="Tempo (BPM):").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.var_pat_tempo = tk.StringVar()
        ttk.Entry(right, textvariable=self.var_pat_tempo, width=12).grid(row=1, column=1, sticky=tk.W, pady=3)

        ttk.Label(right, text="Pattern Level (0-127):").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.var_pat_level = tk.StringVar()
        ttk.Entry(right, textvariable=self.var_pat_level, width=12).grid(row=2, column=1, sticky=tk.W, pady=3)

        ttk.Separator(right, orient=tk.HORIZONTAL).grid(row=3, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(right, text="Part Sound & Mixer (MSB / LSB / PC / Lvl / Pan):", font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, columnspan=2, sticky=tk.W, pady=4
        )

        self.part_vars = []
        part_labels = ["Synth 1 (M08)", "Synth 2 (M09)", "Synth 3 (M11)", "Synth 4 (M12)", "Rhythm (M13)"]
        for p in range(5):
            frm = ttk.Frame(right)
            frm.grid(row=5 + p, column=0, columnspan=2, sticky=tk.W, pady=2)
            ttk.Label(frm, text=f"{part_labels[p]}:", width=13).pack(side=tk.LEFT)
            v_msb = tk.StringVar()
            v_lsb = tk.StringVar()
            v_pc = tk.StringVar()
            v_lvl = tk.StringVar()
            v_pan = tk.StringVar()
            for lbl, var, w in [("MSB", v_msb, 4), ("LSB", v_lsb, 4), ("PC", v_pc, 4), ("Lvl", v_lvl, 4), ("Pan", v_pan, 4)]:
                ttk.Label(frm, text=lbl).pack(side=tk.LEFT, padx=(3, 1))
                ttk.Entry(frm, textvariable=var, width=w).pack(side=tk.LEFT)
            self.part_vars.append((v_msb, v_lsb, v_pc, v_lvl, v_pan))

        ttk.Button(right, text="✅ Apply Pattern Changes", command=self.on_apply_pattern).grid(
            row=11, column=0, columnspan=2, sticky="ew", pady=10
        )

        ttk.Separator(right, orient=tk.HORIZONTAL).grid(row=12, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(right, text="Target Pattern Slot (1..128):").grid(row=13, column=0, sticky=tk.W, pady=3)
        self.var_pat_target = tk.StringVar(value="1")
        ttk.Entry(right, textvariable=self.var_pat_target, width=8).grid(row=13, column=1, sticky=tk.W, pady=3)
        ttk.Button(right, text="🔀 Swap with Target Slot", command=self.on_swap_pattern).grid(
            row=14, column=0, columnspan=2, sticky="ew", pady=2
        )
        ttk.Button(right, text="📋 Copy to Target Slot", command=self.on_copy_pattern).grid(
            row=15, column=0, columnspan=2, sticky="ew", pady=2
        )

    # ---------------- TAB 2: SYNTH PATCHES ----------------
    def _build_patches_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text="🎹 2. User Synth Patches & Sound Editor (256 Slots - PATc)")

        left = ttk.Frame(tab)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        cols = ("idx", "slot", "name", "osc_model", "lvl", "cutoff", "reso", "sliders")
        self.tree_patch = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        p_headers = {
            "idx": ("#", 40),
            "slot": ("Bank-Slot (PC)", 125),
            "name": ("Synth Patch Name", 155),
            "osc_model": ("OSC Model", 130),
            "lvl": ("Lvl", 45),
            "cutoff": ("Cutoff", 60),
            "reso": ("Reso", 55),
            "sliders": ("OSC Sliders 1-4", 120),
        }
        for c, (txt, w) in p_headers.items():
            self.tree_patch.heading(c, text=txt)
            self.tree_patch.column(c, width=w, anchor=tk.W if c in ("slot", "name", "osc_model") else tk.CENTER)

        sb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree_patch.yview)
        self.tree_patch.configure(yscrollcommand=sb.set)
        self.tree_patch.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_patch.bind("<<TreeviewSelect>>", self.on_select_patch)

        right = ttk.LabelFrame(tab, text="Synth Patch Sound & Parameter Editor", padding=10)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        self.var_patch_name = tk.StringVar()
        self.var_p_osc = tk.StringVar()
        self.var_p_lvl = tk.StringVar()
        self.var_p_mfx = tk.StringVar()
        self.var_p_s1 = tk.StringVar()
        self.var_p_s2 = tk.StringVar()
        self.var_p_s3 = tk.StringVar()
        self.var_p_s4 = tk.StringVar()
        self.var_p_cutoff = tk.StringVar()
        self.var_p_reso = tk.StringVar()
        self.var_p_fenv = tk.StringVar()
        self.var_p_fatk = tk.StringVar()
        self.var_p_fdec = tk.StringVar()
        self.var_p_fsus = tk.StringVar()
        self.var_p_frel = tk.StringVar()
        self.var_p_aatk = tk.StringVar()
        self.var_p_adec = tk.StringVar()
        self.var_p_asus = tk.StringVar()
        self.var_p_arel = tk.StringVar()
        self.var_p_lshape = tk.StringVar()
        self.var_p_lrate = tk.StringVar()
        self.var_p_lpitch = tk.StringVar()
        self.var_p_lflt = tk.StringVar()
        self.var_p_lamp = tk.StringVar()

        # General & Oscillator Model
        g_frm = ttk.Frame(right)
        g_frm.pack(fill=tk.X, pady=2)
        ttk.Label(g_frm, text="Patch Name:", width=14).grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(g_frm, textvariable=self.var_patch_name, width=20).grid(row=0, column=1, columnspan=3, sticky=tk.W, pady=2)

        ttk.Label(g_frm, text="OSC Model ID:", width=14).grid(row=1, column=0, sticky=tk.W, pady=2)
        self.cb_osc_model = ttk.Combobox(
            g_frm,
            textvariable=self.var_p_osc,
            values=[f"{k}: {v.split(': ')[1]}" for k, v in SH4dSVD.OSC_MODELS.items()],
            width=18,
        )
        self.cb_osc_model.grid(row=1, column=1, columnspan=3, sticky=tk.W, pady=2)

        ttk.Label(g_frm, text="Patch Lvl (0-127):").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Entry(g_frm, textvariable=self.var_p_lvl, width=6).grid(row=2, column=1, sticky=tk.W, pady=2)
        ttk.Label(g_frm, text="MFX Type (0-93):").grid(row=2, column=2, sticky=tk.W, padx=(8, 2), pady=2)
        ttk.Entry(g_frm, textvariable=self.var_p_mfx, width=6).grid(row=2, column=3, sticky=tk.W, pady=2)

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # OSC Sliders 1-4
        ttk.Label(right, text="OSC Mixer Sliders 1–4 (0..127):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        s_frm = ttk.Frame(right)
        s_frm.pack(fill=tk.X, pady=2)
        for i, var in enumerate([self.var_p_s1, self.var_p_s2, self.var_p_s3, self.var_p_s4], start=1):
            ttk.Label(s_frm, text=f"S{i}:").pack(side=tk.LEFT, padx=(4 if i > 1 else 0, 2))
            ttk.Entry(s_frm, textvariable=var, width=5).pack(side=tk.LEFT)

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # Filter & Filter ADSR
        ttk.Label(right, text="Filter & Filter ADSR (0..1023):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        f_frm = ttk.Frame(right)
        f_frm.pack(fill=tk.X, pady=2)
        ttk.Label(f_frm, text="Cutoff (0-1023):").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(f_frm, textvariable=self.var_p_cutoff, width=6).grid(row=0, column=1, sticky=tk.W, padx=2)
        ttk.Label(f_frm, text="Reso (0-1023):").grid(row=0, column=2, sticky=tk.W, padx=(6, 0), pady=2)
        ttk.Entry(f_frm, textvariable=self.var_p_reso, width=6).grid(row=0, column=3, sticky=tk.W, padx=2)
        ttk.Label(f_frm, text="Env Depth:").grid(row=1, column=0, sticky=tk.W, pady=2)
        ttk.Entry(f_frm, textvariable=self.var_p_fenv, width=6).grid(row=1, column=1, sticky=tk.W, padx=2)

        fadsr = ttk.Frame(right)
        fadsr.pack(fill=tk.X, pady=2)
        for lbl, var in [("F-Atk", self.var_p_fatk), ("F-Dec", self.var_p_fdec), ("F-Sus", self.var_p_fsus), ("F-Rel", self.var_p_frel)]:
            ttk.Label(fadsr, text=f"{lbl}:").pack(side=tk.LEFT, padx=(3, 1))
            ttk.Entry(fadsr, textvariable=var, width=5).pack(side=tk.LEFT)

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # Amp ADSR
        ttk.Label(right, text="Amp Envelope ADSR (0..1023):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        aadsr = ttk.Frame(right)
        aadsr.pack(fill=tk.X, pady=2)
        for lbl, var in [("A-Atk", self.var_p_aatk), ("A-Dec", self.var_p_adec), ("A-Sus", self.var_p_asus), ("A-Rel", self.var_p_arel)]:
            ttk.Label(aadsr, text=f"{lbl}:").pack(side=tk.LEFT, padx=(3, 1))
            ttk.Entry(aadsr, textvariable=var, width=5).pack(side=tk.LEFT)

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # LFO Section
        ttk.Label(right, text="LFO Rate & Modulation Depths:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        lfo_frm = ttk.Frame(right)
        lfo_frm.pack(fill=tk.X, pady=2)
        ttk.Label(lfo_frm, text="Shape (0-5):").grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Entry(lfo_frm, textvariable=self.var_p_lshape, width=5).grid(row=0, column=1, sticky=tk.W, padx=2)
        ttk.Label(lfo_frm, text="Rate (0-1023):").grid(row=0, column=2, sticky=tk.W, padx=(6, 0), pady=2)
        ttk.Entry(lfo_frm, textvariable=self.var_p_lrate, width=6).grid(row=0, column=3, sticky=tk.W, padx=2)

        lfo_d = ttk.Frame(right)
        lfo_d.pack(fill=tk.X, pady=2)
        for lbl, var in [("Pitch Dep", self.var_p_lpitch), ("Filter Dep", self.var_p_lflt), ("Amp Dep", self.var_p_lamp)]:
            ttk.Label(lfo_d, text=f"{lbl}:").pack(side=tk.LEFT, padx=(3, 1))
            ttk.Entry(lfo_d, textvariable=var, width=5).pack(side=tk.LEFT)

        ttk.Button(right, text="✅ Apply All Sound Parameters to .SVD Patch", command=self.on_rename_patch).pack(fill=tk.X, pady=4)
        ttk.Button(right, text="⚡ Load This Patch on SH-4d Live (MIDI PC)", command=self.on_live_load_selected_patch).pack(fill=tk.X, pady=2)
        ttk.Button(right, text="⚡ Push Patch Parameters to SH-4d Live (MIDI CC)", command=self.on_live_push_patch_ccs).pack(fill=tk.X, pady=2)

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        act_frm = ttk.Frame(right)
        act_frm.pack(fill=tk.X)
        ttk.Label(act_frm, text="Target Slot (1..256):").pack(side=tk.LEFT)
        self.var_patch_target = tk.StringVar(value="1")
        ttk.Entry(act_frm, textvariable=self.var_patch_target, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Button(act_frm, text="🔀 Swap", command=self.on_swap_patch).pack(side=tk.LEFT, padx=2)
        ttk.Button(act_frm, text="📋 Copy", command=self.on_copy_patch).pack(side=tk.LEFT, padx=2)

        io_frm = ttk.Frame(right)
        io_frm.pack(fill=tk.X, pady=4)
        ttk.Button(io_frm, text="📤 Export (.sh4d_patch)", command=self.on_export_patch).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        ttk.Button(io_frm, text="📥 Import (.sh4d_patch)", command=self.on_import_patch).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

    # ---------------- TAB 3: RHYTHM KITS & DRUM PITCH EDITOR ----------------
    def _build_rhythm_tab(self):
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text="🥁 3. Rhythm Kits & Drum Pitch/Filter Editor (RHYa + RHIa)")

        # Left: 64 Rhythm Kits
        kit_frame = ttk.LabelFrame(tab, text="64 User Rhythm Kits (MSB=86, LSB=0)", padding=6)
        kit_frame.pack(side=tk.LEFT, fill=tk.Y)

        self.tree_kit = ttk.Treeview(kit_frame, columns=("num", "name", "lvl"), show="headings", selectmode="browse")
        self.tree_kit.heading("num", text="Kit #")
        self.tree_kit.column("num", width=55)
        self.tree_kit.heading("name", text="Kit Name")
        self.tree_kit.column("name", width=135)
        self.tree_kit.heading("lvl", text="Lvl")
        self.tree_kit.column("lvl", width=45)
        self.tree_kit.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.tree_kit.bind("<<TreeviewSelect>>", self.on_select_kit)

        k_ctrl = ttk.Frame(kit_frame, padding=(0, 6, 0, 0))
        k_ctrl.pack(fill=tk.X)
        ttk.Label(k_ctrl, text="Kit Name:").grid(row=0, column=0, sticky=tk.W)
        self.var_kit_name = tk.StringVar()
        ttk.Entry(k_ctrl, textvariable=self.var_kit_name, width=16).grid(row=0, column=1, pady=2)
        ttk.Label(k_ctrl, text="Kit Level:").grid(row=1, column=0, sticky=tk.W)
        self.var_kit_lvl = tk.StringVar()
        ttk.Entry(k_ctrl, textvariable=self.var_kit_lvl, width=8).grid(row=1, column=1, sticky=tk.W, pady=2)
        ttk.Button(k_ctrl, text="✏️ Update Kit Name / Level", command=self.on_update_kit_meta).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=3
        )

        # Middle: 26 Drum Instruments inside selected Kit
        mid_frame = ttk.LabelFrame(tab, text="26 Drum Instruments in Selected Kit (MIDI Note 36 C2 .. 61 C#4)", padding=6)
        mid_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8)

        d_cols = ("key", "note", "label", "pitch", "level", "pan", "cutoff", "reso", "decay", "wave")
        self.tree_drum = ttk.Treeview(mid_frame, columns=d_cols, show="headings", selectmode="browse")
        d_headers = {
            "key": ("#", 35),
            "note": ("Note", 65),
            "label": ("Instrument", 145),
            "pitch": ("Pitch (Semitones)", 105),
            "level": ("Level", 55),
            "pan": ("Pan", 55),
            "cutoff": ("Cutoff (0-1023)", 95),
            "reso": ("Reso", 55),
            "decay": ("Decay (0-1023)", 95),
            "wave": ("Wave ID", 65),
        }
        for c, (txt, w) in d_headers.items():
            self.tree_drum.heading(c, text=txt)
            self.tree_drum.column(c, width=w, anchor=tk.CENTER if c != "label" else tk.W)

        sb_d = ttk.Scrollbar(mid_frame, orient=tk.VERTICAL, command=self.tree_drum.yview)
        self.tree_drum.configure(yscrollcommand=sb_d.set)
        self.tree_drum.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_d.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_drum.bind("<<TreeviewSelect>>", self.on_select_drum_key)

        # Right: Selected Drum Instrument Parameter Editor
        d_edit = ttk.LabelFrame(tab, text="Selected Drum Sound (Pitch / Filter / Mixer)", padding=10)
        d_edit.pack(side=tk.RIGHT, fill=tk.Y)

        self.lbl_drum_title = ttk.Label(d_edit, text="Select a drum instrument", font=("Segoe UI", 9, "bold"))
        self.lbl_drum_title.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8))

        self.var_d_pitch = tk.StringVar()
        self.var_d_level = tk.StringVar()
        self.var_d_pan = tk.StringVar()
        self.var_d_cutoff = tk.StringVar()
        self.var_d_reso = tk.StringVar()
        self.var_d_decay = tk.StringVar()
        self.var_d_wave = tk.StringVar()

        fields = [
            ("🎯 Pitch (-48 .. +48 Semitones):", self.var_d_pitch),
            ("🔊 Level (0 .. 127):", self.var_d_level),
            ("↔️ Pan (-64 L .. +63 R):", self.var_d_pan),
            ("🎛️ Filter Cutoff (0 .. 1023):", self.var_d_cutoff),
            ("⚡ Filter Resonance (0 .. 127):", self.var_d_reso),
            ("⏳ Amp Decay (0 .. 1023):", self.var_d_decay),
            ("🌊 Wave ID (Layer 1):", self.var_d_wave),
        ]
        for idx, (lbl, var) in enumerate(fields, start=1):
            ttk.Label(d_edit, text=lbl).grid(row=idx, column=0, sticky=tk.W, pady=3)
            ttk.Entry(d_edit, textvariable=var, width=10).grid(row=idx, column=1, sticky=tk.W, pady=3, padx=4)

        ttk.Button(d_edit, text="✅ Apply to This Drum Sound", command=self.on_apply_drum_key).grid(
            row=9, column=0, columnspan=2, sticky="ew", pady=8
        )

        ttk.Separator(d_edit, orient=tk.HORIZONTAL).grid(row=10, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(d_edit, text="Batch Kit Pitch Shift (All 26 Drums):", font=("Segoe UI", 9, "bold")).grid(
            row=11, column=0, columnspan=2, sticky=tk.W, pady=2
        )
        self.var_batch_pitch = tk.StringVar(value="0")
        ttk.Label(d_edit, text="Semitone Offset (e.g. +3 / -2):").grid(row=12, column=0, sticky=tk.W)
        ttk.Entry(d_edit, textvariable=self.var_batch_pitch, width=8).grid(row=12, column=1, sticky=tk.W, pady=2)
        ttk.Button(d_edit, text="🚀 Shift Pitch of Entire Kit", command=self.on_batch_pitch_kit).grid(
            row=13, column=0, columnspan=2, sticky="ew", pady=6
        )

        ttk.Separator(d_edit, orient=tk.HORIZONTAL).grid(row=14, column=0, columnspan=2, sticky="ew", pady=8)
        ttk.Label(d_edit, text="Copy Kit to Target Slot (1..64):").grid(row=15, column=0, sticky=tk.W)
        self.var_kit_target = tk.StringVar(value="7")
        ttk.Entry(d_edit, textvariable=self.var_kit_target, width=8).grid(row=15, column=1, sticky=tk.W, pady=2)
        ttk.Button(d_edit, text="📋 Copy Kit to Target Slot", command=self.on_copy_kit).grid(
            row=16, column=0, columnspan=2, sticky="ew", pady=4
        )

    # ---------------- DATA LOADING & REFRESH ----------------
    def load_svd(self, path: str):
        try:
            self.svd = SH4dSVD(path)
            self.lbl_status.config(text=f"Loaded: {path} ({len(self.svd.data):,} bytes | SVD5 JP-M)")
            self.refresh_all()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read SVD file:\n{e}")

    def refresh_all(self):
        if not self.svd:
            return
        self.refresh_patterns()
        self.refresh_patches()
        self.refresh_kits()

    def refresh_patterns(self):
        sel = self.tree_pat.selection()
        self.tree_pat.delete(*self.tree_pat.get_children())
        for i in range(128):
            info = self.svd.get_pattern_info(i)
            p = info["parts"]
            self.tree_pat.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    info["slot"],
                    info["name"],
                    f"{info['tempo']:.1f}",
                    p[0]["resolved"],
                    p[1]["resolved"],
                    p[2]["resolved"],
                    p[3]["resolved"],
                    p[4]["resolved"],
                ),
            )
        if sel:
            self.tree_pat.selection_set(sel)

    def refresh_patches(self):
        sel = self.tree_patch.selection()
        self.tree_patch.delete(*self.tree_patch.get_children())
        for i in range(256):
            pr = self.svd.get_patch_params(i)
            bank = (i // 16) + 1
            num = (i % 16) + 1
            lsb = i // 128
            pc = i % 128
            sliders_str = f"{pr['slider1']}/{pr['slider2']}/{pr['slider3']}/{pr['slider4']}"
            self.tree_patch.insert(
                "",
                tk.END,
                iid=str(i),
                values=(
                    i + 1,
                    f"U{bank:02d}-{num:02d} (LSB:{lsb} PC:{pc})",
                    pr["name"],
                    pr["osc_model_label"],
                    pr["patch_level"],
                    pr["cutoff"],
                    pr["resonance"],
                    sliders_str,
                ),
            )
        if sel:
            self.tree_patch.selection_set(sel)
        else:
            self.tree_patch.selection_set("0")
            self.on_select_patch(None)

    def refresh_kits(self):
        sel = self.tree_kit.selection()
        self.tree_kit.delete(*self.tree_kit.get_children())
        for i in range(64):
            name = self.svd.get_kit_name(i)
            lvl = self.svd.get_kit_level(i)
            self.tree_kit.insert("", tk.END, iid=str(i), values=(f"#{i+1:02d}", name, lvl))
        if sel:
            self.tree_kit.selection_set(sel)
        else:
            self.tree_kit.selection_set("0")
            self.on_select_kit(None)

    def refresh_drums_for_kit(self, kit_idx: int):
        sel = self.tree_drum.selection()
        self.tree_drum.delete(*self.tree_drum.get_children())
        for k in range(26):
            d = self.svd.get_drum_key_params(kit_idx, k)
            pitch_str = f"{d['pitch_semi']:+d}" if d["pitch_semi"] != 0 else "0"
            self.tree_drum.insert(
                "",
                tk.END,
                iid=str(k),
                values=(
                    k + 1,
                    f"{d['midi_note']} ({d['note_name']})",
                    d["label"],
                    pitch_str,
                    d["level"],
                    d["pan"],
                    d["cutoff"],
                    d["resonance"],
                    d["decay"],
                    d["wave_id"],
                ),
            )
        if sel:
            self.tree_drum.selection_set(sel)

    # ---------------- EVENT HANDLERS ----------------
    def get_active_midi_channel(self) -> int:
        raw = self.var_midi_ch.get().split(":")[0].strip()
        return int(raw) if raw.isdigit() else 8

    def on_select_midi_port(self, _event=None):
        raw = self.var_midi_port.get().split(":")[0].strip()
        if raw.isdigit():
            self.midi.open(int(raw))

    def on_test_note(self):
        ch = self.get_active_midi_channel()
        for n in (48, 55, 60):
            self.midi.send_note_on(ch, n, 100)
        self.after(450, lambda: [self.midi.send_note_off(ch, n) for n in (48, 55, 60)])

    def on_live_send_user_pc(self):
        ch = self.get_active_midi_channel()
        slot_1_256 = max(1, min(256, int(self.var_live_pc_slot.get()))) - 1
        msb = 86 if ch in (10, 13) else 87
        lsb = slot_1_256 // 128
        pc = slot_1_256 % 128
        self.midi.send_pc(ch, msb, lsb, pc)

    def on_live_send_all_sliders(self):
        ch = self.get_active_midi_channel()
        for cc, var in self.live_cc_vars.items():
            self.midi.send_cc(ch, cc, var.get())

    def on_live_load_selected_patch(self):
        sel = self.tree_patch.selection()
        if not sel:
            return
        idx = int(sel[0])
        ch = self.get_active_midi_channel()
        self.midi.send_pc(ch, 87, idx // 128, idx % 128)

    def on_live_push_patch_ccs(self):
        ch = self.get_active_midi_channel()
        # Scale 0..1023 SVD values to 0..127 MIDI CC values and transmit live
        cc_map = {
            7: int(self.var_p_lvl.get()),
            85: int(self.var_p_s1.get()),
            86: int(self.var_p_s2.get()),
            87: int(self.var_p_s3.get()),
            88: int(self.var_p_s4.get()),
            74: int(round(int(self.var_p_cutoff.get()) * 127 / 1023)),
            71: int(round(int(self.var_p_reso.get()) * 127 / 1023)),
            82: int(round(int(self.var_p_fatk.get()) * 127 / 1023)),
            83: int(round(int(self.var_p_fdec.get()) * 127 / 1023)),
            29: int(round(int(self.var_p_fsus.get()) * 127 / 1023)),
            31: int(round(int(self.var_p_frel.get()) * 127 / 1023)),
            73: int(round(int(self.var_p_aatk.get()) * 127 / 1023)),
            75: int(round(int(self.var_p_adec.get()) * 127 / 1023)),
            30: int(round(int(self.var_p_asus.get()) * 127 / 1023)),
            72: int(round(int(self.var_p_arel.get()) * 127 / 1023)),
            16: int(round(int(self.var_p_lrate.get()) * 127 / 1023)),
        }
        for cc, val in cc_map.items():
            cval = max(0, min(127, val))
            self.midi.send_cc(ch, cc, cval)
            if cc in self.live_cc_vars:
                self.live_cc_vars[cc].set(cval)

    def on_open(self):
        p = filedialog.askopenfilename(
            title="Select SH-4d .SVD File",
            filetypes=[("Roland SVD Backup", "*.SVD"), ("All Files", "*.*")],
        )
        if p:
            self.load_svd(p)

    def on_save(self):
        if not self.svd:
            return
        saved = self.svd.save(make_backup=True)
        messagebox.showinfo("Saved", f"File saved successfully (with .bak backup created):\n{saved}")

    def on_save_as(self):
        if not self.svd:
            return
        p = filedialog.asksaveasfilename(
            title="Save As (.SVD)",
            defaultextension=".SVD",
            initialfile="SH4d.SVD",
            filetypes=[("Roland SVD Backup", "*.SVD")],
        )
        if p:
            saved = self.svd.save(out_path=p, make_backup=False)
            messagebox.showinfo("Saved", f"New SVD file saved:\n{saved}")

    def on_select_pattern(self, _event):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        info = self.svd.get_pattern_info(idx)
        self.var_pat_name.set(info["name"])
        self.var_pat_tempo.set(f"{info['tempo']:.2f}")
        self.var_pat_level.set(str(info["level"]))
        for p_idx, p_data in enumerate(info["parts"]):
            v_msb, v_lsb, v_pc, v_lvl, v_pan = self.part_vars[p_idx]
            v_msb.set(str(p_data["msb"]))
            v_lsb.set(str(p_data["lsb"]))
            v_pc.set(str(p_data["pc"]))
            v_lvl.set(str(p_data["level"]))
            v_pan.set(str(p_data["pan"]))

    def on_apply_pattern(self):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        parts = []
        for v_msb, v_lsb, v_pc, v_lvl, v_pan in self.part_vars:
            parts.append(
                {
                    "msb": int(v_msb.get()),
                    "lsb": int(v_lsb.get()),
                    "pc": int(v_pc.get()),
                    "level": int(v_lvl.get()),
                    "pan": int(v_pan.get()),
                }
            )
        self.svd.set_pattern_info(
            idx,
            name=self.var_pat_name.get(),
            tempo=float(self.var_pat_tempo.get()),
            level=int(self.var_pat_level.get()),
            parts=parts,
        )
        self.refresh_patterns()

    def on_swap_pattern(self):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        idx1 = int(sel[0])
        idx2 = max(0, min(127, int(self.var_pat_target.get()) - 1))
        self.svd.swap_patterns(idx1, idx2)
        self.refresh_patterns()

    def on_copy_pattern(self):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        idx1 = int(sel[0])
        idx2 = max(0, min(127, int(self.var_pat_target.get()) - 1))
        self.svd.copy_pattern(idx1, idx2)
        self.refresh_patterns()

    def on_select_patch(self, _event):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        pr = self.svd.get_patch_params(idx)
        self.var_patch_name.set(pr["name"])
        self.var_p_osc.set(pr["osc_model_label"])
        self.var_p_lvl.set(str(pr["patch_level"]))
        self.var_p_mfx.set(str(pr["mfx_type"]))
        self.var_p_s1.set(str(pr["slider1"]))
        self.var_p_s2.set(str(pr["slider2"]))
        self.var_p_s3.set(str(pr["slider3"]))
        self.var_p_s4.set(str(pr["slider4"]))
        self.var_p_cutoff.set(str(pr["cutoff"]))
        self.var_p_reso.set(str(pr["resonance"]))
        self.var_p_fenv.set(str(pr["flt_env_depth"]))
        self.var_p_fatk.set(str(pr["flt_atk"]))
        self.var_p_fdec.set(str(pr["flt_dec"]))
        self.var_p_fsus.set(str(pr["flt_sus"]))
        self.var_p_frel.set(str(pr["flt_rel"]))
        self.var_p_aatk.set(str(pr["amp_atk"]))
        self.var_p_adec.set(str(pr["amp_dec"]))
        self.var_p_asus.set(str(pr["amp_sus"]))
        self.var_p_arel.set(str(pr["amp_rel"]))
        self.var_p_lshape.set(str(pr["lfo_shape"]))
        self.var_p_lrate.set(str(pr["lfo_rate"]))
        self.var_p_lpitch.set(str(pr["lfo_pitch"]))
        self.var_p_lflt.set(str(pr["lfo_flt"]))
        self.var_p_lamp.set(str(pr["lfo_amp"]))

    def on_rename_patch(self):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        osc_str = self.var_p_osc.get().split(":")[0].strip()
        osc_id = int(osc_str) if osc_str.isdigit() else None
        self.svd.set_patch_params(
            idx,
            name=self.var_patch_name.get(),
            osc_model=osc_id,
            patch_level=int(self.var_p_lvl.get()),
            mfx_type=int(self.var_p_mfx.get()),
            slider1=int(self.var_p_s1.get()),
            slider2=int(self.var_p_s2.get()),
            slider3=int(self.var_p_s3.get()),
            slider4=int(self.var_p_s4.get()),
            cutoff=int(self.var_p_cutoff.get()),
            resonance=int(self.var_p_reso.get()),
            flt_env_depth=int(self.var_p_fenv.get()),
            flt_atk=int(self.var_p_fatk.get()),
            flt_dec=int(self.var_p_fdec.get()),
            flt_sus=int(self.var_p_fsus.get()),
            flt_rel=int(self.var_p_frel.get()),
            amp_atk=int(self.var_p_aatk.get()),
            amp_dec=int(self.var_p_adec.get()),
            amp_sus=int(self.var_p_asus.get()),
            amp_rel=int(self.var_p_arel.get()),
            lfo_shape=int(self.var_p_lshape.get()),
            lfo_rate=int(self.var_p_lrate.get()),
            lfo_pitch=int(self.var_p_lpitch.get()),
            lfo_flt=int(self.var_p_lflt.get()),
            lfo_amp=int(self.var_p_lamp.get()),
        )
        self.refresh_patches()
        self.refresh_patterns()

    def on_swap_patch(self):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx1 = int(sel[0])
        idx2 = max(0, min(255, int(self.var_patch_target.get()) - 1))
        self.svd.swap_patches(idx1, idx2)
        self.refresh_patches()
        self.refresh_patterns()

    def on_copy_patch(self):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx1 = int(sel[0])
        idx2 = max(0, min(255, int(self.var_patch_target.get()) - 1))
        self.svd.set_patch_bytes(idx2, self.svd.get_patch_bytes(idx1))
        self.refresh_patches()
        self.refresh_patterns()

    def on_export_patch(self):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        name = self.svd.get_patch_name(idx).replace(" ", "_")
        p = filedialog.asksaveasfilename(
            title="Export Synth Patch",
            defaultextension=".sh4d_patch",
            initialfile=f"U{idx+1:03d}_{name}.sh4d_patch",
            filetypes=[("SH-4d Patch", "*.sh4d_patch")],
        )
        if p:
            with open(p, "wb") as f:
                f.write(self.svd.get_patch_bytes(idx))
            messagebox.showinfo("Exported", f"Patch exported to:\n{p}")

    def on_import_patch(self):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        p = filedialog.askopenfilename(
            title="Import Synth Patch",
            filetypes=[("SH-4d Patch", "*.sh4d_patch"), ("All Files", "*.*")],
        )
        if p:
            raw = open(p, "rb").read()
            self.svd.set_patch_bytes(idx, raw)
            self.refresh_patches()
            self.refresh_patterns()

    def on_select_kit(self, _event):
        sel = self.tree_kit.selection()
        if not sel or not self.svd:
            return
        kit_idx = int(sel[0])
        self.var_kit_name.set(self.svd.get_kit_name(kit_idx))
        self.var_kit_lvl.set(str(self.svd.get_kit_level(kit_idx)))
        self.refresh_drums_for_kit(kit_idx)

    def on_update_kit_meta(self):
        sel = self.tree_kit.selection()
        if not sel or not self.svd:
            return
        kit_idx = int(sel[0])
        self.svd.set_kit_name(kit_idx, self.var_kit_name.get())
        self.svd.set_kit_level(kit_idx, int(self.var_kit_lvl.get()))
        self.refresh_kits()
        self.refresh_patterns()

    def on_select_drum_key(self, _event):
        kit_sel = self.tree_kit.selection()
        key_sel = self.tree_drum.selection()
        if not kit_sel or not key_sel or not self.svd:
            return
        kit_idx = int(kit_sel[0])
        key_idx = int(key_sel[0])
        d = self.svd.get_drum_key_params(kit_idx, key_idx)
        self.lbl_drum_title.config(
            text=f"Kit #{kit_idx+1:02d} | Key {key_idx+1:02d}: {d['label']} ({d['note_name']})"
        )
        self.var_d_pitch.set(str(d["pitch_semi"]))
        self.var_d_level.set(str(d["level"]))
        self.var_d_pan.set(str(d["pan"]))
        self.var_d_cutoff.set(str(d["cutoff"]))
        self.var_d_reso.set(str(d["resonance"]))
        self.var_d_decay.set(str(d["decay"]))
        self.var_d_wave.set(str(d["wave_id"]))

    def on_apply_drum_key(self):
        kit_sel = self.tree_kit.selection()
        key_sel = self.tree_drum.selection()
        if not kit_sel or not key_sel or not self.svd:
            return
        kit_idx = int(kit_sel[0])
        key_idx = int(key_sel[0])
        self.svd.set_drum_key_params(
            kit_idx,
            key_idx,
            level=int(self.var_d_level.get()),
            pan=int(self.var_d_pan.get()),
            pitch_semi=int(self.var_d_pitch.get()),
            cutoff=int(self.var_d_cutoff.get()),
            resonance=int(self.var_d_reso.get()),
            decay=int(self.var_d_decay.get()),
            wave_id=int(self.var_d_wave.get()),
        )
        self.refresh_drums_for_kit(kit_idx)

    def on_batch_pitch_kit(self):
        kit_sel = self.tree_kit.selection()
        if not kit_sel or not self.svd:
            return
        kit_idx = int(kit_sel[0])
        delta = int(self.var_batch_pitch.get())
        for k in range(26):
            cur = self.svd.get_drum_key_params(kit_idx, k)["pitch_semi"]
            self.svd.set_drum_key_params(kit_idx, k, pitch_semi=cur + delta)
        self.refresh_drums_for_kit(kit_idx)
        self.on_select_drum_key(None)

    def on_copy_kit(self):
        kit_sel = self.tree_kit.selection()
        if not kit_sel or not self.svd:
            return
        src = int(kit_sel[0])
        dst = max(0, min(63, int(self.var_kit_target.get()) - 1))
        self.svd.copy_kit(src, dst)
        self.refresh_kits()


def print_summary(svd: SH4dSVD):
    print(f"=== Roland SH-4d SVD Summary: {svd.path} ===")
    print("\n[Active User Patterns (First 24 Slots)]")
    for i in range(24):
        info = svd.get_pattern_info(i)
        p_summary = " | ".join(f"P{idx+1}:{pt['resolved']}" for idx, pt in enumerate(info["parts"]))
        print(f"  {info['slot']} | {info['name']:16} | {info['tempo']:6.2f} BPM | {p_summary}")

    print("\n[Active User Rhythm Kits (First 6 Slots)]")
    for k in range(6):
        name = svd.get_kit_name(k)
        bd = svd.get_drum_key_params(k, 0)
        sd = svd.get_drum_key_params(k, 2)
        print(
            f"  Kit #{k+1:02d}: {name:16} (Lvl {svd.get_kit_level(k):3d}) | "
            f"BD1 Pitch={bd['pitch_semi']:+d}, Cutoff={bd['cutoff']}, Decay={bd['decay']} | "
            f"SD1 Pitch={sd['pitch_semi']:+d}, Cutoff={sd['cutoff']}"
        )


def main():
    parser = argparse.ArgumentParser(description="Roland SH-4d .SVD Backup Editor & Librarian")
    parser.add_argument("file", nargs="?", default=DEFAULT_SVD_PATH, help="Path to SH4d.SVD file")
    parser.add_argument("--summary", action="store_true", help="Print detailed summary to console and exit")
    args = parser.parse_args()

    if args.summary:
        svd = SH4dSVD(args.file)
        print_summary(svd)
        return

    app = SH4dEditorApp(args.file if os.path.exists(args.file) else None)
    app.mainloop()


if __name__ == "__main__":
    main()
