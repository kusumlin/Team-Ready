"""Print each agent's address (derived from its seed). Paste these into the README before submitting."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))

from common import AGENTS, address  # noqa: E402

for name in AGENTS:
    print(f"teamready-{name:13s} {address(name)}")
