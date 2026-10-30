"""Confidence, computed in code from four visible factors. No fixed base points.

retrieval     30 pts  how strongly the best doc matched the question
agreement     25 pts  0 if the docs used conflict (for example a stale runbook)
freshness     15 pts  how recently the cited docs were updated
verification  30 pts  share of the AI's claims the verifier accepted
"""
from dataclasses import dataclass

RETRIEVAL_FULL_AT = 10.0  # BM25 score treated as a full-strength match


@dataclass
class Confidence:
    score: int
    label: str
    factors: dict[str, dict]

    def summary(self) -> str:
        return ", ".join(f"{k} {v['points']}/{v['max']}" for k, v in self.factors.items())


def compute(top_score: float, conflict: bool, newest_age_days: int | None, verified: int, total: int) -> Confidence:
    retrieval = round(30 * min(1.0, top_score / RETRIEVAL_FULL_AT))
    agreement = 0 if conflict else 25
    if newest_age_days is None:
        freshness = 0
    elif newest_age_days <= 90:
        freshness = 15
    elif newest_age_days <= 365:
        freshness = 8
    else:
        freshness = 0
    verification = round(30 * verified / total) if total else 0
    score = retrieval + agreement + freshness + verification
    label = "High" if score >= 80 else "Medium" if score >= 60 else "Low"
    return Confidence(
        score=score,
        label=label,
        factors={
            "retrieval": {"value": f"match strength {top_score:.1f}", "points": retrieval, "max": 30},
            "agreement": {"value": "conflict found" if conflict else "sources agree", "points": agreement, "max": 25},
            "freshness": {"value": "unknown" if newest_age_days is None else f"newest source {newest_age_days} days old", "points": freshness, "max": 15},
            "verification": {"value": f"{verified} of {total} claims verified", "points": verification, "max": 30},
        },
    )
