# Enterprise AI Sales Workflow Integration

- Status: architecture and implementation plan
- Launch region: United Kingdom
- Initial customers: mid-market and large enterprises
- Initial CRM: Salesforce
- Initial productivity suite: Microsoft 365
- Next CRMs: HubSpot, then Microsoft Dynamics 365

## Purpose

This package describes how to build an AI-first sales workspace that coordinates enterprise work across CRM, email, calendar, meetings, messaging, and permitted social-media signals. It is deliberately a plan, not an implemented product.

The product does not replace the customer's systems of record. It observes authorised events, gathers evidence, recommends or prepares actions, obtains approval when required, performs approved actions safely, and leaves an auditable explanation.

## Users and why they were selected

| User | Need | First-release experience |
|---|---|---|
| Sales representative | Less administration and faster follow-up | Meeting summary, draft email, tasks, CRM suggestions |
| Account executive | Move opportunities forward | Deal health, stakeholder gaps, next-best actions |
| Sales manager | See risk and coach consistently | Team digest, inactive opportunities, evidence-backed risk |
| Sales operations | Data quality and controlled automation | Rules, mappings, workflow configuration, metrics |

All four are in scope because the workflow crosses individual execution, management, and operational governance. The account executive and sales representative receive the richest first-release interaction because they generate the activity data and feel the administrative cost daily. Managers and Sales Operations are not postponed: they receive the controls and visibility required for enterprise adoption.

## Chosen product shape

**Choice:** an AI coordination layer across existing enterprise products.

Alternatives considered:

- A new CRM: rejected because enterprise customers will not readily replace their system of record.
- A chat-only assistant: rejected because suggestions without reliable write-back do not complete work.
- Fully autonomous sales agent: rejected for the first release because external communication, profiling, bad data, and irreversible CRM changes create unacceptable risk.
- Point solution for meeting notes: too narrow to demonstrate end-to-end efficiency.

The first release is a prototype in breadth but production-minded in its safety boundaries. It proves several workflows while using shared foundations: identity, tenancy, evidence, approvals, audit, integration adapters, evaluation, and observability.

## Workflows in scope

1. Post-meeting follow-up.
2. Lead capture and qualification.
3. Inbound email or messaging response.
4. Inactive-opportunity detection and recovery.
5. Permitted social-engagement signal processing.
6. Manager and Sales Operations digest.

The post-meeting workflow is delivered first because it uses high-quality first-party evidence, has a clear human review point, and exercises the reusable platform end to end. It is the first delivery slice, not the only workflow.

## Recommended reading order

1. [Decisions and scope](./01_DECISIONS_AND_SCOPE.md)
2. [Workflows and requirements](./02_WORKFLOWS_AND_REQUIREMENTS.md)
3. [High-level architecture](./03_HIGH_LEVEL_ARCHITECTURE.md)
4. [Integration design](./04_INTEGRATION_DESIGN.md)
5. [AI and multi-agent low-level design](./05_AI_MULTI_AGENT_LLD.md)
6. [AI evaluations](./06_AI_EVALUATION.md)
7. [Security, privacy, and UK governance](./07_SECURITY_PRIVACY_GOVERNANCE.md)
8. [Scale, reliability, and performance](./08_SCALE_RELIABILITY_PERFORMANCE.md)
9. [Observability and operations](./09_OBSERVABILITY_AND_OPERATIONS.md)
10. [Engineering delivery](./10_ENGINEERING_DELIVERY.md)
11. [Roadmap and success metrics](./11_ROADMAP_AND_METRICS.md)
12. [Risk register and failure analysis](./12_RISK_REGISTER.md)
13. [Requirement traceability](./13_TRACEABILITY_MATRIX.md)
14. [Primary-source research](./research/PRIMARY_SOURCES.md)

## Non-negotiable principles

- No external message or social post is sent without approval in the initial release.
- The model never receives a direct credential for an external system.
- A deterministic workflow engine, not an LLM, owns state, retries, timeouts, and approvals.
- Every material claim and proposed change carries evidence references.
- “Confidence” is empirically calibrated by task; model self-confidence is not treated as probability.
- Low evidence or material contradictions cause abstention, not guessing.
- Customer data is not used to train shared models by default.
- Every tenant is isolated logically from day one and can receive stronger physical isolation when contracted.
- Integrations are idempotent, rate-aware, replayable, and reconciled.
- Releases are blocked by evaluation and security gates, not only unit tests.

## Definition of success

The north-star metric is **weekly active sellers completing at least one integrated workflow with a verified outcome**. Supporting measures include follow-up time, CRM completeness, accepted suggestions, administrative time saved, workflow success rate, opportunity progression, user trust, override rate, abstention quality, and cost per successful workflow.
