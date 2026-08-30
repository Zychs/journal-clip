# HISTORY

Rebuilt from git log + file mtimes. This file is not the git log.

Repo root flattened here 2026-08-30 from `apps\journal-clip`. History commits are unchanged.

## Waves

### 2026-08-30 · the hand
- `Clip-hand.bat` + `python\clip_hand.py`: one window, `record | alarm |
  controls`. Three windows became three tabs.
- The controls card built from `Controls.dc.html` — storage ⟷ prompt-out, all
  figures read live from the three stores.
- Every card class grew `master=None` and `shutdown()`, so the same class opens
  alone or mounts into the hand. No card was forked to do this.
- Ran, not only tested: all three cards and both controls faces captured.
- Still open: circadia A vs B, and the two borrowed cards that would take the
  hand from three to five.

### 2026-08-30 · three products, the circadia card, and the hand canvas
- The pipeline split into three append-only stores with three preservation
  rules — `clip_audio.py`, `clip_transcript.py`, `clip_semantics.py`.
  `clip_store.py` became a projection over them and migrates legacy folders on
  first read.
- `change-audio archive|shred` added through `clip_config.py`, forwarded from
  `src\main.zig`. `archive` is the default; the Zig shred now only ever destroys
  its own scratch wav.
- Circadia card committed with the rest — `Circadia.bat`,
  `python\clip_circadia.py`, `design\circadia-card.html`. Its flip is imported
  from `clip_ui.py` rather than written twice.
- `design\canvas\` landed: five artboards for the intended card **hand**, plus
  `canvas.json` annotations naming the open choices. Two are unresolved —
  circadia A vs B, and which two cards finish the hand.
- `AGENTS.md` written. Prototypes for the last two cards located but **not
  retrieved**: archival view and aytree, in `C:\Users\bardw\artifact-scanner`
  (not `C:\dev`, despite the pointer's neighbourhood) and `C:\dev\AyTree`.
- Green at the time of writing: `zig build` on 0.16.0, 110 python tests.

### 2026-08-30 · flatten this copy
- Nested `apps\journal-clip` lifted to this folder. `.git` came with it.
- Duplicate trees parked on `I:\Archive\journal-clip-twins\20260830-flatten`.
- Clippers at `C:\dev\journal-clippers\audio-journal-system` was not moved.

### 2026-08-29 · Circadia card (working tree, not a commit)
- `Circadia.bat`, `python\clip_circadia.py`, `design\circadia-card.html` appear on disk ~01:17 2026-08-30.
- Alarm module and `ALARM.md` already committed as 0.2.0.

### 2026-08-28 · this Desktop copy
- `journal-clip.7z` landed under `apps\` ~23:08. Streamlined folder named that day.

### 2026-08-21 · card flip (git)
- `d16b1c7` card flip — current `codex/recover-compact-alarm` / `revisions`.
- Earlier: `87dc729` Sesefus 0.2.0 alarms (interval, toggle, daemon, hop fire).
- `845ae38` Elegance In journaling.

### Before that (git, approximate)
- Build-stability branch then a revert merge on `master`.
- Remote: `https://github.com/Zychs/journal-clip.git`

## Not this tree
- Clippers / `Zychs/audio-journal-system` is a sibling product.
- Sesefus host stays at `C:\dev\sesefus`. `apps\journal-clip` there is a POINTER only.
