#!/usr/bin/env python3
"""PUBLIC_DOCS is GENERATED from the one doc source (§DOCSOURCE, 2026-10-16, his word "ok. i approve. do this autonomously").

The documentation is written in ONE place: the console's doc folder in AgentVault,
    agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs
which every console renders (#/docs, #/operator-docs) and docs.theprotocol.cloud publishes (docs-site/sync-content.mjs).
This script writes the repository's copy, PUBLIC_DOCS, from that folder at a given AgentVault commit, so the repository,
the frame kit and the docs site can no longer drift apart (they did: the repository's governance page still described
the voting model production left on 2026-10-03).

    python3 scripts/distribution/gen_public_docs.py --write [--av-ref <sha>]    # write PUBLIC_DOCS from the pinned (or given)
                                                                                # AgentVault commit, never its working tree
    python3 scripts/distribution/gen_public_docs.py --check [--stack-ref <ref>] # the committed PUBLIC_DOCS at <ref> equals the
                                                                                # generation from that ref's pinned AgentVault;
                                                                                # exit 1 names every difference (the export's G14)

Names other files and scripts link to never change (the MANIFEST maps each source page to its repository name); a page's
links are rewritten for the repository: a console route to the console, a docs-site path to the repository page that
holds it or else to docs.theprotocol.cloud, a link to the public repository's own files to a relative path.
Hand-kept, never generated: PUBLIC_DOCS/LICENSE (the documentation licence) and PUBLIC_DOCS/THIRD_PARTY_SOFTWARE.md.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AV = ROOT / "AgentVault"
DOCS = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/assets/docs"
VIEW = "agentvault_registry/src/agentvault_registry/static/new_registry_frontend/src/views/OperatorDocsView.vue"
OUT = "PUBLIC_DOCS"
KEPT = ("LICENSE", "THIRD_PARTY_SOFTWARE.md")
SITE = "https://docs.theprotocol.cloud"
CONSOLE = "https://theprotocol.cloud"
REPO_BLOB = "https://github.com/SecureAgentTools/TheProtocol/blob/main/"
APP_ROUTES = ("/admin/", "/blog/", "/blueprints/", "/services", "/monetize", "/showcase", "/status", "/desk", "/frame-commander")
MANIFEST = [  # (source page under DOCS, its name under PUBLIC_DOCS)
    ("operator/00_quickstart.md", "00_QUICKSTART.md"),
    ("operator/01_architecture.md", "01_ARCHITECTURE.md"),
    ("operator/02_configuration.md", "02_CONFIGURATION.md"),
    ("operator/03_federation.md", "03_FEDERATION.md"),
    ("operator/04_token_economy.md", "04_TOKEN_ECONOMY.md"),
    ("operator/05_api_reference.md", "05_API_REFERENCE.md"),
    ("operator/06_monitoring.md", "06_MONITORING.md"),
    ("operator/07_troubleshooting.md", "07_TROUBLESHOOTING.md"),
    ("operator/08_security.md", "08_SECURITY.md"),
    ("operator/09_governance.md", "09_GOVERNANCE.md"),
    ("operator/10_compliance.md", "10_COMPLIANCE.md"),
    ("operator/11_sovereign_frames.md", "SOVEREIGN_FRAMES.md"),
    ("operator/12_host_cli.md", "HOST_CLI.md"),
    ("operator/13_ai_assistants.md", "AI_ASSISTANTS.md"),
    ("operator/14_setup_manual.md", "OPERATOR_SETUP_MANUAL.md"),
    ("operator/15_frame_federation.md", "FRAME_FEDERATION.md"),
    ("operator/16_updates.md", "12_UPDATES.md"),
    ("operator/17_legal_for_operators.md", "11_LEGAL_FOR_OPERATORS.md"),
    ("operator/18_canaries.md", "CANARIES.md"),
    ("operator/19_market_simulation.md", "MARKET_SIMULATION.md"),
    ("operator/20_test_verified_development.md", "TEST_VERIFIED_DEVELOPMENT.md"),
    ("operator/21_ai_operations_brief.md", "OPERATOR_CLAUDE.md"),
    ("operator/22_suspension.md", "SUSPENSION.md"),
    ("specs/README.md", "specs/README.md"),
    ("specs/a2a-payment-extension-v1.md", "specs/a2a-payment-extension-v1.md"),
    ("specs/federation-licence-certificate-v1.md", "specs/federation-licence-certificate-v1.md"),
    ("specs/registry-card-v0.6.md", "specs/registry-card-v0.6.md"),
    ("specs/registry-card-v0.6.schema.json", "specs/registry-card-v0.6.schema.json"),
    ("specs/supply-audit-standard-v1.0.md", "specs/supply-audit-standard-v1.0.md"),
]
OPTIONAL = [  # generated references: shipped when the source holds them
    ("reference/api.md", "reference/API.md"),
    ("reference/mcp-tools.md", "reference/MCP_TOOLS.md"),
]
LINK = re.compile(r"\]\(([^)\s]+)\)")
ENTRY = re.compile(r"\{\s*section:\s*'(\w+)',\s*slug:\s*'([^']+)',\s*title:\s*(?:'((?:[^'\\]|\\.)*)'|\"([^\"]*)\"),\s*src:\s*'([^']+)'"
                   r"(?:,\s*docsNum:\s*'(\d+)')?")
CHAPTER = re.compile(r"\{ id: '(\d+)', number: '\d+', title: '((?:[^'\\]|\\.)*)', subtitle: '((?:[^'\\]|\\.)*)', content: ch\d+")


def git(args: list[str], cwd: Path, binary: bool = False):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=True)
    return r.stdout if binary else r.stdout.decode("utf-8")


def pinned(stack_ref: str) -> str:
    out = git(["ls-tree", stack_ref, "AgentVault"], ROOT).split()
    if len(out) < 3 or out[1] != "commit":
        raise SystemExit(f"{stack_ref} pins no AgentVault commit")
    return out[2]


def av_file(av_ref: str, rel: str, binary: bool = False):
    try:
        return git(["show", f"{av_ref}:{rel}"], AV, binary)
    except subprocess.CalledProcessError:
        return None


def site_map(stack_ref: str):
    """the docs site's pages, as docs-site/content-map.mjs at the stack ref lists them"""
    text = git(["show", f"{stack_ref}:docs-site/content-map.mjs"], ROOT)
    pages = [{"section": m.group(1), "slug": m.group(2), "title": (m.group(3) or m.group(4) or "").replace("\\'", "'"),
              "src": m.group(5), "num": m.group(6)} for m in ENTRY.finditer(text)]
    if len(pages) < 20:
        raise SystemExit(f"docs-site/content-map.mjs at {stack_ref}: {len(pages)} pages read, too few to trust")
    return pages


def rewrite(text: str, depth: int, pages, names: dict[str, str]) -> str:
    """the source's link forms, made to work in the repository (a page at PUBLIC_DOCS/<depth dirs>/)"""
    by_num = {p["num"]: p for p in pages if p["num"]}
    by_path = {f"/{p['section']}/{p['slug']}": p for p in pages}
    up = "../" * depth

    def repo_or_site(path: str, anchor: str, page) -> str:
        name = names.get(page["src"]) if page else None
        return f"{up}{name}{anchor}" if name else f"{SITE}{path}{anchor}"

    def one(m: re.Match) -> str:
        t = m.group(1)
        if t.startswith(REPO_BLOB):
            rel = t[len(REPO_BLOB):]
            return "](" + (up + rel[len(OUT) + 1:] if rel.startswith(OUT + "/") else "../" * (depth + 1) + rel) + ")"
        d = re.fullmatch(r"/docs/(\d{1,2})(#[\w-]+)?", t)
        if d:
            p = by_num.get(d.group(1).zfill(2))
            if p:
                return "](" + repo_or_site(f"/{p['section']}/{p['slug']}", d.group(2) or "", p) + ")"
            return f"]({CONSOLE}/#/docs/{d.group(1)}{d.group(2) or ''})"
        s = re.fullmatch(r"(/(?:learn|build|operate|reference)/[\w-]+)(#[\w-]+)?", t)
        if s:
            return "](" + repo_or_site(s.group(1), s.group(2) or "", by_path.get(s.group(1))) + ")"
        if any(t == r or t == r.rstrip("/") or t.startswith(r) for r in APP_ROUTES):
            return f"]({CONSOLE}{t})"
        return m.group(0)

    return LINK.sub(one, text)


def header(src: str) -> str:
    return (f"<!-- GENERATED from AgentVault/{DOCS}/{src} by scripts/distribution/gen_public_docs.py. Edit that file, not this "
            "copy: the export refuses a copy that differs from its source. -->\n\n")


def first_heading(text: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else "?"


def build(stack_ref: str, av_ref: str | None = None) -> dict[str, bytes]:
    av_ref = av_ref or pinned(stack_ref)
    pages = site_map(stack_ref)
    entries = list(MANIFEST) + [e for e in OPTIONAL if av_file(av_ref, f"{DOCS}/{e[0]}") is not None]
    names = {src: name for src, name in entries}
    out: dict[str, bytes] = {}
    for src, name in entries:
        raw = av_file(av_ref, f"{DOCS}/{src}", binary=True)
        if raw is None:
            raise SystemExit(f"AgentVault {av_ref[:12]} holds no {DOCS}/{src}")
        if not name.endswith(".md"):
            out[name] = raw
            continue
        body = rewrite(raw.decode("utf-8"), name.count("/"), pages, names)
        out[name] = (header(src) + body).encode("utf-8")
    out["README.md"] = index(av_ref, pages, entries, out).encode("utf-8")
    return out


def index(av_ref: str, pages, entries, out: dict[str, bytes]) -> str:
    view = av_file(av_ref, VIEW) or ""
    chapters = {f"operator/{cid}": (t.replace("\\'", "'"), s.replace("\\'", "'")) for cid, t, s in CHAPTER.findall(view)}
    lines = ["<!-- GENERATED by scripts/distribution/gen_public_docs.py from the one doc source; do not edit. -->", "",
             "# Documentation", "",
             "Everything here is generated from one source: the console's doc folder in this repository, "
             f"[`AgentVault/{DOCS}`](../AgentVault/{DOCS}). Every console renders the same pages (`#/docs` and "
             f"`#/operator-docs`), and [docs.theprotocol.cloud]({SITE}) publishes them. To change a page, edit its source "
             "there; the export refuses a copy here that differs from it.", "",
             "## Run a registry or a frame", "", "| Page | What it covers |", "|---|---|"]
    for src, name in entries:
        if not src.startswith("operator/"):
            continue
        cid = src.split("/")[1][:2]
        title, sub = chapters.get(f"operator/{cid}", (first_heading(out[name].decode()), ""))
        lines.append(f"| [{title}]({name}) | {sub} |")
    lines += ["", "## Specifications", "", "| Specification | File |", "|---|---|"]
    for src, name in entries:
        if src.startswith("specs/") and name.endswith(".md") and not name.endswith("README.md"):
            lines.append(f"| {first_heading(out[name].decode())} | [{name.split('/')[-1]}]({name}) |")
    lines.append(f"| The registry card's JSON Schema | [registry-card-v0.6.schema.json](specs/registry-card-v0.6.schema.json) |")
    refs = [(src, name) for src, name in entries if src.startswith("reference/")]
    if refs:
        lines += ["", "## Reference, generated from the code", ""]
        lines += [f"- [{first_heading(out[name].decode())}]({name})" for _s, name in refs]
    lines += ["", "## Learn and build", "",
              f"The concepts and the developer guides are published at [docs.theprotocol.cloud]({SITE}) (and in every "
              "console at `#/docs`):", ""]
    for sec, label in (("learn", "Learn"), ("build", "Build"), ("reference", "Reference")):
        items = [f"[{p['title']}]({SITE}/{sec}/{p['slug']})" for p in pages if p["section"] == sec]
        if items:
            lines.append(f"- **{label}:** " + " · ".join(items))
    lines += ["", "## Kept by hand", "",
              "- [THIRD_PARTY_SOFTWARE.md](THIRD_PARTY_SOFTWARE.md): third-party software in the images and the kit.",
              "- [LICENSE](LICENSE): the documentation is licensed under CC BY 4.0; the code is not (see "
              "[LICENSING.md](../LICENSING.md)).", ""]
    return "\n".join(lines)


def committed(stack_ref: str) -> dict[str, bytes]:
    names = [n for n in git(["ls-tree", "-r", "--name-only", stack_ref, OUT], ROOT).splitlines() if n]
    return {n[len(OUT) + 1:]: git(["show", f"{stack_ref}:{n}"], ROOT, binary=True) for n in names}


def differences(expected: dict[str, bytes], actual: dict[str, bytes]) -> list[str]:
    diffs = []
    for name, data in sorted(expected.items()):
        if name not in actual:
            diffs.append(f"{OUT}/{name}: missing (the source holds it)")
        elif actual[name] != data:
            diffs.append(f"{OUT}/{name}: differs from its source")
    for name in sorted(set(actual) - set(expected) - set(KEPT)):
        diffs.append(f"{OUT}/{name}: neither generated nor kept by hand")
    return diffs


def check(stack_ref: str = "HEAD") -> list[str]:
    return differences(build(stack_ref), committed(stack_ref))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="write PUBLIC_DOCS in the working tree")
    g.add_argument("--check", action="store_true", help="the committed PUBLIC_DOCS equals the generation")
    ap.add_argument("--stack-ref", default="HEAD")
    ap.add_argument("--av-ref", default=None, help="the AgentVault commit to read (default: the one the stack ref pins)")
    a = ap.parse_args()
    if a.check:
        diffs = check(a.stack_ref)
        for d in diffs:
            print(d)
        print(f"[public-docs] {a.stack_ref}: {'IN STEP with its source' if not diffs else f'{len(diffs)} difference(s)'}")
        return 1 if diffs else 0
    files = build(a.stack_ref, a.av_ref)
    base = ROOT / OUT
    current = {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}
    for name, data in sorted(files.items()):
        p = base / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists() or p.read_bytes() != data:
            p.write_bytes(data)
            print(f"  wrote {OUT}/{name}")
    for name in sorted(current - set(files) - set(KEPT)):
        (base / name).unlink()
        print(f"  removed {OUT}/{name} (neither generated nor kept by hand)")
    print(f"[public-docs] {len(files)} file(s) from AgentVault {(a.av_ref or pinned(a.stack_ref))[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
