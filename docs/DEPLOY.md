# Deploy on Vultr with a GoDaddy domain

The full step-by-step, including Agentverse and ASI:One testing, is in [`GO_LIVE.md`](GO_LIVE.md) (Phase 4). This page is the short version.

One server runs the web app, the seven agents, and HTTPS.

## 1. Domain (GoDaddy)
Register a domain (for example `teamready-ai.xyz`). Keep the DNS page open; you'll add the server IP in step 3.

## 2. Server (Vultr)
1. Deploy → Cloud Compute → Shared CPU, Ubuntu 24.04, 2 GB RAM is enough. Add your SSH key.
2. SSH in and install Docker:
   ```bash
   curl -fsSL https://get.docker.com | sh
   ```
3. Open ports 80 and 443 in the Vultr firewall (or leave the firewall off for the demo).

## 3. Point the domain
In GoDaddy DNS, add an **A record**: host `@`, value = the Vultr server's IPv4, TTL 600. Wait until
`ping your-domain.xyz` shows that IP (usually a few minutes).

## 4. Run it
```bash
git clone https://github.com/<you>/unblock.git && cd unblock
cp .env.example .env    # fill in keys, seeds, DOMAIN=your-domain.xyz
docker compose up -d --build
docker compose logs -f agents   # expect "Agentverse mailbox connected" seven times
```
Open `https://your-domain.xyz`. Caddy gets the HTTPS certificate on first visit.

## 5. Check
- `https://your-domain.xyz/api/health` shows the model, retrieval and Friction Map store in use.
- `docker compose ps` shows web, agents and caddy running.
- Update after a change: `git pull && docker compose up -d --build`.
