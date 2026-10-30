"""Shared agent setup: seeds, addresses, Agentverse mailbox mode."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncio  # noqa: E402

# Python 3.14 no longer creates an event loop on demand, and uagents.Agent()
# asks for one when it is constructed. Make sure one exists before any agent is
# built. On Python 3.11-3.13 a loop already exists, so this changes nothing.
try:
    asyncio.get_event_loop_policy().get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from uagents import Agent  # noqa: E402
from uagents.crypto import Identity  # noqa: E402

from unblock import activity  # noqa: E402
from unblock.config import env, env_bool  # noqa: E402

PUBLISH = bool(env("AGENTVERSE_API_KEY"))
READMES = Path(__file__).resolve().parent / "readmes"

# name -> (seed env var, default seed, local port)
AGENTS = {
    "orchestrator": ("ORCHESTRATOR_SEED", "unblock orchestrator demo seed CHANGE ME", 8100),
    "knowledge": ("KNOWLEDGE_SEED", "unblock knowledge demo seed CHANGE ME", 8101),
    "routing": ("ROUTING_SEED", "unblock routing demo seed CHANGE ME", 8102),
    "manager": ("MANAGER_SEED", "unblock manager demo seed CHANGE ME", 8103),
    "insights": ("INSIGHTS_SEED", "unblock insights demo seed CHANGE ME", 8104),
    "tracker": ("TRACKER_SEED", "unblock tracker demo seed CHANGE ME", 8105),
    "canary": ("CANARY_SEED", "unblock canary demo seed CHANGE ME", 8106),
}


def seed(name: str) -> str:
    seed_env, default, _ = AGENTS[name]
    return env(seed_env, default)


def address(name: str) -> str:
    return Identity.from_seed(seed(name), 0).address


activity.NAMES.update({address(n): n for n in AGENTS})


def _auto_connect(agent: Agent, port: int, key: str) -> None:
    """Connect this agent's Agentverse mailbox at startup, the same call the
    Agent Inspector's "Connect" button makes, so a server needs no browser step.
    Works when each agent runs as its own process (scripts/run_all.sh)."""
    import asyncio
    import json

    import aiohttp

    @agent.on_event("startup")
    async def connect(ctx):
        async def go():
            await asyncio.sleep(4)  # let the agent's local server start
            ctx.logger.info("Connecting the Agentverse mailbox with your API key...")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(f"http://127.0.0.1:{port}/connect",
                                            json={"user_token": key, "agent_type": "mailbox"},
                                            timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        raw = await resp.text()
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = {"success": False, "detail": f"HTTP {resp.status}: {raw[:120]}"}
                ok = isinstance(body, dict) and body.get("success")
                ctx.logger.info("Agentverse mailbox connected" if ok else f"Mailbox auto-connect failed: {body}. "
                                "Open the Agent Inspector link above and click Connect instead.")
            except Exception as exc:
                ctx.logger.warning(f"Mailbox auto-connect skipped ({type(exc).__name__}). "
                                   "Open the Agent Inspector link above and click Connect instead.")

        agent._unblock_connect_task = asyncio.create_task(go())  # keep a reference so it isn't garbage-collected


def create_agent(name: str, title: str, description: str, tags: list[str]) -> Agent:
    _, _, port = AGENTS[name]
    key = env("AGENTVERSE_API_KEY") or None
    mailbox = bool(key) and env_bool("UNBLOCK_MAILBOX", True)
    readme = READMES / f"{name}.md"
    agent = Agent(
        name=title,
        seed=seed(name),
        port=port,
        endpoint=None if mailbox else [f"http://127.0.0.1:{port}/submit"],
        agentverse=key,
        mailbox=mailbox,
        publish_agent_details=bool(key),
        description=description,
        handle_messages_concurrently=True,
        readme_path=str(readme) if readme.exists() else None,
        metadata={"tags": ["teamready", "la-hacks-ai-2026", "workday", "onboarding", "innovationlab", *tags]},
    )
    if mailbox and env_bool("UNBLOCK_AUTO_CONNECT", True):
        _auto_connect(agent, port, key)
    return agent
