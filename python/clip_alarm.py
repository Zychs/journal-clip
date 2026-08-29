#!/usr/bin/env python3
"""Alarm store and local timekeeper for journal-clip.

Time fires. Then you speak.

Store is a tape: %USERPROFILE%\\.sesefus\\clip-alarms.jsonl (one alarm per line),
or SESEFUS_CLIP_ALARMS. It lives outside the journal and outside the repo.

No port. No socket. No listener. File + process only.
The server sleeps until the next armed `when` and fires overdue rows on wake.

Ids are slugs. Unique. Never silently replaced.
Search is not mutate: an edit query must hit exactly one row.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = 1
STORE_NAME = "clip-alarms.jsonl"
LOCK_NAME = "clip-alarms.lock"

ARMED = "armed"
PAUSED = "paused"
ARCHIVED = "archived"
STATES = {ARMED, PAUSED, ARCHIVED}

DO_HOP = "hop"
DO_CUE = "cue"
DO_NONE = "none"
ACTIONS = {DO_HOP, DO_CUE, DO_NONE}

FIELDS = [
    "id",
    "title",
    "when",
    "every",
    "do",
    "note",
    "state",
    "created",
    "next_due",
    "last_fired",
    "fires",
    "schema",
]

_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_DELTA = re.compile(r"^\+?(\d+)\s*([smhd])$", re.IGNORECASE)
_CLOCK = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")

_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


class AlarmError(Exception):
    """Refusal. Carries a human line and nothing else."""


# ---------------------------------------------------------------- paths


def sesefus_home() -> Path:
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or Path.home())
    return home / ".sesefus"


def alarms_path() -> Path:
    env = os.environ.get("SESEFUS_CLIP_ALARMS")
    if env:
        return Path(env)
    return sesefus_home() / STORE_NAME


def lock_path() -> Path:
    return alarms_path().parent / LOCK_NAME


def repo_root() -> Path:
    """The tree this module lives in. Used to find Clip-ui.bat for a hop."""
    return Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- parsing


def parse_when(text: str, now: datetime | None = None) -> datetime:
    """07:00 · +25m · RFC3339. A bare clock that already passed means tomorrow."""
    raw = (text or "").strip()
    if not raw:
        raise AlarmError("when is required: 07:00 · +25m · RFC3339")
    now = now or datetime.now()

    m = _DELTA.match(raw)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if n <= 0:
            raise AlarmError(f"when {raw!r}: offset must be positive")
        return now + timedelta(seconds=n * _UNIT_SECONDS[unit])

    m = _CLOCK.match(raw)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        ss = int(m.group(3) or 0)
        if hh > 23 or mm > 59 or ss > 59:
            raise AlarmError(f"when {raw!r}: not a clock time")
        cand = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        if cand <= now:
            cand += timedelta(days=1)
        return cand

    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise AlarmError(
            f"when {raw!r}: use 07:00 · +25m · or an RFC3339 stamp"
        ) from None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def parse_every(text: str) -> int:
    """1d · 90m · 30s → seconds. Zero or empty means one-shot."""
    raw = (text or "").strip()
    if not raw:
        return 0
    m = _DELTA.match(raw)
    if not m:
        raise AlarmError(f"every {raw!r}: use 30s · 90m · 2h · 1d")
    n = int(m.group(1))
    if n <= 0:
        raise AlarmError("every: interval must be positive")
    return n * _UNIT_SECONDS[m.group(2).lower()]


def _slug(text: str) -> str:
    s = (text or "").strip().lower()
    if not s:
        raise AlarmError("id is required")
    if not _SLUG_OK.match(s):
        raise AlarmError(
            f"id {s!r}: lowercase letters, digits, dot, dash, underscore; must start alnum"
        )
    return s


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat(sep=" ")


def _from_iso(text: str) -> datetime | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


# ---------------------------------------------------------------- store


def _normalize(obj: dict[str, Any]) -> dict[str, Any]:
    state = str(obj.get("state") or ARMED).strip().lower()
    if state not in STATES:
        state = ARMED
    action = str(obj.get("do") or DO_HOP).strip().lower()
    if action not in ACTIONS:
        action = DO_HOP
    try:
        every = int(obj.get("every") or 0)
    except (TypeError, ValueError):
        every = 0
    try:
        fires = int(obj.get("fires") or 0)
    except (TypeError, ValueError):
        fires = 0
    return {
        "id": str(obj.get("id") or "").strip().lower(),
        "title": str(obj.get("title") or ""),
        "when": str(obj.get("when") or ""),
        "every": max(0, every),
        "do": action,
        "note": str(obj.get("note") or ""),
        "state": state,
        "created": str(obj.get("created") or ""),
        "next_due": str(obj.get("next_due") or ""),
        "last_fired": str(obj.get("last_fired") or ""),
        "fires": max(0, fires),
        "schema": SCHEMA,
    }


def read_all(path: Path | None = None) -> list[dict[str, Any]]:
    """Every row in file order. A torn final line is skipped, never rewritten here."""
    p = path or alarms_path()
    if not p.is_file():
        return []
    try:
        body = p.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in body.splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and str(obj.get("id") or "").strip():
            rows.append(_normalize(obj))
    return rows


def write_all(rows: list[dict[str, Any]], path: Path | None = None) -> Path:
    """Atomic whole-tape rewrite. Temp file in the same dir, then replace."""
    p = path or alarms_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(_normalize(r), ensure_ascii=False) for r in rows]
    body = "\n".join(lines) + ("\n" if lines else "")
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".alarms-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def append_one(row: dict[str, Any], path: Path | None = None) -> Path:
    """Append one complete line, flushed and synced before the handle closes."""
    p = path or alarms_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(_normalize(row), ensure_ascii=False) + "\n"
    with p.open("a", encoding="utf-8", newline="\n") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
    return p


# ---------------------------------------------------------------- search


def find(query: str, rows: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Exact id wins alone. Otherwise substring across id, title, note.

    A leading slash marks an explicit query and skips the exact-id shortcut.
    Archived rows are searchable so they can be armed again.
    """
    rows = read_all() if rows is None else rows
    raw = (query or "").strip()
    if not raw:
        return list(rows)

    forced = raw.startswith("/")
    needle = raw[1:].strip().lower() if forced else raw.lower()
    if not needle:
        return list(rows)

    if not forced:
        exact = [r for r in rows if r["id"] == needle]
        if exact:
            return exact

    return [
        r
        for r in rows
        if needle in r["id"].lower()
        or needle in r["title"].lower()
        or needle in r["note"].lower()
    ]


def find_one(query: str, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Mutation needs exactly one row. 0 or 2+ refuses and names what it saw."""
    rows = read_all() if rows is None else rows
    hits = find(query, rows)
    if not hits:
        raise AlarmError(f"no alarm matches {query!r}")
    if len(hits) > 1:
        names = ", ".join(r["id"] for r in hits)
        raise AlarmError(f"{query!r} matches {len(hits)} alarms: {names}")
    return hits[0]


# ---------------------------------------------------------------- mutations


def add(
    *,
    alarm_id: str,
    title: str = "",
    when: str = "",
    every: str = "",
    action: str = DO_HOP,
    note: str = "",
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Create one alarm. Interval is not part of create — see set_interval."""
    now = now or datetime.now()
    slug = _slug(alarm_id)
    rows = read_all(path)
    if any(r["id"] == slug for r in rows):
        raise AlarmError(f"id {slug!r} already exists — edit it or pick another")

    due = parse_when(when, now)
    act = (action or DO_HOP).strip().lower()
    if act not in ACTIONS:
        raise AlarmError(f"do {act!r}: use hop · cue · none")

    row = {
        "id": slug,
        "title": (title or "").strip(),
        "when": (when or "").strip(),
        "every": parse_every(every),
        "do": act,
        "note": (note or "").strip(),
        "state": ARMED,
        "created": _iso(now),
        "next_due": _iso(due),
        "last_fired": "",
        "fires": 0,
        "schema": SCHEMA,
    }
    append_one(row, path)
    return _normalize(row)


def set_interval(
    query: str,
    every: str,
    *,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Step two. Turn a one-shot into a repeater, or clear the interval."""
    now = now or datetime.now()
    rows = read_all(path)
    target = find_one(query, rows)
    seconds = parse_every(every)
    for r in rows:
        if r["id"] == target["id"]:
            r["every"] = seconds
            if seconds and not _from_iso(r["next_due"]):
                r["next_due"] = _iso(now + timedelta(seconds=seconds))
            target = r
            break
    write_all(rows, path)
    return target


def edit(
    query: str,
    *,
    title: str | None = None,
    when: str | None = None,
    note: str | None = None,
    action: str | None = None,
    state: str | None = None,
    now: datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Patch named fields on exactly one row. Id never changes."""
    now = now or datetime.now()
    rows = read_all(path)
    target = find_one(query, rows)

    if action is not None:
        act = action.strip().lower()
        if act not in ACTIONS:
            raise AlarmError(f"do {act!r}: use hop · cue · none")
        action = act
    if state is not None:
        st = state.strip().lower()
        if st not in STATES:
            raise AlarmError(f"state {st!r}: use armed · paused · archived")
        state = st

    for r in rows:
        if r["id"] != target["id"]:
            continue
        if title is not None:
            r["title"] = title.strip()
        if note is not None:
            r["note"] = note.strip()
        if action is not None:
            r["do"] = action
        if when is not None:
            due = parse_when(when, now)
            r["when"] = when.strip()
            r["next_due"] = _iso(due)
        if state is not None:
            r["state"] = state
            if state == ARMED and not _from_iso(r["next_due"]):
                r["next_due"] = _iso(parse_when(r["when"] or "+1m", now))
        target = r
        break

    write_all(rows, path)
    return target


# ---------------------------------------------------------------- firing


def due_rows(
    rows: list[dict[str, Any]], now: datetime | None = None
) -> list[dict[str, Any]]:
    """Armed rows whose next_due has passed. Overdue counts — nothing is skipped."""
    now = now or datetime.now()
    out = []
    for r in rows:
        if r["state"] != ARMED:
            continue
        due = _from_iso(r["next_due"])
        if due is not None and due <= now:
            out.append(r)
    return out


def next_due(
    rows: list[dict[str, Any]] | None = None, now: datetime | None = None
) -> dict[str, Any] | None:
    """The soonest armed row, or None. Never invented."""
    rows = read_all() if rows is None else rows
    best: tuple[datetime, dict[str, Any]] | None = None
    for r in rows:
        if r["state"] != ARMED:
            continue
        due = _from_iso(r["next_due"])
        if due is None:
            continue
        if best is None or due < best[0]:
            best = (due, r)
    return best[1] if best else None


def hop(row: dict[str, Any]) -> bool:
    """Open this tree's record window. Not a port. Not Sound Recorder."""
    launcher = repo_root() / "Clip-ui.bat"
    if not launcher.is_file():
        return False
    try:
        if os.name == "nt":
            subprocess.Popen(
                [str(launcher)],
                cwd=str(repo_root()),
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            subprocess.Popen(["cmd", "/c", str(launcher)], cwd=str(repo_root()))
    except OSError:
        return False
    return True


def fire(
    row: dict[str, Any], *, now: datetime | None = None, do_hop: bool = True
) -> dict[str, Any]:
    """Run one alarm's action and advance its schedule. Returns the patched row."""
    now = now or datetime.now()
    action = row["do"]

    if action == DO_HOP and do_hop:
        opened = hop(row)
        if not opened:
            print(f"  ! hop failed for {row['id']} — Clip-ui.bat not found", flush=True)
    if action in (DO_HOP, DO_CUE):
        label = row["title"] or row["id"]
        print(f"  fire {row['id']}  {label}", flush=True)

    patched = dict(row)
    patched["last_fired"] = _iso(now)
    patched["fires"] = int(row.get("fires") or 0) + 1

    if row["every"]:
        step = timedelta(seconds=row["every"])
        due = _from_iso(row["next_due"]) or now
        while due <= now:
            due += step
        patched["next_due"] = _iso(due)
    else:
        patched["state"] = PAUSED
        patched["next_due"] = ""
    return patched


def tick(now: datetime | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    """One pass: fire everything overdue, persist once, return what fired."""
    now = now or datetime.now()
    rows = read_all(path)
    ready = due_rows(rows, now)
    if not ready:
        return []
    ready_ids = {r["id"] for r in ready}
    fired: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        if r["id"] in ready_ids:
            patched = fire(r, now=now)
            rows[i] = patched
            fired.append(patched)
    write_all(rows, path)
    return fired


# ---------------------------------------------------------------- server


def _lock_acquire() -> Path | None:
    """One timekeeper per machine. A stale lock from a dead pid is reclaimed."""
    lp = lock_path()
    lp.parent.mkdir(parents=True, exist_ok=True)
    if lp.is_file():
        try:
            pid = int(lp.read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid and _pid_alive(pid):
            return None
    lp.write_text(str(os.getpid()), encoding="utf-8")
    return lp


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        )
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _stop(_signum, _frame):  # pragma: no cover - signal path
    raise KeyboardInterrupt


def serve(*, max_sleep: float = 60.0, once: bool = False) -> int:
    """Sleep until the next armed when. Fire overdue on wake. No port."""
    lock = _lock_acquire()
    if lock is None:
        print("alarm server already running — not starting a second one")
        return 1
    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _stop)
            except (OSError, ValueError):
                pass
    print(f"alarm server up  pid {os.getpid()}  store {alarms_path()}")
    print("no port. file + process. ctrl-c to stop.")
    try:
        while True:
            now = datetime.now()
            fired = tick(now)
            if fired:
                print(f"  {len(fired)} fired at {_iso(now)}", flush=True)
            if once:
                return 0
            nxt = next_due()
            if nxt is None:
                time.sleep(max_sleep)
                continue
            due = _from_iso(nxt["next_due"])
            gap = (due - datetime.now()).total_seconds() if due else max_sleep
            time.sleep(max(0.5, min(max_sleep, gap)))
    except KeyboardInterrupt:
        print("\nalarm server down")
        return 0
    finally:
        try:
            if lock and lock.is_file() and lock.read_text(encoding="utf-8").strip() == str(os.getpid()):
                lock.unlink()
        except OSError:
            pass


def server_running() -> int:
    """Real pid or 0. Never guessed."""
    lp = lock_path()
    if not lp.is_file():
        return 0
    try:
        pid = int(lp.read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        return 0
    return pid if _pid_alive(pid) else 0


# ---------------------------------------------------------------- render


def _line(r: dict[str, Any]) -> str:
    mark = {ARMED: "*", PAUSED: "-", ARCHIVED: "x"}.get(r["state"], "?")
    every = f"/{r['every']}s" if r["every"] else ""
    due = r["next_due"] or "—"
    title = r["title"] or ""
    return f" {mark} {r['id']:<16} {due:<20} {r['do']:<5}{every:<8} {title}"


def _print_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("no alarms")
        return
    print(f" {'':1} {'id':<16} {'next':<20} {'do':<13} title")
    for r in rows:
        print(_line(r))


# ---------------------------------------------------------------- cli


def _can_walk() -> bool:
    """Only walk when a human is actually there to answer."""
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def _walk_add() -> dict[str, str]:
    """Six named fields, same order every time. Interval is not one of them."""
    print("walking the schema — blank accepts the default in brackets")
    got: dict[str, str] = {}
    got["id"] = input("  id      (slug, unique) : ").strip()
    got["title"] = input("  title   (human line)  : ").strip()
    got["when"] = input("  when    (07:00 · +25m): ").strip()
    print("  every   skipped on add — use `alarm interval` after")
    got["do"] = input("  do      [hop]         : ").strip() or DO_HOP
    got["note"] = input("  note    (optional)    : ").strip()
    return got


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="alarm", description="journal-clip alarms — time fires, then you speak"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="create by walking the schema")
    a.add_argument("--id", default="")
    a.add_argument("--title", default="")
    a.add_argument("--when", default="")
    a.add_argument("--do", dest="action", default=DO_HOP, choices=sorted(ACTIONS))
    a.add_argument("--note", default="")

    i = sub.add_parser("interval", help="step two — make it repeat")
    i.add_argument("query")
    i.add_argument("--every", required=True)

    f = sub.add_parser("find", help="substring on id · title · note")
    f.add_argument("query", nargs="?", default="")

    e = sub.add_parser("edit", help="patch one row found by query")
    e.add_argument("query")
    e.add_argument("--title")
    e.add_argument("--when")
    e.add_argument("--note")
    e.add_argument("--do", dest="action", choices=sorted(ACTIONS))
    e.add_argument("--pause", action="store_true")
    e.add_argument("--arm", action="store_true")
    e.add_argument("--archive", action="store_true")

    ls = sub.add_parser("list", help="all rows, archived last")
    ls.add_argument("--all", action="store_true", help="include archived")

    sub.add_parser("next", help="the soonest armed row")
    sub.add_parser("status", help="real server state — never faked")

    s = sub.add_parser("server", help="local timekeeper. no port.")
    s.add_argument("--once", action="store_true", help="one pass, then exit")

    args = ap.parse_args(argv)

    try:
        if args.cmd == "add":
            if not args.id and not args.when and _can_walk():
                walked = _walk_add()
                row = add(
                    alarm_id=walked["id"],
                    title=walked["title"],
                    when=walked["when"],
                    action=walked["do"],
                    note=walked["note"],
                )
            else:
                missing = [n for n, v in (("--id", args.id), ("--when", args.when)) if not v]
                if missing:
                    raise AlarmError("missing required: " + ", ".join(missing))
                row = add(
                    alarm_id=args.id,
                    title=args.title,
                    when=args.when,
                    action=args.action,
                    note=args.note,
                )
            print(f"added {row['id']}  next {row['next_due']}")
            return 0

        if args.cmd == "interval":
            row = set_interval(args.query, args.every)
            if row["every"]:
                print(f"{row['id']} repeats every {row['every']}s  next {row['next_due']}")
            else:
                print(f"{row['id']} is one-shot again")
            return 0

        if args.cmd == "find":
            hits = find(args.query)
            _print_rows(hits)
            return 0 if hits else 1

        if args.cmd == "edit":
            state = None
            picked = [args.pause, args.arm, args.archive]
            if sum(1 for p in picked if p) > 1:
                raise AlarmError("pick one of --pause · --arm · --archive")
            if args.pause:
                state = PAUSED
            elif args.arm:
                state = ARMED
            elif args.archive:
                state = ARCHIVED
            if not any(
                v is not None for v in (args.title, args.when, args.note, args.action, state)
            ):
                raise AlarmError("nothing to patch — name a field")
            row = edit(
                args.query,
                title=args.title,
                when=args.when,
                note=args.note,
                action=args.action,
                state=state,
            )
            print(_line(row).strip())
            return 0

        if args.cmd == "list":
            rows = read_all()
            if not args.all:
                rows = [r for r in rows if r["state"] != ARCHIVED]
            _print_rows(rows)
            return 0

        if args.cmd == "next":
            row = next_due()
            if row is None:
                print("next  —  nothing armed")
                return 1
            print(f"next  {row['next_due']}  {row['id']}  {row['title']}")
            return 0

        if args.cmd == "status":
            pid = server_running()
            rows = read_all()
            armed = [r for r in rows if r["state"] == ARMED]
            nxt = next_due(rows)
            print(f"running  {('yes  pid ' + str(pid)) if pid else 'no'}")
            print(f"next     {nxt['next_due'] + '  ' + nxt['id'] if nxt else '—'}")
            last = max((r["last_fired"] for r in rows if r["last_fired"]), default="")
            print(f"last     {last or '—'}")
            print("port     none. file + process.")
            print(f"store    {alarms_path()}")
            print(f"alarms   {len(rows)} total · {len(armed)} armed")
            return 0

        if args.cmd == "server":
            return serve(once=args.once)

    except AlarmError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
