"""teamready-manager: the human approval gate for high-impact requests.

The orchestrator never grants access. It sends an ApprovalRequest here, and a
human manager approves or rejects it from ASI:One. The decision goes back to the
orchestrator, which tells the new hire.

Set MANAGER_ALLOWED_SENDERS to the manager's ASI:One address(es) so only they can
decide. Set MANAGER_CHAT_ADDRESS to push new requests to the manager as a card.
"""
import json
import re

from common import PUBLISH, address, create_agent
from uagents import Context

from unblock import activity
from unblock.chat import card_message, create_chat_protocol, parse_input
from unblock.config import env
from unblock.data import load_people, load_user
from unblock.models import ApprovalDecision, ApprovalRequest

agent = create_agent(
    "manager", "teamready-manager",
    "Human approval gate for new-hire access requests. Managers review the request, the evidence and the "
    "business reason, then approve or reject. TeamReady never grants access by itself.",
    ["approval", "human-in-the-loop"],
)


def _manager_name() -> str:
    return load_people()[load_user()["manager_id"]]["name"]


def _allowed(sender: str) -> bool:
    allowed = [a.strip() for a in env("MANAGER_ALLOWED_SENDERS").split(",") if a.strip()]
    return not allowed or sender in allowed


def _pending(ctx: Context) -> dict:
    return json.loads(ctx.storage.get("pending") or "{}")


def _save(ctx: Context, pending: dict) -> None:
    ctx.storage.set("pending", json.dumps(pending))


def _card(req: dict):
    text = "\n".join([
        f"**Approval request {req['request_id']}**: {req['category']}",
        f"From: {req['requester']['name']}, {req['requester']['role']} ({req['requester']['team']})",
        f"Subject: {req['subject']}", "", req["body"], "",
        "Evidence TeamReady verified in approved docs:", *[f"- {e}" for e in req["evidence"] or ["none"]], "",
        f"Reply **approve {req['request_id']}** or **reject {req['request_id']} <reason>**.",
    ])
    payload = {
        "title": f"Approve {req['category']} for {req['requester']['name']}?",
        "summary_rows": [
            {"label": "Requester", "value": f"{req['requester']['name']}, {req['requester']['role']}"},
            {"label": "Request", "value": req["subject"]},
            {"label": "Business reason", "value": req["body"][:500]},
            {"label": "Evidence", "value": "; ".join(req["evidence"])[:500] or "none"},
            {"label": "Note", "value": "TeamReady prepared this. Only you can approve it."},
        ],
        "approve_cta": {"label": "Approve", "primary": True, "selection": {"action": "ub_approve", "request_id": req["request_id"]}},
        "reject_cta": {"label": "Reject", "selection": {"action": "ub_reject", "request_id": req["request_id"]}},
    }
    return card_message(text, "review", payload)


@agent.on_message(ApprovalRequest)
async def on_request(ctx: Context, sender: str, msg: ApprovalRequest):
    if sender != address("orchestrator"):
        ctx.logger.warning(f"ignored an approval request from {sender}: only the orchestrator can file requests")
        return
    pending = _pending(ctx)
    pending[msg.request_id] = msg.dict()
    _save(ctx, pending)
    ctx.logger.info(f"new approval request {msg.request_id} from {msg.requester.get('name')}")
    activity.log("manager", f"{msg.request_id} is waiting for the manager. Only a person can approve it", kind="step")
    push_to = env("MANAGER_CHAT_ADDRESS")
    if push_to:
        await ctx.send(push_to, _card(pending[msg.request_id]))


async def chat(ctx: Context, sender: str, text: str):
    ctx.logger.info(f"message from {sender} (add this address to MANAGER_ALLOWED_SENDERS to make it the only approver)")
    pending = _pending(ctx)
    sel = parse_input(text)
    action = str(sel.get("action", "")).lower().removeprefix("ub_")
    request_id = str(sel.get("request_id", ""))
    note = ""
    planner = re.search(r"\bub_(approve|reject)\b.*?\b(AR-[A-Z0-9]+)|\b(AR-[A-Z0-9]+)\b.*?\bub_(approve|reject)\b", text, re.I)
    if not action and planner:  # a card click routed through the ASI:One planner
        action = (planner.group(1) or planner.group(4)).lower()
        request_id = (planner.group(2) or planner.group(3)).upper()
    if not action:
        m = re.match(r"^\s*(approve|reject)\s+(AR-[A-Z0-9]+)\s*(.*)$", text, re.I)
        if m:
            action, request_id, note = m.group(1).lower(), m.group(2).upper(), m.group(3).strip()
        elif text.strip().lower() in ("approve", "reject") and len(pending) == 1:
            action, request_id = text.strip().lower(), next(iter(pending))
    if action in ("approve", "reject"):
        if not _allowed(sender):
            return "Only the configured manager can approve or reject requests."
        req = pending.pop(request_id, None)
        if not req:
            return f"I don't have a pending request {request_id}."
        _save(ctx, pending)
        decision = "approved" if action == "approve" else "rejected"
        await ctx.send(req["reply_to"], ApprovalDecision(request_id=request_id, decision=decision, note=note, approver=_manager_name()))
        return f"Done: {request_id} {decision}. I've told the orchestrator, which will let {req['requester']['name']} know."
    if not pending:
        demo = "" if env("MANAGER_ALLOWED_SENDERS") else "\n(Demo mode: anyone can act as the manager. Set MANAGER_ALLOWED_SENDERS to lock this down.)"
        return "No requests are waiting for your approval." + demo
    oldest = next(iter(pending.values()))
    reply = _card(oldest)
    if len(pending) > 1:
        reply.content[0].text += f"\n\n{len(pending) - 1} more waiting: " + ", ".join(list(pending)[1:])
    return reply


agent.include(create_chat_protocol("teamready-manager", chat, person="manager_person"), publish_manifest=PUBLISH)

if __name__ == "__main__":
    agent.run()
