#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Roland SH-4d .SVD Backup / Patch / Pattern / Rhythm Kit Editor & Librarian
Supports Roland SVD5 (JP-M) binary database files (e.g. SH4d.SVD).

DISCLAIMER OF WARRANTY & LIMITATION OF LIABILITY (USE AT YOUR OWN RISK):
This software is an independent, unofficial reverse-engineered tool and is NOT
affiliated with, endorsed, or supported by Roland Corporation.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
CLAIM, DAMAGES, OR OTHER LIABILITY—INCLUDING ANY HARDWARE DAMAGE, FIRMWARE
MALFUNCTION, REPAIR COSTS, OR LOSS OF DATA—ARISING FROM THE USE OF THIS SOFTWARE.
Always keep a separate, unmodified backup copy of your original SH4d.SVD file.
"""

import os
import sys
import math
import random
import shutil
import struct
import ctypes
import argparse
from datetime import datetime
import tkinter as tk
import tkinter.font as tkfont
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

    OSC_MODEL_SPECS = {
        16: {
            "title": "SH-4d Engine — 4 Independent VA Oscillators (OSC 1–4)",
            "active_oscs": 4,
            "osc_names": ["OSC 1:", "OSC 2:", "OSC 3:", "OSC 4:"],
            "sliders": ["S1 (OSC1 Lvl):", "S2 (OSC2 Lvl):", "S3 (OSC3 Lvl):", "S4 (OSC4 Lvl):"],
            "info": "4 full oscillators active. Sliders 1–4 control OSC 1–4 mixer levels.",
        },
        17: {
            "title": "SH-3D Engine — 3 VA Oscillators (OSC 1–3) + 2nd Fast LFO",
            "active_oscs": 3,
            "osc_names": ["OSC 1:", "OSC 2:", "OSC 3:"],
            "sliders": ["S1 (OSC1 Lvl):", "S2 (OSC2 Lvl):", "S3 (OSC3 Lvl):", "S4 (2nd LFO):"],
            "info": "3 oscillators active (OSC 4 is replaced by the 2nd Fast LFO on Slider 4).",
        },
        18: {
            "title": "CHORD Engine — 1 Master Chord Poly-Oscillator",
            "active_oscs": 1,
            "osc_names": ["Chord OSC:"],
            "sliders": ["S1 (Note 1):", "S2 (Note 2):", "S3 (Note 3):", "S4 (Note 4):"],
            "info": "Single Chord Engine. Sliders 1–4 balance the 4 chord notes/inversions.",
        },
        19: {
            "title": "SH-101 Engine — 1 Classic Monophonic Oscillator + Sub + Noise",
            "active_oscs": 1,
            "osc_names": ["SH-101 OSC:"],
            "sliders": ["S1 (Saw Lvl):", "S2 (Sqr Lvl):", "S3 (Sub Lvl):", "S4 (Noise Lvl):"],
            "info": "Single SH-101 oscillator. Sliders 1–4 mix Saw, Square/PW, Sub-Osc & Noise.",
        },
        20: {
            "title": "JUNO-106 Engine — 1 Classic DCO + Sub-Osc + Noise",
            "active_oscs": 1,
            "osc_names": ["JUNO DCO:"],
            "sliders": ["S1 (Saw Lvl):", "S2 (Pulse Lvl):", "S3 (Sub Lvl):", "S4 (Noise Lvl):"],
            "info": "Single JUNO-106 DCO. Sliders 1–4 mix Saw, Pulse/PWM, Sub-Osc & Noise.",
        },
        21: {
            "title": "CROSS FM Engine — 2-Operator FM (Carrier + Modulator)",
            "active_oscs": 2,
            "osc_names": ["OP1 (Carrier):", "OP2 (Modulator):"],
            "sliders": ["S1 (Mod Ratio):", "S2 (FM Depth):", "S3 (Feedback):", "S4 (Harmonics):"],
            "info": "2 FM Operators active (OSC 3–4 unused). Sliders 1–4 control FM Ratio, Depth & Feedback.",
        },
        22: {
            "title": "SYNC Engine — 2 Hard-Synced Oscillators (Master + Slave)",
            "active_oscs": 2,
            "osc_names": ["OSC 1 (Master):", "OSC 2 (Slave):"],
            "sliders": ["S1 (Sync Pitch):", "S2 (Env Dep):", "S3 (OSC1 Lvl):", "S4 (Sync Lvl):"],
            "info": "2 Oscillators active (Master OSC 1 & Synced Slave OSC 2; OSC 3–4 unused).",
        },
        23: {
            "title": "DRAWING Engine — 1 Custom 32-Step Drawn Wave Oscillator",
            "active_oscs": 1,
            "osc_names": ["Drawn Wave:"],
            "sliders": ["S1 (Wave Morph):", "S2 (Wave Edge):", "S3 (Sub Lvl):", "S4 (Noise Lvl):"],
            "info": "1 Custom 32-Step Waveform Oscillator (0x674..0x693) + Wave Edge (0x698).",
        },
        24: {
            "title": "WAVETABLE Engine — Wavetable Oscillator + Sub Oscillator",
            "active_oscs": 2,
            "osc_names": ["Wavetable OSC:", "Sub / Mod OSC:"],
            "sliders": ["S1 (Wave Pos):", "S2 (Harmonics):", "S3 (Sub Lvl):", "S4 (Noise Lvl):"],
            "info": "Wavetable Oscillator + Sub Oscillator (OSC 3–4 unused). Slider 1 scans Wavetable position.",
        },
        25: {
            "title": "RING Engine — 2 Ring-Modulated Oscillators (OSC 1 × OSC 2)",
            "active_oscs": 2,
            "osc_names": ["OSC 1 (Ring A):", "OSC 2 (Ring B):"],
            "sliders": ["S1 (X-Fade):", "S2 (OSC1 Lvl):", "S3 (OSC2 Lvl):", "S4 (Ring Mod):"],
            "info": "2 Oscillators active in Ring Modulation (OSC 3–4 unused).",
        },
        26: {
            "title": "PCM Engine — 4 Sample-Based PCM Partials (PCM 1–4)",
            "active_oscs": 4,
            "osc_names": ["PCM 1:", "PCM 2:", "PCM 3:", "PCM 4:"],
            "sliders": ["S1 (PCM1 Lvl):", "S2 (PCM2 Lvl):", "S3 (PCM3 Lvl):", "S4 (PCM4 Lvl):"],
            "info": "4 PCM Sample Partials active. Sliders 1–4 control PCM 1–4 mixer levels.",
        },
        27: {
            "title": "STEP Engine — 2 Oscillators + 16-Step Sequenced LFO",
            "active_oscs": 2,
            "osc_names": ["Step OSC 1:", "Step OSC 2:"],
            "sliders": ["S1 (OSC1 Lvl):", "S2 (OSC2 Lvl):", "S3 (Step Mod):", "S4 (Sub/Noise):"],
            "info": "2 Oscillators driven by the 16-Step Sequencer (0x410..0x42F; OSC 3–4 unused).",
        },
    }

    OSC_WAVEFORMS = {
        0: "0: OFF",
        1: "1: SAW",
        2: "2: SQR",
        3: "3: TRI",
        4: "4: SINE",
        5: "5: RAMP",
        6: "6: JUNO",
        7: "7: TRI2",
        8: "8: TRI3",
        9: "9: SINE2",
        10: "10: SuperSAW",
        11: "11: NOISE",
    }

    # Hardware-verified MFX blocks (mfx_type -> 16 int16 parameters with valid 127 Output Level)
    HARDWARE_MFX_PRESETS = {
        0: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        4: [3, 3, 0, 18, 18, 127, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        12: [50, 0, 15, 15, 127, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        17: [80, 45, 0, 15, 15, 50, 127, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        26: [20, 0, 14, 18, 6, 0, 30, 20, 50, 127, 0, 0, 0, 0, 0, 0],
        33: [0, 32, 60, 0, 5, 4, 35, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        34: [32, 64, 2, 3, 17, 15, 34, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        73: [1, 0, 20, 18, 127, 85, 122, 0, 0, 1, 100, 0, 0, 0, 0, 0],
        75: [0, 500, 12, 74, 17, 127, 0, 127, 127, 15, 15, 10, 127, 0, 0, 0],
        84: [0, 110, 0, 200, 3, 200, 0, 4, 4000, 0, 4, 1000, 0, 5, -240, 0],
        87: [0, 0, 50, 127, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        92: [-200, 12, -154, 12, 300, 700, 32, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    }

    MATRIX_SOURCES = {
        0: "0: LFO",
        52: "52: Pitch Env",
        94: "94: Pitch Bend",
        95: "95: Aftertouch",
        96: "96: Mod Wheel (CC#1)",
        98: "98: Velocity / Key",
        100: "100: Filter Env",
        102: "102: OFF",
    }

    MATRIX_DESTS = {
        0: "0: OFF",
        3: "3: Pitch",
        4: "4: OSC 2 Pitch",
        6: "6: Filter Cutoff",
        7: "7: Filter Reso",
        9: "9: Filter Env Depth",
        12: "12: LFO Rate",
        14: "14: LFO Pitch Depth",
        15: "15: LFO Filter Depth",
        16: "16: LFO Amp Depth",
        17: "17: OSC 1 PW",
        18: "18: OSC 2 PW",
        19: "19: OSC 3 PW",
        24: "24: OSC 4 PW",
        25: "25: Wave Position",
        28: "28: Pan",
        33: "33: Level",
        35: "35: OSC 1 Level",
        38: "38: OSC 2 Level",
        45: "45: Filter Drive",
        50: "50: Sub Level",
        54: "54: MFX Control",
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
        mfx_sw = self.data[off + 0x51]
        mfx_cho = self.data[off + 0x52]
        mfx_rev = self.data[off + 0x53]
        mfx_params = [
            struct.unpack("<h", self.data[off + 0x60 + i * 2 : off + 0x62 + i * 2])[0]
            for i in range(16)
        ]

        # Voicing / Tone settings ([SHIFT]+[6] TONE)
        category = self.data[off + 0x20]
        coarse_tune = s8(self.data[off + 0x29])
        analog_feel = self.data[off + 0x2D]
        mono_poly = self.data[off + 0x2E]
        legato_sw = self.data[off + 0x31]
        porta_sw = self.data[off + 0x32]
        porta_time = struct.unpack("<H", self.data[off + 0x36 : off + 0x38])[0]
        bend_up = self.data[off + 0x38]
        bend_down = self.data[off + 0x39]

        slider1 = self.data[off + 0x0D8]
        slider2 = self.data[off + 0x154]
        slider3 = self.data[off + 0x1D0]
        slider4 = self.data[off + 0x24C]

        cutoff = struct.unpack("<H", self.data[off + 0x100 : off + 0x102])[0]
        flt_env_depth = self.data[off + 0x102]
        resonance = struct.unpack("<H", self.data[off + 0x106 : off + 0x108])[0]

        amp_atk = struct.unpack("<H", self.data[off + 0x32E : off + 0x330])[0]
        amp_dec = struct.unpack("<H", self.data[off + 0x332 : off + 0x334])[0]
        amp_sus = struct.unpack("<H", self.data[off + 0x334 : off + 0x336])[0]
        amp_rel = struct.unpack("<H", self.data[off + 0x33C : off + 0x33E])[0]

        flt_atk = struct.unpack("<H", self.data[off + 0x38A : off + 0x38C])[0]
        flt_dec = struct.unpack("<H", self.data[off + 0x38E : off + 0x390])[0]
        flt_sus = struct.unpack("<H", self.data[off + 0x390 : off + 0x392])[0]
        flt_rel = struct.unpack("<H", self.data[off + 0x396 : off + 0x398])[0]

        lfo_shape = self.data[off + 0x3FC]
        lfo_rate = struct.unpack("<H", self.data[off + 0x400 : off + 0x402])[0]
        lfo_pitch = s8(self.data[off + 0x40B])
        lfo_flt = s8(self.data[off + 0x40C])
        lfo_amp = s8(self.data[off + 0x40D])

        # 4 Oscillators (0x720 + osc * 44)
        oscs = []
        for o in range(4):
            o_base = off + 0x720 + o * 44
            oscs.append(
                {
                    "wave": self.data[o_base + 0],
                    "coarse": s8(self.data[o_base + 1]),
                    "fine": s8(self.data[o_base + 2]),
                    "pw": self.data[o_base + 3],
                    "pwm": self.data[o_base + 4],
                    "fat": self.data[o_base + 5],
                    "pan": self.data[o_base + 6],
                }
            )

        # 4 Modulation Matrix Slots (0x6F0 + slot * 12)
        matrix = []
        for sl in range(4):
            m_base = off + 0x6F0 + sl * 12
            matrix.append(
                {
                    "src": self.data[m_base + 0],
                    "dst1": self.data[m_base + 1],
                    "dep1": s8(self.data[m_base + 2]),
                    "dst2": self.data[m_base + 3],
                    "dep2": s8(self.data[m_base + 4]),
                    "dst3": self.data[m_base + 5],
                    "dep3": s8(self.data[m_base + 6]),
                    "dst4": self.data[m_base + 7],
                    "dep4": s8(self.data[m_base + 8]),
                }
            )

        return {
            "name": name,
            "osc_model": osc_model,
            "osc_model_label": self.OSC_MODELS.get(osc_model, f"{osc_model}: Model"),
            "patch_level": patch_level,
            "mfx_type": mfx_type,
            "mfx_sw": mfx_sw,
            "mfx_cho": mfx_cho,
            "mfx_rev": mfx_rev,
            "mfx_params": mfx_params,
            "category": category,
            "coarse_tune": coarse_tune,
            "analog_feel": analog_feel,
            "mono_poly": mono_poly,
            "legato_sw": legato_sw,
            "porta_sw": porta_sw,
            "porta_time": porta_time,
            "bend_up": bend_up,
            "bend_down": bend_down,
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
            "oscs": oscs,
            "matrix": matrix,
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
            new_mfx = max(0, min(127, int(kw["mfx_type"])))
            old_mfx = self.data[off + 0x50]
            self.data[off + 0x50] = new_mfx
            if new_mfx != old_mfx and ("mfx_params" not in kw or kw["mfx_params"] is None):
                if new_mfx in self.HARDWARE_MFX_PRESETS:
                    for i, val in enumerate(self.HARDWARE_MFX_PRESETS[new_mfx]):
                        self.data[off + 0x60 + i * 2 : off + 0x62 + i * 2] = struct.pack("<h", int(val))
        if "mfx_sw" in kw and kw["mfx_sw"] is not None:
            self.data[off + 0x51] = max(0, min(1, int(kw["mfx_sw"])))
        # CRITICAL: 0x52 and 0x53 are MFX Dry/Output Level (127 in all hardware patches; <127 attenuates/mutes output!)
        self.data[off + 0x52] = 127
        self.data[off + 0x53] = 127
        if "mfx_params" in kw and kw["mfx_params"] is not None:
            for i, val in enumerate(kw["mfx_params"][:16]):
                self.data[off + 0x60 + i * 2 : off + 0x62 + i * 2] = struct.pack(
                    "<h", max(-32768, min(32767, int(val)))
                )

        # Voicing / Tone settings ([SHIFT]+[6] TONE)
        if "category" in kw and kw["category"] is not None:
            self.data[off + 0x20] = max(0, min(127, int(kw["category"])))
        if "coarse_tune" in kw and kw["coarse_tune"] is not None:
            self.data[off + 0x29] = u8_from_s8(max(-48, min(48, int(kw["coarse_tune"]))))
        if "analog_feel" in kw and kw["analog_feel"] is not None:
            self.data[off + 0x2D] = max(0, min(127, int(kw["analog_feel"])))
        if "mono_poly" in kw and kw["mono_poly"] is not None:
            self.data[off + 0x2E] = max(0, min(1, int(kw["mono_poly"])))
        if "legato_sw" in kw and kw["legato_sw"] is not None:
            self.data[off + 0x31] = max(0, min(1, int(kw["legato_sw"])))
        if "porta_sw" in kw and kw["porta_sw"] is not None:
            self.data[off + 0x32] = max(0, min(1, int(kw["porta_sw"])))
        if "porta_time" in kw and kw["porta_time"] is not None:
            self.data[off + 0x36 : off + 0x38] = struct.pack(
                "<H", max(0, min(1023, int(kw["porta_time"])))
            )
        if "bend_up" in kw and kw["bend_up"] is not None:
            self.data[off + 0x38] = max(0, min(48, int(kw["bend_up"])))
        if "bend_down" in kw and kw["bend_down"] is not None:
            self.data[off + 0x39] = max(0, min(48, int(kw["bend_down"])))

        # 4 Oscillator Sliders
        for s_idx, s_off in enumerate([0x0D8, 0x154, 0x1D0, 0x24C], start=1):
            k = f"slider{s_idx}"
            if k in kw and kw[k] is not None:
                val = max(0, min(127, int(kw[k])))
                self.data[off + s_off] = val
                self.data[off + 0x670 + s_idx] = val

        # 4 Oscillators deep parameters (0x720 + o * 44 & partial DSP mirror at 0x0DA + o*0x7C and 0x5E0 + o*0x24)
        wave_to_dsp = {
            0: (1, 0),
            1: (1, 0),
            2: (1, 1),
            3: (1, 2),
            4: (1, 3),
            5: (1, 4),
            6: (1, 5),
            7: (1, 6),
            8: (1, 0),
            9: (1, 1),
            10: (3, 8),
            11: (4, 8),
        }
        cur_model = self.data[off + 0x08]
        if "oscs" in kw and kw["oscs"] is not None:
            for o, od in enumerate(kw["oscs"][:4]):
                o_base = off + 0x720 + o * 44
                p_coarse_off = off + 0x0DA + o * 0x7C
                dsp_base = off + 0x5E0 + o * 0x24
                if "wave" in od:
                    w_val = max(0, min(255, int(od["wave"])))
                    self.data[o_base + 0] = w_val
                    if cur_model == 16 and w_val in wave_to_dsp:
                        eng_t, sub_w = wave_to_dsp[w_val]
                        self.data[dsp_base + 0] = eng_t
                        self.data[dsp_base + 1] = sub_w
                if "coarse" in od:
                    c_u8 = u8_from_s8(max(-48, min(48, int(od["coarse"]))))
                    self.data[o_base + 1] = c_u8
                    self.data[p_coarse_off] = c_u8
                if "fine" in od:
                    f_u8 = u8_from_s8(max(-50, min(50, int(od["fine"]))))
                    self.data[o_base + 2] = f_u8
                    self.data[p_coarse_off + 1] = f_u8
                if "pw" in od:
                    pw_val = max(0, min(127, int(od["pw"])))
                    self.data[o_base + 3] = pw_val
                    if cur_model == 16:
                        self.data[dsp_base + 4] = max(0, min(127, 64 + pw_val))
                if "pwm" in od:
                    self.data[o_base + 4] = max(0, min(127, int(od["pwm"])))
                if "fat" in od:
                    fat_val = max(0, min(127, int(od["fat"])))
                    self.data[o_base + 5] = fat_val
                    if cur_model == 16:
                        self.data[dsp_base + 6] = max(0, min(127, 64 + fat_val))
                        self.data[dsp_base + 13] = max(0, min(127, 64 + fat_val))
                if "pan" in od:
                    self.data[o_base + 6] = max(0, min(127, int(od["pan"])))

        # 4 Modulation Matrix Slots (0x6F0 + sl * 12 & partial mirror at 0x114 + p*0x7C + sl*12)
        if "matrix" in kw and kw["matrix"] is not None:
            for sl, md in enumerate(kw["matrix"][:4]):
                m_base = off + 0x6F0 + sl * 12
                if "src" in md:
                    self.data[m_base + 0] = max(0, min(255, int(md["src"])))
                for d_i in range(1, 5):
                    dk = f"dst{d_i}"
                    pk = f"dep{d_i}"
                    if dk in md:
                        self.data[m_base + (d_i - 1) * 2 + 1] = max(0, min(255, int(md[dk])))
                    if pk in md:
                        dep_u8 = u8_from_s8(max(-63, min(63, int(md[pk]))))
                        self.data[m_base + (d_i - 1) * 2 + 2] = dep_u8
                        for p in range(4):
                            pm_base = off + 0x114 + p * 0x7C + sl * 12
                            self.data[pm_base + (d_i - 1) * 2 + 2] = dep_u8

        # Filter parameters written across all 4 Partials (stride 0x7C = 124) AND Master Tone Macro (0x6C0, 0x6BC, 0x6BE)
        for p in range(4):
            p_base = off + 0x100 + p * 0x7C
            if "cutoff" in kw and kw["cutoff"] is not None:
                val = max(0, min(1023, int(kw["cutoff"])))
                self.data[p_base : p_base + 2] = struct.pack("<H", val)
                self.data[off + 0x6BC : off + 0x6BE] = struct.pack("<H", val)
            if "flt_env_depth" in kw and kw["flt_env_depth"] is not None:
                fenv_val = u8_from_s8(max(-120, min(120, int(kw["flt_env_depth"]))))
                self.data[p_base + 2] = fenv_val
                self.data[off + 0x6C0] = fenv_val
            if "resonance" in kw and kw["resonance"] is not None:
                val = max(0, min(1023, int(kw["resonance"])))
                self.data[p_base + 6 : p_base + 8] = struct.pack("<H", val)
                self.data[off + 0x6BE : off + 0x6C0] = struct.pack("<H", val)

        # Amp ADSR written across all 4 Partials (stride 0x18 = 24) AND Master Tone Macro (0x6C2..0x6CB)
        # CRITICAL: a_base + 1 (0x329, 0x341, 0x359, 0x371) is Partial Amp Output Enable (MUST BE 1)!
        # Amp Attack is at a_base + 6 (0x32E), Decay at +10 (0x332), Sustain at +12 (0x334), Release at +20 (0x33C).
        for p in range(4):
            a_base = off + 0x328 + p * 0x18
            self.data[a_base + 1] = 1
            self.data[a_base + 16 : a_base + 18] = struct.pack("<H", 1023)
            self.data[a_base + 18 : a_base + 20] = struct.pack("<H", 1023)
            if "amp_atk" in kw and kw["amp_atk"] is not None:
                v_aa = max(0, min(1023, int(kw["amp_atk"])))
                self.data[a_base + 6 : a_base + 8] = struct.pack("<H", v_aa)
                m_aa = int(round((v_aa / 1023.0) ** 0.5 * 1023)) if v_aa > 0 else 0
                self.data[off + 0x6C2 : off + 0x6C4] = struct.pack("<H", m_aa)
            if "amp_dec" in kw and kw["amp_dec"] is not None:
                v_ad = max(0, min(1023, int(kw["amp_dec"])))
                self.data[a_base + 10 : a_base + 12] = struct.pack("<H", v_ad)
                m_ad = int(round((v_ad / 1023.0) ** 0.5 * 1023)) if v_ad > 0 else 0
                self.data[off + 0x6C4 : off + 0x6C6] = struct.pack("<H", m_ad)
                env_curve_byte = max(1, min(63, v_ad)) if v_ad < 120 else 0
                self.data[a_base + 0] = env_curve_byte
                self.data[off + 0x6CB] = env_curve_byte
            if "amp_sus" in kw and kw["amp_sus"] is not None:
                v_as = max(0, min(1023, int(kw["amp_sus"])))
                self.data[a_base + 12 : a_base + 14] = struct.pack("<H", v_as)
                m_as = int(round((v_as / 1023.0) ** 0.5 * 1023)) if v_as > 0 else 0
                self.data[off + 0x6C8 : off + 0x6CA] = struct.pack("<H", m_as)
            if "amp_rel" in kw and kw["amp_rel"] is not None:
                v_ar = max(0, min(1023, int(kw["amp_rel"])))
                self.data[a_base + 20 : a_base + 22] = struct.pack("<H", v_ar)
                m_ar = int(round((v_ar / 1023.0) ** 0.5 * 1023)) if v_ar > 0 else 0
                self.data[off + 0x6C6 : off + 0x6C8] = struct.pack("<H", m_ar)

        # Filter ADSR written across all 4 Partials (stride 0x10 = 16) AND Master Tone Macro (0x6A6..0x6AD)
        # CRITICAL: f_base + 2 (0x38A) is Filter Attack, f_base + 4 (0x38C) is Filter Slope/Enable (30),
        # f_base + 6 (0x38E) is Filter Decay, f_base + 8 (0x390) is Filter Sustain,
        # f_base + 10..13 (0x392..0x395) are Filter Peak Levels (1023), f_base + 14 (0x396) is Filter Release.
        for p in range(4):
            f_base = off + 0x388 + p * 0x10
            if struct.unpack("<H", self.data[f_base + 4 : f_base + 6])[0] == 0 and self.data[off + 0x08] not in (22, 23):
                self.data[f_base + 4 : f_base + 6] = struct.pack("<H", 30)
            self.data[f_base + 10 : f_base + 12] = struct.pack("<H", 1023)
            self.data[f_base + 12 : f_base + 14] = struct.pack("<H", 1023)
            if "flt_atk" in kw and kw["flt_atk"] is not None:
                v_fa = max(0, min(1023, int(kw["flt_atk"])))
                self.data[f_base + 2 : f_base + 4] = struct.pack("<H", v_fa)
                m_fa = int(round((v_fa / 1023.0) ** 0.5 * 1023)) if v_fa > 0 else 0
                self.data[off + 0x6A6 : off + 0x6A8] = struct.pack("<H", m_fa)
            if "flt_dec" in kw and kw["flt_dec"] is not None:
                v_fd = max(0, min(1023, int(kw["flt_dec"])))
                self.data[f_base + 6 : f_base + 8] = struct.pack("<H", v_fd)
                m_fd = int(round((v_fd / 1023.0) ** 0.5 * 1023)) if v_fd > 0 else 0
                self.data[off + 0x6A8 : off + 0x6AA] = struct.pack("<H", m_fd)
            if "flt_sus" in kw and kw["flt_sus"] is not None:
                v_fs = max(0, min(1023, int(kw["flt_sus"])))
                self.data[f_base + 8 : f_base + 10] = struct.pack("<H", v_fs)
                m_fs = int(round((v_fs / 1023.0) ** 0.5 * 1023)) if v_fs > 0 else 0
                self.data[off + 0x6AC : off + 0x6AE] = struct.pack("<H", m_fs)
            if "flt_rel" in kw and kw["flt_rel"] is not None:
                v_fr = max(0, min(1023, int(kw["flt_rel"])))
                self.data[f_base + 14 : f_base + 16] = struct.pack("<H", v_fr)
                m_fr = int(round((v_fr / 1023.0) ** 0.5 * 1023)) if v_fr > 0 else 0
                self.data[off + 0x6AA : off + 0x6AC] = struct.pack("<H", m_fr)

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

    def get_patch_searchable_list(self, idx: int, override_model: int = None) -> list:
        """Returns list of tuples: (key, category, name, offset, value, range) adapted to the active OSC Model."""
        pr = self.get_patch_params(idx)
        model_id = override_model if override_model is not None else pr["osc_model"]
        spec = self.OSC_MODEL_SPECS.get(model_id, self.OSC_MODEL_SPECS[16])
        s_lbls = [s.replace(":", "") for s in spec["sliders"]]
        rows = [
            ("osc_model", "Voicing & Common", "OSC Model ID", "0x008", model_id, "16..27"),
            ("category", "Voicing & Common", "Tone Category ID", "0x020", pr["category"], "0..44"),
            ("patch_level", "Voicing & Common", "Patch Level", "0x024", pr["patch_level"], "0..127"),
            ("coarse_tune", "Voicing & Common", "Tone Coarse Tune (Semitones)", "0x029", pr["coarse_tune"], "-48..+48"),
            ("analog_feel", "Voicing & Common", "Analog Feel", "0x02D", pr["analog_feel"], "0..127"),
            ("mono_poly", "Voicing & Common", "Mono / Poly Switch (0=MONO, 1=POLY)", "0x02E", pr["mono_poly"], "0..1"),
            ("legato_sw", "Voicing & Common", "Legato Switch (0=OFF, 1=ON)", "0x031", pr["legato_sw"], "0..1"),
            ("porta_sw", "Voicing & Common", "Portamento Switch (0=OFF, 1=ON)", "0x032", pr["porta_sw"], "0..1"),
            ("porta_time", "Voicing & Common", "Portamento Time", "0x036", pr["porta_time"], "0..1023"),
            ("bend_up", "Voicing & Common", "Pitch Bend Range Up (Semitones)", "0x038", pr["bend_up"], "0..48"),
            ("bend_down", "Voicing & Common", "Pitch Bend Range Down (Semitones)", "0x039", pr["bend_down"], "0..48"),
            ("slider1", "OSC 1-4", f"Slider 1 — {s_lbls[0]}", "0x0D8", pr["slider1"], "0..127"),
            ("slider2", "OSC 1-4", f"Slider 2 — {s_lbls[1]}", "0x154", pr["slider2"], "0..127"),
            ("slider3", "OSC 1-4", f"Slider 3 — {s_lbls[2]}", "0x1D0", pr["slider3"], "0..127"),
            ("slider4", "OSC 1-4", f"Slider 4 — {s_lbls[3]}", "0x24C", pr["slider4"], "0..127"),
        ]
        for o in range(spec["active_oscs"]):
            od = pr["oscs"][o]
            o_title = spec["osc_names"][o].replace(":", "")
            base_hex = f"0x{0x720 + o * 44:03X}"
            rows.extend(
                [
                    (f"osc{o+1}_wave", "OSC 1-4", f"{o_title} Waveform ID", base_hex, od["wave"], "0..255"),
                    (f"osc{o+1}_coarse", "OSC 1-4", f"{o_title} Coarse Tune (Semi)", f"0x{0x721 + o * 44:03X}", od["coarse"], "-24..+24"),
                    (f"osc{o+1}_fine", "OSC 1-4", f"{o_title} Fine Tune (Cents)", f"0x{0x722 + o * 44:03X}", od["fine"], "-50..+50"),
                    (f"osc{o+1}_pw", "OSC 1-4", f"{o_title} Pulse Width", f"0x{0x723 + o * 44:03X}", od["pw"], "0..63"),
                    (f"osc{o+1}_pwm", "OSC 1-4", f"{o_title} PWM Depth", f"0x{0x724 + o * 44:03X}", od["pwm"], "0..63"),
                    (f"osc{o+1}_fat", "OSC 1-4", f"{o_title} Fat / SuperSAW Detune", f"0x{0x725 + o * 44:03X}", od["fat"], "0..127"),
                    (f"osc{o+1}_pan", "OSC 1-4", f"{o_title} Pan (64=Center)", f"0x{0x726 + o * 44:03X}", od["pan"], "0..127"),
                ]
            )
        rows.extend(
            [
                ("cutoff", "Filter & ADSR", "Filter Cutoff", "0x100", pr["cutoff"], "0..1023"),
                ("resonance", "Filter & ADSR", "Filter Resonance", "0x106", pr["resonance"], "0..1023"),
                ("flt_env_depth", "Filter & ADSR", "Filter Env Depth", "0x102", pr["flt_env_depth"], "0..255"),
                ("flt_atk", "Filter & ADSR", "Filter Attack", "0x38C", pr["flt_atk"], "0..1023"),
                ("flt_dec", "Filter & ADSR", "Filter Decay", "0x38E", pr["flt_dec"], "0..1023"),
                ("flt_sus", "Filter & ADSR", "Filter Sustain", "0x390", pr["flt_sus"], "0..1023"),
                ("flt_rel", "Filter & ADSR", "Filter Release", "0x392", pr["flt_rel"], "0..1023"),
                ("amp_atk", "Filter & ADSR", "Amp Attack", "0x328", pr["amp_atk"], "0..1023"),
                ("amp_dec", "Filter & ADSR", "Amp Decay", "0x332", pr["amp_dec"], "0..1023"),
                ("amp_sus", "Filter & ADSR", "Amp Sustain", "0x334", pr["amp_sus"], "0..1023"),
                ("amp_rel", "Filter & ADSR", "Amp Release", "0x33C", pr["amp_rel"], "0..1023"),
                ("lfo_shape", "LFO", "LFO Waveform Shape", "0x3FC", pr["lfo_shape"], "0..9"),
                ("lfo_rate", "LFO", "LFO Rate", "0x400", pr["lfo_rate"], "0..1023"),
                ("lfo_pitch", "LFO", "LFO Pitch Depth", "0x40B", pr["lfo_pitch"], "-63..+63"),
                ("lfo_flt", "LFO", "LFO Filter Depth", "0x40C", pr["lfo_flt"], "-63..+63"),
                ("lfo_amp", "LFO", "LFO Amp Depth", "0x40D", pr["lfo_amp"], "-63..+63"),
            ]
        )
        for sl in range(4):
            md = pr["matrix"][sl]
            b = 0x6F0 + sl * 12
            rows.append((f"mtx{sl+1}_src", "Matrix", f"Matrix Slot {sl+1} Source ID", f"0x{b:03X}", md["src"], "0..127"))
            for d_i in range(1, 5):
                rows.append(
                    (
                        f"mtx{sl+1}_dst{d_i}",
                        "Matrix",
                        f"Matrix Slot {sl+1} Dest {d_i} ID",
                        f"0x{b + (d_i-1)*2 + 1:03X}",
                        md[f"dst{d_i}"],
                        "0..63",
                    )
                )
                rows.append(
                    (
                        f"mtx{sl+1}_dep{d_i}",
                        "Matrix",
                        f"Matrix Slot {sl+1} Depth {d_i}",
                        f"0x{b + (d_i-1)*2 + 2:03X}",
                        md[f"dep{d_i}"],
                        "-63..+63",
                    )
                )
        rows.extend(
            [
                ("mfx_type", "MFX", "Tone MFX Type ID", "0x050", pr["mfx_type"], "0..93"),
                ("mfx_sw", "MFX", "Tone MFX Switch (0=OFF, 1=ON)", "0x051", pr["mfx_sw"], "0..1"),
                ("mfx_cho", "MFX", "Tone MFX Chorus Send", "0x052", pr["mfx_cho"], "0..127"),
                ("mfx_rev", "MFX", "Tone MFX Reverb Send", "0x053", pr["mfx_rev"], "0..127"),
            ]
        )
        for i in range(16):
            rows.append(
                (
                    f"mfx_p{i+1}",
                    "MFX",
                    f"MFX Internal Param {i+1:02d}",
                    f"0x{0x060 + i*2:03X}",
                    pr["mfx_params"][i],
                    "-32768..32767",
                )
            )
        return rows

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

    def get_part_step_length(self, pat_idx: int, part_idx: int) -> int:
        off = self.get_pattern_offset(pat_idx) + 0x08B4 + part_idx * 24
        return min(64, max(1, self.data[off] + 1))

    def set_part_step_length(self, pat_idx: int, part_idx: int, length_1_64: int):
        off = self.get_pattern_offset(pat_idx) + 0x08B4 + part_idx * 24
        self.data[off] = max(0, min(63, int(length_1_64) - 1))

    def get_step_offset(self, pat_idx: int, part_idx: int, step_idx_0_63: int) -> int:
        return self.get_pattern_offset(pat_idx) + 0x092C + part_idx * 3328 + step_idx_0_63 * 52

    def get_step_info(self, pat_idx: int, part_idx: int, step_idx_0_63: int) -> dict:
        soff = self.get_step_offset(pat_idx, part_idx, step_idx_0_63)
        sb = self.data[soff : soff + 52]
        notes = []
        vels = []
        gates = []
        probs = []
        substeps = []
        for v in range(8):
            n = sb[v]
            if n != 0xFF:
                notes.append(n)
                vels.append(sb[8 + v])
                gates.append(sb[16 + v])
                probs.append(sb[32 + v])
                substeps.append(sb[40 + v])
        if part_idx == 4:
            # Drum Part 5: also show short drum names for notes 36..61
            d_tags = []
            for n in notes:
                if 36 <= n <= 61:
                    lbl = DRUM_KEY_LABELS[n - 36].split("/")[0].split("(")[0].strip()
                    d_tags.append(f"{lbl}({n})")
                else:
                    d_tags.append(f"{midi_note_name(n)}({n})")
            note_names = ", ".join(d_tags) if d_tags else "—"
        else:
            note_names = ", ".join(f"{midi_note_name(n)} ({n})" for n in notes) if notes else "—"
        return {
            "step": step_idx_0_63 + 1,
            "notes": notes,
            "note_names": note_names,
            "vel": vels[0] if vels else 100,
            "gate": gates[0] if gates else 80,
            "prob": probs[0] if probs else 100,
            "substep": substeps[0] if substeps else 0,
            "vels": vels,
            "gates": gates,
            "probs": probs,
            "substeps": substeps,
        }

    def set_step_info(
        self,
        pat_idx: int,
        part_idx: int,
        step_idx_0_63: int,
        notes: list,
        vel: int = 100,
        gate: int = 80,
        prob: int = 100,
        substep: int = 0,
        per_note_vels: list = None,
        per_note_gates: list = None,
        per_note_probs: list = None,
        per_note_substeps: list = None,
    ):
        """Writes a 52-byte step record in PRFd (up to 8 polyphonic notes or drum hits)."""
        soff = self.get_step_offset(pat_idx, part_idx, step_idx_0_63)
        clean_notes = [max(0, min(127, int(n))) for n in notes[:8] if n is not None and 0 <= int(n) <= 127]
        sb = bytearray(52)
        for v in range(8):
            if v < len(clean_notes):
                sb[v] = clean_notes[v]
                v_vel = per_note_vels[v] if (per_note_vels and v < len(per_note_vels)) else vel
                v_gate = per_note_gates[v] if (per_note_gates and v < len(per_note_gates)) else gate
                v_prob = per_note_probs[v] if (per_note_probs and v < len(per_note_probs)) else prob
                v_sub = per_note_substeps[v] if (per_note_substeps and v < len(per_note_substeps)) else substep
                sb[8 + v] = max(1, min(127, int(v_vel)))
                sb[16 + v] = max(1, min(127, int(v_gate)))
                sb[32 + v] = max(0, min(100, int(v_prob)))
                sb[40 + v] = max(0, min(13, int(v_sub)))
            else:
                sb[v] = 0xFF
                sb[8 + v] = 80
                sb[16 + v] = 80
                sb[32 + v] = 100
                sb[40 + v] = 0
        # Preserve Motion Recording bytes (sb[24..31]) if already present, else hardware default [255,255,255,255,0,0,0,0]
        sb[24:28] = b"\xff\xff\xff\xff"
        sb[28:32] = b"\x00\x00\x00\x00"
        sb[48:52] = b"\x00\x00\x00\x00"
        self.data[soff : soff + 52] = sb

    def toggle_drum_step_note(
        self,
        pat_idx: int,
        step_idx_0_63: int,
        drum_midi_note: int,
        vel: int = 100,
        gate: int = 80,
        prob: int = 100,
    ) -> bool:
        """Toggles a drum instrument MIDI note (36..61) on Rhythm Part 5 (part_idx=4) at step_idx_0_63."""
        st = self.get_step_info(pat_idx, 4, step_idx_0_63)
        notes = list(st["notes"])
        vels = list(st["vels"])
        gates = list(st["gates"])
        probs = list(st["probs"])
        subs = list(st["substeps"])
        if drum_midi_note in notes:
            idx = notes.index(drum_midi_note)
            notes.pop(idx)
            vels.pop(idx)
            gates.pop(idx)
            probs.pop(idx)
            subs.pop(idx)
            added = False
        else:
            if len(notes) >= 8:
                notes.pop(-1)
                vels.pop(-1)
                gates.pop(-1)
                probs.pop(-1)
                subs.pop(-1)
            notes.append(drum_midi_note)
            vels.append(vel)
            gates.append(gate)
            probs.append(prob)
            subs.append(0)
            added = True
        self.set_step_info(
            pat_idx,
            4,
            step_idx_0_63,
            notes,
            per_note_vels=vels,
            per_note_gates=gates,
            per_note_probs=probs,
            per_note_substeps=subs,
        )
        return added

    def copy_part_content(
        self,
        src_pat: int,
        src_part: int,
        dst_pat: int,
        dst_part: int,
        include_tone: bool = False,
    ):
        """
        Implements SH-4d Manual 'PART' Copy/Paste:
        Copies the 64-step sequence data (3328 bytes) and 24-byte part sequencer setup.
        By default (per SH-4d manual), tone numbers are NOT copied unless include_tone=True.
        """
        src_p_off = self.get_pattern_offset(src_pat)
        dst_p_off = self.get_pattern_offset(dst_pat)

        # 1. Copy 64-step sequence block (3328 bytes at 0x092C + part*3328)
        s_seq = src_p_off + 0x092C + src_part * 3328
        d_seq = dst_p_off + 0x092C + dst_part * 3328
        tmp_seq = bytes(self.data[s_seq : s_seq + 3328])
        self.data[d_seq : d_seq + 3328] = tmp_seq

        # 2. Copy 24-byte Part Sequencer Config (step length, scale, play direction at 0x08B4 + part*24)
        s_cfg = src_p_off + 0x08B4 + src_part * 24
        d_cfg = dst_p_off + 0x08B4 + dst_part * 24
        tmp_cfg = bytes(self.data[s_cfg : s_cfg + 24])
        self.data[d_cfg : d_cfg + 24] = tmp_cfg

        # 3. Optionally copy Tone / Mixer header (88 bytes at 0x003A + part*88)
        if include_tone:
            s_mix = src_p_off + 0x003A + src_part * 88
            d_mix = dst_p_off + 0x003A + dst_part * 88
            tmp_mix = bytes(self.data[s_mix : s_mix + 88])
            self.data[d_mix : d_mix + 88] = tmp_mix

    def copy_steps_content(
        self,
        src_pat: int,
        src_part: int,
        start_step_1_64: int,
        end_step_1_64: int,
        dst_pat: int,
        dst_part: int,
        dst_start_step_1_64: int,
    ) -> int:
        """
        Implements SH-4d Manual 'STEP' and 'MULTI-STEP' Copy/Paste.
        Copies steps [start_step..end_step] (1-indexed, inclusive) to dst_start_step.
        Returns number of steps copied.
        """
        s_start = max(0, min(63, int(start_step_1_64) - 1))
        s_end = max(s_start, min(63, int(end_step_1_64) - 1))
        d_start = max(0, min(63, int(dst_start_step_1_64) - 1))

        num_steps = min(s_end - s_start + 1, 64 - d_start)
        src_off = self.get_step_offset(src_pat, src_part, s_start)
        dst_off = self.get_step_offset(dst_pat, dst_part, d_start)
        byte_len = num_steps * 52
        buf = bytes(self.data[src_off : src_off + byte_len])
        self.data[dst_off : dst_off + byte_len] = buf
        return num_steps

    def clear_steps_content(
        self, pat_idx: int, part_idx: int, start_step_1_64: int, end_step_1_64: int
    ):
        """Resets selected steps to clean hardware-initialized state."""
        s_start = max(0, min(63, int(start_step_1_64) - 1))
        s_end = max(s_start, min(63, int(end_step_1_64) - 1))
        empty_step = (
            b"\xff" * 8
            + b"\x50" * 16
            + b"\xff" * 4
            + b"\x00" * 4
            + b"\x64" * 8
            + b"\x00" * 12
        )
        for s in range(s_start, s_end + 1):
            off = self.get_step_offset(pat_idx, part_idx, s)
            self.data[off : off + 52] = empty_step

    SCALES = {
        "Minor (Aeolian)": [0, 2, 3, 5, 7, 8, 10],
        "Dorian": [0, 2, 3, 5, 7, 9, 10],
        "Phrygian (Dark/Techno)": [0, 1, 3, 5, 7, 8, 10],
        "Harmonic Minor": [0, 2, 3, 5, 7, 8, 11],
        "Pentatonic Minor": [0, 3, 5, 7, 10],
        "Major (Ionian)": [0, 2, 4, 5, 7, 9, 11],
    }

    CHORD_TYPES = {
        "Single Note": [0],
        "Octave (+12)": [0, 12],
        "Power 5th (0, +7)": [0, 7],
        "Minor Triad (0, +3, +7)": [0, 3, 7],
        "Major Triad (0, +4, +7)": [0, 4, 7],
        "Minor 7th (0, +3, +7, +10)": [0, 3, 7, 10],
        "Major 7th (0, +4, +7, +11)": [0, 4, 7, 11],
        "Sus4 (0, +5, +7)": [0, 5, 7],
    }

    KEY_TO_SEMITONE = {
        "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
        "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
    }

    @staticmethod
    def compute_euclidean_hits(pulses: int, steps: int, rotation: int = 0) -> list:
        """Returns a list of booleans of length `steps` with `pulses` evenly distributed."""
        steps = max(1, min(64, int(steps)))
        pulses = max(0, min(steps, int(pulses)))
        if pulses == 0:
            return [False] * steps
        hit_list = [((i * pulses) % steps) < pulses for i in range(steps)]
        if rotation:
            r = rotation % steps
            hit_list = hit_list[-r:] + hit_list[:-r]
        return hit_list

    def generate_part_sequence(
        self,
        pat_idx: int,
        part_idx: int,
        role: str,
        root_key: str = "C",
        scale_name: str = "Minor (Aeolian)",
        step_len: int = 16,
        density_pct: int = 65,
    ):
        """Generates a musical 16..64 step sequence on (pat_idx, part_idx) according to `role`."""
        step_len = max(1, min(64, int(step_len)))
        self.set_part_step_length(pat_idx, part_idx, step_len)
        self.clear_steps_content(pat_idx, part_idx, 1, 64)

        root_semi = self.KEY_TO_SEMITONE.get(root_key.strip(), 0)
        intervals = self.SCALES.get(scale_name, self.SCALES["Minor (Aeolian)"])
        dens = max(10, min(100, int(density_pct))) / 100.0

        # If Part 5 (Rhythm) or a Drum Role is selected:
        if part_idx == 4 or "Drum" in role:
            target_part = 4 if part_idx == 4 else part_idx
            self.set_part_step_length(pat_idx, target_part, step_len)
            self.clear_steps_content(pat_idx, target_part, 1, 64)
            is_break = "Break" in role or "Electro" in role
            is_minimal = "Minimal" in role or "Acid" in role
            for s in range(step_len):
                pos16 = s % 16
                notes = []
                vels = []
                gates = []
                probs = []
                # 1. Kick (BD1 = 36)
                if is_break:
                    if pos16 in (0, 6, 10) or (pos16 == 14 and random.random() < 0.4):
                        notes.append(36)
                        vels.append(118 if pos16 == 0 else 104)
                        gates.append(80)
                        probs.append(100)
                else:
                    if pos16 % 4 == 0 or (pos16 == 15 and random.random() < 0.35 * dens):
                        notes.append(36)
                        vels.append(118 if pos16 % 4 == 0 else 88)
                        gates.append(80)
                        probs.append(100 if pos16 % 4 == 0 else 75)
                # 2. Snare (38) & Clap (39)
                if pos16 in (4, 12):
                    if not is_minimal:
                        notes.append(38)
                        vels.append(108)
                        gates.append(80)
                        probs.append(100)
                    notes.append(39)
                    vels.append(112)
                    gates.append(80)
                    probs.append(100)
                elif is_break and pos16 in (7, 15) and random.random() < 0.55:
                    notes.append(38)
                    vels.append(72)
                    gates.append(60)
                    probs.append(80)
                # 3. Closed Hat (42) & Open Hat (46)
                if pos16 % 4 == 2:
                    notes.append(46)
                    vels.append(98)
                    gates.append(85)
                    probs.append(100)
                elif random.random() < dens:
                    notes.append(42)
                    vels.append(92 if pos16 % 2 == 0 else 68)
                    gates.append(55)
                    probs.append(100 if pos16 % 2 == 0 else 85)
                # 4. Percussion / Rim / Tom accent (40, 45, 51)
                if pos16 in (3, 9, 11, 14) and random.random() < 0.45 * dens:
                    perc_n = random.choice([40, 45, 47, 51])
                    if perc_n not in notes:
                        notes.append(perc_n)
                        vels.append(random.randint(72, 98))
                        gates.append(65)
                        probs.append(random.choice([75, 90, 100]))
                if notes:
                    self.set_step_info(
                        pat_idx, target_part, s, notes,
                        per_note_vels=vels, per_note_gates=gates, per_note_probs=probs,
                    )
            return

        # Melodic / Polyphonic Synth Roles (Parts 1..4)
        if "Acid" in role:
            base_oct = 36 + root_semi  # C2..B2
            scale_pool = [base_oct + iv for iv in intervals] + [base_oct + 12, base_oct + 12 + intervals[1], base_oct + 12 + intervals[4]]
            for s in range(step_len):
                if s % 4 == 0 or random.random() < dens:
                    n = base_oct if s % 8 == 0 else random.choice(scale_pool)
                    is_accent = (s % 4 == 0) or (random.random() < 0.35)
                    is_slide = random.random() < 0.30
                    vel = random.randint(114, 126) if is_accent else random.randint(76, 96)
                    gate = 108 if is_slide else random.randint(48, 72)
                    self.set_step_info(pat_idx, part_idx, s, [n], vel=vel, gate=gate, prob=100)
        elif "Bass" in role:
            base_oct = 36 + root_semi  # C2..B2
            for s in range(step_len):
                pos4 = s % 4
                bar_deg = (s // 16) % 4
                deg_offset = [0, intervals[min(5, len(intervals)-1)], intervals[min(3, len(intervals)-1)], intervals[min(4, len(intervals)-1)]][bar_deg]
                root_n = base_oct + (deg_offset if s >= 16 else 0)
                if pos4 == 2:
                    # Classic offbeat octave or root bass hit
                    n = root_n + 12 if random.random() < 0.65 else root_n
                    self.set_step_info(pat_idx, part_idx, s, [n], vel=112, gate=78, prob=100)
                elif pos4 == 3 and random.random() < dens:
                    n = root_n + random.choice([0, 7, 12])
                    self.set_step_info(pat_idx, part_idx, s, [n], vel=92, gate=62, prob=95)
                elif pos4 == 0 and (s % 8 == 0 or random.random() < 0.45 * dens):
                    self.set_step_info(pat_idx, part_idx, s, [root_n], vel=116, gate=82, prob=100)
                elif pos4 == 1 and random.random() < 0.4 * dens:
                    self.set_step_info(pat_idx, part_idx, s, [root_n], vel=84, gate=55, prob=85)
        elif "Chord" in role or "Dub" in role:
            base_oct = 48 + root_semi  # C3..B3
            is_dub = "Dub" in role
            prog_degrees = [0, 5, 3, 4] if len(intervals) >= 6 else [0, 2, 3, 4]
            for s in range(step_len):
                deg = prog_degrees[(s // 4) % len(prog_degrees)]
                chord_notes = []
                for c_step in (0, 2, 4, 6):
                    sc_idx = deg + c_step
                    oct_shift = (sc_idx // len(intervals)) * 12
                    semi = intervals[sc_idx % len(intervals)] + oct_shift
                    chord_notes.append(base_oct + semi)
                if is_dub:
                    if s % 16 in (0, 3, 6, 10, 14) and (s % 16 in (0, 6) or random.random() < dens):
                        self.set_step_info(
                            pat_idx, part_idx, s, chord_notes[:4],
                            vel=random.randint(94, 114), gate=random.randint(45, 70), prob=100,
                        )
                else:
                    if s % 4 == 0:
                        self.set_step_info(
                            pat_idx, part_idx, s, chord_notes[:4],
                            vel=102, gate=98, prob=100,
                        )
        elif "Pluck" in role or "Arp" in role:
            base_oct = 60 + root_semi  # C4..B4
            arp_degrees = [0, 2, 4, 6, 7, 4, 2, 1] if len(intervals) >= 7 else [0, 1, 2, 3, 4, 3, 2, 1]
            for s in range(step_len):
                if s % 2 == 0 or random.random() < dens:
                    deg = arp_degrees[s % len(arp_degrees)]
                    oct_shift = (deg // len(intervals)) * 12
                    semi = intervals[deg % len(intervals)] + oct_shift
                    n = base_oct + semi
                    vel = 110 if s % 4 == 0 else random.randint(78, 102)
                    gate = random.randint(45, 72)
                    prob = 100 if s % 2 == 0 else random.choice([85, 95, 100])
                    self.set_step_info(pat_idx, part_idx, s, [n], vel=vel, gate=gate, prob=prob)
        else:
            # Counter-Melody / Lead Hook
            base_oct = 60 + root_semi
            motif_steps = [0, 3, 6, 8, 11, 14]
            for s in range(step_len):
                if (s % 16) in motif_steps or (random.random() < 0.35 * dens):
                    deg = random.choice([0, 2, 3, 4, 6]) % len(intervals)
                    oct_add = random.choice([0, 0, 12])
                    n = base_oct + intervals[deg] + oct_add
                    self.set_step_info(
                        pat_idx, part_idx, s, [n],
                        vel=random.randint(90, 116), gate=random.randint(65, 95), prob=100,
                    )

    def generate_full_pattern(
        self,
        pat_idx: int,
        style: str = "Techno / Peak-Time (132 BPM)",
        root_key: str = "C",
        scale_name: str = "Minor (Aeolian)",
        step_len: int = 16,
        auto_assign_tones: bool = True,
        custom_name: str = None,
    ) -> dict:
        """Generates a complete 5-Part Pattern (Drums + Bass + Chords + Pluck Arp + Lead) in pat_idx."""
        # Clone clean header structure from Pattern 1-03 (idx 2) so all internal mixer/routing flags are valid
        if pat_idx != 2:
            src_off = self.get_pattern_offset(2)
            dst_off = self.get_pattern_offset(pat_idx)
            self.data[dst_off : dst_off + 0x92C] = self.data[src_off : src_off + 0x92C]

        style_specs = {
            "Techno / Peak-Time (132 BPM)": ("TECHNO GRV", 132.0, "Driving Bassline", "Dub Techno Stabs", "Pluck Arpeggio", "Lead Hook", "TR Drum Beat"),
            "Acid House / 303 Groove (128 BPM)": ("ACID 303", 128.0, "Acid 303 Bassline", "Polyphonic Chords", "Pluck Arpeggio", "Lead Hook", "Acid Percussion"),
            "Melodic Techno / Prog Pluck (124 BPM)": ("MELODIC PLK", 124.0, "Driving Bassline", "Polyphonic Chords", "Pluck Arpeggio", "Lead Hook", "TR Drum Beat"),
            "Dub Techno Hypnotic (120 BPM)": ("DUB TECHNO", 120.0, "Driving Bassline", "Dub Techno Stabs", "Pluck Arpeggio", "Dub Techno Stabs", "Minimal Drums"),
            "Synthwave / Electro 80s (112 BPM)": ("SYNTHWAVE", 112.0, "Driving Bassline", "Polyphonic Chords", "Pluck Arpeggio", "Lead Hook", "Electro Breakbeat"),
        }
        base_tag, bpm, r_p1, r_p2, r_p3, r_p4, r_p5 = style_specs.get(
            style, ("SH4D GROOVE", 126.0, "Driving Bassline", "Polyphonic Chords", "Pluck Arpeggio", "Lead Hook", "TR Drum Beat")
        )
        sfx = random.randint(10, 99)
        pat_name = (custom_name or f"{base_tag} {sfx}")[:16]

        parts_mixer = None
        if auto_assign_tones:
            # Part 1: User Bass (e.g. UT001..003), Part 2: User Chord/Pad (UT009..012), Part 3: User Pluck (UT049..064 or UT004), Part 4: Lead (UT007..018), Part 5: User Kit UK01..05
            pluck_pc = random.randint(48, 63) if self.get_patch_name(48).strip().upper() != "INIT TONE" else 3
            parts_mixer = [
                {"msb": 87, "lsb": 0, "pc": random.choice([0, 1, 2, 19]), "level": 106, "pan": 0},
                {"msb": 87, "lsb": 0, "pc": random.choice([8, 9, 10, 11]), "level": 88, "pan": -14},
                {"msb": 87, "lsb": 0, "pc": pluck_pc, "level": 96, "pan": 14},
                {"msb": 87, "lsb": 0, "pc": random.choice([6, 13, 15, 17]), "level": 86, "pan": 6},
                {"msb": 86, "lsb": 0, "pc": random.choice([0, 1, 2, 3, 4]), "level": 112, "pan": 0},
            ]

        self.set_pattern_info(pat_idx, name=pat_name, tempo=bpm, level=110, parts=parts_mixer)
        self.generate_part_sequence(pat_idx, 0, r_p1, root_key, scale_name, step_len, density_pct=70)
        self.generate_part_sequence(pat_idx, 1, r_p2, root_key, scale_name, step_len, density_pct=60)
        self.generate_part_sequence(pat_idx, 2, r_p3, root_key, scale_name, step_len, density_pct=75)
        self.generate_part_sequence(pat_idx, 3, r_p4, root_key, scale_name, step_len, density_pct=55)
        self.generate_part_sequence(pat_idx, 4, r_p5, root_key, scale_name, step_len, density_pct=75)
        return self.get_pattern_info(pat_idx)

    # ---------------- STANDARD MIDI FILE (.MID) PARSER, IMPORTER & EXPORTER ----------------
    @staticmethod
    def _read_vlq(buf: bytes, pos: int) -> tuple:
        val = 0
        while pos < len(buf):
            b = buf[pos]
            pos += 1
            val = (val << 7) | (b & 0x7F)
            if not (b & 0x80):
                break
        return val, pos

    @staticmethod
    def _write_vlq(val: int) -> bytes:
        val = max(0, int(val))
        out = [val & 0x7F]
        val >>= 7
        while val > 0:
            out.append((val & 0x7F) | 0x80)
            val >>= 7
        out.reverse()
        return bytes(out)

    @classmethod
    def parse_midi_file(cls, midi_path: str) -> dict:
        """
        Pure-Python Standard MIDI File (Format 0 & Format 1) parser.
        Returns:
          {
            "bpm": float,
            "ppq": int,
            "total_bars": int,
            "streams": [
              {
                "id": int,
                "label": str,
                "track_idx": int,
                "track_name": str,
                "channel": int (1..16),
                "note_count": int,
                "min_note": int,
                "max_note": int,
                "events": [{"step": int, "note": int, "vel": int, "gate": int}, ...],
              },
              ...
            ]
          }
        """
        with open(midi_path, "rb") as f:
            raw = f.read()

        if len(raw) < 14 or raw[0:4] != b"MThd":
            raise ValueError("Not a valid Standard MIDI File (missing MThd header).")

        hdr_len = struct.unpack(">I", raw[4:8])[0]
        _fmt, num_tracks, division = struct.unpack(">HHH", raw[8:14])
        if division & 0x8000:
            ppq = 480
        else:
            ppq = max(1, division)

        ticks_per_16th = max(1.0, ppq / 4.0)
        pos = 8 + hdr_len
        bpm = 120.0
        tempo_found = False
        streams = []
        max_step_seen = 15

        for trk_i in range(num_tracks):
            while pos + 8 <= len(raw) and raw[pos : pos + 4] != b"MTrk":
                chunk_len = struct.unpack(">I", raw[pos + 4 : pos + 8])[0]
                pos += 8 + chunk_len
            if pos + 8 > len(raw):
                break
            trk_len = struct.unpack(">I", raw[pos + 4 : pos + 8])[0]
            trk_end = min(len(raw), pos + 8 + trk_len)
            p = pos + 8
            pos = trk_end

            abs_tick = 0
            running_status = 0
            trk_name = f"Track {trk_i + 1}"
            active_notes = {}  # (ch, note) -> list of (start_tick, vel)
            ch_events = {}  # ch (1..16) -> list of {"step", "note", "vel", "gate"}

            while p < trk_end:
                delta, p = cls._read_vlq(raw, p)
                abs_tick += delta
                if p >= trk_end:
                    break
                status = raw[p]
                if status < 0x80:
                    if not running_status:
                        p += 1
                        continue
                    status = running_status
                else:
                    p += 1
                    if status < 0xF0:
                        running_status = status

                if status == 0xFF:
                    if p >= trk_end:
                        break
                    meta_type = raw[p]
                    p += 1
                    m_len, p = cls._read_vlq(raw, p)
                    m_data = raw[p : p + m_len]
                    p += m_len
                    if meta_type == 0x03 and m_data:
                        try:
                            dec = m_data.decode("utf-8", errors="ignore").strip()
                            if dec:
                                trk_name = dec
                        except Exception:
                            pass
                    elif meta_type == 0x51 and len(m_data) == 3 and not tempo_found:
                        us_per_q = (m_data[0] << 16) | (m_data[1] << 8) | m_data[2]
                        if us_per_q > 0:
                            bpm = round(60000000.0 / us_per_q, 2)
                            tempo_found = True
                elif status in (0xF0, 0xF7):
                    s_len, p = cls._read_vlq(raw, p)
                    p += s_len
                elif 0x80 <= status <= 0xEF:
                    msg_type = status & 0xF0
                    ch = (status & 0x0F) + 1
                    if msg_type in (0xC0, 0xD0):
                        p += 1
                    else:
                        if p + 2 > trk_end:
                            break
                        d1 = raw[p]
                        d2 = raw[p + 1]
                        p += 2
                        if msg_type == 0x90 and d2 > 0:
                            active_notes.setdefault((ch, d1), []).append((abs_tick, d2))
                        elif msg_type == 0x80 or (msg_type == 0x90 and d2 == 0):
                            stack = active_notes.get((ch, d1))
                            if stack:
                                st_tick, vel = stack.pop(0)
                                dur_ticks = max(1, abs_tick - st_tick)
                                step_idx = int(round(st_tick / ticks_per_16th))
                                dur_steps = dur_ticks / ticks_per_16th
                                gate = max(15, min(127, int(round(dur_steps * 80.0))))
                                ch_events.setdefault(ch, []).append(
                                    {"step": step_idx, "note": d1, "vel": max(1, min(127, vel)), "gate": gate}
                                )
                                if step_idx > max_step_seen:
                                    max_step_seen = step_idx
                else:
                    p += 1

            # Flush any unclosed notes at track end
            for (ch, note_num), stack in active_notes.items():
                for st_tick, vel in stack:
                    step_idx = int(round(st_tick / ticks_per_16th))
                    ch_events.setdefault(ch, []).append(
                        {"step": step_idx, "note": note_num, "vel": max(1, min(127, vel)), "gate": 80}
                    )
                    if step_idx > max_step_seen:
                        max_step_seen = step_idx

            for ch in sorted(ch_events.keys()):
                ev_list = ch_events[ch]
                if not ev_list:
                    continue
                notes_only = [e["note"] for e in ev_list]
                min_n, max_n = min(notes_only), max(notes_only)
                s_id = len(streams)
                lbl = (
                    f"#{s_id+1}: Trk {trk_i+1} '{trk_name[:18]}' | Ch {ch:02d} "
                    f"({len(ev_list)} notes, {midi_note_name(min_n)}..{midi_note_name(max_n)})"
                )
                streams.append(
                    {
                        "id": s_id,
                        "label": lbl,
                        "track_idx": trk_i,
                        "track_name": trk_name,
                        "channel": ch,
                        "note_count": len(ev_list),
                        "min_note": min_n,
                        "max_note": max_n,
                        "events": ev_list,
                    }
                )

        total_bars = max(1, (max_step_seen // 16) + 1)
        return {
            "bpm": max(20.0, min(300.0, bpm)),
            "ppq": ppq,
            "total_bars": total_bars,
            "streams": streams,
        }

    def import_midi_stream_to_part(
        self,
        pat_idx: int,
        part_idx: int,
        events: list,
        start_bar_1_indexed: int = 1,
        transpose_semi: int = 0,
    ) -> int:
        """
        Writes a parsed MIDI stream (`events`) into (`pat_idx`, `part_idx`) without remapping raw note numbers.
        Applies `transpose_semi` (-48..+48) and imports up to 64 steps starting at `start_bar_1_indexed`.
        Returns the number of imported note triggers.
        """
        start_step_offset = max(0, (int(start_bar_1_indexed) - 1) * 16)
        self.clear_steps_content(pat_idx, part_idx, 1, 64)

        step_buckets = {}  # step_0_63 -> list of (note, vel, gate)
        max_rel_step = 0
        imported_count = 0

        for ev in events:
            rel_step = ev["step"] - start_step_offset
            if 0 <= rel_step < 64:
                n_val = max(0, min(127, int(ev["note"]) + int(transpose_semi)))
                bucket = step_buckets.setdefault(rel_step, [])
                if not any(x[0] == n_val for x in bucket) and len(bucket) < 8:
                    bucket.append((n_val, ev["vel"], ev["gate"]))
                    imported_count += 1
                    if rel_step > max_rel_step:
                        max_rel_step = rel_step

        # Determine clean step length (16, 32, 48, or 64)
        if max_rel_step < 16:
            slen = 16
        elif max_rel_step < 32:
            slen = 32
        elif max_rel_step < 48:
            slen = 48
        else:
            slen = 64
        self.set_part_step_length(pat_idx, part_idx, slen)

        for s_idx, bucket in step_buckets.items():
            # Sort polyphonic notes low-to-high
            bucket.sort(key=lambda x: x[0])
            notes = [x[0] for x in bucket]
            vels = [x[1] for x in bucket]
            gates = [x[2] for x in bucket]
            self.set_step_info(
                pat_idx,
                part_idx,
                s_idx,
                notes,
                per_note_vels=vels,
                per_note_gates=gates,
            )
        return imported_count

    def export_pattern_to_midi_file(self, pat_idx: int, out_path: str) -> str:
        """
        Exports all 5 Parts (Synth 1..4 + Rhythm Part 5) of Pattern `pat_idx` to a Standard MIDI File (.mid Format 1).
        Uses Dawless setup MIDI channels (Ch 8, 9, 11, 12, 13) and 480 PPQ.
        """
        info = self.get_pattern_info(pat_idx)
        ppq = 480
        ticks_per_16th = ppq // 4  # 120 ticks per 16th step
        bpm = max(20.0, min(300.0, float(info["tempo"])))
        us_per_q = int(round(60000000.0 / bpm))

        # Track 0: Tempo & Pattern Title Meta Track
        t0 = bytearray()
        pat_title = f"SH-4d {info['slot']} {info['name']}".encode("ascii", errors="ignore")
        t0 += b"\x00\xff\x03" + self._write_vlq(len(pat_title)) + pat_title
        t0 += b"\x00\xff\x51\x03" + struct.pack(">I", us_per_q)[1:4]
        t0 += b"\x00\xff\x2f\x00"

        tracks_bytes = [bytes(t0)]
        part_channels = [8, 9, 11, 12, 13]
        part_labels = ["Synth Part 1", "Synth Part 2", "Synth Part 3", "Synth Part 4", "Rhythm Part 5"]

        for p_i in range(5):
            ch_0_15 = part_channels[p_i] - 1
            slen = self.get_part_step_length(pat_idx, p_i)
            p_meta = info["parts"][p_i]
            trk_title = f"{part_labels[p_i]} - {p_meta['resolved']}".encode("ascii", errors="ignore")

            midi_evs = []  # (tick, order_priority, bytes)
            for s in range(slen):
                st = self.get_step_info(pat_idx, p_i, s)
                if not st["notes"]:
                    continue
                on_tick = s * ticks_per_16th
                for n_idx, n_val in enumerate(st["notes"]):
                    vel = st["vels"][n_idx] if n_idx < len(st["vels"]) else 100
                    gate = st["gates"][n_idx] if n_idx < len(st["gates"]) else 80
                    dur_ticks = max(15, int(round((gate / 80.0) * ticks_per_16th)))
                    off_tick = on_tick + dur_ticks
                    midi_evs.append((on_tick, 1, bytes([0x90 | ch_0_15, n_val & 0x7F, max(1, min(127, vel))])))
                    midi_evs.append((off_tick, 0, bytes([0x80 | ch_0_15, n_val & 0x7F, 0])))

            midi_evs.sort(key=lambda x: (x[0], x[1]))
            tb = bytearray()
            tb += b"\x00\xff\x03" + self._write_vlq(len(trk_title)) + trk_title
            # Also include Bank Select MSB/LSB & Program Change at tick 0
            tb += b"\x00" + bytes([0xB0 | ch_0_15, 0, p_meta["msb"] & 0x7F])
            tb += b"\x00" + bytes([0xB0 | ch_0_15, 32, p_meta["lsb"] & 0x7F])
            tb += b"\x00" + bytes([0xC0 | ch_0_15, p_meta["pc"] & 0x7F])

            last_tick = 0
            for abs_t, _prio, msg_b in midi_evs:
                delta = max(0, abs_t - last_tick)
                last_tick = abs_t
                tb += self._write_vlq(delta) + msg_b
            tb += b"\x00\xff\x2f\x00"
            tracks_bytes.append(bytes(tb))

        out = bytearray()
        out += b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks_bytes), ppq)
        for tb in tracks_bytes:
            out += b"MTrk" + struct.pack(">I", len(tb)) + tb

        with open(out_path, "wb") as f:
            f.write(out)
        return out_path

    # ---------------- PRESET GENERATOR, MUTATOR & MATH WAVE / STEP LAB ----------------
    def find_template_patch_idx(self, preferred_model: int = 16) -> int:
        """Finds a valid non-init hardware patch index in PATc to clone base routing tables from."""
        if preferred_model == 16:
            # Prefer a 4-oscillator SH-4d patch where all 4 partials are enabled (e.g. Saw&Pulse Bass or Mod Apart Pluck)
            for i in range(256):
                p = self.get_patch_params(i)
                if p["osc_model"] == 16 and p["name"].strip().upper() != "INIT TONE":
                    if all(o["wave"] > 0 for o in p["oscs"]):
                        return i
        for i in range(256):
            p = self.get_patch_params(i)
            if p["osc_model"] == preferred_model and p["name"].strip().upper() != "INIT TONE":
                return i
        for i in range(256):
            p = self.get_patch_params(i)
            if p["name"].strip().upper() != "INIT TONE":
                return i
        return 0

    def set_patch_Bytes_from_valid(self, target_idx: int, preferred_idx: int):
        """Copies a valid non-init hardware template into target_idx."""
        if 0 <= preferred_idx < 256 and preferred_idx != target_idx:
            if self.get_patch_name(preferred_idx).strip().upper() != "INIT TONE":
                self.set_patch_bytes(target_idx, self.get_patch_bytes(preferred_idx))
                return
        tmpl = self.find_template_patch_idx(16)
        self.set_patch_bytes(target_idx, self.get_patch_bytes(tmpl))

    def get_drawing_wave(self, idx: int) -> dict:
        """Reads 32-step custom waveform (-72..+72) and Wave Edge (0..127) for DRAWING Model (23)."""
        off = self.get_patch_offset(idx)
        steps = [s8(self.data[off + 0x674 + i]) for i in range(32)]
        edge = int(self.data[off + 0x698])
        return {"steps": steps, "edge": edge}

    def set_drawing_wave(
        self, idx: int, steps_32: list, wave_edge: int = 40, switch_model: bool = True
    ):
        """Writes 32-step custom waveform (-72..+72) and Wave Edge (0..127) into patch idx."""
        if switch_model:
            cur = self.get_patch_params(idx)
            if cur["osc_model"] != 23 or cur["name"].strip().upper() == "INIT TONE":
                tmpl_idx = self.find_template_patch_idx(23)
                cur_name = cur["name"] if cur["name"].strip().upper() != "INIT TONE" else "Math Draw Wave"
                self.set_patch_bytes(idx, self.get_patch_bytes(tmpl_idx))
                self.set_patch_params(idx, name=cur_name, osc_model=23)
        off = self.get_patch_offset(idx)
        for i in range(32):
            v = int(steps_32[i]) if i < len(steps_32) else 0
            self.data[off + 0x674 + i] = u8_from_s8(max(-72, min(72, v)))
        self.data[off + 0x698] = max(0, min(127, int(wave_edge)))

    def get_step_lfo_data(self, idx: int) -> dict:
        """Reads 16-step LFO values (-72..+72) and curves (0..36) for STEP Model (27)."""
        off = self.get_patch_offset(idx)
        vals = [s8(self.data[off + 0x410 + i]) for i in range(16)]
        curves = [int(self.data[off + 0x420 + i]) for i in range(16)]
        return {"vals": vals, "curves": curves}

    def set_step_lfo_data(
        self, idx: int, vals_16: list, curves_16: list = None, switch_model: bool = True
    ):
        """Writes 16-step sequence values (-72..+72) and curves (0..36) into STEP Model (27) partials."""
        if switch_model:
            cur = self.get_patch_params(idx)
            if cur["osc_model"] != 27 or cur["name"].strip().upper() == "INIT TONE":
                tmpl_idx = self.find_template_patch_idx(27)
                cur_name = cur["name"] if cur["name"].strip().upper() != "INIT TONE" else "Math Step Seq"
                self.set_patch_bytes(idx, self.get_patch_bytes(tmpl_idx))
                self.set_patch_params(idx, name=cur_name, osc_model=27)
        off = self.get_patch_offset(idx)
        for p_base in (0x410, 0x478):
            for i in range(16):
                v = int(vals_16[i]) if i < len(vals_16) else 0
                self.data[off + p_base + i] = u8_from_s8(max(-72, min(72, v)))
                if curves_16 is not None and i < len(curves_16):
                    self.data[off + p_base + 0x10 + i] = max(0, min(36, int(curves_16[i])))

    @staticmethod
    def compute_math_wave_32(formula_name: str) -> tuple:
        """Returns (steps_32_list, recommended_edge) for DRAWING Model 23."""
        steps = []
        edge = 35
        for i in range(32):
            t = i / 32.0
            ph = 2.0 * math.pi * t
            if "Additive Odd/Even" in formula_name:
                val = (
                    math.sin(ph)
                    + 0.55 * math.sin(2 * ph)
                    + 0.40 * math.sin(3 * ph)
                    + 0.25 * math.sin(5 * ph)
                    + 0.18 * math.sin(7 * ph)
                ) / 1.65
                edge = 25
            elif "Formant Vocal" in formula_name:
                env = math.exp(-3.2 * t)
                val = env * (0.65 * math.sin(3 * ph) + 0.55 * math.sin(7 * ph) + 0.35 * math.cos(11 * ph))
                edge = 20
            elif "Wave-Folded" in formula_name:
                raw = 2.3 * math.sin(ph)
                val = math.sin(raw * math.pi * 0.65)
                edge = 30
            elif "Bit-Crushed Staircase" in formula_name:
                saw = 1.0 - 2.0 * t
                quant = round(saw * 4.0) / 4.0
                val = quant
                edge = 95
            elif "Hard-Sync" in formula_name:
                slave_ph = (t * 4.5) % 1.0
                win = 1.0 - t
                val = (1.0 - 2.0 * slave_ph) * (0.4 + 0.6 * win)
                edge = 65
            elif "Metallic Inharmonic" in formula_name:
                val = (
                    0.50 * math.sin(ph)
                    + 0.45 * math.sin(2.76 * ph)
                    + 0.35 * math.sin(5.40 * ph)
                    + 0.25 * math.sin(8.93 * ph)
                )
                edge = 45
            elif "FM 2-Op" in formula_name:
                idx_fm = 2.8
                val = math.sin(ph + idx_fm * math.sin(3.0 * ph))
                edge = 30
            else:
                # Smooth Random Spline / Chaos
                val = (
                    0.55 * math.sin(ph + random.uniform(-0.4, 0.4))
                    + 0.45 * math.cos(3 * ph + random.uniform(-0.8, 0.8))
                    + random.uniform(-0.25, 0.25)
                )
                edge = random.randint(20, 75)
            steps.append(max(-72, min(72, int(round(val * 70.0)))))
        return steps, edge

    @staticmethod
    def compute_step_lfo_16(pattern_name: str) -> tuple:
        """Returns (vals_16_list, curves_16_list) for STEP Model 27."""
        if "Trance Gate" in pattern_name:
            vals = [64, -64, 64, -40, 64, -64, 48, -64, 64, -64, 64, -20, 64, 48, -64, -64]
            curves = [0] * 16
        elif "Acid Octave" in pattern_name:
            vals = [0, 24, 0, -24, 14, 0, 24, -14, 0, 24, 36, 0, -24, 14, 24, 0]
            curves = [4, 0, 4, 0, 8, 0, 4, 0, 4, 0, 12, 0, 4, 8, 4, 0]
        elif "Rising Filter" in pattern_name:
            vals = [int(-64 + (128 * i / 15.0)) for i in range(16)]
            curves = [5] * 16
        elif "Pendulum" in pattern_name:
            vals = [int(round(64 * math.sin(2 * math.pi * i / 16.0))) for i in range(16)]
            curves = [6] * 16
        elif "Dub Polyrhythm" in pattern_name:
            base3 = [60, -35, 25]
            vals = [base3[i % 3] for i in range(16)]
            curves = [10 if i % 3 == 0 else 2 for i in range(16)]
        else:
            # Glitch Sample & Hold
            pool = [-64, -48, -36, -24, -12, 0, 12, 24, 36, 48, 64]
            vals = [random.choice(pool) for _ in range(16)]
            curves = [random.choice([0, 0, 4, 8, 15]) for _ in range(16)]
        return vals, curves

    def generate_smart_preset(
        self, target_idx: int, genre: str, custom_name: str = None
    ) -> dict:
        """Synthesizes a complete musical preset in PATc[target_idx] tailored to genre."""
        genres_list = [
            "Acid 303 Bass",
            "Reese / Neuro Bass",
            "Warm Analog Pad",
            "Lush Chord / Strings",
            "Pluck / Arpeggio",
            "Dub Techno Chord Stab",
            "Cyberpunk / Sync Lead",
            "FM / Metallic Bell",
            "Custom Drawn Wave (DRAWING)",
            "Rhythmic Step-Mod (STEP)",
        ]
        if "Mixed" in genre or "Surprise" in genre:
            genre = random.choice(genres_list)

        # Pick best hardware template so internal partial switches are 100% valid
        if "Acid" in genre:
            model = 19  # SH-101
            tmpl = self.find_template_patch_idx(19)
        elif "Sync" in genre:
            model = 22  # SYNC
            tmpl = self.find_template_patch_idx(22)
        elif "DRAWING" in genre:
            model = 23  # DRAWING
            tmpl = self.find_template_patch_idx(23)
        elif "STEP" in genre:
            model = 27  # STEP
            tmpl = self.find_template_patch_idx(27)
        elif "Wavetable" in genre or "Bell" in genre:
            model = random.choice([20, 21, 24])  # FM / RING / WAVETABLE
            tmpl = self.find_template_patch_idx(24)
        else:
            model = random.choice([16, 17])  # SH-4d / SH-3D
            tmpl = self.find_template_patch_idx(16)

        self.set_patch_bytes(target_idx, self.get_patch_bytes(tmpl))

        sfx = random.randint(10, 99)
        if "Acid 303" in genre:
            name = custom_name or f"Acid 303 #{sfx}"
            self.set_patch_params(
                target_idx,
                name=name,
                osc_model=19,
                category=21,
                patch_level=random.randint(105, 122),
                mono_poly=0,
                legato_sw=1,
                porta_sw=1,
                porta_time=random.randint(85, 220),
                analog_feel=random.randint(18, 45),
                slider1=127,
                slider2=random.randint(60, 115),
                slider3=random.randint(40, 95),
                slider4=random.randint(0, 35),
                cutoff=random.randint(220, 460),
                resonance=random.randint(580, 860),
                flt_env_depth=random.randint(68, 92),
                flt_atk=random.randint(0, 15),
                flt_dec=random.randint(220, 480),
                flt_sus=random.randint(40, 140),
                flt_rel=random.randint(120, 280),
                amp_atk=0,
                amp_dec=random.randint(380, 680),
                amp_sus=random.randint(450, 880),
                amp_rel=random.randint(120, 260),
                mfx_type=random.choice([33, 34, 84, 87]),
                mfx_sw=1,
                mfx_cho=random.randint(0, 30),
                mfx_rev=random.randint(10, 45),
            )
        elif "Reese" in genre:
            name = custom_name or f"Reese Bass #{sfx}"
            oscs = [
                {"wave": 1, "coarse": 0, "fine": -random.randint(14, 28), "pw": 64, "pwm": 10, "fat": random.randint(40, 90), "pan": 44},
                {"wave": 1, "coarse": 0, "fine": random.randint(14, 28), "pw": 64, "pwm": 10, "fat": random.randint(40, 90), "pan": 84},
                {"wave": 2, "coarse": -12, "fine": 0, "pw": random.randint(40, 90), "pwm": 24, "fat": random.randint(20, 60), "pan": 64},
                {"wave": 4, "coarse": -12, "fine": 0, "pw": 0, "pwm": 0, "fat": 80, "pan": 64},
            ]
            mtx = [
                {"src": 0, "dst1": 6, "dep1": random.randint(12, 32), "dst2": 17, "dep2": 22, "dst3": 0, "dep3": 0, "dst4": 0, "dep4": 0},
                {"src": 98, "dst1": 6, "dep1": 24, "dst2": 0, "dep2": 0, "dst3": 0, "dep3": 0, "dst4": 0, "dep4": 0},
                {"src": 102, "dst1": 0, "dep1": 0, "dst2": 0, "dep2": 0, "dst3": 0, "dep3": 0, "dst4": 0, "dep4": 0},
                {"src": 102, "dst1": 0, "dep1": 0, "dst2": 0, "dep2": 0, "dst3": 0, "dep3": 0, "dst4": 0, "dep4": 0},
            ]
            self.set_patch_params(
                target_idx,
                name=name,
                osc_model=16,
                category=21,
                patch_level=115,
                mono_poly=0,
                legato_sw=1,
                porta_sw=1,
                porta_time=random.randint(110, 280),
                analog_feel=random.randint(25, 65),
                oscs=oscs,
                matrix=mtx,
                slider1=127,
                slider2=122,
                slider3=random.randint(85, 115),
                slider4=random.randint(90, 127),
                cutoff=random.randint(280, 560),
                resonance=random.randint(220, 480),
                flt_env_depth=random.randint(60, 78),
                flt_atk=random.randint(10, 80),
                flt_dec=random.randint(450, 750),
                flt_sus=random.randint(350, 680),
                flt_rel=random.randint(180, 380),
                amp_atk=random.randint(0, 25),
                amp_dec=700,
                amp_sus=950,
                amp_rel=random.randint(150, 320),
                lfo_shape=0,
                lfo_rate=random.randint(120, 340),
                lfo_flt=random.randint(-28, 28),
                mfx_type=random.choice([4, 33, 73, 87]),
                mfx_sw=1,
                mfx_cho=random.randint(40, 95),
                mfx_rev=random.randint(10, 35),
            )
        elif "Warm Analog Pad" in genre or "Lush Chord" in genre:
            is_lush = "Lush" in genre
            name = custom_name or (f"Lush Pad #{sfx}" if is_lush else f"Warm Pad #{sfx}")
            oscs = [
                {"wave": 10 if is_lush else 1, "coarse": 0, "fine": -random.randint(8, 18), "pw": 64, "pwm": 18, "fat": random.randint(35, 85), "pan": 32},
                {"wave": 6 if is_lush else 2, "coarse": 0, "fine": random.randint(8, 18), "pw": random.randint(50, 90), "pwm": 28, "fat": random.randint(35, 85), "pan": 96},
                {"wave": 3, "coarse": 12 if is_lush else 0, "fine": -random.randint(4, 12), "pw": 64, "pwm": 0, "fat": 40, "pan": 48},
                {"wave": 4, "coarse": -12, "fine": 0, "pw": 0, "pwm": 0, "fat": 50, "pan": 80},
            ]
            mtx = [
                {"src": 0, "dst1": 17, "dep1": 28, "dst2": 18, "dep2": -24, "dst3": 28, "dep3": 18, "dst4": 6, "dep4": 14},
                {"src": 95, "dst1": 6, "dep1": 32, "dst2": 12, "dep2": 20, "dst3": 0, "dep3": 0, "dst4": 0, "dep4": 0},
                {"src": 102, "dst1": 0, "dep1": 0, "dst2": 0, "dep2": 0, "dst3": 0, "dep3": 0, "dst4": 0, "dep4": 0},
                {"src": 102, "dst1": 0, "dep1": 0, "dst2": 0, "dep2": 0, "dst3": 0, "dep3": 0, "dst4": 0, "dep4": 0},
            ]
            self.set_patch_params(
                target_idx,
                name=name,
                osc_model=16,
                category=38,
                patch_level=108,
                mono_poly=1,
                legato_sw=0,
                porta_sw=0,
                analog_feel=random.randint(35, 85),
                oscs=oscs,
                matrix=mtx,
                slider1=118,
                slider2=114,
                slider3=random.randint(80, 115),
                slider4=random.randint(80, 115),
                cutoff=random.randint(420, 760),
                resonance=random.randint(120, 340),
                flt_env_depth=random.randint(56, 76),
                flt_atk=random.randint(120, 340),
                flt_dec=random.randint(520, 860),
                flt_sus=random.randint(580, 880),
                flt_rel=random.randint(520, 880),
                amp_atk=random.randint(90, 280),
                amp_dec=random.randint(580, 880),
                amp_sus=random.randint(680, 960),
                amp_rel=random.randint(540, 900),
                lfo_shape=1,
                lfo_rate=random.randint(90, 260),
                lfo_flt=random.randint(-18, 18),
                mfx_type=random.choice([26, 75, 87, 92]),
                mfx_sw=1,
                mfx_cho=random.randint(70, 120),
                mfx_rev=random.randint(75, 125),
            )
        elif "Pluck" in genre or "Dub Techno" in genre:
            is_dub = "Dub" in genre
            # 8 distinct native-modeled Pluck / Stab sub-archetypes so every slot in a 16-patch bank sounds genuinely different!
            archetype = target_idx % 8
            if is_dub:
                dub_chords = [
                    (0, 3, 7, -12, "Min7 Dub"),
                    (0, 3, 10, 7, "Deep Dub"),
                    (0, 7, 12, -12, "5th Stab"),
                    (0, 5, 10, -12, "Quartal"),
                ]
                c1, c2, c3, c4, c_tag = random.choice(dub_chords)
                w1, w2, w3, w4 = random.choice([(6, 2, 1, 11), (10, 6, 2, 11), (1, 2, 6, 4), (2, 6, 10, 11)])
                oscs = [
                    {"wave": w1, "coarse": c1, "fine": -random.randint(4, 14), "pw": random.randint(40, 85), "pwm": random.randint(10, 30), "fat": random.randint(30, 75), "pan": 46},
                    {"wave": w2, "coarse": c2, "fine": random.randint(4, 14), "pw": random.randint(40, 90), "pwm": random.randint(10, 30), "fat": random.randint(25, 70), "pan": 82},
                    {"wave": w3, "coarse": c3, "fine": -random.randint(3, 10), "pw": 64, "pwm": 0, "fat": random.randint(20, 60), "pan": 54},
                    {"wave": w4, "coarse": c4, "fine": 0, "pw": 0, "pwm": 0, "fat": random.randint(20, 50), "pan": 74},
                ]
                name = custom_name or f"{c_tag} #{sfx}"
                self.set_patch_Bytes_from_valid(target_idx, random.choice([3, 5, 8, 20]))
                self.set_patch_params(
                    target_idx,
                    name=name,
                    osc_model=16,
                    category=34,
                    patch_level=random.randint(92, 104),
                    mono_poly=1,
                    legato_sw=0,
                    porta_sw=0,
                    analog_feel=random.randint(25, 70),
                    oscs=oscs,
                    slider1=random.randint(70, 95),
                    slider2=random.randint(65, 92),
                    slider3=random.randint(55, 85),
                    slider4=random.randint(20, 55),
                    cutoff=random.randint(160, 420),
                    resonance=random.randint(240, 680),
                    flt_env_depth=random.randint(42, 95),
                    flt_atk=random.randint(0, 12),
                    flt_dec=random.randint(90, 260),
                    flt_sus=random.randint(15, 110),
                    flt_rel=random.randint(80, 260),
                    amp_atk=0,
                    amp_dec=random.randint(35, 150),
                    amp_sus=random.randint(20, 140),
                    amp_rel=random.randint(40, 220),
                    mfx_type=random.choice([12, 75, 84, 92]),
                    mfx_sw=1,
                )
            else:
                # 8 Distinct Pluck Archetypes modeled after native SH-4d plucks (#04 Mod Apart, #06 Bright Pluck, #21 Kimene, #14 Drawing Bell, etc.)
                if archetype == 0:
                    # 1. Kimene Warm Analog Short Pluck (template #21 = idx 20)
                    self.set_patch_Bytes_from_valid(target_idx, 20)
                    name = custom_name or f"AnalogPlk #{sfx}"
                    oscs = [
                        {"wave": 1, "coarse": 0, "fine": -random.randint(4, 10), "pw": 64, "pwm": 0, "fat": random.randint(20, 55), "pan": 52},
                        {"wave": 2, "coarse": 0, "fine": random.randint(4, 10), "pw": random.randint(40, 85), "pwm": 18, "fat": random.randint(15, 45), "pan": 76},
                        {"wave": 2, "coarse": -12, "fine": 0, "pw": 64, "pwm": 0, "fat": 20, "pan": 64},
                        {"wave": 11, "coarse": 0, "fine": 0, "pw": 0, "pwm": 0, "fat": 0, "pan": 64},
                    ]
                    self.set_patch_params(
                        target_idx, name=name, osc_model=16, category=34, patch_level=98, mono_poly=1,
                        oscs=oscs, slider1=92, slider2=82, slider3=55, slider4=22,
                        cutoff=random.randint(180, 290), resonance=random.randint(180, 440), flt_env_depth=random.randint(48, 78),
                        flt_atk=0, flt_dec=random.randint(95, 165), flt_sus=random.randint(25, 75), flt_rel=random.randint(40, 110),
                        amp_atk=0, amp_dec=random.randint(40, 95), amp_sus=random.randint(15, 65), amp_rel=random.randint(0, 60),
                        mfx_type=84, mfx_sw=1,
                    )
                elif archetype == 1:
                    # 2. Mod Apart PWM Stereo Pluck (template #04 = idx 3)
                    self.set_patch_Bytes_from_valid(target_idx, 3)
                    name = custom_name or f"ModPluck #{sfx}"
                    oscs = [
                        {"wave": 10, "coarse": 0, "fine": -random.randint(6, 14), "pw": 64, "pwm": 20, "fat": random.randint(45, 85), "pan": 42},
                        {"wave": 1, "coarse": 0, "fine": random.randint(6, 14), "pw": 64, "pwm": 15, "fat": random.randint(35, 75), "pan": 86},
                        {"wave": 2, "coarse": 12, "fine": -4, "pw": random.randint(45, 75), "pwm": 25, "fat": 30, "pan": 64},
                        {"wave": 3, "coarse": -12, "fine": 0, "pw": 0, "pwm": 0, "fat": 20, "pan": 64},
                    ]
                    self.set_patch_params(
                        target_idx, name=name, osc_model=16, category=34, patch_level=96, mono_poly=1,
                        oscs=oscs, slider1=86, slider2=82, slider3=62, slider4=48,
                        cutoff=random.randint(310, 460), resonance=random.randint(40, 220), flt_env_depth=random.randint(35, 68),
                        flt_atk=0, flt_dec=random.randint(120, 210), flt_sus=random.randint(80, 220), flt_rel=random.randint(110, 220),
                        amp_atk=0, amp_dec=random.randint(18, 45), amp_sus=random.randint(60, 145), amp_rel=random.randint(0, 45),
                        mfx_type=87, mfx_sw=1,
                    )
                elif archetype == 2:
                    # 3. Bright Resonant Tape-Echo Pluck (template #06 = idx 5)
                    self.set_patch_Bytes_from_valid(target_idx, 5)
                    name = custom_name or f"EchoPluck #{sfx}"
                    oscs = [
                        {"wave": 6, "coarse": 0, "fine": -8, "pw": 70, "pwm": 15, "fat": 55, "pan": 48},
                        {"wave": 10, "coarse": 12, "fine": 8, "pw": 64, "pwm": 10, "fat": 65, "pan": 80},
                        {"wave": 2, "coarse": 0, "fine": 0, "pw": 85, "pwm": 30, "fat": 40, "pan": 64},
                        {"wave": 11, "coarse": 0, "fine": 0, "pw": 0, "pwm": 0, "fat": 0, "pan": 64},
                    ]
                    self.set_patch_params(
                        target_idx, name=name, osc_model=16, category=34, patch_level=94, mono_poly=1,
                        oscs=oscs, slider1=65, slider2=78, slider3=45, slider4=35,
                        cutoff=random.randint(580, 860), resonance=random.randint(520, 880), flt_env_depth=random.randint(25, 60),
                        flt_atk=0, flt_dec=random.randint(110, 190), flt_sus=random.randint(40, 110), flt_rel=random.randint(120, 220),
                        amp_atk=0, amp_dec=random.randint(18, 42), amp_sus=random.randint(70, 140), amp_rel=random.randint(0, 40),
                        mfx_type=12, mfx_sw=1,
                    )
                elif archetype == 3:
                    # 4. 5th Interval Prog House Pluck (OSC2 = +7 semitones, MFX 75 Delay+Chorus)
                    self.set_patch_Bytes_from_valid(target_idx, 3)
                    name = custom_name or f"FifthPlk #{sfx}"
                    oscs = [
                        {"wave": 10, "coarse": 0, "fine": -10, "pw": 64, "pwm": 0, "fat": 75, "pan": 40},
                        {"wave": 10, "coarse": 7, "fine": 10, "pw": 64, "pwm": 0, "fat": 70, "pan": 88},
                        {"wave": 2, "coarse": -12, "fine": 0, "pw": 75, "pwm": 15, "fat": 40, "pan": 64},
                        {"wave": 4, "coarse": 19, "fine": 0, "pw": 0, "pwm": 0, "fat": 30, "pan": 64},
                    ]
                    self.set_patch_params(
                        target_idx, name=name, osc_model=16, category=34, patch_level=94, mono_poly=1,
                        oscs=oscs, slider1=88, slider2=76, slider3=60, slider4=42,
                        cutoff=random.randint(260, 440), resonance=random.randint(120, 320), flt_env_depth=random.randint(55, 88),
                        flt_atk=0, flt_dec=random.randint(110, 200), flt_sus=random.randint(30, 90), flt_rel=random.randint(80, 180),
                        amp_atk=0, amp_dec=random.randint(25, 70), amp_sus=random.randint(30, 95), amp_rel=random.randint(20, 90),
                        mfx_type=75, mfx_sw=1,
                    )
                elif archetype == 4:
                    # 5. Custom Drawn Wave Pluck (Model 23: DRAWING, template #14 = idx 13)
                    self.set_patch_Bytes_from_valid(target_idx, 13)
                    formulas = ["Formant Vocal Wave", "Metallic Inharmonic Bell", "FM 2-Op Phase Modulated", "Hard-Sync Sweep Wave"]
                    steps_32, edge = self.compute_math_wave_32(random.choice(formulas))
                    self.set_drawing_wave(target_idx, steps_32, edge, switch_model=False)
                    name = custom_name or f"DrawPluck #{sfx}"
                    self.set_patch_params(
                        target_idx, name=name, osc_model=23, category=34, patch_level=98, mono_poly=1,
                        slider1=random.randint(75, 110), slider2=edge, slider3=random.randint(30, 75), slider4=random.randint(0, 25),
                        cutoff=random.randint(340, 620), resonance=random.randint(120, 380), flt_env_depth=random.randint(40, 75),
                        flt_atk=0, flt_dec=random.randint(140, 320), flt_sus=random.randint(40, 160), flt_rel=random.randint(60, 180),
                        amp_atk=0, amp_dec=random.randint(30, 85), amp_sus=random.randint(40, 180), amp_rel=random.randint(40, 140),
                        mfx_type=17, mfx_sw=1,
                    )
                elif archetype == 5:
                    # 6. SH-101 Punchy Mono/Arp Pluck (Model 19: SH-101, template #16 = idx 15)
                    self.set_patch_Bytes_from_valid(target_idx, 15)
                    name = custom_name or f"SH101Plk #{sfx}"
                    self.set_patch_params(
                        target_idx, name=name, osc_model=19, category=34, patch_level=98, mono_poly=1,
                        slider1=random.randint(60, 110), slider2=random.randint(70, 115), slider3=random.randint(50, 95), slider4=random.randint(0, 25),
                        cutoff=random.randint(200, 380), resonance=random.randint(380, 720), flt_env_depth=random.randint(55, 95),
                        flt_atk=0, flt_dec=random.randint(90, 220), flt_sus=random.randint(0, 60), flt_rel=random.randint(40, 140),
                        amp_atk=0, amp_dec=random.randint(35, 110), amp_sus=random.randint(0, 60), amp_rel=random.randint(10, 80),
                        mfx_type=34, mfx_sw=1,
                    )
                elif archetype == 6:
                    # 7. Wavetable Digital Pluck (Model 24: WAVETABLE, template #15 = idx 14)
                    self.set_patch_Bytes_from_valid(target_idx, 14)
                    name = custom_name or f"WavePluck #{sfx}"
                    self.set_patch_params(
                        target_idx, name=name, osc_model=24, category=34, patch_level=96, mono_poly=1,
                        slider1=random.randint(25, 115), slider2=random.randint(40, 110), slider3=random.randint(40, 85), slider4=random.randint(0, 20),
                        cutoff=random.randint(320, 640), resonance=random.randint(160, 460), flt_env_depth=random.randint(45, 85),
                        flt_atk=0, flt_dec=random.randint(100, 240), flt_sus=random.randint(20, 90), flt_rel=random.randint(60, 180),
                        amp_atk=0, amp_dec=random.randint(25, 80), amp_sus=random.randint(20, 90), amp_rel=random.randint(20, 110),
                        mfx_type=26, mfx_sw=1,
                    )
                else:
                    # 8. Minor Chord Stab Pluck (template #09 = idx 8)
                    self.set_patch_Bytes_from_valid(target_idx, 8)
                    name = custom_name or f"ChordPlk #{sfx}"
                    oscs = [
                        {"wave": 6, "coarse": 0, "fine": -7, "pw": 64, "pwm": 12, "fat": 50, "pan": 45},
                        {"wave": 10, "coarse": 3, "fine": 7, "pw": 64, "pwm": 0, "fat": 65, "pan": 83},
                        {"wave": 5, "coarse": 7, "fine": -5, "pw": 64, "pwm": 0, "fat": 45, "pan": 55},
                        {"wave": 2, "coarse": -12, "fine": 0, "pw": 70, "pwm": 0, "fat": 30, "pan": 73},
                    ]
                    self.set_patch_params(
                        target_idx, name=name, osc_model=16, category=34, patch_level=94, mono_poly=1,
                        oscs=oscs, slider1=85, slider2=80, slider3=75, slider4=50,
                        cutoff=random.randint(240, 460), resonance=random.randint(180, 480), flt_env_depth=random.randint(55, 92),
                        flt_atk=0, flt_dec=random.randint(110, 220), flt_sus=random.randint(20, 80), flt_rel=random.randint(60, 160),
                        amp_atk=0, amp_dec=random.randint(25, 75), amp_sus=random.randint(15, 75), amp_rel=random.randint(10, 80),
                        mfx_type=92, mfx_sw=1,
                    )
        elif "Sync Lead" in genre or "Cyberpunk" in genre:
            name = custom_name or f"Cyber Sync #{sfx}"
            self.set_patch_params(
                target_idx,
                name=name,
                osc_model=22,
                category=35,
                patch_level=114,
                mono_poly=0,
                legato_sw=1,
                porta_sw=1,
                porta_time=random.randint(60, 180),
                analog_feel=random.randint(20, 50),
                slider1=127,
                slider2=random.randint(75, 125),
                slider3=random.randint(60, 115),
                slider4=random.randint(40, 100),
                cutoff=random.randint(420, 780),
                resonance=random.randint(280, 540),
                flt_env_depth=random.randint(66, 86),
                flt_atk=random.randint(0, 35),
                flt_dec=random.randint(320, 600),
                flt_sus=random.randint(300, 680),
                flt_rel=random.randint(140, 320),
                amp_atk=0,
                amp_dec=650,
                amp_sus=880,
                amp_rel=random.randint(140, 300),
                mfx_type=random.choice([34, 73, 84, 87]),
                mfx_sw=1,
                mfx_cho=random.randint(30, 80),
                mfx_rev=random.randint(40, 85),
            )
        elif "Bell" in genre or "FM" in genre:
            name = custom_name or f"Metallic Bell #{sfx}"
            self.set_patch_params(
                target_idx,
                name=name,
                osc_model=model,
                category=14,
                patch_level=112,
                mono_poly=1,
                legato_sw=0,
                porta_sw=0,
                slider1=random.randint(95, 127),
                slider2=random.randint(75, 120),
                slider3=random.randint(55, 110),
                slider4=random.randint(40, 95),
                cutoff=random.randint(520, 880),
                resonance=random.randint(140, 360),
                flt_env_depth=random.randint(64, 82),
                flt_atk=0,
                flt_dec=random.randint(420, 760),
                flt_sus=random.randint(180, 480),
                flt_rel=random.randint(480, 880),
                amp_atk=0,
                amp_dec=random.randint(460, 820),
                amp_sus=random.randint(180, 480),
                amp_rel=random.randint(520, 920),
                mfx_type=17,
                mfx_sw=1,
                mfx_cho=random.randint(50, 100),
                mfx_rev=random.randint(75, 125),
            )
        elif "DRAWING" in genre:
            formulas = [
                "Additive Odd/Even Harmonics",
                "Formant Vocal Wave",
                "Wave-Folded West-Coast Sine",
                "Bit-Crushed Staircase Saw",
                "Hard-Sync Sweep Wave",
                "Metallic Inharmonic Bell",
                "FM 2-Op Phase Modulated",
                "Smooth Random Spline",
            ]
            chosen_f = random.choice(formulas)
            steps_32, edge = self.compute_math_wave_32(chosen_f)
            name = custom_name or f"DrawWave #{sfx}"
            self.set_drawing_wave(target_idx, steps_32, edge, switch_model=True)
            self.set_patch_params(
                target_idx,
                name=name,
                osc_model=23,
                category=38,
                patch_level=114,
                cutoff=random.randint(360, 780),
                resonance=random.randint(180, 480),
                flt_env_depth=random.randint(64, 86),
                flt_atk=random.randint(0, 60),
                flt_dec=random.randint(320, 680),
                flt_sus=random.randint(320, 760),
                flt_rel=random.randint(240, 640),
                amp_atk=random.randint(0, 40),
                amp_dec=random.randint(400, 780),
                amp_sus=random.randint(450, 880),
                amp_rel=random.randint(260, 680),
                mfx_cho=random.randint(35, 95),
                mfx_rev=random.randint(45, 110),
            )
        elif "STEP" in genre:
            patterns = [
                "Trance Gate 16-Step",
                "Acid Octave Arpeggio",
                "Rising Filter / Pitch Ramp",
                "Pendulum Sine Groove",
                "Dub Polyrhythm (3x5)",
                "Glitch Sample & Hold",
            ]
            chosen_p = random.choice(patterns)
            vals_16, curves_16 = self.compute_step_lfo_16(chosen_p)
            name = custom_name or f"StepSeq #{sfx}"
            self.set_step_lfo_data(target_idx, vals_16, curves_16, switch_model=True)
            self.set_patch_params(
                target_idx,
                name=name,
                osc_model=27,
                category=41,
                patch_level=114,
                cutoff=random.randint(340, 740),
                resonance=random.randint(240, 560),
                flt_env_depth=random.randint(62, 86),
                mfx_cho=random.randint(40, 95),
                mfx_rev=random.randint(40, 100),
            )
        return self.get_patch_params(target_idx)

    def mutate_patch(
        self,
        idx: int,
        amount_pct: int = 20,
        mut_osc: bool = True,
        mut_flt: bool = True,
        mut_env: bool = True,
        mut_lfo_mtx: bool = True,
        mut_mfx: bool = False,
        new_name: str = None,
    ) -> dict:
        """Organic genetic mutator: drifts unlocked synthesis sections of patch idx by amount_pct (5..100%)."""
        cur = self.get_patch_params(idx)
        if cur["name"].strip().upper() == "INIT TONE":
            tmpl = self.find_template_patch_idx(16)
            self.set_patch_bytes(idx, self.get_patch_bytes(tmpl))
            cur = self.get_patch_params(idx)

        amt = max(1, min(100, int(amount_pct))) / 100.0

        def drift(val, lo, hi, span=None):
            sp = span if span is not None else (hi - lo)
            delta = int(round(random.uniform(-sp * amt * 0.45, sp * amt * 0.45)))
            return max(lo, min(hi, int(val) + delta))

        kw = {}
        if new_name:
            kw["name"] = new_name

        if mut_osc:
            kw["analog_feel"] = drift(cur["analog_feel"], 0, 127, 80)
            kw["slider1"] = drift(cur["slider1"], 45, 127, 90)
            kw["slider2"] = drift(cur["slider2"], 0, 127, 90)
            kw["slider3"] = drift(cur["slider3"], 0, 127, 90)
            kw["slider4"] = drift(cur["slider4"], 0, 127, 90)
            new_oscs = []
            for o in cur["oscs"]:
                no = dict(o)
                if random.random() < amt * 0.45:
                    no["wave"] = random.choice([1, 2, 3, 4, 5, 6, 7, 10])
                no["fine"] = drift(o["fine"], -50, 50, 36)
                no["pw"] = drift(o["pw"], 0, 127, 80)
                no["pwm"] = drift(o["pwm"], -63, 63, 60)
                no["fat"] = drift(o["fat"], 0, 127, 80)
                no["pan"] = drift(o["pan"], -64, 63, 64)
                new_oscs.append(no)
            kw["oscs"] = new_oscs
            if cur["osc_model"] == 23:
                dw = self.get_drawing_wave(idx)
                new_steps = [drift(s, -72, 72, 90) for s in dw["steps"]]
                new_edge = drift(dw["edge"], 0, 127, 80)
                self.set_drawing_wave(idx, new_steps, new_edge, switch_model=False)
            elif cur["osc_model"] == 27:
                st = self.get_step_lfo_data(idx)
                new_vals = [drift(v, -72, 72, 90) for v in st["vals"]]
                self.set_step_lfo_data(idx, new_vals, st["curves"], switch_model=False)

        if mut_flt:
            kw["cutoff"] = drift(cur["cutoff"], 60, 980, 650)
            kw["resonance"] = drift(cur["resonance"], 0, 920, 600)
            kw["flt_env_depth"] = drift(cur["flt_env_depth"], 20, 110, 50)

        if mut_env:
            kw["flt_atk"] = drift(cur["flt_atk"], 0, 950, 500)
            kw["flt_dec"] = drift(cur["flt_dec"], 40, 980, 550)
            kw["flt_sus"] = drift(cur["flt_sus"], 0, 980, 600)
            kw["flt_rel"] = drift(cur["flt_rel"], 20, 980, 550)
            kw["amp_atk"] = drift(cur["amp_atk"], 0, 900, 450)
            kw["amp_dec"] = drift(cur["amp_dec"], 60, 980, 550)
            kw["amp_sus"] = drift(cur["amp_sus"], 0, 1000, 600)
            kw["amp_rel"] = drift(cur["amp_rel"], 20, 980, 550)

        if mut_lfo_mtx:
            if random.random() < amt * 0.4:
                kw["lfo_shape"] = random.randint(0, 5)
            kw["lfo_rate"] = drift(cur["lfo_rate"], 10, 950, 500)
            kw["lfo_pitch"] = drift(cur["lfo_pitch"], -36, 36, 32)
            kw["lfo_flt"] = drift(cur["lfo_flt"], -63, 63, 64)
            kw["lfo_amp"] = drift(cur["lfo_amp"], -63, 63, 50)
            new_mtx = []
            for m in cur["matrix"]:
                nm = dict(m)
                for d_i in range(1, 5):
                    if nm[f"dst{d_i}"] != 0:
                        nm[f"dep{d_i}"] = drift(nm[f"dep{d_i}"], -63, 63, 64)
                new_mtx.append(nm)
            kw["matrix"] = new_mtx

        if mut_mfx:
            if random.random() < amt * 0.35:
                kw["mfx_type"] = random.choice([4, 12, 17, 26, 33, 34, 73, 75, 84, 87, 92])

        self.set_patch_params(idx, **kw)
        return self.get_patch_params(idx)

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
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Roland.SH4d.SVDEditor.1.0")
        except Exception:
            pass
        super().__init__()
        self.title("Roland SH-4d .SVD Editor & Real-Time MIDI Synth Controller (Dawless Project)")
        self.geometry("1260x800")
        self._apply_app_icon()
        self.font_size = 9
        self.style = ttk.Style(self)
        self.svd: SH4dSVD = None
        self.midi = WinMMMidiOut()
        self.live_cc_vars = {}
        self._build_ui()
        self.apply_font_size(self.font_size)

        # Keyboard & MouseWheel shortcuts for resizing fonts (Ctrl + / Ctrl - / Ctrl + MouseWheel)
        self.bind_all("<Control-plus>", lambda _e: self.change_font_size(1))
        self.bind_all("<Control-equal>", lambda _e: self.change_font_size(1))
        self.bind_all("<Control-minus>", lambda _e: self.change_font_size(-1))
        self.bind_all("<Control-MouseWheel>", self._on_ctrl_mousewheel)

        if initial_path and os.path.exists(initial_path):
            self.load_svd(initial_path)

    def _on_ctrl_mousewheel(self, event):
        if event.delta > 0:
            self.change_font_size(1)
        elif event.delta < 0:
            self.change_font_size(-1)

    def change_font_size(self, delta: int):
        new_sz = max(6, min(16, self.font_size + delta))
        if new_sz != self.font_size:
            self.apply_font_size(new_sz, delta)

    def apply_font_size(self, sz: int, delta: int = 0):
        self.font_size = sz
        if hasattr(self, "lbl_font_sz"):
            self.lbl_font_sz.config(text=f"{sz}pt")

        for fname in (
            "TkDefaultFont",
            "TkTextFont",
            "TkFixedFont",
            "TkMenuFont",
            "TkHeadingFont",
            "TkCaptionFont",
            "TkSmallCaptionFont",
            "TkIconFont",
        ):
            try:
                tkfont.nametofont(fname).configure(family="Segoe UI", size=sz)
            except Exception:
                pass

        row_h = max(16, int(sz * 2.3))
        self.style.configure(".", font=("Segoe UI", sz))
        self.style.configure("TLabel", font=("Segoe UI", sz))
        self.style.configure("TButton", font=("Segoe UI", sz))
        self.style.configure("TEntry", font=("Segoe UI", sz))
        self.style.configure("TCombobox", font=("Segoe UI", sz))
        self.style.configure("TCheckbutton", font=("Segoe UI", sz))
        self.style.configure("TLabelframe.Label", font=("Segoe UI", sz, "bold"))
        self.style.configure("TNotebook.Tab", font=("Segoe UI", sz, "bold"))
        self.style.configure("Treeview", font=("Segoe UI", sz), rowheight=row_h)
        self.style.configure("Treeview.Heading", font=("Segoe UI", sz, "bold"))

        if delta != 0:
            self._scale_widget_fonts(self, sz)

    def _scale_widget_fonts(self, widget, base_sz: int):
        for child in widget.winfo_children():
            try:
                f_str = str(child.cget("font"))
                if f_str and not f_str.startswith("Tk"):
                    f_obj = tkfont.Font(root=self, font=child.cget("font"))
                    weight = f_obj.cget("weight")
                    child.configure(font=("Segoe UI", base_sz if weight == "bold" else max(6, base_sz - 1), weight))
            except Exception:
                pass
            self._scale_widget_fonts(child, base_sz)

    def _apply_app_icon(self):
        base_dirs = []
        if hasattr(sys, "_MEIPASS"):
            base_dirs.append(sys._MEIPASS)
        base_dirs.append(os.path.dirname(os.path.abspath(__file__)))
        for d in base_dirs:
            ico = os.path.join(d, "sh4d.ico")
            if os.path.exists(ico):
                try:
                    self.iconbitmap(default=ico)
                    return
                except Exception:
                    pass

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

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Label(top, text="Font:").pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(top, text="A-", width=3, command=lambda: self.change_font_size(-1)).pack(side=tk.LEFT, padx=1)
        self.lbl_font_sz = ttk.Label(top, text="9pt", width=4, anchor=tk.CENTER, font=("Segoe UI", 8, "bold"))
        self.lbl_font_sz.pack(side=tk.LEFT, padx=1)
        ttk.Button(top, text="A+", width=3, command=lambda: self.change_font_size(1)).pack(side=tk.LEFT, padx=1)

        self.lbl_status = ttk.Label(top, text="No file loaded", font=("Segoe UI", 8, "bold"))
        self.lbl_status.pack(side=tk.LEFT, padx=8)

        # Notebook tabs
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._build_live_synth_tab()
        self._build_patches_tab()
        self._build_patterns_tab()
        self._build_rhythm_tab()
        self._build_generator_tab()
        self._build_pattern_creator_tab()

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
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="🎵 1. User Patterns & Step/Part Copy-Paste (128 Slots - PRFd)")

        pw = tk.PanedWindow(tab, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED, bg="#b8b8b8")
        pw.pack(fill=tk.BOTH, expand=True)

        # Left pane: 128 Patterns Table (with Vertical + Horizontal scrollbars)
        left = ttk.LabelFrame(pw, text="128 User Patterns (Drag Divider to Resize)", padding=4)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        cols = ("slot", "name", "tempo", "s1", "s2", "s3", "s4", "rhy")
        self.tree_pat = ttk.Treeview(left, columns=cols, show="headings", selectmode="browse")
        headers = {
            "slot": ("Slot", 46),
            "name": ("Pattern Name", 105),
            "tempo": ("BPM", 48),
            "s1": ("Part 1 (Ch 8)", 110),
            "s2": ("Part 2 (Ch 9)", 110),
            "s3": ("Part 3 (Ch 11)", 110),
            "s4": ("Part 4 (Ch 12)", 110),
            "rhy": ("Rhythm (Ch 13)", 110),
        }
        for c, (txt, w) in headers.items():
            self.tree_pat.heading(c, text=txt)
            self.tree_pat.column(c, width=w, minwidth=40, stretch=True, anchor=tk.W)

        sb_y = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree_pat.yview)
        sb_x = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.tree_pat.xview)
        self.tree_pat.configure(yscrollcommand=sb_y.set, xscrollcommand=sb_x.set)
        self.tree_pat.grid(row=0, column=0, sticky="nsew")
        sb_y.grid(row=0, column=1, sticky="ns")
        sb_x.grid(row=1, column=0, sticky="ew")
        self.tree_pat.bind("<<TreeviewSelect>>", self.on_select_pattern)

        # Middle pane: 64-Step Sequencer Inspector & Manual Copy/Paste (PART / STEP / MULTI-STEP)
        mid = ttk.LabelFrame(pw, text="Sequencer Inspector & Copy/Paste (PART / STEP / MULTI-STEP)", padding=6)

        part_bar = ttk.Frame(mid)
        part_bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(part_bar, text="Inspect Part:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.part_names_list = [
            "1: Synth 1 (M08)",
            "2: Synth 2 (M09)",
            "3: Synth 3 (M11)",
            "4: Synth 4 (M12)",
            "5: Rhythm (M13)",
        ]
        self.var_seq_part = tk.StringVar(value=self.part_names_list[0])
        cb_seq_part = ttk.Combobox(
            part_bar,
            textvariable=self.var_seq_part,
            values=self.part_names_list,
            state="readonly",
            width=15,
        )
        cb_seq_part.pack(side=tk.LEFT, padx=3)
        cb_seq_part.bind("<<ComboboxSelected>>", self.on_select_seq_part)

        ttk.Label(part_bar, text="Step Len:").pack(side=tk.LEFT, padx=(4, 2))
        self.var_seq_len = tk.StringVar(value="64")
        ttk.Entry(part_bar, textvariable=self.var_seq_len, width=4).pack(side=tk.LEFT)
        ttk.Button(part_bar, text="Set Len", command=self.on_set_part_step_length).pack(side=tk.LEFT, padx=3)

        # 64-Step Table
        step_tbl_f = ttk.Frame(mid)
        step_tbl_f.pack(fill=tk.BOTH, expand=True, pady=2)
        s_cols = ("step", "notes", "vel", "gate", "prob")
        self.tree_steps = ttk.Treeview(step_tbl_f, columns=s_cols, show="headings", selectmode="extended", height=9)
        s_headers = {
            "step": ("Step", 42),
            "notes": ("Active Notes (up to 8 poly)", 160),
            "vel": ("Vel", 40),
            "gate": ("Gate", 40),
            "prob": ("Prob%", 45),
        }
        for c, (txt, w) in s_headers.items():
            self.tree_steps.heading(c, text=txt)
            self.tree_steps.column(c, width=w, minwidth=35, anchor=tk.W if c == "notes" else tk.CENTER)
        sb_s = ttk.Scrollbar(step_tbl_f, orient=tk.VERTICAL, command=self.tree_steps.yview)
        self.tree_steps.configure(yscrollcommand=sb_s.set)
        self.tree_steps.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_s.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_steps.bind("<<TreeviewSelect>>", self.on_select_step_row)

        # PART Copy/Paste section (Manual: [SHIFT]+[13] -> PART)
        part_cp = ttk.LabelFrame(mid, text="1. Copy/Paste PART Sequence ([SHIFT]+[13] -> PART)", padding=5)
        part_cp.pack(fill=tk.X, pady=3)

        p_row1 = ttk.Frame(part_cp)
        p_row1.pack(fill=tk.X, pady=2)
        ttk.Label(p_row1, text="Dest Pat (e.g. 1-16 or 16):").pack(side=tk.LEFT)
        self.var_cp_part_dst_pat = tk.StringVar(value="1-01")
        ttk.Entry(p_row1, textvariable=self.var_cp_part_dst_pat, width=6).pack(side=tk.LEFT, padx=3)
        ttk.Label(p_row1, text="Part:").pack(side=tk.LEFT, padx=(3, 2))
        self.var_cp_part_dst_part = tk.StringVar(value=self.part_names_list[0])
        ttk.Combobox(
            p_row1,
            textvariable=self.var_cp_part_dst_part,
            values=self.part_names_list,
            state="readonly",
            width=14,
        ).pack(side=tk.LEFT)

        self.var_cp_part_inc_tone = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            part_cp,
            text="Also copy Part Tone & Mixer (MSB/LSB/PC/Lvl/Pan)",
            variable=self.var_cp_part_inc_tone,
        ).pack(anchor=tk.W, pady=1)
        ttk.Button(part_cp, text="📋 Copy Selected Part Sequence -> Dest Pattern/Part", command=self.on_copy_part_content).pack(
            fill=tk.X, pady=2
        )

        # STEP & MULTI-STEP Copy/Paste section (Manual: [SHIFT]+[13] -> STEP / MULTI-STEP)
        step_cp = ttk.LabelFrame(mid, text="2. Copy/Paste STEP or MULTI-STEP ([SHIFT]+[13] -> STEP / MULTI-STEP)", padding=5)
        step_cp.pack(fill=tk.X, pady=2)

        s_row1 = ttk.Frame(step_cp)
        s_row1.pack(fill=tk.X, pady=2)
        ttk.Label(s_row1, text="Source Steps — Start (1-64):").pack(side=tk.LEFT)
        self.var_cp_step_start = tk.StringVar(value="1")
        ttk.Entry(s_row1, textvariable=self.var_cp_step_start, width=4).pack(side=tk.LEFT, padx=3)
        ttk.Label(s_row1, text="End (1-64):").pack(side=tk.LEFT, padx=(4, 2))
        self.var_cp_step_end = tk.StringVar(value="4")
        ttk.Entry(s_row1, textvariable=self.var_cp_step_end, width=4).pack(side=tk.LEFT, padx=3)

        s_row2 = ttk.Frame(step_cp)
        s_row2.pack(fill=tk.X, pady=2)
        ttk.Label(s_row2, text="Dest Pat:").pack(side=tk.LEFT)
        self.var_cp_step_dst_pat = tk.StringVar(value="1-01")
        ttk.Entry(s_row2, textvariable=self.var_cp_step_dst_pat, width=6).pack(side=tk.LEFT, padx=2)
        ttk.Label(s_row2, text="Part:").pack(side=tk.LEFT, padx=2)
        self.var_cp_step_dst_part = tk.StringVar(value=self.part_names_list[0])
        ttk.Combobox(
            s_row2,
            textvariable=self.var_cp_step_dst_part,
            values=self.part_names_list,
            state="readonly",
            width=12,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Label(s_row2, text="Dest Step:").pack(side=tk.LEFT, padx=2)
        self.var_cp_step_dst_step = tk.StringVar(value="5")
        ttk.Entry(s_row2, textvariable=self.var_cp_step_dst_step, width=4).pack(side=tk.LEFT)

        s_row3 = ttk.Frame(step_cp)
        s_row3.pack(fill=tk.X, pady=2)
        ttk.Button(s_row3, text="📋 Paste Step(s)", command=self.on_copy_steps_content).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2)
        )
        ttk.Button(s_row3, text="🧹 Clear Source Step(s)", command=self.on_clear_steps_content).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0)
        )

        # Right pane: Pattern Editor
        right = ttk.LabelFrame(pw, text="Selected Pattern & Tone Editor", padding=8)

        ttk.Label(right, text="Pattern Name (Max 16):").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.var_pat_name = tk.StringVar()
        ttk.Entry(right, textvariable=self.var_pat_name, width=18).grid(row=0, column=1, sticky=tk.W, pady=2)

        ttk.Label(right, text="Tempo (BPM):").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.var_pat_tempo = tk.StringVar()
        ttk.Entry(right, textvariable=self.var_pat_tempo, width=10).grid(row=1, column=1, sticky=tk.W, pady=2)

        ttk.Label(right, text="Pattern Level (0-127):").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.var_pat_level = tk.StringVar()
        ttk.Entry(right, textvariable=self.var_pat_level, width=10).grid(row=2, column=1, sticky=tk.W, pady=2)

        ttk.Separator(right, orient=tk.HORIZONTAL).grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(right, text="Part Sound & Mixer (MSB / LSB / PC / Lvl / Pan):", font=("Segoe UI", 9, "bold")).grid(
            row=4, column=0, columnspan=2, sticky=tk.W, pady=3
        )

        self.part_vars = []
        part_labels = ["Synth 1 (M08)", "Synth 2 (M09)", "Synth 3 (M11)", "Synth 4 (M12)", "Rhythm (M13)"]
        for p in range(5):
            frm = ttk.Frame(right)
            frm.grid(row=5 + p, column=0, columnspan=2, sticky=tk.W, pady=2)
            ttk.Label(frm, text=f"{part_labels[p]}:", width=12).pack(side=tk.LEFT)
            v_msb = tk.StringVar()
            v_lsb = tk.StringVar()
            v_pc = tk.StringVar()
            v_lvl = tk.StringVar()
            v_pan = tk.StringVar()
            for lbl, var, w in [("MSB", v_msb, 4), ("LSB", v_lsb, 4), ("PC", v_pc, 4), ("Lvl", v_lvl, 4), ("Pan", v_pan, 4)]:
                ttk.Label(frm, text=lbl).pack(side=tk.LEFT, padx=(2, 1))
                ttk.Entry(frm, textvariable=var, width=w).pack(side=tk.LEFT)
            self.part_vars.append((v_msb, v_lsb, v_pc, v_lvl, v_pan))

        ttk.Button(right, text="✅ Apply Pattern Changes", command=self.on_apply_pattern).grid(
            row=11, column=0, columnspan=2, sticky="ew", pady=8
        )

        ttk.Separator(right, orient=tk.HORIZONTAL).grid(row=12, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Label(right, text="Target Pattern (e.g. 1-16 or 16):").grid(row=13, column=0, sticky=tk.W, pady=2)
        self.var_pat_target = tk.StringVar(value="1-01")
        ttk.Entry(right, textvariable=self.var_pat_target, width=8).grid(row=13, column=1, sticky=tk.W, pady=2)
        ttk.Button(right, text="🔀 Swap Entire Pattern with Target", command=self.on_swap_pattern).grid(
            row=14, column=0, columnspan=2, sticky="ew", pady=2
        )
        ttk.Button(right, text="📋 Copy Entire Pattern to Target", command=self.on_copy_pattern).grid(
            row=15, column=0, columnspan=2, sticky="ew", pady=2
        )

        pw.add(left, minsize=220, width=430, stretch="always")
        pw.add(mid, minsize=300, width=430, stretch="always")
        pw.add(right, minsize=290, width=370, stretch="never")

    # ---------------- TAB 2: SYNTH PATCHES ----------------
    def _build_patches_tab(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="🎹 2. User Synth Patches & Sound Editor (256 Slots - PATc)")

        pw = tk.PanedWindow(tab, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED, bg="#b8b8b8")
        pw.pack(fill=tk.BOTH, expand=True)

        left = ttk.LabelFrame(pw, text="256 User Synth Patches (Drag Divider to Resize)", padding=4)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

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
            self.tree_patch.column(c, width=w, minwidth=40, anchor=tk.W if c in ("slot", "name", "osc_model") else tk.CENTER)

        sb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree_patch.yview)
        sb_x = ttk.Scrollbar(left, orient=tk.HORIZONTAL, command=self.tree_patch.xview)
        self.tree_patch.configure(yscrollcommand=sb.set, xscrollcommand=sb_x.set)
        self.tree_patch.grid(row=0, column=0, sticky="nsew")
        sb.grid(row=0, column=1, sticky="ns")
        sb_x.grid(row=1, column=0, sticky="ew")
        self.tree_patch.bind("<<TreeviewSelect>>", self.on_select_patch)

        right = ttk.LabelFrame(pw, text="Synth Patch Sound, Matrix & Deep Parameter Editor", padding=6)
        pw.add(left, minsize=280, width=640, stretch="always")
        pw.add(right, minsize=460, width=560, stretch="always")

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

        # Always-visible Patch Header (Name & OSC Model)
        g_frm = ttk.Frame(right)
        g_frm.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(g_frm, text="Patch Name:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Entry(g_frm, textvariable=self.var_patch_name, width=16).pack(side=tk.LEFT, padx=(4, 10))
        ttk.Label(g_frm, text="OSC Model:", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        self.cb_osc_model = ttk.Combobox(
            g_frm,
            textvariable=self.var_p_osc,
            values=[f"{k}: {v.split(': ')[1]}" for k, v in SH4dSVD.OSC_MODELS.items()],
            width=22,
            state="readonly",
        )
        self.cb_osc_model.pack(side=tk.LEFT, padx=4)
        self.cb_osc_model.bind("<<ComboboxSelected>>", self.on_osc_model_changed)

        # Sub-Notebook with 5 clean tabs inside the Right Panel
        self.nb_patch_sub = ttk.Notebook(right)
        self.nb_patch_sub.pack(fill=tk.BOTH, expand=True, pady=2)

        # --- SUB-TAB 1: MAIN (FILTER / ADSR / LFO) ---
        st_main = ttk.Frame(self.nb_patch_sub, padding=6)
        self.nb_patch_sub.add(st_main, text="🎛️ 1. Main")

        m_top = ttk.Frame(st_main)
        m_top.pack(fill=tk.X, pady=2)
        ttk.Label(m_top, text="Patch Level (0-127):").pack(side=tk.LEFT)
        ttk.Entry(m_top, textvariable=self.var_p_lvl, width=6).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Label(m_top, text="MFX Type (0-93):").pack(side=tk.LEFT)
        ttk.Entry(m_top, textvariable=self.var_p_mfx, width=6).pack(side=tk.LEFT, padx=4)

        ttk.Separator(st_main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        self.lbl_sliders_hdr = ttk.Label(st_main, text="OSC Mixer Sliders 1–4 (0..127):", font=("Segoe UI", 9, "bold"))
        self.lbl_sliders_hdr.pack(anchor=tk.W)
        s_frm = ttk.Frame(st_main)
        s_frm.pack(fill=tk.X, pady=2)
        self.lbl_slider_names = []
        for i, var in enumerate([self.var_p_s1, self.var_p_s2, self.var_p_s3, self.var_p_s4], start=1):
            lbl_s = ttk.Label(s_frm, text=f"S{i}:")
            lbl_s.pack(side=tk.LEFT, padx=(6 if i > 1 else 0, 2))
            self.lbl_slider_names.append(lbl_s)
            ttk.Entry(s_frm, textvariable=var, width=5).pack(side=tk.LEFT)

        ttk.Separator(st_main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        ttk.Label(st_main, text="Filter & Filter ADSR (0..1023):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        f_frm = ttk.Frame(st_main)
        f_frm.pack(fill=tk.X, pady=2)
        ttk.Label(f_frm, text="Cutoff:").pack(side=tk.LEFT)
        ttk.Entry(f_frm, textvariable=self.var_p_cutoff, width=6).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(f_frm, text="Reso:").pack(side=tk.LEFT)
        ttk.Entry(f_frm, textvariable=self.var_p_reso, width=6).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(f_frm, text="Env Dep:").pack(side=tk.LEFT)
        ttk.Entry(f_frm, textvariable=self.var_p_fenv, width=6).pack(side=tk.LEFT, padx=2)

        fadsr = ttk.Frame(st_main)
        fadsr.pack(fill=tk.X, pady=2)
        for lbl, var in [("F-Atk", self.var_p_fatk), ("F-Dec", self.var_p_fdec), ("F-Sus", self.var_p_fsus), ("F-Rel", self.var_p_frel)]:
            ttk.Label(fadsr, text=f"{lbl}:").pack(side=tk.LEFT, padx=(3, 1))
            ttk.Entry(fadsr, textvariable=var, width=5).pack(side=tk.LEFT)

        ttk.Separator(st_main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        ttk.Label(st_main, text="Amp Envelope ADSR (0..1023):", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        aadsr = ttk.Frame(st_main)
        aadsr.pack(fill=tk.X, pady=2)
        for lbl, var in [("A-Atk", self.var_p_aatk), ("A-Dec", self.var_p_adec), ("A-Sus", self.var_p_asus), ("A-Rel", self.var_p_arel)]:
            ttk.Label(aadsr, text=f"{lbl}:").pack(side=tk.LEFT, padx=(3, 1))
            ttk.Entry(aadsr, textvariable=var, width=5).pack(side=tk.LEFT)

        ttk.Separator(st_main, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=4)
        ttk.Label(st_main, text="LFO Rate & Modulation Depths:", font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        lfo_frm = ttk.Frame(st_main)
        lfo_frm.pack(fill=tk.X, pady=2)
        ttk.Label(lfo_frm, text="Shape (0-9):").pack(side=tk.LEFT)
        ttk.Entry(lfo_frm, textvariable=self.var_p_lshape, width=5).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(lfo_frm, text="Rate (0-1023):").pack(side=tk.LEFT)
        ttk.Entry(lfo_frm, textvariable=self.var_p_lrate, width=6).pack(side=tk.LEFT, padx=2)

        lfo_d = ttk.Frame(st_main)
        lfo_d.pack(fill=tk.X, pady=2)
        for lbl, var in [("Pitch Dep", self.var_p_lpitch), ("Filter Dep", self.var_p_lflt), ("Amp Dep", self.var_p_lamp)]:
            ttk.Label(lfo_d, text=f"{lbl}:").pack(side=tk.LEFT, padx=(3, 1))
            ttk.Entry(lfo_d, textvariable=var, width=5).pack(side=tk.LEFT)

        # --- SUB-TAB 2: OSC 1-4 & VOICING ([SHIFT]+[6] TONE) ---
        st_osc = ttk.Frame(self.nb_patch_sub, padding=6)
        self.nb_patch_sub.add(st_osc, text="🌊 2. OSC 1-4 & Voicing")

        v_lf = ttk.LabelFrame(st_osc, text="Tone Voicing & Portamento ([SHIFT]+[6] TONE)", padding=5)
        v_lf.pack(fill=tk.X, pady=(0, 6))

        self.var_p_cat = tk.StringVar()
        self.var_p_coarse = tk.StringVar()
        self.var_p_afeel = tk.StringVar()
        self.var_p_monopoly = tk.StringVar()
        self.var_p_legato = tk.StringVar()
        self.var_p_portasw = tk.StringVar()
        self.var_p_portatime = tk.StringVar()
        self.var_p_bendup = tk.StringVar()
        self.var_p_benddn = tk.StringVar()

        vr1 = ttk.Frame(v_lf)
        vr1.pack(fill=tk.X, pady=2)
        ttk.Label(vr1, text="Mono/Poly (0/1):").pack(side=tk.LEFT)
        ttk.Entry(vr1, textvariable=self.var_p_monopoly, width=4).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(vr1, text="Legato (0/1):").pack(side=tk.LEFT)
        ttk.Entry(vr1, textvariable=self.var_p_legato, width=4).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(vr1, text="Analog Feel (0-127):").pack(side=tk.LEFT)
        ttk.Entry(vr1, textvariable=self.var_p_afeel, width=5).pack(side=tk.LEFT, padx=2)

        vr2 = ttk.Frame(v_lf)
        vr2.pack(fill=tk.X, pady=2)
        ttk.Label(vr2, text="Porta Sw (0/1):").pack(side=tk.LEFT)
        ttk.Entry(vr2, textvariable=self.var_p_portasw, width=4).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(vr2, text="Porta Time (0-1023):").pack(side=tk.LEFT)
        ttk.Entry(vr2, textvariable=self.var_p_portatime, width=6).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(vr2, text="Category (0-44):").pack(side=tk.LEFT)
        ttk.Entry(vr2, textvariable=self.var_p_cat, width=4).pack(side=tk.LEFT, padx=2)

        vr3 = ttk.Frame(v_lf)
        vr3.pack(fill=tk.X, pady=2)
        ttk.Label(vr3, text="Coarse (-48..48):").pack(side=tk.LEFT)
        ttk.Entry(vr3, textvariable=self.var_p_coarse, width=5).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(vr3, text="Bend Up (0-48):").pack(side=tk.LEFT)
        ttk.Entry(vr3, textvariable=self.var_p_bendup, width=4).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(vr3, text="Bend Dn (0-48):").pack(side=tk.LEFT)
        ttk.Entry(vr3, textvariable=self.var_p_benddn, width=4).pack(side=tk.LEFT, padx=2)

        self.o_lf = ttk.LabelFrame(st_osc, text="Individual Oscillators 1–4 (0x720..0x7CF)", padding=5)
        self.o_lf.pack(fill=tk.BOTH, expand=True)

        self.lbl_osc_model_info = ttk.Label(
            self.o_lf,
            text="4 full oscillators active. Sliders 1–4 control OSC 1–4 mixer levels.",
            font=("Segoe UI", 8, "bold"),
        )
        self.lbl_osc_model_info.grid(row=0, column=0, columnspan=8, sticky=tk.W, pady=(0, 4))

        headers_o = ["OSC", "Wave ID", "Coarse", "Fine", "PW", "PWM", "Fat/Det", "Pan"]
        for col_i, h_txt in enumerate(headers_o):
            ttk.Label(self.o_lf, text=h_txt, font=("Segoe UI", 8, "bold")).grid(row=1, column=col_i, padx=3, pady=2)

        self.osc_deep_vars = []
        self.osc_row_widgets = []
        for o_i in range(4):
            lbl_o = ttk.Label(self.o_lf, text=f"OSC {o_i+1}:", font=("Segoe UI", 8, "bold"))
            lbl_o.grid(row=o_i + 2, column=0, padx=3, pady=3, sticky=tk.W)
            vw = tk.StringVar()
            vc = tk.StringVar()
            vf = tk.StringVar()
            vpw = tk.StringVar()
            vpwm = tk.StringVar()
            vfat = tk.StringVar()
            vpan = tk.StringVar()
            row_entries = []
            for col_i, v in enumerate([vw, vc, vf, vpw, vpwm, vfat, vpan], start=1):
                ent = ttk.Entry(self.o_lf, textvariable=v, width=6)
                ent.grid(row=o_i + 2, column=col_i, padx=2, pady=3)
                row_entries.append(ent)
            self.osc_deep_vars.append((vw, vc, vf, vpw, vpwm, vfat, vpan))
            self.osc_row_widgets.append((lbl_o, row_entries))

        self.lbl_osc_wave_help = ttk.Label(
            self.o_lf,
            text="Wave IDs: 1=SAW, 2=SQR, 3=TRI, 4=SINE, 5=RAMP, 6=JUNO, 7=TRI2, 10=SuperSAW, 11=NOISE",
            font=("Segoe UI", 7),
        )
        self.lbl_osc_wave_help.grid(row=7, column=0, columnspan=8, sticky=tk.W, pady=(6, 0))

        # --- SUB-TAB 3: MODULATION MATRIX (4 SLOTS) ---
        st_mtx = ttk.Frame(self.nb_patch_sub, padding=6)
        self.nb_patch_sub.add(st_mtx, text="🕸️ 3. Matrix")

        ttk.Label(
            st_mtx,
            text="4-Slot Modulation Matrix ([SHIFT]+[7] MATRIX — 1 Source -> 4 Destinations & Depths -63..+63):",
            font=("Segoe UI", 8, "bold"),
        ).pack(anchor=tk.W, pady=(0, 4))

        self.mtx_vars = []
        for sl in range(4):
            slf = ttk.LabelFrame(st_mtx, text=f"Matrix Slot {sl+1} (0x{0x6F0 + sl*12:03X})", padding=4)
            slf.pack(fill=tk.X, pady=2)
            v_src = tk.StringVar()
            row_top = ttk.Frame(slf)
            row_top.pack(fill=tk.X)
            ttk.Label(row_top, text="Source ID:").pack(side=tk.LEFT)
            ttk.Entry(row_top, textvariable=v_src, width=5).pack(side=tk.LEFT, padx=(2, 6))
            ttk.Label(
                row_top,
                text="(0=LFO, 52=PEnv, 94=Bend, 95=Aft, 96=ModWhl, 98=Vel, 100=FEnv, 102=OFF)",
                font=("Segoe UI", 7),
            ).pack(side=tk.LEFT)

            row_d = ttk.Frame(slf)
            row_d.pack(fill=tk.X, pady=(2, 0))
            dst_dep_pairs = []
            for d_i in range(1, 5):
                vd = tk.StringVar()
                vp = tk.StringVar()
                ttk.Label(row_d, text=f"D{d_i}:").pack(side=tk.LEFT, padx=(4 if d_i > 1 else 0, 1))
                ttk.Entry(row_d, textvariable=vd, width=4).pack(side=tk.LEFT)
                ttk.Label(row_d, text="Dep:").pack(side=tk.LEFT, padx=(2, 1))
                ttk.Entry(row_d, textvariable=vp, width=4).pack(side=tk.LEFT)
                dst_dep_pairs.append((vd, vp))
            self.mtx_vars.append((v_src, dst_dep_pairs))

        ttk.Label(
            st_mtx,
            text="Common Dest IDs: 0=OFF, 3=Pitch, 4=OSC2 Pitch, 6=Cutoff, 7=Reso, 12=LFO Rate, 17..19=OSC1..3 PW, 28=Pan",
            font=("Segoe UI", 7),
        ).pack(anchor=tk.W, pady=(2, 0))

        # --- SUB-TAB 4: MFX PARAMETERS ---
        st_mfx = ttk.Frame(self.nb_patch_sub, padding=6)
        self.nb_patch_sub.add(st_mfx, text="✨ 4. MFX")

        mfx_top = ttk.LabelFrame(st_mfx, text="Tone MFX Common (0x050..0x053)", padding=5)
        mfx_top.pack(fill=tk.X, pady=(0, 4))
        self.var_p_mfx_sw = tk.StringVar()
        self.var_p_mfx_cho = tk.StringVar()
        self.var_p_mfx_rev = tk.StringVar()

        ttk.Label(mfx_top, text="MFX Type (0-93):").grid(row=0, column=0, sticky=tk.W, padx=2, pady=2)
        ttk.Entry(mfx_top, textvariable=self.var_p_mfx, width=6).grid(row=0, column=1, padx=4, pady=2)
        ttk.Label(mfx_top, text="Switch (0/1):").grid(row=0, column=2, sticky=tk.W, padx=6, pady=2)
        ttk.Entry(mfx_top, textvariable=self.var_p_mfx_sw, width=5).grid(row=0, column=3, padx=4, pady=2)
        ttk.Label(mfx_top, text="Chorus Send:").grid(row=1, column=0, sticky=tk.W, padx=2, pady=2)
        ttk.Entry(mfx_top, textvariable=self.var_p_mfx_cho, width=6).grid(row=1, column=1, padx=4, pady=2)
        ttk.Label(mfx_top, text="Reverb Send:").grid(row=1, column=2, sticky=tk.W, padx=6, pady=2)
        ttk.Entry(mfx_top, textvariable=self.var_p_mfx_rev, width=5).grid(row=1, column=3, padx=4, pady=2)

        mfx_p_lf = ttk.LabelFrame(st_mfx, text="MFX Algorithm Internal Parameters 1–16 (0x060..0x07F)", padding=5)
        mfx_p_lf.pack(fill=tk.BOTH, expand=True)
        self.mfx_param_vars = []
        for i in range(16):
            r_i = i // 4
            c_i = (i % 4) * 2
            v_mp = tk.StringVar()
            ttk.Label(mfx_p_lf, text=f"P{i+1:02d}:").grid(row=r_i, column=c_i, sticky=tk.E, padx=(6, 2), pady=3)
            ttk.Entry(mfx_p_lf, textvariable=v_mp, width=6).grid(row=r_i, column=c_i + 1, sticky=tk.W, padx=2, pady=3)
            self.mfx_param_vars.append(v_mp)

        # --- SUB-TAB 5: SEARCHABLE ALL PARAMETERS TABLE ---
        st_search = ttk.Frame(self.nb_patch_sub, padding=6)
        self.nb_patch_sub.add(st_search, text="🔍 5. Search All")

        s_bar = ttk.Frame(st_search)
        s_bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(s_bar, text="🔍 Search:").pack(side=tk.LEFT)
        self.var_param_search = tk.StringVar()
        self.var_param_search.trace_add("write", lambda *_: self.refresh_patch_search_table())
        ttk.Entry(s_bar, textvariable=self.var_param_search, width=18).pack(side=tk.LEFT, padx=4)

        ttk.Label(s_bar, text="Category:").pack(side=tk.LEFT, padx=(6, 2))
        self.var_param_cat_filter = tk.StringVar(value="All")
        cb_cat = ttk.Combobox(
            s_bar,
            textvariable=self.var_param_cat_filter,
            values=["All", "Voicing & Common", "OSC 1-4", "Filter & ADSR", "LFO", "Matrix", "MFX"],
            state="readonly",
            width=15,
        )
        cb_cat.pack(side=tk.LEFT)
        cb_cat.bind("<<ComboboxSelected>>", lambda _e: self.refresh_patch_search_table())

        tbl_f = ttk.Frame(st_search)
        tbl_f.pack(fill=tk.BOTH, expand=True)
        p_cols = ("cat", "name", "off", "val", "rng")
        self.tree_param_search = ttk.Treeview(tbl_f, columns=p_cols, show="headings", selectmode="browse", height=8)
        for c, (t, w) in [
            ("cat", ("Category", 95)),
            ("name", ("Parameter Name", 185)),
            ("off", ("Offset", 50)),
            ("val", ("Value", 55)),
            ("rng", ("Range", 70)),
        ]:
            self.tree_param_search.heading(c, text=t)
            self.tree_param_search.column(c, width=w, minwidth=35, anchor=tk.W if c in ("cat", "name") else tk.CENTER)
        sb_ps = ttk.Scrollbar(tbl_f, orient=tk.VERTICAL, command=self.tree_param_search.yview)
        self.tree_param_search.configure(yscrollcommand=sb_ps.set)
        self.tree_param_search.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_ps.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_param_search.bind("<<TreeviewSelect>>", self.on_select_search_param)

        edit_bar = ttk.Frame(st_search, padding=(0, 4, 0, 0))
        edit_bar.pack(fill=tk.X)
        self.lbl_search_sel = ttk.Label(edit_bar, text="Select a parameter:", width=26, font=("Segoe UI", 8, "bold"))
        self.lbl_search_sel.pack(side=tk.LEFT)
        self.var_search_edit_val = tk.StringVar()
        ent_sv = ttk.Entry(edit_bar, textvariable=self.var_search_edit_val, width=8)
        ent_sv.pack(side=tk.LEFT, padx=4)
        ent_sv.bind("<Return>", lambda _e: self.on_apply_search_param())
        ttk.Button(edit_bar, text="✏️ Set Value", command=self.on_apply_search_param).pack(side=tk.LEFT, padx=2)

        # Always-visible Bottom Action Bar
        ttk.Button(right, text="✅ Apply All Sound, Matrix & MFX Parameters to .SVD Patch", command=self.on_rename_patch).pack(fill=tk.X, pady=(4, 2))
        live_row = ttk.Frame(right)
        live_row.pack(fill=tk.X, pady=2)
        ttk.Button(live_row, text="⚡ Load Patch Live (MIDI PC)", command=self.on_live_load_selected_patch).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        ttk.Button(live_row, text="⚡ Push Sliders Live (MIDI CC)", command=self.on_live_push_patch_ccs).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=3)
        act_frm = ttk.Frame(right)
        act_frm.pack(fill=tk.X)
        ttk.Label(act_frm, text="Target Slot (1..256):").pack(side=tk.LEFT)
        self.var_patch_target = tk.StringVar(value="1")
        ttk.Entry(act_frm, textvariable=self.var_patch_target, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Button(act_frm, text="🔀 Swap", command=self.on_swap_patch).pack(side=tk.LEFT, padx=2)
        ttk.Button(act_frm, text="📋 Copy", command=self.on_copy_patch).pack(side=tk.LEFT, padx=2)
        ttk.Button(act_frm, text="📤 Export", command=self.on_export_patch).pack(side=tk.LEFT, padx=2)
        ttk.Button(act_frm, text="📥 Import", command=self.on_import_patch).pack(side=tk.LEFT, padx=2)

        gen_quick_row = ttk.Frame(right)
        gen_quick_row.pack(fill=tk.X, pady=(4, 0))
        ttk.Button(
            gen_quick_row,
            text="🎲 Mutate Selected (20%)",
            command=self.on_quick_mutate_patch,
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 2))
        ttk.Button(
            gen_quick_row,
            text="✨ Smart Randomize Slot",
            command=self.on_quick_randomize_patch,
        ).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(2, 0))
        ttk.Button(
            gen_quick_row,
            text="🧪 Open Generator Lab ->",
            command=lambda: self.nb.select(4),
        ).pack(side=tk.LEFT, padx=(4, 0))

    # ---------------- TAB 3: RHYTHM KITS & DRUM PITCH EDITOR ----------------
    def _build_rhythm_tab(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="🥁 3. Rhythm Kits & Drum Pitch/Filter Editor (RHYa + RHIa)")

        pw = tk.PanedWindow(tab, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED, bg="#b8b8b8")
        pw.pack(fill=tk.BOTH, expand=True)

        # Left: 64 Rhythm Kits
        kit_frame = ttk.LabelFrame(pw, text="64 User Rhythm Kits (MSB=86, LSB=0)", padding=6)

        self.tree_kit = ttk.Treeview(kit_frame, columns=("num", "name", "lvl"), show="headings", selectmode="browse")
        self.tree_kit.heading("num", text="Kit #")
        self.tree_kit.column("num", width=50)
        self.tree_kit.heading("name", text="Kit Name")
        self.tree_kit.column("name", width=125)
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
        mid_frame = ttk.LabelFrame(pw, text="26 Drum Instruments in Selected Kit (MIDI Note 36 C2 .. 61 C#4)", padding=6)
        mid_frame.rowconfigure(0, weight=1)
        mid_frame.columnconfigure(0, weight=1)

        d_cols = ("key", "note", "label", "pitch", "level", "pan", "cutoff", "reso", "decay", "wave")
        self.tree_drum = ttk.Treeview(mid_frame, columns=d_cols, show="headings", selectmode="browse")
        d_headers = {
            "key": ("#", 35),
            "note": ("Note", 65),
            "label": ("Instrument", 140),
            "pitch": ("Pitch (Semitones)", 100),
            "level": ("Level", 50),
            "pan": ("Pan", 50),
            "cutoff": ("Cutoff (0-1023)", 90),
            "reso": ("Reso", 50),
            "decay": ("Decay (0-1023)", 90),
            "wave": ("Wave ID", 60),
        }
        for c, (txt, w) in d_headers.items():
            self.tree_drum.heading(c, text=txt)
            self.tree_drum.column(c, width=w, minwidth=35, anchor=tk.CENTER if c != "label" else tk.W)

        sb_d = ttk.Scrollbar(mid_frame, orient=tk.VERTICAL, command=self.tree_drum.yview)
        sb_dx = ttk.Scrollbar(mid_frame, orient=tk.HORIZONTAL, command=self.tree_drum.xview)
        self.tree_drum.configure(yscrollcommand=sb_d.set, xscrollcommand=sb_dx.set)
        self.tree_drum.grid(row=0, column=0, sticky="nsew")
        sb_d.grid(row=0, column=1, sticky="ns")
        sb_dx.grid(row=1, column=0, sticky="ew")
        self.tree_drum.bind("<<TreeviewSelect>>", self.on_select_drum_key)

        # Right: Selected Drum Instrument Parameter Editor
        d_edit = ttk.LabelFrame(pw, text="Selected Drum Sound (Pitch / Filter / Mixer)", padding=8)

        pw.add(kit_frame, minsize=220, width=250, stretch="never")
        pw.add(mid_frame, minsize=350, width=620, stretch="always")
        pw.add(d_edit, minsize=280, width=330, stretch="never")

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
        if hasattr(self, "cb_pc_pat"):
            self.refresh_pattern_creator_tab()

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
        else:
            self.tree_pat.selection_set("0")
            self.on_select_pattern(None)

    def get_selected_seq_part_idx(self) -> int:
        raw = self.var_seq_part.get().split(":")[0].strip()
        return max(0, min(4, int(raw) - 1)) if raw.isdigit() else 0

    def refresh_steps_for_pattern_part(self):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        pat_idx = int(sel[0])
        part_idx = self.get_selected_seq_part_idx()
        step_len = self.svd.get_part_step_length(pat_idx, part_idx)
        self.var_seq_len.set(str(step_len))

        prev_sel = self.tree_steps.selection()
        self.tree_steps.delete(*self.tree_steps.get_children())
        for s in range(64):
            st = self.svd.get_step_info(pat_idx, part_idx, s)
            step_lbl = f"{st['step']:02d}" + (" *" if st["notes"] else "")
            self.tree_steps.insert(
                "",
                tk.END,
                iid=str(s),
                values=(
                    step_lbl,
                    st["note_names"],
                    st["vel"] if st["notes"] else "—",
                    st["gate"] if st["notes"] else "—",
                    f"{st['prob']}%" if st["notes"] else "—",
                ),
            )
        if prev_sel:
            self.tree_steps.selection_set(prev_sel)

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

    def parse_pattern_slot(self, val_str: str) -> int:
        """Accepts either '1-16' (Bank 1..8 - Num 1..16) or '16' (1..128) and returns 0..127 index."""
        s = val_str.strip()
        if "-" in s:
            parts = s.split("-", 1)
            if parts[0].strip().isdigit() and parts[1].strip().isdigit():
                bank = max(1, min(8, int(parts[0].strip())))
                num = max(1, min(16, int(parts[1].strip())))
                return (bank - 1) * 16 + (num - 1)
        if s.isdigit():
            return max(0, min(127, int(s) - 1))
        return 0

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
        self.var_cp_part_dst_pat.set(info["slot"])
        self.var_cp_step_dst_pat.set(info["slot"])
        self.refresh_steps_for_pattern_part()

    def on_select_seq_part(self, _event=None):
        self.var_cp_part_dst_part.set(self.var_seq_part.get())
        self.var_cp_step_dst_part.set(self.var_seq_part.get())
        self.refresh_steps_for_pattern_part()

    def on_select_step_row(self, _event=None):
        sel = self.tree_steps.selection()
        if not sel:
            return
        steps_1_64 = sorted(int(x) + 1 for x in sel)
        if len(steps_1_64) > 1:
            self.var_cp_step_start.set(str(steps_1_64[0]))
            self.var_cp_step_end.set(str(steps_1_64[-1]))
        else:
            s_start = steps_1_64[0]
            self.var_cp_step_start.set(str(s_start))
            try:
                cur_end = int(self.var_cp_step_end.get())
            except ValueError:
                cur_end = s_start
            if cur_end < s_start:
                self.var_cp_step_end.set(str(s_start))

    def on_set_part_step_length(self):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        pat_idx = int(sel[0])
        part_idx = self.get_selected_seq_part_idx()
        self.svd.set_part_step_length(pat_idx, part_idx, int(self.var_seq_len.get()))
        self.refresh_steps_for_pattern_part()

    def on_copy_part_content(self):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        src_pat = int(sel[0])
        src_part = self.get_selected_seq_part_idx()
        dst_pat = self.parse_pattern_slot(self.var_cp_part_dst_pat.get())
        raw_dst_p = self.var_cp_part_dst_part.get().split(":")[0].strip()
        dst_part = max(0, min(4, int(raw_dst_p) - 1)) if raw_dst_p.isdigit() else src_part
        inc_tone = bool(self.var_cp_part_inc_tone.get())

        self.svd.copy_part_content(src_pat, src_part, dst_pat, dst_part, include_tone=inc_tone)
        self.refresh_patterns()
        self.refresh_steps_for_pattern_part()
        src_slot = f"{(src_pat // 16) + 1}-{(src_pat % 16) + 1:02d}"
        dst_slot = f"{(dst_pat // 16) + 1}-{(dst_pat % 16) + 1:02d}"
        messagebox.showinfo(
            "Part Copied",
            f"Copied Pattern {src_slot} Part {src_part+1} -> Pattern {dst_slot} Part {dst_part+1}\n"
            f"(Tone/Mixer included: {'Yes' if inc_tone else 'No - Sequence Only'})",
        )

    def on_copy_steps_content(self):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        src_pat = int(sel[0])
        src_part = self.get_selected_seq_part_idx()
        s_start = int(self.var_cp_step_start.get())
        s_end = int(self.var_cp_step_end.get())
        dst_pat = self.parse_pattern_slot(self.var_cp_step_dst_pat.get())
        raw_dst_p = self.var_cp_step_dst_part.get().split(":")[0].strip()
        dst_part = max(0, min(4, int(raw_dst_p) - 1)) if raw_dst_p.isdigit() else src_part
        dst_step = int(self.var_cp_step_dst_step.get())

        copied = self.svd.copy_steps_content(
            src_pat, src_part, s_start, s_end, dst_pat, dst_part, dst_step
        )
        # Auto-expand destination part step length if pasted steps exceed current length
        end_pasted_step = min(64, dst_step + copied - 1)
        cur_len = self.svd.get_part_step_length(dst_pat, dst_part)
        if end_pasted_step > cur_len:
            self.svd.set_part_step_length(dst_pat, dst_part, end_pasted_step)

        self.refresh_steps_for_pattern_part()
        # Highlight and scroll to the newly pasted steps if viewing the destination pattern/part
        if dst_pat == src_pat and dst_part == src_part:
            pasted_iids = [str(s) for s in range(dst_step - 1, end_pasted_step)]
            if pasted_iids:
                self.tree_steps.selection_set(pasted_iids)
                self.tree_steps.see(pasted_iids[0])

        src_slot = f"{(src_pat // 16) + 1}-{(src_pat % 16) + 1:02d}"
        dst_slot = f"{(dst_pat // 16) + 1}-{(dst_pat % 16) + 1:02d}"
        mode_lbl = "STEP" if copied == 1 else f"MULTI-STEP ({copied} steps)"
        messagebox.showinfo(
            "Steps Copied",
            f"[{mode_lbl}] Copied Pat {src_slot} Part {src_part+1} Steps {s_start}..{s_start+copied-1}\n"
            f"-> Pat {dst_slot} Part {dst_part+1} Steps {dst_step}..{end_pasted_step}.",
        )

    def on_clear_steps_content(self):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        src_pat = int(sel[0])
        src_part = self.get_selected_seq_part_idx()
        s_start = int(self.var_cp_step_start.get())
        s_end = int(self.var_cp_step_end.get())
        self.svd.clear_steps_content(src_pat, src_part, s_start, s_end)
        self.refresh_steps_for_pattern_part()

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
        idx2 = self.parse_pattern_slot(self.var_pat_target.get())
        self.svd.swap_patterns(idx1, idx2)
        self.refresh_patterns()

    def on_copy_pattern(self):
        sel = self.tree_pat.selection()
        if not sel or not self.svd:
            return
        idx1 = int(sel[0])
        idx2 = self.parse_pattern_slot(self.var_pat_target.get())
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
        self.var_p_mfx_sw.set(str(pr["mfx_sw"]))
        self.var_p_mfx_cho.set(str(pr["mfx_cho"]))
        self.var_p_mfx_rev.set(str(pr["mfx_rev"]))
        for i, v_mp in enumerate(self.mfx_param_vars):
            v_mp.set(str(pr["mfx_params"][i]))

        # Voicing
        self.var_p_cat.set(str(pr["category"]))
        self.var_p_coarse.set(str(pr["coarse_tune"]))
        self.var_p_afeel.set(str(pr["analog_feel"]))
        self.var_p_monopoly.set(str(pr["mono_poly"]))
        self.var_p_legato.set(str(pr["legato_sw"]))
        self.var_p_portasw.set(str(pr["porta_sw"]))
        self.var_p_portatime.set(str(pr["porta_time"]))
        self.var_p_bendup.set(str(pr["bend_up"]))
        self.var_p_benddn.set(str(pr["bend_down"]))

        # OSC 1-4
        for o_i, (vw, vc, vf, vpw, vpwm, vfat, vpan) in enumerate(self.osc_deep_vars):
            od = pr["oscs"][o_i]
            vw.set(str(od["wave"]))
            vc.set(str(od["coarse"]))
            vf.set(str(od["fine"]))
            vpw.set(str(od["pw"]))
            vpwm.set(str(od["pwm"]))
            vfat.set(str(od["fat"]))
            vpan.set(str(od["pan"]))

        # Matrix 1-4
        for sl, (v_src, dst_dep_pairs) in enumerate(self.mtx_vars):
            md = pr["matrix"][sl]
            v_src.set(str(md["src"]))
            for d_i, (vd, vp) in enumerate(dst_dep_pairs, start=1):
                vd.set(str(md[f"dst{d_i}"]))
                vp.set(str(md[f"dep{d_i}"]))

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
        self.on_osc_model_changed()

    def _get_selected_osc_model_id(self) -> int:
        osc_str = self.var_p_osc.get().split(":")[0].strip()
        return int(osc_str) if osc_str.isdigit() else 16

    def on_osc_model_changed(self, _event=None):
        """Dynamically updates Slider 1-4 labels, Sub-Tab 2 Oscillator count/rows, and Search table for the selected OSC Model."""
        model_id = self._get_selected_osc_model_id()
        spec = SH4dSVD.OSC_MODEL_SPECS.get(model_id, SH4dSVD.OSC_MODEL_SPECS[16])

        # 1. Update Slider 1-4 labels in Sub-Tab 1 (Main)
        for i, lbl_w in enumerate(self.lbl_slider_names):
            lbl_w.config(text=spec["sliders"][i])

        # 2. Update Sub-Tab 2 tab label, frame title, info banner & visible oscillator rows
        active_n = spec["active_oscs"]
        self.nb_patch_sub.tab(1, text=f"🌊 2. OSC ({active_n}-OSC) & Voicing")
        self.o_lf.config(text=spec["title"])
        self.lbl_osc_model_info.config(text=spec["info"])

        for o_i, (lbl_o, row_entries) in enumerate(self.osc_row_widgets):
            if o_i < active_n:
                lbl_o.config(text=spec["osc_names"][o_i])
                lbl_o.grid(row=o_i + 2, column=0, padx=3, pady=3, sticky=tk.W)
                for col_i, ent in enumerate(row_entries, start=1):
                    ent.grid(row=o_i + 2, column=col_i, padx=2, pady=3)
            else:
                lbl_o.grid_remove()
                for ent in row_entries:
                    ent.grid_remove()

        # 3. Refresh Search All table with the selected OSC Model's active oscillators and slider names
        self.refresh_patch_search_table()

    def refresh_patch_search_table(self):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        q = self.var_param_search.get().strip().lower()
        cat_f = self.var_param_cat_filter.get()
        rows = self.svd.get_patch_searchable_list(idx, override_model=self._get_selected_osc_model_id())
        prev = self.tree_param_search.selection()
        self.tree_param_search.delete(*self.tree_param_search.get_children())
        for key, cat, name, off_hex, val, rng in rows:
            if cat_f != "All" and cat != cat_f:
                continue
            if q and (q not in name.lower() and q not in cat.lower() and q not in off_hex.lower()):
                continue
            self.tree_param_search.insert("", tk.END, iid=key, values=(cat, name, off_hex, val, rng))
        if prev and self.tree_param_search.exists(prev[0]):
            self.tree_param_search.selection_set(prev[0])

    def on_select_search_param(self, _event=None):
        sel = self.tree_param_search.selection()
        if not sel:
            return
        key = sel[0]
        vals = self.tree_param_search.item(key, "values")
        self.lbl_search_sel.config(text=f"{vals[1]} ({vals[4]}):")
        self.var_search_edit_val.set(str(vals[3]))

    def on_apply_search_param(self):
        psel = self.tree_patch.selection()
        ssel = self.tree_param_search.selection()
        if not psel or not ssel or not self.svd:
            return
        key = ssel[0]
        new_val = int(self.var_search_edit_val.get())
        # Map searchable key back to the corresponding GUI variable and apply
        direct_var_map = {
            "patch_level": self.var_p_lvl,
            "mfx_type": self.var_p_mfx,
            "mfx_sw": self.var_p_mfx_sw,
            "mfx_cho": self.var_p_mfx_cho,
            "mfx_rev": self.var_p_mfx_rev,
            "category": self.var_p_cat,
            "coarse_tune": self.var_p_coarse,
            "analog_feel": self.var_p_afeel,
            "mono_poly": self.var_p_monopoly,
            "legato_sw": self.var_p_legato,
            "porta_sw": self.var_p_portasw,
            "porta_time": self.var_p_portatime,
            "bend_up": self.var_p_bendup,
            "bend_down": self.var_p_benddn,
            "slider1": self.var_p_s1,
            "slider2": self.var_p_s2,
            "slider3": self.var_p_s3,
            "slider4": self.var_p_s4,
            "cutoff": self.var_p_cutoff,
            "resonance": self.var_p_reso,
            "flt_env_depth": self.var_p_fenv,
            "flt_atk": self.var_p_fatk,
            "flt_dec": self.var_p_fdec,
            "flt_sus": self.var_p_fsus,
            "flt_rel": self.var_p_frel,
            "amp_atk": self.var_p_aatk,
            "amp_dec": self.var_p_adec,
            "amp_sus": self.var_p_asus,
            "amp_rel": self.var_p_arel,
            "lfo_shape": self.var_p_lshape,
            "lfo_rate": self.var_p_lrate,
            "lfo_pitch": self.var_p_lpitch,
            "lfo_flt": self.var_p_lflt,
            "lfo_amp": self.var_p_lamp,
        }
        if key == "osc_model":
            lbl = SH4dSVD.OSC_MODELS.get(new_val, f"{new_val}: Model")
            self.var_p_osc.set(lbl)
            self.on_osc_model_changed()
        elif key in direct_var_map:
            direct_var_map[key].set(str(new_val))
        elif key.startswith("osc") and "_" in key:
            o_idx = int(key[3]) - 1
            sub = key.split("_", 1)[1]
            sub_idx = {"wave": 0, "coarse": 1, "fine": 2, "pw": 3, "pwm": 4, "fat": 5, "pan": 6}[sub]
            self.osc_deep_vars[o_idx][sub_idx].set(str(new_val))
        elif key.startswith("mtx") and "_" in key:
            sl_idx = int(key[3]) - 1
            sub = key.split("_", 1)[1]
            v_src, pairs = self.mtx_vars[sl_idx]
            if sub == "src":
                v_src.set(str(new_val))
            elif sub.startswith("dst"):
                d_i = int(sub[3]) - 1
                pairs[d_i][0].set(str(new_val))
            elif sub.startswith("dep"):
                d_i = int(sub[3]) - 1
                pairs[d_i][1].set(str(new_val))
        elif key.startswith("mfx_p"):
            p_i = int(key[5:]) - 1
            self.mfx_param_vars[p_i].set(str(new_val))
        self.on_rename_patch()

    def on_rename_patch(self):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        osc_str = self.var_p_osc.get().split(":")[0].strip()
        osc_id = int(osc_str) if osc_str.isdigit() else None

        oscs_payload = []
        for vw, vc, vf, vpw, vpwm, vfat, vpan in self.osc_deep_vars:
            oscs_payload.append(
                {
                    "wave": int(vw.get()),
                    "coarse": int(vc.get()),
                    "fine": int(vf.get()),
                    "pw": int(vpw.get()),
                    "pwm": int(vpwm.get()),
                    "fat": int(vfat.get()),
                    "pan": int(vpan.get()),
                }
            )

        mtx_payload = []
        for v_src, pairs in self.mtx_vars:
            md = {"src": int(v_src.get())}
            for d_i, (vd, vp) in enumerate(pairs, start=1):
                md[f"dst{d_i}"] = int(vd.get())
                md[f"dep{d_i}"] = int(vp.get())
            mtx_payload.append(md)

        mfx_p_payload = [int(v.get()) for v in self.mfx_param_vars]

        self.svd.set_patch_params(
            idx,
            name=self.var_patch_name.get(),
            osc_model=osc_id,
            patch_level=int(self.var_p_lvl.get()),
            mfx_type=int(self.var_p_mfx.get()),
            mfx_sw=int(self.var_p_mfx_sw.get()),
            mfx_cho=int(self.var_p_mfx_cho.get()),
            mfx_rev=int(self.var_p_mfx_rev.get()),
            mfx_params=mfx_p_payload,
            category=int(self.var_p_cat.get()),
            coarse_tune=int(self.var_p_coarse.get()),
            analog_feel=int(self.var_p_afeel.get()),
            mono_poly=int(self.var_p_monopoly.get()),
            legato_sw=int(self.var_p_legato.get()),
            porta_sw=int(self.var_p_portasw.get()),
            porta_time=int(self.var_p_portatime.get()),
            bend_up=int(self.var_p_bendup.get()),
            bend_down=int(self.var_p_benddn.get()),
            oscs=oscs_payload,
            matrix=mtx_payload,
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
        self.on_osc_model_changed()

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

    # ---------------- TAB 5: PRESET GENERATOR, MUTATOR & MATH WAVE/STEP LAB ----------------
    def _build_generator_tab(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="🎲 5. Preset Generator & Mutator Lab")

        pw = tk.PanedWindow(tab, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED, bg="#b8b8b8")
        pw.pack(fill=tk.BOTH, expand=True)

        # --- LEFT PANE: SMART CATEGORY / GENRE PRESET & BATCH BANK GENERATOR ---
        left = ttk.LabelFrame(pw, text="✨ 1. Smart Genre Preset & Batch Bank Generator", padding=8)

        ttk.Label(
            left,
            text="Synthesizes musical SH-4d patches (OSC 1–4, Filter/Amp ADSR, LFO, Matrix & MFX)\ninto .SVD memory without overwriting active slots unless you choose to.",
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, pady=(0, 8))

        r_g = ttk.Frame(left)
        r_g.pack(fill=tk.X, pady=3)
        ttk.Label(r_g, text="Sound Style / Genre:", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        self.var_gen_genre = tk.StringVar(value="Acid 303 Bass")
        self.gen_genres_list = [
            "Acid 303 Bass",
            "Reese / Neuro Bass",
            "Warm Analog Pad",
            "Lush Chord / Strings",
            "Pluck / Arpeggio",
            "Dub Techno Chord Stab",
            "Cyberpunk / Sync Lead",
            "FM / Metallic Bell",
            "Custom Drawn Wave (DRAWING)",
            "Rhythmic Step-Mod (STEP)",
            "🎲 Mixed / Surprise Me",
        ]
        ttk.Combobox(
            r_g,
            textvariable=self.var_gen_genre,
            values=self.gen_genres_list,
            state="readonly",
            width=26,
        ).pack(side=tk.LEFT, padx=6)

        # Single Preset Generation Box
        s_lf = ttk.LabelFrame(left, text="Single Patch Generation", padding=6)
        s_lf.pack(fill=tk.X, pady=6)

        rs1 = ttk.Frame(s_lf)
        rs1.pack(fill=tk.X, pady=2)
        ttk.Label(rs1, text="Target User Slot (1..256):").pack(side=tk.LEFT)
        self.var_gen_single_slot = tk.StringVar(value="36")
        ttk.Spinbox(rs1, from_=1, to=256, textvariable=self.var_gen_single_slot, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Button(rs1, text="🔍 Find First INIT Slot", command=self.on_find_next_init_slot).pack(side=tk.LEFT, padx=4)

        rs2 = ttk.Frame(s_lf)
        rs2.pack(fill=tk.X, pady=3)
        ttk.Label(rs2, text="Custom Name (optional):").pack(side=tk.LEFT)
        self.var_gen_custom_name = tk.StringVar(value="")
        ttk.Entry(rs2, textvariable=self.var_gen_custom_name, width=18).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            s_lf,
            text="✨ Generate Smart Preset into Target Slot",
            command=self.on_gen_single_preset,
        ).pack(fill=tk.X, pady=(4, 2))
        ttk.Button(
            s_lf,
            text="💾 Generate & Export Directly as .sh4d_patch File...",
            command=self.on_gen_and_export_file,
        ).pack(fill=tk.X, pady=2)

        # Batch Bank Generation Box
        b_lf = ttk.LabelFrame(left, text="📦 Batch Bank Generator (Fill 8 or 16 Slots at Once)", padding=6)
        b_lf.pack(fill=tk.X, pady=6)

        rb1 = ttk.Frame(b_lf)
        rb1.pack(fill=tk.X, pady=2)
        ttk.Label(rb1, text="Start Slot (1..256):").pack(side=tk.LEFT)
        self.var_gen_bank_start = tk.StringVar(value="49")
        ttk.Spinbox(rb1, from_=1, to=256, textvariable=self.var_gen_bank_start, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Label(rb1, text="(e.g. 49 = U04-01)", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=2)

        rb2 = ttk.Frame(b_lf)
        rb2.pack(fill=tk.X, pady=3)
        ttk.Label(rb2, text="Number of Patches:").pack(side=tk.LEFT)
        self.var_gen_bank_count = tk.StringVar(value="16 (Full Bank)")
        ttk.Combobox(
            rb2,
            textvariable=self.var_gen_bank_count,
            values=["8 (Half Bank)", "16 (Full Bank)"],
            state="readonly",
            width=15,
        ).pack(side=tk.LEFT, padx=6)

        ttk.Button(
            b_lf,
            text="🚀 Generate Batch Bank (Using Style Above)",
            command=self.on_gen_batch_bank,
        ).pack(fill=tk.X, pady=(4, 2))

        self.lbl_gen_log = ttk.Label(
            left,
            text="Ready — Select a style or slot and click Generate.",
            font=("Segoe UI", 8, "bold"),
            wraplength=340,
        )
        self.lbl_gen_log.pack(anchor=tk.W, pady=(6, 0))

        # --- CENTER PANE: GENETIC PATCH MUTATOR WITH SECTION LOCKS ---
        mid = ttk.LabelFrame(pw, text="🧬 2. Patch Mutator & Variations (With Section Locks)", padding=8)

        ttk.Label(
            mid,
            text="Organically drifts parameters of any existing User Patch while locking sections you want to preserve.",
            font=("Segoe UI", 8),
            wraplength=330,
        ).pack(anchor=tk.W, pady=(0, 6))

        rm_src = ttk.Frame(mid)
        rm_src.pack(fill=tk.X, pady=3)
        ttk.Label(rm_src, text="Source Patch Slot (1..256):", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        self.var_mut_src_slot = tk.StringVar(value="1")
        ttk.Spinbox(rm_src, from_=1, to=256, textvariable=self.var_mut_src_slot, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Button(rm_src, text="⬅ Use Selected in Tab 2", command=self.on_sync_mut_slot_from_tab2).pack(side=tk.LEFT, padx=2)

        rm_amt = ttk.LabelFrame(mid, text="Mutation Intensity / Drift Amount (%)", padding=6)
        rm_amt.pack(fill=tk.X, pady=6)
        self.var_mut_amount = tk.IntVar(value=25)
        self.lbl_mut_amt_val = ttk.Label(rm_amt, text="25% (Subtle Organic Variation)", font=("Segoe UI", 8, "bold"))
        self.lbl_mut_amt_val.pack(anchor=tk.W)
        sc_mut = ttk.Scale(
            rm_amt,
            from_=5,
            to=100,
            orient=tk.HORIZONTAL,
            command=self._on_mut_scale_move,
        )
        sc_mut.set(25)
        sc_mut.pack(fill=tk.X, pady=3)

        rm_locks = ttk.LabelFrame(mid, text="Synthesis Sections to Mutate (Uncheck to Lock)", padding=6)
        rm_locks.pack(fill=tk.X, pady=6)
        self.var_mut_osc = tk.BooleanVar(value=True)
        self.var_mut_flt = tk.BooleanVar(value=True)
        self.var_mut_env = tk.BooleanVar(value=True)
        self.var_mut_lfo = tk.BooleanVar(value=True)
        self.var_mut_mfx = tk.BooleanVar(value=False)

        ttk.Checkbutton(rm_locks, text="🌊 Oscillators 1–4 (Waves, Detune/Fat, PW, Pan, Sliders)", variable=self.var_mut_osc).pack(anchor=tk.W, pady=1)
        ttk.Checkbutton(rm_locks, text="🎛️ Filter (Cutoff, Resonance, Env Depth)", variable=self.var_mut_flt).pack(anchor=tk.W, pady=1)
        ttk.Checkbutton(rm_locks, text="📉 Envelopes (Filter ADSR & Amp ADSR)", variable=self.var_mut_env).pack(anchor=tk.W, pady=1)
        ttk.Checkbutton(rm_locks, text="🕸️ LFO & 4-Slot Modulation Matrix Depths", variable=self.var_mut_lfo).pack(anchor=tk.W, pady=1)
        ttk.Checkbutton(rm_locks, text="✨ MFX Type & Chorus/Reverb Sends", variable=self.var_mut_mfx).pack(anchor=tk.W, pady=1)

        ttk.Button(
            mid,
            text="🎲 Mutate Source Patch In-Place",
            command=self.on_lab_mutate_in_place,
        ).pack(fill=tk.X, pady=(6, 3))

        rm_clone = ttk.LabelFrame(mid, text="Evolve 8 Mutated Clones into Bank", padding=6)
        rm_clone.pack(fill=tk.X, pady=4)
        rc_row = ttk.Frame(rm_clone)
        rc_row.pack(fill=tk.X, pady=2)
        ttk.Label(rc_row, text="Destination Start Slot (1..249):").pack(side=tk.LEFT)
        self.var_mut_clone_dst = tk.StringVar(value="65")
        ttk.Spinbox(rc_row, from_=1, to=249, textvariable=self.var_mut_clone_dst, width=6).pack(side=tk.LEFT, padx=4)
        ttk.Button(
            rm_clone,
            text="🧬 Generate 8 Mutated Variations of Source Patch",
            command=self.on_lab_mutate_clone_bank,
        ).pack(fill=tk.X, pady=(4, 2))

        # --- RIGHT PANE: MATHEMATICAL WAVEFORM (DRAWING) & 16-STEP (STEP) GENERATOR ---
        right = ttk.LabelFrame(pw, text="📐 3. Mathematical Waveform (DRAWING) & Step-LFO (STEP) Lab", padding=8)

        # Visual Waveform / Step Bar Canvas
        self.cv_wave = tk.Canvas(right, width=320, height=135, bg="#161b22", highlightthickness=1, highlightbackground="#444")
        self.cv_wave.pack(fill=tk.X, pady=(0, 6))

        # DRAWING 32-Step Section
        dw_lf = ttk.LabelFrame(right, text="🎨 DRAWING Oscillator (Model 23 — 32-Step Custom Waveform)", padding=6)
        dw_lf.pack(fill=tk.X, pady=4)

        rdw1 = ttk.Frame(dw_lf)
        rdw1.pack(fill=tk.X, pady=2)
        ttk.Label(rdw1, text="Math Formula:").pack(side=tk.LEFT)
        self.var_math_formula = tk.StringVar(value="Additive Odd/Even Harmonics")
        self.math_formulas = [
            "Additive Odd/Even Harmonics",
            "Formant Vocal Wave",
            "Wave-Folded West-Coast Sine",
            "Bit-Crushed Staircase Saw",
            "Hard-Sync Sweep Wave",
            "Metallic Inharmonic Bell",
            "FM 2-Op Phase Modulated",
            "Smooth Random Spline",
        ]
        cb_mf = ttk.Combobox(rdw1, textvariable=self.var_math_formula, values=self.math_formulas, state="readonly", width=24)
        cb_mf.pack(side=tk.LEFT, padx=4)
        cb_mf.bind("<<ComboboxSelected>>", lambda _e: self.on_preview_math_wave())

        rdw2 = ttk.Frame(dw_lf)
        rdw2.pack(fill=tk.X, pady=2)
        ttk.Label(rdw2, text="Wave Edge (0..127):").pack(side=tk.LEFT)
        self.var_draw_edge = tk.StringVar(value="30")
        ttk.Spinbox(rdw2, from_=0, to=127, textvariable=self.var_draw_edge, width=5).pack(side=tk.LEFT, padx=4)
        ttk.Button(rdw2, text="👁️ Preview Wave", command=self.on_preview_math_wave).pack(side=tk.LEFT, padx=4)
        ttk.Button(rdw2, text="📥 Read Slot's Wave", command=self.on_read_slot_drawing_wave).pack(side=tk.LEFT, padx=2)

        ttk.Button(
            dw_lf,
            text="⚡ Inject 32-Step Waveform into Source Slot (Sets Model=DRAWING)",
            command=self.on_inject_math_wave,
        ).pack(fill=tk.X, pady=(4, 2))

        # STEP 16-Step Section
        st_lf = ttk.LabelFrame(right, text="🪜 STEP Oscillator (Model 27 — 16-Step Sequenced LFO)", padding=6)
        st_lf.pack(fill=tk.X, pady=4)

        rst1 = ttk.Frame(st_lf)
        rst1.pack(fill=tk.X, pady=2)
        ttk.Label(rst1, text="16-Step Pattern:").pack(side=tk.LEFT)
        self.var_step_pattern = tk.StringVar(value="Acid Octave Arpeggio")
        self.step_patterns = [
            "Trance Gate 16-Step",
            "Acid Octave Arpeggio",
            "Rising Filter / Pitch Ramp",
            "Pendulum Sine Groove",
            "Dub Polyrhythm (3x5)",
            "Glitch Sample & Hold",
        ]
        cb_sp = ttk.Combobox(rst1, textvariable=self.var_step_pattern, values=self.step_patterns, state="readonly", width=22)
        cb_sp.pack(side=tk.LEFT, padx=4)
        cb_sp.bind("<<ComboboxSelected>>", lambda _e: self.on_preview_step_lfo())

        rst2 = ttk.Frame(st_lf)
        rst2.pack(fill=tk.X, pady=2)
        ttk.Button(rst2, text="👁️ Preview 16 Steps", command=self.on_preview_step_lfo).pack(side=tk.LEFT, padx=2)
        ttk.Button(rst2, text="📥 Read Slot's Steps", command=self.on_read_slot_step_lfo).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            st_lf,
            text="⚡ Inject 16-Step Sequence into Source Slot (Sets Model=STEP)",
            command=self.on_inject_step_lfo,
        ).pack(fill=tk.X, pady=(4, 2))

        pw.add(left, minsize=310, width=380, stretch="always")
        pw.add(mid, minsize=310, width=390, stretch="always")
        pw.add(right, minsize=320, width=420, stretch="always")

        self.last_preview_steps = []
        self.after(150, self.on_preview_math_wave)

    def _on_mut_scale_move(self, val_str):
        v = int(float(val_str))
        self.var_mut_amount.set(v)
        if v <= 15:
            desc = "Micro Drift / Analog Warmth"
        elif v <= 35:
            desc = "Subtle Organic Variation"
        elif v <= 65:
            desc = "Creative Sound Mutation"
        else:
            desc = "Wild Experimental Chaos"
        self.lbl_mut_amt_val.config(text=f"{v}% ({desc})")

    def _draw_wave_canvas(self, values: list, title_txt: str):
        self.cv_wave.delete("all")
        w = max(300, int(self.cv_wave.winfo_width()))
        h = max(120, int(self.cv_wave.winfo_height()))
        mid_y = h // 2
        self.cv_wave.create_line(0, mid_y, w, mid_y, fill="#30363d", dash=(3, 3))
        n = len(values)
        if n == 0:
            return
        bar_w = (w - 20) / float(n)
        pts = []
        for i, v in enumerate(values):
            x0 = 10 + i * bar_w
            x1 = x0 + bar_w - 2
            norm = max(-72, min(72, int(v))) / 72.0
            y = int(mid_y - norm * (mid_y - 18))
            color = "#2ea043" if n == 32 else "#58a6ff"
            self.cv_wave.create_rectangle(x0, min(mid_y, y), x1, max(mid_y, y), fill=color, outline="")
            pts.extend([x0 + bar_w * 0.5, y])
        if len(pts) >= 4:
            self.cv_wave.create_line(*pts, fill="#f0f6fc", width=1.5, smooth=True)
        self.cv_wave.create_text(8, 10, anchor=tk.W, text=title_txt, fill="#c9d1d9", font=("Segoe UI", 8, "bold"))

    def on_preview_math_wave(self):
        formula = self.var_math_formula.get()
        steps_32, edge = SH4dSVD.compute_math_wave_32(formula)
        self.last_preview_steps = steps_32
        self.var_draw_edge.set(str(edge))
        self._draw_wave_canvas(steps_32, f"DRAWING 32-Step Wave: {formula} (Edge={edge})")

    def on_read_slot_drawing_wave(self):
        if not self.svd:
            return
        idx = max(0, min(255, int(self.var_mut_src_slot.get()) - 1))
        dw = self.svd.get_drawing_wave(idx)
        self.last_preview_steps = dw["steps"]
        self.var_draw_edge.set(str(dw["edge"]))
        name = self.svd.get_patch_name(idx)
        self._draw_wave_canvas(dw["steps"], f"Slot #{idx+1:03d} ({name}) 32-Step Wave (Edge={dw['edge']})")

    def on_inject_math_wave(self):
        if not self.svd:
            return
        idx = max(0, min(255, int(self.var_mut_src_slot.get()) - 1))
        if not self.last_preview_steps or len(self.last_preview_steps) != 32:
            self.on_preview_math_wave()
        edge = max(0, min(127, int(self.var_draw_edge.get())))
        self.svd.set_drawing_wave(idx, self.last_preview_steps, edge, switch_model=True)
        self._select_and_refresh_patch(idx)
        self.lbl_gen_log.config(text=f"Injected 32-Step Math Wave into Slot #{idx+1:03d} ({self.svd.get_patch_name(idx)}).")

    def on_preview_step_lfo(self):
        pat_name = self.var_step_pattern.get()
        vals_16, _curves_16 = SH4dSVD.compute_step_lfo_16(pat_name)
        self.last_preview_step_lfo = (vals_16, _curves_16)
        self._draw_wave_canvas(vals_16, f"STEP 16-Step Sequence: {pat_name}")

    def on_read_slot_step_lfo(self):
        if not self.svd:
            return
        idx = max(0, min(255, int(self.var_mut_src_slot.get()) - 1))
        st = self.svd.get_step_lfo_data(idx)
        self.last_preview_step_lfo = (st["vals"], st["curves"])
        name = self.svd.get_patch_name(idx)
        self._draw_wave_canvas(st["vals"], f"Slot #{idx+1:03d} ({name}) 16-Step Sequence")

    def on_inject_step_lfo(self):
        if not self.svd:
            return
        idx = max(0, min(255, int(self.var_mut_src_slot.get()) - 1))
        if not hasattr(self, "last_preview_step_lfo"):
            self.on_preview_step_lfo()
        vals_16, curves_16 = self.last_preview_step_lfo
        self.svd.set_step_lfo_data(idx, vals_16, curves_16, switch_model=True)
        self._select_and_refresh_patch(idx)
        self.lbl_gen_log.config(text=f"Injected 16-Step Sequence into Slot #{idx+1:03d} ({self.svd.get_patch_name(idx)}).")

    def on_find_next_init_slot(self):
        if not self.svd:
            return
        for i in range(256):
            if self.svd.get_patch_name(i).strip().upper() == "INIT TONE":
                self.var_gen_single_slot.set(str(i + 1))
                self.lbl_gen_log.config(text=f"Found empty INIT TONE at Slot #{i+1:03d} (U{(i//16)+1:02d}-{(i%16)+1:02d}).")
                return
        messagebox.showinfo("No INIT TONE Found", "All 256 User Patch slots already contain named patches.")

    def on_sync_mut_slot_from_tab2(self):
        sel = self.tree_patch.selection()
        if sel:
            idx = int(sel[0])
            self.var_mut_src_slot.set(str(idx + 1))
            self.lbl_gen_log.config(text=f"Synced Source Slot to #{idx+1:03d} ({self.svd.get_patch_name(idx)}).")

    def _select_and_refresh_patch(self, idx: int):
        self.refresh_patches()
        self.refresh_patterns()
        sid = str(idx)
        if self.tree_patch.exists(sid):
            self.tree_patch.selection_set(sid)
            self.tree_patch.see(sid)
            self.on_select_patch(None)

    def on_gen_single_preset(self):
        if not self.svd:
            return
        idx = max(0, min(255, int(self.var_gen_single_slot.get()) - 1))
        genre = self.var_gen_genre.get()
        cname = self.var_gen_custom_name.get().strip() or None
        p = self.svd.generate_smart_preset(idx, genre, custom_name=cname)
        self._select_and_refresh_patch(idx)
        if p["osc_model"] == 23:
            self.var_mut_src_slot.set(str(idx + 1))
            self.on_read_slot_drawing_wave()
        elif p["osc_model"] == 27:
            self.var_mut_src_slot.set(str(idx + 1))
            self.on_read_slot_step_lfo()
        self.lbl_gen_log.config(
            text=f"✅ Generated '{p['name']}' ({p['osc_model_label']}) at Slot #{idx+1:03d} (Cutoff={p['cutoff']}, Reso={p['resonance']})."
        )

    def on_gen_and_export_file(self):
        if not self.svd:
            return
        idx = max(0, min(255, int(self.var_gen_single_slot.get()) - 1))
        backup_raw = self.svd.get_patch_bytes(idx)
        genre = self.var_gen_genre.get()
        cname = self.var_gen_custom_name.get().strip() or None
        p = self.svd.generate_smart_preset(idx, genre, custom_name=cname)
        gen_bytes = self.svd.get_patch_bytes(idx)
        # Restore slot if user only wanted standalone export, or keep it
        safe_name = p["name"].replace(" ", "_").replace("#", "")
        out_p = filedialog.asksaveasfilename(
            title="Export Generated SH-4d Patch",
            defaultextension=".sh4d_patch",
            initialfile=f"{safe_name}.sh4d_patch",
            filetypes=[("SH-4d Patch", "*.sh4d_patch")],
        )
        if out_p:
            with open(out_p, "wb") as f:
                f.write(gen_bytes)
            self._select_and_refresh_patch(idx)
            self.lbl_gen_log.config(text=f"💾 Generated & exported '{p['name']}' to {os.path.basename(out_p)}.")
        else:
            self.svd.set_patch_bytes(idx, backup_raw)

    def on_gen_batch_bank(self):
        if not self.svd:
            return
        start_idx = max(0, min(255, int(self.var_gen_bank_start.get()) - 1))
        count = 16 if "16" in self.var_gen_bank_count.get() else 8
        end_idx = min(256, start_idx + count)
        genre = self.var_gen_genre.get()
        created = []
        for i in range(start_idx, end_idx):
            p = self.svd.generate_smart_preset(i, genre)
            created.append(p["name"])
        self._select_and_refresh_patch(start_idx)
        self.lbl_gen_log.config(
            text=f"🚀 Batch generated {len(created)} presets in Slots #{start_idx+1:03d}..#{end_idx:03d} ({created[0]} .. {created[-1]})."
        )
        messagebox.showinfo(
            "Batch Bank Generated",
            f"Generated {len(created)} new '{genre}' patches in Slots #{start_idx+1:03d} to #{end_idx:03d}!\n\n"
            f"Click 'Save (.bak)' in the top toolbar when you want to write to your .SVD file.",
        )

    def on_lab_mutate_in_place(self):
        if not self.svd:
            return
        idx = max(0, min(255, int(self.var_mut_src_slot.get()) - 1))
        amt = int(self.var_mut_amount.get())
        p = self.svd.mutate_patch(
            idx,
            amount_pct=amt,
            mut_osc=self.var_mut_osc.get(),
            mut_flt=self.var_mut_flt.get(),
            mut_env=self.var_mut_env.get(),
            mut_lfo_mtx=self.var_mut_lfo.get(),
            mut_mfx=self.var_mut_mfx.get(),
        )
        self._select_and_refresh_patch(idx)
        self.lbl_gen_log.config(
            text=f"🎲 Mutated Slot #{idx+1:03d} ('{p['name']}') by {amt}% -> Cutoff={p['cutoff']}, Reso={p['resonance']}."
        )

    def on_lab_mutate_clone_bank(self):
        if not self.svd:
            return
        src_idx = max(0, min(255, int(self.var_mut_src_slot.get()) - 1))
        dst_start = max(0, min(248, int(self.var_mut_clone_dst.get()) - 1))
        amt = int(self.var_mut_amount.get())
        src_bytes = self.svd.get_patch_bytes(src_idx)
        base_name = self.svd.get_patch_name(src_idx)[:12].strip()
        for k in range(8):
            d_idx = dst_start + k
            self.svd.set_patch_bytes(d_idx, src_bytes)
            v_name = f"{base_name} M{k+1}"
            self.svd.mutate_patch(
                d_idx,
                amount_pct=amt,
                mut_osc=self.var_mut_osc.get(),
                mut_flt=self.var_mut_flt.get(),
                mut_env=self.var_mut_env.get(),
                mut_lfo_mtx=self.var_mut_lfo.get(),
                mut_mfx=self.var_mut_mfx.get(),
                new_name=v_name,
            )
        self._select_and_refresh_patch(dst_start)
        self.lbl_gen_log.config(
            text=f"🧬 Evolved 8 mutated clones of '{base_name}' ({amt}%) into Slots #{dst_start+1:03d}..#{dst_start+8:03d}."
        )
        messagebox.showinfo(
            "8 Mutated Variations Created",
            f"Created 8 mutated clones of '{base_name}' ({amt}% intensity) in Slots #{dst_start+1:03d} to #{dst_start+8:03d}!",
        )

    def on_quick_mutate_patch(self):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        p = self.svd.mutate_patch(idx, amount_pct=20)
        self._select_and_refresh_patch(idx)
        self.lbl_status.config(text=f"🎲 Mutated #{idx+1:03d} '{p['name']}' (20%)")

    def on_quick_randomize_patch(self):
        sel = self.tree_patch.selection()
        if not sel or not self.svd:
            return
        idx = int(sel[0])
        p = self.svd.generate_smart_preset(idx, "🎲 Mixed / Surprise Me")
        self._select_and_refresh_patch(idx)
        self.lbl_status.config(text=f"✨ Generated '{p['name']}' ({p['osc_model_label']}) in #{idx+1:03d}")

    # ---------------- TAB 6: PATTERN STEP SEQUENCER & GROOVE CREATOR ----------------
    DRUM_MATRIX_LANES = [
        (36, "BD1 (36 C2)"),
        (37, "BD2 (37 C#2)"),
        (38, "SD1 (38 D2)"),
        (39, "Clap (39 D#2)"),
        (40, "SD2/Rim (40 E2)"),
        (42, "Closed Hat (42 F#2)"),
        (46, "Open Hat (46 A#2)"),
        (51, "Ride/Perc (51 D#3)"),
    ]

    def _build_pattern_creator_tab(self):
        tab = ttk.Frame(self.nb, padding=6)
        self.nb.add(tab, text="🎹 6. Pattern Step Sequencer & Groove Creator")

        self.pat_play_running = False
        self.pat_play_step = 0
        self.pat_play_after_id = None

        # Top Pattern & Active Part Bar
        top_bar = ttk.LabelFrame(tab, text="Pattern Selection, Tempo, Active Part & Tone Assignment", padding=6)
        top_bar.pack(fill=tk.X, pady=(0, 6))

        r1 = ttk.Frame(top_bar)
        r1.pack(fill=tk.X, pady=2)
        ttk.Label(r1, text="Pattern Slot:", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        self.var_pc_pat = tk.StringVar(value="1: 1-01")
        pat_opts = [f"{i+1}: {(i//16)+1}-{(i%16)+1:02d}" for i in range(128)]
        self.cb_pc_pat = ttk.Combobox(r1, textvariable=self.var_pc_pat, values=pat_opts, state="readonly", width=18)
        self.cb_pc_pat.pack(side=tk.LEFT, padx=4)
        self.cb_pc_pat.bind("<<ComboboxSelected>>", lambda _e: self.on_pc_select_pattern())

        ttk.Button(r1, text="🔍 First Empty Slot", command=self.on_pc_find_empty_pattern).pack(side=tk.LEFT, padx=2)

        ttk.Label(r1, text="Name:").pack(side=tk.LEFT, padx=(8, 2))
        self.var_pc_name = tk.StringVar(value="USER PATTERN")
        ttk.Entry(r1, textvariable=self.var_pc_name, width=15).pack(side=tk.LEFT, padx=2)

        ttk.Label(r1, text="BPM:").pack(side=tk.LEFT, padx=(6, 2))
        self.var_pc_bpm = tk.StringVar(value="128.0")
        ttk.Entry(r1, textvariable=self.var_pc_bpm, width=7).pack(side=tk.LEFT, padx=2)

        ttk.Label(r1, text="Lvl:").pack(side=tk.LEFT, padx=(4, 2))
        self.var_pc_lvl = tk.StringVar(value="110")
        ttk.Spinbox(r1, from_=0, to=127, textvariable=self.var_pc_lvl, width=5).pack(side=tk.LEFT, padx=2)

        ttk.Button(r1, text="💾 Update Name/BPM", command=self.on_pc_save_header).pack(side=tk.LEFT, padx=4)

        self.btn_pc_play = ttk.Button(r1, text="▶️ Play Pattern Live (MIDI)", command=self.on_pc_toggle_live_play)
        self.btn_pc_play.pack(side=tk.RIGHT, padx=4)

        r2 = ttk.Frame(top_bar)
        r2.pack(fill=tk.X, pady=(4, 1))
        ttk.Label(r2, text="Active Part:", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        self.var_pc_part = tk.StringVar(value="1: Synth Part 1 (Ch 8)")
        part_opts = [
            "1: Synth Part 1 (Ch 8)",
            "2: Synth Part 2 (Ch 9)",
            "3: Synth Part 3 (Ch 11)",
            "4: Synth Part 4 (Ch 12)",
            "5: Rhythm Part 5 (Ch 13)",
        ]
        self.cb_pc_part = ttk.Combobox(r2, textvariable=self.var_pc_part, values=part_opts, state="readonly", width=23)
        self.cb_pc_part.pack(side=tk.LEFT, padx=4)
        self.cb_pc_part.bind("<<ComboboxSelected>>", lambda _e: self.on_pc_select_part())

        ttk.Label(r2, text="Part Tone / Kit:").pack(side=tk.LEFT, padx=(8, 2))
        self.var_pc_tone = tk.StringVar(value="")
        self.cb_pc_tone = ttk.Combobox(r2, textvariable=self.var_pc_tone, state="readonly", width=28)
        self.cb_pc_tone.pack(side=tk.LEFT, padx=2)
        ttk.Button(r2, text="📌 Assign Tone to Part", command=self.on_pc_assign_tone).pack(side=tk.LEFT, padx=3)

        ttk.Label(r2, text="Step Length (1..64):").pack(side=tk.LEFT, padx=(8, 2))
        self.var_pc_slen = tk.StringVar(value="16")
        ttk.Spinbox(r2, from_=1, to=64, textvariable=self.var_pc_slen, width=5, command=self.on_pc_apply_slen).pack(side=tk.LEFT, padx=2)
        for q_len in (16, 32, 64):
            ttk.Button(r2, text=f"{q_len}st", width=4, command=lambda l=q_len: self.on_pc_quick_slen(l)).pack(side=tk.LEFT, padx=1)

        ttk.Button(r2, text="🧹 Clear Active Part", command=self.on_pc_clear_part).pack(side=tk.RIGHT, padx=4)

        # Main 3-Pane Split
        pw = tk.PanedWindow(tab, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED, bg="#b8b8b8")
        pw.pack(fill=tk.BOTH, expand=True)

        # LEFT PANE: Groove & Pattern Generator + Euclidean Sequencer
        left = ttk.LabelFrame(pw, text="🎲 1. Groove & 5-Part Pattern Generator", padding=8)

        g1 = ttk.LabelFrame(left, text="Musical Key, Scale & Full 5-Part Pattern Creator", padding=6)
        g1.pack(fill=tk.X, pady=(0, 6))

        rk = ttk.Frame(g1)
        rk.pack(fill=tk.X, pady=2)
        ttk.Label(rk, text="Root Key:").pack(side=tk.LEFT)
        self.var_pc_key = tk.StringVar(value="C")
        ttk.Combobox(
            rk,
            textvariable=self.var_pc_key,
            values=list(SH4dSVD.KEY_TO_SEMITONE.keys()),
            state="readonly",
            width=5,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Label(rk, text="Scale:").pack(side=tk.LEFT, padx=(4, 2))
        self.var_pc_scale = tk.StringVar(value="Minor (Aeolian)")
        ttk.Combobox(
            rk,
            textvariable=self.var_pc_scale,
            values=list(SH4dSVD.SCALES.keys()),
            state="readonly",
            width=19,
        ).pack(side=tk.LEFT, padx=2)

        rs = ttk.Frame(g1)
        rs.pack(fill=tk.X, pady=3)
        ttk.Label(rs, text="Groove Style:").pack(side=tk.LEFT)
        self.var_pc_style = tk.StringVar(value="Techno / Peak-Time (132 BPM)")
        style_list = [
            "Techno / Peak-Time (132 BPM)",
            "Acid House / 303 Groove (128 BPM)",
            "Melodic Techno / Prog Pluck (124 BPM)",
            "Dub Techno Hypnotic (120 BPM)",
            "Synthwave / Electro 80s (112 BPM)",
        ]
        ttk.Combobox(rs, textvariable=self.var_pc_style, values=style_list, state="readonly", width=26).pack(side=tk.LEFT, padx=4)

        self.var_pc_auto_tones = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            g1,
            text="Auto-Assign User Synth Patches & Drum Kit (Parts 1–5)",
            variable=self.var_pc_auto_tones,
        ).pack(anchor=tk.W, pady=2)

        ttk.Button(
            g1,
            text="🚀 Generate Full 5-Part Pattern (Drums + Bass + Chords + Pluck + Lead)",
            command=self.on_pc_generate_full_pattern,
        ).pack(fill=tk.X, pady=(4, 2))

        # Single Part Sequence Generator
        g2 = ttk.LabelFrame(left, text="🎹 Single-Part Sequence Generator (Active Part Only)", padding=6)
        g2.pack(fill=tk.X, pady=6)

        rp1 = ttk.Frame(g2)
        rp1.pack(fill=tk.X, pady=2)
        ttk.Label(rp1, text="Part Role:").pack(side=tk.LEFT)
        self.var_pc_role = tk.StringVar(value="Pluck Arpeggio")
        role_opts = [
            "Driving Bassline",
            "Acid 303 Bassline",
            "Pluck Arpeggio",
            "Polyphonic Chords",
            "Dub Techno Stabs",
            "Lead Hook",
            "TR Drum Beat",
            "Electro Breakbeat",
            "Minimal Drums",
        ]
        ttk.Combobox(rp1, textvariable=self.var_pc_role, values=role_opts, state="readonly", width=22).pack(side=tk.LEFT, padx=4)

        rp2 = ttk.Frame(g2)
        rp2.pack(fill=tk.X, pady=2)
        ttk.Label(rp2, text="Note Density (%):").pack(side=tk.LEFT)
        self.var_pc_density = tk.StringVar(value="70")
        ttk.Spinbox(rp2, from_=15, to=100, increment=5, textvariable=self.var_pc_density, width=6).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            g2,
            text="✨ Generate Sequence on Active Part Only",
            command=self.on_pc_generate_active_part,
        ).pack(fill=tk.X, pady=(4, 2))

        # Euclidean Sequencer
        g3 = ttk.LabelFrame(left, text="📐 Euclidean Polyrhythm Generator E(k, n, rot)", padding=6)
        g3.pack(fill=tk.X, pady=6)

        re1 = ttk.Frame(g3)
        re1.pack(fill=tk.X, pady=2)
        ttk.Label(re1, text="Pulses (k):").pack(side=tk.LEFT)
        self.var_euc_k = tk.StringVar(value="5")
        ttk.Spinbox(re1, from_=1, to=64, textvariable=self.var_euc_k, width=4).pack(side=tk.LEFT, padx=2)
        ttk.Label(re1, text="Steps (n):").pack(side=tk.LEFT, padx=(4, 1))
        self.var_euc_n = tk.StringVar(value="16")
        ttk.Spinbox(re1, from_=1, to=64, textvariable=self.var_euc_n, width=4).pack(side=tk.LEFT, padx=2)
        ttk.Label(re1, text="Rot:").pack(side=tk.LEFT, padx=(4, 1))
        self.var_euc_rot = tk.StringVar(value="0")
        ttk.Spinbox(re1, from_=0, to=31, textvariable=self.var_euc_rot, width=4).pack(side=tk.LEFT, padx=2)

        re2 = ttk.Frame(g3)
        re2.pack(fill=tk.X, pady=2)
        ttk.Label(re2, text="MIDI Note (e.g. 60=C4, 36=BD1, 42=CH):").pack(side=tk.LEFT)
        self.var_euc_note = tk.StringVar(value="60")
        ttk.Spinbox(re2, from_=0, to=127, textvariable=self.var_euc_note, width=5).pack(side=tk.LEFT, padx=4)

        ttk.Button(
            g3,
            text="🔀 Apply Euclidean Rhythm to Active Part",
            command=self.on_pc_apply_euclidean,
        ).pack(fill=tk.X, pady=(4, 2))

        # Standard MIDI File (.mid) Import & Export Box
        g4 = ttk.LabelFrame(left, text="🎼 Standard MIDI File (.mid) Import & Export", padding=6)
        g4.pack(fill=tk.X, pady=6)

        ttk.Button(
            g4,
            text="📥 Import .mid -> Active Part (Single Track/Ch)...",
            command=self.on_pc_import_midi_single_part,
        ).pack(fill=tk.X, pady=2)

        ttk.Button(
            g4,
            text="🎼 Import Multi-Track .mid -> Pattern (Parts 1–5)...",
            command=self.on_pc_import_midi_multitrack,
        ).pack(fill=tk.X, pady=2)

        ttk.Button(
            g4,
            text="📤 Export Pattern (All 5 Parts) -> .mid File...",
            command=self.on_pc_export_pattern_midi,
        ).pack(fill=tk.X, pady=2)

        self.lbl_pc_status = ttk.Label(
            left,
            text="Ready — Select a Pattern & Part to edit or generate.",
            font=("Segoe UI", 8, "bold"),
            wraplength=330,
        )
        self.lbl_pc_status.pack(anchor=tk.W, pady=(6, 0))

        # CENTER PANE: Interactive 16-Step Sequencer Grid + 8-Lane TR Drum Matrix + Step Editor
        center = ttk.LabelFrame(pw, text="🎛️ 2. Interactive 16/64-Step Grid, TR Drum Matrix & Step Editor", padding=8)

        pg_bar = ttk.Frame(center)
        pg_bar.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(pg_bar, text="Step Page:", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        self.var_pc_page = tk.IntVar(value=0)
        for pg_i, pg_lbl in enumerate(["Steps 1–16", "Steps 17–32", "Steps 33–48", "Steps 49–64"]):
            ttk.Radiobutton(
                pg_bar,
                text=pg_lbl,
                variable=self.var_pc_page,
                value=pg_i,
                command=self.refresh_pc_grid_and_table,
            ).pack(side=tk.LEFT, padx=4)

        self.var_pc_paint_mode = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            pg_bar,
            text="⚡ Paint Mode (Click Step Button to Toggle Note/Chord)",
            variable=self.var_pc_paint_mode,
        ).pack(side=tk.RIGHT, padx=2)

        # 16 Hardware-style Step Buttons (2 rows of 8 steps for clean fit)
        step_btn_lf = ttk.LabelFrame(center, text="16-Step Sequencer Bar (Click Step to Select or Paint)", padding=4)
        step_btn_lf.pack(fill=tk.X, pady=3)
        self.pc_step_btns = []
        for s_i in range(16):
            r_idx = s_i // 8
            c_idx = s_i % 8
            step_btn_lf.columnconfigure(c_idx, weight=1)
            b = tk.Button(
                step_btn_lf,
                text=f"{s_i+1:02d}\n—",
                width=7,
                height=2,
                relief=tk.RAISED,
                bg="#21262d",
                fg="#c9d1d9",
                font=("Segoe UI", 8, "bold"),
                command=lambda idx=s_i: self.on_pc_click_step_btn(idx),
            )
            b.grid(row=r_idx, column=c_idx, padx=2, pady=2, sticky="ew")
            self.pc_step_btns.append(b)

        # Selected Step Polyphonic Note / Chord / Velocity / Gate Editor
        ed_lf = ttk.LabelFrame(center, text="✏️ Selected Step Note / Chord / Velocity / Gate Editor", padding=6)
        ed_lf.pack(fill=tk.X, pady=4)

        er1 = ttk.Frame(ed_lf)
        er1.pack(fill=tk.X, pady=2)
        ttk.Label(er1, text="Selected Step (1..64):", font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        self.var_pc_sel_step = tk.StringVar(value="1")
        sp_st = ttk.Spinbox(er1, from_=1, to=64, textvariable=self.var_pc_sel_step, width=5, command=self.on_pc_load_selected_step)
        sp_st.pack(side=tk.LEFT, padx=4)
        sp_st.bind("<Return>", lambda _e: self.on_pc_load_selected_step())

        ttk.Label(er1, text="Root Note:").pack(side=tk.LEFT, padx=(6, 2))
        self.var_pc_step_root = tk.StringVar(value="60: C4")
        note_choices = [f"{n}: {midi_note_name(n)}" for n in range(24, 97)]
        ttk.Combobox(er1, textvariable=self.var_pc_step_root, values=note_choices, state="readonly", width=10).pack(side=tk.LEFT, padx=2)

        ttk.Label(er1, text="Chord Builder:").pack(side=tk.LEFT, padx=(6, 2))
        self.var_pc_step_chord = tk.StringVar(value="Single Note")
        ttk.Combobox(
            er1,
            textvariable=self.var_pc_step_chord,
            values=list(SH4dSVD.CHORD_TYPES.keys()),
            state="readonly",
            width=20,
        ).pack(side=tk.LEFT, padx=2)
        ttk.Button(er1, text="🎹 Fill Notes", command=self.on_pc_fill_chord_notes).pack(side=tk.LEFT, padx=3)

        er2 = ttk.Frame(ed_lf)
        er2.pack(fill=tk.X, pady=2)
        ttk.Label(er2, text="MIDI Notes (up to 8, comma-sep):").pack(side=tk.LEFT)
        self.var_pc_step_notes = tk.StringVar(value="60")
        ttk.Entry(er2, textvariable=self.var_pc_step_notes, width=22).pack(side=tk.LEFT, padx=4)

        ttk.Label(er2, text="Vel (1-127):").pack(side=tk.LEFT, padx=(4, 1))
        self.var_pc_step_vel = tk.StringVar(value="100")
        ttk.Spinbox(er2, from_=1, to=127, textvariable=self.var_pc_step_vel, width=5).pack(side=tk.LEFT, padx=2)

        ttk.Label(er2, text="Gate (1-127):").pack(side=tk.LEFT, padx=(4, 1))
        self.var_pc_step_gate = tk.StringVar(value="80")
        ttk.Spinbox(er2, from_=1, to=127, textvariable=self.var_pc_step_gate, width=5).pack(side=tk.LEFT, padx=2)

        ttk.Label(er2, text="Prob %:").pack(side=tk.LEFT, padx=(4, 1))
        self.var_pc_step_prob = tk.StringVar(value="100")
        ttk.Spinbox(er2, from_=0, to=100, textvariable=self.var_pc_step_prob, width=5).pack(side=tk.LEFT, padx=2)

        ttk.Label(er2, text="Substep:").pack(side=tk.LEFT, padx=(4, 1))
        self.var_pc_step_sub = tk.StringVar(value="0")
        ttk.Spinbox(er2, from_=0, to=13, textvariable=self.var_pc_step_sub, width=4).pack(side=tk.LEFT, padx=2)

        er3 = ttk.Frame(ed_lf)
        er3.pack(fill=tk.X, pady=(4, 1))
        ttk.Button(er3, text="✅ Write Step to Pattern", command=self.on_pc_write_step).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 3))
        ttk.Button(er3, text="🗑️ Clear Step", command=self.on_pc_clear_single_step).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(3, 0))

        # 8-Lane × 16-Step TR-Style Drum Matrix (Directly edits Part 5 Rhythm on current Page 1..16)
        drum_lf = ttk.LabelFrame(center, text="🥁 Part 5 (Rhythm) 8-Lane × 16-Step TR Drum Matrix (Click Any Cell to Toggle Hit)", padding=4)
        drum_lf.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        for c_i in range(16):
            lbl_c = ttk.Label(drum_lf, text=f"{c_i+1:02d}", anchor=tk.CENTER, font=("Segoe UI", 7, "bold"))
            lbl_c.grid(row=0, column=c_i + 1, padx=1, pady=1)

        self.pc_drum_grid_btns = []
        for r_i, (d_note, d_lbl) in enumerate(self.DRUM_MATRIX_LANES):
            ttk.Label(drum_lf, text=d_lbl, font=("Segoe UI", 7, "bold")).grid(row=r_i + 1, column=0, sticky=tk.W, padx=(2, 4))
            row_btns = []
            for c_i in range(16):
                drum_lf.columnconfigure(c_i + 1, weight=1)
                db = tk.Button(
                    drum_lf,
                    text="·",
                    width=2,
                    height=1,
                    relief=tk.FLAT,
                    bg="#21262d",
                    fg="#8b949e",
                    font=("Segoe UI", 8, "bold"),
                    command=lambda dn=d_note, sc=c_i: self.on_pc_toggle_drum_cell(dn, sc),
                )
                db.grid(row=r_i + 1, column=c_i + 1, padx=1, pady=1, sticky="ew")
                row_btns.append(db)
            self.pc_drum_grid_btns.append((d_note, row_btns))

        # RIGHT PANE: Full 64-Step Sequence Table for Active Part
        right = ttk.LabelFrame(pw, text="📋 3. Full 64-Step Sequence Table (Active Part)", padding=6)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        cols_pc = ("step", "notes", "vel", "gate", "prob", "sub")
        self.tree_pc_steps = ttk.Treeview(right, columns=cols_pc, show="headings", selectmode="browse")
        self.tree_pc_steps.heading("step", text="Step")
        self.tree_pc_steps.column("step", width=48, anchor=tk.CENTER)
        self.tree_pc_steps.heading("notes", text="Notes / Chord / Drum Hits")
        self.tree_pc_steps.column("notes", width=175, anchor=tk.W)
        self.tree_pc_steps.heading("vel", text="Vel")
        self.tree_pc_steps.column("vel", width=40, anchor=tk.CENTER)
        self.tree_pc_steps.heading("gate", text="Gate")
        self.tree_pc_steps.column("gate", width=42, anchor=tk.CENTER)
        self.tree_pc_steps.heading("prob", text="Prob")
        self.tree_pc_steps.column("prob", width=45, anchor=tk.CENTER)
        self.tree_pc_steps.heading("sub", text="Sub")
        self.tree_pc_steps.column("sub", width=38, anchor=tk.CENTER)

        sb_pcs = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self.tree_pc_steps.yview)
        self.tree_pc_steps.configure(yscrollcommand=sb_pcs.set)
        self.tree_pc_steps.grid(row=0, column=0, sticky="nsew")
        sb_pcs.grid(row=0, column=1, sticky="ns")
        self.tree_pc_steps.bind("<<TreeviewSelect>>", self.on_pc_select_table_step)

        pw.add(left, minsize=300, width=355, stretch="never")
        pw.add(center, minsize=450, width=540, stretch="always")
        pw.add(right, minsize=280, width=340, stretch="always")

    def _get_pc_pat_idx(self) -> int:
        raw = self.var_pc_pat.get().split(":")[0].strip()
        return max(0, min(127, int(raw) - 1)) if raw.isdigit() else 0

    def _get_pc_part_idx(self) -> int:
        raw = self.var_pc_part.get().split(":")[0].strip()
        return max(0, min(4, int(raw) - 1)) if raw.isdigit() else 0

    def refresh_pattern_creator_tab(self):
        if not self.svd:
            return
        pat_opts = []
        for i in range(128):
            info = self.svd.get_pattern_info(i)
            pat_opts.append(f"{i+1}: {info['slot']} {info['name'].strip()}")
        cur_pat = self._get_pc_pat_idx()
        self.cb_pc_pat.config(values=pat_opts)
        self.var_pc_pat.set(pat_opts[cur_pat])
        self.on_pc_select_pattern()

    def on_pc_select_pattern(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        info = self.svd.get_pattern_info(pat_idx)
        self.var_pc_name.set(info["name"])
        self.var_pc_bpm.set(f"{info['tempo']:.2f}")
        self.var_pc_lvl.set(str(info["level"]))
        self.on_pc_select_part()

    def on_pc_select_part(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        info = self.svd.get_pattern_info(pat_idx)
        slen = self.svd.get_part_step_length(pat_idx, part_idx)
        self.var_pc_slen.set(str(slen))

        # Populate Tone/Kit dropdown for this part
        if part_idx < 4:
            tone_opts = [
                f"U{(i//16)+1:02d}-{(i%16)+1:02d} (#{i+1:03d}): {self.svd.get_patch_name(i).strip()}"
                for i in range(256)
            ]
            self.cb_pc_tone.config(values=tone_opts)
            p_data = info["parts"][part_idx]
            if p_data["msb"] == 87 and p_data["lsb"] in (0, 1):
                u_idx = max(0, min(255, p_data["lsb"] * 128 + p_data["pc"]))
                self.var_pc_tone.set(tone_opts[u_idx])
            else:
                self.var_pc_tone.set(p_data["resolved"])
        else:
            kit_opts = [
                f"UK#{i+1:02d}: {self.svd.get_kit_name(i).strip()}"
                for i in range(64)
            ]
            self.cb_pc_tone.config(values=kit_opts)
            p_data = info["parts"][4]
            if p_data["msb"] == 86 and p_data["lsb"] == 0 and 0 <= p_data["pc"] < 64:
                self.var_pc_tone.set(kit_opts[p_data["pc"]])
            else:
                self.var_pc_tone.set(p_data["resolved"])

        self.refresh_pc_grid_and_table()

    def refresh_pc_grid_and_table(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        page = self.var_pc_page.get()
        base_step = page * 16
        sel_step_0_63 = max(0, min(63, int(self.var_pc_sel_step.get()) - 1))

        # 1. Update 16-Step Hardware Bar
        for i in range(16):
            s_idx = base_step + i
            st = self.svd.get_step_info(pat_idx, part_idx, s_idx)
            is_sel = (s_idx == sel_step_0_63)
            if st["notes"]:
                if part_idx == 4:
                    tag = f"{len(st['notes'])}hit"
                elif len(st["notes"]) > 1:
                    tag = f"{midi_note_name(st['notes'][0])}+{len(st['notes'])-1}"
                else:
                    tag = midi_note_name(st["notes"][0])
                bg = "#1f6feb" if is_sel else "#238636"
                fg = "#ffffff"
            else:
                tag = "—"
                bg = "#388bfd" if is_sel else "#21262d"
                fg = "#ffffff" if is_sel else "#8b949e"
            self.pc_step_btns[i].config(text=f"{s_idx+1:02d}\n{tag}", bg=bg, fg=fg)

        # 2. Update 8-Lane × 16-Step Drum Matrix (always reflects Part 5 Rhythm for current page)
        for d_note, row_btns in self.pc_drum_grid_btns:
            for c_i in range(16):
                s_idx = base_step + c_i
                st_d = self.svd.get_step_info(pat_idx, 4, s_idx)
                if d_note in st_d["notes"]:
                    row_btns[c_i].config(
                        text="●",
                        bg="#d29922" if (c_i % 4 == 0) else "#2ea043",
                        fg="#ffffff",
                    )
                else:
                    row_btns[c_i].config(
                        text="·",
                        bg="#2d333b" if (c_i % 4 == 0) else "#21262d",
                        fg="#8b949e",
                    )

        # 3. Update 64-Step Treeview
        self.tree_pc_steps.delete(*self.tree_pc_steps.get_children())
        for s in range(64):
            st = self.svd.get_step_info(pat_idx, part_idx, s)
            has_n = bool(st["notes"])
            self.tree_pc_steps.insert(
                "",
                tk.END,
                iid=str(s),
                values=(
                    f"{s+1:02d}" + (" ●" if has_n else ""),
                    st["note_names"],
                    st["vel"] if has_n else "—",
                    st["gate"] if has_n else "—",
                    f"{st['prob']}%" if has_n else "—",
                    st["substep"] if (has_n and st["substep"] > 0) else "—",
                ),
            )

    def _parse_step_notes_entry(self) -> list:
        raw = self.var_pc_step_notes.get().strip()
        notes = []
        for tok in raw.replace(";", ",").split(","):
            t = tok.strip()
            if t.isdigit():
                notes.append(max(0, min(127, int(t))))
        return notes[:8]

    def on_pc_click_step_btn(self, btn_idx_0_15: int):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        s_idx = self.var_pc_page.get() * 16 + btn_idx_0_15
        self.var_pc_sel_step.set(str(s_idx + 1))

        if self.var_pc_paint_mode.get():
            st = self.svd.get_step_info(pat_idx, part_idx, s_idx)
            if st["notes"]:
                self.svd.clear_steps_content(pat_idx, part_idx, s_idx + 1, s_idx + 1)
            else:
                notes = self._parse_step_notes_entry() or [60]
                vel = int(self.var_pc_step_vel.get())
                gate = int(self.var_pc_step_gate.get())
                prob = int(self.var_pc_step_prob.get())
                sub = int(self.var_pc_step_sub.get())
                self.svd.set_step_info(pat_idx, part_idx, s_idx, notes, vel=vel, gate=gate, prob=prob, substep=sub)
            self.refresh_pc_grid_and_table()
            self.refresh_steps_for_pattern_part()
        else:
            self.on_pc_load_selected_step()

    def on_pc_load_selected_step(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        s_idx = max(0, min(63, int(self.var_pc_sel_step.get()) - 1))
        st = self.svd.get_step_info(pat_idx, part_idx, s_idx)
        if st["notes"]:
            self.var_pc_step_notes.set(", ".join(str(n) for n in st["notes"]))
            n0 = st["notes"][0]
            if 24 <= n0 <= 96:
                self.var_pc_step_root.set(f"{n0}: {midi_note_name(n0)}")
            self.var_pc_step_vel.set(str(st["vel"]))
            self.var_pc_step_gate.set(str(st["gate"]))
            self.var_pc_step_prob.set(str(st["prob"]))
            self.var_pc_step_sub.set(str(st["substep"]))
        self.refresh_pc_grid_and_table()

    def on_pc_select_table_step(self, _event=None):
        sel = self.tree_pc_steps.selection()
        if not sel:
            return
        s_idx = int(sel[0])
        self.var_pc_sel_step.set(str(s_idx + 1))
        if (s_idx // 16) != self.var_pc_page.get():
            self.var_pc_page.set(s_idx // 16)
        self.on_pc_load_selected_step()

    def on_pc_fill_chord_notes(self):
        root_str = self.var_pc_step_root.get().split(":")[0].strip()
        root_n = int(root_str) if root_str.isdigit() else 60
        c_type = self.var_pc_step_chord.get()
        ivs = SH4dSVD.CHORD_TYPES.get(c_type, [0])
        notes = [max(0, min(127, root_n + iv)) for iv in ivs]
        self.var_pc_step_notes.set(", ".join(str(n) for n in notes))

    def on_pc_write_step(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        s_idx = max(0, min(63, int(self.var_pc_sel_step.get()) - 1))
        notes = self._parse_step_notes_entry()
        vel = int(self.var_pc_step_vel.get())
        gate = int(self.var_pc_step_gate.get())
        prob = int(self.var_pc_step_prob.get())
        sub = int(self.var_pc_step_sub.get())
        self.svd.set_step_info(pat_idx, part_idx, s_idx, notes, vel=vel, gate=gate, prob=prob, substep=sub)
        self.refresh_pc_grid_and_table()
        self.refresh_steps_for_pattern_part()
        self.lbl_pc_status.config(text=f"✅ Wrote Step {s_idx+1:02d} on Part {part_idx+1}: Notes={notes}, Vel={vel}, Gate={gate}")

    def on_pc_clear_single_step(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        s_idx = max(0, min(63, int(self.var_pc_sel_step.get()) - 1))
        self.svd.clear_steps_content(pat_idx, part_idx, s_idx + 1, s_idx + 1)
        self.refresh_pc_grid_and_table()
        self.refresh_steps_for_pattern_part()
        self.lbl_pc_status.config(text=f"🗑️ Cleared Step {s_idx+1:02d} on Part {part_idx+1}.")

    def on_pc_toggle_drum_cell(self, drum_note: int, col_0_15: int):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        s_idx = self.var_pc_page.get() * 16 + col_0_15
        vel = int(self.var_pc_step_vel.get())
        gate = int(self.var_pc_step_gate.get())
        prob = int(self.var_pc_step_prob.get())
        added = self.svd.toggle_drum_step_note(pat_idx, s_idx, drum_note, vel=vel, gate=gate, prob=prob)
        self.refresh_pc_grid_and_table()
        self.refresh_steps_for_pattern_part()
        self.lbl_pc_status.config(
            text=f"🥁 {'Added' if added else 'Removed'} Drum Note {drum_note} at Step {s_idx+1:02d} (Part 5 Rhythm)."
        )

    def on_pc_find_empty_pattern(self):
        if not self.svd:
            return
        for i in range(128):
            total_hits = sum(
                1 for p in range(5) for s in range(64) if self.svd.get_step_info(i, p, s)["notes"]
            )
            if total_hits == 0:
                opts = self.cb_pc_pat.cget("values")
                if i < len(opts):
                    self.var_pc_pat.set(opts[i])
                    self.on_pc_select_pattern()
                    self.lbl_pc_status.config(text=f"🔍 Selected first empty pattern slot: {(i//16)+1}-{(i%16)+1:02d}.")
                return
        messagebox.showinfo("Info", "All 128 Pattern slots already contain active steps.")

    def on_pc_save_header(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        self.svd.set_pattern_info(
            pat_idx,
            name=self.var_pc_name.get(),
            tempo=float(self.var_pc_bpm.get()),
            level=int(self.var_pc_lvl.get()),
        )
        self.refresh_patterns()
        self.refresh_pattern_creator_tab()
        self.lbl_pc_status.config(text=f"💾 Updated Pattern {pat_idx+1} Header ('{self.var_pc_name.get()}', {self.var_pc_bpm.get()} BPM).")

    def on_pc_assign_tone(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        info = self.svd.get_pattern_info(pat_idx)
        parts = info["parts"]
        sel_txt = self.var_pc_tone.get()
        if part_idx < 4 and "(#" in sel_txt:
            num_str = sel_txt.split("(#", 1)[1].split(")", 1)[0]
            if num_str.isdigit():
                u_idx = max(0, min(255, int(num_str) - 1))
                parts[part_idx]["msb"] = 87
                parts[part_idx]["lsb"] = u_idx // 128
                parts[part_idx]["pc"] = u_idx % 128
        elif part_idx == 4 and sel_txt.startswith("UK#"):
            num_str = sel_txt[3:5]
            if num_str.isdigit():
                k_idx = max(0, min(63, int(num_str) - 1))
                parts[4]["msb"] = 86
                parts[4]["lsb"] = 0
                parts[4]["pc"] = k_idx
        self.svd.set_pattern_info(pat_idx, parts=parts)
        self.refresh_patterns()
        self.on_pc_select_part()
        self.lbl_pc_status.config(text=f"📌 Assigned '{sel_txt}' to Pattern Part {part_idx+1}.")

    def on_pc_apply_slen(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        slen = max(1, min(64, int(self.var_pc_slen.get())))
        self.svd.set_part_step_length(pat_idx, part_idx, slen)
        self.refresh_steps_for_pattern_part()
        self.lbl_pc_status.config(text=f"📏 Set Part {part_idx+1} Step Length to {slen} steps.")

    def on_pc_quick_slen(self, length_val: int):
        self.var_pc_slen.set(str(length_val))
        self.on_pc_apply_slen()

    def on_pc_clear_part(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        self.svd.clear_steps_content(pat_idx, part_idx, 1, 64)
        self.refresh_pc_grid_and_table()
        self.refresh_steps_for_pattern_part()
        self.lbl_pc_status.config(text=f"🧹 Cleared all 64 steps on Part {part_idx+1}.")

    def on_pc_generate_full_pattern(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        style = self.var_pc_style.get()
        r_key = self.var_pc_key.get()
        scale = self.var_pc_scale.get()
        slen = max(1, min(64, int(self.var_pc_slen.get())))
        auto_t = bool(self.var_pc_auto_tones.get())
        info = self.svd.generate_full_pattern(
            pat_idx,
            style=style,
            root_key=r_key,
            scale_name=scale,
            step_len=slen,
            auto_assign_tones=auto_t,
        )
        self.refresh_patterns()
        self.refresh_pattern_creator_tab()
        self.lbl_pc_status.config(
            text=f"🚀 Generated Full 5-Part Pattern '{info['name']}' ({info['tempo']:.0f} BPM, {r_key} {scale}, {slen} steps) in {info['slot']}!"
        )

    def on_pc_generate_active_part(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        role = self.var_pc_role.get()
        r_key = self.var_pc_key.get()
        scale = self.var_pc_scale.get()
        slen = max(1, min(64, int(self.var_pc_slen.get())))
        dens = int(self.var_pc_density.get())
        self.svd.generate_part_sequence(pat_idx, part_idx, role, r_key, scale, slen, density_pct=dens)
        self.refresh_pc_grid_and_table()
        self.refresh_steps_for_pattern_part()
        self.lbl_pc_status.config(
            text=f"✨ Generated '{role}' ({r_key} {scale}, {slen} steps) on Part {part_idx+1}."
        )

    def on_pc_apply_euclidean(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        k = int(self.var_euc_k.get())
        n = max(1, min(64, int(self.var_euc_n.get())))
        rot = int(self.var_euc_rot.get())
        note = max(0, min(127, int(self.var_euc_note.get())))
        vel = int(self.var_pc_step_vel.get())
        gate = int(self.var_pc_step_gate.get())
        hits = SH4dSVD.compute_euclidean_hits(k, n, rot)
        self.svd.set_part_step_length(pat_idx, part_idx, n)
        self.var_pc_slen.set(str(n))
        for s in range(n):
            if part_idx == 4:
                # Toggle/set this specific drum instrument on Rhythm Part 5 without wiping other drum lanes
                st = self.svd.get_step_info(pat_idx, 4, s)
                cur_n = [x for x in st["notes"] if x != note]
                if hits[s]:
                    cur_n.append(note)
                self.svd.set_step_info(pat_idx, 4, s, cur_n, vel=vel, gate=gate)
            else:
                self.svd.set_step_info(pat_idx, part_idx, s, [note] if hits[s] else [], vel=vel, gate=gate)
        self.refresh_pc_grid_and_table()
        self.refresh_steps_for_pattern_part()
        self.lbl_pc_status.config(text=f"📐 Applied Euclidean E({k}, {n}, rot={rot}) with Note {note} on Part {part_idx+1}.")

    def on_pc_toggle_live_play(self):
        if self.pat_play_running:
            self.pat_play_running = False
            if self.pat_play_after_id:
                try:
                    self.after_cancel(self.pat_play_after_id)
                except Exception:
                    pass
                self.pat_play_after_id = None
            self.btn_pc_play.config(text="▶️ Play Pattern Live (MIDI)")
            self.lbl_pc_status.config(text="⏹️ Stopped live MIDI pattern playback.")
            return
        if not self.svd:
            return
        self.pat_play_running = True
        self.pat_play_step = 0
        self.btn_pc_play.config(text="⏹️ Stop Pattern Playback")
        self._tick_pc_live_play()

    def _tick_pc_live_play(self):
        if not self.pat_play_running or not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        try:
            bpm = max(40.0, min(260.0, float(self.var_pc_bpm.get())))
        except ValueError:
            bpm = 128.0
        step_ms = int(round((60000.0 / bpm) / 4.0))
        gate_ms = max(35, int(step_ms * 0.72))

        # CIHAZLARIM.md SH-4d 5-Part MIDI Channels: Synth 1..4 = Ch 8, 9, 11, 12; Rhythm = Ch 13
        part_channels = [8, 9, 11, 12, 13]
        notes_to_off = []
        for p_i in range(5):
            slen = self.svd.get_part_step_length(pat_idx, p_i)
            s_idx = self.pat_play_step % slen
            st = self.svd.get_step_info(pat_idx, p_i, s_idx)
            ch = part_channels[p_i]
            for n_i, n_val in enumerate(st["notes"]):
                prob = st["probs"][n_i] if n_i < len(st["probs"]) else 100
                if prob >= 100 or random.randint(1, 100) <= prob:
                    vel = st["vels"][n_i] if n_i < len(st["vels"]) else 100
                    self.midi.send_note_on(ch, n_val, vel)
                    notes_to_off.append((ch, n_val))

        if notes_to_off:
            self.after(gate_ms, lambda pairs=notes_to_off: [self.midi.send_note_off(c, n) for c, n in pairs])

        self.pat_play_step = (self.pat_play_step + 1) % 64
        self.pat_play_after_id = self.after(step_ms, self._tick_pc_live_play)

    def on_pc_import_midi_single_part(self):
        if not self.svd:
            return
        m_path = filedialog.askopenfilename(
            title="Select Standard MIDI File (.mid) to Import into Active Part",
            filetypes=[("Standard MIDI Files", "*.mid *.midi"), ("All Files", "*.*")],
        )
        if not m_path:
            return
        try:
            parsed = SH4dSVD.parse_midi_file(m_path)
        except Exception as e:
            messagebox.showerror("MIDI Parse Error", f"Could not read MIDI file:\n{e}")
            return

        streams = parsed["streams"]
        if not streams:
            messagebox.showwarning("Empty MIDI", "No MIDI Note events were found in the selected file.")
            return

        pat_idx = self._get_pc_pat_idx()
        part_idx = self._get_pc_part_idx()
        info = self.svd.get_pattern_info(pat_idx)

        dlg = tk.Toplevel(self)
        dlg.title(f"Import MIDI -> Pattern {info['slot']} Part {part_idx+1}")
        dlg.geometry("540x250")
        dlg.transient(self)
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm,
            text=f"File: {os.path.basename(m_path)}  |  Tempo: {parsed['bpm']:.1f} BPM  |  Total Length: {parsed['total_bars']} bar(s)",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        r_st = ttk.Frame(frm)
        r_st.pack(fill=tk.X, pady=4)
        ttk.Label(r_st, text="Select MIDI Track / Channel:").pack(side=tk.LEFT)
        stream_labels = [s["label"] for s in streams]
        var_sel_stream = tk.StringVar(value=stream_labels[0])
        ttk.Combobox(r_st, textvariable=var_sel_stream, values=stream_labels, state="readonly", width=52).pack(side=tk.LEFT, padx=6)

        r_opt = ttk.Frame(frm)
        r_opt.pack(fill=tk.X, pady=6)
        ttk.Label(r_opt, text=f"Start Bar (1..{parsed['total_bars']}):").pack(side=tk.LEFT)
        var_bar = tk.StringVar(value="1")
        ttk.Spinbox(r_opt, from_=1, to=max(1, parsed["total_bars"]), textvariable=var_bar, width=6).pack(side=tk.LEFT, padx=6)

        ttk.Label(r_opt, text="Transpose (Semitones -24..+24):").pack(side=tk.LEFT, padx=(10, 2))
        var_tr = tk.StringVar(value="0")
        ttk.Spinbox(r_opt, from_=-24, to=24, textvariable=var_tr, width=6).pack(side=tk.LEFT, padx=4)

        var_use_bpm = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm,
            text=f"Also update Pattern Tempo to {parsed['bpm']:.1f} BPM",
            variable=var_use_bpm,
        ).pack(anchor=tk.W, pady=4)

        def do_import():
            sel_lbl = var_sel_stream.get()
            chosen = streams[0]
            for s in streams:
                if s["label"] == sel_lbl:
                    chosen = s
                    break
            bar_val = max(1, int(var_bar.get()))
            tr_val = max(-48, min(48, int(var_tr.get())))
            count = self.svd.import_midi_stream_to_part(
                pat_idx, part_idx, chosen["events"], start_bar_1_indexed=bar_val, transpose_semi=tr_val
            )
            if var_use_bpm.get():
                self.svd.set_pattern_info(pat_idx, tempo=parsed["bpm"])
                self.var_pc_bpm.set(f"{parsed['bpm']:.2f}")
            self.refresh_patterns()
            self.on_pc_select_part()
            self.refresh_steps_for_pattern_part()
            self.lbl_pc_status.config(
                text=f"📥 Imported {count} notes from '{chosen['track_name']}' (Ch {chosen['channel']}) into Part {part_idx+1} (raw MIDI notes kept)."
            )
            dlg.destroy()

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Button(btn_row, text="✅ Import into Active Part", command=do_import).pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=4)

    def on_pc_import_midi_multitrack(self):
        if not self.svd:
            return
        m_path = filedialog.askopenfilename(
            title="Select Multi-Track Standard MIDI File (.mid) to Import into Pattern (Parts 1–5)",
            filetypes=[("Standard MIDI Files", "*.mid *.midi"), ("All Files", "*.*")],
        )
        if not m_path:
            return
        try:
            parsed = SH4dSVD.parse_midi_file(m_path)
        except Exception as e:
            messagebox.showerror("MIDI Parse Error", f"Could not read MIDI file:\n{e}")
            return

        streams = parsed["streams"]
        if not streams:
            messagebox.showwarning("Empty MIDI", "No MIDI Note events were found in the selected file.")
            return

        pat_idx = self._get_pc_pat_idx()
        info = self.svd.get_pattern_info(pat_idx)

        dlg = tk.Toplevel(self)
        dlg.title(f"Multi-Track MIDI Import -> Pattern {info['slot']} ({info['name']})")
        dlg.geometry("680x360")
        dlg.transient(self)
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm,
            text=f"File: {os.path.basename(m_path)}  |  Detected Tempo: {parsed['bpm']:.1f} BPM  |  Length: {parsed['total_bars']} bar(s) ({len(streams)} stream(s))",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, pady=(0, 6))

        top_opt = ttk.Frame(frm)
        top_opt.pack(fill=tk.X, pady=4)
        ttk.Label(top_opt, text=f"Import 4-Bar Window Starting at Bar (1..{parsed['total_bars']}):").pack(side=tk.LEFT)
        var_start_bar = tk.StringVar(value="1")
        ttk.Spinbox(top_opt, from_=1, to=max(1, parsed["total_bars"]), textvariable=var_start_bar, width=6).pack(side=tk.LEFT, padx=6)

        var_apply_bpm = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            top_opt,
            text=f"Set Pattern Tempo to {parsed['bpm']:.1f} BPM",
            variable=var_apply_bpm,
        ).pack(side=tk.LEFT, padx=12)

        map_lf = ttk.LabelFrame(frm, text="Map MIDI Track / Channel Streams -> SH-4d Parts 1–5 (Raw MIDI Notes Preserved)", padding=8)
        map_lf.pack(fill=tk.BOTH, expand=True, pady=6)

        none_lbl = "— None (Keep Existing Part Sequence) —"
        clear_lbl = "— Clear Part —"
        all_choices = [none_lbl, clear_lbl] + [s["label"] for s in streams]

        # Smart pre-selection: check Dawless setup channels (Ch 8, 9, 11, 12, 13/10) first, else sequential melodic + drum channel
        part_titles = [
            "Part 1 (Synth 1 / Ch 8):",
            "Part 2 (Synth 2 / Ch 9):",
            "Part 3 (Synth 3 / Ch 11):",
            "Part 4 (Synth 4 / Ch 12):",
            "Part 5 (Rhythm / Ch 13 & 10):",
        ]
        dawless_pref_ch = [8, 9, 11, 12, 13]
        used_ids = set()
        default_sel = [none_lbl] * 5

        # 1. Match Dawless preferred channels or Ch 10 for drums
        for p_i in range(5):
            pref_c = dawless_pref_ch[p_i]
            for s in streams:
                if s["channel"] == pref_c and s["id"] not in used_ids:
                    default_sel[p_i] = s["label"]
                    used_ids.add(s["id"])
                    break
        if default_sel[4] == none_lbl:
            for s in streams:
                if s["channel"] == 10 and s["id"] not in used_ids:
                    default_sel[4] = s["label"]
                    used_ids.add(s["id"])
                    break
        # 2. Fill remaining Synth Parts 1..4 with remaining non-Ch10 streams
        for p_i in range(4):
            if default_sel[p_i] == none_lbl:
                for s in streams:
                    if s["id"] not in used_ids and s["channel"] not in (10, 13):
                        default_sel[p_i] = s["label"]
                        used_ids.add(s["id"])
                        break

        part_stream_vars = []
        part_tr_vars = []
        for p_i in range(5):
            ttk.Label(map_lf, text=part_titles[p_i], font=("Segoe UI", 8, "bold")).grid(row=p_i, column=0, sticky=tk.W, pady=3, padx=4)
            v_st = tk.StringVar(value=default_sel[p_i])
            cb = ttk.Combobox(map_lf, textvariable=v_st, values=all_choices, state="readonly", width=52)
            cb.grid(row=p_i, column=1, padx=4, pady=3)
            ttk.Label(map_lf, text="Transpose:").grid(row=p_i, column=2, padx=(6, 2), pady=3)
            v_tr = tk.StringVar(value="0")
            ttk.Spinbox(map_lf, from_=-24, to=24, textvariable=v_tr, width=5).grid(row=p_i, column=3, padx=2, pady=3)
            part_stream_vars.append(v_st)
            part_tr_vars.append(v_tr)

        def do_multitrack_import():
            bar_val = max(1, int(var_start_bar.get()))
            total_notes = 0
            parts_touched = 0
            for p_i in range(5):
                choice = part_stream_vars[p_i].get()
                tr_semi = max(-48, min(48, int(part_tr_vars[p_i].get())))
                if choice == none_lbl:
                    continue
                elif choice == clear_lbl:
                    self.svd.clear_steps_content(pat_idx, p_i, 1, 64)
                    parts_touched += 1
                else:
                    for s in streams:
                        if s["label"] == choice:
                            total_notes += self.svd.import_midi_stream_to_part(
                                pat_idx, p_i, s["events"], start_bar_1_indexed=bar_val, transpose_semi=tr_semi
                            )
                            parts_touched += 1
                            break
            if var_apply_bpm.get():
                self.svd.set_pattern_info(pat_idx, tempo=parsed["bpm"])
                self.var_pc_bpm.set(f"{parsed['bpm']:.2f}")
            self.refresh_patterns()
            self.refresh_pattern_creator_tab()
            self.refresh_steps_for_pattern_part()
            self.lbl_pc_status.config(
                text=f"🎼 Imported {total_notes} notes across {parts_touched} part(s) from '{os.path.basename(m_path)}' (Bar {bar_val}..{bar_val+3})."
            )
            dlg.destroy()

        btn_row = ttk.Frame(frm)
        btn_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row, text="🚀 Import Mapped Tracks into Pattern", command=do_multitrack_import).pack(
            side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4)
        )
        ttk.Button(btn_row, text="Cancel", command=dlg.destroy).pack(side=tk.LEFT, padx=4)

    def on_pc_export_pattern_midi(self):
        if not self.svd:
            return
        pat_idx = self._get_pc_pat_idx()
        info = self.svd.get_pattern_info(pat_idx)
        safe_name = info["name"].strip().replace(" ", "_")
        out_p = filedialog.asksaveasfilename(
            title=f"Export Pattern {info['slot']} (All 5 Parts) to Standard MIDI File (.mid)",
            defaultextension=".mid",
            initialfile=f"SH4d_Pat_{info['slot']}_{safe_name}.mid",
            filetypes=[("Standard MIDI File", "*.mid")],
        )
        if not out_p:
            return
        try:
            self.svd.export_pattern_to_midi_file(pat_idx, out_p)
            self.lbl_pc_status.config(text=f"📤 Exported Pattern {info['slot']} (5 Parts, {info['tempo']:.1f} BPM) to {os.path.basename(out_p)}.")
            messagebox.showinfo(
                "MIDI Exported",
                f"Exported Pattern {info['slot']} ('{info['name']}', {info['tempo']:.1f} BPM, 5 Tracks on Ch 8, 9, 11, 12, 13) to:\n{out_p}",
            )
        except Exception as e:
            messagebox.showerror("MIDI Export Error", f"Failed to export MIDI file:\n{e}")


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
