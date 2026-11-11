"""V0660 (c): `tp-proxy quantum-card` prints the extension for the backend the spec runs.

The first test here is the one that matters: a parser entry without a dispatch line is a command that
parses its arguments and then does nothing, which is the same unwired shape as a plugin that is never
registered. It reads as working from the help text and is absent from the product.
"""
from __future__ import annotations

import json
import sys

import pytest
import yaml

import proxy_fake as F


def _main(argv, capsys):
    from theprotocol.proxy.cli import main

    code = main(argv)
    out = capsys.readouterr()
    return code, out.out, out.err


def _spec(tmp_path, backend=None, section="qpu", type_="quantum_submit"):
    """The recipe's own shape, so the fixture needs no fake plugins and reads like a real spec.

    Built through the shared proxy_fake.spec_doc because a spec has required fields a hand-rolled one
    misses. Note its mappings default is taken when the argument is FALSY, so passing [] silently keeps
    the fakes' mapping — which is why this passes a real one.
    """
    bk = backend if backend is not None else {"kind": "simulator", "id": "sim-1", "qubits": 4}
    jobs, meter = str(tmp_path / "jobs"), str(tmp_path / "meter")
    doc = F.spec_doc(
        tmp_path,
        sources={"results": {"type": "quantum_results", "config": {"dir": jobs, "backend": bk}}},
        actions={"report": {"type": "quantum_report", "config": {"meter_dir": meter}}},
        sinks={section: {"type": type_, "config": {"dir": jobs, "backend": bk}}},
        mappings=[{"name": "report", "version": 1, "from": "results", "to": "report",
                   "fields": {"job_id": "$.payload.job_id", "shots": "$.payload.shots"}}],
    )
    path = tmp_path / "proxy.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return path


class TestTheCommandIsReachable:
    def test_it_is_dispatched_and_not_merely_parsed(self, tmp_path, capsys):
        code, out, err = _main(["quantum-card", str(_spec(tmp_path)),
                                "--receipt-schema-version", "1.0",
                                "--receipt-signing-algorithm", "Ed25519"], capsys)
        assert code == 0, f"the command failed: {err or out}"
        answer = json.loads(out)
        assert answer["extension"]["uri"].endswith("/quantum/workload")

    def test_it_appears_in_the_help(self, tmp_path, capsys):
        from theprotocol.proxy.cli import parser

        text = parser().format_help()
        assert "quantum-card" in text


class TestWhatItPrints:
    def test_the_card_carries_the_backend_s_real_facts(self, tmp_path, capsys):
        code, out, _ = _main(["quantum-card", str(_spec(tmp_path, backend={
            "kind": "simulator", "id": "sim-7", "qubits": 9, "max_shots": 2048})),
            "--receipt-schema-version", "1.0", "--receipt-signing-algorithm", "Ed25519"], capsys)
        assert code == 0
        backend = json.loads(out)["extension"]["params"]["backends"][0]
        assert backend["id"] == "sim-7"
        assert backend["qubits"]["physical"] == 9
        assert backend["limits"]["max_shots"] == 2048

    def test_the_roles_and_residency_can_be_said(self, tmp_path, capsys):
        code, out, _ = _main(["quantum-card", str(_spec(tmp_path)), "--roles", "provider",
                              "--residency", "DE", "--receipt-schema-version", "1.0",
                              "--receipt-signing-algorithm", "Ed25519"], capsys)
        assert code == 0
        params = json.loads(out)["extension"]["params"]
        assert params["roles"] == ["provider"]
        assert params["data"]["residency"] == ["DE"]


class TestItRefusesClearly:
    def test_a_spec_with_no_quantum_section_says_so(self, tmp_path, capsys):
        path = _spec(tmp_path)
        code, out, _ = _main(["quantum-card", str(path), "--section", "nothing-here"], capsys)
        assert code != 0
        answer = json.loads(out)
        assert "no quantum section named" in answer["error"]
        assert "qpu" in answer["sections"], "a refusal that lists the real names is one a person can act on"

    def test_a_spec_running_no_quantum_backend_at_all_says_so(self, tmp_path, capsys, monkeypatch):
        """The other branch, with a non-quantum spec. It needs the same fake source the core's own CLI
        tests use, because every real source has required config of its own."""
        from theprotocol.proxy import plugins

        monkeypatch.setitem(plugins.BUILTINS["source"], "list_source", "proxy_fake:ListSource")
        doc = F.spec_doc(tmp_path)
        path = tmp_path / "plain.yaml"
        path.write_text(yaml.safe_dump(doc), encoding="utf-8")
        code, out, _ = _main(["quantum-card", str(path)], capsys)
        assert code != 0
        assert "no quantum" in json.loads(out)["error"]

    def test_without_a_receipt_block_it_refuses_and_names_who_owns_it(self, tmp_path, capsys, monkeypatch):
        """Same correction as the card test: (b)'s module is made absent here, so this keeps guarding the
        refusal path after (b) merges instead of turning red on the day it does."""
        monkeypatch.setitem(sys.modules, "theprotocol.quantum.receipts", None)
        code, out, _ = _main(["quantum-card", str(_spec(tmp_path))], capsys)
        assert code != 0
        assert "receipt" in json.loads(out)["error"].lower()

    def test_a_stub_cloud_backend_cannot_be_carded(self, tmp_path, capsys):
        code, out, _ = _main(["quantum-card", str(_spec(tmp_path, backend={
            "kind": "qpu", "id": "ibm-1", "vendor": "ibm"})),
            "--receipt-schema-version", "1.0", "--receipt-signing-algorithm", "Ed25519"], capsys)
        assert code != 0
        assert "stub" in json.loads(out)["error"] or "facts" in json.loads(out)["error"]


class TestTheShippedExampleReallyRuns:
    """A doc example nobody executes is a doc example that rots. These run the shipped spec through the
    real loader and the real card generator, so a field renamed in the code breaks the example here rather
    than in a provider's terminal."""

    def _example(self, tmp_path):
        import shutil
        from pathlib import Path

        src = Path(__file__).resolve().parents[1] / "proxy" / "proxy.quantum.example.yaml"
        assert src.exists(), f"the shipped example is missing: {src}"
        dst = tmp_path / "proxy.quantum.example.yaml"
        shutil.copy(src, dst)
        (tmp_path / ".env.secret").write_text(f"CLIENT_ID={F.CLIENT_ID}\nCLIENT_SECRET={F.CLIENT_SECRET}\n",
                                              encoding="utf-8")
        return dst

    def test_tp_proxy_validate_accepts_the_shipped_example(self, tmp_path, capsys):
        code, out, err = _main(["validate", str(self._example(tmp_path))], capsys)
        assert code == 0, f"the shipped example does not validate: {err or out}"
        answer = json.loads(out)
        assert answer["sinks"] == {"qpu": "quantum_submit"}
        assert answer["sources"] == {"results": "quantum_results"}
        assert answer["actions"] == {"report": "quantum_report"}

    def test_the_example_names_the_permission_the_recipe_needs(self, tmp_path, capsys):
        code, out, _ = _main(["validate", str(self._example(tmp_path))], capsys)
        assert code == 0
        assert json.loads(out)["permissions"] == {"report": ["reputation.signal"]}

    def test_quantum_card_works_on_the_shipped_example(self, tmp_path, capsys):
        code, out, err = _main(["quantum-card", str(self._example(tmp_path)),
                                "--receipt-schema-version", "1.0",
                                "--receipt-signing-algorithm", "Ed25519"], capsys)
        assert code == 0, f"the example's own card command failed: {err or out}"
        params = json.loads(out)["extension"]["params"]
        assert params["backends"][0]["qubits"]["physical"] == 16
        assert params["backends"][0]["limits"]["max_shots"] == 20000
        assert params["backends"][0]["location"]["jurisdiction"] == "EU"
