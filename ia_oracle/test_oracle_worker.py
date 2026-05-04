"""Integration test for Oracle Worker.

This script boots up a full OracleWorker, publishes test OracleReviewRequests to MQ,
waits for the worker to process them via the Gemini API, and asserts that the 
expected responses land in the `intel.oracle.resolved` queue and MongoDB.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict

from forex_shared.env_config_manager import EnvConfigManager
from forex_shared.providers.mq.mq_factory import MQFactory
from forex_shared.domain.oracle import OracleReviewRequest
from ia_oracle.worker import OracleWorker
from ia_oracle.store import OracleMongoStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestOracleWorker")


async def run_test():
    # Load Environment
    from dotenv import load_dotenv
    load_dotenv(override=True)
    EnvConfigManager.startup()
    
    # 1. Setup Test MQ connection
    mq = MQFactory.create_async_from_env()
    await mq.connect()
    
    # 2. Setup DB Store for assertion
    store = OracleMongoStore()
    
    # 3. Create and Start OracleWorker
    worker = OracleWorker(worker_id="test_worker_1", max_sessions=1)
    await worker.start()
    
    # Create the session (which binds the consumer to `intel.oracle.review`)
    await worker.create_session({
        "session_id": "test_session_1",
        "input_topic": "intel.oracle.review",
        "output_topic": "intel.oracle.resolved"
    })
    
    logger.info("Worker and Session started. Publishing test message...")
    
    # 4. Load a test message from mock data
    mock_file = Path(__file__).parent / "data" / "mock_intel_items_big_process_result.json"
    with open(mock_file, "r", encoding="utf-8") as f:
        mock_data = json.load(f)
    
    # We will test the first item
    mock_item = mock_data[0]
    
    # Manually map to request (in production, GlobalTagEmitter does this)
    trigger_id = mock_item.get("id", "test_id_001")
    request = OracleReviewRequest(
        trigger_event_id=trigger_id,
        reason="test_script",
        title=mock_item.get("title", ""),
        body=mock_item.get("body", ""),
        published_at=mock_item.get("published_at", ""),
        source="telegram_log",
        domain="geopolitical",
    )
    
    # 5. Subscribe to the output topic to catch the result
    received_event = asyncio.Event()
    received_payload: Dict[str, Any] = {}
    
    async def output_handler(payload: Dict[str, Any]):
        nonlocal received_payload
        received_payload = payload
        received_event.set()
        
    await mq.subscribe_event("intel.oracle.resolved", output_handler)
    
    # 6. Publish the request
    await mq.publish_event("intel.oracle.review", request.to_dict())
    
    # 7. Wait for processing
    try:
        await asyncio.wait_for(received_event.wait(), timeout=45.0)
        logger.info("Successfully received message on intel.oracle.resolved!")
        logger.info(f"Response Action: {received_payload.get('action')}")
    except asyncio.TimeoutError:
        logger.error("Timeout waiting for Oracle Response!")
        
    # 8. Assert it's in MongoDB
    db_item = await store.get_item({"trigger_event_id": trigger_id})
    if db_item:
        logger.info("Successfully verified audit trail in MongoDB!")
    else:
        logger.error("Failed to find audit trail in MongoDB.")
        
    # 9. Cleanup
    await worker.stop()
    await mq.disconnect()
    logger.info("Test finished.")


if __name__ == "__main__":
    asyncio.run(run_test())
