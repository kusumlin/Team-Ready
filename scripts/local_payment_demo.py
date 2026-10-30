"""People Ops buys the full Friction Map report through the Payment Protocol (local, no ASI:One).

    UNBLOCK_LLM=extractive python scripts/local_payment_demo.py
"""
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "agents"))
os.environ.setdefault("UNBLOCK_TODAY", "2026-10-17")
os.environ["AGENTVERSE_API_KEY"] = ""

from common import address  # noqa: E402
from uagents import Agent, Bureau, Context  # noqa: E402
from uagents_core.contrib.protocols.chat import ChatAcknowledgement, ChatMessage  # noqa: E402
from uagents_core.contrib.protocols.payment import CommitPayment, CompletePayment, RequestPayment  # noqa: E402

from insights_agent import agent as insights  # noqa: E402
from unblock.chat import message_text, text_message  # noqa: E402

buyer = Agent(name="demo-people-ops", seed="unblock local demo people ops")
got = asyncio.Queue()


@buyer.on_message(ChatMessage)
async def chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(timestamp=msg.timestamp, acknowledged_msg_id=msg.msg_id))
    print(f"\n--- insights -> people ops ---\n{message_text(msg)}")
    await got.put("chat")


@buyer.on_message(ChatAcknowledgement)
async def ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass


@buyer.on_message(RequestPayment)
async def pay(ctx: Context, sender: str, msg: RequestPayment):
    f = msg.accepted_funds[0]
    print(f"\n--- payment request: {f.amount} {f.currency} ({f.payment_method}) ref {msg.reference} ---")
    await ctx.send(sender, CommitPayment(funds=f, recipient=msg.recipient, transaction_id="demo-tx-" + (msg.reference or ""), reference=msg.reference))


@buyer.on_message(CompletePayment)
async def complete(ctx: Context, sender: str, msg: CompletePayment):
    print(f"\n--- payment complete: {msg.transaction_id} ---")


@buyer.on_event("startup")
async def go(ctx: Context):
    await asyncio.sleep(2)
    # With CREAO on, the drafted fix arrives as a third message when the Doc Steward's run finishes.
    from unblock import creao
    for text, replies in (("friction map", 1), ("full report", 3 if creao.enabled() else 2), ("approve", 1)):
        print(f"\n>>> people ops says: {text}")
        await ctx.send(address("insights"), text_message(text))
        for _ in range(replies):
            await asyncio.wait_for(got.get(), timeout=900)
    sys.stdout.flush()
    os._exit(0)


bureau = Bureau(port=8011, endpoint=["http://127.0.0.1:8011/submit"])
bureau.add(insights)
bureau.add(buyer)

if __name__ == "__main__":
    bureau.run()
