#!/usr/bin/env python3
"""sbom.py: the dependency licence scan and a CycloneDX SBOM for TheProtocol's distribution images, offline.

    python3 scripts/distribution/sbom.py \\
        --image theprotocol/registry:stable --image theprotocol/teg-layer:stable --image theprotocol/event-store:stable \\
        --lockfile AgentVault/agentvault_registry/src/agentvault_registry/static/new_registry_frontend/package-lock.json \\
        --out dist/sbom
    python3 scripts/distribution/sbom.py --selftest

Python packages are read from INSIDE each image (importlib.metadata, `--network none`, nothing installed), so the
list is the dependency set that ships. The frontend's npm packages come from its package-lock.json (lockfile v2 and v3
record each package's licence); production and development entries are both scanned and told apart. Writes one
CycloneDX 1.5 JSON per component and `licenses-summary.json`.

Where a package's metadata names no licence, the licence it ships decides: a Python package's licence file in its
dist-info; an npm package's package.json (`license`, or the older `licenses` list) or licence file under
--node-modules-root (default: beside the lockfile), read only when the installed version is the locked one. The text
is matched against a few well-known licences, and every component records where its licence came from
(`theprotocol:licence-source`).

Every licence is put in one class for an AGPL-3.0-or-later server (the SDKs are Apache-2.0 and ship none of these):
  permissive · weak-copyleft (LGPL, MPL) · copyleft-compatible (GPL-3.0, GPL-2.0-or-later, AGPL-3.0) ·
  INCOMPATIBLE (GPL-2.0-only, SSPL, BUSL, Commons Clause, proprietary) · REVIEW (empty, unknown, or unrecognised).
An SPDX `OR` takes its best alternative and `AND` its worst. Exit 1 when anything is INCOMPATIBLE; REVIEW items are
listed for a person to read, never silently passed. `--selftest` runs the classification controls.
"""
from __future__ import annotations
import argparse, json, re, subprocess, sys, tempfile
from pathlib import Path

PY_PROBE = r'''
import importlib.metadata as md, json
def head(d, rel):
    try:
        return d.locate_file(rel).read_text(errors="replace")[:3000]
    except Exception:
        return ""
out = []
for d in md.distributions():
    m = d.metadata
    lic = (m.get("License") or "").strip()
    own = [str(f) for f in (d.files or []) if str(f).split("/")[0].endswith((".dist-info", ".egg-info"))
           and str(f).rsplit("/", 1)[-1].upper().startswith(("LICENSE", "LICENCE", "COPYING"))]
    out.append({"name": m.get("Name"), "version": d.version,
                "expression": (m.get("License-Expression") or "").strip(),
                "license": lic.splitlines()[0][:160] if lic else "",
                "license_text": lic[:3000],
                "licence_file_text": head(d, own[0]) if own else "",
                "classifiers": [c for c in (m.get_all("Classifier") or []) if c.startswith("License ::")]})
print(json.dumps(out))
'''

CLASSIFIER_MAP = {
    "MIT License": "MIT", "BSD License": "BSD", "Apache Software License": "Apache-2.0", "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0", "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "GNU Lesser General Public License v2 or later (LGPLv2+)": "LGPL-2.0-or-later",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0", "GNU Library or Lesser General Public License (LGPL)": "LGPL",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0", "GNU General Public License v2 (GPLv2)": "GPL-2.0",
    "GNU General Public License v2 or later (GPLv2+)": "GPL-2.0-or-later", "The Unlicense (Unlicense)": "Unlicense",
    "Historical Permission Notice and Disclaimer (HPND)": "HPND", "Public Domain": "Public-Domain",
    "zlib/libpng License": "Zlib", "Academic Free License (AFL)": "AFL",
}

INCOMPAT = re.compile(r"(GPL-2\.0-only|GPLv2 only|\bSSPL|Server Side Public|\bBUSL|Business Source|Commons Clause|Proprietary|Elastic License)", re.I)
# EPL and CDDL are weak copyleft too, but the GPL family cannot absorb them: EPL-2.0 only when the author named the GPL as a
# "Secondary License", CDDL never. For an AGPL-3.0 product they are a question for a person, not a pass (elkjs, EPL-2.0,
# reached the V0494 frontend through mermaid 12 as "weak copyleft" and was found by the 2026-09-30 licence review).
GPL_INCOMPAT_WEAK = re.compile(r"(\bEPL|Eclipse Public|\bCDDL|Common Development and Distribution)", re.I)
WEAK = re.compile(r"(\bLGPL|Lesser General Public|Library General Public|\bMPL|Mozilla Public)", re.I)
COMPAT = re.compile(r"(\bAGPL|Affero|GPL-3|GPLv3|GPL-2\.0-or-later|GPLv2\+|GNU General Public License v3)", re.I)
ANY_GPL = re.compile(r"(\bGPL|General Public License)", re.I)
# TCL is SPDX's id for the Tcl/Tk licence, a BSD-style permissive licence (ujson ships `BSD-3-Clause AND TCL`).
PERMISSIVE = re.compile(
    r"(\bMIT\b|MIT-CMU|\bX11\b|\bISC\b|0BSD|\bBSD\b|BSD-[234]-Clause|[23]-Clause BSD|New BSD|Simplified BSD|\bApache\b|"
    r"Apache-2\.0|Unlicense|\bCC0|Public[ -]Domain|\bPSF|Python-2\.0|Python Software Foundation|\bZlib\b|BlueOak-1\.0\.0|"
    r"\bHPND\b|CC-BY-4\.0|\bWTFPL\b|Artistic-2\.0|UPL-1\.0|Unicode|\bAFL\b|MIT-0|\bTCL\b)", re.I)
RANK = {"permissive": 0, "weak-copyleft": 1, "copyleft-compatible": 2, "REVIEW": 3, "INCOMPATIBLE": 4}


def klass(s: str) -> str:
    s = (s or "").strip().strip("()").strip()
    if not s or s.upper() in ("UNKNOWN", "NONE", "UNLICENSED", "SEE LICENSE", "SEE LICENSE FILE") or s.upper().startswith("SEE LICENSE"):
        return "REVIEW"
    if INCOMPAT.search(s):
        return "INCOMPATIBLE"
    if GPL_INCOMPAT_WEAK.search(s):
        return "REVIEW"
    if WEAK.search(s):
        return "weak-copyleft"
    if COMPAT.search(s):
        return "copyleft-compatible"
    if ANY_GPL.search(s):
        return "REVIEW"  # a GPL whose version or "or later" is not stated
    return "permissive" if PERMISSIVE.search(s) else "REVIEW"


def klass_expr(expr: str) -> str:
    e = (expr or "").strip()
    while e.startswith("(") and e.endswith(")") and e.count("(") == 1:
        e = e[1:-1].strip()
    if re.search(r"\s+OR\s+", e, re.I):
        return min((klass_expr(p) for p in re.split(r"\s+OR\s+", e, flags=re.I)), key=RANK.get)
    if re.search(r"\s+AND\s+", e, re.I):
        return max((klass_expr(p) for p in re.split(r"\s+AND\s+", e, flags=re.I)), key=RANK.get)
    return klass(e)


def text_licence(text: str) -> str:
    """Name a licence from its text, copyleft checked first so a text that mentions both is never read as the milder
    one (an LGPL text also says "general public license"). Anything unmatched returns "" and stays REVIEW."""
    t = " ".join((text or "").split()).lower()
    if not t:
        return ""
    if "gnu affero general public license" in t:
        return "AGPL"
    if "gnu lesser general public license" in t or "gnu library general public license" in t:
        return "LGPL"
    if "gnu general public license" in t:
        return "GPL"
    if "mozilla public license" in t and "2.0" in t:
        return "MPL-2.0"
    if "apache license" in t and "version 2.0" in t:
        return "Apache-2.0"
    if "mit license" in t or "permission is hereby granted, free of charge, to any person obtaining a copy" in t:
        return "MIT"
    if "redistribution and use in source and binary forms" in t:
        return "BSD"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in t:
        return "ISC"
    return ""


def py_label(p: dict) -> tuple:
    """(licence, where it came from). The metadata decides first; the shipped licence text only where it names nothing."""
    if p.get("expression"):
        return p["expression"], "metadata-expression"
    lic = p.get("license") or ""
    # a short licence field is a name; a long one is usually the licence TEXT, which the classifiers name better
    if lic and len(lic) <= 60 and lic.upper() not in ("UNKNOWN", "DUAL LICENSE"):
        return lic, "metadata-license"
    mapped = [CLASSIFIER_MAP.get(c.split("::")[-1].strip(), c.split("::")[-1].strip()) for c in p.get("classifiers", [])]
    if mapped:
        return " OR ".join(mapped), "classifier"
    for field, source in (("license_text", "metadata-license-text"), ("licence_file_text", "licence-file")):
        named = text_licence(p.get(field, ""))
        if named:
            return named, source
    return lic, "none"


NO_PYTHON = set()   # images the scan found no Python interpreter in: the summary says so, so a zero is not read as a failed scan


def _no_such_executable(stderr: str) -> bool:
    """The runtime's own words for an entrypoint that does not exist in the image, and nothing else (a permission or a
    resource failure is a real failure to read the image, and refuses)."""
    return "executable file not found" in stderr or ("exec:" in stderr and "no such file or directory" in stderr)


def scan_image(image: str) -> list:
    """The Python distributions an image carries, read by its own interpreter. An image with NO Python interpreter (the
    cert-writer: a shell script around the SPIRE agent binary) carries no Python distributions: that is recorded, never
    refused; its base image's licence is in PUBLIC_DOCS/THIRD_PARTY_SOFTWARE.md. Any other failure to read refuses."""
    for interpreter in ("python", "python3"):
        r = subprocess.run(["docker", "run", "--rm", "--network", "none", "--entrypoint", interpreter, image, "-c", PY_PROBE],
                           capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            break
        if not _no_such_executable(r.stderr):
            raise SystemExit(f"[sbom] REFUSED: could not read {image}: {r.stderr.strip()[-300:]}")
    else:
        NO_PYTHON.add(image.split("/")[-1].split(":")[0])
        print(f"[sbom] {image}: no Python interpreter in the image, so no Python distributions to list")
        return []
    comps = []
    for p in json.loads(r.stdout.strip().splitlines()[-1]):
        if not p.get("name"):
            continue
        label, source = py_label(p)
        comps.append({"name": p["name"], "version": p["version"], "label": label, "source": source,
                      "class": klass_expr(label), "dev": False,
                      "purl": f"pkg:pypi/{p['name'].lower().replace('_', '-')}@{p['version']}"})
    return comps


def npm_installed_licence(pkg_dir: Path, locked_version: str) -> tuple:
    """(licence, source) from an installed package, or ("", "none"). An installed version other than the locked one is
    evidence about a different package and is not used."""
    try:
        meta = json.loads((pkg_dir / "package.json").read_text())
    except (OSError, ValueError):
        return "", "none"
    if meta.get("version") != locked_version:
        return "", "none"
    lic = meta.get("license")
    if isinstance(lic, dict):
        lic = lic.get("type")
    if isinstance(lic, str) and lic.strip():
        return lic.strip(), "package.json"
    older = meta.get("licenses")  # the pre-SPDX list: several entries mean the package may be taken under any of them
    if isinstance(older, list):
        names = [x.get("type") if isinstance(x, dict) else x for x in older]
        names = [n.strip() for n in names if isinstance(n, str) and n.strip()]
        if names:
            return " OR ".join(names), "package.json"
    for f in sorted(pkg_dir.iterdir()):
        if f.is_file() and f.name.upper().startswith(("LICENSE", "LICENCE", "COPYING")):
            named = text_licence(f.read_text(errors="replace")[:3000])
            if named:
                return named, "licence-file"
    return "", "none"


def scan_lockfile(path: Path, root: Path | None = None) -> list:
    d = json.loads(path.read_text())
    if int(d.get("lockfileVersion", 1)) < 2:
        raise SystemExit(f"[sbom] REFUSED: {path} is lockfile v{d.get('lockfileVersion')}; v2 or v3 records licences")
    root = root or path.parent
    comps = []
    for key, v in sorted(d.get("packages", {}).items()):
        if not key.startswith("node_modules/") and "/node_modules/" not in key:
            continue
        name = key.split("node_modules/")[-1]
        label = v.get("license") or ""
        if isinstance(label, dict):
            label = label.get("type", "")
        label, source = (str(label), "lockfile") if label else npm_installed_licence(root / key, v.get("version", ""))
        purl_name = ("%40" + name[1:]) if name.startswith("@") else name
        comps.append({"name": name, "version": v.get("version", ""), "label": label, "source": source,
                      "class": klass_expr(label), "dev": bool(v.get("dev") or v.get("devOptional")),
                      "purl": f"pkg:npm/{purl_name}@{v.get('version', '')}"})
    return comps


def cyclonedx(component: str, version: str, comps: list) -> dict:
    return {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
            "metadata": {"component": {"type": "application", "name": component, "version": version}},
            "components": [{"type": "library", "name": c["name"], "version": c["version"], "purl": c["purl"],
                            "licenses": ([{"license": {"name": c["label"]}}] if c["label"] else []),
                            "properties": [{"name": "theprotocol:licence-class", "value": c["class"]},
                                           {"name": "theprotocol:licence-source", "value": c["source"]},
                                           {"name": "theprotocol:scope", "value": "development" if c["dev"] else "runtime"}]}
                           for c in comps]}


def selftest() -> bool:
    """The controls: every class and every fallback must answer as written, including the ones that must stay REVIEW."""
    ok = True

    def check(name, got, want):
        nonlocal ok
        good = got == want
        print(f"[selftest] {'ok  ' if good else 'FAIL'} {name}: {got!r}" + ("" if good else f" (want {want!r})"))
        ok &= good

    check("MIT", klass_expr("MIT"), "permissive")
    check("an AND with TCL (ujson)", klass_expr("BSD-3-Clause AND TCL"), "permissive")
    check("an OR takes its best alternative", klass_expr("GPL-2.0-only OR MIT"), "permissive")
    check("an AND takes its worst", klass_expr("MIT AND GPL-2.0-only"), "INCOMPATIBLE")
    check("LGPL is weak copyleft", klass_expr("LGPL-3.0-only"), "weak-copyleft")
    check("EPL is a question for a person, not weak copyleft", klass_expr("EPL-2.0"), "REVIEW")
    check("CDDL is a question for a person too", klass_expr("CDDL-1.0"), "REVIEW")
    check("MPL stays weak copyleft", klass_expr("MPL-2.0"), "weak-copyleft")
    check("GPL-2.0-only is incompatible", klass_expr("GPL-2.0-only"), "INCOMPATIBLE")
    check("a GPL without a version is REVIEW", klass_expr("GPL"), "REVIEW")
    check("empty is REVIEW", klass_expr(""), "REVIEW")
    check("unknown words are REVIEW", klass_expr("Some Custom Terms"), "REVIEW")
    mit = "MIT License\n\nCopyright (c) 2020 Someone\n\nPermission is hereby granted, free of charge, to any person obtaining a copy"
    check("an MIT licence file", text_licence(mit), "MIT")
    check("an LGPL text is not read as GPL", text_licence("GNU LESSER GENERAL PUBLIC LICENSE Version 3"), "LGPL")
    check("a GPL text stays REVIEW", klass_expr(text_licence("GNU GENERAL PUBLIC LICENSE Version 2, June 1991")), "REVIEW")
    check("a text naming no licence is empty", text_licence("Copyright (c) 2014, Electronic Arts Inc."), "")
    check("metadata empty: the licence file decides", py_label({"license": "", "classifiers": [], "licence_file_text": mit}), ("MIT", "licence-file"))
    check("a short License field wins over the file", py_label({"license": "BSD-3-Clause", "classifiers": [], "licence_file_text": mit}), ("BSD-3-Clause", "metadata-license"))
    check("nothing anywhere stays REVIEW", klass_expr(py_label({"license": "", "classifiers": []})[0]), "REVIEW")
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        def pkg(name, meta, licence_text=None):
            d = root / "node_modules" / name
            d.mkdir(parents=True)
            (d / "package.json").write_text(json.dumps(meta))
            if licence_text:
                (d / "license").write_text(licence_text)

        pkg("older", {"version": "0.3.1", "licenses": [{"type": "MIT", "url": "https://example.com/LICENSE"}]})
        pkg("fileonly", {"version": "2.1.0"}, mit)
        pkg("drifted", {"version": "9.9.9", "license": "MIT"})
        pkg("nothing", {"version": "1.0.0"})
        lock = root / "package-lock.json"
        lock.write_text(json.dumps({"lockfileVersion": 3, "packages": {
            "": {},
            "node_modules/older": {"version": "0.3.1", "dev": True},
            "node_modules/fileonly": {"version": "2.1.0"},
            "node_modules/drifted": {"version": "1.0.0"},
            "node_modules/nothing": {"version": "1.0.0"},
            "node_modules/locked": {"version": "1.0.0", "license": "ISC"}}}))
        by = {c["name"]: (c["label"], c["source"], c["class"]) for c in scan_lockfile(lock)}
        check("npm: the older licenses list", by["older"], ("MIT", "package.json", "permissive"))
        check("npm: a licence file only", by["fileonly"], ("MIT", "licence-file", "permissive"))
        check("npm: an installed version other than the locked one is not evidence", by["drifted"], ("", "none", "REVIEW"))
        check("npm: nothing anywhere stays REVIEW", by["nothing"], ("", "none", "REVIEW"))
        check("npm: the lockfile's own licence", by["locked"], ("ISC", "lockfile", "permissive"))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", action="append", default=[], help="a distribution image to read Python packages from (repeatable)")
    ap.add_argument("--lockfile", default="", help="the frontend's package-lock.json")
    ap.add_argument("--node-modules-root", default="",
                    help="where the lockfile's node_modules/ paths resolve, for packages whose lock entry names no licence (default: beside the lockfile)")
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        ok = selftest()
        print(f"[selftest] {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 2
    if not a.out:
        ap.error("--out is required")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    targets = [(img.split("/")[-1].split(":")[0], img.split(":")[-1] if ":" in img.split("/")[-1] else "latest", scan_image(img)) for img in a.image]
    if a.lockfile:
        lock = Path(a.lockfile)
        version = json.loads(lock.read_text()).get("version", "")
        targets.append(("frontend", version, scan_lockfile(lock, Path(a.node_modules_root) if a.node_modules_root else None)))
    if not targets:
        print("[sbom] nothing to scan: pass --image and/or --lockfile"); return 2
    summary, bad = {}, 0
    for name, version, comps in targets:
        (out / f"sbom-{name}.cdx.json").write_text(json.dumps(cyclonedx(name, version, comps), indent=1))
        counts = {k: sum(1 for c in comps if c["class"] == k) for k in RANK}
        row = lambda c: {"name": c["name"], "version": c["version"], "licence": c["label"], "source": c["source"],
                         "class": c["class"], "development": c["dev"]}
        flagged = [row(c) for c in comps if c["class"] in ("REVIEW", "INCOMPATIBLE")]
        weak = [row(c) for c in comps if c["class"] == "weak-copyleft"]
        from_text = sum(1 for c in comps if c["source"] in ("licence-file", "metadata-license-text", "package.json"))
        summary[name] = {"version": version, "packages": len(comps), "runtime": sum(1 for c in comps if not c["dev"]),
                         "classes": counts, "named_by_shipped_text_or_package_json": from_text,
                         "flagged": flagged, "weak_copyleft": weak}
        if name in NO_PYTHON:
            summary[name]["python"] = "absent: no Python interpreter in the image, so no Python distributions"
        bad += counts["INCOMPATIBLE"]
        print(f"[sbom] {name}:{version} packages={len(comps)} " + " ".join(f"{k}={v}" for k, v in counts.items())
              + f" (named from shipped text or package.json: {from_text})")
        for f in flagged:
            print(f"[sbom]   {f['class']}: {f['name']} {f['version']} licence={f['licence']!r}{' (development)' if f['development'] else ''}")
        for w in weak:
            print(f"[sbom]   weak-copyleft: {w['name']} {w['version']} licence={w['licence']!r}{' (development)' if w['development'] else ''}")
    (out / "licenses-summary.json").write_text(json.dumps(summary, indent=1))
    print(f"[sbom] wrote {len(targets)} CycloneDX files + licenses-summary.json to {out}")
    if bad:
        print(f"[sbom] FAIL: {bad} INCOMPATIBLE licence(s)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
