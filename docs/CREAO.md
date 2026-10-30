# CREAO: Best Team Empowerment

**Track question:** do agents act as the connective tissue between people, making a team work better together without replacing anyone?

**TeamReady's answer:** two CREAO agents keep onboarding docs from going stale. They don't answer new hires; the Fetch.ai agents do that. They turn the new hires' repeated blockers into fixes that the right human (the doc owner) approves.

| CREAO agent | Trigger | What it does | Without it |
| --- | --- | --- | --- |
| **Doc Steward** | API Trigger, called by `teamready-insights` | Reads the worst Friction Map cluster, the doc new hires started from, and the doc that has the missing step. Drafts a one-span edit as JSON. | No doc fixes get drafted; the same blocker keeps coming back |
| **Weekly Digest** | Scheduled run, Mondays 9am | Reads `https://YOUR-DOMAIN/api/friction` (anonymous aggregates, groups of 5+). Posts each doc owner's top gap to Slack or Notion, with a link to ask TeamReady for the fix. | Doc owners never hear that their doc is the problem |

The Doc Steward also drafts the one-line edits for **Canary New Hires** detours (walls the synthetic new hires find
before real hires do, `unblock/canary.py`): same inputs, same API Trigger, same exact-quote check, and the run link shows
on `/canary`.

The Doc Steward's output still goes through TeamReady's exact-quote check, then a People Ops "approve", then the doc owner decides. A human approves every change.

**Status:** Doc Steward live (agent ID `b450ed0d-985d-4079-917f-d9f9ee75e812`, tested against `data/docs/D02.md`/`D01.md`, matches the expected output exactly; [share link to a run](https://agent.creao.ai/share/0773babf9c5d456f0fc0446a58d6da2f)). Weekly Digest agent built (agent ID `add647c2-ebdf-4f6f-858a-a8d5f303b3d9`), Notion connected, test run posted both notes to the ["Onboarding health"](https://app.notion.com/p/Onboarding-health-3fc5a84da8e0815b82f5c42a8d01605a) page. Slack timed out on the first try, so Notion is the live channel. The weekly schedule is set once the domain is live (it needs the real `/api/friction` URL).

**The one rule:** a CREAO agent does the core work. For the doc-fix loop, it does: with `CREAO_APP_ID` set, the drafting happens only on CREAO. Say in the pitch: *"Remove the Doc Steward and the docs never get fixed. Every new hire keeps hitting the same wall."*

## Setup (about 30 minutes)

1. Sign up with the hackathon link (it gives an upgraded account): https://creao.ai/signup?hackathon=ucla-ai
2. On **agent.creao.ai**, create the **Doc Steward** by chatting, paste the instructions below, then click **Create Agent**.
   - Inputs (text): `cluster`, `doc_title`, `doc_body`, `source_title`, `source_body`
3. On the agent's page, copy its **agent ID** and create an API key (`capi_…`). Put both in `.env` on the server:
   ```
   CREAO_APP_ID=...
   CREAO_API_KEY=capi_...
   ```
   Keep the key on the server only. Never put it in the browser, the repo, or the README.
4. Restart the agents. `/api/health` should show `"doc_fixes": "CREAO Doc Steward (…)"`.
5. Test in ASI:One: message **teamready-insights** "full report", then pay. The report arrives with
   "The CREAO Doc Steward is drafting…". A few minutes later the proposal card arrives in the same chat.
   Locally, without ASI:One: `python scripts/local_payment_demo.py` (with the two CREAO variables set).
6. Create the **Weekly Digest** agent (instructions below). Connect Slack or Notion under Skills and connectors. Schedule it weekly, and run it once by hand for the demo.
7. **For Devpost (required):** in the README, add the Doc Steward's agent ID and a **share link to one of its runs**. Show a run in the demo video.

If CREAO is slow or a run fails, TeamReady waits up to `CREAO_TIMEOUT_MINUTES` (12), then drafts the fix locally and says so in the chat. The demo can't get stuck.

## Doc Steward instructions (paste into agent.creao.ai)

```
You are the Doc Steward for a company's onboarding docs. New hires keep getting stuck on one topic.
You get:
- cluster: JSON with topic, count (blockers in 30 days), pattern (where they got stuck), resolved_share
- doc_title, doc_body: the doc most of them started from (the one to fix)
- source_title, source_body: another doc that has the step the first doc is missing

Draft ONE small edit to doc_body so the next new hire doesn't get stuck.
Rules:
1. before_quote must be copied word for word from doc_body: one line or sentence, at least 4 words.
2. after_text replaces that span. Keep the original wording and add the missing step, using only facts from source_body.
3. Don't invent links, names, numbers or policies. If source_body doesn't have the missing step, return {"before_quote": "", "after_text": "", "rationale": "not enough information"}.
4. Never include names of people or anything from a private message. You only get aggregates.

Reply with ONLY this JSON, nothing else:
{"before_quote": "...", "after_text": "...", "rationale": "one sentence, citing the cluster numbers"}
```

## Weekly Digest instructions

```
Every Monday, fetch https://YOUR-DOMAIN/api/friction (public, anonymous aggregates only).
For each cluster with "fixable": true, write a 3-line note for the owner of the doc in "start_doc":
what new hires got stuck on, how many (count), and that they can ask teamready-insights on ASI:One for a drafted fix.
Post the notes to the #onboarding-docs Slack channel (or the "Onboarding health" Notion page).
Never name individual new hires; the data has none, and don't add any.
```

## Rubric check

| Criterion | Weight | How TeamReady meets it |
| --- | --- | --- |
| AI as foundation | 30% | The doc-fix loop runs on the Doc Steward's output |
| Depth on CREAO | 25% | API Trigger from our backend, async polling, our own verifier on its output, a second scheduled agent with a Slack/Notion connector |
| Originality and ambition | 20% | New hires' confusion becomes fixes for the people who own the docs |
| Track fit | 15% | Connects new hires, People Ops and doc owners; replaces no one |
| Demo and storytelling | 10% | Show the run on CREAO, then the card in ASI:One, then the email to the owner |
