"""Evaluate TeamReady on 40 labeled questions.

    python eval/run_eval.py                 # Anthropic (needs ANTHROPIC_API_KEY, LLM_MODEL)
    python eval/run_eval.py --llm extractive  # no-model baseline

Reports:
  behavior accuracy   answered / routed to a person / stopped / sent for approval, as expected
  citation accuracy   answered questions that cite an expected source
  helper accuracy     routed questions sent to an expected person
  unsupported claims  claims the model made that the verifier blocked (they would
                      have reached the user without it), and how many questions had one
  invented answers    adversarial questions answered instead of routed (should be 0)
Writes eval/results.json and eval/RESULTS.md.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("UNBLOCK_TODAY", "2026-10-17")

from unblock.data import load_user  # noqa: E402
from unblock.knowledge import answer  # noqa: E402
from unblock.llm import get_llm  # noqa: E402
from unblock.risk import assess  # noqa: E402
from unblock.routing import rank  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", default=None, help="anthropic (default) | gemini | snowflake | extractive")
    parser.add_argument("--embeddings", default="", help="gemini to use hybrid retrieval")
    args = parser.parse_args()
    if args.embeddings:
        os.environ["UNBLOCK_EMBEDDINGS"] = args.embeddings
    llm = get_llm(args.llm)
    user = load_user()
    questions = json.loads((ROOT / "eval" / "questions.json").read_text())

    rows = []
    for q in questions:
        start = time.time()
        risk = assess(q["question"])
        row = {"id": q["id"], "question": q["question"], "expect": q["expect"], "adversarial": q.get("adversarial", False)}
        if risk.level == "stop":
            row.update(got="stop", cited=[], blocked=0, helper=None)
        else:
            result = answer(q["question"], user, llm)
            got = "approval" if risk.level == "approval" else result.decision
            helper = None
            if got == "route":
                r = rank(q["question"], user, result.retrieved_doc_ids if result.confidence["factors"]["retrieval"]["points"] >= 9 else None)
                helper = r.chosen.person_id if r.chosen else None
            row.update(got=got, cited=[c["id"] for c in result.citations], blocked=len(result.blocked),
                       blocked_examples=result.blocked[:2], helper=helper, confidence=result.confidence["score"],
                       error=result.error)
        row["seconds"] = round(time.time() - start, 2)
        row["behavior_ok"] = row["got"] == q["expect"]
        if q["expect"] in ("answer", "approval") and q["sources"]:
            row["citation_ok"] = bool(set(row["cited"]) & set(q["sources"]))
        if row["got"] == "route" and q["helpers"]:
            row["helper_ok"] = row["helper"] in q["helpers"]
        rows.append(row)
        mark = "ok " if row["behavior_ok"] else "MISS"
        print(f"{mark} {q['id']} expect={q['expect']:8s} got={row['got']:8s} cited={row['cited']} blocked={row['blocked']} helper={row['helper']}")

    def share(key):
        vals = [r[key] for r in rows if key in r]
        return (sum(vals), len(vals))

    beh, cit, hel = share("behavior_ok"), share("citation_ok"), share("helper_ok")
    blocked_total = sum(r["blocked"] for r in rows)
    with_blocked = sum(1 for r in rows if r["blocked"])
    adversarial = [r for r in rows if r["adversarial"]]
    invented = sum(1 for r in adversarial if r["got"] == "answer")
    summary = {
        "llm": llm.mode, "model": getattr(llm, "model", ""), "questions": len(rows),
        "behavior_accuracy": f"{beh[0]}/{beh[1]}", "citation_accuracy": f"{cit[0]}/{cit[1]}",
        "helper_accuracy": f"{hel[0]}/{hel[1]}", "unsupported_claims_blocked": blocked_total,
        "questions_where_verifier_blocked_a_claim": with_blocked,
        "adversarial_answered_instead_of_routed": f"{invented}/{len(adversarial)}",
        "unsupported_claims_shown_to_user": 0,
    }
    summary["retrieval"] = "hybrid (Gemini embeddings)" if args.embeddings else "keyword (BM25)"
    out = {"summary": summary, "rows": rows}
    tag = llm.mode + ("_hybrid" if args.embeddings else "")
    (ROOT / "eval" / f"results_{tag}.json").write_text(json.dumps(out, indent=1))
    md = ["# TeamReady eval results", "", f"Mode: **{llm.mode}** {summary['model']}", "",
          "| Metric | Result |", "| --- | --- |"]
    md += [f"| {k.replace('_', ' ')} | {v} |" for k, v in summary.items() if k not in ("llm", "model")]
    md += ["", "Unsupported claims shown to the user is 0 by construction: the verifier removes any claim it can't find word for word.",
           "Without the verifier, every blocked claim above would have been shown as fact."]
    (ROOT / "eval" / f"RESULTS_{tag}.md").write_text("\n".join(md) + "\n")
    print("\n" + json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
