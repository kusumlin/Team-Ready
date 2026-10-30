"""Generate synthetic onboarding blocker events for the Friction Map.

Each event is one blocker a new hire raised: topic, the docs they read first,
whether TeamReady resolved it without a ticket, and a day. No names or message
text are stored, which mirrors what the live system logs.

Run:  python scripts/generate_events.py
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(17)
END = date(2026, 10, 16)

# topic, count, docs read before asking, share resolved without a ticket
CLUSTERS = [
    ("analytics access", 18, [["D02"], ["D02"], ["D01"]], 0.55),
    ("staging deploys", 14, [["D14"], ["D14", "D13"], ["D13"]], 0.5),
    ("expense submission", 12, [["D04"], ["D05"]], 0.75),
    ("design software licenses", 9, [["D08"]], 0.65),
    ("time off setup", 8, [["D06", "D07"], ["D06"]], 0.6),
    ("vpn and remote access", 6, [["D10"]], 0.85),
    ("data warehouse query access", 5, [["D03"], ["D01"]], 0.6),
    ("password and mfa", 3, [["D11"]], 1.0),
    ("badge access", 2, [["D21"]], 1.0),
]

events = []
n = 0
for topic, count, paths, resolved_share in CLUSTERS:
    resolved_count = round(count * resolved_share)
    for i in range(count):
        n += 1
        # "analytics access": 8 of 18 came straight from the checklist with no form link.
        if topic == "analytics access":
            docs_read = ["D02"] if i < 8 else random.choice(paths)
        elif topic == "staging deploys":
            docs_read = ["D14"] if i < 6 else random.choice(paths)
        else:
            docs_read = random.choice(paths)
        events.append({
            "id": f"E{n:03d}",
            "topic": topic,
            "docs_read": docs_read,
            "resolved_without_ticket": i < resolved_count,
            "day": (END - timedelta(days=random.randint(0, 29))).isoformat(),
        })

events.sort(key=lambda e: e["day"])
out = Path(__file__).resolve().parent.parent / "data" / "events.json"
out.write_text(json.dumps(events, indent=1))
print(f"wrote {len(events)} events to {out}")
