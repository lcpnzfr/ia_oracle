# ia_oracle - Agent Reference

LLM-backed Oracle and Strategist service for the Forex intelligence pipeline.
It turns high-impact enriched intel into actionable `GlobalTag` events and
periodic `global_pulse` macro SITREPs.

## Role in the Pipeline

```text
collector_events / OSINT / market feeds
  -> intel.events.{domain}
  -> collector_events.translation
  -> intel.translated.{domain}
  -> forex_nlp.NLPEnrichmentSession
  -> intel.enriched.{domain}
  -> intel.oracle.review
  -> ia_oracle.OracleWorker
  -> intel.oracle.resolved
  -> intel.global_tags

intel.enriched.# + Mongo intel_items/oracle_resolved/market_opportunities
  -> ia_oracle.StrategistWorker
  -> Mongo global_pulse
  -> Redis global_pulse:latest
  -> intel.global_tags / trading.signals
```

`GlobalTag` is consumed by `session_manager`, `executor_trading`, risk logic,
and API/streaming surfaces. `global_pulse` is the latest macro narrative and is
used by `OracleWorker` as context for later reviews.

## Main Modules

- `ia_oracle/main.py`: standalone `OracleWorker` bootstrap.
- `ia_oracle/worker.py`: MQ-driven Oracle review worker.
- `ia_oracle/strategist_worker.py`: Global Pulse synthesis worker.
- `ia_oracle/store.py`: Mongo store for Oracle decisions and GlobalTags.
- `ia_oracle/strategist_store.py`: Mongo store/aggregation for Global Pulse.
- `ia_oracle/providers/`: IA providers for Ollama, Gemini, and OpenAI native.
- `ia_oracle/prompts/`: Oracle, translator, summarizer, and strategist prompts.
- `test_mq_publisher.py` / `test_mq_subscriber.py`: local MQ harnesses.

Ignore generated/runtime data when reasoning about source:

- `*.egg-info/**`
- `__pycache__/**`
- `.venv/**`
- `logs/**`
- `test_runs/**`
- `ia_oracle/data/*.json` unless explicitly used as fixtures

## OracleWorker

`ia_oracle/worker.py` is the production Oracle MQ worker.

Topics:

- consumes `IntelTopics.ORACLE_REVIEW` (`intel.oracle.review`);
- publishes `IntelTopics.ORACLE_RESOLVED` (`intel.oracle.resolved`);
- publishes `IntelTopics.GLOBAL_TAGS` (`intel.global_tags`) when the Oracle
  action is `EMIT`.

Startup:

1. Registers local IA providers in `IAProviderFactory`.
2. Creates provider from environment.
3. Initializes `StrategistStore` to read latest Global Pulse and market
   opportunities.
4. Connects MQ and subscribes to `intel.oracle.review`.
5. Uses `asyncio.Semaphore(max_sessions)` for LLM concurrency.

Per review:

1. Deserialize `OracleReviewRequest`.
2. Load latest Global Pulse from MongoDB, falling back to Redis
   `global_pulse:latest`.
3. Inject `macro_context`, `domain_context`, `regional_context`, and market
   opportunity context into the request.
4. Select prompt by `prompt_type`: `trend`, `trend_fast`, `fundamental`,
   `interest_rate`, or `summarizer`.
5. Call the configured IA provider.
6. Parse either the current nested `ia_trend_oracle_v1` response or the legacy
   flat schema.
7. Publish `OracleReviewResponse` to `intel.oracle.resolved`.
8. If action is `EMIT`, convert directives into `GlobalTag` payloads and publish
   to `intel.global_tags`.
9. Persist results to MongoDB if a store is available.

Default tag TTL is 240 minutes unless a directive provides
`volatility_duration_minutes`.

Entrypoint:

```powershell
python -m ia_oracle.main --worker-id oracle_worker_1 --max-sessions 1
python -m ia_oracle.main --provider OPENAI_NATIVE --model gpt-4.1
python -m ia_oracle.main --no-mongo --no-output-file
```

`main.py` calls `EnvConfigManager.startup()`, then loads the repo `.env` with
override enabled. Be aware that local `.env` may override Mongo-backed env
config for Oracle runtime.

## Oracle Persistence

`OracleMongoStore` writes:

- `oracle_resolved`: idempotent by `trigger_event_id`;
- `global_tags`: emitted tags and one decision envelope per Oracle result.

Important methods:

- `store_item(response)`;
- `store_global_tag(tag)`;
- `store_oracle_decision_tag(response)`;
- `get_global_tag(trigger_event_id, asset)`.

Persistence failures should not interrupt MQ processing.

## StrategistWorker and Global Pulse

`ia_oracle/strategist_worker.py` builds the Global Narrative Pulse/SITREP.

Triggers:

- subscribes to `intel.enriched.#`;
- high-danger events (`danger_score >= 0.9`) may trigger immediate synthesis
  after a cooldown;
- periodic loop attempts scheduled synthesis roughly every 12 minutes;
- recovery loop retries failed global-stage synthesis runs.

Synthesis flow:

1. `StrategistStore.fetch_semantic_gems()` reads recent high-danger
   `intel_items`, weighted with `oracle_resolved` confidence when available.
2. Fetch current market context from Mongo `market_opportunities` and Yahoo
   Finance prices.
3. Fetch previous completed pulse for continuity.
4. Story pass: group semantic gems into narratives.
5. Domain pass: synthesize thematic/domain SITREPs.
6. Incremental BLUF/global pass: update the macro summary.
7. Market implications pass: generate actionable asset implications.
8. Persist progress/checkpoints into Mongo.
9. Cache completed pulse to Redis as `global_pulse:latest`.
10. Emit regional bias `GlobalTag` events.
11. Optionally emit high-conviction meta-signals to `trading.signals`.

Mongo collections:

- `global_pulse`;
- `global_pulse_synthesis_runs`;
- reads `intel_items`;
- reads `oracle_resolved`;
- reads `market_opportunities`.

The completed pulse includes fields such as:

- `bluf`;
- `domain_pulses`;
- `regional_highlights`;
- `market_implications`;
- `indicators_to_watch`;
- `affected_currencies`;
- `market_context`;
- `synthesis_run_id`.

`OracleWorker` treats MongoDB as the system of record for pulse context and
Redis as a fast fallback/cache.

## IA Providers

Providers implement `forex_shared.worker_api.IAProvider`.

- `OllamaProvider`: local Ollama async client; supports JSON format mode and
  long timeouts for synthesis.
- `GeminiIAProvider`: Google Gemini via `google-genai`; discovers models,
  rotates on quota/unavailable errors, supports URL context and Google Search.
- `OpenAIIAProvider`: native OpenAI Responses API; discovers models, rotates
  across a fallback chain, supports structured JSON and optional web search.

Provider selection is via `IAProviderFactory.create_from_env()` and shared
Oracle/IA environment config.

## Relations With Other Repos

- `collector_events.translation.session` imports IA providers from this repo to
  translate raw `intel.events.#` payloads into English.
- `forex_nlp.NLPEnrichmentSession` creates `OracleReviewRequest` payloads for
  high-impact enriched intel and publishes them to `intel.oracle.review`.
- `collector_events.events_extractors` and OSINT Telegram relay create raw
  IntelItems that eventually flow into translation/NLP/Oracle.
- `session_manager.EventDrivenTradingSession` consumes `intel.global_tags` and
  passes macro/rate context into strategy `additional_data`.
- `executor_trading.TradeMonitor` and pre-trade risk code consume global tags
  to block/reduce conflicted trades.
- `risk_manager` can react to global tags as macro risk context.

## Compatibility Rules

- Keep Oracle input/output contracts in `forex_shared.domain.oracle`.
- Keep `GlobalTag` contracts in `forex_shared.domain.intel`.
- Do not publish trade orders from Oracle; strategist meta-signals go to
  `trading.signals` and still pass through `executor_trading`.
- Keep LLM response parsing tolerant of both current and legacy schemas.
- Keep Mongo persistence best-effort; MQ publication is the live path.
- Prefer `publish_event()` for structured MQ payloads. Existing `publish()` uses
  should be checked against the provider API before refactoring.
- Do not let a failed Global Pulse final pass discard completed story/domain
  work; use checkpoints/recovery.
- Be careful editing prompts: downstream parsers expect JSON fields for Oracle
  decisions, directives, and strategist implications.

