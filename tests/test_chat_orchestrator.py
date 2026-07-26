from collections.abc import Sequence
from pathlib import Path

from pricing_copilot.chat.contracts import ChatContext, ChatIntent, ChatTurn
from pricing_copilot.chat.orchestrator import (
    ChatOrchestrationPlan,
    ChatToolCall,
    ChatToolName,
    build_chat_orchestrator_prompt,
)
from pricing_copilot.chat.service import ChatService
from pricing_copilot.config import Settings
from pricing_copilot.contracts import ScenarioName


class _FakeChatOrchestrator:
    def __init__(self, plan: ChatOrchestrationPlan) -> None:
        self.plan = plan
        self.calls: list[str] = []
        self.histories: list[list[ChatTurn]] = []

    def plan_request(
        self,
        message: str,
        context: ChatContext,
        history: Sequence[ChatTurn] = (),
    ) -> ChatOrchestrationPlan:
        self.calls.append(message)
        self.histories.append(list(history))
        return self.plan


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        analytics_database_path=tmp_path / "synthetic.duckdb",
        replay_directory=tmp_path / "replay",
        evaluation_directory=tmp_path / "evaluation",
        drift_directory=tmp_path / "drift",
        local_tracing_enabled=False,
        agents_sdk_tracing_enabled=False,
    )


def test_llm_orchestration_plan_selects_sources_without_keyword_routing(tmp_path: Path) -> None:
    orchestrator = _FakeChatOrchestrator(
        ChatOrchestrationPlan(
            scenario=ScenarioName.CONTROLLED_INCREASE,
            tool_calls=[
                ChatToolCall(tool=ChatToolName.QUERY_CLAIMS),
                ChatToolCall(tool=ChatToolName.QUERY_CONVERSION),
            ],
        )
    )
    service = ChatService(_settings(tmp_path), orchestrator=orchestrator)

    response = service.submit("Compare loss experience with the sales funnel")

    assert orchestrator.calls == ["Compare loss experience with the sales funnel"]
    assert response.intent is ChatIntent.MULTI_SOURCE_SUMMARY
    assert [table.title for table in response.tables] == ["Claims", "Conversion"]


def test_llm_orchestration_plan_controls_the_allowlisted_database_fields(tmp_path: Path) -> None:
    orchestrator = _FakeChatOrchestrator(
        ChatOrchestrationPlan(
            scenario=ScenarioName.CONTROLLED_INCREASE,
            tool_calls=[
                ChatToolCall(
                    tool=ChatToolName.QUERY_CLAIMS,
                    columns=["period", "incurred_loss_gbp"],
                )
            ],
        )
    )
    service = ChatService(_settings(tmp_path), orchestrator=orchestrator)

    response = service.submit("Give me the loss values over time")

    assert response.tables[0].columns == ["period", "incurred_loss_gbp"]


def test_llm_orchestration_receives_the_active_chat_history(tmp_path: Path) -> None:
    orchestrator = _FakeChatOrchestrator(
        ChatOrchestrationPlan(
            scenario=ScenarioName.CONTROLLED_INCREASE,
            tool_calls=[ChatToolCall(tool=ChatToolName.QUERY_CONVERSION)],
        )
    )
    service = ChatService(_settings(tmp_path), orchestrator=orchestrator)
    history = [
        ChatTurn(role="user", content="Show claims performance"),
        ChatTurn(role="assistant", content="Claims deteriorated during this period."),
    ]

    service.submit("How does that compare with conversion?", history=history)

    assert orchestrator.histories == [history]


def test_security_refusal_runs_before_the_llm_orchestrator(tmp_path: Path) -> None:
    orchestrator = _FakeChatOrchestrator(
        ChatOrchestrationPlan(
            scenario=ScenarioName.CONTROLLED_INCREASE,
            tool_calls=[ChatToolCall(tool=ChatToolName.RESPOND_HELP)],
        )
    )
    service = ChatService(_settings(tmp_path), orchestrator=orchestrator)

    response = service.submit("SELECT * FROM claims")

    assert response.refused
    assert orchestrator.calls == []
    assert orchestrator.histories == []


def test_chat_orchestrator_prompt_maps_tools_to_governed_data_stores() -> None:
    prompt = build_chat_orchestrator_prompt(
        "Compare performance",
        ChatContext(scenario=ScenarioName.CONTROLLED_INCREASE),
        [
            ChatTurn(role="user", content="Show claims"),
            ChatTurn(role="assistant", content="Claims increased."),
        ],
    )

    assert "DuckDB" in prompt
    assert "retrieved document corpus" in prompt
    assert "run_governed_pricing_analysis" in prompt
    assert "Never create SQL" in prompt
    assert "RECENT CONVERSATION" in prompt
    assert "Claims increased." in prompt


def test_llm_orchestrator_can_answer_a_greeting_conversationally(tmp_path: Path) -> None:
    orchestrator = _FakeChatOrchestrator(
        ChatOrchestrationPlan(
            scenario=ScenarioName.CONTROLLED_INCREASE,
            tool_calls=[ChatToolCall(tool=ChatToolName.RESPOND_HELP)],
            assistant_message=(
                "Hello! I can help review this portfolio or explain which evidence to inspect."
            ),
        )
    )
    service = ChatService(_settings(tmp_path), orchestrator=orchestrator)

    response = service.submit("Hi hello")

    assert response.intent is ChatIntent.HELP
    assert response.message.startswith("Hello!")
