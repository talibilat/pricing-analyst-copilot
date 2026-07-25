# AI Evaluation Strategy

## Evaluation is a release system

Evaluation begins before implementation and continues in production. Each workflow version has an evaluation contract defining population, rubric, slice, metric, minimum threshold, confidence interval, risk owner, and release consequence.

Passing an average score is insufficient. Safety-critical and enterprise slices have hard floors.

## Evaluation layers

| Layer | Examples | Run when |
|---|---|---|
| Deterministic | schema, permissions, citations exist, dates/amounts valid | every build/request |
| Component | identity resolution, retrieval, extraction, classification, drafting | every relevant change |
| Agent | tool selection, stopping, grounded output, budget use | every prompt/model/tool change |
| Workflow | end-to-end post-meeting package and execution verification | pre-merge/nightly |
| Safety | injection, data leakage, disallowed action, harmful content | pre-release and recurring |
| Human quality | correctness, usefulness, tone, edit severity | sampled releases/production |
| Online outcome | adoption, overrides, errors, business outcome | continuous |

## Dataset programme

### Dataset types

- synthetic contract and schema cases for broad edge coverage;
- expert-authored canonical examples;
- de-identified or contractually authorised pilot traces;
- adversarial red-team cases;
- production failures converted to regression cases;
- counterfactual cases that change one material fact;
- longitudinal opportunity histories for point-in-time evaluation.

### Split strategy

Split by tenant/account and time, not random message. Keep a sealed final holdout. Near-duplicate detection prevents the same meeting/template appearing across train and test. Evaluation data never flows into shared training without an explicit legal and contractual path.

### Required slices

- UK English and common international English variants;
- short/long/noisy transcripts;
- multiple speakers and unresolved identities;
- large/custom Salesforce schemas;
- missing/stale/contradictory CRM information;
- opt-outs, complaints, legal/security/procurement content;
- different sales stages, industries, team sizes, and deal cycles;
- provider throttling, timeout, duplicate and out-of-order events;
- prompt injection inside emails, notes, attachments, and social text;
- protected/sensitive references and proxy-feature tests.

## Task rubrics

### Meeting analysis

- atomic factual precision/recall;
- speaker attribution;
- commitment owner/due-date accuracy;
- question and objection recall;
- unsupported claim rate;
- material contradiction rate;
- evidence-locator accuracy.

### CRM mapping

- correct object and field;
- correct proposed value;
- no unauthorised field;
- no overwriting newer data;
- custom-field robustness;
- appropriate abstention.

### Drafting

- all required questions answered;
- facts and claims grounded;
- recipients correct;
- no invented commitments or pricing;
- tone/template compliance;
- opt-out and prohibited-content compliance;
- human edit distance and edit severity.

### Deal health

- ranking quality and precision at review capacity;
- recall of genuinely stalled/high-risk cases;
- calibration and risk-coverage;
- stability under small irrelevant changes;
- subgroup/tenant performance;
- action usefulness;
- lead-time before the business outcome.

## Graders

Use multiple grader types:

- exact deterministic checks;
- schema and policy validators;
- source-grounded entailment/contradiction grader;
- expert human rubric;
- pairwise blinded preference;
- LLM grader only after agreement against experts is measured.

An LLM judge cannot be the sole grader for its own model family on high-risk criteria. Grader prompts and models are versioned and evaluated. Human disagreements are adjudicated and used to improve the rubric.

## Confidence evaluation

For each calibrated output:

- reliability diagram;
- expected calibration error;
- Brier score and log loss;
- precision/recall at every proposed threshold;
- risk-coverage curve;
- abstention precision: percentage of abstentions that truly needed review;
- automation false-positive budget.

Thresholds are approved by product, AI, security/privacy, and workflow owner where consequential.

## Agent-specific tests

- chooses only allowed tools;
- never calls a write tool;
- uses the minimum necessary retrieval;
- handles tool denial/empty/error explicitly;
- stops within calls/tokens/time;
- does not follow instructions embedded in source data;
- cites every material claim;
- does not repeat expensive calls;
- preserves typed handoff invariants;
- fails safely when another agent produces malformed output.

## Integration and fault evaluation

Replay end-to-end traces with:

- duplicate events;
- out-of-order events;
- webhook signature failure;
- subscription expiry;
- 429 with and without retry hints;
- timeout before/after provider accepted a write;
- stale ETag/version;
- partial multi-action success;
- revoked permission;
- tenant quota exhaustion;
- model timeout or invalid schema;
- regional failover.

The assertion is the external business state plus audit trail, not merely an HTTP status.

## Release gates

A model/prompt/retrieval/feature change cannot progress unless:

1. deterministic and security tests pass;
2. no critical slice regresses;
3. aggregate quality meets the task floor;
4. unsupported material claims remain below the agreed ceiling;
5. confidence remains calibrated or thresholds are recomputed;
6. latency and cost remain within budget;
7. human review approves sampled outputs for material changes;
8. shadow deployment shows no new production failure cluster;
9. canary has automatic rollback criteria.

## Production evaluation

Sample using risk-weighted and random strategies. Capture approval, rejection, edits, reason codes, subsequent correction, execution verification, complaints, opt-outs, and business outcomes. Do not interpret “accepted” as “correct” without periodic expert audit.

Drift detectors cover input length/language/source, feature distributions, missingness, retrieval relevance, output taxonomy, confidence, calibration, edit severity, abstention, provider/version, and cost.

## Evaluation ownership

| Owner | Accountability |
|---|---|
| Product/workflow owner | usefulness and business rubric |
| AI engineering | datasets, graders, calibration, regressions |
| Domain sales expert | label quality and operational realism |
| Security/privacy/legal | prohibited outcomes and risk slices |
| Platform/SRE | performance and fault tests |
| Independent release reviewer | evidence that gates passed |
