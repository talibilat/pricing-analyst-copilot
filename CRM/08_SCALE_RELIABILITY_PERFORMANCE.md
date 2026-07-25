# Scale, Reliability, and Performance

## Capacity model

Capacity is driven by:

`tenants × active users × events/user/day × workflows/event × model/tool calls/workflow × peak factor`.

Track separately:

- interactive review requests;
- webhook/event bursts;
- scheduled deal-health scans;
- connector backfills;
- AI token throughput;
- external API allocations;
- vector/index ingestion;
- evaluation and analytics batches.

Before pilot, build low/base/high forecasts and measure real distributions. Never size from averages alone; calendar boundaries, campaign sends, and end-of-quarter activity produce correlated peaks.

## Horizontal scaling

- stateless APIs scale on concurrency and latency;
- event consumers scale by partitions while preserving resource-local order;
- AI workers scale by task class, token budget, and provider quota;
- connector workers scale by provider/tenant with fair scheduling;
- backfills use separate capacity from interactive actions;
- database reads use replicas only for safe stale-tolerant paths;
- large tenants graduate to dedicated cells/shards.

## Noisy-neighbour controls

- per-tenant request, event, token, storage, and connector quotas;
- weighted fair queues;
- maximum concurrent workflows per tenant/user;
- batch admission control;
- cost ceiling and anomaly kill switch;
- circuit breakers scoped to provider and tenant where possible;
- rate-limit debt cannot spill unboundedly into other tenants.

## Reliability patterns

- durable workflow state and timers;
- transactional outbox/inbox;
- idempotent consumer and external command keys;
- exponential backoff with jitter and provider hints;
- retry budget and dead-letter queue;
- circuit breaker and bulkhead;
- request hedging only for safe reads;
- deadline propagation and cancellation;
- read-back verification;
- scheduled reconciliation;
- regional fencing to avoid dual writers;
- tested backup restore and disaster recovery.

## Idempotency

An action key is derived from tenant, workflow run, immutable proposal version, action ordinal, and target system. The action table records `NOT_STARTED`, `IN_FLIGHT`, `AMBIGUOUS`, `SUCCEEDED`, `VERIFIED`, or `FAILED_FINAL`.

After an ambiguous timeout, query the provider using stable identifiers or reconciliation before retrying. Email sends and public/internal messages must never be blindly repeated.

## Performance budgets

Illustrative post-meeting budget:

- event validation/queue: 1 second p95;
- canonical/context reads: 2 seconds p95;
- parallel analysis branches: 8 seconds p95;
- verification/composition: 4 seconds p95;
- policy/confidence/package: 1 second p95;
- total interactive draft: 15 seconds p95.

Use progressive UI: show workflow received, context gathered, analysis ready, and actions pending. A slower but correct result remains usable if progress and cancellation are visible.

## Cost optimisation order

1. Eliminate unnecessary workflows and duplicate events.
2. Retrieve less and summarise deterministically where possible.
3. Cache stable, non-sensitive prompt prefixes and metadata safely.
4. Route simple validated tasks to smaller models.
5. Parallelise only independent work that improves wall time.
6. Batch offline features/evaluations.
7. Cap output verbosity and revision loops.
8. Negotiate provider capacity after workload is measured.

Cost per completed verified workflow is the unit measure - not raw token price.

## Load and resilience tests

- steady, burst, soak, and tenant-skew load;
- end-of-quarter burst profile;
- large Salesforce schema and opportunity history;
- webhook replay storm;
- provider 429/5xx/latency;
- model capacity error and malformed output;
- queue partition loss/rebalance;
- database failover and hot tenant;
- subscription renewal backlog;
- regional failover and restoration;
- deletion across large tenant;
- kill switch during in-flight actions.

## Service-level indicators

- request availability/latency;
- event age and terminal-workflow latency;
- action verified-success rate;
- duplicate external-effect rate;
- data freshness and reconciliation divergence;
- approval delivery latency;
- retrieval completeness;
- model schema-valid rate;
- per-provider throttling;
- cost per verified workflow.

Error budgets govern feature release pace. Safety/security incidents are not traded against an availability error budget.
