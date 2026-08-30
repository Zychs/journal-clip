#!/usr/bin/env python3
"""The controls card. Front is storage, back is prompt-out.

Design: design/canvas/Controls.dc.html

Front — the three data products, each stating its own preservation rule, its
size and its health, read live from the journal folder. The archive/shred
toggle is the one destructive control on this card, so it sits alone.

Back — what read the take and what wrote about it: the three model ids, the
global system prompt, and the per-kind overrides. Nothing on that face is
ground truth and the face says so.

Every number here comes from clip_store.systems_status. Nothing is invented:
if a store is empty the card says empty, it does not say healthy.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CLIP_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import clip_audio  # noqa: E402
import clip_store  # noqa: E402
from clip_config import (  # noqa: E402
    AUDIO_RETENTIONS,
    load_config,
    resolved_out_dir,
    save_config,
)
from clip_look import (  # noqa: E402
    AMBER,
    BG_TOP,
    CYAN,
    CYAN_SOFT,
    FONT_MONO_SM,
    GOOD,
    INK,
    INK_MUTE,
    INK_SOFT,
    LINE,
    PANEL,
    VOID,
    apply as apply_look,
    card,
    ink_button,
    log_box,
)
from clip_ui import FLIP_MS, FLIP_STEPS, flip_swap_step, flip_width_scale  # noqa: E402

WINDOW = (520, 680)
WINDOW_MIN = (460, 560)

PROTO_PATH = HERE / "prototypes.json"

# The three products in the order the README states them. The accent is how a
# glance tells them apart; it is not a health colour.
PRODUCTS = (
    ("raw_audio", "raw audio", CYAN),
    ("transcript", "transcript / diarization", CYAN_SOFT),
    ("derived_semantics", "derived semantics", AMBER),
)


def human_bytes(n: int) -> str:
    """Size a person reads. Bytes below a kilobyte, never 0.0 KB."""
    n = int(n or 0)
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB"):
        n_f = n / 1024.0
        if n_f < 1024 or unit == "GB":
            return f"{n_f:.1f} {unit}"
        n = int(n_f)
    return f"{n} B"


def integrity_line(problems: Any) -> tuple[str, str]:
    """(text, tone) for the raw-audio health chip.

    clip_audio.verify returns [] when every clip still hashes to its name;
    clip_store.systems_status turns that empty list into the word "intact".
    Anything else is a list of real problems and is reported as a count.
    """
    if problems == "intact":
        return "intact", GOOD
    if isinstance(problems, list) and not problems:
        return "intact", GOOD
    if isinstance(problems, list):
        return f"{len(problems)} damaged", AMBER
    return str(problems), AMBER


def model_counts(counts: dict[str, int] | None) -> str:
    """`whisper:base ×106  ·  large-v3 ×9`, or the honest empty."""
    items = sorted((counts or {}).items(), key=lambda kv: (-int(kv[1]), kv[0]))
    if not items:
        return "none yet"
    return "  ·  ".join(f"{k} ×{v}" for k, v in items)


def product_facts(key: str, block: dict[str, Any]) -> tuple[str, list[tuple[str, str]]]:
    """(headline, [(chip, tone)]) for one product panel."""
    if key == "raw_audio":
        clips = int(block.get("clips") or 0)
        text, tone = integrity_line(block.get("integrity"))
        return (
            human_bytes(block.get("bytes") or 0),
            [
                (f"{clips} clips", INK_SOFT),
                (text, tone),
                ("read-only on disk", INK_MUTE),
            ],
        )
    if key == "transcript":
        takes = int(block.get("takes") or 0)
        versions = int(block.get("versions") or 0)
        chips = [(f"{takes} takes", INK_SOFT), (model_counts(block.get("transcription_models")), INK_MUTE)]
        # who read it only earns a chip when it says something the model id
        # does not - a human correction, an import, or a mix of producers
        read_by = block.get("read_by") or {}
        if len(read_by) > 1 or "human" in read_by or "import" in read_by:
            chips.append((model_counts(read_by), INK_SOFT if "human" in read_by else INK_MUTE))
        return (f"{versions} v", chips)
    stale = list(block.get("stale") or [])
    revisions = int(block.get("revisions") or 0)
    return (
        f"{len(stale)} stale" if stale else "current",
        [
            (f"{revisions} revisions", INK_SOFT),
            ("ground_truth false", INK_MUTE),
            ("safe to discard", INK_MUTE),
        ],
    )


def load_models(path: Path | None = None) -> dict[str, str]:
    """The three model ids this tree is configured to use. From disk, not memory."""
    p = path or PROTO_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "whisper": str(data.get("whisper_model") or ""),
        "embed": str(data.get("embed_model") or ""),
        "chat": str(data.get("chat_model") or ""),
    }


def load_kinds(path: Path | None = None) -> list[str]:
    p = path or PROTO_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    kinds = data.get("kinds") if isinstance(data, dict) else None
    if not isinstance(kinds, list):
        return []
    return [str(k.get("id") or "") for k in kinds if isinstance(k, dict) and k.get("id")]


def kind_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get("kind") or "").strip()
        if k:
            out[k] = out.get(k, 0) + 1
    return out


def prompt_source_line(cfg: dict[str, Any], builtin_n: int) -> str:
    """What the 7B is actually told, globally. Names the file when there is one."""
    path = str(cfg.get("prompt_file") or "").strip()
    if path:
        return path
    return f"builtin · {builtin_n} prompts"


class ControlsCard:
    """Storage ⟷ prompt-out. `master` mounts it into a hand; see ClipUi."""

    def __init__(self, out_dir: Path | None = None, master: Any = None) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.cfg = load_config()
        self.out_dir = Path(out_dir) if out_dir else resolved_out_dir(self.cfg)
        self._face_is_back = False
        self._flipping = False
        self._flip_step = 0
        self._flip_dest_back = False
        self._flip_job: str | int | None = None
        self._closing = False
        self._retention_btns: dict[str, Any] = {}
        self._product_rows: dict[str, dict[str, Any]] = {}
        self.owns_root = master is None

        if master is None:
            self.root = tk.Tk()
            self.root.title("journal-clip · controls")
            self.root.geometry("%dx%d" % WINDOW)
            self.root.minsize(*WINDOW_MIN)
            style = ttk.Style(self.root)
            apply_look(self.root, style)
            pad = ttk.Frame(self.root)
            pad.pack(fill=tk.BOTH, expand=True, padx=18, pady=16)
        else:
            self.root = master.winfo_toplevel()
            pad = ttk.Frame(master)
            pad.pack(fill=tk.BOTH, expand=True)

        self.card = card(pad)
        self.card.pack(fill=tk.BOTH, expand=True)

        # see ClipUi: the hand's strip already says journal-clip
        self._mast_prefix = "⬡  journal-clip  /  " if self.owns_root else ""

        chrome = ttk.Frame(self.card)
        chrome.pack(fill=tk.X, padx=14, pady=(12, 0))
        self.mast = ttk.Label(chrome, text=f"{self._mast_prefix}controls · storage", style="Mast.TLabel")
        self.mast.pack(side=tk.LEFT)
        self.flip_btn = ink_button(chrome, "flip", self.on_flip)
        self.flip_btn.pack(side=tk.RIGHT)

        self.flip_host = ttk.Frame(self.card)
        self.flip_host.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
        self.face_front = ttk.Frame(self.flip_host)
        self.face_back = ttk.Frame(self.flip_host)
        self._build_storage(self.face_front)
        self._build_prompt_out(self.face_back)
        self._apply_face(1.0)

        self.refresh()

    # ---- front: storage ------------------------------------------------

    def _build_storage(self, parent: Any) -> None:
        import tkinter as tk
        from tkinter import ttk

        dirrow = ttk.Frame(parent)
        dirrow.pack(fill=tk.X, pady=(0, 10))
        self.dir_label = ttk.Label(dirrow, text=str(self.out_dir), style="Mute.TLabel", wraplength=380)
        self.dir_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ink_button(dirrow, "change", self.on_change_dir).pack(side=tk.RIGHT)

        for key, name, accent in PRODUCTS:
            panel = tk.Frame(parent, bg=VOID, highlightthickness=1, highlightbackground=LINE)
            panel.pack(fill=tk.X, pady=(0, 8))
            # the accent is a left edge, as on the artboard - one pixel column,
            # not a coloured panel, so three of them do not fight
            edge = tk.Frame(panel, bg=accent, width=2)
            edge.pack(side=tk.LEFT, fill=tk.Y)
            body = tk.Frame(panel, bg=VOID)
            body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=8)

            head = tk.Frame(body, bg=VOID)
            head.pack(fill=tk.X)
            tk.Label(head, text=name, bg=VOID, fg=INK, font=("Segoe UI", 9)).pack(side=tk.LEFT)
            big = tk.Label(head, text="—", bg=VOID, fg=accent, font=("Consolas", 11))
            big.pack(side=tk.RIGHT)
            rule = tk.Label(body, text="", bg=VOID, fg=INK_MUTE, font=FONT_MONO_SM, anchor="w")
            rule.pack(fill=tk.X, pady=(4, 0))
            chips = tk.Frame(body, bg=VOID)
            chips.pack(fill=tk.X, pady=(5, 0))
            self._product_rows[key] = {"big": big, "rule": rule, "chips": chips}

        # The artboard pins this block to the foot of the card (margin-top:auto)
        # so the destructive control never drifts up into the readouts. Packed
        # bottom-up, hence the reversed order.
        self.say_line = ttk.Label(parent, text="", style="Soft.TLabel", wraplength=440)
        self.say_line.pack(side=tk.BOTTOM, anchor="w", pady=(8, 0))

        actrow = ttk.Frame(parent)
        actrow.pack(side=tk.BOTTOM, fill=tk.X)
        ink_button(actrow, "verify audio", self.on_verify).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.stale_btn = ink_button(actrow, "stale —", self.on_stale)
        self.stale_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        ink_button(actrow, "rebuild view", self.on_rebuild).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0)
        )

        keeprow = ttk.Frame(parent)
        keeprow.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 10))
        ttk.Label(parent, text="raw audio retention", style="Mute.TLabel").pack(
            side=tk.BOTTOM, anchor="w", pady=(10, 4)
        )
        notes = {
            "archive": "keep the wav · ~32 KB/s",
            "shred": "text only · sound gone",
        }
        for mode in AUDIO_RETENTIONS:
            btn = tk.Button(
                keeprow,
                text=f"{mode}\n{notes[mode]}",
                command=lambda m=mode: self.set_retention(m),
                bg=PANEL,
                fg=INK_MUTE,
                activebackground=BG_TOP,
                activeforeground=CYAN,
                bd=0,
                relief="flat",
                highlightthickness=1,
                highlightbackground=LINE,
                highlightcolor=CYAN,
                font=FONT_MONO_SM,
                justify="left",
                anchor="w",
                cursor="hand2",
                padx=10,
                pady=6,
            )
            btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
            self._retention_btns[mode] = btn

    # ---- back: prompt-out ----------------------------------------------

    def _build_prompt_out(self, parent: Any) -> None:
        import tkinter as tk
        from tkinter import ttk

        models = load_models()
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.X, pady=(0, 10))
        grid.columnconfigure(1, weight=1)
        for i, key in enumerate(("whisper", "embed", "chat")):
            ttk.Label(grid, text=key, style="Mute.TLabel", width=9).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(
                grid,
                text=models.get(key) or "not configured",
                style="Soft.TLabel",
            ).grid(row=i, column=1, sticky="w", pady=2)
            # "local" / "ollama" is where it runs, not whether it answered.
            # This card does not probe, so it must not claim up.
            where = "local" if key == "whisper" else "ollama"
            ttk.Label(grid, text=where, style="Mute.TLabel").grid(row=i, column=2, sticky="e", pady=2)

        ttk.Label(parent, text="system prompt · global", style="Mute.TLabel").pack(anchor="w")
        prow = ttk.Frame(parent)
        prow.pack(fill=tk.X, pady=(4, 10))
        self.prompt_label = ttk.Label(prow, text="—", style="Soft.TLabel", wraplength=340)
        self.prompt_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ink_button(prow, "pick", self.on_pick_prompt).pack(side=tk.RIGHT)
        ink_button(prow, "clear", self.on_clear_prompt).pack(side=tk.RIGHT, padx=(0, 6))

        ttk.Label(
            parent,
            text="per-kind override · cosine still picks the kind",
            style="Mute.TLabel",
        ).pack(anchor="w")
        self.kinds_box = log_box(parent, height=9)
        self.kinds_box.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        self.kinds_box.configure(state="disabled")

        ttk.Label(
            parent,
            text="every output here is revisable · nothing on this face is ground truth",
            style="Mute.TLabel",
        ).pack(anchor="w")

    # ---- data ----------------------------------------------------------

    def refresh(self) -> None:
        """Re-read config and all three stores, then repaint both faces."""
        self.cfg = load_config()
        try:
            status = clip_store.systems_status(self.out_dir)
        except Exception as e:  # a folder that is not a journal yet
            self.say(f"cannot read {self.out_dir}: {e}", warn=True)
            status = {}
        self._paint_products(status)
        self._paint_retention()
        self._paint_prompt_out()

    def _paint_products(self, status: dict[str, Any]) -> None:
        import tkinter as tk

        for key, _name, accent in PRODUCTS:
            row = self._product_rows.get(key)
            if not row:
                continue
            block = status.get(key) or {}
            headline, chips = product_facts(key, block)
            row["big"].configure(text=headline)
            row["rule"].configure(text=str(block.get("rule") or "—"))
            for child in row["chips"].winfo_children():
                child.destroy()
            for text, tone in chips:
                tk.Label(
                    row["chips"],
                    text=text,
                    bg=VOID,
                    fg=tone,
                    font=FONT_MONO_SM,
                    highlightthickness=1,
                    highlightbackground=LINE,
                    padx=6,
                    pady=1,
                ).pack(side=tk.LEFT, padx=(0, 5))
        stale = list((status.get("derived_semantics") or {}).get("stale") or [])
        self.stale_btn.configure(text=f"stale {len(stale)}")
        self._stale = stale

    def _paint_retention(self) -> None:
        keep = str(self.cfg.get("audio_retention") or "archive")
        for mode, btn in self._retention_btns.items():
            on = mode == keep
            # shred is the destructive choice, so when it is the live one it
            # is amber, not cyan. Cyan would read as approval.
            tone = (AMBER if mode == "shred" else CYAN) if on else INK_MUTE
            btn.configure(fg=tone, highlightbackground=tone if on else LINE)

    def _paint_prompt_out(self) -> None:
        kinds = load_kinds()
        self.prompt_label.configure(text=prompt_source_line(self.cfg, len(kinds)))
        try:
            rows = clip_store.list_takes(self.out_dir)
        except Exception:
            rows = []
        counts = kind_counts(rows)
        overrides = self.cfg.get("prompt_overrides") or {}
        lines = []
        for kind in kinds:
            src = str(overrides.get(kind) or "").strip()
            mark = ">" if src else " "
            lines.append(f"{mark} {kind:<11} {(src or 'builtin'):<34} {counts.get(kind, 0)}")
        if not lines:
            lines = ["prototypes.json has no kinds"]
        self.kinds_box.configure(state="normal")
        self.kinds_box.delete("1.0", "end")
        self.kinds_box.insert("1.0", "\n".join(lines))
        self.kinds_box.configure(state="disabled")

    def say(self, text: str, *, warn: bool = False) -> None:
        if not hasattr(self, "say_line"):
            return
        self.say_line.configure(text=text, style="Warn.TLabel" if warn else "Soft.TLabel")

    # ---- actions -------------------------------------------------------

    def set_retention(self, mode: str) -> None:
        if mode not in AUDIO_RETENTIONS:
            return
        self.cfg["audio_retention"] = mode
        save_config(self.cfg)
        self._paint_retention()
        if mode == "shred":
            self.say("shred — new takes keep text only, the sound is gone", warn=True)
        else:
            self.say("archive — the wav is kept under audio/, never overwritten")

    def on_change_dir(self) -> None:
        from clip_ui import prompt_session_dir

        chosen = prompt_session_dir()
        if chosen is None:
            return
        self.out_dir = chosen.resolve()
        self.dir_label.configure(text=str(self.out_dir))
        self.refresh()
        self.say(f"folder {self.out_dir}")

    def on_verify(self) -> None:
        try:
            problems = clip_audio.verify(self.out_dir)
        except Exception as e:
            self.say(f"verify failed: {e}", warn=True)
            return
        if not problems:
            self.say("every archived clip still hashes to its name")
        else:
            first = problems[0]
            self.say(f"{len(problems)} damaged · first {first.get('uid') or first}", warn=True)
        self.refresh()

    def on_stale(self) -> None:
        """Name what is owed a recompute. Does not run one - that is clip_heavy."""
        stale = list(getattr(self, "_stale", []))
        if not stale:
            self.say("no take is owed a recompute")
            return
        shown = ", ".join(stale[:8])
        more = f" (+{len(stale) - 8})" if len(stale) > 8 else ""
        self.say(f"owed a recompute: {shown}{more} — re-record or re-run the heavy pass", warn=True)

    def on_rebuild(self) -> None:
        try:
            path = clip_store.project(self.out_dir)
        except Exception as e:
            self.say(f"rebuild failed: {e}", warn=True)
            return
        self.say(f"rebuilt {path.name} from the three stores")
        self.refresh()

    def on_pick_prompt(self) -> None:
        from tkinter import filedialog

        chosen = filedialog.askopenfilename(
            parent=self.root,
            title="Controls — global system prompt for the 7B",
            filetypes=[("Markdown / text", "*.md *.txt"), ("All files", "*.*")],
        )
        if not chosen:
            return
        self.cfg["prompt_file"] = str(Path(chosen))
        save_config(self.cfg)
        self._paint_prompt_out()
        self.say(f"prompt {Path(chosen).name}")

    def on_clear_prompt(self) -> None:
        self.cfg["prompt_file"] = ""
        self.cfg["prompt_overrides"] = {}
        save_config(self.cfg)
        self._paint_prompt_out()
        self.say("back to the built-in prompts")

    # ---- flip ----------------------------------------------------------

    def on_flip(self) -> None:
        self.flip(animate=True)

    def flip(self, *, animate: bool = True) -> None:
        if self._flipping:
            return
        nxt = not self._face_is_back
        if not animate:
            self._face_is_back = nxt
            self._apply_face(1.0)
            return
        self._flipping = True
        self._flip_step = 0
        self._flip_dest_back = nxt
        self._tick_flip()

    def _tick_flip(self) -> None:
        step = self._flip_step
        steps = FLIP_STEPS
        if step == flip_swap_step(steps):
            self._face_is_back = self._flip_dest_back
        self._apply_face(flip_width_scale(step, steps))
        if step >= steps:
            self._flipping = False
            self._flip_job = None
            self._apply_face(1.0)
            return
        self._flip_step = step + 1
        self._flip_job = self.root.after(FLIP_MS, self._tick_flip)

    def _apply_face(self, scale: float) -> None:
        show = self.face_back if self._face_is_back else self.face_front
        hide = self.face_front if self._face_is_back else self.face_back
        hide.place_forget()
        show.place(relx=0.5, rely=0, relwidth=max(0.02, float(scale)), relheight=1.0, anchor="n")
        face = "prompt-out" if self._face_is_back else "storage"
        self.mast.configure(text=f"{self._mast_prefix}controls · {face}")

    def shutdown(self) -> None:
        self._closing = True
        if self._flip_job is not None:
            try:
                self.root.after_cancel(self._flip_job)
            except Exception:
                pass
            self._flip_job = None

    def on_close(self) -> None:
        self.shutdown()
        self.root.destroy()

    def run(self) -> None:
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()


def main() -> int:
    ControlsCard().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
