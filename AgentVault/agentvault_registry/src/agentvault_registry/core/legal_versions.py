"""The version and dates of the published legal set, in one place.

§LEGALKIT (2026-09-20). Three copies of the Terms version used to exist (`config.TOS_VERSION`,
`fiat_onramp.CURRENT_TOS_VERSION`, `BecomeABacker.vue`) and the effective date lived only in the
frontend content module. Every reader now asks here; the frontend asks `GET /api/v1/legal/config`.

  DOCUMENTS_VERSION   the version stamped on every page of the suite
  PUBLISHED           the day this version was put on the platform (ISO date)
  EFFECTIVE           the day it takes effect for existing users (Terms § 10.2: at least 30 days after
                      publication for a material change; new registrations accept it at once)
"""
from __future__ import annotations

from ..config import settings

DOCUMENTS_VERSION = "2.5"
PUBLISHED = "2026-10-04"
EFFECTIVE = "2026-11-03"
EFFECTIVE_LABEL = "3 November 2026"

# Set 2.4 (2026-09-30) changed only the Federation Operator Terms (1.2) materially: DOCUMENTS_VERSION moved, so every
# account holding an operator relationship accepts them again; the Terms stay at 2.3 and are not asked again.
# The Terms carry their own version so the acceptance record names the document a person read.
TOS_VERSION = settings.TOS_VERSION

# Set 2.5 (2026-10-04) changed only the Terms (2.4: membership instead of staking, the commons, AGORA in the frame's
# Unit): every account accepts the Terms again at its next login. The Federation Operator Terms did not change, so an
# operator's acceptance stays keyed to the set they last changed in (2.4) and is not asked again. Move this only when
# the Operator Terms themselves change.
OPERATOR_TERMS_SET_VERSION = "2.4"

# Documents that ask for an acceptance, and the version each is currently served at.
ACCEPTABLE_DOCUMENTS = {
    "terms": TOS_VERSION,
    "operators": OPERATOR_TERMS_SET_VERSION,
    "age18": "1",
}


def current_version(document: str) -> str | None:
    return ACCEPTABLE_DOCUMENTS.get(document)
