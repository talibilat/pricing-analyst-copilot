# Workflows and Requirements

## Common workflow state machine

`RECEIVED → VALIDATED → CONTEXT_READY → ANALYSED → POLICY_CHECKED → PROPOSED → AWAITING_APPROVAL → EXECUTING → VERIFIED → COMPLETED`

Exceptional states: `ABSTAINED`, `PARTIALLY_COMPLETED`, `RETRY_SCHEDULED`, `DEAD_LETTERED`, `CANCELLED`, and `COMPENSATION_REQUIRED`.

Every transition records tenant, actor, reason, evidence set, policy version, workflow definition version, model/prompt versions, timestamps, and correlation identifiers.

## WF-1: Post-meeting follow-up

### Trigger

An authorised meeting ends and a transcript or approved notes become available.

### Flow

1. Resolve participants to CRM identities; leave ambiguous matches unresolved.
2. retrieve the opportunity, account, recent activities, open tasks, and relevant approved playbook;
3. separate facts, commitments, questions, risks, objections, and proposed next steps;
4. generate an evidence-linked summary;
5. propose safe Salesforce field updates;
6. draft an Outlook follow-up email;
7. create proposed tasks with owners and due dates;
8. prepare a Teams and/or Slack internal update;
9. run grounding, policy, recipient, tone, claim, and sensitive-data checks;
10. show one approval package;
11. execute only selected actions using idempotency keys;
12. read back external records and verify the effects.

### Always require approval

- email recipients and sending;
- any externally visible message;
- opportunity stage/value/date/owner changes;
- novel claims or commitments;
- tasks assigned to people other than the approving user.

### Key acceptance measures

- factual-summary precision and recall;
- commitment and next-step extraction F1;
- CRM-field proposal precision;
- citation/evidence correctness;
- send-recipient correctness;
- median meeting-to-approved-follow-up time;
- percentage of actions accepted without material edits.

## WF-2: Lead capture and qualification

### Triggers

Authorised web form, campaign response, inbound message, event list, or permitted social signal.

### Flow

Deduplicate identity → validate consent/source → enrich only from approved sources → map account/contact → extract explicit needs → score using transparent features → propose Salesforce Lead/Contact creation → assign using deterministic territory rules → notify owner.

Lead score is advisory. It must show contributing evidence and must not infer protected or sensitive traits. Where a social signal lacks a stable authorised identifier, create a review item rather than a CRM person record.

## WF-3: Inbound response

### Trigger

An email or supported message arrives in a monitored, authorised scope.

### Flow

Classify intent and urgency → match CRM context → detect opt-out or objection before any other action → identify direct questions → draft an answer with cited account facts → propose CRM activity and task updates → obtain approval → send and verify.

Opt-out, legal threat, complaint, security report, procurement restriction, and sensitive-data cases bypass normal drafting and route to a human queue.

## WF-4: Inactive opportunity

### Trigger

A scheduled feature computation or relevant CRM/activity event changes the deal-health state.

### Initial transparent features

- days since last meaningful customer interaction;
- days since last seller response;
- days until/past expected close;
- next meeting present or absent;
- next step present, dated, and owned;
- unresolved customer questions;
- stakeholder coverage and seniority gaps;
- opportunity-stage dwell time relative to tenant baseline;
- task overdue count and age;
- recent negative, uncertain, or positive evidence;
- explicit customer commitment recency;
- CRM completeness and contradictory fields.

The first version uses tenant-configured rules plus a calibrated ranking model. A learned model is introduced only after point-in-time-correct labels and bias checks exist.

### Output

Risk band, explanation, evidence, missing information, recommended next actions, and an optional draft. Do not automatically downgrade, close, or reassign an opportunity.

## WF-5: Social engagement signal

### Trigger

An event arrives through an officially supported API or a customer-provided, lawfully collected source.

### Flow

Validate provenance and permitted purpose → resolve identity conservatively → determine whether consent/legitimate-interest and platform policy permit processing → classify the signal → connect it to an existing account/opportunity where justified → propose research or human outreach.

No scraping, password sharing, browser automation designed to bypass platform controls, sensitive-trait inference, or automatic direct message.

## WF-6: Manager and Sales Operations digest

Produces a prioritised summary of inactive opportunities, missing CRM data, follow-up delays, failed workflows, adoption, and quality. Aggregate outputs must retain drill-down evidence and respect the manager's CRM visibility.

## Functional requirements

- FR-001: SSO, SCIM-ready lifecycle, roles, tenant policy, and delegated/application consent.
- FR-002: connector install, scope inspection, health, renewal, suspension, and deletion.
- FR-003: canonical sales objects with raw-source references and schema versions.
- FR-004: event ingestion with validation, deduplication, ordering metadata, replay, and reconciliation.
- FR-005: deterministic workflow execution with durable timers and approvals.
- FR-006: AI outputs constrained by versioned schemas.
- FR-007: evidence links at claim, field, and proposed-action level.
- FR-008: risk classification before any tool is offered to an agent.
- FR-009: preview, approve, edit, reject, expire, revoke, and verify actions.
- FR-010: append-only security/audit events plus policy-controlled content retention.
- FR-011: tenant-specific mappings, templates, vocabulary, thresholds, and prohibited actions.
- FR-012: offline evaluation, shadow deployment, canary, rollback, and trace replay.
- FR-013: data-subject access, correction, objection, restriction, and deletion workflows.

## Non-functional requirements

Initial service objectives, to be validated in pilots:

- 99.9% monthly availability for interactive review and approval;
- 99.5% of accepted low-risk actions reach a terminal verified state within five minutes, excluding provider outage;
- no acknowledged event loss; at-least-once processing with idempotent effects;
- interactive draft p95 under 15 seconds and progress feedback within two seconds;
- event acknowledgement p95 under one second by queueing before processing;
- recovery point objective under five minutes for workflow state;
- recovery time objective under one hour for critical regional service;
- tenant-level usage and cost limits enforced before model or connector calls;
- encryption in transit and at rest, with managed keys and optional tenant-specific keys;
- all production changes attributable, reviewable, and reversible.
