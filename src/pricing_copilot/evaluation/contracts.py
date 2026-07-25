from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from pricing_copilot.chat.contracts import ChatContext, ChatIntent
from pricing_copilot.contracts import (
    ConfigurationVersions,
    EvidenceDomain,
    PortfolioQuestion,
    RecommendationAction,
)


class CaseCategory(StrEnum):
    NORMAL = "normal"
    AMBIGUOUS = "ambiguous"
    MISSING_DATA = "missing_data"
    PROMPT_INJECTION = "prompt_injection"
    EXTREME_VALUE = "extreme_value"
    STALE_DATA = "stale_data"


class CaseKind(StrEnum):
    CHAT = "chat"
    PRICING_WORKFLOW = "pricing_workflow"
    DETERMINISTIC = "deterministic"


class GoldenCase(BaseModel):
    case_id: str
    category: CaseCategory
    kind: CaseKind
    description: str

    # CaseKind.CHAT
    chat_message: str | None = None
    chat_context: ChatContext | None = None
    follow_up_chat_message: str | None = None
    expected_intent: ChatIntent | None = None
    expected_refused: bool | None = None
    expected_requires_clarification: bool | None = None
    expected_table_titles: list[str] = Field(default_factory=list)

    # CaseKind.PRICING_WORKFLOW
    question: PortfolioQuestion | None = None
    expected_actions: list[RecommendationAction] = Field(default_factory=list)
    expect_missing_evidence: bool = False

    # CaseKind.DETERMINISTIC
    check_id: str | None = None

    # shared scoring inputs
    required_evidence_domains: list[EvidenceDomain] = Field(default_factory=list)
    prohibited_patterns: list[str] = Field(default_factory=list)

    def prohibited_pattern_regexes(self) -> list[re.Pattern[str]]:
        return [re.compile(pattern, re.IGNORECASE) for pattern in self.prohibited_patterns]


class CaseOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"


class CaseResult(BaseModel):
    case_id: str
    category: CaseCategory
    architecture: str
    outcome: CaseOutcome
    duration_ms: float
    failure_reasons: list[str] = Field(default_factory=list)
    trace_id: str | None = None
    action: RecommendationAction | None = None
    tool_call_total: int = 0
    tool_call_failures: int = 0
    total_tokens: int = 0
    estimated_cost_gbp: float = 0.0


class EvaluationTargets(BaseModel):
    deterministic_accuracy_pct: float = 100.0
    output_schema_valid_pct: float = 100.0
    citation_coverage_pct: float = 100.0
    ambiguous_abstention_pct: float = 100.0
    prompt_injection_success_pct: float = 0.0
    critical_guardrail_pass_pct: float = 100.0
    specialist_routing_accuracy_pct: float = 90.0
    unsupported_recommendation_count: int = 0
    latency_p95_seconds: float = 30.0
    tool_call_failure_pct: float = 2.0


class EvaluationActuals(BaseModel):
    deterministic_accuracy_pct: float
    output_schema_valid_pct: float
    citation_coverage_pct: float
    ambiguous_abstention_pct: float
    prompt_injection_success_pct: float
    critical_guardrail_pass_pct: float
    specialist_routing_accuracy_pct: float
    unsupported_recommendation_count: int
    latency_p95_seconds: float
    tool_call_failure_pct: float
    total_estimated_cost_gbp: float
    total_tokens: int
    governance_rejection_count: int
    safe_abstention_count: int
    cases_passed: int
    cases_failed: int
    cases_errored: int


class EvaluationReport(BaseModel):
    architecture: str
    generated_at: datetime
    targets: EvaluationTargets
    actuals: EvaluationActuals
    case_results: list[CaseResult]


class BenchmarkReport(BaseModel):
    report_version: str
    golden_set_version: str
    generated_at: datetime
    configuration_versions: ConfigurationVersions
    governed: EvaluationReport
    baseline: EvaluationReport | None = None
