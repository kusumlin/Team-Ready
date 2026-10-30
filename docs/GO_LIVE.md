# Go live: from zip to a working demo

Do the phases in order. Each one ends with a check, so you know it works before moving on.
Phases 1 to 3 are what the Fetch.ai and Workday judges need. Phase 4 puts it on the internet.
Phase 5 adds the other sponsors.

## Phase 1: Run it on a laptop (about 20 minutes)

1. Install Python 3.11 or newer, unzip the project, then:
   ```bash
   cd unblock
   python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env
   ```
2. Get the two required keys and put them in `.env`:
   - `ANTHROPIC_API_KEY` from console.anthropic.com
   - `AGENTVERSE_API_KEY` from agentverse.ai (Profile → API Keys)
3. Set seven seeds in `.env` to long random strings, one per agent. Anyone who knows a seed controls that
   agent, so never commit `.env`:
   ```bash
   python -c "import secrets; [print(f'{n}_SEED={secrets.token_hex(24)}') for n in ['ORCHESTRATOR','KNOWLEDGE','ROUTING','MANAGER','INSIGHTS','TRACKER','CANARY']]"
   ```
   Paste the seven lines into `.env`, replacing the empty ones.
4. Check the code works:
   ```bash
   python scripts/generate_events.py
   python -m pytest -q                         # expect 70 passed
   python eval/run_eval.py                     # Sonnet, 40 questions, about 3 minutes
   ```
   **Check:** the eval's adversarial line should read `0/5` (Sonnet routed every trick question to a person).
   If it doesn't, tell me which questions failed before going further.

## Phase 2: Put the agents on Agentverse (about 15 minutes)

1. Start all seven agents, each as its own process:
   ```bash
   ./scripts/run_all.sh            # Windows: run each agents/*_agent.py and agents/orchestrator.py in its own terminal
   tail -f logs/*.log
   ```
2. Each agent connects its mailbox automatically with your API key. In the logs, look for
   **"Agentverse mailbox connected"** seven times.
   If an agent says "auto-connect failed", open the **Agent Inspector** link printed above it and click **Connect** → Mailbox.
3. On agentverse.ai → Agents, you should see seven agents named `teamready-…`, each with its README and the
   innovationlab and hackathon badges.
4. Print the addresses and paste them into the README's agent table:
   ```bash
   python scripts/addresses.py
   ```

## Phase 3: Test the whole flow in ASI:One (about 30 minutes)

Open asi1.ai, sign in, and message **teamready-orchestrator** (search for it, or @-mention its address).
Go through the demo script and tick each line:

- [ ] "How do I set up my dev environment?" → answer with sources and an Interactive Card
- [ ] "What's our deploy process for staging?" → stale legacy doc flagged, offer to tell its owner
- [ ] "How many vacation days do I get?" → no guess, routed to a person with a draft
- [ ] "edit: ... my password is test123 ..." → **Guardian stops it**
- [ ] "edit: <clean message>" then "approve" → sent (or "Simulated" without email set up)
- [ ] "wrong person" → a different person, ranking updated
- [ ] "I need access to the analytics dashboard" → "approve" → request goes to the manager agent
- [ ] From a **second ASI:One account** (the manager), message **teamready-manager**: "pending" → "approve"
- [ ] The new hire's chat gets "Jordan Lee approved…" (if it doesn't appear, type "status": it's shown there)
- [ ] Wait for the Tracker (for the demo set `TRACKER_DUE_MINUTES=2` in `.env` and restart) → follow-up card → "approve"
- [ ] "Can the AI decide whether I deserve a promotion?" → stopped, HR named
- [ ] "do my checklist" → plan card → "approve" → Slack, training and 1:1 done (record ids), access request to the manager;
      after the manager approves, the new hire gets "I filed it for you: ACC-…"
- [ ] "my laptop screen is cracked" → IT ticket card → "approve" → ITH-… ; "what have you done" lists everything
- [ ] Message **teamready-insights**: "friction map", then "full report" → pay 0.1 FET in the ASI:One wallet → report and doc fix
- [ ] Message **teamready-canary**: "run" → report card with confirmed and predicted walls → "fixes" → "approve F1"

**Lock the manager gate:** put the manager account's address in `MANAGER_ALLOWED_SENDERS` and restart.
(The manager agent logs the sender address of every message; copy it from there.)

**Real email (recommended for the demo):** in `.env` set `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`,
`SMTP_USER` and `SMTP_PASSWORD` (a Gmail **app password**), `SMTP_FROM`, and
`DEMO_RECIPIENT_OVERRIDE=<your own inbox>` so every email lands with you, not the fictional employees.

**If something breaks:** check `logs/<agent>.log`. If a card doesn't render, the same content is in the
message text, so the flow still works; set `UNBLOCK_CARDS=false` to send text only.

## Phase 4: Deploy on Vultr with your domain (about 30 minutes)

1. **Domain:** register one on GoDaddy (for example `teamready-ai.xyz`).
2. **Server:** on Vultr, deploy Cloud Compute → Ubuntu 24.04, 2 GB RAM. Add your SSH key. Then:
   ```bash
   ssh root@SERVER_IP
   curl -fsSL https://get.docker.com | sh
   git clone https://github.com/<you>/unblock.git && cd unblock
   nano .env              # paste your laptop's .env, then add DOMAIN=teamready-ai.xyz
   ```
3. **DNS:** in GoDaddy, add an A record: host `@`, value `SERVER_IP`. Wait until `ping teamready-ai.xyz` shows it.
4. **Stop the agents on your laptop first.** Two copies with the same seeds would fight over the mailboxes.
5. Start everything:
   ```bash
   docker compose up -d --build
   docker compose logs -f agents      # expect "Agentverse mailbox connected" seven times
   ```
   If an agent can't auto-connect, tunnel its port and use the Inspector link from your laptop:
   `ssh -L 8100:127.0.0.1:8100 -L 8101:127.0.0.1:8101 ... -L 8106:127.0.0.1:8106 root@SERVER_IP`
6. **Check:** `https://teamready-ai.xyz` shows the page; `https://teamready-ai.xyz/api/health` lists the model,
   retrieval, Friction Map store and profile source; the ASI:One flow from Phase 3 still works.
7. **Update after a change:** `git pull && docker compose up -d --build`.

## Phase 5: Sponsor add-ons (in this order, skip any you run out of time for)

| Order | Sponsor | Guide | Time |
| --- | --- | --- | --- |
| 1 | Workday dev tenant (new hire profile) | `docs/WORKDAY.md` | 15 min |
| 2 | Gemini (hybrid retrieval + eval) | `docs/TRACKS.md` → Gemini | 5 min |
| 3 | Tiger Data (Friction Map store) | `docs/TRACKS.md` → Tiger Data | 10 min |
| 4 | ElevenLabs voice agent | `docs/ELEVENLABS.md` (needs Phase 4) | 15 min |
| 5 | Snowflake Cortex | `docs/TRACKS.md` → Snowflake | 15 min |
| 6 | Solana Pay | `docs/TRACKS.md` → Solana | 15 min |

After each one, check `/api/health` and run one question.

## Phase 6: Submit

- [ ] Make the GitHub repo public; README has the seven agent addresses and the eval results
- [ ] Record the 3-minute demo video (keep a backup recording of the full flow)
- [ ] Devpost submission, listing every sponsor track you actually demo
- [ ] Fetch.ai: submit through the ASI:One Submission Agent
- [ ] Every teammate can explain the part they built
