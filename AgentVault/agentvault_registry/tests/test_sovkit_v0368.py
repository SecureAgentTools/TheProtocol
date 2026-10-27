"""§SOVKIT V0368 (2026-09-14) — two registry-side facts a frame's event-store mTLS flip depends on.

1. Frame Management's `license_auth_available` follows the EVENT STORE's own `/health` (`mtls_required`), and the
   answer NAMES its source; the registry's `EVENTSTORE_MTLS_REQUIRED` env is only the fallback, labelled as such
   (agentvault2-85's S0 risk 7: a copy of a fact that lives elsewhere keeps saying the old thing after the flip).
2. The emitter presents its INTERNAL KEY to its own store whenever it holds one; a federation licence is only what
   a registry without a key has left (S0 risk 5: a licensed frame's HTTP fallback to its OWN ledger was refused).
"""
from __future__ import annotations

from agentvault_registry import event_emitter as ee
from agentvault_registry.routers import operator_applications as oa


async def _drive(monkeypatch, env_copy: str | None, url: str | None, body=None, raises: Exception | None = None):
    if env_copy is None:
        monkeypatch.delenv("EVENTSTORE_MTLS_REQUIRED", raising=False)
    else:
        monkeypatch.setenv("EVENTSTORE_MTLS_REQUIRED", env_copy)
    if url is None:
        monkeypatch.delenv("EVENT_STORE_URL", raising=False)
    else:
        monkeypatch.setenv("EVENT_STORE_URL", url)
    seen = []

    async def fake_read(base):
        seen.append(base)
        if raises is not None:
            raise raises
        return body

    monkeypatch.setattr(oa, "_read_es_health", fake_read)
    return await oa._event_store_mtls_required(), seen


async def test_the_store_saying_true_wins_over_an_env_copy_saying_false(monkeypatch):
    (required, source), seen = await _drive(monkeypatch, "false", "http://eu-event-store:8200/", {"status": "ok", "mtls_required": True})
    assert required is True and source == "event-store:/health"
    assert seen == ["http://eu-event-store:8200"], "the trailing slash is stripped before /health is appended"


async def test_the_store_saying_false_wins_over_an_env_copy_saying_true(monkeypatch):
    (required, source), _ = await _drive(monkeypatch, "true", "http://eu-event-store:8200", {"mtls_required": False})
    assert required is False and source == "event-store:/health"


async def test_an_older_store_without_the_field_leaves_the_env_copy_labelled(monkeypatch):
    (required, source), _ = await _drive(monkeypatch, "true", "http://eu-event-store:8200", {"status": "ok"})
    assert required is True and source == "registry-env (the store reports no mtls_required)"
    (required, source), _ = await _drive(monkeypatch, "true", "http://eu-event-store:8200", {"mtls_required": "yes"})
    assert required is True and "reports no mtls_required" in source, "a non-boolean is not an answer"


async def test_a_store_that_does_not_answer_leaves_the_env_copy_labelled_and_never_raises(monkeypatch):
    (required, source), _ = await _drive(monkeypatch, "false", "http://eu-event-store:8200", raises=ConnectionError("down"))
    assert required is False and source == "registry-env (the store did not answer)"


async def test_no_store_url_is_the_env_copy_labelled(monkeypatch):
    (required, source), seen = await _drive(monkeypatch, "true", None, {"mtls_required": False})
    assert required is True and source == "registry-env (no EVENT_STORE_URL)" and seen == []


def _emitter(internal: str, licence: str) -> ee.EventEmitter:
    em = object.__new__(ee.EventEmitter)
    em.internal_api_key = internal
    em.federation_license_key = licence
    return em


def test_the_internal_key_wins_whenever_it_is_configured():
    assert _emitter("k-internal", "tp_fed_licence") ._auth_headers() == {"X-Internal-Key": "k-internal"}
    assert _emitter("k-internal", "")._auth_headers() == {"X-Internal-Key": "k-internal"}


def test_the_licence_is_only_what_a_registry_without_a_key_has_left():
    assert _emitter("", "tp_fed_licence")._auth_headers() == {"X-Federation-License": "tp_fed_licence"}
    assert _emitter("", "")._auth_headers() == {}


def test_emit_builds_its_headers_from_the_one_method():
    import inspect
    src = inspect.getsource(ee.EventEmitter.emit)
    assert "self._auth_headers()" in src
    assert "X-Federation-License" not in src and "X-Internal-Key" not in src, "a second copy of the decision is back in emit()"
