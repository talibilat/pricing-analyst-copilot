# Task 1 report: validated free-form SQL over the analytics database

## What was built

A second query path on `PersistentAnalyticsDatabase` (in
`src/pricing_copilot/data/persistent.py`) that accepts raw free-form SQL text
from a chat model and executes it safely, alongside the existing structured
`plan_query`/`execute_plan`/`query_source` path (which is unchanged).

New public surface:

- `FreeformSqlRequest(sql: str, scenario: ScenarioName)` - frozen dataclass; a
  container for untrusted SQL text plus the closed-enum scenario it must be
  scoped to.
- `FreeformSqlResult(sql, columns, rows, scenario, database_version)` - frozen
  dataclass carrying the executed SQL, result column names, capped rows, the
  scenario, and `ANALYTICS_DATABASE_VERSION`.
- `PersistentAnalyticsDatabase.run_freeform_sql(request) -> FreeformSqlResult` -
  validates then executes.
- `PersistentAnalyticsDatabase.execute_freeform_sql(sql, scenario) ->
  FreeformSqlResult` - convenience wrapper mirroring `query_source`.
- `validate_freeform_sql(sql) -> frozenset[str]` - module-level pure validator;
  raises `ValueError` naming the first violation, returns the referenced base
  tables. Nothing is executed during validation.
- Module constants `FREEFORM_ROW_LIMIT = 200` and internal `_SCENARIO_COLUMN`.

Every validation failure raises a plain `ValueError` whose message starts with
`Free-form SQL rejected:` and names what was rejected, matching the project's
existing `ValueError`-for-policy convention.

## How validation works (AST, not regex)

Validation uses DuckDB's built-in `json_serialize_sql(?)` scalar function, run on
a throwaway in-memory connection with the SQL bound as a parameter. This is the
same parser that will execute the query, so there is no dialect-mismatch risk,
and nothing from the SQL is executed. Controls (default-deny):

1. If the serializer returns `error: true` the statement is rejected. DuckDB's
   serializer only serializes SELECT statements, so `INSERT`/`UPDATE`/`DELETE`/
   `CREATE`/`DROP`/`ALTER`/`ATTACH`/`COPY`/`EXPORT`/`SET`/`LOAD`/`PRAGMA` and any
   `SELECT ...; DROP ...` mixed stack all fail here.
2. Exactly one statement must be present (`len(statements) == 1`). This is the
   defense against a two-`SELECT` stack (`SELECT ...; SELECT ...`), which DuckDB
   does serialize as two statements.
3. The single statement's `node.type` must be exactly `SELECT_NODE`.
4. The entire parsed tree is walked recursively (`_iter_ast_nodes`). For every
   `from_table`:
   - `TABLE_FUNCTION` (read_csv/read_parquet/generate_series/external files) is
     rejected outright.
   - `BASE_TABLE` must have empty `schema_name` and `catalog_name` (any
     `main.claims` or `catalog.schema.table` form is rejected) and its
     `table_name` must be one of the four allowlisted tables - unless it names a
     CTE defined in the query (CTE names surface as `BASE_TABLE` references).
   - `JOIN` and `SUBQUERY` are handled naturally because the walk recurses into
     the whole tree, so each nested `BASE_TABLE`/`COLUMN_REF` is validated.
5. Every `COLUMN_REF`'s last `column_names` segment must not be `scenario`
   (explicit reject with a scenario-specific message) and must resolve to an
   allowlisted column of a referenced table, a CTE name, or an alias the query
   itself introduces. Collecting output aliases (the non-empty `alias` fields)
   avoids false positives on legal queries that `ORDER BY`/`HAVING` an alias.

## How scenario scoping works (not by trusting a WHERE clause)

`run_freeform_sql` opens the DuckDB file **read-only** (`read_only=True`), calls
`self.ensure()` first (same as `execute_plan`), then before running the user SQL
creates four scenario-scoped temp views that shadow the base table names on the
same connection:

```
CREATE TEMP VIEW <table> AS SELECT <allowlisted columns>
FROM "<current_catalog()>".main.<table>
WHERE scenario = '<scenario.value>'
```

- The projection lists only `SOURCE_TABLES[table]` columns (never `*` and never
  `scenario`), so the scenario column structurally does not exist in the
  queryable namespace - this is the primary control; the AST column check is the
  fast, user-facing fail path.
- `scenario.value` is inlined (not bound): DDL cannot be parameterized in DuckDB
  (`Binder Error: Unexpected prepared parameter`), and the value only ever comes
  from the closed `ScenarioName` enum, so there is no injection surface.
- The source is qualified with the live `current_catalog()` value (e.g.
  `"synthetic".main.claims`), never the literal `main`, to avoid
  `Binder Error: infinite recursion detected` from the shadowing temp view.
- Because all four base tables get their own scoped view, cross-table joins are
  automatically scoped on both sides.

Temp views live in the in-memory temp schema, so creating them on a read-only
connection is allowed (verified).

## How row capping works

After execution, `cursor.fetchall()` results are sliced to
`FREEFORM_ROW_LIMIT` (`rows[:200]`) in Python. This is correct for every case,
including queries with their own `LIMIT`/`ORDER BY` (a caller `LIMIT 5` yields 5;
a 576-row cross join yields exactly 200).

## Tests added (`tests/test_persistent_data.py`)

A `database` fixture builds the artifact once; `_row_count` reads a scenario's
row count via a second read-only connection to prove non-execution.

Allowed shapes (each asserts real rows / correct columns):

- `test_freeform_allows_projection_and_filter` - projection + WHERE filter.
- `test_freeform_run_request_object_returns_full_metadata` - the
  `run_freeform_sql(FreeformSqlRequest(...))` entry point returns executed SQL,
  columns, scenario, and database version.
- `test_freeform_allows_aggregate_alias_and_ordering` - `SUM ... AS total_loss
  ... GROUP BY ... ORDER BY total_loss` (aggregate + alias + ordering by alias).
- `test_freeform_allows_common_table_expression` - `WITH ... SELECT`.
- `test_freeform_allows_join_across_two_allowlisted_tables` - join of `claims`
  and `conversion`.

Rejected shapes (each asserts the specific `ValueError` and that no rows come
back; `_assert_rejected_without_execution` helper):

- `test_freeform_rejects_stacked_statements` - `SELECT ...; DROP TABLE claims`.
- `test_freeform_rejects_stacked_select_statements` - two stacked SELECTs
  (proves the `len == 1` guard).
- `test_freeform_rejects_mutations` (parametrized) - INSERT, UPDATE, DELETE,
  CREATE TABLE, DROP TABLE, ALTER TABLE.
- `test_freeform_rejects_unknown_table` - `customers`.
- `test_freeform_rejects_schema_or_catalog_qualified_access` (parametrized) -
  `main.claims`, `synthetic.main.claims`.
- `test_freeform_rejects_table_functions_and_external_files` (parametrized) -
  `read_csv('/etc/passwd')`, `read_parquet(...)`, `generate_series(...)`.
- `test_freeform_rejects_extensions_pragmas_attach_copy_export` (parametrized) -
  PRAGMA, ATTACH, COPY, EXPORT DATABASE, SET, LOAD.
- `test_freeform_rejects_non_catalogue_column` - `customer_id`.
- `test_freeform_rejects_direct_scenario_column_reference` - `SELECT scenario`.
- `test_freeform_rejects_scenario_bypass_in_where_clause` - `WHERE scenario =
  'retention_concern'`.
- `test_freeform_scenario_filter_always_wins` - same SQL under two scenarios
  returns scenario-confined, differing row sets, and the controlled count
  matches the raw scenario row count.
- `test_freeform_caps_result_rows_at_two_hundred` - 24x24 cross join capped to
  exactly 200.
- `test_freeform_row_cap_holds_with_explicit_limit_and_order` - caller `LIMIT 5`
  respected.
- `test_freeform_rejection_leaves_database_intact` - claims row count unchanged
  after a rejected stacked-DROP attempt.

## Verification commands and output

- `uv run pytest tests/test_persistent_data.py -q` -> `36 passed in 4.07s`.
- `uv run ruff check src/pricing_copilot/data/persistent.py
  tests/test_persistent_data.py` -> `All checks passed!`.
- `uv run mypy src/pricing_copilot/data/persistent.py` -> `Success: no issues
  found in 1 source file`.
- `uv run pytest -q` (full suite) -> `302 passed, 4 skipped` plus 10 pre-existing
  failures in `test_api.py`, `test_cli.py`, `test_recommendation_live.py`,
  `test_streamlit_chat_e2e.py`, `test_workflow.py`. These are all replay /
  streamlit / model-workflow tests; confirmed pre-existing by stashing my two
  files and re-running two of them on the clean tree (both still failed). They
  are unrelated to this task and outside my ownership.

## Concerns

- The assigned brief file `.superpowers/sdd/task-1-brief.md` did not exist in
  this worktree (nor anywhere under the repo). I proceeded from the fully
  detailed requirements embedded in the task prompt itself (controls,
  interfaces, and exhaustive test list), which appear to be verbatim from the
  plan. Flagging in case the missing brief indicates a worktree-sync gap.
- The AST `COLUMN_REF` check accepts any query-introduced alias as a valid
  column identifier (needed so `ORDER BY <alias>` works). This is intentional
  defense-in-depth only: the scenario column is explicitly rejected regardless,
  and the shadowing views - which never project `scenario` - are the primary
  guarantee that scenario cannot leak even if the column check were bypassed.
- `SELECT *` is allowed and produces no `COLUMN_REF` to validate; it is safe
  because the temp views project only allowlisted columns, so `*` cannot expand
  to `scenario` or any non-catalogue field.
