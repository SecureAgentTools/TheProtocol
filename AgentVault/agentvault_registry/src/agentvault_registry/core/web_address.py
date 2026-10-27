"""A web address a person types for others to follow (§FESUITE 135, agentvault2-5b, 2026-10-15).

The console renders an organization's website and a developer's website and GitHub page as links that other people
press. The registry stored any string, so a "javascript:" address became a link that ran in the console's origin for
whoever pressed it (the console now guards its links, fe/views-5b and fe/desk-polish 73425f46; this refuses the
address where it is written). Only an http(s) address is stored; an empty value clears the field; None leaves it.
"""
import re
from typing import Optional

_WEB = re.compile(r"^https?://[^\s<>\"']+$", re.IGNORECASE)


def web_address_or_empty(value: Optional[str], what: str = "address") -> Optional[str]:
    """The address trimmed, '' to clear, or None (not given); anything but http(s) is refused with a sentence."""
    if value is None:
        return None
    v = value.strip()
    if v == "":
        return ""
    if not _WEB.match(v):
        raise ValueError(f"{what} must be an http:// or https:// address")
    return v
