"""BM25 search over doc passages, with region filtering and stale-doc flags.

Each line of a doc is one passage. The doc title is added to every passage's
index text so a question like "deploy to staging" matches the right doc even
when the passage itself doesn't repeat the title words.
"""
import math
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache

from .config import STALE_AFTER_DAYS, today
from .data import Doc, Passage, load_docs
from . import semantic
from .text import tokens

K1 = 1.4
B = 0.75
TITLE_BOOST = 2  # title tokens are repeated this many times in the index


@dataclass
class Hit:
    passage: Passage
    score: float


@dataclass
class DocHit:
    doc: Doc
    score: float
    passages: list[Hit]
    stale: bool
    age_days: int


@dataclass
class SearchResult:
    query: str
    docs: list[DocHit]
    excluded_regional: list[Doc] = field(default_factory=list)
    searched_count: int = 0
    method: str = "keyword (BM25)"

    @property
    def top_score(self) -> float:
        return self.docs[0].score if self.docs else 0.0


class _Index:
    def __init__(self, docs: dict[str, Doc]):
        self.passages: list[Passage] = []
        self.terms: list[Counter] = []
        for doc in docs.values():
            title_tokens = tokens(doc.title) * TITLE_BOOST
            for passage in doc.passages:
                self.passages.append(passage)
                self.terms.append(Counter(tokens(passage.text) + title_tokens))
        self.n = len(self.passages)
        self.avg_len = sum(sum(c.values()) for c in self.terms) / max(self.n, 1)
        df = Counter()
        for counter in self.terms:
            df.update(counter.keys())
        self.idf = {t: math.log(1 + (self.n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def score(self, query_tokens: list[str], i: int) -> float:
        counter = self.terms[i]
        length = sum(counter.values())
        total = 0.0
        for t in set(query_tokens):
            tf = counter.get(t, 0)
            if not tf:
                continue
            total += self.idf[t] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / self.avg_len))
        return total


@lru_cache(maxsize=1)
def _index() -> _Index:
    return _Index(load_docs())


def search(query: str, office: str = "", max_docs: int = 4, per_doc: int = 3) -> SearchResult:
    docs = load_docs()
    index = _index()
    q = tokens(query)
    bonus: dict[str, float] = {}
    method = "keyword (BM25)"
    if semantic.enabled():
        try:
            bonus = semantic.scores(query)
            method = "hybrid: keyword (BM25) + Gemini embeddings"
        except Exception as exc:  # Gemini down: keep working on keywords
            method = f"keyword (BM25); Gemini embeddings unavailable ({type(exc).__name__})"
    hits = [Hit(p, index.score(q, i) + bonus.get(p.ref, 0.0)) for i, p in enumerate(index.passages)]
    hits = [h for h in hits if h.score > 0]

    by_doc: dict[str, list[Hit]] = {}
    for hit in sorted(hits, key=lambda h: h.score, reverse=True):
        by_doc.setdefault(hit.passage.doc_id, []).append(hit)

    ranked: list[DocHit] = []
    excluded: list[Doc] = []
    now = today()
    for doc_id, doc_hits in by_doc.items():
        doc = docs[doc_id]
        if office and doc.region not in ("global", office):
            excluded.append(doc)
            continue
        top = doc_hits[:per_doc]
        # Doc score: best passage plus a small bonus for more matching passages.
        score = top[0].score + 0.25 * sum(h.score for h in top[1:])
        age = (now - doc.updated_at).days
        ranked.append(DocHit(doc, score, top, stale=age > STALE_AFTER_DAYS, age_days=age))

    ranked.sort(key=lambda d: d.score, reverse=True)
    best = ranked[0].score if ranked else 0.0
    # Keep docs that score at least 35% of the best one.
    kept = [d for d in ranked if d.score >= 0.35 * best][:max_docs]
    kept_ids = {d.doc.id for d in kept}
    excluded = [d for d in excluded if by_doc[d.id][0].score >= 0.35 * best and d.id not in kept_ids]
    return SearchResult(query=query, docs=kept, excluded_regional=excluded, searched_count=len(docs), method=method)
