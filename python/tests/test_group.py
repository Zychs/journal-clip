#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from clip_group import (  # noqa: E402
    group_day,
    group_domain,
    group_intent,
    group_interval,
    group_magnitude,
    group_rows,
    probe_gap_cut,
    probe_length_cuts,
)


def _row(i: str, date: str, time: str, text: str, kind: str = "dump") -> dict[str, str]:
    return {"id": i, "date": date, "time": time, "text": text, "kind": kind}


class TestGroup(unittest.TestCase):
    def test_day_groups_by_date(self):
        rows = [
            _row("1", "2026-08-20", "09:00:00", "a"),
            _row("2", "2026-08-21", "09:00:00", "b"),
            _row("3", "2026-08-21", "10:00:00", "c"),
        ]
        g = group_day(rows)
        self.assertEqual([x["key"] for x in g], ["2026-08-20", "2026-08-21"])
        self.assertEqual(g[1]["n"], 2)

    def test_interval_probes_local_gap(self):
        rows = [
            _row("1", "2026-08-21", "05:11:00", "one"),
            _row("2", "2026-08-21", "05:12:00", "two"),
            _row("3", "2026-08-21", "09:40:00", "later"),
        ]
        g = group_interval(rows)
        self.assertGreaterEqual(len(g), 2)
        self.assertEqual(sum(x["n"] for x in g), 3)

    def test_gap_cut_uses_this_set(self):
        self.assertGreaterEqual(probe_gap_cut([60, 70, 80, 10000]), 180)
        self.assertEqual(probe_gap_cut([]), 15 * 60)

    def test_magnitude_cuts_from_local_lengths(self):
        cuts = probe_length_cuts([10, 12, 11, 200, 210, 400])
        self.assertTrue(cuts)
        rows = [
            _row("1", "2026-08-21", "09:00:00", "x" * 10),
            _row("2", "2026-08-21", "09:01:00", "y" * 200),
        ]
        g = group_magnitude(rows)
        self.assertGreaterEqual(len(g), 1)
        self.assertEqual(sum(x["n"] for x in g), 2)

    def test_domain_uses_kind_when_split(self):
        rows = [
            _row("1", "2026-08-21", "09:00:00", "hello", kind="dump"),
            _row("2", "2026-08-21", "09:01:00", "hello", kind="daily"),
        ]
        g = group_domain(rows)
        keys = {x["key"] for x in g}
        self.assertEqual(keys, {"dump", "daily"})

    def test_intent_splits_on_cues(self):
        rows = [
            _row("1", "2026-08-21", "09:00:00", "waveform audio timer"),
            _row("2", "2026-08-21", "09:01:00", "grocery list milk"),
        ]
        g = group_intent(rows, cues="waveform timer tape")
        keys = [x["key"] for x in g]
        self.assertIn("on-goal", keys)
        on = next(x for x in g if x["key"] == "on-goal")
        self.assertEqual(on["rows"][0]["id"], "1")

    def test_period_abbrev_routes(self):
        rows = [_row("1", "2026-08-21", "09:00:00", "hello")]
        self.assertEqual(group_rows(rows, ".d")[0]["key"], "2026-08-21")
        self.assertEqual(sum(x["n"] for x in group_rows(rows, ".m")), 1)


if __name__ == "__main__":
    unittest.main()
