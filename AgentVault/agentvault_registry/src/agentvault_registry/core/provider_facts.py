"""Provider facts: who legally stands behind THIS registry, as data.

§LEGALKIT (2026-09-20). The legal pages, the email footer, security.txt and the OpenAPI metadata used to
carry the operator's name, address and mailboxes as literals in source, translated nine times over in the
locale bundles. Every registry built from that source, including a stranger's frame stood up from the kit,
served OUR imprint as its own; and the day the operator moves, every literal has to be found again.

One object, read from the environment, rendered everywhere:

    LEGAL_SUITE_MODE            theprotocol or operator   (default: operator)
    LEGAL_PROVIDER_LEGAL_NAME   the natural or legal person
    LEGAL_PROVIDER_LEGAL_FORM   e.g. "sole proprietor" / "Einzelunternehmer" / "GmbH"
    LEGAL_PROVIDER_TRADING_AS   e.g. "The Protocol"
    LEGAL_PROVIDER_STREET · LEGAL_PROVIDER_POSTAL_CODE · LEGAL_PROVIDER_CITY · LEGAL_PROVIDER_COUNTRY
    LEGAL_PROVIDER_COUNTRY_CODE ISO 3166-1 alpha-2 ("DE")
    LEGAL_CONTACT_EMAIL · LEGAL_PRIVACY_EMAIL · LEGAL_SECURITY_EMAIL · LEGAL_SUPPORT_EMAIL
    LEGAL_SUPERVISORY_AUTHORITY the data protection authority, name and address, one line
    LEGAL_GOVERNING_LAW         e.g. "Germany"
    LEGAL_VENUE                 e.g. "Sometown, Examplia"
    LEGAL_BUSINESS_DAYS         e.g. "Monday to Friday, public holidays of the seat excluded"
    LEGAL_VAT_ID                optional; LEGAL_SMALL_BUSINESS=true prints the § 19 UStG note instead
    LEGAL_EDITORIAL_PERSON      § 18 (2) MStV person; defaults to the legal name
    LEGAL_PROVIDER_PHONE        optional; the imprint prints it as the second direct channel beside the email
                                (§ 5 (1) no. 2 DDG); unset, the imprint carries no phone line (never a placeholder)
    LEGAL_TERMS_URL · LEGAL_PRIVACY_URL · LEGAL_SECURITY_POLICY_URL
                                operator mode: where the operator's own documents live (links)

Two modes, no third:

  * ``theprotocol``: the frame is run by the author of the software and serves the full legal suite with
    these facts rendered into it. The facts are REQUIRED; a frame that declares this mode without them
    refuses to boot (``validate_at_boot``), because a legal page that invents a provider is worse than a
    page that says the provider has not published one.
  * ``operator``: the frame is run by someone else. The console renders the operator's facts and links
    where supplied, and an honest "not yet published" page where not. It never renders the suite's
    contractual texts as the operator's own, and it never falls back to the author's details.

There is deliberately NO literal default for any personal detail in this module: the export gate refuses
them, and a stranger's frame must not be able to look like ours by accident.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict
from typing import Optional

logger = logging.getLogger(__name__)

MODE_THEPROTOCOL = "theprotocol"
MODE_OPERATOR = "operator"

# The facts a `theprotocol` frame cannot be without (an imprint under § 5 DDG needs all of them).
REQUIRED_IN_THEPROTOCOL_MODE = (
    "legal_name", "street", "postal_code", "city", "country", "legal_email", "privacy_email", "security_email",
)


def _env(name: str) -> Optional[str]:
    v = os.getenv(name)
    if v is None:
        return None
    v = v.strip()
    return v or None


def _bool(name: str) -> bool:
    return (os.getenv(name, "") or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ProviderFacts:
    legal_name: Optional[str]
    legal_form: Optional[str]
    trading_as: Optional[str]
    street: Optional[str]
    postal_code: Optional[str]
    city: Optional[str]
    country: Optional[str]
    country_code: Optional[str]
    legal_email: Optional[str]
    privacy_email: Optional[str]
    security_email: Optional[str]
    support_email: Optional[str]
    supervisory_authority: Optional[str]
    governing_law: Optional[str]
    venue: Optional[str]
    business_days: Optional[str]
    vat_id: Optional[str]
    small_business: bool
    editorial_person: Optional[str]
    # §COOKIES (2026-10-02): optional, and last with a default so every existing constructor stays valid
    phone: Optional[str] = None

    @property
    def address_line(self) -> Optional[str]:
        """"Street, Postal City, Country" on one line; None while any part is missing."""
        if not (self.street and self.postal_code and self.city and self.country):
            return None
        return f"{self.street}, {self.postal_code} {self.city}, {self.country}"

    @property
    def full_line(self) -> Optional[str]:
        """The one-line identification the contracts use: name, trading-as, address."""
        if not self.legal_name:
            return None
        parts = [self.legal_name]
        if self.trading_as:
            parts.append(f'trading as "{self.trading_as}"')
        if self.address_line:
            parts.append(self.address_line)
        return ", ".join(parts)

    @property
    def address_block(self) -> Optional[str]:
        """The multi-line block an imprint prints."""
        if not (self.legal_name and self.address_line):
            return None
        lines = [self.legal_name, self.street, f"{self.postal_code} {self.city}", self.country]
        return "\n".join(str(x) for x in lines if x)

    def missing(self) -> list[str]:
        return [k for k in REQUIRED_IN_THEPROTOCOL_MODE if not getattr(self, k)]

    def as_public_dict(self) -> dict:
        d = asdict(self)
        d["address_line"] = self.address_line
        d["full_line"] = self.full_line
        d["address_block"] = self.address_block
        return d


def suite_mode() -> str:
    mode = (_env("LEGAL_SUITE_MODE") or MODE_OPERATOR).lower()
    return MODE_THEPROTOCOL if mode == MODE_THEPROTOCOL else MODE_OPERATOR


def provider_facts() -> ProviderFacts:
    """Read the facts from the environment. Never invents; every field may be None."""
    legal_name = _env("LEGAL_PROVIDER_LEGAL_NAME")
    return ProviderFacts(
        legal_name=legal_name,
        legal_form=_env("LEGAL_PROVIDER_LEGAL_FORM"),
        trading_as=_env("LEGAL_PROVIDER_TRADING_AS"),
        street=_env("LEGAL_PROVIDER_STREET"),
        postal_code=_env("LEGAL_PROVIDER_POSTAL_CODE"),
        city=_env("LEGAL_PROVIDER_CITY"),
        country=_env("LEGAL_PROVIDER_COUNTRY"),
        country_code=(_env("LEGAL_PROVIDER_COUNTRY_CODE") or "").upper() or None,
        legal_email=_env("LEGAL_CONTACT_EMAIL"),
        privacy_email=_env("LEGAL_PRIVACY_EMAIL"),
        security_email=_env("LEGAL_SECURITY_EMAIL"),
        support_email=_env("LEGAL_SUPPORT_EMAIL"),
        supervisory_authority=_env("LEGAL_SUPERVISORY_AUTHORITY"),
        governing_law=_env("LEGAL_GOVERNING_LAW"),
        venue=_env("LEGAL_VENUE"),
        business_days=_env("LEGAL_BUSINESS_DAYS"),
        vat_id=_env("LEGAL_VAT_ID"),
        small_business=_bool("LEGAL_SMALL_BUSINESS"),
        editorial_person=_env("LEGAL_EDITORIAL_PERSON") or legal_name,
        phone=_env("LEGAL_PROVIDER_PHONE"),
    )


def operator_links() -> dict:
    """Operator mode: where the operator keeps the documents the software does not write for them."""
    return {
        "terms_url": _env("LEGAL_TERMS_URL"),
        "privacy_url": _env("LEGAL_PRIVACY_URL"),
        "security_policy_url": _env("LEGAL_SECURITY_POLICY_URL"),
    }


def has_provider_identity(facts: Optional[ProviderFacts] = None) -> bool:
    """True when the frame can say who runs it (name + a way to reach them)."""
    f = facts or provider_facts()
    return bool(f.legal_name and (f.legal_email or f.support_email))


def validate_at_boot() -> None:
    """A `theprotocol` frame without its facts must not come up looking like an anonymous one.

    Raised at import of main so the recreate fails in the health loop and the roll driver rolls back,
    rather than the frame serving legal pages with unresolved placeholders for the life of the image.
    """
    if suite_mode() != MODE_THEPROTOCOL:
        return
    missing = provider_facts().missing()
    if missing:
        raise RuntimeError(
            "the theprotocol suite mode requires the provider facts; missing: " + ", ".join(missing)
            + " (set the LEGAL_* variables in this frame's env file, or run in operator mode)"
        )


def source_code_url() -> str | None:
    """AGPL-3.0 § 13: where the users of this deployment get its Corresponding Source. SOURCE_CODE_URL names it; an
    operator who modifies the software sets it to the repository of their modified version. Unset, or anything but a
    plain http(s) URL, is None, and the console shows nothing rather than a link that leads nowhere."""
    v = (os.getenv("SOURCE_CODE_URL") or "").strip()
    if not v.startswith(("https://", "http://")) or any(c.isspace() for c in v) or len(v) > 300:
        return None
    return v


def legal_config(*, tos_version: str, documents_version: str, effective: str, published: str) -> dict:
    """The public description of this frame's legal posture, served at GET /api/v1/legal/config."""
    facts = provider_facts()
    mode = suite_mode()
    identified = has_provider_identity(facts)
    return {
        "mode": mode,
        "provider": facts.as_public_dict() if (mode == MODE_THEPROTOCOL or identified) else None,
        "provider_identified": identified,
        "operator_links": operator_links() if mode == MODE_OPERATOR else None,
        "tos_version": tos_version,
        "documents_version": documents_version,
        "effective": effective,
        "published": published,
        "source_code_url": source_code_url(),
    }
