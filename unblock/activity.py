"""Agent Activity: a live log of what each agent is doing, for the /activity page.

Every agent appends one JSON line per step to data/runtime/activity.jsonl (a
volume the web container shares). The page polls /api/activity and draws the
messages between agents as they happen.

Privacy: the log keeps what the agents did, not what people wrote. A user
message is shown only if the Guardian finds nothing sensitive in it, and is cut
to 100 characters. Drafted message bodies are never logged.

UNBLOCK_ACTIVITY=false turns it off.
"""
import json
import re
import threading
import time

from .config import DATA_DIR, env

PATH = DATA_DIR / "runtime" / "activity.jsonl"
MAX_BYTES = 2_000_000
KEEP = 2000
NAMES: dict[str, str] = {}   # agent address -> short name, filled in by agents/common.py
_lock = threading.Lock()
_last = [0]


def enabled() -> bool:
    return env("UNBLOCK_ACTIVITY", "true").lower() != "false"


def name_for(address: str, default: str = "user") -> str:
    return NAMES.get(address, default)


def _clean(text: str, limit: int = 240) -> str:
    text = re.sub(r"\*\*|`|__", "", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def said(text: str) -> str:
    """What a person typed, safe to show: hidden if it holds a secret, an ID number or health details."""
    from .risk import check_draft

    if any(i.startswith("contains") or "health" in i for i in check_draft("", text)):
        return "(message hidden: it contains sensitive details)"
    if text.strip().startswith("{"):
        return "(clicked a card button)"
    return "“" + _clean(text, 100) + "”"


def log(src: str, text: str, to: str = "", kind: str = "step") -> None:
    """kind: message (one agent to another), step (inside an agent), check (passed), block (stopped), done."""
    if not enabled():
        return
    with _lock:
        now = time.time_ns()
        _last[0] = now = max(now, _last[0] + 1)
        event = {"id": now, "ts": round(now / 1e9, 3), "from": src, "to": to, "kind": kind, "text": _clean(text)}
        try:
            PATH.parent.mkdir(parents=True, exist_ok=True)
            with PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event) + "\n")
            if PATH.stat().st_size > MAX_BYTES:
                lines = PATH.read_text(encoding="utf-8").splitlines()[-KEEP:]
                PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass  # the log must never break an agent


def since(after: int = 0, limit: int = 300) -> list[dict]:
    try:
        lines = PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-KEEP:]:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("id", 0) > after:
            out.append(event)
    return out[-limit:]


def clear() -> None:
    with _lock:
        try:
            PATH.unlink()
        except OSError:
            pass
