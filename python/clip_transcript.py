#!/usr/bin/env python3
"""System 2 of 3 - transcript / diarization.

Purpose: the searchable linguistic record.
Preservation rule: **version alongside the transcription model**.

A transcript is not the take and it is not a fact. It is what one named
model heard on one named day. Swap Whisper base for large and you get a
different, equally legitimate reading of the same audio - so the store is
a version log, never a cell to be edited:

  <root>/transcript/transcripts.jsonl     append-only, one version per line

Every row names the engine, the model, and what it was derived from
(`audio_uid`, when audio exists). `update` does not mutate: it appends
version n+1 with source "human". Version 1 stays readable forever, which
is what makes a model swap auditable instead of destructive.

Diarization lives here too, in `segments` - the same record, one level
finer. Nothing here tags, scores, or summarizes. That is system 3.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA = 1
TRANSCRIPT_DIR = "transcript"
LOG_NAME = "transcripts.jsonl"

# Two different questions, kept in two different fields:
#   produced_by - who made these words (the axis that decides staleness)
#   source      - which channel the take arrived on (clip, harvest, a CSV)
# Collapsing them loses the ability to ask either one cleanly.
HUMAN = "human"
MACHINE = "whisper"
IMPORTED = "import"
PRODUCERS = (MACHINE, HUMAN, IMPORTED)


def producer(engine: str, given: str = "") -> str:
    """Who produced a reading, from its engine name.

    A typed take (`--say`) is a human reading: nobody transcribed anything,
    so no better model will ever improve it.
    """
    if given in PRODUCERS:
        return given
    e = (engine or "").strip().lower()
    if e in (HUMAN, "typed"):
        return HUMAN
    if e == IMPORTED:
        return IMPORTED
    return MACHINE


def transcript_root(root: Path | str) -> Path:
    return Path(root) / TRANSCRIPT_DIR


def log_path(root: Path | str) -> Path:
    return transcript_root(root) / LOG_NAME


def _read_log(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in body.splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and str(obj.get("take_id") or "").strip():
            rows.append(obj)
    return rows


def _append_log(path: Path, row: dict[str, Any]) -> None:
    """Append-only. No caller rewrites this file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def model_id(engine: str, model: str) -> str:
    """The version axis. Two transcripts are comparable only within one of these."""
    engine = (engine or "").strip() or "unknown"
    model = (model or "").strip() or "unknown"
    return f"{engine}:{model}"


def all_versions(root: Path | str) -> list[dict[str, Any]]:
    return _read_log(log_path(root))


def history(root: Path | str, take_id: str | int) -> list[dict[str, Any]]:
    """Every version for one take, oldest first."""
    wanted = str(take_id).strip()
    rows = [r for r in all_versions(root) if str(r.get("take_id") or "").strip() == wanted]
    return sorted(rows, key=lambda r: int(r.get("version") or 0))


def latest(root: Path | str, take_id: str | int) -> dict[str, Any] | None:
    """Highest version wins. A human edit is just a later version."""
    rows = history(root, take_id)
    return rows[-1] if rows else None


def latest_by_take(root: Path | str) -> dict[str, dict[str, Any]]:
    """One current version per take, in one pass over the log."""
    out: dict[str, dict[str, Any]] = {}
    for row in all_versions(root):
        tid = str(row.get("take_id") or "").strip()
        prev = out.get(tid)
        if prev is None or int(row.get("version") or 0) >= int(prev.get("version") or 0):
            out[tid] = row
    return out


def next_version(root: Path | str, take_id: str | int) -> int:
    rows = history(root, take_id)
    return (max(int(r.get("version") or 0) for r in rows) + 1) if rows else 1


def take_ids(root: Path | str) -> list[str]:
    seen: list[str] = []
    for row in all_versions(root):
        tid = str(row.get("take_id") or "").strip()
        if tid and tid not in seen:
            seen.append(tid)
    return seen


def next_take_id(root: Path | str) -> int:
    """Monotonic. Never reused, even after a take is superseded."""
    nums = []
    for tid in take_ids(root):
        try:
            nums.append(int(tid))
        except ValueError:
            continue
    return (max(nums) + 1) if nums else 1


def normalize_segments(segments: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Diarization rows: start, end, speaker, text. Anything else is dropped."""
    out: list[dict[str, Any]] = []
    for seg in segments or []:
        if not isinstance(seg, dict):
            continue
        text = str(seg.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(seg.get("start") or 0.0)
            end = float(seg.get("end") or 0.0)
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        out.append(
            {
                "start": round(start, 3),
                "end": round(end, 3),
                "speaker": str(seg.get("speaker") or "").strip(),
                "text": text,
            }
        )
    return out


def append_version(
    root: Path | str,
    take_id: str | int,
    text: str,
    *,
    engine: str = MACHINE,
    model: str = "",
    audio_uid: str = "",
    segments: Iterable[dict[str, Any]] | None = None,
    language: str = "",
    source: str = "clip",
    produced_by: str = "",
    when: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add one transcript version. Existing versions are never touched."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty transcript - not stored")
    take_id = str(take_id).strip()
    if not take_id:
        raise ValueError("transcript needs a take_id")
    root = Path(root)
    when = when or datetime.now()
    version = next_version(root, take_id)
    prior = latest(root, take_id)
    row = {
        "schema": SCHEMA,
        "take_id": take_id,
        "version": version,
        "supersedes": int(prior.get("version")) if prior else None,
        "audio_uid": str(audio_uid or (prior.get("audio_uid") if prior else "") or ""),
        "text": text,
        "segments": normalize_segments(segments),
        "engine": engine,
        "model": model,
        "model_id": model_id(engine, model),
        "language": language,
        "source": source,
        "produced_by": producer(engine, produced_by),
        "created": when.isoformat(timespec="seconds"),
        "date": when.strftime("%Y-%m-%d"),
        "time": when.strftime("%H:%M:%S"),
        "extra": dict(extra or {}),
    }
    _append_log(log_path(root), row)
    return row


def update(
    root: Path | str,
    take_id: str | int,
    text: str,
    *,
    source: str = HUMAN,
    when: datetime | None = None,
) -> dict[str, Any]:
    """A correction is a new version, not an overwrite.

    The machine reading it replaces stays in the log, which is the whole
    point: you can still ask what the model actually heard.
    """
    prior = latest(root, take_id)
    if prior is None:
        raise ValueError(f"no take id {take_id}")
    return append_version(
        root,
        take_id,
        text,
        engine=source,
        model=str(prior.get("model") or ""),
        audio_uid=str(prior.get("audio_uid") or ""),
        segments=None,
        language=str(prior.get("language") or ""),
        # the take still arrived on whatever channel it arrived on; only the
        # producer of this particular reading has changed
        source=str(prior.get("source") or "clip"),
        produced_by=source,
        when=when,
        extra={"corrects_version": prior.get("version")},
    )


def models_used(root: Path | str) -> dict[str, int]:
    """Which transcription models this record was built from, and how much of it.

    Machine readings only. A human correction is not a transcription model,
    and counting it as one would misreport how the record was produced.
    """
    counts: dict[str, int] = {}
    for row in latest_by_take(root).values():
        if producer(str(row.get("engine") or ""), str(row.get("produced_by") or "")) != MACHINE:
            continue
        counts[str(row.get("model_id") or "unknown")] = (
            counts.get(str(row.get("model_id") or "unknown"), 0) + 1
        )
    return counts


def producers_used(root: Path | str) -> dict[str, int]:
    """How many current readings came from a machine, a person, or an import."""
    counts: dict[str, int] = {}
    for row in latest_by_take(root).values():
        key = producer(str(row.get("engine") or ""), str(row.get("produced_by") or ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def behind_model(root: Path | str, model_id_now: str) -> list[str]:
    """Takes whose current transcript predates the model in use - re-run candidates.

    Only machine readings qualify. A human reading is not stale because a
    model moved, and an imported one has no audio to re-run against.
    """
    out: list[str] = []
    for tid, row in latest_by_take(root).items():
        if producer(str(row.get("engine") or ""), str(row.get("produced_by") or "")) != MACHINE:
            continue
        if str(row.get("model_id") or "") != model_id_now:
            out.append(tid)
    return sorted(out, key=lambda t: (len(t), t))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="journal-clip transcript store (versioned by model)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("history", help="every version of one take")
    h.add_argument("--root", required=True)
    h.add_argument("--take", required=True)
    ls = sub.add_parser("list", help="current version of every take")
    ls.add_argument("--root", required=True)
    m = sub.add_parser("models", help="which models this record was built from")
    m.add_argument("--root", required=True)
    b = sub.add_parser("behind", help="takes whose transcript predates a given model")
    b.add_argument("--root", required=True)
    b.add_argument("--model-id", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "history":
        for row in history(args.root, args.take):
            print(
                f"v{row['version']}  {row['model_id']}  by={row.get('produced_by')}  "
                f"via={row.get('source')}  {row['created']}"
            )
            print(f"    {row['text']}")
        return 0
    if args.cmd == "list":
        for tid, row in sorted(latest_by_take(args.root).items(), key=lambda kv: (len(kv[0]), kv[0])):
            print(f"{tid}  v{row['version']}  {row['model_id']}  {row['text'][:72]}")
        return 0
    if args.cmd == "models":
        print(json.dumps(models_used(args.root), indent=2))
        return 0
    if args.cmd == "behind":
        stale = behind_model(args.root, args.model_id)
        print(json.dumps(stale))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
