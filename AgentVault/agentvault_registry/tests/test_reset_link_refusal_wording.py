"""§FESUITE (V0594): the second use of a mailed reset link is refused in words that fit it.

The token is cleared on a successful reset, so a used link cannot be told from an unknown one and both are refused
alike; the sentence said "Reset token is invalid or has expired." of a link the person had just used (lifecycle 85's
second-use step, sbx-beta and the sandbox operators). It names a link, says it may have been used already, and says
what to do. The route reads no token here: an unknown one, the same refusal a used one gets.
"""
import asyncio

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import auth_secure


def test_a_used_or_unknown_reset_link_is_refused_in_words_that_fit(monkeypatch):
    async def nobody(_db, _token):
        return None

    monkeypatch.setattr(auth_secure, "get_developer_by_reset_token", nobody)
    fn = getattr(auth_secure.reset_password_via_email, "__wrapped__", auth_secure.reset_password_via_email)
    with pytest.raises(HTTPException) as e:
        asyncio.run(fn(request=None, token="used-token", new_password="Aa1!aaaaaaaaaa", db=None))
    assert e.value.status_code == 400
    said = str(e.value.detail)
    assert "already used" in said and "expired" in said and "Request a new one" in said, said
    assert "token" not in said.lower(), "a person holds a link, not a token"
