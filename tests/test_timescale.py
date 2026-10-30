"""Tiger Data store. Runs only when UNBLOCK_TEST_PG_URL points at a scratch Postgres/Timescale database."""
import os

import pytest

from unblock import friction, timeseries
from unblock.data import load_events

URL = os.environ.get("UNBLOCK_TEST_PG_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="set UNBLOCK_TEST_PG_URL to run against a scratch database")


def test_timescale_store_matches_json_and_takes_live_events(monkeypatch):
    json_map = friction.build_map()
    monkeypatch.setenv("TIMESCALE_URL", URL)
    with timeseries.connect() as conn:
        conn.execute("DROP VIEW IF EXISTS friction_daily")
        conn.execute("DROP TABLE IF EXISTS friction_events CASCADE")
        kind = timeseries.setup(conn)
        assert timeseries.seed(conn, load_events()) == len(load_events())
        assert timeseries.seed(conn, load_events()) == 0  # only seeds an empty table
    db_map = friction.build_map()
    assert db_map["storage"] in ("Tiger Data (TimescaleDB continuous aggregate)", "Postgres view")
    assert kind in ("timescale", "postgres")
    strip = lambda m: [(c["topic"], c["count"], c["resolved_without_ticket"], c["start_doc"]) for c in m["clusters"]]  # noqa: E731
    assert strip(db_map) == strip(json_map)
    assert db_map["total_blockers"] == json_map["total_blockers"]

    before = {c["topic"]: c["count"] for c in db_map["clusters"]}["vpn and remote access"]
    friction.log_live_event("D10", ["D10"], True)
    after = {c["topic"]: c["count"] for c in friction.build_map()["clusters"]}["vpn and remote access"]
    assert after == before + 1
