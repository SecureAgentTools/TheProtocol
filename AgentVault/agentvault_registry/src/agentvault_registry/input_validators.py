"""
Input Validation Utilities — S10 Security Audit
================================================
Central validation for DID formats, HTML sanitization, URL safety,
LIKE wildcard escaping, and password strength.

Used by Pydantic schemas and routers across the registry.
"""

import asyncio
import re
import ipaddress
import socket
from urllib.parse import urlparse
from typing import List


# ---------------------------------------------------------------------------
# DID FORMAT VALIDATION
# ---------------------------------------------------------------------------

# Accepted DID prefixes: did:theprotocol:<uuid> or did:cos:<hex> (legacy)
# Also: system DIDs like did:theprotocol:teg_system_treasury
DID_PATTERN = re.compile(
    r"^did:(theprotocol|cos):(?:[a-z0-9][a-z0-9.-]{0,61}[a-z0-9]:)?[a-z0-9_][a-z0-9_\-]{2,80}$"
)

# Pattern string for Pydantic Field(pattern=...)
DID_PATTERN_STR = r"^did:(theprotocol|cos):(?:[a-z0-9][a-z0-9.-]{0,61}[a-z0-9]:)?[a-z0-9_][a-z0-9_\-]{2,80}$"


def validate_did(did: str) -> str:
    """Validate a DID string. Returns the DID or raises ValueError."""
    if not did or not DID_PATTERN.match(did):
        raise ValueError(
            f"Invalid DID format: must match did:(theprotocol|cos):<identifier>. Got: {did[:60]}"
        )
    return did


# ---------------------------------------------------------------------------
# HTML / XSS SANITIZATION
# ---------------------------------------------------------------------------

# Characters that enable HTML injection
_HTML_TAG_RE = re.compile(r"<[^>]*>")

# Dangerous patterns beyond simple tags
_DANGEROUS_PATTERNS = [
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),  # onerror=, onload=, etc.
    re.compile(r"data\s*:\s*text/html", re.IGNORECASE),
]

# Control characters (except \n, \r, \t which are legitimate)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str) -> str:
    """
    Strip HTML tags and dangerous patterns from user text input.
    Preserves legitimate text content. Used for stored fields like
    names, descriptions, proposals, disputes.
    """
    if not text:
        return text
    # Strip control characters
    text = _CONTROL_CHAR_RE.sub("", text)
    # Strip HTML tags
    text = _HTML_TAG_RE.sub("", text)
    return text


def contains_dangerous_content(text: str) -> bool:
    """Check if text contains XSS-dangerous patterns."""
    if not text:
        return False
    if _HTML_TAG_RE.search(text):
        return True
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(text):
            return True
    return False


def validate_safe_text(text: str, field_name: str = "field") -> str:
    """Validate that text doesn't contain HTML/script injection. Raises ValueError if dangerous."""
    if contains_dangerous_content(text):
        raise ValueError(
            f"{field_name} contains potentially dangerous content (HTML tags or script patterns are not allowed)"
        )
    # Strip control characters regardless
    return _CONTROL_CHAR_RE.sub("", text)


# ---------------------------------------------------------------------------
# URL SAFETY (SSRF PREVENTION)
# ---------------------------------------------------------------------------

# Private/reserved IP ranges
_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 private
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]

# Cloud metadata endpoints
_BLOCKED_HOSTNAMES = {
    "metadata.google.internal",
    "metadata.google",
    "169.254.169.254",
}


def _is_internal_address(ip) -> bool:
    """True for any address this registry must never call on a caller's behalf: private, loopback, link-local,
    multicast, reserved, unspecified or otherwise not globally routable, including an IPv4 address carried inside
    an IPv6 one (IPv4-mapped, 6to4)."""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.sixtofour is not None:
            ip = ip.sixtofour
    if any(ip in net for net in _PRIVATE_RANGES if net.version == ip.version):
        return True
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified or not ip.is_global)


def _refuse_internal_resolution(hostname: str, port: int) -> None:
    """D6-760 (2026-10-16): resolve the host and refuse when ANY address it resolves to is internal.

    A literal-host check alone let a name that resolves to an internal address through (a public name pointed
    at 127.0.0.1, or a name the registry's own resolver maps to a service on its network). A host that does not
    resolve at all is not refused here: nothing can be reached through it now, and every delivery resolves it
    itself and connects only to an address it checked (webhook_target_addresses)."""
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except UnicodeError:
        raise ValueError("URL host is not a valid hostname")
    except (socket.gaierror, OSError):
        return
    for info in infos:
        addr = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_internal_address(ip):
            raise ValueError("URL host resolves to a private or internal address")


def validate_webhook_url(url: str, *, resolve: bool = True) -> str:
    """
    Validate a webhook/callback URL is safe to call.
    Must be HTTPS, no private IPs, no metadata endpoints.
    Returns the URL or raises ValueError.

    resolve=True (the default) also resolves the host and refuses it when any address it resolves to is
    internal (D6-760). The lookup blocks: an async caller uses avalidate_webhook_url. resolve=False keeps the
    literal checks only, for callers whose URL is bound to an allowlist of federation peers (a peer may sit on
    the registry's own network) or that the registry never calls (a repository URL).
    """
    if not url or not isinstance(url, str):
        raise ValueError("URL is required")

    try:
        parsed = urlparse(url)
        port = parsed.port
    except Exception:
        raise ValueError("Invalid URL format")

    # Must be HTTPS (allow HTTP only for known internal federation peers)
    if parsed.scheme not in ("https", "http"):
        raise ValueError("URL must use HTTPS scheme")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")

    # Block cloud metadata endpoints
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise ValueError("URL points to a blocked endpoint")

    # Check for private/reserved IPs
    try:
        ip = ipaddress.ip_address(hostname.split("%", 1)[0])
    except ValueError:
        ip = None  # a name, not an address literal
    if ip is not None and _is_internal_address(ip):
        raise ValueError("URL must not point to a private/reserved IP address")

    if resolve and ip is None:
        _refuse_internal_resolution(hostname, port or (443 if parsed.scheme == "https" else 80))

    return url


async def avalidate_webhook_url(url: str) -> str:
    """validate_webhook_url with the host lookup off the event loop (for async routes)."""
    return await asyncio.to_thread(validate_webhook_url, url)


class WebhookHostUnresolved(ValueError):
    """The webhook's host resolves to no address right now: there is nothing to deliver to (not a refusal)."""


def webhook_target_addresses(url: str) -> List[str]:
    """SEC-14 (2026-10-17): the addresses a delivery to the stored webhook URL `url` may connect to, now.

    Every address the host resolves to, each checked as validate_webhook_url checks (D6-760), in the resolver's order;
    [] for a host written as an address (validated, and connected to as written). Raises ValueError when the URL may
    not be called: the literal checks, or ANY address internal; WebhookHostUnresolved when the host resolves to
    nothing. The delivery connects only to one of these addresses (services/webhook_service): letting the HTTP client
    look the name up again would let a name whose answer changes between the two lookups reach an address nobody
    checked. A URL stored before D6-760, or a name whose address changed since it was stored, is refused at the
    moment of sending, not only when it was registered."""
    validate_webhook_url(url, resolve=False)
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    try:
        ipaddress.ip_address(hostname.split("%", 1)[0])
        return []
    except ValueError:
        pass
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except UnicodeError:
        raise ValueError("URL host is not a valid hostname")
    except (socket.gaierror, OSError):
        raise WebhookHostUnresolved("the URL's host resolves to no address right now")
    addresses: List[str] = []
    for info in infos:
        addr = str(info[4][0]).split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if _is_internal_address(ip):
            raise ValueError("URL host resolves to a private or internal address")
        if addr not in addresses:
            addresses.append(addr)
    if not addresses:
        raise WebhookHostUnresolved("the URL's host resolves to no address right now")
    return addresses


async def awebhook_target_addresses(url: str) -> List[str]:
    """webhook_target_addresses with the host lookup off the event loop."""
    return await asyncio.to_thread(webhook_target_addresses, url)


# ---------------------------------------------------------------------------
# REPO / BRANCH / PR URL VALIDATION (Contracts B5/X18)
# ---------------------------------------------------------------------------

# Git-safe branch name: alphanumeric + . _ - / ; cannot start with - or be empty
_BRANCH_PATTERN = re.compile(r"^[A-Za-z0-9._/][A-Za-z0-9._\-/]{0,199}$")


def validate_repo_url(url: str) -> str:
    """
    Validate a Git repository URL.

    Allows http/https schemes. Rejects javascript:, file://, data:, etc.
    Rejects private IPs / cloud metadata endpoints (uses validate_webhook_url
    SSRF rules underneath).

    Used by RUC contract source_code_repo_url + pr_url fields.
    """
    if not url:
        raise ValueError("Repository URL is required")

    # validate_webhook_url enforces http/https + SSRF prevention (the literal checks: the registry stores a
    # repository URL and never calls it, so it does not resolve the host)
    return validate_webhook_url(url, resolve=False)


def validate_branch_name(branch: str) -> str:
    """
    Validate a Git branch name. Reject empty + control chars + shell metachars.

    Used by RUC contract source_code_branch field.
    """
    if not branch or not branch.strip():
        raise ValueError("Branch name cannot be empty")
    branch = branch.strip()
    if not _BRANCH_PATTERN.match(branch):
        raise ValueError(
            "Branch name must be alphanumeric (with . _ - /), max 200 chars, "
            "and cannot start with hyphen"
        )
    return branch


def validate_federation_callback_url(url: str, allowed_base_urls: list[str]) -> str:
    """
    Validate a federation callback URL against known peer registry base URLs.
    The callback must be under one of the registered peer base URLs.
    """
    if not url:
        raise ValueError("Callback URL is required")

    # First do basic URL safety check (literal: the allowlist of peer base URLs below is the authority,
    # and a federation peer may sit on the registry's own network)
    validate_webhook_url(url, resolve=False)

    # Check that the callback URL starts with a known peer base URL
    url_lower = url.lower().rstrip("/")
    for base_url in allowed_base_urls:
        base_lower = base_url.lower().rstrip("/")
        if url_lower.startswith(base_lower):
            return url

    raise ValueError(
        "Callback URL must be under a registered peer registry base URL"
    )


# ---------------------------------------------------------------------------
# LIKE WILDCARD ESCAPING
# ---------------------------------------------------------------------------

def escape_like(pattern: str) -> str:
    """
    Escape SQL LIKE wildcard characters (% and _) in user input.
    Use with SQLAlchemy .ilike() to prevent pattern injection.
    """
    return (
        pattern
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


# ---------------------------------------------------------------------------
# PASSWORD STRENGTH
# ---------------------------------------------------------------------------

def validate_password_strength(password: str) -> str:
    """
    Validate password meets minimum strength requirements.
    Must match frontend RegisterRefined.vue requirements:
    12+ chars, uppercase, lowercase, digit, special character.
    """
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long")
    if len(password) > 128:
        raise ValueError("Password must not exceed 128 characters")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Password must contain at least one uppercase letter")
    if not re.search(r"[a-z]", password):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"[0-9]", password):
        raise ValueError("Password must contain at least one digit")
    if not re.search(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>/?~`]", password):
        raise ValueError("Password must contain at least one special character")
    return password
