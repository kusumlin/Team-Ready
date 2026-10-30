"""Real actions, run only after the new hire approves.

If SMTP settings are present, TeamReady sends the email for real (with a calendar
invite attached for 1:1 requests). If not, it writes the exact email to /outbox
and says "simulated" out loud. It never claims a send that didn't happen.

DEMO_RECIPIENT_OVERRIDE sends every email to one inbox you control, so a live
demo can show a real delivery without emailing the fictional employees.
"""
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from .config import OUTBOX_DIR, env


def make_ics(summary: str, organizer: str, attendee: str, start: datetime, minutes: int = 30) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fmt = "%Y%m%dT%H%M%SZ"
    end = start + timedelta(minutes=minutes)
    return "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TeamReady//LA Hacks//EN", "METHOD:REQUEST", "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@unblock", f"DTSTAMP:{stamp}",
        f"DTSTART:{start.astimezone(timezone.utc).strftime(fmt)}", f"DTEND:{end.astimezone(timezone.utc).strftime(fmt)}",
        f"SUMMARY:{summary}", f"ORGANIZER:mailto:{organizer}", f"ATTENDEE;RSVP=TRUE:mailto:{attendee}",
        "END:VEVENT", "END:VCALENDAR", "",
    ])


def next_slot(hour: int = 10) -> datetime:
    """Next weekday at the given local hour (Pacific, as a fixed UTC-7 offset for the demo)."""
    tz = timezone(timedelta(hours=-7))
    day = datetime.now(tz) + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0)


_reach: dict = {}


def _reachable(host: str, port: int) -> bool:
    """A 3-second check, cached for a minute, so a network that blocks email never makes an approval hang."""
    import socket
    import time as _t
    key = (host, port)
    if key in _reach and _t.time() - _reach[key][1] < 60:
        return _reach[key][0]
    try:
        socket.create_connection((host, port), timeout=3).close()
        ok = True
    except OSError:
        ok = False
    _reach[key] = (ok, _t.time())
    return ok


def send_email(to: str, subject: str, body: str, sender: str, ics: str | None = None) -> dict:
    override = env("DEMO_RECIPIENT_OVERRIDE")
    actual_to = override or to
    msg = EmailMessage()
    msg["From"] = env("SMTP_FROM", sender)
    msg["To"] = actual_to
    msg["Reply-To"] = sender
    msg["Subject"] = subject
    note = f"\n\n(Sent by TeamReady for {sender}. Intended recipient: {to}.)" if override else "\n\n(Sent by TeamReady after the sender approved it.)"
    msg.set_content(body + note)
    if ics:
        msg.add_attachment(ics.encode(), maintype="text", subtype="calendar", filename="invite.ics",
                           params={"method": "REQUEST"})

    host = env("SMTP_HOST")
    reachable = bool(host) and _reachable(host, int(env("SMTP_PORT", "587")))
    if not reachable:
        OUTBOX_DIR.mkdir(exist_ok=True)
        path = OUTBOX_DIR / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}.eml"
        path.write_bytes(bytes(msg))
        why = ("Email is not configured" if not host else
               "The mail server isn't reachable from this network (some Wi-Fi networks block email)")
        return {"status": "simulated", "to": actual_to, "detail": f"{why}, so nothing was sent. Saved to outbox/{path.name}."}
    try:
        port = int(env("SMTP_PORT", "587"))
        if port == 465:  # implicit TLS, for networks that block port 587
            server_cm = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
        else:
            server_cm = smtplib.SMTP(host, port, timeout=20)
        with server_cm as server:
            if port != 465:
                server.starttls(context=ssl.create_default_context())
            server.login(env("SMTP_USER"), env("SMTP_PASSWORD"))
            server.send_message(msg)
    except Exception as exc:
        return {"status": "failed", "to": actual_to, "detail": f"Email send failed: {exc}. Nothing was sent."}
    return {"status": "sent", "to": actual_to, "detail": f"Email sent to {actual_to}" + (" with a calendar invite." if ics else ".")}
