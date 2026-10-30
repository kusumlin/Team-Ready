"""TeamReady web app: landing page with a live verified-answer demo, the live Friction
Map, and the voice tool endpoint for an ElevenLabs voice agent.

    uvicorn web.app:app --host 0.0.0.0 --port 8080

The web app is read-only: it answers and explains, but every action (messages,
access requests) happens in ASI:One, where the new hire approves it first.
"""
import asyncio
import json
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))

from fastapi import FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from unblock import activity, canary, creao, portal, semantic, timeseries, workday, workday_mcp  # noqa: E402
from unblock.config import env  # noqa: E402
from unblock.data import load_people, load_user  # noqa: E402
from unblock.friction import build_map  # noqa: E402
from unblock.knowledge import answer  # noqa: E402
from unblock.llm import get_llm_or_unavailable  # noqa: E402
from unblock.risk import assess  # noqa: E402
from unblock.routing import rank  # noqa: E402

app = FastAPI(title="TeamReady", docs_url="/api/docs")
STATIC = Path(__file__).resolve().parent / "static"
RATE = int(env("WEB_RATE_PER_MIN", "20"))
_hits: dict[str, deque] = defaultdict(deque)


class Ask(BaseModel):
    question: str = Field(min_length=2, max_length=500)


def _limit(request: Request) -> None:
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
    q = _hits[ip]
    now = time.time()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE:
        raise HTTPException(429, "Too many questions in a minute. Wait a moment and try again.")
    q.append(now)


def _speech(result: dict) -> str:
    """A short spoken version, built only from verified claims."""
    kind = result["kind"]
    if kind == "stop":
        return (f"That's something a person should handle, not an assistant. {result['reason']} "
                f"Please talk to {result['helper']['name']}, {result['helper']['role']}.")
    if kind == "route":
        helper = result.get("helper")
        who = f"{helper['name']}, {helper['role']}" if helper else "People Ops"
        return f"I couldn't find a reliable answer in the approved docs, so I won't guess. The best person to ask is {who}."
    facts = [c["text"].rstrip(".") for c in result["claims"] + result["steps"]][:4]
    source = result["citations"][0]["title"] if result["citations"] else "the approved docs"
    text = "Here's what the docs say. " + ". ".join(facts) + f". That's from {source}."
    if kind == "approval":
        text += f" {result['reason']} You can ask TeamReady in ASI:One to prepare the request."
    return text


def run_ask(question: str) -> dict:
    user = load_user()
    people = load_people()
    activity.log("user", activity.said(question), to="orchestrator", kind="message")
    risk = assess(question)
    if risk.level == "stop":
        activity.log("orchestrator", f"Risk gate stopped it: {risk.category}. No search, no draft; handing it to a person", kind="block")
    else:
        activity.log("orchestrator", "Risk gate: " + ("needs the manager's approval" if risk.level == "approval" else "safe to answer from the docs"),
                     kind="step" if risk.level == "approval" else "check")
        activity.log("orchestrator", "Check the approved docs for this question", to="knowledge", kind="message")
    if risk.level == "stop":
        human = people[risk.human_id]
        result = {"kind": "stop", "title": "This needs a person", "reason": risk.reason, "category": risk.category,
                  "helper": {"name": human["name"], "role": human["role"]}, "claims": [], "steps": [], "blocked": [],
                  "conflicts": [], "citations": [], "trace": ["Stopped before searching or drafting"], "confidence": None}
    else:
        a = answer(question, user, get_llm_or_unavailable()).to_dict()
        for line in a["trace"]:
            bad = any(w in line.lower() for w in ("blocked", "stale", "no approved doc", "unavailable", "disagree"))
            activity.log("knowledge", line, kind="block" if bad else "step")
        conf = (a.get("confidence") or {}).get("score")
        activity.log("knowledge", ("Answer verified" if a["decision"] == "answer" else "No reliable answer: route to a person")
                     + (f", confidence {conf}/100" if conf is not None else ""), to="orchestrator", kind="message")
        kind = "approval" if risk.level == "approval" else a["decision"]
        helper = None
        if kind == "route":
            activity.log("orchestrator", "Who's the best person to help?", to="routing", kind="message")
            r = rank(question, user, a["retrieved_doc_ids"] or None)
            if r.chosen:
                activity.log("routing", f"Ask {r.chosen.name} ({r.chosen.role}), score {r.chosen.score:.2f}: " + "; ".join(r.chosen.reasons[:2]),
                             to="orchestrator", kind="message")
            if r.chosen:
                helper = {"name": r.chosen.name, "role": r.chosen.role, "reasons": r.chosen.reasons}
        result = {"kind": kind, "title": a["title"], "reason": risk.reason if kind == "approval" else a["route_reason"],
                  "claims": a["claims"], "steps": a["steps"], "blocked": a["blocked"], "conflicts": a["conflicts"],
                  "citations": a["citations"], "trace": a["trace"], "confidence": a["confidence"], "helper": helper,
                  "llm": a["llm_mode"], "error": a["error"]}
    result["speech"] = _speech(result)
    activity.log("orchestrator", {"answer": "Answer with sources", "route": "No guess: sent to a person",
                                   "approval": "Needs manager approval", "stop": "Stopped: a person handles this"}.get(result["kind"], result["kind"]),
                 to="user", kind="message")
    return result


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.post("/api/ask")
async def api_ask(body: Ask, request: Request):
    _limit(request)
    return await asyncio.to_thread(run_ask, body.question)


@app.post("/api/voice/ask")
async def voice_ask(body: Ask, request: Request, x_unblock_secret: str = Header(default="")):
    """Webhook tool for an ElevenLabs voice agent. Returns `answer` to be spoken."""
    secret = env("VOICE_TOOL_SECRET")
    if secret and x_unblock_secret != secret:
        raise HTTPException(401, "Missing or wrong X-Unblock-Secret header.")
    _limit(request)
    result = await asyncio.to_thread(run_ask, body.question)
    return {"answer": result["speech"], "kind": result["kind"],
            "sources": [c["title"] for c in result["citations"]], "blocked_claims": len(result["blocked"])}


BOOT = str(int(time.time()))


@app.get("/api/boot")
def api_boot():
    # Changes every time the server starts, so open pages know a demo reset happened and reload (locking the manager view).
    return {"boot": BOOT}


@app.get("/api/voice/config")
def voice_config():
    # The agent id is public (the widget puts it in the page); the tool secret never leaves the server.
    return {"agent_id": env("ELEVENLABS_AGENT_ID") or None}


_fmap: dict = {"at": 0.0, "value": None, "busy": False}
FRICTION_CACHE_SECONDS = 60


def _refresh_fmap() -> None:
    try:
        _fmap.update(value=build_map(), at=time.time())
    finally:
        _fmap["busy"] = False


@app.get("/api/friction")
def api_friction():
    # A remote database can be slow, so the map is cached for a minute and refreshed in the background.
    if _fmap["value"] is None:
        _refresh_fmap()
    elif time.time() - _fmap["at"] > FRICTION_CACHE_SECONDS and not _fmap["busy"]:
        _fmap["busy"] = True
        threading.Thread(target=_refresh_fmap, daemon=True).start()
    # Walls the Canary New Hires found: topics and doc titles only. "predicted" means no real new hire has hit it yet.
    return {**_fmap["value"], "canary_walls": canary.predicted_for_map()}


@app.get("/api/agents")
def api_agents():
    from common import AGENTS, address

    return [{"name": f"teamready-{n}", "address": address(n)} for n in AGENTS]


# ---------- New Hire Portal ----------

class PortalChat(BaseModel):
    session: str = Field(min_length=8, max_length=40, pattern=r"^web-[a-z0-9]+$")
    text: str = Field(default="", max_length=1500)
    selection: dict | None = None


class Remind(BaseModel):
    session: str = Field(min_length=8, max_length=40, pattern=r"^web-[a-z0-9]+$")
    item_id: str = Field(max_length=20)
    send: bool = False


class Decide(BaseModel):
    request_id: str = Field(max_length=20)
    decision: str = Field(pattern=r"^(approved|rejected)$")
    note: str = Field(default="", max_length=300)


def _manager_ok(key: str) -> None:
    if env("PORTAL_MANAGER_KEY") and key != env("PORTAL_MANAGER_KEY"):
        raise HTTPException(403, "Only the manager can do this.")


@app.get("/app")
def portal_page():
    return FileResponse(STATIC / "portal.html")


@app.get("/api/portal/session")
def portal_session():
    return {"session": portal.new_session()}


@app.post("/api/portal/chat")
async def portal_chat(body: PortalChat, request: Request):
    _limit(request)
    if not body.text.strip() and not body.selection:
        raise HTTPException(400, "Say something first.")
    return await portal.chat(body.session, body.text.strip(), body.selection)


@app.get("/api/portal/state")
def portal_state(session: str, after: int = 0):
    if not session.startswith("web-") or len(session) > 40:
        raise HTTPException(400, "bad session")
    return portal.state(session, after)


@app.post("/api/portal/remind")
def portal_remind(body: Remind):
    return portal.reminder(body.session, body.item_id, body.send)


@app.get("/api/portal/manager")
def portal_manager(x_manager_key: str = Header(default="")):
    _manager_ok(x_manager_key)
    return portal.pending_approvals()


@app.post("/api/portal/decide")
async def portal_decide(body: Decide, x_manager_key: str = Header(default="")):
    _manager_ok(x_manager_key)
    return await portal.decide(body.request_id, body.decision, body.note)


# ---------- Canary New Hires ----------

class CanaryFix(BaseModel):
    run_id: str = Field(max_length=20, pattern=r"^CR-[A-Z0-9]+$")
    fix_id: str = Field(max_length=6, pattern=r"^F\d+$")


_canary = {"thread": None, "last": 0.0}


async def _canary_ask(question: str, user: dict) -> dict:
    activity.log("canary", f"{user['name']}: {question[:80]}", to="knowledge", kind="message")
    return (await asyncio.to_thread(answer, question, user, get_llm_or_unavailable())).to_dict()


@app.get("/canary")
def canary_page():
    return FileResponse(STATIC / "canary.html")


@app.post("/api/canary/run")
def canary_run(request: Request):
    """Start a run in the background (one at a time) and return it; poll /api/canary/latest for progress."""
    _limit(request)
    t = _canary["thread"]
    if t and t.is_alive():
        return canary.latest()
    if time.time() - _canary["last"] < 15:
        raise HTTPException(429, "A run just finished. Wait a few seconds.")
    rec = canary.new_run("web")
    canary.save(rec)
    _canary["last"] = time.time()
    _canary["thread"] = threading.Thread(target=lambda: asyncio.run(canary.run(_canary_ask, "web", rec)), daemon=True)
    _canary["thread"].start()
    return rec


@app.get("/api/canary/latest")
def canary_latest():
    return canary.latest() or {"status": "none"}


@app.post("/api/canary/approve")
def canary_approve(body: CanaryFix, request: Request, x_manager_key: str = Header(default="")):
    """People Ops sends one fix to its doc owner. Uses the portal's manager key when one is set."""
    _manager_ok(x_manager_key)
    _limit(request)
    return canary.approve(body.run_id, body.fix_id)


@app.get("/workday")
def workday_page():
    """TeamReady in a Workday-style worker home (Canvas design tokens), with every feature in one place."""
    return FileResponse(STATIC / "workday.html")


@app.get("/activity")
def activity_page():
    return FileResponse(STATIC / "activity.html")


@app.get("/api/activity")
def api_activity(after: int = 0):
    return JSONResponse({"events": activity.since(after), "now": time.time_ns()})


@app.get("/api/activity/replay")
def api_activity_replay():
    """A recorded run of all six agents (data/demo_activity.json), for when nothing is happening live."""
    path = ROOT / "data" / "demo_activity.json"
    return JSONResponse(json.loads(path.read_text()) if path.exists() else [])


@app.get("/api/health")
def health():
    llm = get_llm_or_unavailable()
    return JSONResponse({"ok": True, "llm": llm.mode, "model": "Anthropic Sonnet" if llm.mode == "anthropic" else getattr(llm, "model", ""),
                         "retrieval": "hybrid (Gemini)" if semantic.enabled() else "keyword (BM25)",
                         "friction_store": "Tiger Data" if timeseries.usable() else ("JSON files (Tiger Data unreachable)" if timeseries.enabled() else "JSON files"),
                         "new_hire_profile": (load_user(), workday.status())[1],
                         "doc_fixes": creao.status(), "workday_mcp": workday_mcp.status()})
