# TeamReady Knowledge: answers you can verify

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

Answers onboarding questions only from approved company docs. Anthropic's model drafts the answer as claims with supporting quotes; a plain-code verifier keeps a claim only if its quote appears word for word in the cited doc and every number in the claim appears in the quote. Unsupported claims are blocked and counted.

Also flags stale docs (over a year old) and docs that disagree, and sets aside docs for a different office.

Confidence is computed from four visible factors: retrieval strength, agreement, freshness and the verifier pass rate.

**Try:** How long do I have to submit an expense report?
