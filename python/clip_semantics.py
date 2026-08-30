#!/usr/bin/env python3
"""System 3 of 3 - derived semantics.

Purpose: tags, embeddings, summaries, inferred state.
Preservation rule: **treat as revisable model output, not ground truth**.

Everything in here is a guess. The cosine said "daily"; the 7B wrote that
summary; the embedder placed the take at those coordinates. Change any of
those models and every one of those answers should be free to change with
it - so this store is a revision log that is explicitly *not* authoritative:

  <root>/semantics/semantics.jsonl     append-only, one revision per line

Every row carries `ground_truth: false`, the models that produced it, and
the exact transcript version it was derived from. That last field is what
makes `stale()` possible: when the transcript moves, its semantics are
known-suspect rather than quietly wrong.

Deleting this whole directory must cost nothing but compute. If it ever
costs you a fact, that fact was filed in the wrong system.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCHEMA = 1
SEMANTICS_DIR = "semantics"
LOG_NAME = "semantics.jsonl"


def semantics_root(root: Path | str) -> Path:
    return Path(root) / SEMANTICS_DIR


def log_path(root: Path | str) -> Path:
    return semantics_root(root) / LOG_NAME


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
    """Append-only. A revision supersedes; it does not erase."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def all_revisions(root: Path | str) -> list[dict[str, Any]]:
    return _read_log(log_path(root))


def history(root: Path | str, take_id: str | int) -> list[dict[str, Any]]:
    wanted = str(take_id).strip()
    rows = [r for r in all_revisions(root) if str(r.get("take_id") or "").strip() == wanted]
    return sorted(rows, key=lambda r: int(r.get("revision") or 0))


def latest(root: Path | str, take_id: str | int) -> dict[str, Any] | None:
    rows = history(root, take_id)
    return rows[-1] if rows else None


def latest_by_take(root: Path | str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in all_revisions(root):
        tid = str(row.get("take_id") or "").strip()
        prev = out.get(tid)
        if prev is None or int(row.get("revision") or 0) >= int(prev.get("revision") or 0):
            out[tid] = row
    return out


def next_revision(root: Path | str, take_id: str | int) -> int:
    rows = history(root, take_id)
    return (max(int(r.get("revision") or 0) for r in rows) + 1) if rows else 1


def _clean_tags(tags: Iterable[str] | None) -> list[str]:
    out: list[str] = []
    for t in tags or []:
        s = str(t or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def append_revision(
    root: Path | str,
    take_id: str | int,
    *,
    transcript_version: int | None = None,
    kind: str = "dump",
    score: float = 0.0,
    structured: str = "",
    summary: str = "",
    tags: Iterable[str] | None = None,
    embedding: list[float] | None = None,
    embed_model: str = "",
    chat_model: str = "",
    prompt_source: str = "",
    inferred: dict[str, Any] | None = None,
    degraded: Iterable[str] | None = None,
    when: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add one interpretation of one transcript version. Never authoritative."""
    take_id = str(take_id).strip()
    if not take_id:
        raise ValueError("semantics needs a take_id")
    root = Path(root)
    when = when or datetime.now()
    row = {
        "schema": SCHEMA,
        "take_id": take_id,
        "revision": next_revision(root, take_id),
        "derived_from_transcript_version": (
            int(transcript_version) if transcript_version is not None else None
        ),
        "ground_truth": False,
        "kind": kind or "dump",
        "score": round(float(score or 0.0), 6),
        "structured": structured or "",
        "summary": summary or "",
        "tags": _clean_tags(tags),
        "embedding": list(embedding) if embedding else [],
        "embed_model": embed_model,
        "chat_model": chat_model,
        "prompt_source": prompt_source,
        "inferred": dict(inferred or {}),
        "degraded": [str(d) for d in (degraded or [])],
        "created": when.isoformat(timespec="seconds"),
        "extra": dict(extra or {}),
    }
    _append_log(log_path(root), row)
    return row


def stale(root: Path | str, transcript_versions: dict[str, int]) -> list[str]:
    """Takes whose semantics were derived from an older transcript version.

    Pass `{take_id: current_version}` (clip_transcript.latest_by_take gives it).
    A take with no semantics at all is stale too - it has never been read.
    """
    current = latest_by_take(root)
    out: list[str] = []
    for tid, version in transcript_versions.items():
        row = current.get(str(tid))
        if row is None:
            out.append(str(tid))
            continue
        derived = row.get("derived_from_transcript_version")
        if derived is None or int(derived) < int(version):
            out.append(str(tid))
    return sorted(out, key=lambda t: (len(t), t))


def models_used(root: Path | str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in latest_by_take(root).values():
        key = f"{row.get('embed_model') or '-'} / {row.get('chat_model') or '-'}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def discard(root: Path | str) -> bool:
    """Drop the whole semantics log. Safe by construction - it is all recomputable.

    Neither system 1 nor system 2 is touched. If discarding this ever loses
    something you cannot rebuild, that something belonged in another system.
    """
    path = log_path(root)
    if path.is_file():
        path.unlink()
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="journal-clip derived semantics (revisable, not ground truth)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("history", help="every revision of one take")
    h.add_argument("--root", required=True)
    h.add_argument("--take", required=True)
    ls = sub.add_parser("list", help="current revision of every take")
    ls.add_argument("--root", required=True)
    s = sub.add_parser("stale", help="takes whose semantics lag their transcript")
    s.add_argument("--root", required=True)
    m = sub.add_parser("models")
    m.add_argument("--root", required=True)
    d = sub.add_parser("discard", help="delete the log; it is all recomputable")
    d.add_argument("--root", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "history":
        for row in history(args.root, args.take):
            print(
                f"r{row['revision']}  kind={row['kind']}  score={row['score']}  "
                f"from-transcript-v{row.get('derived_from_transcript_version')}  {row['created']}"
            )
        return 0
    if args.cmd == "list":
        for tid, row in sorted(latest_by_take(args.root).items(), key=lambda kv: (len(kv[0]), kv[0])):
            print(f"{tid}  r{row['revision']}  {row['kind']}  {row['score']}")
        return 0
    if args.cmd == "stale":
        import clip_transcript

        versions = {
            tid: int(r.get("version") or 0)
            for tid, r in clip_transcript.latest_by_take(args.root).items()
        }
        print(json.dumps(stale(args.root, versions)))
        return 0
    if args.cmd == "models":
        print(json.dumps(models_used(args.root), indent=2))
        return 0
    if args.cmd == "discard":
        print("discarded" if discard(args.root) else "nothing to discard")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
