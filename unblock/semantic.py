"""Meaning-based scores from Gemini embeddings, blended into BM25 search.

Turn on with UNBLOCK_EMBEDDINGS=gemini. Passage vectors are cached on disk, so
only new or edited passages are embedded again. If Gemini is unavailable, search
falls back to keywords only and the trust trace says so.
"""
import hashlib
import json
import math

from .config import DATA_DIR, env
from .data import load_docs

CACHE_DIR = DATA_DIR / "runtime"
SEM_WEIGHT = float(env("UNBLOCK_SEM_WEIGHT", "6"))
SEM_FLOOR = float(env("UNBLOCK_SEM_FLOOR", "0.55"))  # cosine below this adds nothing

_embedder = None


def enabled() -> bool:
    return env("UNBLOCK_EMBEDDINGS").lower() == "gemini"


def get_embedder():
    global _embedder
    if _embedder is None:
        from .providers import GeminiEmbedder
        _embedder = GeminiEmbedder()
    return _embedder


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _passage_vectors(embedder) -> dict[str, list[float]]:
    cache_path = CACHE_DIR / f"embeddings_{getattr(embedder, 'model', 'model')}.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    wanted, texts = [], []
    vectors = {}
    for doc in load_docs().values():
        for p in doc.passages:
            text = f"{doc.title}: {p.text}"
            key = f"{p.ref}|{hashlib.sha1(text.encode()).hexdigest()[:10]}"
            if key in cache:
                vectors[p.ref] = cache[key]
            else:
                wanted.append((p.ref, key))
                texts.append(text)
    if texts:
        for (ref, key), vec in zip(wanted, embedder.embed(texts, "RETRIEVAL_DOCUMENT")):
            cache[key] = vec
            vectors[ref] = vec
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache))
    return vectors


def scores(query: str) -> dict[str, float]:
    """Passage ref -> semantic bonus in BM25 units (0 when unrelated)."""
    embedder = get_embedder()
    vectors = _passage_vectors(embedder)
    q = embedder.embed([query], "RETRIEVAL_QUERY")[0]
    out = {}
    for ref, vec in vectors.items():
        cos = _cosine(q, vec)
        if cos > SEM_FLOOR:
            out[ref] = SEM_WEIGHT * (cos - SEM_FLOOR) / (1 - SEM_FLOOR)
    return out
