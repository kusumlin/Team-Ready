---
title: We built an onboarding agent that isn't allowed to make things up
tags: ai, agents, python, hackathon
---

New hires get stuck on questions nobody has answered for them yet: how to deploy, who owns the dashboard, how to request access. An AI assistant over internal docs sounds like the fix, until it confidently invents a deploy command. A new hire can't tell a real answer from a made-up one.

At LA Hacks AI Hackathon 2026 we built **TeamReady**, a team of five agents on Fetch.ai's Agentverse that answers only what it can prove.

## The rule: no quote, no claim

The model (Anthropic's Sonnet, or Gemini, or Snowflake Cortex: they're interchangeable) never answers directly. It returns claims, each with a quote and a doc id. Then plain Python decides what the new hire sees. A claim survives only if:

- the quote appears word for word in a doc we actually retrieved,
- the quote isn't cut out of a sentence that says "not",
- most of the claim's words are in the quote, and
- every number in the claim is in the quote.

If nothing survives, TeamReady doesn't guess. It finds the right person and drafts the message.

<!-- Add one real blocked claim from your demo here. -->

## Five agents, one chat

- **Orchestrator:** the ASI:One front door, with a risk gate that stops pay, performance and harassment questions before any search.
- **Knowledge:** hybrid search (BM25 + Gemini embeddings), the verifier, stale and conflicting doc detection.
- **Routing:** who to ask, with a visible score and a fairness rotation so the same senior engineer isn't always the default.
- **Manager:** a human approval gate. Access requests are prepared, never granted.
- **Insights:** the Friction Map, anonymous patterns of what keeps blocking people, stored in TimescaleDB and sold to People Ops through Fetch.ai's Payment Protocol.

## What we measured

<!-- Paste your eval table: behavior accuracy, citation accuracy, blocked claims, adversarial questions routed. -->

## What we'd do next

<!-- Your real lessons. -->

Code: <!-- repo link -->
