from __future__ import annotations

from fastapi import FastAPI, HTTPException

from pricing_copilot.catalog import UnsupportedPortfolioError
from pricing_copilot.contracts import PortfolioQuestion, WorkflowResult
from pricing_copilot.workflow import run_portfolio_workflow

app = FastAPI(
    title="Pricing Decision Copilot",
    description="Governed decision-support prototype for portfolio pricing questions.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/workflow", response_model=WorkflowResult)
def submit_portfolio_question(question: PortfolioQuestion) -> WorkflowResult:
    try:
        return run_portfolio_workflow(question)
    except UnsupportedPortfolioError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
