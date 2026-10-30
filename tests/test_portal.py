from fastapi.testclient import TestClient

import web.app as webapp
from unblock import activity

client = TestClient(webapp.app)


def chat(session, text="", selection=None):
    r = client.post("/api/portal/chat", json={"session": session, "text": text, "selection": selection})
    assert r.status_code == 200, r.text
    return r.json()


def test_portal_page_and_session():
    assert "New Hire Portal" in client.get("/app").text
    assert client.get("/api/portal/session").json()["session"].startswith("web-")


def test_answer_then_route_draft_guardian_and_send():
    s = client.get("/api/portal/session").json()["session"]
    r = chat(s, "How do I set up my dev environment?")
    assert r["kind"] == "detail" and "Local Development" in r["text"]
    r = chat(s, "How many vacation days do I get?")
    r = chat(s, "", {"action": "ub_ask_helper"}) if r["kind"] != "review" else r
    assert r["kind"] == "review" and r["draft"]["to_name"]
    r = chat(s, "edit: my password is hunter22")
    assert r["draft"]["guardian"]
    r = chat(s, "", {"action": "ub_approve"})
    assert "Nothing was sent" in r["text"]
    chat(s, "edit: Hi, how many vacation days do new US hires get? Thanks, Maya")
    r = chat(s, "", {"action": "ub_approve"})
    assert r["text"].startswith("**Simulated")
    state = client.get(f"/api/portal/state?session={s}").json()
    assert state["followups"] and state["followups"][0]["status"] == "waiting"
    assert state["checklist"][0].startswith("Finish laptop")
    texts = " ".join(e["text"] for e in activity.since())
    assert "hunter22" not in texts and "Guardian blocked" in texts


def test_access_request_manager_decides_and_new_hire_hears():
    s = client.get("/api/portal/session").json()["session"]
    r = chat(s, "I need access to the analytics dashboard")
    assert r["kind"] == "review"
    r = chat(s, "approve")
    assert "AR-" in r["text"]
    pending = [p for p in client.get("/api/portal/manager").json() if p["status"] == "pending"]
    rid = pending[0]["request_id"]
    assert client.post("/api/portal/decide", json={"request_id": rid, "decision": "approved"}).json()["ok"]
    assert not client.post("/api/portal/decide", json={"request_id": rid, "decision": "approved"}).json()["ok"]
    state = client.get(f"/api/portal/state?session={s}").json()
    assert any("approved" in m["text"] for m in state["inbox"])
    assert state["requests"][0]["status"] == "approved"


def test_reminder_when_no_reply(monkeypatch):
    monkeypatch.setenv("TRACKER_DUE_MINUTES", "0")
    s = client.get("/api/portal/session").json()["session"]
    chat(s, "How many vacation days do I get?")
    chat(s, "", {"action": "ub_ask_helper"})
    chat(s, "approve")
    state = client.get(f"/api/portal/state?session={s}").json()
    nudge = [m for m in state["inbox"] if m.get("kind") == "reminder"]
    assert nudge
    draft = client.post("/api/portal/remind", json={"session": s, "item_id": nudge[0]["item_id"]}).json()
    assert draft["draft"]["body"] and not draft["draft"]["guardian"]
    sent = client.post("/api/portal/remind", json={"session": s, "item_id": nudge[0]["item_id"], "send": True}).json()
    assert sent["text"].startswith("**Simulated")


def test_manager_key(monkeypatch):
    monkeypatch.setenv("PORTAL_MANAGER_KEY", "k")
    assert client.get("/api/portal/manager").status_code == 403
    assert client.get("/api/portal/manager", headers={"X-Manager-Key": "k"}).status_code == 200
