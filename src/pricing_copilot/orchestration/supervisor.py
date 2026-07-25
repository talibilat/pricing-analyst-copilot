from __future__ import annotations

import asyncio

from pricing_copilot.contracts import EvidenceDomain, SpecialistReport
from pricing_copilot.orchestration.contracts import SpecialistFindings
from pricing_copilot.orchestration.specialists import SpecialistAgent


async def run_specialists(
    specialists: dict[EvidenceDomain, SpecialistAgent],
) -> tuple[dict[EvidenceDomain, SpecialistFindings], list[EvidenceDomain]]:
    """Run every specialist concurrently. A specialist that raises is isolated - it is
    reported as a failed domain rather than crashing the other independent specialists."""
    domains = list(specialists.keys())
    results = await asyncio.gather(
        *(specialists[domain].analyze() for domain in domains), return_exceptions=True
    )

    findings_by_domain: dict[EvidenceDomain, SpecialistFindings] = {}
    failed_domains: list[EvidenceDomain] = []
    for domain, result in zip(domains, results, strict=True):
        if isinstance(result, BaseException):
            failed_domains.append(domain)
        else:
            findings_by_domain[domain] = result
    return findings_by_domain, failed_domains


def to_specialist_report(domain: EvidenceDomain, findings: SpecialistFindings) -> SpecialistReport:
    return SpecialistReport(
        domain=domain,
        status="completed",
        evidence_ids=findings.cited_evidence_ids,
        summary=findings.summary,
    )
