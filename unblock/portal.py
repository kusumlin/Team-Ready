"""New Hire Portal: the same TeamReady conversation as in ASI:One, in a web page.

The portal runs the orchestrator's own conversation logic (unblock/flow.py)
with the same checks: risk gate, verified answers, fair routing, Guardian,
approve-before-send, manager approval, Tracker follow-ups. The steps run inside
the web app (the knowledge and routing code is the same code the agents run),
and every step is written to the Agent Activity log.

State lives in one JSON file on the shared runtime volume, keyed by a session
id the browser keeps. A session is not a login: this is a demo with a fictional
new hire, so no real employee data goes in.
"""
import json
import re
import threading
import time
import uuid

from . import activity, autopilot, tracker
from . import knowledge as knowledge_lib
from . import routing as routing_lib
from .actions import send_email
from .config import DATA_DIR, today
from .data import load_docs, load_people, load_user
from .flow import Orchestrator, Reply
from .friction import build_map, log_live_event
from .llm import get_llm, get_llm_or_unavailable

PATH = DATA_DIR / "runtime" / "portal.json"
_lock = threading.RLock()


def _load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save(db: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db))
    tmp.replace(PATH)


def _update(fn):
    with _lock:
        db = _load()
        out = fn(db)
        _save(db)
        return out


def _push(session: str, text: str, kind: str | None = None, payload: dict | None = None, extra: dict | None = None) -> None:
    def add(db):
        box = db.setdefault("inbox", {}).setdefault(session, [])
        box.append({"id": time.time_ns(), "text": text, "kind": kind, "payload": payload, **(extra or {})})
        del box[:-50]
    _update(add)


class Store:
    def get(self, key: str) -> dict | None:
        with _lock:
            return _load().get("state", {}).get(key)

    def set(self, key: str, value: dict) -> None:
        _update(lambda db: db.setdefault("state", {}).__setitem__(key, value))


def _knowledge_summary(r: dict) -> str:
    conf = (r.get("confidence") or {}).get("score")
    return ("Answer verified" if r.get("decision") == "answer" else "No reliable answer: route to a person") + (
        f", confidence {conf}/100" if conf is not None else "")


class Services:
    """What the agents do for the orchestrator, run here, logged under the same agent names."""

    async def knowledge(self, question: str, user: dict) -> dict:
        import asyncio
        activity.log("orchestrator", "Check the approved docs for this question", to="knowledge", kind="message")
        result = (await asyncio.to_thread(knowledge_lib.answer, question, user, get_llm_or_unavailable())).to_dict()
        for line in result.get("trace", []):
            bad = any(w in line.lower() for w in ("blocked", "stale", "no approved doc", "unavailable", "disagree"))
            activity.log("knowledge", line, kind="block" if bad else "step")
        activity.log("knowledge", _knowledge_summary(result), to="orchestrator", kind="message")
        return result

    async def routing(self, question: str, user: dict, doc_ids: list[str], exclude: list[str]) -> dict:
        activity.log("orchestrator", "Who's the best person to help?" + (f" (skip {len(exclude)} already tried)" if exclude else ""),
                     to="routing", kind="message")
        result = routing_lib.rank(question, user, doc_ids or None, set(exclude)).to_dict()
        c = result.get("chosen")
        if result.get("rotation_note"):
            activity.log("routing", "Fairness: " + result["rotation_note"], kind="check")
        activity.log("routing", f"Ask {c['name']} ({c['role']}), score {c['score']:.2f}" if c else "Nobody clearly owns this",
                     to="orchestrator", kind="message")
        return result

    async def wrong_person(self, person_id: str, topic_key: str) -> None:
        count = routing_lib.record_wrong_person(person_id, topic_key)
        activity.log("routing", f"Learned: lowered that person's score for this topic ({count}x)")

    async def request_approval(self, req: dict) -> str:
        activity.log("orchestrator", f"Approval request {req['request_id']} ({req['category']}) for the manager", to="manager", kind="message")
        activity.log("manager", f"{req['request_id']} is waiting for the manager. Only a person can approve it")
        record = {**req, "session": req.get("sender", ""), "status": "pending", "created": time.time()}
        _update(lambda db: db.setdefault("approvals", {}).__setitem__(req["request_id"], record))
        return "It's in Jordan's queue on the Manager tab."

    async def friction_event(self, doc_id: str, docs_read: list[str], resolved: bool) -> None:
        if doc_id:
            activity.log("orchestrator", "Anonymous blocker logged (doc path only, no names or text)", to="insights", kind="message")
            log_live_event(doc_id, docs_read, resolved)

    async def track(self, item_id: str, user: str, kind: str, summary: str, to_name: str, to_email: str) -> None:
        activity.log("orchestrator", f"Track {item_id}: waiting for {to_name} to reply", to="tracker", kind="message")
        _update(lambda db: tracker.add(db.setdefault("tracker", {}), item_id, user, kind, summary, to_name, to_email))

    async def track_resolved(self, item_id: str, outcome: str) -> None:
        if _update(lambda db: tracker.resolve(db.setdefault("tracker", {}), item_id, outcome)):
            activity.log("tracker", f"{item_id} closed: {outcome}", kind="done")

    async def friction_map(self) -> dict:
        return build_map()

    async def send_email(self, to: str, subject: str, body: str, sender: str, ics: str | None) -> dict:
        import asyncio
        result = await asyncio.to_thread(send_email, to, subject, body, sender, ics)
        label = {"sent": "Email sent", "simulated": "Email simulated (no SMTP set up)", "failed": "Email failed"}[result["status"]]
        activity.log("orchestrator", f"{label}: \"{subject}\" after your approval", to="people", kind="done" if result["status"] != "failed" else "block")
        return result

    async def source_feedback(self, source_ids: list[str]) -> None:
        _update(lambda db: db.setdefault("source_feedback", []).append({"source_ids": source_ids, "message_text_stored": False}))


def _reply(reply: Reply, session: str) -> dict:
    state = Store().get(session) or {}
    pending = state.get("pending")
    out = {"text": reply.text, "kind": reply.kind, "payload": reply.payload}
    if reply.kind == "review" and pending and pending["type"] not in ("system_action", "system_batch"):
        out["draft"] = {k: pending[k] for k in ("type", "to_name", "to_role", "subject", "body", "guardian")}
    return out


async def chat(session: str, text: str, selection: dict | None = None) -> dict:
    who = "user"
    if selection:
        activity.log(who, "(clicked " + str(selection.get("action", "a button")).removeprefix("ub_").replace("_", " ") + ")", to="orchestrator", kind="message")
    else:
        activity.log(who, activity.said(text), to="orchestrator", kind="message")
    flow = Orchestrator(Services(), Store(), get_llm)
    reply = await flow.handle(session, text, selection or {})
    first = (reply.text.strip().splitlines() or [""])[0]
    activity.log("orchestrator", ("[card] " if reply.kind else "") + first, to="user", kind="message")
    return _reply(reply, session)


# ---------- the new hire's side panel ----------

def checklist() -> list[str]:
    doc = load_docs().get("D02")
    if not doc:
        return []
    return [re.sub(r"^\d+\.\s*", "", line).strip() for line in doc.body.splitlines() if re.match(r"^\d+\.", line.strip())]


def _check_overdue(db: dict, session: str) -> None:
    items = db.setdefault("tracker", {})
    now = time.time()
    for item in tracker.overdue(items, now):
        if item["user"] != session:
            continue
        item["nudged"] = True
        waited = tracker.age_text(now - item["created"])
        activity.log("tracker", f"No reply from {item['to_name']} after {waited}; offering a follow-up")
        activity.log("tracker", "[card] Want me to send a friendly reminder?", to="user", kind="message")
        box = db.setdefault("inbox", {}).setdefault(session, [])
        box.append({"id": time.time_ns(), "from": "tracker", "item_id": item["id"], "kind": "reminder",
                    "text": f"**No reply yet from {item['to_name']}** about \"{item['summary']}\" ({waited}). "
                            "Want me to send a short, friendly reminder? I'll show it to you first."})


def _workday_mcp_status() -> str:
    from . import workday_mcp
    return workday_mcp.status_cached()


def state(session: str, after: int = 0) -> dict:
    from . import workday

    user = load_user()
    with _lock:
        db = _load()
        _check_overdue(db, session)
        _save(db)
    items = [i for i in db.get("tracker", {}).values() if i["user"] == session]
    requests = [{k: r[k] for k in ("request_id", "category", "subject", "status", "decided_by", "created") if k in r}
                for r in db.get("approvals", {}).values() if r.get("session") == session]
    inbox = [m for m in db.get("inbox", {}).get(session, []) if m["id"] > after]
    pend = (db.get("state", {}).get(session) or {}).get("pending")
    awaiting = ({"type": pend["type"], "title": pend.get("title") or pend.get("subject", ""), "to": pend.get("to_name", ""),
                 "blocked": bool(pend.get("guardian"))} if pend else None)
    return {
        "profile": {"name": user["name"], "role": user["role"], "team": user.get("team", ""), "office": user.get("office", ""),
                    "manager": load_people().get(user.get("manager_id", ""), {}).get("name", ""),
                    "source": user.get("profile_source", "Sample profile"), "workday": workday.status(),
                    "workday_mcp": _workday_mcp_status(), "start_date": user.get("start_date", ""),
                    "today": today().isoformat()},
        "checklist": checklist(),
        # Checklist steps TeamReady already did for this session (by index), and everything it did.
        "checklist_done": [i for i, step in enumerate(checklist()) for p in autopilot.plan_checklist([step], user, session)
                           if p["status"] == "done"],
        "checklist_doable": [i for i, step in enumerate(checklist()) for p in autopilot.plan_checklist([step], user, session)
                             if p["status"] in ("will_do", "manager")],
        "checklist_waiting": [i for i, step in enumerate(checklist()) for p in autopilot.plan_checklist([step], user, session)
                              if p["status"] == "manager" and any(r.get("status") == "pending" and r.get("category") == "analytics access"
                                                                  for r in db.get("approvals", {}).values() if r.get("session") == session)],
        "done_for_you": [{k: r[k] for k in ("id", "title", "system", "status", "detail")} for r in autopilot.records(session)][::-1],
        "followups": sorted(({"id": i["id"], "kind": tracker.KIND_LABEL.get(i["kind"], i["kind"]), "to": i["to_name"],
                              "summary": i["summary"], "status": "waiting" if i["status"] == "open" else i["status"],
                              "age": tracker.age_text(time.time() - i["created"]), "nudged": i["nudged"]} for i in items),
                            key=lambda x: x["id"]),
        "requests": sorted(requests, key=lambda r: r.get("created", 0)),
        "inbox": inbox,
        "awaiting_you": awaiting,  # what's waiting for the new hire's approve / reject right now
    }


def reminder(session: str, item_id: str, send: bool) -> dict:
    """Show the reminder draft (send=False) or send it after the new hire approves (send=True)."""
    with _lock:
        db = _load()
        item = db.get("tracker", {}).get(item_id)
    if not item or item["user"] != session:
        return {"text": "I don't have that follow-up anymore."}
    draft = tracker.reminder_draft(item, load_user()["name"])
    if not send:
        return {"text": "Here's the reminder. Nothing is sent until you approve it.", "draft": {
            "to_name": item["to_name"], "to_role": "", "subject": draft["subject"], "body": draft["body"], "guardian": draft["guardian"]},
            "reminder_for": item_id}
    if draft["guardian"]:
        return {"text": "Guardian stopped the reminder: " + "; ".join(draft["guardian"]) + ". Nothing was sent."}
    result = send_email(item["to_email"], draft["subject"], draft["body"], load_user()["email"])
    activity.log("tracker", f"Reminder to {item['to_name']} after your approval: {result['status']}", to="people",
                 kind="done" if result["status"] != "failed" else "block")
    label = {"sent": "Sent", "simulated": "Simulated (email not configured)", "failed": "Not sent"}[result["status"]]
    return {"text": f"**{label}.** {result['detail']}"}


# ---------- the manager's side ----------

def pending_approvals() -> list[dict]:
    with _lock:
        db = _load()
    out = []
    for r in db.get("approvals", {}).values():
        out.append({k: r.get(k) for k in ("request_id", "category", "requester", "subject", "body", "evidence", "status", "created", "note")})
    return sorted(out, key=lambda r: (r["status"] != "pending", -(r["created"] or 0)))


async def decide(request_id: str, decision: str, note: str = "") -> dict:
    manager = load_people().get(load_user().get("manager_id", ""), {}).get("name", "Your manager")

    def mark(db):
        r = db.get("approvals", {}).get(request_id)
        if not r or r["status"] != "pending":
            return None
        r.update(status=decision, decided_by=manager, note=note)
        return r
    req = _update(mark)
    if not req:
        return {"ok": False, "text": f"{request_id} isn't waiting for a decision."}
    activity.log("manager_person", f"{decision.capitalize()} {request_id}", to="manager", kind="message")
    activity.log("manager", f"{manager} {decision} {request_id}", to="orchestrator", kind="message")
    flow = Orchestrator(Services(), Store(), get_llm)
    out = await flow.on_decision({"request_id": request_id, "decision": decision, "note": note, "approver": manager,
                                  "sender": req["session"]})
    if out:
        session, reply = out
        activity.log("orchestrator", reply.text.splitlines()[0], to="user", kind="message")
        _push(session, reply.text, extra={"from": "manager"})
    return {"ok": True, "text": f"{request_id} {decision}. Maya has been told."}


def new_session() -> str:
    return "web-" + uuid.uuid4().hex[:12]
