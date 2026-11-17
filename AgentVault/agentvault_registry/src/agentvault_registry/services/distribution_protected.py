"""V0667 D6: the PROTECTED SET of a distribution build, checked against its base release (gwo_65c7b7d9, session-release).

DESIGN_2026-11-15_DISTRIBUTIONS.md section 10 (room seq 4614: "we check whats in it and if delicate routes for the
federation and compliance are still untouched"): a distribution may add inside its open paths and take optional modules out,
but four areas stay BYTE-IDENTICAL to the base release, or OUR pipeline refuses the build:

    federation   peer trust, the frame licence, the registry card and its signature, the federation routes
    compliance   the legal texts, the audit records, the supply audit and the auditor's reads
    money        the TEG rails (the whole TEG source), the emission policy
    identity     SPIFFE, mTLS, authentication
    build        the build's own inputs: the Dockerfile, the requirements, constraints and lock files, gunicorn_conf
                 (session-lead seq 5532)

A tree is {repo-relative path: content hash} of ONE kind: "git" (blob ids, tree_of a commit) or "sha256" (tree_of_files a
directory, an image's /app). Equal hashes of one kind mean equal bytes; two kinds are never compared (ValueError), since a
blob id and a sha256 of the same file differ.

    verdict(base, dist, switches_base=None, switches_dist=None) -> {
        "verdict": "intact" | "refused",
        "refusals": [{"area", "path", "kind": "changed" | "added" | "removed"}, ...],   # empty when intact
        "areas": {area: {"files": <in the base>, "changed": [...], "added": [...], "removed": [...]}},
        "removed": {"modules": ["agentvault_registry.<pkg>.<mod>", ...],   # outside the protected set, taken out
                    "files": <count>, "switches": [{"name", "base", "distribution"}, ...]}}

The report travels with the distribution's release (D6) and its compliance report (D7). Nothing here reads the network or a
database; tree_of runs `git ls-tree`.
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional, Tuple, Union

R = "agentvault_registry/src/agentvault_registry"
TEG = "agentvault_teg_layer_mvp"
AREAS = ("federation", "compliance", "money", "identity", "build")

# Patterns are repo-relative fnmatch patterns ("*" crosses directories). Order inside an area does not matter; a path is
# classified by the FIRST area (in AREAS order) with a matching pattern.
PROTECTED: Dict[str, Tuple[str, ...]] = {
    "federation": (
        f"{R}/routers/federation_*.py", f"{R}/routers/admin_federation.py", f"{R}/routers/chat_federation.py",
        f"{R}/routers/contract_federation.py", f"{R}/routers/exchange_federation.py", f"{R}/routers/oauth_federation.py",
        f"{R}/routers/registry_card.py", f"{R}/routers/admin_registry_card.py",
        f"{R}/services/federation_*.py", f"{R}/services/peer_trust_policy.py", f"{R}/services/registry_card_*.py",
        f"{R}/services/oauth_peer_verify.py", f"{R}/services/chat_federation.py",
        f"{R}/core/federation_*.py", f"{R}/core/peer_group.py", f"{R}/core/registry_identity.py",
        f"{R}/background_tasks/federation_*.py", f"{R}/background_tasks/license_drift_monitor.py",
        f"{R}/background_tasks/reactor_federation_*.py", f"{R}/background_tasks/reactor_frame_federation_*.py",
        f"{R}/background_tasks/reactor_registry_federated.py",
    ),
    "compliance": (
        "LICENSE", "agentvault_registry/LICENSE",
        f"{R}/routers/legal.py", f"{R}/core/legal_versions.py", f"{R}/services/legal_acceptance.py",
        f"{R}/static/new_registry_frontend/src/content/legal/*",
        f"{R}/services/admin_audit.py", f"{R}/routers/mcp_audit_log.py", f"{R}/mcp/audit.py",
        f"{R}/routers/supply_auditor_admin.py", f"{R}/background_tasks/supply_auditor.py",
        f"{R}/background_tasks/auditor_worker.py", f"{R}/background_tasks/reactor_supply_invariant_breach.py",
        f"{R}/core/auditor_rules.py",
    ),
    "money": (
        f"{TEG}/*",
        f"{R}/routers/teg_*.py", f"{R}/routers/cross_teg_sweeper_admin.py",
        f"{R}/event_emitter.py", f"{R}/services/emission_policy_view.py",
        f"{R}/background_tasks/reactor_emission_policy_updated.py", f"{R}/services/org_treasury.py",
    ),
    "identity": (
        f"{R}/identity/*", f"{R}/security.py", f"{R}/security_utils.py", f"{R}/security_oauth/*", f"{R}/agent_authz.py",
        f"{R}/routers/auth*.py", f"{R}/routers/agent_mtls.py",
        f"{R}/services/agent_spire.py", f"{R}/services/spiffe_canonical.py", f"{R}/services/spire_ops_client.py",
        f"{R}/services/two_factor_auth.py", f"{R}/services/webauthn.py", f"{R}/services/oauth_keystore.py",
        f"{R}/core/mtls_auth.py", f"{R}/core/tls_client.py", f"{R}/core/spire_mtls_client.py", f"{R}/core/svid_server.py",
        f"{R}/core/jwt_svid_provider.py", f"{R}/core/secret_hash.py", f"{R}/core/process_identity.py",
    ),
    # session-lead seq 5532 (1): the build's own inputs (what goes into the image besides the code)
    "build": (
        ".dockerignore", "pyproject.toml",
        "agentvault_registry/Dockerfile", "agentvault_registry/.dockerignore", "agentvault_registry/requirements*.txt",
        "agentvault_registry/constraints-*.txt", "agentvault_registry/poetry.lock", "agentvault_registry/pyproject.toml",
        "agentvault_registry/gunicorn_conf.py",
        f"{R}/static/new_registry_frontend/package.json", f"{R}/static/new_registry_frontend/package-lock.json",
    ),
}

# Never part of a protected file's bytes: build and editor droppings
_IGNORED_PARTS = ("__pycache__", ".pytest_cache", "node_modules")
_IGNORED_SUFFIXES = (".pyc", ".pyo")


@dataclass
class Tree:
    kind: str                                   # "git" | "sha256"
    files: Dict[str, str] = field(default_factory=dict)


TreeLike = Union[Tree, Mapping[str, str]]


def matches(pattern: str, path: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


def classify(path: str) -> Optional[str]:
    """The protected area a repo-relative path belongs to, or None (outside the protected set)."""
    if _ignored(path):
        return None
    for area in AREAS:
        if any(matches(p, path) for p in PROTECTED[area]):
            return area
    return None


def registry_patterns() -> List[str]:
    """Every pattern inside the registry's source tree (the ones its own tests can check against files on disk)."""
    return [p for area in AREAS for p in PROTECTED[area] if p.startswith(R + "/")]


def _ignored(path: str) -> bool:
    parts = path.split("/")
    return any(x in parts for x in _IGNORED_PARTS) or path.endswith(_IGNORED_SUFFIXES)


def _as_tree(t: TreeLike) -> Tree:
    return t if isinstance(t, Tree) else Tree(kind="", files=dict(t))


def _module_name(path: str) -> Optional[str]:
    prefix = "agentvault_registry/src/"
    if not path.startswith(prefix) or not path.endswith(".py"):
        return None
    mod = path[len(prefix):-3].replace("/", ".")
    return mod[:-len(".__init__")] if mod.endswith(".__init__") else mod


def verdict(base: TreeLike, dist: TreeLike, switches_base: Optional[Mapping[str, str]] = None,
            switches_dist: Optional[Mapping[str, str]] = None) -> Dict[str, object]:
    b, d = _as_tree(base), _as_tree(dist)
    if b.kind and d.kind and b.kind != d.kind:
        raise ValueError(f"hash kinds differ ({b.kind} vs {d.kind}): read both trees the same way")
    areas = {a: {"files": 0, "changed": [], "added": [], "removed": []} for a in AREAS}
    refusals: List[Dict[str, str]] = []
    removed_modules: List[str] = []
    removed_files = 0
    for path in sorted(set(b.files) | set(d.files)):
        area = classify(path)
        in_b, in_d = path in b.files, path in d.files
        if area is None:
            if in_b and not in_d and not _ignored(path):
                removed_files += 1
                m = _module_name(path)
                if m:
                    removed_modules.append(m)
            continue
        if in_b:
            areas[area]["files"] += 1
        kind = None
        if in_b and in_d and b.files[path] != d.files[path]:
            kind = "changed"
        elif in_d and not in_b:
            kind = "added"
        elif in_b and not in_d:
            kind = "removed"
        if kind:
            areas[area][kind].append(path)
            refusals.append({"area": area, "path": path, "kind": kind})
    switches = []
    sb, sd = dict(switches_base or {}), dict(switches_dist or {})
    for name in sorted(set(sb) | set(sd)):
        if sb.get(name) != sd.get(name):
            switches.append({"name": name, "base": sb.get(name), "distribution": sd.get(name)})
    return {
        "verdict": "refused" if refusals else "intact",
        "refusals": refusals,
        "areas": areas,
        "removed": {"modules": sorted(removed_modules), "files": removed_files, "switches": switches},
    }


def tree_of(repo: str, ref: str) -> Tree:
    """{path: blob id} of every file at <ref> in the git repository <repo> (`git ls-tree -r`; submodules and links kept
    as their object id). Raises on a git error."""
    out = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "-z", "--full-tree", ref], capture_output=True, check=True).stdout
    return parse_ls_tree(out)


def parse_ls_tree(out: bytes) -> Tree:
    """`git ls-tree -r -z` output ("<mode> <type> <id>\\t<path>\\0" per entry) as a git-kind Tree."""
    files: Dict[str, str] = {}
    for rec in out.split(b"\0"):
        if not rec:
            continue
        meta, _, path = rec.partition(b"\t")
        files[path.decode("utf-8", "surrogateescape")] = meta.split()[2].decode()
    return Tree(kind="git", files=files)


def tree_of_files(root: str) -> Tree:
    """{path relative to <root>: sha256} of every regular file under <root> (an exported checkout or an image's tree)."""
    files: Dict[str, str] = {}
    for d, dirs, fs in os.walk(root):
        dirs[:] = [x for x in dirs if x not in _IGNORED_PARTS]
        for f in fs:
            p = os.path.join(d, f)
            if os.path.islink(p) or not os.path.isfile(p):
                continue
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            if _ignored(rel):
                continue
            hs = hashlib.sha256()
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    hs.update(chunk)
            files[rel] = hs.hexdigest()
    return Tree(kind="sha256", files=files)



# ── session-lead seq 5532 (2) and (3): what a changed file outside the set may not do ────────────────────────────────────
MIGRATIONS = "agentvault_registry/alembic/versions/"
LIMITS = ("The scan reads each changed Python file outside the protected set as written; it cannot see a module reached by "
          "a computed name (importlib.import_module or __import__ with a built string), code run through exec, eval or "
          "compile, a patch made through an object passed in from elsewhere, or anything outside Python. Those are named "
          "below where they appear; the review and OPA cover them.")
_TABLE_OPS = {  # op name -> (positional index of the table, keyword naming it)
    "create_table": (0, None), "drop_table": (0, None), "create_index": (1, "table_name"), "drop_index": (None, "table_name"),
    "add_column": (0, None), "drop_column": (0, None), "alter_column": (0, None), "create_foreign_key": (1, None),
    "drop_constraint": (1, "table_name"), "create_unique_constraint": (1, None), "create_check_constraint": (1, None),
}


def _dotted(node: ast.AST) -> Optional[str]:
    parts: List[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def protected_modules(base_files) -> set:
    """The dotted names of every protected Python module in the base tree."""
    out = set()
    for p in base_files:
        if classify(p) and p.endswith(".py"):
            m = _module_name(p)
            if m:
                out.add(m)
    return out


def scan_patches(path: str, source: str, protected: set) -> Tuple[List[Dict[str, object]], List[Dict[str, object]]]:
    """(refusals, unseen) for one changed file outside the protected set: an assignment to or deletion of a protected
    module's attribute, setattr/delattr on one, a write to sys.modules, importlib.reload; and the dynamic forms the scan
    cannot follow (named, not refused)."""
    tree = ast.parse(source, filename=path)
    alias: Dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.asname:
                    alias[a.asname] = a.name
                else:
                    alias[a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom) and n.module and not n.level:
            for a in n.names:
                alias[a.asname or a.name] = f"{n.module}.{a.name}"

    def resolve(dotted: Optional[str]) -> Optional[str]:
        if not dotted:
            return None
        head, _, rest = dotted.partition(".")
        base = alias.get(head)
        if base is None:
            return None
        return base + ("." + rest if rest else "")

    def protected_owner(full: Optional[str]) -> bool:
        """The object an attribute is set on (all but the last name) is, or lives in, a protected module."""
        if not full or "." not in full:
            return False
        owner = full.rsplit(".", 1)[0]
        parts = owner.split(".")
        return any(".".join(parts[:i]) in protected for i in range(1, len(parts) + 1))

    def is_sys_modules(node: ast.AST) -> bool:
        return resolve(_dotted(node)) == "sys.modules"

    refusals: List[Dict[str, object]] = []
    unseen: List[Dict[str, object]] = []

    def refuse(node, what):
        refusals.append({"area": None, "path": path, "kind": "patches_protected", "line": node.lineno, "what": what})

    for n in ast.walk(tree):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                if isinstance(t, ast.Attribute) and protected_owner(resolve(_dotted(t))):
                    refuse(n, f"assigns {ast.unparse(t)}")
                if isinstance(t, ast.Subscript) and is_sys_modules(t.value):
                    refuse(n, "writes sys.modules")
        elif isinstance(n, ast.Delete):
            for t in n.targets:
                if isinstance(t, ast.Attribute) and protected_owner(resolve(_dotted(t))):
                    refuse(n, f"deletes {ast.unparse(t)}")
                if isinstance(t, ast.Subscript) and is_sys_modules(t.value):
                    refuse(n, "writes sys.modules")
        elif isinstance(n, ast.Call):
            fn = resolve(_dotted(n.func)) or _dotted(n.func)
            if fn in ("setattr", "delattr") and n.args:
                target = resolve(_dotted(n.args[0]))
                if target and any(target == m or target.startswith(m + ".") for m in protected):
                    refuse(n, f"{fn} on {ast.unparse(n.args[0])}")
            elif fn in ("importlib.reload", "imp.reload"):
                refuse(n, "importlib.reload")
            elif isinstance(n.func, ast.Attribute) and is_sys_modules(n.func.value) and n.func.attr in (
                    "update", "__setitem__", "setdefault", "pop", "popitem", "clear", "__delitem__"):
                refuse(n, "writes sys.modules")
            elif fn in ("exec", "eval", "compile"):
                unseen.append({"path": path, "line": n.lineno, "what": fn})
            elif fn in ("importlib.import_module", "__import__") and not (n.args and isinstance(n.args[0], ast.Constant)):
                unseen.append({"path": path, "line": n.lineno, "what": f"{fn} with a computed name"})
    return refusals, unseen


def check_migration(path: str, source: str) -> Tuple[List[Dict[str, object]], List[str]]:
    """(refusals, tables created) for a distribution's new migration: v1 lets it create its OWN tables (and their indexes,
    constraints and columns) and drop them in its downgrade; an op on any other table, a computed table name, a raw
    op.execute or an op outside that list is refused."""
    tree = ast.parse(source, filename=path)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "op"]
    created = []
    for c in calls:
        if c.func.attr == "create_table" and c.args and isinstance(c.args[0], ast.Constant) and isinstance(c.args[0].value, str):
            created.append(c.args[0].value)
    refusals: List[Dict[str, object]] = []

    def refuse(node, what):
        refusals.append({"area": None, "path": path, "kind": "migration", "line": node.lineno, "what": what})

    for c in sorted(calls, key=lambda c: (c.lineno, c.col_offset)):
        fn = c.func.attr
        if fn == "execute":
            refuse(c, "op.execute (raw SQL) is not allowed in a distribution's migration (v1)")
            continue
        if fn not in _TABLE_OPS:
            refuse(c, f"op.{fn} is not allowed in a distribution's migration (v1)")
            continue
        pos, kw = _TABLE_OPS[fn]
        node = None
        if kw:
            node = next((k.value for k in c.keywords if k.arg == kw), None)
        if node is None and pos is not None and len(c.args) > pos:
            node = c.args[pos]
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            refuse(c, f"{fn} names its table by a computed value")
            continue
        if node.value not in created:
            refuse(c, f"{fn} on {node.value}: a table this migration does not create")
    return refusals, created


def full_check(base: TreeLike, dist: TreeLike, read_dist, switches_base: Optional[Mapping[str, str]] = None,
               switches_dist: Optional[Mapping[str, str]] = None) -> Dict[str, object]:
    """verdict() plus the scan of every changed Python file outside the set (2) and the migration rule (3).
    read_dist(path) -> bytes reads a file of the distribution's tree."""
    b, d = _as_tree(base), _as_tree(dist)
    v = verdict(b, d, switches_base=switches_base, switches_dist=switches_dist)
    refusals: List[Dict[str, object]] = list(v["refusals"])
    protected = protected_modules(b.files)
    unseen: List[Dict[str, object]] = []
    scanned = 0
    migrations = []
    for path in sorted(set(b.files) | set(d.files)):
        if classify(path) or _ignored(path):
            continue
        in_b, in_d = path in b.files, path in d.files
        if path.startswith(MIGRATIONS) and path.endswith(".py"):
            if in_b and (not in_d or b.files[path] != d.files[path]):
                refusals.append({"area": None, "path": path, "kind": "migration", "line": None,
                                 "what": "removes a base migration" if not in_d else "changes a base migration"})
                continue
            if in_d and not in_b:
                try:
                    r, created = check_migration(path, read_dist(path).decode("utf-8"))
                except SyntaxError as e:
                    refusals.append({"area": None, "path": path, "kind": "unparsable", "line": e.lineno, "what": str(e.msg)})
                    continue
                refusals.extend(r)
                migrations.append({"path": path, "creates": created})
            continue
        if not path.endswith(".py") or not in_d or (in_b and b.files[path] == d.files[path]):
            continue
        scanned += 1
        try:
            r, u = scan_patches(path, read_dist(path).decode("utf-8"), protected)
        except SyntaxError as e:
            refusals.append({"area": None, "path": path, "kind": "unparsable", "line": e.lineno, "what": str(e.msg)})
            continue
        refusals.extend(r)
        unseen.extend(u)
    v["refusals"] = refusals
    v["verdict"] = "refused" if refusals else "intact"
    v["scan"] = {"files": scanned, "unseen": unseen, "limits": LIMITS}
    v["migrations"] = migrations
    return v
