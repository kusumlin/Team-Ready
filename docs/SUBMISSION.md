# Submission checklist (Devpost due 11:30am Sun Oct 18 PT)

Requirements from the hackathon page, what's ready, and what's left for a person.

| Requirement | Status | Where |
| --- | --- | --- |
| Project description: what it does, the problem, the tracks, how it fits each company challenge | Ready to paste | `docs/devpost.md` → "Project description (short)" and "Sponsor tracks" |
| Public GitHub repo, well documented | Code and docs ready; secret scan clean; **not pushed yet** | README, `docs/` |
| Demo video, 2–3 min | Recorded (2:58, narrated, captions, includes a live ElevenLabs voice call): `demo/teamready_demo.mp4` (not in git); **needs uploading** | `docs/video_script.md` |
| Devpost page: summary, technologies, extra resources | Text ready to paste; **needs filling in on Devpost** | `docs/devpost.md` |
| Present in person for judging | **Whole team at the table during judging** | — |

**Fetch.ai also requires the ASI:One Submission Agent** (separate from Devpost), with agent profile URLs and a shared ASI:One chat: everything is in `docs/FETCH_SUBMISSION.md`.

## Steps for a person

1. **Repo is public:** https://github.com/SreenijaPavuluri/teamready. Check on GitHub
   afterwards that `.env` is not in the file list.
2. **Upload the video** (`demo/teamready_demo.mp4`) to YouTube (Unlisted is fine) or Vimeo and copy the link.
3. **Fill in Devpost**, section by section, from `docs/devpost.md`:
   - Tagline → **Tagline**
   - "Project description (short)" + "What it does" → **About the project** (Devpost's story field takes the
     Inspiration / What it does / How we built it / Challenges / Accomplishments / What we learned / What's next sections
     as they are)
   - "Built with" → **Built with** tags
   - GitHub link, video link, live link (if deployed), CREAO run link → **Try it out** links
   - Video link → **Video demo link**
   - Pick the tracks: Workday, Fetch.ai, CREAO, plus any MLH prizes you qualify for (Tiger Data; Vultr / GoDaddy only
     if it's deployed there)
   - Add teammates to the Devpost project so everyone is listed
   - Image gallery: optional; screenshots of `/workday`, `/canary` and `/activity`
4. **Replace the placeholders** once you have the links: `VIDEO-LINK`, `LIVE-LINK`, `DEVPOST-LINK` in `README.md` and
   `docs/devpost.md`, then commit and push.
5. **Fetch.ai specifics:** keep the agents running through judging (only one copy with the real seeds). The README's
   innovationlab and hackathon badges and the agent address table are what the Fetch.ai judges look for.
6. **Submit before 11:30am.** Devpost allows edits until the deadline, so submit early and update the links after.

## Quick facts for judges

- Seven Agentverse agents, Chat Protocol, mailbox mode, usable in ASI:One: orchestrator, knowledge, routing, manager,
  insights, tracker, canary.
- Eval with Sonnet: 39–40/40 behavior, 0/5 adversarial questions answered; 104 automated tests.
- Every action needs a person's approval; access needs the manager; pay, performance and HR questions go to a person.
- Synthetic company (Lumen Labs) only. No real employee data.
