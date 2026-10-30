# Demo video script (2:45)

Devpost wants 2–3 minutes. This cut is 2:45, so there's room for a slow click.

**Tabs, in order:** `/workday` (fresh session: in the browser console run `localStorage.clear()` and reload) ·
ASI:One signed in as the new hire, chat with `teamready-orchestrator` open · `/canary` · `/activity` ·
the CREAO run link.

**Before recording:** agents running (`python scripts/run_agents.py`, seven "mailbox connected"); web app running;
send one throwaway question so nothing is cold; phone hotspot on if you want the 1:1 invite to arrive by real email.
Record at 1440×900 or larger, browser zoom 100%, notifications off.

| Time | Screen | Say |
| --- | --- | --- |
| 0:00 | `/workday` as Maya: hero, Awaiting Your Action, Onboarding Journey | "It's Maya's second week at Lumen Labs. Onboarding is six steps across five systems, the docs are a maze, and she doesn't know who to ask. This is TeamReady: seven AI agents that onboard her, can't make things up, and do the work for her." |
| 0:15 | Assistant: **"What's our deploy process for staging?"** Open *Sources and confidence* | "Every claim is checked word for word against an approved doc, with the doc's date and owner. The old runbook is two years stale, so TeamReady leaves it out and offers to tell its owner." |
| 0:35 | **"How many vacation days do I get?"** | "The docs don't say. Most assistants would guess. TeamReady won't: on our eval it answered zero of five trick questions. It finds the right person and drafts the message for her." |
| 0:50 | Awaiting Your Action → **Review the plan**, then **Approve and do them** in the assistant. Show the journey turning green and Done for You filling | "Now what a chatbot can't do. TeamReady plans her checklist: it joins her Slack channels, enrolls her in training and books her 1:1 with a real calendar invite. Guardian checks every step. It won't touch MFA, and analytics access needs her manager." |
| 1:15 | Approve the message to the manager. Switch to **Jordan** in the top bar → **Approve**. Back to **Maya**: the access form is in Done for You | "Only Jordan, a person, can approve access. The moment Jordan does, TeamReady files the form for her. Nothing happened without a yes." |
| 1:35 | ASI:One: message `teamready-orchestrator` "my laptop screen is cracked" → approve the card. Glance at `/activity` | "The same agents run on Fetch.ai's Agentverse, so Maya can do all of this from ASI:One too. Here it opens an IT ticket, and you can watch the agents talk to each other live." |
| 1:55 | Switch to **Elena** → Where New Hires Get Stuck. Then `/canary` → **Run the canaries** | "For People Ops, here's the twist. Before real hires start, three synthetic new hires go through onboarding with only the docs." |
| 2:10 | Point at the walls: detour (13 reported), stale runbook (10), two not reported yet | "They hit the same walls real new hires hit, plus two nobody has reported yet." |
| 2:20 | Doc fix → CREAO run link on agent.creao.ai | "For each wall, CREAO's Doc Steward drafts the fix. We check it quotes the doc exactly, and the doc owner decides. New hires stop being your QA team." |
| 2:35 | Back to `/workday`, scroll to How TeamReady Works | "Seven agents, Sonnet behind a verifier, 39 or 40 out of 40 on our eval, and a person approving every action. That's TeamReady." |

## If ASI:One is slow on the day

Skip the 1:35 row and say the line over `/activity` instead. Everything else runs in the web app.

## Things to say if asked
- **"Is it acting on real systems?"** The company is fictional, so Slack, the Learning Hub, the calendar, IT Help and the
  Access Hub are demo adapters behind one action call. The calendar invite is a real email. Swapping in the Slack,
  LMS, calendar or ServiceNow API changes only the adapter.
- **"Where's the AI?"** Sonnet reasons and drafts; plain code verifies, gates and acts. The CREAO Doc Steward drafts the
  doc fixes.
- **"Is it connected to Workday?"** There's a REST connector for the profile and an MCP client for Workday's
  Agent-Ready tools. Our sandbox tenant was down during the event, so the demo uses a local profile, and the page says so.
