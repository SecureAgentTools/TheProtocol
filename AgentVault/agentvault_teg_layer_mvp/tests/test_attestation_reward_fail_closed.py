"""§ATTESTREWARD (agentvault2-45, 2026-10-13; agentvault2-90's §ZKV2 finding): an attestation reward is paid only for a
proof a REAL verifier accepted.

THE DEFECT: POST /api/v1/attestation/submit started from `should_issue_reward = True`, so a submission WITHOUT a proof
was paid the treasury reward (system_config attestation_submission_reward, default 10), and the registry's
POST /api/v1/teg/attestations/submit forwards none: any agent holding reputation.signal (the service-provider role,
which an owner may give its own agent) drew 10 per call, each call made unique by its arbitrary attestation_data
(the unique key is agent, type and the data's hash). With a proof, core/zkp_verifier.py only simulates: a 32+ char
string starting "VALID_" passes. Measured 2026-10-13: 0 rows in teg_attestation_logs on the six production TEGs and
sbx-beta, so it was never drawn on.

THE FIX: a reward needs a proof, its verification, and a verifier that is not a simulation (ZKPVerifier.SIMULATED).
The submission is still logged, and its status still says what the verifier answered.

The handler runs for real here with its collaborators stubbed (no database): TransferService.execute_transfer is the
one place a reward moves, so every test counts its calls. Red control: the same file against the pre-fix
endpoints_attestation.py fails the no-proof and the forged-proof tests (the real-verifier test passes on both).
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest

from teg_core_service.api.v1 import endpoints_attestation as ea
from teg_core_service.api.v1.schemas import AttestationSubmissionRequest, ZKPAttestationDetail
from teg_core_service.core.zkp_verifier import ZKPVerifier


class _Query:
    def __init__(self, obj):
        self.obj = obj

    def filter_by(self, **_kw):
        return self

    def first(self):
        return self.obj


class _DB:
    """The session the handler is given: it commits, refreshes, rolls back and reloads the submission."""

    def __init__(self):
        self.submission = None

    def commit(self):
        pass

    def refresh(self, _obj):
        pass

    def rollback(self):
        pass

    def query(self, _model):
        return _Query(self.submission)


class _Verifier:
    def __init__(self, answer: bool, simulated: bool):
        self.answer = answer
        self.SIMULATED = simulated

    def verify_proof(self, circuit_id, public_inputs, proof_value):
        return self.answer


@pytest.fixture
def rail(monkeypatch):
    """Stub the CRUDs the handler calls; return the list of reward transfers it made."""
    db = _DB()
    transfers: list[dict] = []

    def create_submission(db=None, **kw):
        db.submission = SimpleNamespace(submission_id="sub-1", status="logged", reward_issued_tx_id=None,
                                        agent_did=kw["agent_did"], attestation_type=kw["attestation_type"])
        return db.submission

    def execute_transfer(db=None, sender_id=None, receiver_id=None, amount=None, fee_amount=None):
        transfers.append({"from": sender_id, "to": receiver_id, "amount": amount})
        return SimpleNamespace(transaction_id=f"tx-{len(transfers)}", transaction_type=None)

    monkeypatch.setattr(ea.AgentCRUD, "get_or_create", lambda db_, did: SimpleNamespace(token_balance=Decimal("1e9")))
    monkeypatch.setattr(ea.PolicyCRUD, "get_policy_by_circuit_identifier", lambda db_, cid: None)
    monkeypatch.setattr(ea.PolicyCRUD, "get_policy_by_id", lambda db_, pid: None)
    monkeypatch.setattr(ea.SystemConfigCRUD, "get_attestation_policy_id", lambda db_: None)
    monkeypatch.setattr(ea.SystemConfigCRUD, "get_proof_of_positive_balance_policy_id", lambda db_: None)
    monkeypatch.setattr(ea.SystemConfigCRUD, "get_treasury_did", lambda db_: "did:theprotocol:treasury")
    monkeypatch.setattr(ea.SystemConfigCRUD, "get_attestation_reward_amount", lambda db_: Decimal("10"))
    monkeypatch.setattr(ea.AttestationCRUD, "create_submission", create_submission)
    monkeypatch.setattr(ea.TransferService, "execute_transfer", execute_transfer)
    return SimpleNamespace(db=db, transfers=transfers, monkeypatch=monkeypatch)


def _submit(rail, zkp: ZKPAttestationDetail | None, verifier):
    rail.monkeypatch.setattr(ea, "get_zkp_verifier", lambda: verifier)
    req = AttestationSubmissionRequest(agent_did="did:theprotocol:agent-1", attestation_type="ProofOfFairMarkup",
                                       attestation_hash="ab" * 32, storage_pointer="registry://attestation/x",
                                       zkp_payload=zkp)
    return asyncio.run(ea.submit_attestation(req, "did:theprotocol:agent-1", rail.db))


def _proof(value: str) -> ZKPAttestationDetail:
    return ZKPAttestationDetail(circuit_id="fairMarkupPolicy/v1.0.0", public_inputs={"markup_cap": 10}, proof_value=value)


def test_a_submission_without_a_proof_is_logged_and_never_paid(rail):
    out = _submit(rail, None, _Verifier(answer=True, simulated=False))
    assert out.submission_id == "sub-1"
    assert rail.transfers == [], "a proof-less submission drew a reward from the treasury"


def test_a_forged_proof_the_simulation_accepts_is_never_paid(rail):
    out = _submit(rail, _proof("VALID_" + "f" * 40), ZKPVerifier())
    assert rail.transfers == [], "a proof only the simulation accepted drew a reward from the treasury"
    assert out.status in ("zkp_verified_true", "zkp_verified_false")   # the verdict is still recorded, as it is
    assert ZKPVerifier.SIMULATED is True


def test_a_refused_proof_is_never_paid(rail):
    _submit(rail, _proof("anything-at-all-" + "0" * 32), _Verifier(answer=False, simulated=False))
    assert rail.transfers == []


def test_a_proof_a_real_verifier_accepted_is_paid_once(rail):
    _submit(rail, _proof("p" * 64), _Verifier(answer=True, simulated=False))
    assert rail.transfers == [{"from": "did:theprotocol:treasury", "to": "did:theprotocol:agent-1",
                               "amount": Decimal("10")}]
