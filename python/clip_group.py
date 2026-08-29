#!/usr/bin/env python3
"""Local grouping profiles for the tape. Boundaries are probed from this set."""
from __future__ import annotations

import re
from collections import Counter, OrderedDict
from datetime import datetime
from typing import Any

# period-style abbrev → profile id
PROFILES: tuple[tuple[str, str], ...] = (
    (".d", "day"),
    (".i", "interval"),
    (".n", "domain"),
    (".g", "intent"),
    (".m", "magnitude"),
)

STOP = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "in",
    "it",
    "is",
    "was",
    "i",
    "i'm",
    "im",
    "you",
    "that",
    "this",
    "for",
    "with",
    "on",
    "but",
    "so",
    "all",
    "right",
    "yeah",
    "just",
    "not",
    "have",
    "be",
    "it's",
    "its",
    "my",
    "me",
    "we",
    "they",
    "really",
    "very",
    "like",
}


def content_words(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']{3,}", (text or "").lower())
    return [w.strip("'") for w in words if w.strip("'") and w not in STOP]


def when_ts(row: dict[str, str]) -> float | None:
    day = (row.get("date") or "").strip()
    clock = (row.get("time") or "00:00:00").strip() or "00:00:00"
    if not day:
        return None
    if len(clock) == 5:
        clock = clock + ":00"
    try:
        return datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M:%S").timestamp()
    except ValueError:
        try:
            return datetime.strptime(day, "%Y-%m-%d").timestamp()
        except ValueError:
            return None


def probe_gap_cut(deltas: list[float]) -> float:
    """Local interval boundary from this set's gaps. Seconds."""
    xs = sorted(d for d in deltas if d > 0)
    if not xs:
        return 15 * 60
    if len(xs) == 1:
        return max(xs[0] * 2, 15 * 60)
    lower = xs[: max(1, len(xs) // 2)]
    base = lower[len(lower) // 2]
    return max(base * 3.0, 15 * 60)


def probe_length_cuts(lengths: list[int]) -> list[int]:
    """Up to two payload-size cuts from gaps in this set."""
    xs = sorted(set(int(n) for n in lengths if n >= 0))
    if len(xs) <= 2:
        return []
    gaps = [(xs[i + 1] - xs[i], xs[i]) for i in range(len(xs) - 1)]
    gap_sizes = sorted(g[0] for g in gaps)
    med = gap_sizes[len(gap_sizes) // 2]
    need = max(med * 2, 24)
    cuts: list[int] = []
    for gap, at in sorted(gaps, reverse=True):
        if gap >= need and at not in cuts:
            cuts.append(at)
        if len(cuts) >= 2:
            break
    return sorted(cuts)


def _groups_from_map(buckets: OrderedDict[str, list[dict[str, str]]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key, rows in buckets.items():
        out.append({"key": key, "label": key, "rows": rows, "n": len(rows)})
    return out


def group_day(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    buckets: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
    for r in rows:
        k = (r.get("date") or "").strip() or "undated"
        buckets.setdefault(k, []).append(r)
    return _groups_from_map(buckets)


def group_interval(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    ordered = sorted(
        rows,
        key=lambda r: (when_ts(r) is None, when_ts(r) or 0.0, str(r.get("id") or "")),
    )
    if not ordered:
        return []
    times = [when_ts(r) for r in ordered]
    deltas: list[float] = []
    for a, b in zip(times, times[1:]):
        if a is None or b is None:
            deltas.append(0.0)
        else:
            deltas.append(max(0.0, b - a))
    cut = probe_gap_cut([d for d in deltas if d > 0])
    chunks: list[list[dict[str, str]]] = [[ordered[0]]]
    for r, d in zip(ordered[1:], deltas):
        if d > cut:
            chunks.append([r])
        else:
            chunks[-1].append(r)
    out: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks, 1):
        t0 = (chunk[0].get("time") or "")[:5]
        t1 = (chunk[-1].get("time") or "")[:5]
        day = chunk[0].get("date") or ""
        label = f"{day} {t0}–{t1}".strip()
        out.append({"key": f"i{i}", "label": label, "rows": chunk, "n": len(chunk)})
    return out


def group_domain(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    kinds = {(r.get("kind") or "dump").strip() or "dump" for r in rows}
    if len(kinds) > 1:
        buckets: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
        for r in rows:
            k = (r.get("kind") or "dump").strip() or "dump"
            buckets.setdefault(k, []).append(r)
        return _groups_from_map(buckets)
    freq: Counter[str] = Counter()
    per: list[list[str]] = []
    for r in rows:
        ws = content_words(r.get("text") or "")
        per.append(ws)
        freq.update(set(ws))
    n = max(1, len(rows))
    distinctive = {w for w, c in freq.items() if 1 < c < n}
    buckets = OrderedDict()
    for r, ws in zip(rows, per):
        cands = [w for w in ws if w in distinctive]
        if cands:
            key = min(cands, key=lambda w: (freq[w], w))
        else:
            key = "·"
        buckets.setdefault(key, []).append(r)
    return _groups_from_map(buckets)


def group_intent(rows: list[dict[str, str]], cues: str = "") -> list[dict[str, Any]]:
    cue_words = set(content_words(cues))
    if not cue_words:
        buckets: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
        for r in rows:
            k = (r.get("kind") or "dump").strip() or "dump"
            buckets.setdefault(f"kind:{k}", []).append(r)
        return _groups_from_map(buckets)
    scores: list[int] = []
    for r in rows:
        words = set(content_words(r.get("text") or ""))
        scores.append(len(words & cue_words))
    positive = [s for s in scores if s > 0]
    cut = 1
    if positive:
        cut = max(1, sorted(positive)[len(positive) // 2])
    buckets = OrderedDict([("on-goal", []), ("near", []), ("off", [])])
    for r, s in zip(rows, scores):
        if s >= cut and s > 0:
            buckets["on-goal"].append(r)
        elif s > 0:
            buckets["near"].append(r)
        else:
            buckets["off"].append(r)
    return [
        {"key": k, "label": k, "rows": v, "n": len(v)}
        for k, v in buckets.items()
        if v
    ]


def group_magnitude(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    lengths = [len((r.get("text") or "").strip()) for r in rows]
    cuts = probe_length_cuts(lengths)

    def label_for(n: int) -> str:
        if not cuts:
            return "all"
        if n <= cuts[0]:
            return f"≤{cuts[0]}"
        for a, b in zip(cuts, cuts[1:]):
            if n <= b:
                return f"{a + 1}–{b}"
        return f">{cuts[-1]}"

    buckets: OrderedDict[str, list[dict[str, str]]] = OrderedDict()
    for r, n in zip(rows, lengths):
        buckets.setdefault(label_for(n), []).append(r)
    return _groups_from_map(buckets)


def group_rows(
    rows: list[dict[str, str]],
    profile: str,
    *,
    intent_cues: str = "",
) -> list[dict[str, Any]]:
    pid = profile if not profile.startswith(".") else dict(PROFILES).get(profile, profile)
    if profile.startswith(".") and profile in dict(PROFILES):
        pid = dict(PROFILES)[profile]
    if pid == "day":
        return group_day(rows)
    if pid == "interval":
        return group_interval(rows)
    if pid == "domain":
        return group_domain(rows)
    if pid == "intent":
        return group_intent(rows, intent_cues)
    if pid == "magnitude":
        return group_magnitude(rows)
    return group_day(rows)
