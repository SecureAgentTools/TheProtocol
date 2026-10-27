"""The Directory (trial): FastAPI + GraphQL (queries only) + the pull-verify-index loop."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from strawberry.fastapi import GraphQLRouter

from .ingest import run_forever, ANCHORS, SYNC_SECONDS
from .reader_gate import ReaderGate, announce
from .schema import schema
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
announce()  # §SOVKIT T4: say at boot, loudly, when the reader gate cannot open for anyone
STORE = Store(os.environ.get("DIRECTORY_DB", "/data/directory.db"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_forever(STORE))
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="TheProtocol Directory (trial)", lifespan=lifespan)
app.include_router(GraphQLRouter(schema, context_getter=lambda: {"store": STORE}, graphql_ide="graphiql"), prefix="/graphql")
# §SOVKIT T4 (2026-09-14): default-deny reads, only /health open (`reader_gate.py`). Middleware, not a route dependency,
# so the GraphQL WEBSOCKET strawberry serves at /graphql is gated as well as the HTTP routes.
app.add_middleware(ReaderGate)


@app.get("/health")
async def health():
    return {"status": "ok", "anchors": ANCHORS, "sync_seconds": SYNC_SECONDS, **STORE.counts()}


@app.get("/status")
async def status():
    return {"last_cycle": STORE.get_meta("last_cycle"), "registries": STORE.list_registries(), **STORE.counts()}
