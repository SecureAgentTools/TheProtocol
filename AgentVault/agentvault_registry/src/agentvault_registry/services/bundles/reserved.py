"""§pass51 — Reserved slug + reserved name prefix policy.

Per PLAN §17.2. Slugs in this set OR matching these prefixes are restricted
to admin_platform on publish.
"""
import re

RESERVED_SLUG_PREFIXES = (
    "official-",
    "sovereign-",
    "verified-",
    "theprotocol-",
    "tp-",
    "system-",
    "core-",
)

# Sovereign first-names (sourced from PRODUCTION_DOCS/03_SERVICES/Sovereign_Agents.md
# at autonomous-impl time 2026-05-20). Adding new sovereigns? Update this list.
RESERVED_SOVEREIGN_SLUGS = {
    "veridian", "herald", "moira", "crucible", "ozymandias",
    "gerald", "sybil", "boris", "chester", "gregory", "auditor",
}

# Name prefixes that trigger suspicion-flagged in UI but don't block (unless
# is_official=true is also requested without admin_platform)
RESERVED_NAME_PREFIXES_CASEFOLD = (
    "official ", "official-", "sovereign ", "sovereign-",
    "verified ", "verified-", "theprotocol ", "tp ",
    "veridian", "herald", "moira", "crucible", "ozymandias",
    "gerald", "sybil", "boris", "chester", "gregory", "auditor",
)

SLUG_REGEX = re.compile(r"^[a-z][a-z0-9-]{2,79}$")


def is_slug_reserved(slug: str) -> bool:
    """True if the slug requires admin_platform to publish."""
    slug = (slug or "").lower()
    if not slug:
        return False
    if slug in RESERVED_SOVEREIGN_SLUGS:
        return True
    for prefix in RESERVED_SLUG_PREFIXES:
        if slug.startswith(prefix):
            return True
    return False


def is_slug_well_formed(slug: str) -> bool:
    """True if the slug matches our format requirements."""
    return bool(slug and SLUG_REGEX.match(slug))


def name_triggers_suspicion(name: str) -> bool:
    """True if the name LOOKS like a reserved-pattern (UI flag, not a block)."""
    cf = (name or "").casefold().strip()
    return any(cf.startswith(p) for p in RESERVED_NAME_PREFIXES_CASEFOLD)
