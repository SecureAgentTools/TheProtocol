"""§SUITES1018 (2026-10-18): both agent builders build their bundles from the files the TREE carries.

The api-tester's authenticated sweep on sbx-alpha (V0623) read POST /agent-builder/generate-template as 500
"Template file missing: .env.j2. Backend configuration incomplete.": the generator renders common_zkp/.env.j2,
.env.secret.example.j2 and mcp_server/lib/{auth,config,http_client}.js.j2, and agentvault_registry/.gitignore's `.env.*`
and `lib/` had kept them out of git since the reality sync, so every image built from a clean checkout lacked them (the
shared checkout and the old working-tree images had them). The second builder (POST /agent-builder/generate) rendered
common/.env.example.j2, missing the same way. The env templates are named dotenv*.j2 in the tree now (a file named .env*
never reaches git: the .gitignore and the pre-commit hook refuse env files) and keep their .env names in the bundles.

These build every bundle through the real generators and loaders, so a template the code renders and the tree lacks
fails here, in CI's clean checkout, and not in a downloaded bundle. RED on a clean checkout of 9ac0925c.
"""
from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

import pytest

from agentvault_registry import schemas
from agentvault_registry.routers import agent_builder as ab
from agentvault_registry.routers import agent_builder_templates as abt

TEMPLATE_IDS = list(schemas.TemplateDownloadConfig.model_fields["template_id"].annotation.__args__)


@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_every_template_builds_its_bundle(template_id):
    cfg = schemas.TemplateDownloadConfig(
        template_id=template_id, agent_name="Bundle Check", human_readable_id="bundle-check",
        agent_did="did:theprotocol:0f0e0d0c-0b0a-4908-8706-050403020100", client_id="agent-0123abcd")
    blob = abt._generate_bundle(cfg)
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    for name in (".env", ".env.secret.example", "mcp/lib/auth.js", "mcp/lib/config.js", "mcp/lib/http_client.js"):
        assert f"bundle-check/{name}" in names, (name, sorted(names)[:30])


@pytest.mark.parametrize("builder_type", ["simple_wrapper", "adk_agent"])
async def test_both_package_types_build(builder_type):
    extra = ({"wrapper_llm_backend_type": "openai_api", "wrapper_model_name": "gpt-4o-mini"}
             if builder_type == "simple_wrapper" else {"adk_model_name": "gemini-2.0-flash", "adk_instruction": "answer briefly"})
    cfg = schemas.AgentBuildConfig(agent_name="Package Check", agent_description="a check",
                                   human_readable_id="check-org/package-check", agent_builder_type=builder_type, **extra)
    dev = SimpleNamespace(id=1, name="Check", email="check@example.test")
    resp = await ab.generate_agent_package(cfg, current_developer=dev)
    names = zipfile.ZipFile(resp.path).namelist()
    assert ".env.example" in names and "dotenv.example" not in names, sorted(names)


def test_the_env_templates_are_in_the_tree_and_hold_placeholders_only():
    for path in (abt.COMMON_ZKP_DIR / "dotenv.j2", abt.COMMON_ZKP_DIR / "dotenv.secret.example.j2",
                 ab.COMMON_TEMPLATE_DIR / "dotenv.example.j2"):
        text = path.read_text()
        assert "REPLACE" in text or "{{" in text or "..." in text, path
