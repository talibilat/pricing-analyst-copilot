# Roadmap and Success Metrics

Durations are planning ranges, not commitments. Parallel work is possible only after contracts and safety boundaries are stable.

## Phase 0 - discovery and risk closure (weeks 0–4)

- recruit 3–5 UK design partners;
- map real Salesforce/Microsoft schemas and permission models;
- baseline seller administration/follow-up/CRM quality;
- complete threat model, DPIA inputs, and legal analysis;
- secure provider sandbox/API access;
- build evaluation rubric and first 200–500 representative cases;
- confirm SLO/capacity/cost hypotheses.

Exit: signed workflow definition, data access, risk owners, baseline, and initial eval set.

## Phase 1 - platform foundation (weeks 3–10)

- tenant identity/control plane;
- connector/event/action contracts;
- Salesforce read connector;
- workflow engine and evidence graph;
- policy/audit/telemetry;
- AI gateway and evaluation harness;
- UK deployment cell.

Exit: synthetic and sandbox events execute end to end with no external write.

## Phase 2 - post-meeting shadow pilot (weeks 8–16)

- Microsoft Calendar/meeting/transcript ingestion;
- meeting analysis, CRM mapping, email/task/internal drafts;
- evidence UI, confidence, abstention;
- shadow comparison with human outcomes;
- security/red-team/load testing.

Exit: quality gates met on holdout and partner shadow data.

## Phase 3 - approval-based execution (weeks 14–22)

- approval package;
- Salesforce/task/email/Teams/Slack actions;
- verification, idempotency, reconciliation;
- production pilot with 20–50 users per partner;
- weekly quality and governance review.

Exit: reliable verified actions, acceptable trust/edit metrics, no critical incidents.

## Phase 4 - multiple workflows (weeks 20–32)

- inactive opportunity and manager digest;
- inbound response with opt-out priority;
- lead qualification;
- permitted social signals;
- initial learned deal ranking if data gates pass.

Exit: shared platform handles multiple workflows without duplicated control logic.

## Phase 5 - scale and expansion (weeks 28–48)

- HubSpot then Dynamics;
- self-service admin and connector certification;
- cell sharding and enterprise isolation tiers;
- additional UK customers;
- EU/US policy and regional deployment discovery;
- bounded low-risk automation for opted-in tenants.

## North-star and guardrail metrics

### North-star

Weekly active sellers who complete at least one integrated workflow with a verified outcome.

### Adoption

- eligible-user activation;
- weekly/monthly retained users;
- workflows completed/user/week;
- cross-workflow adoption;
- manager and Sales Ops usage;
- time to first verified value.

### Efficiency

- meeting-to-follow-up time;
- seller administration minutes saved, periodically time-studied;
- CRM field completeness/freshness;
- overdue-task reduction;
- manual system switches per workflow.

### AI quality

- supported material-claim rate;
- task precision/recall;
- evidence-locator correctness;
- confidence calibration;
- correct abstention;
- approval acceptance and edit severity;
- wrong-recipient/field/action rate;
- regression by slice.

### Reliability and scale

- terminal and verified workflow rate;
- p50/p95 latency and event age;
- duplicate external effects;
- provider throttle/reconciliation divergence;
- SLO/error budget;
- cost per verified workflow;
- capacity by tenant and cell.

### Business outcome

- opportunity progression;
- response and meeting-booked rates;
- sales-cycle duration;
- conversion/win rate;
- product retention/expansion.

Use matched cohorts or phased rollout where feasible. Do not claim causal revenue lift from simple before/after correlation.

### Trust, governance, and safety guardrails

- external action without approval: target zero;
- cross-tenant exposure: target zero;
- suppression/objection breach: target zero;
- material unsupported claims;
- complaints and undo/correction;
- access/policy violations;
- deletion SLA;
- critical incidents and time to contain;
- seller perception of control and explanation usefulness.

## Pilot success proposal

Agree exact values after baselining. Suggested directional gates:

- at least 60% of eligible pilot sellers complete a workflow weekly by the final four weeks;
- median meeting-to-approved-follow-up improves by at least 50%;
- at least 80% of shown post-meeting packages are accepted, with major-edit rate below 15%;
- material unsupported claims below the agreed safety ceiling and no critical slice failure;
- verified action success at least 99.5% excluding declared provider outage;
- no unauthorised send, cross-tenant exposure, or suppression failure;
- a majority of users report meaningful weekly time saved;
- unit cost supports target gross margin.

## Commercial packaging

- core Salesforce/Microsoft/Teams/Slack integrations included in per-user product tier;
- enterprise governance tier for SSO/SCIM, audit export, retention, regional storage, dedicated keys/networking, advanced policy, and isolation;
- custom connector/professional services separately scoped;
- usage guardrails transparent; avoid pricing that discourages completing the workflow.
