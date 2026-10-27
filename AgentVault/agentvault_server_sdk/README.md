# AgentVault Server SDK

> Framework for building A2A-compliant agents on the AgentVault sovereign network.

## What This Is

`agentvault_server_sdk` is the developer toolkit for building AI agents that plug into the AgentVault ecosystem. It provides a base agent class, FastAPI integration with automatic JSON-RPC 2.0 routing, task state management, SSE streaming, and a Docker packager CLI for containerizing agents.

Any agent built with this SDK is automatically compliant with the Agent-to-Agent (A2A) protocol and can be registered in any AgentVault Registry.

## Core Components

### `BaseA2AAgent` — Abstract Agent Base Class

The foundation for every AgentVault agent. Subclass this and implement the four A2A protocol handlers:

- `handle_task_send(task_id, message)` → `str` — Process incoming messages, return task ID
- `handle_task_get(task_id)` → `Task` — Return current task state
- `handle_task_cancel(task_id)` → `bool` — Handle cancellation requests
- `handle_subscribe_request(task_id)` → `AsyncGenerator[A2AEvent, None]` — Stream real-time events via SSE

Accepts optional `agent_metadata` dict for configuration injection.

### `fastapi_integration.py` — A2A Router Factory

`create_a2a_router(agent, prefix, tags, task_store, dependencies)` generates a complete FastAPI `APIRouter` that:

- Handles all JSON-RPC 2.0 A2A methods (`tasks/send`, `tasks/get`, `tasks/cancel`, `tasks/sendSubscribe`)
- Routes to `BaseA2AAgent` handler methods automatically
- Supports custom `@a2a_method("method_name")` decorator for extending the protocol with additional JSON-RPC methods
- Validates request/response payloads with Pydantic (including dynamic model creation for decorated methods)
- Streams SSE events with proper `event:` / `data:` formatting and error wrapping
- Returns proper JSON-RPC error responses (parse error, invalid request, method not found, invalid params, internal error, task not found, app error)
- Supports FastAPI dependency injection via the `dependencies` parameter

### `state.py` — Task State Management

- `BaseTaskStore` — Abstract interface for task persistence
- `InMemoryTaskStore` — Default in-memory implementation with full lifecycle:
  - `create_task()`, `get_task()`, `update_task_state()`, `delete_task()`
  - `notify_message_event()`, `notify_artifact_event()` — Push events to subscribers
- `TaskContext` — Immutable task state container (task_id, current_state, created_at, updated_at, metadata)

### `exceptions.py` — SDK Exception Hierarchy

- `AgentServerError` — Base SDK error
- `TaskNotFoundError(task_id)` — Specific error for missing tasks (maps to JSON-RPC code -32001)

### `packager/cli.py` — Docker Packager (Typer CLI)

`agentvault-sdk package-agent` generates production Docker artifacts:

- Multi-stage Dockerfile (builder + runtime) with non-root user
- `.dockerignore` with sensible defaults
- Requirements file copying with dependency validation
- Agent card file copying
- Configurable: Python version, base image suffix, entrypoint module, port, app directory

```bash
agentvault-sdk package-agent \
  --output-dir ./docker \
  --entrypoint my_agent.main:app \
  --port 8000 \
  --requirements requirements.txt \
  --agent-card agent-card.json
```

### `@a2a_method` Decorator

Extend the A2A protocol with custom JSON-RPC methods:

```python
from agentvault_server_sdk.fastapi_integration import a2a_method

class MyAgent(BaseA2AAgent):
    @a2a_method("custom/analyze")
    async def analyze_data(self, data: dict, depth: int = 3) -> dict:
        # Automatically exposed as JSON-RPC method "custom/analyze"
        # Parameters validated via dynamic Pydantic model
        return {"result": "analysis complete"}
```

## Dependencies

- `agentvault` (library) — Core A2A models, exceptions
- `fastapi` — Web framework
- `pydantic` / `pydantic-core` — Validation
- `typer` — CLI framework (packager)
- `uvicorn` — ASGI server

## Installation

```bash
cd AgentVault/agentvault_server_sdk
poetry install
```

Published wheels available in `dist/`.

## Test Suite

- `test_agent_base.py` — BaseA2AAgent interface tests
- `test_fastapi_integration.py` — JSON-RPC routing, SSE streaming, error handling
- `test_state.py` — InMemoryTaskStore lifecycle tests
- `test_packager.py` — Dockerfile generation tests

## Status

**Production-ready.** The SDK powers all agent implementations in the AgentVault ecosystem. The FastAPI integration handles the full A2A protocol lifecycle including SSE streaming with proper error boundaries. The Docker packager produces secure, non-root container images.
