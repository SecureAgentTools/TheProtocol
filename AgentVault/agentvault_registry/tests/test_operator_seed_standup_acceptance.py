"""The frame kit's standup records what its person accepted with the account it issues (agentvault2-56, 2026-10-22;
his word: "make sure terms are accepted also on framekit standup. because there an account is issued").

Every other rail that issues an account records the documents its person accepted. A frame stood up with the kit's
frame-up.py was issued its first admin by operator_seed with none. frame-up.py now asks for the Federation Operator Terms
(the prompt, or --accept-terms) and passes the acceptance in FIRST_ADMIN_ACCEPTED / _AT / _BY; operator_seed records it
with the account, in the same transaction, at the version this registry serves (never the client's word).

Pinned: which documents are recorded and at which version; that unset records nothing (a network-run frame, a cloud
operator, an older kit); that a name the registry does not serve is left out; that the rows share the account's
transaction and carry the person's moment and tool; that seed() uses both. RED on a662f7d4 (V0631): neither
standup_acceptances nor create_admin exists, and record_acceptance takes no accepted_at.
"""
from __future__ import annotations

import ast
import asyncio
import datetime
import pathlib
import types

from agentvault_registry import models, operator_seed
from agentvault_registry.core.legal_versions import current_version

AT = "2026-10-22T12:34:56Z"
BY = "frame-up.py 1.0.0-beta.23"


def test_unset_records_nothing():
    assert operator_seed.standup_acceptances({}) == []
    assert operator_seed.standup_acceptances({"FIRST_ADMIN_ACCEPTED": " , "}) == []


def test_the_operator_terms_at_the_version_this_registry_serves():
    rows = operator_seed.standup_acceptances({"FIRST_ADMIN_ACCEPTED": "operators", "FIRST_ADMIN_ACCEPTED_AT": AT,
                                              "FIRST_ADMIN_ACCEPTED_BY": BY})
    assert rows == [("operators", current_version("operators"),
                     datetime.datetime(2026, 10, 22, 12, 34, 56, tzinfo=datetime.timezone.utc), BY)]


def test_unknown_names_are_left_out_and_repeats_count_once():
    rows = operator_seed.standup_acceptances({"FIRST_ADMIN_ACCEPTED": "Operators, nosuchdoc, operators, terms"})
    assert [(d, v) for d, v, _at, _by in rows] == [("operators", current_version("operators")),
                                                  ("terms", current_version("terms"))]


def test_an_unreadable_moment_is_stamped_now_and_always_carries_a_zone():
    before = datetime.datetime.now(datetime.timezone.utc)
    (_d, _v, at, by), = operator_seed.standup_acceptances({"FIRST_ADMIN_ACCEPTED": "operators",
                                                           "FIRST_ADMIN_ACCEPTED_AT": "yesterday"})
    assert at >= before and at.tzinfo is not None and by is None
    (_d, _v, at, _b), = operator_seed.standup_acceptances({"FIRST_ADMIN_ACCEPTED": "operators",
                                                           "FIRST_ADMIN_ACCEPTED_AT": "2026-10-22T12:00:00"})
    assert at.tzinfo is not None


class _Session:
    """Collects what the seed adds; the account gets its id at the flush, the way the database gives it."""

    def __init__(self):
        self.added, self.calls = [], []

    def add(self, obj):
        self.added.append(obj)
        self.calls.append(("add", type(obj).__name__))

    async def flush(self):
        self.calls.append(("flush", None))
        for obj in self.added:
            if isinstance(obj, models.Developer) and obj.id is None:
                obj.id = 41

    async def commit(self):
        self.calls.append(("commit", None))

    async def refresh(self, obj):
        self.calls.append(("refresh", type(obj).__name__))


def _admin():
    return models.Developer(name="kit-admin", email="ops@example.org", hashed_password="x", is_admin=True,
                            is_verified=True)


def test_the_account_and_its_acceptance_share_one_transaction():
    db, admin = _Session(), _admin()
    accepted = operator_seed.standup_acceptances({"FIRST_ADMIN_ACCEPTED": "operators", "FIRST_ADMIN_ACCEPTED_AT": AT,
                                                  "FIRST_ADMIN_ACCEPTED_BY": BY})
    asyncio.run(operator_seed.create_admin(db, admin, accepted))
    rows = [o for o in db.added if isinstance(o, models.LegalAcceptance)]
    assert len(rows) == 1
    row = rows[0]
    assert (row.developer_id, row.subject_kind, row.subject_id) == (41, "developer", "41")
    assert (row.document, row.version, row.via) == ("operators", current_version("operators"), "frame_standup")
    assert row.accepted_at == datetime.datetime(2026, 10, 22, 12, 34, 56, tzinfo=datetime.timezone.utc)
    assert row.user_agent == BY and row.source_ip is None
    assert [c for c, _ in db.calls].count("commit") == 1
    assert db.calls.index(("commit", None)) > db.calls.index(("add", "LegalAcceptance")), db.calls
    assert admin.tos_accepted_version is None, "the operator terms do not stamp the Terms"


def test_the_terms_also_stamp_the_accounts_fast_path():
    db, admin = _Session(), _admin()
    asyncio.run(operator_seed.create_admin(db, admin, operator_seed.standup_acceptances(
        {"FIRST_ADMIN_ACCEPTED": "terms", "FIRST_ADMIN_ACCEPTED_AT": AT})))
    assert admin.tos_accepted_version == current_version("terms")
    assert admin.tos_accepted_at == datetime.datetime(2026, 10, 22, 12, 34, 56, tzinfo=datetime.timezone.utc)


def test_no_acceptance_named_adds_the_account_alone():
    db = _Session()
    asyncio.run(operator_seed.create_admin(db, _admin(), []))
    assert [type(o).__name__ for o in db.added] == ["Developer"]
    assert ("commit", None) in db.calls


def test_seed_reads_the_acceptance_and_creates_the_admin_with_it():
    tree = ast.parse(pathlib.Path(operator_seed.__file__).read_text())
    seed = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "seed")
    called = {getattr(c.func, "id", None) for c in ast.walk(seed) if isinstance(c, ast.Call)}
    assert {"standup_acceptances", "create_admin"} <= called
    assert not any(isinstance(c.func, ast.Attribute) and c.func.attr == "commit" for c in ast.walk(seed)
                   if isinstance(c, ast.Call)), "the admin is committed by create_admin, with its acceptance"


def test_the_shared_writer_keeps_its_old_callers_unchanged():
    from agentvault_registry.services import legal_acceptance as la
    db = _Session()
    req = types.SimpleNamespace(headers={"user-agent": "console"}, client=None)
    row = asyncio.run(la.record_acceptance(db, document="terms", subject_kind="developer", subject_id="7", via="login",
                                           developer_id=7, request=req))
    assert row.user_agent == "console" and row.accepted_at.tzinfo is not None
    assert row.version == current_version("terms")
