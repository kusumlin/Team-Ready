"""Canary New Hires: synthetic new hires who onboard before real people do.

Each canary (data/canaries.json) is a fictional new hire with a role and an
office. It walks its onboarding checklist step by step, plus a few tasks for its
role, and asks TeamReady how to do each one, through the same risk gate and
verified-answer pipeline a real new hire gets. Then it judges whether a person
could actually do the step from what the docs say:

  clear      the doc says how
  findable   the doc names the thing; the how is one search away
  detour     the doc says what, not how, and the how is in a doc it doesn't name
  loop       the only source is the checklist itself: no doc says how
  trap       an out-of-date doc still ranks for the task and says something else
  dead_end   no approved doc covers it for this office
  approval   gated on purpose (the manager approves)
  person     high-impact: a person handles it by design

Detours, loops, traps and dead ends are "walls". Each wall is checked against
the Friction Map: walls real new hires already hit, and walls nobody has hit yet
(predicted). For each wall the canary proposes a fix for the doc owner: a
one-line edit (drafted by the CREAO Doc Steward when it is set up), an archive
note for a stale doc, or a request to the right person to write the missing
step. A human approves before anything is sent.

The canaries never touch real data: fictional people, synthetic docs, and only
doc ids and step text are logged.
"""
import asyncio
import json
import re
import threading
import time
import uuid
from datetime import datetime, timezone

from . import activity, creao, friction
from .config import DATA_DIR, env
from .data import load_docs, load_people
from .llm import LLMError, get_llm_or_unavailable
from .risk import assess
from .text import normalize, tokens

PATH = DATA_DIR / "runtime" / "canary.json"
CANARIES_PATH = DATA_DIR / "canaries.json"
_lock = threading.RLock()

# label, estimated minutes a real new hire loses here, what it means
STATUS = {
    "clear": ("Clear", 0, "The doc says how to do it."),
    "findable": ("Found by name", 10, "The doc names it, so one search finds the how-to."),
    "detour": ("Detour", 30, "The doc says what to do but not how, and doesn't point to the doc that does."),
    "loop": ("Circular", 120, "The only source is the checklist itself. No approved doc says how."),
    "trap": ("Stale-doc trap", 90, "An out-of-date doc still ranks for this and gives different instructions."),
    "dead_end": ("Dead end", 240, "No approved doc covers this for this office, so it waits on a person."),
    "approval": ("Needs manager", 0, "Gated on purpose: TeamReady prepares the request and the manager approves."),
    "person": ("Person only", 0, "High-impact: TeamReady hands it to a person by design."),
}
WALLS = ("trap", "dead_end", "loop", "detour")
MINUTES_NOTE = ("Estimated minutes a real new hire would lose at each wall: detour 30, stale-doc trap 90, "
                "circular 120, dead end 240 (waiting on a person). Assumptions, not measurements.")
# Something a person can act on: a go/ link, a Slack channel, a command, or a named system.
AFFORDANCE = re.compile(r"go/[\w-]+|#[a-z][\w-]+|\b(?:make|git|lumen) [a-z]|\b(?:[A-Z][a-z]+ ){1,2}(?:Hub|Center|Catalog|Service)\b")
STEP_LINE = re.compile(r"^\s*(\d+)\.\s+(.*\S)\s*$")


def load_canaries() -> list[dict]:
    return json.loads(CANARIES_PATH.read_text())


def canary_user(c: dict) -> dict:
    """The canary as a new-hire profile. Fictional: never a real person and never from Workday."""
    return {"id": c["id"], "name": c["name"], "role": c["role"], "team": c["team"], "office": c["office"],
            "manager_id": c["manager_id"], "email": f"{c['id']}@canary.lumen.example", "projects": [f"{c['team']} onboarding"],
            "profile_source": "canary"}


def journey(c: dict) -> list[dict]:
    """The steps a canary tries: its start doc's numbered checklist, then its role tasks."""
    steps = []
    doc = load_docs().get(c.get("start_doc", ""))
    if doc:
        for line in doc.body.splitlines():
            m = STEP_LINE.match(line)
            if m:
                steps.append({"task": m.group(2), "from": f"{doc.title}, step {m.group(1)}", "start_doc": doc.id})
    steps += [{"task": t, "from": f"{c['role']} task", "start_doc": ""} for t in c.get("tasks", [])]
    return steps


def shorten(task: str) -> str:
    """The task without its trailing conditions ("after ...", "within ...", "for your ..."), as a person would search it."""
    return re.split(r"\s(?:after|within|during|before|on your|for your|in your|with your)\b", task.strip().rstrip("."), maxsplit=1)[0]


def question_for(task: str) -> str:
    t = task.strip().rstrip(".")
    t = re.sub(r"\byour\b", "my", t[0].lower() + t[1:])
    return f"How do I {t}?"


def _overlap(task: str, title: str) -> float:
    want = set(tokens(title))
    return len(want & set(tokens(task))) / len(want) if want else 0.0


def classify(task: str, start_doc: str, risk, answer: dict) -> tuple[str, dict]:
    """(status, details) for one step, from the risk gate and TeamReady's verified answer."""
    docs = load_docs()
    stale = next((c for c in answer.get("conflicts", []) if c.get("type") == "stale doc"), None)
    cited = [c["id"] for c in answer.get("citations", [])]
    extra = {"stale_doc": stale["stale_doc_id"] if stale else "", "source_doc": next((d for d in cited if d != start_doc), "")}
    if risk.level == "stop":
        return "person", extra
    if risk.level == "approval":
        return "approval", extra
    if answer.get("decision") != "answer":
        # A checklist step names the task, so if nothing says how, it's circular; a role task with no doc is a dead end.
        return ("loop" if start_doc else "dead_end"), extra
    if stale:
        return "trap", extra
    if AFFORDANCE.search(task):
        return "clear", extra
    if not start_doc:
        return "clear", extra
    if not extra["source_doc"]:
        # The answer only quoted the checklist. A retrieved doc may still hold the how-to: a line a person can act on.
        want = set(tokens(task))
        for doc_id in answer.get("retrieved_doc_ids", []):
            if doc_id == start_doc or doc_id not in docs or _is_stale(docs[doc_id]):
                continue
            line = next((x for x in docs[doc_id].body.splitlines() if AFFORDANCE.search(x) and want & set(tokens(x))), "")
            if line:
                extra.update(source_doc=doc_id, source_line=line)
                break
    if not extra["source_doc"]:
        return "loop", extra
    if _overlap(task, docs[extra["source_doc"]].title) >= 0.5:
        return "findable", extra
    return "detour", extra


async def walk(c: dict, ask, on_step=None) -> list[dict]:
    """One canary's walk. ask(question, user) -> TeamReady's answer dict. Calls on_step(record) after each step."""
    user = canary_user(c)
    docs = load_docs()
    out = []
    for n, step in enumerate(journey(c), 1):
        q = question_for(step["task"])
        risk = assess(q)
        answer = {} if risk.level == "stop" else await ask(q, user)
        status, extra = classify(step["task"], step["start_doc"], risk, answer)
        rephrased = ""
        if status == "loop":
            # A real new hire rephrases once. If a shorter search finds the how-to elsewhere, it's a detour.
            short = shorten(step["task"])
            if short != step["task"]:
                q2 = question_for(short)
                a2 = await ask(q2, user)
                # Judge the rephrase the way a person would: is there an actionable how-to in what the search turned up?
                # (Search is deterministic; the model's yes/no on a loosely worded question isn't.)
                want = set(tokens(short))
                found = ""
                for doc_id in [c["id"] for c in a2.get("citations", [])] + a2.get("retrieved_doc_ids", []):
                    d = docs.get(doc_id)
                    if not d or doc_id == step["start_doc"] or _is_stale(d):
                        continue
                    line = next((x for x in d.body.splitlines() if AFFORDANCE.search(x) and want & set(tokens(x))), "")
                    if line:
                        found = doc_id
                        break
                if found and assess(q2).level == "routine":
                    status, answer, rephrased = "detour", a2, q2
                    extra = {"stale_doc": "", "source_doc": found, "source_line": line}
        label, minutes, why = STATUS[status]
        rec = {"n": n, "task": step["task"], "from": step["from"], "question": q, "status": status, "label": label,
               "why": why, "minutes": minutes, "start_doc": step["start_doc"], **extra,
               "cited": [{"id": x["id"], "title": x["title"]} for x in answer.get("citations", [])],
               "confidence": (answer.get("confidence") or {}).get("score"),
               "claims": [x["text"] for x in answer.get("claims", []) + answer.get("steps", [])][:3],
               "retrieved": answer.get("retrieved_doc_ids", [])[:3], "rephrased": rephrased}
        if rephrased:
            rec["why"] = f"The checklist's own words find nothing useful. Rephrased as \"{rephrased}\", the how-to is in another doc the checklist doesn't link."
        if status == "trap":
            rec["why"] += f" ('{docs[extra['stale_doc']].title}')"
        activity.log("canary", f"{c['name']} ({c['role']}, {c['office']}): {step['task'][:70]}: {label}",
                     kind="block" if status in WALLS else "check")
        out.append(rec)
        if on_step:
            on_step(rec)
    return out


# ---------- walls and fixes ----------

def _wall_key(rec: dict) -> tuple:
    s = rec["status"]
    if s == "detour":
        return (s, rec["start_doc"], rec["source_doc"])
    if s == "trap":
        return (s, rec["stale_doc"])
    return (s, normalize(rec["task"]))


def _humans_hit(rec: dict) -> int:
    """How many real new-hire blockers in the last 30 days match this wall (same topic and starting doc)."""
    s = rec["status"]
    if s == "detour":
        topic, first = friction.topic_for(rec["source_doc"]), rec["start_doc"]
    elif s == "trap":
        topic, first = friction.topic_for(rec["stale_doc"]), rec["stale_doc"]
    else:
        return 0
    return sum(1 for e in friction.all_events(30) if e["topic"] == topic and (e["docs_read"] or [None])[0] == first)


def walls(canaries: list[dict]) -> list[dict]:
    docs, people = load_docs(), load_people()
    grouped: dict[tuple, dict] = {}
    for c in canaries:
        for rec in c["steps"]:
            if rec["status"] not in WALLS:
                continue
            w = grouped.setdefault(_wall_key(rec), {"status": rec["status"], "label": rec["label"], "task": rec["task"],
                                                   "why": rec["why"], "minutes": rec["minutes"], "canaries": [],
                                                   "start_doc": rec["start_doc"], "source_doc": rec["source_doc"],
                                                   "stale_doc": rec["stale_doc"], "source_line": rec.get("source_line", ""),
                                                   "offices": []})
            if c["name"] not in w["canaries"]:
                w["canaries"].append(c["name"])
            if c["office"] not in w["offices"]:
                w["offices"].append(c["office"])
            w.setdefault("_rec", rec)
    out = []
    for w in grouped.values():
        w["humans_hit"] = _humans_hit(w["_rec"])
    # Walls real new hires already hit first (most-hit first), then the predicted ones.
    order = sorted(grouped.values(), key=lambda w: (w["humans_hit"] == 0, -w["humans_hit"], WALLS.index(w["status"]), -len(w["canaries"])))
    for i, w in enumerate(order, 1):
        rec = w.pop("_rec")
        w["id"] = f"W{i}"
        w["predicted"] = w["humans_hit"] == 0
        doc_id = w["stale_doc"] if w["status"] == "trap" else w["start_doc"]
        if w["status"] == "detour":
            w["headline"] = f"'{docs[doc_id].title}' says \"{w['task'].rstrip('.')}\" but not how; the how-to is in '{docs[w['source_doc']].title}'"
        elif w["status"] == "trap":
            w["headline"] = f"'{docs[doc_id].title}' is out of date and still comes up for \"{w['task'].rstrip('.')}\""
        elif w["status"] == "loop":
            w["headline"] = f"\"{w['task'].rstrip('.')}\": the checklist asks for it, and no approved doc says how"
        else:
            w["headline"] = f"\"{w['task'].rstrip('.')}\": no approved doc covers it for {', '.join(w['offices'])} hires"
        if doc_id:
            owner = people.get(docs[doc_id].owner, {})
            w["doc_id"], w["doc_title"] = doc_id, docs[doc_id].title
            w["owner"] = {"id": owner.get("id", ""), "name": owner.get("name", ""), "role": owner.get("role", "")}
        if w["status"] in ("loop", "dead_end"):
            w["writer"] = _writer(w["task"], w.get("owner"))
        out.append(w)
    return out


def _writer(task: str, fallback: dict | None) -> dict:
    """Who should write a missing how-to: the person whose listed skills match the task best, else the doc owner."""
    want = set(tokens(task))
    best, score = None, 0
    for p in load_people().values():
        s = sum(1 for skill in p.get("skills", []) if set(tokens(skill)) & want)
        if s > score:
            best, score = p, s
    if best:
        return {"id": best["id"], "name": best["name"], "role": best["role"]}
    if fallback and fallback.get("id"):
        return fallback
    p = load_people()["p05"]
    return {"id": p["id"], "name": p["name"], "role": p["role"]}


def _check_fix(fix, doc) -> dict:
    """The same exact-quote rule as the insights agent, whoever drafted the fix."""
    if not isinstance(fix, dict):
        return {"error": "The drafted fix wasn't in the expected format, so it was blocked."}
    before, after = str(fix.get("before_quote") or ""), fix.get("after_text")
    if len(normalize(before).split()) < 4 or normalize(before) not in normalize(doc.body):
        return {"error": "The drafted fix didn't quote the doc word for word, so it was blocked."}
    if not isinstance(after, str) or not after.strip():
        return {"error": "The drafted fix was empty, so it was blocked."}
    return {"before": before, "after": after.strip(), "rationale": str(fix.get("rationale") or "")}


def _local_fix(w: dict, rec_claims: list[str]) -> dict:
    """A deterministic one-line fix from the source doc's own words."""
    docs = load_docs()
    source = docs[w["source_doc"]]
    lines = [x for x in source.body.splitlines() if x.strip()]
    pick = w.get("source_line") or next((x for x in rec_claims + lines if AFFORDANCE.search(x)), lines[0])
    return {"before_quote": w["task"], "after_text": f"{w['task'].rstrip('.')}. {pick} (See '{source.title}'.)",
            "rationale": f"{len(w['canaries'])} canary new hire(s) couldn't do this from the checklist alone."}


def _cluster(w: dict) -> dict:
    return {"topic": w["task"], "count": len(w["canaries"]) + w["humans_hit"],
            "pattern": f"{len(w['canaries'])} canary new hires and {w['humans_hit']} real new hires got stuck on "
                       f"\"{w['task']}\" in '{w['doc_title']}'; the missing how-to is in another doc",
            "resolved_share": 0, "start_doc": w["doc_id"]}


def propose(w: dict, claims: list[str]) -> dict:
    """A fix proposal for one wall. Detours get a one-line doc edit; traps an archive note; the rest a writing request."""
    docs = load_docs()
    fix = {"id": "F" + w["id"][1:], "wall": w["id"], "status": "ready"}
    if w["status"] == "detour":
        doc, source = docs[w["doc_id"]], docs[w["source_doc"]]
        fix.update(kind="edit", to=w["owner"], doc_id=doc.id, doc_title=doc.title, source_title=source.title)
        if creao.enabled():
            try:
                run_id = creao.start_run(creao.fix_inputs(_cluster(w), doc.title, doc.body, source.title, source.body))
                activity.log("canary", f"Draft a fix for '{doc.title}': canaries hit a detour", to="creao", kind="message")
                activity.log("creao", f"Doc Steward run {run_id[:8]} started (runs take a few minutes)")
                fix.update(status="drafting", drafter="CREAO Doc Steward", creao_run=run_id, run_url=creao.run_url(run_id),
                           started=time.time(), checked=0)
                return fix
            except Exception as exc:  # CREAO down or misconfigured: draft here instead
                activity.log("canary", f"CREAO unavailable ({type(exc).__name__}); drafting the fix here", kind="block")
        llm = get_llm_or_unavailable()
        drafted, drafter = None, "TeamReady (from the source doc's own words)"
        if llm.mode not in ("extractive", "unavailable"):
            try:
                drafted, drafter = llm.propose_fix(_cluster(w), doc.body, doc.title, source.body), f"TeamReady ({llm.mode})"
            except LLMError:
                drafted = None
        checked = _check_fix(drafted, doc) if drafted else {"error": "no model draft"}
        if "error" in checked:
            checked, drafter = _check_fix(_local_fix(w, claims), doc), "TeamReady (from the source doc's own words)"
        fix.update(drafter=drafter, **checked)
        if "error" in checked:
            fix["status"] = "blocked"
    elif w["status"] == "trap":
        doc = docs[w["doc_id"]]
        current = next((d for d in docs.values() if d.id != doc.id and not _is_stale(d) and
                        _overlap(w["task"], d.title) >= 0.5), None)
        first = next(x for x in doc.body.splitlines() if x.strip())
        fix.update(kind="archive", to=w["owner"], doc_id=doc.id, doc_title=doc.title, before=first,
                   after="OUT OF DATE: don't use this runbook." + (f" Follow '{current.title}' instead." if current else ""),
                   rationale=f"It was last updated {doc.updated_at.isoformat()} and new hires still find it.",
                   drafter="TeamReady (archive note)")
    else:
        to = w.get("writer") or {"id": "p05", "name": load_people()["p05"]["name"], "role": load_people()["p05"]["role"]}
        fix.update(kind="write", to=to, doc_id=w.get("doc_id", ""), doc_title=w.get("doc_title", ""),
                   before="", after=f"A short how-to for \"{w['task']}\" ({', '.join(w['offices'])} offices).",
                   rationale=w["why"], drafter="TeamReady (writing request)")
    return fix


def _is_stale(doc) -> bool:
    from .config import today
    return (today() - doc.updated_at).days > 365


def refresh(run: dict) -> bool:
    """Check CREAO runs that are still drafting. Returns True if anything changed."""
    if not creao.enabled():
        return False
    changed, docs = False, load_docs()
    every = float(env("CREAO_CHECK_SECONDS", "20"))
    give_up = float(env("CREAO_TIMEOUT_MINUTES", "12")) * 60
    for fix in run.get("fixes", []):
        if fix.get("status") != "drafting" or time.time() - fix.get("checked", 0) < every:
            continue
        fix["checked"], changed = time.time(), True
        w = next(x for x in run["walls"] if x["id"] == fix["wall"])
        try:
            r = creao.get_run(fix["creao_run"])
        except Exception:
            r = None
        timed_out = time.time() - fix["started"] > give_up
        if r is not None and r.get("status") not in creao.DONE and not timed_out:
            continue
        try:
            checked = _check_fix(creao.result_fix(r), docs[fix["doc_id"]]) if r else {"error": "CREAO didn't answer"}
        except LLMError as exc:
            checked = {"error": str(exc)}
        if "error" in checked:
            activity.log("canary", f"CREAO run unusable ({checked['error']}); drafting the fix here", kind="block")
            checked = _check_fix(_local_fix(w, []), docs[fix["doc_id"]])
            fix["drafter"] = "TeamReady (CREAO run unusable, drafted from the source doc)"
        else:
            activity.log("creao", "Drafted a one-line fix to the doc", to="canary", kind="message")
            activity.log("canary", "Exact-quote check passed: the fix quotes the doc word for word", kind="check")
        fix.update(status="blocked" if "error" in checked else "ready", **checked)
    return changed


# ---------- runs ----------

def summary(run: dict) -> dict:
    ws = run.get("walls", [])
    steps = [s for c in run.get("canaries", []) for s in c["steps"]]
    lost = sum(w["minutes"] * len(w["canaries"]) for w in ws)
    return {"canaries": len(run.get("canaries", [])), "steps": len(steps),
            "clear": sum(1 for s in steps if s["status"] in ("clear", "findable", "approval", "person")),
            "walls": len(ws), "predicted": sum(1 for w in ws if w["predicted"]),
            "confirmed": sum(1 for w in ws if not w["predicted"]),
            "minutes_saved_per_cohort": lost, "minutes_note": MINUTES_NOTE}


def _load() -> dict:
    try:
        return json.loads(PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return {"runs": []}


STALE_SECONDS = 300  # a live run saves after every step; a "running" run quiet for this long was interrupted


def save(run: dict) -> None:
    run["updated"] = time.time()
    with _lock:
        db = _load()
        db["runs"] = [r for r in db["runs"] if r["run_id"] != run["run_id"]][-9:] + [run]
        PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(db))
        tmp.replace(PATH)


def latest() -> dict | None:
    with _lock:
        runs = _load()["runs"]
        run = runs[-1] if runs else None
    if run and run["status"] == "running" and time.time() - run.get("updated", 0) > STALE_SECONDS:
        run["status"] = "interrupted"  # its process stopped mid-run (restart, deploy); a new run can start
        save(run)
    if run and refresh(run):
        save(run)
    return run


def get(run_id: str) -> dict | None:
    with _lock:
        return next((r for r in _load()["runs"] if r["run_id"] == run_id), None)


def new_run(trigger: str) -> dict:
    llm = get_llm_or_unavailable()
    return {"run_id": "CR-" + uuid.uuid4().hex[:6].upper(), "status": "running", "trigger": trigger,
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds"), "llm": llm.mode,
            "canaries": [{**{k: c[k] for k in ("id", "name", "role", "team", "office")}, "total": len(journey(c)), "steps": []}
                         for c in load_canaries()],
            "walls": [], "fixes": []}


async def run(ask, trigger: str = "manual", run_rec: dict | None = None) -> dict:
    """Walk every canary (in parallel), find the walls, propose fixes, and save as it goes."""
    rec = run_rec or new_run(trigger)
    save(rec)
    activity.log("canary", f"Canary run {rec['run_id']}: {len(rec['canaries'])} synthetic new hires start onboarding", kind="step")
    cache: dict[tuple, asyncio.Future] = {}

    async def cached_ask(q: str, user: dict) -> dict:
        # The checklist steps are the same for every canary, so each is asked once and every canary gets the same
        # verdict (model answers vary run to run). Role tasks are per canary, so their office still applies.
        key = normalize(q)
        if key not in cache:
            cache[key] = asyncio.ensure_future(ask(q, user))
        return await cache[key]

    async def one(c: dict, slot: dict):
        def step(r):
            slot["steps"].append(r)
            save(rec)
        await walk(c, cached_ask, step)

    await asyncio.gather(*(one(c, slot) for c, slot in zip(load_canaries(), rec["canaries"])))
    rec["walls"] = walls(rec["canaries"])
    claims = {(s["status"], s["start_doc"], s["source_doc"]): s["claims"] for c in rec["canaries"] for s in c["steps"]}
    rec["fixes"] = [await asyncio.to_thread(propose, w, claims.get((w["status"], w["start_doc"], w["source_doc"]), []))
                    for w in rec["walls"]]
    rec["summary"] = summary(rec)
    rec["status"] = "done"
    rec["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    save(rec)
    s = rec["summary"]
    activity.log("canary", f"Run {rec['run_id']} done: {s['walls']} walls ({s['predicted']} nobody has hit yet), "
                           f"{len(rec['fixes'])} fixes for doc owners to approve", kind="done")
    return rec


def report_text(run: dict) -> str:
    """The run as chat text, for ASI:One."""
    s = run.get("summary") or summary(run)
    lines = [f"**Canary run {run['run_id']}**: {s['canaries']} synthetic new hires tried {s['steps']} onboarding steps.",
             f"{s['walls']} walls found: {s['confirmed']} that real new hires already hit, {s['predicted']} nobody has hit yet.", ""]
    for w in run.get("walls", []):
        tag = "PREDICTED" if w["predicted"] else f"confirmed by {w['humans_hit']} real blockers"
        lines.append(f"- **{w['label']}** ({tag}): {w['headline']}. Hit by {', '.join(w['canaries'])}.")
    if run.get("fixes"):
        lines += ["", f"{len(run['fixes'])} fixes drafted for the doc owners. Reply **fixes** to review them."]
    return "\n".join(lines)


def fixes_text(run: dict) -> str:
    out = []
    for f in run.get("fixes", []):
        head = {"edit": "Edit", "archive": "Archive note", "write": "Writing request"}[f["kind"]]
        if f["status"] == "drafting":
            out.append(f"**{f['id']} {head}** for '{f['doc_title']}': the CREAO Doc Steward is still drafting it.")
            continue
        if f["status"] == "blocked":
            out.append(f"**{f['id']} {head}**: blocked ({f.get('error', 'failed the check')}).")
            continue
        body = (f"\n- Before: {f['before']}\n- After: {f['after']}" if f.get("before") else f"\n- Ask: {f['after']}")
        out.append(f"**{f['id']} {head}** to {f['to']['name']} ({f['to']['role']}){': ' + repr(f['doc_title']) if f.get('doc_title') else ''}"
                   f"{body}\n- Drafted by: {f['drafter']}" + (f" ({f['run_url']})" if f.get("run_url") else "")
                   + ("\n- Sent." if f["status"] == "sent" else f"\nReply **approve {f['id']}** to send it to {f['to']['name']}."))
    return "\n\n".join(out) or "No fixes in this run."


def approve(run_id: str, fix_id: str) -> dict:
    """A person approved a fix: send it to the doc owner (DEMO_RECIPIENT_OVERRIDE gets it in a demo)."""
    from .actions import send_email

    with _lock:
        run = get(run_id)
        fix = next((f for f in (run or {}).get("fixes", []) if f["id"] == fix_id.upper()), None)
        if not fix:
            return {"ok": False, "detail": "No such fix."}
        if fix["status"] != "ready":
            return {"ok": False, "detail": f"This fix is {fix['status']}, so it can't be sent."}
        to = load_people().get(fix["to"]["id"], {})
        if fix["kind"] == "write":
            subject = "Onboarding docs: a missing how-to new hires will need"
            body = (f"Hi {fix['to']['name'].split()[0]},\n\nUnblock's canary new hires (synthetic, no real people) tried to onboard "
                    f"with our docs and couldn't find how to do this: {fix['after']}\n\n{fix['rationale']}\n\n"
                    "Could you write a few lines for it, or tell People Ops who should?\n\nThanks,\nPeople Ops (via TeamReady)")
        else:
            subject = f"Proposed fix for '{fix['doc_title']}'"
            body = (f"Hi {fix['to']['name'].split()[0]},\n\nUnblock's canary new hires (synthetic, no real people) got stuck on "
                    f"'{fix['doc_title']}'. Proposed change:\n\nBefore: {fix['before']}\nAfter: {fix['after']}\n\n"
                    f"Why: {fix['rationale']}\n\nNothing changes until you approve it.\n\nThanks,\nPeople Ops (via TeamReady)")
        result = send_email(to.get("email", ""), subject, body, "people-ops@lumen.example")
        if result["status"] != "failed":
            fix["status"] = "sent"
            save(run)
        activity.log("canary", f"People Ops approved {fix_id}; " + {"sent": "sent", "simulated": "saved to the outbox (email not set up)",
                                                                      "failed": "not sent"}[result["status"]] + f" to {fix['to']['name']}",
                     to="people", kind="message")
        return {"ok": result["status"] != "failed", "detail": result["detail"], "status": result["status"]}


def predicted_for_map(run: dict | None = None) -> list[dict]:
    """Walls from the latest run, for the Friction Map: topics only, no names."""
    run = run or latest()
    if not run or run.get("status") != "done":
        return []
    return [{"wall": w["label"], "task": w["task"], "doc": w.get("doc_title", ""), "canaries": len(w["canaries"]),
             "humans_hit": w["humans_hit"], "predicted": w["predicted"]} for w in run["walls"]]
