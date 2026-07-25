from datetime import date

import pytest
from agents import OpenAIChatCompletionsModel
from openai import AsyncOpenAI

from pricing_copilot.config import get_azure_openai_settings, get_settings
from pricing_copilot.contracts import (
    AnalysisPeriod,
    PortfolioQuestion,
    Product,
    Region,
    ScenarioName,
    Segment,
)
from pricing_copilot.data.repository import PortfolioDataRepository
from pricing_copilot.documents.retrieval import retrieve_documents
from pricing_copilot.workflow_common import RETRIEVAL_QUERY, build_analytics


@pytest.fixture
def controlled_increase_analytics():
    question = PortfolioQuestion(
        product=Product.PERSONAL_MOTOR,
        region=Region.NORTH_WEST,
        segment=Segment.RENEWAL,
        analysis_period=AnalysisPeriod(start_month=date(2026, 1, 1), end_month=date(2026, 6, 1)),
        scenario=ScenarioName.CONTROLLED_INCREASE,
    )
    repository = PortfolioDataRepository.from_scenario(ScenarioName.CONTROLLED_INCREASE)
    return build_analytics(question, repository)


@pytest.fixture
def controlled_increase_documents():
    return retrieve_documents(
        scenario=ScenarioName.CONTROLLED_INCREASE,
        region=Region.NORTH_WEST,
        query=RETRIEVAL_QUERY,
        top_k=6,
    )


@pytest.fixture
def azure_chat_model():
    azure = get_azure_openai_settings()
    settings = get_settings()
    base_url = (azure.endpoint or "https://example.invalid").rstrip("/") + "/openai/v1"
    client = AsyncOpenAI(api_key=azure.api_key or "unset", base_url=base_url)
    deployment = azure.chat_deployment or settings.model_name
    return OpenAIChatCompletionsModel(model=deployment, openai_client=client)
