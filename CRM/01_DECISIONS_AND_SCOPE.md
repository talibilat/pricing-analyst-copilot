# Decisions and Scope

## Confirmed decisions

| Area | Options considered | Decision | Why |
|---|---|---|---|
| Customer segment | SMB; mid-market; enterprise | Mid-market and enterprise | Strong workflow pain, governance need, and expansion value |
| Scalability | Prototype-only; scalable foundations | Scalable foundations | Avoid redesigning tenancy, data, events, and audit after pilots |
| Daily users | One seller persona; all sales roles | Representatives, account executives, managers, Sales Operations | Adoption and governance span all four roles |
| Workflow count | One workflow; several workflows | Several, delivered as vertical slices | Shared platform must prove reuse without a “big bang” |
| First slice | Cold outbound; meeting follow-up; lead scraping | Post-meeting follow-up | Better first-party evidence and lower legal/reputation risk |
| CRM | Salesforce; HubSpot; Dynamics | Salesforce first, HubSpot second, Dynamics third | Enterprise priority with an explicit adapter path |
| Productivity | Google; Microsoft | Microsoft 365 first | Strong fit with target enterprise segment |
| Messaging | Teams; Slack; SMS/WhatsApp | Teams and Slack | Enterprise internal collaboration with lower consent risk |
| Social | Scraping; official integrations | Officially permitted APIs and customer-authorised sources only | Platform terms, privacy, security, and data quality |
| Region | US; EU; UK | UK first | Defined launch boundary, local governance, and focused design partners |
| Automation | Suggest only; bounded automation; full autonomy | Bounded, risk-tiered automation | Delivers efficiency without hiding consequential action |
| AI runtime | One general prompt; bounded specialist agents | Deterministic orchestration plus specialist agents | Separates concerns and makes evaluation and traces meaningful |
| Source of truth | Product database; existing systems | Existing enterprise systems | Prevents creation of a shadow CRM |
| Cloud | Cloud-neutral lowest common denominator; Azure-first portable design | Azure UK deployment, portable contracts | Microsoft alignment and UK deployment, without coupling domain logic |

## Why UK first

UK-first is a delivery boundary, not a claim that UK compliance is simple. It provides:

- one primary legal and operational context for the pilot;
- a clear initial data-residency decision;
- focused consent and direct-marketing controls;
- one business-hours and incident-response operating model;
- a credible base for later EU and US variants.

The system must still separate policy from code. Legal bases, retention, communication rules, residency, and model-provider settings are tenant policy records, not hard-coded UK assumptions.

## In scope

- Salesforce accounts, contacts, leads, opportunities, activities, tasks, selected custom fields, and permitted events.
- Microsoft Entra ID SSO and enterprise consent.
- Outlook email and calendar.
- Teams meetings and internal notifications.
- Slack internal notifications.
- Meeting transcript/notes ingestion from authorised providers.
- Lead, meeting, inbound-response, inactivity, and social-signal workflows.
- Evidence graph, approvals, audit, confidence, evaluation, monitoring, and administrative control plane.
- UK data protection and electronic-marketing control design.
- Extension contracts for HubSpot and Dynamics 365.

## Explicitly out of scope for the first release

- Unattended cold-outreach campaigns.
- Scraping LinkedIn or any other social platform.
- Automatic public posting.
- Automatic changes to opportunity value, stage, close date, owner, or closed status.
- Automatic deletion or merging of CRM records.
- Legal advice or a claim of compliance certification.
- Training shared models on customer content.
- Replacing the CRM, email client, or collaboration product.
- A general-purpose autonomous agent with unrestricted tools.

## Assumptions to validate with design partners

1. Customers can provide Salesforce sandbox and Microsoft 365 test tenants.
2. Meeting transcripts can be accessed under customer policy and participant notice.
3. Each customer will nominate a Sales Operations owner and security/privacy owner.
4. CRM field mappings vary and need tenant configuration.
5. “Inactive” differs by sales motion and must be configurable.
6. Some customers will prohibit storage of full message bodies or model traces.
7. Social platforms may not grant the API scope desired; the workflow must degrade gracefully.
8. Customers will accept human approval as the first-release safety boundary.

## Architecture fitness functions

The design is accepted only while it can demonstrate:

- no cross-tenant access in automated isolation tests;
- replay of an event does not duplicate external effects;
- every proposed CRM mutation has evidence, policy result, confidence, and approval status;
- deletion propagates to derived stores and caches within the contracted window;
- the loss of one connector or model provider does not corrupt workflow state;
- per-tenant quotas prevent a single tenant from exhausting shared capacity;
- model or prompt changes cannot ship without regression evaluation;
- an operator can reconstruct a workflow without viewing redacted customer content;
- the service can add a new CRM through the adapter contract rather than core-domain rewrites.
