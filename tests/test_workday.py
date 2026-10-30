import httpx

from unblock import data, workday


def setup_env(monkeypatch):
    for k, v in {"WORKDAY_HOST": "wd.example.com", "WORKDAY_TENANT": "acme_dev", "WORKDAY_CLIENT_ID": "id",
                 "WORKDAY_CLIENT_SECRET": "secret", "WORKDAY_REFRESH_TOKEN": "rt", "WORKDAY_WORKER_SEARCH": "mcneil"}.items():
        monkeypatch.setenv(k, v)
    workday._token.clear()
    workday._profile.update(at=0.0, value=None, error="")


def tenant(calls):
    def handler(request: httpx.Request):
        calls.append(request)
        if request.url.path == "/ccx/oauth2/acme_dev/token":
            assert b"grant_type=refresh_token" in request.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert request.url.path == "/ccx/api/v1/acme_dev/workers" and request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"data": [{"id": "3aa5", "descriptor": "Logan McNeil", "businessTitle": "Chief HR Officer",
                                                   "primaryWorkEmail": "lmcneil@workday.net",
                                                   "primarySupervisoryOrganization": {"descriptor": "Human Resources"}}]})
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_profile_from_workday(monkeypatch):
    setup_env(monkeypatch)
    calls = []
    p = workday.profile(tenant(calls))
    assert p == {"workday_id": "3aa5", "name": "Logan McNeil", "role": "Chief HR Officer", "team": "Human Resources",
                 "email": "lmcneil@workday.net"}
    assert calls[1].url.params["search"] == "mcneil"
    assert "Logan McNeil" in workday.status()


def test_load_user_merges_only_profile_fields(monkeypatch):
    setup_env(monkeypatch)
    workday.profile(tenant([]))
    user = data.load_user()
    assert user["name"] == "Logan McNeil" and user["profile_source"] == "Workday"
    assert user["manager_id"] == "p01" and user["office"] == "US"  # local fields untouched


def test_workday_failure_falls_back(monkeypatch):
    setup_env(monkeypatch)
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    assert workday.profile(down) is None
    assert "Workday unavailable" in workday.status()
    workday._profile.update(at=0.0)
    monkeypatch.delenv("WORKDAY_HOST")
    assert data.load_user()["name"] == "Maya Chen"
