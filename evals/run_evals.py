"""Deterministic retrieval evals. No API key needed; runs on every PR.

    python evals/run_evals.py              # score against thresholds, exit 1 on failure
    python evals/run_evals.py --calibrate  # print raw scores to tune SECOND_BRAIN_MIN_SCORE
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from common import fresh_brain, load_golden, write_summary


@dataclass
class CaseResult:
    id: str
    type: str
    passed: bool
    detail: str
    top_score: float
    hit: bool = False    # expected source retrieved (answerable only)
    fact: bool = False   # expected fact present in that source's chunks


def _contains_all(text: str, needles: list[str]) -> bool:
    lowered = text.lower()
    return all(n.lower() in lowered for n in needles)


def evaluate(brain, golden: dict) -> tuple[list[CaseResult], dict[str, float], int]:
    canaries: list[str] = golden.get("pii_canaries", [])
    results: list[CaseResult] = []
    leaks = sum(1 for c in canaries if c in brain.store.all_text())

    for case in golden["cases"]:
        hits = brain.search(case["query"])
        raw = brain.search(case["query"], min_score=0.0)
        top = raw[0].score if raw else 0.0
        leaks += sum(1 for h in hits for c in canaries if c in h.text)

        hit = fact = False
        if case["type"] == "unanswerable":
            passed = not hits
            detail = "abstained" if passed else f"returned {hits[0].source} ({hits[0].score})"
        else:
            from_source = [h for h in hits if h.source == case["source"]]
            hit = bool(from_source)
            fact = any(_contains_all(h.text, case["contains"]) for h in from_source)
            passed = hit and fact
            detail = (
                "ok" if passed
                else "source missing" if not hit
                else f"fact missing: {case['contains']}"
            )

        results.append(CaseResult(case["id"], case["type"], passed, detail, top, hit, fact))

    answerable = [r for r in results if r.type == "answerable"]
    unanswerable = [r for r in results if r.type == "unanswerable"]
    metrics = {
        "hit_rate": sum(r.hit for r in answerable) / max(len(answerable), 1),
        "fact_recall": sum(r.fact for r in answerable) / max(len(answerable), 1),
        "abstention": sum(r.passed for r in unanswerable) / max(len(unanswerable), 1),
    }
    return results, metrics, leaks


def calibrate(results: list[CaseResult]) -> None:
    ans = sorted((r.top_score for r in results if r.type == "answerable"))
    neg = sorted((r.top_score for r in results if r.type == "unanswerable"))
    print("\nTop similarity per case")
    for r in sorted(results, key=lambda r: r.top_score):
        print(f"  {r.top_score:6.3f}  {r.type:12}  {r.id}")
    if ans and neg:
        print(f"\nlowest answerable = {ans[0]:.3f}   highest unanswerable = {neg[-1]:.3f}")
        if ans[0] > neg[-1]:
            print(f"Separable. Suggested SECOND_BRAIN_MIN_SCORE = {(ans[0] + neg[-1]) / 2:.3f}")
        else:
            print("Not cleanly separable; pick a floor that favours abstention and let the "
                  "judge eval cover the overlap.")


def report(results, metrics, leaks, thresholds) -> bool:
    checks = {name: metrics[name] >= thresholds[name] for name in metrics}
    checks["pii_leaks"] = leaks <= thresholds["pii_leaks"]
    ok = all(checks.values())

    lines = ["## Retrieval evals", "", "| metric | value | threshold | |", "|---|---|---|---|"]
    for name, value in metrics.items():
        lines.append(f"| {name} | {value:.2%} | {thresholds[name]:.0%} | {'✅' if checks[name] else '❌'} |")
    lines.append(f"| pii_leaks | {leaks} | {thresholds['pii_leaks']} | {'✅' if checks['pii_leaks'] else '❌'} |")
    failures = [r for r in results if not r.passed]
    if failures:
        lines += ["", "**Failing cases**", ""]
        lines += [f"- `{r.id}` ({r.type}): {r.detail}" for r in failures]
    markdown = "\n".join(lines)

    print("\n" + markdown)
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    write_summary(markdown)
    return ok


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true", help="Print raw scores, don't gate")
    args = parser.parse_args()

    golden = load_golden()
    with fresh_brain() as brain:
        results, metrics, leaks = evaluate(brain, golden)

    if args.calibrate:
        calibrate(results)
        return
    sys.exit(0 if report(results, metrics, leaks, golden["thresholds"]) else 1)


if __name__ == "__main__":
    main()
