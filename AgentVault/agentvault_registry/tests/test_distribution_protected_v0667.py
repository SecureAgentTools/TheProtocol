"""V0667 D6 (gwo_65c7b7d9, session-release): the protected-set check of a distribution build against its base release.

DESIGN_2026-11-15_DISTRIBUTIONS.md section 10: federation (peer trust, the frame licence, the registry card and its signature,
the federation routes), compliance (the legal texts, the audit records, the supply audit and the auditor's reads), money (the
TEG rails, the emission policy) and identity (SPIFFE, mTLS, authentication) stay byte-identical to the base release, or the
build is refused. The report lists every removed module and switch beside the verdict.

The trees here are maps {repo-relative path: content hash}, the shape services.distribution_protected.tree_of reads from a
git commit (blob ids) or a file tree (sha256): equal hashes mean equal bytes."""
import hashlib
import os

import pytest

from agentvault_registry.services import distribution_protected as dp

R = "agentvault_registry/src/agentvault_registry"


def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# one real file per area: a one-byte change in it must refuse the build
ONE_PER_AREA = {
    "federation": f"{R}/services/registry_card_signer.py",
    "compliance": f"{R}/routers/legal.py",
    "money": f"{R}/routers/teg_integration.py",
    "identity": f"{R}/security.py",
}
OPEN_PATH = f"{R}/static/new_registry_frontend/src/views/Contributions.vue"
OPTIONAL_MODULE = f"{R}/arena/mount.py"


def base_tree():
    t = {p: h(p.encode()) for p in ONE_PER_AREA.values()}
    t[OPEN_PATH] = h(b"<template>base</template>")
    t[OPTIONAL_MODULE] = h(b"def mount_games(app): ...")
    t[f"{R}/arena/robowars.py"] = h(b"robowars")
    t["agentvault_teg_layer_mvp/src/teg_core_service/api/v1/endpoints_token.py"] = h(b"teg")
    return t


def test_identical_trees_are_intact():
    v = dp.verdict(base_tree(), dict(base_tree()))
    assert v["verdict"] == "intact"
    assert v["refusals"] == []
    assert set(v["areas"]) == {"federation", "compliance", "money", "identity", "build"}


@pytest.mark.parametrize("area,path", sorted(ONE_PER_AREA.items()))
def test_a_one_byte_change_in_each_area_refuses(area, path):
    base = base_tree()
    dist = dict(base)
    dist[path] = h(path.encode() + b" ")          # one byte more
    v = dp.verdict(base, dist)
    assert v["verdict"] == "refused"
    assert {"area": area, "path": path, "kind": "changed"} in v["refusals"]
    assert v["areas"][area]["changed"] == [path]


def test_a_change_in_an_open_path_is_intact():
    base = base_tree()
    dist = dict(base)
    dist[OPEN_PATH] = h(b"<template>the team's own view</template>")
    v = dp.verdict(base, dist)
    assert v["verdict"] == "intact"
    assert v["refusals"] == []


def test_a_new_file_in_a_protected_area_refuses():
    base = base_tree()
    dist = dict(base)
    dist[f"{R}/routers/federation_extra.py"] = h(b"new route")
    v = dp.verdict(base, dist)
    assert v["verdict"] == "refused"
    assert {"area": "federation", "path": f"{R}/routers/federation_extra.py", "kind": "added"} in v["refusals"]


def test_a_removed_protected_file_refuses():
    base = base_tree()
    dist = dict(base)
    del dist[ONE_PER_AREA["identity"]]
    v = dp.verdict(base, dist)
    assert v["verdict"] == "refused"
    assert {"area": "identity", "path": ONE_PER_AREA["identity"], "kind": "removed"} in v["refusals"]


def test_a_removed_optional_module_is_listed_and_does_not_refuse():
    base = base_tree()
    dist = dict(base)
    del dist[OPTIONAL_MODULE]
    del dist[f"{R}/arena/robowars.py"]
    v = dp.verdict(base, dist, switches_base={"GAMES_ENABLED": "true"}, switches_dist={"GAMES_ENABLED": "false"})
    assert v["verdict"] == "intact"
    assert v["removed"]["modules"] == ["agentvault_registry.arena.mount", "agentvault_registry.arena.robowars"]
    assert v["removed"]["switches"] == [{"name": "GAMES_ENABLED", "base": "true", "distribution": "false"}]


def test_the_teg_source_is_money():
    p = "agentvault_teg_layer_mvp/src/teg_core_service/api/v1/endpoints_token.py"
    assert dp.classify(p) == "money"
    base = base_tree()
    dist = dict(base)
    dist[p] = h(b"teg!")
    assert dp.verdict(base, dist)["verdict"] == "refused"


def test_classify_names_one_area_or_none():
    assert dp.classify(OPEN_PATH) is None
    for area, path in ONE_PER_AREA.items():
        assert dp.classify(path) == area


def test_trees_of_different_hash_kinds_are_refused_not_compared():
    base = dp.Tree(kind="git", files=base_tree())
    dist = dp.Tree(kind="sha256", files=base_tree())
    with pytest.raises(ValueError, match="hash kinds differ"):
        dp.verdict(base, dist)


def test_parse_ls_tree_reads_git_output():
    """tree_of runs `git ls-tree -r -z --full-tree <ref>` (the pipeline host has git; the image does not); its parser:"""
    out = (b"100644 blob 1111111111111111111111111111111111111111\tagentvault_registry/src/agentvault_registry/security.py\0"
           b"100755 blob 2222222222222222222222222222222222222222\tagentvault_teg_layer_mvp/run.sh\0"
           b"160000 commit 3333333333333333333333333333333333333333\tsome/submodule\0")
    t = dp.parse_ls_tree(out)
    assert t.kind == "git"
    assert t.files == {"agentvault_registry/src/agentvault_registry/security.py": "1" * 40,
                       "agentvault_teg_layer_mvp/run.sh": "2" * 40, "some/submodule": "3" * 40}


def test_tree_of_files_reads_a_directory(tmp_path):
    root = tmp_path / "app"
    (root / "agentvault_registry/src/agentvault_registry").mkdir(parents=True)
    (root / "agentvault_registry/src/agentvault_registry/security.py").write_bytes(b"x = 1\n")
    t = dp.tree_of_files(str(root))
    assert t.kind == "sha256"
    assert t.files == {"agentvault_registry/src/agentvault_registry/security.py": h(b"x = 1\n")}


def test_every_registry_pattern_matches_a_real_file():
    """The list cannot rot quietly: each registry pattern names at least one file in this tree's source (a pattern that
    matches nothing protects nothing). The TEG and the repository root are not in the registry's test layout."""
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.normpath(os.path.join(here, "..", "src", "agentvault_registry"))
    files = []
    # followlinks: CI's image-build layout links the staged console source into the image's tree (ci.yml: "ln -s /w/fe_src
    # $F/src"), and os.walk does not enter a linked directory by default (Forgejo run 3205, session-code seq 5627)
    for d, _dirs, fs in os.walk(src, followlinks=True):
        for f in fs:
            files.append("agentvault_registry/" + os.path.relpath(os.path.join(d, f), os.path.join(here, "..")).replace(os.sep, "/"))
    missing = [p for p in dp.registry_patterns() if not any(dp.matches(p, f) for f in files)]
    assert missing == []


# ── session-lead seq 5532: the four additions ─────────────────────────────────────────────────────────────────────────
# (1) the build's own inputs are protected (added and deleted files refuse too, above)
@pytest.mark.parametrize("path", [
    "agentvault_registry/Dockerfile", "agentvault_registry/requirements.txt", "agentvault_registry/poetry.lock",
    "agentvault_registry/gunicorn_conf.py", "agentvault_registry/pyproject.toml", "agentvault_registry/constraints-dist.txt",
    f"{R}/static/new_registry_frontend/package-lock.json", f"{R}/static/new_registry_frontend/package.json",
])
def test_the_build_inputs_are_protected(path):
    assert dp.classify(path) == "build"
    base = dict(base_tree(), **{path: h(b"x")})
    dist = dict(base, **{path: h(b"x ")})
    v = dp.verdict(base, dist)
    assert {"area": "build", "path": path, "kind": "changed"} in v["refusals"]


def check(dist_sources, base_extra=None):
    """full_check over a base of the four representative files plus base_extra, and a distribution that adds or changes
    the files in dist_sources (path -> source text)."""
    base_src = {p: p for p in ONE_PER_AREA.values()}
    base_src.update(base_extra or {})
    dist_src = dict(base_src, **dist_sources)
    base = {p: h(s.encode()) for p, s in base_src.items()}
    dist = {p: h(s.encode()) for p, s in dist_src.items()}
    return dp.full_check(base, dist, read_dist=lambda p: dist_src[p].encode())


# (2) a changed file outside the set may not patch a protected module
@pytest.mark.parametrize("src,line,what", [
    ("from agentvault_registry import security\n\nsecurity.verify = lambda *a: True\n", 3, "assigns security.verify"),
    ("import agentvault_registry.security as s\ns.verify = None\n", 2, "assigns s.verify"),
    ("from agentvault_registry import security\nsetattr(security, 'verify', None)\n", 2, "setattr on security"),
    ("from agentvault_registry.routers import legal\ndel legal.router\n", 2, "deletes legal.router"),
    ("import sys\nsys.modules['agentvault_registry.security'] = object()\n", 2, "writes sys.modules"),
    ("import sys\nsys.modules.update({})\n", 2, "writes sys.modules"),
    ("import importlib\nimportlib.reload(object())\n", 2, "importlib.reload"),
])
def test_patching_a_protected_module_from_outside_refuses(src, line, what):
    p = f"{R}/services/team_tweak.py"
    v = check({p: src})
    assert v["verdict"] == "refused"
    hits = [r for r in v["refusals"] if r["kind"] == "patches_protected"]
    assert hits and hits[0]["path"] == p and hits[0]["line"] == line and what in hits[0]["what"]


def test_an_open_change_that_patches_nothing_is_intact_and_the_limits_are_named():
    p = f"{R}/services/team_view.py"
    v = check({p: "from agentvault_registry import security\n\ndef who(x):\n    return security.__name__ + str(x)\n"})
    assert v["verdict"] == "intact"
    assert v["scan"]["files"] == 1
    assert "cannot see" in v["scan"]["limits"]


def test_what_the_scan_cannot_see_is_noted_not_refused():
    p = f"{R}/services/team_dyn.py"
    v = check({p: "import importlib\nm = importlib.import_module('agentvault_' + 'registry.security')\nexec('x = 1')\n"})
    assert v["verdict"] == "intact"
    notes = v["scan"]["unseen"]
    assert {"path": p, "line": 2, "what": "importlib.import_module with a computed name"} in notes
    assert {"path": p, "line": 3, "what": "exec"} in notes


def test_a_file_that_does_not_parse_refuses():
    p = f"{R}/services/team_broken.py"
    v = check({p: "def (\n"})
    assert v["verdict"] == "refused"
    assert any(r["kind"] == "unparsable" and r["path"] == p for r in v["refusals"])


# (3) a distribution's migration may only create its own tables
MIG = "agentvault_registry/alembic/versions"


def test_a_migration_that_creates_its_own_table_is_intact():
    src = ('from alembic import op\nimport sqlalchemy as sa\nrevision = "0300_lyceum_notes"\ndown_revision = "0238_x"\n'
           'def upgrade():\n    op.create_table("lyceum_notes", sa.Column("id", sa.String(40), primary_key=True))\n'
           '    op.create_index("ix_lyceum_notes_id", "lyceum_notes", ["id"])\n'
           'def downgrade():\n    op.drop_index("ix_lyceum_notes_id", table_name="lyceum_notes")\n    op.drop_table("lyceum_notes")\n')
    v = check({f"{MIG}/0300_lyceum_notes.py": src})
    assert v["verdict"] == "intact", v["refusals"]
    assert v["migrations"] == [{"path": f"{MIG}/0300_lyceum_notes.py", "creates": ["lyceum_notes"]}]


@pytest.mark.parametrize("body,what", [
    ('    op.add_column("developers", sa.Column("x", sa.String(4)))\n', "add_column on developers"),
    ('    op.create_index("ix_dev_x", "developers", ["x"])\n', "create_index on developers"),
    ('    op.execute("update developers set x = 1")\n', "op.execute"),
    ('    op.drop_table("agents")\n', "drop_table on agents"),
])
def test_a_migration_that_touches_an_existing_table_or_runs_raw_sql_refuses(body, what):
    src = ('from alembic import op\nimport sqlalchemy as sa\nrevision = "0300_bad"\ndown_revision = "0238_x"\n'
           'def upgrade():\n' + body + 'def downgrade():\n    pass\n')
    v = check({f"{MIG}/0300_bad.py": src})
    assert v["verdict"] == "refused"
    hits = [r for r in v["refusals"] if r["kind"] == "migration"]
    assert hits and what in hits[0]["what"] and hits[0]["line"] == 6


def test_a_changed_or_removed_base_migration_refuses():
    old = f"{MIG}/0231_code_distributions.py"
    v = check({old: "# edited\n"}, base_extra={old: "revision = '0231'\n"})
    assert any(r["kind"] == "migration" and r["path"] == old and "changes a base migration" in r["what"] for r in v["refusals"])
