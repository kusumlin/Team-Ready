import json

import httpx
from fastapi.testclient import TestClient

import web.app as webapp
from unblock import autopilot, portal, workday_mcp

client = TestClient(webapp.app)

TOOLS = [
    {"name": "Find_Absence_Balances", "title": "Find Absence Balances", "description": "Returns the worker's time off balances.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "Create_Worker_Time_Off_Request", "title": "Create Worker Time Off Request",
     "description": "Submits a time off request for the worker.",
     "inputSchema": {"type": "object", "properties": {"startDate": {"type": "string"}, "endDate": {"type": "string"}, "timeOffType": {"type": "string"}}}},
    {"name": "List_Onboarding_Business_Process_Tasks", "title": "List Onboarding Business Process Tasks",
     "description": "Lists onboarding tasks.", "inputSchema": {"type": "object", "properties": {}}},
]


class FakeLLM:
    """Stands in for the model: picks the tool the way the prompt asks and summarizes the result."""
    mode = "anthropic"

    def _json(self, system, prompt, max_tokens=500):
        if "Pick the ONE tool" in system:
            if "Request time off" in prompt:
                return {"tool": "Create_Worker_Time_Off_Request", "arguments": {"startDate": "2026-11-03", "endDate": "2026-11-04", "timeOffType": "Vacation"},
                        "explain": "Requests vacation for Nov 3 and Nov 4 in Workday."}
            return {"tool": "Find_Absence_Balances", "arguments": {}, "explain": "Looks up time off balances."}
        return {"answer": "You have 10 days of vacation left."}


def setup(monkeypatch, fail=False):
    calls = []

    def handler(r: httpx.Request):
        body = json.loads(r.content)
        calls.append(body)
        assert r.headers["authorization"] == "Bearer asu-test"
        if fail:
            return httpx.Response(503)
        if body["method"] == "tools/list":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": TOOLS}})
        name = body["params"]["name"]
        text = "Vacation: 80 hours (10 days)" if name == "Find_Absence_Balances" else "Time off request submitted, routed to Jordan Lee"
        # Streamable HTTP may answer as server-sent events
        sse = f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': {'content': [{'type': 'text', 'text': text}]}})}\n\n"
        return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

    real = httpx.Client
    monkeypatch.setattr(workday_mcp.httpx, "Client", lambda *a, **k: real(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("WORKDAY_MCP_URL", "https://us.agent.workday.com/lumen/mcp")
    monkeypatch.setenv("WORKDAY_MCP_TOKEN", "asu-test")
    monkeypatch.setattr(portal, "get_llm", lambda *a, **k: FakeLLM())
    workday_mcp._state.update(tools=None, session="", token="")
    return calls


def chat(s, text="", selection=None):
    r = client.post("/api/portal/chat", json={"session": s, "text": text, "selection": selection})
    assert r.status_code == 200, r.text
    return r.json()


def test_reads_balances_from_workday_without_changing_anything(monkeypatch):
    calls = setup(monkeypatch)
    s = client.get("/api/portal/session").json()["session"]
    r = chat(s, "How many vacation days do I have left?")
    assert r["text"].startswith("**From Workday:** You have 10 days") and "Nothing was changed" in r["text"]
    assert [c["params"]["name"] for c in calls if c["method"] == "tools/call"] == ["Find_Absence_Balances"]


def test_time_off_request_waits_for_approval_then_runs_in_workday(monkeypatch):
    calls = setup(monkeypatch)
    s = client.get("/api/portal/session").json()["session"]
    r = chat(s, "Please request time off for Nov 3 to Nov 4")
    assert r["kind"] == "review" and "Create Worker Time Off Request" in r["payload"]["title"]
    assert not [c for c in calls if c["method"] == "tools/call"]  # nothing changes before approval
    assert client.get(f"/api/portal/state?session={s}").json()["awaiting_you"]["type"] == "workday_action"
    r = chat(s, "approve")
    assert r["text"].startswith("**Done in Workday: WD-")
    sent = [c for c in calls if c["method"] == "tools/call"][0]["params"]
    assert sent == {"name": "Create_Worker_Time_Off_Request", "arguments": {"startDate": "2026-11-03", "endDate": "2026-11-04", "timeOffType": "Vacation"}}
    assert autopilot.records(s)[0]["system"] == "Workday"


def test_falls_back_to_the_docs_when_workday_is_down(monkeypatch):
    setup(monkeypatch, fail=True)
    s = client.get("/api/portal/session").json()["session"]
    r = chat(s, "How many vacation days do I have left?")
    assert not r["text"].startswith("**From Workday")


def test_only_lookups_run_without_approval():
    assert workday_mcp.is_read({"name": "Find_Absence_Balances"})
    assert workday_mcp.is_read({"name": "listOnboardingTasks"})
    assert not workday_mcp.is_read({"name": "Create_Worker_Time_Off_Request"})
    assert not workday_mcp.is_read({"name": "Update_Journey_Steps"})
    assert workday_mcp.is_read({"name": "anything", "annotations": {"readOnlyHint": True}})
