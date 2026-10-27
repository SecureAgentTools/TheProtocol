"""§LEGALKIT: renewed acceptance is asked exactly when the served version moved past the accepted one."""
import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from agentvault_registry.services import legal_acceptance as la  # noqa: E402
from agentvault_registry.core import legal_versions as lv  # noqa: E402


def test_reconsent_required_semantics():
    assert la.reconsent_required(None, "2.1") is True          # no record at all: ask
    assert la.reconsent_required("2.0", "2.1") is True         # older: ask
    assert la.reconsent_required("2.1", "2.1") is False        # current: quiet
    assert la.reconsent_required("2.2", "2.1") is False        # a rolled-back frame does not ask
    assert la.reconsent_required("2026-07-09", "2.1") is True  # the pre-v2 date-shaped stamp counts as older
    assert la.reconsent_required("2.0", None) is False         # a frame with no version serves no question


def test_versions_are_one_copy():
    from agentvault_registry.config import settings
    assert lv.TOS_VERSION == settings.TOS_VERSION == "2.4"   # §BAFIN 2026-10-04: 2.4, membership instead of staking
    assert la.reconsent_required("2.3", lv.TOS_VERSION) is True   # every 2.3 account is asked again at its next login
    # the Operator Terms did not change in set 2.5: an operator who accepted them at 2.4 is not asked again
    assert lv.DOCUMENTS_VERSION == "2.5" and lv.OPERATOR_TERMS_SET_VERSION == "2.4"
    assert lv.ACCEPTABLE_DOCUMENTS["operators"] == lv.OPERATOR_TERMS_SET_VERSION
    assert la.reconsent_required("2.2", lv.TOS_VERSION) is True   # every 2.2 account is asked again at its next login
    assert lv.ACCEPTABLE_DOCUMENTS["terms"] == lv.TOS_VERSION
    assert lv.current_version("nope") is None
    from agentvault_registry.routers import fiat_onramp
    assert fiat_onramp.CURRENT_TOS_VERSION == settings.TOS_VERSION


class _FakeDB:
    def __init__(self):
        self.added = []
        self.flushed = 0
        self.committed = 0

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        self.flushed += 1

    async def commit(self):
        self.committed += 1


def test_record_acceptance_stamps_the_served_version_and_the_request_evidence():
    db = _FakeDB()
    req = SimpleNamespace(headers={"user-agent": "probe/1.0", "x-forwarded-for": "203.0.113.77, 198.51.100.50"},
                          client=SimpleNamespace(host="127.0.0.1"))
    row = asyncio.run(la.record_acceptance(db, document="terms", subject_kind=la.SUBJECT_DEVELOPER, subject_id="7",
                                           via="register", developer_id=7, request=req))
    assert row.version == lv.TOS_VERSION and row.document == "terms" and row.via == "register"
    assert row.user_agent == "probe/1.0" and row.subject_id == "7" and row.developer_id == 7
    assert db.flushed == 1 and db.committed == 0 and db.added == [row]


def test_record_acceptance_refuses_an_unknown_document():
    db = _FakeDB()
    try:
        asyncio.run(la.record_acceptance(db, document="unknown-doc", subject_kind="developer", subject_id="1", via="x"))
    except ValueError as exc:
        assert "unknown legal document" in str(exc)
    else:
        raise AssertionError("an unknown document must not produce a record")
    assert db.added == []


# ---- V0414: the documents to accept, the operator terms among them only for an account that holds operators ----
class _Result:
    def __init__(self, value):
        self._v = value

    def scalar(self):
        return self._v


class _QueryDB:
    """Answers each SELECT in order: a fake that says which relationships and acceptances exist."""
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    async def execute(self, stmt, params=None):
        self.calls += 1
        return _Result(self.answers.pop(0) if self.answers else None)


def _dev(tos="2.1"):
    return SimpleNamespace(id=42, tos_accepted_version=tos)


def _docs(db, dev):
    return asyncio.run(la.reconsent_documents(db, dev, tos_version="2.1", documents_version="2.1"))


def test_an_operator_owner_without_the_acceptance_is_asked_for_the_operator_document():
    # operator application: yes (id 7); acceptance of operators v2.1: none
    assert _docs(_QueryDB([7, None]), _dev()) == ["operators"]


def test_a_frame_requester_counts_as_an_operator_owner():
    # operator application: none; frame request: yes (id 3); acceptance: none
    assert _docs(_QueryDB([None, 3, None]), _dev()) == ["operators"]


def test_an_operator_owner_who_accepted_the_served_version_is_quiet():
    assert _docs(_QueryDB([7, 900]), _dev()) == []


def test_a_developer_without_operators_is_never_asked_for_the_operator_document():
    db = _QueryDB([None, None])
    assert _docs(db, _dev()) == []
    assert db.calls == 2   # both relationship queries ran, no acceptance query


def test_the_terms_come_first_and_both_can_be_due():
    assert _docs(_QueryDB([7, None]), _dev(tos="2.0")) == ["terms", "operators"]
    assert _docs(_QueryDB([None, None]), _dev(tos=None)) == ["terms"]


def test_no_documents_version_means_no_operator_question():
    db = _QueryDB([7, None])
    assert asyncio.run(la.reconsent_documents(db, _dev(), tos_version="2.1", documents_version="")) == []
    assert db.calls == 0
