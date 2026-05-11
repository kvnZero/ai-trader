# AGENTS

## Purpose

This repository is a Flask application initialized with `uv` for Python dependency management and Tailwind CSS for styling. Future work should preserve this baseline unless the user explicitly changes the stack.

The current product direction is an AI-assisted A-share investment research system. Core capabilities must remain independently implementable so that market data, technical analysis, sentiment ingestion, entity mapping, trader agent reasoning, and recommendation output can each be delivered and tested in isolation.
The user has explicitly authorized proactive requirement derivation. Future implementation should infer missing but necessary product capabilities from the A-share AI investment research context instead of waiting for every detail to be specified.

## Stack

- Python `3.12` via `.python-version`
- `uv` for environment, dependency, and command execution
- `Flask` as the web framework
- `Tailwind CSS` via npm CLI, outputting to `app/static/dist/styles.css`

## Working Rules

- Prefer `uv run ...` for Python commands.
- Prefer `uv add` / `uv remove` for Python dependency changes.
- Prefer `npm run dev` for Tailwind watch mode and `npm run build` for production CSS output.
- Keep Flask templates under `app/templates/`.
- Keep source CSS under `app/static/src/`.
- Treat `app/static/dist/styles.css` as a generated artifact; rebuild it instead of hand-editing.
- Do not replace this app layout with a different framework without explicit user approval.
- Keep domain capabilities decoupled behind clear module boundaries and contracts.
- Do not mix AKShare market data access, sentiment crawling, and agent decision logic into one module.
- Prefer structured outputs between modules over prompt-only coupling.
- Every small feature or sub-capability must be committed separately in git.
- Do not accumulate a large batch of unrelated changes into a single commit.
- Each commit message should briefly describe the implemented feature in one line.
- Before starting the next small feature, ensure the current feature is committed.
- Subagents must also work in small, isolated feature increments that are safe to commit independently.

## Current Entry Points

- Flask app object: `main.py`
- Flask app factory: `app/__init__.py`
- Base template: `app/templates/base.html`
- Tailwind input: `app/static/src/input.css`

## Domain Scope

- A-share market data access through `AKShare`
- Technical analysis on K-line / indicators / trend structure
- Sentiment collection from finance news, platform content, and fast-news feeds
- Mapping public sentiment to listed companies and stock codes
- A trader agent that consumes structured inputs and emits explainable buy / sell / watch suggestions

## Product Intent

- This is an AI investment research and recommendation system for China A-share markets.
- The first product stage focuses on research assistance and decision support, not automated order execution.
- Recommendation outputs should prefer `buy`, `sell`, `watch`, and `avoid` style judgments with evidence and risk notes.
- Recommendations must remain explainable, evidence-based, and traceable to underlying market data and sentiment items.
- The system should be designed so deterministic scoring and LLM reasoning can be compared side by side.
- The web platform is a primary operating surface, not a secondary demo layer.
- Users must be able to maintain a personal watchlist of focus stocks and keep them under active monitoring during configured market hours.

## Financial Design Constraints

- Treat data freshness as a first-class concern because market and sentiment signals decay quickly.
- Separate medium-term technical signals from short-term event-driven signals.
- Support company, sector, industry, and theme relationships because A-share moves often propagate across related names.
- Treat conflicting evidence explicitly rather than forcing a single-direction bullish interpretation.
- Prefer conservative confidence scoring when entity mapping or sentiment attribution is ambiguous.
- Always preserve enough structured evidence for later review of why a recommendation was produced.
- Default market-hour monitoring should align with A-share sessions on trading days and pause outside those windows unless the user explicitly overrides it.
- Include market regime detection so the system can distinguish trend, range, panic, and rebound phases before issuing suggestions.
- Include liquidity and slippage awareness so small-cap, low-volume, or wide-spread names can be down-weighted.
- Include event-calendar awareness for earnings, announcements, ex-dividend dates, unlocks, and major macro events.
- Include multi-timeframe confirmation so a short-term signal is not treated as stronger than the broader trend.
- Include a "no-trade" outcome when evidence quality is weak or the setup is too noisy.
- Include post-signal review so the system can learn which setups historically worked better.

## Monitoring Requirements

- Support a user-managed watchlist of stocks under continuous recommendation monitoring.
- Monitoring must have an explicit on/off switch.
- The default monitoring schedule should be limited to A-share market hours on trading days.
- During active monitoring, the platform should refresh analysis and recommendation outputs repeatedly on a configured cadence.
- The UI must clearly show current monitoring state, last refresh time, latest recommendation, and whether monitoring is paused because the market is closed.
- Recommendation changes for watched stocks should produce in-site unread alerts.
- In-site alerts should escalate to a blinking page title until the user has read or acknowledged the new content.

## Derived Capability Guidance

- It is acceptable and expected to derive supporting capabilities such as risk scoring, data freshness checks, event-driven signals, sector/theme linkage, confidence scoring, explainability, and evidence traceability.
- When a requirement is ambiguous, choose the interpretation that best supports a robust A-share research workflow.
- Prefer domain-complete but modular implementations over narrow literal interpretations of the original prompt.

## Next Expected Use

Use `task.md` as the implementation breakdown baseline. Future work should execute capability-by-capability rather than attempting a single large coupled implementation.
Within each capability, execution should proceed sub-feature by sub-feature with one git commit per completed small unit.
