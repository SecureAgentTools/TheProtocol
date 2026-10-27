"""§TESTBED (2026-09-19): the emission census in a release image.

The kit's release image ships bytecode only, and the federation suite ran inside a kit sandbox: the census found 0 emit
sites, its self-check went red and the emit-site check called every event type in the ledger an orphan. Neither was a
finding about the code; the image had no source to read. The census now says so (a named skip), while a tree that HAS
source and yields no census stays red: that is the failure the self-check exists for.
"""
import pytest

from agentvault_registry.api_tests.federation_suite.rig import PreconditionUnmet
from agentvault_registry.api_tests.federation_suite.tests import test_event_emission_contract as c


def test_a_bytecode_only_package_is_not_measured_and_says_why(tmp_path, monkeypatch):
    pkg = tmp_path / "agentvault_registry"
    (pkg / "routers").mkdir(parents=True)
    (pkg / "__init__.pyc").write_bytes(b"\x00")
    (pkg / "routers" / "teg_integration.pyc").write_bytes(b"\x00")
    monkeypatch.setattr(c, "_registry_root", lambda: str(pkg))
    with pytest.raises(PreconditionUnmet) as exc:
        c._census()
    assert "bytecode only" in str(exc.value) and "2 .pyc files, 0 .py" in str(exc.value)


def test_the_shipped_test_suite_does_not_count_as_source(tmp_path, monkeypatch):
    """A release image ships api_tests as .py beside a bytecode-only package (measured on the dev3 kit image)."""
    pkg = tmp_path / "agentvault_registry"
    (pkg / "api_tests" / "federation_suite").mkdir(parents=True)
    (pkg / "api_tests" / "federation_suite" / "runner.py").write_text("x = 1\n")
    (pkg / "test_seed.py").write_text("x = 1\n")         # the seed scripts compose runs by name ship as source too
    (pkg / "routers").mkdir()
    for i in range(40):
        (pkg / "routers" / f"m{i}.pyc").write_bytes(b"\x00")
    monkeypatch.setattr(c, "_registry_root", lambda: str(pkg))
    with pytest.raises(PreconditionUnmet):
        c._census()


def test_a_tree_with_source_and_no_emit_sites_is_still_an_empty_census(tmp_path, monkeypatch):
    """The control: source present, nothing found -> [] (the self-check turns that red), never a skip."""
    pkg = tmp_path / "agentvault_registry"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("x = 1\n")
    (pkg / "stale.pyc").write_bytes(b"\x00")
    monkeypatch.setattr(c, "_registry_root", lambda: str(pkg))
    assert c._census() == []


def test_the_real_tree_still_has_a_census():
    assert len(c._census()) > 100
