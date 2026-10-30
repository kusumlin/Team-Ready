import asyncio

from unblock import canary, creao
from unblock import knowledge
from unblock.llm import get_llm_or_unavailable


async def ask(q, user):
    return (await asyncio.to_thread(knowledge.answer, q, user, get_llm_or_unavailable())).to_dict()


def run():
    loop = asyncio.new_event_loop()  # not asyncio.run: it clears the loop other tests rely on
    try:
        return loop.run_until_complete(canary.run(ask, "test"))
    finally:
        loop.close()


def test_canaries_find_the_walls_real_hires_hit_and_predict_new_ones():
    r = run()
    assert r["status"] == "done" and len(r["canaries"]) == 3
    by = {(w["status"], w.get("doc_id")): w for w in r["walls"]}
    detour = by[("detour", "D02")]          # the checklist never says how to request analytics access
    assert detour["source_doc"] == "D01" and detour["humans_hit"] > 0 and not detour["predicted"]
    trap = by[("trap", "D14")]              # the legacy deploy runbook still comes up
    assert trap["humans_hit"] > 0
    predicted = [w for w in r["walls"] if w["predicted"]]
    assert any(w["status"] == "dead_end" and w["offices"] == ["EU"] for w in predicted)  # no badge doc for EU hires
    assert r["walls"][0]["humans_hit"] >= r["walls"][-1]["humans_hit"]
    s = r["summary"]
    assert s["walls"] == len(r["walls"]) and s["predicted"] + s["confirmed"] == s["walls"]
    assert canary.latest()["run_id"] == r["run_id"]


def test_gated_and_high_impact_steps_are_not_walls():
    r = run()
    steps = {s["task"]: s for c in r["canaries"] for s in c["steps"]}
    assert steps["Get production access"]["status"] == "approval"
    assert all(w["task"] != "Get production access" for w in r["walls"])


def test_fixes_quote_the_doc_exactly_and_need_a_person():
    r = run()
    docs = canary.load_docs()
    edit = next(f for f in r["fixes"] if f["kind"] == "edit")
    assert edit["status"] == "ready" and edit["before"] in docs[edit["doc_id"]].body
    assert "go/analytics-access" in edit["after"]
    archive = next(f for f in r["fixes"] if f["kind"] == "archive")
    assert archive["to"]["name"] == "Wei Zhang" and "Deploying to Staging" in archive["after"]
    assert all(f["status"] == "ready" for f in r["fixes"])  # nothing is sent until someone approves
    out = canary.approve(r["run_id"], edit["id"])
    assert out["ok"] and out["status"] == "simulated"
    assert not canary.approve(r["run_id"], edit["id"])["ok"]  # only once
    assert canary.get(r["run_id"])["fixes"][[f["id"] for f in r["fixes"]].index(edit["id"])]["status"] == "sent"


def test_creao_drafts_the_edit_and_its_reply_is_checked(monkeypatch):
    monkeypatch.setenv("CREAO_APP_ID", "app-1")
    monkeypatch.setenv("CREAO_API_KEY", "capi_test")
    monkeypatch.setenv("CREAO_CHECK_SECONDS", "0")
    monkeypatch.setattr(creao, "start_run", lambda inputs, client=None: "run-9")
    r = run()
    edit = next(f for f in r["fixes"] if f["kind"] == "edit")
    assert edit["status"] == "drafting" and edit["creao_run"] == "run-9"
    reply = {"status": "completed", "result": {"text": '{"before_quote": "Request analytics tools after core account setup is complete.", '
                                                       '"after_text": "Request analytics tools at go/analytics-access.", "rationale": "13 blockers"}'}}
    monkeypatch.setattr(creao, "get_run", lambda run_id, client=None: reply)
    edit = next(f for f in canary.latest()["fixes"] if f["kind"] == "edit")
    assert edit["status"] == "ready" and edit["drafter"] == "CREAO Doc Steward" and edit["after"].endswith("go/analytics-access.")


def test_a_made_up_creao_quote_is_blocked_and_redrafted(monkeypatch):
    monkeypatch.setenv("CREAO_APP_ID", "app-1")
    monkeypatch.setenv("CREAO_API_KEY", "capi_test")
    monkeypatch.setenv("CREAO_CHECK_SECONDS", "0")
    monkeypatch.setattr(creao, "start_run", lambda inputs, client=None: "run-9")
    monkeypatch.setattr(creao, "get_run", lambda run_id, client=None: {"status": "completed", "result": {
        "text": '{"before_quote": "This sentence is not in the doc at all.", "after_text": "x", "rationale": "r"}'}})
    run()
    edit = next(f for f in canary.latest()["fixes"] if f["kind"] == "edit")
    assert edit["status"] == "ready" and "CREAO run unusable" in edit["drafter"]


def test_report_text_and_map_feed_have_no_people_from_messages():
    r = run()
    text = canary.report_text(r)
    assert "PREDICTED" in text and "confirmed by" in text
    feed = canary.predicted_for_map(r)
    assert feed and set(feed[0]) == {"wall", "task", "doc", "canaries", "humans_hit", "predicted"}


def test_a_run_whose_process_stopped_shows_as_interrupted(monkeypatch):
    rec = canary.new_run("scheduled")
    canary.save(rec)
    assert canary.latest()["status"] == "running"
    monkeypatch.setattr(canary, "STALE_SECONDS", -1)
    assert canary.latest()["status"] == "interrupted"
