"""StrategistWorker — Orchestrates the multi-stage Global Pulse synthesis.

This worker monitors the enrichment pipeline and periodically (or on critical triggers) 
executes a 3-pass LLM synthesis to generate the 'Global Narrative Pulse'.

Pipeline:
    1. Aggregation: Fetch high-danger 'Semantic Gems' from StrategistStore.
    2. Story Pass: Cluster items into cohesive narratives.
    3. Domain Pass: Synthesize stories into Thematic SITREPs (Conflict, Energy, etc.).
    4. Global Pass: Generate the BLUF and Market Implications.
    5. Persistence: Save to MongoDB 'global_pulse' and update Redis for Oracle.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from forex_shared.worker_api.ia_factory import IAProviderFactory
from forex_shared.providers.mq.mq_factory import MQFactory
from forex_shared.providers.market_data.yahoo_provider import YahooFinanceProvider, ProviderConfig
from forex_shared.providers.cache.redis_provider import RedisProvider
from forex_shared.logging.get_logger import get_logger
from ia_oracle.strategist_store import StrategistStore

log = get_logger(__name__)

class StrategistWorker:
    """The 'Chief Strategist' that synthesizes raw intel into a narrative pulse."""

    def __init__(
        self, 
        store: StrategistStore, 
        worker_id: str = "strategist_1",
        model_override: Optional[str] = "qwen3:4b-instruct-2507-q4_K_M"
    ):
        self.store = store
        self.worker_id = worker_id
        self.model_override = model_override
        
        self.prompts_dir = Path("C:/Projects/forex_system/services/ia_oracle/ia_oracle/prompts")
        self.provider = None
        self._mq = None
        self._is_running = False
        self._last_pulse_at = datetime.fromtimestamp(0, tz=timezone.utc)
        self._last_item_ids_hash = None
        self._synthesis_lock = asyncio.Lock()

    async def start(self):
        """Initialize IA provider and start the synthesis loop/trigger listener."""
        self.provider = IAProviderFactory.create_from_env()
        # Ensure we are using the local Qwen model for synthesis
        if hasattr(self.provider, "model") and self.model_override:
            self.provider.model = self.model_override
            
        await self.provider.initialize()
        log.info("StrategistWorker initialized with IA provider: %s (%s)", 
                 self.provider.provider_type, self.model_override)
        
        self._is_running = True
        self._mq = MQFactory.create_async_from_env()
        await self._mq.connect()
        
        # 1. Listen for new enriched items to trigger delta-re-synthesis
        await self._mq.subscribe_event("intel.enriched.#", self._handle_trigger_event)
        
        # 2. Start the periodic pulse timer (every 30 minutes)
        asyncio.create_task(self._periodic_loop())
        
        log.info("StrategistWorker started. Listening for triggers...")

    async def _handle_trigger_event(self, payload: Dict[str, Any]):
        """Triggered whenever a new event is enriched.
        
        If the event is high-danger (> 0.9), it may trigger an immediate re-synthesis
        subject to a cooldown period.
        """
        extra = payload.get("extra", {})
        danger = float(extra.get("danger_score", 0.0))
        
        if danger >= 0.9:
            log.info("Critical event detected (danger=%.2f). Checking for immediate synthesis...", danger)
            # 5-minute cooldown for triggered synthesis to prevent hammering the local LLM
            if (datetime.now(timezone.utc) - self._last_pulse_at).total_seconds() > 300:
                await self.perform_full_synthesis(reason=f"CRITICAL_EVENT_{payload.get('id')}")

    async def _periodic_loop(self):
        """Background loop for scheduled SITREP updates."""
        while self._is_running:
            await asyncio.sleep(1800) # 30 minutes
            if (datetime.now(timezone.utc) - self._last_pulse_at).total_seconds() > 1700:
                await self.perform_full_synthesis(reason="SCHEDULED_PULSE")

    async def perform_full_synthesis(self, reason: str = "MANUAL", min_danger: float = 0.4):
        """Execute the 3-pass synthesis pipeline."""
        async with self._synthesis_lock:
            run_id = self._build_run_id(reason, min_danger, [])
            pulse_id: str | None = None
            log.info("Starting Full Global Pulse Synthesis (Reason: %s, min_danger=%.2f) | Provider: %s | Host: %s", 
                     reason, min_danger, self.provider.provider_type, getattr(self.provider, '_host', 'unknown'))
            try:
                # Pass 0: Aggregation (Refinement #4: Semantic Gem Selection)
                items = await self.store.fetch_semantic_gems(hours=6, limit=100, min_danger=min_danger)
                if not items:
                    log.info("No semantic gems found in last 6 hours. Skipping pulse.")
                    pulse_id = await self.store.start_pulse_run(
                        run_id=run_id,
                        reason=reason,
                        min_danger=min_danger,
                        item_ids=[],
                    )
                    await self.store.update_pulse_run(
                        pulse_id,
                        stage="skipped_no_items",
                        status="SKIPPED",
                        fields={
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                            "bluf": "No semantic gems found in the configured window.",
                        },
                    )
                    return

                # Deduplication Step A: Check if input items have changed
                current_item_ids = sorted([str(i.get("_id") or i.get("id")) for i in items])
                run_id = self._build_run_id(reason, min_danger, current_item_ids)
                current_hash = hash(tuple(current_item_ids))
                if current_hash == self._last_item_ids_hash and reason == "SCHEDULED_PULSE":
                    log.info("Input items haven't changed since last scheduled pulse. Skipping synthesis.")
                    return

                # Pass -1: Market Context
                market_context = await self._fetch_market_context()

                # Refinement #1: Narrative Continuity (Get Previous Pulse)
                previous_pulse = await self.store.get_latest_pulse()
                previous_bluf = previous_pulse.get("bluf", "Stable market conditions.") if previous_pulse else "No previous SITREP available."
                previous_pulse_id = str(previous_pulse.get("_id")) if previous_pulse else None

                pulse_id = await self.store.start_pulse_run(
                    run_id=run_id,
                    reason=reason,
                    min_danger=min_danger,
                    item_ids=current_item_ids,
                    previous_pulse_id=previous_pulse_id,
                )
                await self.store.update_pulse_run(
                    pulse_id,
                    stage="market_context",
                    fields={
                        "market_context": market_context,
                        "previous_bluf": previous_bluf,
                    },
                )
                await self.store.save_synthesis_checkpoint(
                    run_id=run_id,
                    stage="market_context",
                    payload={
                        "reason": reason,
                        "min_danger": min_danger,
                        "item_count": len(items),
                        "item_ids": current_item_ids,
                        "market_context": market_context,
                    },
                )

                # Pass 1: Story Aggregation
                stories = await self._pass_story_aggregation(
                    items,
                    previous_bluf,
                    run_id=run_id,
                    pulse_id=pulse_id,
                )
                await self.store.save_synthesis_checkpoint(
                    run_id=run_id,
                    stage="stories_complete",
                    payload={"stories": stories},
                )
                await self.store.update_pulse_run(
                    pulse_id,
                    stage="stories_complete",
                    fields={
                        "stories": stories,
                        "story_count": len(stories),
                    },
                )
                
                # Pass 2: Domain Synthesis
                domains = await self._pass_domain_synthesis(
                    stories,
                    previous_bluf,
                    run_id=run_id,
                    pulse_id=pulse_id,
                )
                await self.store.save_synthesis_checkpoint(
                    run_id=run_id,
                    stage="domains_complete",
                    payload={"domains": domains},
                )
                await self.store.update_pulse_run(
                    pulse_id,
                    stage="domains_complete",
                    fields={
                        "domain_pulses": domains,
                    },
                )
                
                # Pass 3: Global Pulse (BLUF)
                pulse = await self._pass_global_synthesis(
                    stories,
                    domains,
                    previous_bluf,
                    market_context,
                    run_id=run_id,
                    pulse_id=pulse_id,
                )
                
                # Finalize and Save
                pulse["reason"] = reason
                pulse["item_count"] = len(items)
                pulse["story_count"] = len(stories)
                pulse["synthesis_run_id"] = run_id
                pulse["_id"] = pulse_id
                
                # Deduplication Step B: Semantic ID Reuse and Content Hashing
                if previous_pulse:
                    is_identical = pulse.get("bluf") == previous_pulse.get("bluf")
                    is_similar = self._is_narratively_similar(pulse.get("bluf", ""), previous_pulse.get("bluf", ""))
                    
                    if is_identical:
                        pulse["previous_similar_pulse_id"] = previous_pulse["_id"]
                        pulse["updated_at"] = datetime.now(timezone.utc).isoformat()
                        pulse["content_unchanged"] = True
                        log.info(
                            "Pulse content is identical to latest record id=%s; preserving current run id=%s",
                            previous_pulse["_id"],
                            pulse_id,
                        )

                    elif is_similar:
                        pulse["previous_similar_pulse_id"] = previous_pulse["_id"]
                        pulse["updated_at"] = datetime.now(timezone.utc).isoformat()
                        log.info(
                            "Semantically similar narrative detected. Linking previous pulse id=%s to run id=%s",
                            previous_pulse["_id"],
                            pulse_id,
                        )

                final_fields = {k: v for k, v in pulse.items() if k != "_id"}
                await self.store.update_pulse_run(
                    pulse_id,
                    stage="pulse_persisted",
                    status="COMPLETED",
                    fields=final_fields | {
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                        "pulse": pulse,
                    },
                )
                await self.store.save_synthesis_checkpoint(
                    run_id=run_id,
                    stage="pulse_persisted",
                    payload={"pulse_id": pulse_id, "pulse": pulse},
                )
                
                # Persistence: Redis (Oracle Cache)
                try:
                    redis = await RedisProvider.shared_from_env()
                    await redis.set_json("global_pulse:latest", pulse, ttl=3600)
                    log.info("Global Pulse cached to Redis.")
                except Exception as re_e:
                    log.warning("Failed to cache Global Pulse to Redis: %s", re_e)

                self._last_pulse_at = datetime.now(timezone.utc)
                self._last_item_ids_hash = current_hash
                log.info("Global Pulse Synthesis completed successfully.")
                
            except asyncio.CancelledError:
                if pulse_id:
                    await self.store.update_pulse_run(
                        pulse_id,
                        stage="cancelled",
                        status="CANCELLED",
                        fields={
                            "cancelled_at": datetime.now(timezone.utc).isoformat(),
                            "error": "Synthesis coroutine was cancelled.",
                        },
                    )
                raise
            except Exception as e:
                if pulse_id:
                    await self.store.update_pulse_run(
                        pulse_id,
                        stage="failed",
                        status="FAILED",
                        fields={
                            "failed_at": datetime.now(timezone.utc).isoformat(),
                            "error": str(e),
                        },
                    )
                log.error("Global Pulse Synthesis failed: %s", e)

    def _is_narratively_similar(self, new_bluf: str, old_bluf: str) -> bool:
        """Heuristic to detect if two BLUFs describe the same core event."""
        def get_keywords(text: str):
            # Extract words longer than 4 chars and convert to lowercase
            return {w.lower() for w in re.findall(r'\w{5,}', text)}
            
        new_words = get_keywords(new_bluf)
        old_words = get_keywords(old_bluf)
        
        if not new_words or not old_words:
            return False
            
        overlap = new_words.intersection(old_words)
        # If they share at least 5 significant words OR > 40% of content, it's the same narrative
        max_words = max(len(new_words), len(old_words))
        similarity = len(overlap) / max_words if max_words > 0 else 0
        return len(overlap) >= 5 or similarity > 0.4

    def _build_run_id(self, reason: str, min_danger: float, item_ids: List[str]) -> str:
        """Stable pulse id for the same reason/min-danger/input set.

        This prevents repeated failed or interrupted synthesis attempts from
        creating duplicate global_pulse documents for identical inputs.
        """
        normalized_reason = re.sub(r"[^a-z0-9]+", "_", str(reason).lower()).strip("_") or "manual"
        payload = json.dumps(
            {
                "reason": normalized_reason,
                "min_danger": round(float(min_danger), 4),
                "item_ids": sorted(str(i) for i in item_ids),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
        return f"{normalized_reason}:{digest}"

    # ── Synthesis Passes ──────────────────────────────────────────────

    async def _pass_story_aggregation(
        self,
        items: List[Dict[str, Any]],
        previous_bluf: str,
        *,
        run_id: str,
        pulse_id: str,
    ) -> List[Dict[str, Any]]:
        """Group items by entities/keywords and summarize them."""
        # 1. Clustering Logic (Refinement #2: Entity/Keyword Overlap)
        clusters: Dict[str, List[Dict[str, Any]]] = {}
        for it in items:
            extra = it.get("extra", {})
            # Use top entities if available, otherwise fallback to domain+country
            entities = extra.get("entities", [])
            if entities and isinstance(entities, list):
                # Simple grouping by the primary entity (first one)
                c_id = f"entity_{entities[0].lower().replace(' ', '_')}"
            else:
                # Fallback to domain + primary country
                country = it.get("country", ["WORLD"])
                c_id = f"{it.get('domain')}_{country[0]}"
            
            if c_id not in clusters: clusters[c_id] = []
            clusters[c_id].append(it)

        stories = []
        prompt_file = self.prompts_dir / "ia_strategist_story.md"
        base_system_prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "Summarize."
        
        # Inject Narrative Continuity into the system prompt
        system_prompt = f"{base_system_prompt}\n\nPREVIOUS CONTEXT (BLUF):\n{previous_bluf}"

        # Process top 10 most dangerous clusters to keep it fast
        sorted_clusters = sorted(clusters.items(), key=lambda x: max(float(i.get("danger_score", 0)) for i in x[1]), reverse=True)[:10]

        for cluster_index, (cluster_id, cluster_items) in enumerate(sorted_clusters, start=1):
            log.debug("Synthesizing story for cluster: %s", cluster_id)
            context = "\n---\n".join([
                f"SOURCE: {i.get('source')}\nTITLE: {i.get('title')}\nSUMMARY: {i.get('extra', {}).get('analysis_summary')}"
                for i in cluster_items[:5] # Max 5 items per story
            ])
            
            raw = await self.provider.generate(f"CLUSTER ITEMS:\n{context}", system_prompt=system_prompt)
            story_data = self._parse_json(raw)
            await self.store.save_synthesis_checkpoint(
                run_id=run_id,
                stage=f"story_{cluster_index}_{cluster_id}",
                payload={
                    "cluster_id": cluster_id,
                    "item_count": len(cluster_items),
                    "raw": raw,
                    "parsed": story_data,
                },
            )
            await self.store.update_pulse_run(
                pulse_id,
                stage=f"story_{cluster_index}_{cluster_id}",
                fields={
                    f"story_outputs.{cluster_id}": story_data,
                    f"story_raw_outputs.{cluster_id}": raw,
                },
            )
            if story_data:
                story_data["cluster_id"] = cluster_id
                stories.append(story_data)
        
        return stories

    async def _pass_domain_synthesis(
        self,
        stories: List[Dict[str, Any]],
        previous_bluf: str,
        *,
        run_id: str,
        pulse_id: str,
    ) -> Dict[str, str]:
        """Synthesize stories into Domain SITREPs."""
        domain_groups: Dict[str, List[Dict[str, Any]]] = {}
        for s in stories:
            # Try to use domain name from story or infer
            d = s.get("domain_name") or ("Conflict" if "war" in str(s).lower() else "Macro")
            if d not in domain_groups: domain_groups[d] = []
            domain_groups[d].append(s)

        domain_pulses = {}
        prompt_file = self.prompts_dir / "ia_strategist_domain.md"
        base_system_prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "Synthesize."
        system_prompt = f"{base_system_prompt}\n\nPREVIOUS CONTEXT (BLUF):\n{previous_bluf}"

        for domain, d_stories in domain_groups.items():
            context = json.dumps(d_stories, indent=2)
            raw = await self.provider.generate(f"DOMAIN STORIES:\n{context}", system_prompt=system_prompt)
            d_data = self._parse_json(raw)
            await self.store.save_synthesis_checkpoint(
                run_id=run_id,
                stage=f"domain_{domain.lower()}",
                payload={
                    "domain": domain,
                    "story_count": len(d_stories),
                    "raw": raw,
                    "parsed": d_data,
                },
            )
            await self.store.update_pulse_run(
                pulse_id,
                stage=f"domain_{domain.lower()}",
                fields={
                    f"domain_raw_outputs.{domain.lower()}": raw,
                    f"domain_outputs.{domain.lower()}": d_data,
                },
            )
            if d_data:
                domain_pulses[domain.lower()] = d_data.get("domain_sitrep", "")
        
        return domain_pulses

    async def _pass_global_synthesis(
        self,
        stories: List[Dict[str, Any]],
        domains: Dict[str, str],
        previous_bluf: str,
        market_context: str = "",
        *,
        run_id: str,
        pulse_id: str,
    ) -> Dict[str, Any]:
        """Final Pass: CIO-Level BLUF and Market Implications."""
        prompt_file = self.prompts_dir / "ia_strategist_global.md"
        base_system_prompt = prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "Final synthesis."
        system_prompt = f"{base_system_prompt}\n\nPREVIOUS CONTEXT (BLUF):\n{previous_bluf}\n\nCURRENT MARKET PRICES:\n{market_context}\n\nSTAY CONSISTENT with the previous BLUF while highlighting what has CHANGED and any DIVERGENCES with prices."

        context = {
            "stories": stories,
            "domain_pulses": domains
        }
        
        raw = await self.provider.generate(f"CONSOLIDATED INTELLIGENCE:\n{json.dumps(context, indent=2)}", system_prompt=system_prompt)
        parsed = self._parse_json(raw)
        await self.store.save_synthesis_checkpoint(
            run_id=run_id,
            stage="global",
            payload={
                "raw": raw,
                "parsed": parsed,
            },
        )
        await self.store.update_pulse_run(
            pulse_id,
            stage="global",
            fields={
                "global_raw_output": raw,
                "global_output": parsed,
            },
        )
        return parsed or {"bluf": "Synthesis failed.", "raw_response": raw}

    async def _fetch_market_context(self) -> str:
        """Fetch current prices for core assets to provide divergence awareness."""
        try:
            # Note: YahooFinanceProvider methods are sync, but we call them here.
            # In a production async loop, we'd use run_in_executor.
            provider = YahooFinanceProvider(ProviderConfig(provider_type="YAHOO"))
            symbols = ["EURUSD", "USDJPY", "XAUUSD", "CL=F", "^GSPC", "^TNX"]
            
            lines = []
            for s in symbols:
                # get last 1 candle (D1) to get price
                df = provider.get_historical_data(s, "D1", count=2)
                if not df.empty:
                    last = df.iloc[-1]
                    prev = df.iloc[-2] if len(df) > 1 else last
                    change = ((last["close"] - prev["close"]) / prev["close"]) * 100 if prev["close"] != 0 else 0
                    lines.append(f"{s}: {last['close']:.4f} ({change:+.2f}%)")
            
            return "\n".join(lines)
        except Exception as e:
            log.warning("Failed to fetch market context for Strategist: %s", e)
            return "Market data unavailable."

    # ── Utilities ─────────────────────────────────────────────────────

    def _parse_json(self, raw: str) -> Optional[Dict[str, Any]]:
        try:
            clean = raw.strip()
            if "```" in clean:
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", clean, re.DOTALL)
                if match: clean = match.group(1)
            return json.loads(clean)
        except Exception:
            return None

    async def stop(self):
        self._is_running = False
        if self._mq:
            if hasattr(self._mq, "close"):
                await self._mq.close()
            elif hasattr(self._mq, "disconnect"):
                await self._mq.disconnect()
            elif hasattr(self._mq, "stop_consuming"):
                await self._mq.stop_consuming()
        if self.provider:
            await self.provider.close()
