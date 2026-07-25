# Engineering Delivery Plan

## Team topology

Minimum cross-functional team:

- staff/principal architect accountable for system boundaries;
- product manager and sales-domain lead;
- two integration engineers;
- two platform/backend engineers;
- two AI/ML engineers;
- frontend/product engineer;
- data/analytics engineer;
- SRE/platform engineer;
- security engineer;
- privacy/legal partner;
- QA/evaluation lead and domain labellers.

These are responsibilities, not necessarily full-time headcount at prototype stage. Security, privacy, SRE, and evaluation cannot be deferred to “after MVP.”

## Repository and module layout

```text
apps/
  workspace-web/
  admin-console/
services/
  control-plane/
  event-ingress/
  workflow-workers/
  ai-runtime/
  policy/
  action-gateway/
connectors/
  salesforce/
  microsoft-graph/
  teams/
  slack/
packages/
  domain/
  connector-contract/
  event-schemas/
  evidence/
  agent-contracts/
  policies/
  telemetry/
evals/
  datasets/
  graders/
  scenarios/
  reports/
infra/
  environments/
  modules/
docs/
```

Keep a monorepo initially for atomic contract changes and discoverability. Enforce module boundaries and ownership. Split repositories only for a concrete security, release, or organisational reason.

## Environments

- local with fake providers and synthetic data;
- shared development;
- ephemeral PR environment for integration/UI changes;
- Salesforce and Microsoft sandbox integration;
- staging with production-like policy and load;
- isolated evaluation/red-team;
- UK production cells;
- disaster-recovery environment.

No production customer content is copied to lower environments.

## API and schema discipline

- OpenAPI/JSON Schema or equivalent for synchronous contracts;
- schema registry for events;
- backward-compatible additive change by default;
- consumer-driven contract tests;
- generated clients;
- deprecation window and usage telemetry;
- expand/migrate/contract database changes;
- canonical model does not leak provider SDK types.

## CI gates

1. format/lint/type/unit tests;
2. secret, dependency, licence, SAST, and IaC checks;
3. schema compatibility and migration checks;
4. tenant-isolation and authorisation tests;
5. connector contract tests against simulators;
6. AI deterministic and fast regression suite;
7. artefact signing/SBOM;
8. preview deployment and smoke tests.

Nightly/on-demand:

- sandbox end-to-end integrations;
- full AI evaluation;
- adversarial/prompt-injection tests;
- load/fault tests;
- deletion and restore tests.

## Delivery slices

### Foundation

Tenant/identity, policy skeleton, audit, event envelope, workflow engine, connector/action contracts, evidence schema, evaluation harness, telemetry, and deployment cell.

### Salesforce read path

Admin connection, least-privilege scopes, metadata mapping, canonical projection, event/reconciliation, sandbox certification.

### Microsoft meeting context

Entra consent, Outlook/Calendar/meeting event path, transcript policy, identity resolution, evidence assembly.

### AI post-meeting package

Meeting analysis, CRM mapping, draft/task/internal update, evidence viewer, confidence/abstention, offline evaluation.

### Approval and writes

Immutable proposal, field-level diff, action tokens, Salesforce writes, email send, Teams/Slack post, verification, ambiguous-timeout handling.

### Additional workflows

Inactive opportunity, inbound response, lead qualification, social signal, manager digest.

### Expansion

HubSpot, Dynamics, additional regions, isolation tiers, connector SDK.

## Definition of done for a workflow

- approved threat model and data-flow record;
- user story and failure/abuse cases;
- versioned event/input/output/action schemas;
- permission, purpose, policy, and approval controls;
- idempotency/reconciliation;
- evidence and explanation UI;
- task-specific evaluation thresholds and report;
- load and fault test;
- metrics, alerts, runbook, and ownership;
- retention/deletion coverage;
- accessibility and usability review;
- sandbox pilot and rollback/kill switch.

## Test strategy

- unit/property tests for domain and policy logic;
- generative tests for malformed events and schemas;
- contract tests for every connector;
- state-machine tests for all workflow transitions;
- model-free deterministic fixtures;
- recorded/provider-approved sandbox interactions;
- AI golden/adversarial/longitudinal evaluations;
- chaos tests for providers, queues, database, and model;
- security tests for injection, tenant escape, SSRF, secrets, and over-permission;
- human exploratory QA with sales representatives, AEs, managers, and Sales Ops.

## Rollout

Internal synthetic/sandbox → design-partner shadow mode → read-only recommendations → approval-required writes → tenant opt-in low-risk automation → broader availability.

Use per-tenant flags and version pinning. Canary by tenant/workflow, not random individual request when behaviour consistency matters. Rollback stops new runs while allowing safe completion or cancellation of in-flight work.

## Design-partner contract

Each partner agrees on:

- users and workflows;
- systems/scopes and sandbox access;
- baseline metrics;
- data processing and evaluation use;
- prohibited actions;
- named product, Sales Ops, IT/security, and privacy contacts;
- weekly review and incident path;
- success/exit criteria.
