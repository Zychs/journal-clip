#!/usr/bin/env python3
"""Out-of-process heavy steps for journal-clip.

Whisper → nomic-embed-text (text only) → cosine vs ≤8 prototypes → local 7B.

Prints JSON. Does not write the journal. Does not delete the wav.
Zig owns record / write / shred.

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

from clip_config import load_config, resolve_system_prompt, resolved_out_dir
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
    if na <= 0.0 or nb <= 0.0:
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


def transcribe_wav(wav_path: Path, whisper_model: str) -> str:
    import whisper  # heavy; local weights

    model = whisper.load_model(whisper_model)
    result = model.transcribe(str(wav_path))
    return str(result.get("text") or "").strip()


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
    transcribe_fn: Callable[[Path, str], str] | None = None,
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

    if text is not None and text.strip():
        transcript = text.strip()
    elif wav is not None:
        tfn = transcribe_fn or transcribe_wav
        transcript = tfn(wav, whisper_model)
    else:
        raise SystemExit("need --wav or --text")

    if not transcript:
        raise RuntimeError("empty transcript")

    efn = embed_fn or (lambda ts: embed_texts(ts, embed_model))
    degraded: list[str] = []
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

    out_root = resolved_out_dir(cfg)
    dest_rel = "takes.jsonl"
    stored_id = ""
    if config is None:
        stored = store_append(
            out_root,
            text=transcript,
            kind=kind,
            score=score,
            structured=structured,
            source="clip",
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
