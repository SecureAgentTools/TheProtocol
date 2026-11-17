#!/usr/bin/env python3
"""The proxy catalog and the shared mapping vectors, GENERATED into the console (V0664, C1; the gen_public_docs.py pattern).

The proxy and migration consoles (C3, C4) build their forms from what the SDK accepts, never from a second copy of it:

    theprotocol-sdk  `tp-proxy catalog --json`            every built-in plugin with its config_schema, the spec's CORE_SCHEMA,
                                                          the migration manifest schema, the value-node vocabulary
                     tests/data/mapping_vectors.json     the cases the Python mapping and the console's TypeScript port both run

    AgentVault       agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/data/proxy/
                         catalog.generated.json           the catalog, plus "generated_by"
                         mapping_vectors.generated.json   the vectors, plus "generated_by"
                         recipes.generated.json           the eight recipes (C3, gwo_4110e12c): each README's title and five
                                                          sections, its "Try it locally" commands, its row of the recipes
                                                          table, and proxy.yaml as its file text

    python3 scripts/distribution/gen_proxy_catalog.py --write [--av-dir <AgentVault checkout>]   # write both files
    python3 scripts/distribution/gen_proxy_catalog.py --check [--av-dir <AgentVault checkout>]   # exit 1 naming each file that
                                                                                                # differs from a fresh generation
    (--av-dir defaults to <stack>/AgentVault. --check never writes.)

The catalog is made by running the SDK of THIS tree (theprotocol-sdk/src) with the Python that runs this script: that Python needs the
SDK's own dependencies (the sdk-ref venv has them). It is the same whichever optional extras are installed, because a plugin's drivers
are imported when it starts, not when its class loads; a plugin that does not load at all is never written (the catalog would differ by
machine), and the run stops naming it. The SDK version is in the catalog: bump it and --check fails until --write is run.
Exit: 0 written or equal; 1 a file differs or is missing; 2 a usage error or a catalog that could not be made.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any, Dict, List

HERE = pathlib.Path(__file__).resolve().parent
STACK = HERE.parents[1]
SDK_SRC = STACK / "theprotocol-sdk" / "src"
VECTORS = STACK / "theprotocol-sdk" / "tests" / "data" / "mapping_vectors.json"
RECIPES = STACK / "theprotocol-sdk" / "proxy" / "recipes"
DATA = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/data/proxy"
CATALOG_FILE, VECTORS_FILE, RECIPES_FILE = "catalog.generated.json", "mapping_vectors.generated.json", "recipes.generated.json"
GENERATED_BY = "scripts/distribution/gen_proxy_catalog.py --write"


class Unmade(Exception):
    """The catalog could not be made (not a difference between files: a usage or an environment problem)."""


def fresh_catalog() -> Dict[str, Any]:
    env = dict(os.environ, PYTHONPATH=str(SDK_SRC))
    r = subprocess.run([sys.executable, "-m", "theprotocol.proxy.cli", "catalog", "--json"], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise Unmade("tp-proxy catalog failed (does this Python have the SDK's dependencies? the sdk-ref venv does): "
                     + (r.stderr.strip().splitlines() or ["no message"])[-1][:200])
    try:
        return json.loads(r.stdout)
    except ValueError as e:
        raise Unmade(f"tp-proxy catalog did not print JSON ({e})") from None


def problems_in(doc: Dict[str, Any]) -> List[str]:
    return [f"the {p['kind']} plugin {p['name']!r} does not load ({p['error']}): a catalog made on this machine would differ from one made on another"
            for items in doc["plugins"].values() for p in items if p.get("error")]


# A recipe README's five sections, in order: each opens with its bold lead-in (the recipes' one shape)
SECTIONS = (("legacy", "The legacy side."), ("on_theprotocol", "On TheProtocol."), ("needs", "What it needs."),
            ("try_it", "Try it locally."), ("check", "Check it."))
_TITLE = re.compile(r"^# ([A-Z][A-Z0-9]*): (.+)$")
_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.S | re.M)
TABLE_KEYS = ("legacy_system", "source", "on_theprotocol", "out")


def read_recipe(d: pathlib.Path) -> Dict[str, Any]:
    """One recipe folder: its README read into its parts, proxy.yaml as text. A README that lost a part is refused, naming
    the recipe and the part, so the console never shows half a recipe."""
    try:
        readme = (d / "README.md").read_text(encoding="utf-8")
        spec = (d / "proxy.yaml").read_text(encoding="utf-8")
    except OSError as e:
        raise Unmade(f"the recipe {d.name}: {type(e).__name__} reading its README.md or proxy.yaml") from None
    m = _TITLE.match(readme.splitlines()[0] if readme else "")
    if not m:
        raise Unmade(f"the recipe {d.name}: its README has no title line '# NAME: what it does'")
    out: Dict[str, Any] = {"id": d.name, "name": m.group(1), "summary": m.group(2).strip()}
    at = []
    for key, lead in SECTIONS:
        i = readme.find(f"**{lead}**")
        if i < 0:
            raise Unmade(f"the recipe {d.name}: its README lost the section '{lead}'")
        at.append((key, lead, i))
    for n, (key, lead, i) in enumerate(at):
        end = at[n + 1][2] if n + 1 < len(at) else len(readme)
        body = readme[i + len(lead) + 4:end]
        if key == "try_it":
            f = _FENCE.search(body)
            if not f:
                raise Unmade(f"the recipe {d.name}: its 'Try it locally' section lost its command block")
            out["commands"] = [ln.rstrip() for ln in f.group(1).splitlines() if ln.strip()]
            body = body[:f.start()]
        out[key] = " ".join(body.split())
    out["proxy_yaml"] = spec
    return out


def recipes_table() -> Dict[str, Dict[str, str]]:
    """The recipes README's table: recipe id -> its row (the legacy system, source, on TheProtocol, out)."""
    rows: Dict[str, Dict[str, str]] = {}
    for line in (RECIPES / "README.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        m = re.match(r"^\[([a-z0-9-]+)\]\(", cells[0]) if cells else None
        if m and len(cells) == 5:
            rows[m.group(1)] = dict(zip(TABLE_KEYS, cells[1:]))
    return rows


def fresh_recipes() -> Dict[str, Any]:
    table = recipes_table()
    recipes = []
    for d in sorted(p for p in RECIPES.iterdir() if p.is_dir()):
        r = read_recipe(d)
        if d.name not in table:
            raise Unmade(f"the recipe {d.name} has no row in {RECIPES / 'README.md'}")
        r["table"] = table[d.name]
        recipes.append(r)
    return {"schema": "theprotocol.proxy.recipes/v1", "recipes": recipes}


def _text(doc: Any, sort_keys: bool) -> str:
    return json.dumps(doc, sort_keys=sort_keys, indent=1, ensure_ascii=False) + "\n"


def generate() -> Dict[str, str]:
    """file name -> the text it must hold."""
    cat = fresh_catalog()
    bad = problems_in(cat)
    if bad:
        raise Unmade("; ".join(bad))
    cat["generated_by"] = GENERATED_BY
    try:
        vec = json.loads(VECTORS.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Unmade(f"{VECTORS} could not be read ({type(e).__name__})") from None
    vec["generated_by"] = GENERATED_BY
    rec = fresh_recipes()
    rec["generated_by"] = GENERATED_BY
    return {CATALOG_FILE: _text(cat, True), VECTORS_FILE: _text(vec, False), RECIPES_FILE: _text(rec, False)}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write or check the console's copy of the proxy catalog and the mapping vectors.")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--av-dir", default=str(STACK / "AgentVault"), help="the AgentVault checkout (default <stack>/AgentVault)")
    a = ap.parse_args(argv)
    if a.write == a.check:
        print("gen_proxy_catalog: give exactly one of --write and --check", file=sys.stderr)
        return 2
    out = pathlib.Path(a.av_dir) / DATA
    try:
        want = generate()
    except Unmade as e:
        print(f"gen_proxy_catalog: {e}", file=sys.stderr)
        return 2
    if a.write:
        out.mkdir(parents=True, exist_ok=True)
        for name, text in want.items():
            (out / name).write_text(text, encoding="utf-8")
            print(f"wrote {out / name} ({len(text)} bytes)")
        return 0
    bad = 0
    for name, text in want.items():
        p = out / name
        if not p.is_file():
            print(f"missing: {p} (run --write)")
            bad = 1
        elif p.read_text(encoding="utf-8") != text:
            print(f"differs: {p} (run --write)")
            bad = 1
    if not bad:
        print(f"equal: {out / CATALOG_FILE}, {out / VECTORS_FILE}, {out / RECIPES_FILE}")
    return bad


if __name__ == "__main__":
    sys.exit(main())
