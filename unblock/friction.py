"""Friction Map: repeated blockers turned into anonymous, fixable patterns.

Every number is computed from events (seeded synthetic history plus topics the
live system logs). Events hold a topic, the docs read first, whether it was
resolved without a ticket, and a day. No names and no message text.
Clusters with fewer than min_cohort_size events are hidden.
"""
import json
from collections import Counter
from datetime import date, timedelta

from .config import DATA_DIR, today
from . import timeseries
from .data import load_docs, load_events, load_policies

LIVE_EVENTS_PATH = DATA_DIR / "runtime" / "live_events.json"

# Topic label for live events, keyed by the top retrieved doc.
DOC_TOPICS = {
    "D01": "analytics access", "D02": "analytics access", "D03": "data warehouse query access",
    "D04": "expense submission", "D05": "expense submission", "D06": "time off setup", "D07": "time off setup",
    "D08": "design software licenses", "D10": "vpn and remote access", "D11": "password and mfa",
    "D12": "dev environment setup", "D13": "staging deploys", "D14": "staging deploys", "D21": "badge access",
}

# Where the fix belongs when a cluster mostly starts from one doc.
FIX_SOURCES = {"D02": "D01", "D14": "D13"}


def topic_for(doc_id: str) -> str:
    return DOC_TOPICS.get(doc_id, "other onboarding questions")


def log_live_event(doc_id: str, docs_read: list[str], resolved: bool) -> None:
    if timeseries.usable():
        try:
            with timeseries.connect() as conn:
                timeseries.insert(conn, topic_for(doc_id), (docs_read or [None])[0], resolved, today())
            return
        except Exception:  # unreachable from this network: keep the event locally instead of failing the reply
            timeseries.mark_down()
    LIVE_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    events = json.loads(LIVE_EVENTS_PATH.read_text()) if LIVE_EVENTS_PATH.exists() else []
    events.append({"id": f"L{len(events) + 1:03d}", "topic": topic_for(doc_id), "docs_read": docs_read,
                   "resolved_without_ticket": resolved, "day": today().isoformat()})
    LIVE_EVENTS_PATH.write_text(json.dumps(events, indent=1))


def all_events(days: int = 30) -> list[dict]:
    events = load_events()
    if LIVE_EVENTS_PATH.exists():
        events += json.loads(LIVE_EVENTS_PATH.read_text())
    since = today() - timedelta(days=days)
    return [e for e in events if date.fromisoformat(e["day"]) > since]


def _rows(days: int) -> tuple[list[dict], str]:
    """(topic, start_doc, blockers, resolved) rows for the window, from Tiger Data or JSON."""
    if timeseries.usable():
        try:
            with timeseries.connect() as conn:
                kind = timeseries.backend(conn)
                rows = timeseries.daily_rows(conn, today() - timedelta(days=days), today())
            label = "Tiger Data (TimescaleDB continuous aggregate)" if kind == "timescale" else "Postgres view"
            return rows, label
        except Exception:
            timeseries.mark_down()
    grouped: dict[tuple, dict] = {}
    for e in all_events(days):
        key = (e["topic"], (e["docs_read"] or [None])[0])
        row = grouped.setdefault(key, {"topic": key[0], "start_doc": key[1], "blockers": 0, "resolved": 0})
        row["blockers"] += 1
        row["resolved"] += 1 if e["resolved_without_ticket"] else 0
    return list(grouped.values()), ("JSON files (Tiger Data not reachable from this network)" if timeseries.enabled() else "JSON files")


def build_map(days: int = 30) -> dict:
    docs = load_docs()
    min_cohort = load_policies()["min_cohort_size"]
    rows, storage = _rows(days)
    by_topic: dict[str, list[dict]] = {}
    for r in rows:
        by_topic.setdefault(r["topic"], []).append(r)

    clusters, hidden = [], 0
    for topic, items in by_topic.items():
        count = sum(r["blockers"] for r in items)
        if count < min_cohort:
            hidden += count
            continue
        resolved = sum(r["resolved"] for r in items)
        first_docs = Counter()
        for r in items:
            if r["start_doc"]:
                first_docs[r["start_doc"]] += r["blockers"]
        doc_id, from_doc = first_docs.most_common(1)[0] if first_docs else ("", 0)
        pattern = ""
        # Only call it a pattern when people start from a doc that's stale or missing a step.
        if doc_id and from_doc / count >= 0.4:
            started = f"{from_doc} of {count} started from '{docs[doc_id].title}'"
            if (today() - docs[doc_id].updated_at).days > 365:
                pattern = started + ", a doc that is more than a year out of date"
            elif doc_id in FIX_SOURCES:
                pattern = started + f", which doesn't include what '{docs[FIX_SOURCES[doc_id]].title}' says"
        clusters.append({
            "topic": topic, "count": count, "resolved_without_ticket": resolved,
            "resolved_share": round(resolved / count, 2), "start_doc": doc_id,
            "start_doc_share": round(from_doc / count, 2), "pattern": pattern,
            "fixable": bool(pattern) and doc_id in FIX_SOURCES,
        })
    clusters.sort(key=lambda c: c["count"], reverse=True)
    total = sum(r["blockers"] for r in rows)
    resolved_total = sum(r["resolved"] for r in rows)
    return {
        "window_days": days, "total_blockers": total,
        "resolved_without_ticket_share": round(resolved_total / total, 2) if total else 0.0,
        "clusters": clusters, "hidden_small_cohort_events": hidden, "min_cohort_size": min_cohort,
        "process_gaps": sum(1 for c in clusters if c["fixable"]),
        "data_note": "Synthetic events. Topics and doc paths only: no names, no message text.",
        "storage": storage,
    }


def fix_target(cluster: dict) -> tuple[str, str] | None:
    """Return (doc to fix, doc that has the missing detail) for a fixable cluster."""
    start = cluster.get("start_doc")
    if start in FIX_SOURCES:
        return start, FIX_SOURCES[start]
    return None
