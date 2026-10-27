"""D6-481: an 'org' bundle is read by its organization's active owner, admins and members.

visibility 'org' was accepted and stored on publish, and no read path admitted anyone but the owner, so it behaved
as 'private'. One rule now: list_bundles carries it in SQL (_org_reader_sql), org_reader_of asks it for one bundle
and bundle_visible_to takes its answer (manifest, download, rating, restore and every fork). A guest reads no 'org'
bundle (a restore copies the pipelines a guest may not see); an inactive membership or organization reads none.
"""
import asyncio

from agentvault_registry.services.bundles import service as svc

ORG = "0b6f1d2e-3c4d-4e5f-8a9b-0c1d2e3f4a5b"
BID = "11111111-1111-1111-1111-111111111111"


class _Result:
    def __init__(self, answer):
        self.answer = answer

    def first(self):
        return self.answer

    def scalar(self):
        return self.answer

    def fetchall(self):
        return list(self.answer or [])


class _Db:
    def __init__(self, *answers):
        self.calls = []
        self.answers = list(answers)

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), dict(params or {})))
        return _Result(self.answers.pop(0) if self.answers else None)

    async def commit(self):
        pass


def test_the_rule_admits_an_org_reader_to_an_org_bundle_only():
    assert svc.bundle_visible_to(1, "org", False, False, 2, True)
    assert not svc.bundle_visible_to(1, "org", False, False, 2, False)
    assert not svc.bundle_visible_to(1, "org", False, False, 2)
    assert not svc.bundle_visible_to(1, "private", False, False, 2, True)
    assert not svc.bundle_visible_to(1, "org", False, True, 2, True)
    assert svc.bundle_visible_to(2, "org", False, False, 2, False)


def test_org_reader_of_asks_the_membership_rule():
    db = _Db(True)
    assert asyncio.run(svc.org_reader_of(db, ORG, "org", 7))
    sql, params = db.calls[0]
    assert params == {"org": ORG, "dev_id": 7}
    for clause in ("m.organization_id = :org", "m.developer_id = :dev_id", "m.is_active", "o.is_active",
                   "m.role IN ('owner', 'admin', 'member')"):
        assert clause in sql, clause
    assert "guest" not in sql
    assert not asyncio.run(svc.org_reader_of(_Db(False), ORG, "org", 7))


def test_org_reader_of_asks_nothing_for_another_bundle():
    db = _Db(True, True, True, True)
    for vis, org, dev in (("private", ORG, 7), ("public", ORG, 7), ("org", None, 7), ("org", ORG, None)):
        assert not asyncio.run(svc.org_reader_of(db, org, vis, dev))
    assert db.calls == []


def test_the_list_carries_the_same_rule():
    db = _Db([])
    asyncio.run(svc.list_bundles(db=db, requesting_dev_id=7))
    sql, params = db.calls[0]
    assert "visibility = 'org' AND EXISTS" in sql
    assert "m.organization_id = CAST(agent_bundles.source_org_id AS TEXT)" in sql
    assert "m.role IN ('owner', 'admin', 'member')" in sql
    assert params["dev_id"] == 7


def test_a_reader_gets_the_manifest_and_a_stranger_does_not():
    row = ({"bundle": "m"}, 1, "org", False, False, ORG)
    assert asyncio.run(svc.get_manifest(_Db(row, True), BID, requesting_dev_id=7)) == {"bundle": "m"}
    assert asyncio.run(svc.get_manifest(_Db(row, False), BID, requesting_dev_id=8)) is None


def test_a_stranger_downloads_no_org_bundle():
    row = ("key", 1, "org", False, False, ORG)
    db = _Db(row, False)
    assert asyncio.run(svc.download_bytes(db, BID, requesting_dev_id=8)) is None
    assert len(db.calls) == 2 and "download_count" not in db.calls[-1][0]
