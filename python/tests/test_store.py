#!/usr/bin/env python3
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from clip_store import (  # noqa: E402
    TAPE_NAME,
    append,
    harvest,
    import_from_csv,
    list_takes,
    next_id,
    purge,
    update_text,
)


class TestStore(unittest.TestCase):
    def test_ids_monotonic_and_empty_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = append(root, text="first take", kind="dump")
            b = append(root, text="second take", kind="daily")
            self.assertEqual(a["id"], "1")
            self.assertEqual(b["id"], "2")
            self.assertEqual(next_id(root), 3)
            with self.assertRaises(ValueError):
                append(root, text="  ")
            tape = (root / TAPE_NAME).read_text(encoding="utf-8")
            self.assertIn("first take", tape)
            self.assertIn("second take", tape)
            self.assertFalse((root / "transcriptions.csv").is_file())
            self.assertFalse((root / "ledger.csv").is_file())

    def test_append_survives_markdown_clobber(self):
        """Zig used to overwrite takes.jsonl as markdown. New lines must still land."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tape = root / TAPE_NAME
            tape.write_text(
                "---\nkind: dump\nclip: journal-clip\n---\n\nold wreckage\n",
                encoding="utf-8",
            )
            row = append(root, text="widget take for test-write")
            self.assertEqual(row["id"], "1")
            body = tape.read_text(encoding="utf-8")
            self.assertIn("widget take for test-write", body)
            texts = [t["text"] for t in list_takes(root)]
            self.assertEqual(texts, ["widget take for test-write"])

    def test_harvest_skips_empty_purge_keeps_csv(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            good = root / "journal" / "20260811-210712"
            good.mkdir(parents=True)
            (good / "NOTE.txt").write_text("smoke freeform journal\n", encoding="utf-8")
            empty = root / "journal" / "20260812-142752"
            empty.mkdir(parents=True)
            (empty / "meta.json").write_text('{"note":""}', encoding="utf-8")
            junk = root / "readme-skip.txt"
            junk.write_text("Dogfood capture inbox for durable land.\n", encoding="utf-8")
            rows = harvest(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["id"], "1")
            gone = purge(root)
            self.assertTrue(any("journal" in g for g in gone))
            self.assertTrue((root / TAPE_NAME).is_file())
            self.assertFalse((root / "journal").exists())

    def test_update_text_rewrites_tape(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            append(root, text="wrong word here", kind="dump")
            row = update_text(root, "1", "right word here")
            self.assertEqual(row["text"], "right word here")
            self.assertEqual(row["structured"], "right word here")
            self.assertEqual(list_takes(root)[0]["text"], "right word here")
            tape = (root / TAPE_NAME).read_text(encoding="utf-8")
            self.assertIn("right word here", tape)
            self.assertNotIn("wrong word here", tape)
            with self.assertRaises(ValueError):
                update_text(root, "1", "  ")
            with self.assertRaises(ValueError):
                update_text(root, "99", "nope")

    def test_import_human_csv_when_ledger_misses_a_row(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "ledger.csv").write_text(
                "id,date,time,kind,score,text,structured,source,schema,extra\n"
                "1,2026-08-21,09:00:00,dump,0.0,only in ledger,only in ledger,clip,1,{}\n",
                encoding="utf-8",
            )
            (root / "transcriptions.csv").write_text(
                "date,text\n"
                "2026-08-21,only in ledger\n"
                "2026-08-21,spoken only on the human csv\n",
                encoding="utf-8",
            )
            rows = import_from_csv(root)
            texts = [r["text"] for r in rows]
            self.assertEqual(texts, ["only in ledger", "spoken only on the human csv"])
            got = list_takes(root)
            self.assertEqual([r["text"] for r in got], texts)
            self.assertTrue((root / TAPE_NAME).is_file())
            self.assertTrue((root / "ledger.csv").is_file())
            self.assertTrue((root / "transcriptions.csv").is_file())


if __name__ == "__main__":
    unittest.main()
