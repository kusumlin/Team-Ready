"""teamready-insights: the Friction Map, sold to People Ops through the Payment Protocol.

Free:  "friction map" -> top clusters (anonymous aggregates only).
Paid:  "full report"  -> 0.1 FET via the Payment Protocol, then the full report
       plus an AI-drafted doc fix for the worst process gap. The doc owner, a
       human, approves the fix before anything changes.

With CREAO_APP_ID set, the fix is drafted by the CREAO Doc Steward agent
(unblock/creao.py): the run starts, the report goes out, and the proposal
follows in the same chat when the run finishes. The exact-quote check applies
either way, and a failed or slow run falls back to drafting here.
"""
import asyncio
import json
import time
import uuid

from common import PUBLISH, create_agent  # noqa: F401
from uagents import Context, Protocol
from uagents_core.contrib.protocols.payment import (
    CancelPayment,
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
    payment_protocol_spec,
)

from unblock import activity, creao, render, solana_pay
from unblock.actions import send_email
from unblock.chat import card_message, create_chat_protocol, parse_input, text_message
from unblock.config import env
from unblock.data import load_docs, load_people
from unblock.friction import build_map, fix_target, log_live_event
from unblock.llm import LLMError, get_llm
from unblock.models import FrictionEvent
from unblock.text import normalize

PRICE = env("INSIGHTS_PRICE_FET", "0.1")
CREAO_CHECK_SECONDS = float(env("CREAO_CHECK_SECONDS", "20"))
CREAO_TIMEOUT_SECONDS = float(env("CREAO_TIMEOUT_MINUTES", "12")) * 60

agent = create_agent(
    "insights", "teamready-insights",
    "Friction Map for People Ops: groups repeated new-hire blockers into anonymous patterns (groups of 5+ only), "
    "finds the doc behind them, and drafts a fix for the doc owner to approve. Full report: 0.1 FET.",
    ["analytics", "people-ops", "payments"],
)
payment = Protocol(spec=payment_protocol_spec, role="seller")


@agent.on_message(FrictionEvent)
async def on_event(ctx: Context, sender: str, msg: FrictionEvent):
    if msg.doc_id:
        log_live_event(msg.doc_id, msg.docs_read, msg.resolved)


def _wallet() -> str:
    try:
        return str(agent.wallet.address())
    except Exception:
        return str(agent.address)


async def _request_payment(ctx: Context, sender: str) -> None:
    reference = "FR-" + uuid.uuid4().hex[:8].upper()
    ctx.storage.set(f"pay:{sender}", json.dumps({"reference": reference, "expires": time.time() + 300}))
    activity.log("insights", f"Payment request: {PRICE} FET (ref {reference})", to=activity.name_for(sender, "people_ops"), kind="message")
    testnet = env("FET_USE_TESTNET", "true").lower() == "true"
    await ctx.send(sender, RequestPayment(
        accepted_funds=[Funds(amount=PRICE, currency="FET", payment_method="fet_direct")],
        recipient=_wallet(), deadline_seconds=300, reference=reference,
        description="TeamReady Friction Map full report with doc-fix proposal",
        metadata={"agent": "teamready-insights", "service": "friction_map_report",
                  "fet_network": "stable-testnet" if testnet else "mainnet", "mainnet": "false" if testnet else "true",
                  "provider_agent_wallet": _wallet(),
                  "content": f"Pay {PRICE} FET to get the full Friction Map report and a drafted fix for the biggest process gap."},
    ))


def _target():
    """The biggest fixable cluster, with the doc to fix and the doc that has the missing detail."""
    docs = load_docs()
    for cluster in build_map()["clusters"]:
        target = fix_target(cluster) if cluster["fixable"] else None
        if target:
            return cluster, docs[target[0]], docs[target[1]]
    return None


def _check_fix(fix, cluster: dict, doc) -> dict:
    """Same rules whoever drafted the fix (Anthropic, Gemini or the CREAO Doc Steward): exact quote, non-empty edit."""
    if not isinstance(fix, dict):
        return {"cluster": cluster, "error": "The drafted fix wasn't in the expected format, so I blocked it."}
    before, after = str(fix.get("before_quote") or ""), fix.get("after_text")
    if len(normalize(before).split()) < 4 or normalize(before) not in normalize(doc.body):
        return {"cluster": cluster, "error": "The drafted fix didn't quote the doc exactly, so I blocked it."}
    if not isinstance(after, str) or not after.strip():
        return {"cluster": cluster, "error": "The drafted fix was empty, so I blocked it."}
    return {"cluster": cluster, "doc_id": doc.id, "doc_title": doc.title, "owner_id": doc.owner,
            "before": before, "after": after.strip(), "rationale": str(fix.get("rationale") or "")}


def _proposal() -> dict | None:
    found = _target()
    if not found:
        return None
    cluster, doc, source = found
    try:
        fix = get_llm().propose_fix(cluster, doc.body, doc.title, source.body)
    except LLMError as exc:
        return {"cluster": cluster, "error": f"The model is unavailable ({exc}), so no fix was drafted."}
    return _check_fix(fix, cluster, doc)


def _proposal_message(ctx: Context, sender: str, text: str, proposal: dict | None):
    if not proposal:
        return text_message(text + "\n\nNo cluster has a clear doc fix right now.")
    if "error" in proposal:
        return text_message(text + f"\n\n{proposal['error']}")
    ctx.storage.set(f"fix:{sender}", json.dumps(proposal))
    owner = load_people()[proposal["owner_id"]]
    text += (f"\n\n**Biggest fixable gap: {proposal['cluster']['topic']}.** {proposal['cluster']['pattern']}.\n"
             f"Proposed change to '{proposal['doc_title']}':\n- Before: {proposal['before']}\n- After: {proposal['after']}\n"
             f"Why: {proposal['rationale']}\n\nReply **approve** to send this to {owner['name']} (doc owner) for review, or **reject**.")
    return card_message(text, "review", {
        "title": f"Send a doc fix to {owner['name']}?",
        "summary_rows": [
            {"label": "Cluster", "value": f"{proposal['cluster']['topic']}: {proposal['cluster']['count']} blockers"},
            {"label": "Pattern", "value": proposal["cluster"]["pattern"]},
            {"label": "Before", "value": proposal["before"]}, {"label": "After", "value": proposal["after"]},
            {"label": "Privacy", "value": "Aggregates of 5+ only. No names or message text."}],
        "approve_cta": {"label": "Send to doc owner", "primary": True, "selection": {"action": "ub_approve"}},
        "reject_cta": {"label": "Not now", "selection": {"action": "ub_reject"}},
    })


def _start_creao(ctx: Context, sender: str) -> str:
    """Hand the drafting to the CREAO Doc Steward. Returns a status line, or "" to draft locally instead."""
    found = _target()
    if not found:
        return ""
    cluster, doc, source = found
    try:
        run_id = creao.start_run(creao.fix_inputs(cluster, doc.title, doc.body, source.title, source.body))
    except Exception as exc:
        ctx.logger.warning(f"CREAO run failed to start, drafting locally: {exc}")
        return ""
    pending = json.loads(ctx.storage.get("creao:pending") or "{}")
    pending[run_id] = {"sender": sender, "doc_id": doc.id, "topic": cluster["topic"], "started": time.time()}
    ctx.storage.set("creao:pending", json.dumps(pending))
    ctx.logger.info(f"CREAO Doc Steward run {run_id} started for {cluster['topic']}")
    activity.log("insights", f"Draft a fix for '{doc.title}': {cluster['count']} new-hire blockers about {cluster['topic']}", to="creao", kind="message")
    activity.log("creao", f"Doc Steward run {run_id[:8]} started (runs take a few minutes)", kind="step")
    return (f"\n\n**The CREAO Doc Steward is drafting a fix for '{doc.title}'** (run `{run_id}`). "
            "It takes a few minutes; I'll post the proposal in this chat when it's ready.")


async def _send_report(ctx: Context, sender: str):
    text = render.friction_text(build_map(), full=True)
    if creao.enabled():
        line = await asyncio.to_thread(_start_creao, ctx, sender)
        if line:
            return text_message(text + line)
    proposal = await asyncio.to_thread(_proposal)
    if proposal and "error" not in proposal:
        activity.log("insights", f"Drafted a fix for '{proposal['doc_title']}'; exact-quote check passed", kind="check")
    elif proposal:
        activity.log("insights", proposal["error"], kind="block")
    return _proposal_message(ctx, sender, text, proposal)


@agent.on_interval(period=CREAO_CHECK_SECONDS)
async def check_creao(ctx: Context):
    pending = json.loads(ctx.storage.get("creao:pending") or "{}")
    if not pending:
        return
    for run_id, job in list(pending.items()):
        timed_out = time.time() - job["started"] > CREAO_TIMEOUT_SECONDS
        try:
            run = await asyncio.to_thread(creao.get_run, run_id)
        except Exception as exc:
            ctx.logger.warning(f"CREAO poll {run_id}: {exc}")
            run = None
        if run is not None and run.get("status") not in creao.DONE and not timed_out:
            activity.log("creao", f"Doc Steward run {run_id[:8]}: {run.get('status', 'running')}…", kind="step")
            continue
        if run is None and not timed_out:
            continue
        del pending[run_id]
        ctx.storage.set("creao:pending", json.dumps(pending))
        found = _target()
        if not found:
            await ctx.send(job["sender"], text_message("The Friction Map changed while the fix was drafted; no fix is needed now."))
            continue
        cluster, doc, _ = found
        try:
            if run is None:
                raise LLMError("the run took too long")
            proposal = _check_fix(creao.result_fix(run), cluster, doc)
            head = f"**CREAO Doc Steward finished** (run `{run_id}`)."
            activity.log("creao", "Drafted a one-line fix to the doc", to="insights", kind="message")
            activity.log("insights", "Exact-quote check " + ("failed: fix blocked" if "error" in proposal else "passed: the fix quotes the doc word for word"), kind="block" if "error" in proposal else "check")
        except LLMError as exc:
            ctx.logger.warning(f"CREAO run {run_id} unusable ({exc}); drafting locally")
            activity.log("insights", f"CREAO run unusable ({exc}); drafting the fix here instead", kind="block")
            proposal = await asyncio.to_thread(_proposal)
            head = f"The CREAO run didn't return a usable fix ({exc}), so I drafted it here instead."
        activity.log("insights", "[card] Send this doc fix to the doc owner?" if proposal and "error" not in proposal else "No usable fix this time",
                     to=activity.name_for(job["sender"], "people_ops"), kind="message")
        await ctx.send(job["sender"], _proposal_message(ctx, job["sender"], head, proposal))


def _payment_problem(pending: dict | None, msg: CommitPayment) -> str:
    """Check the commit matches what we asked for. On-chain confirmation of the
    transaction itself is left to the ASI:One wallet in this build (see README)."""
    if not pending:
        return "there is no open payment request"
    if time.time() > pending["expires"]:
        return "the payment request expired"
    if msg.reference != pending["reference"]:
        return "the payment reference doesn't match"
    if msg.funds.currency.upper() != "FET":
        return "the currency must be FET"
    try:
        if float(msg.funds.amount) < float(PRICE):
            return f"the amount must be at least {PRICE} FET"
    except ValueError:
        return "the amount isn't a number"
    if msg.recipient != _wallet():
        return "the payment went to a different wallet"
    if not msg.transaction_id:
        return "there is no transaction id"
    return ""


@payment.on_message(CommitPayment)
async def on_commit(ctx: Context, sender: str, msg: CommitPayment):
    raw = ctx.storage.get(f"pay:{sender}")
    problem = _payment_problem(json.loads(raw) if raw else None, msg)
    if problem:
        ctx.logger.warning(f"payment from {sender} refused: {problem}")
        activity.log("insights", f"Payment refused: {problem}", kind="block")
        await ctx.send(sender, CancelPayment(transaction_id=msg.transaction_id, reason=problem))
        await ctx.send(sender, text_message(f"I couldn't accept that payment: {problem}. Nothing was charged for the report."))
        return
    ctx.storage.remove(f"pay:{sender}")
    activity.log("insights", f"Payment checked: reference, amount and wallet match ({msg.funds.amount} FET)", kind="check")
    try:
        report = await _send_report(ctx, sender)
    except Exception as exc:  # never take payment without delivering
        ctx.logger.exception("report failed")
        await ctx.send(sender, CancelPayment(transaction_id=msg.transaction_id, reason=f"report failed: {type(exc).__name__}"))
        await ctx.send(sender, text_message("Sorry, the report failed to generate, so I cancelled the payment. Please try again."))
        return
    await ctx.send(sender, CompletePayment(transaction_id=msg.transaction_id))
    activity.log("insights", "Full Friction Map report (groups of 5+ only)", to=activity.name_for(sender, "people_ops"), kind="message")
    await ctx.send(sender, report)


@payment.on_message(RejectPayment)
async def on_reject(ctx: Context, sender: str, msg: RejectPayment):
    ctx.storage.remove(f"pay:{sender}")
    await ctx.send(sender, text_message("No problem, the payment was cancelled. The free Friction Map summary is still available."))


async def chat(ctx: Context, sender: str, text: str):
    sel = parse_input(text)
    typed = text.strip().lower().rstrip(".!")
    action = str(sel.get("action", "")).lower().removeprefix("ub_") or typed
    if "ub_approve" in typed:
        action = "approve"
    elif "ub_reject" in typed:
        action = "reject"
    if action in ("approve", "reject"):
        raw = ctx.storage.get(f"fix:{sender}")
        if not raw:
            return "There's no drafted fix waiting. Ask for the full report first."
        ctx.storage.remove(f"fix:{sender}")
        if action == "reject":
            return "Okay, I discarded the proposed fix. Nothing was sent."
        p = json.loads(raw)
        owner = load_people()[p["owner_id"]]
        body = (f"Hi {owner['name'].split()[0]},\n\nUnblock's Friction Map shows {p['cluster']['count']} new-hire blockers about "
                f"{p['cluster']['topic']} in the last 30 days. {p['cluster']['pattern']}.\n\nProposed change to '{p['doc_title']}':\n"
                f"Before: {p['before']}\nAfter: {p['after']}\n\nYou decide whether to publish it.\n\nPeople Ops, via TeamReady")
        result = await asyncio.to_thread(send_email, owner["email"], f"Suggested fix for '{p['doc_title']}'", body, "people-ops@lumen.example")
        activity.log("insights", f"Fix sent to {owner['name']}, the doc owner, who decides whether to publish ({result['status']})", to="people", kind="done")
        return f"**{result['status'].capitalize()}.** {result['detail']} {owner['name']} decides whether to publish it."
    if action in ("pay with solana", "solana", "pay with usdc", "usdc", "solana pay"):
        if not solana_pay.enabled():
            return "Solana Pay isn't set up on this agent yet. Say **full report** to pay in FET instead."
        reference = solana_pay.new_reference()
        ctx.storage.set(f"sol:{sender}", reference)
        price = solana_pay.settings()["price"]
        return (f"Pay {price} USDC with any Solana wallet using this Solana Pay link:\n\n{solana_pay.payment_url(reference)}\n\n"
                "When your wallet confirms, say **check payment** and I'll verify it on-chain before sending the report.")
    if action in ("check payment", "check", "i paid", "paid", "done"):
        reference = ctx.storage.get(f"sol:{sender}")
        if not reference:
            return "There's no Solana payment waiting. Say **pay with solana** to start one."
        paid, detail = await asyncio.to_thread(solana_pay.check_payment, reference)
        if not paid:
            return detail
        ctx.storage.remove(f"sol:{sender}")
        report = await _send_report(ctx, sender)
        report.content[0].text = f"**{detail}**\n\n" + report.content[0].text
        return report
    if action in ("full report", "buy", "buy the report", "buy full report", "purchase", "get the full report", "buy report"):
        await _request_payment(ctx, sender)
        return f"The full report with a drafted doc fix costs {PRICE} FET. I've sent a payment request in this chat."
    extra = f" or **pay with solana** ({solana_pay.settings()['price']} USDC)" if solana_pay.enabled() else ""
    return render.friction_text(build_map()) + f"\n\nSay **full report** to get patterns and a drafted fix ({PRICE} FET){extra}."


agent.include(create_chat_protocol("teamready-insights", chat, person="people_ops"), publish_manifest=PUBLISH)
agent.include(payment, publish_manifest=PUBLISH)

if __name__ == "__main__":
    agent.run()
