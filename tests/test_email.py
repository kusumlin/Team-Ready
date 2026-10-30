from unblock import actions


def test_unreachable_mail_server_saves_to_outbox_instead_of_hanging(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    actions._reach.clear()
    monkeypatch.setattr(actions, "_reachable", lambda host, port: False)
    r = actions.send_email("someone@lumen.example", "Hi", "Body", "maya.chen@lumen.example")
    assert r["status"] == "simulated" and "isn't reachable from this network" in r["detail"]


def test_no_smtp_host_is_simulated():
    r = actions.send_email("someone@lumen.example", "Hi", "Body", "maya.chen@lumen.example")
    assert r["status"] == "simulated" and "not configured" in r["detail"]


def test_unreachable_tiger_data_falls_back_to_local_events(monkeypatch):
    from unblock import friction, timeseries
    monkeypatch.setenv("TIMESCALE_URL", "postgres://user:pw@unreachable.example:5432/db")
    timeseries._down["until"] = 0
    def boom():
        raise OSError("connection timeout expired")
    monkeypatch.setattr(timeseries, "connect", boom)
    friction.log_live_event("D01", ["D02"], False)   # no exception: the event is kept locally
    m = friction.build_map()
    assert m["storage"].startswith("JSON files") and "not reachable" in m["storage"]
    timeseries._down["until"] = 0
