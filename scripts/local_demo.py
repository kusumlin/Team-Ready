"""Run the full demo locally, with no ASI:One: a test user and a test manager chat
with the real agents over uAgents messages and print every reply.

    UNBLOCK_LLM=extractive python scripts/local_demo.py   # no API key needed
    python scripts/local_demo.py                          # uses the Anthropic model

Steps: a verified answer, a stale-doc flag, a question the docs can't answer
(routed to a person, then "wrong person", then the Guardian blocking a password), a Tracker follow-up when nobody
answers, an access request approved by the manager agent, and the high-impact stop.
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents"))
os.environ.setdefault("UNBLOCK_TODAY", "2026-10-17")
os.environ["AGENTVERSE_API_KEY"] = ""  # always local
os.environ.setdefault("TRACKER_DUE_MINUTES", "0.05")   # 3 seconds, so the demo shows a follow-up
os.environ.setdefault("TRACKER_CHECK_SECONDS", "2")

from common import address  # noqa: E402
from uagents import Agent, Bureau, Context  # noqa: E402
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage  # noqa: E402

from insights_agent import agent as insights  # noqa: E402
from knowledge_agent import agent as knowledge  # noqa: E402
from manager_agent import agent as manager  # noqa: E402
from orchestrator import agent as orchestrator  # noqa: E402
from routing_agent import agent as routing  # noqa: E402
from tracker_agent import agent as tracker  # noqa: E402
from unblock.chat import message_text, text_message  # noqa: E402
from unblock.routing import reset_feedback  # noqa: E402

SCRIPT = [
    ("user", "How do I set up my dev environment?"),
    ("user", "How do I deploy to staging?"),
    ("user", "reject"),
    ("user", "How many vacation days do I get?"),
    ("user", "wrong person"),
    ("user", "edit: Hi Sofia, quick question about vacation days. My password is hunter22 if you need to check my account."),
    ("user", "edit: Hi Sofia, how many vacation days do new US hires get in their first year? Thanks, Maya"),
    ("user", "approve"),
    ("wait", "the Tracker notices no reply and offers a follow-up"),
    ("tracker", "approve"),
    ("user", "I need access to the analytics dashboard"),
    ("user", "approve"),
    ("manager", "pending"),
    ("manager", "approve"),
    ("user", "Can the AI decide whether I deserve a promotion?"),
]

user = Agent(name="demo-new-hire", seed="unblock local demo user")
boss = Agent(name="demo-manager", seed="unblock local demo manager")
queue: asyncio.Queue = asyncio.Queue()
done = asyncio.Event()


def show(who: str, text: str) -> None:
    print(f"\n{'=' * 78}\n{who}\n{'-' * 78}\n{text}")


NAMES = {address("orchestrator"): "UNBLOCK", address("manager"): "MANAGER AGENT", address("tracker"): "TRACKER"}


for a, to in ((user, "new hire"), (boss, "manager")):
    @a.on_message(ChatMessage)
    async def got(ctx: Context, sender: str, msg: ChatMessage, to=to):
        await ctx.send(sender, ChatAcknowledgement(timestamp=msg.timestamp, acknowledged_msg_id=msg.msg_id))
        cards = [c for c in msg.content if getattr(c, "type", "") == "metadata"]
        src = NAMES.get(sender, sender[:12])
        show(f"{src} -> {to}" + (f"  [card: {cards[0].metadata.get('card_kind')}]" if cards else ""), message_text(msg))
        await queue.put(src)

    @a.on_message(ChatAcknowledgement)
    async def ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass


async def expect(src: str, timeout: float = 120) -> None:
    """Wait for a reply from one agent; other agents' messages are shown but don't count."""
    end = asyncio.get_event_loop().time() + timeout
    while True:
        left = end - asyncio.get_event_loop().time()
        if left <= 0:
            show("TIMEOUT", f"no reply from {src}")
            return
        try:
            if await asyncio.wait_for(queue.get(), timeout=left) == src:
                return
        except asyncio.TimeoutError:
            show("TIMEOUT", f"no reply from {src}")
            return


@user.on_event("startup")
async def run_script(ctx: Context):
    reset_feedback()
    await asyncio.sleep(2)
    targets = {"user": ("orchestrator", "UNBLOCK"), "tracker": ("tracker", "TRACKER"), "manager": ("manager", "MANAGER AGENT")}
    for who, text in SCRIPT:
        if who == "wait":
            show("(waiting)", text)
            await expect("TRACKER", 60)
            continue
        show(f"{'NEW HIRE' if who != 'manager' else 'MANAGER'} -> {targets[who][1]}", text)
        agent_name, src = targets[who]
        sender_ctx = boss_ctx if who == "manager" else ctx
        await sender_ctx.send(address(agent_name), text_message(text))
        await expect(src)
        if who == "manager" and text == "approve":
            await expect("UNBLOCK", 60)  # the new hire gets the decision
    print("\nDemo finished.", flush=True)
    os._exit(0)


boss_ctx = None


@boss.on_event("startup")
async def keep(ctx: Context):
    global boss_ctx
    boss_ctx = ctx


bureau = Bureau(port=8010, endpoint=["http://127.0.0.1:8010/submit"])
for a in (orchestrator, knowledge, routing, manager, insights, tracker, user, boss):
    bureau.add(a)

if __name__ == "__main__":
    bureau.run()
