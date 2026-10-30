"""The orchestrator's conversation logic, independent of uAgents so it can be tested.

The agent supplies `services` (calls to the other agents, with local fallback)
and a `store` (per-sender state). Every reply is a Reply: text, plus an optional
Interactive Card.
"""
import asyncio
import re
import uuid
from dataclasses import dataclass

from . import activity, autopilot, render, workday_mcp
from .data import load_people, load_user
from .llm import ExtractiveLLM, LLMError
from .risk import assess, check_draft


@dataclass
class Reply:
    text: str
    kind: str | None = None
    payload: dict | None = None
    terminal: bool = False


APPROVE = {"approve", "approved", "yes", "send", "send it", "approve and send", "looks good", "go ahead"}
REJECT = {"reject", "no", "cancel", "don't send", "dont send", "stop"}
GREETINGS = {"hi", "hello", "hey", "help", "start", "what can you do", "what can you do?"}

INTRO = (
    "Hi, I'm **TeamReady**, your onboarding buddy at Lumen Labs. No question is too basic.\n\n"
    "Tell me what's blocking you, in your own words. I'll answer only from approved company docs and show "
    "my sources, or find the right person to ask and draft the message for you. Nothing is sent without your OK.\n\n"
    "Try: \"How do I set up my dev environment?\", \"I need access to the analytics dashboard\", "
    "\"What's our deploy process for staging?\" or \"How many vacation days do I get?\""
)


# Card buttons carry distinctive ids ("ub_approve") so a typed sentence can never
# be mistaken for a click. Typed commands must match a whole short phrase.
ACTION_TYPES = ("system_action", "system_batch", "workday_action")  # pending items that do something, not messages
ACTIONS = ("approve", "reject", "wrong_person", "wrong_answer", "ask_helper", "book_1_1", "do_it", "autopilot")
PHRASES = {
    "wrong_person": {"wrong person", "not the right person", "wrong person, try someone else", "someone else please"},
    "wrong_answer": {"this looks wrong", "that looks wrong", "looks wrong", "that's wrong", "thats wrong", "this is wrong", "that's outdated"},
    "ask_helper": {"ask someone", "ask a person", "i'm still stuck", "still stuck"},
    "book_1_1": {"book a 1:1", "schedule a 1:1", "book a meeting"},
    "friction_map": {"friction map", "show the friction map"},
    "status": {"status", "any update", "any updates"},
    "do_it": {"do it", "do it for me", "yes do it", "please do it", "yes, do it", "go for it"},
    "my_actions": {"what have you done", "what have you done for me", "my actions", "done for me", "what did you do"},
}


def _guardian_log(issues: list[str], to_name: str) -> None:
    if issues:
        activity.log("orchestrator", f"Guardian blocked the draft to {to_name}: " + "; ".join(issues), kind="block")
    else:
        activity.log("orchestrator", f"Drafted a message to {to_name}; Guardian checked it: clear. Waiting for your approval", kind="check")


def _command(text: str, selection: dict, has_pending: bool = False) -> str:
    action = str(selection.get("action", "")).lower().removeprefix("ub_")
    if action:
        return action
    t = text.lower().strip().rstrip(".!")
    if t in APPROVE:
        return "approve"
    if t in REJECT:
        return "reject"
    if t.startswith("edit:"):
        return "edit"
    if t in GREETINGS:
        return "intro"
    for key, phrases in PHRASES.items():
        if t in phrases:
            return key
    # Planner-routed card clicks arrive as a sentence that mentions the selection id.
    m = re.search(r"\bub_(" + "|".join(ACTIONS) + r")\b", t)
    if m:
        return m.group(1)
    return ""


class Orchestrator:
    def __init__(self, services, store, llm_factory):
        self.s = services
        self.store = store
        self.llm_factory = llm_factory

    # ---------- helpers ----------
    def _user(self) -> dict:
        return load_user()

    async def _draft(self, purpose: str, recipient: dict, facts: list[str], question: str, ask: str = "") -> tuple[dict, str]:
        """purpose instructs the model; ask is the first-person line the no-model template uses."""
        user = self._user()
        try:
            llm = self.llm_factory()
            if getattr(llm, "mode", "") == "extractive":
                return llm.draft(ask or purpose, user, recipient, facts, question), ""
            return await asyncio.to_thread(llm.draft, purpose, user, recipient, facts, question), ""
        except LLMError as exc:
            return ExtractiveLLM().draft(ask or purpose, user, recipient, facts, question), f"\n(Template draft: the model is unavailable: {exc})"

    def _pending(self, kind: str, person: dict, draft: dict) -> dict:
        p = {"type": kind, "to_id": person["id"] if "id" in person else person.get("person_id", ""),
             "to_name": person["name"], "to_role": person["role"], "to_email": person["email"],
             "subject": str(draft.get("subject", "Question from a new hire"))[:120], "body": str(draft.get("body", ""))[:1500]}
        p["guardian"] = check_draft(p["subject"], p["body"])
        _guardian_log(p["guardian"], p["to_name"])
        return p

    def _review(self, state: dict, prefix: str = "") -> Reply:
        p = state["pending"]
        if p["type"] in ACTION_TYPES:
            if p.get("guardian"):
                prefix = (prefix + "\n\n" if prefix else "") + render.guardian_text(p["guardian"])
            return Reply((prefix + "\n\n" + render.system_text(p)).strip(), "review", render.system_card(p))
        if p.get("guardian"):
            prefix = (prefix + "\n\n" if prefix else "") + render.guardian_text(p["guardian"])
        text = render.action_text(p, state.get("answer"), state.get("helper"), state.get("rotation_note", ""))
        return Reply((prefix + "\n\n" + text).strip(), "review", render.action_card(p, state.get("answer"), state.get("helper")))

    async def _route(self, sender: str, state: dict, exclude: list[str] | None = None) -> Reply:
        user = self._user()
        answer = state.get("answer") or {}
        routing = await self.s.routing(state["question"], user, answer.get("retrieved_doc_ids", []), exclude or [])
        chosen = routing.get("chosen")
        if not chosen:
            return Reply("I couldn't find anyone who clearly owns this. Try posting in #ask-people-ops; I didn't send anything.")
        people = load_people()
        person = dict(people[chosen["person_id"]])
        helper = {"person_id": chosen["person_id"], "name": chosen["name"], "role": chosen["role"], "reasons": chosen["reasons"]}
        facts = [c["text"] for c in answer.get("claims", [])]
        draft, note = await self._draft("Ask this person for help because the docs don't clearly answer the question. Mention what was already found, if anything.",
                                         person, facts, state["question"], ask="I couldn't find a clear answer in our docs and would really appreciate your help.")
        state.update(helper=helper, topic_key=routing.get("topic_key", ""), rotation_note=routing.get("rotation_note", ""),
                     excluded=list(exclude or []), pending=self._pending("message_helper", person, draft))
        self.store.set(sender, state)
        return self._review(state, note.strip())

    # ---------- entry points ----------
    async def handle(self, sender: str, text: str, selection: dict | None = None) -> Reply:
        selection = selection or {}
        state = self.store.get(sender) or {}
        cmd = _command(text, selection, has_pending=bool(state.get("pending")))

        if cmd == "intro" or (not text and not selection):
            return Reply(INTRO)
        if cmd == "friction_map":
            fmap = await self.s.friction_map()
            return Reply(render.friction_text(fmap) + "\n\nPeople Ops can buy the full report with fix proposals from the TeamReady Insights agent.")
        if cmd == "autopilot" or autopilot.AUTOPILOT.match(text.strip().rstrip(".!")):
            return self._autopilot(sender, state)
        if cmd == "my_actions":
            recs = autopilot.records(sender)
            if not recs:
                return Reply("I haven't done anything for you yet. Try **do my checklist**, or ask me to join your Slack channels.")
            return Reply("Here's what I've done for you:\n" + "\n".join(
                f"- **{r['id']}** {r['title']} ({r['system']}): {r['status']}" for r in recs[-10:]))
        if cmd == "do_it" and state.get("offer") and not state.get("pending"):
            return self._propose(sender, state, state.pop("offer"), "")
        if cmd == "status":
            waiting = state.get("awaiting")
            if waiting:
                return Reply(f"Your request {waiting['request_id']} is waiting for {waiting['approver']}.")
            return Reply(state.get("last_decision") or "Nothing is waiting on anyone right now.")

        pending = state.get("pending")
        if cmd == "approve" and pending:
            if pending.get("guardian"):
                fix = ("Reply **reject**, then ask again without that detail." if pending["type"] in ACTION_TYPES
                       else "Reply **edit: <new message>** or **reject**.")
                return Reply(render.guardian_text(pending["guardian"]) + f"\n\nNothing was sent. {fix}")
            if pending["type"] in ACTION_TYPES:
                return await self._do(sender, state, state.pop("pending"))
            return await self._execute(sender, state)
        if cmd == "reject" and pending:
            state.pop("pending", None)
            self.store.set(sender, state)
            return Reply("Okay, I discarded the draft. Nothing was sent.")
        if cmd == "edit" and pending and pending["type"] in ACTION_TYPES:
            return Reply("This is an action, not a message, so there's nothing to edit. Reply **approve** or **reject**.")
        if cmd == "edit" and pending:
            new_body = re.sub(r"^\s*edit:\s*", "", text, flags=re.I).strip()
            if new_body:
                pending["body"] = new_body
                pending["guardian"] = check_draft(pending["subject"], new_body)
                _guardian_log(pending["guardian"], pending["to_name"])
                self.store.set(sender, state)
            return self._review(state, "Updated your draft." + ("" if pending.get("guardian") else " Guardian checked it: clear to send."))
        if cmd == "wrong_person" and state.get("helper"):
            helper = state["helper"]
            await self.s.wrong_person(helper["person_id"], state.get("topic_key", ""))
            exclude = state.get("excluded", []) + [helper["person_id"]]
            reply = await self._route(sender, state, exclude)
            reply.text = f"Thanks, I noted that {helper['name']} isn't the right person for this and updated the ranking.\n\n" + reply.text
            return reply
        if cmd == "ask_helper" and state.get("question"):
            return await self._route(sender, state)
        if cmd == "book_1_1" and state.get("helper"):
            person = load_people()[state["helper"]["person_id"]]
            draft, note = await self._draft("Ask for a 30-minute 1:1 to get unblocked on the question.", person, [], state["question"],
                                             ask="Could we do a quick 30-minute 1:1 this week? I've sent a calendar invite.")
            state["pending"] = self._pending("book_1_1", person, draft)
            self.store.set(sender, state)
            return self._review(state, note)
        if cmd == "wrong_answer" and state.get("answer"):
            return await self._wrong_answer(sender, state)
        if cmd in ("approve", "reject", "edit", "wrong_person", "ask_helper", "book_1_1", "wrong_answer", "do_it"):
            return Reply("There's nothing waiting for that right now. Ask me a question to get started.")

        if workday_mcp.enabled() and assess(text).level != "stop":
            found = workday_mcp.intent(text)
            if found:
                reply = await self._workday(sender, state, text, found)
                if reply:
                    return reply
        wanted = autopilot.detect(text)
        if wanted and assess(text).level == "routine":
            return self._propose(sender, state, wanted, text)
        return await self._new_question(sender, text)

    # ---------- doing things ----------
    def _propose(self, sender: str, state: dict, action: str, text: str) -> Reply:
        """Fill the form for one action and show it. Nothing happens until the new hire approves."""
        user = self._user()
        if action in autopilot.done_actions(sender) and action != "it_ticket":
            return Reply(f"Already done: {autopilot.ACTIONS[action]['title'].lower()}. Say **what have you done** to see it.")
        if autopilot.ACTIONS[action]["gate"] == "manager":
            return Reply("Analytics access needs your manager's approval first. Say **I need access to the analytics dashboard** "
                         "and I'll prepare the request; I file the form the moment they approve.")
        form = autopilot.build(action, user, text)
        spec = autopilot.ACTIONS[action]
        p = {"type": "system_action", "action": action, "form": form, "system": spec["system"], "title": spec["title"],
             "does": autopilot.describe(action, form), "to_name": spec["system"], "to_role": "Lumen system",
             "subject": spec["title"], "body": autopilot.describe(action, form), "guardian": autopilot.guardian(form)}
        activity.log("orchestrator", f"Can do this: {spec['title']} ({spec['system']}). Waiting for your approval", kind="check")
        state = {**state, "pending": p}
        self.store.set(sender, state)
        return self._review(state)

    def _autopilot(self, sender: str, state: dict) -> Reply:
        """Plan the whole onboarding checklist: what TeamReady will do now, what needs the manager, what it can't do."""
        from .portal import checklist
        plan = autopilot.plan_checklist(checklist(), self._user(), sender, waiting=bool(state.get("awaiting")))
        todo = [x for x in plan if x["status"] in ("will_do", "manager")]
        activity.log("orchestrator", f"Autopilot: {len(todo)} of {len(plan)} checklist steps TeamReady can do", kind="step")
        if not todo:
            return Reply("Nothing left on your checklist that I can do. " + autopilot.plan_text(plan).split("\n\n")[0])
        p = {"type": "system_batch", "plan": plan, "to_name": "your checklist", "to_role": "Lumen systems",
             "subject": "Onboarding checklist autopilot", "body": autopilot.plan_text(plan), "guardian": []}
        state = {**state, "pending": p}
        self.store.set(sender, state)
        return self._review(state)

    async def _workday(self, sender: str, state: dict, text: str, found: tuple) -> Reply | None:
        """Read from or act in the new hire's Workday tenant through its Agent-Ready MCP tools. None = fall back."""
        import asyncio
        name, words, goal = found
        user = self._user()
        activity.log("orchestrator", f"Workday: {goal.lower()}", to="systems", kind="message")
        try:
            candidates = await asyncio.to_thread(workday_mcp.shortlist, words)
            if not candidates:
                raise LLMError("no matching Workday tool is registered for TeamReady")
            plan = await asyncio.to_thread(workday_mcp.plan, goal, text, user, candidates, self.llm_factory())
        except Exception as exc:
            activity.log("systems", f"Workday unavailable ({str(exc)[:80]}); answering from the docs instead", kind="block")
            return None
        if plan["read"]:
            try:
                result = await asyncio.to_thread(workday_mcp.call, plan["tool"], plan["arguments"])
            except Exception as exc:
                activity.log("systems", f"Workday {plan['title']} failed: {str(exc)[:80]}", kind="block")
                return None
            answer = await asyncio.to_thread(workday_mcp.summarize, result, goal, self.llm_factory())
            activity.log("systems", f"Workday {plan['title']}: read, nothing changed", to="orchestrator", kind="done")
            return Reply(f"**From Workday:** {answer}\n\nRead live from your Workday tenant with the *{plan['title']}* tool, "
                         "as you. Nothing was changed.")
        import json as _json
        p = {"type": "workday_action", "tool": plan["tool"], "form": plan["arguments"], "title": plan["title"],
             "system": "Workday", "does": plan["explain"] or f"Run {plan['title']} in Workday.", "to_name": "Workday",
             "to_role": "your tenant", "subject": plan["title"], "body": plan["explain"],
             "guardian": check_draft("", _json.dumps(plan["arguments"]))}
        p["form"] = {**p["form"], "why": "Workday Agent-Ready MCP tool; Workday's own approvals still apply"}
        activity.log("orchestrator", f"Can do this in Workday: {plan['title']}. Waiting for your approval", kind="check")
        state = {**state, "pending": p}
        self.store.set(sender, state)
        return self._review(state)

    async def _do(self, sender: str, state: dict, p: dict) -> Reply:
        import asyncio
        user = self._user()
        if p["type"] == "workday_action":
            args = {k: v for k, v in p["form"].items() if k != "why"}
            try:
                result = await asyncio.to_thread(workday_mcp.call, p["tool"], args)
            except Exception as exc:
                self.store.set(sender, state)
                return Reply(f"**Not done.** Workday didn't accept it: {str(exc)[:300]}. Nothing else changed.")
            answer = await asyncio.to_thread(workday_mcp.summarize, result, p["title"], self.llm_factory())
            rec = autopilot.log_record("workday", p["title"], "Workday", "submitted", answer, sender, args)
            self.store.set(sender, state)
            return Reply(f"**Done in Workday: {rec['id']}.** {answer}\n\nWorkday's own approvals (for example your manager "
                         "for time off) still apply.")
        if p["type"] == "system_action":
            rec = await asyncio.to_thread(autopilot.execute, p["action"], p["form"], user, sender)
            self.store.set(sender, state)
            if p["action"] == "it_ticket":
                await self.s.track(rec["id"], sender, "it_ticket", p["form"]["description"][:100], "IT Support", "it-help@lumen.example")
            return Reply(f"**Done: {rec['id']}.** {rec['detail']}\n\nSay **what have you done** any time to see everything I did for you.")
        lines, access = [], None
        done = autopilot.done_actions(sender)  # the plan may be stale: skip whatever got done since it was shown
        for item in p["plan"]:
            if item.get("action") in done:
                continue
            if item["status"] == "will_do":
                rec = await asyncio.to_thread(autopilot.execute, item["action"], item["form"], user, sender)
                lines.append(f"- **{rec['id']}** {rec['detail']}")
            elif item["status"] == "manager" and not state.get("awaiting"):
                access = item
        self.store.set(sender, state)
        text = "**Done.**\n" + "\n".join(lines) if lines else "Nothing new to do: it was already done."
        if access:
            manager = dict(load_people()[user["manager_id"]])
            draft, _ = await self._draft(f"Ask my manager to approve Analytics Workspace access for my work on {', '.join(user['projects'])}.",
                                         manager, [access["form"]["why"]], "I need access to the analytics dashboard",
                                         ask=f"Could you approve my analytics access request? I need it for {', '.join(user['projects'])}.")
            # The manager message is a message, so the new hire reviews it (and the Guardian checks it) before it goes.
            state.update(risk={"category": "analytics access"}, answer={}, helper=None,
                         pending=self._pending("access_request", manager, draft))
            self.store.set(sender, state)
            return self._review(state, text + "\n\nLast one: analytics access needs your manager. Here's the request; "
                                       "I file the go/analytics-access form the moment they approve.")
        return Reply(text.strip())

    async def _new_question(self, sender: str, question: str) -> Reply:
        user = self._user()
        people = load_people()
        risk = assess(question)
        if risk.level == "stop":
            activity.log("orchestrator", f"Risk gate stopped it: {risk.category}. No search, no draft; handing it to a person", kind="block")
        elif risk.level == "approval":
            activity.log("orchestrator", f"Risk gate: {risk.category} needs the manager's approval", kind="step")
        else:
            activity.log("orchestrator", "Risk gate: safe to answer from the docs", kind="check")
        if risk.level == "stop":
            previous = self.store.get(sender) or {}
            self.store.set(sender, {k: previous[k] for k in ("awaiting", "last_decision") if k in previous})
            human = people[risk.human_id]
            text = render.stop_text(risk.__dict__, human)
            return Reply(text, "detail", {"title": "This needs a person", "summary_rows": [
                {"label": "Category", "value": risk.category}, {"label": "Why I stopped", "value": risk.reason},
                {"label": "What I did", "value": "Stopped before searching, choosing anyone, or drafting"},
                {"label": "Right person", "value": f"{human['name']}, {human['role']}"}], "ctas": []}, terminal=True)

        answer = await self.s.knowledge(question, user)
        previous = self.store.get(sender) or {}
        state = {"question": question, "answer": answer, "risk": risk.__dict__,
                 **{k: previous[k] for k in ("awaiting", "last_decision") if k in previous}}

        if risk.level == "approval":
            manager = dict(people[user["manager_id"]])
            facts = [c["text"] for c in answer.get("claims", [])]
            purpose = (f"Ask my manager to approve {risk.category} for my work on {', '.join(user['projects'])}. "
                       "Explain the business reason briefly.")
            draft, note = await self._draft(purpose, manager, facts, question,
                                            ask=f"Could you approve my {risk.category} request? I need it for {', '.join(user['projects'])}.")
            state["pending"] = self._pending("access_request", manager, draft)
            state["helper"] = None
            self.store.set(sender, state)
            return self._review(state, f"**{risk.reason}**{note}")

        if answer.get("decision") == "answer":
            routing = await self.s.routing(question, user, answer.get("retrieved_doc_ids", []), [])
            chosen = routing.get("chosen")
            helper = {"person_id": chosen["person_id"], "name": chosen["name"], "role": chosen["role"], "reasons": chosen["reasons"]} if chosen else None
            state.update(helper=helper, topic_key=routing.get("topic_key", ""), rotation_note=routing.get("rotation_note", ""))
            text = render.answer_text(answer)
            stale = [c for c in answer.get("conflicts", []) if c.get("type") == "stale doc"]
            if stale:
                owner = people[stale[0]["owner_id"]]
                stale_title = render.doc_title(stale[0]["stale_doc_id"])
                note_draft, _ = await self._draft(f"Let the doc owner know '{stale_title}' looks out of date and points new hires to an old process.",
                                                  owner, [stale[0]["description"]], question,
                                                  ask=f"I think '{stale_title}' is out of date: it describes a different process than the current docs. Could you update or archive it?")
                state["pending"] = self._pending("doc_owner_note", owner, note_draft)
                text += (f"\n\nWant me to tell {owner['name']} (the owner) that the old doc is out of date? "
                         "Reply **approve** to send the note I drafted, or **reject**.")
            offer = "" if stale else autopilot.offer_for(answer)
            if offer and offer not in autopilot.done_actions(sender):
                does = autopilot.describe(offer, autopilot.build(offer, user))
                state["offer"] = offer
                text += f"\n\n**Want me to do it?** I can {does[0].lower() + does[1:]} Reply **do it** and I'll show you first."
            self.store.set(sender, state)
            await self.s.friction_event(answer["retrieved_doc_ids"][0] if answer.get("retrieved_doc_ids") else "", answer.get("retrieved_doc_ids", [])[:1], True)
            if stale:
                return Reply(text, "review", render.action_card(state["pending"], answer, helper))
            card = render.answer_card(answer, helper)
            if state.get("offer"):
                card["ctas"].insert(0, {"label": "Do it for me", "primary": True, "selection": {"action": "ub_do_it"}})
            return Reply(text, "detail", card)

        self.store.set(sender, state)
        return await self._route(sender, state)

    async def _wrong_answer(self, sender: str, state: dict) -> Reply:
        answer = state["answer"]
        cited = answer.get("citations", [])
        if not cited:
            return await self._route(sender, state)
        people = load_people()
        owner = dict(people[cited[0]["owner_id"]])
        draft, note = await self._draft(f"Flag that the answer from '{cited[0]['title']}' may be wrong or out of date and ask them to confirm.",
                                        owner, [c["text"] for c in answer.get("claims", [])], state["question"],
                                        ask=f"Something in '{cited[0]['title']}' doesn't seem to match what I'm seeing. Could you confirm it's still correct?")
        state["helper"] = {"person_id": owner["id"], "name": owner["name"], "role": owner["role"], "reasons": [f"owns {cited[0]['title']}"]}
        state["pending"] = self._pending("message_helper", owner, draft)
        self.store.set(sender, state)
        await self.s.source_feedback([c["id"] for c in cited])
        return self._review(state, f"Thanks for flagging it. I logged the source ids only, not your message.{note}")

    async def _execute(self, sender: str, state: dict) -> Reply:
        p = state.pop("pending")
        if p["type"] == "access_request":
            return await self._send_access_request(sender, state, p)
        return await self._send_message(sender, state, p)

    async def _send_access_request(self, sender: str, state: dict, p: dict) -> Reply:
        user = self._user()
        answer = state.get("answer") or {}
        request_id = "AR-" + uuid.uuid4().hex[:6].upper()
        evidence = [f"{c['text']} [{c['source_id']}]" for c in answer.get("claims", [])]
        status = await self.s.request_approval({
            "request_id": request_id, "category": state.get("risk", {}).get("category", "access"),
            "requester": {"name": user["name"], "role": user["role"], "team": user["team"], "email": user["email"]},
            "subject": p["subject"], "body": p["body"], "evidence": evidence, "sender": sender,
        })
        state["awaiting"] = {"request_id": request_id, "approver": p["to_name"]}
        self.store.set(sender, state)
        self.store.set(f"req:{request_id}", {"sender": sender, "category": state.get("risk", {}).get("category", "access")})
        await self.s.track(request_id, sender, "access_request", p["subject"], p["to_name"], p["to_email"])
        return Reply(f"Sent request **{request_id}** to {p['to_name']}'s approval agent. {status}\n"
                     "Only your manager can approve it. I'll message you here as soon as they decide.")

    async def _send_message(self, sender: str, state: dict, p: dict) -> Reply:
        user = self._user()
        answer = state.get("answer") or {}
        ics = None
        if p["type"] == "book_1_1":
            from .actions import make_ics, next_slot
            ics = make_ics(f"1:1: {user['name']} and {p['to_name']}", user["email"], p["to_email"], next_slot())
        result = await self.s.send_email(p["to_email"], p["subject"], p["body"], user["email"], ics)
        self.store.set(sender, state)
        if p["type"] in ("message_helper", "book_1_1"):
            doc = (answer.get("retrieved_doc_ids") or [""])[0]
            await self.s.friction_event(doc, answer.get("retrieved_doc_ids", [])[:1], False)
            if result["status"] in ("sent", "simulated"):
                await self.s.track("MS-" + uuid.uuid4().hex[:6].upper(), sender, p["type"],
                                   state.get("question") or p["subject"], p["to_name"], p["to_email"])
        label = {"sent": "Sent", "simulated": "Simulated (email not configured)", "failed": "Not sent"}[result["status"]]
        if result["status"] != "failed":
            result["detail"] += " The TeamReady Tracker will check back if there's no reply."
        follow = " Reply **wrong person** if they can't help, and I'll find someone else." if p["type"] == "message_helper" else ""
        return Reply(f"**{label}.** {result['detail']}{follow}")

    async def on_decision(self, decision: dict) -> tuple[str, Reply] | None:
        """Called when the manager agent sends back a decision."""
        sender = decision.get("sender") or (self.store.get(f"req:{decision['request_id']}") or {}).get("sender", "")
        if not sender:
            return None
        state = self.store.get(sender) or {}
        state.pop("awaiting", None)
        await self.s.track_resolved(decision["request_id"], decision["decision"])
        if decision["decision"] == "approved":
            text = f"**{decision.get('approver', 'Your manager')} approved request {decision['request_id']}.**"
            category = (self.store.get(f"req:{decision['request_id']}") or {}).get("category") or state.get("risk", {}).get("category", "")
            if category == "analytics access" and "analytics_access" not in autopilot.done_actions(sender):
                import asyncio
                rec = await asyncio.to_thread(autopilot.execute, "analytics_access", autopilot.build("analytics_access", self._user()),
                                              self._user(), sender, decision.get("approver", ""))
                text += f"\n\n**I filed it for you: {rec['id']}.** {rec['detail']}"
            claims = (state.get("answer") or {}).get("claims", [])
            if claims:
                text += "\n\nWhat happens next, from the docs:\n" + "\n".join(f"- {c['text']}  [{c['source_id']}]" for c in claims)
        else:
            text = f"**{decision.get('approver', 'Your manager')} didn't approve request {decision['request_id']}.**"
        if decision.get("note"):
            text += f"\n\nTheir note: {decision['note']}"
        state["last_decision"] = text  # also shown when the new hire asks for "status"
        self.store.set(sender, state)
        return sender, Reply(text)
