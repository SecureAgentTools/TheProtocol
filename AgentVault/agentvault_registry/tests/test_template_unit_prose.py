"""§FESUITE V0595 (his word 2026-10-11, "also correct the avt prose in the docs"): the official template bundles name the
registry's own unit, not AVT. 0187 rewrites the Herald template's seeded description where it still stands (and only
there), and 0076's blueprint carries the same words, so a fresh frame and an old one read alike. The migrations are
loaded from their files with a recording stand-in for the database.
"""
import importlib.util
import pathlib
import re

VERSIONS = pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Bind:
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params))


def _run(mod, fn, monkeypatch):
    bind = _Bind()
    monkeypatch.setattr(mod.op, "get_bind", lambda: bind, raising=False)
    getattr(mod, fn)()
    return bind.calls


def test_0187_rewrites_the_seeded_description_only_where_it_still_stands(monkeypatch):
    m = _load("0187_template_unit_prose")
    assert m.down_revision == "0186_operator_application_env" and len(m.revision) <= 32
    (sql, params), = _run(m, "upgrade", monkeypatch)
    assert re.search(r"UPDATE agent_bundles SET description = :now WHERE slug = :slug AND is_official = TRUE AND description = :was", sql)
    assert params == {"now": m.NOW, "slug": "sovereign-herald-v1", "was": m.SEEDED}, "a description its registry changed is left alone"
    assert "AVT" in m.SEEDED and not re.search(r"\b(?:AVT|JDAY|BVT)\b", m.NOW)
    (_, back), = _run(m, "downgrade", monkeypatch)
    assert back == {"now": m.SEEDED, "slug": "sovereign-herald-v1", "was": m.NOW}


def test_the_0076_blueprint_names_no_legacy_unit_and_matches_0187():
    m76 = _load("0076_bdl_seed_templates")
    m87 = _load("0187_template_unit_prose")
    texts = []
    for bp in m76.TEMPLATE_BLUEPRINTS:
        texts += [bp["name"], bp["description"]] + [c["description"] for c in bp.get("capabilities", [])]
    assert len(m76.TEMPLATE_BLUEPRINTS) == 6 and len(texts) > 12
    assert [t for t in texts if re.search(r"\b(?:AVT|JDAY|BVT)\b", t)] == []
    herald = next(bp for bp in m76.TEMPLATE_BLUEPRINTS if bp["slug"] == "sovereign-herald-v1")
    assert herald["description"] == m87.NOW, "a fresh frame and an old one would read different words"
