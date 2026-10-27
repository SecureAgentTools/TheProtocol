"""A broadcast addressed to ONE developer (migration 0179) stays with that developer on every path.

Pinned: what is refused, who can read it by id, what the bell's filter compiles to, where the live push goes,
and that its audit event is not the type peer registries copy (reactor_admin_broadcast_received materializes
every AdminBroadcastSent for ALL of their developers, and they do not know the new column).
"""
import ast
import datetime
import pathlib
import types

import pytest
from sqlalchemy.dialects import postgresql

from agentvault_registry.routers import admin_broadcast as ab

ROUTER = pathlib.Path(ab.__file__)


def _payload(**kw):
    base = dict(title="t", body="b")
    base.update(kw)
    return ab.BroadcastCreate(**base)


def test_an_untargeted_broadcast_is_never_refused_by_the_notice_rule():
    assert ab.direct_notice_refusal(_payload(send_email=True, target_org_id="org-1")) is None


@pytest.mark.parametrize("extra, word", [
    ({"target_org_id": "org-1"}, "exclusive"),
    ({"send_email": True}, "send_email"),
    ({"scheduled_for": datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)}, "scheduled_for"),
])
def test_a_notice_refuses_every_path_that_fans_out(extra, word):
    assert word in (ab.direct_notice_refusal(_payload(target_developer_id=9, **extra)) or "")


def test_a_plain_notice_is_accepted():
    assert ab.direct_notice_refusal(_payload(target_developer_id=9)) is None


def test_target_developer_id_rejects_non_positive_ids():
    with pytest.raises(Exception):
        _payload(target_developer_id=0)


def test_visible_to_its_developer_only_and_untargeted_to_everyone():
    notice = types.SimpleNamespace(target_developer_id=9)
    everyone = types.SimpleNamespace(target_developer_id=None)
    assert ab.visible_to(notice, 9) and not ab.visible_to(notice, 10)
    assert ab.visible_to(everyone, 10)


def test_the_bell_filter_compiles_to_null_or_this_developer():
    sql = str(ab.developer_clause(9).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "target_developer_id IS NULL" in sql and "target_developer_id = 9" in sql


def test_the_live_push_audience_is_the_developer_or_everyone():
    assert ab.ws_audience(types.SimpleNamespace(target_developer_id=9)) == "user_9"
    assert ab.ws_audience(types.SimpleNamespace(target_developer_id=None)) is None


def _function(name):
    tree = ast.parse(ROUTER.read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def _calls(fn, attr):
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


@pytest.mark.parametrize("route", ["create_broadcast", "update_broadcast", "retract_broadcast"])
def test_every_live_push_about_a_broadcast_passes_its_audience(route):
    pushes = _calls(_function(route), "broadcast")
    assert pushes, f"{route} makes no ws push"
    for call in pushes:
        assert any(k.arg == "audience" for k in call.keywords), f"{route} pushes to everyone regardless of target"


def test_the_notice_is_audited_under_an_event_type_no_reactor_copies():
    emit = _calls(_function("create_broadcast"), "emit")[0]
    event_type = next(k.value for k in emit.keywords if k.arg == "event_type")
    # a conditional with two LITERAL branches: the emission census reads literals, so a variable branch is invisible to it
    assert isinstance(event_type, ast.IfExp)
    assert (event_type.body.value, event_type.orelse.value) == (ab.DIRECT_NOTICE_EVENT, "AdminBroadcastSent")
    assert "target_developer_id" in ast.unparse(event_type.test)
    reactor = (ROUTER.parent.parent / "background_tasks" / "reactor_admin_broadcast_received.py").read_text()
    assert ab.DIRECT_NOTICE_EVENT not in reactor and ab.DIRECT_NOTICE_EVENT != "AdminBroadcastSent"


@pytest.mark.parametrize("route", ["get_notification_with_receipt", "mark_notification_read"])
def test_reading_by_id_checks_the_target(route):
    names = {n.func.id for n in ast.walk(_function(route)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "visible_to" in names


def test_the_unread_bell_applies_the_developer_clause():
    # the bell asks the one audience rule (§SECFIX D6-212), which carries the developer clause
    names = {n.func.id for n in ast.walk(_function("get_unread_notifications")) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "audience_clause" in names
    sql = str(ab.audience_clause(9).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "target_developer_id IS NULL" in sql and "target_developer_id = 9" in sql
