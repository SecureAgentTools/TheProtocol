"""OpenAPI-driven catalog sync (AAA+ refactor 2026-05-21).

Replaces the hand-maintained `endpoints_registry.py` with a live introspection
of sandbox-A's `/openapi.json`, merged with per-endpoint manual overrides from
`overrides.yaml`. Result: catalog drift is structurally impossible.

Precedence (highest wins):
    1. Contract class registered via @Endpoint (Phase II — not yet)
    2. overrides.yaml per-endpoint entry
    3. OpenAPI introspection (tag → category, security → auth, summary → description)
    4. Heuristic fallback (path prefix → auth, first segment → category)

Globs in `paths_to_exclude` are applied before any of the above — those paths
never enter the catalog.

The output shape mirrors `EndpointsRegistry.get_all_endpoints()` so the existing
`GET /admin/api-test/endpoints` handler can drop this in without frontend changes.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import yaml

logger = logging.getLogger(__name__)

# Where to fetch OpenAPI from. Defaults to the BFF's test target (sandbox-A).
DEFAULT_OPENAPI_URL = (
    os.getenv("API_TEST_TARGET_URL", "http://registry-test:8000").rstrip("/")
    + "/openapi.json"
)

# Cache TTL — OpenAPI fetched at most once per 60s. /endpoints is fast; OpenAPI is heavy.
_CACHE_TTL_SEC = 60.0
_CACHE: Dict[str, Any] = {"built_at": 0.0, "catalog": None, "openapi_url": None}

# Heuristic auth tier (in absence of OpenAPI security and overrides)
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# Where overrides.yaml lives
_OVERRIDES_PATH = Path(__file__).resolve().parent.parent / "overrides.yaml"


def _strip_api_prefix(path: str) -> str:
    """Drop /api/v1 prefix; OpenAPI paths include it, catalog convention strips."""
    if path.startswith("/api/v1/"):
        return path[len("/api/v1"):]
    if path == "/api/v1":
        return "/"
    return path


# §MCPTEST30 (V0545): the shape each section must have; a section that is null (a YAML key whose entries are all
# commented out) is the empty section, never a reason to drop the others
_OVERRIDE_SECTIONS = {"paths_to_exclude": list, "endpoints": dict, "auth_prefix_defaults": dict, "tag_remap": dict}


def _load_overrides() -> Dict[str, Any]:
    """Read overrides.yaml; cached after first call. Returns empty dict if missing.

    §MCPTEST30 (V0545): `endpoints:` holds only commented examples, which YAML reads as null; the log line's
    `len(data.get('endpoints', {}))` then raised (a key that is present returns its null, not the default), and the
    except below returned {} for the WHOLE file: the 15 excludes (the cloud-operator provision and teardown routes,
    the recursive run-all, the MCP and OAuth surfaces), 15 auth prefix defaults and 62 tag remaps all stopped applying,
    with an ERROR line per load. Each section is now read on its own and a null section is an empty one."""
    try:
        if not _OVERRIDES_PATH.exists():
            logger.warning(f"overrides.yaml not found at {_OVERRIDES_PATH}; running with defaults")
            return {}
        with open(_OVERRIDES_PATH) as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            logger.error(f"overrides.yaml is a {type(data).__name__}, not a mapping; running with defaults")
            return {}
        for key, kind in _OVERRIDE_SECTIONS.items():
            if data.get(key) is None:
                data[key] = kind()
            elif not isinstance(data[key], kind):
                logger.error(f"overrides.yaml: `{key}` is a {type(data[key]).__name__}, not a {kind.__name__}; "
                             f"that section is ignored, the others apply")
                data[key] = kind()
        logger.info(
            f"overrides.yaml loaded: {len(data['paths_to_exclude'])} excludes, "
            f"{len(data['endpoints'])} per-endpoint, "
            f"{len(data['auth_prefix_defaults'])} prefix defaults"
        )
        return data
    except Exception as e:
        logger.error(f"overrides.yaml load failed: {e!r}")
        return {}


def _is_excluded(path: str, exclude_globs: List[str]) -> bool:
    """fnmatch any of the globs against the path."""
    for glob in exclude_globs:
        if fnmatch.fnmatchcase(path, glob):
            return True
    return False


def _infer_category(
    method: str,
    path: str,
    op_spec: Dict[str, Any],
    overrides: Dict[str, Any],
) -> str:
    """Per-endpoint override > tag remap > tag literal > path segment heuristic."""
    key = f"{method.upper()} {path}"
    ep_override = overrides.get("endpoints", {}).get(key, {})
    if "category" in ep_override:
        return str(ep_override["category"])

    tag_remap = overrides.get("tag_remap", {})
    tags = op_spec.get("tags") or []
    if tags:
        primary_tag = tags[0]
        if primary_tag in tag_remap:
            return str(tag_remap[primary_tag])
        # Normalize: lowercase, replace em/en-dash/space/slash/parens with underscore, collapse runs
        import re as _re
        normalized = primary_tag.lower()
        normalized = _re.sub(r"[—–\s\-/()+]+", "_", normalized)  # em-dash, en-dash, space, hyphen, slash, parens
        normalized = _re.sub(r"_+", "_", normalized).strip("_")
        return normalized or "other"

    # Heuristic: first non-trivial path segment
    segments = [s for s in path.strip("/").split("/") if s and not s.startswith("{")]
    return segments[0] if segments else "other"


def _infer_auth(
    method: str,
    path: str,
    op_spec: Dict[str, Any],
    overrides: Dict[str, Any],
) -> str:
    """Per-endpoint override > OpenAPI security > path-prefix default > fallback."""
    key = f"{method.upper()} {path}"
    ep_override = overrides.get("endpoints", {}).get(key, {})
    if "auth" in ep_override:
        return str(ep_override["auth"])

    # OpenAPI security: list of dicts. Empty/None = no auth needed.
    security = op_spec.get("security")
    if security == [] or security == [{}]:
        return "none"
    if security:
        # Look at first scheme name. Common ones: HTTPBearer, OAuth2PasswordBearer, APIKeyHeader, mTLSPeer
        try:
            scheme_name = next(iter(security[0].keys()))
            sn = scheme_name.lower()
            if "mtls" in sn:
                return "mtls"
            if "oauth" in sn:
                # Could be developer or agent — fall through to prefix heuristic
                pass
        except (IndexError, KeyError, AttributeError, TypeError, StopIteration):
            pass

    # Path-prefix heuristic
    prefix_defaults = overrides.get("auth_prefix_defaults", {})
    # Sort by length DESC so longest prefix wins (/admin/api-test before /admin/)
    for prefix in sorted(prefix_defaults.keys(), key=len, reverse=True):
        if path.startswith(prefix):
            return str(prefix_defaults[prefix])

    # Final fallback: paths starting with /admin → developer, else developer (safest default)
    if path.startswith("/admin/") or path == "/admin":
        return "developer"
    return "developer"


def _infer_description(op_spec: Dict[str, Any]) -> str:
    """OpenAPI summary > operationId > empty."""
    return str(op_spec.get("summary") or op_spec.get("operationId") or "").strip()


async def _fetch_openapi(url: str, timeout_sec: float = 15.0) -> Optional[Dict[str, Any]]:
    """Fetch OpenAPI JSON from the test target. Returns None on failure (logged)."""
    try:
        async with httpx.AsyncClient(timeout=timeout_sec, follow_redirects=True) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.error(f"OpenAPI fetch from {url} failed: {e!r}")
        return None


async def build_catalog(
    openapi_url: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, List[Dict[str, Any]]]:
    """Build the test catalog from OpenAPI + overrides.

    Returns a dict matching `EndpointsRegistry.get_all_endpoints()` shape:
        {category: [{"method", "path", "auth", "description"}, ...], ...}

    Cached for `_CACHE_TTL_SEC`. Pass `force_refresh=True` to bypass cache.
    """
    target_url = openapi_url or DEFAULT_OPENAPI_URL
    now = time.time()
    if (
        not force_refresh
        and _CACHE["catalog"] is not None
        and _CACHE["openapi_url"] == target_url
        and (now - _CACHE["built_at"]) < _CACHE_TTL_SEC
    ):
        return _CACHE["catalog"]

    overrides = _load_overrides()
    exclude_globs = overrides.get("paths_to_exclude", []) or []

    spec = await _fetch_openapi(target_url)
    if spec is None:
        # Fall back to legacy registry if OpenAPI is unreachable
        logger.warning("OpenAPI unreachable — falling back to legacy endpoints_registry")
        try:
            from agentvault_registry.api_tests.endpoints_registry import endpoints_registry
            legacy = endpoints_registry.get_all_endpoints()
            _CACHE.update(catalog=legacy, built_at=now, openapi_url=target_url)
            return legacy
        except Exception as e:
            logger.error(f"Legacy fallback also failed: {e!r}")
            return {}

    catalog: Dict[str, List[Dict[str, Any]]] = {}
    excluded_count = 0
    total_paths = 0

    for raw_path, ops in (spec.get("paths") or {}).items():
        path = _strip_api_prefix(raw_path)
        for method, op_spec in (ops or {}).items():
            if not isinstance(op_spec, dict):
                continue
            method_upper = method.upper()
            if method_upper not in _HTTP_METHODS:
                continue
            total_paths += 1

            if _is_excluded(path, exclude_globs):
                excluded_count += 1
                continue

            key = f"{method_upper} {path}"
            ep_override = overrides.get("endpoints", {}).get(key, {})
            if ep_override.get("hidden"):
                excluded_count += 1
                continue

            category = _infer_category(method_upper, path, op_spec, overrides)
            auth = _infer_auth(method_upper, path, op_spec, overrides)
            description = ep_override.get("description") or _infer_description(op_spec)

            catalog.setdefault(category, []).append({
                "method": method_upper,
                "path": path,
                "auth": auth,
                "description": description,
            })

    # Stable sort within each category for deterministic ordering
    for cat in catalog:
        catalog[cat].sort(key=lambda e: (e["path"], e["method"]))

    total_kept = sum(len(v) for v in catalog.values())
    logger.info(
        f"Catalog built: {total_kept} endpoints across {len(catalog)} categories "
        f"(from {total_paths} OpenAPI paths, {excluded_count} excluded)"
    )

    _CACHE.update(catalog=catalog, built_at=now, openapi_url=target_url)
    return catalog


def get_total_endpoint_count(catalog: Dict[str, List[Dict[str, Any]]]) -> int:
    return sum(len(v) for v in catalog.values())


def invalidate_cache() -> None:
    """Drop the cache (forces next call to re-fetch OpenAPI)."""
    _CACHE.update(catalog=None, built_at=0.0)
