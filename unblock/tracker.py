"""Tracker: follows up on what the new hire sent, so nothing quietly stalls.

The orchestrator tells the Tracker about every message, 1:1 invite and access
request it sends. When one gets no answer within the due time, the Tracker
offers the new hire a drafted, friendly reminder. Like every other action, the
reminder goes through the Guardian check and is sent only after approval.

TRACKER_DUE_HOURS     how long before a follow-up is offered (default 24)
TRACKER_DUE_MINUTES   overrides the hours, for live demos (e.g. 2)
TRACKER_CHECK_SECONDS how often the Tracker checks (default 300)
"""
import time

from .config import env
from .risk import check_draft

KIND_LABEL = {"message_helper": "your message", "book_1_1": "your 1:1 invite", "access_request": "your access request",
              "it_ticket": "your IT ticket"}


def due_seconds() -> int:
    minutes = env("TRACKER_DUE_MINUTES")
    if minutes:
        return int(float(minutes) * 60)
    return int(float(env("TRACKER_DUE_HOURS", "24")) * 3600)


def add(items: dict, item_id: str, user: str, kind: str, summary: str, to_name: str, to_email: str, now: float | None = None) -> dict:
    items[item_id] = {"id": item_id, "user": user, "kind": kind, "summary": summary[:120], "to_name": to_name,
                      "to_email": to_email, "created": now if now is not None else time.time(), "nudged": False, "status": "open"}
    return items[item_id]


def resolve(items: dict, item_id: str, outcome: str) -> bool:
    item = items.get(item_id)
    if not item or item["status"] != "open":
        return False
    item["status"] = outcome
    return True


def overdue(items: dict, now: float | None = None, due: int | None = None) -> list[dict]:
    now = time.time() if now is None else now
    due = due_seconds() if due is None else due
    return [i for i in items.values() if i["status"] == "open" and not i["nudged"] and now - i["created"] >= due]


def age_text(seconds: float) -> str:
    def unit(n: int, word: str) -> str:
        return f"{n} {word}{'' if n == 1 else 's'}"

    if seconds < 3600:
        return unit(max(1, int(seconds // 60)), "minute")
    if seconds < 86400:
        return unit(int(seconds // 3600), "hour")
    return unit(int(seconds // 86400), "day")


def reminder_draft(item: dict, sender_name: str) -> dict:
    """A short, polite follow-up. Plain template: it states only what was sent and when."""
    first = item["to_name"].split()[0]
    what = {"access_request": f"my access request {item['id']}", "book_1_1": "my 1:1 invite"}.get(item["kind"], "my earlier message")
    draft = {"subject": f"Following up: {item['summary']}",
             "body": f"Hi {first},\n\nJust following up on {what} about \"{item['summary']}\". No rush, and thank you for your help!\n\n{sender_name.split()[0]}"}
    draft["guardian"] = check_draft(draft["subject"], draft["body"])
    return draft


def plan_text(items: dict, user: str, now: float | None = None) -> str:
    now = time.time() if now is None else now
    mine = [i for i in items.values() if i["user"] == user]
    if not mine:
        return "Nothing to track yet. When TeamReady sends a message or request for you, I'll follow its progress here."
    lines = ["**Your onboarding follow-ups**"]
    for i in sorted(mine, key=lambda x: x["created"]):
        state = "waiting" if i["status"] == "open" else i["status"]
        lines.append(f"- {i['id']}: {KIND_LABEL.get(i['kind'], i['kind'])} to {i['to_name']} about \"{i['summary']}\". "
                     f"{state.capitalize()}, sent {age_text(now - i['created'])} ago.")
    return "\n".join(lines)
