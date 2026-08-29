#!/usr/bin/env python3
"""Persistent controls for journal-clip: change-dir, change-input, change-prompt.

Config lives at %USERPROFILE%\\.sesefus\\clip-config.json
(or SESEFUS_CLIP_CONFIG). Independent of out_dir so a dir change cannot lose the file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "out_dir": "",
    "input_index": 0,
    "prompt_file": "",
    "prompt_overrides": {},
}


def config_path() -> Path:
    env = os.environ.get("SESEFUS_CLIP_CONFIG")
    if env:
        return Path(env)
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return home / ".sesefus" / "clip-config.json"


def default_out_dir() -> Path:
    env = os.environ.get("SESEFUS_CLIP_INBOX")
    if env:
        return Path(env)
    vault = Path("V:/ssfs-vault/journal")
    if vault.is_dir():
        return vault
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return home / "test-write"


def load_config(path: Path | None = None) -> dict[str, Any]:
    p = path or config_path()
    cfg = dict(DEFAULTS)
    cfg["prompt_overrides"] = {}
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if isinstance(data.get("out_dir"), str):
                    cfg["out_dir"] = data["out_dir"]
                if isinstance(data.get("input_index"), int):
                    cfg["input_index"] = data["input_index"]
                if isinstance(data.get("prompt_file"), str):
                    cfg["prompt_file"] = data["prompt_file"]
                ov = data.get("prompt_overrides")
                if isinstance(ov, dict):
                    cfg["prompt_overrides"] = {
                        str(k): str(v) for k, v in ov.items() if isinstance(v, str)
                    }
        except (OSError, json.JSONDecodeError):
            pass
    return cfg


def save_config(cfg: dict[str, Any], path: Path | None = None) -> Path:
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "out_dir": str(cfg.get("out_dir") or ""),
        "input_index": int(cfg.get("input_index") or 0),
        "prompt_file": str(cfg.get("prompt_file") or ""),
        "prompt_overrides": dict(cfg.get("prompt_overrides") or {}),
    }
    p.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return p


def resolved_out_dir(cfg: dict[str, Any] | None = None) -> Path:
    cfg = cfg if cfg is not None else load_config()
    raw = str(cfg.get("out_dir") or "").strip()
    if raw:
        return Path(os.path.expandvars(raw)).expanduser()
    return default_out_dir()


def list_input_devices() -> list[tuple[int, str]]:
    """WinMM capture devices. Index is what change-input stores."""
    if sys.platform != "win32":
        return [(0, "default (non-windows)")]
    import ctypes
    from ctypes import wintypes

    class WAVEINCAPSA(ctypes.Structure):
        _fields_ = [
            ("wMid", wintypes.WORD),
            ("wPid", wintypes.WORD),
            ("vDriverVersion", wintypes.UINT),
            ("szPname", ctypes.c_char * 32),
            ("dwFormats", wintypes.DWORD),
            ("wChannels", wintypes.WORD),
            ("wReserved1", wintypes.WORD),
        ]

    winmm = ctypes.windll.winmm
    n = int(winmm.waveInGetNumDevs())
    out: list[tuple[int, str]] = []
    for i in range(n):
        caps = WAVEINCAPSA()
        rc = winmm.waveInGetDevCapsA(i, ctypes.byref(caps), ctypes.sizeof(caps))
        if rc == 0:
            name = caps.szPname.decode("mbcs", errors="replace").rstrip("\x00")
        else:
            name = f"(caps failed {rc})"
        out.append((i, name))
    if not out:
        out.append((0, "default"))
    return out


def resolve_system_prompt(kind: str, builtin: str, cfg: dict[str, Any]) -> tuple[str, str]:
    """Return (system_text, source_label). Cosine still picks kind/dir."""
    ov = cfg.get("prompt_overrides") or {}
    kind_path = ov.get(kind) if isinstance(ov, dict) else None
    if kind_path:
        p = Path(kind_path)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip(), f"override:{kind}:{p}"
    global_path = str(cfg.get("prompt_file") or "").strip()
    if global_path:
        p = Path(global_path)
        if p.is_file():
            return p.read_text(encoding="utf-8").strip(), f"prompt_file:{p}"
    return builtin, "builtin"


def cmd_change_dir(path: str | None) -> str:
    cfg = load_config()
    if not path:
        return f"out_dir={resolved_out_dir(cfg)}"
    dest = Path(os.path.expandvars(path)).expanduser().resolve()
    dest.mkdir(parents=True, exist_ok=True)
    cfg["out_dir"] = str(dest)
    save_config(cfg)
    return f"out_dir={dest}"


def cmd_change_input(index: str | None) -> str:
    cfg = load_config()
    devices = list_input_devices()
    if index is None or index in ("", "list", "--list"):
        lines = [f"[{i}] {name}" + ("  (current)" if i == int(cfg.get("input_index") or 0) else "") for i, name in devices]
        lines.append(f"current_index={int(cfg.get('input_index') or 0)}")
        return "\n".join(lines)
    try:
        n = int(index)
    except ValueError:
        raise SystemExit(f"change-input needs an integer index, got {index!r}")
    ids = [i for i, _ in devices]
    if ids and n not in ids:
        raise SystemExit(f"no capture device index {n}. {cmd_change_input('list')}")
    cfg["input_index"] = n
    save_config(cfg)
    return f"input_index={n}"


def cmd_change_prompt(path: str | None, *, kind: str | None, clear: bool) -> str:
    cfg = load_config()
    if clear:
        cfg["prompt_file"] = ""
        cfg["prompt_overrides"] = {}
        save_config(cfg)
        return "prompt cleared (builtin structure)"
    if not path:
        ov = cfg.get("prompt_overrides") or {}
        lines = [
            f"prompt_file={cfg.get('prompt_file') or '(none)'}",
            "prompt_overrides=" + (json.dumps(ov) if ov else "{}"),
        ]
        return "\n".join(lines)
    p = Path(os.path.expandvars(path)).expanduser().resolve()
    if not p.is_file():
        raise SystemExit(f"prompt file not found: {p}")
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit("prompt file is empty")
    if kind:
        ov = dict(cfg.get("prompt_overrides") or {})
        ov[kind] = str(p)
        cfg["prompt_overrides"] = ov
        save_config(cfg)
        return f"prompt_override[{kind}]={p}"
    cfg["prompt_file"] = str(p)
    save_config(cfg)
    return f"prompt_file={p}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="journal-clip controls")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("change-dir")
    d.add_argument("path", nargs="?")
    i = sub.add_parser("change-input")
    i.add_argument("index", nargs="?")
    p = sub.add_parser("change-prompt")
    p.add_argument("path", nargs="?")
    p.add_argument("--kind", default=None, help="only this prototype id")
    p.add_argument("--clear", action="store_true")
    sub.add_parser("show")
    args = ap.parse_args(argv)
    if args.cmd == "change-dir":
        print(cmd_change_dir(args.path))
    elif args.cmd == "change-input":
        print(cmd_change_input(args.index))
    elif args.cmd == "change-prompt":
        print(cmd_change_prompt(args.path, kind=args.kind, clear=args.clear))
    elif args.cmd == "show":
        cfg = load_config()
        print(json.dumps({**cfg, "resolved_out_dir": str(resolved_out_dir(cfg))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
