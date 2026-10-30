from unblock.confidence import compute
from unblock.data import load_docs, load_user
from unblock.friction import build_map, log_live_event
from unblock.knowledge import answer
from unblock.retrieval import search
from unblock.risk import assess
from unblock.routing import rank, record_wrong_person
from unblock.verifier import Claim, verify_claim

DOCS = load_docs()
USER = load_user()


# ---------- verifier ----------
def test_verifier_accepts_exact_quote():
    v = verify_claim(Claim("The meal limit is 75 USD per person", "The meal limit is 75 USD per person including tax and tip.", "D04"), DOCS)
    assert v.passed


def test_verifier_ignores_case_spacing_and_quotes():
    v = verify_claim(Claim("The meal limit is 75 USD", "the MEAL limit   is 75 USD per person", "D04"), DOCS)
    assert v.passed


def test_verifier_blocks_invented_quote():
    v = verify_claim(Claim("Run deploy-prod", "Run make deploy-prod to ship to production.", "D13"), DOCS)
    assert not v.passed and "not found" in v.reason


def test_verifier_blocks_wrong_number():
    v = verify_claim(Claim("The meal limit is 100 USD", "The meal limit is 75 USD per person", "D04"), DOCS)
    assert not v.passed and "100" in v.reason


def test_verifier_blocks_unretrieved_source_and_short_quote():
    assert not verify_claim(Claim("The meal limit is 75 USD", "The meal limit is 75 USD", "D99"), DOCS).passed
    assert not verify_claim(Claim("meal limit", "meal limit", "D04"), DOCS).passed


def test_verifier_blocks_quotes_cut_out_of_a_negation():
    v = verify_claim(Claim("New engineers get production access in their first week",
                           "get production access during their first 30 days", "D15"), DOCS)
    assert not v.passed


def test_verifier_blocks_claims_that_flip_or_stretch_the_quote():
    assert not verify_claim(Claim("You need special access to deploy to staging",
                                  "You do not need special access to deploy to staging", "D13"), DOCS).passed
    assert not verify_claim(Claim("Alcohol is reimbursable, no approval needed",
                                  "alcohol is not reimbursable unless", "D04"), DOCS).passed
    assert verify_claim(Claim("You don't need special access to deploy to staging",
                              "You do not need special access to deploy to staging", "D13"), DOCS).passed


# ---------- risk gate ----------
def test_risk_stops_high_impact_topics():
    for q in ["Can the AI decide whether I deserve a promotion?", "What's my salary band?",
              "Am I eligible for benefits as an intern?", "I feel harassed by a coworker"]:
        assert assess(q).level == "stop", q


def test_risk_catches_indirect_pay_and_benefits_questions():
    for q in ["How much do I get paid?", "When is payday?", "How is my performance evaluated?",
              "Does health insurance start on day one?"]:
        assert assess(q).level == "stop", q
    assert assess("I need access to the production DB").level == "approval"


def test_risk_has_no_false_stops_on_substrings():
    for q in ["I am quite lost on the VPN", "how do I pip install the cli", "How do I improve dashboard performance?",
              "Is there a coverage report dashboard?"]:
        assert assess(q).level == "routine", q


def test_risk_requires_approval_for_elevated_access():
    assert assess("Give me prod DB access").level == "approval"
    assert assess("I need access to the analytics dashboard").level == "approval"


def test_risk_leaves_routine_questions_alone():
    for q in ["How do I raise a ticket with IT?", "How do I approve expenses?", "How do I deploy to staging?"]:
        assert assess(q).level == "routine", q


# ---------- retrieval ----------
def test_retrieval_flags_stale_doc():
    r = search("How do I deploy to staging?", office="US")
    ids = {d.doc.id: d.stale for d in r.docs}
    assert ids.get("D13") is False and ids.get("D14") is True


def test_retrieval_sets_aside_other_region():
    r = search("How do I request time off?", office="US")
    assert [d.doc.id for d in r.docs][0] == "D06"
    assert "D07" in [d.id for d in r.excluded_regional]


def test_retrieval_is_weak_when_docs_dont_cover_question():
    assert search("Is there free lunch on Fridays?", office="US").top_score < 6


# ---------- confidence ----------
def test_confidence_has_no_fixed_base():
    assert compute(0, False, None, 0, 0).score == 25  # only the agreement factor
    assert compute(12, False, 10, 3, 3).score == 100
    assert compute(12, True, 10, 3, 3).label != "High"


# ---------- knowledge pipeline ----------
class LyingLLM:
    mode = "test"

    def answer(self, question, user, passages):
        return {"can_answer": True, "title": "Deploying",
                "claims": [{"text": "Merges to main deploy staging automatically", "quote": "Staging deploys happen automatically when a pull request is merged to main", "source_id": "D13"},
                           {"text": "Run make deploy-prod", "quote": "run make deploy-prod from your laptop", "source_id": "D13"}],
                "steps": [], "conflicts": [], "missing": ""}


def test_pipeline_shows_only_verified_claims():
    r = answer("How do I deploy to staging?", USER, LyingLLM())
    assert [c["text"] for c in r.claims] == ["Merges to main deploy staging automatically"]
    assert len(r.blocked) == 1 and "deploy-prod" in r.blocked[0]["text"]
    assert any(c["type"] == "stale doc" for c in r.conflicts)


def test_pipeline_without_verifier_lets_lies_through():
    r = answer("How do I deploy to staging?", USER, LyingLLM(), verify=False)
    assert len(r.claims) == 2 and not r.blocked


def test_pipeline_routes_when_docs_dont_cover_it():
    r = answer("Is there free lunch on Fridays?", USER, LyingLLM())
    assert r.decision == "route"


# ---------- routing ----------
def test_routing_prefers_doc_owner():
    r = rank("my vpn won't connect", USER)
    assert r.chosen.name == "Diego Martinez"
    assert any("owns" in x for x in r.chosen.reasons)


def test_fairness_rotation_spreads_load():
    r = rank("How do I set up my dev environment?", USER)
    assert r.chosen.name == "Hannah Brooks"  # Wei owns the doc but already has 14 recent questions
    assert "spreading questions" in r.rotation_note


def test_wrong_person_feedback_changes_ranking():
    first = rank("my vpn won't connect", USER)
    for _ in range(3):
        record_wrong_person(first.chosen.person_id, first.topic_key)
    again = rank("my vpn won't connect", USER)
    assert again.chosen.person_id != first.chosen.person_id


def test_routing_never_returns_the_new_hire():
    assert all(c.person_id != USER["id"] for c in [rank("dashboards", USER).chosen])


# ---------- friction map ----------
def test_friction_map_is_computed_and_hides_small_groups():
    fmap = build_map()
    topics = {c["topic"]: c for c in fmap["clusters"]}
    assert topics["analytics access"]["count"] == 18
    assert "password and mfa" not in topics and fmap["hidden_small_cohort_events"] >= 5
    assert all(c["count"] >= fmap["min_cohort_size"] for c in fmap["clusters"])
    assert topics["analytics access"]["fixable"]


def test_live_events_update_the_map():
    before = {c["topic"]: c["count"] for c in build_map()["clusters"]}["vpn and remote access"]
    log_live_event("D10", ["D10"], True)
    after = {c["topic"]: c["count"] for c in build_map()["clusters"]}["vpn and remote access"]
    assert after == before + 1


# ---------- payments ----------
def test_payment_commit_must_match_the_request(monkeypatch):
    import sys
    import time
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent / "agents"))
    import insights_agent as ia
    from uagents_core.contrib.protocols.payment import CommitPayment, Funds

    pending = {"reference": "FR-1", "expires": time.time() + 60}
    good = CommitPayment(funds=Funds(amount="0.1", currency="FET"), recipient=ia._wallet(), transaction_id="tx", reference="FR-1")
    assert ia._payment_problem(pending, good) == ""
    assert ia._payment_problem(None, good)
    assert ia._payment_problem(pending, good.copy(update={"reference": "FR-2"}))
    assert ia._payment_problem(pending, good.copy(update={"funds": Funds(amount="0.01", currency="FET")}))
    assert ia._payment_problem(pending, good.copy(update={"recipient": "fetch1someoneelse"}))
    assert ia._payment_problem({"reference": "FR-1", "expires": time.time() - 1}, good)


def test_strip_agent_mentions():
    from unblock.chat import strip_mentions
    a = "agent1qvxgega6yer28glv25lyrkrr2j5r4dhky93twt94gjntrk2lcpswud2vcg7"
    assert strip_mentions(f"@{a} What's our deploy process?") == "What's our deploy process?"
    assert strip_mentions(f"@{a} pending") == "pending"
    assert strip_mentions(f"@{a} edit: Hi Wei, thanks") == "edit: Hi Wei, thanks"
    assert strip_mentions("email me at a@b.com") == "email me at a@b.com"
    assert strip_mentions('{"action": "approve"}') == '{"action": "approve"}'
