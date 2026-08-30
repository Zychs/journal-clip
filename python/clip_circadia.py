#!/usr/bin/env python3
"""Prototype Circadia card for journal-clip.

Design from disk: journal-clippers/.../design/alarm-card.html
Left card flips add ↔ edit. Right rail is the timekeeper and never flips.
File + process. No port. Hop still opens Clip-ui.

Circadia fires. Clip records.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CLIP_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from clip_alarm import (  # noqa: E402
    ACTIONS,
    AlarmError,
    add,
    alarms_path,
    edit,
    find,
    hop,
    next_due,
    read_all,
    server_running,
    set_interval,
)
from clip_look import (  # noqa: E402
    AMBER,
    BG_TOP,
    CYAN,
    FONT_RECORD,
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

# The toggle's cycle order. Asserted against clip_alarm so a new action there
# cannot become unreachable from this card without the import failing loudly.
DO_ORDER = ("hop", "cue", "none")
assert set(DO_ORDER) == ACTIONS, f"do toggle is missing {ACTIONS - set(DO_ORDER)}"

_SLUG_STRIP = re.compile(r"[^a-z0-9._-]+")
_SLUG_RUN = re.compile(r"-{2,}")


def slugify(text: str) -> str:
    """Title -> id. The user types a title; the slug is never their problem.

    Matches clip_alarm._SLUG_OK: lowercase alnum start, then alnum . - _
    """
    s = _SLUG_STRIP.sub("-", (text or "").strip().lower())
    s = _SLUG_RUN.sub("-", s).strip("-._")
    while s and not s[0].isalnum():
        s = s[1:]
    return s[:32]


def clamp_clock(hour: str, minute: str) -> tuple[int, int]:
    """Whatever is in the two boxes, read back as a real time of day."""

    def num(raw: str, hi: int) -> int:
        try:
            n = int((raw or "").strip() or 0)
        except ValueError:
            n = 0
        return max(0, min(hi, n))

    return num(hour, 23), num(minute, 59)


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
        style.configure(
            "TSpinbox",
            fieldbackground=PANEL,
            background=PANEL,
            foreground=INK,
            insertcolor=CYAN,
            arrowcolor=CYAN,
            bordercolor=LINE,
            lightcolor=LINE,
            darkcolor=LINE,
            padding=4,
        )
        style.map("TSpinbox", fieldbackground=[("focus", VOID)], foreground=[("focus", INK)])

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

    def _entry(self, parent: Any, label: str, hint: str = "") -> Any:
        """Label + field. A hint line only when one is asked for."""
        import tkinter as tk
        from tkinter import ttk

        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row, text=label, style="Mute.TLabel", width=8).pack(side=tk.LEFT)
        var = tk.StringVar()
        ent = ttk.Entry(row, textvariable=var)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if hint:
            ttk.Label(parent, text=hint, style="Mute.TLabel").pack(anchor="w", pady=(0, 8))
        return var

    def _build_add(self, parent: Any) -> None:
        """Label, field, nothing else.

        You type a title. The id follows from it, the clock cannot hold a
        bad time, and `do` is a toggle standing two fields tall beside the
        two fields it belongs with.
        """
        import tkinter as tk
        from tkinter import ttk

        # id — derived from title, shown so you can see what you got, not typed
        id_row = ttk.Frame(parent)
        id_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(id_row, text="id", style="Mute.TLabel", width=8).pack(side=tk.LEFT)
        self.add_id = tk.StringVar()
        ttk.Entry(id_row, textvariable=self.add_id, state="readonly").pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )

        # title — the one field you actually fill in
        self.add_title = self._entry(parent, "title")
        self.add_title.trace_add("write", self._on_title)

        # when — two boxes that can only hold a clock
        when_row = ttk.Frame(parent)
        when_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(when_row, text="when", style="Mute.TLabel", width=8).pack(side=tk.LEFT)
        ok = (self.root.register(self._clock_ok), "%P")
        self.when_h = tk.StringVar(value="07")
        self.when_m = tk.StringVar(value="00")
        for var, hi in ((self.when_h, 23), (self.when_m, 59)):
            box = ttk.Spinbox(
                when_row,
                from_=0,
                to=hi,
                wrap=True,
                width=4,
                justify="center",
                textvariable=var,
                validate="key",
                validatecommand=ok,
                command=self._norm_clock,
            )
            box.pack(side=tk.LEFT)
            box.bind("<FocusOut>", self._norm_clock)
            if var is self.when_h:
                ttk.Label(when_row, text=":", style="Mute.TLabel").pack(side=tk.LEFT, padx=4)

        # note + every stacked, with the do toggle two fields tall beside them
        block = ttk.Frame(parent)
        block.pack(fill=tk.X, pady=(0, 6))
        block.columnconfigure(1, weight=1)
        ttk.Label(block, text="note", style="Mute.TLabel", width=8).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )
        self.add_note = tk.StringVar()
        ttk.Entry(block, textvariable=self.add_note).grid(
            row=0, column=1, sticky="ew", pady=(0, 6)
        )
        ttk.Label(block, text="every", style="Mute.TLabel", width=8).grid(
            row=1, column=0, sticky="w"
        )
        self.add_every = tk.StringVar()
        ttk.Entry(block, textvariable=self.add_every).grid(row=1, column=1, sticky="ew")

        self._do_at = 0
        self.do_btn = tk.Button(
            block,
            text=DO_ORDER[0],
            command=self.on_do_toggle,
            bg=PANEL,
            fg=CYAN,
            activebackground=BG_TOP,
            activeforeground=CYAN,
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=CYAN,
            highlightcolor=CYAN,
            font=FONT_RECORD,
            cursor="hand2",
            width=6,
        )
        self.do_btn.grid(row=0, column=2, rowspan=2, sticky="nsew", padx=(8, 0))

        ink_button(parent, "add", self.on_add, primary=True).pack(fill=tk.X, pady=(10, 6))
        ink_button(parent, "interval last id", self.on_interval).pack(fill=tk.X)

    # ---- add-face input locks ----------------------------------------

    def _clock_ok(self, proposed: str) -> bool:
        """Two digits at most, digits only. Nothing else reaches the box."""
        return proposed == "" or (proposed.isdigit() and len(proposed) <= 2)

    def _norm_clock(self, _evt: Any = None) -> None:
        h, m = clamp_clock(self.when_h.get(), self.when_m.get())
        self.when_h.set(f"{h:02d}")
        self.when_m.set(f"{m:02d}")

    def when_text(self) -> str:
        h, m = clamp_clock(self.when_h.get(), self.when_m.get())
        return f"{h:02d}:{m:02d}"

    def _on_title(self, *_a: Any) -> None:
        base = slugify(self.add_title.get())
        self.add_id.set(self._free_id(base) if base else "")

    def _free_id(self, base: str) -> str:
        """First id in the base, base-2, base-3 … series that is not taken."""
        try:
            taken = {str(r.get("id") or "") for r in read_all()}
        except OSError:
            taken = set()
        if base not in taken:
            return base
        n = 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    def on_do_toggle(self) -> None:
        self._do_at = (self._do_at + 1) % len(DO_ORDER)
        value = DO_ORDER[self._do_at]
        tone = CYAN if value == "hop" else (INK if value == "cue" else INK_MUTE)
        self.do_btn.configure(text=value, fg=tone, highlightbackground=tone)

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

        head = ttk.Frame(inner)
        head.pack(fill=tk.X)
        ttk.Label(head, text="hop", style="Mute.TLabel").pack(side=tk.LEFT)
        ink_button(head, "hop now", self.on_hop_now).pack(side=tk.RIGHT)
        self.hop_box = log_box(inner, height=10)
        self.hop_box.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.hop_box.configure(state="disabled")

    def say(self, text: str, *, warn: bool = False) -> None:
        self._msg = text
        self.warn.configure(text=text)
        if warn:
            self.warn.configure(style="Warn.TLabel")
        else:
            self.warn.configure(style="Soft.TLabel")

    def on_add(self) -> None:
        if not (self.add_title.get() or "").strip():
            self.say("a title — the id follows from it", warn=True)
            return
        self._norm_clock()
        try:
            row = add(
                alarm_id=self.add_id.get(),
                title=self.add_title.get(),
                when=self.when_text(),
                action=DO_ORDER[self._do_at],
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
        self._fill_hop(rows)

    def _fill_hop(self, rows: list[dict[str, Any]]) -> None:
        """The box under `hop`: what a hop opens, and who is queued to do it."""
        launcher = CLIP_ROOT / "Clip-ui.bat"
        head = str(launcher) if launcher.is_file() else f"{launcher}  (missing)"
        lines = [f"opens  {head}", ""]
        hops = 0
        for r in rows:
            if r.get("state") == "archived":
                continue
            action = str(r.get("do") or "")
            armed = r.get("state") == "armed"
            if action == "hop" and armed:
                mark = ">"
                hops += 1
            else:
                mark = "-"
            lines.append(
                f"{mark} {r.get('id')}  {r.get('next_due') or '—'}  {action}  {r.get('title') or ''}"
            )
        if len(lines) == 2:
            lines.append("no alarms")
        else:
            lines.append("")
            lines.append(f"{hops} armed will hop")
        self.hop_box.configure(state="normal")
        self.hop_box.delete("1.0", "end")
        self.hop_box.insert("1.0", "\n".join(lines))
        self.hop_box.configure(state="disabled")

    def on_hop_now(self) -> None:
        rows = read_all()
        target = next_due(rows) or {}
        if hop(target):
            self.say("hop · Clip-ui opening")
        else:
            self.say("hop failed — Clip-ui.bat not found", warn=True)

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
