from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

DlpAction = Literal["allow", "warn", "quarantine", "reject"]

# Patterns match common PII without capturing the values themselves.
# Each entry: (category_name, compiled_pattern)
_DLP_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ssn",
        re.compile(
            r"\b(?!000|666|9\d{2})\d{3}[- ](?!00)\d{2}[- ](?!0{4})\d{4}\b",
            re.ASCII,
        ),
    ),
    (
        "credit_card",
        re.compile(
            r"\b(?:4\d{3}|5[1-5]\d{2}|6011|3[47]\d{2})[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
            re.ASCII,
        ),
    ),
    (
        "email_address",
        re.compile(
            r"\b[a-zA-Z0-9._%+\-]{1,64}@[a-zA-Z0-9.\-]{1,253}\.[a-zA-Z]{2,}\b",
            re.ASCII,
        ),
    ),
    (
        "phone_number",
        re.compile(
            r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b",
            re.ASCII,
        ),
    ),
    (
        "iban",
        re.compile(
            r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}(?:[A-Z0-9]{0,16})\b",
        ),
    ),
]

# Email addresses that look like documentation examples; skip counting those.
_EMAIL_ALLOWLIST_DOMAINS = frozenset({"example.com", "example.org", "test.com", "localhost"})


@dataclass(frozen=True)
class DlpFinding:
    category: str
    count: int


@dataclass
class DlpScanResult:
    action: DlpAction
    findings: list[DlpFinding] = field(default_factory=list)
    total_findings: int = 0
    skipped: bool = False

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "total_findings": self.total_findings,
            "skipped": self.skipped,
            "findings": [{"category": f.category, "count": f.count} for f in self.findings],
        }


def _count_emails(text: str) -> int:
    pattern = _DLP_PATTERNS[2][1]
    matches = pattern.findall(text)
    filtered = [
        m for m in matches if not any(m.lower().endswith("@" + d) for d in _EMAIL_ALLOWLIST_DOMAINS)
    ]
    return len(filtered)


def scan_text_for_dlp(
    text: str,
    *,
    enabled: bool = True,
    action: DlpAction = "warn",
    min_findings: int = 3,
) -> DlpScanResult:
    """Scan extracted document text for PII/sensitive data patterns.

    Returns a DlpScanResult with counts per category and the resolved policy action.
    Never stores matched text — only counts — to avoid persisting PII in audit logs.
    """
    if not enabled or not text:
        return DlpScanResult(action="allow", skipped=True)

    findings: list[DlpFinding] = []
    for category, pattern in _DLP_PATTERNS:
        if category == "email_address":
            count = _count_emails(text)
        else:
            count = len(pattern.findall(text))
        if count > 0:
            findings.append(DlpFinding(category=category, count=count))

    total = sum(f.count for f in findings)
    if total < min_findings:
        return DlpScanResult(action="allow", findings=findings, total_findings=total)

    return DlpScanResult(action=action, findings=findings, total_findings=total)
