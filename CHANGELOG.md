# Changelog

Reverse-chronological. Dates are local. Reconstructed entries marked
(reconstructed).

No silent semver scheme beyond the `VERSION` file (`0.2.0`). Stay on
`[Unreleased]` plus that file.

## [Unreleased]

### LOCKED
- 2026-08-29 — 0.2.0 alarms: interval, toggle, daemon, hop fire. No port. Store outside the journal (`ALARM.md`).
- 2026-08-30 — this copy is a flat git root. Do not nest it back under `apps\`.
- Do not recreate `C:\dev\sesefus\apps\journal-clip` as a live product.
- 2026-08-30 — one take makes three products with three preservation rules:
  raw audio never overwritten, transcript versioned per model, semantics
  revisable and never ground truth. `takes.jsonl` is a projection over them,
  not a store. Written down as law in `AGENTS.md` §2.
- 2026-08-30 — `archive` is the default audio retention. Raw audio is the one
  product here that cannot be regenerated.

### PARKED
- Groups and bulk: `ALARM.md` §7, intended `0.2.1`.
- Windows live smoke of `Clip.bat alarm add` / `server` / hop — listed open in `ALARM.md`.
- Whether this tree later replaces Clippers as SSOT. Two remotes today.
- **Circadia A (dial) vs B (composer).** Both designed on the canvas, both drop
  the permanent server rail `clip_circadia.py` has today. `canvas.json`
  annotation `pick-a-circadia`. Nothing picked.
- **The last two cards of the hand** — archival view and aytree, to be borrowed
  from Artifact Scanner (`C:\Users\bardw\artifact-scanner`) and `C:\dev\AyTree`.
  Located, read, not retrieved. Open under it: whether they land as verbatim
  originals, as ported `.dc.html` artboards, or both; and how aytree's
  green-gold palette meets this repo's negentropic-blue.

### Added
- Flattened repo root (2026-08-30). Written `HISTORY.md`.
- The three data products, each its own append-only store: `python\clip_audio.py`
  (sha256 manifest, read-only clips, `OverwriteRefused`),
  `python\clip_transcript.py` (a version per transcription model, `produced_by`
  human/whisper/import), `python\clip_semantics.py` (revisions, `ground_truth:
  false`, stale when the transcript moves under them).
- `Clip.bat change-audio archive|shred` — `python\clip_config.py cmd_change_audio`,
  forwarded from `src\main.zig`.
- Circadia alarm card: `Circadia.bat`, `python\clip_circadia.py`,
  `design\circadia-card.html`. Flip is imported from `clip_ui.py`, not rewritten.
- `design\canvas\` — the card-hand canvas: `Record`, `Main` (circadia A),
  `CircadiaB`, `Controls`, `Cabinet` artboards plus `canvas.json` and its
  annotations.
- `AGENTS.md` — laws, module map, card idiom, how to run the split test suite.
- Tests: `python\tests\test_pipeline.py` (22), `test_circadia.py` (6),
  `test_circadia_add.py` (7).

### Changed
- Launchers look for venv in this folder, then `.venv`, then `C:\dev\sesefus\venv`, then PATH.
- `python\clip_store.py` rebuilt as a projection over the three systems, with
  one-time migration of legacy `takes.jsonl` and the CSV twins. Nothing deleted.
- `python\clip_heavy.py` archives the take before Whisper is loaded, and reports
  `audio_uid` / `audio_path` / `audio_retained` back to Zig and the UI.
- `src\main.zig` shreds only its own scratch wav, and says so in the header.
  Usage text now names the three products.
- Record card front line is `speak · keep · plate`, not `speak · plate · shred`.
  The log line marks the kind as a guess.

### Verified 2026-08-30
- `zig build` clean on zig 0.16.0.
- 110 python tests pass — 39 in `test_alarm.py` (pytest), 71 across the seven
  unittest files.

## [0.2.0] — 2026-08-29 (reconstructed)

Alarms rung as packed in `ALARM.md`. Four of six jobs shipped (interval, toggle, daemon, hop). Groups and bulk deferred.
