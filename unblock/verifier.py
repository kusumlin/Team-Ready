"""The verifier: plain code that decides which AI claims a new hire may see.

A claim passes only if:
1. it cites a doc that was actually retrieved for this question,
2. its supporting quote appears word for word in that doc, on word boundaries
   (after normalizing case, quotes, dashes and spaces),
3. the quote is long enough to mean something (at least 4 words),
4. the quote isn't cut out of a negated sentence ("...do not get production
   access..." can't be quoted as "get production access"),
5. the claim and its quote agree on negation (one can't say "not" when the other doesn't),
6. most of the claim's content words appear in the quote, so the claim can't
   say something the quote doesn't, and
7. every number in the claim also appears in the quote ("100 USD" can't be
   backed by a quote that says "75 USD").
Anything else is blocked and never shown as fact.
"""
import re
from dataclasses import dataclass

from .data import Doc
from .text import normalize, numbers, tokens

MIN_QUOTE_WORDS = 4
MIN_OVERLAP = 0.6
NEGATIONS = {"not", "no", "never", "cannot", "can't", "don't", "doesn't", "isn't", "aren't", "won't", "without", "unless", "nor"}


@dataclass
class Claim:
    text: str
    quote: str
    source_id: str


@dataclass
class Verdict:
    claim: Claim
    passed: bool
    reason: str


def _negated(words: list[str]) -> bool:
    return any(w.strip(".,;:") in NEGATIONS or w.endswith("n't") for w in words)


def verify_claim(claim: Claim, allowed_docs: dict[str, Doc]) -> Verdict:
    doc = allowed_docs.get(claim.source_id)
    if doc is None:
        return Verdict(claim, False, f"cites {claim.source_id or 'no source'}, which was not retrieved")
    quote = normalize(claim.quote)
    if len(quote.split()) < MIN_QUOTE_WORDS:
        return Verdict(claim, False, "supporting quote is too short to verify")
    body = normalize(doc.body)
    match = re.search(rf"(?<![a-z0-9]){re.escape(quote)}(?![a-z0-9])", body)
    if not match:
        return Verdict(claim, False, f"quote not found word for word in {doc.id}")
    # Words just before the quote, within the same sentence.
    sentence_start = max(body.rfind(". ", 0, match.start()), body.rfind("\n", 0, match.start()))
    before = body[sentence_start + 1 : match.start()].split()[-3:]
    if _negated(before):
        return Verdict(claim, False, "quote leaves out a 'not' that comes just before it")
    if _negated(normalize(claim.text).split()) != _negated(quote.split()):
        return Verdict(claim, False, "claim and quote disagree on negation")
    claim_words = set(tokens(claim.text))
    if not claim_words:
        return Verdict(claim, False, "claim has no content to verify")
    quote_words = set(tokens(claim.quote)) | set(tokens(doc.title))
    overlap = len(claim_words & quote_words) / len(claim_words)
    if overlap < MIN_OVERLAP:
        return Verdict(claim, False, f"claim says things its quote doesn't ({overlap:.0%} word overlap)")
    missing = numbers(claim.text) - numbers(claim.quote)
    if missing:
        return Verdict(claim, False, f"number {', '.join(sorted(missing))} is not in the quoted source")
    return Verdict(claim, True, f"verified in {doc.id}")


def verify_all(claims: list[Claim], allowed_docs: dict[str, Doc]) -> list[Verdict]:
    return [verify_claim(c, allowed_docs) for c in claims]
