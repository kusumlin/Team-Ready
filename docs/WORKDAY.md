# Connect TeamReady to a Workday development tenant

Workday Build gives developers a free, non-production Workday tenant with sample
workers. TeamReady can read the new hire's profile from it: name, business title,
supervisory organization and work email. It never requests anything else.

## 1. Get a tenant (about 5 minutes)
1. Create a free account at developer.workday.com with a personal email.
2. Menu → Console → Tenants → **Create Tenant** (1 to 2 minutes). Check your email for the password link.
3. Sign in to the tenant as **lmcneil** (the sample persona Logan McNeil). Change the password within 72 hours.
   The tenant expires after 7 days without a login, so sign in once a day until judging.
4. Optional: open the REST API Explorer and search workers for "mcneil" to confirm the data is there.

## 2. Create API credentials (about 10 minutes)
In the tenant, search for these tasks:
1. **Register API Client for Integrations**: give it a name, tick "Non-Expiring Refresh Tokens",
   and add the scopes that cover workers (Staffing; add Integration if offered). Save the **Client ID** and **Client Secret**.
2. **Manage Refresh Tokens for Integrations**: choose the account to act as (for example lmcneil), then generate a
   **refresh token** for your API client.
3. Find your **REST API host** and **tenant name** in the API client's details (the token endpoint looks like
   `https://HOST/ccx/oauth2/TENANT/token`).

Exact task names and scope labels can differ by tenant version. If a step doesn't match, the
"Get Started on the Workday Developer Platform" and "Steps: Set Up ISU Authentication for Apps" docs
on developer.workday.com cover it.

## 3. Configure TeamReady
```
WORKDAY_HOST=your-host.workday.com
WORKDAY_TENANT=your_tenant
WORKDAY_CLIENT_ID=...
WORKDAY_CLIENT_SECRET=...
WORKDAY_REFRESH_TOKEN=...
WORKDAY_WORKER_SEARCH=mcneil
```
Restart. `GET /api/health` should show `"new_hire_profile": "Workday worker Logan McNeil"`, and each answer's
trust trace starts with "Read your name, title and organization from Workday (nothing else)".

If Workday is unreachable, TeamReady keeps working on the local profile and `/api/health` says why.

## How to pitch it
"TeamReady reads the new hire's identity from Workday itself, the system of record, and only the four fields it
needs. Company docs and the people directory stay synthetic for the demo."


## 4. Let TeamReady act in Workday: Agent-Ready MCP tools

Workday exposes 400+ **Agent-Ready MCP tools** (absence, onboarding, journeys, learning, expenses, talent) at one
endpoint. With them TeamReady answers "how many vacation days do I have left?" from Workday itself (the docs can't),
and does Workday tasks such as **Create Worker Time Off Request**, always after the new hire approves. Workday's own
approvals (the manager for time off) still apply, and in delegate mode the agent can never do more than the person.

Code: `unblock/workday_mcp.py` (JSON-RPC 2.0 client, tool discovery, read vs change), wired into `unblock/flow.py`.
Lookups (find / list / get) run straight away; anything that changes Workday shows a review card first.

**Setup in the tenant** (Workday docs: Agents → External Agents → *Connect an External Agent with Workday MCP*; it
needs an Extend-enabled tenant, so confirm your Build tenant has Agent System of Record):
1. **Set Up Agent System of Record** (ASOR) in the tenant.
2. **Register External Agents**: register "TeamReady".
3. **Configure External Agents**: add the skills/tools it may use. Start with *Find Absence Balances*, *Find Eligible
   Absence Types*, *Find Worker Valid Time Off Dates*, *Create Worker Time Off Request*, *List Onboarding Business
   Process Tasks*, *Find Journey Statuses*, *Update Journey Steps*, and the *Learning* lookups.
4. **Configure Security Policies for Agent Skills**.
5. Get an ASU token (the docs use Bruno or Postman):
   `GET https://us.agent.workday.com/auth/authorize/<tenant>` (client_id, redirect_uri, response_type=code), log in as
   the demo worker, then `POST https://us.agent.workday.com/auth/oauth2/<tenant>/token` with
   `grant_type=authorization_code&code=…&client_id=…&client_secret=…`.
6. In `.env`: `WORKDAY_MCP_URL=https://us.agent.workday.com/<tenant>/mcp` and `WORKDAY_MCP_TOKEN=<access_token>`
   (it lasts 60 minutes; for longer, also set `WORKDAY_MCP_TOKEN_URL`, `WORKDAY_MCP_CLIENT_ID`,
   `WORKDAY_MCP_CLIENT_SECRET`, `WORKDAY_MCP_REFRESH_TOKEN` and TeamReady refreshes it).
7. Check: `/api/health` shows `"workday_mcp": "connected: N Agent-Ready tools"`, and the Workday view's profile card
   shows "Workday MCP: connected". Then ask "How many vacation days do I have left?".
