"""Other model providers behind the same prompts and the same verifier.

Gemini (Google AI Studio REST API):
  UNBLOCK_LLM=gemini, GEMINI_API_KEY, GEMINI_MODEL (default gemini-2.5-flash)
  Gemini embeddings also power hybrid retrieval: UNBLOCK_EMBEDDINGS=gemini,
  GEMINI_EMBED_MODEL (default gemini-embedding-001).

Snowflake Cortex (OpenAI-compatible chat completions REST API):
  UNBLOCK_LLM=snowflake, SNOWFLAKE_ACCOUNT (account identifier, e.g. myorg-myacct),
  SNOWFLAKE_PAT (programmatic access token), SNOWFLAKE_MODEL (default llama3.1-70b)

Swapping models never weakens the guarantees: every claim still goes through the
same plain-code verifier, and the eval compares providers on the same 40 questions.
"""
import httpx

from .config import env
from .llm import LLMError, PromptLLM, _parse_json

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiLLM(PromptLLM):
    mode = "gemini"

    def __init__(self, model: str | None = None, client: httpx.Client | None = None):
        self.key = env("GEMINI_API_KEY")
        if not self.key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.model = model or env("GEMINI_MODEL", "gemini-2.5-flash")
        self.client = client or httpx.Client(timeout=60)

    def _json(self, system: str, prompt: str, max_tokens: int = 1500) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": max_tokens, "responseMimeType": "application/json"},
        }
        try:
            r = self.client.post(f"{GEMINI_BASE}/models/{self.model}:generateContent",
                                 headers={"x-goog-api-key": self.key}, json=body)
            r.raise_for_status()
            data = r.json()
            parts = data["candidates"][0]["content"]["parts"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Gemini request failed: {exc}") from exc
        return _parse_json("".join(p.get("text", "") for p in parts))


class SnowflakeLLM(PromptLLM):
    mode = "snowflake"

    def __init__(self, model: str | None = None, client: httpx.Client | None = None):
        self.account = env("SNOWFLAKE_ACCOUNT")
        self.token = env("SNOWFLAKE_PAT")
        if not (self.account and self.token):
            raise LLMError("SNOWFLAKE_ACCOUNT and SNOWFLAKE_PAT must be set")
        self.model = model or env("SNOWFLAKE_MODEL", "llama3.1-70b")
        self.client = client or httpx.Client(timeout=90)

    @property
    def url(self) -> str:
        return f"https://{self.account}.snowflakecomputing.com/api/v2/cortex/v1/chat/completions"

    def _json(self, system: str, prompt: str, max_tokens: int = 1500) -> dict:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0,
            "max_completion_tokens": max_tokens,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                   "Accept": "application/json", "X-Snowflake-Authorization-Token-Type": "PROGRAMMATIC_ACCESS_TOKEN"}
        try:
            r = self.client.post(self.url, headers=headers, json=body)
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Snowflake Cortex request failed: {exc}") from exc
        if isinstance(content, list):  # content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return _parse_json(str(content))


class GeminiEmbedder:
    """Gemini embeddings for hybrid (meaning + keyword) retrieval."""

    def __init__(self, client: httpx.Client | None = None):
        self.key = env("GEMINI_API_KEY")
        if not self.key:
            raise LLMError("GEMINI_API_KEY is not set")
        self.model = env("GEMINI_EMBED_MODEL", "gemini-embedding-001")
        self.client = client or httpx.Client(timeout=60)

    def embed(self, texts: list[str], task: str) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 100):  # API batch limit
            batch = texts[i : i + 100]
            body = {"requests": [{"model": f"models/{self.model}", "content": {"parts": [{"text": t}]}, "taskType": task}
                                 for t in batch]}
            try:
                r = self.client.post(f"{GEMINI_BASE}/models/{self.model}:batchEmbedContents",
                                     headers={"x-goog-api-key": self.key}, json=body)
                r.raise_for_status()
                out += [e["values"] for e in r.json()["embeddings"]]
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                raise LLMError(f"Gemini embedding request failed: {exc}") from exc
        return out
