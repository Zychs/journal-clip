# journal-clip — what this is

This folder is the git root (flattened 2026-08-30). Not nested under `apps\`.

A **small** Sesefus command. Not the host. Not Circadia. Not the dashboard.

You speak. It keeps the **sound**, the **words**, and its **reading** of them —
three products, three rules, three places. It destroys only the scratch wav.

Zig 0.16 only. `Clip.bat` always runs `zig build` first.

Changing this repo? Read **`AGENTS.md`** first — it holds the laws (never
overwrite raw audio, never overwrite a transcript, no port, flat git root), the
module map, and how to run the split test suite.

---

## The three data products

One take produces three things. They have different lifetimes, different
owners, and different failure modes, so they are not stored together.

| Data product | Purpose | Preservation rule | Where |
| --- | --- | --- | --- |
| **Raw audio** | acoustic / prosodic research, retraining, audit | **never overwrite** | `audio/` · `python\clip_audio.py` |
| **Transcript / diarization** | searchable linguistic record | **version alongside the transcription model** | `transcript/` · `python\clip_transcript.py` |
| **Derived semantics** | tags, embeddings, summaries, inferred state | **revisable model output, not ground truth** | `semantics/` · `python\clip_semantics.py` |

Under the journal folder:

```
audio/2026/08/20260830-145907-9f3c1a02.wav   read-only, named by content hash
audio/audio.jsonl                            append-only manifest (+ sha256)
transcript/transcripts.jsonl                 append-only, one line per version
semantics/semantics.jsonl                    append-only, one line per revision
takes.jsonl                                  flat projection — rebuildable
```

Why it is split this way:

- **The wav happened once.** Whisper can be re-run, the 7B can be re-asked, but
  the sound of a take cannot be regenerated. It is archived *before* Whisper is
  even loaded, under a content-addressed name, and the file is made read-only.
  Archiving the same bytes twice is a no-op; a destination holding *different*
  bytes raises `OverwriteRefused` rather than clobbering anything.
- **A transcript is a reading, not a fact.** It is what one named model heard on
  one named day. Swap `base` for `large-v3` and you get a different, equally
  legitimate reading — so a re-run *appends* version 2 and version 1 stays
  readable forever. Your own corrections in `Clip-edit.bat` do the same thing:
  they append a version marked `produced_by: human`. The machine's reading is
  never overwritten, which is what makes a model swap auditable.
- **Semantics are guesses.** The cosine picked the kind; the 7B wrote the gist.
  Every row carries `ground_truth: false` and names the transcript version it
  was derived from. Correct a transcript and its real model output does **not**
  silently follow — it stays put and starts reporting as stale, owed a recompute.
  Deleting `semantics/` outright costs nothing but compute.

`takes.jsonl` is no longer where anything lives; it is one flat line per take,
rebuilt from the other two on every write, kept because the UIs already speak
it. Delete it and `clip_store.py project` builds it back byte for byte.

```bat
python python\clip_store.py status --root D:\journal    all three, and their rules
python python\clip_audio.py verify --root D:\journal    re-hash the archive
python python\clip_transcript.py history --root D:\journal --take 7
python python\clip_semantics.py stale --root D:\journal  takes owed a recompute
```

Old journal folders migrate themselves: the first read splits a legacy
`takes.jsonl` (or the CSV twins) into the three systems, once. Nothing is
deleted, and the CSVs stay exactly where they are.

If you want the old behaviour — text lands, sound gone:

```bat
Clip.bat change-audio shred
Clip.bat change-audio archive
```

---

## One window — `Clip-hand.bat`

Double-click `Clip-hand.bat`. One window, every card.

```
record  |  alarm  |  controls
```

Three cards, each two-faced. The tab strip picks the card; **flip** turns the
card that is showing.

| Card | Front | Back |
| --- | --- | --- |
| **record** | record — mic, waveform, plate | ledger — count, groups, profiles |
| **alarm** | add — title, when, do | edit — find one row, patch it |
| **controls** | storage — the three products, retention | prompt-out — models, prompts, per-kind |

Keys: `1` `2` `3` pick a card, `ctrl+tab` walks the hand, `f` flips the card
you are on. Keys stay out of the way while you are typing in a field.

Cards are built the first time you pick their tab, not at startup — the record
card opens a capture device list and the alarm card starts a clock, and neither
should happen because you wanted the other one.

The single-card launchers still work and still open exactly one card in its own
window: `Clip-ui.bat` (record), `Circadia.bat` (alarm),
`python python\clip_controls.py` (controls). Same classes, same code — a card
just takes a parent frame when it joins a hand.

---

## The record card on its own (`Clip-ui.bat`)

Double-click `Clip-ui.bat`. Same folder as `Clip.bat`.

1. Startup reloads the **last folder** (`%USERPROFILE%\.sesefus\clip-ui.json`). Missing folder → dialog. **change** picks another. Not written into `clip-config.json`.
2. Dropdown is WinMM capture devices. Default pick is the **Maono USB** mic if it is present.
3. **Record** clicks: 1=30s, 2=60s, 3=90s, 4=120s. Wait a beat after the last click, then it starts. **Stop / send** ends early.
4. Waveform is a bipolar envelope (DC bias stripped so gain is true amplitude). Whole-second timer sits top-right of that widget. Look is house **negentropic-blue**.
5. One **card**. Front is record. **Flip** turns it over — ledger on the back (count, scroll, collapsible groups). Slim profiles `.d` day · `.i` interval · `.n` domain · `.g` intent · `.m` magnitude. Boundaries are probed from this folder’s takes. Click a profile to preview the same tape under different category rules.
6. Whisper runs **inside this window**. Transcript lands on the plate. No cmd popup. No warning dialog. Silence warns on the amber line.
7. The take is copied into `audio/` first, then the **temp** wav is shredded. The log line names the clip it kept.

No dashboard. No extra server. Close the window to end the session.

---

## Circadia alarm card (prototype)

Double-click `Circadia.bat`. The left card flips between **add** and **edit**;
the right rail is the local timekeeper and never flips. Alarm state is kept in
`%USERPROFILE%\\.sesefus\\clip-alarms.jsonl` through `python\\clip_alarm.py`.
It is file + process, with no port; a `hop` still opens `Clip-ui.bat`.

`Circadia.bat design` opens the static twin at `design\\circadia-card.html`.

---

## The card hand

Every window here is a **card**: one bordered face on house void, and a
two-faced card turns over with the same 8-step horizontal squash — defined once
in `clip_ui.py` (`flip_width_scale`, 16 ms a step, faces swap at the midpoint)
and imported by everything else.

`design\canvas\` is the canvas the hand is drawn from — artboards as `.dc.html`,
laid out by `canvas.json`, annotations carrying the open questions.

| Artboard | Card | State |
| --- | --- | --- |
| `Record.dc.html` | record ⟷ ledger | **built** — `python\clip_ui.py` |
| `Controls.dc.html` | storage ⟷ prompt-out | **built** — `python\clip_controls.py` |
| — | alarm, add ⟷ edit | **built** — `python\clip_circadia.py` |
| `Main.dc.html` | circadia A · the dial | designed |
| `CircadiaB.dc.html` | circadia B · the composer | designed |
| `Cabinet.dc.html` | filing cabinet, three drawers | designed |

The hand host is `python\clip_hand.py`, opened by `Clip-hand.bat`. A card joins
a hand by being handed a parent frame (`master=`); with no parent it opens its
own window, which is what the single-card launchers do.

Every number on the controls card is read from the three stores through
`clip_store.systems_status`. Nothing on that card is invented: an empty store
reports as empty, and `verify audio` says `n damaged` or nothing at all. The
model rows name where a model **runs**, not whether it answered — the card does
not probe, so it must not claim `up`.

Two decisions are open on the canvas and neither has been made:

- **Circadia A or B.** Both drop the permanent server rail that
  `clip_circadia.py` has today and move it to the back face. A is the dial
  (quiet, closest to what exists); B is the composer (denser, faster once
  learned). The `pick-a-circadia` annotation says pick one. Until then the
  alarm card in the hand is the existing add ⟷ edit card, rail and all.
- **The last two cards of a five-card hand.** The intended fill is the
  *archival view* and *aytree*, both borrowed from Artifact Scanner at
  `C:\Users\bardw\artifact-scanner` (`archive_bay.py` + `experimental\archive\`
  and `experimental\aytree\`). Neither has been retrieved into this repo yet.
  AyTree's canonical product tree is `C:\dev\AyTree`; its palette is green-gold
  by its own law, which this repo's negentropic-blue has to answer for.

Those trees are **read-only origins** from here. Copy out of them; never write
into them.

---

## Transcription editor (separate goal)

Double-click `Clip-edit.bat`. Not Record. No mic. No Whisper.

1. Folder dialog — pick the journal folder (`takes.jsonl`; old CSVs are imported, not deleted).
2. Click a take. Fix the text. **Save text**.
3. Kind is left alone. This does not re-transcribe.

Your correction is appended as a new transcript version, not written over the
old one — `clip_transcript.py history --take N` still shows what Whisper
actually heard. If the take had real 7B output, that summary is left alone and
starts reporting under `clip_semantics.py stale`, because it read the old
words. If `structured` was only a mirror of the transcript, it follows along.

---

## What you have

Two layers:

1. **Zig** (`journal-clip.exe`) — record mic, start Python, shred the *scratch* wav.
2. **Python** — archive the audio, then Whisper, then optional Ollama; each result
   lands in its own store and the flat `takes.jsonl` view is reprojected.

The shred in step 1 runs only after step 2 has returned, by which time the
archived copy already exists. That order is deliberate: the irreplaceable
product is saved before anything that can fail gets a chance to.

Settings persist in `%USERPROFILE%\.sesefus\clip-config.json`. That file is **not** inside the journal folder, so changing the output dir cannot lose it.

---

## Do this, in order

Or skip the UI and drive it from a terminal.

Open **PowerShell** or **cmd**. One folder:

```bat
cd C:\Users\bardw\Desktop\journal-clip-streamlined
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

Surface of that folder: `audio/`, `transcript/`, `semantics/` — the three
products — plus `takes.jsonl`, the flat view over them. Old
`transcriptions.csv` / `ledger.csv` are imported once, and left in place. Not
nested stamp dirs.

Omit the path to **print** the current dir.

### 2b. Decide whether the sound is kept

```bat
Clip.bat change-audio            print the current mode
Clip.bat change-audio archive    keep raw audio (default)
Clip.bat change-audio shred      text only, sound gone
```

`archive` is the default because raw audio is the one product here that cannot
be regenerated. It costs roughly 32 KB per second of speech (16 kHz mono 16-bit).

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
