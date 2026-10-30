"""Canary New Hires, locally with no ASI:One: People Ops chats with teamready-canary,
which sends three synthetic new hires through the docs via the real knowledge agent.

    UNBLOCK_LLM=extractive python scripts/local_canary_demo.py   # no API key needed
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents"))
os.environ.setdefault("UNBLOCK_TODAY", "2026-10-17")
os.environ["AGENTVERSE_API_KEY"] = ""  # always local
os.environ["CANARY_INTERVAL_HOURS"] = "100000"  # no scheduled run: this script starts it

from common import address  # noqa: E402
from uagents import Agent, Bureau, Context  # noqa: E402
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage  # noqa: E402

from canary_agent import agent as canary_agent  # noqa: E402
from knowledge_agent import agent as knowledge  # noqa: E402
from unblock import canary  # noqa: E402
from unblock.chat import message_text, text_message  # noqa: E402

ops = Agent(name="demo-people-ops", seed="unblock local canary demo people ops")
got: asyncio.Queue = asyncio.Queue()


@ops.on_message(ChatMessage)
async def reply(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=msg.timestamp, acknowledged_msg_id=msg.msg_id))
    print(f"\n{'=' * 78}\nCANARY -> people ops\n{'-' * 78}\n{message_text(msg)}", flush=True)
    await got.put(1)


@ops.on_message(ChatAcknowledgement)
async def ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


@ops.on_event("startup")
async def go(ctx: Context):
    await asyncio.sleep(2)
    for text, replies in (("run", 2), ("fixes", 1), (None, 1)):
        if text is None:  # approve the first ready fix
            fix = next(f for f in canary.latest()["fixes"] if f["status"] == "ready")
            text = f"approve {fix['id']}"
        print(f"\n>>> people ops says: {text}", flush=True)
        await ctx.send(address("canary"), text_message(text))
        for _ in range(replies):
            await asyncio.wait_for(got.get(), timeout=600)
    print("\nCanary demo finished.", flush=True)
    os._exit(0)


bureau = Bureau(port=8011, endpoint=["http://127.0.0.1:8011/submit"])
for a in (knowledge, canary_agent, ops):
    bureau.add(a)

if __name__ == "__main__":
    bureau.run()
