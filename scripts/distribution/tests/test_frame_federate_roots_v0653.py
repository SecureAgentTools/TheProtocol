"""V0653 (ao) item 1 (the dev machine's beta.30 test, room seq 582 and 587/588): frame-federate's step 4 asks whether the
peer's root is in each terminator's bundle, by its fingerprint, not whether the root count rose.

A re-run inside one cert-writer cycle of a refusal found the root already copied and the count unchanged, waited 630 s
and blamed the cert-writer for a root that was there. Step 3 now hands step 4 the fingerprints of the roots it imported
(a SPIFFE bundle's x5c, or PEM blocks); step 4 reads each terminator's bundle.0.pem and returns at once when they are
there, waits a cert-writer cycle when they are not, and names the root only when it never arrives. BASE (kit beta.31):
the re-run below waits the whole bound and blames the cert-writer (the control reproduces it with the count rule).
"""
import base64
import hashlib
import importlib.util
import json
import pathlib
import sys
import types

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("frame_federate_roots", HERE.parent / "frame-federate.py")
ff = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ff
SPEC.loader.exec_module(ff)

OWN, PEER = b"own-root-der-bytes", b"peer-root-der-bytes"
FP = hashlib.sha256(PEER).hexdigest()


def _pem(*ders):
    return "".join(f"-----BEGIN CERTIFICATE-----\n{base64.b64encode(d).decode()}\n-----END CERTIFICATE-----\n" for d in ders)


FACTS = types.SimpleNamespace(terminators=["lantern-nginx-federation", "lantern-nginx-teg"], cert_dir="/certs",
                              refresh_sec=300)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_the_peer_roots_are_read_from_a_spiffe_bundle_and_from_pem():
    spiffe = json.dumps({"keys": [{"use": "x509-svid", "x5c": [base64.b64encode(PEER).decode()]},
                                  {"use": "jwt-svid", "kid": "k1", "kty": "EC"}]})
    assert ff.bundle_root_fingerprints(spiffe, "spiffe") == [FP]
    assert ff.bundle_root_fingerprints(_pem(PEER), "pem") == [FP]
    assert ff.pem_fingerprints(_pem(OWN, PEER)) == [hashlib.sha256(OWN).hexdigest(), FP]


def test_a_rerun_finds_the_root_already_there_and_does_not_wait():
    lines = []
    exec_in = lambda c, argv: (0, _pem(OWN, PEER))

    def no_sleep(_):
        raise AssertionError("step 4 waited for a root that was already there")

    ff.step4_roots(FACTS, {c: 2 for c in FACTS.terminators}, False, roots=[FP], exec_in=exec_in, log=lines.append,
                   clock=_Clock(), sleep=no_sleep)
    assert lines == [f"[4/7] roots: the peer's root (sha256 {FP[:16]}) is already in every terminator's bundle "
                     f"(lantern-nginx-federation, lantern-nginx-teg); nothing to wait for"]


def test_control_the_count_rule_waits_the_whole_bound_and_blames_the_cert_writer():
    clock = _Clock()
    exec_in = lambda c, argv: (0, "2")                       # grep -c: the count did not rise, the root is there
    with pytest.raises(ff.TimedOut) as e:
        ff.wait_for_roots(exec_in, FACTS.terminators, "/certs", {c: 2 for c in FACTS.terminators}, 300,
                          clock=clock, sleep=clock.sleep, log=lambda *_: None)
    assert clock.t >= 630 and "cert-writer" in str(e.value)


def test_a_root_that_arrives_ends_the_wait_and_says_after_how_long():
    clock, seen, lines = _Clock(), {"n": 0}, []

    def exec_in(c, argv):
        seen["n"] += 1
        return 0, _pem(OWN, PEER) if clock.t >= 20 else _pem(OWN)

    ff.step4_roots(FACTS, {}, False, roots=[FP], exec_in=exec_in, log=lines.append, clock=clock, sleep=clock.sleep)
    assert lines[-1].startswith(f"[4/7] roots: the peer's root (sha256 {FP[:16]}) reached every terminator's bundle after")
    assert any("not yet" in ln for ln in lines[:-1])


def test_a_root_that_never_arrives_is_named_with_the_cert_writers_clock():
    clock = _Clock()
    with pytest.raises(ff.TimedOut) as e:
        ff.step4_roots(FACTS, {}, False, roots=[FP], exec_in=lambda c, argv: (0, _pem(OWN)), log=lambda *_: None,
                       clock=clock, sleep=clock.sleep)
    assert FP[:16] in str(e.value) and "FT_CW_REFRESH_SEC=300" in str(e.value) and "do not carry the peer's root" in str(e.value)


def test_a_terminator_that_cannot_answer_is_waited_for_never_counted_as_holding():
    held = ff.roots_held(lambda c, argv: (1, "cat: /certs/bundle.0.pem: No such file or directory"), ["x"], "/certs", [FP])
    assert held == {"x": None}


def test_control_without_fingerprints_step4_keeps_the_count_rule():
    lines = []
    ff.step4_roots(FACTS, {}, True, roots=None, exec_in=lambda c, argv: (0, "3"), log=lines.append)
    assert lines and "already held" in lines[0]
