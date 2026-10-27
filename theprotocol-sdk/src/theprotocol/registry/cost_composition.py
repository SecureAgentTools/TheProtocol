"""Registry Card v0.3 — cost-composition reference helper.

Given an Agent Card + the agent's host Registry Card, compute the buyer's
total upfront cost (service price + optional hosting fee + cross-registry
network fee). Mirrors the spec §8 math.

All amounts are Decimal — use ROUND_HALF_EVEN (banker's) per spec
`economic_disclosure.rounding`. The card declares `fee_floor_avt = 0.000001`,
so results are quantised to 6 decimal places.

Reference implementation; clients may inline this logic.
"""
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Dict, List, Optional

_FEE_FLOOR = Decimal("0.000001")


# The v0.3 BASELINE signing set (13 paths). Newer cards (v0.4+; prod is v0.5
# with 23 paths) declare their own longer list in signature.signed_canonical —
# verifiers must prefer the card's declared list; this constant is only the
# fallback for cards that declare nothing.
SIGNED_CANONICAL_PATHS: List[str] = [
    "registry_card_version",
    "identity.spiffe_id",
    "identity.registry_name",
    "identity.trust_domain",
    "identity.tier",
    "visual.sovereign_variant",
    "federation.is_genesis_registry",
    "federation.is_sovereign_frame",
    "federation.policy_hash",
    "fees.cross_registry.base_rate_percent",
    "fees.hosting.enabled",
    "fees.hosting.rate_percent_of_agent_service_fee",
    "lifecycle.card_etag",
]


def extract_signed_payload(card: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the 13 signed canonical paths out of a card, in deterministic order.

    Returns a dict keyed by full dotted path → value. Re-encode with
    json.dumps(sort_keys=True, separators=(",", ":"), default=str) to get
    the exact bytes that were signed.
    """
    out: Dict[str, Any] = {}
    for path in SIGNED_CANONICAL_PATHS:
        cursor: Any = card
        for part in path.split("."):
            if isinstance(cursor, dict) and part in cursor:
                cursor = cursor[part]
            else:
                cursor = None
                break
        out[path] = cursor
    return out


def _q(amount: Decimal) -> Decimal:
    return amount.quantize(_FEE_FLOOR, rounding=ROUND_HALF_EVEN)


def compute_total_cost(
    agent_card: Dict[str, Any],
    host_registry_card: Dict[str, Any],
    *,
    a2a_extension_uri: str = "https://theprotocol.cloud/extensions/v1/auth/a2a-payment",
) -> Dict[str, Any]:
    """Compute buyer cost breakdown from an agent card + the agent's host RC.

    Args:
        agent_card: A2A v1.0 Agent Card body (dict).
        host_registry_card: The Registry Card v0.3 of the registry hosting the agent.
        a2a_extension_uri: Override if the agent uses a non-canonical
            payment-extension URI.

    Returns:
        {
          "service_price":          Decimal,
          "hosting_fee":            Decimal,
          "cross_registry_fee":     Decimal,
          "buyer_total":            Decimal,
          "agent_receives":         Decimal,
          "hosting_registry_gets":  Decimal,
          "currency":               "ECU",
        }

    Raises:
        ValueError: if the agent card has no a2a-payment extension or the RC
            has no fees block.
    """
    # 1. Service price from Agent Card.
    extensions = agent_card.get("extensions") or []
    a2a_ext = next(
        (ext for ext in extensions if ext.get("uri") == a2a_extension_uri),
        None,
    )
    if a2a_ext is None:
        raise ValueError(
            f"Agent card has no extension with uri={a2a_extension_uri!r}; "
            f"agents accepting A2A payments MUST publish this extension."
        )
    base_rate_raw = (a2a_ext.get("params") or {}).get("base_rate")
    if base_rate_raw is None:
        raise ValueError("a2a-payment extension missing params.base_rate")
    service_price = Decimal(str(base_rate_raw))

    # 2. Hosting fee from Registry Card.
    fees = host_registry_card.get("fees") or {}
    hosting = fees.get("hosting") or {}
    hosting_enabled = bool(hosting.get("enabled", False))
    applies_to = hosting.get("applies_to_agent_dids")
    agent_did = agent_card.get("did") or agent_card.get("agent_did")
    if hosting_enabled and (applies_to is None or (agent_did and agent_did in applies_to)):
        host_pct = Decimal(str(hosting.get("rate_percent_of_agent_service_fee", "0")))
        hosting_fee = _q(service_price * host_pct / Decimal("100"))
    else:
        hosting_fee = Decimal("0")

    # 3. Cross-registry fee from RC.
    cross_reg = fees.get("cross_registry") or {}
    cross_pct = Decimal(str(cross_reg.get("base_rate_percent", "0")))
    cross_registry_fee = _q(service_price * cross_pct / Decimal("100"))

    buyer_total = _q(service_price + hosting_fee + cross_registry_fee)
    agent_receives = _q(service_price - cross_registry_fee)
    hosting_registry_gets = _q(hosting_fee + cross_registry_fee)

    return {
        "service_price":          service_price,
        "hosting_fee":            hosting_fee,
        "cross_registry_fee":     cross_registry_fee,
        "buyer_total":            buyer_total,
        "agent_receives":         agent_receives,
        "hosting_registry_gets":  hosting_registry_gets,
        "currency":               fees.get("settlement_currency", ""),
    }


__all__ = [
    "SIGNED_CANONICAL_PATHS",
    "extract_signed_payload",
    "compute_total_cost",
]
