"""Response snapshot diff (AAA+ Phase VI, 2026-05-21).

For ~50 critical endpoints, commit a "baseline" response signature to disk.
On each run, the actual response is diffed against the baseline. Drift = PR
review required. Catches subtle response-shape regressions that 200-status
checks miss (e.g., RFC 7807 dual-emit adding new error fields).

Signature = deterministic hash of (status, header subset, json schema shape).
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Where snapshots live (committed alongside code)
SNAPSHOT_ROOT = Path(__file__).resolve().parent.parent / "snapshots"


def _shape(obj: Any, depth: int = 0, max_depth: int = 4) -> Any:
    """Recursively reduce a JSON object to its SHAPE: types + sorted keys.

    Replaces values with type names; preserves keys; truncates lists/dicts at depth.
    """
    if depth > max_depth:
        return "...truncated"
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "bool"
    if isinstance(obj, int):
        return "int"
    if isinstance(obj, float):
        return "float"
    if isinstance(obj, str):
        return "string"
    if isinstance(obj, list):
        if not obj:
            return []
        return [_shape(obj[0], depth + 1, max_depth)]  # representative element only
    if isinstance(obj, dict):
        return {k: _shape(v, depth + 1, max_depth) for k, v in sorted(obj.items())}
    return type(obj).__name__


def signature(status: int, body: Any, headers_subset: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Build a deterministic signature for a response."""
    shape = _shape(body)
    body_hash = hashlib.sha256(
        json.dumps(shape, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return {
        "status": status,
        "body_shape_hash": body_hash,
        "body_shape": shape,
        "headers": dict(sorted((headers_subset or {}).items())),
    }


def _key_to_path(method: str, path: str) -> Path:
    """Map (METHOD, /path) to a filesystem path for the snapshot file."""
    safe = path.replace("/", "_").replace("{", "(").replace("}", ")").strip("_")
    return SNAPSHOT_ROOT / f"{method.upper()}_{safe}.json"


def save(method: str, path: str, signature_data: Dict[str, Any]) -> Path:
    SNAPSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    out = _key_to_path(method, path)
    with open(out, "w") as f:
        json.dump(signature_data, f, indent=2, default=str, sort_keys=True)
    return out


def load(method: str, path: str) -> Optional[Dict[str, Any]]:
    f = _key_to_path(method, path)
    if not f.exists():
        return None
    try:
        with open(f) as fp:
            return json.load(fp)
    except Exception as e:
        logger.warning(f"snapshot load {f} failed: {e!r}")
        return None


def diff(method: str, path: str, current: Dict[str, Any]) -> Dict[str, Any]:
    """Compare current signature against committed baseline.

    Returns dict with:
        baseline_exists: bool
        status_match: bool
        shape_match: bool
        added_keys: list
        removed_keys: list
        type_changes: list
        verdict: "match" | "drift" | "missing_baseline"
    """
    baseline = load(method, path)
    if baseline is None:
        return {"baseline_exists": False, "verdict": "missing_baseline"}

    status_match = baseline["status"] == current["status"]
    shape_match = baseline["body_shape_hash"] == current["body_shape_hash"]

    # Diff at key level
    added, removed, type_changed = _shape_diff(
        baseline.get("body_shape"),
        current.get("body_shape"),
    )

    verdict = "match" if (status_match and shape_match) else "drift"
    return {
        "baseline_exists": True,
        "status_match": status_match,
        "shape_match": shape_match,
        "added_keys": added,
        "removed_keys": removed,
        "type_changes": type_changed,
        "verdict": verdict,
    }


def _shape_diff(a: Any, b: Any, path: str = "$") -> tuple[List[str], List[str], List[str]]:
    """Recursive shape diff. Returns (added, removed, type_changed)."""
    added, removed, type_changed = [], [], []
    if isinstance(a, dict) and isinstance(b, dict):
        a_keys = set(a.keys())
        b_keys = set(b.keys())
        for k in b_keys - a_keys:
            added.append(f"{path}.{k}")
        for k in a_keys - b_keys:
            removed.append(f"{path}.{k}")
        for k in a_keys & b_keys:
            sub_a, sub_r, sub_t = _shape_diff(a[k], b[k], f"{path}.{k}")
            added += sub_a
            removed += sub_r
            type_changed += sub_t
    elif isinstance(a, list) and isinstance(b, list) and a and b:
        sub_a, sub_r, sub_t = _shape_diff(a[0], b[0], f"{path}[0]")
        added += sub_a
        removed += sub_r
        type_changed += sub_t
    elif a != b:
        type_changed.append(f"{path}: {a} → {b}")
    return added, removed, type_changed
