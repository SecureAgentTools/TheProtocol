"""§MCPSWEEP 2026-09-27: the diagnostics config route masks a secret by its VALUE, not only by its variable name.

Measured on sbx-alpha's one diagnostics target (op-sbxalphaop), key names and lengths only: GET
/admin/diagnostics/config/{target} (the Command Center drawer, MCP getDiagnosticConfig) handed an admin_platform caller
a DSN password in DATABASE_URL_SYNC (only four named DSN keys were URL-masked), an `api_key` inside the PARTNER_TEGS JSON
(and the partner_tegs section returned PARTNER_TEGS with no masking at all), and two 64-hex proxy markers
(X-Registry-Proxy-Auth, X-TEG-Proxy-Auth) in the nginx section. Every planted secret below must be absent from the
output, and every non-secret beside it must survive.
"""
from __future__ import annotations

import asyncio
import json

from agentvault_registry.services.diagnostics import config_reader as cr

DB_PW = "Zq9vB2tLw8xRkP4m"
REDIS_PW = "Hn3cV7yQe1sDfG6j"
API_KEY = "b" * 12 + "7f3e9a1c4d2b8e6f0a5c3d9e1f7b2a4c"
MARKER_A = "3c" * 32
MARKER_B = "9f" * 32
TOTP_KEY = "kQ3vN8wZ1xC5bM7nL2pR9tY4uE6iO0aS"
PASSPHRASE = "orchard-lantern-quiet-harbour-17"
SECRETS = (DB_PW, REDIS_PW, API_KEY, MARKER_A, MARKER_B, TOTP_KEY, PASSPHRASE)

ENV = {
    "DATABASE_URL_SYNC": f"postgresql://registry:{DB_PW}@op-db:5432/registry",
    "RATE_LIMIT_REDIS_URL": f"redis://:{REDIS_PW}@op-redis:6379/1",
    "PARTNER_TEGS": json.dumps([{"teg_id": "teg-layer-test", "url": "", "api_key": API_KEY}]),
    "CANARY_REBALANCER_OP_CREDS": "ops-admin:" + DB_PW,
    "PG_PASS_REGISTRY": DB_PW,
    "TWO_FACTOR_ENCRYPTION_KEY": TOTP_KEY,
    "REGISTRY_SIGNING_KEY_PASSPHRASE": PASSPHRASE,
    "PUBLIC_URL": "https://op.example.test:27543",
    "EVENT_STORE_URL": "http://event-store:8200",
    "UVICORN_WORKERS": "4",
    "FEATURE_FLAG": "true",
    "CERT_DIR": "/certs",
    # near misses of the name patterns that must stay visible
    "EXCHANGE_PASSPORT_ENABLED": "true",
    "SANDBOX_BYPASS_RATE_LIMIT": "false",
    "REGISTRY_SIGNING_KEY_REQUIRE_ENCRYPTION": "true",
    "MAIL_FROM": "noreply@example.test",
}

NGINX = "\n".join([
    "server {",
    "    listen 8443 ssl;",
    "    ssl_certificate_key /etc/nginx/certs/svid.key;",
    f"    proxy_set_header X-Registry-Proxy-Auth {MARKER_A};",
    f'    proxy_set_header X-TEG-Proxy-Auth "{MARKER_B}";',
    "    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
    "    proxy_set_header Authorization $http_authorization;",
    "    proxy_pass http://registry:8000;",
    "}",
])


class _Probe:
    async def container_inspect(self, name):
        return {"Config": {"Env": [f"{k}={v}" for k, v in ENV.items()]}}

    async def exec_in(self, container, argv, timeout=4):
        return 0, NGINX


TARGET = {"containers": {"registry": "op-registry", "nginx_federation": "op-nginx-federation"}}


def _leaks(text: str) -> list:
    return [s for s in SECRETS if s in text]


def test_env_section_masks_secrets_inside_values():
    out = asyncio.run(cr.read_env_section(TARGET, _Probe(), role="registry"))
    assert set(out) == set(ENV)
    assert not _leaks(json.dumps(out)), _leaks(json.dumps(out))
    # the non-secret parts of the same values survive
    assert out["DATABASE_URL_SYNC"].startswith("postgresql://registry:") and out["DATABASE_URL_SYNC"].endswith(
        "@op-db:5432/registry")
    assert out["RATE_LIMIT_REDIS_URL"].endswith("@op-redis:6379/1")
    teg = json.loads(out["PARTNER_TEGS"])
    assert teg[0]["teg_id"] == "teg-layer-test" and teg[0]["url"] == ""
    for k in ("PUBLIC_URL", "EVENT_STORE_URL", "UVICORN_WORKERS", "FEATURE_FLAG", "CERT_DIR",
              "EXCHANGE_PASSPORT_ENABLED", "SANDBOX_BYPASS_RATE_LIMIT", "REGISTRY_SIGNING_KEY_REQUIRE_ENCRYPTION",
              "MAIL_FROM"):
        assert out[k] == ENV[k], k


def test_partner_tegs_section_is_masked():
    out = asyncio.run(cr.read_partner_tegs(TARGET, _Probe()))
    assert isinstance(out, list) and len(out) == 1 and all(isinstance(x, str) for x in out)
    assert not _leaks(json.dumps(out))
    assert json.loads(out[0])["teg_id"] == "teg-layer-test"


def test_nginx_section_masks_proxy_markers_and_keeps_variables():
    out = asyncio.run(cr.read_nginx_section(TARGET, _Probe()))
    assert not _leaks(out), _leaks(out)
    for kept in ("ssl_certificate_key /etc/nginx/certs/svid.key;",
                 "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                 "proxy_set_header Authorization $http_authorization;",
                 "proxy_pass http://registry:8000;"):
        assert kept in out, kept
    assert out.count("(masked)") == 2


def test_control_the_fixture_carries_every_secret_before_masking():
    """Control: the planted values really are in the input, so an absence above is the masking's doing."""
    raw = json.dumps(ENV) + NGINX
    assert _leaks(raw) == list(SECRETS)
    # and a plain port is never read as a URL password
    assert cr.mask_url("http://host:8000/x") == "http://host:8000/x"
