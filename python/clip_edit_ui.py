#!/usr/bin/env python3
"""Transcription editor. Separate window from Clip-ui. No mic. No Whisper.

Load a journal folder's CSVs, pick a take, fix the text, save. Kind and
Whisper are not rerun from here.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from clip_look import apply as apply_look, ink_button, plate  # noqa: E402
from clip_store import list_takes, tape_path, update_text  # noqa: E402
from clip_ui import load_recent_dir, prompt_session_dir, save_recent_dir  # noqa: E402


def prompt_folder() -> Path | None:
    recent = load_recent_dir()
    if recent is not None:
        return recent
    return prompt_session_dir()


class EditUi:
    def __init__(self, root_dir: Path) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.root_dir = root_dir.resolve()
        self.takes: list[dict[str, str]] = []
        self.current_id: str | None = None

        self.win = tk.Tk()
        self.win.title("journal-clip · transcription")
        self.win.geometry("640x520")
        self.win.minsize(480, 380)
        style = ttk.Style(self.win)
        apply_look(self.win, style)

        pad = ttk.Frame(self.win)
        pad.pack(fill=tk.BOTH, expand=True, padx=22, pady=18)

        ttk.Label(pad, text="⬡  journal-clip  /  transcription", style="Mast.TLabel").pack(anchor="w")
        ttk.Label(pad, text="edit the plate. record is Clip-ui.bat.", style="Soft.TLabel").pack(
            anchor="w", pady=(6, 8)
        )
        ttk.Label(pad, text=str(self.root_dir), style="Mute.TLabel", wraplength=580).pack(anchor="w")

        self.listbox = tk.Listbox(
            pad,
            height=7,
            bg="#0a0a10",
            fg="#e7e7f2",
            selectbackground="#17172a",
            selectforeground="#7cf7ff",
            relief="flat",
            exportselection=False,
            highlightthickness=1,
            highlightbackground="#272739",
            font=("Consolas", 9),
        )
        self.listbox.pack(fill=tk.X, pady=(8, 8))
        self.listbox.bind("<<ListboxSelect>>", self.on_select)

        self.body = plate(pad, height=12, undo=True)
        self.body.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        row = ttk.Frame(pad)
        row.pack(fill=tk.X)
        ink_button(row, "save text", self.on_save, primary=True).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ink_button(row, "reload", self.reload).pack(side=tk.LEFT, padx=(8, 0))
        self.status = ttk.Label(row, text="", style="Warn.TLabel")
        self.status.pack(side=tk.LEFT, padx=(12, 0))

        self.reload()

    def reload(self) -> None:
        self.takes = list_takes(self.root_dir)
        self.listbox.delete(0, "end")
        if not self.takes:
            if not tape_path(self.root_dir).is_file():
                self.status.configure(text="no tape in this folder")
            else:
                self.status.configure(text="tape empty")
            self.current_id = None
            self.body.delete("1.0", "end")
            return
        for row in self.takes:
            preview = (row.get("text") or "").replace("\n", " ")
            if len(preview) > 72:
                preview = preview[:72] + "…"
            self.listbox.insert(
                "end",
                f"{row.get('id') or '?'}  {row.get('date') or ''}  {preview}",
            )
        self.status.configure(text=f"{len(self.takes)} takes")
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(0)
        self.on_select()

    def on_select(self, _evt: object | None = None) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        row = self.takes[int(sel[0])]
        self.current_id = str(row.get("id") or "")
        self.body.delete("1.0", "end")
        self.body.insert("1.0", row.get("text") or "")
        self.status.configure(text=f"id {self.current_id}")

    def on_save(self) -> None:
        if not self.current_id:
            self.status.configure(text="pick a take")
            return
        text = self.body.get("1.0", "end").strip()
        try:
            update_text(self.root_dir, self.current_id, text)
        except ValueError as e:
            self.status.configure(text=str(e))
            return
        keep = self.current_id
        self.reload()
        for i, row in enumerate(self.takes):
            if str(row.get("id") or "") == keep:
                self.listbox.selection_clear(0, "end")
                self.listbox.selection_set(i)
                self.on_select()
                break
        self.status.configure(text=f"saved id {keep}")

    def run(self) -> None:
        self.win.mainloop()


def main() -> int:
    folder = prompt_folder()
    if folder is None:
        return 0
    save_recent_dir(folder)
    EditUi(folder).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
