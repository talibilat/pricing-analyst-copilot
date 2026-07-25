# Release Manifest

Generated 2026-07-25T23:56:23.937970+00:00 by `scripts/generate_release_manifest.py` from the running application's own configuration - not hand-typed.

- Application commit: `c7dc2fd2b39336de5f9228adf740cf709b54f195`
- Model: `gpt-5.4`
- Recommendation version: `governed-multi-agent-v1`
- Governance version: `deterministic-governance-v1`
- Prompt version: `governed-prompts-v2`
- Agent registry version: `approved-agent-registry-v1`
- Tool version: `deterministic-read-only-tools-v2`
- Recommendation policy version: `recommendation-policy-v2`
- Output schema version: `workflow-result-schema-v1`
- Scenario dataset version: `v1` (seed `20260101`)
- Analytics database version: `synthetic-portfolio-duckdb-v2`
- Max price movement policy: 5.0%
- Golden evaluation set version: `golden-set-v1`
- Drift report version: `drift-report-v1`

## Persistent dataset schema catalogue and row counts

| Table | Permitted columns | Row count | Access | Source version |
|---|---|---|---|---|
| `claims` | 9 | 97 | read_only_portfolio_level | `v1` |
| `conversion` | 10 | 161 | read_only_portfolio_level | `v1` |
| `competitors` | 5 | 291 | read_only_portfolio_level | `v1` |
| `pricing_history` | 9 | 4 | read_only_portfolio_level | `v1` |

## Latest evaluation report

- Report version: `benchmark-report-v1`
- Golden set version: `golden-set-v1`
- Governed cases: 18 passed, 0 failed, 0 errored

## Latest drift report

- Report version: `drift-report-v1`
- 17 total alerts, 6 material
