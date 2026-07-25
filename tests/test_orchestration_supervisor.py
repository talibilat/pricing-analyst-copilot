import asyncio
import time

from pricing_copilot.contracts import EvidenceDomain
from pricing_copilot.orchestration.contracts import SpecialistFindings
from pricing_copilot.orchestration.specialists import SpecialistAgent
from pricing_copilot.orchestration.supervisor import run_specialists, to_specialist_report


class _SlowFakeSpecialist:
    def __init__(self, findings: SpecialistFindings, delay_seconds: float) -> None:
        self._findings = findings
        self._delay_seconds = delay_seconds

    async def analyze(self) -> SpecialistFindings:
        await asyncio.sleep(self._delay_seconds)
        return self._findings


class _FailingFakeSpecialist:
    async def analyze(self) -> SpecialistFindings:
        raise RuntimeError("specialist tool call failed")


def test_run_specialists_executes_concurrently_not_sequentially() -> None:
    specialists: dict[EvidenceDomain, SpecialistAgent] = {
        domain: _SlowFakeSpecialist(SpecialistFindings(summary=f"{domain.value} ok"), 0.2)
        for domain in EvidenceDomain
    }
    started = time.monotonic()
    asyncio.run(run_specialists(specialists))
    elapsed = time.monotonic() - started
    assert elapsed < 0.2 * len(EvidenceDomain)  # would be ~0.8s if run sequentially
    assert elapsed < 0.4  # generous upper bound for one ~0.2s parallel batch


def test_run_specialists_isolates_a_failing_domain_without_crashing_others() -> None:
    specialists: dict[EvidenceDomain, SpecialistAgent] = {
        EvidenceDomain.CLAIMS: _FailingFakeSpecialist(),
        EvidenceDomain.CONVERSION: _SlowFakeSpecialist(
            SpecialistFindings(summary="conversion ok"), 0.01
        ),
        EvidenceDomain.MARKET_INTELLIGENCE: _SlowFakeSpecialist(
            SpecialistFindings(summary="market ok"), 0.01
        ),
        EvidenceDomain.PRICING_HISTORY: _SlowFakeSpecialist(
            SpecialistFindings(summary="history ok"), 0.01
        ),
    }
    findings_by_domain, failed_domains = asyncio.run(run_specialists(specialists))
    assert failed_domains == [EvidenceDomain.CLAIMS]
    assert set(findings_by_domain) == {
        EvidenceDomain.CONVERSION,
        EvidenceDomain.MARKET_INTELLIGENCE,
        EvidenceDomain.PRICING_HISTORY,
    }


def test_to_specialist_report_carries_summary_and_citations() -> None:
    findings = SpecialistFindings(summary="Loss ratio rose.", cited_evidence_ids=["claims-x"])
    report = to_specialist_report(EvidenceDomain.CLAIMS, findings)
    assert report.status == "completed"
    assert report.summary == "Loss ratio rose."
    assert report.evidence_ids == ["claims-x"]
