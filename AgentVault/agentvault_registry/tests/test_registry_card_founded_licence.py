"""The registry card's founding date and software licence row (2026-09-30).

Before: every frame whose operator had not stated identity.founded_at published the network's founding date
(2026-03-18), so ASIA's card claimed to be six months older than ASIA; and EU's and ASIA's cards left the
software licence row empty because their operators' commitments block named other things but not the licence.
After: the founding date is the registry's own first account, and the licence row is filled per key.
"""
import datetime

import pytest

from agentvault_registry.services import registry_card_builder as rcb


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    def __init__(self, value):
        self.value = value
        self.calls = 0

    async def execute(self, _stmt):
        self.calls += 1
        return _Result(self.value)


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(rcb, "_FOUNDED_AT_CACHE", None)


async def test_the_first_account_dates_the_registry_and_is_read_once():
    db = _FakeDb(datetime.datetime(2026, 9, 7, 6, 51, 12))  # naive, as the column may hand it back
    first = await rcb._founded_at_fallback(db)
    assert first == "2026-09-07T06:51:12+00:00"
    assert await rcb._founded_at_fallback(db) == first
    assert db.calls == 1


async def test_a_registry_with_no_account_has_no_derived_date():
    assert await rcb._founded_at_fallback(_FakeDb(None)) is None


def test_the_identity_block_uses_the_derived_date_and_the_operator_wins():
    derived = "2026-09-07T06:51:12+00:00"
    assert rcb._build_identity_block({}, founded_fallback=derived)["founded_at"] == derived
    stated = {"identity": {"founded_at": "2026-09-01T00:00:00+00:00"}}
    assert rcb._build_identity_block(stated, founded_fallback=derived)["founded_at"] == "2026-09-01T00:00:00+00:00"


def test_the_network_date_is_only_the_last_resort():
    assert rcb._build_identity_block({})["founded_at"] == "2026-03-18T00:00:00+00:00"


def test_a_commitments_block_without_the_licence_still_carries_it():
    stated = {"gdpr_compliant": True, "uptime_sla_pct": 99.5}
    got = rcb._with_software_licence(stated)
    assert got["open_source_license"] == "AGPL-3.0-or-later"
    assert got["gdpr_compliant"] is True and got["uptime_sla_pct"] == 99.5
    assert "open_source_license" not in stated  # the operator's dict is never mutated


def test_the_operators_own_licence_wins():
    got = rcb._with_software_licence({"open_source_license": "AGPL-3.0-only"})
    assert got["open_source_license"] == "AGPL-3.0-only"


def test_the_builder_revision_moves_the_etag(monkeypatch):
    before = rcb._etag_from_basis({}, rcb._id_subset({}), None)
    monkeypatch.setattr(rcb, "_BUILDER_REV", rcb._BUILDER_REV + 1)
    assert rcb._etag_from_basis({}, rcb._id_subset({}), None) != before
