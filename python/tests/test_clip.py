#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from clip_config import (  # noqa: E402
    cmd_change_dir,
    cmd_change_prompt,
    load_config,
    resolve_system_prompt,
)
from clip_heavy import cosine, load_prototypes, pick_kind, run  # noqa: E402


def _one_hot(kind_id: str, kinds: list[dict]) -> list[float]:
    ids = [str(k["id"]) for k in kinds]
    vec = [0.0] * len(ids)
    if kind_id in ids:
        vec[ids.index(kind_id)] = 1.0
    else:
        vec[ids.index("dump")] = 1.0
    return vec


class TestClip(unittest.TestCase):
    def test_prototype_count(self):
        spec = load_prototypes()
        n = len(spec["kinds"])
        self.assertGreaterEqual(n, 1)
        self.assertLessEqual(n, 10)

    def test_cosine_identical(self):
        v = [1.0, 0.0, 3.0]
        self.assertAlmostEqual(cosine(v, v), 1.0, places=6)

    def test_cosine_orthogonal(self):
        self.assertAlmostEqual(cosine([1.0, 0.0], [0.0, 1.0]), 0.0, places=6)

    def test_pick_dream(self):
        spec = load_prototypes()
        kinds = spec["kinds"]

        def embed_fn(texts: list[str]) -> list[list[float]]:
            out = []
            for t in texts:
                low = t.lower()
                if "dream" in low or "nightmare" in low or "hypnagogic" in low:
                    out.append(_one_hot("dream", kinds))
                elif t == texts[0]:
                    out.append(_one_hot("dream", kinds))
                else:
                    kid = "dump"
                    for k in kinds:
                        if str(k.get("prototype") or "") == t:
                            kid = str(k["id"])
                            break
                    out.append(_one_hot(kid, kinds))
            return out

        kind, score = pick_kind("I dreamed I was flying last night", kinds, embed_fn)
        self.assertEqual(kind, "dream")
        self.assertGreater(score, 0.9)

    def test_low_score_falls_to_dump(self):
        spec = load_prototypes()
        kinds = spec["kinds"]

        def embed_fn(texts: list[str]) -> list[list[float]]:
            return [[0.01] * 4 for _ in texts]

        kind, score = pick_kind("xyzzy", kinds, embed_fn, min_score=0.18)
        self.assertEqual(kind, "dump")
        self.assertLess(score, 0.18)

    def test_run_no_llm_technical(self):
        spec = load_prototypes()
        kinds = spec["kinds"]

        def embed_fn(texts: list[str]) -> list[list[float]]:
            out = []
            for i, t in enumerate(texts):
                if i == 0:
                    out.append(_one_hot("technical", kinds))
                else:
                    kid = str(kinds[i - 1]["id"])
                    out.append(_one_hot(kid, kinds))
            return out

        result = run(
            wav=None,
            text="zig build failed in journal-clip with error code 1",
            proto_path=HERE / "prototypes.json",
            no_llm=True,
            embed_fn=embed_fn,
            config={},
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["kind"], "technical")
        self.assertEqual(result["embed_on"], "text")
        self.assertIn("## gist", result["structured"])
        self.assertEqual(result["dest_rel"], "takes.jsonl")

    def test_dest_shape(self):
        # Zig writes {root}/{kind}/{YYYY-MM-DD}/{HHmmss}.md — python only names kind.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            kind = "gratitude"
            day = "2026-08-21"
            dest_dir = root / kind / day
            dest_dir.mkdir(parents=True)
            path = dest_dir / "120000.md"
            path.write_text("# ok\n", encoding="utf-8")
            self.assertTrue(path.is_file())
            self.assertEqual(path.parent.name, day)
            self.assertEqual(path.parent.parent.name, kind)

    def test_change_dir_and_prompt(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            cfg_path = td / "clip-config.json"
            os.environ["SESEFUS_CLIP_CONFIG"] = str(cfg_path)
            self.addCleanup(lambda: os.environ.pop("SESEFUS_CLIP_CONFIG", None))
            out = td / "journal-out"
            msg = cmd_change_dir(str(out))
            self.assertIn(str(out.resolve()), msg)
            cfg = load_config()
            self.assertEqual(Path(cfg["out_dir"]), out.resolve())

            prompt = td / "structure.md"
            prompt.write_text("You are a clerk.\n## only-this\n", encoding="utf-8")
            msg = cmd_change_prompt(str(prompt), kind=None, clear=False)
            self.assertIn("prompt_file=", msg)
            text, src = resolve_system_prompt("dump", "builtin", load_config())
            self.assertIn("## only-this", text)
            self.assertTrue(src.startswith("prompt_file:"))

            kind_p = td / "daily.md"
            kind_p.write_text("DAILY ONLY", encoding="utf-8")
            cmd_change_prompt(str(kind_p), kind="daily", clear=False)
            text, src = resolve_system_prompt("daily", "builtin", load_config())
            self.assertEqual(text, "DAILY ONLY")
            text_dump, _ = resolve_system_prompt("dump", "builtin", load_config())
            self.assertIn("## only-this", text_dump)

            cmd_change_prompt(None, kind=None, clear=True)
            text, src = resolve_system_prompt("daily", "builtin", load_config())
            self.assertEqual(text, "builtin")
            self.assertEqual(src, "builtin")


if __name__ == "__main__":
    unittest.main()
