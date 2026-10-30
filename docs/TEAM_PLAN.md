# Team plan: Saturday 2:30pm → Sunday noon

The code is built and tested (73 tests). What's left is mostly accounts, keys, going live and the demo.
Four owners. Each person owns their part end to end and can explain it to judges.
Put your names in the brackets.

| Owner | Area | Tracks it wins | Code they explain |
| --- | --- | --- | --- |
| **A [   ]** Agents lead | 6 agents on Agentverse, the full ASI:One flow, cards, payment, manager account | Fetch.ai | `agents/`, `unblock/flow.py`, `unblock/chat.py` |
| **B [   ]** Infra lead | Vultr server, GoDaddy domain, Docker, HTTPS, email, Tiger Data | Vultr, GoDaddy, Tiger Data | `Dockerfile`, `docker-compose.yml`, `unblock/timeseries.py`, `unblock/actions.py` |
| **C [   ]** Integrations lead | CREAO Doc Steward + Weekly Digest, Workday dev tenant, ElevenLabs voice | CREAO, Workday (live data), ElevenLabs | `unblock/creao.py`, `unblock/workday.py`, `web/app.py` voice route |
| **D [   ]** AI quality + story | Sonnet eval, Gemini, responsible-AI story, README, Devpost, video, pitch | Workday (judging), Gemini, DEV | `unblock/verifier.py`, `unblock/confidence.py`, `unblock/risk.py`, `eval/` |

## Everyone, first 30 minutes

1. Clone the repo, run Phase 1 of `docs/GO_LIVE.md` with `UNBLOCK_LLM=extractive` (no keys needed):
   `pytest -q` → 73 passed, and `python scripts/local_demo.py` → ends with "Demo finished."
2. Read the output of `local_demo.py` once. It is the demo script.
3. **Only A's laptop runs agents with the real seeds.** Two copies with the same seeds fight over the mailboxes.

## A: Agents lead (Fetch.ai)

| By | Task | Done when |
| --- | --- | --- |
| 4:00pm | Anthropic + Agentverse keys in `.env`, six seeds generated (GO_LIVE Phase 1) | `.env` filled; shared with B over a private channel, never committed |
| 5:00pm | `./scripts/run_all.sh`; six mailboxes connected (Phase 2) | Six `teamready-…` agents on agentverse.ai with READMEs and badges |
| 7:00pm | Whole Phase 3 checklist in ASI:One | Every line ticked; screenshots of each card |
| 7:30pm | Second ASI:One account as the manager; set `MANAGER_ALLOWED_SENDERS` | Fake manager gets refused, real one approves |
| 8:00pm | Fix anything that broke in ASI:One (cards not rendering → `UNBLOCK_CARDS=false` is the fallback) | Send the bug list to the group |
| 11:00pm | After B deploys: stop local agents, re-test Phase 3 against the server | Same checklist passes live |
| Sun 9:00am | Fetch.ai **ASI:One Submission Agent** + addresses in README (`python scripts/addresses.py`) | Submission confirmed |

## B: Infra lead (Vultr, GoDaddy, Tiger Data)

| By | Task | Done when |
| --- | --- | --- |
| 4:00pm | Claim MLH credits: Vultr, GoDaddy Registry domain, Tiger Cloud | Domain bought, server running Ubuntu 24.04 + Docker |
| 5:00pm | DNS A record → server; repo pushed to GitHub (private for now) | `ping your-domain` shows the server IP |
| 6:00pm | Tiger Cloud service; `TIMESCALE_URL`; `python scripts/setup_timescale.py` | `/api/health` → `"friction_store": "Tiger Data"` |
| 7:00pm | Gmail app password, SMTP vars, `DEMO_RECIPIENT_OVERRIDE` = a team inbox | An approved email lands in that inbox |
| 10:30pm | Phase 4: `docker compose up -d --build` on the server (A stops local agents first) | `https://your-domain` loads; six mailboxes connected in `docker compose logs agents` |
| 1:00am | Backups: record a full local run as a video in case Wi-Fi fails on stage | Video file in the team drive |
| Sun 10:00am | Make the repo public; check `.env` is not in git history (`git log --all -- .env` is empty) | Public link works in a private window |

## C: Integrations lead (CREAO, Workday, ElevenLabs)

| By | Task | Done when |
| --- | --- | --- |
| 4:30pm | CREAO account via the hackathon link; build the **Doc Steward** from `docs/CREAO.md` | Run it by hand with `data/docs/D02.md` as the doc and `D01.md` as the source; it returns the JSON with an exact quote |
| 5:30pm | `CREAO_APP_ID` + `CREAO_API_KEY` to A; test "full report" in ASI:One | Proposal card arrives from the CREAO run; run share link saved |
| 7:00pm | **Weekly Digest** agent: Slack or Notion connector, scheduled weekly, run once by hand (needs B's domain; until then point it at the friction JSON pasted in) | A Slack/Notion post exists to show in the demo |
| 8:30pm | Workday developer tenant (`docs/WORKDAY.md`): API client, refresh token, env vars | `/api/health` → new hire profile from Workday |
| 11:30pm | ElevenLabs agent (`docs/ELEVENLABS.md`), after B's deploy | Voice question answered with a source |
| Sun 9:00am | Agent ID + run share link into README's CREAO row | README has no `TODO` left |

## D: AI quality and story (Workday judging)

| By | Task | Done when |
| --- | --- | --- |
| 4:30pm | `python eval/run_eval.py` with Sonnet | Adversarial line reads `0/5`. If not, send the failing questions to the group |
| 6:00pm | Gemini key: `python eval/run_eval.py --llm gemini --embeddings gemini` | Two result tables for the README |
| 8:00pm | Workday pitch: one slide per principle (transparent, fair, accountable, privacy-preserving, reliable), each with the screen that proves it | 5 slides + a title and an ending slide |
| 10:00pm | Devpost draft: problem, how it works, the six agents + CREAO agents, eval table, responsible AI, tracks | Draft shared with the team |
| 2:00am | Sleep. A and B take shifts too: nobody stays up all night |  |
| Sun 8:00am | Record the 3-minute video from the live server (script below) | Uploaded, unlisted |
| Sun 11:00am | Submit on Devpost. Select **Workday, Fetch.ai, CREAO**, plus every MLH track that's actually in the video | Submitted before 11:30am (not noon) |

## Checkpoints (whole team, 5 minutes each)

| Time | Must be true | If not |
| --- | --- | --- |
| **5:00pm** | Six agents on Agentverse; domain + server exist; CREAO account live | A and C pair on it; B continues |
| **8:00pm** | Full Phase 3 checklist works in ASI:One; one real CREAO run | Drop ElevenLabs and Solana; all hands on ASI:One |
| **11:30pm** | Live on the domain; ASI:One flow works against the server | Demo from A's laptop; keep the server for the URL only |
| **Sun 8:00am** | Code freeze. Only README/Devpost changes after this | — |
| **Sun 11:30am** | Everything submitted | — |

## 3-minute video script

Record with `https://your-domain/activity` open next to ASI:One, so judges see each agent light up as it works.

1. **0:00 Problem (20s).** A new hire's real blocker isn't finding a doc. It's knowing who to ask, and not getting a confident wrong answer.
2. **0:20 ASI:One (60s).** Dev setup answer with sources → stale deploy doc flagged → vacation days: no guess, routed to a person with a draft → Guardian blocks a password in the draft.
3. **1:20 Agents working together (40s).** Access request → manager agent approves from another account → the Tracker's follow-up card.
4. **2:00 People Ops (35s).** Friction Map → pay 0.1 FET → **CREAO Doc Steward run on screen** → card → doc owner's email. Slack digest.
5. **2:35 Trust (25s).** Eval: 0/5 trick questions answered wrongly; "AI can't decide your promotion" stop; human approves everything.

## Cut list if behind (cut from the top)

Solana → Snowflake → ElevenLabs → Workday live tenant (the synthetic profile still works) → Weekly Digest.
Never cut: the ASI:One flow, the CREAO Doc Steward run, the eval number, the video.
