"""Naming parity tests — CLI's _safe_name and _slug MUST match mainframe.

Per Operator_CLI_Strategy.md §14.Q1 and §17.5 Appendix D, the CLI's copies
of these functions must produce byte-identical output to the mainframe
implementations. Drift means CLI commands silently target the wrong
operator or fail federation auth (the class of bugs flagged by
`feedback_peer_name_must_match_self_report.md`).

Run with:
  python -m pytest tests/property/test_naming_parity.py -v
"""
import re
import unicodedata

import pytest

from tp_operator.naming import safe_name, slug


# ── Mainframe-side reference implementations (verbatim copies) ──
# These MUST stay byte-identical to:
#   cloud_provisioner.py:_safe_name
#   teg_integration.py:_slug

def mainframe_safe_name(name: str) -> str:
    """Copied from cloud_provisioner.py:95-97."""
    return re.sub(r"[^a-z0-9-]", "", name.lower())[:40]


def mainframe_slug(n: str) -> str:
    """Copied from teg_integration.py:42-43."""
    return (
        unicodedata.normalize("NFKD", n)
        .encode("ASCII", "ignore")
        .decode("ASCII")
        .lower()
        .replace(" ", "-")
        .strip("-")
    )


# ── Corpus — historical + current operator names + edge cases ──
CORPUS = [
    "op-london",
    "op-paris",
    "op-tokyo",
    "op-singapore",
    "op-washington",
    "op-berlin",
    "op-sydney",
    "op-seoul",
    "sandboxalpha",
    "sandboxbeta",
    "sandboxgamma",
    "Sandbox Alpha",
    "Sandbox Beta",
    "Sandbox Gamma",
    "Registry A",
    "Registry B",
    "Registry Test A",
    "Registry Test B",
    "Frame-B",
    "my-registry",
    "MY-REGISTRY",
    "My Registry",
    "São Paulo",
    "São paulo operator",
    "東京",
    "drone-fleet-001",
    "DroneFleet-001",
    "neon-nyc",
    "acme-test",
    "alpha-b",
    "beta-b",
    "gamma-b",
    "iota-b",
    "kappa-b",
    "registry-a",
    "cloud-op-op-london",
    "",
    "a",
    "1",
    "a-b-c-d-e-f-g-h-i-j-k-l-m-n-o-p-q-r-s-t-u-v-w-x-y-z",
    "lots--of--hyphens--",
    "  spaces around  ",
    "MixedCASE123",
    "Has.Periods.And-Hyphens",
    "под",  # Cyrillic — should ASCII-strip to empty via NFKD
    "operator-with-emoji-🚀",
]


@pytest.mark.parametrize("name", CORPUS)
def test_safe_name_parity(name: str) -> None:
    assert safe_name(name) == mainframe_safe_name(name), (
        f"safe_name('{name}') drift: CLI={safe_name(name)!r} mainframe={mainframe_safe_name(name)!r}"
    )


@pytest.mark.parametrize("name", CORPUS)
def test_slug_parity(name: str) -> None:
    assert slug(name) == mainframe_slug(name), (
        f"slug('{name}') drift: CLI={slug(name)!r} mainframe={mainframe_slug(name)!r}"
    )


# ── Explicit divergence assertions ─────────────────────────────
# These document the cases where _safe_name and _slug INTENTIONALLY diverge.
# If both produce the same output here, that means at least one of the
# primitives has changed behavior — the test catches that.

DIVERGENT = [
    ("Sandbox Alpha", "sandboxalpha", "sandbox-alpha"),
    ("São Paulo", "sopaulo", "sao-paulo"),
    ("My Registry", "myregistry", "my-registry"),
]


@pytest.mark.parametrize("name,expected_safe,expected_slug", DIVERGENT)
def test_documented_divergence(name: str, expected_safe: str, expected_slug: str) -> None:
    assert safe_name(name) == expected_safe
    assert slug(name) == expected_slug
    assert expected_safe != expected_slug


# ── Idempotence ────────────────────────────────────────────────
@pytest.mark.parametrize("name", CORPUS)
def test_safe_name_idempotent(name: str) -> None:
    once = safe_name(name)
    twice = safe_name(once)
    # _safe_name is NOT strictly idempotent in the mathematical sense
    # because re-applying could shorten further. But for outputs that
    # already conform, it should be a no-op.
    if once and len(once) <= 40 and re.match(r"^[a-z0-9-]+$", once):
        assert twice == once


@pytest.mark.parametrize("name", CORPUS)
def test_slug_idempotent(name: str) -> None:
    once = slug(name)
    twice = slug(once)
    if once:
        assert twice == once


# ── Bounds ─────────────────────────────────────────────────────
def test_safe_name_truncates_to_40() -> None:
    very_long = "a" * 200
    assert len(safe_name(very_long)) == 40


def test_safe_name_strips_special_chars() -> None:
    assert safe_name("!@#$%^&*()") == ""
    assert safe_name("a!b") == "ab"


def test_slug_strips_diacritics() -> None:
    assert slug("Café") == "cafe"
    assert slug("naïve") == "naive"
