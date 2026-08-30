#!/usr/bin/env python3
"""System 1 of 3 - raw audio.

Purpose: acoustic / prosodic research, retraining, audit.
Preservation rule: **never overwrite**.

The wav is the only artifact in this pipeline that cannot be regenerated.
Transcripts can be re-run; semantics can be re-inferred; the sound of the
take happened once. So this module only ever *adds*:

  <root>/audio/<YYYY>/<MM>/<stamp>-<sha8>.wav   immutable, read-only on disk
  <root>/audio/audio.jsonl                      append-only manifest

Destination names carry the content hash, so the same bytes always land on
the same path and re-archiving is idempotent. A path that exists with
*different* bytes is an OverwriteRefused, never a silent clobber.

Nothing here transcribes, tags, or interprets. Those are systems 2 and 3.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import stat
import wave
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = 1
AUDIO_DIR = "audio"
MANIFEST_NAME = "audio.jsonl"
CHUNK = 1 << 20


class OverwriteRefused(RuntimeError):
    """Raised when archiving would replace bytes already preserved."""


def audio_root(root: Path | str) -> Path:
    return Path(root) / AUDIO_DIR


def manifest_path(root: Path | str) -> Path:
    return audio_root(root) / MANIFEST_NAME


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def probe_wav(path: Path) -> dict[str, Any]:
    """Best-effort PCM header read. A non-wav still archives; it just has no shape."""
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as w:
            frames = w.getnframes()
            rate = w.getframerate() or 0
            return {
                "sample_rate": rate,
                "channels": w.getnchannels(),
                "bits": w.getsampwidth() * 8,
                "frames": frames,
                "seconds": round(frames / rate, 3) if rate else 0.0,
            }
    except (wave.Error, OSError, EOFError):
        return {"sample_rate": 0, "channels": 0, "bits": 0, "frames": 0, "seconds": 0.0}


def _read_manifest(path: Path) -> list[dict[str, Any]]:
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
        if isinstance(obj, dict) and obj.get("uid"):
            rows.append(obj)
    return rows


def _append_manifest(path: Path, row: dict[str, Any]) -> None:
    """Append-only. This file is opened for writing here and nowhere else."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _freeze(path: Path) -> None:
    """Clear the write bit. A guard against accident, not against an attacker."""
    try:
        mode = path.stat().st_mode
        path.chmod(mode & ~stat.S_IWRITE & ~stat.S_IWGRP & ~stat.S_IWOTH)
    except OSError:
        pass


def _thaw(path: Path) -> None:
    try:
        path.chmod(path.stat().st_mode | stat.S_IWRITE)
    except OSError:
        pass


def list_audio(root: Path | str) -> list[dict[str, Any]]:
    """Every manifest line, in order. This is a log: a uid can appear twice."""
    return _read_manifest(manifest_path(root))


def clips(root: Path | str) -> list[dict[str, Any]]:
    """One current row per archived clip - the log folded down, newest wins.

    A clip gets a second line when its take_id is bound after archiving,
    which is normal: the id does not exist yet when the bytes are saved.
    """
    latest: dict[str, dict[str, Any]] = {}
    for row in list_audio(root):
        latest[str(row.get("uid") or "")] = row
    return list(latest.values())


def by_take(root: Path | str, take_id: str | int) -> dict[str, Any] | None:
    """Newest manifest row bound to this take, if any."""
    wanted = str(take_id).strip()
    found = None
    for row in list_audio(root):
        if str(row.get("take_id") or "").strip() == wanted:
            found = row
    return found


def by_uid(root: Path | str, uid: str) -> dict[str, Any] | None:
    found = None
    for row in list_audio(root):
        if str(row.get("uid") or "") == uid:
            found = row
    return found


def resolve(root: Path | str, row: dict[str, Any]) -> Path:
    return Path(root) / str(row.get("path") or "")


def archive(
    root: Path | str,
    wav: Path | str,
    *,
    take_id: str | int = "",
    device_index: int = 0,
    source: str = "clip",
    when: datetime | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy `wav` into the immutable audio store and return its manifest row.

    Idempotent on identical bytes. Never replaces a differing file.
    The caller may then shred its temp copy: this one is the preserved product.
    """
    wav = Path(wav)
    if not wav.is_file():
        raise FileNotFoundError(f"no wav to archive: {wav}")
    root = Path(root)
    when = when or datetime.now()

    digest = sha256_file(wav)
    stamp = when.strftime("%Y%m%d-%H%M%S")
    uid = f"{stamp}-{digest[:8]}"
    rel = Path(AUDIO_DIR) / when.strftime("%Y") / when.strftime("%m") / f"{uid}.wav"
    dest = root / rel

    known = by_uid(root, uid)
    if dest.exists():
        if sha256_file(dest) != digest:
            raise OverwriteRefused(
                f"{dest} holds different audio than {wav} - refusing to overwrite"
            )
        if known is not None and str(known.get("take_id") or "") == str(take_id or ""):
            return known
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        shutil.copyfile(wav, tmp)
        if dest.exists():  # lost a race between the check above and now
            _thaw(tmp)
            tmp.unlink()
            if sha256_file(dest) != digest:
                raise OverwriteRefused(f"{dest} appeared with different audio")
        else:
            os.replace(tmp, dest)
        _freeze(dest)

    shape = probe_wav(dest)
    row = {
        "schema": SCHEMA,
        "uid": uid,
        "take_id": str(take_id or ""),
        "path": rel.as_posix(),
        "sha256": digest,
        "bytes": dest.stat().st_size,
        "captured": when.isoformat(timespec="seconds"),
        "device_index": int(device_index or 0),
        "source": source,
        **shape,
        "extra": dict(extra or {}),
    }
    _append_manifest(manifest_path(root), row)
    return row


def bind_take(root: Path | str, uid: str, take_id: str | int) -> dict[str, Any] | None:
    """Record a take_id for an already-archived uid by appending a new row.

    The earlier row is left in place - the manifest is a log, not a table.
    """
    row = by_uid(root, uid)
    if row is None:
        return None
    if str(row.get("take_id") or "") == str(take_id):
        return row
    fresh = dict(row)
    fresh["take_id"] = str(take_id)
    fresh["rebound"] = datetime.now().isoformat(timespec="seconds")
    _append_manifest(manifest_path(root), fresh)
    return fresh


def verify(root: Path | str) -> list[dict[str, str]]:
    """Audit: re-hash every manifest row. Empty list means the archive is intact."""
    root = Path(root)
    problems: list[dict[str, str]] = []
    seen: dict[str, str] = {}
    for row in list_audio(root):
        uid = str(row.get("uid") or "")
        path = resolve(root, row)
        want = str(row.get("sha256") or "")
        if not path.is_file():
            problems.append({"uid": uid, "problem": "missing", "path": str(path)})
            continue
        got = sha256_file(path)
        if got != want:
            problems.append(
                {
                    "uid": uid,
                    "problem": "hash-mismatch",
                    "path": str(path),
                    "expected": want,
                    "found": got,
                }
            )
        prior = seen.get(uid)
        if prior is not None and prior != want:
            problems.append({"uid": uid, "problem": "uid-reused", "path": str(path)})
        seen[uid] = want
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="journal-clip raw audio store (never overwrite)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("archive", help="copy a wav into the immutable store")
    a.add_argument("--root", required=True)
    a.add_argument("--wav", required=True)
    a.add_argument("--take", default="")
    ls = sub.add_parser("list")
    ls.add_argument("--root", required=True)
    v = sub.add_parser("verify", help="re-hash the archive against the manifest")
    v.add_argument("--root", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "archive":
        print(json.dumps(archive(args.root, args.wav, take_id=args.take), ensure_ascii=False))
        return 0
    if args.cmd == "list":
        for row in clips(args.root):
            print(
                f"{row['uid']}  take={row.get('take_id') or '-'}  "
                f"{row.get('seconds', 0)}s  {row.get('bytes', 0)}B  {row.get('path')}"
            )
        return 0
    if args.cmd == "verify":
        bad = verify(args.root)
        if not bad:
            print("audio archive intact")
            return 0
        for b in bad:
            print(json.dumps(b, ensure_ascii=False))
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
