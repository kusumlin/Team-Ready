"""Turn results into chat text plus an Interactive Card payload."""
from .data import load_docs

NEVER_DO = [
    "send or file anything without your approval",
    "grant access or approve its own requests",
    "read private DMs, performance reviews or pay data",
    "present an answer as fact when it can't find the source",
]


def _sources_line(citations: list[dict]) -> str:
    return "; ".join(f"{c['title']} (updated {c['updated_at']}, owner {c['owner']})" for c in citations) or "none"


def trust_rows(answer: dict, helper: dict | None = None, data_used: str = "your role, team, office and this question") -> list[dict]:
    conf = answer.get("confidence", {})
    rows = [
        {"label": "What I did", "value": " -> ".join(answer.get("trace", []))[:400]},
        {"label": "Sources", "value": _sources_line(answer.get("citations", []))[:400]},
        {"label": "Confidence", "value": f"{conf.get('label', '?')} ({conf.get('score', 0)}/100): " +
         ", ".join(f"{k} {v['points']}/{v['max']}" for k, v in conf.get("factors", {}).items())},
        {"label": "Claims blocked", "value": str(len(answer.get("blocked", [])))},
    ]
    if helper:
        rows.append({"label": "Why this person", "value": "; ".join(helper.get("reasons", []))})
    rows.append({"label": "Data used", "value": data_used})
    rows.append({"label": "Data not used", "value": "performance, pay, demographics, private messages"})
    return rows


def answer_text(answer: dict) -> str:
    lines = [f"**{answer['title']}**", ""]
    if answer["claims"]:
        lines.append("What the approved docs say:")
        for c in answer["claims"]:
            lines.append(f"- {c['text']}  [{c['source_id']}]")
    if answer["steps"]:
        lines += ["", "Your next steps:"]
        for i, s in enumerate(answer["steps"], 1):
            lines.append(f"{i}. {s['text']}  [{s['source_id']}]")
    for conflict in answer.get("conflicts", []):
        lines += ["", f"Heads up: {conflict['description']}"]
    if answer.get("blocked"):
        lines += ["", f"Blocked {len(answer['blocked'])} claim(s) I couldn't find word for word in a source:"]
        for b in answer["blocked"][:3]:
            lines.append(f"- ~~{b['text']}~~ ({b['reason']})")
    conf = answer["confidence"]
    lines += ["", f"Confidence: {conf['label']} ({conf['score']}/100). Sources: {_sources_line(answer['citations'])}"]
    if answer.get("llm_mode") == "extractive":
        lines.append("_Mode: extractive (no AI model). Answers are direct quotes from the docs._")
    return "\n".join(lines)


def answer_card(answer: dict, helper: dict | None) -> dict:
    ctas = []
    if helper:
        ctas.append({"label": f"Still stuck? Ask {helper['name']}", "selection": {"action": "ub_ask_helper"}})
    ctas.append({"label": "This looks wrong", "selection": {"action": "ub_wrong_answer"}})
    return {"title": f"{answer['title']} · {answer['confidence']['label']} confidence",
            "summary_rows": trust_rows(answer, helper), "ctas": ctas}


def action_text(pending: dict, answer: dict | None, helper: dict | None, rotation_note: str = "") -> str:
    kind = {"message_helper": "Message", "book_1_1": "1:1 invite", "access_request": "Access request for manager approval",
            "doc_owner_note": "Note to the doc owner"}[pending["type"]]
    lines = []
    if answer and answer.get("route_reason"):
        lines.append(answer["route_reason"])
    if answer and answer.get("claims"):
        lines.append("What I could verify so far:")
        lines += [f"- {c['text']}  [{c['source_id']}]" for c in answer["claims"]]
    if answer and answer.get("blocked"):
        lines.append(f"(Blocked {len(answer['blocked'])} unsupported claim(s) before showing you anything.)")
    if helper:
        lines += ["", f"Best person to ask: **{helper['name']}**, {helper['role']} ({'; '.join(helper['reasons'])})."]
    if rotation_note:
        lines.append(f"Fairness note: {rotation_note}")
    lines += ["", f"I drafted this {kind.lower()} for you. Nothing is sent until you approve it.",
              f"To: {pending['to_name']} <{pending['to_email']}>", f"Subject: {pending['subject']}", "", pending["body"], "",
              "Reply **approve**, **reject**, **edit: <your new message>**, or **wrong person**."]
    return "\n".join(lines)


def action_card(pending: dict, answer: dict | None, helper: dict | None) -> dict:
    what_happens = {
        "message_helper": "TeamReady emails this message from you. Nothing else is shared.",
        "book_1_1": "TeamReady emails this message with a 30-minute calendar invite.",
        "access_request": f"TeamReady sends this to {pending['to_name']}'s approval agent. Only your manager can approve it.",
        "doc_owner_note": "TeamReady emails the doc owner. They decide whether to update the doc.",
    }[pending["type"]]
    rows = [{"label": "To", "value": f"{pending['to_name']} ({pending['to_role']})"},
            {"label": "Subject", "value": pending["subject"]},
            {"label": "Message", "value": pending["body"][:600]},
            {"label": "What happens", "value": what_happens},
            {"label": "Data shared", "value": "your name, role and this message only"},
            {"label": "Guardian check", "value": ("Blocked: " + "; ".join(pending["guardian"])) if pending.get("guardian")
             else "Clear: no pay, performance, health, personal data or secrets"}]
    if answer:
        rows += [r for r in trust_rows(answer, helper) if r["label"] in ("Sources", "Confidence", "Claims blocked", "Why this person")]
    return {"title": "Review before anything is sent", "summary_rows": rows,
            "approve_cta": {"label": "Approve and send", "primary": True, "selection": {"action": "ub_approve"}},
            "reject_cta": {"label": "Reject", "selection": {"action": "ub_reject"}}}


def system_text(p: dict) -> str:
    """A pending action in a Lumen system (or the checklist autopilot), shown before anything happens."""
    if p["type"] == "system_batch":
        return p["body"]
    form = "\n".join(f"- {k.replace('_', ' ').capitalize()}: {', '.join(v) if isinstance(v, list) else v}"
                     for k, v in p["form"].items() if k not in ("why", "with_email"))
    return (f"**{p['title']}**, in {p['system']}. Here's exactly what I'll do:\n{p['does']}\n\n{form}\n\n"
            f"Why: {p['form'].get('why', '')}\n\nNothing happens until you reply **approve** (or **reject**).")


def system_card(p: dict) -> dict:
    if p["type"] == "system_batch":
        mark = {"will_do": "I'll do it", "manager": "Needs your manager", "done": "Already done", "person": "You or a person",
                "waiting": "With your manager"}
        rows = [{"label": mark[x["status"]], "value": x["step"].rstrip(".") + (f": {x['does']}" if x.get("does") else f": {x.get('why', '')}" if x.get("why") else "")}
                for x in p["plan"]]
        return {"title": "Your onboarding checklist: I can do these for you", "summary_rows": rows,
                "approve_cta": {"label": "Approve and do them", "primary": True, "selection": {"action": "ub_approve"}},
                "reject_cta": {"label": "Not now", "selection": {"action": "ub_reject"}}}
    rows = [{"label": "System", "value": p["system"]}, {"label": "What I'll do", "value": p["does"]}]
    rows += [{"label": k.replace("_", " ").capitalize(), "value": ", ".join(v) if isinstance(v, list) else str(v)}
             for k, v in p["form"].items() if k not in ("why", "with_email")]
    rows += [{"label": "Source", "value": p["form"].get("why", "")},
             {"label": "Guardian check", "value": ("Blocked: " + "; ".join(p["guardian"])) if p.get("guardian") else "Clear"}]
    return {"title": f"Review before I do it: {p['title']}", "summary_rows": rows,
            "approve_cta": {"label": "Approve and do it", "primary": True, "selection": {"action": "ub_approve"}},
            "reject_cta": {"label": "Reject", "selection": {"action": "ub_reject"}}}


def stop_text(risk: dict, human: dict) -> str:
    return "\n".join([
        f"**This needs a person, not an assistant.** ({risk['category']})",
        risk["reason"],
        "",
        "I stopped before searching, choosing anyone, or drafting a message.",
        f"The right person: **{human['name']}**, {human['role']} ({risk['channel']}).",
        "",
        "TeamReady will never: " + "; ".join(NEVER_DO) + ".",
    ])


def friction_text(fmap: dict, full: bool = False) -> str:
    lines = [f"**Friction Map: last {fmap['window_days']} days** ({fmap['data_note']})",
             f"{fmap['total_blockers']} blockers · {round(fmap['resolved_without_ticket_share'] * 100)}% resolved without a ticket · "
             f"{fmap['process_gaps']} process gaps · {fmap['hidden_small_cohort_events']} events hidden (groups under {fmap['min_cohort_size']})", ""]
    for c in fmap["clusters"][: (len(fmap["clusters"]) if full else 4)]:
        line = f"- {c['topic']}: {c['count']} blockers, {round(c['resolved_share'] * 100)}% self-resolved"
        if full and c["pattern"]:
            line += f". Pattern: {c['pattern']}"
        lines.append(line)
    walls = fmap.get("canary_walls")
    if walls is None:
        from .canary import predicted_for_map
        walls = predicted_for_map()
    predicted = [w for w in walls if w["predicted"]]
    if predicted:
        lines += ["", "**Predicted by Canary New Hires** (no real new hire has hit these yet):"]
        lines += [f"- {w['wall']}: {w['task'].rstrip('.')}" + (f" ('{w['doc']}')" if w["doc"] else "") for w in predicted]
    return "\n".join(lines)


def doc_title(doc_id: str) -> str:
    doc = load_docs().get(doc_id)
    return doc.title if doc else doc_id


def guardian_text(issues: list[str]) -> str:
    return ("**Guardian stopped this draft:** it " + "; it ".join(issues) +
            ". TeamReady won't send it. Remove that part with **edit: <new message>**, or **reject** it.")
