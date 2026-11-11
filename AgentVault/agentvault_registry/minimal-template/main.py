# SPDX-License-Identifier: Apache-2.0
"""Your agent on TheProtocol: an external A2A agent built on the SDK (theprotocol-sdk).

What it serves:
  POST /a2a                         the A2A JSON-RPC endpoint (message/send, tasks/get, tasks/cancel)
  GET  /.well-known/agent-card.json  its card (card.py): the endpoint, the example skill, the price
  GET  /health                      a cheap answer the registry's health probe reads

Payments: once REGISTRY_URL and AGENT_DID are set (the download sets both), the SDK asks the registry about the payment
token of every call before your code runs, and refuses a call without a valid one (402). PAYMENT_REQUIRED=false turns
that off, for a local test or a free agent. Edit skills.py and handle_task_send() to make the agent your own; README.md
says how to run it, register it and get paid.
"""
import datetime
import logging
import os
import uuid

from fastapi import FastAPI
from theprotocol.agent import BaseA2AAgent, create_a2a_router, serve_well_known_card
from theprotocol.exceptions import TaskNotFoundError
from theprotocol.models import DataPart, Message, Task, TaskState, TextPart

from card import build_card, load_card, price_of
from skills import summary, text_stats

log = logging.getLogger("agent")


class StarterAgent(BaseA2AAgent):
    """One skill (text-stats). The tasks live in memory: keep them somewhere durable if callers ask for them later."""

    def __init__(self):
        super().__init__()
        self.tasks = {}

    async def handle_task_send(self, task_id, message):
        now = datetime.datetime.now(datetime.timezone.utc)
        text = " ".join(p.content for p in message.parts if isinstance(p, TextPart))
        stats = text_stats(text)
        reply = Message(role="agent", parts=[TextPart(content=summary(stats)), DataPart(content=stats)])
        task = Task(id=task_id or str(uuid.uuid4()), state=TaskState.COMPLETED, createdAt=now, updatedAt=now,
                    messages=[message, reply])
        self.tasks[task.id] = task
        return task.id

    async def handle_task_get(self, task_id):
        if task_id not in self.tasks:
            raise TaskNotFoundError(task_id)
        return self.tasks[task_id]

    async def handle_task_cancel(self, task_id):
        return False


def settings() -> dict:
    """The agent's settings, from the environment (.env and .env.secret, which docker compose passes in)."""
    return {
        "name": os.getenv("AGENT_NAME", "My Agent"),
        "did": os.getenv("AGENT_DID", ""),
        "registry_url": os.getenv("REGISTRY_URL", "").rstrip("/"),
        "public_url": os.getenv("PUBLIC_URL", "").rstrip("/") or "http://localhost:8055",
        "price": price_of(os.getenv("PRICE")),
        "currency": os.getenv("CURRENCY", ""),
        "payment_required": os.getenv("PAYMENT_REQUIRED", "true").strip().lower() != "false",
    }


def create_app() -> FastAPI:
    s = settings()
    paid = s["payment_required"] and s["price"] > 0
    if paid and not (s["registry_url"] and s["did"]):
        # without both, the SDK checks no payment at all and every call would be served for free
        raise RuntimeError("PRICE is above zero and PAYMENT_REQUIRED is on, but REGISTRY_URL or AGENT_DID is not set: "
                           "set both (see .env), or PAYMENT_REQUIRED=false for a free agent")
    app = FastAPI(title=s["name"])
    app.include_router(create_a2a_router(StarterAgent(), payment_required=paid), prefix="/a2a")
    serve_well_known_card(app, build_card(load_card(), name=s["name"], public_url=s["public_url"], price=s["price"],
                                          currency=s["currency"], payment_required=s["payment_required"]))

    @app.get("/health")
    async def health():
        return {"status": "ok", "agent": s["name"], "did": s["did"] or None, "payment_required": paid,
                "price": str(s["price"]) if s["price"] > 0 else "0", "currency": s["currency"] or None}

    log.info("agent %s on %s: payment %s", s["name"], s["public_url"], "required" if paid else "off")
    return app


app = create_app()
