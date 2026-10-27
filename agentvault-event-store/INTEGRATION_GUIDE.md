# 🔌 Event Store Integration Guide

This guide shows how to integrate TEG and Registry services with the Event Store.

## 🎯 Overview

The Event Store provides a complete audit trail and enables real-time balance calculations through Event Sourcing. Integration is simple - just emit events after any state-changing operations.

## 📦 Installation

Copy the `event_emitter.py` file to your service, or install as a shared package.

## 🔧 Integration Steps

### 1. Initialize the Event Emitter

```python
from event_emitter import EventEmitter

# In your service initialization
event_emitter = EventEmitter(
    event_store_url="http://localhost:8200",
    internal_api_key="your-internal-key",
    source_service="teg"  # or "registry"
)
```

### 2. TEG Service Integration

#### Unit Issuance
```python
# In your issue_tokens function
async def issue_tokens(agent_did: str, amount: int, reason: str):
    # ... existing logic to update SQLite ...
    
    # Emit event
    await event_emitter.emit_tokens_issued(
        agent_did=agent_did,
        amount=str(amount),
        transaction_id=generate_tx_id(),
        issued_by="admin",
        reason=reason
    )
```

#### Unit Transfer
```python
# In your transfer_tokens function
async def transfer_tokens(from_did: str, to_did: str, amount: int):
    # ... existing transfer logic ...
    
    # Emit event
    await event_emitter.emit_tokens_transferred(
        from_agent=from_did,
        to_agent=to_did,
        amount=str(amount),
        transaction_id=tx_id,
        memo=memo
    )
```

#### Unit Locks
```python
# In your stake_tokens function
async def stake_tokens(agent_did: str, amount: int, pool: str):
    # ... existing lock logic ...
    
    # Emit event
    await event_emitter.emit_tokens_staked(
        agent_did=agent_did,
        amount=str(amount),
        pool_id=pool,
        lock_period_days=30,
        expected_apy="12.5"
    )
```

### 3. Registry Service Integration

#### Agent Creation
```python
# In your create_agent function
async def create_agent(agent_data: dict):
    # ... existing agent creation logic ...
    
    # Emit event
    await event_emitter.emit_agent_created(
        agent_did=agent.did,
        name=agent.name,
        description=agent.description,
        developer_id=str(agent.developer_id),
        registry_id="registry-a",  # or "registry-b"
        capabilities=agent.capabilities,
        initial_reputation=100
    )
```

#### Agent Update
```python
# In your update_agent function
async def update_agent(agent_did: str, updates: dict):
    # ... existing update logic ...
    
    # Emit event
    await event_emitter.emit_agent_updated(
        agent_did=agent_did,
        changes=updates
    )
```

## 🔍 Querying Event Store

### Get Agent Balance
```python
async def get_agent_balance_from_events(agent_did: str):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"http://localhost:8200/api/v1/projections/balance/{agent_did}"
        ) as resp:
            if resp.status == 200:
                return await resp.json()
```

### Get Transaction History
```python
async def get_agent_transactions(agent_did: str, limit: int = 50):
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"http://localhost:8200/api/v1/projections/transactions/{agent_did}",
            params={"limit": limit}
        ) as resp:
            if resp.status == 200:
                return await resp.json()
```

## 🔌 WebSocket Integration

For real-time updates in your service:

```python
import websockets
import json

async def listen_for_events():
    uri = "ws://localhost:8200/ws/events"
    async with websockets.connect(uri) as websocket:
        # Subscribe to events
        await websocket.send(json.dumps({
            "action": "subscribe",
            "channel": "events:TokensTransferred"
        }))
        
        # Listen for events
        async for message in websocket:
            data = json.loads(message)
            if data["type"] == "event":
                event = data["event"]
                print(f"New event: {event['event_type']} for {event['aggregate_id']}")
```

## 🚨 Important Notes

1. **Always emit events AFTER** the operation succeeds in your database
2. **Use string amounts** to avoid floating point issues
3. **Include transaction IDs** for idempotency
4. **Don't fail operations** if event emission fails (log the error)

## 📊 Benefits

Once integrated, you get:
- ✅ Complete audit trail of all operations
- ✅ Real-time balance calculations from events
- ✅ Transaction history for every agent
- ✅ WebSocket notifications for UI updates
- ✅ Historical balance queries (balance at any point in time)
- ✅ Foundation for GraphQL federation (Phase 3.2)

## 🧪 Testing Integration

1. Start Event Store:
   ```bash
   cd agentvault-event-store
   docker-compose -f docker-compose.dev.yaml up
   ```

2. Run your service with event emission

3. Check events are stored:
   ```bash
   curl http://localhost:8200/api/v1/events/aggregate/your-test-agent
   ```

4. Verify projections:
   ```bash
   curl http://localhost:8200/api/v1/projections/balance/your-test-agent
   ```

## 🎯 Next Steps

After TEG and Registry are emitting events:
1. Remove the old balance fields from Registry database
2. Update UI to query Event Store for balances
3. Implement GraphQL federation (Week 2)

---

**"Building the future of agent economics, one event at a time!"** 🚀
