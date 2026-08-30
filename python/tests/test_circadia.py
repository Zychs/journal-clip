#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from clip_circadia import last_stamp, next_stamp, server_stamp, store_stamp  # noqa: E402


class TestCircadiaCard(unittest.TestCase):
    def test_bat_and_design_sit_in_the_tree(self):
        self.assertTrue((ROOT / "Circadia.bat").is_file())
        html = ROOT / "design" / "circadia-card.html"
        self.assertTrue(html.is_file())
        body = html.read_text(encoding="utf-8")
        self.assertIn("journal-clip  /  circadia card", body)
        self.assertIn("Circadia.bat", body)
        self.assertIn("Not :3000", body)

    def test_server_stamp_is_honest(self):
        self.assertEqual(server_stamp(0), "stopped · design")
        self.assertEqual(server_stamp(4242), "running · pid 4242")
        self.assertNotIn("ALIGNED", server_stamp(0))
        self.assertNotIn("ALIGNED", server_stamp(1))

    def test_next_stamp_never_invents(self):
        self.assertEqual(next_stamp(None), "—")
        self.assertEqual(
            next_stamp({"id": "morning", "next_due": "2026-08-30T07:00:00", "title": "wake"}),
            "morning  2026-08-30T07:00:00  wake",
        )
        self.assertEqual(next_stamp({"id": "x", "next_due": ""}), "x  —")

    def test_last_stamp_picks_newest_fire(self):
        self.assertEqual(last_stamp([]), "—")
        rows = [
            {"id": "a", "last_fired": "2026-08-29T07:00:00"},
            {"id": "b", "last_fired": "2026-08-29T08:00:00"},
            {"id": "c", "last_fired": ""},
        ]
        self.assertTrue(last_stamp(rows).startswith("b  "))

    def test_store_stamp_is_the_tape_path(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "clip-alarms.jsonl"
            self.assertEqual(store_stamp(p), str(p))

    def test_circadia_card_constructs(self):
        import os
        import tkinter as tk

        from clip_circadia import CircadiaCard

        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError:
            self.skipTest("no display")
        os.environ["SESEFUS_CLIP_ALARMS"] = str(Path(tempfile.gettempdir()) / "circadia-test-alarms.jsonl")
        ui = CircadiaCard()
        try:
            ui.root.update_idletasks()
            self.assertFalse(ui._face_is_back)
            self.assertIn("stopped", ui.stamp.cget("text"))
            ui.on_flip()
            # The flip advances on root.after(FLIP_MS) timers. Spinning update()
            # in a tight loop outruns them and the flip never lands, so wait for
            # it to finish rather than for a fixed number of iterations.
            import time

            deadline = time.monotonic() + 2.0
            while ui._flipping and time.monotonic() < deadline:
                ui.root.update()
                time.sleep(0.005)
            self.assertFalse(ui._flipping, "flip did not finish within 2s")
            self.assertTrue(ui._face_is_back)
        finally:
            ui.root.destroy()


if __name__ == "__main__":
    unittest.main()
