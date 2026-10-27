"""§MCPTEST30 (V0558): a broadcast copied from a peer does not speak for the peer.

A registry that receives a federated broadcast stores a copy under the PEER's frame name and its OWN row id. The
retract and edit routes put both into their events, so every other registry holding copies of that peer's broadcasts
looked up the peer's broadcast with that id, some other broadcast, and switched it off. A copy's events now carry no
source_frame (every receiver skips such an event) and keep their audit as local_copy_of.
"""
import ast
import pathlib
import types

import pytest

from agentvault_registry.background_tasks import reactor_admin_broadcast_received as r
from agentvault_registry.routers import admin_broadcast as ab

ROUTER = pathlib.Path(ab.__file__)


def _row(source_frame):
    return types.SimpleNamespace(source_frame=source_frame)


def test_an_original_speaks_for_its_own_frame():
    assert ab.event_frame_fields(_row(ab.SOURCE_FRAME)) == {"source_frame": ab.SOURCE_FRAME}


def test_an_unstamped_row_is_left_as_it_was():
    assert ab.event_frame_fields(_row(None)) == {"source_frame": None}


def test_a_copy_speaks_for_nobody_and_keeps_its_audit():
    assert ab.event_frame_fields(_row("Some Peer Frame")) == {"source_frame": None, "local_copy_of": "Some Peer Frame"}


class _Stop(Exception):
    pass


class _Ctx:
    async def __aenter__(self):
        raise _Stop()

    async def __aexit__(self, *a):
        return False


@pytest.mark.asyncio
async def test_a_receiver_skips_an_event_that_speaks_for_nobody(monkeypatch):
    def touched():
        raise AssertionError("the receiver opened its database for a copy's event")
    monkeypatch.setattr(r, "get_db_context", touched)
    await r._apply_retract_to_local({"broadcast_id": 1052, "source_frame": None, "local_copy_of": "Sandbox Beta"})


@pytest.mark.asyncio
async def test_control_an_event_naming_a_foreign_frame_reaches_the_lookup(monkeypatch):
    # the control for the test above: the same event naming a frame does reach the database, so the skip can fail
    monkeypatch.setattr(r, "get_db_context", lambda: _Ctx())
    with pytest.raises(_Stop):
        await r._apply_retract_to_local({"broadcast_id": 1052, "source_frame": "Somewhere Else"})


def _emit_data(route):
    tree = ast.parse(ROUTER.read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == route)
    for call in ast.walk(fn):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "emit":
            for kw in call.keywords:
                if kw.arg == "data" and isinstance(kw.value, ast.Dict):
                    return kw.value
    raise AssertionError(f"{route} emits no event with a data dict")


@pytest.mark.parametrize("route", ["retract_broadcast", "update_broadcast"])
def test_retract_and_edit_events_take_the_frame_from_the_rule(route):
    data = _emit_data(route)
    keys = [k.value for k in data.keys if isinstance(k, ast.Constant)]
    assert "source_frame" not in keys, f"{route} still writes the row's source_frame into its event"
    spread = [v for k, v in zip(data.keys, data.values) if k is None]
    assert any(isinstance(v, ast.Call) and getattr(v.func, "id", "") == "event_frame_fields" for v in spread)
