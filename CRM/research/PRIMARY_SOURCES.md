# Primary-source research for a UK-first enterprise AI sales platform

- **Research date:** 25 July 2026
- **Scope:** authoritative inputs for the architecture of a scalable, multi-tenant AI product spanning sales workflows, Salesforce, Microsoft 365, Teams, Slack and permitted social integrations, with HubSpot and Microsoft Dynamics as follow-on connectors.
**Source rule:** vendor capabilities come from vendor documentation; legal claims come from legislation, regulators or government; standards come from their issuing bodies; confidence claims come from original peer-reviewed research.

This is architecture research, not legal advice. A UK privacy and marketing specialist must validate the lawful basis, controller/processor roles, notices, DPIA and channel policy before production launch.

## Executive conclusions

1. **The AI must be evidence-governed, not merely conversational.** Every recommendation should retain source identifiers, versions, timestamps, access context, extraction results, policy decisions, model/prompt versions and the human or system action that followed. Confidence must be empirically calibrated for each workflow; an LLM's self-reported percentage is not a correctness probability. The calibration literature defines useful confidence as correspondence between predicted probability and observed correctness, and shows that modern neural networks can be poorly calibrated ([Guo et al., 2017](https://proceedings.mlr.press/v70/guo17a.html)).
2. **Agents must not call enterprise systems directly.** Every read or write should pass through a deterministic connector and policy plane that checks tenant, identity, source permissions, legal/channel policy, quota, schema, approval, idempotency and audit requirements. This is a direct mitigation for OWASP's prompt-injection, sensitive-information-disclosure and excessive-agency risks ([OWASP LLM Top 10, 2025](https://genai.owasp.org/llm-top-10/)).
3. **Events are hints, not an exactly-once source of truth.** Salesforce retains Pub/Sub events for 72 hours, Microsoft Graph can delay or drop notifications from slow endpoints, Slack retries failed event deliveries, and HubSpot can deliver batches and retries. The platform therefore needs durable ingress, deduplication, replay checkpoints and scheduled reconciliation ([Salesforce event durability](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/event-message-durability.html), [Microsoft Graph webhook delivery](https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks), [Slack Events API](https://api.slack.com/apis/connections/events-api), [HubSpot webhooks](https://developers.hubspot.com/docs/api-reference/latest/webhooks/guide)).
4. **UK marketing eligibility is deterministic policy, never an AI judgement.** PECR electronic-mail rules cover email, text and private social-media messages; subscriber type, channel, consent or soft opt-in, suppression status and purpose all matter. A public social profile is not permission to contact someone ([ICO electronic-mail marketing](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guide-to-pecr/electronic-and-telephone-marketing/electronic-mail-marketing/), [ICO B2B marketing](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/)).
5. **Current UK automated-decision law changed in 2026.** The Data (Use and Access) Act 2025 provisions commenced in stages, with the majority of Part 5 in force on 5 February 2026 ([UK Government commencement plan](https://www.gov.uk/guidance/data-use-and-access-act-2025-plans-for-commencement)). The revised framework permits significant solely automated decisions more broadly when appropriate safeguards are present, while retaining tighter restrictions for special-category data. Safeguards include information about the decision, representations, human intervention and contestability ([ICO DUAA automated-decision summary](https://ico.org.uk/about-the-ico/what-we-do/legislation-we-cover/data-use-and-access-act-2025/the-data-use-and-access-act-2025-duaa-summary-of-the-changes/data-protection/)). Older ICO Article 22 material is explicitly under review, so the legal policy pack must be versioned and monitored.
6. **LinkedIn is not a safe launch dependency.** LinkedIn currently says it is not accepting new Sales Navigator API partners; its User Agreement prohibits scraping and unauthorized automation, including automated messaging and engagement ([Sales Navigator platform](https://learn.microsoft.com/en-us/linkedin/sales/), [LinkedIn User Agreement](https://www.linkedin.com/legal/user-agreement)). Launch should use user-supplied links, manual deep links and approved Marketing/Community APIs only where the customer, app and member have the required access.
7. **Scale requires tenant-aware isolation and budgets.** Authentication alone is not tenant isolation, and isolation enforcement should be a shared platform concern rather than left to every service author ([AWS SaaS Lens: isolation mindset](https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/isolation-mindset.html)). Use pooled deployment stamps for normal tenants, tenant-aware partitioning and quotas throughout, with optional siloed stamps for regulated or premium customers; Azure's official multi-tenant guidance identifies deployment stamps as a way to scale while trading isolation, cost and manageability ([Azure multi-tenant approaches](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/approaches/overview)).

## Annotated source matrix

| Area | Authoritative source | Material fact | Design implication |
|---|---|---|---|
| Salesforce event ingestion | [Pub/Sub API overview](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/intro.html) | Pub/Sub provides a gRPC/HTTP2 interface for Platform Events, Change Data Capture and real-time monitoring events, with client-controlled flow control. | Use one bounded Salesforce event adapter per tenant/org, with backpressure; normalize CDC into the internal event envelope. |
| Salesforce replay | [Event message durability](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/event-message-durability.html) | Events are retained for 72 hours; Replay IDs are opaque, non-contiguous and not guaranteed unique across some maintenance events. | Persist replay position only after durable processing; never infer gaps arithmetically; run reconciliation after outages or resets. |
| Salesforce flow control | [Pull subscription and flow control](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/flow-control.html) | A subscribe call can request at most 100 events and the client controls outstanding demand. | Couple requested demand to queue capacity and tenant budget; pause intake before downstream overload. |
| Salesforce retries | [Retry long-lived RPC calls](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/retry-rpc-calls.html) | Long-lived calls close on error; Salesforce recommends bounded retry with exponential backoff and replay-based resume. | Use a subscription state machine, jittered retry, replay checkpoints and an operationally visible degraded state. |
| Salesforce API quota | [API limits and monitoring](https://developer.salesforce.com/blogs/2024/11/api-limits-and-monitoring-your-api-usage) | Entitlements vary; REST responses and the Limits resource expose usage and remaining allocation; sustained excess can lead to `REQUEST_LIMIT_EXCEEDED`. | Do not hard-code capacity. Maintain tenant/org budgets, monitor limit headers, reserve capacity for approved writes and degrade gracefully. |
| Salesforce write plans | [Composite REST resource](https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/resources_composite_composite_post.htm) | A composite call can contain up to 25 subrequests, with at most five query or collection operations, and returns each subrequest result. | Use composite for ordered approved update plans, but audit every result and provide compensation; HTTP success does not prove all logical writes succeeded. |
| Salesforce authorization | [Salesforce well-architected security](https://architect.salesforce.com/docs/architect/well-architected/guide/secure.html) | Salesforce's security guidance emphasizes least privilege, sharing controls and traceable integration identities. | Use a distinct customer integration principal, minimal OAuth scopes and CRUD/FLS preflight; preserve Salesforce sharing semantics. |
| Outlook events | [Outlook change notifications](https://learn.microsoft.com/en-us/graph/outlook-change-notifications-overview) | Graph supports message, event and contact subscriptions; shared/delegated folders have permission limitations; there can be 1,000 active Outlook subscriptions per mailbox across applications. | Default to delegated access; require explicit admin authorization for application access; centralize renewals and mailbox subscription quotas. |
| Graph notifications | [Change-notification overview](https://learn.microsoft.com/en-us/graph/change-notifications-overview) | Graph supports basic, resource-data and lifecycle notifications; Teams subscriptions share a 10,000-per-organization quota and have resource-specific lifetimes. | Maintain a subscription registry, expiry SLO and quota dashboard; encrypt resource-data paths and prefer narrow subscriptions. |
| Graph webhook delivery | [Webhook delivery](https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks) | The endpoint should respond within three seconds; queued work can return `202`; slow endpoints can be throttled and notifications may be dropped. | Keep ingress limited to validation, durable enqueue and acknowledgement; autoscale it independently and reconcile when delivery health degrades. |
| Graph lifecycle recovery | [Lifecycle events](https://learn.microsoft.com/en-us/graph/change-notifications-lifecycle-events) | Graph signals reauthorization, subscription removal and missed notifications. | Model connector health explicitly; recreate or reauthorize and run delta/reconciliation before allowing new AI decisions. |
| Graph throttling | [Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling) | Graph returns `429` and `Retry-After`; limits vary by scenario and service; change notifications reduce polling pressure. | Use per-tenant/resource/operation token buckets, honor `Retry-After` with jitter, and isolate backfill from interactive work. |
| Teams deep ingestion | [Teams change notifications](https://learn.microsoft.com/en-us/graph/teams-changenotifications-chatmessage) | Chat and channel message subscriptions require powerful permissions for broad access, and long subscriptions require lifecycle handling. | Do not request tenant-wide message access for the normal product. Offer broad ingestion as an optional, admin-approved capability. |
| Teams transcript | [Call transcript resource](https://learn.microsoft.com/en-us/graph/api/resources/calltranscript?view=graph-rest-1.0) | A transcript is a later artifact with meeting identity, timestamps and content stream; tenant policy controls access. | Treat availability as asynchronous. Persist a source pointer/hash and speaker/timestamp evidence; fall back to notes/calendar/email when unavailable. |
| Teams UX | [Activity-feed notification practices](https://learn.microsoft.com/en-us/graph/teams-activity-feed-notifications-best-practices) | Microsoft recommends actionable, relevant notifications, one notification mechanism per use case, and no more than 20 notifications/minute/user. | Deduplicate and digest; link to the approval/action; choose feed or bot for each workflow, not both. |
| Slack ingress | [Events API](https://api.slack.com/apis/connections/events-api) | Events are scope-bound; Slack expects a 2xx within three seconds, retries failed requests three times and caps deliveries at 30,000/workspace/app/hour. | Verify, enqueue and acknowledge; deduplicate by event ID; never describe visible Slack context as workspace-complete. |
| Slack authenticity | [Verifying Slack requests](https://docs.slack.dev/authentication/verifying-requests-from-slack/) | Slack signs the raw request body using an HMAC-SHA256 signature and timestamp. | Verify the unmodified body, reject stale timestamps and compare signatures in constant time before enqueueing. |
| Slack rate limits | [Web API rate limits](https://api.slack.com/apis/rate-limits) | Limits are method/workspace scoped; `429` carries `Retry-After`; posting is generally limited to about one message/second/channel. | Use per-workspace/method queues, preserve ordering and collapse bursts into digests. |
| Slack token lifecycle | [Token rotation](https://api.slack.com/authentication/rotation) | Rotating access tokens expire after 12 hours; refresh tokens are single-use after a grace period and only two active tokens are allowed. | Keep refresh state transactional in a token vault; monitor expiry and model revoke/uninstall as connector-state transitions. |
| HubSpot roadmap | [Webhook guide](https://developers.hubspot.com/docs/api-reference/latest/webhooks/guide) | Webhooks can be batched and retried; signature validation and app-level subscriptions are required; duplicate or out-of-order privacy events are possible. | Reuse the signed multi-tenant ingress, dedupe and out-of-order handlers; prioritize privacy deletion and retain tombstones. |
| HubSpot quotas | [Platform usage guidelines](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines) | OAuth-app API limits are account scoped and vary by API/tier; `429` signals excess. | Add HubSpot through the same capability/limit abstraction; isolate CRM Search budget and prefer webhooks. |
| Dynamics roadmap | [Dataverse service-protection limits](https://learn.microsoft.com/en-us/power-apps/developer/data-platform/api-limits) | Dataverse returns `429`/`Retry-After`; service-protection defaults vary and evaluate request count, execution time and concurrency. | Tune concurrency adaptively per environment/principal; avoid large periodic spikes and do not assume published defaults are guaranteed. |
| LinkedIn availability | [Sales Navigator platform](https://learn.microsoft.com/en-us/linkedin/sales/) | LinkedIn says it is not currently accepting new Sales Navigator API partners. | Keep launch independent of SNAP and place partner features behind a capability flag. |
| LinkedIn approved APIs | [Marketing access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access) | Products and scopes require approval, qualification, member consent and relevant roles; access tiers have different restrictions. | Resolve capability at runtime by app approval, customer, role, scope and API version; fail closed. |
| LinkedIn automation | [LinkedIn User Agreement](https://www.linkedin.com/legal/user-agreement) | The agreement prohibits scraping, bypassing access limits, unauthorized bots, automated messaging and inauthentic engagement. | No scraping or browser automation. Use approved APIs, user-supplied context and manual deep links only. |
| UK direct marketing | [ICO B2B marketing](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/) | PECR treatment differs for corporate and individual subscribers; social direct messages are electronic mail; public contact data does not eliminate data-protection duties. | Resolve recipient type and jurisdiction before every send; treat sole traders/partnerships appropriately; never infer consent from a public profile. |
| UK electronic mail | [ICO electronic-mail guidance](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guide-to-pecr/electronic-and-telephone-marketing/electronic-mail-marketing/) | Consent or a valid soft opt-in is required in protected cases; identification, opt-out and suppression duties apply. | Centralize a channel-specific consent and suppression ledger; include identity and opt-out; store the send-policy decision. |
| Current UK ADM | [ICO DUAA summary](https://ico.org.uk/about-the-ico/what-we-do/legislation-we-cover/data-use-and-access-act-2025/the-data-use-and-access-act-2025-duaa-summary-of-the-changes/data-protection/) | Revised rules allow more significant solely automated decisions with safeguards; special-category data remains more restricted; meaningful human involvement is part of the statutory test. | Keep consequential sales scoring in recommendation mode initially; provide information, representations, human intervention and contestability; block special-category features absent explicit legal approval. |
| UK legal currency | [Government commencement plan](https://www.gov.uk/guidance/data-use-and-access-act-2025-plans-for-commencement) | The majority of DUAA Part 5 privacy provisions commenced on 5 February 2026. | Date/version every legal rule, subscribe to regulator changes and do not rely uncritically on pre-DUAA Article 22 summaries. |
| EU expansion | [Regulation (EU) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/) | The EU AI Act establishes risk-based duties, including stronger lifecycle controls for high-risk systems and phased application dates. | Maintain jurisdictional policy packs and an AI-system inventory; reassess classification if the product expands into employment, credit or essential-service decisions. |
| AI risk lifecycle | [NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework) and [GenAI Profile](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf) | NIST organizes voluntary AI risk work into Govern, Map, Measure and Manage; the GenAI profile adapts those functions to generative-AI risks. | Use the four functions as a continuous release and operations loop; tie every identified risk to tests, thresholds, owners and treatment. |
| AI management system | [ISO/IEC 42001:2023](https://www.iso.org/standard/42001) | ISO 42001 specifies requirements to establish, implement, maintain and continually improve an AI management system. | Maintain accountable owners, inventory, risk/impact assessments, supplier controls, objectives, audits, corrective actions and management review. |
| Agent security | [OWASP GenAI LLM risks](https://genai.owasp.org/llm-top-10/) | The 2025 list includes prompt injection, sensitive-data disclosure, improper output handling, excessive agency, misinformation and unbounded consumption. | Treat all retrieved content as untrusted; keep credentials/policy outside prompts; validate outputs; narrow tools; gate side effects; budget compute. |
| Trace model | [OpenTelemetry trace API](https://opentelemetry.io/docs/specs/otel/trace/api/) | Spans form causal trees and carry attributes, events, links, timestamps and status. | Use one propagated correlation context from trigger through retrieval, agents, approval and connector effects. |
| GenAI telemetry | [OpenTelemetry GenAI attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/) | Conventions cover GenAI operations, tokens and tool calls; some content fields can be large or sensitive and are not recommended by default. | Record hashes/IDs, versions, counts and outcomes by default, not raw prompts, bodies, transcripts or tool arguments. |
| Telemetry privacy | [OpenTelemetry sensitive-data guidance](https://opentelemetry.io/docs/security/handling-sensitive-data/) | The implementer must identify sensitive fields; OpenTelemetry supports filtering, deletion, hashing and redaction. | Apply an allowlist at collection, tenant separation, encryption and short retention; use exceptional, authorized debug capture only. |
| Confidence calibration | [Guo et al., 2017](https://proceedings.mlr.press/v70/guo17a.html) | Modern neural networks can be miscalibrated; temperature scaling can calibrate classification probabilities on held-out data. | Build workflow/action-specific calibrators and reliability diagrams; recalibrate after material model or distribution change. |
| LLM uncertainty | [Farquhar et al., 2024](https://www.nature.com/articles/s41586-024-07421-0) | Semantic entropy can identify some confabulations by measuring meaning-level disagreement, but it does not detect every error. | Use consistency as one feature, never the confidence score; combine it with evidence, validators, policy and empirical outcome data. |
| Multi-tenant isolation | [AWS SaaS isolation mindset](https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/isolation-mindset.html) | Authentication/authorization alone do not guarantee isolation, and enforcement should use a shared mechanism. | Put tenant context and isolation in the data/connector platform, with deny-by-default storage and retrieval boundaries. |
| Multi-tenant scaling | [Azure architecture approaches](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/approaches/overview) | Shared and single-tenant deployments trade cost, scale, isolation and manageability; deployment stamps support continued scale. | Use region-scoped pooled stamps, automated sharding and tenant placement; offer dedicated stamps without maintaining tenant-specific product versions. |
| OpenAI agent runtime | [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | The SDK provides agents, tools/handoffs, guardrails, sessions, human-in-the-loop support and tracing, and uses the Responses API by default for OpenAI models. | Use it behind an internal gateway for bounded agent execution; retain deterministic workflow, policy and action control in product services. |
| OpenAI tracing | [Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/) | SDK traces can include generations, tool calls, handoffs and guardrails; model/tool content can be sensitive and capture is configurable. | Export redacted operational spans and keep the product decision/audit ledger separate; disable sensitive trace content according to tenant policy. |
| OpenAI model routing | [OpenAI model guidance](https://developers.openai.com/api/docs/guides/latest-model) | The current GPT-5.6 family exposes different quality/cost roles and recommends the Responses API for reasoning, tool-calling and multi-turn workflows. | Evaluate Sol/Terra/Luna per task and record the chosen immutable version; never hard-code one model for every workflow or accept an unevaluated fallback. |
| OpenAI embeddings | [text-embedding-3-large](https://developers.openai.com/api/docs/models/text-embedding-3-large) | OpenAI documents the model as its most capable embedding model for English and non-English tasks, suitable for search and related similarity tasks. | Treat it as an initial retrieval candidate; benchmark relevance, privacy mode, latency and cost against alternatives before production scale. |

## Detailed design implications

### 1. AI evidence, provenance and traceability

For each atomic claim, extracted CRM field or proposed action, retain an **evidence envelope**:

- tenant, user/service principal and effective source permissions;
- source system, immutable source ID, version/eTag where available, event time, retrieval time and content hash;
- exact excerpt coordinates or structured fields that support the claim;
- extractor/model, prompt-template and policy versions;
- normalized claim/action and deterministic validation results;
- conflicts, missing evidence and freshness;
- calibrated reliability class and the threshold policy used;
- approval actor, edits, connector result, idempotency key and compensation status.

This is an application record, distinct from hidden model reasoning. UK safeguards require usable information and contestability, not disclosure of private chain-of-thought; the ICO's current DUAA summary requires information about significant automated decisions plus representation, human-intervention and contest rights ([ICO DUAA summary](https://ico.org.uk/about-the-ico/what-we-do/legislation-we-cover/data-use-and-access-act-2025/the-data-use-and-access-act-2025-duaa-summary-of-the-changes/data-protection/)).

Use OpenTelemetry spans for the operational path - trigger, retrieval, agent/model call, tool proposal, policy check, approval, connector call and retry - because its trace model links causal operations across service boundaries ([OpenTelemetry trace API](https://opentelemetry.io/docs/specs/otel/trace/api/)). Keep the compliance audit ledger separately immutable and access-controlled; operational telemetry has different volume, sampling, retention and privacy needs. OpenTelemetry warns that instrumentation cannot determine sensitivity for the implementer and recommends minimization/redaction controls ([sensitive-data guidance](https://opentelemetry.io/docs/security/handling-sensitive-data/)).

### 2. Confidence is an evaluated routing control

Do not expose a raw model probability or prompted statement such as “95% confident.” Build a reliability model for each atomic output from measurable features:

1. evidence coverage and source authority;
2. freshness and temporal alignment;
3. retrieval score and permission-filter success;
4. cross-source contradiction count;
5. structured extraction/schema/business-rule validation;
6. model consistency or semantic uncertainty;
7. out-of-distribution signals;
8. historical correctness for the workflow/model/prompt/tenant segment.

Calibration means that results assigned probability \(p\) are correct approximately \(p\) of the time; modern neural networks often fail this property without post-hoc calibration ([Guo et al.](https://proceedings.mlr.press/v70/guo17a.html)). Semantic entropy is useful for detecting a class of meaning-level confabulations but cannot detect consistently wrong answers, so it is only one feature ([Farquhar et al.](https://www.nature.com/articles/s41586-024-07421-0)).

Evaluate:

- task accuracy/F1 for extraction and classification;
- grounded claim precision, citation validity and evidence coverage;
- action-argument accuracy and postcondition success;
- policy violation and unauthorized-tool-call rate;
- Brier score/log loss, expected calibration error and reliability plots;
- risk–coverage curve, abstention rate and error among auto-executed actions;
- slices by workflow, model, prompt, language, tenant, industry, channel, source quality and autonomy tier;
- latency, token/tool cost and retries without allowing them to conceal safety failures.

Recommended routing:

- **Abstain:** evidence missing/conflicting, permission uncertain, policy unresolved or out-of-distribution.
- **Draft for approval:** any external communication, material CRM field, ambiguous attribution or intermediate reliability.
- **Eligible for admin-enabled automation:** only low-risk internal actions that have met a separately approved, calibrated error ceiling and rollback/postcondition requirements.

Recalibrate and rerun frozen/adversarial suites after any material model, prompt, retrieval, embedding, tool, source schema, policy or population change. NIST's AI RMF and GenAI Profile position measurement and management as lifecycle activities rather than one-time certification ([NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework), [NIST AI 600-1](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf)).

### 3. Agent and connector security boundary

Emails, CRM notes, meeting transcripts, Teams/Slack messages, attachments and web/social content are **untrusted data**. They can contain indirect instructions designed to redirect an agent. OWASP lists prompt injection as its first LLM risk and also identifies sensitive disclosure, improper output handling and excessive agency ([OWASP 2025](https://genai.owasp.org/llm-top-10/)).

Required boundary:

`untrusted source -> parser/sanitizer -> permission-filtered retrieval -> narrow agent -> typed proposal -> deterministic policy/authorization -> approval if required -> idempotent connector -> verified postcondition`

Controls:

- no credentials, legal rules or authorization decisions in prompts;
- separate read-only research/summarization tools from write tools;
- server-side typed schemas and allowlisted fields/operations;
- tenant and acting-principal context injected and verified outside the model;
- deterministic communication policy before every external send;
- per-action approval token bound to the exact payload, destinations and expiry;
- idempotency and effect ledger for all side effects;
- output encoding and attachment scanning before downstream use;
- cost/time/tool-call budgets and cancellation;
- adversarial tests for prompt injection, cross-tenant retrieval, poisoned documents, privilege escalation, exfiltration, repeated sends and unbounded loops.

### 4. Connector reliability and scale

The common connector runtime needs:

- signed/encrypted ingress and source authenticity checks;
- a durable queue partitioned by tenant/source/entity;
- inbox deduplication and outbox/effect records;
- per-tenant/principal/operation rate limiting with vendor `Retry-After` support;
- subscription lifecycle, renewal and reauthorization state machines;
- replay checkpoint and delta/reconciliation workers;
- poison/dead-letter isolation and tenant-visible recovery state;
- encrypted token vault, rotation, revocation and admin kill switch;
- canonical sales entities with raw-source extension fields;
- capability flags by customer, source edition, scope, role and API version;
- backfill isolated from interactive workflow capacity;
- per-tenant cost, backlog, lag and quota observability.

Microsoft advises Graph webhook endpoints to acknowledge within three seconds and queue work when it cannot be processed immediately; slow endpoints can be throttled and can lose notifications ([Graph webhook delivery](https://learn.microsoft.com/en-us/graph/change-notifications-delivery-webhooks)). Slack similarly requires acknowledgement within three seconds and retries failed events ([Slack Events API](https://api.slack.com/apis/connections/events-api)). Salesforce supports replay only inside its 72-hour window ([Salesforce durability](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/event-message-durability.html)). These facts require reconciliation rather than an “events are complete” assumption.

For multi-tenant scale, enforce tenant context through shared libraries/middleware and partition keys. AWS states that authorization alone is insufficient and isolation should not be left to individual service developers ([AWS SaaS Lens](https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/isolation-mindset.html)). Use automated region-scoped deployment stamps so capacity can be added without a global migration; Azure identifies stamps as a scalable pattern and describes their isolation/cost/manageability trade-offs ([Azure multi-tenancy](https://learn.microsoft.com/en-us/azure/architecture/guide/multitenant/approaches/overview)).

### 5. UK-first legal and governance baseline

Why UK first:

- it is the stated launch market, allowing one operational policy pack and one regulator-facing interpretation to be tested before expansion;
- ICO guidance directly covers electronic marketing across email, text and private social messaging ([ICO electronic-mail marketing](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/guide-to-pecr/electronic-and-telephone-marketing/electronic-mail-marketing/));
- the current UK automated-decision regime can be implemented as a versioned policy after the 2026 DUAA commencement ([Government commencement plan](https://www.gov.uk/guidance/data-use-and-access-act-2025-plans-for-commencement), [ICO DUAA summary](https://ico.org.uk/about-the-ico/what-we-do/legislation-we-cover/data-use-and-access-act-2025/the-data-use-and-access-act-2025-duaa-summary-of-the-changes/data-protection/)).

UK first does not mean “UK rules satisfy the EU.” Externalize lawful basis, notices, consent, retention, residency, automated-decision safeguards and prohibited-use rules into jurisdiction/version policy packs. The EU AI Act is a separate risk-based product regime and must be classified by intended purpose at EU expansion ([official EU AI Act](https://eur-lex.europa.eu/eli/reg/2024/1689/)).

The send-policy service must evaluate recipient/subscriber type, jurisdiction, channel, purpose, sender identity, lawful basis, consent evidence, soft-opt-in facts, suppression/objection state, customer rules and required identity/opt-out text. PECR covers direct social messages as electronic mail, and individuals have strong objection rights for direct marketing ([ICO B2B marketing](https://ico.org.uk/for-organisations/direct-marketing-and-privacy-and-electronic-communications/business-to-business-marketing/)). The model may draft content but must never determine legal eligibility.

Governance artifacts:

- AI-system and workflow inventory with intended purpose and prohibited uses;
- named business, engineering, privacy, security and model-risk owners;
- DPIA/impact assessment and current data-flow map;
- risk register and treatment evidence;
- model, prompt, retrieval, embedding, tool and supplier register;
- evaluation datasets, slice coverage, thresholds and signed release report;
- incident, appeal, correction, deletion and model rollback procedures;
- user/admin training and automation-tier policy;
- periodic audit and management review.

ISO/IEC 42001 is a certifiable AI management-system standard requiring establishment, implementation, maintenance and continual improvement of an AIMS ([ISO/IEC 42001:2023](https://www.iso.org/standard/42001)); NIST AI RMF is a voluntary risk framework; OWASP is security guidance; OpenTelemetry is an observability specification; UK GDPR/DUAA/PECR are law and regulatory duties. They must not be represented as interchangeable “compliance frameworks.”

## Source-backed implementation rules

1. Never hard-code a vendor quota; observe headers/events, budget per tenant and expose connector health.
2. Never accept a webhook before authenticity validation and durable enqueue.
3. Never treat a webhook or event stream as complete; maintain replay plus reconciliation.
4. Never allow retrieved content to grant itself permissions or change policy.
5. Never let an LLM decide whether marketing contact is lawful.
6. Never display self-reported model confidence as observed correctness.
7. Never auto-execute an action solely because prose “looks confident.”
8. Never store raw prompts, bodies, transcripts or credentials in default telemetry.
9. Never make LinkedIn scraping or unauthorized automation a product dependency.
10. Never claim human oversight when the reviewer lacks evidence, time or authority to change the result.
11. Never couple backfill traffic to interactive workflow capacity.
12. Never allow one tenant's source quota, backlog, model spend or poisoned input to affect another tenant.

## Primary-source watchlist

These facts are time-sensitive and should be checked at least quarterly and before each connector release:

- ICO's final post-DUAA automated-decision guidance: the ICO states its ADM guidance is being updated ([ICO technology guidance plan](https://ico.org.uk/about-the-ico/what-we-do/our-plans-for-new-and-updated-guidance/technology/)).
- Salesforce API/Pub/Sub allocations and supported editions ([Pub/Sub overview](https://developer.salesforce.com/docs/platform/pub-sub-api/guide/intro.html)).
- Graph subscription lifetimes, Teams organization quotas, permissions and licensing ([Graph notifications](https://learn.microsoft.com/en-us/graph/change-notifications-overview)).
- Slack per-method rate limits and token policies ([Slack rate limits](https://api.slack.com/apis/rate-limits)).
- LinkedIn partnership availability, access tiers, scopes and API versions ([Sales Navigator](https://learn.microsoft.com/en-us/linkedin/sales/), [Marketing access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access)).
- NIST AI RMF revision status: NIST marks AI RMF 1.0 as under revision ([NIST AI RMF](https://www.nist.gov/itl/ai-risk-management-framework)).
- OpenTelemetry GenAI semantic-convention maturity and version ([OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/)).
