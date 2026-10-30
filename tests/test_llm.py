"""The Anthropic path, with a fake Anthropic client (no network)."""
import json
from types import SimpleNamespace

from unblock.data import load_user
from unblock.knowledge import answer
from unblock.llm import AnthropicLLM, LLMError, _parse_json


def test_parse_json_handles_fences_and_prose():
    assert _parse_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('{"a": {"b": 2}} trailing') == {"a": {"b": 2}}
    try:
        _parse_json("no json here")
        raise AssertionError("expected LLMError")
    except LLMError:
        pass


class FakeMessages:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="```json\n" + json.dumps(self.payload) + "\n```")])


def make_anthropic(payload):
    llm = AnthropicLLM.__new__(AnthropicLLM)
    llm.model = "test-model"
    llm.client = SimpleNamespace(messages=FakeMessages(payload))
    return llm


def test_model_answer_goes_through_the_verifier():
    payload = {"can_answer": True, "title": "Expense limits",
               "claims": [{"text": "Client meals are capped at 75 USD per person", "quote": "The meal limit is 75 USD per person including tax and tip.", "source_id": "D04"},
                          {"text": "Alcohol is always fine", "quote": "Alcohol is always reimbursable at client dinners", "source_id": "D04"}],
               "steps": [{"text": "Submit within 30 days", "quote": "Submit expense reports in Expense Hub within 30 days of the purchase.", "source_id": "D05"}],
               "conflicts": [], "missing": ""}
    llm = make_anthropic(payload)
    r = answer("What's the meal limit for a client lunch?", load_user(), llm)
    assert r.decision == "answer"
    assert [c["source_id"] for c in r.claims] == ["D04"] and len(r.steps) == 1
    assert len(r.blocked) == 1 and "Alcohol" in r.blocked[0]["text"]
    sent = llm.client.messages.calls[0]
    assert "temperature" not in sent and "[D04]" in sent["messages"][0]["content"]  # current models reject sampling params


def test_model_saying_it_cannot_answer_routes_to_a_person():
    llm = make_anthropic({"can_answer": False, "title": "Not covered", "claims": [], "steps": [], "conflicts": [], "missing": "number of days"})
    r = answer("How many vacation days do I get per year?", load_user(), llm)
    assert r.decision == "route"
