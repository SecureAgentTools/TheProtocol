"""§MCPTEST30 (V0640): a client's bundle template choice never answers 500, and the registry lists what it has.

POST /api/v1/onboard/download-bundle answered 500 "Template 'full-capacity' not available. Contact administrator." for
Agent Forge's featured template on every frame stood up since 2026-09-07 (its directory was a host bind mount on Frame
A), and read any name outside the catalogue as "full-capacity" (agentvault2-66, 2026-10-24; agentvault2-d6's terms).
Pinned: GET /onboard/bundle-templates lists the templates whose directory exists, in Agent Forge's order, with the
first as the default; a template the registry does not have, or a name outside the catalogue, answers 404 naming the
ones it has, before anything is read.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import agent_bundle as B

DEV = SimpleNamespace(id=7)


class _NoDb:
    async def execute(self, _stmt):
        raise AssertionError("the template check comes before any read")


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    (tmp_path / "minimal").mkdir()
    (tmp_path / "ppao").mkdir()
    monkeypatch.setattr(B, "TEMPLATE_DIR", tmp_path / "absent-full-capacity")
    monkeypatch.setattr(B, "MINIMAL_TEMPLATE_DIR", tmp_path / "minimal")
    monkeypatch.setattr(B, "PPAO_TEMPLATE_DIR", tmp_path / "ppao")
    return tmp_path


def _ask(template_type):
    req = B.BundleRequest(agent_did="did:theprotocol:x", client_id="agent-c", client_secret="s",
                          template_type=template_type)
    return asyncio.run(B.download_bundle(req, current_developer=DEV, db=_NoDb()))


def test_the_registry_lists_the_templates_it_has_in_forge_order(dirs):
    assert B.available_templates() == ["minimal", "ppao"]
    assert asyncio.run(B.bundle_templates(current_developer=DEV)) == {"templates": ["minimal", "ppao"],
                                                                       "default": "minimal"}


@pytest.mark.parametrize("asked", ["full-capacity", "no-such-template"])
def test_a_template_the_registry_does_not_have_answers_404_naming_what_it_has(dirs, asked):
    with pytest.raises(HTTPException) as e:
        _ask(asked)
    assert e.value.status_code == 404
    assert e.value.detail == f"Template '{asked}' is not available on this registry; it has: minimal, ppao"


def test_a_registry_with_no_template_says_none(dirs, monkeypatch):
    monkeypatch.setattr(B, "MINIMAL_TEMPLATE_DIR", dirs / "gone")
    monkeypatch.setattr(B, "PPAO_TEMPLATE_DIR", dirs / "gone-too")
    assert asyncio.run(B.bundle_templates(current_developer=DEV)) == {"templates": [], "default": None}
    with pytest.raises(HTTPException) as e:
        _ask("minimal")
    assert e.value.status_code == 404 and e.value.detail.endswith("it has: none")
