# Requirement Traceability Matrix

This matrix prevents major requirements from disappearing between strategy, design, delivery, and validation.

| Requirement | Design location | Verification/evidence |
|---|---|---|
| Mid-market and enterprise, scalable | `01`, `03`, `08` | Tenant-skew load, cell placement, quota/isolation tests |
| Representatives, AEs, managers, Sales Ops | `README`, `02`, `10` | Role-based usability and permission tests |
| Multiple workflows | `02` | Per-workflow definition-of-done and end-to-end eval |
| Post-meeting summary | `02`, `05` | Factual precision/recall and evidence correctness |
| Salesforce update | `04`, `05` | Sandbox contract, stale-write, read-back verification |
| Draft/send email | `02`, `04`, `05` | Recipient, policy, approval, ambiguous-timeout tests |
| Create tasks | `02`, `05` | Owner/due-date/action idempotency tests |
| Teams and Slack update | `02`, `04` | Rate, visibility, duplicate, notification UX tests |
| Detect inactive opportunities | `02`, `05` | Longitudinal point-in-time backtest and calibration |
| Social engagement | `02`, `04`, `12` | Runtime capability/API-policy review; no-scraping test |
| Salesforce then HubSpot/Dynamics | `01`, `04`, `11` | Connector certification suite |
| Microsoft 365 first | `01`, `04` | Entra/Graph sandbox and scope review |
| UK first | `01`, `07` | UK policy pack, counsel sign-off, DPIA |
| GDPR/DPA/DUAA/PECR | `07`, research | Control mapping and current legal review |
| SOC 2/ISO 27001/42001/NIST/OWASP | `07`, research | Assurance plan, AI inventory, threat/eval evidence |
| AI-first information gathering | `05` | Retrieval relevance/completeness/leakage eval |
| AI decision support | `05` | Claim/action rubric and human usefulness |
| Complex multi-agent design | `05` | Agent contract, DAG, tool/budget/failure tests |
| Confidence | `05`, `06` | Calibration, Brier/ECE, risk-coverage |
| Answer/source trace | `05`, `09` | Evidence locator and end-to-end lineage tests |
| Detailed evaluation | `06` | Signed release report and slice gates |
| Feature engineering | `02`, `05` | Point-in-time correctness and online/offline parity |
| Governance and risk | `07`, `12` | Committee review, risk treatments, go/no-go |
| Evaluation and monitoring | `06`, `09` | Pre-release gates and production dashboards |
| Technical delivery | `10` | CI evidence and definition-of-done |
| Roadmap | `11` | Phase exit evidence |
| Success metrics | `11` | Baseline and pilot scorecard |
| Data isolation and privacy | `03`, `07`, `08` | Cross-tenant, deletion, restoration, access tests |
| Reliability at scale | `03`, `04`, `08` | Burst/soak/fault/reconciliation/failover tests |
| Human approval | `02`, `05`, `07` | Payload-bound approval token and replay tests |
| Auditability | `03`, `05`, `09` | Audit completeness and tamper/access tests |
| Provider portability | `03`, `05` | Model and connector contract conformance |
| Pessimistic failure analysis | `03`, `06`, `08`, `12` | Fault injection, pre-mortem, no-go review |
| Primary references | `research/PRIMARY_SOURCES.md` | Quarterly watchlist review |

## Cross-cutting release evidence pack

Every production workflow release contains:

1. versioned workflow, event, agent, evidence, policy, and action schemas;
2. architecture and data-flow diagram;
3. threat model, privacy assessment, and legal-policy version;
4. permissions and connector capability report;
5. AI evaluation report with dataset/slices/calibration;
6. deterministic, contract, security, load, and fault-test reports;
7. current risk register and accepted residual risks;
8. operational dashboard, alerts, runbooks, and on-call owner;
9. migration, canary, rollback, and kill-switch plan;
10. product metric baseline and pilot/rollout decision.
