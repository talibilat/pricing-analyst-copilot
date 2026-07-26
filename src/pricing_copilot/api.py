from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.chat.contracts import ChatRequest, ChatResponse
from pricing_copilot.chat.service import ChatService
from pricing_copilot.config import Settings, get_settings
from pricing_copilot.contracts import (
    AnalystDecision,
    DecisionRequest,
    PortfolioQuestion,
    WorkflowResult,
)
from pricing_copilot.decisions.service import get_decision_store, record_analyst_decision
from pricing_copilot.replay.store import ReplayArtifactIncompatibleError, ReplayArtifactMissingError
from pricing_copilot.workflow import run_portfolio_workflow

app = FastAPI(
    title="Pricing Decision Copilot",
    description="Governed decision-support prototype for portfolio pricing questions.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/workflow", response_model=WorkflowResult)
def submit_portfolio_question(question: PortfolioQuestion, replay: bool = False) -> WorkflowResult:
    try:
        return run_portfolio_workflow(question, Settings(), replay=replay)
    except UnsupportedPortfolioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ReplayArtifactMissingError, ReplayArtifactIncompatibleError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/chat", response_model=ChatResponse)
def submit_chat_message(request: ChatRequest) -> ChatResponse:
    """Submit a safe, natural-language portfolio query to the chat service."""
    return ChatService().submit(request.message, request.context)


@app.post("/decisions", response_model=AnalystDecision)
def submit_decision(request: DecisionRequest) -> AnalystDecision:
    try:
        return record_analyst_decision(request, get_settings(), get_decision_store())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/decisions/{record_id}", response_model=AnalystDecision)
def fetch_decision(record_id: str) -> AnalystDecision:
    decision = get_decision_store().get(record_id)
    if decision is None:
        raise HTTPException(status_code=404, detail=f"No decision record found for id {record_id}.")
    return decision
