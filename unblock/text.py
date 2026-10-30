"""Small text helpers shared by retrieval, routing and the verifier."""
import re

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "can", "do", "does", "for",
    "from", "get", "how", "i", "if", "in", "into", "is", "it", "its", "me", "my", "need",
    "of", "on", "or", "our", "should", "so", "that", "the", "their", "then", "there", "this",
    "to", "up", "us", "was", "we", "what", "when", "where", "which", "who", "why", "will",
    "with", "you", "your", "want", "trying", "help", "please", "know", "im", "i'm", "am", "lumen", "labs",
}

_TOKEN = re.compile(r"[a-z0-9]+")


def stem(token: str) -> str:
    for suffix in ("ing", "ies", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


SYNONYMS = {
    "vacation": ["time", "off"], "pto": ["time", "off"], "leave": ["time", "off"], "holiday": ["time", "off"],
    "prod": ["production"], "repo": ["repository"], "reimburse": ["expense"], "reimbursement": ["expense"],
    "looker": ["analytics", "dashboard"], "laptop": ["laptop", "device"], "2fa": ["mfa"],
}


def tokens(text: str) -> list[str]:
    out = []
    for t in _TOKEN.findall(text.lower()):
        if t in STOPWORDS:
            continue
        out.extend(SYNONYMS.get(t, [t]))
    return [stem(t) for t in out]


def normalize(text: str) -> str:
    """Normalize text for verbatim comparison: case, quotes, dashes, spaces."""
    text = text.lower()
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip().strip(".,;:!?\"' ")


NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in NUMBER.findall(text)}
