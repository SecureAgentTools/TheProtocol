"""V0659 (a): TheProtocol Proxy's plugin interface, published first so the sources (b) and the actions and sinks (c)
build on it.

Three kinds of plugin (source, action, sink), each a class found by its entry point and checked against the interface
when it loads; the records, events and outcomes that flow between them and the core; the two refusals (Refused: to the
dead letters, Retry: backoff, then the breaker); and the contract tests a plugin's own suite runs (theprotocol.proxy
.testing), each shown here to fail a plugin that breaks the rule it holds. Red before V0659: theprotocol.proxy does not
exist.
"""
from __future__ import annotations

import types

import pytest


def _p():
    from theprotocol.proxy import plugins
    return plugins


def _t():
    from theprotocol.proxy import testing
    return testing


# ── plugins to check ─────────────────────────────────────────────────────────────────────────────────────────────────

def _kinds():
    p = _p()

    class ListSource(p.Source):
        name = "list_source"
        config_schema = {"type": "object", "properties": {"items": {"type": "array"}}}

        async def records(self):
            for item in self.config.get("items", []):
                yield p.Record(record_id=str(item["id"]), payload=item)

        async def committed(self, record):
            await self.ctx.state.set("cursor", record.record_id)

    class AttestAction(p.Action):
        name = "attest_test"
        needs = frozenset({"attest.submit"})

        async def perform(self, mapped, *, key, dry_run):
            body = {"claim": dict(mapped)}
            if dry_run:
                return p.Outcome.dry("would attest", request=body)
            r = await self.ctx.call("POST", "/api/v1/attestations", json=body, idempotency_key=key)
            if r.status_code >= 500 or r.status_code == 429:
                raise p.Retry(f"HTTP {r.status_code}", status=r.status_code)
            if r.status_code >= 400:
                raise p.Refused(f"HTTP {r.status_code}", status=r.status_code, answer=r.json())
            return p.Outcome.done(reference=str(r.json().get("id", "")))

    class ListSink(p.Sink):
        name = "list_sink"
        delivered = []

        async def deliver(self, event, *, key, dry_run):
            if dry_run:
                return p.Outcome.dry("would deliver", event_id=event.event_id)
            if key not in [k for k, _ in type(self).delivered]:
                type(self).delivered.append((key, event.event_id))
            return p.Outcome.done(reference=key)

    return ListSource, AttestAction, ListSink


# ── the interface ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_each_kind_keeps_the_interface():
    p, t = _p(), _t()
    src, act, sink = _kinds()
    for cls, kind in ((src, "source"), (act, "action"), (sink, "sink")):
        assert p.problems(cls) == () and p.problems(cls, kind) == ()
        t.check_class(cls, kind)
    assert p.GROUPS == {"source": "theprotocol.proxy.sources", "action": "theprotocol.proxy.actions",
                        "sink": "theprotocol.proxy.sinks"}
    assert p.INTERFACE_VERSION == 1


def test_a_class_that_breaks_the_interface_is_named_for_what_it_breaks():
    p = _p()
    src, act, _sink = _kinds()

    class NoName(src):
        name = "Not A Name"

    class Abstract(p.Source):
        name = "abstract_source"

    class OldInterface(src):
        name = "old_one"
        interface = 0

    class NoSchema(src):
        name = "no_schema"
        config_schema = {"type": "array"}

    class LooseNeeds(act):
        name = "loose_needs"
        needs = {"attest.submit"}

    assert any("lower-case identifier" in x for x in p.problems(NoName))
    assert any("does not implement records" in x for x in p.problems(Abstract))
    assert any("built for interface 0" in x for x in p.problems(OldInterface))
    assert any("config_schema" in x for x in p.problems(NoSchema))
    assert any("needs is not a frozenset" in x for x in p.problems(LooseNeeds))
    assert any("is not a Sink" in x for x in p.problems(src, "sink"))
    assert p.problems(object()) and p.problems(src, "nothing")


def test_an_outcome_is_done_or_a_dry_run_and_a_refusal_is_raised():
    p = _p()
    assert p.Outcome.done("att-1", proof="x").status == "done" and p.Outcome.done("att-1").reference == "att-1"
    assert p.Outcome.dry("would", request={"a": 1}).data == {"request": {"a": 1}}
    with pytest.raises(ValueError):
        p.Outcome("refused")
    r = p.Refused("no", status=422, answer={"detail": "no"})
    assert (r.detail, r.status, r.answer) == ("no", 422, {"detail": "no"})
    assert p.Retry("later", after=30).after == 30


def _fake_entry_points(monkeypatch, group_items):
    p = _p()

    def eps(group):
        return [types.SimpleNamespace(name=n, value=v) for n, v in group_items.get(group, [])]
    monkeypatch.setattr(p, "_entry_points", eps)


def test_a_plugin_is_found_by_its_entry_point_and_checked_when_it_loads(monkeypatch):
    p = _p()
    src, act, sink = _kinds()
    mod = types.ModuleType("proxy_plugins_under_test")
    mod.ListSource, mod.AttestAction, mod.ListSink = src, act, sink
    mod.Misnamed = type("Misnamed", (src,), {"name": "other_name"})
    mod.NotAPlugin = type("NotAPlugin", (), {})
    monkeypatch.setitem(__import__("sys").modules, "proxy_plugins_under_test", mod)
    _fake_entry_points(monkeypatch, {
        "theprotocol.proxy.sources": [("list_source", "proxy_plugins_under_test:ListSource"),
                                      ("misnamed", "proxy_plugins_under_test:Misnamed"),
                                      ("broken", "proxy_plugins_under_test:NotAPlugin"),
                                      ("gone", "no_such_module_anywhere:Thing")],
        "theprotocol.proxy.actions": [("attest_test", "proxy_plugins_under_test:AttestAction")],
    })
    assert p.load("source", "list_source") is src and p.load("action", "attest_test") is act
    assert set(p.available("source")) >= {"list_source", "misnamed", "broken", "gone"}
    with pytest.raises(p.PluginError, match="calls itself 'other_name'"):
        p.load("source", "misnamed")
    with pytest.raises(p.PluginError, match="does not keep the interface"):
        p.load("source", "broken")
    with pytest.raises(p.PluginError, match="does not load"):
        p.load("source", "gone")
    with pytest.raises(p.PluginError, match="no sink plugin called 'nope'"):
        p.load("sink", "nope")
    with pytest.raises(p.PluginError, match="no plugin kind"):
        p.available("filter")


def test_an_installed_plugin_never_takes_a_built_ins_name(monkeypatch):
    p = _p()
    monkeypatch.setitem(p.BUILTINS["source"], "webhook", "theprotocol.proxy.sources_builtin:WebhookSource")
    _fake_entry_points(monkeypatch, {"theprotocol.proxy.sources": [("webhook", "evil_plugin:Webhook")]})
    assert p.available("source")["webhook"] == "theprotocol.proxy.sources_builtin:WebhookSource"


# ── the contract kit, and that it fails what it is for ───────────────────────────────────────────────────────────────

ITEMS = {"items": [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}]}


async def test_the_source_contract_passes_a_source_that_keeps_it():
    t = _t()
    src, _a, _s = _kinds()
    ctx = t.FakeContext()
    got = await t.check_source(src, ITEMS, ctx=ctx)
    assert [r.record_id for r in got] == ["1", "2"] and await ctx.state.get("cursor") == "2"


async def test_the_source_contract_fails_a_source_that_calls_out_or_changes_its_ids():
    p, t = _p(), _t()
    src, _a, _s = _kinds()
    import itertools
    counter = itertools.count()

    class Caller(src):
        name = "caller"

        async def records(self):
            await self.ctx.call("GET", "/api/v1/agents")
            yield p.Record(record_id="1", payload={})

    class Unstable(src):
        name = "unstable"

        async def records(self):
            yield p.Record(record_id=f"r{next(counter)}", payload={})

    class Unserializable(src):
        name = "unserializable"

        async def records(self):
            yield p.Record(record_id="1", payload={"when": object()})

    with pytest.raises(AssertionError, match="a source only reads"):
        await t.check_source(Caller, {})
    with pytest.raises(AssertionError, match="other record ids"):
        await t.check_source(Unstable, {})
    with pytest.raises(AssertionError, match="not JSON-compatible"):
        await t.check_source(Unserializable, {})


async def test_the_resume_contract_passes_a_source_whose_cursor_holds_and_fails_one_without():
    p, t = _p(), _t()
    src, _a, _s = _kinds()

    class Cursor(src):
        name = "cursor_source"

        async def records(self):
            after = await self.ctx.state.get("cursor")
            for item in self.config.get("items", []):
                if after is not None and int(item["id"]) <= int(after):
                    continue
                yield p.Record(record_id=str(item["id"]), payload=item)

    class Cursorless(src):
        name = "cursorless"

        async def committed(self, record):
            pass

    class Skips(Cursor):
        name = "skips"

        async def committed(self, record):
            await self.ctx.state.set("cursor", str(int(record.record_id) + 1))

    items = {"items": [{"id": i} for i in range(1, 6)]}
    assert await t.check_resume(Cursor, items, first=2) == ["1", "2", "3", "4", "5"]
    with pytest.raises(AssertionError, match="again after a restart"):
        await t.check_resume(Cursorless, items, first=2)
    with pytest.raises(AssertionError, match="resumed at the wrong record"):
        await t.check_resume(Skips, items, first=2)


async def test_the_action_contract_passes_an_action_that_keeps_it():
    t = _t()
    _s, act, _k = _kinds()
    out = await t.check_action(act, {}, {"temperature": 4.2}, answers=[t.FakeResponse(200, {"id": "att-9"})])
    assert out.reference == "att-9"
    await t.check_action_refusals(act, {}, {"temperature": 4.2})


async def test_the_action_contract_fails_an_action_that_loses_the_key_sends_in_a_dry_run_or_swallows_a_refusal():
    p, t = _p(), _t()
    _s, act, _k = _kinds()

    class NoKey(act):
        name = "no_key"

        async def perform(self, mapped, *, key, dry_run):
            if dry_run:
                return p.Outcome.dry()
            await self.ctx.call("POST", "/api/v1/attestations", json={})
            return p.Outcome.done()

    class SendsWhenDry(act):
        name = "sends_when_dry"

        async def perform(self, mapped, *, key, dry_run):
            await self.ctx.call("POST", "/api/v1/attestations", json={}, idempotency_key=key)
            return p.Outcome.dry() if dry_run else p.Outcome.done()

    class Swallows(act):
        name = "swallows"

        async def perform(self, mapped, *, key, dry_run):
            if dry_run:
                return p.Outcome.dry()
            await self.ctx.call("POST", "/api/v1/attestations", json={}, idempotency_key=key)
            return p.Outcome.done(detail="whatever it answered")

    with pytest.raises(AssertionError, match="without the record's key"):
        await t.check_action(NoKey, {}, {})
    with pytest.raises(AssertionError, match="dry run called POST"):
        await t.check_action(SendsWhenDry, {}, {})
    with pytest.raises(AssertionError, match="instead of raising Refused"):
        await t.check_action_refusals(Swallows, {}, {})


async def test_the_sink_contract_delivers_one_key_once_and_nothing_in_a_dry_run():
    p, t = _p(), _t()
    _s, _a, sink = _kinds()
    sink.delivered = []
    ev = p.Event(event_id="evt-1", event_type="SlashMoved", aggregate_id="did:x", data={"amount": "3"})
    out = await t.check_sink(sink, {}, ev, delivered=lambda: sink.delivered)
    assert out.status == "done" and sink.delivered == [("proxy-contract-key-3", "evt-1")]

    class Twice(p.Sink):
        name = "twice"
        got = []

        async def deliver(self, event, *, key, dry_run):
            if not dry_run:
                type(self).got.append(key)
            return p.Outcome.dry() if dry_run else p.Outcome.done()

    with pytest.raises(AssertionError, match="delivered one key twice"):
        await t.check_sink(Twice, {}, ev, delivered=lambda: Twice.got)


async def test_the_fake_context_resolves_secrets_and_keeps_state_as_json():
    t = _t()
    ctx = t.FakeContext(secrets={"env:ERP_TOKEN": "s3cret"})
    assert ctx.secret("env:ERP_TOKEN") == "s3cret"
    with pytest.raises(KeyError):
        ctx.secret("env:NOT_SET")
    await ctx.state.set("cursor", {"at": 3})
    assert await ctx.state.get("cursor") == {"at": 3} and await ctx.state.get("nothing", 0) == 0
