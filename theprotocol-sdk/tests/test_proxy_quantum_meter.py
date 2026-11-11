"""V0660 (c): the shot meter — what it proves, and what it refuses to pretend.

The circuit this serves is accurateResourceUsagePolicy/v2.0.0, read from the registry rather than guessed:

    public:  max_discrepancy_bps (u32), transaction_ref (Field, non-zero), reported_units (u64)
    private: logged_units (u64), salt (Field)
    output:  log_commitment = Poseidon2(DOMAIN, transaction_ref, logged_units, salt), DOMAIN "tp.resource_usage.v2"
    rule:    |reported_units - logged_units| * 10000 <= logged_units * max_discrepancy_bps
    policy:  max_discrepancy_bps at_most 100

The circuit's own Limits note carries the design constraint this module exists to honour: "a verifier should
compare log_commitment with one the meter published". A commitment first published at REPORT time proves
nothing at all, because a provider free to choose logged_units after the fact can always match its own
report. So the meter commits when the work runs, and refuses to report a job it never metered.
"""
from __future__ import annotations

import pytest

from theprotocol.proxy.quantum.meter import (
    DOMAIN_RESOURCE_USAGE_V2,
    POLICY_MAX_DISCREPANCY_BPS,
    MeterRefused,
    ShotMeter,
    derive_reference,
)


def meter(tmp_path, **kw):
    return ShotMeter(dir=str(tmp_path), agent_did="did:theprotocol:eu.theprotocol.cloud:abc", **kw)


class TestTheReference:
    def test_it_is_derived_the_way_the_registry_demands(self):
        """The registry refuses a v2 proof whose reference is not derive_reference(submitting DID, label),
        so a reference we invent is a proof nobody accepts. The algorithm is published: the first 31 bytes
        of SHA-256 over "tp.attestation.ref.v1|", the DID, "|" and the label, big-endian."""
        import hashlib

        did, label = "did:theprotocol:eu/x", "job-1"
        raw = hashlib.sha256(b"tp.attestation.ref.v1|" + did.encode() + b"|" + label.encode()).digest()
        assert derive_reference(did, label) == int.from_bytes(raw[:31], "big")

    def test_it_is_never_zero(self):
        """The circuit requires a non-zero transaction_ref."""
        assert derive_reference("did:theprotocol:eu/x", "job-1") != 0

    def test_a_different_agent_gives_a_different_reference(self):
        """A proof made for one agent must not verify when another submits it."""
        a = derive_reference("did:theprotocol:eu/one", "job-1")
        b = derive_reference("did:theprotocol:eu/two", "job-1")
        assert a != b

    def test_it_matches_the_server_sdk_when_that_is_installed(self):
        """A cross-check against the implementation the registry was built against, skipped loudly rather
        than silently when the package is not importable here."""
        try:
            from agentvault_server_sdk.zkp_attestation import derive_reference as theirs
        except Exception:
            pytest.skip("agentvault_server_sdk is not importable here: cross-check NOT MEASURED")
        did, label = "did:theprotocol:eu/x", "job-1"
        assert derive_reference(did, label) == theirs(did, label)


class TestMeteringAtRunTime:
    def test_it_commits_when_the_work_runs(self, tmp_path):
        m = meter(tmp_path)
        entry = m.record("job-1", shots=1024)
        assert entry.logged_units == 1024
        assert entry.transaction_ref != 0
        assert entry.salt, "a commitment needs its blinding salt"
        assert entry.committed_at, "the commitment is published when the work runs, and says when"

    def test_the_log_is_hash_linked(self, tmp_path):
        m = meter(tmp_path)
        first = m.record("job-1", shots=10)
        second = m.record("job-2", shots=20)
        assert second.prev == first.hash
        assert m.verify() == [], "an untouched log verifies"

    def test_a_changed_entry_breaks_the_chain(self, tmp_path):
        """A log nobody can tamper with is the whole value of the commitment; a log we never check is a
        claim, so verify() must really fail."""
        m = meter(tmp_path)
        m.record("job-1", shots=10)
        m.record("job-2", shots=20)
        path = m.path
        before = path.read_text(encoding="utf-8")
        # the log is canonical JSON, so there is no space after the colon. Asserting the edit LANDED is the
        # point: a tamper test that silently tampers with nothing passes against a verify() that checks
        # nothing, which is the shape of every gate that cannot fail.
        text = before.replace('"logged_units":10', '"logged_units":99')
        assert text != before, "the tamper did not change the file, so this test would prove nothing"
        path.write_text(text, encoding="utf-8")
        problems = ShotMeter(dir=str(tmp_path), agent_did="x").verify()
        assert problems, "a changed shot count must break the chain"
        assert any("job-1" in p or "hash" in p.lower() for p in problems)

    def test_the_same_job_is_metered_once(self, tmp_path):
        """Exactly-once is the core's promise; the meter keeps it for its own log, so a replayed job does
        not double the shots it claims."""
        m = meter(tmp_path)
        a = m.record("job-1", shots=10)
        b = m.record("job-1", shots=10)
        assert a.hash == b.hash
        assert len(m.entries()) == 1

    def test_the_same_job_with_different_shots_is_refused(self, tmp_path):
        """Two different shot counts under one job id is the state the meter exists to make impossible."""
        m = meter(tmp_path)
        m.record("job-1", shots=10)
        with pytest.raises(MeterRefused) as e:
            m.record("job-1", shots=11)
        assert "job-1" in str(e.value) and "10" in str(e.value) and "11" in str(e.value)


class TestTheReport:
    def test_an_exact_report_is_within_tolerance(self, tmp_path):
        m = meter(tmp_path)
        m.record("job-1", shots=1000)
        claim = m.claim("job-1", reported_units=1000)
        assert claim.public["reported_units"] == 1000
        assert claim.public["max_discrepancy_bps"] <= POLICY_MAX_DISCREPANCY_BPS
        assert claim.public["transaction_ref"] != 0

    def test_a_report_inside_the_tolerance_passes(self, tmp_path):
        m = meter(tmp_path)
        m.record("job-1", shots=1000)          # 100 bps of 1000 is 10
        assert m.claim("job-1", reported_units=1009).public["reported_units"] == 1009

    def test_a_report_outside_the_tolerance_is_refused_with_both_numbers(self, tmp_path):
        m = meter(tmp_path)
        m.record("job-1", shots=1000)
        with pytest.raises(MeterRefused) as e:
            m.claim("job-1", reported_units=1200)
        assert "1200" in str(e.value) and "1000" in str(e.value)

    def test_a_tolerance_looser_than_the_policy_is_refused_here_too(self, tmp_path):
        """The registry refuses a proof whose tolerance is looser than its policy. Refusing locally means a
        provider learns it at the meter instead of after paying for a proof."""
        m = meter(tmp_path)
        m.record("job-1", shots=1000)
        with pytest.raises(MeterRefused) as e:
            m.claim("job-1", reported_units=1000, max_discrepancy_bps=POLICY_MAX_DISCREPANCY_BPS + 1)
        assert str(POLICY_MAX_DISCREPANCY_BPS) in str(e.value)

    def test_a_job_that_was_never_metered_cannot_be_reported(self, tmp_path):
        """THE ordering property. A commitment published at report time proves nothing, because logged_units
        could be chosen to match any report. So a report with no run-time commitment behind it is refused."""
        m = meter(tmp_path)
        with pytest.raises(MeterRefused) as e:
            m.claim("job-never-ran", reported_units=1000)
        assert "job-never-ran" in str(e.value)
        assert "metered" in str(e.value).lower() or "committed" in str(e.value).lower()


class TestWhatItWillNotPretend:
    def test_the_poseidon2_commitment_is_not_computed_without_a_prover(self, tmp_path):
        """nargo and bb produce the circuit's commitment; neither is a dependency of this SDK. The claim
        therefore carries the exact pre-image and says the commitment is NOT COMPUTED, rather than putting
        a hash of our own under the name the circuit uses. A wrong log_commitment would be worse than an
        absent one: it would be compared against the circuit's and fail far from here."""
        m = meter(tmp_path)
        m.record("job-1", shots=1000)
        claim = m.claim("job-1", reported_units=1000)
        assert claim.log_commitment is None
        assert claim.log_commitment_state == "NOT_COMPUTED"
        assert "nargo" in claim.log_commitment_reason or "bb" in claim.log_commitment_reason
        assert claim.preimage["domain"] == DOMAIN_RESOURCE_USAGE_V2
        assert claim.preimage["logged_units"] == 1000
        assert claim.preimage["transaction_ref"] == claim.public["transaction_ref"]
        assert claim.preimage["salt"]

    def test_the_private_figures_stay_out_of_the_public_inputs(self, tmp_path):
        """logged_units and salt are the circuit's PRIVATE inputs: a claim that published them would give
        away exactly what the proof exists to keep."""
        m = meter(tmp_path)
        m.record("job-1", shots=1000)
        claim = m.claim("job-1", reported_units=1000)
        assert set(claim.public) == {"max_discrepancy_bps", "transaction_ref", "reported_units"}
        assert "salt" not in claim.public and "logged_units" not in claim.public
