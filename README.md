# journal-clip — what this is

A **small** Sesefus command. Not the host. Not Circadia. Not the dashboard.

You speak. It keeps **text**. It destroys the **wav**.

Zig 0.16 only. `Clip.bat` always runs `zig build` first.

---

## UI (launcher over Clip.bat)

Double-click `Clip-ui.bat`. Same folder as `Clip.bat`.

1. Startup reloads the **last folder** (`%USERPROFILE%\.sesefus\clip-ui.json`). Missing folder → dialog. **change** picks another. Not written into `clip-config.json`.
2. Dropdown is WinMM capture devices. Default pick is the **Maono USB** mic if it is present.
3. **Record** clicks: 1=30s, 2=60s, 3=90s, 4=120s. Wait a beat after the last click, then it starts. **Stop / send** ends early.
4. Waveform is a bipolar envelope (DC bias stripped so gain is true amplitude). Whole-second timer sits top-right of that widget. Look is house **negentropic-blue**.
5. Tape is on the **right**: entry count, scroll, collapsible groups. Slim profiles `.d` day · `.i` interval · `.n` domain · `.g` intent · `.m` magnitude. Boundaries are probed from this folder’s takes. Click a profile to preview the same tape under different category rules.
6. Whisper runs **inside this window**. Transcript lands on the plate. No cmd popup. No warning dialog. Silence warns on the amber line.
7. Temp wav is shredded after the take.

No dashboard. No extra server. Close the window to end the session.

---

## Compact widget (`zig build` → `zig-out\bin\journal-clip-widget.exe`)

A 300×132 always-on-top pane. Native Win32, no Python in that process, no Tk.

1. `zig build` builds it beside `journal-clip.exe`. `zig build widget` builds and runs it.
2. Live mic level, straight off WinMM. Device is the one `change-input` picked.
3. Record clicks, same as the UI: 1=30s, 2=60s, 3=90s, 4=120s. Wait a beat after the last click. Click again — or Space / Enter — to **stop and send early**.
4. On stop it writes one temp wav and hands it to `journal-clip.exe --file`, which owns whisper, the 7B and the tape. The widget shreds the wav when that exe exits.
5. Bottom line is the next **armed** alarm off `clip-alarms.jsonl`, re-read every 30s.

Non-Windows targets skip the widget; `zig build` still produces `journal-clip.exe`.

---

## Transcription editor (separate goal)

Double-click `Clip-edit.bat`. Not Record. No mic. No Whisper.

1. Folder dialog — pick the journal folder (`takes.jsonl`; old CSVs are imported, not deleted).
2. Click a take. Fix the text. **Save text**.
3. Kind is left alone. This does not re-transcribe.

---

## What you have

Two layers:

1. **Zig** (`journal-clip.exe`) — record mic, start Python, shred the wav.
2. **Python** — Whisper, optional Ollama, append two CSVs on the output folder surface.

Settings persist in `%USERPROFILE%\.sesefus\clip-config.json`. That file is **not** inside the journal folder, so changing the output dir cannot lose it.

---

## Do this, in order

Or skip the UI and drive it from a terminal.

Open **PowerShell** or **cmd**. One folder:

```bat
cd C:\dev\sesefus\apps\journal-clip
```

### 1. Prove it compiles

```bat
zig build
Clip.bat status
```

You want: `[clip] journal-clip ok` and a dump of current settings. No recording.

If `zig build` errors, the binary is not updated. Stay in this folder. Zig must be 0.16 (`zig version`).

### 2. Aim the output

```bat
Clip.bat change-dir C:\Users\bardw\test-write
```

Surface of that folder: `takes.jsonl` (one utterance per line). Old `transcriptions.csv` / `ledger.csv` are imported once if the tape is missing. Not nested stamp dirs.

Omit the path to **print** the current dir.

### 3. Pick the mic

```bat
Clip.bat change-input
```

Lists devices with indexes. Then:

```bat
Clip.bat change-input 0
```

Use the number next to the mic you want.

### 4. (Optional) Change how the 7B writes

```bat
Clip.bat change-prompt C:\path\to\structure.md
Clip.bat change-prompt --kind daily C:\path\to\daily.md
Clip.bat change-prompt --clear
```

A prompt file is just markdown/text: the system instructions for the local 7B (headings, tone). Cosine still picks the **folder name** (daily / dump / …). `--clear` goes back to the built-in 8 prompts.

### 5. Record (later — needs Ollama)

Do **not** do this until status works and Ollama is serving `nomic-embed-text` plus `qwen2.5:7b-instruct`.

```bat
Clip.bat
```

Speak ~10 seconds. Then look under the dir from step 2.

Safe dry path (no mic, no 7B):

```bat
Clip.bat --say "this is a test dump" --no-llm
```

That still writes a markdown file. It does not need Whisper.

---

## What you are not doing

- Not starting `sesefus.exe --role host`.
- Not opening the React dashboard.
- Not Circadia.
- Not a paid API. Local Whisper + local Ollama only.

---

## If it fails

- **zig build red** — Zig is not 0.16, or PATH is wrong. `zig version` should print `0.16.x`.
- **clip_config.py not found** — you ran the exe from another folder without `Clip.bat`. Use `Clip.bat`.
- **zig not on PATH** — `Clip.bat` still runs **controls** through Python only. Record needs the exe.
- **Ollama down** — controls still work. Full `Clip.bat` record will fail at embed/7B. That is the next sitting, not this compile sitting.
