"""§SOVKIT V0369 (2026-09-14, agentvault2-85's finding) — the reactor's "Connecting to <ws url>" line no longer logs the
store's credential. `reactor_base` built the websocket URL with `?token=<INTERNAL_API_KEY or JWT-SVID>` and logged it whole
on every connect (sbx-alpha 60, sbx-beta 120, eu 55, asia 55 lines in 24 h; the live store key, readable in Dozzle).
The line now goes through the one masker the access log uses (core/access_log_mask.mask_query_secrets).
"""
from __future__ import annotations

import inspect
import logging

from agentvault_registry.background_tasks import reactor_base as rb
from agentvault_registry.core.access_log_mask import mask_query_secrets


def test_the_masker_hides_a_token_in_a_websocket_url_and_keeps_the_rest():
    url = "wss://eu-nginx-event-store:8443/ws/events?token=abc.def.ghi&types=TokensTransferred"
    out = mask_query_secrets(url)
    assert "abc.def.ghi" not in out and "token=" in out and "types=TokensTransferred" in out and out.startswith("wss://eu-nginx-event-store:8443/ws/events?")
    assert mask_query_secrets("http://es:8200/ws/events") == "http://es:8200/ws/events"


def test_the_connect_line_is_masked_at_source():
    src = inspect.getsource(rb)
    assert "Connecting to {mask_query_secrets(ws_url)}" in src
    assert "Connecting to {ws_url}" not in src, "the unmasked line is back"
    assert rb.mask_query_secrets is mask_query_secrets, "the reactor uses the one masker, not a copy"


def test_a_log_record_built_the_way_the_reactor_builds_it_carries_no_token(caplog):
    logger = logging.getLogger("agentvault_registry.background_tasks.reactor_base")
    ws_url = "ws://eu-event-store:8200/ws/events?token=THE-LIVE-STORE-KEY"
    with caplog.at_level(logging.INFO, logger=logger.name):
        logger.info(f"[Reactor:test] Connecting to {rb.mask_query_secrets(ws_url)}")
    lines = [r.getMessage() for r in caplog.records]
    assert lines and "THE-LIVE-STORE-KEY" not in lines[0] and "Connecting to ws://eu-event-store:8200/ws/events?token=" in lines[0]
