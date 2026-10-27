"""§MCPTEST30 (V0559): a registry names itself to a peer the way its card does, never by its container label.

Measured 2026-10-03 on the sandbox (journal 50's flow): sbxbetaop's REGISTRY_NAME is "cloud-op-sbxbetaop" (the
provisioner's container label, for cache keys and channels), while its signed card, its SPIFFE path and its parent's peer
row say "sbxbetaop". Its federal ballot named the label, so Sandbox Beta refused it (403 registry_mismatch: "the ballot
names another operator than its caller"), and no cloud operator anywhere could cast. One rule now names the registry on
the card, in the ballot and in an elevated proposal: registry_card_builder.federation_name().
"""
import ast
import pathlib

from agentvault_registry.config import settings
from agentvault_registry.routers import governance
from agentvault_registry.services import federation_ballot as fb
from agentvault_registry.services import registry_card_builder as rcb


def _as_operator(monkeypatch):
    monkeypatch.setattr(settings, "REGISTRY_NAME", "cloud-op-sbxbetaop")
    monkeypatch.setenv("REGISTRY_FEDERATION_NAME", "sbxbetaop")
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-b.theprotocol.cloud")


def test_an_operator_ballot_names_the_operator_as_its_card_and_spiffe_path_do(monkeypatch):
    _as_operator(monkeypatch)
    me = fb.own_identity()
    assert me["name"] == "sbxbetaop"
    assert me["id"] == "registry:sandbox-b.theprotocol.cloud/sbxbetaop"
    # the host's check: the ballot's registry name against the caller's SPIFFE path segment
    _td, segs = fb.split_spiffe("spiffe://sandbox-b.theprotocol.cloud/operator/sbxbetaop/registry")
    assert fb.registry_name_slug(me["name"]) == fb.registry_name_slug(segs[1])


def test_control_the_container_label_is_what_the_host_refused(monkeypatch):
    _as_operator(monkeypatch)
    _td, segs = fb.split_spiffe("spiffe://sandbox-b.theprotocol.cloud/operator/sbxbetaop/registry")
    assert fb.registry_name_slug(settings.REGISTRY_NAME) != fb.registry_name_slug(segs[1])


def test_a_mainframe_without_a_federation_name_keeps_its_registry_name(monkeypatch):
    monkeypatch.setattr(settings, "REGISTRY_NAME", "Sandbox Alpha")
    monkeypatch.delenv("REGISTRY_FEDERATION_NAME", raising=False)
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", "sandbox-a.theprotocol.cloud")
    assert fb.own_identity()["id"] == "registry:sandbox-a.theprotocol.cloud/sandbox-alpha"
    assert rcb.federation_name() == "Sandbox Alpha"


def _src(mod):
    return pathlib.Path(mod.__file__).read_text()


def test_the_card_the_ballot_and_the_elevation_ask_one_rule():
    card = _src(rcb)
    assert card.count("_federation_name = federation_name()") == 1
    ballot_fn = next(n for n in ast.walk(ast.parse(_src(fb))) if isinstance(n, ast.FunctionDef) and n.name == "own_identity")
    names = {n.id for n in ast.walk(ballot_fn) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(ballot_fn) if isinstance(n, ast.Attribute)}
    assert "federation_name" in names and "REGISTRY_NAME" not in attrs
    assert 'registry_name = federation_name() or "Unknown Registry"' in _src(governance)
    assert 'os.getenv("REGISTRY_NAME", "Unknown Registry")' not in _src(governance)
