"""TeamReady core library: everything the agents share, with no network calls.

The agents in /agents wrap these functions in uAgents. Keeping the logic here
means it can be tested without Agentverse, and the orchestrator can fall back
to running a step locally if a specialist agent is unreachable.
"""
