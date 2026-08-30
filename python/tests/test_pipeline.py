#!/usr/bin/env python3
"""The three data products stay three data products.

Each test here pins one of the three preservation rules:

  raw audio          never overwrite
  transcript         version alongside the transcription model
  derived semantics  revisable model output, not ground truth
"""
from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
import wave
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import clip_audio  # noqa: E402
import clip_semantics  # noqa: E402
import clip_store  # noqa: E402
import clip_transcript  # noqa: E402


def make_wav(path: Path, *, seconds: float = 0.25, value: int = 1000) -> Path:
    """A tiny real PCM wav so the archive can probe its shape."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16000
    n = int(rate * seconds)
    frames = b"".join(int(value).to_bytes(2, "little", signed=True) for _ in range(n))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(frames)
    return path


class TestSeparation(unittest.TestCase):
    def test_one_take_lands_in_three_places(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            row = clip_store.append(
                root,
                text="the mic was on",
                kind="daily",
                score=0.42,
                structured="## gist\nmic",
                engine="whisper",
                model="base",
                embed_model="nomic-embed-text",
                chat_model="qwen2.5:7b-instruct",
            )
            self.assertEqual(row["id"], "1")

            # system 2 holds the words, and says which model produced them
            tv = clip_transcript.latest(root, "1")
            self.assertEqual(tv["text"], "the mic was on")
            self.assertEqual(tv["version"], 1)
            self.assertEqual(tv["model_id"], "whisper:base")

            # system 3 holds the reading of them, and disclaims ground truth
            sem = clip_semantics.latest(root, "1")
            self.assertEqual(sem["kind"], "daily")
            self.assertEqual(sem["revision"], 1)
            self.assertIs(sem["ground_truth"], False)
            self.assertEqual(sem["derived_from_transcript_version"], 1)

            # the words are not duplicated into system 3, nor the tags into 2
            self.assertNotIn("text", sem)
            self.assertNotIn("kind", tv)

    def test_tape_is_a_projection_and_rebuilds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.append(root, text="first", kind="dump")
            clip_store.append(root, text="second", kind="daily")
            tape = clip_store.tape_path(root)
            before = tape.read_text(encoding="utf-8")

            tape.unlink()
            self.assertFalse(tape.is_file())
            clip_store.project(root)
            self.assertEqual(tape.read_text(encoding="utf-8"), before)

            rows = clip_store.list_takes(root)
            self.assertEqual([r["id"] for r in rows], ["1", "2"])
            extra = json.loads(rows[0]["extra"])
            self.assertEqual(extra["provenance"]["transcript_version"], 1)
            self.assertIs(extra["provenance"]["semantics_ground_truth"], False)

    def test_purge_keeps_all_three_systems(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wav = make_wav(root / "scratch" / "take.wav")
            clip_audio.archive(root, wav, take_id="1")
            clip_store.append(root, text="kept", kind="dump")
            (root / "junk").mkdir()
            (root / "junk" / "x.txt").write_text("junk", encoding="utf-8")

            gone = clip_store.purge(root)
            self.assertTrue(any("junk" in g for g in gone))
            self.assertTrue(clip_transcript.log_path(root).is_file())
            self.assertTrue(clip_semantics.log_path(root).is_file())
            self.assertTrue(clip_audio.manifest_path(root).is_file())
            self.assertEqual(clip_audio.verify(root), [])


class TestRawAudioNeverOverwrites(unittest.TestCase):
    def test_same_bytes_archive_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wav = make_wav(root / "scratch" / "take.wav")
            when = datetime(2026, 8, 30, 14, 0, 0)
            a = clip_audio.archive(root, wav, take_id="1", when=when)
            b = clip_audio.archive(root, wav, take_id="1", when=when)
            self.assertEqual(a["uid"], b["uid"])
            self.assertEqual(a["sha256"], b["sha256"])
            self.assertEqual(len({r["uid"] for r in clip_audio.list_audio(root)}), 1)
            self.assertEqual(a["sample_rate"], 16000)
            self.assertGreater(a["seconds"], 0)

    def test_different_audio_never_shares_a_destination(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            when = datetime(2026, 8, 30, 14, 0, 0)
            a = clip_audio.archive(
                root, make_wav(root / "s" / "a.wav", value=1000), take_id="1", when=when
            )
            b = clip_audio.archive(
                root, make_wav(root / "s" / "b.wav", value=7000), take_id="2", when=when
            )
            # same second, different sound: the content hash keeps them apart
            self.assertNotEqual(a["uid"], b["uid"])
            self.assertNotEqual(a["path"], b["path"])
            self.assertTrue(clip_audio.resolve(root, a).is_file())
            self.assertTrue(clip_audio.resolve(root, b).is_file())

    def test_a_squatted_destination_is_refused_not_clobbered(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wav = make_wav(root / "s" / "take.wav", value=1000)
            when = datetime(2026, 8, 30, 14, 0, 0)
            first = clip_audio.archive(root, wav, take_id="1", when=when)
            dest = clip_audio.resolve(root, first)

            # Something else put foreign bytes exactly where this take lives.
            clip_audio._thaw(dest)
            dest.write_bytes(b"RIFF-not-this-take")
            with self.assertRaises(clip_audio.OverwriteRefused):
                clip_audio.archive(root, wav, take_id="1", when=when)
            # refusing means refusing: the file on disk is left alone
            self.assertEqual(dest.read_bytes(), b"RIFF-not-this-take")

    def test_archived_file_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wav = make_wav(root / "scratch" / "take.wav")
            row = clip_audio.archive(root, wav, take_id="1")
            dest = clip_audio.resolve(root, row)
            self.assertFalse(bool(dest.stat().st_mode & stat.S_IWRITE))

    def test_verify_catches_a_tampered_clip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wav = make_wav(root / "scratch" / "take.wav")
            row = clip_audio.archive(root, wav, take_id="1")
            self.assertEqual(clip_audio.verify(root), [])
            dest = clip_audio.resolve(root, row)
            clip_audio._thaw(dest)
            dest.write_bytes(b"RIFFnot-the-take")
            bad = clip_audio.verify(root)
            self.assertEqual(len(bad), 1)
            self.assertEqual(bad[0]["problem"], "hash-mismatch")


class TestTranscriptVersioning(unittest.TestCase):
    def test_a_better_model_appends_it_does_not_replace(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.append(root, text="i sent a leather", engine="whisper", model="base")
            clip_transcript.append_version(
                root, "1", "i said it later", engine="whisper", model="large-v3"
            )
            hist = clip_transcript.history(root, "1")
            self.assertEqual([r["version"] for r in hist], [1, 2])
            self.assertEqual(hist[0]["text"], "i sent a leather")
            self.assertEqual(hist[0]["model_id"], "whisper:base")
            self.assertEqual(hist[1]["model_id"], "whisper:large-v3")
            self.assertEqual(hist[1]["supersedes"], 1)
            self.assertEqual(clip_transcript.latest(root, "1")["text"], "i said it later")

            clip_store.project(root)
            self.assertEqual(clip_store.list_takes(root)[0]["text"], "i said it later")

    def test_models_used_and_behind_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.append(root, text="one", engine="whisper", model="base")
            clip_store.append(root, text="two", engine="whisper", model="base")
            clip_transcript.append_version(
                root, "2", "two, better", engine="whisper", model="large-v3"
            )
            self.assertEqual(
                clip_transcript.models_used(root),
                {"whisper:base": 1, "whisper:large-v3": 1},
            )
            self.assertEqual(clip_transcript.behind_model(root, "whisper:large-v3"), ["1"])

    def test_a_human_correction_is_not_counted_as_a_transcription_model(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.append(root, text="one", engine="whisper", model="base")
            clip_store.append(root, text="two", engine="whisper", model="base")
            clip_store.update_text(root, "2", "two, corrected")
            self.assertEqual(clip_transcript.models_used(root), {"whisper:base": 1})
            self.assertEqual(
                clip_transcript.producers_used(root), {"whisper": 1, "human": 1}
            )

    def test_human_correction_keeps_the_machine_reading(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.append(root, text="wrong word here", engine="whisper", model="base")
            clip_store.update_text(root, "1", "right word here")

            hist = clip_transcript.history(root, "1")
            self.assertEqual(len(hist), 2)
            self.assertEqual(hist[0]["text"], "wrong word here")
            self.assertEqual(hist[0]["produced_by"], "whisper")
            self.assertEqual(hist[1]["produced_by"], "human")
            # the take still arrived on the clip channel; only the reader changed
            self.assertEqual(hist[0]["source"], "clip")
            self.assertEqual(hist[1]["source"], "clip")

            # the projection shows only the correction...
            tape = clip_store.tape_path(root).read_text(encoding="utf-8")
            self.assertIn("right word here", tape)
            self.assertNotIn("wrong word here", tape)
            # ...but system 2 still has what the model actually heard
            log = clip_transcript.log_path(root).read_text(encoding="utf-8")
            self.assertIn("wrong word here", log)

    def test_a_human_reading_is_not_stale_when_the_model_moves(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.append(root, text="as heard", engine="whisper", model="base")
            clip_store.update_text(root, "1", "as meant")
            self.assertEqual(clip_transcript.behind_model(root, "whisper:large-v3"), [])


class TestSemanticsAreRevisable(unittest.TestCase):
    def test_a_new_reading_supersedes_without_erasing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.append(root, text="a note about sleep", kind="dump", score=0.1)
            clip_semantics.append_revision(
                root,
                "1",
                transcript_version=1,
                kind="dream",
                score=0.88,
                structured="## gist\nsleep",
                tags=["sleep", "rem"],
                chat_model="qwen2.5:7b-instruct",
            )
            hist = clip_semantics.history(root, "1")
            self.assertEqual([r["revision"] for r in hist], [1, 2])
            self.assertEqual(hist[0]["kind"], "dump")
            self.assertEqual(clip_semantics.latest(root, "1")["kind"], "dream")
            self.assertEqual(clip_semantics.latest(root, "1")["tags"], ["sleep", "rem"])

            clip_store.project(root)
            self.assertEqual(clip_store.list_takes(root)[0]["kind"], "dream")

    def test_real_model_output_goes_stale_when_the_transcript_is_corrected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.append(
                root,
                text="wrong word here",
                kind="daily",
                structured="## gist\nan actual 7B summary",
                chat_model="qwen2.5:7b-instruct",
            )
            versions = {"1": 1}
            self.assertEqual(clip_semantics.stale(root, versions), [])

            clip_store.update_text(root, "1", "right word here")
            now = {
                t: int(r["version"]) for t, r in clip_transcript.latest_by_take(root).items()
            }
            self.assertEqual(now, {"1": 2})
            # the summary read the old words, and says so
            self.assertEqual(clip_semantics.stale(root, now), ["1"])
            self.assertEqual(
                clip_semantics.latest(root, "1")["structured"], "## gist\nan actual 7B summary"
            )

    def test_a_bare_mirror_follows_the_correction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.append(root, text="wrong word here", kind="dump")
            row = clip_store.update_text(root, "1", "right word here")
            # nothing was ever interpreted, so nothing goes stale
            self.assertEqual(row["structured"], "right word here")
            now = {
                t: int(r["version"]) for t, r in clip_transcript.latest_by_take(root).items()
            }
            self.assertEqual(clip_semantics.stale(root, now), [])

    def test_discarding_semantics_costs_only_compute(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            wav = make_wav(root / "scratch" / "take.wav")
            audio = clip_audio.archive(root, wav, take_id="1")
            clip_store.append(root, text="still here", kind="daily", audio_uid=audio["uid"])

            self.assertTrue(clip_semantics.discard(root))
            # systems 1 and 2 are untouched
            self.assertEqual(clip_audio.verify(root), [])
            self.assertEqual(clip_transcript.latest(root, "1")["text"], "still here")
            # the projection still composes; the reading falls back to default
            rows = clip_store.list_takes(root)
            self.assertEqual(rows[0]["text"], "still here")
            self.assertEqual(rows[0]["kind"], "dump")


class TestMigration(unittest.TestCase):
    def test_a_legacy_flat_tape_is_split_into_three(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clip_store.tape_path(root).write_text(
                json.dumps(
                    {
                        "id": "1",
                        "date": "2026-08-21",
                        "time": "09:00:00",
                        "kind": "daily",
                        "score": 0.5,
                        "text": "an old take",
                        "structured": "## gist\nold",
                        "source": "clip",
                        "schema": 1,
                        "extra": {},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            rows = clip_store.list_takes(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["text"], "an old take")
            self.assertEqual(rows[0]["kind"], "daily")

            tv = clip_transcript.latest(root, "1")
            self.assertEqual(tv["engine"], clip_transcript.IMPORTED)
            self.assertEqual(tv["date"], "2026-08-21")
            sem = clip_semantics.latest(root, "1")
            self.assertEqual(sem["kind"], "daily")
            self.assertIs(sem["ground_truth"], False)

            # migration happens once, and new ids continue from it
            clip_store.list_takes(root)
            self.assertEqual(len(clip_transcript.all_versions(root)), 1)
            self.assertEqual(clip_store.append(root, text="a new take")["id"], "2")

    def test_csv_twins_still_import(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "transcriptions.csv").write_text(
                "date,text\n2026-08-21,spoken only on the human csv\n", encoding="utf-8"
            )
            rows = clip_store.list_takes(root)
            self.assertEqual([r["text"] for r in rows], ["spoken only on the human csv"])
            self.assertTrue((root / "transcriptions.csv").is_file())
            self.assertTrue(clip_transcript.log_path(root).is_file())


class TestHeavyOrdersTheSystems(unittest.TestCase):
    def _cfg(self, root: Path) -> None:
        import os

        os.environ["SESEFUS_CLIP_CONFIG"] = str(root / "clip-config.json")
        self.addCleanup(lambda: os.environ.pop("SESEFUS_CLIP_CONFIG", None))
        import clip_config

        clip_config.save_config({"out_dir": str(root), "audio_retention": "archive"})

    def test_audio_is_archived_before_whisper_can_fail(self):
        from clip_heavy import run

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._cfg(root)
            wav = make_wav(root / "scratch" / "take.wav")

            def boom(_p: Path, _m: str) -> str:
                raise RuntimeError("whisper exploded")

            with self.assertRaises(RuntimeError):
                run(
                    wav=wav,
                    text=None,
                    proto_path=HERE / "prototypes.json",
                    no_llm=True,
                    transcribe_fn=boom,
                )
            # the take is gone, but the sound of it is not
            clips = clip_audio.list_audio(root)
            self.assertEqual(len(clips), 1)
            self.assertEqual(clip_audio.verify(root), [])

    def test_a_full_take_binds_all_three(self):
        from clip_heavy import run

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._cfg(root)
            wav = make_wav(root / "scratch" / "take.wav")

            def heard(_p: Path, _m: str) -> dict:
                return {
                    "text": "a spoken line",
                    "language": "en",
                    "segments": [
                        {"start": 0.0, "end": 1.2, "speaker": "", "text": "a spoken line"}
                    ],
                }

            def embed(texts: list[str]) -> list[list[float]]:
                return [[1.0, 0.0] for _ in texts]

            result = run(
                wav=wav,
                text=None,
                proto_path=HERE / "prototypes.json",
                no_llm=True,
                transcribe_fn=heard,
                embed_fn=embed,
            )
            self.assertTrue(result["ok"])
            self.assertTrue(result["audio_retained"])
            self.assertIs(result["semantics_ground_truth"], False)
            self.assertEqual(result["transcript_model"], result["whisper_model"])
            self.assertEqual(result["segments"], 1)

            uid = result["audio_uid"]
            self.assertTrue(uid)
            take_id = result["id"]
            # the manifest logged the archive and the later take binding,
            # but that is one clip, not two
            self.assertEqual(len(clip_audio.list_audio(root)), 2)
            self.assertEqual(len(clip_audio.clips(root)), 1)
            self.assertEqual(clip_audio.clips(root)[0]["take_id"], take_id)
            self.assertEqual(clip_audio.by_take(root, take_id)["uid"], uid)
            tv = clip_transcript.latest(root, take_id)
            self.assertEqual(tv["audio_uid"], uid)
            self.assertEqual(tv["language"], "en")
            self.assertEqual(len(tv["segments"]), 1)
            self.assertEqual(tv["engine"], "whisper")
            self.assertIs(clip_semantics.latest(root, take_id)["ground_truth"], False)

    def test_shred_retention_keeps_text_and_no_audio(self):
        import clip_config
        from clip_heavy import run

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._cfg(root)
            clip_config.save_config({"out_dir": str(root), "audio_retention": "shred"})
            wav = make_wav(root / "scratch" / "take.wav")

            result = run(
                wav=wav,
                text=None,
                proto_path=HERE / "prototypes.json",
                no_llm=True,
                transcribe_fn=lambda _p, _m: "text only please",
                embed_fn=lambda ts: [[1.0, 0.0] for _ in ts],
            )
            self.assertTrue(result["ok"])
            self.assertFalse(result["audio_retained"])
            self.assertEqual(clip_audio.list_audio(root), [])
            self.assertEqual(clip_transcript.latest(root, result["id"])["text"], "text only please")


if __name__ == "__main__":
    unittest.main()
