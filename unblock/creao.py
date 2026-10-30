"""CREAO: the Doc Steward agent that drafts doc fixes from the Friction Map.

The Doc Steward is a saved agent on agent.creao.ai (instructions in
docs/CREAO.md). The insights agent starts a run through CREAO's API Trigger
and polls it. Runs take minutes, so nothing waits on an open request: the
pending run is stored and checked on an interval, and the new hire's or People
Ops' chat gets the result when it's ready. Whatever CREAO returns still goes
through the same exact-quote check before a human sees it.

CREAO_APP_ID    the Doc Steward's agent ID (shown on its page)
CREAO_API_KEY   the agent's capi_ key. Server-side only: never in the browser or the repo.
CREAO_CHECK_SECONDS / CREAO_TIMEOUT_MINUTES  polling interval (20 s) and give-up time (12 min)
"""
import json

import httpx

from .config import env
from .llm import LLMError, _parse_json

BASE = "https://agent.creao.ai/api/v1/apps"
DONE = ("completed", "failed", "cancelled")


def enabled() -> bool:
    return bool(env("CREAO_APP_ID") and env("CREAO_API_KEY"))


def _headers() -> dict:
    return {"Authorization": f"Bearer {env('CREAO_API_KEY')}", "Content-Type": "application/json"}


def fix_inputs(cluster: dict, doc_title: str, doc_body: str, source_title: str, source_body: str) -> dict:
    """Inputs for the Doc Steward. Aggregates only: topic, count, pattern and doc text, never names or messages."""
    summary = {k: cluster.get(k) for k in ("topic", "count", "pattern", "resolved_share", "start_doc")}
    return {"cluster": json.dumps(summary), "doc_title": doc_title, "doc_body": doc_body,
            "source_title": source_title, "source_body": source_body}


def start_run(inputs: dict, client: httpx.Client | None = None) -> str:
    client = client or httpx.Client()
    body = {"inputs": inputs}
    if env("CREAO_WEBHOOK_URL"):
        body["webhookUrl"] = env("CREAO_WEBHOOK_URL")
    r = client.post(f"{BASE}/{env('CREAO_APP_ID')}/runs", headers=_headers(), json=body, timeout=30)
    r.raise_for_status()
    run_id = r.json().get("id")
    if not run_id:
        raise LLMError("CREAO accepted the run but returned no id")
    return run_id


def get_run(run_id: str, client: httpx.Client | None = None) -> dict:
    client = client or httpx.Client()
    r = client.get(f"{BASE}/{env('CREAO_APP_ID')}/runs/{run_id}", headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def run_url(run_id: str) -> str:
    return f"https://agent.creao.ai/apps/{env('CREAO_APP_ID')}/runs/{run_id}"


def result_fix(run: dict) -> dict:
    """The Doc Steward's JSON reply from a finished run. Raises LLMError if it failed or isn't JSON."""
    status = run.get("status")
    if status != "completed":
        code = run.get("errorCode") or (run.get("error") or {}).get("code") or status
        raise LLMError(f"the CREAO run ended as {code}")
    result = run.get("result") or {}
    text = result.get("text") or result.get("chatText") or ""
    if not isinstance(text, str) or not text.strip():
        raise LLMError("the CREAO run finished with no text")
    return _parse_json(text)


def status() -> str:
    return f"CREAO Doc Steward ({env('CREAO_APP_ID')[:8]}…)" if enabled() else "off"
