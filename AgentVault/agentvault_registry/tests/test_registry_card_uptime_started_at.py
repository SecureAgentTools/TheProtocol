"""§DOCSFIX CB-397: federation.uptime_started_at never falls back to a fixed date.

With UPTIME_STARTED_AT unset the card published 2026-03-18T00:00:00+00:00, the former network's founding date: EU and
ASIA, founded 2026-09-07, claimed to have been up six months before either existed (the founded_at fallback had been
fixed for the same reason, test_registry_card_founded_licence.py). Unset, it is now the registry's own founding date
(its first account, the same derivation as identity.founded_at), and null on a registry with no account.
"""
import datetime

import pytest

from agentvault_registry.services import frame_policy as fp
from agentvault_registry.services import registry_card_builder as rcb

LITERAL = "2026-03-18T00:00:00+00:00"


class _Result:
    def __init__(self, first):
        self._first = first

    def scalar(self):
        return 0                      # active peer count

    def all(self):
        return []                     # trust domains

    def scalar_one_or_none(self):
        return self._first            # the first account's created_at


class _Db:
    def __init__(self, first):
        self.first = first

    async def execute(self, _stmt):
        return _Result(self.first)


def _policy():
    return fp.ResolvedPolicy(doc=fp.resolve(None), version=0, source="factory_default", _row_json=None)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(rcb, "_FOUNDED_AT_CACHE", None)
    monkeypatch.delenv("UPTIME_STARTED_AT", raising=False)
    monkeypatch.delenv("RC_PUBLISH_PEER_ROSTER", raising=False)


async def test_unset_it_is_the_registrys_own_founding_date():
    block = await rcb._build_federation_block(_Db(datetime.datetime(2026, 9, 7, 6, 51, 12)), _policy())
    assert block["uptime_started_at"] == "2026-09-07T06:51:12+00:00"


async def test_a_registry_with_no_account_publishes_none_rather_than_a_date():
    block = await rcb._build_federation_block(_Db(None), _policy())
    assert block["uptime_started_at"] is None


async def test_the_configured_date_wins(monkeypatch):
    monkeypatch.setenv("UPTIME_STARTED_AT", "2026-09-08T00:00:00+00:00")
    block = await rcb._build_federation_block(_Db(datetime.datetime(2026, 9, 7)), _policy())
    assert block["uptime_started_at"] == "2026-09-08T00:00:00+00:00"


def test_the_builder_holds_no_fixed_uptime_date():
    import inspect
    assert LITERAL not in inspect.getsource(rcb._build_federation_block)
