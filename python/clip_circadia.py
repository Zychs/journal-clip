#!/usr/bin/env python3
"""Prototype Circadia card for journal-clip.

Design from disk: journal-clippers/.../design/alarm-card.html
Left card flips add ↔ edit. Right rail is the timekeeper and never flips.
File + process. No port. Hop still opens Clip-ui.

Circadia fires. Clip records.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CLIP_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from clip_alarm import (  # noqa: E402
    AlarmError,
    add,
    alarms_path,
    edit,
    find,
    next_due,
    read_all,
    server_running,
    set_interval,
)
from clip_look import (  # noqa: E402
    AMBER,
    CYAN,
    INK,
    INK_MUTE,
    LINE,
    PANEL,
    VOID,
    apply as apply_look,
    card,
    ink_button,
    log_box,
)
from clip_ui import FLIP_MS, FLIP_STEPS, flip_swap_step, flip_width_scale  # noqa: E402

WINDOW = (980, 620)
WINDOW_MIN = (760, 520)


def server_stamp(pid: int) -> str:
    """Honest. Never ALIGNED. Never a fake clock."""
    if pid:
        return f"running · pid {pid}"
    return "stopped · design"


def next_stamp(row: dict[str, Any] | None) -> str:
    if not row:
        return "—"
    due = (row.get("next_due") or "").strip() or "—"
    ident = (row.get("id") or "").strip() or "?"
    title = (row.get("title") or "").strip()
    if title:
        return f"{ident}  {due}  {title}"
    return f"{ident}  {due}"


def last_stamp(rows: list[dict[str, Any]]) -> str:
    best = ""
    who = ""
    for r in rows:
        fired = (r.get("last_fired") or "").strip()
        if fired > best:
            best = fired
            who = (r.get("id") or "").strip()
    if not best:
        return "—"
    return f"{who}  {best}" if who else best


def store_stamp(path: Path | None = None) -> str:
    p = path or alarms_path()
    return str(p)


class CircadiaCard:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self._face_is_back = False
        self._flipping = False
        self._flip_step = 0
        self._flip_dest_back = False
        self._flip_job: str | int | None = None
        self._msg = ""

        self.root = tk.Tk()
        self.root.title("journal-clip · circadia")
        self.root.geometry("%dx%d" % WINDOW)
        self.root.minsize(*WINDOW_MIN)
        style = ttk.Style(self.root)
        apply_look(self.root, style)
        style.configure(
            "TEntry",
            fieldbackground=PANEL,
            foreground=INK,
            insertcolor=CYAN,
            bordercolor=LINE,
            lightcolor=LINE,
            darkcolor=LINE,
            padding=4,
        )
        style.map("TEntry", fieldbackground=[("focus", VOID)], foreground=[("focus", INK)])

        pad = ttk.Frame(self.root)
        pad.pack(fill=tk.BOTH, expand=True, padx=18, pady=14)

        ttk.Label(pad, text="⬡  journal-clip  /  circadia card", style="Mast.TLabel").pack(anchor="w")
        ttk.Label(pad, text="Time fires. Then you speak.", style="Soft.TLabel").pack(anchor="w", pady=(6, 4))
        ttk.Label(
            pad,
            text="left card flips add ↔ edit · Circadia rail never moves · no port",
            style="Mute.TLabel",
        ).pack(anchor="w", pady=(0, 10))

        body = ttk.Frame(pad)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.Frame(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")

        chrome = ttk.Frame(left)
        chrome.pack(fill=tk.X)
        self.mast = ttk.Label(chrome, text="front · add", style="Mast.TLabel")
        self.mast.pack(side=tk.LEFT)
        self.flip_btn = ink_button(chrome, "flip to edit", self.on_flip)
        self.flip_btn.pack(side=tk.RIGHT)

        self.card = card(left)
        self.card.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.flip_host = ttk.Frame(self.card)
        self.flip_host.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

        self.face_front = ttk.Frame(self.flip_host)
        self.face_back = ttk.Frame(self.flip_host)
        self._build_add(self.face_front)
        self._build_edit(self.face_back)
        self._apply_face(1.0)

        self._build_server(right)

        self.warn = ttk.Label(pad, text="", style="Warn.TLabel")
        self.warn.pack(anchor="w", pady=(8, 0))

        self.root.bind("<Key-f>", self._on_f)
        self.root.bind("<Key-F>", self._on_f)
        self.root.after(80, self.refresh_rail)
        self.root.after(2000, self._tick_rail)

    def _entry(self, parent: Any, label: str, hint: str) -> Any:
        import tkinter as tk
        from tkinter import ttk

        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row, text=label, style="Mute.TLabel", width=8).pack(side=tk.LEFT)
        var = tk.StringVar()
        ent = ttk.Entry(row, textvariable=var)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(parent, text=hint, style="Mute.TLabel").pack(anchor="w", pady=(0, 8))
        return var

    def _build_add(self, parent: Any) -> None:
        import tkinter as tk
        from tkinter import ttk

        ttk.Label(parent, text="Create by walking the schema", style="Soft.TLabel").pack(anchor="w")
        ttk.Label(
            parent,
            text="Interval is not part of create. Missing required fields refuse.",
            style="Mute.TLabel",
        ).pack(anchor="w", pady=(4, 10))
        self.add_id = self._entry(parent, "id", "slug handle. unique. morning")
        self.add_title = self._entry(parent, "title", "human line on the cue")
        self.add_when = self._entry(parent, "when", "07:00 · +25m · RFC3339")
        self.add_do = self._entry(parent, "do", "hop (default) · cue · none")
        self.add_do.set("hop")
        self.add_note = self._entry(parent, "note", "search haystack. optional.")
        self.add_every = self._entry(parent, "every", "skip on add. interval later. 1d · 90m")
        ink_button(parent, "add", self.on_add, primary=True).pack(fill=tk.X, pady=(4, 6))
        ink_button(parent, "interval last id", self.on_interval).pack(fill=tk.X)

    def _build_edit(self, parent: Any) -> None:
        import tkinter as tk
        from tkinter import ttk

        ttk.Label(parent, text="Find, then patch one row", style="Soft.TLabel").pack(anchor="w")
        ttk.Label(
            parent,
            text="A query must hit exactly one row. 0 or 2+ refuses.",
            style="Mute.TLabel",
        ).pack(anchor="w", pady=(4, 10))
        self.ed_query = self._entry(parent, "find", "substring on id · title · note  ·  or exact slug")
        self.ed_title = self._entry(parent, "title", "patch. blank leaves it.")
        self.ed_when = self._entry(parent, "when", "patch. blank leaves it.")
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(8, 0))
        ink_button(row, "edit", self.on_edit, primary=True).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ink_button(row, "pause", lambda: self.on_state("pause")).pack(side=tk.LEFT, padx=(6, 0))
        ink_button(row, "arm", lambda: self.on_state("arm")).pack(side=tk.LEFT, padx=(6, 0))
        ink_button(row, "archive", lambda: self.on_state("archive")).pack(side=tk.LEFT, padx=(6, 0))

    def _build_server(self, parent: Any) -> None:
        import tkinter as tk
        from tkinter import ttk

        rail = card(parent)
        rail.pack(fill=tk.BOTH, expand=True)
        inner = ttk.Frame(rail)
        inner.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
        ttk.Label(inner, text="right · circadia", style="Mast.TLabel").pack(anchor="w")
        ttk.Label(inner, text="No flip", style="Soft.TLabel").pack(anchor="w", pady=(6, 8))
        self.stamp = ttk.Label(inner, text="stopped · design", style="Warn.TLabel")
        self.stamp.pack(anchor="w", pady=(0, 8))
        self.row_running = ttk.Label(inner, text="running    —", style="Mute.TLabel")
        self.row_running.pack(anchor="w")
        self.row_next = ttk.Label(inner, text="next       —", style="Mute.TLabel")
        self.row_next.pack(anchor="w")
        self.row_last = ttk.Label(inner, text="last       —", style="Mute.TLabel")
        self.row_last.pack(anchor="w")
        ttk.Label(inner, text="port       none. file + process.", style="Mute.TLabel").pack(anchor="w")
        self.row_store = ttk.Label(inner, text="store      —", style="Mute.TLabel", wraplength=280)
        self.row_store.pack(anchor="w", pady=(0, 8))
        ttk.Label(
            inner,
            text="Local timekeeper. Sleeps until next armed when. Hop opens Clip-ui. Not :3000.",
            style="Soft.TLabel",
            wraplength=280,
        ).pack(anchor="w", pady=(0, 8))
        ink_button(inner, "start timekeeper", self.on_server).pack(fill=tk.X, pady=(0, 8))
        ttk.Label(inner, text="tape", style="Mute.TLabel").pack(anchor="w")
        self.tape = log_box(inner, height=10)
        self.tape.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.tape.configure(state="disabled")

    def say(self, text: str, *, warn: bool = False) -> None:
        self._msg = text
        self.warn.configure(text=text)
        if warn:
            self.warn.configure(style="Warn.TLabel")
        else:
            self.warn.configure(style="Soft.TLabel")

    def on_add(self) -> None:
        try:
            row = add(
                alarm_id=self.add_id.get(),
                title=self.add_title.get(),
                when=self.add_when.get(),
                action=(self.add_do.get() or "hop").strip() or "hop",
                note=self.add_note.get(),
            )
        except AlarmError as e:
            self.say(str(e), warn=True)
            return
        every = (self.add_every.get() or "").strip()
        if every:
            try:
                row = set_interval(row["id"], every)
            except AlarmError as e:
                self.say(f"added {row['id']} · interval refused: {e}", warn=True)
                self.refresh_rail()
                return
        self.say(f"added {row['id']}")
        self.refresh_rail()

    def on_interval(self) -> None:
        ident = (self.add_id.get() or "").strip()
        every = (self.add_every.get() or "").strip()
        if not ident or not every:
            self.say("interval needs id + every", warn=True)
            return
        try:
            row = set_interval(ident, every)
        except AlarmError as e:
            self.say(str(e), warn=True)
            return
        self.say(f"interval {row['id']} every {every}")
        self.refresh_rail()

    def on_edit(self) -> None:
        q = (self.ed_query.get() or "").strip()
        if not q:
            self.say("find needs a query", warn=True)
            return
        kw: dict[str, Any] = {}
        title = (self.ed_title.get() or "").strip()
        when = (self.ed_when.get() or "").strip()
        if title:
            kw["title"] = title
        if when:
            kw["when"] = when
        if not kw:
            hits = find(q)
            if len(hits) == 1:
                self.say(f"found {hits[0]['id']} — name a field to patch")
            elif not hits:
                self.say("no row", warn=True)
            else:
                self.say(f"{len(hits)} rows — narrow the query", warn=True)
            return
        try:
            row = edit(q, **kw)
        except AlarmError as e:
            self.say(str(e), warn=True)
            return
        self.say(f"edited {row['id']}")
        self.refresh_rail()

    def on_state(self, kind: str) -> None:
        q = (self.ed_query.get() or "").strip()
        if not q:
            self.say("find needs a query", warn=True)
            return
        states = {"pause": "paused", "arm": "armed", "archive": "archived"}
        try:
            row = edit(q, state=states[kind])
        except AlarmError as e:
            self.say(str(e), warn=True)
            return
        self.say(f"{kind} {row['id']}")
        self.refresh_rail()

    def on_server(self) -> None:
        if server_running():
            self.say("timekeeper already running")
            self.refresh_rail()
            return
        py = sys.executable
        script = HERE / "clip_alarm.py"
        flags = 0
        if os.name == "nt":
            flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        try:
            subprocess.Popen(
                [py, str(script), "server"],
                cwd=str(CLIP_ROOT),
                creationflags=flags,
            )
        except OSError as e:
            self.say(f"server spawn failed: {e}", warn=True)
            return
        self.say("timekeeper spawn · file + process")
        self.root.after(400, self.refresh_rail)

    def refresh_rail(self) -> None:
        pid = server_running()
        rows = read_all()
        nxt = next_due(rows)
        self.stamp.configure(text=server_stamp(pid))
        self.row_running.configure(text=f"running    {pid or 'no'}")
        self.row_next.configure(text=f"next       {next_stamp(nxt)}")
        self.row_last.configure(text=f"last       {last_stamp(rows)}")
        self.row_store.configure(text=f"store      {store_stamp()}")
        lines = []
        for r in rows:
            if r.get("state") == "archived":
                continue
            mark = "*" if r.get("state") == "armed" else "-"
            lines.append(f"{mark} {r.get('id')}  {r.get('next_due') or '—'}  {r.get('do')}  {r.get('title') or ''}")
        body = "\n".join(lines) if lines else "no alarms"
        self.tape.configure(state="normal")
        self.tape.delete("1.0", "end")
        self.tape.insert("1.0", body)
        self.tape.configure(state="disabled")

    def _tick_rail(self) -> None:
        self.refresh_rail()
        self.root.after(2000, self._tick_rail)

    def _on_f(self, evt: Any) -> None:
        w = evt.widget
        cls = w.winfo_class() if hasattr(w, "winfo_class") else ""
        if cls in ("TEntry", "Entry", "Text"):
            return
        self.on_flip()

    def on_flip(self) -> None:
        if self._flipping:
            return
        self._flipping = True
        self._flip_step = 0
        self._flip_dest_back = not self._face_is_back
        self._tick_flip()

    def _tick_flip(self) -> None:
        step = self._flip_step
        steps = FLIP_STEPS
        if step == flip_swap_step(steps):
            self._face_is_back = self._flip_dest_back
        self._apply_face(flip_width_scale(step, steps))
        if step >= steps:
            self._flipping = False
            self._apply_face(1.0)
            return
        self._flip_step = step + 1
        self._flip_job = self.root.after(FLIP_MS, self._tick_flip)

    def _apply_face(self, scale: float) -> None:
        show = self.face_back if self._face_is_back else self.face_front
        hide = self.face_front if self._face_is_back else self.face_back
        hide.place_forget()
        show.place(relx=0.5, rely=0, relwidth=max(0.02, float(scale)), relheight=1.0, anchor="n")
        if self._face_is_back:
            self.mast.configure(text="back · edit")
            self.flip_btn.configure(text="flip to add")
        else:
            self.mast.configure(text="front · add")
            self.flip_btn.configure(text="flip to edit")

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    CircadiaCard().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
