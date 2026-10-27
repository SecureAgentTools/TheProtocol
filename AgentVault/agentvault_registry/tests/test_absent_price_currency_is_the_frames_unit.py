"""§DOCSFIX D6-457 + CB-437 (2026-10-16): a price that names no currency is read in the registry's own unit, never in
a retired one.

The /quote rail fills the reading registry's FRAME_CURRENCY for a legacy pricing block, and the console fills its own
registry's unit (services/cardPricing.ts), but two readers filled a hard-coded "AVT", a unit no production frame uses:
`compat.derive_payment_extension` (the extension a registry derives for its own paid cards, measured on EU: SYBIL's read
currency AVT, base_rate 5.0) and the discovery SQL (`_SQL_PRICING_EFFECTIVE`, for an extension without a currency).
Both now take the registry's own unit (core/frame_currency), so every reader agrees: an absent currency is the unit of
the registry that reads the card, which for a card on its own registry is the agent's own unit.

RED on the pre-change tree: the two ECU tests. The controls are green before and after.
"""
from __future__ import annotations

import os
import subprocess
import sys

from agentvault_registry.services.a2a_v1.compat import derive_payment_extension

URI = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"


def _ext(card):
    return next(e for e in card.get("extensions", []) if e.get("uri") == URI)


def test_a_derived_extension_names_the_registrys_own_unit(monkeypatch):
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    card = derive_payment_extension({"name": "SYBIL", "pricing": {"base_rate": 5.0, "payment_required": True}})
    assert _ext(card)["params"] == {"base_rate": "5.0", "currency": "ECU", "pricing_model": "per_request"}


_PROBE = (
    "from agentvault_registry.routers import agent_cards as m; "
    "sqls = (m._SQL_PRICING_EFFECTIVE, m._ONE_CARD_PRICING_SQL, m._DISCOVER_SLIM_CTE); "
    "print('|'.join(str(int(token in s)) for s in sqls for token in (\"'ECU'\", \"'AVT'\")))"
)


def _probe(ccy):
    env = dict(os.environ)
    env["FRAME_CURRENCY"] = ccy
    env.setdefault("PYTHONPATH", "/app/src")
    out = subprocess.run([sys.executable, "-c", _PROBE], capture_output=True, text=True, env=env, timeout=180)
    assert out.returncode == 0, f"probe failed: {out.stderr[-800:]}"
    return out.stdout.strip().splitlines()[-1]


def test_the_discovery_price_rule_fills_an_absent_extension_currency_with_the_registrys_own_unit():
    # each of the three statements built from the rule: 'ECU' present (1), 'AVT' absent (0)
    assert _probe("ECU") == "1|0|1|0|1|0"


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_currency_the_block_names_is_kept_upper_case(monkeypatch):
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    card = derive_payment_extension({"pricing": {"base_rate": "0.5", "currency": "acu", "model": "per_call"}})
    assert _ext(card)["params"] == {"base_rate": "0.5", "currency": "ACU", "pricing_model": "per_call"}


def test_control_an_extension_the_author_wrote_is_never_overwritten(monkeypatch):
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    own = {"uri": URI, "params": {"base_rate": "2"}}
    card = derive_payment_extension({"pricing": {"base_rate": "5", "payment_required": True}, "extensions": [own]})
    assert card["extensions"] == [own]


def test_control_a_block_without_a_usable_rate_gets_no_extension(monkeypatch):
    monkeypatch.setenv("FRAME_CURRENCY", "ECU")
    card = derive_payment_extension({"pricing": {"payment_required": True}})
    assert "extensions" not in card
