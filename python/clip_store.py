#!/usr/bin/env python3
"""Surface store for journal-clip - the read view over three separate systems.

The pipeline produces three data products with three different preservation
rules, and they are kept in three different places:

  1. raw audio          clip_audio.py       never overwrite
  2. transcript         clip_transcript.py  version alongside the model
  3. derived semantics  clip_semantics.py   revisable output, not ground truth

`takes.jsonl` is no longer where anything lives. It is a **projection** -
one flat line per take, rebuilt from systems 2 and 3 on every write, kept
because the UIs and every outside reader already speak it. Delete it and
`project()` builds it back. Delete a system and you have lost something.

Ids are monotonic integers. Never reused. schema=1.
CSV twins are imported if present, never deleted, never written.
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

import clip_audio
import clip_semantics
import clip_transcript

SCHEMA = 1
TAPE_NAME = "takes.jsonl"
TRANS_NAME = "transcriptions.csv"
LEDGER_NAME = "ledger.csv"
# The three systems are never swept by purge(). Neither is the projection.
SYSTEM_DIRS = {
    clip_audio.AUDIO_DIR,
    clip_transcript.TRANSCRIPT_DIR,
    clip_semantics.SEMANTICS_DIR,
}
KEEP = {TAPE_NAME, TRANS_NAME, LEDGER_NAME} | SYSTEM_DIRS
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


def _ids(rows: list[dict[str, str]]) -> list[int]:
    ids: list[int] = []
    for r in rows:
        try:
            ids.append(int(str(r.get("id") or "").strip()))
        except ValueError:
            continue
    return ids


def next_id(root: Path) -> int:
    """Next take id. Owned by the transcript log - every take has a transcript."""
    ensure(root)
    return clip_transcript.next_take_id(root)


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


# --------------------------------------------------------------------------
# projection: three systems -> one flat tape
# --------------------------------------------------------------------------


def _row_from_systems(
    take_id: str,
    transcript: dict[str, Any],
    semantics: dict[str, Any] | None,
    audio: dict[str, Any] | None,
) -> dict[str, str]:
    """Flatten one take across the three systems into a legacy tape row.

    Nothing here is authoritative - it is a copy, and `extra.provenance`
    says exactly which version and revision of which system it came from.
    """
    sem = semantics or {}
    extra: dict[str, Any] = dict(sem.get("extra") or {})
    inner = transcript.get("extra")
    if isinstance(inner, dict):
        for k, v in inner.items():
            extra.setdefault(k, v)
    degraded = sem.get("degraded") or []
    if degraded:
        extra["degraded"] = degraded
    extra["provenance"] = {
        "transcript_version": transcript.get("version"),
        "transcript_model": transcript.get("model_id"),
        "transcript_produced_by": transcript.get("produced_by"),
        "semantics_revision": sem.get("revision"),
        "semantics_ground_truth": False,
        "audio_uid": (audio or {}).get("uid") or transcript.get("audio_uid") or "",
        "audio_sha256": (audio or {}).get("sha256") or "",
    }
    text = str(transcript.get("text") or "")
    return {
        "id": take_id,
        "date": str(transcript.get("date") or ""),
        "time": str(transcript.get("time") or ""),
        "kind": str(sem.get("kind") or "dump"),
        "score": str(sem.get("score") if sem.get("score") is not None else 0.0),
        "text": text,
        "structured": str(sem.get("structured") or text),
        "source": str(transcript.get("source") or "clip"),
        "schema": str(SCHEMA),
        "extra": json.dumps(extra, ensure_ascii=False),
    }


def _sort_key(take_id: str) -> tuple[int, int, str]:
    try:
        return (0, int(take_id), "")
    except ValueError:
        return (1, 0, take_id)


def compose(root: Path | str) -> list[dict[str, str]]:
    """Read the three systems and return the flat take view. No writes."""
    root = Path(root)
    transcripts = clip_transcript.latest_by_take(root)
    if not transcripts:
        return []
    semantics = clip_semantics.latest_by_take(root)
    audio = {
        str(r.get("take_id") or ""): r
        for r in clip_audio.list_audio(root)
        if str(r.get("take_id") or "")
    }
    rows: list[dict[str, str]] = []
    for take_id in sorted(transcripts, key=_sort_key):
        rows.append(
            _row_from_systems(
                take_id,
                transcripts[take_id],
                semantics.get(take_id),
                audio.get(take_id),
            )
        )
    return rows


def project(root: Path | str) -> Path:
    """Rebuild takes.jsonl from the three systems. Cheap, and always safe."""
    root = Path(root)
    path = tape_path(root)
    _write_tape(path, compose(root))
    return path


# --------------------------------------------------------------------------
# migration: one flat tape -> three systems
# --------------------------------------------------------------------------


def _adopt_legacy(root: Path, rows: list[dict[str, str]]) -> int:
    """Split old flat rows across the three systems. Audio is simply absent.

    A migrated transcript is honest about its provenance: engine "import",
    no model name, because nobody recorded which Whisper produced it.
    """
    n = 0
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        take_id = str(row.get("id") or "").strip() or str(n + 1)
        day = str(row.get("date") or "") or datetime.now().strftime("%Y-%m-%d")
        clock = str(row.get("time") or "") or "00:00:00"
        try:
            when = datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            when = datetime.now()
        extra: Any = row.get("extra") or "{}"
        if isinstance(extra, str):
            try:
                extra = json.loads(extra) if extra.strip().startswith("{") else {}
            except json.JSONDecodeError:
                extra = {}
        if not isinstance(extra, dict):
            extra = {}
        source = str(row.get("source") or "clip")
        clip_transcript.append_version(
            root,
            take_id,
            text,
            engine=clip_transcript.IMPORTED,
            model=str(extra.get("whisper_model") or ""),
            source=source,
            when=when,
            extra={**extra, "migrated_from": TAPE_NAME},
        )
        try:
            score = float(row.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        clip_semantics.append_revision(
            root,
            take_id,
            transcript_version=1,
            kind=str(row.get("kind") or "dump"),
            score=score,
            structured=str(row.get("structured") or text),
            embed_model=str(extra.get("embed_model") or ""),
            chat_model=str(extra.get("chat_model") or ""),
            prompt_source=str(extra.get("prompt_source") or ""),
            degraded=extra.get("degraded") or [],
            when=when,
            extra={"migrated_from": TAPE_NAME},
        )
        n += 1
    return n


def ensure(root: Path | str) -> Path:
    """Make the three systems real, migrating a legacy tape or CSVs once.

    Idempotent: once transcripts.jsonl exists, this does nothing.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    if clip_transcript.log_path(root).is_file():
        return tape_path(root)
    legacy = _read_tape(tape_path(root)) or import_from_csv(root)
    if legacy:
        _adopt_legacy(root, legacy)
        project(root)
    return tape_path(root)


def ensure_tape(root: Path | str) -> Path:
    """Back-compat alias. The tape is a projection now; the systems are the store."""
    return ensure(root)


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------


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
    audio_uid: str = "",
    engine: str = clip_transcript.MACHINE,
    model: str = "",
    segments: list[dict[str, Any]] | None = None,
    language: str = "",
    tags: list[str] | None = None,
    embedding: list[float] | None = None,
    embed_model: str = "",
    chat_model: str = "",
    prompt_source: str = "",
    inferred: dict[str, Any] | None = None,
    degraded: list[str] | None = None,
) -> dict[str, str]:
    """Land one take across all three systems. Empty text is refused (useless).

    Writes transcript v1 (system 2) and semantics r1 (system 3), binds any
    already-archived audio (system 1) to the new id, then reprojects.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text - not stored")
    root = _root(root)
    ensure(root)
    when = when or datetime.now()
    take_id = str(clip_transcript.next_take_id(root))

    tv = clip_transcript.append_version(
        root,
        take_id,
        text,
        engine=engine,
        model=model,
        audio_uid=audio_uid,
        segments=segments,
        language=language,
        source=source,
        when=when,
        extra=extra,
    )
    clip_semantics.append_revision(
        root,
        take_id,
        transcript_version=int(tv["version"]),
        kind=kind,
        score=score,
        structured=structured or text,
        tags=tags,
        embedding=embedding,
        embed_model=embed_model,
        chat_model=chat_model,
        prompt_source=prompt_source,
        inferred=inferred,
        degraded=degraded,
        when=when,
    )
    if audio_uid:
        clip_audio.bind_take(root, audio_uid, take_id)
    project(root)
    row = next((r for r in compose(root) if r["id"] == take_id), None)
    if row is None:  # unreachable unless a system was deleted mid-write
        raise RuntimeError(f"take {take_id} did not compose after write")
    return row


def list_takes(root: Path | str) -> list[dict[str, str]]:
    """Flat take view, oldest id first. Migrates a legacy tape or CSVs once."""
    root = Path(root)
    ensure(root)
    return compose(root)


def update_text(root: Path | str, take_id: str, text: str) -> dict[str, str]:
    """Correct a transcript. Appends a version; the model's reading is kept.

    Kind is never retouched - that is system 3's business. What happens to
    the semantics depends on whether they were ever really inferred:

    * `structured` was only a mirror of the transcript (no 7B ran) - a new
      revision mirrors the corrected text, because nothing was interpreted.
    * `structured` is genuine model output - it is left exactly as it was,
      still pointing at the version it was derived from, so that
      `clip_semantics.stale()` reports it as owed a recompute.

    Either way the old transcript stays in system 2 and no interpretation
    is silently rewritten to look like it had read the new text.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("empty text - not stored")
    root = Path(root)
    ensure(root)
    wanted = str(take_id).strip()
    before = clip_transcript.latest(root, wanted)
    if before is None:
        raise ValueError(f"no take id {wanted}")
    old_text = str(before.get("text") or "").strip()
    after = clip_transcript.update(root, wanted, text, source=clip_transcript.HUMAN)

    sem = clip_semantics.latest(root, wanted)
    if sem is not None:
        structured = str(sem.get("structured") or "").strip()
        if not structured or structured == old_text:
            # Never interpreted - a mirror can follow the correction freely.
            clip_semantics.append_revision(
                root,
                wanted,
                transcript_version=int(after["version"]),
                kind=str(sem.get("kind") or "dump"),
                score=float(sem.get("score") or 0.0),
                structured=text,
                summary=str(sem.get("summary") or ""),
                tags=sem.get("tags") or [],
                embed_model=str(sem.get("embed_model") or ""),
                chat_model=str(sem.get("chat_model") or ""),
                prompt_source=str(sem.get("prompt_source") or ""),
                extra={"restated_after": "transcript-correction"},
            )
    project(root)
    row = next((r for r in compose(root) if r["id"] == wanted), None)
    if row is None:
        raise ValueError(f"no take id {wanted}")
    return row


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
                engine=clip_transcript.IMPORTED,
                extra=extra,
                when=when,
            )
        )
    return written


def purge(root: Path | str) -> list[str]:
    """Delete everything under root except the three systems, the tape, and CSVs."""
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


def systems_status(root: Path | str) -> dict[str, Any]:
    """One glance at all three products and whether their rules still hold."""
    root = Path(root)
    ensure(root)
    transcripts = clip_transcript.latest_by_take(root)
    versions = {t: int(r.get("version") or 0) for t, r in transcripts.items()}
    kept = clip_audio.clips(root)
    return {
        "root": str(root),
        "raw_audio": {
            "rule": "never overwrite",
            "clips": len(kept),
            "bytes": sum(int(r.get("bytes") or 0) for r in kept),
            "integrity": clip_audio.verify(root) or "intact",
        },
        "transcript": {
            "rule": "version alongside transcription model",
            "takes": len(transcripts),
            "versions": len(clip_transcript.all_versions(root)),
            "transcription_models": clip_transcript.models_used(root),
            "read_by": clip_transcript.producers_used(root),
        },
        "derived_semantics": {
            "rule": "revisable model output, not ground truth",
            "ground_truth": False,
            "revisions": len(clip_semantics.all_revisions(root)),
            "models": clip_semantics.models_used(root),
            "stale": clip_semantics.stale(root, versions),
        },
        "projection": {
            "file": TAPE_NAME,
            "rule": "rebuildable - holds nothing of its own",
            "rows": len(compose(root)),
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="journal-clip take view over the three systems")
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
    r = sub.add_parser("project", help="rebuild takes.jsonl from the three systems")
    r.add_argument("--root", required=True)
    s = sub.add_parser("status", help="all three products and their preservation rules")
    s.add_argument("--root", required=True)
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
    if args.cmd == "project":
        print(project(args.root))
        return 0
    if args.cmd == "status":
        print(json.dumps(systems_status(args.root), indent=2, default=str))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
