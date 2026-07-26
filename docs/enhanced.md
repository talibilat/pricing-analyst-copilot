# Complete system documentation

## 1. System at a glance

```mermaid
flowchart LR
    User["People and integrations<br/>Submit questions, workflows, and operational commands"]
    Entry["Streamlit, API, and CLI<br/>Accept requests and return results"]
    Chat["Chat service<br/>Chooses the right response path for a question"]
    Workflow["Governed workflow<br/>Builds and checks a pricing recommendation"]
    Sources["Analytics and market evidence<br/>Provide approved facts and documents"]
    Operations["Operations services<br/>Store decisions, replays, evaluation, and drift reports"]

    User --> Entry
    Entry --> Chat
    Entry --> Workflow
    Chat --> Sources
    Chat --> Workflow
    Workflow --> Sources
    Entry --> Operations
```

> How to read this diagram: People use the Streamlit app, API, or CLI.
> The chat service answers questions directly or starts the governed workflow.
> Both use approved evidence, while operations services keep the records needed to monitor and improve the system.

## 2. Ways to use the system

```mermaid
flowchart TB
    Analyst["Analyst<br/>Uses the chat and monitoring screens"] --> UI["Streamlit app<br/>Presents answers, decisions, and drift reports"]
    Client["API client<br/>Calls the chat, workflow, or decision endpoints"] --> API["FastAPI service<br/>Exposes programmatic access"]
    Operator["Operator<br/>Runs maintenance and evaluation tasks"] --> CLI["CLI commands<br/>Build data, ingest documents, evaluate, and monitor"]

    UI --> Results["Results and records<br/>Answers, recommendations, decisions, and reports"]
    API --> Results
    CLI --> Results
```

> How to read this diagram: The system has three entry points.
> Streamlit is for analyst work, the API is for other software, and the CLI is for operational jobs.
> Each produces a useful answer, report, or stored record.

## 3. Chat request journey

```mermaid
sequenceDiagram
    participant Analyst as Analyst
    participant Chat as Chat service - understands the request
    participant Plan as Conversation planner - selects a safe response path
    participant Tools as Approved tools - retrieve only allowed evidence
    participant Flow as Governed workflow - analyses complex pricing questions

    Analyst->>Chat: Ask a question with context
    Chat->>Plan: Classify the request and resolve scope
    alt Help, clarification, or refusal
        Plan-->>Chat: Write a direct safe response
    else Simple lookup
        Plan->>Tools: Retrieve permitted rows or documents
        Tools-->>Chat: Return cited evidence
    else Analysis or recommendation
        Plan->>Flow: Start an evidence-backed analysis
        Flow-->>Chat: Return a checked recommendation and evidence
    end
    Chat-->>Analyst: Return one clear ChatResponse
```

> How to read this diagram: Every chat message is planned before evidence is read.
> Simple requests use approved lookups.
> Pricing analysis goes through the governed workflow, which returns a checked, evidence-backed result.

## 4. Who can access evidence

```mermaid
flowchart TB
    Planner["Conversation planner<br/>Chooses which approved source a chat request may use"]
    Supervisor["Portfolio supervisor<br/>Coordinates specialist analysis for a workflow"]
    Specialists["Specialists<br/>Interpret claims, conversion, market, and price-history evidence"]
    Tools["Approved tool layer<br/>Limits every request to a fixed, safe payload"]
    Analytics["Analytics database and calculators<br/>Provide portfolio metrics and price history"]
    Documents["Market retrieval service<br/>Finds scoped documents and removes unsafe content"]
    Ledger["Evidence ledger<br/>Records the facts and sources used in a recommendation"]

    Planner --> Tools
    Supervisor --> Specialists
    Specialists --> Tools
    Tools --> Analytics
    Tools --> Documents
    Specialists --> Ledger
```

> How to read this diagram: Models and specialists do not read databases directly.
> They use the approved tool layer, which restricts what can be retrieved.
> Specialist findings are preserved in the evidence ledger for later checking.

## 5. Governed pricing workflow

```mermaid
flowchart LR
    Question["Portfolio question<br/>States the requested pricing investigation"]
    Check["Scope and data checks<br/>Reject unsupported scenarios or invalid inputs"]
    Evidence["Evidence collection<br/>Calculate metrics and retrieve safe market documents"]
    Review["Specialist review<br/>Compare claims, conversion, market, and price history"]
    Draft["Recommendation draft<br/>Propose an evidence-backed action"]
    Guard["Validation and governance review<br/>Check citations, figures, scope, and language"]
    Result["Workflow result<br/>Return a recommendation, confidence, evidence, and caveats"]
    Safe["Safe INVESTIGATE result<br/>Explain why a recommendation cannot be made yet"]

    Question --> Check --> Evidence --> Review --> Draft --> Guard --> Result
    Check -. invalid .-> Safe
    Evidence -. incomplete, stale, or conflicting .-> Safe
    Guard -. cannot approve .-> Safe
```

> How to read this diagram: A recommendation is only produced after scope, data, evidence, and governance checks pass.
> Any failed safety check produces an INVESTIGATE result instead of an unsupported recommendation.

## 6. How an answer is produced

```mermaid
flowchart TB
    Request["Analyst question<br/>Provides the intent and context"]
    Route["Request plan<br/>Chooses the appropriate answer route"]
    Direct["Direct response<br/>Explains, clarifies, or refuses without business evidence"]
    Lookup["Evidence lookup<br/>Combines approved database rows and safe documents"]
    Analysis["Governed analysis<br/>Builds a checked recommendation from an evidence ledger"]
    Replay["Replay or report lookup<br/>Returns a saved response, evaluation, or drift report"]
    Answer["Chat response<br/>Presents the answer, tables, citations, and caveats"]

    Request --> Route
    Route --> Direct --> Answer
    Route --> Lookup --> Answer
    Route --> Analysis --> Answer
    Route --> Replay --> Answer
```

> How to read this diagram: The request plan keeps response types distinct.
> Direct chat does not query evidence, lookups cite retrieved evidence, analysis uses the governed workflow, and replay or reporting routes read saved artifacts.

## 7. Data and persisted records

```mermaid
flowchart LR
    Build["Data-building jobs<br/>Create portfolio analytics and ingest market intelligence"]
    Stores["Evidence stores<br/>Keep analytics tables, market documents, vectors, and raw files"]
    Read["Application readers<br/>Retrieve approved evidence for chat and workflows"]
    Records["Operational records<br/>Keep analyst decisions, replays, traces, evaluation, and drift"]
    Monitor["Monitoring and governance services<br/>Assess quality, drift, and recommendation outcomes"]

    Build --> Stores --> Read
    Read --> Records
    Records --> Monitor
    Stores --> Monitor
```

> How to read this diagram: Data-building jobs create the evidence stores used by the application.
> Separate operational records make decisions and system behavior auditable, while monitoring compares those records with the underlying data.

## 8. Market-intelligence ingestion and retrieval

```mermaid
flowchart LR
    Files["Raw market documents<br/>Supply competitor, customer, and market information"]
    Ingest["Ingestion pipeline<br/>Loads, chunks, embeds, and catalogues each document"]
    Index["Search index and catalogue<br/>Store document text, metadata, and vector representations"]
    Query["Scoped retrieval request<br/>Specifies allowed scenario, product, region, and dates"]
    Search["Hybrid search<br/>Filters metadata then combines semantic and keyword ranking"]
    Safe["Safe evidence<br/>Removes unsafe content before returning cited documents"]

    Files --> Ingest --> Index
    Query --> Search
    Index --> Search --> Safe
```

> How to read this diagram: Documents are prepared once during ingestion.
> At question time, retrieval first applies scope filters, then combines semantic and keyword search.
> Unsafe content is quarantined before any document becomes evidence.

## 9. Evaluation, drift, and replay

```mermaid
flowchart TB
    Cases["Golden test cases<br/>Define expected chat and workflow behavior"]
    Evaluate["Evaluation runner<br/>Scores chat, governed workflow, and baseline results"]
    Benchmark["Benchmark report<br/>Stores scores and individual case results"]
    Drift["Drift monitor<br/>Checks data, behavior, operations, and configuration changes"]
    Decisions["Analyst decisions and outcomes<br/>Record review of a recommendation and later results"]
    Trace["Workflow traces and replays<br/>Preserve what happened and allow compatible replay"]
    Views["Monitoring and chat views<br/>Show evaluation, drift, replay, and decision information"]

    Cases --> Evaluate --> Benchmark --> Drift --> Views
    Decisions --> Views
    Trace --> Views
```

> How to read this diagram: Golden cases measure quality.
> Their results feed drift monitoring, while decisions, traces, and replays provide additional operational context.
> Analysts can view all of these through the monitoring and chat routes.

## 10. Safety controls

```mermaid
flowchart LR
    Request["Request checks<br/>Validate contracts, supported portfolios, and prohibited attributes"]
    Plan["Planning checks<br/>Allow only approved response plans and evidence sources"]
    Evidence["Evidence checks<br/>Restrict data access and reject unsafe, stale, or conflicting evidence"]
    Agent["Agent checks<br/>Enforce typed outputs and runtime limits"]
    Draft["Recommendation checks<br/>Validate citations, numbers, scope, language, and price range"]
    Human["Human decision<br/>A qualified analyst accepts or rejects the recommendation"]
    Record["Outcome record<br/>Keep the decision separately for audit and learning"]
    Safe["Safe refusal or INVESTIGATE<br/>Stop when the system cannot support a reliable answer"]

    Request --> Plan --> Evidence --> Agent --> Draft --> Human --> Record
    Request -. block or clarify .-> Safe
    Evidence -. missing or unsafe evidence .-> Safe
    Agent -. service failure .-> Safe
    Draft -. cannot validate .-> Safe
```

> How to read this diagram: Controls are applied in layers, from the incoming request through the final analyst decision.
> A problem at any automated layer stops the path and returns a safe refusal or INVESTIGATE outcome.
