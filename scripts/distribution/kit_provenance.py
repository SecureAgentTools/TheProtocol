#!/usr/bin/env python3
"""What a kit build was built FROM, so a test report can say which code it measured.

The kit a stranger downloads is a `git archive` of one release commit: no history travels with it. The export writes
KIT_FILES.sha256 at the kit's root (one `sha256  path` line per released file), and this compares the tree being built
against it: the tree's own digest, whether it differs from the release ("modified"), and how many files do. build.sh
stamps the answer into every image (labels) and into the registry (/app/BUILD_INFO.json, shown by /health), so a
sandbox running a contributor's change says so, and two reports that measured different trees cannot be compared as if
they were the same.

  kit_provenance.py --root <kit root> --version <kit version> [--out dist/build-info.json]
  kit_provenance.py --root <kit root> --write-manifest        (the export's step: writes KIT_FILES.sha256)
"""
import argparse
import datetime
import hashlib
import json
import os
import sys

MANIFEST = "KIT_FILES.sha256"
# what a build or a run leaves in the tree, never the kit's content: excluded on both sides
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", "dist", ".venv", "venv"}
SKIP_SUFFIXES = (".pyc", ".pyo")
SKIP_FILES = {MANIFEST, "BUILD_INFO.json", ".DS_Store"}
# What the kit's own setup writes into the tree it runs from (operator-setup.sh and the env generators write beside
# themselves, in scripts/distribution): runtime state with secrets in it, never the kit's content. Counted as a change
# (CB-016), a build run after setup tagged its images with the version only, so the standalone compose kept running the
# previous :stable. These exact paths only: the same names anywhere else stay a change, which is how frame-review sees
# (and refuses) a secret file a contribution carries, and nginx-templates/pgbouncer.ini is kit content.
RUNTIME_PATHS = {f"scripts/distribution/{n}" for n in (".env.operator", "pgbouncer.ini", "userlist.txt", "redis-users.acl")}


def files(root: str):
    """Every content file under root, as sorted relative paths (POSIX separators)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for fn in filenames:
            if fn in SKIP_FILES or fn.endswith(SKIP_SUFFIXES):
                continue
            p = os.path.join(dirpath, fn)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if rel not in RUNTIME_PATHS:
                out.append(rel)
    return sorted(out)


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digests(root: str) -> dict:
    return {rel: sha256_file(os.path.join(root, rel)) for rel in files(root)}


def tree_digest(d: dict) -> str:
    """One digest for a whole tree: sha256 over the sorted `sha256  path` lines (the manifest's own format)."""
    return hashlib.sha256("".join(f"{v}  {k}\n" for k, v in sorted(d.items())).encode()).hexdigest()


def read_manifest(root: str):
    path = os.path.join(root, MANIFEST)
    if not os.path.isfile(path):
        return None
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if len(line) > 66 and line[64:66] == "  ":
                out[line[66:]] = line[:64]
    return out


def write_manifest(root: str) -> int:
    d = digests(root)
    with open(os.path.join(root, MANIFEST), "w", encoding="utf-8") as f:
        for k, v in sorted(d.items()):
            f.write(f"{v}  {k}\n")
    return len(d)


def changed(root: str):
    """(changed paths, the release manifest) for the tree at root; (None, None) without a manifest."""
    release = read_manifest(root)
    if release is None:
        return None, None
    now = digests(root)
    return sorted(k for k in set(now) | set(release) if now.get(k) != release.get(k)), release


def build_info(root: str, version: str) -> dict:
    """The provenance of the tree at root against the release it came from."""
    now = digests(root)
    release = read_manifest(root)
    info = {"kit_version": version, "tree_digest": tree_digest(now), "files": len(now),
            "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if release is None:
        # a checkout of the source, or a kit from before the manifest: the digest still names the tree exactly
        info.update({"release_digest": None, "modified": None, "changed_files": None,
                     "note": f"no {MANIFEST} in this tree: the build cannot say whether it differs from a release"})
        return info
    changed = sorted(k for k in set(now) | set(release) if now.get(k) != release.get(k))
    info.update({"release_digest": tree_digest(release), "modified": bool(changed), "changed_files": len(changed),
                 "changed_sample": changed[:20]})
    return info


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--version", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--write-manifest", action="store_true")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)
    if a.write_manifest:
        n = write_manifest(root)
        print(f"{MANIFEST}: {n} files")
        return 0
    info = build_info(root, a.version)
    text = json.dumps(info, indent=1, sort_keys=True)
    if a.out:
        os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
