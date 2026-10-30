"""teamready-knowledge: answers from approved docs, and only shows verified claims.

Usable directly from ASI:One ("How do I deploy to staging?") and by the
orchestrator through KnowledgeRequest.
"""
import asyncio

from common import PUBLISH, create_agent  # noqa: F401  (also fixes sys.path)
from uagents import Context

from unblock import activity, render
from unblock.chat import create_chat_protocol
from unblock.data import load_people, load_user
from unblock.risk import assess
from unblock.knowledge import answer
from unblock.llm import get_llm_or_unavailable
from unblock.models import KnowledgeRequest, KnowledgeResponse

agent = create_agent(
    "knowledge", "teamready-knowledge",
    "Answers new-hire questions only from approved company docs. Every claim is checked word for word "
    "against its source; anything unsupported is blocked. Flags stale and conflicting docs.",
    ["rag", "verification"],
)


async def run(question: str, user: dict) -> dict:
    return (await asyncio.to_thread(answer, question, user, get_llm_or_unavailable())).to_dict()


@agent.on_message(KnowledgeRequest, replies=KnowledgeResponse)
async def on_request(ctx: Context, sender: str, msg: KnowledgeRequest):
    activity.log("knowledge", "Searching approved docs and checking every claim against its source")
    result = await run(msg.question, msg.user)
    for line in result.get("trace", []):
        blocked = any(w in line.lower() for w in ("blocked", "stale", "no approved doc", "unavailable", "disagree"))
        activity.log("knowledge", line, kind="block" if blocked else "step")
    await ctx.send(sender, KnowledgeResponse(request_id=msg.request_id, result=result))


async def chat(ctx: Context, sender: str, text: str):
    risk = assess(text)
    if risk.level == "stop":
        return render.stop_text(risk.__dict__, load_people()[risk.human_id])
    result = await run(text, load_user())
    if risk.level == "approval":
        return (render.answer_text(result) + f"\n\n{risk.reason} Ask the TeamReady orchestrator to prepare the request for your manager.")
    if result["decision"] == "answer":
        return render.answer_text(result)
    return render.answer_text(result) + f"\n\n{result['route_reason']} Ask the TeamReady orchestrator to find the right person."


agent.include(create_chat_protocol("teamready-knowledge", chat), publish_manifest=PUBLISH)

if __name__ == "__main__":
    agent.run()
