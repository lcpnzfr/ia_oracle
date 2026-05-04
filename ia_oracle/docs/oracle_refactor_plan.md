# IA Oracle Refactoring Plan (Worker API)

## Objective
Refactor the `async_gemini_processor` (in `ia_oracle`) from a local polling mock into a fully distributed worker using `shared_lib/forex_shared/worker_api`. 

## Sprint 1: Base Infrastructure (Shared Lib) - DONE
- [x] Create `BaseStore(ABC)` in `forex_shared/worker_api/store.py` wrapping `MongoManager`.
- [x] Create `BaseCache(ABC)` in `forex_shared/worker_api/cache.py` wrapping `RedisProvider`.
- [x] Define `OracleReviewRequest`/`Response` dataclasses in the shared domain.
- [x] Create `BaseEventConsumer(ABC)` in `forex_shared/worker_api/event_consumer.py` for robust MQ subscriptions and message routing.

## Sprint 2: Session & Domain Logic (IA Oracle)
- [ ] Implement `OracleMongoStore(BaseStore)` and `OracleCache(BaseCache)`.
- [ ] Create `OracleSession(BaseSession)`:
  - Subscribes to `intel.oracle.review`.
  - Uses `asyncio.Semaphore` to rate-limit Gemini API calls.
  - Publishes results via `MQEventPublisher` to `intel.oracle.resolved`.
  - Stores results in MongoDB and Redis.

## Sprint 3: Worker & Broker Orchestration
- [ ] Create `OracleWorker(BaseSessionWorker)` to host `OracleSession`s.
- [ ] Create `OracleBroker(BaseBroker)` to manage workers and scale.
- [ ] Implement `main.py` entrypoint.

## Sprint 4: Testing & Migration
- [ ] Write integration test (`test_oracle_worker.py`).
- [ ] Delete legacy `async_gemini_processor` and mock ingestors.
- [ ] Test end-to-end flow with `GlobalTagEmitter` (from `collector_events`).