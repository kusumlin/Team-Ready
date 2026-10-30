"""teamready-routing: finds the right person to ask, fairly, and learns from feedback.

Usable directly from ASI:One ("Who should I ask about VPN problems?") and by the
orchestrator through RoutingRequest and WrongPersonFeedback.
"""
import re

from common import PUBLISH, create_agent  # noqa: F401
from uagents import Context

from unblock import activity
from unblock.chat import create_chat_protocol
from unblock.data import load_user
from unblock.models import RoutingRequest, RoutingResponse, WrongPersonFeedback
from unblock.routing import rank, record_wrong_person

agent = create_agent(
    "routing", "teamready-routing",
    "Finds who a new hire should ask, with a transparent score (50% skills, 30% team, 20% availability), "
    "fairness rotation across qualified people, and learning from 'wrong person' feedback.",
    ["routing", "fairness"],
)


@agent.on_message(RoutingRequest, replies=RoutingResponse)
async def on_request(ctx: Context, sender: str, msg: RoutingRequest):
    result = rank(msg.question, msg.user, msg.retrieved_doc_ids or None, set(msg.exclude))
    activity.log("routing", "Scored people: 50% skills, 30% team, 20% availability; no protected characteristics")
    if result.rotation_note:
        activity.log("routing", "Fairness: " + result.rotation_note, kind="check")
    await ctx.send(sender, RoutingResponse(request_id=msg.request_id, result=result.to_dict()))


@agent.on_message(WrongPersonFeedback)
async def on_feedback(ctx: Context, sender: str, msg: WrongPersonFeedback):
    count = record_wrong_person(msg.person_id, msg.topic_key)
    activity.log("routing", f"Learned: lowered that person's score for this topic ({count}x)", kind="step")
    ctx.logger.info(f"feedback: {msg.person_id} wrong for {msg.topic_key} ({count}x)")


async def chat(ctx: Context, sender: str, text: str):
    question = re.sub(r"^(who should i ask about|who do i ask about|who owns)\s*", "", text.strip(), flags=re.I) or text
    result = rank(question, load_user())
    if not result.chosen:
        return "I couldn't find anyone who clearly owns this. Try #ask-people-ops."
    c = result.chosen
    f = c.factors
    lines = [f"**Ask {c.name}**, {c.role} ({c.team}).",
             f"Why: {'; '.join(c.reasons)}.",
             f"Score {c.score:.2f} = 50% skills ({f['skill']}) + 30% team ({f['team']}) + 20% availability ({f['availability']})"
             + (f" - feedback penalty {f['penalty']}" if f["penalty"] else "") + "."]
    if result.rotation_note:
        lines.append(f"Fairness: {result.rotation_note}")
    if result.alternatives:
        lines.append("Also good: " + ", ".join(f"{a.name} ({a.score:.2f})" for a in result.alternatives) + ".")
    lines.append("I never use age, gender, race, nationality or other protected characteristics.")
    return "\n".join(lines)


agent.include(create_chat_protocol("teamready-routing", chat), publish_manifest=PUBLISH)

if __name__ == "__main__":
    agent.run()
