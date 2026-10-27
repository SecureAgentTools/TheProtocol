"""§INGRESS404 (2026-09-26): a TEG never dials a peer registry's cached console address without its port.

Measured: the federation suite's delta->alpha payment was refused "Target TEG rejected transfer" (no funds moved)
because sbxbetaop's TEG sent the FX ingress prepare to `https://sandbox-b.theprotocol.cloud/api/v1/cross-teg/prepare`
(443, sbx-beta's console: 404). The address came from a FALLBACK that fed the peer's cached url to
`_to_internal_mtls_url`, which returns an unknown public host as it is; the main lookup passes it through
`_smart_https_url` first. Seen on the 09-20..22 nightlies and at 14:41Z today, right after an operator restart left its
topology cache cold. RED control: the tree before §INGRESS404 fails every test here (no `_teg_dial_url`, and both
fallbacks still call `_to_internal_mtls_url(fed_url)`).
"""
from __future__ import annotations

import ast
import os
import pathlib
import socket

import pytest

_HERE = pathlib.Path(__file__).resolve()
_PKG = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")
SRC = _PKG / "routers" / "teg_integration.py"
NAMES = ("_is_rfc1918", "_smart_https_url", "_to_internal_mtls_url", "_teg_dial_url")


def _fns():
    """The four functions from the module source, compiled on their own (no app import, no settings)."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in NAMES]
    assert sorted(n.name for n in nodes) == sorted(NAMES), [n.name for n in nodes]
    ns = {"Optional": __import__("typing").Optional}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SRC), "exec"), ns)
    return ns


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "93.184.216.34")  # a public address (example.com), not this host's


@pytest.fixture
def bridge_dns(monkeypatch):
    monkeypatch.setattr(socket, "gethostbyname", lambda h: "172.16.94.14")


def test_a_portless_console_address_gets_the_mtls_port(public_dns):
    f = _fns()
    assert f["_to_internal_mtls_url"]("https://sandbox-b.theprotocol.cloud") == "https://sandbox-b.theprotocol.cloud", \
        "the defect: the mapping alone keeps the console address"
    assert f["_teg_dial_url"]("https://sandbox-b.theprotocol.cloud") == "https://sandbox-b.theprotocol.cloud:8443"


def test_on_the_bridge_the_container_port_is_used(bridge_dns):
    f = _fns()
    assert f["_teg_dial_url"]("https://sandbox-b.theprotocol.cloud") == "https://sandbox-b.theprotocol.cloud:8443"


def test_an_explicit_port_is_kept_where_the_main_lookup_keeps_it(public_dns):
    f = _fns()
    assert f["_teg_dial_url"]("https://sbxbetaop.op.theprotocol.cloud:8443") == "https://sbxbetaop.op.theprotocol.cloud:8443"
    assert f["_teg_dial_url"]("https://example.test:27343") == "https://example.test:27343"
    assert f["_teg_dial_url"]("") == ""


def test_both_fallbacks_use_it_and_none_dials_the_raw_cached_url():
    text = SRC.read_text(encoding="utf-8")
    assert text.count("teg_url = _teg_dial_url(fed_url)") == 2, "the transfer's add-partner and the FX 1:1 leg"
    assert "_to_internal_mtls_url(fed_url)" not in text
