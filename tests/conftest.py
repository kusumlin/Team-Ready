import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["UNBLOCK_TODAY"] = "2026-10-17"
os.environ["UNBLOCK_LLM"] = "extractive"
os.environ["SMTP_HOST"] = ""
os.environ["DEMO_RECIPIENT_OVERRIDE"] = ""
# Keep tests independent of the deployment .env (load_dotenv never overrides a variable that is already set).
for _name in ("ANTHROPIC_API_KEY", "AGENTVERSE_API_KEY", "WORKDAY_MCP_URL", "WORKDAY_MCP_TOKEN", "WORKDAY_MCP_REFRESH_TOKEN", "VOICE_TOOL_SECRET", "PORTAL_MANAGER_KEY", "MANAGER_ALLOWED_SENDERS", "MANAGER_CHAT_ADDRESS",
              "TRACKER_DUE_MINUTES", "TRACKER_DUE_HOURS", "UNBLOCK_EMBEDDINGS", "GEMINI_API_KEY", "TIMESCALE_URL",
              "CREAO_APP_ID", "CREAO_API_KEY", "CREAO_WEBHOOK_URL", "WORKDAY_HOST", "WORKDAY_TENANT",
              "WORKDAY_CLIENT_ID", "WORKDAY_CLIENT_SECRET", "WORKDAY_REFRESH_TOKEN", "SNOWFLAKE_ACCOUNT",
              "SNOWFLAKE_PAT", "SOLANA_RECIPIENT", "SMTP_USER", "SMTP_PASSWORD", "WEB_RATE_PER_MIN"):
    os.environ[_name] = ""

import pytest  # noqa: E402

from unblock import friction, routing  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(routing, "FEEDBACK_PATH", tmp_path / "feedback.json")
    monkeypatch.setattr(friction, "LIVE_EVENTS_PATH", tmp_path / "live.json")
    import unblock.actions as actions
    monkeypatch.setattr(actions, "OUTBOX_DIR", tmp_path / "outbox")
    from unblock import activity, portal
    monkeypatch.setattr(activity, "PATH", tmp_path / "activity.jsonl")
    monkeypatch.setattr(portal, "PATH", tmp_path / "portal.json")
    from unblock import canary
    monkeypatch.setattr(canary, "PATH", tmp_path / "canary.json")
    from unblock import autopilot
    monkeypatch.setattr(autopilot, "PATH", tmp_path / "systems.json")
    if "web.app" in sys.modules:  # each test gets a fresh per-minute rate limit
        sys.modules["web.app"]._hits.clear()
        sys.modules["web.app"]._fmap.update(value=None, at=0.0)
    yield
