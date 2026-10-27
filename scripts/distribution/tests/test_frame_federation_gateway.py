"""The frame's federation gateway passes the AGORA card a peer pulls (D6-645).

The registry card links its AGORA catalogue at /.well-known/stock-card.json (fees.exchange.stock_card.url), and a peer
with STOCK_CARD_SYNC pulls it first-hand over the federation lane. The frame template's gateway let only the registry
card, its JWKS and its schema through under /.well-known, so the pull met 404 and no frame's federated_stock_cards
filled. The location's own regex decides here.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
CONF = ROOT / "templates" / "frame-test" / "nginx-federation-frame-test.conf.tmpl"


@pytest.mark.skipif(not CONF.exists(), reason="the frame template is not beside this kit")
def test_the_well_known_lane_passes_the_card_documents_and_nothing_else():
    m = re.search(r"location ~ (\^/\\\.well-known/\S+\$) \{", CONF.read_text())
    assert m, "no regex location for /.well-known in the frame's federation gateway"
    lane = re.compile(m.group(1))
    for path in ("/.well-known/registry-card.json", "/.well-known/registry-jwks.json",
                 "/.well-known/registry-card-schema.json", "/.well-known/stock-card.json"):
        assert lane.match(path), path
    for path in ("/.well-known/acme-challenge/x", "/.well-known/stock-card.json.bak", "/.well-known/agent.json"):
        assert not lane.match(path), path
