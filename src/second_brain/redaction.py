"""PII redaction, applied at ingest so sensitive values never reach the index
or any model. Each category is a small rule; enable them via SECOND_BRAIN_REDACT.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable

Rule = Callable[[str, Counter], str]


def _luhn_valid(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def _pattern_rule(category: str, pattern: str, keep_group: int | None = None) -> Rule:
    """Replace matches with a tag. If keep_group is set, that group (a label
    like 'Account number:') is preserved and only the value is replaced."""
    regex = re.compile(pattern, re.IGNORECASE)
    tag = f"[REDACTED_{category.upper()}]"

    def rule(text: str, counts: Counter) -> str:
        def sub(m: re.Match) -> str:
            counts[category] += 1
            return (m.group(keep_group) if keep_group else "") + tag

        return regex.sub(sub, text)

    return rule


def _credit_card_rule(text: str, counts: Counter) -> str:
    def sub(m: re.Match) -> str:
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            counts["credit_card"] += 1
            return "[REDACTED_CREDIT_CARD]"
        return m.group()

    return re.sub(r"\b\d(?:[ -]?\d){12,18}\b", sub, text)


_LABEL = r"(?:number|no\.?|#)\s*[:#]?\s*"

RULES: dict[str, Rule] = {
    "ssn": _pattern_rule("ssn", r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
    "bank_account": _pattern_rule("bank_account", rf"(account\s+{_LABEL})\d[\d -]{{4,18}}\d", 1),
    "routing_number": _pattern_rule("routing_number", rf"(routing\s+{_LABEL})\d{{9}}\b", 1),
    "credit_card": _credit_card_rule,
    "email": _pattern_rule("email", r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": _pattern_rule("phone", r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b"),
}


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int]


class Redactor:
    def __init__(self, categories: Iterable[str]) -> None:
        unknown = set(categories) - RULES.keys()
        if unknown:
            raise ValueError(f"Unknown redaction categories: {sorted(unknown)}")
        # Order matters: SSN and labelled numbers before the generic card scan.
        self._rules = [RULES[c] for c in RULES if c in set(categories)]

    def redact(self, text: str) -> RedactionResult:
        counts: Counter = Counter()
        for rule in self._rules:
            text = rule(text, counts)
        return RedactionResult(text, dict(counts))
