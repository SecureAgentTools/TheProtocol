"""The proxy's spec (proxy.yaml): what it reads, how it maps, what it does, where it delivers, and its limits.

    version: 1
    name: hansa-gate
    registry: https://api.theprotocol.cloud
    identity:
      agent_did: env:AGENT_DID
      client_id: env:CLIENT_ID
      client_secret: env:CLIENT_SECRET        # a reference, never the secret itself
      mtls: {enabled: false, dir: ./certs}
    state: ./proxy-state.db                    # the durable outbox (SQLite, WAL)
    sources:
      gate: {type: webhook, config: {listen: "0.0.0.0:8711", path: /in/gate, id_field: event_id, secret: env:GATE_HMAC}}
    actions:
      attest: {type: attestation, config: {attestation_type: tos.gate_out}, limits: {per_minute: 60}}
    sinks: {}
    mappings:
      - {name: gate-out, version: 1, from: gate, to: attest,
         when: {path: $.payload.status, equals: OUT},
         fields: {container: $.payload.container_id, at: $.payload.timestamp, terminal: HAM-CTA}}
    retry: {first_s: 2, max_s: 300, attempts: 8}
    breaker: {refusals: 5}
    service: {listen: 127.0.0.1:9108}

A secret is never written in the spec. A value is a reference wherever the spec holds a credential: `env:NAME` (an
environment variable), `file:/path` (a file's content) or `file:/path#KEY` (one KEY=value line of a dotenv file, such
as the Agent Forge starter's .env.secret). That holds for identity.client_secret, every plugin field whose schema marks
it "x-secret", and every key whose name says it holds one (secret, password, token, api key, private key). A literal
value there is refused at load, naming its path. The spec is checked against the core's schema and each plugin's config
against the plugin's own config_schema.

A mapping goes from a source to an action (inbound: the legacy system's record becomes a call on TheProtocol) or to a
sink (outbound: a source of TheProtocol's events, delivered to a legacy system); actions and sinks share one namespace.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .plugins import PluginError, load

SPEC_VERSION = 1
REF = re.compile(r"^(env|file):(.+)$")
# a key whose NAME ends in a secret word holds a credential (client_secret, password, access_token, api_key); a key
# that only mentions one (token_url, secret_field) does not
SECRET_KEY = re.compile(r"(?:^|[_-])(?:secret|password|passwd|passphrase|token|api[_-]?key|private[_-]?key|credentials?)s?$",
                        re.I)
NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$"

_PLUGIN_SECTION = {
    "type": "object",
    "required": ["type"],
    "additionalProperties": False,
    "properties": {
        "type": {"type": "string"},
        "config": {"type": "object"},
        "limits": {"type": "object", "additionalProperties": False,
                   "properties": {"per_minute": {"type": "number", "exclusiveMinimum": 0}}},
    },
}

CORE_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["version", "name", "registry", "identity"],
    "additionalProperties": False,
    "properties": {
        "version": {"const": SPEC_VERSION},
        "name": {"type": "string", "pattern": NAME},
        "registry": {"type": "string", "pattern": "^https?://"},
        "identity": {
            "type": "object", "additionalProperties": False,
            "required": ["agent_did", "client_id", "client_secret"],
            "properties": {
                "agent_did": {"type": "string"},
                "client_id": {"type": "string"},
                "client_secret": {"type": "string", "x-secret": True},
                "mtls": {"type": "object", "additionalProperties": False,
                         "properties": {"enabled": {"type": "boolean"}, "dir": {"type": "string"}}},
            },
        },
        "state": {"type": "string"},
        "sources": {"type": "object", "propertyNames": {"pattern": NAME}, "additionalProperties": _PLUGIN_SECTION},
        "actions": {"type": "object", "propertyNames": {"pattern": NAME}, "additionalProperties": _PLUGIN_SECTION},
        "sinks": {"type": "object", "propertyNames": {"pattern": NAME}, "additionalProperties": _PLUGIN_SECTION},
        "mappings": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "version", "from", "to", "fields"],
            "properties": {
                "name": {"type": "string", "pattern": NAME},
                "version": {"type": "integer", "minimum": 1},
                "from": {"type": "string"},
                "to": {"type": "string"},
                "when": {"type": "object"},
                "fields": {"type": "object"},
            },
        }},
        "retry": {"type": "object", "additionalProperties": False, "properties": {
            "first_s": {"type": "number", "exclusiveMinimum": 0}, "max_s": {"type": "number", "exclusiveMinimum": 0},
            "attempts": {"type": "integer", "minimum": 1}}},
        "breaker": {"type": "object", "additionalProperties": False, "properties": {
            "refusals": {"type": "integer", "minimum": 1},
            "failures": {"type": "integer", "minimum": 1},
            "cooldown_s": {"type": "number", "exclusiveMinimum": 0}}},
        "service": {"type": "object", "additionalProperties": False, "properties": {
            "enabled": {"type": "boolean"},
            "listen": {"type": "string", "pattern": r"^[^:]*:\d+$"}}},
    },
}


class SpecError(ValueError):
    """The spec cannot run as written; the message names every problem, with its path."""

    def __init__(self, problems: List[str]):
        self.problems = list(problems)
        super().__init__("the proxy's spec is refused:\n  - " + "\n  - ".join(self.problems))


def is_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(REF.match(value.strip()))


def resolve(ref: str, *, base: Optional[Path] = None, environ: Optional[Mapping[str, str]] = None) -> str:
    """The value a reference names: `env:NAME` (an environment variable), `file:/path` (a file's content, stripped;
    a relative path is read from the spec's folder)."""
    m = REF.match((ref or "").strip())
    if not m:
        raise SpecError([f"{ref!r} is not a reference (env:NAME or file:/path)"])
    kind, what = m.group(1), m.group(2).strip()
    env = os.environ if environ is None else environ
    if kind == "env":
        if what not in env:
            raise SpecError([f"the environment variable {what} is not set"])
        return env[what]
    what, _, key = what.partition("#")
    p = Path(what)
    if not p.is_absolute() and base is not None:
        p = base / p
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise SpecError([f"the file {p} cannot be read: {e.strerror or e}"])
    if not key:
        return text.strip()
    found = dotenv_value(text, key.strip())
    if found is None:
        raise SpecError([f"the file {p} has no line {key.strip()}=..."])
    return found


def dotenv_value(text: str, key: str) -> Optional[str]:
    """KEY's value in a dotenv text (`KEY=value`, `export KEY=value`, quotes taken off); None when it has no such line."""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        k, sep, v = line.partition("=")
        if sep and k.strip() == key:
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            return v
    return None


def _secret_paths(schema: Mapping[str, Any], prefix: str = "") -> List[str]:
    """The dotted paths a JSON Schema marks "x-secret"."""
    out = []
    props = schema.get("properties") if isinstance(schema, Mapping) else None
    for key, sub in (props or {}).items():
        path = f"{prefix}{key}"
        if isinstance(sub, Mapping):
            if sub.get("x-secret"):
                out.append(path)
            out.extend(_secret_paths(sub, path + "."))
    return out


def _get(doc: Any, path: str) -> Any:
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, Mapping) or part not in cur:
            return None
        cur = cur[part]
    return cur


def literal_secrets(doc: Any, *, declared: Tuple[str, ...] = (), prefix: str = "") -> List[str]:
    """Paths in `doc` that hold a credential written out: a declared secret path, or any key whose name says it holds
    one, with a value that is not a reference."""
    out = []
    for path in declared:
        v = _get(doc, path)
        if v not in (None, "") and not is_ref(v):
            out.append(f"{prefix}{path}")

    def walk(node: Any, at: str) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                p = f"{at}.{k}" if at else str(k)
                if isinstance(v, str) and v and SECRET_KEY.search(str(k).strip()) and not is_ref(v):
                    out.append(f"{prefix}{p}")
                walk(v, p)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{at}[{i}]")
    walk(doc, "")
    return sorted(set(out))


def _validate(instance: Any, schema: Mapping[str, Any], where: str) -> List[str]:
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - the [proxy] extra brings it
        raise SpecError(["the spec cannot be checked: install theprotocol-sdk[proxy] (jsonschema)"])
    validator = jsonschema.Draft202012Validator(schema)
    out = []
    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        path = ".".join(str(p) for p in err.absolute_path)
        out.append(f"{where}{('.' + path) if path else ''}: {err.message}")
    return out


@dataclass(frozen=True)
class PluginSpec:
    kind: str
    name: str            # the section's name in the spec
    type: str            # the plugin's name
    config: Dict[str, Any]
    per_minute: Optional[float] = None


@dataclass(frozen=True)
class MappingSpec:
    name: str
    version: int
    source: str
    action: str          # the action or sink it delivers to
    fields: Dict[str, Any]
    when: Optional[Dict[str, Any]] = None
    kind: str = "action"  # "action" (inbound) or "sink" (outbound)


@dataclass(frozen=True)
class Spec:
    name: str
    registry: str
    identity: Dict[str, Any]
    state: str
    sources: Dict[str, PluginSpec]
    actions: Dict[str, PluginSpec]
    sinks: Dict[str, PluginSpec]
    mappings: List[MappingSpec]
    retry: Dict[str, Any] = field(default_factory=dict)
    breaker: Dict[str, Any] = field(default_factory=dict)
    service: Dict[str, Any] = field(default_factory=dict)
    base: Optional[Path] = None

    def secret(self, ref: str) -> str:
        return resolve(ref, base=self.base)

    def value(self, v: Any) -> Any:
        """A spec value as the proxy uses it: a reference resolved, anything else as written."""
        return self.secret(v) if is_ref(v) else v

    @property
    def state_path(self) -> str:
        """The outbox file, a relative path read from the spec's folder."""
        p = Path(self.state)
        if not p.is_absolute() and self.base is not None:
            p = self.base / p
        return str(p)

    def secret_values(self) -> List[str]:
        """Every secret this spec references, resolved (for the log redactor); those that cannot resolve are left out."""
        refs = []
        def walk(node: Any) -> None:
            if isinstance(node, Mapping):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif is_ref(node):
                refs.append(node)
        walk(self.identity)
        for group in (self.sources, self.actions, self.sinks):
            for p in group.values():
                walk(p.config)
        out = []
        for r in refs:
            try:
                v = self.secret(r)
            except SpecError:
                continue
            if v and len(v) >= 4:
                out.append(v)
        return out


def parse(doc: Any, *, base: Optional[Path] = None, check_plugins: bool = True) -> Spec:
    """A spec document (already read) to a Spec, or SpecError naming every problem."""
    problems = _validate(doc, CORE_SCHEMA, "spec")
    if problems:
        raise SpecError(problems)
    problems.extend(literal_secrets(doc.get("identity") or {}, declared=("client_secret",), prefix="identity."))
    groups: Dict[str, Dict[str, PluginSpec]] = {}
    for kind, section in (("source", "sources"), ("action", "actions"), ("sink", "sinks")):
        groups[kind] = {}
        for name, sec in (doc.get(section) or {}).items():
            cfg = dict(sec.get("config") or {})
            where = f"{section}.{name}"
            if check_plugins:
                try:
                    cls = load(kind, sec["type"])
                except PluginError as e:
                    problems.append(f"{where}.type: {e}")
                    cls = None
                if cls is not None:
                    problems.extend(_validate(cfg, cls.config_schema, f"{where}.config"))
                    problems.extend(literal_secrets(cfg, declared=tuple(_secret_paths(cls.config_schema)),
                                                    prefix=f"{where}.config."))
            else:
                problems.extend(literal_secrets(cfg, prefix=f"{where}.config."))
            groups[kind][name] = PluginSpec(kind, name, sec["type"], cfg, (sec.get("limits") or {}).get("per_minute"))
    for both in sorted(set(groups["action"]) & set(groups["sink"])):
        problems.append(f"sinks.{both}: an action is called {both!r} too (actions and sinks share one namespace)")
    mappings = []
    seen = set()
    for i, m in enumerate(doc.get("mappings") or []):
        where = f"mappings[{i}]"
        if m["name"] in seen:
            problems.append(f"{where}.name: {m['name']!r} names another mapping too")
        seen.add(m["name"])
        if m["from"] not in groups["source"]:
            problems.append(f"{where}.from: no source called {m['from']!r}")
        if m["to"] not in groups["action"] and m["to"] not in groups["sink"]:
            problems.append(f"{where}.to: no action or sink called {m['to']!r}")
        mappings.append(MappingSpec(m["name"], int(m["version"]), m["from"], m["to"], dict(m["fields"]),
                                    dict(m["when"]) if m.get("when") else None,
                                    "sink" if m["to"] in groups["sink"] else "action"))
    if problems:
        raise SpecError(problems)
    return Spec(name=doc["name"], registry=doc["registry"].rstrip("/"), identity=dict(doc["identity"]),
                state=doc.get("state") or f"{doc['name']}.proxy.db", sources=groups["source"],
                actions=groups["action"], sinks=groups["sink"], mappings=mappings, retry=dict(doc.get("retry") or {}),
                breaker=dict(doc.get("breaker") or {}), service=dict(doc.get("service") or {}), base=base)


def read(path: str, *, check_plugins: bool = True) -> Spec:
    """Read proxy.yaml (YAML or JSON) from `path` and parse it."""
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as e:
        raise SpecError([f"{p}: {e.strerror or e}"])
    if p.suffix.lower() == ".json":
        doc = json.loads(text)
    else:
        try:
            import yaml
        except ImportError:  # pragma: no cover
            raise SpecError(["a YAML spec needs theprotocol-sdk[proxy] (PyYAML)"])
        doc = yaml.safe_load(text)
    if not isinstance(doc, dict):
        raise SpecError([f"{p}: the spec is not a mapping"])
    return parse(doc, base=p.parent.resolve(), check_plugins=check_plugins)
