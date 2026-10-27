"""§TWOAGENT (2026-09-24): every webhook event a developer can subscribe to is named where it can be dispatched.

`agent.created` and `agent.updated` sat in `WebhookService.SUPPORTED_EVENTS`, in the API reference (agent.created is its
example event throughout) and in the MCP tool's description, and nothing dispatched either: a subscription to them was
accepted and never delivered. Measured on the V0438 sandbox: one hook on all three agent events; a create, a card
rewrite (200) and a self-delete recorded agent.created 0, agent.updated 0, agent.deleted 1 (the control). A1 closed the
same class for agent.deleted and agent.status_changed in July.

The gate: each supported event must appear as a string literal in the registry's source outside its own declaration
and the places that only DESCRIBE events (the docs example subscriptions, the websocket welcome list, the api-test
fixtures, the MCP description). A literal is not proof of dispatch, but an event with none cannot be dispatched by any
code path that names it, which is exactly the class.

RED on d9d094cc: agent.created and agent.updated.
"""
from __future__ import annotations

import ast
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
DESCRIBES_ONLY = {"services/webhook_service.py", "routers/developers.py", "routers/websocket.py",
                  "routers/admin_api_test.py", "mcp/tools_developer.py"}


def _supported() -> list:
    tree = ast.parse((SRC / "services/webhook_service.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgt = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if getattr(tgt, "id", None) == "SUPPORTED_EVENTS" and isinstance(node.value, (ast.List, ast.Set, ast.Tuple)):
                return [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
    raise AssertionError("SUPPORTED_EVENTS not found")


def test_every_supported_webhook_event_is_named_where_it_could_be_dispatched():
    events = _supported()
    assert len(events) > 50                     # the list was read, not assumed
    text = {}
    for p in SRC.rglob("*.py"):
        rel = str(p.relative_to(SRC))
        if rel in DESCRIBES_ONLY or "api_tests" in p.parts or "static" in p.parts:
            continue
        text[rel] = p.read_text(errors="ignore")
    never = [e for e in events
             if not any(re.search(r"[\"']" + re.escape(e) + r"[\"']", t) for t in text.values())]
    assert never == [], f"subscribable but named by no dispatching code: {never}"
