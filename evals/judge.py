"""End-to-end eval: retrieve, answer with Claude, then grade with a second model.

Needs ANTHROPIC_API_KEY. Run on demand or nightly, not on every PR (it costs money).

    python evals/judge.py
"""
from __future__ import annotations

import json
import os
import re
import sys

from anthropic import Anthropic

from common import fresh_brain, load_golden, write_summary

ANSWER_MODEL = os.getenv("SECOND_BRAIN_ANSWER_MODEL", "claude-sonnet-5-5")
JUDGE_MODEL = os.getenv("SECOND_BRAIN_JUDGE_MODEL", "claude-haiku-4-5-20251001")

ANSWER_SYSTEM = (
    "You answer questions about the user's personal documents using ONLY the context "
    "provided. Cite the source path for each fact in [brackets]. If the context does not "
    "contain the answer, say exactly: 'I couldn't find that in your documents.' Never guess "
    "values shown as [REDACTED_*]."
)

JUDGE_SYSTEM = """You grade an assistant's answer. Return ONLY a JSON object:
{"grounded": true|false, "correct": true|false, "reason": "<one sentence>"}

grounded: every factual claim in the answer is supported by the CONTEXT. An answer that
  says the information isn't available is grounded.
correct: if EXPECT is "not_found", the answer must decline to answer. If EXPECT is
  "answer", the answer must actually answer the question and include every MUST_INCLUDE item."""


def _context(hits) -> str:
    if not hits:
        return "(no relevant documents found)"
    return "\n\n".join(f"[{h.source}]\n{h.text}" for h in hits)


def _text(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text").strip()


def _parse_json(raw: str) -> dict:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(match.group()) if match else {"grounded": False, "correct": False, "reason": raw}


def run_case(client: Anthropic, brain, case: dict) -> dict:
    context = _context(brain.search(case["query"]))
    answer = _text(client.messages.create(
        model=ANSWER_MODEL,
        max_tokens=500,
        system=ANSWER_SYSTEM,
        messages=[{"role": "user", "content": f"CONTEXT:\n{context}\n\nQUESTION: {case['query']}"}],
    ))
    verdict = _parse_json(_text(client.messages.create(
        model=JUDGE_MODEL,
        max_tokens=300,
        system=JUDGE_SYSTEM,
        messages=[{"role": "user", "content": (
            f"QUESTION: {case['query']}\nEXPECT: {case['expect']}\n"
            f"MUST_INCLUDE: {case.get('contains', [])}\n\nCONTEXT:\n{context}\n\nANSWER:\n{answer}"
        )}],
    )))
    return {"id": case["id"], "answer": answer, **verdict}


def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set; the judge eval calls the Claude API.")

    golden = load_golden()
    client = Anthropic()
    with fresh_brain() as brain:
        results = [run_case(client, brain, c) for c in golden["judge_cases"]]

    n = len(results)
    grounded = sum(bool(r.get("grounded")) for r in results) / n
    correct = sum(bool(r.get("correct")) for r in results) / n
    t = golden["judge_thresholds"]
    ok = grounded >= t["grounded"] and correct >= t["correct"]

    lines = [
        f"## Judge evals ({ANSWER_MODEL}, judged by {JUDGE_MODEL})", "",
        f"- grounded: {grounded:.0%} (threshold {t['grounded']:.0%})",
        f"- correct: {correct:.0%} (threshold {t['correct']:.0%})", "",
    ]
    for r in results:
        mark = "✅" if r.get("grounded") and r.get("correct") else "❌"
        lines.append(f"- {mark} `{r['id']}`: {r.get('reason', '')}")
    markdown = "\n".join(lines)
    print(markdown)
    print(f"\nRESULT: {'PASS' if ok else 'FAIL'}")
    write_summary(markdown)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
