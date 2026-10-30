"""ASI:One Chat Protocol helpers and Interactive Cards.

Every card message also carries the full answer as plain text, so the flow still
works if a client doesn't render cards.
"""
import json
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from inspect import isawaitable
from uuid import uuid4

from uagents import Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    EndSessionContent,
    MetadataContent,
    StartSessionContent,
    TextContent,
    chat_protocol_spec,
)

from . import activity
from .config import env_bool

CARDS_ON = env_bool("UNBLOCK_CARDS", True)

# A responder returns a ChatMessage, plain text, or None.
Responder = Callable[[Context, str, str], "ChatMessage | str | None | Awaitable[ChatMessage | str | None]"]


def text_message(text: str) -> ChatMessage:
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=[TextContent(type="text", text=text)])


def card_message(text: str, kind: str, payload: dict, terminal: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if CARDS_ON:
        metadata = {
            "card_protocol_version": "1",
            "requires_card_interaction": "false" if terminal else "true",
            "card_kind": kind,
            "card_payload": json.dumps(payload),
        }
        if terminal:
            metadata["is_terminal"] = "true"
        content.append(MetadataContent(type="metadata", metadata=metadata))
    return ChatMessage(timestamp=datetime.now(timezone.utc), msg_id=uuid4(), content=content)


def parse_input(text: str) -> dict:
    """Card clicks arrive as a JSON selection; typed text arrives as prose."""
    text = text.strip()
    if text.startswith("{"):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"text": text}


_MENTION = re.compile(r"^(?:\s*@agent1[0-9a-z]+[\s,:]*)+")


def strip_mentions(text: str) -> str:
    """ASI:One passes "@agent1q... " mentions through in the text; drop them from the start."""
    return _MENTION.sub("", text).strip()


def message_text(msg: ChatMessage) -> str:
    return strip_mentions("\n".join(item.text for item in msg.content if isinstance(item, TextContent)))


def create_chat_protocol(label: str, responder: Responder, person: str = "user") -> Protocol:
    """person: who a message from an unknown address is, on the activity page (user, manager, people_ops)."""
    proto = Protocol(spec=chat_protocol_spec)
    me = label.removeprefix("teamready-")

    @proto.on_message(ChatMessage)
    async def handle(ctx: Context, sender: str, msg: ChatMessage):
        await ctx.send(sender, ChatAcknowledgement(timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
        for item in msg.content:
            if isinstance(item, StartSessionContent):
                ctx.logger.info(f"{label}: session started by {sender}")
            elif isinstance(item, EndSessionContent):
                ctx.logger.info(f"{label}: session ended by {sender}")
        text = message_text(msg)
        if not text:
            return
        who = activity.name_for(sender, person)
        activity.log(who, activity.said(text), to=me, kind="message")
        try:
            reply = responder(ctx, sender, text)
            if isawaitable(reply):
                reply = await reply
        except Exception as exc:  # never leave the user hanging
            ctx.logger.exception(f"{label}: error handling message")
            reply = f"Sorry, something went wrong on my side ({type(exc).__name__}). Nothing was sent. Please try again."
        if reply is None:
            return
        out = reply if isinstance(reply, ChatMessage) else text_message(str(reply))
        cards = [c for c in out.content if getattr(c, "type", "") == "metadata"]
        first = (message_text(out).strip().splitlines() or [""])[0]
        activity.log(me, ("[card] " if cards else "") + first, to=who, kind="message")
        await ctx.send(sender, out)

    @proto.on_message(ChatAcknowledgement)
    async def ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
        pass

    return proto
