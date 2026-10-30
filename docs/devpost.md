# TeamReady: Devpost submission

**Tagline:** An onboarding agent network that does the work for new hires, can't make things up, and tests your docs
with synthetic new hires before real people start.

**Tracks:** Workday "Build the Future of Work with AI" · Fetch.ai ASI:One Agent Challenge · CREAO Best Team Empowerment

**Links:** GitHub https://github.com/SreenijaPavuluri/teamready · Demo video VIDEO-LINK · Live site LIVE-LINK (`/workday`,
`/canary`, `/activity`) · CREAO run https://agent.creao.ai/share/0773babf9c5d456f0fc0446a58d6da2f · ASI:One: message
`teamready-orchestrator` (addresses in the README)

## Project description (short)

TeamReady is a network of seven Fetch.ai agents that onboards new hires. It answers only from approved company docs and
checks every claim word for word, so it can't make things up. It also does the onboarding work: it joins Slack channels,
enrolls the new hire in training, books the first 1:1 and files the access request once the manager approves. Every
action runs only after a person approves it. For People Ops, **Canary New Hires** send synthetic new hires through the
docs before real people start, find where they get stuck, and have a CREAO agent draft the fix for the doc owner.
For Workday's challenge, it's an AI teammate for the first 90 days that is transparent, keeps people in control, and
turns blockers into fixable patterns. For Fetch.ai, it's seven Agentverse agents with the Chat Protocol, usable in
ASI:One, with a human-approval agent and the Payment Protocol. For CREAO, the Doc Steward agent does the core of the
doc-fix loop.

---

## Inspiration

Your first weeks at a job are a maze of small blockers: which form, which channel, who owns the dashboard, is this doc
still right? New hires lose days to questions nobody has answered for them. They interrupt the same busy senior people,
and they hit the same walls the last cohort hit. AI assistants over internal docs make it worse when they invent a
confident answer: a new hire can't tell a real answer from a made-up one.

We wanted an onboarding buddy that (1) only says what it can prove, (2) actually does the work instead of handing you a
to-do list, and (3) stops the same walls from hitting the next person.

## What it does

**For the new hire (in ASI:One, or the web portal):**
- **Verified answers.** Every claim is checked word for word against an approved company doc before the new hire sees
  it. Stale docs are flagged and left out. If the docs don't answer, TeamReady doesn't guess: it finds the right person,
  with a visible, fair score, and drafts the message.
- **It does the work.** "Do my checklist" makes TeamReady plan the whole onboarding checklist. It joins the right Slack
  channels, enrolls the new hire in required training, books the first 1:1 with the manager (with a calendar invite)
  and opens IT tickets. For analytics access it drafts the request to the manager and **files the access form the
  moment the manager approves**. It says plainly what it won't do: MFA and passwords, and in-person IT setup. Every
  action shows exactly what will happen and runs only after the new hire approves.
- **Safety by design.** A risk gate runs before any model call: pay, performance, benefits eligibility and harassment
  questions go straight to a named person. A Guardian check stops any draft or form that contains a password, an ID
  number or health details. Only a human manager can approve access.
- **Follow-up.** A Tracker agent notices when nobody replied and offers a polite reminder (sent only after approval).

**For People Ops and doc owners:**
- **Friction Map:** anonymous patterns of what keeps blocking new hires (topics and doc paths only, groups of 5+), sold
  as a full report through the Fetch.ai Payment Protocol.
- **Canary New Hires:** three synthetic new hires (a Data Analyst, a Backend Engineer, a Product Designer in the EU) walk
  the onboarding docs through the same verified-answer pipeline, step by step, before real people start. They find the
  walls (a checklist step with no how-to, a stale runbook that still comes up, a missing doc for one office) and check
  each one against the Friction Map: confirmed by real new hires, or predicted. On our synthetic company they rediscover
  the two walls real hires hit most (13 and 10 blockers) and predict two that nobody has reported yet.
- **Doc fixes, drafted by CREAO.** For each wall, the CREAO Doc Steward drafts a one-line fix. TeamReady checks that it
  quotes the doc word for word, and the doc owner (a person) decides.

## How we built it

- **Seven Fetch.ai uAgents on Agentverse** (Chat Protocol, mailbox mode, ASI:One): `teamready-orchestrator` (front door,
  risk gate, Guardian, actions), `teamready-knowledge` (search + Sonnet + verifier), `teamready-routing` (who to ask),
  `teamready-manager` (the human approval gate), `teamready-insights` (Friction Map + Payment Protocol), `teamready-tracker`
  (follow-ups) and `teamready-canary` (Canary New Hires). They exchange typed messages (knowledge, routing, approval and
  tracking requests). Interactive Cards carry the review, approve and reject buttons. If a specialist doesn't answer in
  time, the orchestrator runs the same step locally and says so.
- **Anthropic's Sonnet model** drafts claims with quotes; **plain Python decides** what's shown (the verifier checks
  quote presence, negation, word overlap and numbers). Confidence is computed in code from four visible factors.
- **CREAO:** the Doc Steward agent (API Trigger, async polling) drafts doc fixes for the Friction Map and the canaries.
  A Weekly Digest agent posts each doc owner's top gap to Notion.
- **Web app (FastAPI):** a New Hire Portal with the same conversation, a manager tab and a "Done for you" panel; the
  Canary New Hires page; and Agent Activity, a live map of every message between the agents.
- **Workday:** a REST connector reads the new hire's name, title, organization and work email from a Workday Build
  development tenant (only those four fields), and an MCP client is ready for Workday's Agent-Ready tools (time off
  balances, onboarding tasks, learning; anything that writes needs approval). Our sandbox tenant's token endpoint was
  returning errors during the event, so the demo runs on a local fallback profile and says so.
- **Web view (`/workday`):** a Workday-style worker home for three people: Maya (new hire), Jordan (manager), Elena
  (People Ops).
- 104 automated tests, a 40-question eval, Docker deploy.

## Challenges we ran into

- **Making "refuse to guess" measurable.** The extractive baseline "answered" all 5 adversarial questions with
  irrelevant quotes. With Sonnet behind the verifier, it answers none of them.
- **Model answers vary run to run, but the canaries must not.** Each checklist step is asked once and shared across
  canaries. When a canary rephrases, it judges the result on what the search found, which is deterministic. Four runs
  in a row give the same walls.
- **Agentverse mailboxes:** running all agents in one process left only some of them reachable. We moved to one process
  per agent, with a launcher that checks and retries every mailbox.
- **An SDK change mid-hackathon:** the current Anthropic SDK rejects `temperature` for the newest models, which silently
  routed every question to a person until we caught it in the eval.

## Accomplishments we're proud of

- **Eval with Sonnet: 39–40/40 behavior across three runs, 0/5 adversarial questions answered in every run**, 2 unsupported claims
  blocked by the verifier and 0 shown to the user.
- An agent that does onboarding tasks end to end, including a manager-gated step, without ever acting on its own.
- Canary New Hires found real walls with no knowledge of the Friction Map.

## What we learned

The interesting part of an onboarding agent isn't the answer, it's the judgment around it: when not to answer, who
should decide, what to do on the new hire's behalf, and how to make the next person's first week easier.

## What's next

Real connectors behind the same action calls (Slack, the LMS, Google/Outlook calendar, ServiceNow, Workday time off),
canaries for every role and office, and measuring time-to-first-commit for new hires before and after.

---

## Sponsor tracks

**Fetch.ai: ASI:One Agent Challenge.** Seven uAgents registered on Agentverse in mailbox mode with the Chat Protocol,
usable from ASI:One. The orchestrator coordinates the knowledge, routing, manager and tracker agents with typed
messages. The manager agent is a human approval gate (only the configured manager's address can approve). The canary
agent sends synthetic new hires through the knowledge agent. Interactive Cards for every review. The insights agent
sells its full report through the Payment Protocol (FET). Try `teamready-orchestrator` with "do my checklist", or
`teamready-canary` with "run". Agent addresses are in the README.

**Workday: Build the Future of Work with AI.** A new-hire agent built on Workday's responsible-AI principles: every
claim cited and verified, approve-before-act on every action, a human manager for access, and high-impact topics handed
to a person. It has a Workday REST connector (four profile fields only) and a client for Workday's Agent-Ready MCP
tools; the demo uses a local fallback profile because our sandbox tenant was unavailable. For People Ops, the Friction
Map and Canary New Hires turn individual blockers into fixable patterns, and doc owners stay in control. The `/workday`
view puts all of it in a Workday-style worker home: Awaiting Your Action, an Onboarding Journey that TeamReady completes,
Done for You (process history), Grow at Lumen Labs (learning budget, mentorship and internal moves, answered from approved docs), the manager's approval inbox, People Ops onboarding health, and a "How TeamReady Works"
card that answers each "Design for Trust" question.

**CREAO: Best Team Empowerment.** The CREAO Doc Steward (agent ID `b450ed0d-985d-4079-917f-d9f9ee75e812`) does the core
work of the doc-fix loop. Our backend calls it through the API Trigger, polls the run, and checks its reply quotes the
doc exactly. The doc owner, a person, approves. A second CREAO agent, the Weekly Digest, posts each doc owner's top gap
to Notion. Remove the Doc Steward and the docs never get fixed. Run:
https://agent.creao.ai/share/0773babf9c5d456f0fc0446a58d6da2f

**ElevenLabs (MLH).** New hires can talk to TeamReady: the ElevenLabs voice agent calls our `/api/voice/ask` webhook, which runs the same risk gate and word-for-word verifier, and reads back only the verified answer. The voice widget is on the Workday view and the portal.

**Tiger Data (MLH).** The Friction Map stores blocker events in TimescaleDB on Tiger Data with a continuous aggregate,
and falls back to local files if the database isn't reachable.
<!-- Add Vultr / GoDaddy only if the site is deployed there at submission. -->

## Built with

Python · ElevenLabs Conversational AI · Fetch.ai uAgents · Agentverse · ASI:One · Chat Protocol · Payment Protocol · Anthropic Sonnet · CREAO ·
FastAPI · TimescaleDB (Tiger Data) · Workday REST API · Model Context Protocol · Gmail SMTP · Docker · HTML/CSS/JS

**Team:** Sreenija (integration, autopilot actions, Canary New Hires, web app, go-live), Lux (Fetch.ai agents on
Agentverse, mailbox launcher, ASI:One fixes), Kusum (CREAO Doc Steward and Weekly Digest), Raj (Workday tenant, Tiger
Data, email). <!-- adjust names and roles -->
