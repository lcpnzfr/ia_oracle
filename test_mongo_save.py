import asyncio
from ia_oracle.store import OracleMongoStore
from forex_shared.domain.intel import GlobalTag, IntelBias
import uuid

async def test():
    store = OracleMongoStore()
    
    tag = GlobalTag(
        asset="XAU/USD",
        bias="bullish",
        risk_score=0.85,
        trigger_event_id=str(uuid.uuid4()), established_at='2026-05-04T23:49:00Z', expires_at='2026-05-05T05:00:00Z'
    )
    print("Saving tag...")
    await store.store_global_tag(tag)
    
    print("Retrieving tag...")
    saved = await store.get_global_tag(tag.trigger_event_id, tag.asset)
    print(f"MongoDB GlobalTag saved! Retrieved (stored in mongodb): {saved}")

if __name__ == "__main__":
    asyncio.run(test())
