# Roland SH-4d `.SVD` Editor, Librarian & Real-Time MIDI Synth Controller

An open-source **offline `.SVD` backup editor / patch librarian** and **real-time MIDI CC/PC synth controller** for the **Roland SH-4d** synthesizer (`SVD5` / `JP-M` binary database format).

Built with **pure Python 3** (`tkinter` + `ctypes` WinMM MIDI) — **zero external dependencies (`pip install` not required)**.

> 📖 **[Read the Complete User Manual (`USER_MANUAL.md`)](USER_MANUAL.md)** for step-by-step instructions on Backing Up / Restoring `SH4d.SVD`, Real-Time MIDI Control, Sound Editing, and Pattern / Part / Step / Multi-Step Copy & Paste.

---

## ✨ Features

### 1. 🎛️ Live Real-Time Synth Control (MIDI CC & Program Change)
* **Zero-dependency Windows MIDI Out (`winmm.dll`)** — connects directly to your SH-4d over USB-C MIDI or 5-pin DIN MIDI interface.
* **31 Live Real-Time CC Sliders** across 4 sections:
  * **Oscillator & Mixer:** `OSC Sliders 1–4` (`CC#85–88`), `Pitch` (`CC#28`), `Timbre` (`CC#77`), `Part Level` (`CC#7`), `Part Pan` (`CC#10`)
  * **Filter & Filter ADSR:** `Cutoff` (`CC#74`), `Resonance` (`CC#71`), `Drive` (`CC#90`), `Env Depth` (`CC#81`), `HPF` (`CC#79`), `Filter Attack/Decay/Sustain/Release` (`CC#82, 83, 29, 31`)
  * **Amp ADSR & LFO:** `Amp Attack/Decay/Sustain/Release` (`CC#73, 75, 30, 72`), `LFO Rate` (`CC#16`), `LFO Pitch/Filter/Amp Depth` (`CC#18, 19, 20`)
  * **Effects & Expression:** `Mod Wheel` (`CC#1`), `Portamento` (`CC#5`), `Expression` (`CC#11`), `Reverb/Chorus/Delay Send` (`CC#91, 93, 94`)
* **1-Click Live Patch Audition:** Send `Bank Select MSB/LSB + Program Change` directly to switch User Patches (`U01-01`..`U16-16`) or push `.SVD` patch parameters live over MIDI CC.

### 2. 🎹 User Synth Patches & Sound Editor (`PATc` — 256 Slots)
* View and edit all **256 User Synth Patches** (`U01-01` to `U16-16`, `2,048 bytes` each).
* Edit **Patch Name**, **Oscillator Model** (`SH-4d`, `SH-3D`, `CHORD`, `SH-101`, `JUNO-106`, `CROSS FM`, `SYNC`, `DRAWING`, `WAVETABLE`, `RING`, `PCM`, `STEP / HARMONIC`), **Patch Level**, and **MFX Type**.
* Edit **OSC Mixer Sliders 1–4** (`0–127`), **Filter Cutoff / Resonance / Env Depth** (`0–1023`), **Filter ADSR** (`0–1023`), **Amp ADSR** (`0–1023`), and **LFO Shape / Rate / Depths**.
* **Swap**, **Copy**, and **Export / Import** individual `.sh4d_patch` files (`2,048 bytes`).

### 3. 🎵 User Patterns Librarian, 64-Step Sequencer Inspector & Copy/Paste (`PRFd` — 128 Slots)
* Inspect and edit all **128 User Patterns** (`1-01` to `8-16`, `18,988 bytes` each).
* Edit **Pattern Name**, **Tempo (`BPM`)**, **Pattern Level**, and **Part 1–5 Sound Assignments (`MSB / LSB / PC`)**, **Part Levels**, and **Part Pan**.
* Automatically resolves User Synth Patch names (`U01-01`..`U16-16`) and User Rhythm Kit names (`Kit #01`..`Kit #64`) used inside each pattern.
* **64-Step Sequencer Inspector:** Inspect all 64 steps (`Step 1..64`) for any Part (`Part 1–4` Synth or `Part 5` Rhythm), displaying up to 8 polyphonic MIDI notes per step, Velocity, Gate Time, Probability %, and Part Step Length (`1–64`).
* **Full Implementation of SH-4d Manual *"Copying and pasting the content of patterns"* (`[SHIFT] + [13] COPY`):**
  1. **`PATTERN` Mode:** Copy or Swap an entire pattern across any of the 128 slots (`18,988 bytes`).
  2. **`PART` Mode:** Copy a single Part's 64-step sequence (`3,328 bytes` at `0x092C + part*3328`) and sequencer configuration (`24 bytes` at `0x08B4 + part*24`) to any destination Pattern and Part — either **without overwriting Tone/Mixer** (matching the SH-4d hardware behavior) or **including Tone/Mixer (`88 bytes` at `0x003A + part*88`)** via checkbox.
  3. **`STEP` Mode:** Copy any single step (`1–64`, `52 bytes`) to any target step in any Pattern/Part.
  4. **`MULTI-STEP` Mode:** Copy any range of steps (`Start Step .. End Step`) to any destination starting step (`Dest Step`), or clear a range of steps.

### 4. 🥁 User Rhythm Kits & Per-Drum Pitch/Filter Editor (`RHYa` + `RHIa` — 64 Kits × 26 Drum Keys)
* Edit all **64 User Rhythm Kits** (`Kit #01` to `Kit #64`).
* Inspect and edit each of the **26 Drum Instruments (`MIDI Notes 36 C2 .. 61 C#4`)** inside any kit:
  * **Coarse Pitch (`-48` to `+48` semitones)**
  * **Instrument Level (`0–127`)** & **Pan (`-64 L` to `+63 R`)**
  * **Filter Cutoff (`0–1023`)** & **Filter Resonance (`0–127`)**
  * **Amp Decay (`0–1023`)** & **Wave ID (`Layer 1`)**
* **Batch Kit Pitch Shift:** Transpose all 26 drum sounds in a kit by `±N` semitones in one click, and copy kits across slots to create real-time Program Change kit snapshots.

---

## 📦 Reverse-Engineered Roland `SH4d.SVD` (`SVD5 / JP-M`) Binary Specification

The Roland SH-4d backup file (`SH4d.SVD`, `4,385,916 bytes`) is an **unencrypted** `SVD5` container with model identifier `JP-M`. Its directory header (`0x000010`–`0x00006F`) defines 6 sections, each starting with a 16-byte sub-header (`uint32 count, uint32 item_size, uint32 header_size=16, uint32 reserved=0`):

| Section | Model | File Offset | Length (Bytes) | Count | Item Size | Description |
| :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **`PRFd`** | `JP-M` | `0x000070` | `2,430,480` | `128` | `18,988` (`0x4A2C`) | **User Patterns (`1-01`..`8-16`)** — Name (`0x00`), Level (`0x10`), Tempo×100 (`0x12`), 5 Parts at `0x3A + p*88` |
| **`PATc`** | `JP-M` | `0x251680` | `524,304` | `256` | `2,048` (`0x0800`) | **User Synth Patches (`U01-01`..`U16-16`)** — OSC Model (`0x08`), Name (`0x10`), Level (`0x24`), 4 Partials |
| **`SYSd`** | `JP-M` | `0x2D1690` | `1,436` | `1` | `1,420` (`0x058C`) | **System Settings** — Global MIDI, Clock, System FX |
| **`RHYa`** | `JP-M` | `0x2D1C2C` | `213,008` | `64` | `3,328` (`0x0D00`) | **User Rhythm Kits (Mixer/Common)** — Name (`0x00`), Kit Level (`0x14`), 88×20B key mixer at `0xA0` |
| **`RHIa`** | `JP-M` | `0x305C3C` | `1,216,528` | `64` | `19,008` (`0x4A40`) | **User Rhythm Instruments** — 88×216B key synth engines (Slots `15..40` = MIDI Notes `36..61`) |
| **`DIFa`** | `JP-M` | `0x42EC4C` | `48` | `1` | `32` (`0x0020`) | **Device Metadata Block** |

---

## 🚀 Installation & Usage

### Option 1: Standalone Windows Application (Recommended — No Python Required)
Anyone on Windows 10/11 can download and run the application immediately without installing Python:
1. Go to the **[GitHub Releases Page](https://github.com/antmen71/roland-sh4d-svd-editor/releases/latest)**.
2. Download either:
   * **`SH4d_SVD_Editor.exe`** *(Standalone single-file Windows executable)*, or
   * **`Roland-SH4d-SVD-Editor-Windows-x64.zip`** *(Complete bundle including `SH4d_SVD_Editor.exe`, `USER_MANUAL.md`, and source script)*.
3. Double-click **`SH4d_SVD_Editor.exe`** to launch the app, then click **`📂 Open .SVD...`** in the top-left corner to load your `SH4d.SVD` backup file.

### Option 2: Run from Python Source (`Python 3.8+`, Zero `pip` Dependencies)
```bash
git clone https://github.com/antmen71/roland-sh4d-svd-editor.git
cd roland-sh4d-svd-editor
python sh4d_svd_editor.py path/to/SH4d.SVD
```
*(On Windows with Python installed, you can also double-click `run_editor.bat`).*

### Print Console Summary of an `.SVD` File (CLI)
```bash
python sh4d_svd_editor.py path/to/SH4d.SVD --summary
```

---

## 📄 License
MIT License
