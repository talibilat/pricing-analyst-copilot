from pathlib import Path

from pricing_copilot.config import CostSettings, Settings
from pricing_copilot.observability.contracts import TraceEventKind
from pricing_copilot.observability.trace import WorkflowTraceRecorder, read_trace


def test_local_trace_records_versions_limits_usage_and_configured_cost(tmp_path: Path) -> None:
    settings = Settings(
        trace_directory=tmp_path,
        cost=CostSettings(
            input_cost_per_million_tokens_gbp=1.0,
            output_cost_per_million_tokens_gbp=2.0,
        ),
    )
    recorder = WorkflowTraceRecorder(
        settings,
        {
            "model_name": "test-model",
            "prompt_version": "prompt-v1",
            "agent_registry_version": "registry-v1",
            "tool_version": "tools-v1",
            "dataset_version": "dataset-v1",
            "policy_version": "policy-v1",
        },
    )
    recorder.event(TraceEventKind.ROUTING, "claims", "scheduled")
    recorder.add_usage(
        requests=1,
        input_tokens=1_000_000,
        output_tokens=500_000,
        agent_name="claims-specialist",
    )

    trace = recorder.complete("completed")
    saved = read_trace(tmp_path / f"{trace.trace_id}.json")

    assert saved.configuration_versions["agent_registry_version"] == "registry-v1"
    assert saved.limits["max_retries"] == 1
    assert saved.usage.total_tokens == 1_500_000
    assert saved.usage.estimated_cost_gbp == 2.0
    assert saved.usage.pricing_configured is True
    assert {event.kind for event in saved.events} >= {
        TraceEventKind.ROUTING,
        TraceEventKind.MODEL_CALL,
    }
