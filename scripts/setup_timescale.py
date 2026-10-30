"""Create the Friction Map tables in Tiger Data (TimescaleDB) and load the synthetic history.

    TIMESCALE_URL=postgres://... python scripts/setup_timescale.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unblock import timeseries  # noqa: E402
from unblock.data import load_events  # noqa: E402
from unblock.friction import build_map  # noqa: E402

if not timeseries.enabled():
    sys.exit("Set TIMESCALE_URL first (your Tiger Cloud service URL).")

with timeseries.connect() as conn:
    kind = timeseries.setup(conn)
    added = timeseries.seed(conn, load_events())
print(f"Schema ready on {kind}. Seeded {added} events.")
fmap = build_map()
print(f"Friction Map from {fmap['storage']}: {fmap['total_blockers']} blockers, "
      f"{len(fmap['clusters'])} clusters, top: {fmap['clusters'][0]['topic'] if fmap['clusters'] else '-'}")
