"""Personal ids in the store's PUBLIC answers (§SECBATCH wave 2, 2026-10-16): the store's side of the registry's D6-606.

A developer's TEG account id is built from the developer's e-mail address (the registry's identifiers.developer_teg_did:
`did:theprotocol:<address with @ written _at_>`), and an event can carry a plain address too (an invitation). The
registry withholds both from its public reads since wave 1; the store's websocket, which every frame's console opens
without credentials through its public /ws/events lane, still streamed them. This module is the same rule for the
store's public answers: an e-mail-derived account id becomes `account:<16 hex>`, an HMAC-SHA256 that is stable on this
store and can neither be turned back into the address nor tested against a guessed one (a plain hash of an address
can), and an address becomes "[address withheld]". Stored events are never changed: the ledger and its authenticated
readers keep the real ids.

The key is the store's INTERNAL_API_KEY (every worker of a store holds the same one, so an account has one public id per
store); a store without a usable key uses a random key per process, never an unkeyed hash. SEC-12 (2026-10-17): the
frame's registry keys its own public id (identifiers.public_account_id) with this same key, which it presents on every
event it writes here (its EVENT_STORE_API_KEY), so an account shows one id on the registry's public reads and in this
store's public stream. Neither resolves to the account, by design; this formula and that one must stay the same.
"""
import hashlib
import hmac
import re
import secrets

_EMAIL_DERIVED_DID_RE = re.compile(r"did:theprotocol:[^\s\"<>/?#:,;()\[\]{}]*_at_[^\s\"<>/?#:,;()\[\]{}]*")
_EMAIL_ADDRESS_RE = re.compile(r"[A-Za-z0-9.!#$%&*+=?^_`{|}~'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
PUBLIC_ACCOUNT_PREFIX = "account:"
EMAIL_WITHHELD = "[address withheld]"
_MIN_KEY_LEN = 16
_PROCESS_KEY = secrets.token_bytes(32)


def _key() -> bytes:
    from . import internal_key

    current = str(internal_key._CURRENT or "")
    return current.encode() if len(current) >= _MIN_KEY_LEN else _PROCESS_KEY


def is_email_derived_account_id(account_id) -> bool:
    """True for a TEG account id built from an e-mail address: no agent DID carries `_at_`."""
    return isinstance(account_id, str) and _EMAIL_DERIVED_DID_RE.fullmatch(account_id.strip()) is not None


def carries_personal_id(value: str) -> bool:
    """True when a string holds an e-mail-derived account id or an e-mail address anywhere in it."""
    return isinstance(value, str) and bool(
        ("_at_" in value and _EMAIL_DERIVED_DID_RE.search(value)) or ("@" in value and _EMAIL_ADDRESS_RE.search(value))
    )


def public_account_id(account_id: str) -> str:
    mac = hmac.new(_key(), b"public-account-id\x00" + account_id.strip().encode(), hashlib.sha256).hexdigest()
    return f"{PUBLIC_ACCOUNT_PREFIX}{mac[:16]}"


def withhold_personal_ids(value):
    """A copy of a JSON value fit for a public answer: every e-mail-derived account id becomes its public_account_id and
    every e-mail address is withheld, in values and in keys, at any depth."""
    if isinstance(value, str):
        if "_at_" in value:
            value = _EMAIL_DERIVED_DID_RE.sub(lambda m: public_account_id(m.group(0)), value)
        if "@" in value:
            value = _EMAIL_ADDRESS_RE.sub(EMAIL_WITHHELD, value)
        return value
    if isinstance(value, dict):
        return {withhold_personal_ids(k): withhold_personal_ids(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [withhold_personal_ids(v) for v in value]
    return value
