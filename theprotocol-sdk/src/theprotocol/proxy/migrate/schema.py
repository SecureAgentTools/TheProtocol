"""The kit: its manifest's JSON Schema (theprotocol.migration/v1), its caps, and its content hash.

A kit is a folder: migration.yaml (the manifest), proxy.yaml (a proxy spec whose sources read system A and whose sinks
write system B), README.md, sample/<file> per source, and optionally LICENSE. Everything under `.migrate/` is the CLI's
own working state (state.db, scratch/, reports/, template.json) and is not part of the kit.

The caps hold here and again on the registry (M4 copies MANIFEST_SCHEMA and KIT_CAPS verbatim, with a test on each side
pinning the two equal): at most 64 files, each at most 256 KiB, 2 MiB in all, UTF-8 text only, and every path matching
PATH_PATTERN (no `..`, no leading `/` or `.`).

content_hash = sha256 of the canonical JSON of {"manifest": <migration.yaml parsed>, "files": {<path>: <text>}}, where
"files" holds every file of the kit, migration.yaml included, as text. Canonical JSON everywhere:
json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False), UTF-8.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

SCHEMA_ID = "theprotocol.migration/v1"
REPORT_SCHEMA_ID = "theprotocol.migration.report/v1"
STATE_DIR = ".migrate"
TEMPLATE_COPY = "template"    # .migrate/template/: the files a library kit came with (get, fork), as they came
REQUIRED_FILES = ("migration.yaml", "proxy.yaml", "README.md")
PATH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$"
KIT_CAPS = {"max_files": 64, "max_file_bytes": 256 * 1024, "max_total_bytes": 2 * 1024 * 1024,
            "path_pattern": PATH_PATTERN, "encoding": "utf-8"}
_PATH = re.compile(PATH_PATTERN)

KINDS = ["sql", "file", "rest"]
_SIDE = {
    "type": "object",
    "required": ["kind"],
    "additionalProperties": False,
    "properties": {
        "kind": {"enum": KINDS},
        "engines": {"type": "array", "items": {"type": "string", "minLength": 1}, "uniqueItems": True},
        "what": {"type": "string"},
    },
}
_COLS = {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1, "uniqueItems": True}

# The manifest. ONE constant: the registry (M4) copies it verbatim.
MANIFEST_SCHEMA: Dict[str, Any] = {
    "$id": SCHEMA_ID,
    "type": "object",
    "required": ["schema", "name", "title", "from", "to", "load", "rollback"],
    "additionalProperties": False,
    "properties": {
        "schema": {"const": SCHEMA_ID},
        "name": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,62}$"},
        "title": {"type": "string", "minLength": 1, "maxLength": 200},
        "summary": {"type": "string", "maxLength": 2000},
        "from": _SIDE,
        "to": _SIDE,
        "parameters": {
            "type": "object",
            "propertyNames": {"pattern": "^[A-Za-z_][A-Za-z0-9_]{0,62}$"},
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "description": {"type": "string"},
                    "default": {"type": ["string", "number", "integer", "boolean"]},
                    "enum": {"type": "array", "minItems": 1},
                    "secret": {"type": "boolean"},
                },
            },
        },
        "load": {
            "type": "object",
            "required": ["mappings"],
            "additionalProperties": False,
            "properties": {
                "mappings": _COLS,
                "batch_rows": {"type": "integer", "minimum": 1, "maximum": 1000000},
            },
        },
        "reconcile": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["mapping", "source", "target", "pairs"],
                "additionalProperties": False,
                "properties": {
                    "mapping": {"type": "string", "minLength": 1},
                    "source": {"type": "object", "required": ["key", "fields"], "additionalProperties": False,
                               "properties": {"key": _COLS, "fields": {"type": "array", "items": {"type": "string"}}}},
                    "target": {"type": "object", "required": ["key", "fields"], "additionalProperties": False,
                               "properties": {
                                   "key": _COLS, "fields": {"type": "array", "items": {"type": "string"}},
                                   # a rest target is read back only when the manifest names how: GET url answers a JSON
                                   # list (or an object whose items_path holds one) of the written objects
                                   "read": {"type": "object", "required": ["url"], "additionalProperties": False,
                                            "properties": {"url": {"type": "string", "minLength": 1},
                                                           "items_path": {"type": "string"},
                                                           "headers": {"type": "object",
                                                                       "additionalProperties": {"type": "string"}}}}}},
                    "pairs": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "string"}},
                },
            },
        },
        "sample": {
            "type": "object",
            "additionalProperties": {
                "type": "object",
                "required": ["file"],
                "additionalProperties": False,
                "properties": {"file": {"type": "string", "pattern": PATH_PATTERN},
                               "format": {"enum": ["csv", "json", "jsonl", "xml"]}},
            },
        },
        "cutover": {"type": "object", "additionalProperties": False,
                    "properties": {"checklist": {"type": "array", "items": {"type": "string"}}}},
        "rollback": {"enum": ["auto", "manual"]},
        "workflow": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["key", "role", "acceptance"],
                "additionalProperties": False,
                "properties": {
                    "key": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{0,62}$"},
                    "role": {"type": "string", "minLength": 1},
                    "acceptance": {"type": "string", "minLength": 1},
                    "input_from": {"type": "string"},
                    "budget_share": {"type": "integer", "minimum": 0, "maximum": 100},
                },
            },
        },
    },
}


class KitError(ValueError):
    """A kit that cannot be used: every problem, named."""

    def __init__(self, problems: List[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def canonical(doc: Any) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def content_hash(manifest: Mapping[str, Any], files: Mapping[str, str]) -> str:
    return sha256_hex(canonical({"manifest": manifest, "files": dict(files)}))


@dataclass
class Kit:
    root: Optional[Path]
    manifest: Dict[str, Any]
    files: Dict[str, str]
    content_hash: str
    template: Optional[Dict[str, Any]] = field(default=None)    # .migrate/template.json, when the kit came from a library

    @property
    def state_dir(self) -> Path:
        assert self.root is not None
        return self.root / STATE_DIR

    @property
    def name(self) -> str:
        return str(self.manifest.get("name") or "")

    def template_ref(self) -> Dict[str, Any]:
        """The report's `template`: the library's id, version and hash, or {"local": hash} for a kit never published."""
        t = self.template or {}
        if t.get("id") and t.get("content_hash") == self.content_hash:
            return {"id": t["id"], "version": t.get("version"), "content_hash": self.content_hash}
        return {"local": self.content_hash}


def check_files(files: Mapping[str, bytes]) -> List[str]:
    """What breaks the caps (empty when none does)."""
    problems = []
    if len(files) > KIT_CAPS["max_files"]:
        problems.append(f"the kit holds {len(files)} files: at most {KIT_CAPS['max_files']}")
    total = 0
    for path in sorted(files):
        data = files[path]
        total += len(data)
        if not _PATH.match(path):
            problems.append(f"{path}: a path is letters, digits, '.', '_' and '-' in parts that start with a letter or "
                            f"a digit (no '..', no leading '/' or '.')")
        if len(data) > KIT_CAPS["max_file_bytes"]:
            problems.append(f"{path}: {len(data)} bytes, at most {KIT_CAPS['max_file_bytes']}")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            problems.append(f"{path}: not UTF-8 text")
    if total > KIT_CAPS["max_total_bytes"]:
        problems.append(f"the kit holds {total} bytes: at most {KIT_CAPS['max_total_bytes']}")
    for need in REQUIRED_FILES:
        if need not in files:
            problems.append(f"{need}: missing (a kit holds {', '.join(REQUIRED_FILES)})")
    return problems


def read_tree(root: Path) -> Dict[str, bytes]:
    """Every file under `root` (not `.migrate/`), by its path relative to it with '/' between parts."""
    out: Dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirnames[:] = [d for d in dirnames if d != STATE_DIR]
        dirnames.sort()
        for f in sorted(filenames):
            full = Path(dirpath) / f
            if full.is_symlink():
                out[(rel_dir / f).as_posix()] = b"\0symlink"    # refused below as not text: a kit is plain files
                continue
            out[(rel_dir / f).as_posix() if rel_dir != Path(".") else f] = full.read_bytes()
    return out


def _yaml(text: str, where: str) -> Any:
    try:
        import yaml
    except ImportError:  # pragma: no cover
        raise KitError(["a kit needs theprotocol-sdk[proxy] (PyYAML)"])
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise KitError([f"{where}: not YAML ({e.__class__.__name__})"])


def validate_manifest(manifest: Any) -> List[str]:
    from ..spec import _validate
    if not isinstance(manifest, dict):
        return ["migration.yaml: the manifest is not a mapping"]
    problems = _validate(manifest, MANIFEST_SCHEMA, "migration")
    if problems:
        return problems
    params = manifest.get("parameters") or {}
    for name, p in params.items():
        if p.get("secret") and "default" in p:
            problems.append(f"migration.parameters.{name}: a secret parameter has no default (it is given as a "
                            f"reference, env:NAME or file:/path, when the kit runs)")
        if "enum" in p and "default" in p and p["default"] not in p["enum"]:
            problems.append(f"migration.parameters.{name}: the default is not one of its enum")
    steps = [w["key"] for w in manifest.get("workflow") or []]
    for w in manifest.get("workflow") or []:
        if w.get("input_from") and w["input_from"] not in steps:
            problems.append(f"migration.workflow.{w['key']}.input_from: no step called {w['input_from']!r}")
    for i, r in enumerate(manifest.get("reconcile") or []):
        if len(r["source"]["key"]) != len(r["target"]["key"]):
            problems.append(f"migration.reconcile[{i}]: the source and target keys name a different number of columns")
    return problems


def kit_from_files(files: Mapping[str, str], *, root: Optional[Path] = None) -> Kit:
    """A kit from its files (path -> text), checked: the caps, the manifest's schema."""
    raw = {p: t.encode("utf-8") for p, t in files.items()}
    problems = check_files(raw)
    if problems:
        raise KitError(problems)
    manifest = _yaml(files["migration.yaml"], "migration.yaml")
    problems = validate_manifest(manifest)
    if problems:
        raise KitError(problems)
    for name, s in (manifest.get("sample") or {}).items():
        if s["file"] not in files:
            problems.append(f"migration.sample.{name}.file: the kit has no {s['file']}")
    if problems:
        raise KitError(problems)
    return Kit(root=root, manifest=manifest, files=dict(files), content_hash=content_hash(manifest, files))


def load_kit(root: Any) -> Kit:
    """The kit in folder `root`, checked (KitError naming every problem)."""
    r = Path(root or ".").resolve()
    if not r.is_dir():
        raise KitError([f"{r}: no such folder (a kit is a folder holding {', '.join(REQUIRED_FILES)})"])
    raw = read_tree(r)
    problems = check_files(raw)
    if problems:
        raise KitError(problems)
    kit = kit_from_files({p: b.decode("utf-8") for p, b in raw.items()}, root=r)
    tpl = r / STATE_DIR / "template.json"
    if tpl.is_file():
        try:
            kit.template = json.loads(tpl.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            kit.template = None
    return kit
