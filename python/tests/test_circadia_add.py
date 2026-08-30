#!/usr/bin/env python3
"""The add face: one field to type, and nothing that can hold a bad value."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from clip_circadia import DO_ORDER, clamp_clock, slugify  # noqa: E402


class TestSlugify(unittest.TestCase):
    def test_title_becomes_a_legal_id(self):
        import re

        from clip_alarm import _SLUG_OK

        cases = [
            "wake journal",
            "Wake Journal",
            "  Morning   Plate  ",
            "wind-down @ 10pm!",
            "***stretch***",
            "café notes",
            "7am start",
            "a" * 80,
        ]
        for title in cases:
            got = slugify(title)
            self.assertTrue(got, f"{title!r} produced an empty slug")
            self.assertTrue(
                _SLUG_OK.match(got), f"{title!r} -> {got!r} is not a legal alarm id"
            )
            self.assertLessEqual(len(got), 32)
            self.assertIsNone(re.search(r"--", got), f"{got!r} has a double dash")

    def test_known_shapes(self):
        self.assertEqual(slugify("wake journal"), "wake-journal")
        self.assertEqual(slugify("Wind-Down @ 10pm!"), "wind-down-10pm")
        self.assertEqual(slugify("7am start"), "7am-start")

    def test_unsluggable_title_is_empty_not_illegal(self):
        for title in ["", "   ", "!!!", "***", "---"]:
            self.assertEqual(slugify(title), "")


class TestClockLock(unittest.TestCase):
    def test_clamps_into_a_real_time_of_day(self):
        self.assertEqual(clamp_clock("07", "00"), (7, 0))
        self.assertEqual(clamp_clock("23", "59"), (23, 59))
        self.assertEqual(clamp_clock("99", "99"), (23, 59))
        self.assertEqual(clamp_clock("", ""), (0, 0))
        self.assertEqual(clamp_clock("  ", "5"), (0, 5))
        self.assertEqual(clamp_clock("abc", "xy"), (0, 0))

    def test_every_clamped_pair_parses_as_a_when(self):
        from clip_alarm import parse_when

        for raw_h, raw_m in [("07", "00"), ("99", "99"), ("", ""), ("abc", "7")]:
            h, m = clamp_clock(raw_h, raw_m)
            parse_when(f"{h:02d}:{m:02d}")  # raises AlarmError if the lock leaks


class TestDoToggle(unittest.TestCase):
    def test_cycle_covers_every_action_clip_alarm_accepts(self):
        from clip_alarm import ACTIONS

        self.assertEqual(set(DO_ORDER), ACTIONS)
        self.assertEqual(DO_ORDER[0], "hop")


class TestAddFaceWidgets(unittest.TestCase):
    def test_card_builds_and_the_face_carries_no_hint_text(self):
        import tkinter as tk

        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError:
            self.skipTest("no display")

        with tempfile.TemporaryDirectory() as td:
            os.environ["SESEFUS_CLIP_ALARMS"] = str(Path(td) / "clip-alarms.jsonl")
            self.addCleanup(lambda: os.environ.pop("SESEFUS_CLIP_ALARMS", None))
            from clip_circadia import CircadiaCard

            ui = CircadiaCard()
            try:
                ui.root.update_idletasks()

                # the id follows the title, and is never typed
                ui.add_title.set("Wake Journal")
                self.assertEqual(ui.add_id.get(), "wake-journal")
                ui.add_title.set("")
                self.assertEqual(ui.add_id.get(), "")

                # the clock boxes refuse anything that is not a clock
                self.assertTrue(ui._clock_ok("7"))
                self.assertTrue(ui._clock_ok("23"))
                self.assertTrue(ui._clock_ok(""))
                self.assertFalse(ui._clock_ok("7a"))
                self.assertFalse(ui._clock_ok("123"))
                self.assertFalse(ui._clock_ok("+25m"))
                ui.when_h.set("99")
                ui.when_m.set("99")
                ui._norm_clock()
                self.assertEqual(ui.when_text(), "23:59")

                # do is a toggle, two fields tall, starting on hop
                self.assertEqual(ui.do_btn.cget("text"), "hop")
                info = ui.do_btn.grid_info()
                self.assertEqual(int(info["rowspan"]), 2)
                self.assertEqual(int(info["row"]), 0)
                ui.on_do_toggle()
                self.assertEqual(ui.do_btn.cget("text"), "cue")
                ui.on_do_toggle()
                ui.on_do_toggle()
                self.assertEqual(ui.do_btn.cget("text"), "hop")

                # nothing on the add face is prose
                labels = self._label_texts(ui.face_front)
                self.assertEqual(
                    sorted(labels), sorted([":", "every", "id", "note", "title", "when"])
                )
            finally:
                ui.root.destroy()

    def _label_texts(self, widget: object) -> list[str]:
        from tkinter import ttk

        out: list[str] = []
        for child in widget.winfo_children():  # type: ignore[attr-defined]
            if isinstance(child, ttk.Label):
                text = str(child.cget("text")).strip()
                if text:
                    out.append(text)
            out.extend(self._label_texts(child))
        return out


if __name__ == "__main__":
    unittest.main()
