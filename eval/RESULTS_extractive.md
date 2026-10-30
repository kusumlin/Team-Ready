# TeamReady eval results

Mode: **extractive** 

| Metric | Result |
| --- | --- |
| questions | 40 |
| behavior accuracy | 34/40 |
| citation accuracy | 27/27 |
| helper accuracy | 2/2 |
| unsupported claims blocked | 0 |
| questions where verifier blocked a claim | 0 |
| adversarial answered instead of routed | 5/5 |
| unsupported claims shown to user | 0 |
| retrieval | keyword (BM25) |

Unsupported claims shown to the user is 0 by construction: the verifier removes any claim it can't find word for word.
Without the verifier, every blocked claim above would have been shown as fact.
