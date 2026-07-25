from __future__ import annotations

import re

from pydantic import BaseModel

from pricing_copilot.documents.corpus import SourceType
from pricing_copilot.documents.retrieval import RetrievedDocument

_INSTRUCTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("instruction_override", re.compile(r"\b(?:system|developer)\s+override\b", re.IGNORECASE)),
    (
        "ignore_instructions",
        re.compile(
            r"\bignore (?:all |any )?(?:prior|previous|system) instructions\b",
            re.IGNORECASE,
        ),
    ),
    (
        "policy_weakening",
        re.compile(
            r"\b(?:weaken|disable|bypass|ignore).{0,40}\b(?:policy|limit|guardrail)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_escalation",
        re.compile(
            r"\b(?:add|create|enable|call|use) (?:a )?(?:new )?(?:tool|agent)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "data_exfiltration",
        re.compile(
            r"\b(?:exfiltrat|reveal|print|send|upload).{0,40}"
            r"\b(?:secret|credential|api key|environment variable|customer data)\b",
            re.IGNORECASE,
        ),
    ),
)

_PROTECTED_OR_PERSONAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:customer|policyholder)[_-]?id\b", re.IGNORECASE),
    re.compile(r"\bdate of birth\b", re.IGNORECASE),
    re.compile(r"\b(?:email address|phone number|postcode)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:age|ethnicity|race|religion|sex|sexual orientation|disability|"
        r"gender reassignment)\b",
        re.IGNORECASE,
    ),
)


class DocumentGuardrailFinding(BaseModel):
    document_id: str
    reason: str


def quarantine_unsafe_documents(
    documents: list[RetrievedDocument],
) -> tuple[list[RetrievedDocument], list[DocumentGuardrailFinding]]:
    safe: list[RetrievedDocument] = []
    findings: list[DocumentGuardrailFinding] = []
    for retrieved in documents:
        document = retrieved.document
        instruction_matches = [
            name for name, pattern in _INSTRUCTION_PATTERNS if pattern.search(document.body)
        ]
        if instruction_matches:
            findings.append(
                DocumentGuardrailFinding(
                    document_id=document.document_id,
                    reason=(
                        "Quarantined untrusted document containing instruction-like content: "
                        f"{', '.join(instruction_matches)}."
                    ),
                )
            )
            continue

        if document.source_type is SourceType.CUSTOMER_FEEDBACK and any(
            pattern.search(document.body) for pattern in _PROTECTED_OR_PERSONAL_PATTERNS
        ):
            findings.append(
                DocumentGuardrailFinding(
                    document_id=document.document_id,
                    reason=(
                        "Quarantined customer-feedback document containing personal or protected "
                        "attribute text; only aggregate portfolio themes are permitted."
                    ),
                )
            )
            continue
        safe.append(retrieved)
    return safe, findings
