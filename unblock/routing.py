"""Who should the new hire ask? A transparent weighted score, computed in code.

score = 50% skill match + 30% team/process match + 20% availability - feedback penalty

Fairness rotation: among everyone within 10% of the top score, TeamReady picks the
person with the lightest recent question load, so the same senior engineer isn't
always the default. Protected characteristics are never inputs.

Feedback: "wrong person" lowers that person's score for that topic next time.
"""
import json
from dataclasses import asdict, dataclass

from .config import DATA_DIR
from .data import load_docs, load_people, load_policies
from .retrieval import search
from .text import tokens

FEEDBACK_PATH = DATA_DIR / "runtime" / "feedback.json"
ROTATION_BAND = 0.10
PENALTY_PER_FLAG = 0.25


@dataclass
class Candidate:
    person_id: str
    name: str
    role: str
    team: str
    email: str
    score: float
    factors: dict
    reasons: list[str]


@dataclass
class RoutingResult:
    topic_key: str
    chosen: Candidate | None
    alternatives: list[Candidate]
    rotation_note: str

    def to_dict(self) -> dict:
        return asdict(self)


def _load_feedback() -> dict:
    if FEEDBACK_PATH.exists():
        return json.loads(FEEDBACK_PATH.read_text())
    return {}


def record_wrong_person(person_id: str, topic_key: str) -> int:
    feedback = _load_feedback()
    key = f"{person_id}|{topic_key}"
    feedback[key] = feedback.get(key, 0) + 1
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEEDBACK_PATH.write_text(json.dumps(feedback, indent=1))
    return feedback[key]


def reset_feedback() -> None:
    if FEEDBACK_PATH.exists():
        FEEDBACK_PATH.unlink()


def rank(question: str, user: dict, retrieved_doc_ids: list[str] | None = None, exclude: set[str] | None = None) -> RoutingResult:
    docs = load_docs()
    people = load_people()
    exclude = set(exclude or ())
    if retrieved_doc_ids is None:
        found = search(question, office=user.get("office", ""))
        # Weak matches say nothing about who owns the topic; route on skills alone.
        retrieved_doc_ids = [d.doc.id for d in found.docs] if found.top_score >= 3.0 else []
    fresh_ids = [i for i in retrieved_doc_ids if i in docs]
    topic_key = fresh_ids[0] if fresh_ids else "general"
    top_team = docs[fresh_ids[0]].team if fresh_ids else ""
    owners = {docs[i].owner: (1.0 if n == 0 else 0.8) for n, i in reversed(list(enumerate(fresh_ids)))}
    q_tokens = set(tokens(question))
    feedback = _load_feedback()

    candidates = []
    for pid, person in people.items():
        if pid in exclude:
            continue
        reasons = []
        skill_tokens = set(tokens(" ".join(person["skills"])))
        overlap = len(q_tokens & skill_tokens)
        skill = 0.8 if overlap >= 2 else 0.5 if overlap == 1 else 0.0
        if pid in owners and owners[pid] >= skill:
            skill = owners[pid]
            owned = [docs[i].title for i in fresh_ids if docs[i].owner == pid]
            reasons.append(f"owns {owned[0]}")
        elif overlap:
            reasons.append("skills: " + ", ".join(s for s in person["skills"] if set(tokens(s)) & q_tokens))
        team = 1.0 if top_team and person["team"] == top_team else 0.5 if person["team"] == user.get("team") else 0.0
        if team == 1.0:
            reasons.append(f"on the {person['team']} team that owns this process")
        elif team == 0.5:
            reasons.append("on your team")
        avail = (0.7 if person["available"] else 0.0) + (0.3 if person["timezone"] == user.get("timezone") else 0.0)
        reasons.append("available today" if person["available"] else "away today")
        flags = feedback.get(f"{pid}|{topic_key}", 0)
        penalty = PENALTY_PER_FLAG * flags
        if flags:
            reasons.append(f"marked 'wrong person' {flags}x for this topic")
        score = round(0.5 * skill + 0.3 * team + 0.2 * avail - penalty, 3)
        if skill == 0 and team == 0:
            continue
        candidates.append(Candidate(pid, person["name"], person["role"], person["team"], person["email"], score,
                                    {"skill": round(skill, 2), "team": round(team, 2), "availability": round(avail, 2),
                                     "penalty": round(penalty, 2), "recent_load": person["recent_load"]}, reasons))

    candidates.sort(key=lambda c: c.score, reverse=True)
    if not any(c.factors["skill"] > 0 for c in candidates):
        # Nobody clearly owns this topic: People Ops triages general questions.
        default_id = load_policies().get("default_helper", "")
        person = people.get(default_id)
        if person and default_id not in exclude:
            fallback = Candidate(default_id, person["name"], person["role"], person["team"], person["email"], 0.0,
                                 {"skill": 0.0, "team": 0.0, "availability": 0.0, "penalty": 0.0, "recent_load": person["recent_load"]},
                                 ["no doc or skill clearly covers this", "People Ops triages general questions"])
            return RoutingResult(topic_key, fallback, candidates[:2], "")
    if not candidates:
        return RoutingResult(topic_key, None, [], "")
    top = candidates[0].score
    band = [c for c in candidates if c.score >= top * (1 - ROTATION_BAND) and c.score > 0]
    chosen = min(band, key=lambda c: (c.factors["recent_load"], -c.score))
    note = ""
    if chosen is not candidates[0]:
        leader = candidates[0]
        note = (f"{leader.name} and {chosen.name} are both a strong match. {chosen.name} has answered fewer "
                f"questions recently ({chosen.factors['recent_load']} vs {leader.factors['recent_load']}), so I'm "
                "spreading questions across qualified people.")
    alternatives = [c for c in candidates if c is not chosen][:2]
    return RoutingResult(topic_key, chosen, alternatives, note)
