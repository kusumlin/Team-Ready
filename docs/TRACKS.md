# Tracks: what each one asks for, where TeamReady meets it, and what you must do by hand

Status key: **Built and tested** means code plus automated tests in this repo. **Needs your account** means the code is ready but only your keys or clicks can switch it on. Nothing here could be tested against the real sponsor service from the build environment, so test each one live once.

## Main targets (recruiters on site)

### Workday: Build the Future of Work with AI
| What they score | Where TeamReady meets it |
| --- | --- |
| Agentic logic and AI innovation (30%) | Intent classification, risk gate, verified retrieval, helper routing, drafted actions, manager approval, feedback learning (`unblock/flow.py`) |
| New hire relevance (20%) | Built around a new hire's first 90 days (Maya, data analyst) |
| Responsible AI and trust (20%) | Verifier, trust panel on every answer, approve/edit/reject, high-impact stop, privacy limits; table in README |
| Future of work (15%) | Friction Map turns individual blockers into fixable org patterns; fair helper rotation |
| UX and inclusivity (10%) | Plain-language onboarding-buddy tone, web demo, voice option, works without cards |
| Pitch (5%) | 3-minute script in README |

**Built on Workday's own platform:** with a free Workday Build development tenant, TeamReady reads the new hire's name, title, organization and work email from Workday (the system of record), and nothing else. Setup: [`docs/WORKDAY.md`](WORKDAY.md), about 15 minutes. Code: `unblock/workday.py`, tested against a fake tenant; **test it live**.

**You must:** create the dev tenant and API client; present it; say exactly which parts each teammate built (their recruiters asked for this).

### Fetch.ai: ASI:One Agent Challenge
| Requirement | Status |
| --- | --- |
| Agent(s) registered on Agentverse | Needs your account: `AGENTVERSE_API_KEY`, run agents, connect each mailbox |
| Chat Protocol | Built and tested (all five agents) |
| Discoverable and usable in ASI:One, whole workflow in chat | Built; **test in ASI:One yourself** |
| Meaningful multi-agent orchestration | Built and tested: 6 agents (orchestrator, knowledge, routing, manager, insights, tracker), real messages, local fallback |
| Public GitHub repo with run steps | Needs you: push the repo, make it public |
| Submission Agent + Devpost | Needs you |
| Bonus: Payment Protocol | Built and tested locally (FET); test a real ASI:One wallet payment |
| Bonus: Interactive Cards | Built; **check they render in ASI:One** |
| Bonus: reliability | Built and tested: fallbacks, clear errors, payment cancels on failure |

## CREAO: Best Team Empowerment

| Requirement | Status |
| --- | --- |
| A CREAO agent does the core work | Built: the Doc Steward drafts every doc fix (`unblock/creao.py`, `agents/insights_agent.py`), tested with a stubbed API |
| Agent built on agent.creao.ai | Needs you: paste the instructions from `docs/CREAO.md` |
| README has the agent ID and a run share link | Needs you, after the first real run |
| Agent shown running in the demo | Needs you |
| Devpost: select the CREAO track | Needs you |

## MLH prizes

### Best use of Gemini
- **Where:** Gemini embeddings power hybrid retrieval (meaning + keywords), so "lunch with a customer" finds the expense policy with no shared keywords. Gemini is also a full drop-in reasoning model (`UNBLOCK_LLM=gemini`) behind the same verifier.
- **Story for judges:** "We ran the same 40-question eval with Sonnet and Gemini behind one verifier." Run `python eval/run_eval.py --llm gemini --embeddings gemini` and put both result tables in the README.
- **You must:** get a key at aistudio.google.com, set `GEMINI_API_KEY`, `UNBLOCK_EMBEDDINGS=gemini`. About 5 minutes.

### Snowflake REST API
- **Where:** `UNBLOCK_LLM=snowflake` runs every answer through Snowflake Cortex's chat completions REST API, still verified by our code.
- **You must:** create a Snowflake trial, enable Cortex for your region, create a programmatic access token, set `SNOWFLAKE_ACCOUNT` and `SNOWFLAKE_PAT`, then run `python eval/run_eval.py --llm snowflake`. About 15 minutes. Only enter if you run at least part of the demo on it.

### Tiger Data (TimescaleDB)
- **Where:** Friction Map events live in a hypertable; the 30-day view reads a continuous aggregate (`friction_daily`, 1-day buckets, refresh policy every 15 minutes, real-time for new events). Live events from the agents are inserted as they happen.
- **You must:** create a free Tiger Cloud service, set `TIMESCALE_URL`, run `python scripts/setup_timescale.py` (it prints "Schema ready on timescale"). About 10 minutes. The web page then says "Data from Tiger Data (TimescaleDB continuous aggregate)".

### ElevenLabs
- **Where:** a voice onboarding buddy. An ElevenLabs voice agent calls `POST /api/voice/ask`, which runs the same risk gate and verifier and returns only verified facts to speak. Setup in `docs/ELEVENLABS.md`.
- **You must:** deploy the web app with HTTPS first, then create the voice agent and its webhook tool. About 15 minutes. Weakest fit with the core product: cut it first if time is short.

### Vultr
- **Where:** `Dockerfile` + `docker-compose.yml` run the web app, the five agents and HTTPS (Caddy) on one Vultr server. Steps in `docs/DEPLOY.md`.
- **You must:** create the server, install Docker, copy the repo and `.env`, `docker compose up -d --build`. About 20 minutes.

### GoDaddy Registry
- **Where:** your domain points to the Vultr server; Caddy gets the HTTPS certificate automatically.
- **You must:** register the domain, add an A record to the server's IP, set `DOMAIN` in `.env`. About 5 minutes (plus DNS wait).

### Solana
- **Where:** People Ops can buy the Friction Map report in USDC with a Solana Pay link; the insights agent finds the transaction by its reference and confirms the USDC arrived before releasing the report.
- **You must:** set `SOLANA_RECIPIENT` to a devnet wallet, get devnet USDC from a faucet, pay once in Phantom (devnet) and say "check payment". About 15 minutes. A stretch fit: present it as "payments where People Ops already pays".

### DEV
- **Where:** `docs/dev_post.md` is a draft article. Publish it after the event and add your own numbers.

### MLH Commit Fellowship
- **You must:** opt in on the submission form and fill out the separate fellowship form, if you'd continue TeamReady as a startup.

## Order to do the manual steps (with about 22 hours left)
1. Anthropic + Agentverse keys, connect mailboxes, test the full flow in ASI:One (Fetch is the hiring prize).
2. Run the Sonnet eval; fix anything it shows.
2b. Workday dev tenant + API client (`docs/WORKDAY.md`); log in daily so it doesn't expire.
3. Gemini key + hybrid retrieval + Gemini eval (cheap and strong).
4. Tiger Cloud + setup script.
5. Vultr + GoDaddy + HTTPS.
6. ElevenLabs voice agent.
7. Snowflake, Solana: only if everything above works.
8. Record the video, push the public repo, submit on Devpost and the ASI:One Submission Agent.
