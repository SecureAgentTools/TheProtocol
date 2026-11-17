"""V0664 "Migrate a system", M4 (order gwo_e97a483512cfaf2151f17b7a): the template library on the registry.

THE CONTRACT is sessionlogs2026/DESIGN_2026-11-14_MIGRATION_TEMPLATES.md (section D; A for the kit, C for what the CLI
calls). The engine (the proxy, migrate, dry run, reconcile, certificate) is free and open source; what people write are
templates, put up free or for a price, and forkable, a fork paying its parent's author a share of each sale.

  the kit        check_kit: migration.yaml, proxy.yaml, README.md; at most 64 files, 256 KiB each, 2 MiB in all, UTF-8
                 text, paths that match PATH_PATTERN; yaml.safe_load only; the manifest against MANIFEST_SCHEMA and its four
                 checks (theprotocol-sdk's proxy/migrate/schema.py, MANIFEST_SCHEMA and KIT_CAPS copied verbatim; the
                 stack's scripts/distribution/check_migration_pins.py pins the copies equal at release); the
                 secret rule of theprotocol-sdk's spec.py (SECRET_KEY and REF, copied: a test pins them equal where the
                 SDK sits beside the tree). A refusal names the file, the field and the rule, never a value.
  destinations   a published kit names no destination of its own (section D, DESTINATIONS): every host, url, database
                 and path in its sources and sinks is a ${PARAM} the manifest declares (after a url's parameter only a
                 /path or a ?query, never . : or @), and a default for a host, url or path may only be local (localhost,
                 127.0.0.1, ::1, or a relative path inside the kit); a database name's default is free
  the hash       content_hash = sha256 of the canonical JSON of {"manifest", "files"}
  who publishes  any agent drafts (create, versions, fork: private); what others can see or what costs money (a template
                 created or patched to public, unlisted or org, a version published while it is visible, a price set or
                 raised) passes the reputation bond gate at site template_publish (session-lead, room seq 3957)
  who sees what  a template: public, unlisted (by id), its organization's agents, its owner (a developer through an
                 agent it owns that qualifies; anonymous callers see public and unlisted ones); a version's FILES: anyone
                 when the template is free and visible, else the owner and buyers (402 otherwise); a draft: its owner
  money          no new path (rule 14): a purchase is services/escrow's deposit "wtpl:{tid}:{buyer}:in", a payout to the
                 author ":out" and, for a fork whose parent sets a share, a payout to the parent's author ":up"; one level;
                 no fee. The purchase is RECORDED pending before the deposit (price, share, currency, the two payees) and
                 done after the payouts: a retry pays what the record says, never the template's price or share at the
                 retry, so the escrow never pays out more than it took (session-lead, room seq 3873); a recorded
                 purchase finishes as recorded whatever the template says now. A refusal before anything moved (a 4xx
                 other than 409: an insufficient balance) is 402 and withdraws the record; an unconfirmed deposit (a 409
                 or a 5xx) is 502 and keeps it for the retry
  use            instantiate: a V0663 workflow draft (services/workflows.create) from the manifest's workflow, with the
                 template's provenance on it; certified: the agent's own TEG attestation of type migration.certificate
                 (the TEG keeps its data's hash: the caller posts the data, the registry hashes it as the submit did),
                 its claim naming this template and one of its versions' content hashes, verdict pass; recorded once
                 per template and agent (session-lead, room seq 3755); the listing's instantiations and certified count
                 distinct developers, the agents' creator (room seq 3873: "certified by N developers")
Behind WORKFLOW_TEMPLATES_ENABLED (default false): the routes answer 503 while it is off, and the public
registry-config field workflow_templates_enabled reads the same templates_enabled().
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import secrets
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx
from sqlalchemy import select

from ..es_ssl_helper import get_httpx_verify

logger = logging.getLogger(__name__)

SCHEMA_ID = "theprotocol.migration/v1"
CERTIFICATE_TYPE = "migration.certificate"
VISIBILITY = ("private", "org", "unlisted", "public")
PRICING = ("free", "purchase")
REQUIRED_FILES = ("migration.yaml", "proxy.yaml", "README.md")
DEFAULT_FORK_SHARE_BPS = 2000
MAX_FORK_SHARE_BPS = 5000
# copied verbatim from theprotocol-sdk/src/theprotocol/proxy/migrate/schema.py (M3): the caps and the path rule
PATH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$"
KIT_CAPS = {"max_files": 64, "max_file_bytes": 256 * 1024, "max_total_bytes": 2 * 1024 * 1024,
            "path_pattern": PATH_PATTERN, "encoding": "utf-8"}
MAX_FILES, MAX_FILE_BYTES, MAX_KIT_BYTES = KIT_CAPS["max_files"], KIT_CAPS["max_file_bytes"], KIT_CAPS["max_total_bytes"]
PATH_RE = re.compile(PATH_PATTERN)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,118}$")
BUY_FIRST = "This template is purchase-priced — buy it first (POST …/purchase)"
_Q = Decimal("0.0000000001")

# copied from theprotocol-sdk/src/theprotocol/proxy/spec.py (tests/test_workflow_templates_kit_v0664.py pins them equal):
# a key whose NAME ends in a secret word holds a credential; a value is a reference when it is env:NAME or file:/path
SECRET_KEY = re.compile(r"(?:^|[_-])(?:secret|password|passwd|passphrase|token|api[_-]?key|private[_-]?key|credentials?)s?$",
                        re.I)
REF = re.compile(r"^(env|file):(.+)$")

# contract section D, DESTINATIONS (session-lead, room seq 3820): a published kit names no destination of its own
DESTINATION_KEYS = ("url", "host", "database", "path", "dir")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")
# a parameter's name as M3's schema allows it (parameters.propertyNames)
_PARAM_ONLY = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]{0,62})\}$")
# a url starts with its parameter, and what follows may only begin with / or ? (or nothing): never a . : or @ right
# after it, which would change the host (session-lead, room seq 3831)
_PARAM_URL = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]{0,62})\}([/?]\S*)?$")

# THE MANIFEST SCHEMA, theprotocol.migration/v1: M3's, copied verbatim from here to its closing brace
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



def templates_enabled() -> bool:
    """The one reading of the flag: the route guard and the public registry-config field both ask this."""
    return (os.getenv("WORKFLOW_TEMPLATES_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


# --- the kit -------------------------------------------------------------------------------------------------------

class KitRefused(Exception):
    def __init__(self, sentence: str) -> None:
        super().__init__(sentence)
        self.sentence = sentence


def is_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(REF.match(value.strip()))


def _secret_fields(doc: Any) -> List[Tuple[str, str]]:
    """(path, value) for every string value in `doc` whose key says it holds a credential."""
    out: List[Tuple[str, str]] = []

    def walk(node: Any, at: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                p = f"{at}.{k}" if at else str(k)
                if isinstance(v, str) and v and SECRET_KEY.search(str(k).strip()):
                    out.append((p, v))
                walk(v, p)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{at}[{i}]")
    walk(doc, "")
    return out


def written_out_secrets(doc: Any, prefix: str, secret_params: Iterable[str] = ()) -> List[str]:
    """The paths in `doc` whose key says it holds a credential and whose value is written out: neither a reference
    (env:NAME, file:/path) nor exactly one ${NAME} naming a parameter the manifest declares secret: true (the kits the SDK
    ships fill a secret field so, and the CLI turns that parameter into a reference when the kit runs)."""
    secret = set(secret_params)
    out = []
    for p, v in _secret_fields(doc):
        m = _PARAM_ONLY.match(v.strip())
        if is_ref(v) or (m and m.group(1) in secret):
            continue
        out.append(f"{prefix}{p}")
    return sorted(set(out))


def plain_parameter_secrets(doc: Any, prefix: str, secret_params: Iterable[str]) -> List[str]:
    """The paths of a credential field holding exactly one ${NAME} that names no parameter declared secret: true (a
    plain parameter, or none): the field would carry whatever that parameter holds, in the open."""
    secret = set(secret_params)
    out = []
    for p, v in _secret_fields(doc):
        m = _PARAM_ONLY.match(v.strip())
        if m and m.group(1) not in secret:
            out.append(f"{prefix}{p}")
    return sorted(set(out))


def _local_default(value: Any, key: str) -> bool:
    """Whether a destination parameter's default stays on the user's own machine: a host or url on localhost,
    127.0.0.1 or ::1, or a path (or database name) relative to the kit."""
    from urllib.parse import urlsplit
    v = str(value).strip()
    if key == "url":
        try:
            u = urlsplit(v)
        except ValueError:
            return False
        return u.scheme in ("http", "https") and not u.username and not u.password and (u.hostname or "") in LOCAL_HOSTS
    if key == "host":
        return v.strip("[]") in LOCAL_HOSTS
    if not v or v.startswith(("/", "~", "\\")) or ":" in v or "\\" in v:
        return False
    return ".." not in v.split("/")


def destination_refusals(proxy: Dict[str, Any], manifest: Dict[str, Any]) -> List[str]:
    """Every host, url, database and path in the kit's sources and sinks (at any depth of their config) must be a
    ${PARAM} the manifest declares, and that parameter's default, when it has one, must be local. The paths that break
    the rule, never their values."""
    params = manifest.get("parameters") or {}
    out: List[str] = []

    def walk(node: Any, at: str) -> None:
        if not isinstance(node, dict):
            return
        for k, v in node.items():
            p = f"{at}.{k}"
            if str(k) in DESTINATION_KEYS:
                m = (_PARAM_URL if k == "url" else _PARAM_ONLY).match(v) if isinstance(v, str) else None
                if not m:
                    out.append(f"proxy.yaml:{p}")
                    continue
                name = m.group(1)
                spec = params.get(name)
                if not isinstance(spec, dict):
                    out.append(f"proxy.yaml:{p} (names ${{{name}}}, which migration.yaml does not declare)")
                # a database NAME default is allowed: the host decides where data goes, and the host is a parameter
                # (session-lead, room seq 3843); hosts, urls and paths (sqlite files included) stay local-only
                elif k != "database" and spec.get("default") not in (None, "") and \
                        not _local_default(spec["default"], str(k)):
                    out.append(f"migration.yaml:parameters.{name}.default")
            elif isinstance(v, dict):
                walk(v, p)
    for section in ("sources", "sinks"):
        for name, plug in (proxy.get(section) or {}).items() if isinstance(proxy.get(section), dict) else ():
            if isinstance(plug, dict):
                walk(plug.get("config"), f"{section}.{name}.config")
    return sorted(set(out))


def _yaml(files: Dict[str, str], name: str) -> Dict[str, Any]:
    import yaml
    try:
        doc = yaml.safe_load(files[name])
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise KitRefused(f"{name} is not YAML the safe loader reads{where}") from None
    if not isinstance(doc, dict):
        raise KitRefused(f"{name} is not a mapping")
    try:
        json.dumps(doc)
    except (TypeError, ValueError):
        raise KitRefused(f"{name} holds a value JSON cannot carry (quote dates and times)") from None
    return doc


def _schema_refusal(err: Any) -> str:
    path = ".".join(str(p) for p in err.absolute_path) or "(the document)"
    if err.validator == "additionalProperties" and isinstance(err.instance, dict):
        allowed = set((err.schema or {}).get("properties", {}))
        extra = sorted(str(k) for k in err.instance if k not in allowed)
        return f"migration.yaml {path}: unknown key(s) {', '.join(extra)}"
    if err.validator == "required":
        return f"migration.yaml {path}: a required key is missing ({err.message.split(' ')[0]})"
    return f"migration.yaml {path}: fails the schema's {err.validator} rule"


def _manifest_checks(manifest: Dict[str, Any]) -> None:
    """M3's checks beyond the schema (theprotocol/proxy/migrate/schema.validate_manifest), in its order, so a kit the
    CLI refuses is refused here too; the sentence names the place, never a value."""
    for name, p in (manifest.get("parameters") or {}).items():
        if p.get("secret") and "default" in p:
            raise KitRefused(f"migration.yaml parameters.{name}.default: a secret parameter has no default (it is given "
                             f"as a reference, env:NAME or file:/path, when the kit runs)")
        if "enum" in p and "default" in p and p["default"] not in p["enum"]:
            raise KitRefused(f"migration.yaml parameters.{name}.default: the default is not one of its enum")
    steps = [w["key"] for w in manifest.get("workflow") or []]
    for w in manifest.get("workflow") or []:
        if w.get("input_from") and w["input_from"] not in steps:
            raise KitRefused(f"migration.yaml workflow.{w['key']}.input_from: names no step of the workflow")
    for i, r in enumerate(manifest.get("reconcile") or []):
        if len(r["source"]["key"]) != len(r["target"]["key"]):
            raise KitRefused(f"migration.yaml reconcile[{i}]: the source and target keys name a different number of "
                             f"columns")


def check_kit(files: Any) -> Dict[str, Any]:
    """The manifest of a kit that passes every upload rule; KitRefused (naming what failed, never a value) otherwise."""
    if not isinstance(files, dict) or not files:
        raise KitRefused("files is a JSON object of path to text")
    if len(files) > MAX_FILES:
        raise KitRefused(f"a kit holds at most {MAX_FILES} files (this one holds {len(files)})")
    total = 0
    for path, text in files.items():
        if not isinstance(path, str) or not PATH_RE.match(path) or len(path) > 300:
            raise KitRefused(f"a path breaks the path rule (relative, letters, digits, '.', '_', '-' and '/'): "
                             f"{str(path)[:80]!r}")
        if not isinstance(text, str) or "\x00" in text:
            raise KitRefused(f"{path} is not text (a kit carries UTF-8 text only)")
        size = len(text.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise KitRefused(f"{path} is over 256 KiB")
        total += size
    if total > MAX_KIT_BYTES:
        raise KitRefused("the kit is over 2 MiB in all")
    for name in REQUIRED_FILES:
        if name not in files:
            raise KitRefused(f"the kit has no {name}")
    manifest = _yaml(files, "migration.yaml")
    import jsonschema
    errors = sorted(jsonschema.Draft202012Validator(MANIFEST_SCHEMA).iter_errors(manifest),
                    key=lambda e: [str(p) for p in e.absolute_path])
    if errors:
        raise KitRefused(_schema_refusal(errors[0]))
    _manifest_checks(manifest)
    proxy = _yaml(files, "proxy.yaml")
    secret_params = {n for n, p in (manifest.get("parameters") or {}).items() if isinstance(p, dict) and p.get("secret")}
    plain = plain_parameter_secrets(proxy, "proxy.yaml:", secret_params)
    if plain:
        raise KitRefused(f"a credential field names a parameter migration.yaml does not mark secret: true, at "
                         f"{', '.join(plain)}: name a parameter declared secret: true, or write an env:NAME or "
                         f"file:/path reference")
    leaks = written_out_secrets(proxy, "proxy.yaml:", secret_params) + written_out_secrets(manifest, "migration.yaml:")
    if leaks:
        raise KitRefused(f"a credential is written out at {', '.join(sorted(set(leaks)))}: write an env:NAME or "
                         f"file:/path reference instead")
    places = destination_refusals(proxy, manifest)
    if places:
        raise KitRefused(f"the kit names a destination of its own at {', '.join(places)}: every host, url and path in "
                         f"its sources and sinks is a ${{PARAM}} the user sets, and a default for a host, url or path may only be local "
                         f"(localhost, 127.0.0.1, ::1, or a relative path inside the kit)")
    for source, s in (manifest.get("sample") or {}).items():
        if s.get("file") not in files:
            raise KitRefused(f"the sample {s.get('file')} the manifest names for {source} is not in the kit")
    return manifest


def canonical(doc: Any) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(manifest: Dict[str, Any], files: Dict[str, str]) -> str:
    return hashlib.sha256(canonical({"manifest": manifest, "files": files})).hexdigest()


def structure(manifest: Dict[str, Any]) -> Dict[str, Any]:
    """What anyone who may see a template is shown of it, paid or not: its shape, never a file or a mapping."""
    params = manifest.get("parameters") or {}
    return {
        "schema": manifest.get("schema"), "name": manifest.get("name"),
        "from": manifest.get("from"), "to": manifest.get("to"),
        "parameters": sorted(params),
        "secret_parameters": sorted(k for k, v in params.items() if isinstance(v, dict) and v.get("secret")),
        "steps": [{"key": s.get("key"), "role": s.get("role"), "budget_share": s.get("budget_share"),
                   "input_from": s.get("input_from")} for s in (manifest.get("workflow") or [])],
        "load_mappings": list((manifest.get("load") or {}).get("mappings") or []),
        "reconcile": [{"mapping": r.get("mapping"), "fields": len((r.get("source") or {}).get("fields") or [])}
                      for r in (manifest.get("reconcile") or [])],
        "samples": len(manifest.get("sample") or {}),
        "rollback": manifest.get("rollback"),
        "cutover_steps": len((manifest.get("cutover") or {}).get("checklist") or []),
    }


# --- the library -----------------------------------------------------------------------------------------------------

class LibraryRefusal(Exception):
    """A refusal the route answers with its status, a short code and a sentence."""

    def __init__(self, status: int, code: str, sentence: str) -> None:
        super().__init__(sentence)
        self.status, self.code, self.sentence = status, code, sentence


class PaymentDeclined(Exception):
    """The escrow deposit was not taken. ``status`` is the ledger's answer: a 4xx other than 409 is a refusal before
    anything moved (an insufficient balance); a 409 (a key in flight or used) or a 5xx leaves it open whether the
    deposit took, so the purchase's record stays for a retry, whose deposit under the same key and amount moves once."""

    def __init__(self, sentence: str, status: Optional[int] = None) -> None:
        super().__init__(sentence)
        self.status = status

    @property
    def nothing_moved(self) -> bool:
        return self.status is not None and 400 <= self.status < 500 and self.status != 409


def _iso(v: Any) -> Any:
    return v.isoformat() if isinstance(v, (dt.datetime, dt.date)) else v


def _money(v: Any) -> Optional[Decimal]:
    if v in (None, ""):
        return None
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None
    return d if d.is_finite() else None


COUNT_KEYS = ("kit_downloads", "instantiations", "certified", "forks")
MINE_MAX = 200          # an owner's own templates in one read
PATCHABLE = ("title", "summary", "visibility", "pricing_model", "price", "fork_share_bps")


class Library:
    """The rules over a store (DbStore on the database; an in-memory one in the tests). An actor is None (no
    credential), an agent {"kind": "agent", "did", "developer_id", "org"} or a developer {"kind": "developer",
    "developer_id"}. Writes are an agent's."""

    def __init__(self, store: Any) -> None:
        self.s = store

    # -- guards --
    async def _tpl(self, tid: str) -> Dict[str, Any]:
        t = await self.s.template(tid)
        if not t:
            raise LibraryRefusal(404, "not_found", "no template with that id")
        return t

    async def _visible(self, actor: Optional[Dict[str, Any]], t: Dict[str, Any]) -> bool:
        vis = t["visibility"]
        if vis in ("public", "unlisted"):
            return True
        if not actor:
            return False
        org = t.get("source_org_id")
        if actor.get("kind") == "agent":
            if actor.get("did") == t["owner_agent_did"]:
                return True
            return vis == "org" and bool(org) and str(actor.get("org") or "") == str(org)
        dev = actor.get("developer_id")
        if dev is None:
            return False
        if await self.s.developer_owns(dev, t["owner_agent_did"]):
            return True
        return vis == "org" and bool(org) and await self.s.developer_in_org(dev, org)

    async def _see(self, actor: Optional[Dict[str, Any]], t: Dict[str, Any]) -> None:
        if not await self._visible(actor, t):
            if not actor:
                raise LibraryRefusal(404, "not_found", "no template with that id")
            raise LibraryRefusal(403, "not_visible", "this template is not visible to you")

    async def _is_owner(self, actor: Optional[Dict[str, Any]], t: Dict[str, Any]) -> bool:
        if not actor:
            return False
        if actor.get("kind") == "agent":
            return actor.get("did") == t["owner_agent_did"]
        dev = actor.get("developer_id")
        return dev is not None and await self.s.developer_owns(dev, t["owner_agent_did"])

    async def _owns_or_bought(self, actor: Optional[Dict[str, Any]], t: Dict[str, Any]) -> bool:
        if await self._is_owner(actor, t):
            return True
        if not actor:
            return False
        if actor.get("kind") == "agent":
            return await self.s.purchased(t["id"], actor.get("did"))
        dev = actor.get("developer_id")
        return dev is not None and await self.s.developer_bought(dev, t["id"])

    async def _files_right(self, actor: Optional[Dict[str, Any]], t: Dict[str, Any]) -> None:
        """The right to a template's files: visible, and free or held by the owner or a buyer."""
        await self._see(actor, t)
        if t["pricing_model"] != "free" and not await self._owns_or_bought(actor, t):
            raise LibraryRefusal(402, "payment_required", BUY_FIRST + ", then use its files")

    @staticmethod
    def _agent(actor: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if not actor or actor.get("kind") != "agent" or not actor.get("did"):
            raise LibraryRefusal(401, "agent_only", "this step is an agent's (an agent JWT)")
        return actor

    async def _owner_only(self, actor: Optional[Dict[str, Any]], tid: str) -> Dict[str, Any]:
        a = self._agent(actor)
        t = await self._tpl(tid)
        if a["did"] != t["owner_agent_did"]:
            raise LibraryRefusal(403, "not_owner", "only the template's owner agent changes it")
        return t

    # -- the record, as shown --
    async def _current(self, t: Dict[str, Any], versions: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
        if not t.get("current_version_id"):
            return None
        versions = versions if versions is not None else await self.s.template_versions(t["id"])
        return next((v for v in versions if v["id"] == t["current_version_id"]), None)

    async def _counts(self, t: Dict[str, Any]) -> Dict[str, int]:
        if all(k in t for k in COUNT_KEYS):
            return {k: int(t.get(k) or 0) for k in COUNT_KEYS}
        return {k: int(v or 0) for k, v in (await self.s.counts(t["id"])).items()}

    async def _listing(self, t: Dict[str, Any], versions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        cur = await self._current(t, versions)
        return {
            "id": t["id"], "slug": t["slug"], "title": t["title"], "summary": t.get("summary"), "kind": t["kind"],
            "from_kind": t.get("from_kind"), "to_kind": t.get("to_kind"), "owner_agent_did": t["owner_agent_did"],
            "visibility": t["visibility"], "pricing_model": t["pricing_model"],
            "price": str(t["price"]) if t.get("price") is not None else None, "price_currency": t.get("price_currency"),
            "fork_share_bps": int(t.get("fork_share_bps") if t.get("fork_share_bps") is not None else DEFAULT_FORK_SHARE_BPS),
            "forked_from_template_id": t.get("forked_from_template_id"), "forked_from_version": t.get("forked_from_version"),
            "current_version": cur["version"] if cur else None, "current_content_hash": cur["content_hash"] if cur else None,
            "created_at": _iso(t.get("created_at")), "updated_at": _iso(t.get("updated_at")),
            "counts": await self._counts(t),
        }

    async def mine(self, actor: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """The caller's own templates (gwo_ef4d9981, for C4's My templates): an agent's, or every template of the agents
        a developer created; each with its listing, every version (drafts too) and its buyers (done purchases: the
        buyer's agent DID and the time, nothing else about a buyer)."""
        if actor and actor.get("kind") == "agent" and actor.get("did"):
            rows = await self.s.templates_of_agent(actor["did"])
        elif actor and actor.get("kind") == "developer" and actor.get("developer_id") is not None:
            rows = await self.s.templates_of_developer(int(actor["developer_id"]))
        else:
            raise LibraryRefusal(401, "signed_in", "your own templates need an agent or a developer token")
        items = []
        for t in rows[:MINE_MAX]:
            versions = await self.s.template_versions(t["id"])
            item = await self._listing(t, versions)
            item["versions"] = [{"version": v["version"], "published": v.get("published_at") is not None,
                                 "published_at": _iso(v.get("published_at")), "content_hash": v["content_hash"],
                                 "changelog": v.get("changelog")} for v in versions]
            buyers = await self.s.buyers(t["id"])
            item["buyers"] = {"count": len(buyers),
                              "list": [{"agent_did": b["buyer_did"], "at": _iso(b.get("done_at"))} for b in buyers]}
            items.append(item)
        return {"items": items}

    async def list(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        rows = await self.s.list_public(filters)
        return {"items": [await self._listing(t) for t in rows]}

    async def detail(self, actor: Optional[Dict[str, Any]], tid: str) -> Dict[str, Any]:
        t = await self._tpl(tid)
        await self._see(actor, t)
        versions = await self.s.template_versions(tid)
        owner = await self._is_owner(actor, t)
        shown = [v for v in versions if v.get("published_at") is not None or owner]
        out = await self._listing(t, versions)
        cur = await self._current(t, versions) or (shown[-1] if shown else None)
        out["versions"] = [{"version": v["version"], "content_hash": v["content_hash"], "changelog": v.get("changelog"),
                            "published_at": _iso(v.get("published_at"))} for v in shown]
        out["structure"] = structure(cur["manifest"]) if cur else None
        return out

    async def version(self, actor: Optional[Dict[str, Any]], tid: str, n: int, *, kit: bool = False) -> Dict[str, Any]:
        t = await self._tpl(tid)
        v = await self.s.version(tid, int(n))
        if not v or (v.get("published_at") is None and not await self._is_owner(actor, t)):
            raise LibraryRefusal(404, "not_found", "no such version")
        await self._files_right(actor, t)
        if kit:
            await self.s.add_use({"template_id": tid, "version": v["version"], "kind": "kit", "reference": None,
                                  "agent_did": actor.get("did") if actor and actor.get("kind") == "agent" else None,
                                  "at": self.s.now()})
        return {"template_id": tid, "version": v["version"], "manifest": v["manifest"], "files": v["files"],
                "content_hash": v["content_hash"], "changelog": v.get("changelog"),
                "published_at": _iso(v.get("published_at"))}

    # -- writes --
    def _kit(self, files: Any) -> Dict[str, Any]:
        try:
            return check_kit(files)
        except KitRefused as e:
            raise LibraryRefusal(422, "kit", e.sentence) from None

    @staticmethod
    def _pricing(pricing: Any, price: Any) -> Optional[Decimal]:
        if pricing not in PRICING:
            raise LibraryRefusal(422, "pricing_model", f"pricing_model is one of {', '.join(PRICING)}")
        if pricing == "free":
            return None
        p = _money(price)
        if p is None or p <= 0:
            raise LibraryRefusal(422, "price", "a purchase-priced template needs a price above zero")
        return p

    @staticmethod
    def _share(v: Any) -> int:
        if v is None:
            return DEFAULT_FORK_SHARE_BPS
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= MAX_FORK_SHARE_BPS:
            raise LibraryRefusal(422, "fork_share_bps", f"fork_share_bps is a whole number from 0 to {MAX_FORK_SHARE_BPS}")
        return v

    async def _new_version(self, tid: str, n: int, manifest: Dict[str, Any], files: Dict[str, str],
                           changelog: Optional[str]) -> Dict[str, Any]:
        row = {"id": "wtpv_" + secrets.token_hex(10), "template_id": tid, "version": n, "manifest": manifest,
               "files": files, "content_hash": content_hash(manifest, files),
               "changelog": (str(changelog)[:500] if changelog else None), "published_at": None, "created_at": self.s.now()}
        await self.s.insert_version(row)
        return row

    async def create(self, actor: Optional[Dict[str, Any]], body: Dict[str, Any]) -> Dict[str, Any]:
        a = self._agent(actor)
        slug = str(body.get("slug") or "")
        if not SLUG_RE.match(slug):
            raise LibraryRefusal(422, "slug", "a slug of 2 to 119 lowercase letters, digits and '-'")
        title = str(body.get("title") or "").strip()
        if not title or len(title) > 200:
            raise LibraryRefusal(422, "title", "a title of 1 to 200 characters")
        summary = body.get("summary")
        if summary is not None and len(str(summary)) > 500:
            raise LibraryRefusal(422, "summary", "a summary of at most 500 characters")
        if (body.get("kind") or "migration") != "migration":
            raise LibraryRefusal(422, "kind", "kind is migration (workflow templates come later)")
        visibility = body.get("visibility") or "private"
        if visibility not in VISIBILITY:
            raise LibraryRefusal(422, "visibility", f"visibility is one of {', '.join(VISIBILITY)}")
        pricing = body.get("pricing_model") or "free"
        price = self._pricing(pricing, body.get("price"))
        share = self._share(body.get("fork_share_bps"))
        manifest = self._kit(body.get("files"))
        if visibility != "private" or pricing != "free":
            await self._publish_gates(a["did"])       # shown to others, or priced: the gates, before anything is written
        if await self.s.slug_taken(a["did"], slug):
            raise LibraryRefusal(409, "slug_taken", "this agent already has a template with that slug")
        now = self.s.now()
        tid = "wtpl_" + secrets.token_hex(10)
        await self.s.insert_template({
            "id": tid, "slug": slug, "title": title, "summary": summary, "kind": "migration",
            "from_kind": manifest["from"]["kind"], "to_kind": manifest["to"]["kind"], "owner_agent_did": a["did"],
            "source_org_id": a.get("org"), "visibility": visibility, "pricing_model": pricing, "price": price,
            "price_currency": body.get("currency") or os.getenv("FRAME_CURRENCY", "AVT"), "fork_share_bps": share,
            "forked_from_template_id": None, "forked_from_version": None, "current_version_id": None,
            "created_at": now, "updated_at": now})
        v = await self._new_version(tid, 1, manifest, body["files"], body.get("changelog") or "first version")
        return {"template_id": tid, "version": 1, "version_id": v["id"], "content_hash": v["content_hash"],
                "published": False}

    async def add_version(self, actor: Optional[Dict[str, Any]], tid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        await self._owner_only(actor, tid)
        manifest = self._kit(body.get("files"))
        versions = await self.s.template_versions(tid)
        n = max((v["version"] for v in versions), default=0) + 1
        v = await self._new_version(tid, n, manifest, body["files"], body.get("changelog"))
        await self.s.update_template(tid, updated_at=self.s.now())
        return {"template_id": tid, "version": n, "version_id": v["id"], "content_hash": v["content_hash"],
                "published": False}

    async def publish(self, actor: Optional[Dict[str, Any]], tid: str, n: int) -> Dict[str, Any]:
        t = await self._owner_only(actor, tid)
        v = await self.s.version(tid, int(n))
        if not v:
            raise LibraryRefusal(404, "not_found", "no such version")
        if v.get("published_at") is not None:
            raise LibraryRefusal(409, "published", "a published version never changes: add a new version")
        if t["visibility"] != "private":
            await self._publish_gates(t["owner_agent_did"])  # a version others will see
        now = self.s.now()
        await self.s.update_version(v["id"], published_at=now)
        await self.s.update_template(tid, current_version_id=v["id"], from_kind=v["manifest"]["from"]["kind"],
                                     to_kind=v["manifest"]["to"]["kind"], updated_at=now)
        return {"template_id": tid, "version": v["version"], "content_hash": v["content_hash"], "published": True}

    async def patch(self, actor: Optional[Dict[str, Any]], tid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        t = await self._owner_only(actor, tid)
        extra = sorted(k for k in body if k not in PATCHABLE)
        if extra:
            raise LibraryRefusal(422, "content", f"a patch changes the listing, never the content ({', '.join(extra)}): "
                                                 f"add and publish a new version")
        fields: Dict[str, Any] = {}
        if "title" in body:
            title = str(body.get("title") or "").strip()
            if not title or len(title) > 200:
                raise LibraryRefusal(422, "title", "a title of 1 to 200 characters")
            fields["title"] = title
        if "summary" in body:
            if body["summary"] is not None and len(str(body["summary"])) > 500:
                raise LibraryRefusal(422, "summary", "a summary of at most 500 characters")
            fields["summary"] = body["summary"]
        if "visibility" in body:
            if body["visibility"] not in VISIBILITY:
                raise LibraryRefusal(422, "visibility", f"visibility is one of {', '.join(VISIBILITY)}")
            fields["visibility"] = body["visibility"]
        if "pricing_model" in body or "price" in body:
            pricing = body.get("pricing_model", t["pricing_model"])
            fields["pricing_model"] = pricing
            fields["price"] = self._pricing(pricing, body.get("price", t.get("price")))
        if "fork_share_bps" in body:
            fields["fork_share_bps"] = self._share(body["fork_share_bps"])
        if self._patch_publishes(t, fields):
            await self._publish_gates(t["owner_agent_did"])
        fields["updated_at"] = self.s.now()
        await self.s.update_template(tid, **fields)
        return await self._listing(await self._tpl(tid))

    async def _publish_gates(self, did: str) -> None:
        """What others see or pay for: the suspension gate first (a suspended author publishes nothing and sets no
        price, session-lead room seq 4002), then the reputation bond; both at site template_publish."""
        await self.s.enforcement_gate(did)
        await self.s.bond_gate(did)

    @staticmethod
    def _patch_publishes(t: Dict[str, Any], fields: Dict[str, Any]) -> bool:
        """A patch that shows the template to others (to public, unlisted or org from another visibility) or sets or
        raises its price; a lower price, a free template or a private one asks nothing."""
        vis = fields.get("visibility")
        if vis is not None and vis != "private" and vis != t["visibility"]:
            return True
        if fields.get("pricing_model", t["pricing_model"]) != "purchase":
            return False
        if t["pricing_model"] != "purchase":
            return True
        new, old = _money(fields.get("price")), _money(t.get("price"))
        return new is not None and (old is None or new > old)

    async def fork(self, actor: Optional[Dict[str, Any]], tid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        a = self._agent(actor)
        t = await self._tpl(tid)
        await self._files_right(a, t)
        cur = await self._current(t)
        if not cur:
            raise LibraryRefusal(409, "no_published_version", "the template has no published version to fork")
        slug = str(body.get("slug") or "")
        if slug:
            if not SLUG_RE.match(slug):
                raise LibraryRefusal(422, "slug", "a slug of 2 to 119 lowercase letters, digits and '-'")
            if await self.s.slug_taken(a["did"], slug):
                raise LibraryRefusal(409, "slug_taken", "this agent already has a template with that slug")
        else:
            slug = await self._fork_slug(a["did"], str(t.get("slug") or "template"))
        now = self.s.now()
        nid = "wtpl_" + secrets.token_hex(10)
        await self.s.insert_template({
            "id": nid, "slug": slug, "title": (str(body.get("title") or "") or f"Fork of {t['title']}")[:200],
            "summary": t.get("summary"), "kind": t["kind"], "from_kind": t.get("from_kind"), "to_kind": t.get("to_kind"),
            "owner_agent_did": a["did"], "source_org_id": a.get("org"), "visibility": "private", "pricing_model": "free",
            "price": None, "price_currency": t.get("price_currency"), "fork_share_bps": DEFAULT_FORK_SHARE_BPS,
            "forked_from_template_id": tid, "forked_from_version": cur["version"], "current_version_id": None,
            "created_at": now, "updated_at": now})
        await self._new_version(nid, 1, cur["manifest"], cur["files"], f"forked from {tid} v{cur['version']}")
        return {"template_id": nid, "slug": slug, "version": 1, "forked_from": tid, "forked_from_version": cur["version"],
                "published": False}

    async def _fork_slug(self, owner: str, parent_slug: str) -> str:
        """gwo_04e1334c (M8 step 4): a fork that names no slug (the CLI posts none) gets the parent's slug and "-fork", then
        "-fork-2", "-fork-3" ... the first this agent has not used; the parent's part is cut so the whole keeps the slug rule."""
        for n in range(1, 1000):
            tail = "-fork" if n == 1 else f"-fork-{n}"
            base = parent_slug[:119 - len(tail)].rstrip("-") or "template"
            cand = base + tail
            if SLUG_RE.match(cand) and not await self.s.slug_taken(owner, cand):
                return cand
        raise LibraryRefusal(409, "slug_taken", "no free fork slug is left for this agent: name one")

    # -- money --
    async def purchase(self, actor: Optional[Dict[str, Any]], tid: str) -> Dict[str, Any]:
        a = self._agent(actor)
        t = await self._tpl(tid)
        buyer = a["did"]
        row = await self.s.purchase_row(tid, buyer)
        if row is None:
            await self._see(a, t)
            if t["pricing_model"] != "purchase":
                raise LibraryRefusal(409, "not_for_sale", "this template is free: get its kit, nothing to buy")
            if buyer == t["owner_agent_did"]:
                return {"ok": True, "already": "owner"}
            # a suspended author sells nothing new (a purchase recorded before the suspension finishes as recorded)
            await self.s.enforcement_gate(t["owner_agent_did"])
            price = _money(t.get("price"))
            if price is None or price <= 0:
                raise LibraryRefusal(409, "no_price", "the template has no price set")
            parent = await self.s.template(t["forked_from_template_id"]) if t.get("forked_from_template_id") else None
            bps = int(parent.get("fork_share_bps") or 0) if parent else 0
            share = (price * bps / Decimal(10000)).quantize(_Q, rounding=ROUND_DOWN) if bps > 0 else Decimal(0)
            await self.s.insert_pending_purchase({
                "template_id": tid, "buyer_did": buyer, "price": price, "share": share,
                "currency": t.get("price_currency"), "author_did": t["owner_agent_did"],
                "parent_did": parent["owner_agent_did"] if share > 0 else None, "at": self.s.now()})
            # the record as stored: ours, or a concurrent first attempt's (one per buyer and template)
            row = await self.s.purchase_row(tid, buyer)
            if row is None:
                raise LibraryRefusal(409, "purchase_conflict", "another attempt of this purchase was withdrawn meanwhile: "
                                                               "try again")
        if row["status"] == "done":
            return {"ok": True, "already": "purchased"}
        # from here the record decides every amount and payee: what the first attempt deposited is what a retry pays
        price, share = _money(row["price"]), _money(row.get("share")) or Decimal(0)
        try:
            await self.s.deposit(buyer, price, f"wtpl:{tid}:{buyer}:in")
        except PaymentDeclined as e:
            if e.nothing_moved:
                await self.s.withdraw_pending_purchase(tid, buyer)
                raise LibraryRefusal(402, "payment_declined", f"the purchase was declined ({e}): nothing moved") from None
            raise LibraryRefusal(502, "deposit_unconfirmed", f"the ledger did not confirm the deposit ({e}): the purchase "
                                                             f"is recorded at {price} and a retry finishes it, the "
                                                             f"deposit moving once") from None
        await self.s.payout(row["author_did"], price - share, f"wtpl:{tid}:{buyer}:out")
        if share > 0:
            await self.s.payout(row["parent_did"], share, f"wtpl:{tid}:{buyer}:up")
        if await self.s.finish_purchase(row, self.s.now()):
            await self.s.emit("WorkflowTemplatePurchased", tid, {"buyer": buyer, "price": str(price)})
            logger.info("[WTPL] %s bought by %s for %s (parent share %s)", tid, buyer, price, share)
        return {"ok": True, "template_id": tid, "price": str(price), "currency": row.get("currency"),
                "parent_share": str(share) if share > 0 else None}

    # -- use --
    async def instantiate(self, actor: Optional[Dict[str, Any]], tid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        a = self._agent(actor)
        t = await self._tpl(tid)
        await self._files_right(a, t)
        if body.get("version") is not None:
            v = await self.s.version(tid, int(body["version"]))
            if not v or v.get("published_at") is None:
                raise LibraryRefusal(409, "no_published_version", "no published version with that number")
        else:
            v = await self._current(t)
            if not v:
                raise LibraryRefusal(409, "no_published_version", "the template has no published version")
        steps_in = (v.get("manifest") or {}).get("workflow") or []
        if not steps_in:
            raise LibraryRefusal(409, "no_workflow", "this template's manifest has no workflow section to run as a "
                                                     "workflow: run its kit with tp-proxy migrate")
        total = _money(body.get("total_budget"))
        if total is None or total <= 0:
            raise LibraryRefusal(422, "total_budget", "total_budget is the whole workflow's budget, above zero")
        steps = []
        for s, budget in zip(steps_in, self._step_budgets(steps_in, total)):
            step = {"key": s["key"], "role": s["role"], "budget": str(budget), "acceptance": s.get("acceptance"),
                    "spec": s.get("spec") or (f"Step {s['key']} of the migration template {t['title']} ({tid} "
                                              f"v{v['version']}, content {v['content_hash'][:12]})")}
            if s.get("input_from"):
                step["input_from"] = s["input_from"]
            steps.append(step)
        title = (str(body.get("title") or "") or f"{t['title']} (template {tid} v{v['version']})")[:200]
        wf_body: Dict[str, Any] = {"title": title, "steps": steps, "total_budget": str(total)}
        if body.get("currency"):
            wf_body["currency"] = body["currency"]
        wid = await self.s.create_workflow(a["did"], wf_body)
        await self.s.set_provenance(wid, tid, v["version"], v["content_hash"])
        await self.s.add_use({"template_id": tid, "version": v["version"], "agent_did": a["did"], "kind": "instantiate",
                              "reference": wid, "at": self.s.now()})
        return {"workflow_id": wid, "template_id": tid, "version": v["version"], "content_hash": v["content_hash"]}

    @staticmethod
    def _step_budgets(steps: List[Dict[str, Any]], total: Decimal) -> List[Decimal]:
        """A step's budget: its budget_share percent of the total; the steps that name no share split what the named
        shares leave, evenly (M3's schema makes the share optional). A step left with nothing refuses the instantiate."""
        named = sum(int(s["budget_share"]) for s in steps if s.get("budget_share") is not None)
        if named > 100:
            raise LibraryRefusal(409, "budget_share", f"the workflow's budget shares add up to {named}, above 100")
        unnamed = sum(1 for s in steps if s.get("budget_share") is None)
        out = []
        for s in steps:
            part = (total * Decimal(int(s["budget_share"])) / Decimal(100) if s.get("budget_share") is not None
                    else total * Decimal(100 - named) / Decimal(100) / Decimal(unnamed))
            budget = part.quantize(_Q, rounding=ROUND_DOWN)
            if budget <= 0:
                raise LibraryRefusal(409, "budget_share", f"the step {s['key']} would get no budget: give it a "
                                                          f"budget_share above zero, or leave room for it")
            out.append(budget)
        return out

    async def certified(self, actor: Optional[Dict[str, Any]], tid: str, body: Dict[str, Any]) -> Dict[str, Any]:
        a = self._agent(actor)
        t = await self._tpl(tid)
        await self._see(a, t)
        att_id = str(body.get("attestation_id") or "")
        if not att_id or len(att_id) > 120:
            raise LibraryRefusal(422, "attestation_id", "attestation_id names the certificate's attestation")
        data = body.get("attestation_data")
        if not isinstance(data, dict):
            raise LibraryRefusal(422, "attestation_data", "attestation_data is the exact data the certificate was "
                                                          "submitted with")
        att = next((x for x in await self.s.agent_attestations(a["did"])
                    if str(x.get("attestation_id")) == att_id and x.get("attestation_type") == CERTIFICATE_TYPE), None)
        if att is None:
            raise LibraryRefusal(409, "no_attestation", f"this agent submitted no {CERTIFICATE_TYPE} attestation with "
                                                        f"that id")
        # the hash the registry's submit computed (routers/teg_integration: sha256 of json.dumps(data, sort_keys=True))
        if hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest() != att.get("hash"):
            raise LibraryRefusal(409, "hash", "the data posted is not the data the attestation was submitted with")
        claim = data.get("claim") if isinstance(data.get("claim"), dict) else {}
        named = claim.get("template") if isinstance(claim.get("template"), dict) else {}
        hashes = {v["content_hash"] for v in await self.s.template_versions(tid) if v.get("published_at") is not None}
        if named.get("id") != tid or named.get("content_hash") not in hashes:
            raise LibraryRefusal(409, "other_template", "the certificate names another template or a content hash none "
                                                        "of this template's published versions has")
        if claim.get("verdict") != "pass":
            raise LibraryRefusal(409, "not_pass", "the certificate's verdict is not pass")
        if await self.s.certified_by(tid, a["did"]):
            return {"ok": True, "already": True, "template_id": tid}
        await self.s.add_use({"template_id": tid, "version": named.get("version"), "agent_did": a["did"],
                              "kind": "certified", "reference": att_id, "at": self.s.now()})
        return {"ok": True, "already": False, "template_id": tid}


# --- the store on the database ---------------------------------------------------------------------------------------

def _j(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


class DbStore:
    """Library's store on the registry database (text SQL, as routers/contract_templates.py). Writes commit as they go;
    money goes through services/escrow only."""

    def __init__(self, db: Any) -> None:
        self.db = db

    async def _rows(self, sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        from sqlalchemy import text
        return [dict(r) for r in (await self.db.execute(text(sql), params or {})).mappings().all()]

    async def _exec(self, sql: str, params: Dict[str, Any]) -> None:
        from sqlalchemy import text
        await self.db.execute(text(sql), params)
        await self.db.commit()

    async def _exec_rows(self, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        from sqlalchemy import text
        rows = [dict(r) for r in (await self.db.execute(text(sql), params)).mappings().all()]
        await self.db.commit()
        return rows

    @staticmethod
    def _version_row(r: Dict[str, Any]) -> Dict[str, Any]:
        r["manifest"], r["files"] = _j(r.get("manifest")), _j(r.get("files"))
        return r

    async def template(self, tid: str) -> Optional[Dict[str, Any]]:
        rows = await self._rows("SELECT * FROM workflow_templates WHERE id = :t", {"t": tid})
        return rows[0] if rows else None

    async def template_versions(self, tid: str) -> List[Dict[str, Any]]:
        return [self._version_row(r) for r in await self._rows(
            "SELECT * FROM workflow_template_versions WHERE template_id = :t ORDER BY version", {"t": tid})]

    async def version(self, tid: str, n: int) -> Optional[Dict[str, Any]]:
        rows = await self._rows("SELECT * FROM workflow_template_versions WHERE template_id = :t AND version = :n",
                                {"t": tid, "n": n})
        return self._version_row(rows[0]) if rows else None

    async def slug_taken(self, owner: str, slug: str) -> bool:
        return bool(await self._rows("SELECT 1 AS hit FROM workflow_templates WHERE owner_agent_did = :o AND slug = :s",
                                     {"o": owner, "s": slug}))

    async def purchased(self, tid: str, did: str) -> bool:
        return bool(await self._rows("SELECT 1 AS hit FROM workflow_template_purchases WHERE template_id = :t "
                                     "AND buyer_did = :b AND status = 'done'", {"t": tid, "b": did}))

    async def purchase_row(self, tid: str, did: str) -> Optional[Dict[str, Any]]:
        rows = await self._rows("SELECT * FROM workflow_template_purchases WHERE template_id = :t AND buyer_did = :b",
                                {"t": tid, "b": did})
        return rows[0] if rows else None

    async def developer_owns(self, dev: int, did: str) -> bool:
        return bool(await self._rows("SELECT 1 AS hit FROM agents WHERE did = :d AND creator_developer_id = :dev",
                                     {"d": did, "dev": dev}))

    async def developer_bought(self, dev: int, tid: str) -> bool:
        return bool(await self._rows("SELECT 1 AS hit FROM workflow_template_purchases p JOIN agents a ON a.did = p.buyer_did "
                                     "WHERE p.template_id = :t AND p.status = 'done' AND a.creator_developer_id = :dev LIMIT 1",
                                     {"t": tid, "dev": dev}))

    async def developer_in_org(self, dev: int, org: str) -> bool:
        return bool(await self._rows("SELECT 1 AS hit FROM agents WHERE creator_developer_id = :dev "
                                     "AND organization_id = :org LIMIT 1", {"dev": dev, "org": str(org)}))

    # instantiations and certified count distinct developers (the agents' creator), so one developer's many agents
    # count once; an agent this registry has no row for counts as itself (room seq 3873)
    _BY_DEVELOPER = ("count(DISTINCT COALESCE('dev:' || CAST(a.creator_developer_id AS TEXT), 'agent:' || u.agent_did)) "
                     "FROM workflow_template_uses u LEFT JOIN agents a ON a.did = u.agent_did WHERE u.template_id = t.id")
    _COUNTS = ("(SELECT count(*) FROM workflow_template_uses u WHERE u.template_id = t.id AND u.kind = 'kit') AS kit_downloads, "
               f"(SELECT {_BY_DEVELOPER} AND u.kind = 'instantiate') AS instantiations, "
               f"(SELECT {_BY_DEVELOPER} AND u.kind = 'certified') AS certified, "
               "(SELECT count(*) FROM workflow_templates f WHERE f.forked_from_template_id = t.id) AS forks")

    async def counts(self, tid: str) -> Dict[str, int]:
        rows = await self._rows(f"SELECT {self._COUNTS} FROM workflow_templates t WHERE t.id = :t", {"t": tid})
        return rows[0] if rows else {k: 0 for k in COUNT_KEYS}

    async def list_public(self, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        from . import enforcement_propagation as ep
        where, params = ["t.visibility = 'public'"], {}
        if ep.propagation_mode() == "enforce":     # a suspended or revoked author's templates leave the list (as discovery)
            where.append("NOT EXISTS (SELECT 1 FROM agents ea WHERE ea.did = t.owner_agent_did "
                         "AND ea.status IN ('suspended', 'revoked'))")
        for key, col in (("kind", "kind"), ("from", "from_kind"), ("to", "to_kind"), ("pricing", "pricing_model")):
            if filters.get(key):
                where.append(f"t.{col} = :{key}")
                params[key] = str(filters[key])[:20]
        if filters.get("q"):
            where.append("(t.title ILIKE :q OR t.summary ILIKE :q OR t.slug ILIKE :q)")
            params["q"] = f"%{str(filters['q'])[:80]}%"
        order = {"uses": "kit_downloads DESC, t.id DESC", "certified": "certified DESC, t.id DESC"}.get(
            str(filters.get("sort") or "new"), "t.created_at DESC, t.id DESC")
        params["lim"] = max(1, min(int(filters.get("limit") or 50), 100))
        return await self._rows(f"SELECT t.*, {self._COUNTS} FROM workflow_templates t WHERE {' AND '.join(where)} "
                                f"ORDER BY {order} LIMIT :lim", params)

    async def templates_of_agent(self, did: str) -> List[Dict[str, Any]]:
        return await self._rows("SELECT * FROM workflow_templates WHERE owner_agent_did = :d ORDER BY updated_at DESC, id "
                                f"LIMIT {MINE_MAX}", {"d": did})

    async def templates_of_developer(self, dev: int) -> List[Dict[str, Any]]:
        return await self._rows("SELECT t.* FROM workflow_templates t JOIN agents a ON a.did = t.owner_agent_did "
                                "WHERE a.creator_developer_id = :dev ORDER BY t.updated_at DESC, t.id "
                                f"LIMIT {MINE_MAX}", {"dev": dev})

    async def buyers(self, tid: str) -> List[Dict[str, Any]]:
        """The done purchases of a template: who (the buyer's agent DID) and when, nothing else."""
        return await self._rows("SELECT buyer_did, done_at FROM workflow_template_purchases WHERE template_id = :t "
                                "AND status = 'done' ORDER BY done_at, buyer_did", {"t": tid})

    async def certified_by(self, tid: str, did: str) -> bool:
        return bool(await self._rows("SELECT 1 AS hit FROM workflow_template_uses WHERE template_id = :t "
                                     "AND kind = 'certified' AND agent_did = :d", {"t": tid, "d": did}))

    async def agent_attestations(self, did: str) -> List[Dict[str, Any]]:
        """This agent's own TEG attestations, read as routers/teg_integration.list_attestations reads them for it: GET
        <teg>/attestation with the agent's TEG token through prepare_teg_headers (gwo_a0af9f35: the import, the path and the
        headers were wrong and nothing ran this; tests/test_workflow_templates_certified_v0664.py runs it)."""
        from .. import models                                    # the ORM, and the router's TEG door: imported where used
        from ..routers.teg_integration import TEG_API_BASE_URL, TEG_API_V1_PREFIX, get_teg_token_for_agent, prepare_teg_headers
        agent = (await self.db.execute(select(models.Agent).where(models.Agent.did == did))).scalar_one_or_none()
        if agent is None:
            return []
        token = await get_teg_token_for_agent(agent.id, did)
        async with httpx.AsyncClient(verify=get_httpx_verify(), timeout=20.0) as client:
            r = await client.get(f"{TEG_API_BASE_URL}{TEG_API_V1_PREFIX}/attestation", headers=prepare_teg_headers(token),
                                 params={"attestation_type": CERTIFICATE_TYPE, "limit": 1000})   # the TEG's page limit
        if r.status_code != 200:
            raise LibraryRefusal(503, "ledger_unavailable", f"the ledger did not answer for this agent's attestations "
                                                            f"(HTTP {r.status_code})")
        data = r.json()
        items = data if isinstance(data, list) else data.get("attestations", data.get("items", []))
        return [{"attestation_id": str(x.get("submission_id") or x.get("attestation_id") or ""),
                 "attestation_type": x.get("attestation_type"), "hash": x.get("attestation_hash")} for x in items]

    async def insert_template(self, row: Dict[str, Any]) -> None:
        await self._exec(
            "INSERT INTO workflow_templates (id, slug, title, summary, kind, from_kind, to_kind, owner_agent_did, "
            "source_org_id, visibility, pricing_model, price, price_currency, fork_share_bps, forked_from_template_id, "
            "forked_from_version, current_version_id, created_at, updated_at) VALUES (:id, :slug, :title, :summary, "
            ":kind, :from_kind, :to_kind, :owner_agent_did, :source_org_id, :visibility, :pricing_model, :price, "
            ":price_currency, :fork_share_bps, :forked_from_template_id, :forked_from_version, :current_version_id, "
            ":created_at, :updated_at)", row)

    _TEMPLATE_COLS = ("title", "summary", "visibility", "pricing_model", "price", "fork_share_bps", "current_version_id",
                      "from_kind", "to_kind", "updated_at")

    async def update_template(self, tid: str, **fields: Any) -> None:
        cols = [k for k in fields if k in self._TEMPLATE_COLS]
        if not cols:
            return
        await self._exec(f"UPDATE workflow_templates SET {', '.join(f'{c} = :{c}' for c in cols)} WHERE id = :tid",
                         {**{c: fields[c] for c in cols}, "tid": tid})

    async def insert_version(self, row: Dict[str, Any]) -> None:
        await self._exec(
            "INSERT INTO workflow_template_versions (id, template_id, version, manifest, files, content_hash, changelog, "
            "published_at, created_at) VALUES (:id, :template_id, :version, CAST(:manifest AS JSONB), "
            "CAST(:files AS JSONB), :content_hash, :changelog, :published_at, :created_at)",
            {**row, "manifest": json.dumps(row["manifest"]), "files": json.dumps(row["files"])})

    async def update_version(self, vid: str, **fields: Any) -> None:
        if set(fields) != {"published_at"}:
            raise ValueError("a version changes only by being published")
        # a published version never changes: the guard is in the statement too
        await self._exec("UPDATE workflow_template_versions SET published_at = :p WHERE id = :v AND published_at IS NULL",
                         {"p": fields["published_at"], "v": vid})

    async def enforcement_gate(self, did: str) -> None:
        """services/enforcement_propagation.gate at site template_publish: off passes, shadow counts, enforce refuses a
        suspended or revoked agent with the enforcement sentence, returned as the library's refusal."""
        from fastapi import HTTPException
        from . import enforcement_propagation as ep
        try:
            await ep.gate(self.db, did, site="template_publish")
        except HTTPException as e:
            if e.status_code == 403:
                raise LibraryRefusal(403, "enforced", str(e.detail)) from None
            raise

    async def bond_gate(self, did: str) -> None:
        """services/reputation_bond.gate at site template_publish: off passes, shadow counts, enforce refuses with the
        gate's own sentence (the amount and the door), returned as the library's refusal."""
        from fastapi import HTTPException
        from . import reputation_bond as rb
        try:
            await rb.gate(self.db, did, site="template_publish")
        except HTTPException as e:
            if e.status_code == 403:
                raise LibraryRefusal(403, "bond_required", str(e.detail)) from None
            raise

    async def deposit(self, did: str, amount: Decimal, ref: str) -> None:
        from . import escrow
        try:
            await escrow.escrow_deposit(did, amount, ref, reason="contract_escrow")
        except escrow.EscrowError as e:
            from .ledger_unavailable import refusal_from_error   # §LEDGERGATE (V0598): the ledger's own refusal
            refusal = refusal_from_error(e)
            if refusal is not None:
                raise refusal
            raise PaymentDeclined(e.message, status=e.status_code) from None

    async def payout(self, did: str, amount: Decimal, ref: str) -> None:
        from . import escrow
        await escrow.escrow_payout(self.db, did, amount, ref, reason="contract_settle")

    _PURCHASE_INSERT = ("INSERT INTO workflow_template_purchases (template_id, buyer_did, price, share, currency, "
                        "author_did, parent_did, status, created_at, done_at) VALUES (:template_id, :buyer_did, :price, "
                        ":share, :currency, :author_did, :parent_did, :status, :at, :done_at) "
                        "ON CONFLICT (template_id, buyer_did) DO NOTHING")

    async def insert_pending_purchase(self, row: Dict[str, Any]) -> None:
        """The record, committed before the deposit (a first attempt that dies after it leaves the amounts behind)."""
        await self._exec(self._PURCHASE_INSERT, {**row, "status": "pending", "done_at": None})

    async def withdraw_pending_purchase(self, tid: str, did: str) -> None:
        await self._exec("DELETE FROM workflow_template_purchases WHERE template_id = :t AND buyer_did = :b "
                         "AND status = 'pending'", {"t": tid, "b": did})

    async def finish_purchase(self, row: Dict[str, Any], at: dt.datetime) -> bool:
        """pending -> done, once (True for the attempt that flipped it). A record a concurrent attempt withdrew on its
        clean decline after this attempt's deposit took is written back done."""
        flipped = await self._exec_rows("UPDATE workflow_template_purchases SET status = 'done', done_at = :at "
                                        "WHERE template_id = :t AND buyer_did = :b AND status = 'pending' RETURNING id",
                                        {"at": at, "t": row["template_id"], "b": row["buyer_did"]})
        if flipped:
            return True
        back = {k: row.get(k) for k in ("template_id", "buyer_did", "price", "share", "currency", "author_did",
                                        "parent_did")}
        return bool(await self._exec_rows(self._PURCHASE_INSERT + " RETURNING id",
                                          {**back, "status": "done", "at": row.get("created_at") or at, "done_at": at}))

    async def add_use(self, row: Dict[str, Any]) -> None:
        await self._exec("INSERT INTO workflow_template_uses (template_id, version, agent_did, kind, reference, at) "
                         "VALUES (:template_id, :version, :agent_did, :kind, :reference, :at) ON CONFLICT DO NOTHING", row)

    async def emit(self, event: str, tid: str, data: Dict[str, Any]) -> None:
        from . import contract_settlement as cs   # the emitter contract templates use for ContractTemplatePurchased
        cs.emit(event, tid, data)

    async def create_workflow(self, owner_did: str, body: Dict[str, Any]) -> str:
        from . import workflows
        return (await workflows.create(self.db, owner_did, body))["id"]

    async def set_provenance(self, wid: str, tid: str, version: int, content_hash: str) -> None:
        await self._exec("UPDATE agent_workflows SET template_id = :t, template_version = :v, template_content_hash = :h "
                         "WHERE id = :w", {"t": tid, "v": version, "h": content_hash, "w": wid})

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


def store_for(db: Any) -> DbStore:
    return DbStore(db)
