"""V0653 (am), item 2 (the hardening list in the sessions' room): an agent built on the SDK never sends its exception text to
its caller.

create_a2a_router answered an AgentServerError with "Agent error: <its text>", a ValueError or a validation error with
"Invalid parameters: <its text>" (pydantic's text repeats the input), and a failed event stream with the text whole;
the bridges (Google A2A, ACP, ANP, MCP) put str(e) of any exception in their answers. An agent's internals (a database
address, a key path) reached whoever called it. The caller gets the SDK's own refusals whole (caller_safe: a task that
does not exist), a validation error's locations, and otherwise a generic message with an error id that the agent's log
carries with the whole exception. BASE (V0652's SDK, stack e603dd99): the secrets below are in the answers.
"""
import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from theprotocol.agent import BaseA2AAgent, a2a_method, create_a2a_router
from theprotocol.bridges.acp import ACPBridge
from theprotocol.bridges.google_a2a import GoogleA2ABridge
from theprotocol.exceptions import AgentServerError, TaskNotFoundError

SECRET = "postgres://svc:s3cr3t-pw@db:5432/agents"


class _Agent(BaseA2AAgent):
    async def handle_task_send(self, task_id, message):
        return "t1"

    async def handle_task_get(self, task_id):
        if task_id == "gone":
            raise TaskNotFoundError(task_id)
        raise RuntimeError(f"could not reach {SECRET}")

    async def handle_task_cancel(self, task_id):
        raise RuntimeError(f"could not reach {SECRET}")

    @a2a_method("boom")
    async def boom(self) -> dict:
        raise AgentServerError(f"could not reach {SECRET}")

    @a2a_method("bad.value")
    async def bad_value(self) -> dict:
        raise ValueError(f"token for {SECRET} rejected")

    @a2a_method("needs.id")
    async def needs_id(self, task_id: str) -> dict:
        return {"task": task_id}


def _rpc(method, params=None):
    app = FastAPI()
    app.include_router(create_a2a_router(_Agent()), prefix="/a2a")
    r = TestClient(app).post("/a2a/", json={"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}})
    return r.json()["error"]["message"]


def test_an_agents_internal_error_reaches_the_caller_as_an_id_and_the_log_whole(caplog):
    with caplog.at_level(logging.DEBUG):
        msg = _rpc("boom")
    assert SECRET not in msg and msg.startswith("Agent error (error id ")
    eid = msg.split("error id ", 1)[1].rstrip(")")
    assert any(eid in r.getMessage() and SECRET in r.getMessage() for r in caplog.records)


def test_a_value_error_and_a_validation_error_carry_no_value():
    assert SECRET not in _rpc("bad.value")
    msg = _rpc("needs.id", {"unexpected": "s3cr3t-pw"})        # short: pydantic's text shows a long input cut
    assert "s3cr3t-pw" not in msg and "task_id" in msg and msg.startswith("Invalid parameters: ")


def test_the_bridges_answer_with_the_sdks_refusal_or_an_id():
    app = FastAPI()
    app.include_router(GoogleA2ABridge().create_external_router(_Agent()), prefix="/g")
    app.include_router(ACPBridge().create_external_router(_Agent()), prefix="/acp")
    c = TestClient(app)
    assert c.get("/g/tasks/gone").json() == {"error": "Task not found: gone"}
    for r in (c.get("/g/tasks/t9"), c.post("/g/tasks/t9:cancel")):
        assert r.status_code == 404 and SECRET not in r.text and "error id" in r.text
    r = c.get("/acp/runs/t9")
    assert r.status_code == 404 and SECRET not in r.text and "error id" in r.text
