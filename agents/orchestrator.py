"""teamready-orchestrator: the ASI:One front door.

Runs the risk gate, asks the knowledge and routing agents, drafts actions, shows
Interactive Cards, executes approved actions, and relays manager decisions.
If a specialist agent doesn't answer in time, it runs the same step locally and
says so in the trust trace, so the user is never left waiting.
"""
import asyncio
import json
import uuid

from common import PUBLISH, address, create_agent
from uagents import Context

from unblock import activity
from unblock import knowledge as knowledge_lib
from unblock import routing as routing_lib
from unblock.actions import send_email
from unblock.chat import card_message, create_chat_protocol, parse_input, text_message
from unblock.config import DATA_DIR
from unblock.flow import Orchestrator, Reply
from unblock.friction import build_map, log_live_event
from unblock.llm import get_llm, get_llm_or_unavailable
from unblock.models import (
    ApprovalDecision,
    ApprovalRequest,
    FrictionEvent,
    KnowledgeRequest,
    KnowledgeResponse,
    RoutingRequest,
    RoutingResponse,
    TrackItem,
    TrackResolved,
    WrongPersonFeedback,
)

TIMEOUT = 45          # knowledge includes a model call
ROUTING_TIMEOUT = 15  # routing is pure code

agent = create_agent(
    "orchestrator", "teamready-orchestrator",
    "TeamReady does a new hire's onboarding: say 'do my checklist' and it joins Slack channels, enrolls training, "
    "books your 1:1, opens IT tickets and files access forms once your manager approves. Every action waits for "
    "your OK; answers are verified against approved docs.",
    ["orchestrator", "asi-one", "chat", "new-hire", "employee-onboarding", "hr", "it-help", "employee-experience", "first-week", "takes-action"],
)


class Store:
    def __init__(self, ctx: Context):
        self.ctx = ctx

    def get(self, key: str) -> dict | None:
        raw = self.ctx.storage.get(f"s:{key}")
        return json.loads(raw) if raw else None

    def set(self, key: str, value: dict) -> None:
        self.ctx.storage.set(f"s:{key}", json.dumps(value))


class Services:
    """Calls to the other agents, each with a local fallback."""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    async def knowledge(self, question: str, user: dict) -> dict:
        req = KnowledgeRequest(request_id=uuid.uuid4().hex, question=question, user=user)
        activity.log("orchestrator", "Check the approved docs for this question", to="knowledge", kind="message")
        try:
            resp, status = await self.ctx.send_and_receive(address("knowledge"), req, KnowledgeResponse, timeout=TIMEOUT)
        except Exception as exc:  # network errors
            resp, status = None, exc
        if isinstance(resp, KnowledgeResponse):
            activity.log("knowledge", _knowledge_summary(resp.result), to="orchestrator", kind="message")
            return resp.result
        activity.log("orchestrator", "Knowledge agent didn't answer in time; running the same check locally", kind="block")
        self.ctx.logger.warning(f"knowledge agent unavailable ({status}); answering locally")
        result = (await asyncio.to_thread(knowledge_lib.answer, question, user, get_llm_or_unavailable())).to_dict()
        result["trace"].insert(0, "Knowledge agent didn't respond in time, so I ran the same check locally")
        return result

    async def routing(self, question: str, user: dict, doc_ids: list[str], exclude: list[str]) -> dict:
        req = RoutingRequest(request_id=uuid.uuid4().hex, question=question, user=user, retrieved_doc_ids=doc_ids, exclude=exclude)
        activity.log("orchestrator", "Who's the best person to help?" + (f" (skip {len(exclude)} already tried)" if exclude else ""), to="routing", kind="message")
        try:
            resp, status = await self.ctx.send_and_receive(address("routing"), req, RoutingResponse, timeout=ROUTING_TIMEOUT)
        except Exception as exc:
            resp, status = None, exc
        if isinstance(resp, RoutingResponse):
            activity.log("routing", _routing_summary(resp.result), to="orchestrator", kind="message")
            return resp.result
        activity.log("orchestrator", "Routing agent didn't answer in time; ranking locally", kind="block")
        self.ctx.logger.warning(f"routing agent unavailable ({status}); ranking locally")
        return routing_lib.rank(question, user, doc_ids or None, set(exclude)).to_dict()

    async def wrong_person(self, person_id: str, topic_key: str) -> None:
        activity.log("orchestrator", "Feedback: that person couldn't help, rank them lower for this topic", to="routing", kind="message")
        status = await self.ctx.send(address("routing"), WrongPersonFeedback(person_id=person_id, topic_key=topic_key))
        if getattr(status, "status", None) and str(status.status).lower().endswith("failed"):
            routing_lib.record_wrong_person(person_id, topic_key)

    async def request_approval(self, req: dict) -> str:
        msg = ApprovalRequest(request_id=req["request_id"], category=req["category"], requester=req["requester"],
                              subject=req["subject"], body=req["body"], evidence=req["evidence"], reply_to=str(self.ctx.agent.address))
        activity.log("orchestrator", f"Approval request {req['request_id']} ({req['category']}) for the manager", to="manager", kind="message")
        status = await self.ctx.send(address("manager"), msg)
        detail = str(getattr(status, "status", "")).lower()
        if "fail" in detail:
            return "The approval agent didn't confirm delivery yet; I'll keep the request on file."
        return "Delivered."

    async def friction_event(self, doc_id: str, docs_read: list[str], resolved: bool) -> None:
        if not doc_id:
            return
        activity.log("orchestrator", "Anonymous blocker logged (doc path only, no names or text)", to="insights", kind="message")
        status = await self.ctx.send(address("insights"), FrictionEvent(doc_id=doc_id, docs_read=docs_read, resolved=resolved))
        if "fail" in str(getattr(status, "status", "")).lower():
            log_live_event(doc_id, docs_read, resolved)

    async def track(self, item_id: str, user: str, kind: str, summary: str, to_name: str, to_email: str) -> None:
        activity.log("orchestrator", f"Track {item_id}: waiting for {to_name} to reply", to="tracker", kind="message")
        await self.ctx.send(address("tracker"), TrackItem(item_id=item_id, user=user, kind=kind, summary=summary,
                                                          to_name=to_name, to_email=to_email))

    async def track_resolved(self, item_id: str, outcome: str) -> None:
        await self.ctx.send(address("tracker"), TrackResolved(item_id=item_id, outcome=outcome))

    async def friction_map(self) -> dict:
        return build_map()

    async def send_email(self, to: str, subject: str, body: str, sender: str, ics: str | None) -> dict:
        result = await asyncio.to_thread(send_email, to, subject, body, sender, ics)
        label = {"sent": "Email sent", "simulated": "Email simulated (no SMTP set up)", "failed": "Email failed"}[result["status"]]
        activity.log("orchestrator", f"{label}: \"{subject}\" after your approval", to="people", kind="done" if result["status"] != "failed" else "block")
        return result

    async def source_feedback(self, source_ids: list[str]) -> None:
        path = DATA_DIR / "runtime" / "source_feedback.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        log = json.loads(path.read_text()) if path.exists() else []
        log.append({"source_ids": source_ids, "reason": "user_flagged", "message_text_stored": False})
        path.write_text(json.dumps(log, indent=1))


def _knowledge_summary(r: dict) -> str:
    conf = (r.get("confidence") or {}).get("score")
    verdict = "Answer verified" if r.get("decision") == "answer" else "No reliable answer: route to a person"
    return verdict + (f", confidence {conf}/100" if conf is not None else "")


def _routing_summary(r: dict) -> str:
    c = r.get("chosen")
    if not c:
        return "Nobody clearly owns this; fall back to People Ops"
    return f"Ask {c['name']} ({c['role']}), score {c['score']:.2f}: " + "; ".join(c.get("reasons", [])[:2])


def _to_message(reply: Reply):
    if reply.kind and reply.payload:
        return card_message(reply.text, reply.kind, reply.payload, terminal=reply.terminal)
    return text_message(reply.text)


async def chat(ctx: Context, sender: str, text: str):
    flow = Orchestrator(Services(ctx), Store(ctx), get_llm)
    selection = parse_input(text)
    plain = selection.get("text", "") if "text" in selection else ""
    reply = await flow.handle(sender, plain or text, selection if "text" not in selection else {})
    return _to_message(reply)


@agent.on_message(ApprovalDecision)
async def on_decision(ctx: Context, sender: str, msg: ApprovalDecision):
    if sender != address("manager"):
        ctx.logger.warning(f"ignored an approval decision from {sender}: only the manager agent can decide")
        return
    activity.log("manager", f"{msg.approver} {msg.decision} {msg.request_id}", to="orchestrator", kind="message")
    flow = Orchestrator(Services(ctx), Store(ctx), get_llm)
    out = await flow.on_decision(msg.dict())
    if out:
        user_address, reply = out
        await ctx.send(user_address, _to_message(reply))


agent.include(create_chat_protocol("teamready-orchestrator", chat), publish_manifest=PUBLISH)

if __name__ == "__main__":
    agent.run()
