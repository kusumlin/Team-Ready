"""Model layer. Anthropic's model does the reasoning; an extractive mode exists for tests and
as a measured baseline in the eval. The mode is always shown to the user.

UNBLOCK_LLM=anthropic   (default) needs ANTHROPIC_API_KEY and LLM_MODEL
UNBLOCK_LLM=extractive  no model: quotes the best passages directly
"""
import json
import re

from .config import env

ANSWER_SYSTEM = """You are TeamReady, an onboarding assistant for new employees at Lumen Labs (a fictional company).
You answer ONLY from the passages provided. You never use outside knowledge about any company.

Rules:
- Every fact you state must be a claim with a supporting quote copied WORD FOR WORD from one passage, plus that passage's doc id.
- A quote must be one continuous span of the passage text, at least 4 words long. Do not paraphrase inside quotes.
- If the passages do not answer the question, set can_answer to false. Do not guess.
- Do not stretch a number or value written for one purpose to answer a different one. If the question asks for a
  specific value (an amount, limit, date, hostname, command or password) and no passage gives that value for that
  case, set can_answer to false and say in missing what is not covered (for example, a parking fee is not a
  commuting allowance). A general rule that clearly covers the question still answers it, such as a rule for all
  production access, or a page for an office in the employee's own region.
- Ignore passages marked STALE unless no other passage covers the topic.
- If two passages give different instructions for the same thing, report it in conflicts.
- steps are the concrete actions the employee should take next, in order (0 to 4), each with its own quote.
- Write each claim using the same words as its quote, lightly shortened. Keep every "not", "no", "never" and "unless".
- Never add numbers, names, links or commands that are not in the quote.
- can_answer must be the JSON boolean true or false.

Return ONLY a JSON object with exactly these keys:
{"can_answer": true|false,
 "title": "a short headline with no facts, max 8 words",
 "claims": [{"text": "...", "quote": "...", "source_id": "D01"}],
 "steps": [{"text": "...", "quote": "...", "source_id": "D01"}],
 "conflicts": [{"description": "...", "quote_a": "...", "source_a": "D13", "quote_b": "...", "source_b": "D14"}],
 "missing": "what the passages do not cover, or empty string"}"""

DRAFT_SYSTEM = """You write short, friendly workplace messages on behalf of a new employee.
Write in the employee's voice, plain language, under 120 words. Do not invent policies, links, dates or numbers;
only use facts given to you. Return ONLY JSON: {"subject": "...", "body": "..."}"""

FIX_SYSTEM = """You propose a small edit to an internal onboarding doc so new hires stop getting stuck.
Use only the facts given. before_quote must be copied WORD FOR WORD from the target doc.
after_text is the improved replacement for that span. Return ONLY JSON:
{"before_quote": "...", "after_text": "...", "rationale": "one sentence"}"""


class LLMError(RuntimeError):
    pass


def _parse_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise LLMError("model did not return JSON")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"model returned invalid JSON: {exc}") from exc


class PromptLLM:
    """Shared prompts. Each provider only implements _json(system, prompt, max_tokens)."""

    mode = "base"
    model = ""

    def _json(self, system: str, prompt: str, max_tokens: int = 1500) -> dict:
        raise NotImplementedError

    def answer(self, question: str, user: dict, passages: list[dict]) -> dict:
        lines = []
        for p in passages:
            flag = " STALE" if p["stale"] else ""
            lines.append(f"[{p['doc_id']}] {p['title']} (updated {p['updated_at']}{flag}): {p['text']}")
        prompt = (
            f"Employee: {user['name']}, {user['role']}, {user['team']} team, {user['office']} office.\n"
            f"Question: {question}\n\nPassages:\n" + "\n".join(lines)
        )
        return self._json(ANSWER_SYSTEM, prompt)

    def draft(self, purpose: str, sender: dict, recipient: dict, facts: list[str], question: str) -> dict:
        prompt = (
            f"Purpose: {purpose}\nFrom: {sender['name']} ({sender['role']}, started {sender['start_date']})\n"
            f"To: {recipient['name']} ({recipient['role']})\nThe employee's question: {question}\n"
            "Facts you may use:\n" + ("\n".join(f"- {f}" for f in facts) or "- none")
        )
        return self._json(DRAFT_SYSTEM, prompt, max_tokens=500)

    def propose_fix(self, cluster: dict, doc_body: str, doc_title: str, related: str) -> dict:
        prompt = (
            f"Blocker cluster: {cluster['topic']} ({cluster['count']} blockers in 30 days).\n"
            f"Pattern: {cluster['pattern']}\n\nTarget doc '{doc_title}':\n{doc_body}\n\n"
            f"Related doc that has the missing detail:\n{related}"
        )
        return self._json(FIX_SYSTEM, prompt, max_tokens=500)


class AnthropicLLM(PromptLLM):
    mode = "anthropic"

    def __init__(self, model: str | None = None):
        key = env("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set")
        import anthropic

        self.client = anthropic.Anthropic(api_key=key)
        self.model = model or env("LLM_MODEL")
        if not self.model:
            raise LLMError("LLM_MODEL is not set (the Anthropic model ID)")

    def _json(self, system: str, prompt: str, max_tokens: int = 1500) -> dict:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # network, auth, rate limit
            raise LLMError(f"Model request failed: {exc}") from exc
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        return _parse_json(text)


class ExtractiveLLM:
    """No model. Quotes the strongest passages directly. Used for tests and as the
    eval baseline, never presented as AI reasoning."""

    mode = "extractive"

    def answer(self, question: str, user: dict, passages: list[dict]) -> dict:
        fresh = [p for p in passages if not p["stale"]] or passages
        if not fresh or fresh[0]["score"] < 4.0:
            return {"can_answer": False, "title": "No approved answer found", "claims": [], "steps": [], "conflicts": [], "missing": question}
        top_doc = fresh[0]["doc_id"]
        chosen = [p for p in fresh if p["doc_id"] == top_doc][:3]
        claims = [{"text": p["text"], "quote": p["text"], "source_id": p["doc_id"]} for p in chosen]
        return {"can_answer": True, "title": fresh[0]["title"], "claims": claims, "steps": [], "conflicts": [], "missing": ""}

    def draft(self, purpose: str, sender: dict, recipient: dict, facts: list[str], question: str) -> dict:
        first = recipient["name"].split()[0]
        body = f"Hi {first},\n\nI'm {sender['name']}, a new {sender['role']} on {sender['team']}. {purpose}\n\nMy question: {question}\n\nThank you!\n{sender['name'].split()[0]}"
        return {"subject": f"New hire question: {question[:60]}", "body": body}

    def propose_fix(self, cluster: dict, doc_body: str, doc_title: str, related: str) -> dict:
        from .text import tokens
        topic = set(tokens(cluster["topic"]))
        lines = [x for x in doc_body.splitlines() if x.strip()]
        before = max(lines, key=lambda x: len(topic & set(tokens(x))))
        return {"before_quote": before, "after_text": before.rstrip(".") + ". " + related.splitlines()[0],
                "rationale": cluster["pattern"]}


class UnavailableLLM:
    """Stands in when the model can't be created, so callers get a clear LLMError."""

    mode = "unavailable"

    def __init__(self, reason: str):
        self.reason = reason

    def answer(self, *args, **kwargs):
        raise LLMError(self.reason)

    def draft(self, *args, **kwargs):
        raise LLMError(self.reason)

    def propose_fix(self, *args, **kwargs):
        raise LLMError(self.reason)


def get_llm_or_unavailable(mode: str | None = None):
    try:
        return get_llm(mode)
    except LLMError as exc:
        return UnavailableLLM(str(exc))


def get_llm(mode: str | None = None):
    """anthropic (default) | gemini | snowflake | extractive"""
    mode = (mode or env("UNBLOCK_LLM", "anthropic")).lower()
    if mode == "extractive":
        return ExtractiveLLM()
    if mode == "gemini":
        from .providers import GeminiLLM
        return GeminiLLM()
    if mode == "snowflake":
        from .providers import SnowflakeLLM
        return SnowflakeLLM()
    return AnthropicLLM()
