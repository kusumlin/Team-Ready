from fastapi.testclient import TestClient

import web.app as webapp
from unblock import autopilot

client = TestClient(webapp.app)


def session():
    return client.get("/api/portal/session").json()["session"]


def chat(s, text="", selection=None):
    r = client.post("/api/portal/chat", json={"session": s, "text": text, "selection": selection})
    assert r.status_code == 200, r.text
    return r.json()


def test_detects_what_the_new_hire_wants_done():
    assert autopilot.detect("Can you join the Slack channels for me?") == "slack_channels"
    assert autopilot.detect("sign me up for security awareness training") == "security_training"
    assert autopilot.detect("schedule my 1:1 with my manager") == "manager_1_1"
    assert autopilot.detect("my laptop screen is cracked") == "it_ticket"
    assert autopilot.detect("Which Slack channels should I join?") == ""  # a question, not a request
    assert autopilot.detect("My VPN won't connect, what should I do?") == ""
    assert autopilot.detect("How do I schedule my first 1:1 with my manager?") == ""
    assert autopilot.detect("I lost my MFA device, my laptop is broken") == ""  # never acts on MFA
    assert autopilot.detect("Can you schedule my 1:1 with my manager?") == "manager_1_1"


def test_answer_offers_to_do_it_and_nothing_happens_before_approve():
    s = session()
    r = chat(s, "Which Slack channels should I join?")
    assert "Want me to do it?" in r["text"]
    assert r["payload"]["ctas"][0]["selection"] == {"action": "ub_do_it"}
    r = chat(s, "", {"action": "ub_do_it"})
    assert r["kind"] == "review" and "#data-help" in r["text"]  # Maya is an analyst
    assert autopilot.records(s) == []
    r = chat(s, "approve")
    assert r["text"].startswith("**Done: SL-")
    assert [x["action"] for x in autopilot.records(s)] == ["slack_channels"]
    assert "Already done" in chat(s, "join the slack channels for me")["text"]


def test_reject_and_edit_do_nothing():
    s = session()
    chat(s, "sign me up for security awareness training")
    assert "nothing to edit" in chat(s, "edit: something else")["text"]
    assert "Nothing was sent" in chat(s, "reject")["text"]
    assert autopilot.records(s) == []


def test_it_ticket_text_goes_through_the_guardian():
    s = session()
    r = chat(s, "my laptop is broken, my SSN is 123-45-6789 if IT needs it")
    guard = next(row["value"] for row in r["payload"]["summary_rows"] if row["label"] == "Guardian check")
    assert guard.startswith("Blocked")
    r = chat(s, "approve")
    assert "Nothing was sent" in r["text"] and autopilot.records(s) == []


def test_checklist_autopilot_does_what_it_can_and_the_manager_gates_access():
    s = session()
    r = chat(s, "do my checklist")
    assert r["kind"] == "review"
    plan = {row["label"] for row in r["payload"]["summary_rows"]}
    assert {"I'll do it", "Needs your manager", "You or a person"} <= plan
    assert "never touches passwords or MFA" in r["text"]
    r = chat(s, "approve")
    done = {x["action"] for x in autopilot.records(s)}
    assert done == {"slack_channels", "security_training", "manager_1_1"}
    assert r["kind"] == "review" and r["draft"]["type"] == "access_request"  # the manager message is reviewed first
    r = chat(s, "approve")
    assert "AR-" in r["text"]
    again = chat(s, "do my checklist")  # while the request is with the manager, it isn't asked for again
    assert "With your manager" in again["text"]
    chat(s, "approve")
    assert sum(1 for p in client.get("/api/portal/manager").json() if p["status"] == "pending") == 1
    rid = next(p for p in client.get("/api/portal/manager").json() if p["status"] == "pending")["request_id"]
    assert client.post("/api/portal/decide", json={"request_id": rid, "decision": "approved"}).json()["ok"]
    assert "analytics_access" in {x["action"] for x in autopilot.records(s)}
    inbox = client.get(f"/api/portal/state?session={s}").json()["inbox"]
    assert any("I filed it for you: ACC-" in m["text"] for m in inbox)
    assert "Nothing left" in chat(s, "do my checklist")["text"]


def test_access_request_filed_only_after_manager_approves():
    s = session()
    chat(s, "I need access to the analytics dashboard")
    chat(s, "approve")
    assert autopilot.records(s) == []
    rid = next(p for p in client.get("/api/portal/manager").json() if p["status"] == "pending")["request_id"]
    client.post("/api/portal/decide", json={"request_id": rid, "decision": "rejected"})
    assert autopilot.records(s) == []


def test_workday_home_and_what_awaits_the_new_hire():
    assert "TeamReady for Workday" in client.get("/workday").text
    s = session()
    assert client.get(f"/api/portal/state?session={s}").json()["awaiting_you"] is None
    chat(s, "do my checklist")
    waiting = client.get(f"/api/portal/state?session={s}").json()["awaiting_you"]
    assert waiting["type"] == "system_batch" and not waiting["blocked"]
