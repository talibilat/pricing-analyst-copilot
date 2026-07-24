from pricing_copilot.contracts import Region, ScenarioName
from pricing_copilot.documents.retrieval import retrieve_documents


def test_retrieval_ranks_relevant_documents_first() -> None:
    results = retrieve_documents(
        scenario=ScenarioName.CONTROLLED_INCREASE,
        region=Region.NORTH_WEST,
        query="claims severity repair cost inflation",
        top_k=3,
    )
    assert results
    assert results[0].document.document_id == "doc-repair-cost-2025-10"
    assert all(results[i].score >= results[i + 1].score for i in range(len(results) - 1))


def test_retrieval_respects_top_k() -> None:
    results = retrieve_documents(
        scenario=ScenarioName.CONTROLLED_INCREASE,
        region=Region.NORTH_WEST,
        query="market competitor broker feedback claims",
        top_k=2,
    )
    assert len(results) == 2


def test_retrieval_filters_by_region() -> None:
    assert (
        retrieve_documents(
            scenario=ScenarioName.CONTROLLED_INCREASE,
            region=Region.SOUTH_EAST,
            query="anything",
            top_k=5,
        )
        == []
    )


def test_retrieval_does_not_leak_documents_across_scenarios() -> None:
    controlled_increase_ids = {
        r.document.document_id
        for r in retrieve_documents(
            scenario=ScenarioName.CONTROLLED_INCREASE,
            region=Region.NORTH_WEST,
            query="claims conversion competitor broker feedback",
            top_k=10,
        )
    }
    retention_concern_ids = {
        r.document.document_id
        for r in retrieve_documents(
            scenario=ScenarioName.RETENTION_CONCERN,
            region=Region.NORTH_WEST,
            query="claims conversion competitor broker feedback",
            top_k=10,
        )
    }
    assert controlled_increase_ids
    assert retention_concern_ids
    assert controlled_increase_ids.isdisjoint(retention_concern_ids)


def test_retrieval_can_surface_the_adversarial_document() -> None:
    results = retrieve_documents(
        scenario=ScenarioName.CONTROLLED_INCREASE,
        region=Region.NORTH_WEST,
        query="market competitor repricing pricing",
        top_k=7,
    )
    ids = [r.document.document_id for r in results]
    assert "doc-market-2025-11-adversarial" in ids
