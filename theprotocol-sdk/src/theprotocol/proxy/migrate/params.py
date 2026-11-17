"""Parameters: the `${NAME}` placeholders in a kit's proxy.yaml, filled from --set NAME=VALUE, --params FILE (KEY=VALUE
lines) and the manifest's defaults, in that order of precedence.

The placeholders are filled in the PARSED document (each string value), never in the YAML text, so a value cannot
change the document's structure. A string that is exactly `${NAME}` becomes the value itself (a default of 30 stays a
number); a placeholder inside a longer string is replaced by the value's text.

Refusals (ParamError, exit 2), each naming the parameter: a placeholder the manifest does not declare; a declared
parameter with no value and no default; a --set or --params name the manifest does not declare; a value outside the
parameter's enum; a `secret: true` parameter given as anything but a reference (env:NAME or file:/path).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from ..spec import is_ref

PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
UNSET_PREFIX = "env:TP_MIGRATE_UNSET_"


class ParamError(ValueError):
    def __init__(self, problems: List[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def read_params_file(path: str) -> Dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments skipped; a value may be quoted."""
    out: Dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ParamError([f"--params {path}: {e.strerror or e}"])
    for n, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("export "):
            s = s[7:].lstrip()
        k, sep, v = s.partition("=")
        if not sep or not k.strip():
            raise ParamError([f"--params {path} line {n}: not KEY=VALUE"])
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k.strip()] = v
    return out


def parse_sets(sets: Iterable[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for s in sets or ():
        k, sep, v = str(s).partition("=")
        if not sep or not k.strip():
            raise ParamError([f"--set {s!r}: give NAME=VALUE"])
        out[k.strip()] = v
    return out


def placeholders(doc: Any) -> List[str]:
    """Every placeholder name in the document, in the order first met."""
    seen: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            for m in PLACEHOLDER.finditer(node):
                if m.group(1) not in seen:
                    seen.append(m.group(1))
    walk(doc)
    return seen


def resolve_values(manifest: Mapping[str, Any], *, sets: Optional[Mapping[str, str]] = None,
                   file_values: Optional[Mapping[str, str]] = None, needed: Iterable[str] = (),
                   allow_unset_secrets: bool = False) -> Dict[str, Any]:
    """name -> value for every declared parameter that has one. `needed` (the placeholders the spec uses) must all be
    declared and have a value. With allow_unset_secrets (a --sample run, which reads no system), a secret with no value
    becomes a reference nothing resolves (env:TP_MIGRATE_UNSET_<NAME>), so trying a kit needs no password."""
    declared: Mapping[str, Mapping[str, Any]] = manifest.get("parameters") or {}
    problems: List[str] = []
    given: Dict[str, Any] = {}
    for origin, values in (("--params", file_values or {}), ("--set", sets or {})):
        for k, v in values.items():
            if k not in declared:
                problems.append(f"{origin} {k}: the manifest declares no parameter {k} "
                                f"(it declares {', '.join(sorted(declared)) or 'none'})")
            else:
                given[k] = v
    out: Dict[str, Any] = {}
    for name, p in declared.items():
        if name in given:
            typed, why = typed_value(given[name], p.get("default"))
            if why:
                problems.append(f"parameter {name}: {why}")
                continue
            out[name] = typed
        elif "default" in p:
            out[name] = p["default"]
        elif p.get("secret") and allow_unset_secrets:
            out[name] = UNSET_PREFIX + name
            continue
        else:
            continue
        v = out[name]
        if p.get("secret") and not (isinstance(v, str) and is_ref(v)):
            problems.append(f"parameter {name}: a secret is given as a reference (env:NAME or file:/path), never as "
                            f"its value")
            out.pop(name, None)
            continue
        if "enum" in p and v not in p["enum"] and str(v) not in [str(e) for e in p["enum"]]:
            problems.append(f"parameter {name}: not one of {', '.join(str(e) for e in p['enum'])}")
    for name in needed:
        if name not in declared:
            problems.append(f"proxy.yaml uses ${{{name}}}: the manifest declares no parameter {name}")
        elif name not in out and not any(name in pr for pr in problems):
            problems.append(f"parameter {name}: no value (give --set {name}=... or --params FILE"
                            f"{'' if declared[name].get('secret') else ', or a default in the manifest'})")
    if problems:
        raise ParamError(problems)
    return out


def typed_value(v: Any, default: Any) -> Tuple[Any, Optional[str]]:
    """A value given on the command line or in a file is text; a parameter whose default is an integer or a boolean
    takes that type (so `port: ${SOURCE_PORT}` passes an integer schema), and text that does not parse is refused."""
    if not isinstance(v, str):
        return v, None
    if isinstance(default, bool):
        t = v.strip().lower()
        if t in ("true", "yes", "on", "1"):
            return True, None
        if t in ("false", "no", "off", "0"):
            return False, None
        return None, "its default is a boolean: give true or false"
    if isinstance(default, int):
        t = v.strip()
        if re.fullmatch(r"[+-]?\d{1,18}", t):
            return int(t), None
        return None, "its default is an integer: give digits"
    return v, None


def fill(doc: Any, values: Mapping[str, Any]) -> Any:
    """The document with every placeholder replaced (a copy)."""
    if isinstance(doc, Mapping):
        return {k: fill(v, values) for k, v in doc.items()}
    if isinstance(doc, list):
        return [fill(v, values) for v in doc]
    if isinstance(doc, str):
        whole = PLACEHOLDER.fullmatch(doc)
        if whole:
            return values[whole.group(1)]
        return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), doc)
    return doc


def secret_names(manifest: Mapping[str, Any]) -> Tuple[str, ...]:
    return tuple(n for n, p in (manifest.get("parameters") or {}).items() if p.get("secret"))


def fill_known(doc: Any, values: Mapping[str, Any]) -> Any:
    """Like fill, but a placeholder with no value stays as written (for reading what a template names on its own)."""
    if isinstance(doc, Mapping):
        return {k: fill_known(v, values) for k, v in doc.items()}
    if isinstance(doc, list):
        return [fill_known(v, values) for v in doc]
    if isinstance(doc, str):
        whole = PLACEHOLDER.fullmatch(doc)
        if whole and whole.group(1) in values:
            return values[whole.group(1)]
        return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), doc)
    return doc
