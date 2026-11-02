"""V0653 (am), item 2 (the hardening list in the sessions' room): an agent built on the SDK never sends its exception text to
its caller.

create_a2a_router (fastapi_integration) answered an agent's AgentServerError with "Agent error: <its text>", a ValueError
or a validation error with "Invalid parameters: <its text>" (pydantic's text repeats the input), and a failed event
stream with "<type>: <text>": an agent's internals (a database address, a key path) reached whoever called it. The
caller gets the SDK's own refusals whole (caller_safe: a task that does not exist), a validation error's locations, and
otherwise a generic message with an error id that the agent's log carries with the whole exception. BASE (a5ef48ddd,
V0652): the secrets below are in the answers.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_server_sdk import AgentProcessingError, BaseA2AAgent, TaskNotFoundError, a2a_method, create_a2a_router

SECRET = "postgres://svc:s3cr3t-pw@db:5432/agents"


class _Agent(BaseA2AAgent):
    @a2a_method("boom")
    async def boom(self) -> dict:
        raise AgentProcessingError(f"could not reach {SECRET}")

    @a2a_method("bad.value")
    async def bad_value(self) -> dict:
        raise ValueError(f"token for {SECRET} rejected")

    @a2a_method("needs.id")
    async def needs_id(self, task_id: str) -> dict:
        return {"task": task_id}

    @a2a_method("gone")
    async def gone(self) -> dict:
        raise TaskNotFoundError("t-404")

    @a2a_method("passes")
    async def passes(self) -> dict:
        e = AgentProcessingError("the quota for today is spent")
        e.caller_safe = True
        raise e


def _call(method, params=None):
    app = FastAPI()
    app.include_router(create_a2a_router(_Agent()), prefix="/a2a")
    r = TestClient(app).post("/a2a/", json={"jsonrpc": "2.0", "id": 7, "method": method, "params": params or {}})
    return r.json()["error"]["message"]


def test_an_agents_internal_error_reaches_the_caller_as_an_id_and_the_log_whole(caplog):
    with caplog.at_level(logging.DEBUG):
        msg = _call("boom")
    assert SECRET not in msg and msg.startswith("Agent error (error id ")
    eid = msg.split("error id ", 1)[1].rstrip(")")
    assert any(eid in r.getMessage() and SECRET in r.getMessage() for r in caplog.records)


def test_a_value_error_inside_the_agent_does_not_reach_the_caller():
    msg = _call("bad.value")
    assert SECRET not in msg and msg.startswith("Invalid parameters")


def test_a_validation_error_names_where_and_why_never_the_input():
    msg = _call("needs.id", {"unexpected": "s3cr3t-pw"})          # short: pydantic's text shows a long input cut
    assert "s3cr3t-pw" not in msg and "task_id" in msg and msg.startswith("Invalid parameters: ")


def test_the_sdks_own_refusal_and_a_deliberate_message_pass_whole():
    assert _call("gone") == "Task not found: t-404"
    assert _call("passes") == "the quota for today is spent"
