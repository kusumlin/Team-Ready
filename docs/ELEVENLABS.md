# Voice onboarding buddy with ElevenLabs

The voice agent talks; TeamReady decides what is true. Every spoken fact comes from
`POST /api/voice/ask`, which runs the same risk gate and verifier as the chat agents.

## Before you start
- The web app must be reachable over HTTPS (see `docs/DEPLOY.md`), for example `https://your-domain.xyz`.
- Pick a long random value for `VOICE_TOOL_SECRET` in `.env` and restart the web app.

## Create the agent (ElevenLabs dashboard)
1. Agents → Create agent → Blank template. Name it **TeamReady Voice**.
2. **First message:** "Hi, I'm TeamReady, your onboarding buddy at Lumen Labs. What's blocking you?"
3. **System prompt:**
   ```
   You are TeamReady, a friendly onboarding buddy for new employees at Lumen Labs, a fictional company.
   For ANY question about how things work at Lumen Labs, call the ask_unblock tool with the employee's
   question, then say the tool's "answer" field in a natural voice. Do not add facts, numbers, names,
   links or commands that are not in the tool's answer. If the tool says a person should handle it,
   tell the employee who to talk to and stop. Never answer company questions from your own knowledge.
   Keep replies under 40 seconds. Never judge a question as too basic.
   ```
4. Tools → Add tool → **Webhook**:
   - Name: `ask_unblock`
   - Description: "Answers a new hire's question using only verified company docs."
   - Method: `POST`, URL: `https://your-domain.xyz/api/voice/ask`
   - Headers: `X-Unblock-Secret` = your `VOICE_TOOL_SECRET`
   - Body parameter: `question` (string, required): "The employee's question, in their own words."
5. Choose a warm, clear voice. Save, then use **Test AI agent** in the dashboard.

## Demo lines
- "How do I deploy to staging?" spoken answer cites "Deploying to Staging".
- "How many vacation days do I get?" it says it won't guess and names who to ask.
- "Can the AI decide my promotion?" it says a person should handle it.

## What the endpoint returns
```json
{"answer": "Here's what the docs say. ...", "kind": "answer|route|stop|approval",
 "sources": ["Deploying to Staging"], "blocked_claims": 0}
```
