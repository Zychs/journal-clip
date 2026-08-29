#!/usr/bin/env python3
"""Thin Clip UI. Session dir + USB mic + waveform. Whisper plates in-window.

Capture lives here so a waveform can draw. Whisper runs in-process
and plates the transcript here (no cmd popup). Session dir/device go in a temp
SESEFUS_CLIP_CONFIG; the lasting clip-config dir is not overwritten.
"""
from __future__ import annotations

import array
import json
import os
import queue
import re
import struct
import sys
import tempfile
import threading
import time
import wave
from collections import deque
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
CLIP_ROOT = HERE.parent
CLIP_BAT = CLIP_ROOT / "Clip.bat"

DEVICE_LINE = re.compile(r"^\[(\d+)\]\s+(.*?)(?:\s+\(current\))?\s*$")
RATE = 16000
CHUNK_SAMPLES = 1600  # 100 ms
NBUFS = 6
SILENCE_PEAK = 500  # int16 abs; below this = no input
DEFAULT_SECONDS = 30
SECONDS_PER_CLICK = 30
MAX_RECORD_CLICKS = 4
MAX_SECONDS = SECONDS_PER_CLICK * MAX_RECORD_CLICKS
CLICK_WAIT_MS = 450

sys.path.insert(0, str(HERE))
from clip_config import list_input_devices, load_config  # noqa: E402
from clip_look import (  # noqa: E402
    BG_TOP,
    CYAN,
    CYAN_DEEP,
    FONT_MONO,
    FONT_PLATE,
    INK,
    INK_MUTE,
    LINE,
    VOID,
    apply as apply_look,
    dot_button,
    ink_button,
    log_box,
    plate,
)
from clip_group import PROFILES, group_rows  # noqa: E402
from clip_store import list_takes  # noqa: E402


def parse_device_list(text: str) -> tuple[list[tuple[int, str]], int]:
    devices: list[tuple[int, str]] = []
    current = 0
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("current_index="):
            try:
                current = int(line.split("=", 1)[1].strip())
            except ValueError:
                current = 0
            continue
        m = DEVICE_LINE.match(line)
        if m:
            devices.append((int(m.group(1)), m.group(2).strip()))
    if not devices:
        devices = [(0, "default")]
    return devices, current


def pick_default_device(devices: list[tuple[int, str]], current: int = 0) -> int:
    """Maono USB first, then any Maono, then a USB mic (not Stereo Mix)."""
    if not devices:
        return 0
    ranked: list[tuple[int, int]] = []
    for i, name in devices:
        n = name.lower()
        mix = "mix" in n or "stereo" in n or "loopback" in n
        score = 0
        if "maono" in n and "usb" in n:
            score = 4
        elif "maono" in n:
            score = 3
        elif "usb" in n and not mix:
            score = 2
        elif "usb" in n:
            score = 1
        ranked.append((score, i))
    ranked.sort(key=lambda t: t[0], reverse=True)
    if ranked[0][0] > 0:
        return ranked[0][1]
    ids = {i for i, _ in devices}
    if current in ids:
        return current
    return devices[0][0]


def device_is_usb_mic(name: str) -> bool:
    n = name.lower()
    if "mix" in n or "stereo" in n:
        return False
    return "maono" in n or "usb" in n


def parse_seconds(text: str, default: int = DEFAULT_SECONDS) -> int:
    raw = (text or "").strip()
    if not raw:
        return default
    try:
        n = int(float(raw))
    except ValueError:
        return default
    if n < 1:
        return default
    return min(n, MAX_SECONDS)


def record_clicks_to_seconds(clicks: int) -> int:
    n = max(1, min(int(clicks), MAX_RECORD_CLICKS))
    return n * SECONDS_PER_CLICK


def remaining_whole_seconds(started_at: float, duration: float, now: float) -> int:
    """Whole seconds left. Floor, never a decimal."""
    return max(0, int(duration - (now - started_at)))


def peak_gain(pcm: bytes) -> float:
    """Peak after DC removal so a negative bias is not drawn as gain."""
    n = len(pcm) // 2
    if n <= 0:
        return 0.0
    arr = array.array("h")
    arr.frombytes(pcm[: n * 2])
    mean = sum(arr) / n
    pk = max((abs(x - mean) for x in arr), default=0.0)
    return min(1.0, pk / 32767.0)


def rows_that_fit(pixel_height: int, line_height: int, pad: int = 4) -> int:
    """How many ledger lines fit. Font does not change."""
    if line_height < 1:
        return 0
    return max(0, (int(pixel_height) - int(pad)) // int(line_height))


def visible_ledger_rows(rows: list[dict[str, str]], fit: int) -> list[dict[str, str]]:
    """Newest rows that fit. Older ones drop off the short ledger."""
    if fit <= 0:
        return []
    if len(rows) <= fit:
        return list(rows)
    return rows[-fit:]


def short_ledger_line(row: dict[str, str], max_chars: int = 48) -> str:
    """One spoken line. Clock then words. No kind/score/extra."""
    clock = (row.get("time") or "")[:5]
    preview = " ".join((row.get("text") or "").split())
    head = f"{clock}  " if clock else ""
    room = max(1, int(max_chars) - len(head))
    if len(preview) > room:
        preview = preview[: max(0, room - 1)] + "…"
    return (head + preview).rstrip()


def load_intent_cues() -> str:
    env = os.environ.get("SESEFUS_INTENT") or os.environ.get("SESEFUS_INTENT_PACKET")
    paths: list[Path] = []
    if env:
        paths.append(Path(env))
    paths.append(Path.cwd() / "intent" / "interview.md")
    chunks: list[str] = []
    for p in paths:
        if p.is_file():
            try:
                chunks.append(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            break
    return "\n".join(chunks)


def ui_state_path() -> Path:
    env = os.environ.get("SESEFUS_CLIP_UI_STATE")
    if env:
        return Path(env)
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return home / ".sesefus" / "clip-ui.json"


def load_recent_dir(state: Path | None = None) -> Path | None:
    p = state or ui_state_path()
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = str(data.get("last_dir") or "").strip()
    if not raw:
        return None
    dest = Path(os.path.expandvars(raw)).expanduser()
    if dest.is_dir():
        return dest.resolve()
    return None


def save_recent_dir(folder: Path, state: Path | None = None) -> Path:
    p = state or ui_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body: dict[str, Any] = {}
    if p.is_file():
        try:
            prev = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(prev, dict):
                body = prev
        except (OSError, json.JSONDecodeError):
            body = {}
    body["last_dir"] = str(Path(folder).resolve())
    p.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return p


def is_silent(pcm: bytes, peak_min: int = SILENCE_PEAK) -> bool:
    if len(pcm) < 4:
        return True
    n = len(pcm) // 2
    if n <= 0:
        return True
    samples = struct.unpack("<" + "h" * n, pcm[: n * 2])
    return max(abs(s) for s in samples) < peak_min


def write_pcm16_wav(path: Path, pcm: bytes, rate: int = RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def shred_temp(path: Path) -> None:
    try:
        n = path.stat().st_size
        with open(path, "r+b") as f:
            f.write(b"\x00" * max(n, 0))
        path.unlink()
    except OSError:
        pass


def write_session_config(
    path: Path,
    *,
    out_dir: str,
    input_index: int,
    base: dict[str, Any] | None = None,
) -> Path:
    src = base if base is not None else {}
    body = {
        "out_dir": str(out_dir),
        "input_index": int(input_index),
        "prompt_file": str(src.get("prompt_file") or ""),
        "prompt_overrides": dict(src.get("prompt_overrides") or {}),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return path


def list_devices_cli() -> tuple[list[tuple[int, str]], int]:
    devices = list_input_devices()
    current = int(load_config().get("input_index") or 0)
    return devices, current


def prompt_session_dir() -> Path | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    recent = load_recent_dir()
    start = str(recent) if recent is not None else (load_config().get("out_dir") or str(Path.home() / "test-write"))
    start_p = Path(str(start))
    if not start_p.is_dir():
        start_p = Path.home()
    chosen = filedialog.askdirectory(
        parent=root,
        title="Clip — folder for this session (takes.jsonl lives here)",
        initialdir=str(start_p),
        mustexist=True,
    )
    root.destroy()
    if not chosen:
        return None
    dest = Path(chosen)
    dest.mkdir(parents=True, exist_ok=True)
    return dest


class WinmmCapture:
    """Chunked WinMM capture. One device. Same 16 kHz mono as journal-clip.exe."""

    def __init__(
        self,
        device_index: int,
        seconds: float,
        on_peak: Callable[[float], None] | None = None,
    ) -> None:
        self.device_index = device_index
        self.seconds = seconds
        self.on_peak = on_peak
        self._stop = threading.Event()
        self.pcm = bytearray()
        self.error: str | None = None

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> bytes:
        if sys.platform != "win32":
            self.error = "WinMM is Windows only"
            return b""
        import ctypes
        from ctypes import wintypes

        class WAVEFORMATEX(ctypes.Structure):
            _fields_ = [
                ("wFormatTag", wintypes.WORD),
                ("nChannels", wintypes.WORD),
                ("nSamplesPerSec", wintypes.DWORD),
                ("nAvgBytesPerSec", wintypes.DWORD),
                ("nBlockAlign", wintypes.WORD),
                ("wBitsPerSample", wintypes.WORD),
                ("cbSize", wintypes.WORD),
            ]

        class WAVEHDR(ctypes.Structure):
            _fields_ = [
                ("lpData", ctypes.c_void_p),
                ("dwBufferLength", wintypes.DWORD),
                ("dwBytesRecorded", wintypes.DWORD),
                ("dwUser", ctypes.c_void_p),
                ("dwFlags", wintypes.DWORD),
                ("dwLoops", wintypes.DWORD),
                ("lpNext", ctypes.c_void_p),
                ("reserved", ctypes.c_void_p),
            ]

        WHDR_DONE = 0x00000001
        chunk_bytes = CHUNK_SAMPLES * 2
        winmm = ctypes.windll.winmm
        wfx = WAVEFORMATEX(
            1, 1, RATE, RATE * 2, 2, 16, 0
        )
        hwi = ctypes.c_void_p()
        rc = winmm.waveInOpen(
            ctypes.byref(hwi),
            ctypes.c_uint(self.device_index),
            ctypes.byref(wfx),
            0,
            0,
            0,
        )
        if rc != 0:
            self.error = f"waveInOpen device {self.device_index} failed ({rc})"
            return b""

        bufs = [ctypes.create_string_buffer(chunk_bytes) for _ in range(NBUFS)]
        hdrs = (WAVEHDR * NBUFS)()
        for i, buf in enumerate(bufs):
            hdrs[i].lpData = ctypes.cast(buf, ctypes.c_void_p).value
            hdrs[i].dwBufferLength = chunk_bytes
            hdrs[i].dwBytesRecorded = 0
            hdrs[i].dwFlags = 0
            hdrs[i].dwLoops = 0
            if winmm.waveInPrepareHeader(hwi, ctypes.byref(hdrs[i]), ctypes.sizeof(WAVEHDR)) != 0:
                self.error = "waveInPrepareHeader failed"
                winmm.waveInClose(hwi)
                return b""
            winmm.waveInAddBuffer(hwi, ctypes.byref(hdrs[i]), ctypes.sizeof(WAVEHDR))

        if winmm.waveInStart(hwi) != 0:
            self.error = "waveInStart failed"
            winmm.waveInReset(hwi)
            winmm.waveInClose(hwi)
            return b""

        deadline = time.monotonic() + max(0.4, float(self.seconds))
        try:
            while not self._stop.is_set() and time.monotonic() < deadline:
                for i, buf in enumerate(bufs):
                    if hdrs[i].dwFlags & WHDR_DONE:
                        n = int(hdrs[i].dwBytesRecorded)
                        if n > 0:
                            chunk = buf.raw[:n]
                            self.pcm.extend(chunk)
                            if self.on_peak:
                                self.on_peak(peak_gain(chunk))
                        hdrs[i].dwBytesRecorded = 0
                        hdrs[i].dwFlags = hdrs[i].dwFlags & ~WHDR_DONE
                        winmm.waveInAddBuffer(hwi, ctypes.byref(hdrs[i]), ctypes.sizeof(WAVEHDR))
                time.sleep(0.01)
        finally:
            winmm.waveInStop(hwi)
            winmm.waveInReset(hwi)
            for i in range(NBUFS):
                winmm.waveInUnprepareHeader(hwi, ctypes.byref(hdrs[i]), ctypes.sizeof(WAVEHDR))
            winmm.waveInClose(hwi)
        return bytes(self.pcm)


class ClipUi:
    def __init__(self, out_dir: Path) -> None:
        import tkinter as tk
        from tkinter import font as tkfont
        from tkinter import ttk

        self.tk = tk
        self.out_dir = out_dir.resolve()
        self.session_cfg = Path(tempfile.gettempdir()) / f"sesefus-clip-ui-{os.getpid()}.json"
        self.log_q: queue.Queue[str] = queue.Queue()
        self.busy = False
        self.capturing = False
        self.capture: WinmmCapture | None = None
        self.devices: list[tuple[int, str]] = [(0, "default")]
        self.peaks: deque[float] = deque([0.0] * 120, maxlen=120)
        self.peak_lock = threading.Lock()
        self._record_clicks = 0
        self._record_click_job: str | int | None = None
        self._record_started_at: float | None = None
        self._record_limit = 0
        self._ledger_rows: list[dict[str, str]] = []
        self._ledger_shown: list[dict[str, str]] = []
        self._ledger_shown_by_iid: dict[str, dict[str, str]] = {}
        self._ledger_fit_n = -1
        self._ledger_chars = 0
        self._profile = ".d"
        self._profile_btns: dict[str, Any] = {}
        self._intent_cues = load_intent_cues()
        save_recent_dir(self.out_dir)

        self.root = tk.Tk()
        self.root.title("journal-clip")
        self.root.geometry("820x640")
        self.root.minsize(700, 480)
        style = ttk.Style(self.root)
        apply_look(self.root, style)

        pad = ttk.Frame(self.root)
        pad.pack(fill=tk.BOTH, expand=True, padx=22, pady=18)

        body = ttk.Frame(pad)
        body.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(body)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(body, width=300)
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(14, 0))
        right.pack_propagate(False)

        ttk.Label(left, text="⬡  journal-clip  /  this tower", style="Mast.TLabel").pack(anchor="w")
        ttk.Label(left, text="speak · plate · shred", style="Soft.TLabel").pack(anchor="w", pady=(6, 10))

        dirrow = ttk.Frame(left)
        dirrow.pack(fill=tk.X, pady=(0, 8))
        self.dir_label = ttk.Label(dirrow, text=str(self.out_dir), style="Mute.TLabel", wraplength=400)
        self.dir_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ink_button(dirrow, "change", self.change_folder).pack(side=tk.RIGHT)

        ttk.Label(left, text="input", style="Mute.TLabel").pack(anchor="w")
        self.device_var = tk.StringVar()
        self.combo = ttk.Combobox(
            left, textvariable=self.device_var, state="readonly", width=62
        )
        self.combo.pack(fill=tk.X, pady=(0, 4))
        self.warn = ttk.Label(left, text="", style="Warn.TLabel")
        self.warn.pack(anchor="w", pady=(0, 8))

        ttk.Label(
            left,
            text="record clicks  1=30s  2=60s  3=90s  4=120s   ·  stop sends early",
            style="Mute.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        self.wave = tk.Canvas(
            left,
            height=72,
            bg=VOID,
            highlightthickness=1,
            highlightbackground=LINE,
        )
        self.wave.pack(fill=tk.X, pady=(0, 8))

        self.record_btn = ink_button(
            left, "record   1–4 clicks", self.on_record_click, primary=True
        )
        self.record_btn.pack(fill=tk.X, pady=(0, 8))

        self.status = ttk.Label(left, text="ready", style="Soft.TLabel")
        self.status.pack(anchor="w", pady=(0, 6))

        ttk.Label(left, text="this take", style="Mute.TLabel").pack(anchor="w")
        self.plate = plate(left, height=5)
        self.plate.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.plate.insert("1.0", "take lands here.")
        self.plate.configure(state="disabled")

        ttk.Label(left, text="log", style="Mute.TLabel").pack(anchor="w")
        self.log = log_box(left, height=3)
        self.log.pack(fill=tk.X)
        self.log.configure(state="disabled")

        head = ttk.Frame(right)
        head.pack(fill=tk.X)
        self.count_label = ttk.Label(head, text="0", style="Mast.TLabel")
        self.count_label.pack(side=tk.LEFT)
        dots = ttk.Frame(head)
        dots.pack(side=tk.RIGHT)
        for abbr, _pid in PROFILES:
            btn = dot_button(dots, abbr, lambda a=abbr: self.set_profile(a), active=(abbr == self._profile))
            btn.pack(side=tk.LEFT, padx=(4, 0))
            self._profile_btns[abbr] = btn

        self._ledger_font = tkfont.Font(font=FONT_PLATE)
        self._ledger_line_h = int(self._ledger_font.metrics("linespace") or 16)
        treeframe = ttk.Frame(right)
        treeframe.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.tree = ttk.Treeview(
            treeframe,
            show="tree",
            selectmode="browse",
            style="Tape.Treeview",
        )
        scroll = ttk.Scrollbar(treeframe, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.ledger = self.tree
        self.tree.bind("<<TreeviewSelect>>", self.on_ledger_select)
        self.tree.bind("<Configure>", self._on_ledger_configure)
        self.tree.tag_configure("group", foreground=CYAN)
        self.tree.tag_configure("take", foreground=INK)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.reload_devices()
        self.reload_ledger()
        self.root.after(50, self._pump)

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        if not text.endswith("\n"):
            self.log.insert("end", "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _pump(self) -> None:
        try:
            while True:
                self.append_log(self.log_q.get_nowait())
        except queue.Empty:
            pass
        self._draw_wave()
        self.root.after(50, self._pump)

    def _draw_wave(self) -> None:
        c = self.wave
        w = int(c.winfo_width() or 500)
        h = int(c.winfo_height() or 72)
        c.delete("all")
        mid = h / 2.0
        amp = h * 0.46
        c.create_line(0, mid, w, mid, fill=LINE)
        with self.peak_lock:
            peaks = list(self.peaks)
        n = len(peaks)
        if n >= 2:
            top: list[float] = []
            bot: list[float] = []
            for i, p in enumerate(peaks):
                x = i * (w - 1) / (n - 1)
                dy = max(0.0, min(1.0, p)) * amp
                top.extend((x, mid - dy))
                bot.extend((x, mid + dy))
            color = CYAN if self.capturing else INK_MUTE
            fill = CYAN_DEEP if self.capturing else LINE
            bot_rev: list[float] = []
            for i in range(n - 1, -1, -1):
                x = i * (w - 1) / (n - 1)
                dy = max(0.0, min(1.0, peaks[i])) * amp
                bot_rev.extend((x, mid + dy))
            c.create_polygon(*top, *bot_rev, fill=fill, outline="")
            c.create_line(*top, fill=color, smooth=True)
            c.create_line(*bot, fill=color, smooth=True)
        label = self._timer_label()
        if label:
            c.create_text(
                w - 8,
                6,
                text=label,
                anchor="ne",
                fill=CYAN if self.capturing else INK_MUTE,
                font=FONT_MONO,
            )

    def _timer_label(self) -> str:
        if self.capturing and self._record_started_at is not None:
            return str(
                remaining_whole_seconds(
                    self._record_started_at, self._record_limit, time.monotonic()
                )
            )
        if self._record_clicks > 0:
            return str(record_clicks_to_seconds(self._record_clicks))
        return ""

    def _ledger_char_count(self) -> int:
        w = int(self.tree.winfo_width() or 240)
        cw = max(1, self._ledger_font.measure("0"))
        return max(16, (w - 28) // cw)

    def _on_ledger_configure(self, _evt: object | None = None) -> None:
        chars = self._ledger_char_count()
        if chars == self._ledger_chars:
            return
        self._ledger_chars = chars
        self._paint_ledger(keep_id=self._ledger_selected_id())

    def _ledger_selected_id(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            return None
        iid = str(sel[0])
        if iid.startswith("t-"):
            return iid[2:] or None
        return None

    def set_profile(self, abbr: str) -> None:
        if abbr == self._profile:
            return
        self._profile = abbr
        for name, btn in self._profile_btns.items():
            on = name == abbr
            btn.configure(fg=CYAN if on else INK_MUTE, highlightbackground=CYAN if on else LINE)
        self._paint_ledger(keep_id=self._ledger_selected_id())

    def reload_ledger(self) -> None:
        try:
            self._ledger_rows = list_takes(self.out_dir)
        except Exception:
            self._ledger_rows = []
        self._paint_ledger()

    def _paint_ledger(self, keep_id: str | None = None) -> None:
        chars = self._ledger_char_count()
        rows = list(self._ledger_rows)
        self.count_label.configure(text=str(len(rows)))
        groups = group_rows(rows, self._profile, intent_cues=self._intent_cues)
        self._ledger_shown = []
        self._ledger_shown_by_iid = {}
        for item in self.tree.get_children(""):
            self.tree.delete(item)
        n = len(rows)
        for gi, g in enumerate(groups):
            gid = f"g-{gi}"
            opened = n < 24 or gi == len(groups) - 1
            self.tree.insert(
                "",
                "end",
                iid=gid,
                text=f"{g['label']}  {g['n']}",
                open=opened,
                tags=("group",),
            )
            for row in g["rows"]:
                tid = f"t-{row.get('id') or gi}"
                if tid in self._ledger_shown_by_iid:
                    tid = f"{tid}-{len(self._ledger_shown)}"
                line = short_ledger_line(row, chars)
                self.tree.insert(gid, "end", iid=tid, text=line, tags=("take",))
                self._ledger_shown.append(row)
                self._ledger_shown_by_iid[tid] = row
        if not rows:
            return
        pick = None
        if keep_id:
            want = f"t-{keep_id}"
            if self.tree.exists(want):
                pick = want
        if pick is None:
            last = rows[-1]
            want = f"t-{last.get('id')}"
            if self.tree.exists(want):
                pick = want
        if pick:
            self.tree.selection_set(pick)
            self.tree.see(pick)

    def on_ledger_select(self, _evt: object | None = None) -> None:
        if self.capturing or self.busy:
            return
        sel = self.tree.selection()
        if not sel:
            return
        iid = str(sel[0])
        row = self._ledger_shown_by_iid.get(iid)
        if not row:
            return
        text = (row.get("text") or "").strip()
        if text:
            self.set_plate(text)

    def selected_index(self) -> int:
        raw = self.device_var.get()
        m = re.match(r"^\[(\d+)\]", raw)
        if m:
            return int(m.group(1))
        return self.devices[0][0] if self.devices else 0

    def selected_name(self) -> str:
        raw = self.device_var.get()
        m = re.match(r"^\[\d+\]\s+(.*)$", raw)
        return m.group(1).strip() if m else ""

    def set_warn(self, text: str) -> None:
        self.warn.configure(text=text)

    def set_plate(self, text: str) -> None:
        self.plate.configure(state="normal")
        self.plate.delete("1.0", "end")
        self.plate.insert("1.0", text)
        self.plate.configure(state="disabled")

    def reload_devices(self) -> None:
        try:
            self.devices, current = list_devices_cli()
        except Exception as e:
            self.devices, current = [(0, "default")], 0
            self.append_log(f"device list failed: {e}")
        labels = [f"[{i}] {name}" for i, name in self.devices]
        self.combo["values"] = labels
        pick_i = pick_default_device(self.devices, current)
        pick = next((lab for lab in labels if lab.startswith(f"[{pick_i}]")), None)
        self.device_var.set(pick or (labels[0] if labels else "[0] default"))
        name = self.selected_name()
        if not self.devices or (len(self.devices) == 1 and self.devices[0][1] == "default"):
            self.set_warn("no capture device — plug in the USB mic")
        elif not device_is_usb_mic(name):
            self.set_warn("USB / Maono mic not found — pick it in the list if it is plugged in")
        else:
            self.set_warn("")

    def change_folder(self) -> None:
        if self.busy:
            return
        chosen = prompt_session_dir()
        if chosen is None:
            return
        self.out_dir = chosen.resolve()
        save_recent_dir(self.out_dir)
        self.dir_label.configure(text=str(self.out_dir))
        self.append_log(f"— folder {self.out_dir}")
        self.reload_ledger()

    def on_record_click(self) -> None:
        if self.capturing and self.capture is not None:
            self.capture.stop()
            return
        if self.busy and self._record_click_job is None:
            return
        self._record_clicks = min(self._record_clicks + 1, MAX_RECORD_CLICKS)
        seconds = record_clicks_to_seconds(self._record_clicks)
        self.status.configure(text=f"{seconds}s — click again up to {MAX_SECONDS}s")
        if self._record_click_job is not None:
            try:
                self.root.after_cancel(self._record_click_job)
            except Exception:
                pass
        self._record_click_job = self.root.after(CLICK_WAIT_MS, self._commit_record_clicks)

    def _commit_record_clicks(self) -> None:
        clicks = self._record_clicks
        self._record_clicks = 0
        self._record_click_job = None
        self.start_record(record_clicks_to_seconds(clicks))

    def start_record(self, seconds: int) -> None:
        if self.busy or self.capturing:
            return
        idx = self.selected_index()
        write_session_config(
            self.session_cfg,
            out_dir=str(self.out_dir),
            input_index=idx,
            base=load_config(),
        )
        self.busy = True
        self.capturing = True
        self._record_started_at = time.monotonic()
        self._record_limit = seconds
        self.record_btn.configure(text="stop / send")
        self.status.configure(text=f"recording — speak  (max {seconds}s)")
        self.set_warn("")
        self.set_plate("listening…")
        self.append_log(f"— capture  dir={self.out_dir}  input={idx}  seconds={seconds}")
        with self.peak_lock:
            self.peaks.clear()
            self.peaks.extend([0.0] * 120)
        cap = WinmmCapture(idx, seconds, on_peak=self._on_peak)
        self.capture = cap
        threading.Thread(target=self._capture_then_clip, args=(cap,), daemon=True).start()

    def _on_peak(self, peak: float) -> None:
        with self.peak_lock:
            self.peaks.append(max(0.0, min(1.0, peak)))

    def _capture_then_clip(self, cap: WinmmCapture) -> None:
        pcm = cap.run()
        self.capturing = False
        self.capture = None
        if cap.error:
            self.log_q.put(f"— capture failed: {cap.error}")
            self.root.after(0, lambda: self.set_plate("no input — capture failed."))
            self.root.after(0, lambda: self._idle("no input — capture failed"))
            self.root.after(0, lambda: self.set_warn("no input detected (device failed to open)"))
            return
        if is_silent(pcm):
            self.log_q.put("— no input detected (mic silent or wrong device)")
            self.root.after(0, lambda: self._warn_silent())
            return
        wav = Path(tempfile.gettempdir()) / f"sesefus-clip-ui-{os.getpid()}-{int(time.time())}.wav"
        write_pcm16_wav(wav, pcm)
        dur = len(pcm) / (RATE * 2)
        self.log_q.put(f"— captured {dur:.1f}s  → whisper in-window")
        self.root.after(0, lambda: self.status.configure(text="transcribing…"))
        self.root.after(0, lambda: self.set_plate("transcribing…"))
        self.root.after(0, lambda: self.record_btn.configure(text="working…", state="disabled"))
        self._run_heavy(wav)

    def _warn_silent(self) -> None:
        self.set_warn("no input detected — USB mic muted, unplugged, or wrong device")
        self.set_plate("no input detected.")
        self._idle("no input detected")

    def _run_heavy(self, wav: Path) -> None:
        import contextlib
        import io
        import warnings

        os.environ["SESEFUS_CLIP_CONFIG"] = str(self.session_cfg)
        buf = io.StringIO()
        result: dict[str, Any] | None = None
        err: str | None = None
        try:
            with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    from clip_heavy import run as heavy_run

                    result = heavy_run(
                        wav=wav,
                        text=None,
                        proto_path=HERE / "prototypes.json",
                    )
        except Exception as e:
            err = str(e)
        finally:
            shred_temp(wav)
        noise = buf.getvalue().strip()
        if noise:
            for line in noise.splitlines():
                if "FP16" in line or "UserWarning" in line:
                    continue
                if line.startswith("{") or line.startswith("  "):
                    continue
                self.log_q.put(line)
        if err:
            self.log_q.put(f"— transcription failed: {err}")
            self.root.after(0, lambda: self.set_plate(f"transcription failed.\n{err}"))
            self.root.after(0, lambda: self._idle("transcription failed"))
            return
        if not result or not result.get("ok"):
            msg = str((result or {}).get("error") or "heavy failed")
            self.log_q.put(f"— {msg}")
            self.root.after(0, lambda: self.set_plate(msg))
            self.root.after(0, lambda: self._idle("transcription failed"))
            return
        text = str(result.get("transcript") or "").strip()
        take_id = str(result.get("id") or "")
        kind = str(result.get("kind") or "dump")
        degraded = result.get("degraded") or []
        self.log_q.put(f"— wrote id {take_id}  kind {kind}")
        self.root.after(0, lambda: self._show_take(text, take_id, kind, list(degraded)))

    def _show_take(self, text: str, take_id: str, kind: str, degraded: list[str]) -> None:
        self.set_plate(text or "(empty)")
        if degraded:
            self.set_warn(f"kind {kind} · id {take_id} · local mouth down — text still saved")
        else:
            self.set_warn("")
        self.reload_ledger()
        self._idle("ready")

    def _idle(self, status: str) -> None:
        self.busy = False
        self.capturing = False
        self._record_started_at = None
        self._record_limit = 0
        try:
            if not self.root.winfo_exists():
                return
        except Exception:
            return
        self.record_btn.configure(state="normal", text="record   1–4 clicks")
        self.status.configure(text=status)

    def on_close(self) -> None:
        if self._record_click_job is not None:
            try:
                self.root.after_cancel(self._record_click_job)
            except Exception:
                pass
        if self.capture is not None:
            self.capture.stop()
        if not self.busy:
            try:
                if self.session_cfg.is_file():
                    self.session_cfg.unlink()
            except OSError:
                pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    out = load_recent_dir()
    if out is None:
        out = prompt_session_dir()
    if out is None:
        return 0
    save_recent_dir(out)
    ClipUi(out).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
