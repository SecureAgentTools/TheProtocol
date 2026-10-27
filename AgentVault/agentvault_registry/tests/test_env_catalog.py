"""§FESUITE V0595 (his word 2026-10-11: "we need env setup in the application forms. but we need to map all the flags ...
the env flips that are frame exclusive should be still displayed for operators but greyed out and not chooseable").

The configuration catalog (services/env_catalog.py) is the ONE source the Frame Commander, the operator application and
the provisioner read. Before it, the Frame Commander's 23 switches lived only in the console and no server code turned a
chosen key into an env flag, and an operator application had no configuration at all. Pinned here: the catalog's shape,
what an operator may and may not choose, the env lines a choice means, how a registry's own option is read (an unset
flag is the code's default, a value the catalog does not write is "unknown"), the public view, the application route's
refusal of a frame-scope key, the provisioner writing (and re-validating) the choices, and the frame request's
features checked against the same catalog (old consoles' yes/no translated, never refused).
"""
import asyncio
import io
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from agentvault_registry.services import env_catalog as ec


def test_every_entry_is_well_formed():
    assert len({e.key for e in ec.CATALOG}) == len(ec.CATALOG), "a key twice"
    for e in ec.CATALOG:
        assert e.group in ec.GROUPS, e.key
        assert e.default in e.options and e.unset_means in e.options, e.key
        assert e.scope in ("frame", "operator"), e.key
        assert set(e.writes) == set(e.options), e.key
        assert all(e.primary in w for w in e.writes.values()), f"{e.key}: every option writes the primary flag"
        if e.scope == "frame":
            assert e.reason, f"{e.key}: an operator is told why it is the frame's"
        if e.pair:
            assert ec.BY_KEY[e.pair].pair == e.key and ec.BY_KEY[e.pair].options == e.options, e.key


def _console_file(rel):
    p = Path(__file__).resolve().parents[1] / "src/agentvault_registry/static/new_registry_frontend/src" / rel
    if not p.exists():
        pytest.skip("the console source is not beside this test")
    return p.read_text()


def test_the_consoles_switch_list_is_the_catalog():
    """The Frame Commander renders services/api/frameRequests.ts's FRAME_FEATURE_SWITCHES (generated from this catalog):
    every key, label, default, option and hint the same, in the same order, or the form offers what the server cannot
    apply (regenerate it from services/env_catalog.py)."""
    body = _console_file("services/api/frameRequests.ts")
    body = body[body.index("export const FRAME_FEATURE_SWITCHES"):]
    body = body[:body.index("\n]")]
    # a commented-out entry is not rendered, so it is not counted
    body = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("//"))
    rows = re.findall(r"\{ key: '([a-z0-9_]+)', label: '((?:[^'\\]|\\.)*)', def: '([^']+)', options: \[([^\]]*)\],\s*hint: '((?:[^'\\]|\\.)*)' \}", body)
    assert len(rows) == len(ec.CATALOG), f"{len(rows)} switches in the console, {len(ec.CATALOG)} in the catalog"
    for (key, label, default, opts, hint), e in zip(rows, ec.CATALOG):
        assert key == e.key, (key, e.key)
        assert (label.replace("\\'", "'"), default, hint.replace("\\'", "'")) == (e.label, e.default, e.hint), key
        assert [o.strip().strip("'") for o in opts.split(",")] == list(e.options), key


def test_the_consoles_groups_are_the_catalogs():
    body = _console_file("services/frameRequestForm.ts")
    body = body[body.index("export const FEATURE_GROUPS"):]
    body = body[:body.index("\n]")]
    body = "\n".join(line for line in body.splitlines() if not line.lstrip().startswith("//"))
    groups = re.findall(r"\{ id: '([a-z]+)', keys: \[([^\]]*)\] \}", body)
    assert [g for g, _ in groups] == list(ec.GROUPS)
    for g, keys in groups:
        assert [k.strip().strip("'") for k in keys.split(",") if k.strip()] == [e.key for e in ec.CATALOG if e.group == g], g


def test_an_operator_chooses_only_what_it_runs():
    clean, errors = ec.validate_choices({"liability_card": "enforce", "contract_templates": "yes", "guild": "no"}, "operator")
    assert errors == [] and clean == {"liability_card": "enforce", "contract_templates": "yes", "guild": "no"}
    clean, errors = ec.validate_choices({"staking": "yes", "agent_permissions": "off", "fiat_onramp": "yes"}, "operator")
    assert clean == {} and len(errors) == 3
    assert all("set by the frame" in e for e in errors), errors


def test_unknown_keys_and_options_are_refused_with_the_reason():
    clean, errors = ec.validate_choices({"no_such_thing": "yes", "liability_card": "maybe"}, "operator")
    assert clean == {}
    assert any("not a setting" in e for e in errors) and any("not one of off, shadow, enforce" in e for e in errors), errors


def test_a_pair_moves_together_for_a_frame():
    clean, errors = ec.validate_choices({"agent_permissions": "enforce"}, "frame")
    assert errors == [] and clean == {"agent_permissions": "enforce", "delegation": "enforce"}
    _clean, errors = ec.validate_choices({"agent_permissions": "enforce", "delegation": "off"}, "frame")
    assert errors and "move together" in errors[0]


def test_the_env_lines_a_choice_means():
    lines = dict(ec.env_lines({"liability_card": "enforce", "sub_agent_wallets": "yes", "zk_proofs": "no"}))
    assert lines["LIABILITY_MODE"] == "enforce"
    assert lines["AGENT_SPAWN_ENABLED"] == "true" and lines["SPAWN_WALLET_ANCHOR_MODE"] == "on"
    assert all(lines[f"ZKP_PHASE_{i}_ENABLED"] == "false" for i in range(1, 6))


def test_a_registrys_own_option_is_read_never_guessed():
    e = ec.BY_KEY["liability_card"]
    assert ec.current_option(e, {}) == ("off", "default")
    assert ec.current_option(e, {"LIABILITY_MODE": "Enforce"}) == ("enforce", "set")
    assert ec.current_option(e, {"LIABILITY_MODE": "sometimes"}) == (None, "unknown")
    s = ec.BY_KEY["staking"]
    assert ec.current_option(s, {}) == ("yes", "default"), "STAKING_ENABLED is on where unset (core/staking_gate.py)"
    assert ec.current_option(s, {"STAKING_ENABLED": "false"}) == ("no", "set")


def test_the_public_view_names_every_entry_and_the_registrys_role():
    v = ec.public_view({"LIABILITY_MODE": "shadow"}, "operator")
    assert v["role"] == "operator" and v["groups"] == list(ec.GROUPS)
    by = {x["key"]: x for x in v["entries"]}
    assert len(by) == len(ec.CATALOG)
    assert by["liability_card"]["current"] == "shadow" and by["liability_card"]["current_source"] == "set"
    assert by["staking"]["scope"] == "frame" and by["staking"]["reason"]


def test_the_application_route_refuses_a_frame_scope_setting():
    from agentvault_registry import schemas
    from agentvault_registry.routers import operator_applications as oa
    fn = getattr(oa.submit_operator_application, "__wrapped__", oa.submit_operator_application)
    body = schemas.OperatorApplicationCreate(name="Ines", email="ines@example.com", accept_operator_terms=True,
                                             env_choices={"staking": "yes"})
    with pytest.raises(HTTPException) as e:
        asyncio.run(fn(request=None, application=body, db=None))   # refused before the database is asked
    assert e.value.status_code == 422 and "set by the frame" in str(e.value.detail)


def test_the_provisioner_writes_the_choices_and_skips_what_the_catalog_refuses():
    from agentvault_registry.services import cloud_provisioner as cp
    out = io.StringIO()
    written = cp._write_env_choices(out, {"liability_card": "enforce", "staking": "yes"})
    text = out.getvalue()
    assert written == ["LIABILITY_MODE"] and "LIABILITY_MODE=enforce\n" in text
    assert "STAKING_ENABLED" not in text, "a frame-scope key in a hand-edited row reached the operator's env"
    out2 = io.StringIO()
    assert cp._write_env_choices(out2, {}) == [] and out2.getvalue() == ""


def test_a_frame_requests_features_are_checked_against_the_catalog():
    from pydantic import ValidationError
    from agentvault_registry.routers.operator_self_service import FrameRequestAnswers
    a = FrameRequestAnswers(features={"liability_card": "yes", "agent_permissions": "enforce", "staking": "no"}).normalized()
    assert a["features"]["liability_card"] == "shadow", "an older console's yes is translated, not refused"
    assert a["features"]["delegation"] == "enforce", "the pair came along"
    with pytest.raises(ValidationError):
        FrameRequestAnswers(features={"no_such_thing": "yes"})


def test_the_admin_review_shows_the_env_the_features_mean():
    import datetime
    from agentvault_registry import schemas
    now = datetime.datetime.now(datetime.timezone.utc)
    row = schemas.FrameRequestAdminRead(id="fr-1", status="pending", contact_name="Ines", contact_email="i@example.com",
                                        answers={"features": {"guild": "no", "liability_card": "enforce"}},
                                        created_at=now, updated_at=now)
    assert "GUILD_ENABLED=false" in row.env_preview and "LIABILITY_MODE=enforce" in row.env_preview
