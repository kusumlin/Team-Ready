"""Read the new hire's profile from a Workday development tenant (Workday Build).

Only four fields are read: name, business title, supervisory organization and
work email. Nothing else (pay, performance, personal data) is requested.

WORKDAY_HOST           e.g. wd2-impl-services1.workday.com (from your tenant's API settings)
WORKDAY_TENANT         your tenant name
WORKDAY_CLIENT_ID      from "Register API Client for Integrations"
WORKDAY_CLIENT_SECRET
WORKDAY_REFRESH_TOKEN  from "Manage Refresh Tokens for Integrations"
WORKDAY_WORKER_SEARCH  who the demo new hire is, e.g. "mcneil" (the sample persona)

If anything fails, TeamReady falls back to data/user.json and says so in /api/health.
"""
import threading
import time

import httpx

from .config import env

_token: dict = {}
_profile: dict = {"at": 0.0, "value": None, "error": ""}
CACHE_SECONDS = 600


def enabled() -> bool:
    return all(env(k) for k in ("WORKDAY_HOST", "WORKDAY_TENANT", "WORKDAY_CLIENT_ID", "WORKDAY_CLIENT_SECRET", "WORKDAY_REFRESH_TOKEN"))


def _base() -> str:
    host = env("WORKDAY_HOST").strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    return f"https://{host}"


def access_token(client: httpx.Client) -> str:
    if _token.get("value") and _token["expires"] > time.time() + 60:
        return _token["value"]
    r = client.post(f"{_base()}/ccx/oauth2/{env('WORKDAY_TENANT')}/token",
                    auth=(env("WORKDAY_CLIENT_ID"), env("WORKDAY_CLIENT_SECRET")),
                    data={"grant_type": "refresh_token", "refresh_token": env("WORKDAY_REFRESH_TOKEN")}, timeout=8)
    r.raise_for_status()
    data = r.json()
    _token.update(value=data["access_token"], expires=time.time() + int(data.get("expires_in", 3600)))
    return _token["value"]


def fetch_profile(client: httpx.Client | None = None) -> dict:
    client = client or httpx.Client()
    token = access_token(client)
    r = client.get(f"{_base()}/ccx/api/v1/{env('WORKDAY_TENANT')}/workers",
                   params={"search": env("WORKDAY_WORKER_SEARCH", "mcneil"), "limit": 1},
                   headers={"Authorization": f"Bearer {token}"}, timeout=8)
    r.raise_for_status()
    items = r.json().get("data") or []
    if not items:
        raise LookupError("no worker matched WORKDAY_WORKER_SEARCH")
    w = items[0]
    org = (w.get("primarySupervisoryOrganization") or {}).get("descriptor", "")
    return {"workday_id": w.get("id", ""), "name": w.get("descriptor", ""), "role": w.get("businessTitle", ""),
            "team": org, "email": w.get("primaryWorkEmail", "")}


def _refresh(client: httpx.Client | None = None) -> None:
    try:
        _profile.update(value=fetch_profile(client), error="")
    except Exception as exc:  # keep working on the local profile
        _profile.update(value=None, error=f"{type(exc).__name__}: {exc}"[:200])
    _profile["at"] = time.time()
    _profile["busy"] = False


def profile(client: httpx.Client | None = None, wait: bool = False) -> dict | None:
    """Cached profile, or None (with the reason kept in status()) if Workday isn't usable.
    Refreshes in the background so a slow or unreachable tenant never holds up a page or a reply;
    wait=True fetches inline (tests and the setup check)."""
    if not enabled():
        return None
    if time.time() - _profile["at"] < CACHE_SECONDS:
        return _profile["value"]
    if wait or client is not None:
        _refresh(client)
    elif not _profile.get("busy"):
        _profile["busy"] = True
        threading.Thread(target=_refresh, daemon=True).start()
    return _profile["value"]


def status() -> str:
    if not enabled():
        return "local profile (Workday not configured)"
    if _profile["value"]:
        return f"Workday worker {_profile['value']['name']}"
    return f"local profile (Workday unavailable: {_profile['error'] or 'not fetched yet'})"
