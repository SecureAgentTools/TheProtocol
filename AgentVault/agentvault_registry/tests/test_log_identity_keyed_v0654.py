"""V0654 (aq), item 23 (CodeQL #392, weak-sensitive-data-hashing): core/log_identity.email_for_log names a person in a log
line by the first character, the domain and a short tag of the whole address. The tag was an unkeyed sha256, so anyone
holding a log line could confirm a guessed address against it. It is an HMAC now, under a key derived from the
registry's own secret (API_KEY_SECRET): every worker and every restart names one person the same, and a guess can be
checked only with that secret. BASE (V0653, f8f1993fb): the tag is sha256(address)[:8].
"""
from __future__ import annotations

import hashlib
import hmac

import pytest

from agentvault_registry.core import log_identity as li

EMAIL = "m.someone@example.org"


@pytest.fixture()
def secret(monkeypatch):
    def use(value):
        if value is None:
            monkeypatch.delenv("API_KEY_SECRET", raising=False)
        else:
            monkeypatch.setenv("API_KEY_SECRET", value)
        monkeypatch.setattr(li, "_tag_key", None, raising=False)     # a restart: the key is derived again
    return use


def _tag(shown: str) -> str:
    return shown.rsplit("#", 1)[1]


def test_the_tag_is_keyed_by_the_registry_s_secret_and_not_the_bare_sha256(secret):
    secret("registry-secret-one-0123456789abcdef")
    shown = li.email_for_log(EMAIL)
    assert shown.startswith("m…@example.org #")
    key = hmac.new(b"registry-secret-one-0123456789abcdef", b"theprotocol log identity tag v1", hashlib.sha256).digest()
    assert _tag(shown) == hmac.new(key, EMAIL.encode(), hashlib.sha256).hexdigest()[:8]
    assert _tag(shown) != hashlib.sha256(EMAIL.encode()).hexdigest()[:8]      # a guess is no longer checkable


def test_one_person_reads_the_same_in_every_line_and_after_a_restart(secret):
    secret("registry-secret-one-0123456789abcdef")
    first = li.email_for_log(EMAIL)
    assert li.email_for_log("  M.Someone@Example.ORG ") == first
    secret("registry-secret-one-0123456789abcdef")                          # restarted, the same secret
    assert li.email_for_log(EMAIL) == first
    assert li.email_for_log("other@example.org") != first


def test_another_registry_s_secret_names_the_same_address_differently(secret):
    secret("registry-secret-one-0123456789abcdef")
    one = li.email_for_log(EMAIL)
    secret("registry-secret-two-0123456789abcdef")
    assert li.email_for_log(EMAIL) != one


def test_without_a_secret_a_process_keys_with_its_own_random_value(secret):
    secret(None)
    shown = li.email_for_log(EMAIL)
    assert li.email_for_log(EMAIL) == shown                                  # stable within the process
    assert _tag(shown) != hashlib.sha256(EMAIL.encode()).hexdigest()[:8]
    assert li.email_for_log("no-at-sign").startswith("email:#") and li.email_for_log(None) == "email:none"
