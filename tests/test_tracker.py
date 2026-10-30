from unblock import tracker


def test_overdue_items_are_offered_once():
    items = {}
    tracker.add(items, "MS-1", "user1", "message_helper", "Is there free lunch?", "Elena Garcia", "elena@x", now=1000)
    tracker.add(items, "AR-1", "user1", "access_request", "Analytics access", "Jordan Lee", "jordan@x", now=1000)
    assert tracker.overdue(items, now=1000 + 59, due=60) == []
    due = tracker.overdue(items, now=1000 + 61, due=60)
    assert {i["id"] for i in due} == {"MS-1", "AR-1"}
    for i in due:
        i["nudged"] = True
    assert tracker.overdue(items, now=5000, due=60) == []


def test_resolved_items_are_not_followed_up():
    items = {}
    tracker.add(items, "AR-1", "u", "access_request", "Analytics access", "Jordan Lee", "j@x", now=0)
    assert tracker.resolve(items, "AR-1", "approved")
    assert not tracker.resolve(items, "AR-1", "approved")
    assert tracker.overdue(items, now=10**6, due=1) == []


def test_reminder_is_polite_and_guardian_checked():
    item = {"id": "MS-1", "kind": "message_helper", "summary": "Is there free lunch on Fridays?", "to_name": "Elena Garcia"}
    d = tracker.reminder_draft(item, "Maya Chen")
    assert d["body"].startswith("Hi Elena") and "Maya" in d["body"] and d["guardian"] == []
    risky = dict(item, summary="Can we talk about my salary?")
    assert tracker.reminder_draft(risky, "Maya Chen")["guardian"]


def test_due_time_settings(monkeypatch):
    monkeypatch.setenv("TRACKER_DUE_HOURS", "2")
    monkeypatch.delenv("TRACKER_DUE_MINUTES", raising=False)
    assert tracker.due_seconds() == 7200
    monkeypatch.setenv("TRACKER_DUE_MINUTES", "3")
    assert tracker.due_seconds() == 180


def test_plan_lists_only_my_items():
    items = {}
    tracker.add(items, "MS-1", "me", "message_helper", "Lunch?", "Elena Garcia", "e@x", now=0)
    tracker.add(items, "MS-2", "someone else", "message_helper", "VPN", "Diego Martinez", "d@x", now=0)
    text = tracker.plan_text(items, "me", now=7200)
    assert "MS-1" in text and "MS-2" not in text and "2 hours" in text
