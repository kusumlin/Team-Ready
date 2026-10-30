"""The answer pipeline: search -> model -> verifier -> confidence -> decision.

Only verified claims and steps are ever shown. The model's free text is not.
"""
from dataclasses import asdict, dataclass, field

from .confidence import compute
from .data import load_docs, load_people
from .llm import LLMError
from .retrieval import search
from .verifier import Claim, verify_all, verify_claim

MIN_RETRIEVAL = 3.0   # below this, nothing in the docs is about the question
ANSWER_AT = 60        # confidence needed to answer without routing to a person


@dataclass
class AnswerResult:
    question: str
    decision: str                 # "answer" | "route"
    title: str
    claims: list[dict]            # verified only
    steps: list[dict]             # verified only
    blocked: list[dict]           # claims the verifier removed, with reasons
    conflicts: list[dict]
    citations: list[dict]
    confidence: dict
    trace: list[str]
    missing: str = ""
    route_reason: str = ""
    llm_mode: str = ""
    error: str = ""
    retrieved_doc_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _claims(raw: list) -> list[Claim]:
    out = []
    for item in raw or []:
        if isinstance(item, dict):
            out.append(Claim(str(item.get("text", "")), str(item.get("quote", "")), str(item.get("source_id", "")).split("#")[0]))
    return out


def answer(question: str, user: dict, llm, verify: bool = True) -> AnswerResult:
    docs = load_docs()
    people = load_people()
    result = search(question, office=user.get("office", ""))
    trace = [f"Searched {result.searched_count} approved docs ({result.method})"]
    if user.get("profile_source") == "Workday":
        trace.insert(0, "Read your name, title and organization from Workday (nothing else)")
    if result.excluded_regional:
        names = ", ".join(f"{d.title}" for d in result.excluded_regional)
        trace.append(f"Set aside {names}: it applies to a different office than yours ({user.get('office')})")

    fresh = [d for d in result.docs if not d.stale]
    stale = [d for d in result.docs if d.stale]
    conflicts: list[dict] = []
    if stale and fresh:
        for s in stale:
            conflicts.append({
                "type": "stale doc",
                "description": f"'{s.doc.title}' was last updated {s.age_days // 365} years ago and disagrees with newer docs, so it was not used.",
                "stale_doc_id": s.doc.id,
                "owner_id": s.doc.owner,
            })
            trace.append(f"Flagged '{s.doc.title}' as stale ({s.age_days} days old) and left it out")
    use = fresh or stale
    allowed = {d.doc.id: d.doc for d in use}

    if not result.docs or result.top_score < MIN_RETRIEVAL:
        trace.append("No approved doc covers this question")
        conf = compute(result.top_score, False, None, 0, 0)
        return AnswerResult(question, "route", "No approved answer found", [], [], [], conflicts, [], conf.__dict__, trace,
                            missing=question, route_reason="No approved doc covers this, so a person should answer.", llm_mode=getattr(llm, "mode", ""))

    passages = []
    for d in result.docs:
        for hit in d.passages:
            passages.append({
                "doc_id": d.doc.id, "title": d.doc.title, "updated_at": d.doc.updated_at.isoformat(),
                "stale": d.stale, "text": hit.passage.text, "score": hit.score,
            })
        # Give the model the doc's other lines too, so steps can be complete.
        for p in d.doc.passages:
            if all(p.text != x["text"] for x in passages):
                passages.append({"doc_id": d.doc.id, "title": d.doc.title, "updated_at": d.doc.updated_at.isoformat(),
                                 "stale": d.stale, "text": p.text, "score": 0.0})
    n = len(result.docs)
    trace.append(f"Found {n} relevant doc{'s' if n != 1 else ''}: " + ", ".join(d.doc.title for d in result.docs))

    try:
        raw = llm.answer(question, user, passages)
    except LLMError as exc:
        conf = compute(result.top_score, bool(conflicts), None, 0, 0)
        trace.append(f"Model unavailable: {exc}")
        return AnswerResult(question, "route", "I couldn't reach the model", [], [], [], conflicts, [], conf.__dict__, trace,
                            route_reason="The reasoning model is unavailable, so a person should answer.", llm_mode=getattr(llm, "mode", ""),
                            error=str(exc), retrieved_doc_ids=[d.doc.id for d in result.docs])

    if not isinstance(raw, dict):
        raw = {}
    claims = _claims(raw.get("claims") if isinstance(raw.get("claims"), list) else [])
    steps = _claims(raw.get("steps") if isinstance(raw.get("steps"), list) else [])
    total = len(claims) + len(steps)
    if verify:
        claim_verdicts = verify_all(claims, allowed)
        step_verdicts = verify_all(steps, allowed)
    else:  # eval only: shows what would reach the user without the verifier
        from .verifier import Verdict
        claim_verdicts = [Verdict(c, True, "verifier off") for c in claims]
        step_verdicts = [Verdict(c, True, "verifier off") for c in steps]

    ok_claims = [{"text": v.claim.text, "quote": v.claim.quote, "source_id": v.claim.source_id} for v in claim_verdicts if v.passed]
    ok_steps = [{"text": v.claim.text, "quote": v.claim.quote, "source_id": v.claim.source_id} for v in step_verdicts if v.passed]
    blocked = [{"text": v.claim.text, "reason": v.reason} for v in claim_verdicts + step_verdicts if not v.passed]
    verified = len(ok_claims) + len(ok_steps)
    trace.append(f"Verified {verified} of {total} claims word for word" + (f"; blocked {len(blocked)}" if blocked else ""))

    for c in raw.get("conflicts") if isinstance(raw.get("conflicts"), list) else []:
        if not isinstance(c, dict):
            continue
        a = Claim("", str(c.get("quote_a", "")), str(c.get("source_a", "")).split("#")[0])
        b = Claim("", str(c.get("quote_b", "")), str(c.get("source_b", "")).split("#")[0])
        all_docs = {d.doc.id: d.doc for d in result.docs}
        if verify_claim(a, all_docs).passed and verify_claim(b, all_docs).passed and a.source_id != b.source_id:
            if not any(x.get("stale_doc_id") in (a.source_id, b.source_id) for x in conflicts):
                conflicts.append({"type": "docs disagree", "description": str(c.get("description", "Two docs disagree.")),
                                  "sources": [a.source_id, b.source_id]})
                trace.append("Found two docs that disagree")

    cited_ids = sorted({c["source_id"] for c in ok_claims + ok_steps})
    ages =[d.age_days for d in result.docs if d.doc.id in cited_ids]
    newest_age = min(ages) if ages else None
    # A stale doc we set aside is resolved, not an open conflict; only live disagreements lower agreement.
    open_conflict = any(c["type"] == "docs disagree" for c in conflicts)
    conf = compute(result.top_score, open_conflict, newest_age, verified, total)

    citations = []
    for doc_id in cited_ids:
        doc = docs[doc_id]
        owner = people.get(doc.owner, {})
        citations.append({"id": doc.id, "title": doc.title, "updated_at": doc.updated_at.isoformat(),
                          "owner": owner.get("name", doc.owner), "owner_id": doc.owner})

    can_answer = raw.get("can_answer") is True and verified > 0
    decision = "answer" if can_answer and conf.score >= ANSWER_AT and not open_conflict else "route"
    route_reason = ""
    if decision == "route":
        if open_conflict:
            route_reason = "Two approved docs disagree, so the doc owner should confirm."
        elif not can_answer:
            route_reason = "The docs don't fully answer this, so a person should."
        else:
            route_reason = f"Confidence is {conf.label.lower()} ({conf.score}), so a person should confirm."

    return AnswerResult(
        question=question, decision=decision, title=str(raw.get("title") or "Here's what the docs say")[:80],
        claims=ok_claims, steps=ok_steps, blocked=blocked, conflicts=conflicts, citations=citations,
        confidence=conf.__dict__, trace=trace, missing=str(raw.get("missing") or "")[:300], route_reason=route_reason,
        llm_mode=getattr(llm, "mode", ""), retrieved_doc_ids=[d.doc.id for d in result.docs],
    )
