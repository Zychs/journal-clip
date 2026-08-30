#!/usr/bin/env python3
"""One window, three cards. The hand builds lazily and flips the one showing."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from clip_controls import (  # noqa: E402
    human_bytes,
    integrity_line,
    kind_counts,
    load_kinds,
    load_models,
    model_counts,
    product_facts,
    prompt_source_line,
)
from clip_hand import CARDS, next_card  # noqa: E402


class TestHandOrder(unittest.TestCase):
    def test_the_hand_is_record_alarm_controls(self):
        self.assertEqual(CARDS, ("record", "alarm", "controls"))

    def test_next_card_wraps_both_ways(self):
        self.assertEqual(next_card("record", 1), "alarm")
        self.assertEqual(next_card("controls", 1), "record")
        self.assertEqual(next_card("record", -1), "controls")
        self.assertEqual(next_card("alarm", -1), "record")

    def test_next_card_recovers_from_an_unknown_name(self):
        self.assertEqual(next_card("", 1), "record")
        self.assertEqual(next_card("cabinet", -1), "record")


class TestControlsReadouts(unittest.TestCase):
    def test_human_bytes_never_says_zero_point_zero_kb(self):
        self.assertEqual(human_bytes(0), "0 B")
        self.assertEqual(human_bytes(512), "512 B")
        self.assertEqual(human_bytes(1024), "1.0 KB")
        self.assertEqual(human_bytes(1536), "1.5 KB")
        self.assertEqual(human_bytes(64 * 1024 * 1024), "64.0 MB")

    def test_integrity_is_only_green_when_nothing_is_damaged(self):
        text, tone = integrity_line("intact")
        self.assertEqual(text, "intact")
        text, tone_empty = integrity_line([])
        self.assertEqual(text, "intact")
        self.assertEqual(tone, tone_empty)
        text, damaged = integrity_line([{"uid": "a"}, {"uid": "b"}])
        self.assertEqual(text, "2 damaged")
        self.assertNotEqual(damaged, tone)

    def test_model_counts_says_none_yet_rather_than_nothing(self):
        self.assertEqual(model_counts({}), "none yet")
        self.assertEqual(model_counts(None), "none yet")
        line = model_counts({"whisper:base": 106, "whisper:large-v3": 9})
        self.assertTrue(line.startswith("whisper:base ×106"))
        self.assertIn("large-v3 ×9", line)

    def test_an_empty_store_reports_empty_not_healthy(self):
        headline, chips = product_facts("raw_audio", {"clips": 0, "bytes": 0, "integrity": []})
        self.assertEqual(headline, "0 B")
        self.assertIn(("0 clips", chips[0][1]), [(c[0], c[1]) for c in chips])

    def test_semantics_headline_counts_the_stale(self):
        headline, _chips = product_facts("derived_semantics", {"revisions": 141, "stale": ["3", "9"]})
        self.assertEqual(headline, "2 stale")
        headline, _chips = product_facts("derived_semantics", {"revisions": 141, "stale": []})
        self.assertEqual(headline, "current")

    def test_transcript_headline_is_versions_not_takes(self):
        headline, chips = product_facts(
            "transcript",
            {"takes": 128, "versions": 141, "transcription_models": {"whisper:base": 128}},
        )
        self.assertEqual(headline, "141 v")
        self.assertEqual(chips[0][0], "128 takes")

    def test_prompt_line_names_the_file_when_there_is_one(self):
        self.assertEqual(prompt_source_line({}, 8), "builtin · 8 prompts")
        self.assertEqual(prompt_source_line({"prompt_file": ""}, 8), "builtin · 8 prompts")
        self.assertEqual(prompt_source_line({"prompt_file": r"C:\p.md"}, 8), r"C:\p.md")

    def test_kinds_and_models_come_off_disk(self):
        kinds = load_kinds()
        self.assertIn("daily", kinds)
        self.assertIn("dump", kinds)
        models = load_models()
        self.assertTrue(models.get("whisper"))
        self.assertTrue(models.get("chat"))

    def test_missing_prototypes_file_is_empty_not_a_crash(self):
        with tempfile.TemporaryDirectory() as td:
            gone = Path(td) / "no-such.json"
            self.assertEqual(load_kinds(gone), [])
            self.assertEqual(load_models(gone), {})

    def test_kind_counts_ignores_takes_with_no_kind(self):
        rows = [{"kind": "daily"}, {"kind": "daily"}, {"kind": ""}, {}]
        self.assertEqual(kind_counts(rows), {"daily": 2})


class TestHandWindow(unittest.TestCase):
    def _skip_without_display(self):
        import tkinter as tk

        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError:
            self.skipTest("no display")

    def test_one_window_holds_all_three_cards(self):
        self._skip_without_display()
        from clip_hand import Hand
        from clip_store import append

        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "journal"
            folder.mkdir()
            append(folder, text="one take in the hand")
            os.environ["SESEFUS_CLIP_UI_STATE"] = str(Path(td) / "clip-ui.json")
            hand = Hand(folder)
            try:
                hand.root.update_idletasks()
                # lazily built: only the card you have looked at exists
                self.assertEqual(hand.active, "record")
                self.assertEqual(list(hand.cards), ["record"])

                hand.show("controls")
                hand.root.update_idletasks()
                self.assertEqual(hand.active, "controls")
                self.assertIn("controls", hand.cards)

                # and it is one window, not three
                tops = [w for w in hand.root.winfo_children() if w.winfo_class() == "Toplevel"]
                self.assertEqual(tops, [])

                # the hand's flip turns the card that is showing, and only it
                controls = hand.cards["controls"]
                self.assertFalse(controls._face_is_back)
                controls.flip(animate=False)
                hand.root.update_idletasks()
                self.assertTrue(controls._face_is_back)
                self.assertIn("prompt-out", controls.mast.cget("text"))
                self.assertFalse(hand.cards["record"]._face_is_back)

                hand.show("alarm")
                hand.root.update_idletasks()
                self.assertEqual(sorted(hand.cards), ["alarm", "controls", "record"])
            finally:
                hand.on_close()

    def test_close_stops_every_card_it_built(self):
        self._skip_without_display()
        from clip_hand import Hand

        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "journal"
            folder.mkdir()
            os.environ["SESEFUS_CLIP_UI_STATE"] = str(Path(td) / "clip-ui.json")
            hand = Hand(folder)
            hand.show("alarm")
            hand.root.update_idletasks()
            built = list(hand.cards.values())
            hand.on_close()
            for card in built:
                self.assertTrue(card._closing, type(card).__name__)


class TestCardsStillOpenAlone(unittest.TestCase):
    def test_a_card_with_no_master_still_owns_its_window(self):
        import tkinter as tk

        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError:
            self.skipTest("no display")
        from clip_controls import ControlsCard

        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "journal"
            folder.mkdir()
            solo = ControlsCard(folder)
            try:
                self.assertTrue(solo.owns_root)
                self.assertEqual(solo.root.winfo_class(), "Tk")
            finally:
                solo.shutdown()
                solo.root.destroy()


if __name__ == "__main__":
    unittest.main()
