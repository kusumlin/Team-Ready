"""Walk through TeamReady live and save presentation screenshots to docs/screenshots.

    pip install playwright   # uses your installed Chrome (channel="chrome")
    python scripts/capture_screenshots.py <PORTAL_MANAGER_KEY>   # with the web app on localhost:8081
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8081"
OUT = Path("/Users/sree/unblock/docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
KEY = sys.argv[1] if len(sys.argv) > 1 else ""
only = set(sys.argv[2:])


def shot(target, name, full=False):
    path = OUT / f"{name}.png"
    if hasattr(target, "screenshot") and not full and target.__class__.__name__ == "Locator":
        target.screenshot(path=str(path))
    else:
        if full:  # a sticky top bar would be drawn mid-page in a full-page capture
            target.add_style_tag(content=".nav{position:static !important}")
        else:
            target.evaluate("window.scrollTo(0,0)")
        target.screenshot(path=str(path), full_page=full)
        if full:
            target.evaluate("document.querySelectorAll('style').forEach(s => { if (s.textContent.includes('.nav{position:static')) s.remove(); })")
    print("saved", path.name, flush=True)


FOCUS_ON = """(keep) => {
  const msgs = [...document.querySelectorAll('#log .msg')];
  msgs.forEach((m, i) => { m.dataset.hid = m.style.display; if (i < msgs.length - keep) m.style.display = 'none'; });
  const a = document.querySelector('aside.panel'); a.dataset.css = a.getAttribute('style') || '';
  a.style.height = 'auto'; a.style.position = 'static'; document.getElementById('log').style.overflow = 'visible';
  document.getElementById('chips').style.display = 'none';
}"""
FOCUS_OFF = """() => {
  document.querySelectorAll('#log .msg').forEach(m => m.style.display = m.dataset.hid || '');
  const a = document.querySelector('aside.panel'); a.setAttribute('style', a.dataset.css);
  document.getElementById('log').style.overflow = ''; document.getElementById('chips').style.display = '';
}"""


def chat_shot(page, name, keep=2):
    """The latest exchange in full (the question and the whole reply), not a cropped scroll window."""
    page.evaluate(FOCUS_ON, keep)
    page.wait_for_timeout(300)
    page.locator("aside.panel").screenshot(path=str(OUT / f"{name}.png"))
    page.evaluate(FOCUS_OFF)
    print("saved", name + ".png", flush=True)


def wait_reply(page, before, timeout=120000):
    page.wait_for_function(
        "n => document.querySelectorAll('#log .msg.bot').length > n && !document.querySelector('#log .typing')",
        arg=before, timeout=timeout)
    page.wait_for_timeout(600)
    page.evaluate("document.getElementById('log').scrollTop = 1e9")


def say(page, text):
    before = page.locator("#log .msg.bot").count()
    page.fill("#q", text)
    page.press("#q", "Enter")
    wait_reply(page, before)


def click_last(page, label):
    before = page.locator("#log .msg.bot").count()
    page.locator("#log .msg.bot").last.locator("button", has_text=re.compile("^" + label)).first.click()
    wait_reply(page, before)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, color_scheme="light")
    page = ctx.new_page()
    assist = page.locator("aside.panel")

    page.goto(BASE + "/")
    page.wait_for_timeout(1500)
    shot(page, "00_landing")

    page.goto(BASE + "/workday")
    page.wait_for_timeout(2500)
    shot(page, "01_workday_home")

    say(page, "What's our deploy process for staging?")
    chat_shot(page, "02_verified_answer_stale_doc_flagged")
    click_last(page, "Reject")

    say(page, "How many vacation days do I get?")
    chat_shot(page, "03_no_guess_routes_to_a_person")
    say(page, "edit: Hi, my password is test123, can you check my account?")
    chat_shot(page, "04_guardian_blocks_password")
    say(page, "reject")

    say(page, "My laptop screen is cracked")
    chat_shot(page, "05_it_ticket_review_before_acting")
    click_last(page, "Approve")
    chat_shot(page, "06_it_ticket_done")

    before = page.locator("#log .msg.bot").count()
    page.click("#autoBtn")
    wait_reply(page, before)
    shot(page, "07_checklist_plan_awaiting_approval")
    chat_shot(page, "07b_checklist_plan_card")
    click_last(page, "Approve")
    chat_shot(page, "08_checklist_done_manager_message_review")
    click_last(page, "Approve")
    page.wait_for_timeout(4500)
    shot(page, "09_request_sent_journey_progress")

    page.click("#rMgr")
    page.wait_for_timeout(1500)
    if page.locator("#mgrKeyRow").is_visible():
        page.fill("#mgrKey", KEY)
        page.click("#mgrKeyGo")
        page.wait_for_timeout(2000)
    summ = page.locator("#mgrInbox details summary").first
    if summ.count():
        summ.click()
    page.wait_for_timeout(500)
    shot(page, "10_manager_inbox_with_evidence")
    page.locator("#mgrInbox button", has_text="Approve").first.click()
    page.wait_for_timeout(2500)
    shot(page, "11_manager_decided_history")

    page.click("#rHire")
    page.wait_for_timeout(6000)
    page.evaluate("document.getElementById('log').scrollTop = 1e9")
    shot(page, "12_form_filed_after_manager_approval", full=True)
    shot(page.locator("#history").locator(".."), "12b_done_for_you")

    say(page, "Can the AI decide whether I deserve a promotion?")
    chat_shot(page, "13_high_impact_stopped_person_named")

    trust = page.locator("section.card", has_text="How TeamReady Works")
    trust.scroll_into_view_if_needed()
    shot(trust, "14_trust_card")

    page.click("#rOps")
    page.wait_for_timeout(3500)
    page.evaluate("window.scrollTo(0,0)")
    shot(page, "15_people_ops_onboarding_health", full=True)

    page.goto(BASE + "/canary")
    page.wait_for_timeout(2500)
    shot(page, "16_canary_new_hires", full=True)

    page.goto(BASE + "/activity")
    page.wait_for_timeout(3500)
    shot(page, "17_agent_activity_live")

    for name, url in [("18_creao_doc_steward_run", "https://agent.creao.ai/share/0773babf9c5d456f0fc0446a58d6da2f")]:
        try:
            page.goto(url, timeout=30000)
            page.wait_for_timeout(5000)
            shot(page, name)
        except Exception as exc:
            print("skip", name, exc)
    browser.close()
