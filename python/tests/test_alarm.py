#!/usr/bin/env python3
"""Contract tests for the alarm store and timekeeper.

No real clock waiting. No real hop. No port. Every test drives an explicit
`now` and an explicit store path so nothing touches %USERPROFILE%\\.sesefus.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import clip_alarm as A  # noqa: E402


NOW = datetime(2026, 8, 29, 9, 0, 0)


@pytest.fixture()
def store(tmp_path, monkeypatch):
    p = tmp_path / "clip-alarms.jsonl"
    monkeypatch.setenv("SESEFUS_CLIP_ALARMS", str(p))
    return p


def mk(store, **kw):
    kw.setdefault("alarm_id", "morning")
    kw.setdefault("when", "07:00")
    kw.setdefault("now", NOW)
    return A.add(**kw)


# ------------------------------------------------------------- when parsing


def test_clock_in_the_future_is_today():
    assert A.parse_when("14:30", NOW) == NOW.replace(hour=14, minute=30)


def test_clock_already_passed_rolls_to_tomorrow():
    got = A.parse_when("07:00", NOW)
    assert got == (NOW + timedelta(days=1)).replace(hour=7, minute=0)


def test_offset_forms():
    assert A.parse_when("+25m", NOW) == NOW + timedelta(minutes=25)
    assert A.parse_when("+2h", NOW) == NOW + timedelta(hours=2)
    assert A.parse_when("+1d", NOW) == NOW + timedelta(days=1)
    assert A.parse_when("+30s", NOW) == NOW + timedelta(seconds=30)


def test_rfc3339_is_accepted():
    assert A.parse_when("2026-09-01T06:15:00", NOW) == datetime(2026, 9, 1, 6, 15)


def test_garbage_when_refuses():
    for bad in ("", "soon", "25:00", "+0m", "tuesday"):
        with pytest.raises(A.AlarmError):
            A.parse_when(bad, NOW)


def test_every_parsing():
    assert A.parse_every("1d") == 86400
    assert A.parse_every("90m") == 5400
    assert A.parse_every("") == 0
    with pytest.raises(A.AlarmError):
        A.parse_every("often")


# ------------------------------------------------------------- add


def test_add_writes_one_line(store):
    mk(store, title="wake journal")
    lines = store.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["id"] == "morning"
    assert obj["state"] == A.ARMED
    assert obj["do"] == A.DO_HOP


def test_add_defaults_to_hop(store):
    assert mk(store)["do"] == A.DO_HOP


def test_interval_is_not_part_of_create(store):
    assert mk(store)["every"] == 0


def test_duplicate_id_refuses(store):
    mk(store)
    with pytest.raises(A.AlarmError):
        mk(store)
    assert len(store.read_text(encoding="utf-8").splitlines()) == 1


def test_bad_slug_refuses(store):
    for bad in ("", "Morning Bell", "-lead", "has/slash"):
        with pytest.raises(A.AlarmError):
            mk(store, alarm_id=bad)


def test_bad_action_refuses(store):
    with pytest.raises(A.AlarmError):
        mk(store, action="explode")


# ------------------------------------------------------------- interval


def test_interval_promotes_a_one_shot(store):
    mk(store)
    row = A.set_interval("morning", "1d", now=NOW)
    assert row["every"] == 86400


def test_interval_can_be_cleared(store):
    mk(store)
    A.set_interval("morning", "1d", now=NOW)
    assert A.set_interval("morning", "", now=NOW)["every"] == 0


# ------------------------------------------------------------- search


def test_exact_id_wins_over_substring(store):
    mk(store, alarm_id="wake")
    mk(store, alarm_id="wake-later")
    assert [r["id"] for r in A.find("wake")] == ["wake"]


def test_leading_slash_forces_query(store):
    mk(store, alarm_id="wake")
    mk(store, alarm_id="wake-later")
    assert {r["id"] for r in A.find("/wake")} == {"wake", "wake-later"}


def test_search_covers_title_and_note(store):
    mk(store, alarm_id="a", title="morning plate")
    mk(store, alarm_id="b", note="stretch the back")
    assert [r["id"] for r in A.find("/plate")] == ["a"]
    assert [r["id"] for r in A.find("/stretch")] == ["b"]


def test_find_one_refuses_on_zero(store):
    with pytest.raises(A.AlarmError):
        A.find_one("nothing")


def test_find_one_refuses_on_many(store):
    mk(store, alarm_id="wake")
    mk(store, alarm_id="wake-later")
    with pytest.raises(A.AlarmError) as exc:
        A.find_one("/wake")
    assert "matches 2" in str(exc.value)


# ------------------------------------------------------------- edit


def test_edit_preserves_id(store):
    mk(store)
    assert A.edit("morning", title="morning plate", now=NOW)["id"] == "morning"


def test_edit_when_moves_next_due(store):
    mk(store)
    row = A.edit("morning", when="+10m", now=NOW)
    assert row["next_due"] == A._iso(NOW + timedelta(minutes=10))


def test_pause_keeps_the_row(store):
    mk(store)
    assert A.edit("morning", state=A.PAUSED, now=NOW)["state"] == A.PAUSED
    assert len(A.read_all()) == 1


def test_archive_does_not_delete(store):
    mk(store)
    A.edit("morning", state=A.ARCHIVED, now=NOW)
    assert len(A.read_all()) == 1


def test_arm_restores_a_due(store):
    mk(store)
    A.edit("morning", state=A.PAUSED, now=NOW)
    row = A.edit("morning", state=A.ARMED, now=NOW)
    assert row["state"] == A.ARMED and row["next_due"]


# ------------------------------------------------------------- firing


def test_only_overdue_armed_rows_fire(store):
    mk(store, alarm_id="soon", when="+1m", action=A.DO_CUE)
    mk(store, alarm_id="later", when="+9h", action=A.DO_CUE)
    fired = A.tick(NOW + timedelta(minutes=2))
    assert [r["id"] for r in fired] == ["soon"]


def test_paused_rows_never_fire(store):
    mk(store, alarm_id="soon", when="+1m", action=A.DO_CUE)
    A.edit("soon", state=A.PAUSED, now=NOW)
    assert A.tick(NOW + timedelta(minutes=5)) == []


def test_one_shot_disarms_after_firing(store):
    mk(store, alarm_id="soon", when="+1m", action=A.DO_CUE)
    fired = A.tick(NOW + timedelta(minutes=2))
    assert fired[0]["state"] == A.PAUSED
    assert fired[0]["next_due"] == ""
    assert fired[0]["fires"] == 1


def test_repeater_advances_past_now(store):
    mk(store, alarm_id="tick", when="+1m", action=A.DO_CUE)
    A.set_interval("tick", "30m", now=NOW)
    fired = A.tick(NOW + timedelta(minutes=70))
    nxt = A._from_iso(fired[0]["next_due"])
    assert nxt > NOW + timedelta(minutes=70)
    assert fired[0]["state"] == A.ARMED


def test_missed_repeater_fires_once_not_once_per_slot(store):
    """Laptop asleep four hours. One catch-up fire, not eight."""
    mk(store, alarm_id="tick", when="+1m", action=A.DO_CUE)
    A.set_interval("tick", "30m", now=NOW)
    fired = A.tick(NOW + timedelta(hours=4))
    assert len(fired) == 1
    assert fired[0]["fires"] == 1


def test_overdue_fires_on_wake(store):
    mk(store, alarm_id="stale", when="+1m", action=A.DO_CUE)
    assert len(A.tick(NOW + timedelta(days=3))) == 1


def test_next_due_is_never_invented(store):
    assert A.next_due() is None
    mk(store, alarm_id="a", when="+5m")
    assert A.next_due()["id"] == "a"


def test_next_due_picks_the_soonest(store):
    mk(store, alarm_id="far", when="+9h")
    mk(store, alarm_id="near", when="+5m")
    assert A.next_due()["id"] == "near"


def test_hop_is_not_invoked_for_cue(store, monkeypatch):
    called = []
    monkeypatch.setattr(A, "hop", lambda row: called.append(row) or True)
    mk(store, alarm_id="quiet", when="+1m", action=A.DO_CUE)
    A.tick(NOW + timedelta(minutes=2))
    assert called == []


def test_hop_is_invoked_for_hop(store, monkeypatch):
    called = []
    monkeypatch.setattr(A, "hop", lambda row: called.append(row["id"]) or True)
    mk(store, alarm_id="loud", when="+1m", action=A.DO_HOP)
    A.tick(NOW + timedelta(minutes=2))
    assert called == ["loud"]


# ------------------------------------------------------------- durability


def test_torn_final_line_does_not_lose_history(store):
    mk(store, alarm_id="one", when="+1h")
    mk(store, alarm_id="two", when="+2h")
    with store.open("a", encoding="utf-8") as f:
        f.write('{"id": "three", "when": "+3h"')  # no newline, no close brace
    rows = A.read_all()
    assert [r["id"] for r in rows] == ["one", "two"]


def test_rewrite_is_atomic_and_leaves_no_temp(store):
    mk(store, alarm_id="one", when="+1h")
    A.edit("one", title="patched", now=NOW)
    leftovers = list(store.parent.glob(".alarms-*.tmp"))
    assert leftovers == []
    assert A.read_all()[0]["title"] == "patched"


def test_store_stays_outside_the_repo(store):
    """The tape never lands next to the source."""
    repo = A.repo_root()
    assert not str(A.alarms_path()).startswith(str(repo))


def test_no_port_anywhere_in_the_module():
    """The card says file + process. Prove no socket ever gets imported."""
    src = Path(A.__file__).read_text(encoding="utf-8")
    assert "import socket" not in src
    assert "socketserver" not in src
    assert "bind(" not in src


def test_append_writes_complete_lines_only(store):
    mk(store, alarm_id="one", when="+1h")
    mk(store, alarm_id="two", when="+2h")
    body = store.read_text(encoding="utf-8")
    assert body.endswith("\n")
    for line in body.splitlines():
        json.loads(line)
