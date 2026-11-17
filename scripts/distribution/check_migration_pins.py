#!/usr/bin/env python3
"""V0664 "Migrate a system" (session-lead, room seq 3873): the registry's copies of the SDK's migration constants,
pinned equal where both files are visible. M9 runs it at release; it needs nothing but the standard library.

  the SDK (theprotocol-sdk/src/theprotocol/proxy/)            the registry (AgentVault, agentvault_registry/src/
                                                              agentvault_registry/services/workflow_templates.py, M4)
  migrate/schema.py  MANIFEST_SCHEMA, KIT_CAPS, PATH_PATTERN  the same three names
                     canonical()  (the content hash's JSON)   canonical()
  spec.py            SECRET_KEY, REF  (the credential rule)   SECRET_KEY, REF

The files are READ, never imported (spec.py imports its own package at its top): each file's top-level assignments are
evaluated in order by a small literal evaluator (constants, dicts with ** unpacking, lists, tuples, names bound above,
a subscript of one, + - * // | on numbers, re.compile(pattern, flags)); canonical() is compared as its AST (its
arguments' names and defaults and its body; the docstring and the annotations left out).

  python3 scripts/distribution/check_migration_pins.py                 # this stack tree and its AgentVault checkout
  python3 scripts/distribution/check_migration_pins.py --agentvault-ref v0664/cut --sdk-ref origin/master
      a ref reads the file from git: the SDK's from the stack repository (--stack-dir), the registry's from the
      AgentVault repository (--agentvault-dir, default <stack>/AgentVault)
  --json   one JSON object instead of the lines

Exit 0: every pin equal. 1: a pin differs (each one named, with the first place the two differ). 2: a file or a name
is missing on a side (named): never a pass.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

HERE = pathlib.Path(__file__).resolve().parent
STACK = HERE.parents[1]

SDK_SCHEMA = "theprotocol-sdk/src/theprotocol/proxy/migrate/schema.py"
SDK_SPEC = "theprotocol-sdk/src/theprotocol/proxy/spec.py"
REGISTRY = "agentvault_registry/src/agentvault_registry/services/workflow_templates.py"

# (the name, what it is, the SDK file that holds the original)
PINS: Tuple[Tuple[str, str, str], ...] = (
    ("MANIFEST_SCHEMA", "value", SDK_SCHEMA),
    ("KIT_CAPS", "value", SDK_SCHEMA),
    ("PATH_PATTERN", "value", SDK_SCHEMA),
    ("canonical", "function", SDK_SCHEMA),
    ("SECRET_KEY", "regex", SDK_SPEC),
    ("REF", "regex", SDK_SPEC),
)


class Missing(Exception):
    """A file or a name a pin needs is not there."""


class _NotLiteral(Exception):
    pass


# --- reading ---------------------------------------------------------------------------------------------------------

class Source:
    """A tree on disk, or a git ref of a repository."""

    def __init__(self, root: pathlib.Path, ref: Optional[str] = None) -> None:
        self.root, self.ref = pathlib.Path(root), ref

    def label(self, rel: str) -> str:
        return f"{self.ref}:{rel}" if self.ref else str(self.root / rel)

    def read(self, rel: str) -> str:
        if self.ref is None:
            p = self.root / rel
            if not p.is_file():
                raise Missing(f"no file {p}")
            return p.read_text(encoding="utf-8")
        r = subprocess.run(["git", "-C", str(self.root), "show", f"{self.ref}:{rel}"], capture_output=True, text=True)
        if r.returncode != 0:
            raise Missing(f"no file {self.ref}:{rel} in {self.root} ({(r.stderr or '').strip()[:160]})")
        return r.stdout


# --- the literal evaluator -------------------------------------------------------------------------------------------

_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
           ast.FloorDiv: lambda a, b: a // b, ast.BitOr: lambda a, b: a | b}


def _eval(node: ast.AST, env: Dict[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in env or env[node.id] is _UNKNOWN:
            raise _NotLiteral(node.id)
        return env[node.id]
    if isinstance(node, ast.Dict):
        out: Dict[Any, Any] = {}
        for k, v in zip(node.keys, node.values):
            if k is None:                                   # {**other, ...}
                inner = _eval(v, env)
                if not isinstance(inner, dict):
                    raise _NotLiteral("** of a non-dict")
                out.update(inner)
            else:
                out[_eval(k, env)] = _eval(v, env)
        return out
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [_eval(e, env) for e in node.elts]
        return items if isinstance(node, ast.List) else tuple(items)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, env)
    if isinstance(node, ast.Subscript):
        return _eval(node.value, env)[_eval(node.slice, env)]
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "re":
        flag = getattr(re, node.attr, None)
        if isinstance(flag, re.RegexFlag):
            return int(flag)
        raise _NotLiteral(f"re.{node.attr}")
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "re" and node.func.attr == "compile" and not node.keywords):
        args = [_eval(a, env) for a in node.args]
        if not args or not isinstance(args[0], str):
            raise _NotLiteral("re.compile without a pattern")
        return {"re.compile": args[0], "flags": int(args[1]) if len(args) > 1 else 0}
    raise _NotLiteral(type(node).__name__)


_UNKNOWN = object()


def module_values(src: str) -> Tuple[Dict[str, Any], Dict[str, ast.FunctionDef]]:
    """The file's top-level names: what the evaluator could compute (others bound to _UNKNOWN), and its functions."""
    tree = ast.parse(src)
    env: Dict[str, Any] = {}
    funcs: Dict[str, ast.FunctionDef] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            funcs[node.name] = node
            continue
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for t in targets:
            if isinstance(t, ast.Name):
                try:
                    env[t.id] = _eval(value, env)
                except (_NotLiteral, KeyError, IndexError, TypeError):
                    env[t.id] = _UNKNOWN
            elif isinstance(t, ast.Tuple) and all(isinstance(e, ast.Name) for e in t.elts):
                try:
                    vals = _eval(value, env)
                    if not isinstance(vals, (list, tuple)) or len(vals) != len(t.elts):
                        raise _NotLiteral("unpack")
                except (_NotLiteral, KeyError, IndexError, TypeError):
                    vals = [_UNKNOWN] * len(t.elts)
                for e, v in zip(t.elts, vals):
                    env[e.id] = v
    return env, funcs


def _function_shape(fn: ast.FunctionDef) -> str:
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]                                      # the docstring is prose, not the rule
    a = fn.args
    names = [x.arg for x in a.posonlyargs + a.args + a.kwonlyargs] + [x.arg for x in (a.vararg, a.kwarg) if x]
    defaults = [ast.dump(d) for d in a.defaults + [d for d in a.kw_defaults if d is not None]]
    return repr((names, defaults)) + "|" + "|".join(ast.dump(s) for s in body)     # annotations are not the rule


# --- comparing -------------------------------------------------------------------------------------------------------

def first_difference(a: Any, b: Any, at: str = "") -> Optional[Tuple[str, Any, Any]]:
    """The first place two values differ (a dotted path, [i] for a list index), or None when they are equal."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = f"{at}.{k}" if at else str(k)
            if k not in a or k not in b:
                return p, a.get(k, "(absent)"), b.get(k, "(absent)")
            d = first_difference(a[k], b[k], p)
            if d:
                return d
        return None
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        for i, (x, y) in enumerate(zip(a, b)):
            d = first_difference(x, y, f"{at}[{i}]")
            if d:
                return d
        if len(a) != len(b):
            return f"{at}(length)", len(a), len(b)
        return None
    return None if (a == b and type(a) is type(b)) else ((at or "(the value)"), a, b)


def _short(v: Any) -> str:
    s = json.dumps(v, sort_keys=True, default=str) if not isinstance(v, str) else repr(v)
    return s if len(s) <= 120 else s[:117] + "..."


def check(sdk: Source, registry: Source) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    sdk_files: Dict[str, Tuple[Dict[str, Any], Dict[str, ast.FunctionDef]]] = {}
    try:
        reg_env, reg_funcs = module_values(registry.read(REGISTRY))
    except Missing as e:
        return {"verdict": "missing", "rows": [{"pin": "(the registry file)", "result": "missing", "why": str(e)}]}
    for name, kind, rel in PINS:
        row: Dict[str, Any] = {"pin": name, "sdk": sdk.label(rel), "registry": registry.label(REGISTRY)}
        try:
            if rel not in sdk_files:
                sdk_files[rel] = module_values(sdk.read(rel))
            env, funcs = sdk_files[rel]
            if kind == "function":
                if name not in funcs or name not in reg_funcs:
                    side = "the SDK" if name not in funcs else "the registry"
                    raise Missing(f"no function {name}() in {side}'s file")
                same = _function_shape(funcs[name]) == _function_shape(reg_funcs[name])
                row.update(result="equal" if same else "differs",
                           why=None if same else f"{name}() is written differently (its arguments or its body)")
            else:
                for side, e in (("the SDK", env), ("the registry", reg_env)):
                    if name not in e:
                        raise Missing(f"no {name} in {side}'s file")
                    if e[name] is _UNKNOWN:
                        raise Missing(f"{name} in {side}'s file is not a value this check can read (a literal, names "
                                      f"bound above it, re.compile)")
                d = first_difference(env[name], reg_env[name])
                row.update(result="equal" if d is None else "differs",
                           why=None if d is None else f"at {d[0]}: the SDK has {_short(d[1])}, the registry {_short(d[2])}")
        except Missing as e:
            row.update(result="missing", why=str(e))
        rows.append(row)
    results = {r["result"] for r in rows}
    verdict = "missing" if "missing" in results else ("differs" if "differs" in results else "equal")
    return {"verdict": verdict, "rows": rows}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stack-dir", default=str(STACK), help="the stack tree (its theprotocol-sdk/), default this one")
    ap.add_argument("--agentvault-dir", default=None, help="the AgentVault tree or repository, default <stack>/AgentVault")
    ap.add_argument("--sdk-ref", default=None, help="read the SDK files at this git ref of the stack repository")
    ap.add_argument("--agentvault-ref", default=None, help="read the registry file at this git ref of AgentVault")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    stack = pathlib.Path(a.stack_dir)
    av = pathlib.Path(a.agentvault_dir) if a.agentvault_dir else stack / "AgentVault"
    out = check(Source(stack, a.sdk_ref), Source(av, a.agentvault_ref))
    if a.json:
        print(json.dumps(out, indent=2))
    else:
        for r in out["rows"]:
            print(f"PIN {r['result'].upper():8} {r['pin']}" + (f": {r['why']}" if r.get("why") else ""))
        n = sum(1 for r in out["rows"] if r["result"] == "equal")
        print(f"MIGRATION PINS: {n} of {len(out['rows'])} equal, verdict {out['verdict']}")
    return {"equal": 0, "differs": 1}.get(out["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
