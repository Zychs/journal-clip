# AGENTS.md — working rules for this repo

For any agent (Claude Code, Codex, a human doing the same job) touching
`journal-clip`. Read this before `README.md`; the README tells you what the
product does, this file tells you what you are allowed to do to it.

---

## 1. What this repo is

A **small** Sesefus command. Not the host. Not the dashboard. Not Circadia the
platform. You speak, it keeps the sound, the words, and its reading of them.

Two layers:

1. **Zig 0.16** (`src\main.zig` → `journal-clip.exe`) — record mic, spawn the
   Python sidecar, shred the *scratch* wav.
2. **Python** (`python\`) — archive audio, Whisper, optional local Ollama, and
   the tk windows.

Zig 0.16 only. `zig version` must print `0.16.x`. `Clip.bat` always runs
`zig build` first.

---

## 2. Laws

These are not preferences. Breaking one is a bug even if the tests pass.

1. **The wav happened once.** Raw audio is archived under a content-addressed
   name and made read-only *before* Whisper is loaded. Same bytes twice is a
   no-op; different bytes at the same destination raises `OverwriteRefused`.
   Never add a code path that overwrites or deletes an archived clip.
2. **A transcript is a reading, not a fact.** Re-running a model **appends** a
   version. A human correction appends a version marked `produced_by: human`.
   Nothing is written over.
3. **Semantics are guesses.** Every row carries `ground_truth: false` and names
   the transcript version it came from. Correcting a transcript does not
   silently update them — they go stale and report as owed a recompute.
4. **`takes.jsonl` is a projection, not a store.** Delete it and
   `clip_store.py project` rebuilds it byte for byte. Never make it the only
   home of anything.
5. **Settings live outside the journal folder.** `%USERPROFILE%\.sesefus\` —
   changing the output dir cannot lose them.
6. **Alarms have no port.** File + process. The store is
   `%USERPROFILE%\.sesefus\clip-alarms.jsonl`, outside the journal *and*
   outside the repo, and there is a test that enforces it.
7. **This repo is a flat git root.** Do not nest it back under `apps\`. Do not
   recreate `C:\dev\sesefus\apps\journal-clip` as a live product — that path is
   a POINTER only.

---

## 3. The three data products

One take makes three things with three lifetimes, three owners, and three
failure modes. They are not stored together.

| Product | Rule | Module | Under the journal root |
|---|---|---|---|
| Raw audio | never overwrite | `python\clip_audio.py` | `audio/`, `audio/audio.jsonl` |
| Transcript / diarization | version alongside the model | `python\clip_transcript.py` | `transcript/transcripts.jsonl` |
| Derived semantics | revisable output, not truth | `python\clip_semantics.py` | `semantics/semantics.jsonl` |

`takes.jsonl` is the flat view over all three, rebuilt on every write.

Old journal folders migrate themselves on first read (legacy `takes.jsonl` or
the CSV twins split into the three systems, once). Nothing is deleted and the
CSVs stay where they are.

---

## 4. Module map

```
src\main.zig            record · orchestrate · shred the scratch wav
python\clip_config.py   settings + change-* controls (incl. change-audio)
python\clip_audio.py    system 1 — immutable audio store, sha256 manifest
python\clip_transcript.py system 2 — append-only versions per model
python\clip_semantics.py  system 3 — append-only revisions, always stale-able
python\clip_store.py    the flat projection + migration + status
python\clip_heavy.py    whisper → embed → cosine kind → optional 7B
python\clip_group.py    ledger grouping profiles (.d .i .n .g .m)
python\clip_look.py     negentropic-blue tokens; every tk window imports these
python\clip_ui.py       the record card (front record ⟷ back ledger) + flip
python\clip_edit_ui.py  transcription editor — no mic, no whisper
python\clip_circadia.py the circadia card — add ⟷ edit, right rail
python\clip_alarm.py    alarm store, daemon, hop fire
```

Launchers: `Clip.bat` (build + record + controls + `alarm`), `Clip-ui.bat`,
`Clip-edit.bat`, `Circadia.bat`.

---

## 5. The card idiom

Every window here is a **card**. Cards are built from `clip_look.py` tokens, not
from ad-hoc colours.

- `card(parent)` is one bordered face on house void.
- A two-faced card flips with an **8-step horizontal squash**:
  `flip_width_scale(step, steps=8)`, `FLIP_MS = 16`, faces swap at
  `flip_swap_step(8) == 4`. This is defined once in `clip_ui.py` and imported
  by everything else — `clip_circadia.py` already does. Do not write a second
  flip.
- Palette is **negentropic-blue** (`BG #050509`, `CYAN #7cf7ff`, `LINE #272739`,
  `AMBER #e2a24a`, `GOOD #4CAE7C`). Not Matrix green, not board cyan.

`design\canvas\` holds the design canvas for the card hand — artboards as
`.dc.html`, laid out by `canvas.json`, with the annotations that state the
open questions. `design\circadia-card.html` is the static twin opened by
`Circadia.bat design`.

Open on the canvas today: **Circadia A (dial) vs B (composer)** — the canvas
annotation `pick-a-circadia` says pick one, and nothing has picked yet.

---

## 6. Running things

```powershell
zig build                                    # must be clean, zig 0.16
Clip.bat status                              # compile/run check, no recording
python python\clip_store.py status --root D:\journal
python python\clip_audio.py verify --root D:\journal
```

Tests — the suite is split by runner:

```powershell
# unittest files: run each directly (python\tests has no __init__.py)
Get-ChildItem python\tests\test_*.py | ForEach-Object { python $_.FullName }

# test_alarm.py is pytest
python -m pytest python\tests\test_alarm.py -q
```

If pytest dies with `PermissionError [WinError 5]` on
`%LOCALAPPDATA%\Temp\pytest-of-bardw`, that is the shared temp dir, not the
code — pass `--basetemp` at a writable path.

As of 2026-08-30: 110 tests pass (39 alarm + 71 across the rest), `zig build`
clean.

---

## 7. House rules for changes

- **Match the surrounding code.** Comment density, naming, the lowercase
  terse UI voice ("speak · keep · plate", "kind is a guess, editable").
- **Never claim a green run you did not do.** Run the tests, paste what
  happened. A skipped step gets said out loud.
- **Do not add a dashboard, a server, or a port.** Four bat files and tk
  windows is the whole surface.
- **Do not touch another tree.** `C:\Users\bardw\artifact-scanner`,
  `C:\dev\AyTree`, and `C:\dev\sesefus` are read-only origins from here. Copy
  out of them; never write into them.
- **Ollama is optional.** `--no-llm` and a down Ollama must still land text.
- Branch, don't commit to `master`, and don't push to `master` without being
  asked for that specifically.

---

## 8. Where the record is kept

| File | Holds |
|---|---|
| `README.md` | what the product does, and how to drive it |
| `AGENTS.md` | this file — the rules for changing it |
| `ALARM.md` | the frozen 0.2.0 alarm contract and the ladder |
| `CHANGELOG.md` | LOCKED / PARKED / Added / Changed, reverse-chronological |
| `HISTORY.md` | waves, rebuilt from git log + mtimes; not the git log |
| `VERSION` | `0.2.0`. No semver scheme beyond this file. |

Something LOCKED in `CHANGELOG.md` does not get quietly reopened. Something
PARKED is a decision that was deliberately not made — leave it parked or say
you are unparking it.
