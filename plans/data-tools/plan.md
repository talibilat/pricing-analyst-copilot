# Data and Tooling Agent Plan

## Goal and time box

Deliver the data and tool half of the LLM-first Streamlit prototype in three to four hours.
Give the conversation graph one interface for schema discovery, safe SQL, documents, stored reports, replay, and the existing governed recommendation workflow.
Do not implement graph routing, prompts, response composition, session memory, or Streamlit UI.

| Time | Task |
|---:|---|
| 0:00-0:20 | Reproduce the current data boundary with focused tests. |
| 0:20-1:20 | Add schema discovery and safe read-only SQL. |
| 1:20-2:10 | Build adapters over all existing resources. |
| 2:10-2:50 | Move production analysis to the persistent DuckDB. |
| 2:50-3:35 | Add focused E2E and security tests. |
| 3:35-4:00 | Remove proven-dead paths, verify, and hand off. |

Stop at four hours and record nonessential refactors as follow-up work.

## Exact file ownership

This agent owns only:

- `src/pricing_copilot/data/persistent.py`
- `src/pricing_copilot/data/repository.py`
- `src/pricing_copilot/chat/tool_adapters.py`
- `src/pricing_copilot/orchestration/pipeline.py`
- `src/pricing_copilot/workflow.py`
- `tests/test_persistent_data.py`
- `tests/test_data_repository.py`
- `tests/test_chat_tool_adapters.py`
- `tests/test_chat_tool_adapters_e2e.py`
- `tests/test_orchestration_pipeline.py`

The conversation agent owns `pyproject.toml`, `uv.lock`, all graph and chat contracts, `chat/service.py`, `streamlit_app.py`, and their tests.
Do not edit files owned by the conversation agent.
Ask that agent to add an SQL AST parser such as `sqlglot`.
If it is unavailable within 20 minutes, keep free-form SQL deferred and expose only the existing structured `ReadOnlyQueryPlan`.
Never describe regex-only validation as safe arbitrary SQL.

## Graph-facing API

Create `ChatToolFacade` in `src/pricing_copilot/chat/tool_adapters.py`.
Expose these methods:

```python
describe_analytics_schema() -> dict[str, object]
execute_read_only_sql(sql: str, scenario: ScenarioName) -> dict[str, object]
search_documents(query: str, scenario: ScenarioName, region: Region, top_k: int = 6) -> dict[str, object]
load_replay(scenario: ScenarioName) -> dict[str, object]
load_evaluation() -> dict[str, object]
load_drift() -> dict[str, object]
run_recommendation(question: PortfolioQuestion, on_activity: ActivityListener | None = None) -> dict[str, object]
```

Every method returns JSON-serializable keys named `status`, `source`, `data`, `citations`, and `error`.
Use `ok`, `not_found`, and `blocked` statuses.
Reuse existing evidence IDs and version metadata as citations.
Convert only known operational outcomes into structured errors and let programming errors fail loudly.

## Task 1: Add safe analytics access

Extend `PersistentAnalyticsDatabase` rather than creating another client.
Add validated SQL request and result contracts in `data/persistent.py`.
Enforce these controls before execution:

- Accept exactly one `SELECT`, including a `WITH` expression ending in `SELECT`.
- Allow only `claims`, `conversion`, `competitors`, and `pricing_history`.
- Reject mutations, schema-qualified access, external files, table functions, extensions, pragmas, attach, copy, and export.
- Allow only catalogue-approved columns.
- Apply the selected scenario inside the query layer rather than trusting the LLM to include it.
- Cap results at 200 rows.
- Open DuckDB read-only.
- Return executed SQL, columns, rows, scenario, and database version.

Use AST validation and rewriting.
Test projections, filters, aggregates, aliases, ordering, and common table expressions.
Test stacked statements, mutations, unknown tables, schema bypasses, external files, hidden statements, prohibited fields, and scenario bypass attempts.

## Task 2: Adapt every existing resource

Build the facade by composing existing implementations without duplicating business logic:

| Capability | Existing implementation |
|---|---|
| Schema and SQL | `PersistentAnalyticsDatabase` |
| Documents | `retrieve_documents` and `quarantine_unsafe_documents` |
| Replay | `load_replay_artifact` |
| Evaluation | `load_benchmark_report` |
| Drift | `load_drift_report` |
| Recommendation | `run_portfolio_workflow` |
| Specialists | Existing claims, conversion, competitor, pricing-history, and market tools |

Pass the user's actual query into document retrieval and quarantine unsafe results before returning them.
Accept only a fully resolved `PortfolioQuestion` for recommendations.
Do not guess product, region, segment, period, or scenario.
Forward workflow activity events for Streamlit progress display.
Preserve evidence IDs, uncertainty, counter-evidence, governance outcome, and human-approval language.

## Task 3: Remove the duplicate production data path

Add a persistent, scenario-scoped constructor to `PortfolioDataRepository`.
Keep `from_dataset` for deterministic tests.
Change production workflow and orchestration calls to read `settings.analytics_database_path`.
Include the scenario predicate in every repository query.
Remove production calls to `from_scenario`.
Remove `from_scenario` itself only if repository-wide search proves no caller needs it.
Do not remove synthetic generation, existing tools, stores, CLI, API, or test helpers.

## Task 4: Focused E2E and security coverage

Create facade-level E2E tests that do not require Streamlit or live model credentials.
Cover:

1. Schema discovery returns all four business tables and units.
2. A last-month premium query returns only the selected scenario.
3. A competitor query returns fictional competitor names.
4. Safe user `SELECT` executes and is capped at 200 rows.
5. Writes, external files, table functions, prohibited fields, and scenario bypasses are blocked before execution.
6. Document search returns evidence IDs and excludes quarantined content.
7. Missing replay, evaluation, and drift artifacts return recoverable `not_found` payloads.
8. Stubbed recommendation dispatch preserves the governed workflow result and activity events.
9. Unexpected tool failures remain visible rather than becoming fabricated answers.

The conversation agent separately owns browser tests for factual answers, clarifications, history, refresh, and graph routing.

## Verification

Run:

```bash
uv run pytest tests/test_persistent_data.py tests/test_data_repository.py tests/test_chat_tool_adapters.py tests/test_chat_tool_adapters_e2e.py tests/test_orchestration_pipeline.py -q
uv run ruff check src/pricing_copilot/data src/pricing_copilot/chat/tool_adapters.py tests/test_chat_tool_adapters.py tests/test_chat_tool_adapters_e2e.py
uv run mypy src/pricing_copilot/data src/pricing_copilot/chat/tool_adapters.py
```

Run the full suite only if time remains.
Report unrelated failures without expanding scope.

## Hand-off and definition of done

Provide the conversation agent with the facade constructor, method signatures, example `ok`, `not_found`, and `blocked` payloads, and escaping exception types.
Confirm that SQL is scenario-scoped, row-limited, and read-only.
Confirm that recommendations still invoke the existing specialist, recommendation, and governance agents.
The conversation agent must import only `ChatToolFacade`, not DuckDB, individual stores, retrieval, or workflow modules.
The work is done when every current resource is reachable through the facade, unsafe SQL is blocked before execution, production analysis uses the persistent database, focused tests pass, and no conversation-agent-owned file changed.
