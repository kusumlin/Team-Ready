# TeamReady eval results

Mode: **anthropic** (Sonnet)

| Metric | Result |
| --- | --- |
| questions | 40 |
| behavior accuracy | 39/40 |
| citation accuracy | 25/27 |
| helper accuracy | 8/9 |
| unsupported claims blocked | 2 |
| questions where verifier blocked a claim | 2 |
| adversarial answered instead of routed | 0/5 |
| unsupported claims shown to user | 0 |
| retrieval | keyword (BM25) |

Unsupported claims shown to the user is 0 by construction: the verifier removes any claim it can't find word for word.
Without the verifier, every blocked claim above would have been shown as fact.
