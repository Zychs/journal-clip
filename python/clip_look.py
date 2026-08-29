"""negentropic-blue tokens for tk clip windows. House look, not Matrix."""
from __future__ import annotations

from typing import Any, Callable

# tokens.css — ink / cyan frame / void
BG = "#050509"
BG_TOP = "#17172a"
INK = "#e7e7f2"
INK_STRONG = "#f4f4fb"
INK_SOFT = "#a7a7bd"
INK_MUTE = "#6c6c83"
CYAN = "#7cf7ff"
CYAN_SOFT = "#9fe9f1"
CYAN_DEEP = "#28A2B2"
AMBER = "#e2a24a"
LINE = "#272739"
PANEL = "#101018"
VOID = "#0a0a10"
GOOD = "#4CAE7C"

FONT_BODY = ("Segoe UI", 10)
FONT_BODY_SM = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 10)
FONT_MONO_SM = ("Consolas", 8)
FONT_MAST = ("Consolas", 8, "normal")
FONT_RECORD = ("Consolas", 11, "bold")
FONT_PLATE = ("Segoe UI", 12)


def apply(root: Any, style: Any) -> None:
    root.configure(bg=BG)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure(".", background=BG, foreground=INK, fieldbackground=PANEL, bordercolor=LINE)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=INK, font=FONT_BODY)
    style.configure("Mast.TLabel", background=BG, foreground=CYAN, font=FONT_MAST)
    style.configure("Soft.TLabel", background=BG, foreground=INK_SOFT, font=FONT_BODY_SM)
    style.configure("Mute.TLabel", background=BG, foreground=INK_MUTE, font=FONT_MONO_SM)
    style.configure("Warn.TLabel", background=BG, foreground=AMBER, font=FONT_BODY_SM)
    style.configure(
        "TCombobox",
        fieldbackground=PANEL,
        background=PANEL,
        foreground=INK,
        arrowcolor=CYAN,
        bordercolor=LINE,
        lightcolor=LINE,
        darkcolor=LINE,
        padding=4,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", PANEL), ("disabled", VOID)],
        foreground=[("readonly", INK)],
        background=[("readonly", PANEL)],
        selectbackground=[("readonly", BG_TOP)],
        selectforeground=[("readonly", INK_STRONG)],
    )
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", INK)
    root.option_add("*TCombobox*Listbox.selectBackground", BG_TOP)
    root.option_add("*TCombobox*Listbox.selectForeground", CYAN)
    root.option_add("*TCombobox*Listbox.font", FONT_MONO_SM)
    style.configure(
        "Tape.Treeview",
        background=VOID,
        fieldbackground=VOID,
        foreground=INK,
        bordercolor=LINE,
        lightcolor=LINE,
        darkcolor=LINE,
        rowheight=26,
        font=FONT_PLATE,
    )
    style.map(
        "Tape.Treeview",
        background=[("selected", BG_TOP)],
        foreground=[("selected", CYAN)],
    )
    style.configure(
        "Tape.Treeview.Heading",
        background=BG,
        foreground=INK_MUTE,
        relief="flat",
        font=FONT_MAST,
    )
    style.configure(
        "Vertical.TScrollbar",
        background=PANEL,
        troughcolor=VOID,
        bordercolor=LINE,
        arrowcolor=CYAN,
        lightcolor=LINE,
        darkcolor=LINE,
    )


def dot_button(parent: Any, text: str, command: Callable[[], None], *, active: bool = False) -> Any:
    import tkinter as tk

    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=PANEL,
        fg=CYAN if active else INK_MUTE,
        activebackground=BG_TOP,
        activeforeground=CYAN,
        disabledforeground=INK_MUTE,
        bd=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground=CYAN if active else LINE,
        highlightcolor=CYAN,
        font=FONT_MAST,
        cursor="hand2",
        padx=6,
        pady=2,
    )


def card(parent: Any) -> Any:
    """One bordered face. House void, not a second window."""
    import tkinter as tk

    return tk.Frame(
        parent,
        bg=BG,
        highlightthickness=1,
        highlightbackground=LINE,
        highlightcolor=CYAN,
    )


def ink_button(parent: Any, text: str, command: Callable[[], None], *, primary: bool = False) -> Any:
    import tkinter as tk

    if primary:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=PANEL,
            fg=CYAN,
            activebackground=BG_TOP,
            activeforeground=CYAN_SOFT,
            disabledforeground=INK_MUTE,
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=CYAN,
            highlightcolor=CYAN,
            font=FONT_RECORD,
            cursor="hand2",
            pady=10,
        )
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=PANEL,
        fg=INK_SOFT,
        activebackground=BG_TOP,
        activeforeground=INK,
        disabledforeground=INK_MUTE,
        bd=0,
        relief="flat",
        highlightthickness=1,
        highlightbackground=LINE,
        highlightcolor=LINE,
        font=FONT_MONO_SM,
        cursor="hand2",
        padx=10,
        pady=4,
    )


def plate(parent: Any, **kwargs: Any) -> Any:
    import tkinter as tk

    w = tk.Text(
        parent,
        bg=VOID,
        fg=INK_STRONG,
        insertbackground=CYAN,
        relief="flat",
        wrap="word",
        font=FONT_PLATE,
        highlightthickness=1,
        highlightbackground=LINE,
        highlightcolor=CYAN_DEEP,
        padx=12,
        pady=10,
        **kwargs,
    )
    return w


def log_box(parent: Any, **kwargs: Any) -> Any:
    import tkinter as tk

    w = tk.Text(
        parent,
        bg=VOID,
        fg=INK_MUTE,
        insertbackground=INK_MUTE,
        relief="flat",
        wrap="word",
        font=FONT_MONO_SM,
        highlightthickness=1,
        highlightbackground=LINE,
        highlightcolor=LINE,
        padx=8,
        pady=6,
        **kwargs,
    )
    return w
