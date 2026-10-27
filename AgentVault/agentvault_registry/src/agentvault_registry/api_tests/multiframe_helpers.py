"""Shared helpers for multi-frame flow tests (BFS, EigenTrust, Governance).

These helpers exercise federation flows that require ≥2 registries cooperating.
The target is "sandbox" (the sandbox pair, already federated). A second target, "frames", named the frames the
retired dual-frame lifecycle test left behind; it went with that test (§NIGHTLYPROV, 2026-09-27).

The helpers reach across container boundaries (docker exec, psql) which the
plain `self.test_endpoint(...)` interface in `APITestBase` cannot do — those
calls run from inside the same registry-test container as the flow runner.

Sandbox-only: the tester runs flows only where API_TEST_EXECUTION_ENABLED=true.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional
from agentvault_registry.core import ledger_names   # W4: an event's old and new names are one event
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD, SANDBOX_TUTORIAL_PASSWORD  # §SBROTATE

from agentvault_registry.api_tests.probe_meter import record_probe

logger = logging.getLogger(__name__)


# ─── Target topology map ──────────────────────────────────────────────────

@dataclass
class TargetEndpoints:
    label: str
    a_registry_container: str
    b_registry_container: str
    a_teg_container: str
    b_teg_container: str
    a_es_container: str
    b_es_container: str
    a_es_db_container: str
    b_es_db_container: str
    a_internal_url: str
    b_internal_base_url: str
    a_external_host: str
    b_external_host: str
    a_admin_email: str
    a_admin_password: str
    b_admin_email: str
    b_admin_password: str


# ── §APITEST 2026-09-04 — the sandbox target is now ENV-OVERRIDABLE ──────────
# Every field below was a hardcoded CONTAINER NAME of the retired sandbox tier,
# and the flow drives those containers over the DOCKER SOCKET (login_admin does a
# `docker exec`), not over HTTP. So against a sandbox that is a separate FRAME the
# very first step returned
#     login rc=-1: exec exception: APIError: 409 ... containers/<id>
# and the whole MCP sweep reported 0 tools / 0 passed in under a second — a zero
# that looks exactly like "nothing to test". Defaults are unchanged, so the
# retired tier still works if it is ever restarted; a frame sets the four A-side
# names (and optionally the B-side) and the same suite runs against it.
def _ti(var: str, default: int) -> int:
    raw = os.getenv(var)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _t(var: str, default: str) -> str:
    return os.getenv(var, default) or default


# The registry's own DB container. The flows that reach it for psql had the
# name as a bare literal in five places (§U3 2026-09-05) — the same class as the
# five container literals §APITEST fixed, and equally silent: docker answers 409
# for a stopped container, so the caller reads an empty result, not an error.
REG_DB_A = _t("API_TEST_REG_DB_CONTAINER", "agentvault_registry_db_test")
REG_DB_B = _t("API_TEST_REG_DB_CONTAINER_B", "agentvault_registry_db_test_b")


SANDBOX_TARGET = TargetEndpoints(
    label="sandbox",
    a_registry_container=_t("API_TEST_TGT_A_REGISTRY", "agentvault_registry_test"),
    b_registry_container=_t("API_TEST_TGT_B_REGISTRY", "agentvault_registry_test_b"),
    a_teg_container=_t("API_TEST_TGT_A_TEG", "agentvault_teg_layer_test_a"),
    b_teg_container=_t("API_TEST_TGT_B_TEG", "agentvault_teg_layer_test_b"),
    a_es_container=_t("API_TEST_TGT_A_ES", "agentvault_event_store_test"),
    b_es_container=_t("API_TEST_TGT_B_ES", "agentvault_event_store_test_b"),
    a_es_db_container=_t("API_TEST_TGT_A_ES_DB", "agentvault_event_store_db_test"),
    b_es_db_container=_t("API_TEST_TGT_B_ES_DB", "agentvault_event_store_db_test_b"),
    a_internal_url=_t("API_TEST_TGT_A_INTERNAL_URL", "http://localhost:8000"),
    b_internal_base_url=_t("API_TEST_TGT_B_INTERNAL_URL", "http://agentvault_registry_test_b:8000"),
    a_external_host=_t("API_TEST_TGT_A_EXTERNAL_HOST", "http://localhost:8002"),
    b_external_host=_t("API_TEST_TGT_B_EXTERNAL_HOST", "http://localhost:8003"),
    a_admin_email=_t("SANDBOX_ADMIN_EMAIL", "admin@test.sandbox"),
    a_admin_password=SANDBOX_ADMIN_PASSWORD,
    b_admin_email=_t("SANDBOX_ADMIN_EMAIL", "admin@test.sandbox"),
    b_admin_password=SANDBOX_ADMIN_PASSWORD,
)


def get_target(name: str) -> TargetEndpoints:
    name = (name or "sandbox").strip().lower()
    if name == "sandbox":
        return SANDBOX_TARGET
    raise ValueError(f"Unknown target: {name!r} (expected 'sandbox')")


# ─── Operator targets (single-registry probes for canary flows) ───────────

@dataclass
class OperatorTarget:
    label: str
    registry_container: str
    db_container: str
    teg_container: str
    public_port: int          # external port mapped on host (registry)
    parent_frame: str         # "frame-a" | "frame-b" — parent sandbox mainframe
    parent_registry_container: str  # central sandbox registry container
    admin_email: str          # operator admin developer (set §pass73.1)
    admin_password: str       # plaintext canonical (sandbox-only, not secret)
    mcp_api_key: str          # bearer for MCP bridge (mint via /auth/api-keys)


# Sandbox cloud-ops post-§pass73.3.2: topology compacted to 2 cloud-ops, one
# parented under each sandbox mainframe. sandboxbeta + sandboxgamma were torn
# down for capacity savings. Both surviving cloud-ops share the central
# sandbox EventStore / SPIRE — they only run their own registry + TEG + DB
# behind their own nginx-federation. Admin credentials + MCP API keys
# documented in memory/reference_sandbox_cloudop_creds.md.
# §FEDSUITE 2026-09-04: the two `avreg_` MCP API keys that used to sit here as
# literals are GONE, not defaulted. They belonged to the retired sandbox
# operators (containers Exited), yet shipped inside every registry image, and
# the pre-commit hook refuses the shape on sight — correctly. Supply them via
# API_TEST_FED_{ALPHA,DELTA}_MCP_KEY if a tier ever needs key auth; the login
# path (admin_email/admin_password) is what the suite actually uses.
# §MCPTEST30 (V0637): the container defaults name the operators that answer today (sbxalphaop under sbx-alpha,
# sbxbetaop under sbx-beta, 2026-10-24); the frame's API_TEST_FED_* env names them first. The keys keep the retired
# operators' names, because the two flows and their history are filed under them.
SANDBOX_OPERATOR_TARGETS = {
    "sandboxalpha": OperatorTarget(
        label="sandboxalpha",
        registry_container=_t("API_TEST_FED_ALPHA_CONTAINER", "cloud-op-sbxalphaop-registry"),
        db_container=_t("API_TEST_FED_ALPHA_DB", "cloud-op-sbxalphaop-db"),
        teg_container=_t("API_TEST_FED_ALPHA_TEG", "cloud-op-sbxalphaop-teg"),
        public_port=_ti("API_TEST_FED_ALPHA_PORT", 31100),
        parent_frame="frame-a",
        parent_registry_container=_t("API_TEST_FED_A_CONTAINER", "sbx-alpha-registry"),
        admin_email=_t("API_TEST_FED_ALPHA_EMAIL", "admin@cloud-op-sandboxalpha.dev"),
        admin_password=_t("API_TEST_FED_ALPHA_PASSWORD", "SandboxOpAdmin2026!"),
        mcp_api_key=_t("API_TEST_FED_ALPHA_MCP_KEY", ""),
    ),
    "sandboxdelta": OperatorTarget(
        label="sandboxdelta",
        registry_container=_t("API_TEST_FED_DELTA_CONTAINER", "cloud-op-sbxbetaop-registry"),
        db_container=_t("API_TEST_FED_DELTA_DB", "cloud-op-sbxbetaop-db"),
        teg_container=_t("API_TEST_FED_DELTA_TEG", "cloud-op-sbxbetaop-teg"),
        public_port=_ti("API_TEST_FED_DELTA_PORT", 31200),
        parent_frame="frame-b",
        parent_registry_container=_t("API_TEST_FED_B_CONTAINER", "sbx-beta-registry"),
        admin_email=_t("API_TEST_FED_DELTA_EMAIL", "admin@cloud-op-sandboxdelta.dev"),
        admin_password=_t("API_TEST_FED_DELTA_PASSWORD", "SandboxOpAdmin2026!"),
        mcp_api_key=_t("API_TEST_FED_DELTA_MCP_KEY", ""),
    ),
}


def get_operator_target(name: str) -> OperatorTarget:
    name = (name or "sandboxalpha").strip().lower()
    if name in SANDBOX_OPERATOR_TARGETS:
        return SANDBOX_OPERATOR_TARGETS[name]
    raise ValueError(
        f"Unknown operator target: {name!r} "
        f"(expected one of {list(SANDBOX_OPERATOR_TARGETS)})"
    )


async def mint_admin_jwt_in_container(
    container: str,
    developer_id: int = 1,
    minutes: int = 10,
) -> tuple[bool, str, str]:
    """Mint a developer JWT directly inside the registry container using its
    own SECRET_KEY/ALGORITHM. Skips the password-login path entirely — useful
    for operator canaries where the first-boot admin password is not in
    session memory.

    Returns (ok, jwt, detail). Caller treats jwt as opaque.
    """
    rc, out = await asyncio.to_thread(
        exec_in_container, container, [
            "sh", "-c",
            "PYTHONPATH=/app/src python3 -c \"\n"
            "import sys; sys.path.insert(0, '/app/src')\n"
            "from agentvault_registry.security import create_access_token\n"
            "from datetime import timedelta\n"
            f"print(create_access_token({{'sub': '{developer_id}'}}, "
            f"expires_delta=timedelta(minutes={minutes})))\n\"",
        ], 15,
    )
    if rc != 0:
        return False, "", f"mint rc={rc}: {(out or '')[-200:]}"
    # The Python script prints the JWT on the last non-empty stdout line.
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        return False, "", "mint produced no output"
    jwt_token = lines[-1]
    if jwt_token.count(".") != 2:
        return False, "", f"mint output not a JWT: {jwt_token[:80]}"
    return True, jwt_token, "ok"


# ─── Docker / psql helpers ────────────────────────────────────────────────

# Per-worker-thread persistent Docker client + container-handle cache.
#
# exec_in_container is invoked thousands of times per sweep. The old impl built
# a brand-new docker.DockerClient (unix-socket connect + urllib3 pool) AND did a
# containers.get() API round-trip on EVERY call — that per-call overhead, ×N,
# serialized, was the dominant wall-clock cost (the actual HTTP work is a
# fraction). We now keep one client per worker thread (asyncio.to_thread reuses
# a bounded ThreadPoolExecutor, so the client count is bounded by the executor
# size and the clients persist across runs) and cache the resolved Container
# handle by name. Thread-local also sidesteps requests.Session cross-thread
# races — each thread owns its client and makes one blocking call at a time, so
# this is safe under the bounded-semaphore sweep parallelism.
import threading as _threading

_docker_tls = _threading.local()


def _docker_client():
    import docker
    cl = getattr(_docker_tls, "client", None)
    if cl is None:
        cl = docker.DockerClient(base_url="unix://var/run/docker.sock")
        _docker_tls.client = cl
        _docker_tls.containers = {}
    return cl


def _get_container(name: str):
    """Return a cached Container handle for `name` (per worker thread).

    Caches the container id so exec_run skips the per-call containers.get()
    round-trip. Stable for a run's lifetime (sandbox containers aren't recreated
    mid-run; a rebuild ends the run). exec_in_container drops + re-resolves the
    handle once on failure to cover a restart / transient socket hiccup.
    """
    client = _docker_client()
    cache = getattr(_docker_tls, "containers", None)
    if cache is None:
        cache = _docker_tls.containers = {}
    c = cache.get(name)
    if c is None:
        c = client.containers.get(name)
        cache[name] = c
    return c


# §MCPSWEEP 2026-09-28 (agentvault2-41): docker's exec_inspect can answer before the process is reaped, so the exit
# code docker-py's exec_run reads right after the output stream ends may be None (docker-py 7.2.0 returns it as is).
# The old `int(rc or 0)` turned that UNKNOWN into a success. Measured symptom: since the V0478 roll, about one probe per
# run came back with rc 0 and no output while the server's own audit row shows it answered (the rig's "HTTP : ",
# the auth matrix's status 0). The exit code is now waited for briefly; a code still unknown after that is its own
# named failure. A momentary "still running" right after the output ends is the ordinary case and not a failure.
_EXEC_EXIT_WAIT_S = 5.0


def _wait_exit_code(api, exec_id: str) -> Optional[int]:
    info = api.exec_inspect(exec_id)
    deadline = time.monotonic() + _EXEC_EXIT_WAIT_S
    while (info.get("Running") or info.get("ExitCode") is None) and time.monotonic() < deadline:
        time.sleep(0.05)
        info = api.exec_inspect(exec_id)
    code = info.get("ExitCode")
    return None if (code is None or info.get("Running")) else int(code)


def _exec_once(name: str, args: list) -> tuple[int, str]:
    c = _get_container(name)
    api = c.client.api
    ex = api.exec_create(c.id, args, stdout=True, stderr=True)
    out = api.exec_start(ex["Id"], demux=False)
    if isinstance(out, (bytes, bytearray)):
        out = out.decode(errors="replace")
    out = str(out or "")
    rc = _wait_exit_code(api, ex["Id"])
    if rc is None:
        return -1, (f"exec returned no exit code: the process still ran {_EXEC_EXIT_WAIT_S:.0f} s after its output "
                    f"stream ended ({len(out)} chars captured): {out[:200]}")
    return rc, out


def exec_in_container(name: str, args: list, timeout: int = 30) -> tuple[int, str]:
    # NOTE: `timeout` is accepted for call-site compatibility but, as in the
    # original impl, is not forwarded to exec_run (docker-py bounds the call by
    # the client's default socket timeout). Behavior preserved deliberately.
    #
    # U1 (2026-09-05): this is the ONE function every federation-suite probe
    # passes through — MCP calls, REST via adminRequest, psql, raw exec. The
    # meter here is what lets the runner tell a real pass from a test that
    # measured nothing. Counted on ENTRY, so a probe that errors still counts as
    # having touched the system; the vacuity verdict is about whether the test
    # reached for the system at all, not about whether the reach succeeded.
    record_probe()
    # §MCPTEST30 (V0553): a curl that reports its status (the -w marker) runs with its whole answer kept in a short-lived
    # file in the container; when the exec's own stream comes back rc 0 without the marker, that file is read with a
    # second exec instead of asking the route again (see _kept_answer).
    token = _kept_token(args)
    run_args = ["sh", "-c", kept_answer_script(args[2], token)] if token else args
    rc, out = _exec_retrying(name, run_args)
    if token and rc == 0 and _HTTP_MARKER not in (out or ""):
        return _kept_answer(name, token, rc, out)
    return rc, out


# ─── §MCPTEST30 (V0553): an answer the exec stream dropped is read back, never asked for again ──────────────────────
# Measured in rounds 15-18: a docker exec now and then returns rc 0 with its output stream cut, so curl's status marker
# (printed even when a transfer fails) is missing although curl ran. For a read the flow asks once more; a WRITE cannot
# be asked twice, so its row read NOT MEASURED ("the answer was lost in transit"). The answer was never lost: it is in
# the container. Every curl status call now keeps its output in /tmp/mcpt-answers/<token> (two minutes; each call
# removes older ones), and a marker-less answer is that file, read back.
_KEPT_DIR = "/tmp/mcpt-answers"
_KEPT_MINUTES = 2
KEPT_RECOVERIES = {"recovered": 0, "still_lost": 0}


def _kept_token(args: list) -> Optional[str]:
    """A token for `sh -c <script>` when the script reports curl's status with the marker; None for anything else."""
    if (isinstance(args, list) and len(args) == 3 and args[0] == "sh" and args[1] == "-c"
            and isinstance(args[2], str) and _HTTP_MARKER in args[2]):
        import secrets as _secrets
        return f"{time.time_ns()}-{_secrets.token_hex(4)}"
    return None


def kept_answer_script(script: str, token: str) -> str:
    """`script` in a subshell (an `exit` inside it, or a `#` comment on its last line, cannot skip what follows), its
    stdout and stderr kept in the token's file and printed, its exit code passed on."""
    f = f"{_KEPT_DIR}/{token}"
    return (f"mkdir -p {_KEPT_DIR} 2>/dev/null; find {_KEPT_DIR} -type f -mmin +{_KEPT_MINUTES} -delete 2>/dev/null; "
            f"(\n{script}\n) > {f} 2>&1; rc=$?; cat {f}; exit $rc")


def _kept_answer(name: str, token: str, rc: int, out: str) -> tuple[int, str]:
    """The first exec came back rc 0 without the marker: read the kept file. Returns it when it carries the marker (the
    call's own answer), else the first exec's result unchanged (still lost: the flow says so as before)."""
    rc2, out2 = _exec_retrying(name, ["sh", "-c", f"cat {_KEPT_DIR}/{token}"])
    if rc2 == 0 and _HTTP_MARKER in (out2 or ""):
        KEPT_RECOVERIES["recovered"] += 1
        logger.info("[exec] an answer the exec stream dropped was read back from the container (%s)", token)
        return 0, out2
    KEPT_RECOVERIES["still_lost"] += 1
    return rc, out


def _exec_retrying(name: str, args: list) -> tuple[int, str]:
    try:
        return _exec_once(name, args)
    except Exception as e:
        # Invalidate the cached handle once and retry — covers a container that
        # was restarted (new exec endpoint) or a transient docker-socket hiccup.
        try:
            cache = getattr(_docker_tls, "containers", None)
            if cache is not None:
                cache.pop(name, None)
            return _exec_once(name, args)
        except Exception as e2:
            return -1, (
                f"exec exception: {type(e2).__name__}: {e2} "
                f"(after retry; first={type(e).__name__}: {e})"
            )


def run_psql_in_db_container(container: str, sql: str, db_name: Optional[str] = None) -> tuple[int, str]:
    encoded = base64.b64encode(sql.encode()).decode()
    db_target = "$POSTGRES_DB" if not db_name else db_name
    cmd = [
        "sh", "-c",
        f"echo '{encoded}' | base64 -d | "
        f"PGPASSWORD=$POSTGRES_PASSWORD psql -U $POSTGRES_USER -d {db_target} "
        f"-At -v ON_ERROR_STOP=1",
    ]
    return exec_in_container(container, cmd, timeout=15)


def query_event_count(es_db_container: str, event_type: str) -> int:
    rc, out = run_psql_in_db_container(
        es_db_container,
        # W4: the event under every name it is stored under (old, new, legacy); names are the map's own constants
        "SELECT count(*) FROM events WHERE event_type IN ("
        + ", ".join(f"'{n}'" for n in ledger_names.names_of(event_type)) + ");",
    )
    if rc != 0:
        return -1
    try:
        return int(out.strip())
    except Exception:
        return -1


def query_total_events(es_db_container: str) -> int:
    rc, out = run_psql_in_db_container(es_db_container, "SELECT count(*) FROM events;")
    if rc != 0:
        return -1
    try:
        return int(out.strip())
    except Exception:
        return -1


# ─── HTTP-from-container helpers ──────────────────────────────────────────

_HTTP_MARKER = "--HTTP_CODE="


def _split_http_body_code(out: str) -> tuple[str, str]:
    if _HTTP_MARKER not in out:
        return out, ""
    body, _, after = out.rpartition(_HTTP_MARKER)
    return body, after.rstrip("-").strip()


async def login_admin(target: TargetEndpoints, side: str = "a") -> tuple[bool, str, str]:
    if side == "a":
        cont, email, password = target.a_registry_container, target.a_admin_email, target.a_admin_password
    else:
        cont, email, password = target.b_registry_container, target.b_admin_email, target.b_admin_password
    rc, out = await asyncio.to_thread(
        exec_in_container, cont, [
            "sh", "-c",
            "curl -sS -X POST "
            f"-H 'Content-Type: application/x-www-form-urlencoded' "
            f"--data-urlencode 'username={email}' "
            f"--data-urlencode 'password={password}' "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/auth/login",
        ], 20,
    )
    if rc != 0:
        return False, "", f"login rc={rc}: {out[:200]}"
    body, code = _split_http_body_code(out)
    if code and not code.startswith("2"):
        return False, "", f"login http={code}: {body[:200]}"
    try:
        d = json.loads(body)
        jwt = d.get("access_token", "")
        if not jwt:
            return False, "", f"no access_token: {body[:200]}"
        return True, jwt, "ok"
    except Exception as e:
        return False, "", f"parse: {e}; body={body[:200]}"


async def onboard_agent(
    target: TargetEndpoints,
    side: str,
    dev_jwt: str,
    name: str,
    description: str = "Multi-frame test agent for verifying federation flows",
) -> tuple[bool, dict, str]:
    cont = target.a_registry_container if side == "a" else target.b_registry_container
    rc, out = await asyncio.to_thread(
        exec_in_container, cont, [
            "sh", "-c",
            f"curl -sS -X POST "
            f"-H 'Authorization: Bearer {dev_jwt}' "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"agent_name_hint\":\"{name}\"}}' "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/onboard/bootstrap/request-token",
        ], 20,
    )
    body, code = _split_http_body_code(out)
    if rc != 0 or (code and not code.startswith("2")):
        return False, {}, f"bootstrap rc={rc}/http={code}: {body[:200]}"
    try:
        bs_token = json.loads(body).get("bootstrap_token", "")
    except Exception as e:
        return False, {}, f"bootstrap parse: {e}; body={body[:200]}"
    if not bs_token:
        return False, {}, f"no bootstrap_token: {body[:200]}"

    card_body = {
        "agent_did_method": "theprotocol",
        "agent_card": {
            "schemaVersion": "1.0",
            "humanReadableId": name,
            "agentVersion": "0.1.0",
            "name": name,
            "description": description,
            "url": "http://localhost:8000/a2a",
            "provider": {"name": name},
            "capabilities": {},
            "skills": [],
            "authSchemes": [{"scheme": "none"}],
        },
    }
    body_b64 = base64.b64encode(json.dumps(card_body).encode()).decode()
    rc, out = await asyncio.to_thread(
        exec_in_container, cont, [
            "sh", "-c",
            f"echo '{body_b64}' | base64 -d | "
            f"curl -sS -X POST "
            f"-H 'Bootstrap-Token: {bs_token}' "
            f"-H 'Content-Type: application/json' "
            f"--data-binary @- "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/onboard/create_agent",
        ], 30,
    )
    body_text, code = _split_http_body_code(out)
    if rc != 0 or (code and not code.startswith("2")):
        return False, {}, f"create_agent rc={rc}/http={code}: {body_text[:300]}"
    try:
        d = json.loads(body_text)
        return True, {
            "did": d.get("agent_did", ""),
            "client_id": d.get("client_id", ""),
            "client_secret": d.get("client_secret", ""),
        }, "ok"
    except Exception as e:
        return False, {}, f"create_agent parse: {e}; body={body_text[:300]}"


async def get_agent_jwt(
    target: TargetEndpoints,
    side: str,
    client_id: str,
    client_secret: str,
) -> tuple[bool, str, str]:
    cont = target.a_registry_container if side == "a" else target.b_registry_container
    rc, out = await asyncio.to_thread(
        exec_in_container, cont, [
            "sh", "-c",
            f"curl -sS -X POST "
            f"-H 'Content-Type: application/x-www-form-urlencoded' "
            f"--data-urlencode 'grant_type=password' "
            f"--data-urlencode 'username={client_id}' "
            f"--data-urlencode 'password={client_secret}' "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            "http://localhost:8000/api/v1/auth/agent/token",
        ], 20,
    )
    body, code = _split_http_body_code(out)
    if rc != 0 or (code and not code.startswith("2")):
        return False, "", f"agent_token rc={rc}/http={code}: {body[:200]}"
    try:
        d = json.loads(body)
        jwt = d.get("access_token", "")
        if not jwt:
            return False, "", f"no access_token: {body[:200]}"
        return True, jwt, "ok"
    except Exception as e:
        return False, "", f"agent_token parse: {e}; body={body[:200]}"


async def get_teg_admin_key(target: TargetEndpoints, side: str) -> Optional[str]:
    cont = target.a_teg_container if side == "a" else target.b_teg_container
    rc, out = await asyncio.to_thread(exec_in_container, cont, ["env"], 5)
    if rc != 0:
        return None
    for line in out.splitlines():
        if line.startswith("ADMIN_API_KEY="):
            return line.split("=", 1)[1].strip()
    return None


async def mint_to_agent(
    target: TargetEndpoints,
    side: str,
    agent_did: str,
    amount: float,
    reason: str = "multiframe test seed funding",
) -> tuple[bool, str]:
    # §pass73.3.19: mint via the REGISTRY's /teg/treasury/mint proxy — the
    # authorized emitter that emits TokensIssued to the EventStore. The prior
    # behavior hit the TEG's /admin/token/issue directly, which credited the TEG
    # ledger but bypassed the registry emit (TEG emit is policy-blocked:
    # event_emission_policies TokensIssued.emit_from_teg=false). So the funding
    # credit never reached the ES projection while the later stake/transfer
    # DEBIT was counted → negative-balance projection drift. Routing through the
    # registry closes that emission gap (TokensIssued now lands in the projection).
    reg_cont = target.a_registry_container if side == "a" else target.b_registry_container
    ok_login, dev_jwt, det = await login_admin(target, side)
    if not ok_login or not dev_jwt:
        return False, f"admin login failed on {side}: {det}"
    ok, body_obj, code = await http_in_container(
        reg_cont, "POST", "/api/v1/teg/treasury/mint",
        body={"target_agent_did": agent_did, "amount": str(amount), "reason": reason},
        jwt=dev_jwt, timeout=30,
    )
    if not ok:
        return False, f"mint via registry /teg/treasury/mint http={code}: {str(body_obj)[:200]}"
    return True, f"minted {amount} to {agent_did[:30]}... (registry proxy → TokensIssued emitted)"


# ─── Cross-registry HTTP via container exec (for sandbox B calls) ─────────

# ─── Supply audit helper (A1) ─────────────────────────────────────────────

def query_supply_audit(es_container: str) -> dict:
    """Call the official `GET /api/v1/projections/supply-audit` endpoint on
    the EventStore. This is the source-of-truth audit (the same one
    auditor.theprotocol.cloud surfaces publicly), with the proper formula:

        net_supply = tokens_issued - tokens_destroyed
        delta = abs(net_supply - total_circulating)

    Earlier this helper queried the DB directly with an INCOMPLETE formula
    (missing tokens_destroyed) — which falsely reported 15K AVT drift in
    sandbox-A. Fixed by routing through the official endpoint.

    Returns the full audit dict: {tokens_issued, tokens_destroyed,
    tokens_fees_collected, net_supply, total_circulating, delta, status,
    agent_count}. On error returns {tokens_issued: -1, total_circulating: -1, delta: None}.
    """
    import asyncio as _asyncio
    # GET endpoint requires X-Internal-Key from the ES container's own env.
    # Fetch the key + curl from inside the same container.
    rc_env, env_out = exec_in_container(es_container, ["env"], 5)
    internal_key = ""
    if rc_env == 0:
        for line in (env_out or "").splitlines():
            if line.startswith("INTERNAL_API_KEY="):
                internal_key = line.split("=", 1)[1].strip()
                break
    if not internal_key:
        return {"tokens_issued": -1.0, "total_circulating": -1.0, "delta": None,
                "_error": "no INTERNAL_API_KEY"}
    rc, out = exec_in_container(es_container, [
        "python3", "-c",
        f"import urllib.request,json,sys;\n"
        f"req=urllib.request.Request('http://localhost:8200/api/v1/projections/supply-audit', "
        f"headers={{'X-Internal-Key': '{internal_key}'}});\n"
        f"r=urllib.request.urlopen(req, timeout=10);\n"
        f"print(r.read().decode())"
    ], 15)
    if rc != 0:
        return {"tokens_issued": -1.0, "total_circulating": -1.0, "delta": None,
                "_error": f"http call failed rc={rc}: {(out or '')[:120]}"}
    try:
        return json.loads((out or "").strip())
    except Exception as e:
        return {"tokens_issued": -1.0, "total_circulating": -1.0, "delta": None,
                "_error": f"parse: {e}; raw={(out or '')[:120]}"}


# ─── Direct TEG balance lookup (B2 — DB consistency check) ────────────────

# ── Direct-DB integrity probes (the canary for TEG↔Registry drift) ────────
#
# These hit the underlying tables directly. They exist BECAUSE the endpoint
# reads (`/teg/balance` always proxies to TEG; `/developers/me/agents`
# returns the registry-cached value) can't tell us if the two databases
# physically agree. Drift between TEG-DB and Registry-DB is the bug class
# we want to alarm on. Endpoint reads are the final cross-check.

def teg_db_balance_for(
    target: TargetEndpoints,
    side: str,
    agent_did: str,
) -> Optional[float]:
    """Direct psql to TEG DB: agent_teg_profiles.token_balance.
    This is the SOURCE OF TRUTH balance — what TEG actually holds.
    Compare with `registry_db_balance_for(...)` to detect cache drift."""
    teg_db_cont = (
        "agentvault_teg_db_test_a" if side == "a"
        else "agentvault_teg_db_test_b"
    )
    rc, out = run_psql_in_db_container(
        teg_db_cont,
        f"SELECT COALESCE(token_balance, 0) FROM agent_teg_profiles WHERE agent_id = '{agent_did}';",
    )
    if rc != 0:
        return None
    line = (out or "").strip()
    if not line:
        return 0.0  # agent not yet in TEG profiles → balance is implicitly 0
    try:
        return float(line)
    except Exception:
        return None


def registry_db_balance_for(
    target: TargetEndpoints,
    side: str,
    agent_did: str,
) -> Optional[float]:
    """Direct psql to Registry DB: agents.liquid_balance.
    This is the CACHED copy — kept in sync from TEG via cross-teg-balance-sync.
    Compare with `teg_db_balance_for(...)` to surface DB-level drift."""
    reg_db_cont = (
        "agentvault_registry_db_test" if side == "a"
        else "agentvault_registry_db_test_b"
    )
    rc, out = run_psql_in_db_container(
        reg_db_cont,
        f"SELECT COALESCE(liquid_balance, 0) FROM agents WHERE did = '{agent_did}';",
    )
    if rc != 0:
        return None
    line = (out or "").strip()
    if not line:
        return 0.0
    try:
        return float(line)
    except Exception:
        return None


# ── Endpoint reads (use these for the LAST verification cross-check) ───────

async def teg_balance_for(
    target: TargetEndpoints,
    side: str,
    agent_did: str,
    dev_jwt: str,
) -> Optional[float]:
    """Read TEG-side balance for one agent via the official GET endpoint.

    For multiple agents prefer `teg_balances_batch` (one call vs N).
    """
    cont = target.a_registry_container if side == "a" else target.b_registry_container
    ok, body, code = await http_in_container(
        cont, "GET", f"/api/v1/developers/me/agents/{agent_did}/balance",
        jwt=dev_jwt, timeout=15,
    )
    if not ok or not isinstance(body, dict):
        return None
    try:
        return float(body.get("balance", 0))
    except Exception:
        return None


async def teg_balances_batch(
    target: TargetEndpoints,
    side: str,
    agent_dids: list,
    dev_jwt: str,
) -> dict:
    """Read TEG-side balances for up to 50 agents in ONE call via the official
    POST /api/v1/developers/me/agents/balances batch endpoint. Returns a dict
    mapping {agent_did: float_balance_or_None}. Missing agents return None.
    """
    cont = target.a_registry_container if side == "a" else target.b_registry_container
    ok, body, code = await http_in_container(
        cont, "POST", "/api/v1/developers/me/agents/balances",
        body={"agent_dids": list(agent_dids)},
        jwt=dev_jwt, timeout=20,
    )
    if not ok or not isinstance(body, dict):
        return {did: None for did in agent_dids}
    raw = body.get("balances", {}) if isinstance(body.get("balances"), dict) else {}
    out: dict = {}
    for did in agent_dids:
        rec = raw.get(did) or {}
        if isinstance(rec, dict) and "error" not in rec:
            try:
                out[did] = float(rec.get("balance", 0))
            except Exception:
                out[did] = None
        else:
            out[did] = None
    return out


async def registry_cached_balance_for(
    target: TargetEndpoints,
    side: str,
    agent_did: str,
    dev_jwt: str,
) -> Optional[float]:
    """Read REGISTRY-cached balance via the official GET endpoint.

    GET /api/v1/developers/me/agents returns the developer's agent list, each
    item containing `liquid_balance` from the registry's agents table (the
    cached field that gets synced from TEG via cross-teg-balance-sync).

    The B2 consistency check asserts abs(teg_balance - registry_cached) < 0.01
    — a divergence means the cache sync is broken (real DB-consistency bug).
    """
    cont = target.a_registry_container if side == "a" else target.b_registry_container
    ok, body, code = await http_in_container(
        cont, "GET", "/api/v1/developers/me/agents",
        jwt=dev_jwt, timeout=15,
    )
    if not ok:
        return None
    agents = body.get("agents") if isinstance(body, dict) else (body if isinstance(body, list) else [])
    if not isinstance(agents, list):
        return None
    for a in agents:
        if isinstance(a, dict) and a.get("did") == agent_did:
            try:
                return float(a.get("liquid_balance", 0))
            except Exception:
                return None
    return None


async def http_in_container(
    container: str,
    method: str,
    path: str,
    body: Optional[dict] = None,
    jwt: Optional[str] = None,
    timeout: int = 30,
) -> tuple[bool, dict, str]:
    """Make an HTTP call from inside `container` to `http://localhost:8000{path}`.
    Returns (ok, parsed_body_or_raw, http_code)."""
    auth = f"-H 'Authorization: Bearer {jwt}'" if jwt else ""
    if body is not None:
        body_b64 = base64.b64encode(json.dumps(body).encode()).decode()
        body_part = (
            f"echo '{body_b64}' | base64 -d | "
            f"curl -sS -X {method} {auth} -H 'Content-Type: application/json' --data-binary @- "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            f"http://localhost:8000{path}"
        )
    else:
        body_part = (
            f"curl -sS -X {method} {auth} "
            f"-w '\\n{_HTTP_MARKER}%{{http_code}}--' "
            f"http://localhost:8000{path}"
        )
    rc, out = await asyncio.to_thread(exec_in_container, container, ["sh", "-c", body_part], timeout)
    body_text, code = _split_http_body_code(out)
    if rc != 0:
        return False, {"_rc": rc, "_raw": body_text[:300]}, code
    if not (code and code.startswith("2")):
        try:
            return False, json.loads(body_text), code
        except Exception:
            return False, {"_raw": body_text[:300]}, code
    try:
        return True, json.loads(body_text), code
    except Exception:
        return True, {"_raw": body_text[:300]}, code
