#!/usr/bin/env python3
"""Out-of-process heavy steps for journal-clip.

Three products come out of one take, and they are produced in that order:

  1. raw audio     archive the wav first, before anything can go wrong
  2. transcript    Whisper, tagged with the model that produced it
  3. semantics     nomic-embed-text → cosine vs ≤8 prototypes → local 7B

Step 1 runs before step 2 on purpose. The audio is the only irreplaceable
artifact, so it is preserved even if Whisper crashes on the next line.

Prints JSON. Does not delete the wav - the caller's temp copy is shredded
after this returns, by which time the archived copy already exists.
Zig owns record / shred.

Local only. No paid APIs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import clip_audio
from clip_config import keeps_audio, load_config, resolve_system_prompt, resolved_out_dir
from clip_store import append as store_append

HERE = Path(__file__).resolve().parent
DEFAULT_PROTO = HERE / "prototypes.json"
OLLAMA = os.environ.get("SESEFUS_CLIP_OLLAMA", "http://127.0.0.1:11434").rstrip("/")


def load_prototypes(path: Path | None = None) -> dict[str, Any]:
    p = path or DEFAULT_PROTO
    data = json.loads(p.read_text(encoding="utf-8"))
    kinds = data.get("kinds") or []
    if not kinds or len(kinds) > 10:
        raise SystemExit(f"prototype set must be 1..10, got {len(kinds)}")
    return data


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    # A tiny vector is an absent/degenerate embedding, not evidence that two
    # texts are semantically identical.  Without this floor, e.g. two
    # near-zero fallback vectors normalize to a misleading cosine of 1.0.
    if na <= 1e-3 or nb <= 1e-3:
        return 0.0
    return dot / math.sqrt(na * nb)


def _http_json(url: str, payload: dict[str, Any], timeout: float = 180.0) -> dict[str, Any]:
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=raw, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"local http failed {url}: {e}") from e


def embed_texts(texts: list[str], model: str) -> list[list[float]]:
    """House embedder: Ollama nomic-embed-text. Text only. Never audio."""
    if not texts:
        return []
    data = _http_json(f"{OLLAMA}/api/embed", {"model": model, "input": texts}, timeout=120.0)
    embs = data.get("embeddings")
    if not isinstance(embs, list) or len(embs) != len(texts):
        raise RuntimeError("nomic-embed-text returned no embeddings (is Ollama up? ollama pull nomic-embed-text)")
    return embs


def transcribe_wav(wav_path: Path, whisper_model: str) -> dict[str, Any]:
    """Whisper's full reading: text plus its own segmentation and language.

    Segments are the seed of the diarization record - kept in system 2
    beside the text they came from, not flattened away into it.
    """
    import whisper  # heavy; local weights

    model = whisper.load_model(whisper_model)
    result = model.transcribe(str(wav_path))
    segments = []
    for seg in result.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        segments.append(
            {
                "start": seg.get("start"),
                "end": seg.get("end"),
                "speaker": "",  # no diarizer yet; the slot is the point
                "text": str(seg.get("text") or "").strip(),
            }
        )
    return {
        "text": str(result.get("text") or "").strip(),
        "segments": segments,
        "language": str(result.get("language") or ""),
    }


def _as_reading(got: Any) -> dict[str, Any]:
    """Accept a plain string or a full reading from any transcribe_fn."""
    if isinstance(got, dict):
        return {
            "text": str(got.get("text") or "").strip(),
            "segments": list(got.get("segments") or []),
            "language": str(got.get("language") or ""),
        }
    return {"text": str(got or "").strip(), "segments": [], "language": ""}


def pick_kind(
    transcript: str,
    kinds: list[dict[str, Any]],
    embed_fn: Callable[[list[str]], list[list[float]]],
    min_score: float = 0.18,
) -> tuple[str, float]:
    texts = [transcript] + [str(k.get("prototype") or "") for k in kinds]
    embs = embed_fn(texts)
    if len(embs) != len(texts):
        return "dump", 0.0
    tvec = embs[0]
    best_id = "dump"
    best = -1.0
    for kind, vec in zip(kinds, embs[1:]):
        s = cosine(tvec, vec)
        if s > best:
            best = s
            best_id = str(kind.get("id") or "dump")
    if best < min_score:
        return "dump", best
    return best_id, best


def structure(
    system: str,
    transcript: str,
    model: str,
) -> str:
    data = _http_json(
        f"{OLLAMA}/api/chat",
        {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": transcript},
            ],
            "options": {"temperature": 0.2},
        },
        timeout=300.0,
    )
    msg = data.get("message") or {}
    text = str(msg.get("content") or "").strip()
    if not text:
        raise RuntimeError(f"7B returned empty ({model}). Is Ollama serving that model?")
    return text


def run(
    *,
    wav: Path | None,
    text: str | None,
    proto_path: Path,
    no_llm: bool = False,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    structure_fn: Callable[[str, str, str], str] | None = None,
    transcribe_fn: Callable[[Path, str], Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = load_prototypes(proto_path)
    kinds: list[dict[str, Any]] = spec["kinds"]
    embed_model = str(spec.get("embed_model") or "nomic-embed-text")
    chat_model = os.environ.get("SESEFUS_CLIP_MODEL") or str(
        spec.get("chat_model") or "qwen2.5:7b-instruct"
    )
    whisper_model = os.environ.get("SESEFUS_CLIP_WHISPER") or str(
        spec.get("whisper_model") or "base"
    )
    cfg = config if config is not None else load_config()
    out_root = resolved_out_dir(cfg)
    live = config is None  # a caller-supplied config means "compute, don't store"

    # ---- system 1: raw audio -------------------------------------------
    # First, and before Whisper can fail. Never overwrites; re-archiving the
    # same bytes is a no-op. A failure here degrades the take, it does not
    # sink it - text still lands.
    audio_uid = ""
    audio_row: dict[str, Any] = {}
    degraded: list[str] = []
    retain = keeps_audio(cfg)
    if wav is not None and live and retain:
        try:
            audio_row = clip_audio.archive(
                out_root,
                wav,
                device_index=int(cfg.get("input_index") or 0),
                source="clip",
            )
            audio_uid = str(audio_row.get("uid") or "")
        except Exception as e:
            degraded.append(f"audio:{e}")

    # ---- system 2: transcript ------------------------------------------
    if text is not None and text.strip():
        reading = {"text": text.strip(), "segments": [], "language": ""}
        engine, engine_model = "typed", ""
    elif wav is not None:
        tfn = transcribe_fn or transcribe_wav
        reading = _as_reading(tfn(wav, whisper_model))
        engine, engine_model = "whisper", whisper_model
    else:
        raise SystemExit("need --wav or --text")

    transcript = reading["text"]
    if not transcript:
        raise RuntimeError("empty transcript")

    # ---- system 3: derived semantics ------------------------------------
    efn = embed_fn or (lambda ts: embed_texts(ts, embed_model))
    try:
        kind, score = pick_kind(transcript, kinds, efn)
    except Exception as e:
        kind, score = "dump", 0.0
        degraded.append(f"embed:{e}")
    row = next((k for k in kinds if k.get("id") == kind), kinds[0])
    builtin = str(row.get("system") or "")
    system, prompt_source = resolve_system_prompt(kind, builtin, cfg)

    structured = ""
    if no_llm:
        structured = (
            f"## gist\n{transcript[:240]}\n\n## body\n{transcript}\n\n## tags\n{kind}\n\n## keep\n"
        )
    else:
        try:
            sfn = structure_fn or structure
            structured = sfn(system, transcript, chat_model)
        except Exception as e:
            structured = transcript
            degraded.append(f"llm:{e}")
            prompt_source = "degraded:raw-transcript"

    dest_rel = "takes.jsonl"
    stored_id = ""
    if live:
        stored = store_append(
            out_root,
            text=transcript,
            kind=kind,
            score=score,
            structured=structured,
            source="clip",
            audio_uid=audio_uid,
            engine=engine,
            model=engine_model,
            segments=reading["segments"],
            language=reading["language"],
            embed_model=embed_model,
            chat_model=chat_model,
            prompt_source=prompt_source,
            degraded=degraded,
            extra={"degraded": degraded} if degraded else {},
        )
        stored_id = stored["id"]

    return {
        "ok": True,
        "transcript": transcript,
        "kind": kind,
        "score": round(float(score), 4),
        "structured": structured,
        "embed_model": embed_model,
        "chat_model": chat_model,
        "whisper_model": whisper_model,
        "embed_on": "text",
        "prompt_source": prompt_source,
        "dest_rel": dest_rel,
        "out_dir": str(out_root),
        "input_index": int(cfg.get("input_index") or 0),
        "id": stored_id,
        "degraded": degraded,
        # what each of the three systems produced for this take
        "audio_uid": audio_uid,
        "audio_path": str(audio_row.get("path") or ""),
        "audio_sha256": str(audio_row.get("sha256") or ""),
        "audio_retained": bool(audio_uid),
        "transcript_engine": engine,
        "transcript_model": engine_model,
        "segments": len(reading["segments"]),
        "language": reading["language"],
        "semantics_ground_truth": False,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="journal-clip heavy sidecar")
    ap.add_argument("--wav", type=Path)
    ap.add_argument("--text")
    ap.add_argument("--out", type=Path, help="write JSON here (also printed)")
    ap.add_argument("--prototypes", type=Path, default=DEFAULT_PROTO)
    ap.add_argument("--no-llm", action="store_true", help="skip 7B (tests)")
    args = ap.parse_args(argv)
    try:
        result = run(
            wav=args.wav,
            text=args.text,
            proto_path=args.prototypes,
            no_llm=args.no_llm,
        )
    except Exception as e:
        err = {"ok": False, "error": str(e)}
        blob = json.dumps(err, ensure_ascii=False)
        print(blob)
        if args.out:
            args.out.write_text(blob + "\n", encoding="utf-8")
        return 1
    blob = json.dumps(result, ensure_ascii=False, indent=2)
    print(blob)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(blob + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
