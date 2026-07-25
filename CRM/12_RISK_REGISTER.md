# Risk Register and Failure Analysis

Scoring: likelihood (L) and impact (I) are 1–5; exposure is `L × I`. Scores are pre-treatment hypotheses and must be reviewed with design partners.

| ID | Risk/failure | L | I | Prevent/detect/respond | Owner |
|---|---|---:|---:|---|---|
| R-01 | Cross-tenant data exposure | 2 | 5 | Trusted tenant context, storage policy/RLS, cell isolation, adversarial tests, access anomaly alert, global kill switch | Security/platform |
| R-02 | Prompt injection causes disclosure/action | 4 | 5 | Treat all source content as data, narrow typed tools, no credentials, policy/action gateway, injection evals | AI security |
| R-03 | Unsupported claim reaches customer | 3 | 5 | Claim-level evidence, verifier, material-claim gate, approval, sampled audit | AI quality |
| R-04 | Wrong recipient/message sent | 2 | 5 | Recipient resolution outside model, frozen payload approval, recheck, domain warning, verification | Messaging |
| R-05 | Duplicate external action | 3 | 5 | Durable effect ledger, idempotency key, ambiguous-timeout reconciliation, no blind send retry | Platform |
| R-06 | Stale CRM overwritten | 3 | 4 | Version/ETag, field diff, approval expiry, pre-execution read, conflict UI | Salesforce |
| R-07 | Event lost or arrives out of order | 4 | 4 | Durable ingress, dedupe, replay cursor, lifecycle handling, reconciliation | Connectors |
| R-08 | Provider quota exhausted | 4 | 4 | Observed quota, hierarchical rate budgets, priority queues, backpressure, degradation | Connectors/SRE |
| R-09 | Connection permission silently revoked | 3 | 4 | Health checks, lifecycle events, permission probes, suspend dependent inference | Connectors |
| R-10 | Social integration violates platform terms | 3 | 5 | Official APIs only, runtime capability flags, no scraping, quarterly access review | Product/legal |
| R-11 | Marketing message lacks lawful basis/PECR condition | 3 | 5 | Deterministic channel policy, consent/suppression ledger, pre-send recheck, legal review | Privacy |
| R-12 | Opt-out not propagated | 2 | 5 | Priority event path, tombstone/suppression, send-time check, end-to-end test | Privacy/CRM |
| R-13 | Current UK ADM rules misimplemented | 3 | 5 | Versioned legal policy, DUAA watch, counsel sign-off, contest/human safeguards | Legal/privacy |
| R-14 | Sensitive traits inferred or used | 2 | 5 | Prohibited feature catalogue, schema/DLP, dataset review, bias tests, policy denial | AI governance |
| R-15 | Confidence is misleading | 4 | 4 | Empirical calibration, reliability plots, risk-coverage, task labels, no self-report | ML |
| R-16 | Human rubber-stamps recommendations | 4 | 4 | Evidence-first UI, material diff, friction by risk, sampling, review-time/override analysis | Product/risk |
| R-17 | Deal-health model disadvantages a cohort | 3 | 4 | Feature ban/proxy review, slice evaluation, appeals, monitor, no consequential autonomy | ML/privacy |
| R-18 | Training/evaluation leakage inflates scores | 3 | 4 | Tenant/time split, dedupe, sealed holdout, provenance, independent review | Evaluation |
| R-19 | Production distribution drifts | 4 | 4 | Input/feature/quality/calibration drift, shadow labels, thresholds, rollback | ML/SRE |
| R-20 | Model/provider changes silently | 3 | 4 | Snapshot/version registry, change monitor, canary, frozen eval, approved fallback | AI platform |
| R-21 | Model outage blocks core workflow | 3 | 3 | Durable workflow, approved fallback, manual path, clear status, retry budget | AI platform |
| R-22 | Agent loop causes runaway cost/latency | 3 | 4 | DAG, max turns/tools/tokens/time, budget enforcement, cancel/kill switch | AI platform |
| R-23 | Retrieved content is stale/incomplete | 4 | 4 | Freshness/evidence coverage, current fetch for material fields, abstention | Evidence |
| R-24 | Identity resolution links wrong person | 3 | 5 | Deterministic match first, ambiguity margin, candidate review, no auto-merge | Identity |
| R-25 | Transcript notice/permission inadequate | 3 | 5 | Tenant policy, meeting/transcript consent process, minimisation, fallback | Privacy/product |
| R-26 | Sensitive data leaks through logs/traces | 3 | 5 | Allowlist telemetry, redaction, sensitive SDK trace disabled, access/retention | SRE/security |
| R-27 | Deletion misses embeddings/cache/evals/backups | 3 | 5 | Data lineage registry, deletion orchestrator, tombstone, periodic proof test | Privacy/data |
| R-28 | One tenant starves shared system | 4 | 4 | Fair queues, quotas, cells, per-tenant concurrency/cost, load tests | Platform |
| R-29 | Regional failover double-executes actions | 2 | 5 | Fencing, single active writer, effect ledger, failover exercise | SRE |
| R-30 | Custom Salesforce schema breaks mapping | 4 | 3 | Schema discovery, tenant mapping, typed unknowns, sandbox certification | Salesforce |
| R-31 | Business KPI correlation mistaken for causality | 4 | 3 | Baselines, phased/matched cohorts, confounder review, transparent claims | Product/data |
| R-32 | Users do not trust/use the workflow | 3 | 5 | Evidence, control, visible status, workflow-native UX, design partners, edit feedback | Product |
| R-33 | Prototype hardens into unscalable design | 3 | 4 | Architecture fitness tests, modular contracts, capacity triggers, roadmap debt register | Architecture |
| R-34 | Premature microservices slow delivery | 3 | 3 | Modular monorepo/control plane, extract only on measured scaling/security need | Architecture |
| R-35 | Connector supply-chain compromise | 2 | 5 | SBOM, signed artefacts, dependency scanning, token isolation, egress control | Security |
| R-36 | Admin over-consents broad access | 3 | 5 | Least-scope defaults, scope explanation, optional broad features, access review | Security/product |
| R-37 | Approval is replayed or payload changes | 2 | 5 | Signed single-use token bound to exact payload/hash, actor, expiry, action | Action gateway |
| R-38 | Partial action package confuses user | 3 | 4 | Saga state, per-action receipt, explicit partial state, safe retry/compensation | Product/platform |
| R-39 | Social API capability unavailable at launch | 4 | 3 | Not a launch dependency, manual deep links, capability negotiation | Product |
| R-40 | Evaluation misses realistic enterprise slice | 4 | 4 | Design-partner data under agreement, slice inventory, failure-to-regression loop | Evaluation |

## Pre-mortem: assume the pilot failed

### Failure story 1: “It wrote polished but wrong follow-ups”

Likely causes: incomplete retrieval, speaker attribution errors, unsupported synthesis, approval fatigue. Early indicators: material edits, citation misses, later corrections, falling trust. Stop condition: any critical unsupported commitment or repeated customer-facing factual error. Response: suspend send path, return to shadow, add regression cases, fix evidence/threshold - not prompt wording alone.

### Failure story 2: “It became another dashboard”

Likely causes: poor embedded UX, no reliable write-back, too many approvals, slow drafts. Indicators: users read summaries but do not complete actions. Response: measure each step, simplify one approval package, embed in Outlook/Salesforce/Teams, automate only proven internal actions.

### Failure story 3: “Enterprise security blocked deployment”

Likely causes: broad Graph scopes, unclear data retention/model use, weak deletion, no isolation proof. Indicators: security questionnaire exceptions and prolonged DPA review. Response: offer delegated/minimal scope, ZDR-compatible path where feasible, evidence of isolation/deletion tests, dedicated tiers.

### Failure story 4: “Integrations collapsed at scale”

Likely causes: polling, quota assumptions, retry storms, backfills sharing interactive capacity. Indicators: queue age, 429s, subscription churn, cost spikes. Response: halt backfills, reserve writes, reconcile, cell/shard, renegotiate capacity only after traffic is controlled.

### Failure story 5: “The AI score created legal or fairness risk”

Likely causes: proxy features, misunderstood UK rules, opaque confidence, operational dependence on score. Indicators: subgroup gaps, appeals, sellers refusing low-scored leads. Response: recommendation-only mode, remove feature/model, legal review, re-evaluate intended purpose and safeguards.

## Go/no-go rules

No-go if any of the following is unresolved:

- cross-tenant or unauthorised access path;
- external effect possible without valid policy and approval;
- no reliable opt-out/suppression check;
- no current UK legal review for the actual workflow/data/channel;
- model quality lacks task-specific evidence and calibrated threshold;
- provider permission/API access is assumed but not granted;
- deletion or incident kill switch is untested;
- ambiguous external writes can duplicate effects;
- pilot users cannot inspect evidence and correct the proposal.

## Risk review cadence

- daily during incident or red-team exercise;
- weekly during design-partner pilot;
- monthly product/AI risk committee;
- quarterly legal/vendor/API watchlist;
- immediately after material workflow, model, prompt, connector, data, or legal change.
