from unblock import activity


def test_log_and_since(tmp_path, monkeypatch):
    monkeypatch.setattr(activity, "PATH", tmp_path / "a.jsonl")
    activity.log("orchestrator", "Check the docs", to="knowledge", kind="message")
    activity.log("knowledge", "Verified 3 of 3 claims")
    events = activity.since()
    assert [e["from"] for e in events] == ["orchestrator", "knowledge"]
    assert events[0]["id"] < events[1]["id"]
    assert activity.since(events[0]["id"]) == events[1:]


def test_said_hides_secrets_but_keeps_questions():
    assert "hidden" in activity.said("edit: my password is hunter22")
    assert "hidden" in activity.said("my SSN is 123-45-6789")
    assert activity.said("Can the AI decide whether I deserve a promotion?").startswith("“")
    assert activity.said('{"action": "ub_approve"}') == "(clicked a card button)"
    assert len(activity.said("x" * 500)) < 110


def test_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(activity, "PATH", tmp_path / "a.jsonl")
    monkeypatch.setenv("UNBLOCK_ACTIVITY", "false")
    activity.log("orchestrator", "hi")
    assert activity.since() == []
