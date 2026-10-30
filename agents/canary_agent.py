"""teamready-canary: synthetic new hires who onboard before real people do.

Every CANARY_INTERVAL_HOURS (and whenever someone says "run"), three fictional
new hires walk the onboarding checklist and their role's tasks. Each step is a
real question to the teamready-knowledge agent, through the same verified-answer
pipeline a new hire gets. Where a canary can't do a step from the docs, that's a
wall: checked against the Friction Map (already hit by real hires, or predicted),
with a fix for the doc owner. Fixes go out only after a person approves them.

Chat (ASI:One): "run", "report", "fixes", "approve F1".
"""
import asyncio
import re
import time
import uuid
from datetime import datetime, timezone

from common import PUBLISH, address, create_agent
from uagents import Context

from unblock import activity, canary
from unblock import knowledge as knowledge_lib
from unblock.chat import card_message, create_chat_protocol, parse_input
from unblock.config import env
from unblock.llm import get_llm_or_unavailable
from unblock.models import KnowledgeRequest, KnowledgeResponse

TIMEOUT = 45
INTERVAL_HOURS = float(env("CANARY_INTERVAL_HOURS", "24"))

agent = create_agent(
    "canary", "teamready-canary",
    "Canary New Hires: synthetic new hires who try your onboarding docs before real people do. They walk the "
    "checklist step by step, find the walls (stale docs, missing how-tos, dead ends), check which ones real new "
    "hires already hit, and draft fixes for the doc owners. Say 'run', 'report' or 'fixes'.",
    ["canary", "docs-ci", "onboarding-qa"],
)
_running: dict = {}
_one_at_a_time = asyncio.Lock()


async def _ask(ctx: Context, question: str, user: dict) -> dict:
    """Ask the knowledge agent, exactly as the orchestrator does; run the same check locally if it doesn't answer."""
    req = KnowledgeRequest(request_id=uuid.uuid4().hex, question=question, user=user)
    async with _one_at_a_time:  # send_and_receive matches replies by sender, so keep one request open at a time
        activity.log("canary", f"{user['name']}: {question[:80]}", to="knowledge", kind="message")
        try:
            resp, status = await ctx.send_and_receive(address("knowledge"), req, KnowledgeResponse, timeout=TIMEOUT)
        except Exception as exc:
            resp, status = None, exc
    if isinstance(resp, KnowledgeResponse):
        return resp.result
    ctx.logger.warning(f"knowledge agent unavailable ({status}); checking locally")
    return (await asyncio.to_thread(knowledge_lib.answer, question, user, get_llm_or_unavailable())).to_dict()


async def _run(ctx: Context, trigger: str) -> dict | None:
    if _running.get("on"):
        return None
    _running["on"] = True
    try:
        return await canary.run(lambda q, u: _ask(ctx, q, u), trigger)
    finally:
        _running["on"] = False


def _allowed(sender: str) -> bool:
    """Who may send a fix to a doc owner: CANARY_APPROVERS, else the locked manager address(es); empty = demo mode."""
    allowed = [a.strip() for a in (env("CANARY_APPROVERS") or env("MANAGER_ALLOWED_SENDERS")).split(",") if a.strip()]
    return not allowed or sender in allowed


def _report_card(run: dict):
    s = run["summary"]
    rows = [{"label": "Walls found", "value": f"{s['walls']} ({s['confirmed']} real hires already hit, {s['predicted']} predicted)"}]
    rows += [{"label": f"{w['id']} {w['label']}" + (" (predicted)" if w["predicted"] else f" ({w['humans_hit']} real blockers)"),
              "value": w["headline"]} for w in run["walls"][:5]]
    return card_message(canary.report_text(run), "detail", {
        "title": f"Canary run {run['run_id']}: {s['canaries']} synthetic new hires, {s['steps']} steps",
        "summary_rows": rows,
        "ctas": [{"label": "Review the fixes", "primary": True, "selection": {"action": "ub_fixes"}}],
    })


_STARTED = time.time()


@agent.on_interval(period=600.0)
async def scheduled(ctx: Context):
    # Never right at startup (that's when people are testing the other agents): the first scheduled run waits a full
    # interval, or comes INTERVAL after the last run.
    last = canary.latest()
    since = (datetime.now(timezone.utc) - datetime.fromisoformat(last["started"])).total_seconds() if last else time.time() - _STARTED
    if since < INTERVAL_HOURS * 3600:
        return
    await _run(ctx, "scheduled")


async def chat(ctx: Context, sender: str, text: str):
    sel = parse_input(text)
    action = str(sel.get("action", "")).lower().removeprefix("ub_")
    t = text.strip().lower()
    m = re.search(r"\bapprove\s+(F\d+)\b", text, re.I)
    if m:
        if not _allowed(sender):
            return "Only People Ops (CANARY_APPROVERS) can send fixes to doc owners."
        run = canary.latest()
        if not run:
            return "There's no canary run yet. Say **run**."
        out = canary.approve(run["run_id"], m.group(1))
        return ("**Sent.** " if out.get("status") == "sent" else "**Simulated** (email not set up). " if out["ok"] else "") + out["detail"]
    # Card clicks routed through the ASI:One planner arrive as sentences mentioning the selection id.
    if not action and re.search(r"\bub_fixes\b", t):
        action = "fixes"
    words = set(re.findall(r"[a-z]+", t))
    if action == "fixes" or (words & {"fix", "fixes"} and len(words) <= 5):
        run = canary.latest()
        return canary.fixes_text(run) if run else "There's no canary run yet. Say **run**."
    if words & {"run", "start", "go", "test"} and len(words) <= 6:
        await ctx.send(sender, card_message("Starting a canary run: 3 synthetic new hires (a Data Analyst, a Backend Engineer and "
                                            "a Product Designer in the EU) are walking the onboarding docs now. It takes a minute or two.",
                                            "detail", {"title": "Canary run started", "summary_rows": [], "ctas": []}))
        run = await _run(ctx, "chat")
        if not run:
            return "A canary run is already going. Say **report** in a minute."
        return _report_card(run)
    if words & {"report", "latest", "status", "results"} and len(words) <= 6:
        run = canary.latest()
        if not run:
            return "There's no canary run yet. Say **run**."
        return _report_card(run) if run["status"] == "done" else "The canary run is still going. Try again in a minute."
    return ("I'm **teamready-canary**. I send synthetic new hires through your onboarding docs before real people start, "
            "and tell you where they'd get stuck.\n\nSay **run** to start a run, **report** for the latest results, "
            "**fixes** to review the drafted fixes, or **approve F1** to send one to its doc owner.")


agent.include(create_chat_protocol("teamready-canary", chat, person="people_ops"), publish_manifest=PUBLISH)

if __name__ == "__main__":
    agent.run()
