import json
import sys
from pathlib import Path

import httpx
import pytest

from unblock import creao
from unblock.llm import LLMError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "agents"))


def setup(monkeypatch):
    monkeypatch.setenv("CREAO_APP_ID", "app-123")
    monkeypatch.setenv("CREAO_API_KEY", "capi_test")


def test_start_and_poll(monkeypatch):
    setup(monkeypatch)
    calls = []

    def handler(r: httpx.Request):
        calls.append(r)
        assert r.headers["authorization"] == "Bearer capi_test"
        if r.method == "POST":
            assert r.url.path == "/api/v1/apps/app-123/runs"
            body = json.loads(r.content)
            assert set(body["inputs"]) == {"cluster", "doc_title", "doc_body", "source_title", "source_body"}
            return httpx.Response(200, json={"id": "run-1", "status": "pending"})
        assert r.url.path == "/api/v1/apps/app-123/runs/run-1"
        return httpx.Response(200, json={"id": "run-1", "status": "completed", "result": {
            "text": 'Here you go:\n```json\n{"before_quote": "a b c d", "after_text": "x", "rationale": "r"}\n```'}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    inputs = creao.fix_inputs({"topic": "access", "count": 9, "pattern": "p", "name": "never sent"}, "T", "body", "S", "src")
    assert "never sent" not in inputs["cluster"]
    run_id = creao.start_run(inputs, client)
    assert run_id == "run-1"
    assert creao.result_fix(creao.get_run(run_id, client))["after_text"] == "x"


def test_failed_or_empty_runs_raise():
    with pytest.raises(LLMError):
        creao.result_fix({"status": "failed", "errorCode": "timeout"})
    with pytest.raises(LLMError):
        creao.result_fix({"status": "completed", "result": {"text": ""}})
    with pytest.raises(LLMError):
        creao.result_fix({"status": "completed", "result": {"text": "no json here"}})


def test_creao_fix_still_needs_exact_quote(monkeypatch):
    monkeypatch.setenv("UNBLOCK_LLM", "extractive")
    import insights_agent

    cluster, doc, _ = insights_agent._target()
    bad = insights_agent._check_fix({"before_quote": "words that are not in the doc", "after_text": "x"}, cluster, doc)
    assert "error" in bad
    line = next(x for x in doc.body.splitlines() if len(x.split()) >= 6)
    good = insights_agent._check_fix({"before_quote": line, "after_text": "better"}, cluster, doc)
    assert good["after"] == "better" and good["doc_id"] == doc.id
    assert "error" in insights_agent._check_fix("not a dict", cluster, doc)
