"""§BAFIN (2026-10-01): AGORA distributions can be switched off per registry.

AGORA stays on the public test network (his decision 2026-10-01: production is a place where anyone can register and
try the platform with play credits). The one share-like feature it carries is the distribution: units paid to point
holders out of an organization's listing treasury. ESMA's guidelines on the classification of crypto-assets as
financial instruments (Rn. 22 and 23) treat votes on technical and fee matters as not share-like, and look at financial
returns such as dividends. With the switch off:

  * no distribution can be declared (both declare routes, and every caller of the service, answer 403 with
    DISTRIBUTIONS_DISABLED_SENTENCE; the code word comes first because the RFC 7807 layer stringifies);
  * the settlement worker funds no new pot; a distribution whose pot already moved to escrow is paid out to the
    end, so no units are stranded in escrow;
  * points keep their votes on the organization's platform parameters and stay tradable for units;
  * /api/v1/public/registry-config says agora_distributions_enabled, and the console hides the declare door.

    AGORA_DISTRIBUTIONS_ENABLED   default "true": a node that sets nothing is unchanged. An unknown value counts as
                                  ON (the core/legacy_surfaces.py rule); only 0/false/no/off disable.
"""
from __future__ import annotations

import os

_OFF = {"0", "false", "no", "off"}

DISTRIBUTIONS_DISABLED_SENTENCE = (
    "agora_distributions_disabled: Declaring distributions on Organization Points is not enabled on this registry "
    "(AGORA_DISTRIBUTIONS_ENABLED=false). Points carry votes on the organization's platform parameters; "
    "no distribution is declared or paid."
)


def distributions_enabled() -> bool:
    """May a distribution be declared and a new pot be funded here? Read per call; a flip takes effect on recreate."""
    v = (os.getenv("AGORA_DISTRIBUTIONS_ENABLED", "true") or "true").strip().lower()
    return v not in _OFF
