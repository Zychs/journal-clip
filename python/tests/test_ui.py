#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from clip_ui import (  # noqa: E402
    CLIP_BAT,
    is_silent,
    load_recent_dir,
    parse_device_list,
    parse_seconds,
    peak_gain,
    pick_default_device,
    record_clicks_to_seconds,
    remaining_whole_seconds,
    rows_that_fit,
    save_recent_dir,
    short_ledger_line,
    visible_ledger_rows,
    write_session_config,
)


class TestClipUi(unittest.TestCase):
    def test_clip_bat_sits_next_to_ui(self):
        self.assertTrue(CLIP_BAT.is_file(), CLIP_BAT)

    def test_parse_device_list(self):
        text = (
            "[0] Microphone (Maono AU-PM421)\n"
            "[1] Stereo Mix (Realtek)  (current)\n"
            "current_index=1\n"
        )
        devices, current = parse_device_list(text)
        self.assertEqual(current, 1)
        self.assertEqual(devices[0], (0, "Microphone (Maono AU-PM421)"))
        self.assertEqual(devices[1], (1, "Stereo Mix (Realtek)"))

    def test_parse_empty_falls_to_default(self):
        devices, current = parse_device_list("")
        self.assertEqual(devices, [(0, "default")])
        self.assertEqual(current, 0)

    def test_session_config_does_not_need_global_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.json"
            write_session_config(
                path,
                out_dir=r"C:\Users\bardw\test-write",
                input_index=2,
                base={"prompt_file": "C:\\p.md", "prompt_overrides": {"daily": "d.md"}},
            )
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["out_dir"], r"C:\Users\bardw\test-write")
            self.assertEqual(data["input_index"], 2)
            self.assertEqual(data["prompt_file"], "C:\\p.md")
            self.assertEqual(data["prompt_overrides"]["daily"], "d.md")

    def test_pick_default_prefers_maono_usb(self):
        devices = [
            (0, "Microphone (Realtek High Definition Audio)"),
            (1, "Stereo Mix (Realtek)"),
            (2, "Microphone (Maono PD200W Mic USB)"),
            (3, "Microphone (USB Audio Device)"),
        ]
        self.assertEqual(pick_default_device(devices, current=0), 2)

    def test_pick_default_maono_without_usb_word(self):
        devices = [
            (0, "Microphone Array"),
            (1, "Microphone (Maono Wireless Mic RX)"),
        ]
        self.assertEqual(pick_default_device(devices), 1)

    def test_parse_seconds_default_and_override(self):
        self.assertEqual(parse_seconds(""), 30)
        self.assertEqual(parse_seconds("30"), 30)
        self.assertEqual(parse_seconds(" 30 "), 30)
        self.assertEqual(parse_seconds("nope"), 30)
        self.assertEqual(parse_seconds("0"), 30)
        self.assertEqual(parse_seconds("90"), 90)
        self.assertEqual(parse_seconds("999"), 120)

    def test_record_clicks_cap_at_120s(self):
        self.assertEqual(record_clicks_to_seconds(1), 30)
        self.assertEqual(record_clicks_to_seconds(2), 60)
        self.assertEqual(record_clicks_to_seconds(3), 90)
        self.assertEqual(record_clicks_to_seconds(4), 120)
        self.assertEqual(record_clicks_to_seconds(9), 120)
        self.assertEqual(record_clicks_to_seconds(0), 30)

    def test_remaining_whole_seconds_no_decimal(self):
        self.assertEqual(remaining_whole_seconds(100.0, 30, 100.0), 30)
        self.assertEqual(remaining_whole_seconds(100.0, 30, 100.9), 29)
        self.assertEqual(remaining_whole_seconds(100.0, 30, 129.9), 0)
        self.assertEqual(remaining_whole_seconds(100.0, 30, 140.0), 0)

    def test_peak_gain_strips_negative_dc_bias(self):
        import struct

        n = 200
        bias = -8000
        quiet = struct.pack("<" + "h" * n, *([bias] * n))
        self.assertLess(peak_gain(quiet), 0.01)
        self.assertGreater(abs(bias) / 32767.0, 0.2)
        ac = 12000
        samples = [bias + (ac if i % 2 == 0 else -ac) for i in range(n)]
        loud = struct.pack("<" + "h" * n, *samples)
        self.assertAlmostEqual(peak_gain(loud), ac / 32767.0, places=2)

    def test_recent_dir_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "journal"
            folder.mkdir()
            state = Path(td) / "clip-ui.json"
            save_recent_dir(folder, state)
            got = load_recent_dir(state)
            self.assertEqual(got, folder.resolve())
            missing = Path(td) / "gone.json"
            missing.write_text('{"last_dir": "C:\\\\no-such-clip-dir-xyz"}', encoding="utf-8")
            self.assertIsNone(load_recent_dir(missing))

    def test_silence_detect(self):
        self.assertTrue(is_silent(b""))
        quiet = b"\x00\x00" * 200
        self.assertTrue(is_silent(quiet))
        loud = b"\x00\x00" * 50 + b"\x00\x40" + b"\x00\x00" * 50  # 16384
        self.assertFalse(is_silent(loud))

    def test_rows_that_fit_does_not_invent_font(self):
        self.assertEqual(rows_that_fit(120, 12, pad=0), 10)
        self.assertEqual(rows_that_fit(124, 12, pad=4), 10)
        self.assertEqual(rows_that_fit(11, 12, pad=0), 0)
        self.assertEqual(rows_that_fit(200, 0), 0)

    def test_visible_ledger_keeps_newest_that_fit(self):
        rows = [{"id": str(i)} for i in range(1, 9)]
        got = visible_ledger_rows(rows, 3)
        self.assertEqual([r["id"] for r in got], ["6", "7", "8"])
        self.assertEqual(visible_ledger_rows(rows, 20), rows)
        self.assertEqual(visible_ledger_rows(rows, 0), [])

    def test_short_ledger_line_is_one_line(self):
        line = short_ledger_line(
            {"id": "12", "time": "09:38:11", "kind": "dump", "text": "hello\nworld  there"},
            max_chars=28,
        )
        self.assertNotIn("\n", line)
        self.assertTrue(line.startswith("09:38  "))
        self.assertNotIn("dump", line)
        self.assertLessEqual(len(line), 28)

    def test_clip_ui_constructs_tape_tree(self):
        import os
        import tkinter as tk

        from clip_store import append
        from clip_ui import ClipUi

        try:
            probe = tk.Tk()
            probe.withdraw()
            probe.destroy()
        except tk.TclError:
            self.skipTest("no display")
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / "journal"
            folder.mkdir()
            append(folder, text="hello tape")
            os.environ["SESEFUS_CLIP_UI_STATE"] = str(Path(td) / "clip-ui.json")
            ui = ClipUi(folder)
            try:
                ui.root.update_idletasks()
                self.assertTrue(ui.tree.winfo_exists())
                self.assertEqual(ui.count_label.cget("text"), "1")
                ui.set_profile(".i")
                ui.root.update_idletasks()
                self.assertEqual(ui._profile, ".i")
            finally:
                ui.root.destroy()


if __name__ == "__main__":
    unittest.main()
