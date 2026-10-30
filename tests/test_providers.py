"""Gemini, Snowflake Cortex and hybrid retrieval, against a fake HTTP server."""
import json

import httpx

from unblock import semantic
from unblock.data import load_user
from unblock.knowledge import answer
from unblock.providers import GeminiEmbedder, GeminiLLM, SnowflakeLLM
from unblock.retrieval import search

GOOD = {"can_answer": True, "title": "Expenses",
        "claims": [{"text": "The meal limit is 75 USD per person", "quote": "The meal limit is 75 USD per person including tax and tip.", "source_id": "D04"},
                   {"text": "Meals over 200 USD are fine", "quote": "Meals over 200 USD are fine with no receipt", "source_id": "D04"}],
        "steps": [], "conflicts": [], "missing": ""}


def test_gemini_answer_is_verified(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}]})

    llm = GeminiLLM(client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = answer("What's the meal limit for a client lunch?", load_user(), llm)
    assert ":generateContent" in seen["url"] and seen["key"] == "test"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert len(r.claims) == 1 and len(r.blocked) == 1 and r.llm_mode == "gemini"


def test_snowflake_cortex_answer_is_verified(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "myorg-myacct")
    monkeypatch.setenv("SNOWFLAKE_PAT", "pat")
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": json.dumps(GOOD)}}]})

    llm = SnowflakeLLM(client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = answer("What's the meal limit for a client lunch?", load_user(), llm)
    assert seen["url"] == "https://myorg-myacct.snowflakecomputing.com/api/v2/cortex/v1/chat/completions"
    assert seen["auth"] == "Bearer pat" and seen["body"]["stream"] is False
    assert len(r.claims) == 1 and len(r.blocked) == 1


def test_provider_errors_route_to_a_person(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    llm = GeminiLLM(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503, text="busy"))))
    r = answer("What's the meal limit for a client lunch?", load_user(), llm)
    assert r.decision == "route" and "Gemini request failed" in r.error


def _fake_embedder():
    # Each dimension is a meaning; several words share one, like real embeddings.
    meanings = [("meal", "lunch", "dinner", "food"), ("vpn", "remote"), ("deploy", "staging")]

    def handler(request: httpx.Request):
        body = json.loads(request.content)
        vecs = []
        for req in body["requests"]:
            text = req["content"]["parts"][0]["text"].lower()
            vecs.append({"values": [1.0 if any(w in text for w in m) else 0.0 for m in meanings] + [0.1]})
        return httpx.Response(200, json={"embeddings": vecs})

    return GeminiEmbedder(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_hybrid_search_uses_gemini_embeddings(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("UNBLOCK_EMBEDDINGS", "gemini")
    monkeypatch.setattr(semantic, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(semantic, "_embedder", _fake_embedder())
    r = search("lunch with a customer", office="US")
    assert "Gemini embeddings" in r.method
    assert r.docs and r.docs[0].doc.id in ("D04", "D05")  # both expense docs; keywords alone rank PII first


def test_hybrid_search_falls_back_to_keywords(monkeypatch):
    monkeypatch.setenv("UNBLOCK_EMBEDDINGS", "gemini")
    broken = GeminiEmbedder.__new__(GeminiEmbedder)
    broken.model = "x"
    broken.embed = lambda texts, task: (_ for _ in ()).throw(RuntimeError("down"))
    monkeypatch.setattr(semantic, "_embedder", broken)
    r = search("How do I deploy to staging?", office="US")
    assert "unavailable" in r.method and r.docs[0].doc.id == "D13"
