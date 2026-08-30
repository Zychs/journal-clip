#!/usr/bin/env python3
"""The hand. One window, one bat file, every card.

    record  |  alarm  |  controls

Three cards, each two-faced. The tab strip picks the card; `flip` (or the f
key) turns the card that is showing:

    record     front record          back ledger
    alarm      front add             back edit
    controls   front storage         back prompt-out

Every card is the same class the standalone launcher opens - `Clip-ui.bat`,
`Circadia.bat` and `python\\clip_controls.py` still work and still open one
card in its own window. The only difference in a hand is that the card is
handed a parent frame, so the window, the look and the close belong here.

Cards are built the first time their tab is picked, not at startup, because
the record card opens a capture device list and the alarm card starts a clock.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
CLIP_ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from clip_config import resolved_out_dir  # noqa: E402
from clip_look import (  # noqa: E402
    BG_TOP,
    CYAN,
    FONT_MONO_SM,
    INK_MUTE,
    LINE,
    PANEL,
    apply as apply_look,
)
from clip_ui import load_recent_dir, prompt_session_dir, save_recent_dir  # noqa: E402

WINDOW = (1000, 760)
WINDOW_MIN = (780, 600)

# Tab order is the order of the sentence: you speak, time fires, then you
# decide what is kept and what is said about it.
CARDS = ("record", "alarm", "controls")

# Each card's design width, from its own artboard and its own standalone
# geometry. A card is centred at this width rather than stretched to the
# window: a 520-wide card pulled across 1000px stops reading as a card.
CARD_WIDTH = {"record": 520, "alarm": 980, "controls": 520}


def card_width(name: str, available: int) -> int:
    """How wide to draw a card in a window this wide. Never wider than the room."""
    want = int(CARD_WIDTH.get(name, 520))
    room = int(available)
    if room <= 0:
        return want
    return min(want, room)


def next_card(current: str, by: int, cards: tuple[str, ...] = CARDS) -> str:
    """Wrap through the hand. ctrl+tab forward, ctrl+shift+tab back."""
    if not cards:
        return current
    try:
        i = cards.index(current)
    except ValueError:
        return cards[0]
    return cards[(i + int(by)) % len(cards)]


class Hand:
    def __init__(self, out_dir: Path) -> None:
        import tkinter as tk
        from tkinter import ttk

        self.tk = tk
        self.out_dir = Path(out_dir).resolve()
        self.cards: dict[str, Any] = {}
        self.slots: dict[str, Any] = {}
        self.tabs: dict[str, Any] = {}
        self.active = ""

        self.root = tk.Tk()
        self.root.title("journal-clip")
        self.root.geometry("%dx%d" % WINDOW)
        self.root.minsize(*WINDOW_MIN)
        style = ttk.Style(self.root)
        apply_look(self.root, style)

        pad = ttk.Frame(self.root)
        pad.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)

        strip = ttk.Frame(pad)
        strip.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(strip, text="⬡  journal-clip", style="Mast.TLabel").pack(side=tk.LEFT, padx=(0, 14))
        for name in CARDS:
            btn = tk.Button(
                strip,
                text=name,
                command=lambda n=name: self.show(n),
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
                cursor="hand2",
                padx=14,
                pady=4,
            )
            btn.pack(side=tk.LEFT, padx=(0, 6))
            self.tabs[name] = btn
        self.hint = ttk.Label(strip, text="tab · ctrl+tab · f flips", style="Mute.TLabel")
        self.hint.pack(side=tk.RIGHT)

        self.body = ttk.Frame(pad)
        self.body.pack(fill=tk.BOTH, expand=True)
        self.body.bind("<Configure>", self._fit_active)
        for name in CARDS:
            slot = ttk.Frame(self.body)
            self.slots[name] = slot

        self.root.bind("<Key-f>", self._on_key_flip)
        self.root.bind("<Key-F>", self._on_key_flip)
        self.root.bind("<Control-Tab>", lambda _e: self._step(1))
        self.root.bind("<Control-Shift-Tab>", lambda _e: self._step(-1))
        for i, name in enumerate(CARDS, start=1):
            self.root.bind(f"<Key-{i}>", lambda _e, n=name: self._key_show(n))
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.show(CARDS[0])

    # ---- building ------------------------------------------------------

    def _build(self, name: str) -> Any:
        """Construct one card into its slot. First pick only."""
        slot = self.slots[name]
        if name == "record":
            from clip_ui import ClipUi

            return ClipUi(self.out_dir, master=slot)
        if name == "alarm":
            from clip_circadia import CircadiaCard

            return CircadiaCard(master=slot)
        if name == "controls":
            from clip_controls import ControlsCard

            return ControlsCard(self.out_dir, master=slot)
        raise KeyError(name)

    def _fit_active(self, _evt: Any = None) -> None:
        """Keep the showing card centred at its design width."""
        if not self.active:
            return
        width = card_width(self.active, self.body.winfo_width())
        self.slots[self.active].place_configure(width=width)

    def show(self, name: str) -> None:
        if name not in self.slots or name == self.active:
            return
        if self.active:
            self.slots[self.active].place_forget()
        if name not in self.cards:
            self.cards[name] = self._build(name)
        self.slots[name].place(
            relx=0.5,
            y=0,
            relheight=1.0,
            anchor="n",
            width=card_width(name, self.body.winfo_width()),
        )
        self.active = name
        for tab, btn in self.tabs.items():
            on = tab == name
            btn.configure(fg=CYAN if on else INK_MUTE, highlightbackground=CYAN if on else LINE)
        # the controls card reads three stores from disk; a take recorded on
        # the record card is only visible here if it re-reads on the way in
        card = self.cards[name]
        if hasattr(card, "refresh"):
            card.refresh()

    # ---- keys ----------------------------------------------------------

    def _typing(self, widget: Any) -> bool:
        """True when a key belongs to a field, not to the hand."""
        cls = widget.winfo_class() if hasattr(widget, "winfo_class") else ""
        return cls in ("TEntry", "Entry", "Text", "TCombobox", "TSpinbox", "Spinbox")

    def _on_key_flip(self, evt: Any) -> None:
        if self._typing(evt.widget):
            return
        self.flip_active()

    def _key_show(self, name: str) -> None:
        focus = self.root.focus_get()
        if focus is not None and self._typing(focus):
            return
        self.show(name)

    def _step(self, by: int) -> str:
        self.show(next_card(self.active, by))
        return "break"

    def flip_active(self) -> None:
        card = self.cards.get(self.active)
        if card is not None and hasattr(card, "flip"):
            card.flip(animate=True)

    # ---- close ---------------------------------------------------------

    def on_close(self) -> None:
        for card in self.cards.values():
            shutdown = getattr(card, "shutdown", None)
            if callable(shutdown):
                try:
                    shutdown()
                except Exception:
                    pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def pick_out_dir() -> Path | None:
    """Last folder, else the configured one, else ask. Same rule as Clip-ui."""
    recent = load_recent_dir()
    if recent is not None:
        return recent
    configured = resolved_out_dir()
    if configured.is_dir():
        return configured
    return prompt_session_dir()


def main() -> int:
    out = pick_out_dir()
    if out is None:
        return 0
    save_recent_dir(out)
    Hand(out).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
