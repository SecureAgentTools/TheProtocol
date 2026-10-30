"""D6-809 (2026-10-17): the TEG's bootstrap_tokens rows hold a token's hash, never the token.

The TEG's own onboarding rail (POST /onboarding/bootstrap/request-token, then /onboarding/onboard/register with a
Bootstrap-Token header) stored each token as itself in bootstrap_tokens.token_value and found a presented token by
that plaintext, so anyone who could read the table held live tokens for their five minutes. The registry's rows have
held a hash since D6-283 (and V0620's migration 0193 scrubbed its older rows); the TEG now does the same: the row holds
"sha256:<hex>", a presented token is found by its hash, and the token exists only in the answer that hands it out.
Read 2026-10-17 on all eleven TEG databases: no bootstrap row at all, so there was no stored token to scrub.

Integration test (real Postgres, real endpoint code) against a THROWAWAY database (DATABASE_URL), never a production
schema. Runner style (python tests/test_bootstrap_token_hash.py) so the CI job's "<passed>/<total> passed" gate reads
it. Mutation-verify: against 6f58e596's crud.py the first two scenarios fail (the row holds the token itself; the
stored value works as a token) and the last fails (the refusal repeats the token); the other two pass on both.
"""
import os
import sys
import asyncio
import hashlib
import signal
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

os.environ.setdefault("AUDITED_BALANCE_ENABLED", "false")
os.environ.setdefault("TEG_HOME_FRAME_GUARD_ENABLED", "false")

from fastapi import HTTPException                                        # noqa: E402
from sqlalchemy import create_engine                                     # noqa: E402
from sqlalchemy.orm import sessionmaker                                  # noqa: E402

from src.teg_core_service.database.models import Base, BootstrapToken    # noqa: E402
from src.teg_core_service.database.crud import BootstrapTokenCRUD        # noqa: E402
import src.teg_core_service.api.v1.endpoints_onboarding as eo            # noqa: E402
from src.teg_core_service.api.v1.schemas import BootstrapTokenRequest, AgentRegisterRequest  # noqa: E402

CREATOR = "did:theprotocol:bootstrap-creator"

_raw = os.environ.get("DATABASE_URL_SYNC") or os.environ["DATABASE_URL"]
from src.teg_core_service.core.db_url import sync_engine_url            # noqa: E402
engine = create_engine(sync_engine_url(_raw))
SessionLocal = sessionmaker(bind=engine)


def reset_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    eo._token_requests_per_creator.clear()


def issue():
    """A token as the rail hands it out, and its row."""
    db = SessionLocal()
    try:
        resp = asyncio.run(eo.request_bootstrap_token(
            request=BootstrapTokenRequest(agent_type_hint="test", requested_by="test"), creator_id=CREATOR, db=db))
        token = resp.bootstrap_token
    finally:
        db.close()
    db = SessionLocal()
    try:
        all_rows = db.query(BootstrapToken).all()
        assert len(all_rows) == 1, f"one row per issued token, found {len(all_rows)}"
        return token, all_rows[0]
    finally:
        db.close()


def find(value):
    db = SessionLocal()
    try:
        return BootstrapTokenCRUD.get_active_bootstrap_token_by_value(db, value)
    finally:
        db.close()


def test_the_row_holds_the_hash_never_the_token():
    reset_db()
    token, row = issue()
    assert token.startswith("bst_"), "the answer hands the token out"
    assert row.token_value == "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()
    columns = [str(getattr(row, c.name)) for c in BootstrapToken.__table__.columns]
    assert not any(token in v for v in columns), "the token appears in no column of its row"


def test_the_token_finds_its_row_and_nothing_else_does():
    reset_db()
    token, row = issue()
    hit = find(token)
    assert hit is not None and hit.token_id == row.token_id, "the token as handed out finds its row"
    assert find(row.token_value) is None, "what the row stores is not itself a token"
    assert find(token[:-1] + ("0" if token[-1] != "0" else "1")) is None, "another token finds nothing"


def test_the_token_registers_once():
    reset_db()
    token, row = issue()
    req = AgentRegisterRequest(agent_did_method="theprotocol", proof_of_work_solution=None)
    db = SessionLocal()
    try:
        out = asyncio.run(eo.register_agent(request=req, bootstrap_token=token, db=db))
    finally:
        db.close()
    assert out.agent_did.startswith("did:theprotocol:")
    db = SessionLocal()
    try:
        used = db.query(BootstrapToken).filter(BootstrapToken.token_id == row.token_id).one()
        assert used.is_used is True and used.used_by_agent_did == out.agent_did
    finally:
        db.close()
    db = SessionLocal()
    try:
        asyncio.run(eo.register_agent(request=req, bootstrap_token=token, db=db))
        raise AssertionError("a used token registered a second agent")
    except HTTPException as e:
        assert e.status_code == 401, e.status_code
    finally:
        db.close()


def test_an_expired_token_finds_nothing():
    reset_db()
    db = SessionLocal()
    try:
        BootstrapTokenCRUD.create_bootstrap_token(
            db, token_value="bst_0123456789abcdef_0123456789ab",
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    finally:
        db.close()
    assert find("bst_0123456789abcdef_0123456789ab") is None


def test_a_duplicate_is_refused_without_repeating_the_token():
    reset_db()
    value = "bst_fedcba9876543210_ba9876543210"
    expires = datetime.now(timezone.utc) + timedelta(seconds=300)
    db = SessionLocal()
    try:
        BootstrapTokenCRUD.create_bootstrap_token(db, token_value=value, expires_at=expires)
        try:
            BootstrapTokenCRUD.create_bootstrap_token(db, token_value=value, expires_at=expires)
            raise AssertionError("a second row with the same token was written")
        except ValueError as e:
            assert value not in str(e), "the refusal must not repeat the token"
    finally:
        db.close()


TESTS = [
    test_the_row_holds_the_hash_never_the_token,
    test_the_token_finds_its_row_and_nothing_else_does,
    test_the_token_registers_once,
    test_an_expired_token_finds_nothing,
    test_a_duplicate_is_refused_without_repeating_the_token,
]


def _alarm(signum, frame):
    raise TimeoutError("scenario exceeded 60 s (a hang is the failure)")


if __name__ == "__main__":
    failed = 0
    signal.signal(signal.SIGALRM, _alarm)
    for t in TESTS:
        signal.alarm(60)
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            import traceback
            print(f"FAIL  {t.__name__}: {e}")
            traceback.print_exc()
        finally:
            signal.alarm(0)
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
