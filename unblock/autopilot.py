"""Autopilot: TeamReady does onboarding tasks for the new hire, not just explains them.

Each action is backed by an approved doc that says how the task is done, and by
the system that does it (Slack, Learning Hub, Calendar, IT Help, Access Hub).
TeamReady fills the form from what it already knows (profile, the doc, the
question), shows exactly what it will do, and acts only after the new hire
approves. Gated actions (analytics access) still go to the manager first; the
form is filed the moment the manager approves.

What it never does: anything with passwords or MFA, pay, performance or
benefits, or anything the docs don't describe.

The systems here are Lumen Labs' demo systems (the company is fictional), kept in
data/runtime/systems.json. Each one is a small adapter: a real deployment swaps in
the Slack, LMS, calendar, ServiceNow or access-request API behind the same call.
The calendar invite is a real .ics email when SMTP is set up.
"""
import json
import re
import threading
import time
import uuid
from datetime import date, timedelta

from . import activity
from .config import DATA_DIR
from .data import load_people
from .risk import check_draft

PATH = DATA_DIR / "runtime" / "systems.json"
_lock = threading.RLock()

# id -> what it is. "doc" is the approved doc that describes the task; "gate" is who must approve besides the new hire.
ACTIONS = {
    "slack_channels": {"title": "Join your Slack channels", "system": "Slack", "doc": "D22", "gate": "you",
                       "step": "Join the Slack channels"},
    "security_training": {"title": "Enroll in Security Awareness Training", "system": "Learning Hub", "doc": "D20",
                          "gate": "you", "step": "Complete Security Awareness Training"},
    "manager_1_1": {"title": "Book your first 1:1 with your manager", "system": "Calendar", "doc": "D23", "gate": "you",
                    "step": "Schedule your first 1:1"},
    "it_ticket": {"title": "Open an IT ticket", "system": "IT Help (go/it-help)", "doc": "D09", "gate": "you", "step": ""},
    "analytics_access": {"title": "Request Analytics Workspace access", "system": "Access Hub (go/analytics-access)",
                         "doc": "D01", "gate": "manager", "step": "Request analytics tools"},
}
# Checklist steps TeamReady must not do, and why.
CANT = {
    "Finish laptop and account setup": "IT does this with you in person on your first day.",
    "Turn on multi-factor authentication": "TeamReady never touches passwords or MFA. You turn it on yourself.",
}

_DO = re.compile(r"\b(for me|do it|sign me up|enrol+ me|add me|book|schedule|set up my 1:1|open a ticket|file a ticket|"
                 r"join (the|my)|register me)\b", re.I)
_TRIGGERS = [
    ("slack_channels", re.compile(r"\bslack\b|\bchannels?\b", re.I)),
    ("security_training", re.compile(r"security (awareness )?training", re.I)),
    ("manager_1_1", re.compile(r"\b1:1\b|one[- ]on[- ]one|meeting with my manager", re.I)),
]
_IT_PROBLEM = re.compile(r"\b(laptop|vpn|badge|device|screen|keyboard|battery|charger|monitor)\b.*\b(broke|broken|not working|"
                         r"doesn'?t work|won'?t|fail|fails|failing|lost|stolen|cracked|dead|problem|issue)|"
                         r"\b(broke|broken|lost|stolen|cracked)\b.*\b(laptop|badge|device|screen|charger)", re.I)
AUTOPILOT = re.compile(r"^(do|finish|start|run) (my|the) (onboarding )?checklist( for me)?$|^onboard me$|^autopilot$", re.I)


_QUESTION = re.compile(r"^(how|what|where|which|who|when|why|is|are|do i|does|can i|could i|should i)\b|\?\s*$", re.I)
_ASKS_ME = re.compile(r"\b(for me|can you|could you|would you|please)\b", re.I)
_NEVER = re.compile(r"\b(mfa|2fa|password|multi-factor|authenticator)\b", re.I)


def detect(text: str) -> str:
    """The action the new hire is asking TeamReady to do, or ''. A question gets an answer, not an action,
    unless it asks TeamReady to do it ("can you...", "for me"). Anything about passwords or MFA is never an action."""
    t = text.strip()
    if _NEVER.search(t) or (_QUESTION.search(t) and not _ASKS_ME.search(t)):
        return ""
    if _IT_PROBLEM.search(t):
        return "it_ticket"
    if not _DO.search(t):
        return ""
    for action, pattern in _TRIGGERS:
        if pattern.search(t):
            return action
    return ""


def offer_for(answer: dict) -> str:
    """An action TeamReady can do after a verified answer that cites the doc for it."""
    cited = {c["id"] for c in answer.get("citations", [])}
    for action, spec in ACTIONS.items():
        if spec["gate"] == "you" and action != "it_ticket" and spec["doc"] in cited:
            return action
    return ""


def _team_channel(user: dict) -> str:
    return "#" + re.sub(r"[^a-z0-9]+", "-", user.get("team", "team").lower()).strip("-")


def build(action: str, user: dict, text: str = "") -> dict:
    """The filled form for one action, from the profile and the doc. Only what the system needs."""
    people = load_people()
    manager = people.get(user.get("manager_id", ""), {})
    if action == "slack_channels":
        role = user.get("role", "").lower()
        channels = ["#announcements", "#ask-people-ops", _team_channel(user)]
        if "engineer" in role or "developer" in role:
            channels += ["#platform-help", "#deploys"]
        if "analyst" in role or "data" in role:
            channels += ["#data-help"]
        return {"channels": channels, "why": "From 'Slack Channels Every New Hire Should Join' for your role [D22]"}
    if action == "security_training":
        start = date.fromisoformat(user.get("start_date", date.today().isoformat()))
        return {"course": "Security Awareness Training (about 45 minutes)", "due": (start + timedelta(days=14)).isoformat(),
                "why": "Due within 14 days of your start date, in the Learning Hub [D20]"}
    if action == "manager_1_1":
        from .actions import next_slot
        return {"with": f"{manager.get('name', 'your manager')} ({manager.get('role', '')})", "with_email": manager.get("email", ""),
                "when": next_slot().strftime("%a %b %d, 10:00 (Pacific)"), "length": "30-minute",
                "agenda": "Your onboarding checklist and any blockers; ask about a buddy on your team",
                "why": "Schedule a 30-minute 1:1 with your manager in your first week [D23]"}
    if action == "it_ticket":
        t = text.lower()
        category = ("Lost badge" if "badge" in t else "VPN" if "vpn" in t else "Laptop hardware")
        return {"category": category, "description": text.strip()[:400], "device": "Lumen laptop",
                "why": "Hardware problems and lost badges go to IT through go/it-help [D09, D21]"}
    if action == "analytics_access":
        return {"access": "Analytics Workspace, standard (read-only)", "business_reason": ", ".join(user.get("projects", [])),
                "manager": manager.get("name", ""),
                "why": "The Analytics Workspace Access form at go/analytics-access needs a business reason and your manager's approval [D01]"}
    raise KeyError(action)


def describe(action: str, form: dict) -> str:
    """One line: exactly what TeamReady will do."""
    if action == "slack_channels":
        return f"Add you to {', '.join(form['channels'])} in Slack."
    if action == "security_training":
        return f"Enroll you in {form['course']} in the Learning Hub, due {form['due']}."
    if action == "manager_1_1":
        return f"Book a {form['length']} 1:1 with {form['with']} on {form['when']} and send the invite."
    if action == "it_ticket":
        return f"Open a {form['category']} ticket with IT through go/it-help, with your description."
    if action == "analytics_access":
        return "File the Analytics Workspace Access form (read-only) at go/analytics-access once your manager approves."
    return ACTIONS[action]["title"]


def done_text(action: str, form: dict) -> str:
    """One line: what TeamReady did."""
    if action == "slack_channels":
        return f"Added you to {', '.join(form['channels'])} in Slack."
    if action == "security_training":
        return f"Enrolled you in {form['course']} in the Learning Hub, due {form['due']}."
    if action == "manager_1_1":
        return f"Booked a {form['length']} 1:1 with {form['with']} on {form['when']}."
    if action == "it_ticket":
        return f"Opened a {form['category']} ticket with IT through go/it-help, with your description."
    return describe(action, form)


def guardian(form: dict) -> list[str]:
    """Free text in a form passes the same Guardian check as any message."""
    text = " ".join(str(v) for k, v in form.items() if k in ("description", "business_reason", "agenda"))
    return check_draft("", text) if text else []


# ---------- the systems ----------

def _load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"records": []}


def _save(db: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(db))
    tmp.replace(PATH)


PREFIX = {"slack_channels": "SL", "security_training": "LH", "manager_1_1": "CAL", "it_ticket": "ITH", "analytics_access": "ACC"}


def execute(action: str, form: dict, user: dict, owner: str, approved_by: str = "") -> dict:
    """Do it: write the record in the system and return it. Call only after approval (and the manager's, if gated)."""
    spec = ACTIONS[action]
    rid = f"{PREFIX[action]}-{uuid.uuid4().hex[:5].upper()}"
    status, detail = "done", done_text(action, form)
    if action == "manager_1_1":
        from .actions import make_ics, next_slot, send_email
        ics = make_ics(f"1:1: {user['name']} and {form['with'].split(' (')[0]}", user["email"], form["with_email"], next_slot())
        sent = send_email(form["with_email"], f"1:1: {user['name']} (new hire)",
                                f"Hi! I'd like to set up our first 1:1 to go over {form['agenda'].lower()}.\n\n{user['name']}",
                                user["email"], ics)
        detail += " Invite " + {"sent": "emailed.", "simulated": "saved to the outbox (not emailed: email is off or unreachable from this network).", "failed": "failed to send."}[sent["status"]]
    elif action == "it_ticket":
        status, detail = "open", f"{detail} IT will reply on the ticket; the Tracker checks back if it goes quiet."
    elif action == "analytics_access":
        status = "processing"
        detail = (f"Filed the Analytics Workspace Access form at go/analytics-access with {approved_by or 'your manager'}'s approval. "
                  "Data Platform processes approved requests within one business day [D01].")
    record = {"id": rid, "action": action, "title": spec["title"], "system": spec["system"], "status": status,
              "detail": detail, "form": {k: v for k, v in form.items() if k not in ("why", "with_email")},
              "owner": owner, "created": time.time(), "approved_by": approved_by or "you"}
    with _lock:
        db = _load()
        db["records"].append(record)
        del db["records"][:-500]
        _save(db)
    activity.log("orchestrator", f"{spec['title']} in {spec['system']}", to="systems", kind="message")
    activity.log("systems", f"{rid}: {status}", to="orchestrator", kind="done")
    return record


def log_record(action: str, title: str, system: str, status: str, detail: str, owner: str, form: dict) -> dict:
    """Record something TeamReady did in another system (e.g. Workday), so it shows in Done for You."""
    record = {"id": f"WD-{uuid.uuid4().hex[:5].upper()}", "action": action, "title": title, "system": system, "status": status,
              "detail": detail, "form": form, "owner": owner, "created": time.time(), "approved_by": "you"}
    with _lock:
        db = _load()
        db["records"].append(record)
        _save(db)
    activity.log("systems", f"{record['id']}: {title} {status}", to="orchestrator", kind="done")
    return record


def records(owner: str) -> list[dict]:
    with _lock:
        return [r for r in _load()["records"] if r["owner"] == owner]


def done_actions(owner: str) -> set[str]:
    return {r["action"] for r in records(owner)}


# ---------- autopilot over the checklist ----------

def plan_checklist(steps: list[str], user: dict, owner: str, waiting: bool = False) -> list[dict]:
    """For each checklist step: what TeamReady will do, what it can't (and why), and what's already done.
    waiting: an access request is already with the manager, so it isn't asked for again."""
    done = done_actions(owner)
    plan = []
    for step in steps:
        action = next((a for a, s in ACTIONS.items() if s["step"] and step.lower().startswith(s["step"].lower())), "")
        cant = next((why for prefix, why in CANT.items() if step.lower().startswith(prefix.lower())), "")
        if action and action in done:
            plan.append({"step": step, "status": "done", "action": action})
        elif action and waiting and ACTIONS[action]["gate"] == "manager":
            plan.append({"step": step, "status": "waiting", "action": action,
                         "why": "Your request is with your manager; I file the form when they approve."})
        elif action:
            form = build(action, user)
            plan.append({"step": step, "status": "manager" if ACTIONS[action]["gate"] == "manager" else "will_do",
                         "action": action, "form": form, "does": describe(action, form)})
        else:
            plan.append({"step": step, "status": "person", "why": cant or "Not something TeamReady can do; ask People Ops."})
    return plan


def plan_text(plan: list[dict]) -> str:
    mark = {"will_do": "I'll do it", "manager": "Needs your manager", "done": "Already done", "person": "You or a person",
            "waiting": "With your manager"}
    lines = []
    for p in plan:
        what = p.get("does") or p.get("why") or ""
        lines.append(f"- **{mark[p['status']]}**: {p['step'].rstrip('.')}. {what}")
    n = sum(1 for p in plan if p["status"] in ("will_do", "manager"))
    return (f"I can take {n} of your {len(plan)} checklist steps off your plate:\n" + "\n".join(lines) +
            "\n\nReply **approve** and I'll do them (the access request goes to your manager first), or **reject**.")
