#!/usr/bin/env python3
"""Surface store for journal-clip.

Live store is a speech tape: takes.jsonl (one utterance per line).
CSV twins (transcriptions.csv, ledger.csv) are imported if present, never
deleted by this module, and are not written on new takes.

Ids are monotonic integers. Never reused. schema=1.
Ollama down still lands text.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
TAPE_NAME = "takes.jsonl"
TRANS_NAME = "transcriptions.csv"
LEDGER_NAME = "ledger.csv"
KEEP = {TAPE_NAME, TRANS_NAME, LEDGER_NAME}
TRANS_FIELDS = ["date", "text"]
LEDGER_FIELDS = [
    "id",
    "date",
    "time",
    "kind",
    "score",
    "text",
    "structured",
    "source",
    "schema",
    "extra",
]
TEXT_NAMES = {"note.txt", "raw.txt", "note.md"}


def _root(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def trans_path(root: Path) -> Path:
    return root / TRANS_NAME


def ledger_path(root: Path) -> Path:
    return root / LEDGER_NAME


def tape_path(root: Path) -> Path:
    return root / TAPE_NAME


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in fields})


def _ids(rows: list[dict[str, str]]) -> list[int]:
    ids: list[int] = []
    for r in rows:
        try:
            ids.append(int(str(r.get("id") or "").strip()))
        except ValueError:
            continue
    return ids


def next_id(root: Path) -> int:
    ensure_tape(root)
    ids = _ids(_read_tape(tape_path(root)))
    return (max(ids) + 1) if ids else 1


def _normalize_take(obj: dict[str, Any]) -> dict[str, str]:
    extra = obj.get("extra")
    if isinstance(extra, dict):
        extra_s = json.dumps(extra, ensure_ascii=False)
    else:
        extra_s = str(extra or "")
    return {
        "id": str(obj.get("id") or ""),
        "date": str(obj.get("date") or ""),
        "time": str(obj.get("time") or ""),
        "kind": str(obj.get("kind") or "dump"),
        "score": str(obj.get("score") if obj.get("score") is not None else ""),
        "text": str(obj.get("text") or ""),
        "structured": str(obj.get("structured") or ""),
        "source": str(obj.get("source") or "clip"),
        "schema": str(obj.get("schema") or SCHEMA),
        "extra": extra_s,
    }


def _take_obj(row: dict[str, str]) -> dict[str, Any]:
    extra: Any = row.get("extra") or {}
    if isinstance(extra, str):
        if extra.strip().startswith("{"):
            try:
                extra = json.loads(extra)
            except json.JSONDecodeError:
                extra = {"raw": extra}
        elif not extra.strip():
            extra = {}
        else:
            extra = {"raw": extra}
    if not isinstance(extra, dict):
        extra = {}
    try:
        score: Any = float(row.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    return {
        "id": str(row.get("id") or ""),
        "date": str(row.get("date") or ""),
        "time": str(row.get("time") or ""),
        "kind": str(row.get("kind") or "dump"),
        "score": score,
        "text": str(row.get("text") or ""),
        "structured": str(row.get("structured") or ""),
        "source": str(row.get("source") or "clip"),
        "schema": SCHEMA,
        "extra": extra,
    }


def _read_tape(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
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
        if isinstance(obj, dict) and str(obj.get("text") or "").strip():
            rows.append(_normalize_take(obj))
    return rows


def _write_tape(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_take_obj(r), ensure_ascii=False) for r in rows]
    path.write_text(("\n".join(lines) + ("\n" if lines else "")), encoding="utf-8")


def _append_tape_line(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(_take_obj(row), ensure_ascii=False) + "\n")


def import_from_csv(root: Path | str) -> list[dict[str, str]]:
    """Union ledger.csv (machine twin) with transcriptions.csv (speech twin)."""
    root = Path(root)
    led = [_normalize_take(r) for r in _read_csv(ledger_path(root))]
    trans = _read_csv(trans_path(root))
    seen = {(r.get("text") or "").strip() for r in led if (r.get("text") or "").strip()}
    n = max(_ids(led), default=0)
    out = list(led)
    for t in trans:
        text = (t.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        n += 1
        out.append(
            _normalize_take(
                {
                    "id": str(n),
                    "date": t.get("date") or "",
                    "time": "",
                    "kind": "dump",
                    "score": 0.0,
                    "text": text,
                    "structured": text,
                    "source": "transcriptions.csv",
                    "schema": SCHEMA,
                    "extra": {"imported": "transcriptions.csv"},
                }
            )
        )
    return out


def ensure_tape(root: Path | str) -> Path:
    """Create takes.jsonl from CSV twins if the tape is missing. CSVs stay."""
    root = Path(root)
    path = tape_path(root)
    if path.is_file():
        return path
    rows = import_from_csv(root)
    if rows:
        _write_tape(path, rows)
    return path


def append(
    root: Path | str,
    *,
    text: str,
    kind: str = "dump",
    score: float = 0.0,
    structured: str = "",
    source: str = "clip",
    extra: dict[str, Any] | None = None,
    when: datetime | None = None,
) -> dict[str, str]:
    """Append one take. Empty text is refused (useless)."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text — not stored")
    root = _root(root)
    when = when or datetime.now()
    nid = next_id(root)
    day = when.strftime("%Y-%m-%d")
    clock = when.strftime("%H:%M:%S")
    row = {
        "id": str(nid),
        "date": day,
        "time": clock,
        "kind": kind or "dump",
        "score": str(score),
        "text": text,
        "structured": structured or text,
        "source": source,
        "schema": str(SCHEMA),
        "extra": json.dumps(extra or {}, ensure_ascii=False),
    }
    _append_tape_line(tape_path(root), row)
    return row


def list_takes(root: Path | str) -> list[dict[str, str]]:
    """Tape rows in file order. Imports CSV twins once if the tape is missing."""
    root = Path(root)
    ensure_tape(root)
    return _read_tape(tape_path(root))


def update_text(root: Path | str, take_id: str, text: str) -> dict[str, str]:
    """Replace transcription text for one id. Empty refused. Kind is not retouched."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text — not stored")
    root = Path(root)
    ensure_tape(root)
    wanted = str(take_id).strip()
    rows = _read_tape(tape_path(root))
    idx = next(
        (i for i, r in enumerate(rows) if str(r.get("id") or "").strip() == wanted),
        None,
    )
    if idx is None:
        raise ValueError(f"no take id {wanted}")
    old = rows[idx].get("text") or ""
    rows[idx]["text"] = text
    structured = rows[idx].get("structured") or ""
    if structured.strip() == old.strip() or not structured.strip():
        rows[idx]["structured"] = text
    _write_tape(tape_path(root), rows)
    return rows[idx]


def _stamp_date(name: str) -> str:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", name)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


def _text_from_item(folder: Path) -> tuple[str, dict[str, Any]]:
    extra: dict[str, Any] = {"folder": str(folder)}
    chunks: list[str] = []
    meta_path = folder / "meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}
        if isinstance(meta, dict):
            extra["meta"] = {
                k: meta.get(k)
                for k in ("stamp", "sampled_by", "activity", "duration_sec", "audio")
                if k in meta
            }
            note = str(meta.get("note") or "").strip()
            if note:
                chunks.append(note)
    for p in sorted(folder.iterdir()) if folder.is_dir() else []:
        if p.name.lower() in TEXT_NAMES:
            t = p.read_text(encoding="utf-8", errors="replace").strip()
            if t and t not in chunks:
                chunks.append(t)
    return "\n\n".join(chunks).strip(), extra


def harvest(root: Path | str) -> list[dict[str, str]]:
    """Pull non-empty text items from nested test-write junk onto the tape."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    items: list[tuple[str, str, dict[str, Any]]] = []

    journal = root / "journal"
    scan_roots = []
    if journal.is_dir():
        scan_roots.append(journal)
    mh = root / "macrohard" / "sessions"
    if mh.is_dir():
        scan_roots.append(mh)
    for base in scan_roots:
        for child in sorted(base.iterdir()):
            if not child.is_dir():
                continue
            text, extra = _text_from_item(child)
            if not text:
                continue
            day = _stamp_date(child.name) or datetime.now().strftime("%Y-%m-%d")
            items.append((day, text, extra))

    for loose in sorted(root.glob("*.txt")):
        if loose.name in KEEP:
            continue
        t = loose.read_text(encoding="utf-8", errors="replace").strip()
        if not t or t.lower().startswith("dogfood capture"):
            continue
        day = _stamp_date(loose.stem) or "2026-08-11"
        items.append((day, t, {"file": loose.name}))

    written: list[dict[str, str]] = []
    for day, text, extra in items:
        when = datetime.strptime(day, "%Y-%m-%d")
        written.append(
            append(
                root,
                text=text,
                kind="dump",
                source="harvest",
                extra=extra,
                when=when,
            )
        )
    return written


def purge(root: Path | str) -> list[str]:
    """Delete everything under root except the tape and any leftover CSVs."""
    root = Path(root)
    removed: list[str] = []
    if not root.is_dir():
        return removed
    for child in list(root.iterdir()):
        if child.name in KEEP:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            removed.append(str(child))
        else:
            try:
                child.unlink()
                removed.append(str(child))
            except OSError:
                pass
    return removed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="journal-clip speech tape store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("harvest")
    h.add_argument("--root", required=True)
    h.add_argument("--purge", action="store_true")
    a = sub.add_parser("append")
    a.add_argument("--root", required=True)
    a.add_argument("--text", required=True)
    a.add_argument("--kind", default="dump")
    a.add_argument("--structured", default="")
    a.add_argument("--source", default="clip")
    u = sub.add_parser("update-text")
    u.add_argument("--root", required=True)
    u.add_argument("--id", required=True)
    u.add_argument("--text", required=True)
    p = sub.add_parser("purge")
    p.add_argument("--root", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "harvest":
        rows = harvest(args.root)
        print(f"harvested {len(rows)}")
        if args.purge:
            gone = purge(args.root)
            print(f"purged {len(gone)}")
        return 0
    if args.cmd == "append":
        row = append(
            args.root,
            text=args.text,
            kind=args.kind,
            structured=args.structured,
            source=args.source,
        )
        print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.cmd == "update-text":
        row = update_text(args.root, args.id, args.text)
        print(json.dumps(row, ensure_ascii=False))
        return 0
    if args.cmd == "purge":
        gone = purge(args.root)
        print(f"purged {len(gone)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
