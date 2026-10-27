"""Shared outbound-mail identity for provisioned nodes: frames AND cloud operators.

ONE sender for every node we host, resolved from the provisioning registry's own
environment. No credential is ever typed per node, and rotating the token is one
place instead of N.

Three rules this module exists to enforce, all learned the hard way:

1. **A node never verifies email without a usable way to send it.** It must never
   be provisioned `verify=true, send=none`. That is the §OPGUIDE-2 lockout, found
   live on **14 cloud operators** on 2026-08-01: verification required (the
   `REQUIRE_EMAIL_VERIFICATION` default is True), mail pointed at
   `smtp.example.com`, login blocked for unverified developers, so every
   self-registered account was permanently dead and the only remedy
   (`POST /admin/developers/{id}/force-email-verify`) exists in no frontend.

2. **A submission token inside a container whose admin is somebody else is a
   credential we have handed away** (PART 11b). `first_party=False` is not a
   hint, it is a refusal to write the secret. Such a node sends by *asking its
   parent to send* — see the `relay` posture below.

3. **Registration gating is an INDEPENDENT axis from mail.** Rule 1 says
   verification needs a send path; it does not say invite codes and mail are
   alternatives. A node can perfectly well require an invitation AND verify the
   address it was invited at — that is exactly the posture the two handed-over
   nodes run. Conflating the two is why this module originally hardcoded
   `invites = not mail`, which could not express the policy we actually wanted.

Three postures, and only three, so the lockout stays unrepresentable:

    direct  MAIL_* credentials, verification on   — first-party, holds the token
    relay   MAIL_RELAY_*, no token, verification on — handed-over, parent sends
    none    no send path at all, verification OFF, invite codes forced on

Config on the PROVISIONING registry (all optional; absence just means
"no shared relay", which is a supported, safe state):

    OPERATOR_MAIL_SERVER      e.g. smtp.protonmail.ch
    OPERATOR_MAIL_PORT        default 587
    OPERATOR_MAIL_USERNAME    the submission identity
    OPERATOR_MAIL_PASSWORD    the submission token
    OPERATOR_MAIL_FROM        e.g. noreply@theprotocol.cloud
    OPERATOR_MAIL_FROM_NAME   brand prefix, default "TheProtocol"
    OPERATOR_MAIL_STARTTLS    default True
    OPERATOR_MAIL_SSL_TLS     default False
    OPERATOR_MAIL_HANDED_OVER comma-separated node slugs that never get the token

`MAIL_FROM` is deliberately shared while `MAIL_FROM_NAME` is per node, so a
recipient can tell which registry mailed them without us minting an address per
operator.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Fields without which a relay cannot work. PORT / FROM_NAME / TLS have
# defaults; these four do not, because guessing any of them produces a sender
# that renders correctly in the UI and bounces at the relay.
_REQUIRED = ("server", "username", "password", "from_addr")


def shared_identity() -> Optional[dict]:
    """The shared first-party relay, or None if it is not fully configured.

    Returns None for "absent" AND for "half-configured", and logs a warning in
    the second case: a partial relay is the dishonest-UI failure mode, never a
    usable one.
    """
    ident = {
        "server": (os.getenv("OPERATOR_MAIL_SERVER") or "").strip(),
        "port": (os.getenv("OPERATOR_MAIL_PORT") or "587").strip(),
        "username": (os.getenv("OPERATOR_MAIL_USERNAME") or "").strip(),
        "password": (os.getenv("OPERATOR_MAIL_PASSWORD") or "").strip(),
        "from_addr": (os.getenv("OPERATOR_MAIL_FROM") or "").strip(),
        "from_name": (os.getenv("OPERATOR_MAIL_FROM_NAME") or "TheProtocol").strip(),
        "starttls": (os.getenv("OPERATOR_MAIL_STARTTLS") or "True").strip(),
        "ssl_tls": (os.getenv("OPERATOR_MAIL_SSL_TLS") or "False").strip(),
    }
    present = [k for k in _REQUIRED if ident[k]]
    if not present:
        return None
    if len(present) != len(_REQUIRED):
        missing = sorted(set(_REQUIRED) - set(present))
        logger.warning(
            "[operator-mail] shared relay is HALF-CONFIGURED (missing: %s). Treating as "
            "absent; provisioned nodes will use the invite-code model instead of a relay "
            "that would bounce.",
            ",".join("OPERATOR_MAIL_" + m.replace("from_addr", "from").upper() for m in missing),
        )
        return None
    return ident


def relay_target(relay: Optional[dict] = None) -> Optional[dict]:
    """The parent-relay target for a node that must not hold the token.

    `relay` is `{"url": ..., "license": ...}`. Both halves are required: a URL
    with no credential authenticates as nobody and every send 401s, which is the
    same dishonest-UI failure as a half-configured SMTP block. Absent or partial
    both read as "no relay", loudly in the partial case.
    """
    if not relay:
        return None
    url = str(relay.get("url") or "").strip().rstrip("/")
    lic = str(relay.get("license") or "").strip()
    if url and lic:
        return {"url": url, "license": lic}
    if url or lic:
        logger.warning(
            "[operator-mail] parent relay is HALF-CONFIGURED (have %s, missing %s). "
            "Treating as absent rather than emitting a relay whose every send would 401.",
            "url" if url else "license",
            "license" if url else "url",
        )
    return None


def provisioned_relay(slug: str) -> Optional[dict]:
    """Parent-relay config for a named node, from the PROVISIONING registry's env.

        OPERATOR_MAIL_RELAY_PARENT_URL   public base URL of this parent
        OPERATOR_MAIL_RELAY_LICENSES     {"<slug>": "tp_fed_..."}

    The license is deliberately PER NODE, not shared. The parent binds each caller
    to its own base URL when it builds links, so one license across several nodes
    would collapse them into a single identity and break that binding — and it
    would make revoking one node's relay revoke everyone's.

    Returns None when this node has no entry, which is not an error: the caller
    then lands in the `none` posture (invite codes, verification off), i.e. exactly
    the safe behaviour that shipped before any relay existed.
    """
    parent = (os.getenv("OPERATOR_MAIL_RELAY_PARENT_URL") or "").strip()
    raw = (os.getenv("OPERATOR_MAIL_RELAY_LICENSES") or "").strip()
    if not parent or not raw:
        return None
    try:
        licenses = json.loads(raw)
        if not isinstance(licenses, dict):
            raise ValueError("OPERATOR_MAIL_RELAY_LICENSES must be a JSON object")
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[operator-mail] OPERATOR_MAIL_RELAY_LICENSES is not parseable (%s) — no node "
            "gets a relay. Refusing beats guessing which node a malformed map meant.",
            exc,
        )
        return None
    key = (slug or "").strip().lower()
    lic = licenses.get(key) or licenses.get(slug or "")
    if not lic:
        return None
    return {"url": parent, "license": str(lic).strip()}


def resolve_posture(
    *,
    first_party: bool,
    relay: Optional[dict] = None,
    override: Optional[dict] = None,
) -> tuple[str, Optional[dict]]:
    """(posture_name, payload) for a node. Single source of truth for the branch.

    A handed-over node is offered the shared token by NOBODY: `first_party=False`
    suppresses `shared_identity()` entirely, and only an explicit `override`
    (the node's OWN credential) or a parent `relay` can give it a send path.
    """
    ident = override or (shared_identity() if first_party else None)
    if ident:
        return "direct", ident
    target = relay_target(relay)
    if target:
        return "relay", target
    return "none", None


def mail_env_lines(
    display_name: str,
    *,
    first_party: bool,
    invite_required: Optional[bool] = None,
    relay: Optional[dict] = None,
    override: Optional[dict] = None,
) -> list[str]:
    """Env-file lines giving a node a coherent mail posture. Never half-configured.

    `display_name`     human label for MAIL_FROM_NAME (e.g. "Berlin", "Frame-B").
    `first_party`      False for any node whose admin credential is held outside
                       this org. Such a node NEVER receives the token.
    `invite_required`  gate registration behind invite codes. INDEPENDENT of the
                       mail posture (rule 3). None => default by trust: open for
                       first-party, invite-only for handed-over.
    `relay`            `{"url", "license"}` parent relay, for a node that may not
                       hold the token but must still send.
    `override`         per-node SMTP identity (same keys as `shared_identity()`),
                       used when a node brings its own mail.

    Exactly one of three postures is emitted, so the §OPGUIDE-2 lockout is
    unrepresentable by construction:

      direct -> MAIL_* set,             REQUIRE_EMAIL_VERIFICATION=true
      relay  -> MAIL_RELAY_* set,       REQUIRE_EMAIL_VERIFICATION=true
      none   -> nothing,                REQUIRE_EMAIL_VERIFICATION=false
    """
    kind, payload = resolve_posture(first_party=first_party, relay=relay, override=override)

    # Default gating by trust, overridable per node. A handed-over registry is
    # not open to the internet unless someone says so explicitly.
    invites = (not first_party) if invite_required is None else bool(invite_required)

    if kind == "none":
        why = (
            "handed-over node, token deliberately withheld and no parent relay given"
            if not first_party
            else "no shared relay configured"
        )
        # Invite codes are FORCED here, not defaulted. With verification off this
        # is the only remaining gate; honouring invite_required=False would leave
        # the node open to the internet with no barrier at all.
        return [
            "",
            f"# Mail: NONE ({why}).",
            "# Registration is gated by invite codes INSTEAD of email verification, so no",
            "# account can be created that then cannot be verified (the §OPGUIDE-2 lockout).",
            "# Invite codes are forced on: with verification off they are the only gate left.",
            "REQUIRE_EMAIL_VERIFICATION=false",
            "BETA_INVITE_REQUIRED=true",
        ]

    if kind == "relay":
        return [
            "",
            "# Mail: PARENT RELAY. This node holds NO submission token (PART 11b) — it asks",
            "# its parent to send. The parent owns the From: address, renders from its own",
            "# template allowlist, rate-limits per caller and audits every send, so the",
            "# credential below can request a verification mail and nothing else.",
            f"MAIL_RELAY_PARENT_URL={payload['url']}",
            f"MAIL_RELAY_LICENSE={payload['license']}",
            "REQUIRE_EMAIL_VERIFICATION=true",
            f"BETA_INVITE_REQUIRED={'true' if invites else 'false'}",
        ]

    safe_label = str(display_name or "").replace('"', "").strip() or "TheProtocol"
    from_name = payload.get("from_name") or "TheProtocol"
    if safe_label.lower() not in from_name.lower():
        from_name = f"{from_name} - {safe_label}"

    return [
        "",
        "# Mail: direct SMTP via the shared first-party sender. One token to rotate.",
        "# MAIL_FROM is shared across nodes; MAIL_FROM_NAME identifies which one wrote.",
        f"MAIL_SERVER={payload['server']}",
        f"MAIL_PORT={payload.get('port') or '587'}",
        f"MAIL_USERNAME={payload['username']}",
        f"MAIL_PASSWORD={payload['password']}",
        f"MAIL_FROM={payload['from_addr']}",
        f'MAIL_FROM_NAME="{from_name}"',
        f"MAIL_STARTTLS={payload.get('starttls') or 'True'}",
        f"MAIL_SSL_TLS={payload.get('ssl_tls') or 'False'}",
        "REQUIRE_EMAIL_VERIFICATION=true",
        f"BETA_INVITE_REQUIRED={'true' if invites else 'false'}",
    ]


def posture(
    *,
    first_party: bool,
    relay: Optional[dict] = None,
    override: Optional[dict] = None,
) -> str:
    """One-line posture for logs and preflight output, without leaking any secret."""
    kind, payload = resolve_posture(first_party=first_party, relay=relay, override=override)
    if kind == "direct":
        return f"direct {payload['from_addr']} via {payload['server']}"
    if kind == "relay":
        return f"relay via parent {payload['url']} (no local token)"
    return "invite-codes (no send path)"
