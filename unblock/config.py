import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTBOX_DIR = ROOT / "outbox"

load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def today() -> date:
    """The date used for freshness. Pin it with UNBLOCK_TODAY for repeatable demos."""
    pinned = env("UNBLOCK_TODAY")
    return date.fromisoformat(pinned) if pinned else date.today()


# How many days before a doc counts as stale.
STALE_AFTER_DAYS = int(env("UNBLOCK_STALE_AFTER_DAYS", "365"))
