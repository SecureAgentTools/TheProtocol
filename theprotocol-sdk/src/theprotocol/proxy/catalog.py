"""The catalog: what the proxy's console builders are made from (V0664, C1).

`tp-proxy catalog --json` prints ONE document, the same every time for the same SDK:

  plugins          every built-in plugin by kind: its name, the class that implements it, its description and its config_schema
                   (a JSON Schema; a field that holds a credential carries "x-secret": true), loaded the way the core loads them,
                   so a plugin whose optional driver is missing is still described from its class (the drivers are imported when a
                   plugin STARTS). A plugin that does not load at all is listed with the CLASS of its error and nothing else
                   (a message could carry a value). `internal: true` marks a plugin no spec should name (the sample stand-in).
  core_schema      the spec's CORE_SCHEMA
  migration        the manifest schema of a migration kit and the kit caps
  value_nodes      the vocabulary of a mapping's value nodes: the keys, the `as` types, the case values and the order the steps run in
  sdk_version      the SDK it was made from

It reads the live objects (no second copy), so a console built from it accepts what the SDK accepts. The stack's
scripts/distribution/gen_proxy_catalog.py writes it into the console and checks that the copy there equals a fresh one.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

SCHEMA_ID = "theprotocol.proxy.catalog/v1"
# plugins that exist for the tool's own use: a spec never names them (tp-proxy migrate --sample reads a kit's sample through one)
INTERNAL = {("source", "migrate_sample")}
# the order a value node's steps run in (mapping._steps): `format` and `tz` belong to `as`
STEP_ORDER = ["null_if", "trim", "case", "regex", "map", "as", "round"]


def _plain(doc: Any) -> Any:
    """The document as JSON holds it (tuples as lists, keys as text), so that the catalog equals what a parse of it gives."""
    return json.loads(json.dumps(doc, default=str))


def _plugin(kind: str, name: str, where: str) -> Dict[str, Any]:
    from . import plugins
    out: Dict[str, Any] = {"kind": kind, "name": name, "class": where, "internal": (kind, name) in INTERNAL}
    try:
        cls = plugins.load(kind, name)
    except plugins.PluginError as e:
        cause = e.__cause__
        out["error"] = type(cause).__name__ if cause is not None else type(e).__name__
        return out
    out["description"] = str(getattr(cls, "description", "") or "")
    out["config_schema"] = _plain(getattr(cls, "config_schema", {}) or {})
    return out


def build() -> Dict[str, Any]:
    from .. import __version__
    from . import mapping, plugins
    from .migrate import schema as migrate_schema
    from .spec import CORE_SCHEMA
    return {
        "schema": SCHEMA_ID,
        "sdk_version": __version__,
        "plugins": {kind: [_plugin(kind, name, where) for name, where in sorted(table.items())]
                    for kind, table in sorted(plugins.BUILTINS.items())},
        "core_schema": _plain(CORE_SCHEMA),
        "migration": {"manifest_schema": _plain(migrate_schema.MANIFEST_SCHEMA), "kit_caps": _plain(migrate_schema.KIT_CAPS)},
        "value_nodes": {"keys": sorted(mapping.VALUE_KEYS), "as": list(mapping.AS_TYPES), "case": list(mapping.CASES),
                        "order": list(STEP_ORDER), "node_needs": "path or concat"},
    }


def dumps(doc: Dict[str, Any]) -> str:
    return json.dumps(doc, sort_keys=True, indent=1, ensure_ascii=False) + "\n"


def table(doc: Dict[str, Any]) -> str:
    """A short text for a person: each plugin on a line, its kind, name and what it does."""
    lines: List[str] = [f"TheProtocol SDK {doc['sdk_version']}: the proxy's built-in parts"]
    for kind, items in doc["plugins"].items():
        for p in items:
            if p.get("internal"):
                continue
            what = p.get("description") or f"(does not load: {p.get('error')})"
            lines.append(f"  {kind:<7} {p['name']:<18} {what}")
    lines.append("tp-proxy catalog --json prints everything: the schemas of every part, the spec and the migration kit.")
    return "\n".join(lines)
