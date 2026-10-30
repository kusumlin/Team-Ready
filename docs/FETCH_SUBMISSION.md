# Fetch.ai submission (ASI:One Submission Agent)

Fetch.ai needs this **in addition to Devpost**. The team lead does it in ASI:One; teammates join with the Team ID.
Source: the LA Hacks "ASI:One Submission — Deliverables & How to Submit" doc.

## Mandatory for the Fetch track
1. Agents registered on agentverse.ai: done (7 agents, all connected).
2. Show the interaction with the agent **from asi1.ai**: the Fetch demo video includes an ASI:One chat.
3. Submit agent profiles, chats and project info through the **LA Hacks ASI:One Submission Agent**, plus Devpost.

## Steps (team lead)
1. Finish the Devpost entry first, so you have its URL.
2. In asi1.ai, open the chat where you demo `teamready-orchestrator` → search icon in the left sidebar →
   **Current chat → Share chat** → copy the `https://asi1.ai/shared-chat/...` link.
3. In ASI:One, message **LA Hacks ASI:One Submission** agent: "Hi" → **Create team (I'm the lead)**.
4. Fill in the fields below → **Continue to review** → **Confirm submission**.
5. Share the Team ID with teammates. Each one messages the Submission agent → **Join with Team ID** → name and email.
   Status turns to **Submitted** when everyone has joined.

## Field values (copy and paste)

| Field | Value |
| --- | --- |
| Project name | TeamReady |
| Table number | (your table) |
| Your name / email | (team lead) |
| Team size including you | (1–4) |
| What problem does your project solve? | New hires lose their first weeks to small blockers: which form, which channel, who owns the dashboard, is this doc still right. TeamReady is a network of seven agents on Agentverse that does the onboarding work for them from one ASI:One chat: it joins Slack channels, enrolls required training, books the first 1:1, opens IT tickets and files access forms once the manager approves. Every answer is verified word for word against approved docs, every action waits for approval, and Canary New Hires find doc gaps before real people hit them. |
| Public GitHub repository URL | https://github.com/SreenijaPavuluri/teamready |
| Devpost project URL | (from Devpost) |
| Demo video URL | (the Fetch cut, 3–5 min, with the ASI:One chat) |
| How many agents did you build? | 7 |
| Agent profile URLs | see the list below (paste as one comma-separated line) |
| How many shared chats? | 1 (or more) |
| Shared chat URLs | (from step 2) |

### Agent profile URLs (one line, comma separated)

```
https://agentverse.ai/agents/details/agent1qvxgega6yer28glv25lyrkrr2j5r4dhky93twt94gjntrk2lcpswud2vcg7/profile,https://agentverse.ai/agents/details/agent1qwh3qfy6nzlzaz9qw34prd5n0a94ns0kkqfjzcxqeqy7hqta8rfq2ql3jdv/profile,https://agentverse.ai/agents/details/agent1qgwxm40ue8umthyvdqmx32hfzt4xkvw66r7qwfervdl5zdhgdnl7q0c9ndk/profile,https://agentverse.ai/agents/details/agent1qvff097rt08j5jqgr9zpvhmusaulnrmyc0zrkmqsfe3jqqalpafmkruga7s/profile,https://agentverse.ai/agents/details/agent1qtqytcznnvddv0u0y62u2ufnugsuvc7c8v3mqdxp4yr8jfun775ejn3f4rl/profile,https://agentverse.ai/agents/details/agent1qds99je8gj9ez2pxwwq0mmy8ytavereqakgfydfr5jauhym2v6j56aeukm7/profile,https://agentverse.ai/agents/details/agent1qd0h9mhhr3wv3dwanf4qjhexmr8ww82ldmzgmcmwmjpj6ja6tvpm62fptn6/profile
```

| Agent | Profile |
| --- | --- |
| teamready-orchestrator | https://agentverse.ai/agents/details/agent1qvxgega6yer28glv25lyrkrr2j5r4dhky93twt94gjntrk2lcpswud2vcg7/profile |
| teamready-knowledge | https://agentverse.ai/agents/details/agent1qwh3qfy6nzlzaz9qw34prd5n0a94ns0kkqfjzcxqeqy7hqta8rfq2ql3jdv/profile |
| teamready-routing | https://agentverse.ai/agents/details/agent1qgwxm40ue8umthyvdqmx32hfzt4xkvw66r7qwfervdl5zdhgdnl7q0c9ndk/profile |
| teamready-manager | https://agentverse.ai/agents/details/agent1qvff097rt08j5jqgr9zpvhmusaulnrmyc0zrkmqsfe3jqqalpafmkruga7s/profile |
| teamready-insights | https://agentverse.ai/agents/details/agent1qtqytcznnvddv0u0y62u2ufnugsuvc7c8v3mqdxp4yr8jfun775ejn3f4rl/profile |
| teamready-tracker | https://agentverse.ai/agents/details/agent1qds99je8gj9ez2pxwwq0mmy8ytavereqakgfydfr5jauhym2v6j56aeukm7/profile |
| teamready-canary | https://agentverse.ai/agents/details/agent1qd0h9mhhr3wv3dwanf4qjhexmr8ww82ldmzgmcmwmjpj6ja6tvpm62fptn6/profile |

## How it scores against Fetch.ai's judging criteria
- **Functionality (25%):** seven agents talking in real time over Agentverse; the full checklist → approval → manager
  → filed-form workflow runs inside one ASI:One chat; specialists fall back locally if one is slow.
- **Use of Fetch.ai tech (20%):** Agentverse registration (mailbox), Chat Protocol on all seven, Interactive Cards for
  every review and approval, Payment Protocol on `teamready-insights` (paid Friction Map report).
- **Innovation (20%):** Canary New Hires (synthetic new hires test the docs before people do), a word-for-word
  verifier, and agents that act instead of chat.
- **Real-world impact (20%):** onboarding is a cost every company pays; actions are gated by the new hire and the
  manager, and People Ops gets fixable patterns.
- **UX and presentation (15%):** guided Interactive Cards in ASI:One, a Workday-style web view, a voice agent, and the
  demo video.

## The ASI:One demo chat (for the shared chat and the video)
Message `teamready-orchestrator` in this order:
1. `Do my checklist` → **Approve and do them** on the card
2. Review the message to the manager → **Approve and send**
3. Message `teamready-manager`: `pending` → **Approve** on the card
4. Back to `teamready-orchestrator`: `What have you done for me?`
5. Optional: `What's our deploy process for staging?` (verified answer with sources) and `My laptop screen is cracked`
