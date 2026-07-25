# Integration Design

## Adapter contract

All providers implement a versioned contract:

```text
Connector
  capabilities(tenant) -> CapabilitySet
  authorize(request) -> Connection
  subscribe(scope, callback) -> Subscription
  renew(subscription) -> Subscription
  backfill(cursor, scope) -> Page<RawRecord>
  get(ref, fields, auth_context) -> VersionedRecord
  search(query, auth_context) -> Page<VersionedRecord>
  plan(command) -> ProviderMutationPlan
  execute(plan, idempotency_key, precondition, approval_token) -> ProviderReceipt
  verify(receipt) -> Verification
  reconcile(window) -> ReconciliationReport
  revoke(connection) -> RevocationReceipt
```

The connector declares supported objects, event types, auth modes, field-level permissions, write risks, batch sizes, rate-limit feedback, regional endpoints, subscription lifetimes, and consistency behaviour. Unsupported capabilities return explicit typed results, never silent omissions.

## Canonical domain model

Core identities: `Tenant`, `User`, `Team`, `Connection`, `ExternalIdentity`.

Sales: `Account`, `Person`, `Lead`, `Opportunity`, `Stage`, `Activity`, `Meeting`, `Message`, `Task`, `Campaign`, `SocialSignal`.

AI/control: `WorkflowRun`, `EvidenceItem`, `Claim`, `FeatureSnapshot`, `Recommendation`, `ProposedAction`, `Approval`, `PolicyDecision`, `ExecutionReceipt`, `EvaluationResult`.

Every canonical record contains:

- canonical and external identifiers;
- tenant and source;
- source version/ETag where supplied;
- observed-at and source-updated-at;
- schema version;
- field provenance;
- sensitivity classification;
- permitted purposes;
- retention/deletion state;
- raw reference, not necessarily raw content.

Provider-specific fields live in namespaced extensions. Mapping changes are versioned and reprocessable.

## Event envelope

```json
{
  "event_id": "uuid",
  "event_type": "meeting.transcript.available.v1",
  "tenant_id": "trusted-tenant-id",
  "source": "microsoft_graph",
  "source_event_id": "provider-id",
  "subject_ref": "opaque-ref",
  "occurred_at": "RFC3339",
  "received_at": "RFC3339",
  "schema_version": 1,
  "correlation_id": "uuid",
  "causation_id": "uuid-or-null",
  "partition_key": "tenant-or-resource",
  "classification": "confidential",
  "payload_ref": "encrypted-object-ref",
  "signature_status": "verified"
}
```

Ingress verifies provider authenticity, rejects oversized/invalid payloads, stores receipt before acknowledgement, and performs no expensive AI work on the webhook thread.

## Salesforce first

### Read scope

Begin with selected Account, Contact, Lead, Opportunity, Task, Event, User, and permitted custom fields. Admin setup includes field discovery and mapping preview. Never request all fields by default.

### Change capture

Prefer supported Salesforce event mechanisms for relevant changes and a replay cursor. Maintain scheduled incremental reconciliation because events can be missed, permissions can change, and subscriptions can fail.

### Write path

1. Read current record/version.
2. Build field-level diff.
3. Apply policy and approval.
4. Re-read before execution if proposal is old.
5. Use provider-supported conditional update where possible.
6. Save provider receipt.
7. Read back changed fields.
8. Mark verified or surface conflict.

### Salesforce scaling controls

- shared per-tenant rate budget informed by provider responses and contracted allocation;
- adaptive concurrency and bulk APIs for true batch workloads;
- no per-record polling;
- cache stable metadata such as object/field definitions;
- partition event consumption without violating resource order;
- replay and reconciliation dashboards;
- sandbox certification before production connection.

## Microsoft 365 first

### Identity

Use Microsoft Entra ID. Separate delegated permissions for user-initiated actions from application permissions for explicitly approved background processing. Admin consent must show why each permission is needed.

### Outlook and Calendar

Use Microsoft Graph change notifications where supported, lifecycle notifications, renewal workers, delta/reconciliation where supported, and `Retry-After`-aware backoff. Prefer basic notifications followed by authorised fetch when rich notifications would unnecessarily move sensitive content.

### Email send

Draft generation is separate from send. At approval time, freeze recipients, subject, body hash, referenced evidence, and expiry. Before sending, recheck approver authority, tenant policy, opt-out status, and content hash. Save the provider message identifier and verify submission; do not retry blindly after an ambiguous timeout.

### Teams

Use approved app experiences, activity feed notifications, or bot messages according to the interaction - not both for the same alert. Notifications are prioritised and rate limited to prevent alert fatigue. Meeting transcript/recording access is separately consented and governed.

## Slack

Install through OAuth with least privilege. Verify signed requests, respect Events API retries, acknowledge quickly, and use a queue. Internal updates default to draft/preview; channel posting follows tenant policy and user/channel visibility.

## HubSpot and Dynamics extension

The canonical domain and connector contract are the compatibility boundary. Each new CRM must pass a connector certification suite:

- auth and revocation;
- scope and field visibility;
- event deduplication and replay/reconciliation;
- paging and rate handling;
- mapping round trips;
- conditional/idempotent writes;
- ambiguous timeout recovery;
- permission change;
- deletion;
- tenant isolation;
- load and fault injection.

Dynamics follows the same Microsoft identity alignment but is not treated as “free” integration: entity customisation, Dataverse behaviour, and customer security roles require dedicated validation.

## Social integrations

Social is a capability-negotiated adapter. The platform may provide one or more of:

- authorised company-page engagement events;
- customer-authorised lead-source imports;
- user-supplied URLs for research;
- permitted identity/profile fields;
- a handoff that opens the native platform for the human to act.

If official access does not permit the required function, the UI states that the capability is unavailable. It must not fall back to scraping.

## Identity resolution

Use deterministic matches first: provider identity, verified email, CRM external ID, and tenant-managed mapping. Fuzzy name/company matching only proposes candidates with features and scores. It never merges records or attributes an interaction automatically when ambiguity exceeds the task threshold.

## Subscription lifecycle

The connection service tracks creation, validation, renewal deadline, last event, lifecycle notification, permission health, last reconciliation, and deletion. A renewal scheduler uses jitter and multiple attempts. Expired connections suspend dependent workflows and notify administrators without generating false “no activity” conclusions.

## Rate limit and backpressure policy

Rate budgeting is hierarchical:

`provider global → tenant/provider → connection/user → workflow → individual operation`.

Use token buckets, priority queues, `Retry-After`, exponential backoff with jitter, circuit breakers, and concurrency limits. Interactive approved writes outrank backfills and analytics. Backpressure propagates to workflow status instead of spawning unlimited retries.

## Integration security

- OAuth tokens encrypted in a dedicated vault and accessed only by connector workloads.
- Webhook secrets rotated and verified before parsing.
- Egress allowlists and private networking where supported.
- No model sees access tokens, refresh tokens, client secrets, or raw connector errors containing secrets.
- Tool responses are schema-filtered, size-limited, classified, and treated as untrusted content.
- Disconnect revokes provider access, stops subscriptions, drains unsafe work, and starts deletion policy.
