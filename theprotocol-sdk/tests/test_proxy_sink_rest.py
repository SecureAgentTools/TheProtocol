"""V0664 (Migrate a system, M1): the writer `rest`, a sink that sends each mapped record to a system's HTTP API.

Unlike the webhook (which wraps an event in an envelope), the MAPPED FIELDS ARE THE BODY: the record is already the shape
the new system wants. {field} placeholders in the url are filled from the mapped fields and URL-encoded (a missing one
refuses the record naming the field); the record's key goes out as an Idempotency-Key (configurable, "" omits it); the id
the other side made is read from the answer at reference_path ($.id by default). Status handling is the webhook's: 2xx
done; 408, 425, 429 and 5xx Retry (Retry-After honoured); anything else Refused with up to 300 characters of the answer.
RED on stack master ed708438: theprotocol.proxy.sinks.rest does not exist.
"""
from __future__ import annotations

import json

import httpx
import pytest

from theprotocol.proxy.plugins import Event, PluginError, Refused, Retry
from theprotocol.proxy.testing import FakeContext, check_sink


@pytest.fixture(autouse=True)
def fake_plugins(monkeypatch):
    """The spec tests below name a source and need one: the shared fakes (proxy_fake) stand in."""
    from theprotocol.proxy import plugins
    monkeypatch.setitem(plugins.BUILTINS["source"], "list_source", "proxy_fake:ListSource")
    monkeypatch.setitem(plugins.BUILTINS["sink"], "list_sink", "proxy_fake:ListSink")


def _ev(i=1, **data):
    return Event(event_id=f"evt-{i}", event_type="migration.row", aggregate_id="customers", data=data)


class _Server:
    """An httpx transport that records what it was sent and answers from a script."""

    def __init__(self, *answers):
        self.requests = []
        self._answers = list(answers)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._answers:
            a = self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]
            return a if isinstance(a, httpx.Response) else httpx.Response(a)
        return httpx.Response(201, json={"id": "crm-77"})


def _sink(server, **cfg):
    from theprotocol.proxy.sinks.rest import RestSink

    class Wired(RestSink):
        transport = httpx.MockTransport(server)
    base = {"url": "https://crm.example.org/api/customers", "method": "POST"}
    base.update(cfg)
    return Wired(base, FakeContext(secrets={"env:CRM_TOKEN": "tok-123"}))


async def test_it_keeps_the_sink_contract_and_is_a_builtin():
    from theprotocol.proxy import plugins
    from theprotocol.proxy.sinks.rest import RestSink
    assert plugins.BUILTINS["sink"]["rest"] == "theprotocol.proxy.sinks.rest:RestSink"
    assert plugins.load("sink", "rest") is RestSink
    server = _Server(201)
    from theprotocol.proxy.sinks.rest import RestSink as R

    class Wired(R):
        transport = httpx.MockTransport(server)
    out = await check_sink(Wired, {"url": "https://crm.example.org/api/customers"}, _ev(1, id=1, name="Ada"))
    assert out.status == "done"
    assert len(server.requests) == 1                         # the dry run sent nothing; the real delivery sent one


async def test_the_mapped_fields_are_the_body_with_no_envelope_and_the_key_is_the_idempotency_key():
    server = _Server(201)
    sink = _sink(server)
    out = await sink.deliver(_ev(1, id=7, name="Ada", tags=["a", "b"]), key="tpx-1", dry_run=False)
    (req,) = server.requests
    assert req.method == "POST" and str(req.url) == "https://crm.example.org/api/customers"
    assert json.loads(req.content) == {"id": 7, "name": "Ada", "tags": ["a", "b"]}
    assert req.headers["Idempotency-Key"] == "tpx-1" and req.headers["Content-Type"] == "application/json"
    assert out.status == "done"


async def test_the_idempotency_header_can_be_renamed_or_left_out():
    renamed, omitted = _Server(201), _Server(201)
    await _sink(renamed, idempotency_header="X-Request-Id").deliver(_ev(1, id=1), key="k1", dry_run=False)
    await _sink(omitted, idempotency_header="").deliver(_ev(1, id=1), key="k1", dry_run=False)
    assert renamed.requests[0].headers["X-Request-Id"] == "k1" and "Idempotency-Key" not in renamed.requests[0].headers
    assert "Idempotency-Key" not in omitted.requests[0].headers


async def test_placeholders_are_filled_from_the_mapped_fields_and_encoded():
    server = _Server(200)
    sink = _sink(server, url="https://crm.example.org/api/customers/{id}/notes/{slug}", method="PUT")
    await sink.deliver(_ev(1, id="a b/c", slug="x?y=1&z", body="hello"), key="k", dry_run=False)
    (req,) = server.requests
    assert req.method == "PUT"
    assert req.url.raw_path.decode() == "/api/customers/a%20b%2Fc/notes/x%3Fy%3D1%26z"
    assert json.loads(req.content) == {"body": "hello", "id": "a b/c", "slug": "x?y=1&z"}   # the fields stay in the body


async def test_a_missing_placeholder_refuses_the_record_naming_the_field():
    sink = _sink(_Server(200), url="https://crm.example.org/api/customers/{customer_id}")
    with pytest.raises(Refused) as e:
        await sink.deliver(_ev(1, id=1), key="k", dry_run=False)
    assert "customer_id" in e.value.detail


async def test_the_created_id_is_read_from_reference_path():
    default = _Server(httpx.Response(201, json={"id": "crm-77", "data": {"uid": "u-9"}}))
    assert (await _sink(default).deliver(_ev(1, id=1), key="k", dry_run=False)).reference == "crm-77"
    nested = _Server(httpx.Response(201, json={"id": "crm-77", "data": {"uid": "u-9"}}))
    assert (await _sink(nested, reference_path="$.data.uid").deliver(_ev(1, id=1), key="k", dry_run=False)).reference == "u-9"
    none = _Server(httpx.Response(204))
    assert (await _sink(none).deliver(_ev(1, id=1), key="the-key", dry_run=False)).reference == "the-key"


async def test_a_2xx_is_done_and_the_retryable_statuses_retry_with_the_servers_wait():
    for st in (408, 425, 429, 500, 503):
        sink = _sink(_Server(httpx.Response(st, headers={"Retry-After": "7"}, text="slow down")))
        with pytest.raises(Retry) as e:
            await sink.deliver(_ev(1, id=1), key="k", dry_run=False)
        assert e.value.status == st
        if st in (429, 503):
            assert e.value.after == 7
    for st in (200, 201, 202, 204):
        assert (await _sink(_Server(st)).deliver(_ev(1, id=1), key="k", dry_run=False)).status == "done"


async def test_other_statuses_are_refused_with_at_most_300_characters_of_the_answer():
    sink = _sink(_Server(httpx.Response(422, text="x" * 900)))
    with pytest.raises(Refused) as e:
        await sink.deliver(_ev(1, id=1), key="k", dry_run=False)
    assert e.value.status == 422 and len(e.value.answer) == 300 and "HTTP 422" in e.value.detail


async def test_an_unreachable_server_is_a_retry():
    def boom(request):
        raise httpx.ConnectError("refused")
    sink = _sink(boom)
    with pytest.raises(Retry):
        await sink.deliver(_ev(1, id=1), key="k", dry_run=False)


async def test_a_dry_run_sends_nothing_and_names_the_request():
    server = _Server(201)
    sink = _sink(server, url="https://crm.example.org/api/customers/{id}")
    out = await sink.deliver(_ev(1, id=5, name="Ada"), key="k", dry_run=True)
    assert server.requests == [] and out.status == "dry_run"
    assert out.data["url"] == "https://crm.example.org/api/customers/5" and out.data["method"] == "POST"
    assert out.data["body"] == {"id": 5, "name": "Ada"}


async def test_a_bearer_is_a_reference_and_a_credential_header_is_refused_at_start():
    server = _Server(201)
    sink = _sink(server, bearer="env:CRM_TOKEN")
    await sink.deliver(_ev(1, id=1), key="k", dry_run=False)
    assert server.requests[0].headers["Authorization"] == "Bearer tok-123"
    bad = _sink(_Server(201), headers={"Authorization": "Bearer written-out"})
    with pytest.raises(PluginError):
        await bad.start()


def test_a_literal_bearer_is_refused_at_load(tmp_path):
    import proxy_fake as F
    from theprotocol.proxy.spec import SpecError, parse
    doc = F.spec_doc(tmp_path, sinks={"crm": {"type": "rest", "config": {"url": "https://crm.example.org/api", "bearer": "tok-written-out"}}})
    with pytest.raises(SpecError) as e:
        parse(doc, base=tmp_path)
    assert "sinks.crm.config.bearer" in e.value.problems


def test_the_url_must_be_http_or_https_with_a_host():
    from theprotocol.proxy.sinks.rest import RestSink
    for bad in ("ftp://x.org/a", "crm.example.org/api", "file:///etc/passwd"):
        with pytest.raises(Exception):
            from jsonschema import validate
            validate({"url": bad}, RestSink.config_schema)
