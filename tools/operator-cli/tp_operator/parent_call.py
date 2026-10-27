"""One call to the parent frame, made the way this operator's own registry makes it (§OPLANE, CB-228, CB-289, SEC-08).

The CLI used to send its calls from the host to the parent's console address with the federation licence alone. A
frame's public console clears X-Federation-License (every frame built from the template, EU and ASIA among them), so
there the licence never arrives; and the routes that check an operator's licence are served on the parent's federation
lane, to a client certificate the parent's own terminator verified (registry core/mtls_auth.require_vouched_peer_cert).
The host holds no such certificate; the operator's registry container does (/certs, kept current by the cert-writer),
together with the licence (FEDERATION_LICENSE_KEY) and the parent's lane (its ACTIVE frame peer row).

So the call runs inside the operator's registry container, through the registry's own
routers.operator_portal_actions._call_parent: the parent's federation lane with the operator's SVID first, the console
path when the lane is unknown or the parent predates it. The licence presented is the one in the operator's
.env.operator (between a `license rotate` and the registry's restart the container still holds the old one), written to
the container's stdin: it never appears in a process's arguments or in the output. The container prints one line,
MARK + JSON: the parent's status, the lane it went through and its answer.

The commands that ask the parent this way: `license verify` and `sync` (CB-228, CB-289), `license rotate`, `spire
enroll` and `spire revoke` (SEC-08). A route that needs a header besides the licence (rotate-self's X-Idempotency-Key)
names it in `headers`: the requests _call_parent makes for that call carry it too, so the lane, the certificate and the
fallback stay the registry's own. An answer can carry a secret (a rotation's new key), so no error text ever repeats an
answer line.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .config import OperatorContext
from .docker_runner import compose_exec

MARK = "TP_PARENT_CALL "

SCRIPT = r'''
import asyncio, json, os, sys
MARK = "TP_PARENT_CALL "


def say(answer):
    sys.stdout.write(MARK + json.dumps(answer, default=str) + "\n")
    sys.stdout.flush()


spec = json.loads(sys.argv[1])
# The licence in the operator's .env.operator arrives on stdin (never in the arguments); the registry's own is the
# fallback. They differ between a `license rotate` and the registry's restart, and the operator's file is the one meant.
key = sys.stdin.read().strip() or (os.environ.get("FEDERATION_LICENSE_KEY") or "").strip()
if not key:
    say({"error": "no_licence", "detail": "no FEDERATION_LICENSE_KEY in .env.operator or in this registry"})
    sys.exit(0)
try:
    # What the registry does at startup; a fresh process holds no SVID until it does, and would skip the lane.
    from agentvault_registry.identity.svid_client import svid_client
    svid_client.initialize()
except Exception:
    pass
try:
    from agentvault_registry.database import get_db_context
    from agentvault_registry.routers.operator_portal_actions import _call_parent
except Exception as exc:
    say({"error": "no_parent_lane", "detail": "this registry image predates the parent lane (V0614): " + type(exc).__name__})
    sys.exit(0)

# SEC-08: a route that needs a header besides the licence (rotate-self's X-Idempotency-Key). _call_parent sends the
# licence alone, so the requests it makes for this call (the lane, and the console when it falls back) carry these too;
# its own headers win, so the licence is always the one it sends.
extra = {str(k): str(v) for k, v in (spec.get("headers") or {}).items()}
if extra:
    import httpx
    _request = httpx.AsyncClient.request

    async def _with_extra(self, method, url, *args, **kwargs):
        if str(url).endswith((spec["lane_path"], spec["console_path"])):
            kwargs["headers"] = {**extra, **dict(kwargs.get("headers") or {})}
        return await _request(self, method, url, *args, **kwargs)

    httpx.AsyncClient.request = _with_extra


async def main():
    async with get_db_context() as db:
        r, lane = await _call_parent(db, spec["method"], spec["console_path"], spec["lane_path"], key,
                                     json_body=spec.get("json"), params=spec.get("params"),
                                     timeout=float(spec.get("timeout", 30)))
    try:
        body = r.json()
    except Exception:
        body = r.text[:2000]
    say({"status": r.status_code, "lane": lane, "body": body})


try:
    asyncio.run(main())
except Exception as exc:
    say({"error": "call_failed", "detail": (type(exc).__name__ + ": " + str(exc))[:300]})
'''


def parse_answer(stdout: Optional[str]) -> Optional[Dict[str, Any]]:
    """The container's answer line, or None when it printed none (its last MARK line wins)."""
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(MARK):
            try:
                answer = json.loads(line[len(MARK):])
            except ValueError:
                return None
            return answer if isinstance(answer, dict) else None
    return None


def call_parent(ctx: OperatorContext, method: str, console_path: str, lane_path: str, *,
                params: Optional[Dict[str, Any]] = None, json_body: Optional[Any] = None,
                headers: Optional[Dict[str, str]] = None, timeout: float = 30.0) -> Dict[str, Any]:
    """{status, lane, body} from the parent, or {error, detail} when no answer came back. The licence presented is the
    one in the operator's .env.operator, written to the container's stdin (an empty stdin, never the terminal's, when
    there is none: the container then uses its own). `headers`: what the route needs besides the licence (never a
    secret: they travel in the exec's arguments)."""
    spec = json.dumps({"method": method, "console_path": console_path, "lane_path": lane_path,
                       "params": params, "json": json_body, "headers": headers or {}, "timeout": timeout})
    try:
        r = compose_exec(ctx, "registry", "python", "-c", SCRIPT, spec, timeout=int(timeout) + 60,
                         input=ctx.federation_license or "")
    except Exception as exc:  # noqa: BLE001  docker missing, the exec timed out
        return {"error": "exec_failed", "detail": f"{type(exc).__name__}: {exc}"[:300]}
    answer = parse_answer(r.stdout)
    if answer is None:
        # the last line that is not an answer: one that failed to parse may still carry a secret (a new licence key)
        lines = [ln for ln in (r.stderr or r.stdout or "").strip().splitlines() if not ln.startswith(MARK)]
        tail = lines[-1:] or [""]
        return {"error": "no_answer", "detail": f"the registry container answered nothing (exit {r.returncode}): "
                                                f"{tail[0][:200]}"}
    return answer


def answer_detail(answer: Dict[str, Any]) -> str:
    """The parent's reason in one line: its RFC 7807 detail, or the raw text."""
    body = answer.get("body")
    if isinstance(body, dict):
        nested = body.get("error") if isinstance(body.get("error"), dict) else {}
        detail = body.get("detail", nested.get("detail"))
        if detail is not None:
            return str(detail)[:300]
        return json.dumps(body)[:300]
    return str(body or answer.get("detail") or "")[:300]
