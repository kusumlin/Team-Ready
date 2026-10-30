"""Risk gate. Runs in code before any model call or search.

stop      -> high-impact topic (pay, performance, benefits eligibility, employment,
             harassment). No search, no draft. Route to a named human channel.
approval  -> elevated or gated access. TeamReady may prepare a request, but only the
             manager agent (a human) can approve it.
routine   -> normal onboarding question.
"""
import re
from dataclasses import dataclass

from .data import load_policies


@dataclass
class Risk:
    level: str  # "stop" | "approval" | "routine"
    category: str = "routine onboarding"
    reason: str = "No high-impact workplace category was detected."
    human_id: str = ""
    channel: str = ""
    approver: str = ""
    matched_term: str = ""


def _matches(text: str, term: str) -> bool:
    """Whole words or phrases by default; a trailing * marks a prefix (harass* matches harassment)."""
    term = term.lower().strip()
    if term.endswith("*"):
        return re.search(rf"(?<![a-z0-9]){re.escape(term[:-1])}", text) is not None
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text) is not None


def assess(query: str) -> Risk:
    text = " " + re.sub(r"\s+", " ", query.lower()) + " "
    policies = load_policies()
    for rule in policies["stop_categories"]:
        for term in rule["terms"]:
            if _matches(text, term):
                return Risk(
                    level="stop",
                    category=rule["category"],
                    reason=rule["reason"],
                    human_id=rule["human_id"],
                    channel=rule["channel"],
                    matched_term=term.strip(),
                )
    for rule in policies["approval_categories"]:
        for term in rule["terms"]:
            if _matches(text, term):
                return Risk(
                    level="approval",
                    category=rule["category"],
                    reason=rule["reason"],
                    approver=rule["approver"],
                    matched_term=term.strip(),
                )
    return Risk(level="routine")


# ---------- Guardian: checks every outgoing draft ----------
# It can only raise risk: a flagged draft can't be sent until the new hire edits it clean.

_SECRET_PATTERNS = [
    ("a Social Security number", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("a password or passcode", re.compile(r"\b(password|passcode|passwd|pwd)\s*(is|:|=)", re.I)),
    ("an API key or token", re.compile(r"\b(sk|pk|ghp|xox[abp])[-_][A-Za-z0-9_\-]{16,}|\bAKIA[0-9A-Z]{16}\b")),
    ("a date of birth", re.compile(r"\b(date of birth|dob|born on)\b", re.I)),
]
_HEALTH = re.compile(r"\b(diagnos\w*|medical condition|medication|pregnan\w*|disabilit\w*|therapy|therapist|surgery|illness)\b", re.I)


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for d in reversed(digits):
        n = int(d)
        if alt:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
        alt = not alt
    return total % 10 == 0


def check_draft(subject: str, body: str) -> list[str]:
    """Return the reasons a draft must not be sent (empty list = clear)."""
    text = f"{subject}\n{body}"
    issues = []
    padded = " " + re.sub(r"\s+", " ", text.lower()) + " "
    for rule in load_policies()["stop_categories"]:
        if any(_matches(padded, term) for term in rule["terms"]):
            issues.append(f"mentions {rule['category']}, which belongs in a private conversation with HR or your manager")
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            issues.append(f"contains {label}")
    for m in re.finditer(r"\b(?:\d[ -]?){13,19}\b", text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            issues.append("contains what looks like a card number")
            break
    if _HEALTH.search(text):
        issues.append("mentions personal health details")
    return issues
