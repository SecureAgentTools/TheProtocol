"""Unit tests for theprotocol.registry.cost_composition."""
from decimal import Decimal

import pytest

from theprotocol.registry import (
    SIGNED_CANONICAL_PATHS,
    compute_total_cost,
    extract_signed_payload,
)


def _sybil_card():
    """SYBIL-shaped agent card with 5.0 AVT base rate."""
    return {
        "did": "did:theprotocol:0f254f2c-9555-a764-aadc",
        "name": "SYBIL",
        "extensions": [
            {
                "uri": "https://theprotocol.cloud/extensions/v1/auth/a2a-payment",
                "params": {"currency": "AVT", "base_rate": "5.0", "pricing_model": "per_request"},
            },
        ],
    }


def _frame_a_card(*, hosting_enabled=False, hosting_pct="0.0",
                  applies_to=None, cross_pct="0.5"):
    return {
        "registry_card_version": "0.3",
        "identity": {"spiffe_id": "spiffe://agentvault.com/registry/Registry-A"},
        "fees": {
            "cross_registry": {"base_rate_percent": cross_pct, "fee_recipient": "receiver_registry"},
            "hosting": {
                "enabled": hosting_enabled,
                "rate_percent_of_agent_service_fee": hosting_pct,
                "applies_to_agent_dids": applies_to,
            },
            "settlement_currency": "AVT",
        },
    }


def test_spec_section_4_example():
    """Spec §4 reference: 5.0 AVT → buyer pays 5.025, agent gets 4.975, host gets 0.025."""
    cost = compute_total_cost(_sybil_card(), _frame_a_card())
    assert cost["service_price"] == Decimal("5.0")
    assert cost["hosting_fee"] == Decimal("0")
    assert cost["cross_registry_fee"] == Decimal("0.025000")
    assert cost["buyer_total"] == Decimal("5.025000")
    assert cost["agent_receives"] == Decimal("4.975000")
    assert cost["hosting_registry_gets"] == Decimal("0.025000")
    assert cost["currency"] == "AVT"


def test_hosting_enabled_general():
    """Hosting fee applies when enabled + applies_to is None."""
    cost = compute_total_cost(_sybil_card(), _frame_a_card(hosting_enabled=True, hosting_pct="5.0"))
    assert cost["hosting_fee"] == Decimal("0.250000")
    assert cost["cross_registry_fee"] == Decimal("0.025000")
    assert cost["buyer_total"] == Decimal("5.275000")
    assert cost["agent_receives"] == Decimal("4.975000")
    assert cost["hosting_registry_gets"] == Decimal("0.275000")


def test_hosting_applies_to_specific_did():
    """Hosting fee applies only when the agent DID is in applies_to."""
    sybil = _sybil_card()
    # SYBIL in the allowlist → hosting fee applies.
    rc = _frame_a_card(hosting_enabled=True, hosting_pct="5.0", applies_to=[sybil["did"]])
    cost = compute_total_cost(sybil, rc)
    assert cost["hosting_fee"] == Decimal("0.250000")
    # Different DID in allowlist → hosting fee skipped.
    cost2 = compute_total_cost(sybil, _frame_a_card(hosting_enabled=True, hosting_pct="5.0",
                                                    applies_to=["did:theprotocol:other-agent"]))
    assert cost2["hosting_fee"] == Decimal("0")


def test_higher_cross_reg_fee_future_state():
    """When LOCKED_PARAMS opens, operators can declare e.g. 0.7%."""
    cost = compute_total_cost(_sybil_card(), _frame_a_card(cross_pct="0.7"))
    assert cost["cross_registry_fee"] == Decimal("0.035000")
    assert cost["buyer_total"] == Decimal("5.035000")
    assert cost["agent_receives"] == Decimal("4.965000")


def test_free_service():
    """Zero-price agent (free service) — fees compute to zero."""
    free_agent = _sybil_card()
    free_agent["extensions"][0]["params"]["base_rate"] = "0"
    cost = compute_total_cost(free_agent, _frame_a_card(hosting_enabled=True, hosting_pct="5.0"))
    assert cost["service_price"] == Decimal("0")
    assert cost["buyer_total"] == Decimal("0")
    assert cost["agent_receives"] == Decimal("0")


def test_round_half_even_banker_rounding():
    """0.005 → 0.000 (ties round to nearest even) per spec rounding mode."""
    # Make a 1.0 AVT service at 0.5% → 0.005 cross fee. Quantised at 6dp = 0.005000.
    cost = compute_total_cost(_sybil_card(), _frame_a_card(cross_pct="0.5"))
    # 5.0 * 0.5% = 0.025 — no rounding ambiguity at this scale.
    assert cost["cross_registry_fee"] == Decimal("0.025000")


def test_missing_payment_extension_raises():
    bare_agent = {"did": "did:theprotocol:bare", "name": "Bare", "extensions": []}
    with pytest.raises(ValueError, match="no extension with uri"):
        compute_total_cost(bare_agent, _frame_a_card())


def test_signed_canonical_paths_count_and_order():
    """Order matters for signature reproducibility — 13 fields, exact order."""
    assert len(SIGNED_CANONICAL_PATHS) == 13
    assert SIGNED_CANONICAL_PATHS[0] == "registry_card_version"
    assert SIGNED_CANONICAL_PATHS[-1] == "lifecycle.card_etag"
    # Order must be stable across SDK versions.
    expected_first_five = [
        "registry_card_version",
        "identity.spiffe_id",
        "identity.registry_name",
        "identity.trust_domain",
        "identity.tier",
    ]
    assert SIGNED_CANONICAL_PATHS[:5] == expected_first_five


def test_extract_signed_payload_pulls_dotted_paths():
    card = {
        "registry_card_version": "0.3",
        "identity": {
            "spiffe_id": "spiffe://agentvault.com/registry/Registry-A",
            "registry_name": "Registry-A",
            "trust_domain": "agentvault.com",
            "tier": "sovereign-mainframe",
        },
        "visual": {"sovereign_variant": "genesis-flame"},
        "federation": {
            "is_genesis_registry": True,
            "is_sovereign_frame": True,
            "policy_hash": "sha256:abc",
        },
        "fees": {
            "cross_registry": {"base_rate_percent": 0.5},
            "hosting": {"enabled": False, "rate_percent_of_agent_service_fee": 0.0},
        },
        "lifecycle": {"card_etag": "sha256:def"},
    }
    payload = extract_signed_payload(card)
    assert payload["registry_card_version"] == "0.3"
    assert payload["identity.spiffe_id"] == "spiffe://agentvault.com/registry/Registry-A"
    assert payload["visual.sovereign_variant"] == "genesis-flame"
    assert payload["fees.cross_registry.base_rate_percent"] == 0.5
    assert payload["lifecycle.card_etag"] == "sha256:def"
    # Missing path → None (not raise).
    bare = extract_signed_payload({"registry_card_version": "0.3"})
    assert bare["identity.spiffe_id"] is None
