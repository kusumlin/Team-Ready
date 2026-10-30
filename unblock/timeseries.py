"""Friction Map events in Tiger Data (TimescaleDB).

Set TIMESCALE_URL (a Tiger Cloud service URL, or any Postgres) to turn it on.
With the timescaledb extension:
  - friction_events is a hypertable partitioned on time
  - friction_daily is a continuous aggregate (time_bucket of 1 day per topic and
    first doc read), refreshed by a policy every 15 minutes and real-time for
    events newer than the last refresh
On plain Postgres, friction_daily is an ordinary view, so the code path is the same.
Only topic, first doc read, resolved and time are stored: no names, no message text.
"""
from datetime import date, datetime, time, timezone

from .config import env

SCHEMA = """
CREATE TABLE IF NOT EXISTS friction_events (
    time       timestamptz NOT NULL,
    topic      text        NOT NULL,
    start_doc  text,
    resolved   boolean     NOT NULL
);
"""

TIMESCALE_SETUP = [
    "SELECT create_hypertable('friction_events', 'time', if_not_exists => TRUE, migrate_data => TRUE)",
    """CREATE MATERIALIZED VIEW IF NOT EXISTS friction_daily
       WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
       SELECT time_bucket(INTERVAL '1 day', time) AS day, topic, start_doc,
              count(*) AS blockers, count(*) FILTER (WHERE resolved) AS resolved
       FROM friction_events GROUP BY time_bucket(INTERVAL '1 day', time), topic, start_doc WITH NO DATA""",
    """SELECT add_continuous_aggregate_policy('friction_daily',
       start_offset => INTERVAL '60 days', end_offset => INTERVAL '1 hour',
       schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE)""",
]

PLAIN_VIEW = """
CREATE OR REPLACE VIEW friction_daily AS
SELECT date_trunc('day', time) AS day, topic, start_doc,
       count(*) AS blockers, count(*) FILTER (WHERE resolved) AS resolved
FROM friction_events GROUP BY 1, 2, 3
"""


_down = {"until": 0.0}


def enabled() -> bool:
    return bool(env("TIMESCALE_URL"))


def usable() -> bool:
    """Configured, and not seen unreachable in the last minute (some networks block the database port)."""
    import time
    return enabled() and time.time() >= _down["until"]


def mark_down() -> None:
    import time
    _down["until"] = time.time() + 60


def connect():
    import psycopg

    return psycopg.connect(env("TIMESCALE_URL"), autocommit=True, connect_timeout=4, client_encoding="utf8",
                           options="-c TimeZone=UTC")


def setup(conn) -> str:
    """Create the schema. Returns 'timescale' or 'postgres'."""
    conn.execute(SCHEMA)
    try:
        conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
        for sql in TIMESCALE_SETUP:
            conn.execute(sql)
        return "timescale"
    except Exception:
        conn.execute(PLAIN_VIEW)
        return "postgres"


def backend(conn) -> str:
    row = conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'").fetchone()
    return "timescale" if row else "postgres"


def _ts(day: str) -> datetime:
    return datetime.combine(date.fromisoformat(day), time(12), tzinfo=timezone.utc)


def seed(conn, events: list[dict]) -> int:
    """Load the synthetic history once (only into an empty table)."""
    if conn.execute("SELECT count(*) FROM friction_events").fetchone()[0]:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO friction_events (time, topic, start_doc, resolved) VALUES (%s, %s, %s, %s)",
            [(_ts(e["day"]), e["topic"], (e["docs_read"] or [None])[0], e["resolved_without_ticket"]) for e in events],
        )
    if backend(conn) == "timescale":
        conn.execute("CALL refresh_continuous_aggregate('friction_daily', NULL, NULL)")
    return len(events)


def insert(conn, topic: str, start_doc: str | None, resolved: bool, day: date) -> None:
    conn.execute("INSERT INTO friction_events (time, topic, start_doc, resolved) VALUES (%s, %s, %s, %s)",
                 (_ts(day.isoformat()), topic, start_doc, resolved))


def daily_rows(conn, since: date, until: date) -> list[dict]:
    """Aggregate rows for days after `since` up to and including `until`."""
    def midnight(d: date) -> datetime:
        return datetime.combine(d, time(0), tzinfo=timezone.utc)

    rows = conn.execute(
        """SELECT topic, start_doc, sum(blockers)::int, sum(resolved)::int
           FROM friction_daily WHERE day > %s AND day <= %s GROUP BY topic, start_doc""",
        (midnight(since), midnight(until)),
    ).fetchall()
    return [{"topic": t, "start_doc": d, "blockers": b, "resolved": r} for t, d, b, r in rows]
