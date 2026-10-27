"""Read-only config slice reader for Command Center detail drawer.

Pulls config from running containers (env vars, labels, mounts) and from
the Docker network/registry side. All secrets are masked server-side
before transport.
"""

import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Patterns that mark a value as secret. Negative lookaheads allow common
# non-secret suffixes (TTL, AGE, EXPIRY, PATH, ISSUER, SERVICE, …) so
# config like `DOCKER_TOKEN_EXPIRY_SECONDS=3600` stays visible.
_TOKEN_NON_SECRET_SUFFIXES = r"_AGE|_TTL|_TYPE|_EXPIRY|_ISSUER|_SERVICE|_PATH|_SECONDS|_MINUTES|_HOURS|_ALGO"
_KEY_NON_SECRET_SUFFIXES = r"_PATH|_ALGO|_TYPE|_ID|_FINGERPRINT"

_SECRET_PATTERNS = (
    re.compile(r"SECRET(?!_PATH|_ALGO|_TYPE)", re.IGNORECASE),
    re.compile(r"PASSWORD", re.IGNORECASE),
    re.compile(r"PRIVATE_?KEY(?!_PATH)", re.IGNORECASE),
    re.compile(rf"_TOKEN(?!{_TOKEN_NON_SECRET_SUFFIXES})", re.IGNORECASE),
    re.compile(rf"API_?KEY(?!{_KEY_NON_SECRET_SUFFIXES})", re.IGNORECASE),
    re.compile(r"_JWT(?!_TYPE|_ALGO|_EXPIRY)", re.IGNORECASE),
    re.compile(r"AVREG_", re.IGNORECASE),
    re.compile(r"FEDERATION_LICENSE", re.IGNORECASE),
    re.compile(r"INTERNAL_KEY(?!_PATH)", re.IGNORECASE),
    re.compile(r"CRED(?:S|ENTIAL)", re.IGNORECASE),
    # §MCPSWEEP 2026-09-27, found by an entropy census of four registries' env (names only): PG_PASS_REGISTRY /
    # _TEG / _EVENT_STORE, TWO_FACTOR_ENCRYPTION_KEY and REGISTRY_SIGNING_KEY_PASSPHRASE matched no pattern above
    re.compile(r"(?:^|_)PASS(?:_|$)|PASSPHRASE|PASSWD", re.IGNORECASE),
    re.compile(r"(?:^|_)KEYS?$|(?:ENCRYPTION|SIGNING)_KEY(?!_PATH|_ID|_FINGERPRINT|_REQUIRE)", re.IGNORECASE),
)

# §MCPSWEEP 2026-09-27: a secret can sit inside a VALUE whose variable name says nothing. Measured on sbx-alpha's one
# target (op-sbxalphaop): a DSN password in DATABASE_URL_SYNC, an `api_key` inside the PARTNER_TEGS JSON (and the
# partner_tegs section returned PARTNER_TEGS unmasked), and the X-Registry-Proxy-Auth / X-TEG-Proxy-Auth markers in
# the nginx section all reached an admin in clear. Masking reads the value now, not only the name.
# the user part may be empty: a Redis URL is usually redis://:password@host
_URL_USERINFO = re.compile(r"(://[^:/@\s\"']*:)([^@/\s\"']+)(@)")
_SECRET_LEAF_KEYS = frozenset({
    "token", "secret", "password", "passwd", "pwd", "key", "api_key", "apikey", "private_key",
    "dsn", "creds", "credentials", "license", "licence",
})
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_NGINX_VALUE_LINE = re.compile(
    r"^(\s*(?:proxy_set_header|add_header|more_set_headers|set)\s+)(\S+)(\s+)(.+?)(\s*;.*)$")
_NGINX_SECRET_NAME = re.compile(r"auth|key|secret|token|licen[cs]e|password|cookie", re.IGNORECASE)


def _looks_unsensitive(value: str) -> bool:
    """Heuristic: short numeric/path/boolean values are never secrets."""
    if not value:
        return True
    if value.isdigit():
        return True
    if value in ("true", "false", "True", "False", "TRUE", "FALSE"):
        return True
    if value.startswith("/") and len(value) < 80:
        return True
    return False


def _mask(value: str) -> str:
    if not value:
        return value
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-2:]} (masked)"


def is_secret(key: str, value: str = "") -> bool:
    if value and _looks_unsensitive(value):
        return False
    return any(p.search(key) for p in _SECRET_PATTERNS)


def mask_url(url: str) -> str:
    """Mask the password of every `scheme://user:pass@` in the text (a DSN, or one inside a JSON value)."""
    return _URL_USERINFO.sub(lambda m: f"{m.group(1)}{_mask(m.group(2))}{m.group(3)}", url)


def _mask_json_leaves(obj: Any) -> Any:
    """A parsed JSON value with every secret-keyed string leaf masked and every URL password masked."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(v, str) and v and (str(k).lower() in _SECRET_LEAF_KEYS or is_secret(str(k), v)):
                out[k] = _mask(v)
            else:
                out[k] = _mask_json_leaves(v)
        return out
    if isinstance(obj, list):
        return [_mask_json_leaves(x) for x in obj]
    if isinstance(obj, str):
        return mask_url(obj)
    return obj


def _json_or_none(value: str) -> Any:
    s = value.strip()
    if s[:1] not in ("{", "["):
        return None
    try:
        parsed = json.loads(s)
    except ValueError:
        return None
    return parsed if isinstance(parsed, (dict, list)) else None


def mask_value(key: str, value: str) -> str:
    """One env value, masked by its NAME and by its CONTENT (a URL password, a secret-keyed JSON leaf)."""
    if not isinstance(value, str) or not value:
        return value
    if is_secret(key, value):
        return _mask(value)
    parsed = _json_or_none(value)
    if parsed is not None:
        masked = _mask_json_leaves(parsed)
        return value if masked == parsed else json.dumps(masked, ensure_ascii=False, separators=(",", ":"))
    return mask_url(value)


def mask_env(env: dict[str, str]) -> dict[str, str]:
    return {k: mask_value(k, v) for k, v in env.items()}


def mask_nginx(text: str) -> str:
    """nginx config with the value of every secret-named header or variable masked, and every 32+ hex literal."""
    lines = []
    for ln in text.splitlines():
        m = _NGINX_VALUE_LINE.match(ln)
        if m and _NGINX_SECRET_NAME.search(m.group(2)) and not m.group(4).lstrip("\"'").startswith("$"):
            ln = f"{m.group(1)}{m.group(2)}{m.group(3)}{_mask(m.group(4))}{m.group(5)}"
        lines.append(_LONG_HEX.sub(lambda h: _mask(h.group(0)), ln))
    return "\n".join(lines)


async def read_docker_section(target: dict, probe) -> dict[str, Any]:
    """Container-level metadata: image, status, ports, mounts, networks."""
    out: dict[str, Any] = {}
    for role, name in target.get("containers", {}).items():
        attrs = await probe.container_inspect(name)
        if "error" in attrs:
            out[role] = {"container": name, "error": attrs["error"]}
            continue
        config = attrs.get("Config", {}) or {}
        state = attrs.get("State", {}) or {}
        net = attrs.get("NetworkSettings", {}) or {}
        out[role] = {
            "container": name,
            "image": config.get("Image"),
            "status": state.get("Status"),
            "started_at": state.get("StartedAt"),
            "restart_count": attrs.get("RestartCount"),
            "networks": list((net.get("Networks") or {}).keys()),
            "ports": list((net.get("Ports") or {}).keys()),
        }
    return out


async def read_env_section(target: dict, probe, role: str = "registry") -> dict[str, str]:
    """Env vars from the named container, with secrets masked."""
    container = target.get("containers", {}).get(role)
    if not container:
        return {}
    attrs = await probe.container_inspect(container)
    if "error" in attrs:
        return {"_error": attrs["error"]}
    env_list = (attrs.get("Config") or {}).get("Env") or []
    env: dict[str, str] = {}
    for entry in env_list:
        if "=" in entry:
            k, _, v = entry.partition("=")
            env[k] = v
    # mask_value masks a URL password in EVERY value (it used to be four named DSN keys only)
    return mask_env(env)


async def read_nginx_section(target: dict, probe) -> Optional[str]:
    """Operator nginx-federation config (read-only)."""
    container = target.get("containers", {}).get("nginx_federation")
    if not container:
        return None
    rc, out = await probe.exec_in(
        container,
        ["sh", "-c", "cat /etc/nginx/conf.d/*.conf 2>/dev/null | head -200"],
        timeout=4,
    )
    if rc != 0:
        return mask_nginx(f"(read failed rc={rc}): {out[:512]}")
    return mask_nginx(out)


async def read_spire_section(target: dict, probe) -> dict[str, Any]:
    """SPIRE federation list + bundle fingerprint for mainframes."""
    container = target.get("containers", {}).get("spire_server")
    if not container:
        return {}
    out: dict[str, Any] = {}
    rc, fed = await probe.exec_in(
        container, ["/opt/spire/bin/spire-server", "federation", "list"], timeout=5
    )
    out["federation_list"] = fed[:1024] if rc == 0 else f"(rc={rc}) {fed[:512]}"
    rc, bundle = await probe.exec_in(
        container, ["/opt/spire/bin/spire-server", "bundle", "show"], timeout=4
    )
    if rc == 0:
        # Just expose first 4 lines + length so we can spot bundle changes
        head = "\n".join(bundle.splitlines()[:4])
        out["bundle_head"] = head
        out["bundle_bytes"] = len(bundle)
    else:
        out["bundle_error"] = f"(rc={rc}) {bundle[:200]}"
    return out


async def read_partner_tegs(target: dict, probe) -> Optional[list[str]]:
    """Parse PARTNER_TEGS from registry env (helps diagnose cross-TEG topology)."""
    container = target.get("containers", {}).get("registry")
    if not container:
        return None
    attrs = await probe.container_inspect(container)
    env_list = (attrs.get("Config") or {}).get("Env") or []
    for entry in env_list:
        if entry.startswith("PARTNER_TEGS="):
            value = entry.split("=", 1)[1]
            parsed = _json_or_none(value)
            if parsed is not None:
                items = parsed if isinstance(parsed, list) else [parsed]
                return [mask_url(x) if isinstance(x, str)
                        else json.dumps(_mask_json_leaves(x), ensure_ascii=False, separators=(",", ":"))
                        for x in items]
            return [_LONG_HEX.sub(lambda h: _mask(h.group(0)), mask_value("PARTNER_TEGS", v.strip()))
                    for v in value.split(",") if v.strip()]
    return None
