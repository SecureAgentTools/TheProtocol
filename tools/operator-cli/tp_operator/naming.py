"""Operator-name normalization primitives — must stay byte-identical to mainframe.

Two primitives, used in distinct call sites:

  _safe_name(n)  — directory naming, docker_registry_username derivation
                   Source: cloud_provisioner.py:95-97
                   Algorithm: re.sub(r'[^a-z0-9-]', '', name.lower())[:40]

  _slug(n)       — federation peer-name matching, peer_registries.name lookup
                   Source: teg_integration.py:42-43
                   Algorithm: unicodedata.NFKD → ASCII-ignore → lower
                              → spaces-to-hyphen → strip-hyphens

For input strings without spaces or non-ASCII chars, the two converge.
Diverge for "Sandbox Alpha", "São Paulo", "My Registry" etc.

If parity ever drifts from mainframe, the CLI build MUST fail. The parity
property test enforces this — see tests/property/test_naming_parity.py.

Reference: PRODUCTION_DOCS/ROADMAP/Operator_CLI_Strategy.md §4.1.1 + Appendix D.
"""
import re
import unicodedata


def safe_name(name: str) -> str:
    """Mirror cloud_provisioner._safe_name (verbatim semantics).

    Examples:
        safe_name("op-london")     == "op-london"
        safe_name("Sandbox Alpha") == "sandboxalpha"
        safe_name("São Paulo")     == "sopaulo"
        safe_name("My Registry")   == "myregistry"
    """
    return re.sub(r"[^a-z0-9-]", "", name.lower())[:40]


def slug(name: str) -> str:
    """Mirror teg_integration._slug (verbatim semantics).

    Examples:
        slug("op-london")     == "op-london"
        slug("Sandbox Alpha") == "sandbox-alpha"
        slug("São Paulo")     == "sao-paulo"
        slug("My Registry")   == "my-registry"
    """
    return (
        unicodedata.normalize("NFKD", name)
        .encode("ASCII", "ignore")
        .decode("ASCII")
        .lower()
        .replace(" ", "-")
        .strip("-")
    )
