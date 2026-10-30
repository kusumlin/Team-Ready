"""Conversation-level tests for the orchestrator logic, with fake agent services."""
import asyncio

from unblock import knowledge, routing
from unblock.data import load_user
from unblock.flow import Orchestrator
from unblock.friction import build_map
from unblock.llm import ExtractiveLLM


class MemStore(dict):
    def get(self, k, default=None):
        return super().get(k, default)

    def set(self, k, v):
        self[k] = v


class FakeServices:
    def __init__(self):
        self.sent, self.approvals, self.feedback, self.events = [], [], [], []
        self.tracked, self.resolved = [], []

    async def knowledge(self, q, user):
        return knowledge.answer(q, user, ExtractiveLLM()).to_dict()

    async def routing(self, q, user, ids, exclude):
        return routing.rank(q, user, ids or None, set(exclude)).to_dict()

    async def wrong_person(self, pid, topic):
        self.feedback.append((pid, topic))
        routing.record_wrong_person(pid, topic)

    async def request_approval(self, req):
        self.approvals.append(req)
        return "Delivered."

    async def friction_event(self, doc, read, resolved):
        self.events.append((doc, resolved))

    async def friction_map(self):
        return build_map()

    async def send_email(self, to, subject, body, sender, ics):
        self.sent.append({"to": to, "subject": subject, "body": body, "ics": ics})
        return {"status": "simulated", "to": to, "detail": "saved"}

    async def source_feedback(self, ids):
        pass

    async def track(self, item_id, user, kind, summary, to_name, to_email):
        self.tracked.append({"id": item_id, "kind": kind, "to": to_name})

    async def track_resolved(self, item_id, outcome):
        self.resolved.append((item_id, outcome))


def run(coro):
    return asyncio.run(coro)


def make():
    services = FakeServices()
    return Orchestrator(services, MemStore(), ExtractiveLLM), services


def test_verified_answer_sends_nothing():
    flow, s = make()
    reply = run(flow.handle("u", "How do I set up my dev environment?"))
    assert "[D12]" in reply.text and reply.kind == "detail"
    assert not s.sent


def test_nothing_is_sent_until_approved():
    flow, s = make()
    reply = run(flow.handle("u", "Is there free lunch on Fridays?"))
    assert reply.kind == "review" and "Nothing is sent until you approve" in reply.text
    assert not s.sent
    run(flow.handle("u", "edit: Hi! Quick question about Paris wifi."))
    done = run(flow.handle("u", "approve"))
    assert len(s.sent) == 1 and s.sent[0]["body"].startswith("Hi! Quick question")
    assert "Simulated" in done.text


def test_reject_discards_draft():
    flow, s = make()
    run(flow.handle("u", "Is there free lunch on Fridays?"))
    reply = run(flow.handle("u", "reject"))
    assert "Nothing was sent" in reply.text
    assert run(flow.handle("u", "approve")).text.startswith("There's nothing waiting")
    assert not s.sent


def test_wrong_person_reroutes_and_records_feedback():
    flow, s = make()
    first = run(flow.handle("u", "Is there free lunch on Fridays?"))
    second = run(flow.handle("u", "wrong person"))
    assert s.feedback and "updated the ranking" in second.text
    assert first.text.split("Best person to ask: **")[1].split("**")[0] != second.text.split("Best person to ask: **")[1].split("**")[0]


def test_access_request_goes_to_manager_only_after_approval():
    flow, s = make()
    reply = run(flow.handle("u", "Give me prod DB access"))
    assert "Jordan Lee" in reply.text and not s.approvals
    done = run(flow.handle("u", "approve"))
    assert len(s.approvals) == 1 and "Only your manager can approve" in done.text
    assert not s.sent  # access requests never go out as plain email
    req_id = s.approvals[0]["request_id"]
    out = run(flow.on_decision({"request_id": req_id, "decision": "approved", "approver": "Jordan Lee"}))
    assert out and out[0] == "u" and "approved" in out[1].text


def test_high_impact_question_stops_before_search():
    flow, s = make()
    reply = run(flow.handle("u", "Can the AI decide whether I deserve a promotion?"))
    assert "needs a person" in reply.text and reply.terminal
    assert not s.sent and not s.approvals and not s.events


def test_stale_doc_offers_note_to_owner():
    flow, s = make()
    reply = run(flow.handle("u", "How do I deploy to staging?"))
    assert "Deploy Runbook (Legacy)" in reply.text and "Wei Zhang" in reply.text
    run(flow.handle("u", "approve"))
    assert s.sent and "wei.zhang" in s.sent[0]["to"]


def test_card_selection_json_works():
    flow, s = make()
    run(flow.handle("u", "Is there free lunch on Fridays?"))
    run(flow.handle("u", "", {"action": "ub_approve"}))
    assert len(s.sent) == 1


def test_sentences_mentioning_approve_never_send():
    flow, s = make()
    run(flow.handle("u", "Is there free lunch on Fridays?"))
    for text in ["don't approve this yet", "I will approve it later", "please do not send", "maybe approve tomorrow"]:
        run(flow.handle("u", text))
    assert not s.sent


def test_planner_routed_click_uses_distinct_id():
    flow, s = make()
    run(flow.handle("u", "Is there free lunch on Fridays?"))
    run(flow.handle("u", "The user clicked the button with action ub_approve"))
    assert len(s.sent) == 1


def test_short_questions_are_not_commands():
    flow, s = make()
    for q in ["Where is the status page?", "Is the VPN doc outdated?", "Can someone else review my PR?"]:
        reply = run(flow.handle("u", q))
        assert not reply.text.startswith("There's nothing waiting"), q
    assert not s.feedback


def test_pending_approval_survives_new_questions():
    flow, s = make()
    run(flow.handle("u", "Give me prod DB access"))
    run(flow.handle("u", "approve"))
    run(flow.handle("u", "How do I reset my password?"))
    assert "waiting for Jordan Lee" in run(flow.handle("u", "status")).text


def test_questions_containing_command_words_are_still_questions():
    flow, s = make()
    reply = run(flow.handle("u", "How do I approve an expense report in Expense Hub?"))
    assert "Expense" in reply.text and not s.sent
    assert load_user()["name"] == "Maya Chen"


# ---------- Guardian ----------
from unblock.risk import check_draft  # noqa: E402


def test_guardian_flags_sensitive_drafts():
    assert check_draft("Hi", "Can we talk about my salary band?")
    assert check_draft("Hi", "My password is hunter2")
    assert check_draft("Hi", "My SSN is 123-45-6789")
    assert check_draft("Hi", "Card 4111 1111 1111 1111 for the license")
    assert check_draft("Hi", "I have a medical condition and need time")
    assert check_draft("Hi", "token sk-abcdefghijklmnopqrstuvwx")
    assert not check_draft("Quick question", "How do I deploy my branch to staging? Thanks!")
    assert not check_draft("Ticket 1234-5678", "Order 1234 5678 9012 3456 is not a card")  # fails the Luhn check


def test_guardian_blocks_send_until_draft_is_clean():
    flow, s = make()
    run(flow.handle("u", "Is there free lunch on Fridays?"))
    reply = run(flow.handle("u", "edit: Also, my password is hunter2 if you need to check my account."))
    assert "Guardian stopped this draft" in reply.text
    blocked = run(flow.handle("u", "approve"))
    assert "Nothing was sent" in blocked.text and not s.sent
    clean = run(flow.handle("u", "edit: Hi Elena, is there free lunch on Fridays?"))
    assert "clear to send" in clean.text
    run(flow.handle("u", "approve"))
    assert len(s.sent) == 1


def test_sent_items_are_tracked_and_decisions_resolve_them():
    flow, s = make()
    run(flow.handle("u", "Is there free lunch on Fridays?"))
    run(flow.handle("u", "approve"))
    assert s.tracked and s.tracked[0]["kind"] == "message_helper"
    run(flow.handle("u", "Give me prod DB access"))
    run(flow.handle("u", "approve"))
    req_id = s.approvals[0]["request_id"]
    assert any(t["id"] == req_id for t in s.tracked)
    run(flow.on_decision({"request_id": req_id, "decision": "approved", "approver": "Jordan Lee"}))
    assert (req_id, "approved") in s.resolved
