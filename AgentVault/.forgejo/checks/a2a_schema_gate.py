#!/usr/bin/env python3
"""§AGENTDISC #189 — A2A v1.0 AgentCard schema gate (2026-08-16).

Validates the OUTPUT of `canonicalize_card_data()` over a fixture corpus against the
vendored schema (encoded field-for-field from a2aproject/A2A v1.0.1 a2a.proto — see
services/a2a_v1/schema/PROVENANCE.md). Dependency-free: `compat.py` is stdlib-only and
loaded by file path (never through the package __init__ chain, which drags settings),
and the validator below implements exactly the JSON-Schema subset the vendored schema
uses (type / required / properties / items / $ref into $defs / minItems).

Gates on: missing REQUIRED fields, wrong types, and a NEGATIVE control that must FAIL
(a gate that cannot fail measures nothing). Strict extras (v0.3 transition siblings)
are REPORTED, never gated — additionalProperties:true is deliberate (see PROVENANCE).

Modes:
  no args        → fixture corpus under .forgejo/checks/fixtures/a2a/ (CI)
  --card FILE    → validate ONE card JSON (the live battery leg feeds a card-export)
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SRC_PKG = os.path.join(REPO, "agentvault_registry", "src", "agentvault_registry")
SCHEMA_PATH = os.path.join(SRC_PKG, "services", "a2a_v1", "schema", "agent_card_v1.schema.json")
COMPAT_PATH = os.path.join(SRC_PKG, "services", "a2a_v1", "compat.py")
FIXTURES = os.path.join(HERE, "fixtures", "a2a")

KNOWN_V1_TOP = None  # filled from schema properties


def load_compat():
    spec = importlib.util.spec_from_file_location("a2a_compat_standalone", COMPAT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _resolve(schema_root, node):
    ref = node.get("$ref")
    if not ref:
        return node
    assert ref.startswith("#/$defs/"), f"unsupported $ref {ref}"
    return schema_root["$defs"][ref.split("/")[-1]]


def validate(obj, node, schema_root, path="$", errors=None, skip_required=()):
    """Minimal validator for the subset the vendored schema uses."""
    if errors is None:
        errors = []
    node = _resolve(schema_root, node)
    t = node.get("type")
    if t == "object":
        if not isinstance(obj, dict):
            errors.append(f"{path}: expected object, got {type(obj).__name__}")
            return errors
        # JSON-null idiom: our stored cards serialize absent optionals as null
        # (pydantic), so null == absent for optionals and null == missing for
        # REQUIRED fields. Present non-null values are validated strictly.
        for req in node.get("required", []):
            if req in skip_required and path == "$":
                continue
            if req not in obj or obj[req] is None:
                errors.append(f"{path}.{req}: REQUIRED field missing")
        for key, sub in (node.get("properties") or {}).items():
            if key in obj and obj[key] is not None:
                validate(obj[key], sub, schema_root, f"{path}.{key}", errors)
    elif t == "array":
        if not isinstance(obj, list):
            errors.append(f"{path}: expected array, got {type(obj).__name__}")
            return errors
        if len(obj) < node.get("minItems", 0):
            errors.append(f"{path}: minItems {node.get('minItems')} violated (len {len(obj)})")
        items = node.get("items")
        if items:
            for i, el in enumerate(obj):
                validate(el, items, schema_root, f"{path}[{i}]", errors)
    elif t == "string":
        if not isinstance(obj, str):
            errors.append(f"{path}: expected string, got {type(obj).__name__}")
    elif t == "boolean":
        if not isinstance(obj, bool):
            errors.append(f"{path}: expected boolean, got {type(obj).__name__}")
    elif t == "number":
        if not isinstance(obj, (int, float)) or isinstance(obj, bool):
            errors.append(f"{path}: expected number, got {type(obj).__name__}")
    return errors


def strict_extras(card, schema_root):
    known = set((schema_root.get("properties") or {}).keys())
    return sorted(k for k in card.keys() if k not in known)


def run_one(card, schema, compat, label, skip_required=()):
    canonical = compat.canonicalize_card_data(card)
    errs = validate(canonical, schema, schema, skip_required=skip_required)
    extras = strict_extras(canonical, schema)
    return canonical, errs, extras


def main() -> int:
    schema = json.load(open(SCHEMA_PATH))
    compat = load_compat()

    if len(sys.argv) == 3 and sys.argv[1] == "--card":
        card = json.load(open(sys.argv[2]))
        skip = () if (card.get("url") or card.get("supportedInterfaces")) else ("supportedInterfaces",)
        _, errs, extras = run_one(card, schema, compat, "live-card", skip_required=skip)
        print(f"live card: {'VALID' if not errs else 'INVALID'}"
              f"{' (no-endpoint: supportedInterfaces waived)' if skip else ''}")
        for e in errs:
            print("  " + e)
        if extras:
            print(f"  strict-extras (reported, non-gating): {', '.join(extras)}")
        return 1 if errs else 0

    manifest = json.load(open(os.path.join(FIXTURES, "manifest.json")))
    failures = 0
    for entry in manifest:
        card = json.load(open(os.path.join(FIXTURES, entry["file"])))
        skip = ("supportedInterfaces",) if entry["expect"] == "no_endpoint" else ()
        _, errs, extras = run_one(card, schema, compat, entry["file"], skip_required=skip)
        if entry["expect"] == "invalid":
            # NEGATIVE CONTROL — the validator must catch this or the gate is blind
            if errs:
                print(f"ok  {entry['file']}: correctly INVALID ({errs[0]})")
            else:
                print(f"FAIL {entry['file']}: negative control VALIDATED — gate is blind")
                failures += 1
        else:
            if errs:
                print(f"FAIL {entry['file']}: {len(errs)} error(s)")
                for e in errs[:6]:
                    print("   " + e)
                failures += 1
            else:
                note = f" extras: {', '.join(extras[:8])}" if extras else ""
                print(f"ok  {entry['file']}: VALID{note}")

    # idempotence: canonicalize twice must be a fixed point (derived fields stable)
    sample = json.load(open(os.path.join(FIXTURES, manifest[0]["file"])))
    once = compat.canonicalize_card_data(sample)
    twice = compat.canonicalize_card_data(once)
    if once != twice:
        print("FAIL idempotence: canonicalize(canonicalize(x)) != canonicalize(x)")
        failures += 1
    else:
        print("ok  idempotence: canonicalization is a fixed point")

    print(f"\nA2A SCHEMA GATE: {'PASS' if failures == 0 else f'{failures} FAILURE(S)'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
