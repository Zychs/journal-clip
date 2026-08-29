# Sesefus 0.2.0 — alarms

Time fires. Then you speak.

This is the frozen contract for the alarm surface. It sits on top of
`0.1.0 — constrained Clip UI` and changes nothing that 0.1 froze.

---

## 1. Ladder position

```
0.1  constrained clip    talk · local Whisper · text · shred wav
0.2  alarms              groups · bulk · interval · toggle · daemon · hop fire   ← here
0.3  fire can sample
0.4  review last
0.5  heuristic ETDI, no net
0.6  optional local Ollama
0.7  circadian mass-ops polish
0.8  cheap cadence drift
0.9-beta  one small app · 60s/day tester loop · no dashboard command
```

Out of 0.1–0.9 entirely: Fleet, Glass, Zig vault, Grok cloud, LeadLogic,
AyTree, sieves, scanner host.

Lineage: `0.9.3-alpha` (old tester + suite) is the alpha source cut. This
ladder is a contraction of it. New `0.9-beta` is the beta of *this* ladder and
is not a successor to `0.9.3`. The Desktop clip changelog `1.0.0` retags to
`0.1.0` — same product, renumbered under the ladder, not a second release.

---

## 2. What 0.2.0 ships

Four of the six packed 0.2 jobs are implemented and tested:

| job | state | surface |
|---|---|---|
| interval | shipped | `alarm interval <query> --every 1d` |
| toggle | shipped | `alarm edit <query> --pause / --arm / --archive` |
| daemon | shipped | `alarm server` |
| hop fire | shipped | `--do hop` opens this tree's record window |
| groups | **deferred** | see §7 |
| bulk | **deferred** | see §7 |

Source: `python/clip_alarm.py`. Tests: `python/tests/test_alarm.py`.
Launcher route: `Clip.bat alarm <cmd>` — dispatched before the zig path, so
alarms never trigger a build.

---

## 3. Store contract

```
%USERPROFILE%\.sesefus\clip-alarms.jsonl     (or SESEFUS_CLIP_ALARMS)
%USERPROFILE%\.sesefus\clip-alarms.lock      single-instance guard, holds a pid
```

* Outside the journal. Outside the repository. Enforced by test.
* One JSON object per line. `schema = 1`.
* Ids are slugs: `^[a-z0-9][a-z0-9._-]*$`. Unique. Never silently replaced.
* Appends are flushed and `fsync`ed before the handle closes.
* Whole-tape rewrites go to a temp file in the same directory, then `os.replace`.
  A crash mid-rewrite leaves the previous complete tape intact.
* A torn final line is skipped on read and never destroys prior records.

Row fields:

```
id · title · when · every · do · note
state · created · next_due · last_fired · fires · schema
```

`state` ∈ `armed | paused | archived`.  `do` ∈ `hop | cue | none`.

---

## 4. Command surface

**Create by walking the schema.** Six named fields, same order every time.
Interval is not part of create.

```
Clip.bat alarm add --id morning --title "wake journal" --when 07:00
Clip.bat alarm add --id stretch --when +25m --do hop
Clip.bat alarm add                      (walks the six fields)
```

The walk runs only when stdin is a terminal. Piped or scheduled, a bare `add`
refuses and names the missing flags rather than blocking on input.

**Then interval it.**

```
Clip.bat alarm interval morning --every 1d
Clip.bat alarm interval /wake --every 90m
```

**Then edit by search.**

```
Clip.bat alarm find stretch
Clip.bat alarm edit morning --when 07:15
Clip.bat alarm edit /wake --title "morning plate"
Clip.bat alarm edit /stretch --pause
Clip.bat alarm edit morning --arm
Clip.bat alarm edit /old --archive
```

**Server and read-only state.**

```
Clip.bat alarm server        local timekeeper. no port.
Clip.bat alarm status
Clip.bat alarm next
Clip.bat alarm list
```

`when` accepts `07:00` · `+25m` · RFC3339. A bare clock already past means
tomorrow. `every` accepts `30s` · `90m` · `2h` · `1d`; empty clears it.

---

## 5. Standing law — holds across the whole ladder

* **No port.** No socket, no bind, no listener, ever. File + process only.
  Not `:3000`. Not `:8777`. Not Sound Recorder. Enforced by test.
* **No faked state.** `status` and `next` report what is actually on disk and
  whether a real pid is alive. Nothing is invented when the server is down.
* **Persistent state lives outside the journal and outside the repository.**
* **Search is not mutate.** An edit query must resolve to exactly one row.
  Zero or two-or-more prints the candidates and exits 1.
* **Archive is not delete.** `archive` hides from `list`; the row stays.

---

## 6. 0.2 gates — true at this rung, not forever

* The 0.1 rule that *no launcher starts a daemon* is a **0.1 gate**. The
  daemon arrives legitimately here at 0.2. The *no port* half of that rule is
  standing law and does not lift.
* `Clip-ui.bat` and `Clip-edit.bat` remain unchanged: double-clicking either
  still opens exactly one window and starts no service. Only `Clip.bat alarm
  server`, typed deliberately, starts the timekeeper.

**Scheduling decision.** A missed repeater fires **once** and rolls forward
past now — not once per skipped slot. Laptop asleep four hours on a 30-minute
interval yields one fire, not eight. Test: `missed repeater fires once, not
once per slot`. Reverse it there if this is wrong.

**One-shot decision.** An alarm with no interval fires once and moves to
`paused`, keeping the row. It is not deleted and not left armed.

---

## 7. Deferred: groups and bulk

Both were packed into 0.2 and neither is implemented. They are mass-ops:
they act on the set that `find` already returns, so the primitive exists and
they are additive rather than structural.

`find_one` currently *refuses* on 2+ matches. Bulk is the deliberate inversion
of that refusal, and must stay deliberate — a bulk verb, never a widened
`edit`. Silent multi-row mutation is the failure mode to design against.

**Decided: they land at `0.2.1`.** Groups and bulk complete 0.2 as originally
packed, and `0.7 circadian mass-ops polish` then polishes what 0.2 built
rather than introducing it. The original packing stands.

Consequences of that choice:

* `0.2.0` ships as a **partial** rung, not a complete one. It is honest about
  shipping four of six jobs; it does not redefine 0.2 to mean four.
* Groups and bulk are out of scope for `0.2.0` verification and in scope for
  `0.2.1`. The `0.2.0` tag may be cut without them.
* `0.7` may assume groups and bulk already exist. It is a polish rung and
  must not be the first place mass-ops appear.

---

## 8. Acceptance checklist — 0.2.0

Store and durability

* [x] Tape lands at `.sesefus\clip-alarms.jsonl`, never inside the repo.
* [x] Append writes one complete JSON line, flushed and synced.
* [x] Rewrite is atomic; no `.alarms-*.tmp` survives a successful edit.
* [x] A torn final line does not lose prior complete records.
* [x] Duplicate id refuses and leaves the tape at its prior length.
* [x] Bad slug, bad `when`, bad `every`, bad `do` all refuse.

Search and edit

* [x] Exact id wins over substring.
* [x] Leading `/` forces query mode across id, title, note.
* [x] `find_one` refuses on 0 and on 2+, naming the candidates.
* [x] Edit preserves the id.
* [x] Pause keeps the row; archive keeps the row.

Firing

* [x] Only armed, overdue rows fire.
* [x] Paused rows never fire.
* [x] One-shot disarms after firing, `fires` increments.
* [x] Repeater advances past now and stays armed.
* [x] A four-hour miss on a 30-minute repeater fires once.
* [x] Overdue rows fire on wake, however stale.
* [x] `cue` does not hop; `hop` does.
* [x] `next` is never invented and picks the soonest armed row.

Boundary

* [x] No socket, socketserver, or bind anywhere in the module.
* [x] Second `alarm server` refuses instead of starting a rival timekeeper.
* [x] Lock releases on Ctrl-C and on SIGTERM.
* [x] A stale lock from a dead pid is reclaimed, not honored.

Launcher

* [x] `Clip.bat alarm ...` dispatches before the zig path; no build runs.
* [x] Quoted arguments survive the re-quote loop, spaces intact.
* [x] Bare `alarm` prints usage and exits non-zero; it does not block.
* [ ] **Real Windows smoke test** — `Clip.bat alarm add` / `server` / `status`
      executed on the machine, plus one live `--do hop` proving the recorder
      window opens. Not yet performed; the harness above ran on Linux.

Automated result: **35 / 35 pass**, plus a clean `compileall` over the tree.

---

## 9. Open at time of writing

1. Groups and bulk have no version. §7.
2. `0.1.0` is not yet tagged. This 0.2 source now sits in the same tree,
   so the repository is no longer a pure 0.1.0 baseline. Either tag `v0.1.0`
   from the commit before the alarm work, or accept that `0.1.0` exists as a
   documented state rather than a tagged commit.
3. `python/alarm_schema.json`, referenced by the alarm card, does not exist.
   The schema currently lives in `_normalize()` and `FIELDS`. Either write the
   JSON and validate against it, or drop the card's link.
4. No dependency manifest exists yet. The alarm module adds no third-party
   imports — standard library only — so 0.2 does not enlarge the requirement.
