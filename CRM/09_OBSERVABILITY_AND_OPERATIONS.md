# Observability and Operations

## Three separate records

1. **Operational telemetry:** metrics, logs, and distributed traces for service health.
2. **Decision trace:** evidence, model/prompt, agents, confidence, policy, and proposal lineage.
3. **Audit ledger:** security- and business-relevant actions, approvals, access, and configuration changes.

They share correlation identifiers but have different access and retention. Debug tracing is not a substitute for an audit ledger.

## Trace propagation

Use W3C Trace Context/OpenTelemetry conventions through HTTP, events, workflows, tools, model calls, and connector calls. Preserve:

- trace and span IDs;
- workflow run/correlation/causation IDs;
- tenant identifier in controlled attributes, not unrestricted metric labels;
- provider request IDs;
- model route and prompt/agent version;
- action idempotency key and receipt reference.

Sensitive content is excluded by default. Operators diagnose from hashes, types, sizes, codes, timings, and authorised break-glass views.

## Dashboards

### Executive/product

Active users, completed workflows, time saved estimate, acceptance/edit/rejection, opportunity progression, retention, and cost per verified workflow.

### AI quality

Grounding, unsupported claim rate, confidence calibration, abstention, override/edit severity, retrieval relevance/completeness, prompt/model cohorts, drift, and evaluation gate state.

### Integration

Connection health, subscription renewal, event age, throttle rate, permission failures, backfill/reconciliation divergence, action verification, and provider incidents.

### SRE

Availability, latency, saturation, queue lag, retries, circuit state, error budgets, database health, cell/tenant skew, regional readiness, and cost anomalies.

### Governance

High-risk action volume, approval/expiry, policy denials, opt-outs, data-subject requests, deletion SLA, admin changes, unusual access, and kill-switch state.

## Alert philosophy

Alerts must be actionable and mapped to a runbook. Page only for immediate customer/risk impact; create tickets for slower degradation.

Page examples:

- suspected cross-tenant access;
- external action without valid approval;
- duplicate message/send;
- opt-out suppression failure;
- significant event backlog or action verification collapse;
- audit pipeline loss;
- regional outage.

Ticket examples:

- calibration drift;
- rising edit severity;
- renewal success decline with sufficient headroom;
- cost per workflow regression;
- non-critical evaluation slice decline.

## Runbooks

Required before pilot:

- revoke/rotate compromised connector;
- suspend one tenant/workflow/model/prompt/action;
- recover subscription and reconcile gap;
- handle ambiguous email/CRM write;
- drain dead-letter queue safely;
- model-provider outage/fallback;
- policy service outage;
- suspected cross-tenant exposure;
- inaccurate recommendation cluster;
- prompt-injection incident;
- objection/opt-out failure;
- regional failover and failback;
- restore and validate backup;
- data deletion failure;
- model rollback.

## AI incident severity

- SEV-0: confirmed cross-tenant disclosure or uncontrolled consequential action.
- SEV-1: repeated unauthorised external action, material privacy/security issue, or widespread harmful fabrication.
- SEV-2: material workflow-quality regression with human approval still containing harm.
- SEV-3: isolated quality/latency issue without material impact.

Incident review records technical root cause, evaluation gap, control failure, customer impact, data impact, containment, regression case, owner, and due date.

## Production feedback loop

Feedback is typed:

- accept unchanged;
- accept with minor/major edit;
- reject as incorrect, unsupported, irrelevant, unsafe, stale, wrong recipient, wrong tone, wrong CRM field, duplicate, or other;
- later correction/undo;
- execution failure;
- complaint/opt-out.

Do not automatically fine-tune on all feedback. Samples require purpose, provenance, authorisation, deduplication, quality review, privacy checks, and train/eval separation.
