"""teamready-tracker: follows up when a message or request gets no answer.

Gets TrackItem / TrackResolved from the orchestrator only. Every few minutes it
checks for items past their due time and messages the new hire in ASI:One with a
drafted reminder. The reminder passes the Guardian check and is sent only after
the new hire approves. Tools: its own follow-up list, the reminder template, and
email-after-approval. It can't send anything on its own.
"""
import asyncio
import json
import time

from common import PUBLISH, address, create_agent
from uagents import Context

from unblock import activity
from unblock import tracker
from unblock.actions import send_email
from unblock.chat import card_message, create_chat_protocol, parse_input
from unblock.config import env
from unblock.data import load_user
from unblock.models import TrackItem, TrackResolved

CHECK_SECONDS = float(env("TRACKER_CHECK_SECONDS", "300"))

agent = create_agent(
    "tracker", "teamready-tracker",
    "Follows up for new hires: watches messages and access requests TeamReady sent, and when one gets no answer, "
    "drafts a friendly reminder that is sent only after the new hire approves. Say 'my plan' to see what's pending.",
    ["follow-up", "reminders"],
)


def _items(ctx: Context) -> dict:
    return json.loads(ctx.storage.get("items") or "{}")


def _save(ctx: Context, items: dict) -> None:
    ctx.storage.set("items", json.dumps(items))


def _reminder_card(item: dict, draft: dict, waited: str):
    text = (f"It's been {waited} since {tracker.KIND_LABEL.get(item['kind'], 'your message')} to **{item['to_name']}** about "
            f"\"{item['summary']}\", and there's no answer yet.\n\nI drafted a friendly follow-up. Nothing is sent until you approve it.\n\n"
            f"To: {item['to_name']} <{item['to_email']}>\nSubject: {draft['subject']}\n\n{draft['body']}\n\n"
            "Reply **approve**, **reject**, or **edit: <your new message>**.")
    payload = {"title": f"Follow up with {item['to_name']}?",
               "summary_rows": [{"label": "Waiting", "value": waited}, {"label": "About", "value": item["summary"]},
                                {"label": "Message", "value": draft["body"]},
                                {"label": "Guardian check", "value": "Clear" if not draft["guardian"] else "Blocked: " + "; ".join(draft["guardian"])}],
               "approve_cta": {"label": "Send follow-up", "primary": True, "selection": {"action": "ub_approve"}},
               "reject_cta": {"label": "Not now", "selection": {"action": "ub_reject"}}}
    return card_message(text, "review", payload)


@agent.on_message(TrackItem)
async def on_track(ctx: Context, sender: str, msg: TrackItem):
    if sender != address("orchestrator"):
        return
    items = _items(ctx)
    tracker.add(items, msg.item_id, msg.user, msg.kind, msg.summary, msg.to_name, msg.to_email)
    _save(ctx, items)


@agent.on_message(TrackResolved)
async def on_resolved(ctx: Context, sender: str, msg: TrackResolved):
    if sender != address("orchestrator"):
        return
    items = _items(ctx)
    if tracker.resolve(items, msg.item_id, msg.outcome):
        activity.log("tracker", f"{msg.item_id} closed: {msg.outcome}", kind="done")
        _save(ctx, items)


@agent.on_interval(period=CHECK_SECONDS)
async def check(ctx: Context):
    items = _items(ctx)
    now = time.time()
    for item in tracker.overdue(items, now):
        item["nudged"] = True
        draft = tracker.reminder_draft(item, load_user()["name"])
        ctx.storage.set(f"draft:{item['user']}", json.dumps({"item_id": item["id"], **draft}))
        activity.log("tracker", f"No reply from {item['to_name']} after {tracker.age_text(now - item['created'])}; offering a follow-up", kind="step")
        activity.log("tracker", "[card] Want me to send a friendly reminder?", to="user", kind="message")
        await ctx.send(item["user"], _reminder_card(item, draft, tracker.age_text(now - item["created"])))
    if items:
        _save(ctx, items)


async def chat(ctx: Context, sender: str, text: str):
    sel = parse_input(text)
    typed = text.strip().lower().rstrip(".!")
    action = str(sel.get("action", "")).lower().removeprefix("ub_") or typed
    if "ub_approve" in typed:
        action = "approve"
    elif "ub_reject" in typed:
        action = "reject"
    raw = ctx.storage.get(f"draft:{sender}")
    if action in ("approve", "reject") or typed.startswith("edit:"):
        if not raw:
            return "There's no follow-up waiting for you right now."
        draft = json.loads(raw)
        items = _items(ctx)
        item = items.get(draft["item_id"])
        if not item:
            ctx.storage.remove(f"draft:{sender}")
            return "That follow-up is no longer open. Nothing was sent."
        if action == "reject":
            ctx.storage.remove(f"draft:{sender}")
            return "Okay, no follow-up. Nothing was sent."
        if typed.startswith("edit:"):
            draft["body"] = text.split(":", 1)[1].strip()
            from unblock.risk import check_draft
            draft["guardian"] = check_draft(draft["subject"], draft["body"])
            ctx.storage.set(f"draft:{sender}", json.dumps(draft))
            return _reminder_card(item, draft, tracker.age_text(time.time() - item["created"]))
        if draft["guardian"]:
            return "Guardian stopped this follow-up: it " + "; it ".join(draft["guardian"]) + ". Edit it first. Nothing was sent."
        result = await asyncio.to_thread(send_email, item["to_email"], draft["subject"], draft["body"], load_user()["email"])
        activity.log("tracker", f"Reminder to {item['to_name']} after your approval: {result['status']}", to="people", kind="done" if result["status"] != "failed" else "block")
        ctx.storage.remove(f"draft:{sender}")
        label = {"sent": "Sent", "simulated": "Simulated (email not configured)", "failed": "Not sent"}[result["status"]]
        return f"**{label}.** {result['detail']}"
    if typed.startswith("done "):
        items = _items(ctx)
        item_id = text.split(None, 1)[1].strip().upper()
        if items.get(item_id, {}).get("user") == sender and tracker.resolve(items, item_id, "answered"):
            _save(ctx, items)
            return f"Marked {item_id} as answered. I'll stop following up on it."
        return f"I don't have an open item {item_id} for you."
    return tracker.plan_text(_items(ctx), sender) + "\n\nSay **done <id>** when someone answers, so I stop following up."


agent.include(create_chat_protocol("teamready-tracker", chat), publish_manifest=PUBLISH)

if __name__ == "__main__":
    agent.run()
