# SPDX-License-Identifier: Apache-2.0
"""The card this agent serves at /.well-known/agent-card.json (A2A v1.0).

The download carries the registry's copy of your card as agent-card.json. At start the agent serves that card with three
things made true: the A2A endpoint is PUBLIC_URL + /a2a, the example skill is declared, and the price is stated in the
payment extension (https://theprotocol.cloud/extensions/v1/auth/a2a-payment) whenever PRICE is above zero. The registry
reads this card from your host and keeps your fields (name, description, skills, interfaces, extensions); the fields a
registry owns are never served.
"""
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Optional

PAYMENT_EXTENSION_URI = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment"
REGISTRY_OWNED = ("federation_metadata", "flare", "last_pulled_at", "last_pulled_etag")
EXAMPLE_SKILL = {
    "id": "text-stats",
    "name": "Text statistics",
    "description": "Counts the words, characters and sentences of a text and names its most used words.",
    "tags": ["text", "example"],
    "examples": ["How long is this paragraph, and which words does it use most?"],
    "inputModes": ["text/plain"],
    "outputModes": ["text/plain", "application/json"],
}
CARD_FILE = Path(__file__).with_name("agent-card.json")


def load_card(path: Optional[Path] = None) -> Dict[str, Any]:
    """The card the download carried (agent-card.json), or an empty card when there is none."""
    p = path or CARD_FILE
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def price_of(raw: Optional[str]) -> Decimal:
    """PRICE as a decimal number of units: 0 for an empty or unreadable value (the agent is then free)."""
    try:
        value = Decimal(str(raw or "0").strip())
    except InvalidOperation:
        return Decimal(0)
    return value if value.is_finite() and value > 0 else Decimal(0)


def build_card(base: Dict[str, Any], *, name: str, public_url: str, price: Decimal, currency: str,
               payment_required: bool) -> Dict[str, Any]:
    """The card to serve: `base` (the registry's copy) with the endpoint, the example skill and the price made true."""
    card = {k: v for k, v in (base or {}).items() if k not in REGISTRY_OWNED}
    card["protocolVersion"] = "1.0"
    card["name"] = card.get("name") or name
    card.setdefault("description", f"{card['name']}, an agent on TheProtocol.")
    endpoint = public_url.rstrip("/") + "/a2a"
    card["supportedInterfaces"] = [{"url": endpoint, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]
    card["url"] = endpoint   # the A2A v0.3 field, for older readers
    card.setdefault("capabilities", {"streaming": False})
    skills = [s for s in (card.get("skills") or []) if isinstance(s, dict)]
    if not any(s.get("id") == EXAMPLE_SKILL["id"] for s in skills):
        skills.append(dict(EXAMPLE_SKILL))
    card["skills"] = skills
    extensions = [e for e in (card.get("extensions") or [])
                  if isinstance(e, dict) and e.get("uri") != PAYMENT_EXTENSION_URI]
    if price > 0:
        extensions.append({"uri": PAYMENT_EXTENSION_URI, "required": bool(payment_required),
                           "params": {"base_rate": str(price), "currency": currency,
                                      "pricing_model": "per_request"}})
    card["extensions"] = extensions
    card.pop("pricing", None)   # one place states the price: the extension
    return card
