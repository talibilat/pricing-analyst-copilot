# Security, Privacy, and UK Governance

This is an engineering control plan, not legal advice. UK counsel and the customer's controller/privacy team must validate purposes, legal bases, notices, contracts, international transfers, and marketing rules before launch.

## UK-first regulatory scope

The control catalogue must map at minimum to:

- UK GDPR and Data Protection Act 2018 principles and individual rights;
- current UK rules affecting automated decision-making and profiling;
- Privacy and Electronic Communications Regulations for electronic marketing;
- direct-marketing guidance and the right to object;
- security assurance programme aligned to SOC 2 and ISO/IEC 27001;
- AI management programme aligned to ISO/IEC 42001 and NIST AI RMF/GenAI Profile;
- contractual/customer controls for model providers and subprocessors.

EU AI Act and EU GDPR are expansion requirements, not assumed identical to UK rules. US state privacy and communication rules require a separate regional policy pack.

## Controller/processor model

For normal enterprise use, the customer is expected to determine sales purposes and act as controller; the product commonly acts as processor. The product may be an independent controller for limited account/security/telemetry purposes. This must be documented per data flow, not asserted globally.

Subprocessor inventory records purpose, data classes, location, retention, transfer mechanism, security evidence, and change-notice process.

## Purpose and legal-basis registry

Every workflow declares:

- business purpose;
- data categories and subjects;
- source and collection context;
- controller/processor role;
- proposed legal basis;
- marketing/PECR condition;
- consent or objection state where applicable;
- recipients/subprocessors;
- retention;
- automated-decision significance;
- human review;
- DPIA status and owner.

Policy enforcement uses a compiled, versioned subset of this registry. Legal text is not pasted into an LLM as the primary control.

## Automated decision-making and profiling

Lead qualification and deal-health scoring are profiling-like processing and receive heightened governance even when they do not make a legally significant decision.

The Data (Use and Access) Act 2025 changed the UK automated-decision framework, and most Part 5 provisions commenced on 5 February 2026. Older summaries of UK GDPR Article 22 are therefore not treated as current implementation requirements. The legal policy owner must track the ICO's replacement guidance. The initial product nevertheless stays in recommendation mode for consequential scoring and supplies information, representation, human-intervention, and contestability controls as a deliberately conservative product choice.

Controls:

- clear notice and meaningful explanation;
- documented lawful basis and purpose;
- data minimisation and accuracy correction;
- human intervention and challenge path;
- no solely automated legally/similarly significant outcome in the initial product;
- no protected/special-category inference;
- ability to object to direct marketing and related profiling;
- periodic accuracy, bias, and outcome checks;
- DPIA before pilot;
- override and appeal recorded without penalising the user.

## Direct marketing and consent

The communications policy engine evaluates channel, recipient type, relationship, source, purpose, geography, consent/soft-opt-in where relevant, suppression list, objection, sender identity, required disclosure, and tenant policy.

Global suppression/objection is checked immediately before proposing and immediately before sending. Opt-out events outrank other workflows and propagate to permitted downstream systems. Social engagement is not treated as consent to email or direct-message.

## Security architecture

### Identity and access

- Entra ID SSO using OIDC/SAML as supported;
- SCIM-ready joiner/mover/leaver lifecycle;
- RBAC plus resource attributes and CRM permissions;
- least privilege, just-in-time administration, MFA/step-up for high-risk actions;
- workload identities and short-lived tokens;
- quarterly access review and immediate revocation path;
- break-glass accounts tightly controlled and audited.

### Data protection

- TLS in transit and managed encryption at rest;
- envelope encryption and key rotation;
- optional tenant-managed/dedicated keys;
- secrets in managed vault, never logs/prompts;
- field-level classification, redaction, and DLP;
- tenant-aware backups with deletion and restoration procedures;
- private endpoints/egress controls where contracted;
- non-production uses synthetic data by default.

### Secure development

- threat modelling per workflow and connector;
- dependency and container scanning;
- SAST, secret scanning, IaC policy, SBOM and signed artefacts;
- protected branches, two-person review, provenance and deployment attestation;
- regular penetration testing and agentic-AI red teaming;
- incident exercises including cross-tenant exposure and bad autonomous action.

## AI governance record

Each production AI use case has:

- owner and intended purpose;
- prohibited use;
- impact/risk tier;
- model/provider/version and approval;
- training/evaluation data provenance;
- evaluation report and known limitations;
- confidence/approval thresholds;
- monitoring and review frequency;
- human oversight design;
- incident/rollback/kill-switch plan;
- retirement criteria.

## Retention and deletion

Recommended starting defaults:

- raw webhook payload: hours to seven days, only for recovery/security need;
- fetched message/transcript content: fetch-on-demand or shortest workflow window;
- proposals and evidence excerpts: tenant-configurable, minimised;
- operational workflow metadata: contractually defined;
- audit metadata: longer, with customer content separated/redacted;
- evaluation samples: explicit selection and authorisation, not automatic indefinite reuse.

Deletion traverses raw storage, operational rows, caches, indexes, embeddings, evaluation sets, analytics mappings, and backups according to documented capability. Tombstones prevent re-ingestion while a source deletion propagates.

## Data-subject and customer rights

Build operator workflows for access, correction, objection, restriction, erasure, export, and explanation. The evidence graph enables discovery of derived claims/features. Human review handles conflicts with retention obligations.

## Governance bodies

- AI/product risk committee for use-case approval and threshold changes;
- security/privacy review for connectors and data flows;
- model change advisory review for material provider/model/prompt updates;
- incident commander with authority to disable a workflow globally;
- customer administrator controls for tenant-local suspension.

## Pre-pilot governance gates

- DPIA and records of processing;
- data processing agreement/subprocessor review;
- lawful-basis and PECR/direct-marketing analysis;
- security threat model and penetration test;
- tenant admin consent UX review;
- data retention/deletion test;
- individual objection/suppression test;
- human oversight and explanation usability test;
- AI evaluation report signed by named owners;
- incident and rollback exercise.
