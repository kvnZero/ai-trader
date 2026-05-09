# Task Breakdown

## Project Goal

Build an AI-assisted A-share investment research system with independently deliverable capabilities:

1. A-share market data access through `AKShare`
2. Technical analysis for K-line and market structure
3. Sentiment collection from finance platforms and fast-news sources
4. Mapping sentiment items to affected listed companies
5. A trader agent with financial domain reasoning
6. Explainable buy / sell / watch recommendations

## Delivery Principles

1. Each capability must be independently implementable, testable, and replaceable.
2. Shared contracts should use structured Python schemas rather than direct cross-module coupling.
3. The trader agent must consume normalized data from upstream modules and should not fetch raw external data directly.
4. Deterministic analysis and scoring should be separated from LLM reasoning so recommendations remain explainable and auditable.
5. External data adapters must account for rate limits, missing fields, retries, caching, and source instability.
6. Implementation cadence must follow small-feature commits: complete one small functional unit, commit it, then move to the next.
7. Ambiguous product details should be completed proactively using sound financial-system design judgment.

## Module Boundaries

| Module | Responsibility | Inputs | Outputs |
| --- | --- | --- | --- |
| `market_data` | Fetch and normalize A-share market data via AKShare | Stock code, date range, granularity | Quotes, K-line, turnover, sector/fundamental data |
| `technical_analysis` | Compute indicators and K-line pattern signals | Normalized market data | Trend summary, indicator values, pattern events, risk tags |
| `sentiment_ingestion` | Collect finance content and fast-news items | Source config, keywords, polling window | Normalized sentiment/news items |
| `entity_mapping` | Map content to listed companies and stock codes | Normalized content, company dictionary | Affected company list, confidence score, matched evidence |
| `trader_agent` | Reason over structured signals with financial knowledge | Market analysis, sentiment summary, metadata | Buy/sell/watch proposal with rationale |
| `recommendation_engine` | Fuse deterministic scores and agent output | Technical signals, sentiment impact, agent result | Final recommendation, confidence, risk notes |
| `delivery_api` | Expose pages/API/tasks for internal use | Requests from UI or scheduler | JSON/API responses and rendered pages |

## Task List

### T001. Shared Architecture and Contracts

**Goal**

Define the project structure, module contracts, configuration layout, and shared schemas so each capability can evolve independently.

**Deliverables**

- Application package structure for routes, services, adapters, and schemas
- Shared config management for API keys, polling intervals, cache TTL, and runtime switches
- Domain schemas for quote data, K-line bars, sentiment items, company entities, and recommendation payloads
- Error handling and logging conventions

**Acceptance Criteria**

- Every downstream module can import only shared schemas/config without directly depending on sibling internals
- Contract examples exist for market data, sentiment data, and recommendation output
- Local development can run with feature flags even when some modules are not yet implemented

### T002. AKShare Market Data Module

**Goal**

Integrate `AKShare` as the A-share market data source and provide normalized interfaces for quotes, K-line, sector, and optional fundamental data.

**Deliverables**

- AKShare adapter layer
- Normalized query service for stock list, daily/weekly/minute K-line, real-time quote, sector/industry, and basic fundamentals
- Caching and retry policy
- Source availability and error fallbacks

**Acceptance Criteria**

- Given a stock code, the module returns normalized K-line data with consistent field names
- The module can independently fetch at least one real-time/near-real-time market snapshot and one historical range
- Errors from AKShare are converted into internal error types rather than leaking raw exceptions

### T003. Technical Analysis Module

**Goal**

Analyze A-share K-line data and produce structured technical signals without involving the LLM.

**Deliverables**

- Indicator computation: MA, EMA, MACD, RSI, Bollinger Bands, volume change, volatility
- K-line pattern recognition: breakout, pullback, long upper shadow, long lower shadow, gap, trend reversal candidates
- Trend/risk summary service
- Signal scoring output for downstream recommendation use

**Acceptance Criteria**

- Given normalized bars from `market_data`, the module returns indicator values and pattern flags
- Output includes both bullish and bearish evidence, not just one-sided signals
- The module can be unit-tested using stored sample K-line data without any network dependency

### T004. Sentiment Ingestion Module

**Goal**

Collect finance-related content and fast-news updates from selected sources, normalize them, and preserve source metadata.

**Deliverables**

- Source adapter interface for news sites, fast-news feeds, and approved content platforms
- Normalized sentiment/news schema with title, body, source, timestamp, URL, tags, and raw payload reference
- De-duplication and source freshness logic
- Compliance/source configuration notes for what is allowed to ingest

**Acceptance Criteria**

- The module can ingest multiple source formats into one internal schema
- Duplicate items across polling windows are suppressed
- Source metadata is retained so later analysis can explain where a signal came from

### T005. Company Entity Mapping Module

**Goal**

Infer which listed companies are affected by each sentiment item or news flash.

**Deliverables**

- Listed company dictionary and alias library
- Name/ticker/industry/theme matching rules
- Confidence scoring for company-impact mapping
- Evidence extraction that explains why a company was linked

**Acceptance Criteria**

- For a given sentiment item, the module outputs zero, one, or multiple mapped companies with confidence scores
- Ambiguous mentions are represented as low-confidence instead of forced matches
- The module can run independently on stored sample news items

### T006. Trader Agent Module

**Goal**

Build a trader-style AI agent that consumes structured market and sentiment inputs and emits explainable trading opinions.

**Deliverables**

- Agent role definition, system prompt, reasoning constraints, and output schema
- Input assembly layer combining technical, sentiment, and company-impact summaries
- Recommendation types: `buy`, `sell`, `watch`, `avoid`
- Explanation format covering thesis, trigger conditions, invalidation conditions, and key risks

**Acceptance Criteria**

- The agent never depends on raw AKShare or crawler calls directly
- Agent outputs are schema-validated and machine-readable
- Output includes explicit reasoning, not only a label

### T007. Recommendation Engine Module

**Goal**

Fuse deterministic signals and trader-agent output into a final recommendation suitable for UI/API display.

**Deliverables**

- Weighted decision layer for technical signals, sentiment impact, and agent opinion
- Confidence scoring
- Risk controls: insufficient data, conflicting signals, stale data, high-volatility warnings
- Final explanation payload for frontend display

**Acceptance Criteria**

- The engine can produce a final result even when some optional modules are unavailable
- Conflicting bullish/bearish evidence is surfaced explicitly
- Final output clearly distinguishes deterministic evidence from agent interpretation

### T008. Delivery API and UI Module

**Goal**

Expose the independent capabilities through Flask pages and API endpoints for internal use and later productization.

**Deliverables**

- API endpoints for market query, technical analysis, sentiment query, entity mapping, agent recommendation, and final fused recommendation
- Minimal pages/dashboard for manual verification
- Background task entry points for polling and refresh jobs

**Acceptance Criteria**

- Each capability has an isolated endpoint or page for standalone verification
- A developer can trigger a single module without running the full pipeline
- API responses follow the shared schema contracts

### T009. Scheduling, Persistence, and Cache Module

**Goal**

Support polling, snapshot retention, and repeatable analysis runs.

**Deliverables**

- Persistence plan for quotes, sentiment items, mappings, and recommendations
- Cache policy for hot market queries
- Scheduled jobs for data refresh and sentiment polling
- Traceable run records for recommendation generation

**Acceptance Criteria**

- A recommendation can be traced back to the market snapshot and sentiment items that produced it
- Polling jobs can run without blocking page requests
- Cache and persistence policies are configurable per module

### T010. Evaluation and Risk-Control Module

**Goal**

Ensure the system is measurable, explainable, and controlled before heavier automation.

**Deliverables**

- Offline evaluation dataset for sample stocks/news cases
- Recommendation quality checks
- Logging/observability for source failures, mapping failures, and agent output issues
- Risk disclaimers and usage boundaries for investment advice scenarios

**Acceptance Criteria**

- Each core module has at least one independent verification path
- Recommendation output can be reviewed after the fact with sufficient evidence
- The system clearly identifies when it lacks enough information to issue a confident signal

## Suggested Implementation Order

1. `T001` Shared Architecture and Contracts
2. `T002` AKShare Market Data Module
3. `T003` Technical Analysis Module
4. `T004` Sentiment Ingestion Module
5. `T005` Company Entity Mapping Module
6. `T006` Trader Agent Module
7. `T007` Recommendation Engine Module
8. `T008` Delivery API and UI Module
9. `T009` Scheduling, Persistence, and Cache Module
10. `T010` Evaluation and Risk-Control Module

## Commit Discipline

1. Every small feature requires its own git commit.
2. Commit after a feature is implemented and minimally verified.
3. Commit messages should be short and concrete, for example:
   - `add shared domain schemas`
   - `add akshare kline adapter`
   - `add technical indicator service`
4. Avoid combining multiple modules into one commit.
5. Subagent-delivered work should be integrated in the same small-feature granularity.

## Independent Milestones

### Milestone A: Market Intelligence Base

- Complete `T001`, `T002`, and `T003`
- Outcome: query A-share data and produce technical signals without any LLM dependency

### Milestone B: Sentiment Intelligence Base

- Complete `T004` and `T005`
- Outcome: collect finance content and map it to listed companies

### Milestone C: AI Trader Recommendation

- Complete `T006` and `T007`
- Outcome: generate explainable buy/sell/watch recommendations from structured evidence

### Milestone D: Product Delivery and Reliability

- Complete `T008`, `T009`, and `T010`
- Outcome: expose usable endpoints/pages and make the pipeline observable and reviewable

## Current Scope Notes

1. The project should start with research and recommendation support, not direct brokerage execution.
2. Sentiment collection source choices must consider compliance, source terms, and technical accessibility.
3. The first version should prioritize explainability and modularity over full automation.
4. The system should proactively include adjacent expert capabilities when they materially improve recommendation quality, such as risk controls, sector/theme context, data staleness handling, and evidence traceability.
