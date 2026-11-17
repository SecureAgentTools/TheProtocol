"""V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the fast lane's CHECKER, our validation of an organization's content change before its ballot counts
(services/content_changes.check_content; DESIGN_2026-11-15_DISTRIBUTIONS.md section 2, item 1, and the order's build item 2).

  five kinds   kit (a migration kit's files), proxy_spec (the proxy.yaml of one of the organization's templates), policy_value (one key of the
               organization's settings catalog), console_text (one text of the organization's console), branding (its tagline, accent, logo)
  the checks   the schema of its kind; the destinations rule of a kit and a proxy spec (the library's own check_kit); no secret in the text
               (the credential shapes the audit trail screens, and the key-named secrets of a kit); its size
  a refusal    names the rule and the field, never the value, and is raised before anything is written or any vote is cast
"""
from __future__ import annotations

import pytest

from tests.test_workflow_templates_kit_v0664 import MANIFEST, PROXY, kit

from agentvault_registry.services import content_changes as cc

ORG = "org-1"
TEMPLATE = {"id": "wtpl_x", "source_org_id": ORG, "visibility": "org", "kind": "migration"}


def check(kind, target, content, **kw):
    kw.setdefault("org_id", ORG)
    if kind in ("kit", "proxy_spec"):
        kw.setdefault("template", TEMPLATE)
        kw.setdefault("latest_files", kit())
    return cc.check_content(kind, target, content, **kw)


def refused(kind, target, content, *bits, **kw):
    with pytest.raises(cc.ContentRefused) as e:
        check(kind, target, content, **kw)
    for b in bits:
        assert b in e.value.sentence, (b, e.value.sentence)
    return e.value


def test_the_kinds_are_the_whole_list():
    assert cc.KINDS == ("kit", "proxy_spec", "policy_value", "console_text", "branding", "compliance_pack")
    refused("code", "x", {}, "kind")


def test_a_good_kit_passes_and_its_verdict_names_the_rules_it_ran():
    v = check("kit", "wtpl_x", {"files": kit()})
    assert v["ok"] is True and v["kind"] == "kit"
    assert {"schema", "destinations", "secrets", "size"} <= set(v["rules"])
    assert v["bytes"] > 0


def test_a_kit_with_a_written_out_secret_is_refused_naming_the_path_and_never_the_value():
    bad = kit(**{"proxy.yaml": PROXY.replace('password: "env:SOURCE_PASSWORD"', 'password: "hunter2hunter2"')})
    e = refused("kit", "wtpl_x", {"files": bad}, "password")
    assert "hunter2" not in e.sentence


def test_a_kit_naming_a_destination_of_its_own_is_refused_by_the_destinations_rule():
    bad = kit(**{"proxy.yaml": PROXY.replace('table: "${TARGET_TABLE}"', 'table: "${TARGET_TABLE}", host: "db.internal.example.org"')})
    refused("kit", "wtpl_x", {"files": bad})


def test_a_kit_over_the_size_cap_is_refused():
    bad = kit(**{"README.md": "x" * (300 * 1024)})
    refused("kit", "wtpl_x", {"files": bad})


def test_a_proxy_spec_replaces_the_proxy_yaml_of_the_latest_version_and_the_whole_kit_is_checked():
    v = check("proxy_spec", "wtpl_x", {"proxy_yaml": PROXY.replace("batch", "batch")})
    assert v["ok"] is True
    assert v["files"]["proxy.yaml"] == PROXY and v["files"]["migration.yaml"] == MANIFEST      # the rest of the kit stays as it was
    refused("proxy_spec", "wtpl_x", {"proxy_yaml": PROXY.replace('table: "${TARGET_TABLE}"', 'table: "${TARGET_TABLE}", host: "db.internal.example.org"')})   # a destination of its own


def test_a_template_that_is_not_the_organizations_own_is_refused_for_a_kit_and_a_proxy_spec():
    other = {**TEMPLATE, "source_org_id": "org-2"}
    refused("kit", "wtpl_x", {"files": kit()}, "own", template=other)
    refused("proxy_spec", "wtpl_x", {"proxy_yaml": PROXY}, "own", template=other)
    refused("kit", "wtpl_x", {"files": kit()}, "own", template={**TEMPLATE, "source_org_id": None})
    refused("kit", "wtpl_x", {"files": kit()}, "template", template=None)


def test_a_policy_value_is_one_key_of_the_organizations_own_catalog_and_validated_as_the_settings_form_does():
    v = check("policy_value", "liability.mode", {"value": "shadow"})
    assert v["ok"] and v["after"] == "shadow"
    refused("policy_value", "liability.mode", {"value": "bogus-tier"}, "liability.mode")
    refused("policy_value", "contract_offer_ttl_days", {"value": 9999}, "contract_offer_ttl_days")
    refused("policy_value", "name", {"value": "Another Name"}, "not")                 # a column of the organization, not a policy value
    refused("policy_value", "frame.fee_bps", {"value": 5}, "not")                      # nothing global
    refused("policy_value", "liability.mode", {"value": "shadow", "extra": 1}, "field")


def test_a_console_text_has_a_key_a_text_and_no_secret_in_it():
    v = check("console_text", "landing.tagline", {"text": "Ship the quiet kind of release."})
    assert v["ok"] and v["after"] == "Ship the quiet kind of release."
    refused("console_text", "Landing Tagline!", {"text": "x"}, "key")
    refused("console_text", "landing.tagline", {"text": ""}, "text")
    refused("console_text", "landing.tagline", {"text": "y" * 601}, "text")
    e = refused("console_text", "landing.tagline", {"text": "our key is " + "avreg" + "_abcdefghijklmnopqrstuvwxyz0123456789"}, "secret")
    assert "avreg" + "_abcdefghijkl" not in e.sentence
    refused("console_text", "landing.tagline", {"text": "-----BEGIN RSA " + "PRIVATE KEY-----\nMIIB\n-----END RSA " + "PRIVATE KEY-----"}, "secret")   # built here: no key header sits in the source


def test_a_branding_change_names_a_tagline_an_accent_or_a_logo_and_each_is_validated():
    v = check("branding", "branding", {"tagline": "Lyceum", "accent_color": "#12ab9f", "logo_url": "https://lyceum.example.org/logo.svg"})
    assert v["ok"] and v["after"]["accent_color"] == "#12ab9f"
    refused("branding", "branding", {}, "branding")
    refused("branding", "branding", {"accent_color": "red"}, "accent_color")
    refused("branding", "branding", {"logo_url": "http://lyceum.example.org/logo.svg"}, "logo_url")
    refused("branding", "branding", {"logo_url": "https://user:pw@lyceum.example.org/logo.svg"}, "logo_url")
    refused("branding", "branding", {"tagline": "x" * 201}, "tagline")
    refused("branding", "branding", {"tagline": "ok", "background": "#fff"}, "field")


def test_a_target_a_kind_does_not_take_is_refused():
    refused("branding", "something-else", {"tagline": "x"}, "target")


def test_a_whole_change_over_64_kib_is_refused_whatever_its_kind():
    refused("console_text", "landing.body", {"text": "z" * 70000}, "size")


def test_every_refusal_carries_a_code_a_sentence_and_a_reason_list():
    e = refused("branding", "branding", {"accent_color": "red"})
    assert e.code == "checker_refused" and e.sentence and e.reasons and all(isinstance(r, str) for r in e.reasons)


# ── the governing registry: every step and every write of the fast lane asks first (the authority order gwo_e086b25f868da7ec9fce9fd2) ────────────────────────────────

def test_every_step_of_the_flow_and_every_write_of_the_store_asks_the_governing_registry_first():
    import inspect
    flow_writes = {"propose", "vote", "withdraw", "undo"}
    steps = {n for n, f in inspect.getmembers(cc.ContentChangeFlow, inspect.iscoroutinefunction) if not n.startswith("_") and n not in ("view", "list")}
    assert steps == flow_writes, f"a flow step without a gate test: {sorted(steps ^ flow_writes)}"
    for n in flow_writes:
        src = inspect.getsource(getattr(cc.ContentChangeFlow, n))
        first_read = min(i for i in (src.find("self._row("), src.find("self.s."), src.find("self._checked(")) if i >= 0)
        assert 0 <= src.find("self._governing()") < first_read, f"{n} does not call the gate first"
    gated = {"insert", "update", "add_vote", "apply", "undo", "claim_apply"}
    writes = {n for n, f in inspect.getmembers(cc.DbStore, inspect.isfunction)
              if any(w in inspect.getsource(f) for w in ("self.db.add(", "self.db.commit(", "store.insert_version(", "store.update_template(", "_set_settings("))
              and n not in ("_set_settings", "_announce")}       # _announce only reads (does the change name a room?) and ends that read; the card it asks for writes through the chat service
    assert writes <= gated, f"writes of the store without the gate: {sorted(writes - gated)}"
    for n in gated:
        assert "await self.check_governing()" in inspect.getsource(getattr(cc.DbStore, n)), n


async def _refused_on_a_registry_that_does_not_govern(monkeypatch, call):
    from agentvault_registry.services import code_authority as ca
    monkeypatch.setattr(ca, "own_name", lambda: "asia")
    monkeypatch.setenv(ca.ENV, "eu")
    with pytest.raises(cc.CodeChangeRefusal) as e:
        await call(cc.DbStore(None))                          # no database: a write that got past the gate would fail on None, not with the sentence
    assert e.value.code == "code_change_not_governed_here"


@pytest.mark.asyncio
@pytest.mark.parametrize("name,args", [("insert", ({},)), ("update", ("c",)), ("add_vote", ({},)), ("apply", ("o", "console_text", "k", {}, {}, "t")),
                                       ("undo", ("o", "console_text", "k", None, None))])
async def test_each_write_of_the_store_refuses_with_the_sentence_before_it_touches_the_database(monkeypatch, name, args):
    await _refused_on_a_registry_that_does_not_govern(monkeypatch, lambda s: getattr(s, name)(*args))


# ── V0667 D7 (order gwo_0f317438b7dfc6dfacd3e9b7): the compliance pack, the sixth kind ─────────────────────────────────────────────────────────────────────────────
# A regulator's rules as policy within the allowed set: data residency (regions), retention (days), approval thresholds (amounts), reporting (an interval and a label).
# Proposed, checked and voted like any content change; applied to the organization's own space (organizations.settings.compliance_packs[name]).

PACK = {"rules": {"data_residency": {"regions": ["de", "fr"]}, "retention": {"audit_log_days": 2555, "chat_message_days": 365},
                  "approval_thresholds": {"payment_amount": 5000, "contract_amount": 25000}, "reporting": {"interval_days": 90, "label": "Quarterly report to the supervisor"}}}


def test_the_compliance_pack_is_the_sixth_kind():
    assert cc.KINDS[-1] == "compliance_pack" and len(cc.KINDS) == 6


def test_a_pack_inside_the_allowed_set_passes_and_its_verdict_carries_the_rules_it_will_apply():
    v = check("compliance_pack", "eu-retention", PACK)
    assert v["ok"] is True and v["after"] == PACK["rules"] and "allowed_set" in v["rules"]
    assert check("compliance_pack", "eu-retention", {"rules": {"retention": {"audit_log_days": 90}}})["ok"]


@pytest.mark.parametrize("rules,bit", [
    ({"data_sharing": {"partners": ["x"]}}, "data_sharing"),                                    # a rule outside the allowed set
    ({"retention": {"audit_log_days": 30}}, "audit_log_days"),                                  # below the allowed range
    ({"retention": {"audit_log_days": 5000}}, "audit_log_days"),
    ({"retention": {"backup_days": 100}}, "backup_days"),                                       # a sub-rule outside the allowed set
    ({"retention": {}}, "retention"),
    ({"data_residency": {"regions": []}}, "regions"),
    ({"data_residency": {"regions": ["Germany"]}}, "regions"),
    ({"data_residency": {"regions": ["de"] * 21}}, "regions"),
    ({"approval_thresholds": {"payment_amount": -1}}, "payment_amount"),
    ({"approval_thresholds": {"payment_amount": "lots"}}, "payment_amount"),
    ({"reporting": {"interval_days": 10}}, "interval_days"),
    ({"reporting": {"interval_days": 30, "label": "x" * 101}}, "label"),
    ({}, "rules"),
])
def test_a_pack_outside_the_allowed_set_is_refused_naming_the_rule(rules, bit):
    refused("compliance_pack", "eu-retention", {"rules": rules}, bit)


def test_a_pack_has_a_name_and_only_a_rules_field():
    refused("compliance_pack", "BaFin 2026", PACK, "name")
    refused("compliance_pack", "eu-retention", {**PACK, "extra": 1}, "field")
    refused("compliance_pack", "eu-retention", {"rules": "all"}, "rules")


def test_nothing_outside_the_fast_lane_reads_the_compliance_packs_so_no_rail_enforces_one():
    """The pack is a declaration (stored, voted, carried in the signed report) and the console says so in one sentence. That sentence is true only while nothing else reads
    organizations.settings.compliance_packs: a rail that starts to must change this test and the sentence together."""
    import pathlib
    src = pathlib.Path(cc.__file__).resolve().parents[1]
    readers = sorted(str(p.relative_to(src)) for p in src.rglob("*.py") if "static" not in p.parts and "compliance_packs" in p.read_text(encoding="utf-8"))
    assert readers == ["services/compliance_packs.py", "services/content_changes.py"], readers
