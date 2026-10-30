"""Run all seven TeamReady agents in one process.

    python agents/main.py

With AGENTVERSE_API_KEY set, each agent connects to Agentverse in mailbox mode
and becomes discoverable in ASI:One. Without it, they run locally.
"""
from common import address  # noqa: F401  (sets sys.path)
from uagents import Bureau

from insights_agent import agent as insights
from knowledge_agent import agent as knowledge
from manager_agent import agent as manager
from orchestrator import agent as orchestrator
from routing_agent import agent as routing
from tracker_agent import agent as tracker
from canary_agent import agent as canary

bureau = Bureau(port=8000, endpoint=["http://127.0.0.1:8000/submit"])
for a in (orchestrator, knowledge, routing, manager, insights, tracker, canary):
    bureau.add(a)

if __name__ == "__main__":
    for a in (orchestrator, knowledge, routing, manager, insights, tracker, canary):
        print(f"{a.name:24s} {a.address}")
    bureau.run()
