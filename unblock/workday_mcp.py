"""Workday Agent-Ready MCP tools: TeamReady reads Workday data and does Workday tasks.

Workday exposes 400+ Agent-Ready MCP tools (absence, onboarding, journeys, learning,
expenses, talent...) at one endpoint, called with MCP's JSON-RPC 2.0 and an Agent
System User (ASU) OAuth token from Workday's Agent System of Record (ASOR). In
delegate mode the agent can never do more than the person it acts for.
Docs: developer.workday.com → Agents → Agent-Ready MCP Tools.

TeamReady's part:
  - discover the tools the tenant registered for this agent (tools/list),
  - for a goal ("how many vacation days do I have?", "request Nov 3-4 off"), shortlist the
    matching tools and let the model pick one and fill its arguments from the tool's own schema
    (Workday's tools are built to be read by an LLM at runtime),
  - read tools (find / list / get) run straight away; anything that changes Workday is shown to
    the new hire first and runs only after they approve. Workday's own business process (e.g. the
    manager approving time off) still applies on top.

WORKDAY_MCP_URL     https://us.agent.workday.com/<tenant>/mcp
WORKDAY_MCP_TOKEN   the ASU access token (expires after 60 minutes), or set these to refresh it:
WORKDAY_MCP_TOKEN_URL, WORKDAY_MCP_CLIENT_ID, WORKDAY_MCP_CLIENT_SECRET, WORKDAY_MCP_REFRESH_TOKEN
"""
import json
import re
import time

import httpx

from .config import env
from .llm import LLMError
from .text import tokens

_state: dict = {"token": "", "expires": 0.0, "session": "", "tools": None, "tools_at": 0.0, "error": ""}
TOOLS_CACHE_SECONDS = 600
READ_VERBS = ("find", "list", "get", "search", "read", "lookup", "view", "retrieve")

# What a new hire asks for, and the words that find the matching Workday tools.
INTENTS = [
    ("balance", re.compile(r"\b(how (much|many)|balance|left|remaining|do i have)\b.*\b(time off|vacation|pto|sick|leave|holiday)|"
                           r"\b(time off|vacation|pto|sick|leave)\b.*\b(balance|left|remaining)\b", re.I),
     ["absence", "balance", "time off"], "Look up my time off balances in Workday"),
    ("time_off", re.compile(r"\b(request|book|take|submit|put in|schedule)\b.*\b(time off|vacation|pto|day off|days off|leave)\b", re.I),
     ["time off request", "absence", "time off", "valid time off dates", "eligible absence"], "Request time off in Workday"),
    ("onboarding", re.compile(r"\b(my|what'?s left|remaining|open)\b.*\b(onboarding|workday)\b.*\b(tasks?|steps?|journey|inbox)\b|"
                              r"\bonboarding tasks?\b|\bmy workday (tasks|inbox)\b", re.I),
     ["onboarding", "journey", "business process task"], "Show my onboarding tasks in Workday"),
    ("learning", re.compile(r"\b(learning|courses?|training)\b.*\b(workday|assigned|required|enrol+ed|my)\b|\bcontinue learning\b", re.I),
     ["learning", "enrollment", "continue learning"], "Show my learning in Workday"),
]

PLAN_SYSTEM = """You call Workday Agent-Ready MCP tools for a new hire.
You get the new hire's goal, who they are, today's date, and a shortlist of Workday tools with their input schemas.
Pick the ONE tool that best does the goal and fill its arguments using only the schema, the goal and the person.
Never invent IDs: if a required ID is unknown, pick a find/list tool that discovers it instead.
Reply with ONLY JSON: {"tool": "<exact tool name>", "arguments": {...}, "explain": "<one plain sentence: what this does in Workday>"}
If no tool fits, reply {"tool": "", "arguments": {}, "explain": "why"}."""

SUMMARY_SYSTEM = """Summarize a Workday tool result for a new hire in 1-3 short sentences.
Use only facts in the result (numbers, dates, names exactly as given). If the result is empty or an error, say so plainly.
Reply with ONLY JSON: {"answer": "..."}"""


def enabled() -> bool:
    return bool(env("WORKDAY_MCP_URL") and (env("WORKDAY_MCP_TOKEN") or env("WORKDAY_MCP_REFRESH_TOKEN")))


def _token(client: httpx.Client) -> str:
    if env("WORKDAY_MCP_REFRESH_TOKEN") and env("WORKDAY_MCP_TOKEN_URL"):
        if _state["token"] and _state["expires"] > time.time() + 60:
            return _state["token"]
        r = client.post(env("WORKDAY_MCP_TOKEN_URL"), data={
            "grant_type": "refresh_token", "refresh_token": env("WORKDAY_MCP_REFRESH_TOKEN"),
            "client_id": env("WORKDAY_MCP_CLIENT_ID"), "client_secret": env("WORKDAY_MCP_CLIENT_SECRET")}, timeout=20)
        r.raise_for_status()
        data = r.json()
        _state.update(token=data["access_token"], expires=time.time() + int(data.get("expires_in", 3600)))
        return _state["token"]
    return env("WORKDAY_MCP_TOKEN")


def _parse(r: httpx.Response) -> dict:
    """MCP over HTTP answers with JSON, or with server-sent events carrying the JSON-RPC message."""
    if "text/event-stream" in r.headers.get("content-type", ""):
        for line in r.text.splitlines():
            if line.startswith("data:"):
                msg = json.loads(line[5:].strip())
                if "result" in msg or "error" in msg:
                    return msg
        raise LLMError("Workday MCP sent no result")
    return r.json()


def rpc(method: str, params: dict | None = None, client: httpx.Client | None = None) -> dict:
    client = client or httpx.Client()
    headers = {"Authorization": f"Bearer {_token(client)}", "Content-Type": "application/json",
               "Accept": "application/json, text/event-stream"}
    if _state["session"]:
        headers["Mcp-Session-Id"] = _state["session"]
    body = {"jsonrpc": "2.0", "id": int(time.time() * 1000) % 10**9, "method": method}
    if params is not None:
        body["params"] = params
    r = client.post(env("WORKDAY_MCP_URL"), headers=headers, json=body, timeout=45)
    if r.status_code == 401:
        _state["token"] = ""
        raise LLMError("Workday rejected the token (it expires after 60 minutes)")
    r.raise_for_status()
    if r.headers.get("mcp-session-id"):
        _state["session"] = r.headers["mcp-session-id"]
    msg = _parse(r)
    if msg.get("error"):
        raise LLMError(f"Workday MCP error: {msg['error'].get('message', msg['error'])}")
    return msg.get("result") or {}


def tools(client: httpx.Client | None = None) -> list[dict]:
    if _state["tools"] is not None and time.time() - _state["tools_at"] < TOOLS_CACHE_SECONDS:
        return _state["tools"]
    found, cursor = [], None
    for _ in range(20):  # paginated
        result = rpc("tools/list", {"cursor": cursor} if cursor else None, client)
        found += result.get("tools", [])
        cursor = result.get("nextCursor")
        if not cursor:
            break
    _state.update(tools=found, tools_at=time.time(), error="")
    return found


def is_read(tool: dict) -> bool:
    """Only tools that look up data run without asking. Anything else changes Workday and needs approval."""
    ann = tool.get("annotations") or {}
    if ann.get("readOnlyHint") is True:
        return True
    name = re.sub(r"([a-z])([A-Z])", r"\1 \2", tool.get("name", "")).replace("_", " ").replace("-", " ").lower()
    return name.split(" ")[0] in READ_VERBS and not ann.get("destructiveHint")


def intent(text: str) -> tuple[str, list[str], str] | None:
    for name, pattern, words, goal in INTENTS:
        if pattern.search(text):
            return name, words, goal
    return None


def shortlist(words: list[str], limit: int = 8, client: httpx.Client | None = None) -> list[dict]:
    """The Workday tools whose name, title or description best match the words."""
    want = [set(tokens(w)) for w in words]
    scored = []
    for t in tools(client):
        have = set(tokens(" ".join(str(t.get(k, "")) for k in ("name", "title", "description"))))
        score = sum(len(w & have) / len(w) for w in want if w)
        if score > 0:
            scored.append((score, t))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:limit]]


def plan(goal: str, text: str, user: dict, candidates: list[dict], llm) -> dict:
    """The model picks a tool and fills its arguments from Workday's own schema."""
    from .config import today
    if not hasattr(llm, "_json"):
        raise LLMError("planning Workday calls needs a model (UNBLOCK_LLM=anthropic)")
    listing = "\n".join(json.dumps({"name": t.get("name"), "title": t.get("title", ""), "description": str(t.get("description", ""))[:400],
                                    "inputSchema": t.get("inputSchema", {})})[:2500] for t in candidates)
    who = {k: user.get(k) for k in ("name", "role", "team", "email", "workday_id", "office") if user.get(k)}
    out = llm._json(PLAN_SYSTEM, f"Goal: {goal}\nThe new hire said: {text}\nPerson: {json.dumps(who)}\nToday: {today().isoformat()}\n\nTools:\n{listing}",
                    max_tokens=800)
    names = {t.get("name"): t for t in candidates}
    if not isinstance(out, dict) or out.get("tool") not in names:
        raise LLMError(str((out or {}).get("explain") or "no Workday tool fits this"))
    return {"tool": out["tool"], "arguments": out.get("arguments") or {}, "explain": str(out.get("explain") or ""),
            "read": is_read(names[out["tool"]]), "title": names[out["tool"]].get("title") or out["tool"]}


def call(tool: str, arguments: dict, client: httpx.Client | None = None) -> str:
    result = rpc("tools/call", {"name": tool, "arguments": arguments}, client)
    parts = []
    for item in result.get("content", []):
        if item.get("type") == "text":
            parts.append(item.get("text", ""))
    if result.get("structuredContent") and not parts:
        parts.append(json.dumps(result["structuredContent"]))
    text = "\n".join(parts).strip()
    if result.get("isError"):
        raise LLMError(f"Workday said: {text[:300] or 'the call failed'}")
    return text


def summarize(result: str, goal: str, llm) -> str:
    if not result:
        return "Workday returned nothing for this."
    if hasattr(llm, "_json"):
        try:
            return str(llm._json(SUMMARY_SYSTEM, f"Goal: {goal}\nWorkday result:\n{result[:4000]}", max_tokens=300).get("answer") or result[:600])
        except LLMError:
            pass
    return result[:600]


def status_cached() -> str:
    """Status without a network call (for pages that poll)."""
    if not enabled():
        return "not connected"
    return f"connected · {len(_state['tools'])} tools" if _state["tools"] is not None else "configured"


def status() -> str:
    if not enabled():
        return "not connected (set WORKDAY_MCP_URL and an ASU token)"
    try:
        return f"connected: {len(tools())} Agent-Ready tools"
    except Exception as exc:  # shown in /api/health, never raised
        _state["error"] = str(exc)[:160]
        return f"configured but not reachable ({_state['error']})"
