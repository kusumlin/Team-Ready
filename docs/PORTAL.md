# New Hire Portal (`/app`)

The portal is the web version of the TeamReady chat in ASI:One. It's a page the new hire can use from day one,
with a manager view on the same page.

## What the new hire can do

| What | How it works |
| --- | --- |
| Ask anything in their own words | Same pipeline as ASI:One: risk gate → knowledge (verified, cited answers) → confidence. The "Why you can trust this" panel shows sources, confidence factors and data used. |
| Get sent to the right person | When the docs don't answer, Routing picks a person (skills, team, availability, fair rotation) and TeamReady drafts the message |
| Approve, edit or reject every draft | The draft card shows exactly what will be sent. **Edit** in place; the Guardian re-checks it and disables **Approve** if it finds a password, ID number, card number, health or pay details |
| Say "wrong person" | Ranking learns; the next best person gets a new draft |
| Request access | Access requests go to the manager's queue (Manager tab). Only the manager can approve. The decision appears in the new hire's chat |
| Get follow-ups | "Waiting on others" lists every message and request. If nobody replies in time, the Tracker offers a reminder, shown before it's sent |
| Work through the first two weeks | The checklist comes from the approved "New Hire Systems Checklist" doc. **Ask** on any item asks TeamReady about it. Ticks are saved in the browser |
| See their profile | Name, role, team and manager. From Workday when the tenant is connected; the badge says which |

The manager tab (Jordan) shows each request with the doc evidence behind it, a note field, Approve and Reject.
Set `PORTAL_MANAGER_KEY` to require a key for the manager tab.

Every step is written to the Agent Activity log, so `/activity` shows what the portal is doing.

## How it relates to the agents

The portal runs the orchestrator's own conversation logic (`unblock/flow.py`) and the same knowledge, routing,
Guardian and tracker code inside the web app, logged under the same agent names. The **multi-agent version runs in
ASI:One**, where each step is a real message between the six uAgents on Agentverse. Say this plainly to judges: the
portal is the new hire's web front end; ASI:One is the agent network.

State is one JSON file on the shared runtime volume, keyed by a browser session id. That is not a login. This is a
demo with a fictional new hire (Maya); never put real employee data in it.

## Workday

What is built and works with a Workday developer tenant (`docs/WORKDAY.md`):
- The new hire's **name, title and organization come from Workday** through its REST API (OAuth refresh token,
  `GET /workers`). The portal badge switches from "Sample profile" to "Profile from Workday".

How it would sit inside Workday at a real company (talk about this in the pitch, don't claim it's built):
- A link to the portal from the new hire's onboarding tasks or a Workday dashboard, so it's one click from where
  they already are.
- Single sign-on with the company's identity provider instead of the demo session.
- Approvals written back to Workday's own business processes instead of the portal's queue.
