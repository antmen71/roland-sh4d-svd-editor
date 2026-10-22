# 📖 Roland SH-4d `.SVD` Editor, Librarian & Real-Time MIDI Synth Controller — User Manual

Welcome to the official user manual for the **Roland SH-4d `.SVD` Editor, Librarian & Real-Time MIDI Synth Controller**. This application provides a complete desktop workflow for managing your Roland SH-4d synthesizer—combining an **offline `.SVD` backup editor, patch/pattern librarian, and 64-step sequencer inspector** with a **real-time Windows MIDI CC & Program Change synth controller**.

> [!CAUTION]
> **⚠️ DISCLAIMER OF WARRANTY & LIMITATION OF LIABILITY (USE AT YOUR OWN RISK)**
> * **Unofficial Tool:** This application is an independent, unofficial community tool created via reverse-engineering and is **NOT affiliated with, endorsed, or supported by Roland Corporation**.
> * **No Warranty & Zero Liability:** This software is provided **"AS IS"**, without warranty of any kind. By using this software, you agree that **you do so entirely at your own risk**. In no event shall the author(s) or contributors be held liable for any direct, indirect, incidental, or consequential damages—including hardware damage, bricked or malfunctioning synthesizers, repair costs, or loss of data/patches/patterns—arising from the use of this software.
> * **Always Backup First:** Always keep a separate, unmodified copy of your original `SH4d.SVD` file in a safe folder on your computer before restoring any edited file to your Roland SH-4d.

---

## 📑 Table of Contents
1. [Overview & System Requirements](#1-overview--system-requirements)
2. [Hardware Workflow: Backing Up & Restoring `SH4d.SVD` on the Roland SH-4d](#2-hardware-workflow-backing-up--restoring-sh4dsvd-on-the-roland-sh-4d)
3. [Workspace Layout, Top Toolbar & Resizable Panels](#3-workspace-layout-top-toolbar--resizable-panels)
4. [Tab 1: Live Real-Time Synth Control (MIDI CC & Program Change)](#4-tab-1-live-real-time-synth-control-midi-cc--program-change)
5. [Tab 2: User Synth Patches & Sound Editor (`PATc` — 256 Slots)](#5-tab-2-user-synth-patches--sound-editor-patc--256-slots)
6. [Tab 3: User Patterns, 64-Step Sequencer Inspector & Copy/Paste (`PRFd` — 128 Slots)](#6-tab-3-user-patterns-64-step-sequencer-inspector--copypaste-prfd--128-slots)
   - [How to Copy an Entire Pattern (`PATTERN` Mode)](#a-how-to-copy-or-swap-an-entire-pattern-pattern-mode)
   - [How to Copy a Single Part's Sequence (`PART` Mode)](#b-how-to-copy-a-single-parts-sequence-part-mode)
   - [How to Copy a Single Step or Range of Steps (`STEP` & `MULTI-STEP` Mode)](#c-how-to-copy-steps-or-bars-step--multi-step-mode--eg-steps-116-to-1732)
7. [Tab 4: Rhythm Kits & Per-Drum Pitch/Filter Editor (`RHYa` + `RHIa` — 64 Kits)](#7-tab-4-rhythm-kits--per-drum-pitchfilter-editor-rhya--rhia--64-kits)
8. [Command-Line Interface (CLI) Usage](#8-command-line-interface-cli-usage)
9. [Technical Reference: `SVD5` (`JP-M`) Binary Specification](#9-technical-reference-svd5-jp-m-binary-specification)

---

## 1. Overview & System Requirements

* **Standalone Windows App (`SH4d_SVD_Editor.exe`):** Pre-built single-file Windows 10/11 executable available on the [GitHub Releases page](https://github.com/antmen71/roland-sh4d-svd-editor/releases/latest) — **no Python installation required**.
* **Zero External Dependencies (Python Source):** Can also run directly from source (`sh4d_svd_editor.py`) on standard **Python 3.8+** using built-in `tkinter` (GUI) and Windows native `winmm.dll` via `ctypes` (real-time MIDI Out). No `pip install` packages are required.
* **Safe `.SVD` Editing:** Every time you click **`💾 Save (.bak)`**, the editor automatically creates a `.SVD.bak` backup copy before writing changes, and preserves all untouched engine bytes bit-for-bit.

### Installation & Launching the Application

#### Option A: Standalone Windows Executable (No Python Needed)
1. Download **`SH4d_SVD_Editor.exe`** (or **`Roland-SH4d-SVD-Editor-Windows-x64.zip`**) from [GitHub Releases](https://github.com/antmen71/roland-sh4d-svd-editor/releases/latest).
2. Double-click **`SH4d_SVD_Editor.exe`** to open the program.
3. Click **`📂 Open .SVD...`** in the top-left toolbar to open your `SH4d.SVD` file.

#### Option B: Running from Python Source
```bash
python sh4d_svd_editor.py path/to/SH4d.SVD
```
*(On Windows, you can also double-click `run_editor.bat` or launch `python sh4d_svd_editor.py` without arguments and click **`📂 Open .SVD...`**).*

---

## 2. Hardware Workflow: Backing Up & Restoring `SH4d.SVD` on the Roland SH-4d

To edit your patterns, patches, and rhythm kits offline in `.SVD` format and load them back into your Roland SH-4d:

### Exporting a Backup from the SH-4d to Your Computer
1. Connect the **Roland SH-4d** to your computer via USB-C.
2. Turn on the SH-4d while holding down the **`[MENU]`** button (or go to **`MENU` -> `UTILITY` -> `STORAGE MODE`**) to mount the SH-4d internal drive on your computer, or perform a **`BACKUP`** first in **`MENU` -> `UTILITY` -> `BACKUP`**.
3. Open the mounted USB drive on your computer and locate the backup file inside `ROLAND/BACKUP/SH4d.SVD` (approx. `4,385,916 bytes`).
4. Copy `SH4d.SVD` to your computer (e.g., `Downloads/SH4d.SVD`) and open it in this editor.

### Restoring Your Edited `SH4d.SVD` Back to the SH-4d
1. After editing in the app, click **`💾 Save (.bak)`** (or **`💾 Save As...`**).
2. Copy the saved `SH4d.SVD` file back into the `ROLAND/BACKUP/` folder on the SH-4d USB storage drive.
3. Eject the USB drive safely on your computer, then execute **`RESTORE`** on the SH-4d (**`MENU` -> `UTILITY` -> `RESTORE`**).

---

## 3. Workspace Layout, Top Toolbar & Resizable Panels

### Top Toolbar Controls
| Control | Description |
| :--- | :--- |
| **`📂 Open .SVD...`** | Opens any Roland SH-4d `.SVD` backup file (`SVD5` / `JP-M` format). |
| **`💾 Save (.bak)`** | Saves all changes to the currently loaded `.SVD` file and automatically creates a `.SVD.bak` safety backup. |
| **`💾 Save As...`** | Saves the modified `.SVD` database to a new file path. |
| **`⚡ Live MIDI Out`** | Selects the active Windows MIDI Output port (e.g., `SH-4d`, `UMC1820 MIDI Out`, or `MOTU MIDI Express XT`). |
| **`Target Ch`** | Selects the active MIDI Channel (`1–16`) for real-time MIDI CC sliders, Program Change, and Test Note auditioning. |
| **`🎹 Test Note`** | Sends a 450 ms triad chord (`C3 - G3 - C4`) on the selected `Target Ch` to immediately audition your sound edits on the hardware. |

### Resizable Split Panels
* Every multi-column tab (**User Patterns**, **User Synth Patches**, and **Rhythm Kits**) uses **draggable split-pane dividers (`PanedWindow`)**.
* Simply **click and drag the vertical raised divider bars** left or right to widen or narrow any table or inspector panel.
* Wide tables also include both **vertical and horizontal scrollbars** at the bottom so no editor panel is ever pushed off-screen.

---

## 4. Tab 1: Live Real-Time Synth Control (MIDI CC & Program Change)

This tab lets you control the Roland SH-4d's synthesis engine **in real time** over USB-C MIDI or 5-pin DIN MIDI without touching `.SVD` files.

### Quick Live User Patch Select (Program Change)
* Enter a **User Patch Slot (`1..256`)** and click **`🚀 Send Program Change to SH-4d`**:
  * For Synth Parts (`Ch 1–9, 11–12, 14–16`), sends `Bank Select MSB = 87`, `LSB = 0` (Slots `1–128` = `U01-01..U08-16`) or `LSB = 1` (Slots `129–256` = `U09-01..U16-16`), plus `Program Change 0–127`.
  * For Rhythm Parts (`Ch 10` or `Ch 13`), sends `Bank Select MSB = 86, LSB = 0` and `Program Change 0–63` (`Kit #01..#64`).
* Click **`📤 Send All Current Sliders`** to transmit the positions of all 31 CC sliders to the active MIDI channel at once.

### Complete Map of the 31 Real-Time MIDI CC Sliders

| Section | Parameter Name | MIDI CC# | Value Range |
| :--- | :--- | :---: | :---: |
| **1. Oscillator & Mixer** | `OSC Slider 1 (Osc 1 Level)` | `CC#85` | `0–127` |
| | `OSC Slider 2 (Osc 2 Level)` | `CC#86` | `0–127` |
| | `OSC Slider 3 (Osc 3 Level)` | `CC#87` | `0–127` |
| | `OSC Slider 4 (Osc 4 / Sub)` | `CC#88` | `0–127` |
| | `OSC Pitch (Coarse/Fine)` | `CC#28` | `0–127` (`64` = Center) |
| | `OSC Timbre / Mod Depth` | `CC#77` | `0–127` |
| | `Part Level (Volume)` | `CC#7` | `0–127` |
| | `Part Pan (L/R)` | `CC#10` | `0–127` (`64` = Center) |
| **2. Filter & Filter ADSR** | `Filter Cutoff` | `CC#74` | `0–127` |
| | `Filter Resonance` | `CC#71` | `0–127` |
| | `Filter Drive` | `CC#90` | `0–127` |
| | `Filter Env Depth` | `CC#81` | `0–127` (`64` = Center) |
| | `HPF Cutoff` | `CC#79` | `0–127` |
| | `Filter Attack` | `CC#82` | `0–127` |
| | `Filter Decay` | `CC#83` | `0–127` |
| | `Filter Sustain` | `CC#29` | `0–127` |
| | `Filter Release` | `CC#31` | `0–127` |
| **3. Amp ADSR & LFO** | `Amp Attack` | `CC#73` | `0–127` |
| | `Amp Decay` | `CC#75` | `0–127` |
| | `Amp Sustain` | `CC#30` | `0–127` |
| | `Amp Release` | `CC#72` | `0–127` |
| | `LFO Rate (Speed)` | `CC#16` | `0–127` |
| | `LFO Pitch Depth` | `CC#18` | `0–127` (`64` = Center) |
| | `LFO Filter Depth` | `CC#19` | `0–127` (`64` = Center) |
| | `LFO Amp Depth` | `CC#20` | `0–127` (`64` = Center) |
| **4. Effects & Expression** | `Modulation Wheel` | `CC#1` | `0–127` |
| | `Portamento Time` | `CC#5` | `0–127` |
| | `Expression` | `CC#11` | `0–127` |
| | `Reverb Send Level` | `CC#91` | `0–127` |
| | `Chorus Send Level` | `CC#93` | `0–127` |
| | `Delay Send Level` | `CC#94` | `0–127` |

---

## 5. Tab 2: User Synth Patches & Sound Editor (`PATc` — 256 Slots)

Displays all **256 User Synth Patches** (`U01-01` through `U16-16`, `2,048 bytes` per patch).

### Editing Sound Parameters in `.SVD`
Select any patch in the left table to load its parameters into the right-hand **Synth Patch Sound & Parameter Editor**:
* **Patch Name:** Up to 16 ASCII characters.
* **OSC Model ID:** Choose from all 12 SH-4d Oscillator Models:
  * `0: SH-4d`, `1: SH-3D`, `2: CHORD`, `3: SH-101`, `4: JUNO-106`, `5: CROSS FM`, `6: SYNC`, `7: DRAWING`, `8: WAVETABLE`, `9: RING`, `10: PCM`, `11: STEP / HARMONIC`
* **Patch Lvl (`0–127`) & MFX Type (`0–93`):** Overall patch volume and insert multi-effect algorithm.
* **OSC Mixer Sliders 1–4 (`S1..S4`, `0–127`):** Stored oscillator mixer levels for Partials 1–4.
* **Filter & Filter ADSR (`0–1023`):** High-resolution 10-bit values for `Cutoff`, `Resonance`, `Env Depth`, `F-Atk`, `F-Dec`, `F-Sus`, and `F-Rel`.
* **Amp Envelope ADSR (`0–1023`):** High-resolution 10-bit values for `A-Atk`, `A-Dec`, `A-Sus`, and `A-Rel`.
* **LFO Section:** `Shape (0–5)`, `Rate (0–1023)`, `Pitch Dep`, `Filter Dep`, and `Amp Dep`.

Click **`✅ Apply All Sound Parameters to .SVD Patch`** to commit your edits to the patch in memory.

### Live Hardware Sync Buttons
* **`⚡ Load This Patch on SH-4d Live (MIDI PC)`:** Sends the exact `MSB=87, LSB, PC` message for the selected row so the SH-4d immediately switches to that User Patch.
* **`⚡ Push Patch Parameters to SH-4d Live (MIDI CC)`:** Converts the `.SVD` patch's 10-bit (`0–1023`) filter/envelope/LFO values into 7-bit (`0–127`) MIDI CC messages and transmits them live to the SH-4d so you can hear your `.SVD` parameter edits in real time!

### Patch Librarian Actions
* **`🔀 Swap` / `📋 Copy`:** Enter a target slot (`1..256`) to swap or duplicate patches across banks.
* **`📤 Export (.sh4d_patch)` / `📥 Import (.sh4d_patch)`:** Save individual `2,048-byte` patches as standalone `.sh4d_patch` files to share or archive on disk, and import them into any slot.

---

## 6. Tab 3: User Patterns, 64-Step Sequencer Inspector & Copy/Paste (`PRFd` — 128 Slots)

This tab manages all **128 User Patterns** (`1-01` to `8-16`, `18,988 bytes` each) and implements the complete **"Copying and pasting the content of patterns"** functionality from the Roland SH-4d Reference Manual (`[SHIFT] + [13] (COPY)`).

### Panel Overview
1. **Left Panel (`128 User Patterns`):** Lists all 128 pattern slots (`1-01` .. `8-16`), Pattern Name, Tempo (`BPM`), and the resolved Patch/Kit names assigned to **Part 1 (`Synth 1`)**, **Part 2 (`Synth 2`)**, **Part 3 (`Synth 3`)**, **Part 4 (`Synth 4`)**, and **Part 5 (`Rhythm`)**.
2. **Middle Panel (`Sequencer Inspector & Copy/Paste`):**
   * **`Inspect Part` Dropdown:** Switch between `1: Synth 1`, `2: Synth 2`, `3: Synth 3`, `4: Synth 4`, and `5: Rhythm` to view all **64 sequencer steps** for that part.
   * **`Step Len` (`1–64`) + `Set Len`:** View or change the active step loop length (`1` to `64` steps) for the selected part.
   * **64-Step Table:** Displays `Step #` (with `*` indicating active note steps), up to 8 polyphonic MIDI notes per step (e.g., `A4 (69)`), `Velocity`, `Gate`, and `Probability %`.
3. **Right Panel (`Selected Pattern & Tone Editor`):** Edit Pattern Name, Tempo (`BPM`), Pattern Level (`0–127`), and the 5 Parts' Sound & Mixer settings (`MSB`, `LSB`, `PC`, `Level`, `Pan`), then click **`✅ Apply Pattern Changes`**.

---

### 📋 Step-by-Step Guide: Copying & Pasting Pattern Content (All 4 Modes)

> **Tip on Pattern Slot Format:** In all target/destination pattern fields (**`Dest Pat`**, **`Target Pattern`**), you can enter **either** the SH-4d bank-number format (e.g., **`1-03`**, **`1-16`**, **`2-01`**) **or** a flat number from **`1` to `128`** (e.g., **`3`**, **`16`**, **`17`**).

#### A. How to Copy or Swap an Entire Pattern (`PATTERN` Mode)
Copies all 5 parts, sequences, tones, tempo, and mixer settings of a pattern to another slot:
1. Click the source pattern in the left table (e.g., **`1-03`**).
2. In the right-hand panel (**Selected Pattern & Tone Editor**), find **`Target Pattern (e.g. 1-16 or 16)`** at the bottom and enter the destination slot (e.g., **`1-04`**).
3. Click **`📋 Copy Entire Pattern to Target`** (or **`🔀 Swap Entire Pattern with Target`** to exchange their positions).

#### B. How to Copy a Single Part's Sequence (`PART` Mode)
Copies only one part's 64-step sequence (e.g., copying `Synth 2` from Pattern `1-03` to `Synth 3` in Pattern `1-05`):
1. Select the source pattern in the left table (e.g., **`1-03`**).
2. At the top of the middle panel, set **`Inspect Part`** to the part you want to copy from (e.g., **`2: Synth 2 (M09)`**).
3. In middle box **`1. Copy/Paste PART Sequence ([SHIFT]+[13] -> PART)`**:
   * Set **`Dest Pat`** to the destination pattern (e.g., **`1-05`** or **`1-03`**).
   * Set **`Part`** to the destination part (e.g., **`3: Synth 3 (M11)`**).
   * **Optional Checkbox (`Also copy Part Tone & Mixer`):**
     * Leave **unchecked** (default, matching the SH-4d hardware manual) to copy **only the sequence notes/steps** without changing the destination part's patch/tone.
     * Check this box if you want to copy **both the sequence AND the synth patch/mixer settings** (`MSB/LSB/PC/Lvl/Pan`).
4. Click **`📋 Copy Selected Part Sequence -> Dest Pattern/Part`**.

#### C. How to Copy Steps or Bars (`STEP` & `MULTI-STEP` Mode — e.g., Steps `1–16` to `17–32`)
Copies a single step (`Start == End`) or a range of steps (`Start .. End`) to any destination step:

**Example: Copying Steps `1–16` to Steps `17–32` in Pattern `1-03`:**
1. Click **`1-03`** in the left **128 User Patterns** table.
2. At the top of the middle panel, select the part in **`Inspect Part`** (e.g., **`2: Synth 2 (M09)`**).
3. Go to the bottom box **`2. Copy/Paste STEP or MULTI-STEP`**:
   * Set **`Source Steps — Start (1-64)`** to **`1`**.
   * Set **`End (1-64)`** to **`16`**.
     *(Shortcut: You can also click Step `01` and Shift-click Step `16` in the 64-step table to fill `Start = 1` and `End = 16` automatically!)*
   * Confirm **`Dest Pat`** is **`1-03`** and **`Part`** is **`2: Synth 2 (M09)`** (these auto-fill when you select the pattern and part).
   * Set **`Dest Step`** to **`17`**.
4. Click **`📋 Paste Step(s)`**.
   * The editor copies the 16 steps (`1..16`) into **`17..32`**.
   * If the part's **`Step Len`** was shorter than `32` (for example, `16`), the editor **automatically expands `Step Len` to `32`** so your newly pasted bars play back on the SH-4d.
   * The 64-step table **automatically scrolls to and highlights Steps `17..32`** so you immediately see the pasted notes on screen.
5. Click **`💾 Save (.bak)`** in the top toolbar to save your changes to the `.SVD` file.

*(To erase a range of steps back to empty rests, set `Start` and `End` and click **`🧹 Clear Source Step(s)`**).*

---

## 7. Tab 4: Rhythm Kits & Per-Drum Pitch/Filter Editor (`RHYa` + `RHIa` — 64 Kits)

The Roland SH-4d Rhythm Part (`Ch 10` / `Ch 13`) contains **26 independent drum instruments per kit** (`MIDI Notes 36 C2` through `61 C#4`), each with its own pitch, level, pan, filter, and envelope. Because the SH-4d hardware does not assign a real-time MIDI CC to individual drum pitches, this tab allows you to edit individual drum pitches or batch-transpose entire kits inside the `.SVD` file.

### Editing a Single Drum Instrument
1. Select one of the **64 User Rhythm Kits (`#01..#64`)** in the left panel.
2. Select one of the **26 Drum Instruments (`#1 BD1 C2` .. `#26 Perc C#4`)** in the middle table.
3. In the right-hand **Selected Drum Sound** panel, edit:
   * **`🎯 Pitch (-48 .. +48 Semitones)`**
   * **`🔊 Level (0 .. 127)`**
   * **`↔️ Pan (-64 L .. +63 R)`**
   * **`🎛️ Filter Cutoff (0 .. 1023)`** & **`⚡ Filter Resonance (0 .. 127)`**
   * **`⏳ Amp Decay (0 .. 1023)`** & **`🌊 Wave ID (Layer 1)`**
4. Click **`✅ Apply to This Drum Sound`**.

### Creating Transposed Kit Variations for Live MIDI Program Change
1. Select a source kit (e.g., `Kit #01`) and copy it to an empty slot (e.g., `Target Slot: 7`) using **`📋 Copy Kit to Target Slot`**.
2. Select `Kit #07`, enter a **`Semitone Offset`** (e.g., `+3` or `-2`) under **Batch Kit Pitch Shift**, and click **`🚀 Shift Pitch of Entire Kit`**.
3. Save and restore your `.SVD` file—now you can switch drum pitches in real time during a live set by sending **MIDI Program Change (`MSB=86, LSB=0, PC=0..63`)** to the SH-4d Rhythm channel!

---

## 8. Command-Line Interface (CLI) Usage

In addition to the desktop GUI, `sh4d_svd_editor.py` includes a full CLI for batch inspection and automation:

```bash
# Print a complete summary of Sections, Active Patterns, User Synth Patches, and Rhythm Kits
python sh4d_svd_editor.py SH4d.SVD --summary

# Rename a User Synth Patch (Slot 1..256)
python sh4d_svd_editor.py SH4d.SVD --rename-patch 1 "My Lead"

# Shift the pitch of a single drum key (1..26) in a Rhythm Kit (1..64)
python sh4d_svd_editor.py SH4d.SVD --kit-drum-pitch 1 1 -3

# Batch-shift all 26 drum instruments in a Rhythm Kit (1..64) by +5 semitones
python sh4d_svd_editor.py SH4d.SVD --kit-pitch-shift 1 5
```

---

## 9. Technical Reference: `SVD5` (`JP-M`) Binary Specification

The Roland SH-4d `.SVD` file (`4,385,916 bytes`) is an unencrypted `SVD5` container with model tag `JP-M`.

### Top-Level Section Directory (`0x000010` – `0x00006F`)

| Section Tag | File Offset | Length (Bytes) | Item Count | Item Size (Bytes) | Description |
| :---: | :---: | :---: | :---: | :---: | :--- |
| **`PRFd`** | `0x000070` | `2,430,480` | `128` | `18,988` (`0x4A2C`) | **User Patterns (`1-01`..`8-16`)** |
| **`PATc`** | `0x251680` | `524,304` | `256` | `2,048` (`0x0800`) | **User Synth Patches (`U01-01`..`U16-16`)** |
| **`SYSd`** | `0x2D1690` | `1,436` | `1` | `1,420` (`0x058C`) | **System Settings** |
| **`RHYa`** | `0x2D1C2C` | `213,008` | `64` | `3,328` (`0x0D00`) | **User Rhythm Kits (Common & 88×20B Key Mixer)** |
| **`RHIa`** | `0x305C3C` | `1,216,528` | `64` | `19,008` (`0x4A40`) | **User Rhythm Instruments (88×216B Key Synth Engines)** |
| **`DIFa`** | `0x42EC4C` | `48` | `1` | `32` (`0x0020`) | **Device Metadata Block** |

### Internal Layout of a `PRFd` Pattern Record (`18,988 bytes`)
* `0x0000..0x000F` (`16B`): ASCII Pattern Name
* `0x0010` (`1B`): Pattern Level (`0–127`)
* `0x0012..0x0013` (`uint16 LE`): Tempo $\times 100$ (e.g., `12000` = `120.00 BPM`)
* `0x003A + part * 88` (`5 × 88 = 440B`): Part 1–5 Tone & Mixer Header (`MSB` at `+0`, `LSB` at `+1`, `PC` at `+2`, `Level` at `+4`, `Pan` at `+5`)
* `0x08B4 + part * 24` (`5 × 24 = 120B`): Part 1–5 Sequencer Setup (`Step Length - 1` at `+0`)
* `0x092C + part * 3328 + step * 52` (`5 parts × 64 steps × 52B = 16,640B`, ending at `0x4A2C`):
  * `+0..+7` (`8B`): 8 Polyphonic MIDI Note slots (`0..127`, `0xFF` = empty)
  * `+8..+15` (`8B`): 8 Gate Time slots (`0x50 = 80` default)
  * `+16..+23` (`8B`): 8 Velocity slots (`0x50 = 80` default)
  * `+24..+31` (`8B`): 8 Sub-step slots (`0xFF` = off)
  * `+32..+39` (`8B`): 8 Probability slots (`0x64 = 100%` default)
  * `+40..+51` (`12B`): Step Motion / Modulation data
