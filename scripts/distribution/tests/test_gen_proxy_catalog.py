"""V0664 consoles (C1, gwo_f1c49a39bfe4eaf7ce9d240d): gen_proxy_catalog.py writes the proxy catalog and the shared mapping vectors into
the console, and --check says when the console's copy differs from a fresh one (the gen_public_docs.py pattern).

  src/data/proxy/catalog.generated.json          what `tp-proxy catalog --json` prints, plus "generated_by"
  src/data/proxy/mapping_vectors.generated.json  theprotocol-sdk/tests/data/mapping_vectors.json, plus "generated_by"

Run with a Python that has the SDK's own dependencies (the sdk-ref venv): the generator runs the SDK's CLI from this tree's source.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPT = HERE.parent / "gen_proxy_catalog.py"
STACK = HERE.parents[2]
DATA = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/data/proxy"

SPEC = importlib.util.spec_from_file_location("gen_proxy_catalog", SCRIPT)
G = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G)


def _run(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True)


@pytest.fixture
def av(tmp_path):
    return tmp_path / "av"


def test_write_makes_both_files_from_the_live_sdk(av):
    r = _run("--write", "--av-dir", av)
    assert r.returncode == 0, r.stderr
    cat = json.loads((av / DATA / "catalog.generated.json").read_text(encoding="utf-8"))
    vec = json.loads((av / DATA / "mapping_vectors.generated.json").read_text(encoding="utf-8"))
    assert cat["schema"] == "theprotocol.proxy.catalog/v1" and cat["generated_by"].startswith("scripts/distribution/gen_proxy_catalog.py")
    assert {p["name"] for p in cat["plugins"]["sink"]} >= {"sql_upsert", "rest", "file_out", "webhook"}
    source = json.loads((STACK / "theprotocol-sdk/tests/data/mapping_vectors.json").read_text(encoding="utf-8"))
    assert vec["cases"] == source["cases"] and vec["schema"] == source["schema"] and vec["generated_by"] == cat["generated_by"]


def test_check_passes_on_what_write_made_and_prints_nothing_to_fix(av):
    assert _run("--write", "--av-dir", av).returncode == 0
    r = _run("--check", "--av-dir", av)
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_names_a_file_that_differs_and_exits_1(av):
    assert _run("--write", "--av-dir", av).returncode == 0
    f = av / DATA / "catalog.generated.json"
    doc = json.loads(f.read_text(encoding="utf-8"))
    doc["sdk_version"] = "0.0.0-edited"
    f.write_text(json.dumps(doc, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    r = _run("--check", "--av-dir", av)
    assert r.returncode == 1 and "catalog.generated.json" in r.stdout and "mapping_vectors" not in r.stdout
    f = av / DATA / "mapping_vectors.generated.json"
    doc = json.loads(f.read_text(encoding="utf-8"))
    doc["cases"][0]["expect"] = {"f": "changed"}
    f.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    r = _run("--check", "--av-dir", av)
    assert r.returncode == 1 and "mapping_vectors.generated.json" in r.stdout


def test_check_fails_when_a_file_is_missing(av):
    assert _run("--write", "--av-dir", av).returncode == 0
    (av / DATA / "mapping_vectors.generated.json").unlink()
    r = _run("--check", "--av-dir", av)
    assert r.returncode == 1 and "missing" in r.stdout and "mapping_vectors.generated.json" in r.stdout
    shutil.rmtree(av)
    assert _run("--check", "--av-dir", av).returncode == 1


def test_check_does_not_write(av):
    assert _run("--check", "--av-dir", av).returncode == 1
    assert not av.exists()


def test_a_run_needs_exactly_one_mode_and_a_real_folder():
    assert _run("--av-dir", "x").returncode == 2
    assert _run("--write", "--check", "--av-dir", "x").returncode == 2


def test_a_catalog_with_a_plugin_that_does_not_load_is_never_written(av, monkeypatch):
    """A catalog made without an optional part would differ by machine: the generator refuses it, naming the part."""
    doc = G.fresh_catalog()
    doc["plugins"]["sink"][0] = {"kind": "sink", "name": "broken", "class": "x:Y", "internal": False, "error": "ModuleNotFoundError"}
    assert G.problems_in(doc) and "broken" in G.problems_in(doc)[0] and "ModuleNotFoundError" in G.problems_in(doc)[0]


def test_the_vectors_file_the_console_gets_is_the_one_the_sdk_tests_read(av):
    assert _run("--write", "--av-dir", av).returncode == 0
    got = json.loads((av / DATA / "mapping_vectors.generated.json").read_text(encoding="utf-8"))
    assert len(got["cases"]) >= 80


# ── C3 (gwo_4110e12c11a69a93de878829): the eight recipes, so the proxy console shows each with its run commands ──────────
# src/data/proxy/recipes.generated.json: every recipe under theprotocol-sdk/proxy/recipes/ (its README's title line and
# five sections, the command block of "Try it locally", the row of the recipes table, proxy.yaml as its file text).

RECIPES = STACK / "theprotocol-sdk" / "proxy" / "recipes"
IDS = ["bazaar", "dynamo", "hansa", "keystone", "lyceum", "meridian", "scrivener", "trunk"]


def test_write_makes_the_recipes_file_from_the_sdks_recipes(av):
    assert _run("--write", "--av-dir", av).returncode == 0
    doc = json.loads((av / DATA / "recipes.generated.json").read_text(encoding="utf-8"))
    assert doc["schema"] == "theprotocol.proxy.recipes/v1" and doc["generated_by"].startswith("scripts/distribution/")
    assert [r["id"] for r in doc["recipes"]] == IDS
    for r in doc["recipes"]:
        assert r["name"] == r["id"].upper() and r["summary"], r["id"]
        for k in ("legacy", "on_theprotocol", "needs", "try_it", "check"):
            assert r[k] and "**" not in r[k], (r["id"], k)
        assert r["commands"] and r["commands"][0].startswith("tp-proxy validate"), r["id"]
        assert r["proxy_yaml"] == (RECIPES / r["id"] / "proxy.yaml").read_text(encoding="utf-8"), "the file text, never a parsed copy"
        assert set(r["table"]) == {"legacy_system", "source", "on_theprotocol", "out"}, r["id"]
    assert doc["recipes"][IDS.index("lyceum")]["table"]["source"] == "file drop (CSV)"


def test_check_names_the_recipes_file_when_it_differs_or_is_missing(av):
    assert _run("--write", "--av-dir", av).returncode == 0
    f = av / DATA / "recipes.generated.json"
    doc = json.loads(f.read_text(encoding="utf-8"))
    doc["recipes"][0]["commands"] = ["tp-proxy run edited.yaml"]
    f.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    r = _run("--check", "--av-dir", av)
    assert r.returncode == 1 and "differs" in r.stdout and "recipes.generated.json" in r.stdout
    f.unlink()
    r = _run("--check", "--av-dir", av)
    assert r.returncode == 1 and "missing" in r.stdout and "recipes.generated.json" in r.stdout


def _recipe(tmp_path, readme, yaml_text="version: 1\n"):
    d = tmp_path / "recipes" / "demo"
    d.mkdir(parents=True)
    (d / "README.md").write_text(readme, encoding="utf-8")
    (d / "proxy.yaml").write_text(yaml_text, encoding="utf-8")
    return d


GOOD = """# DEMO: a demo bridge

Intro words.

**The legacy side.** It exports `rows`.

**On TheProtocol.** Each row is attested.

**What it needs.** An `attestor`.

**Try it locally.** Run the fake. Then:

```
tp-proxy validate proxy.yaml
tp-proxy run proxy.yaml --dry-run            # what it would send
```

**Check it.** Read the record.
"""


def test_a_readme_is_read_into_its_parts(tmp_path):
    r = G.read_recipe(_recipe(tmp_path, GOOD))
    assert (r["id"], r["name"], r["summary"]) == ("demo", "DEMO", "a demo bridge")
    assert r["legacy"] == "It exports `rows`." and r["needs"] == "An `attestor`." and r["check"] == "Read the record."
    assert r["try_it"] == "Run the fake. Then:"
    assert r["commands"] == ["tp-proxy validate proxy.yaml", "tp-proxy run proxy.yaml --dry-run            # what it would send"]


@pytest.mark.parametrize("broken,named", [
    (GOOD.replace("**What it needs.** An `attestor`.\n\n", ""), "What it needs."),
    (GOOD.replace("```\ntp-proxy validate proxy.yaml\ntp-proxy run proxy.yaml --dry-run            # what it would send\n```\n", ""),
     "command block"),
    (GOOD.replace("# DEMO: a demo bridge", "# A demo bridge"), "title line"),
])
def test_a_readme_that_lost_a_part_is_refused_naming_it(tmp_path, broken, named):
    with pytest.raises(G.Unmade) as e:
        G.read_recipe(_recipe(tmp_path, broken))
    assert "demo" in str(e.value) and named in str(e.value)
