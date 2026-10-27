"""tp-operator doctor — comprehensive diagnostic report."""
from __future__ import annotations

import shutil
import socket
import sys
from typing import Any, Dict

import httpx
import typer

from .. import __schema_version__, __version__
from ..config import OperatorContext
from ..docker_runner import compose_ps_json, docker_info_ok
from ..http_client import SETTINGS as _HTTP, event_hooks, timeout_or
from ..output import Output, detect_output_mode


def _diagnose(ctx: OperatorContext) -> Dict[str, Any]:
    checks = []

    # Docker
    docker_ok = docker_info_ok()
    checks.append({"check": "docker-daemon", "result": "ok" if docker_ok else "fail"})

    # Disk free
    try:
        usage = shutil.disk_usage(str(ctx.dir))
        free_gb = round(usage.free / (1024 ** 3), 1)
        checks.append({"check": "disk-free-gb", "result": str(free_gb)})
    except OSError:
        checks.append({"check": "disk-free-gb", "result": "unknown"})

    # Compose ps
    services = compose_ps_json(ctx) if docker_ok else []
    running_count = sum(1 for s in services if (s.get("State") or "").lower() == "running")
    checks.append({"check": "services-running", "result": f"{running_count}/{len(services)}"})

    # License presence
    checks.append({"check": "license-present", "result": "yes" if ctx.federation_license else "no"})

    # Mainframe reachability
    try:
        with httpx.Client(timeout=timeout_or(5.0), verify=False, event_hooks=event_hooks()) as c:
            r = c.get(f"{ctx.mainframe_url}/health")
        checks.append({"check": "mainframe-reachable", "result": "ok" if 200 <= r.status_code < 300 else f"http-{r.status_code}"})
    except Exception as e:
        checks.append({"check": "mainframe-reachable", "result": f"fail:{str(e)[:60]}"})

    return {
        "schema_version": __schema_version__,
        "cli_version": __version__,
        "operator": ctx.name,
        "hostname": socket.gethostname(),
        "checks": checks,
    }


# ── §FRAMEKIT P3.3 (2026-09-12): the read-only FRAME checks — the runbook's acceptance shape as `tp doctor --frame` ──
import json as _json
import os as _os
import subprocess as _sp
import time as _time
import urllib.parse as _up
import urllib.request as _ur
import urllib.error as _ue

FRAME_RAILS = ("agent-cards/discover?limit=1", "agent-cards/?limit=1", "public/registry-config", "federation/registries", "reputation-bond/config")


def _get(url: str, timeout: float = 20.0, headers: Dict[str, str] = None):
    """(status, body-or-json, response headers); never raises."""
    req = _ur.Request(url, headers=headers or {})
    try:
        with _ur.urlopen(req, timeout=timeout_or(timeout)) as r:
            raw = r.read()
            if _HTTP.get("verbose"):
                print(f"HTTP GET {url} -> {r.status}", file=sys.stderr, flush=True)
            try:
                return r.status, _json.loads(raw), dict(r.headers)
            except ValueError:
                return r.status, raw[:200], dict(r.headers)
    except _ue.HTTPError as e:
        if _HTTP.get("verbose"):
            print(f"HTTP GET {url} -> {e.code}", file=sys.stderr, flush=True)
        raw = e.read()
        try:
            return e.code, _json.loads(raw), dict(e.headers)
        except ValueError:
            return e.code, raw[:200], dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {str(e)[:80]}", {}


def limiter_verdict(got: str, env_label: str) -> tuple:
    """(verdict, detail). A BYPASSED limiter sends no header (§RATEFIX); production wants 1200 (measured on EU)."""
    got = got or "none"
    if env_label == "prod":
        return ("ok" if got == "1200" else "fail"), f"x-ratelimit-limit={got} (production wants 1200)"
    if env_label == "sandbox":
        return ("ok" if got in ("none", "999999") else "warn"), f"x-ratelimit-limit={got} (sandbox: the limiter is bypassed, no header expected)"
    return "not-measured", f"x-ratelimit-limit={got}; the meta declares no env_label, so no posture to hold it to"


def rails_verdict(codes: Dict[str, int]) -> tuple:
    bad = {k: v for k, v in codes.items() if v != 200}
    return ("ok" if not bad else "fail"), (f"{len(codes)}/{len(codes)} answer 200" if not bad else f"{bad} (the rest 200)")


def delta_verdict(delta, status: str) -> tuple:
    try:
        ok = float(delta) == 0.0 and str(status).upper() == "OK"
    except (TypeError, ValueError):
        return "not-measured", f"unreadable ({delta!r}, {status!r})"
    return ("ok" if ok else "fail"), f"delta={delta} status={status}"


def targets_verdict(active, name: str) -> tuple:
    """Prometheus /api/v1/targets rows for this frame: by the frame label (file_sd) or by the three job names (static)."""
    want = {f"{name}-registry", f"{name}-teg", f"{name}-event-store"}
    seen = {}
    for t in active or []:
        lab = t.get("labels") or {}
        job = lab.get("job")
        if job in want or (lab.get("frame") == name and job):
            seen[job] = t.get("health")
    up = sorted(j for j, h in seen.items() if h == "up")
    down = sorted(j for j, h in seen.items() if h != "up")
    missing = sorted(want - set(seen))
    if missing and not seen:
        return "fail", f"no scrape target for {name}: {sorted(want)} (nothing scrapes this frame — no history, no alert possible)"
    if missing or down:
        return "warn", f"up={up} down={down} missing={missing}"
    return "ok", f"{len(up)} scraped and up: {up}"


def _diagnose_frame(ctx: OperatorContext) -> Dict[str, Any]:
    checks = []
    def row(check, verdict, result): checks.append({"check": check, "verdict": verdict, "result": result})
    port, esport, name = ctx.frame_registry_port, ctx.frame_es_port, ctx.name
    base = f"http://127.0.0.1:{port}/api/v1" if port else None
    docker_ok = docker_info_ok()
    row("docker-daemon", "ok" if docker_ok else "fail", "ok" if docker_ok else "unreachable")
    try:
        usage = shutil.disk_usage(str(ctx.dir)); free_gb = round(usage.free / (1024 ** 3), 1)
        row("disk-free-gb", "ok" if free_gb >= 60 else "warn", str(free_gb))
    except OSError:
        row("disk-free-gb", "not-measured", "unknown")
    services = compose_ps_json(ctx) if docker_ok else []
    running = sum(1 for s in services if (s.get("State") or "").lower() == "running")
    row("services-running", "ok" if services and running == len(services) else ("warn" if services else "not-measured"), f"{running}/{len(services)}")
    row("posture", "ok", f"env_label={ctx.frame_env_label} trust_domain={ctx.frame_trust_domain or '?'}")
    if not base:
        row("registry-health", "not-measured", "no 127.0.0.1:<port>:8000 mapping in the compose")
        return {"schema_version": __schema_version__, "cli_version": __version__, "kind": "frame", "frame": name, "hostname": socket.gethostname(), "checks": checks}
    st, _b, _h = _get(f"http://127.0.0.1:{port}/health", 10)
    row("registry-health", "ok" if st == 200 else "fail", f"http-{st}")
    codes = {r.split("?")[0]: _get(f"{base}/{r}", 25)[0] for r in FRAME_RAILS}
    row("public-rails", *rails_verdict(codes))
    st, card, _h = _get(f"http://127.0.0.1:{port}/.well-known/registry-card.json", 20)
    card_ver = (card.get("identity") or {}).get("software_version") if isinstance(card, dict) else None
    in_image = ""
    if docker_ok:
        r = _sp.run(["docker", "exec", f"{name}-registry", "python", "-c",
                     "import sys;sys.path.insert(0,'/app/src');from agentvault_registry.core.registry_identity import BUNDLED_IMAGE_TAG as t;print(t)"],
                    capture_output=True, text=True, timeout=60)
        in_image = (r.stdout or "").strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else ""
    if card_ver and in_image:
        row("card-version", "ok" if card_ver == in_image else "fail", f"card={card_ver} image={in_image}" if card_ver != in_image else card_ver)
    else:
        row("card-version", "not-measured", f"card={card_ver} image={in_image or '?'}")
    card_hash = ((card.get("federation") or {}).get("policy_hash") or "").replace("sha256:", "") if isinstance(card, dict) else ""
    st, pc, _h = _get(f"{base}/federation/policy-compliance", 20)
    if st == 401 and ctx.env.get("FIRST_ADMIN_EMAIL") and ctx.env.get("FIRST_ADMIN_PASSWORD"):
        # the peer-facing endpoint wants a licence; the admin one takes the frame admin the stack's env names (a read)
        body = _up.urlencode({"username": ctx.env["FIRST_ADMIN_EMAIL"], "password": ctx.env["FIRST_ADMIN_PASSWORD"]}).encode()
        try:
            with _ur.urlopen(_ur.Request(f"{base}/auth/login", data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"}), timeout=timeout_or(20)) as r:
                tok = _json.loads(r.read()).get("access_token", "")
            st, pc, _h = _get(f"{base}/admin/federation/policy-compliance", 20, {"Authorization": f"Bearer {tok}"})
        except Exception:  # noqa: BLE001 — a stale env admin is a known state (the trap-file class); say so below
            st, pc = 401, None
    served = (pc.get("policy_hash") or pc.get("hash") or "").replace("sha256:", "") if isinstance(pc, dict) else ""
    if st == 200 and card_hash and served:
        row("policy-hash", "ok" if card_hash == served else "fail", f"card {card_hash[:8]} / compliance {served[:8]} (source {pc.get('policy_source', '?') if isinstance(pc, dict) else '?'})")
    else:
        row("policy-hash", "not-measured", f"compliance endpoint http-{st} (the env's frame admin {'logged in' if st != 401 else 'is refused: rotated?'}); card hash {'present' if card_hash else 'absent'}")
    st, _b, hdrs = _get(f"http://127.0.0.1:{port}/health", 10, {"X-Real-IP": "198.51.100.7"})
    got = next((v for k, v in (hdrs or {}).items() if k.lower() == "x-ratelimit-limit"), "")
    row("limiter-posture", *limiter_verdict(got, ctx.frame_env_label))
    since = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime(_time.time() - 2))
    _get(f"http://127.0.0.1:{port}/health", 10, {"X-Forwarded-For": "203.0.113.77, 198.51.100.50"})
    _get(f"http://127.0.0.1:{port}/health", 10, {"X-Real-IP": "198.51.100.9"}); _time.sleep(2)
    if docker_ok:
        logs = _sp.run(["docker", "logs", "--since", since, f"{name}-registry"], capture_output=True, text=True, timeout=30)
        txt = logs.stdout + logs.stderr
        hits, wrong, control = txt.count("198.51.100.50"), txt.count("203.0.113.77"), txt.count("198.51.100.9")
        # a probe may report what it observed and what it could not distinguish, never why: three states
        if hits >= 1:
            row("xff-appended-element", "ok", f"198.51.100.50 logged x{hits} (the caller's own element x{wrong})")
        elif wrong >= 1:
            row("xff-appended-element", "fail", "the CALLER'S element (203.0.113.77) is the one logged — the registry trusts the wrong XFF element (§XFFTRUST)")
        elif control == 0:
            row("xff-appended-element", "not-measured", "this registry logs no client address for /health at all (neither element nor the X-Real-IP control appeared): the trust order cannot be read from its log")
        else:
            row("xff-appended-element", "fail", "the X-Real-IP control was logged but the appended XFF element was not")
    else:
        row("xff-appended-element", "not-measured", "docker unreachable")
    if esport:
        st, sa, _h = _get(f"http://127.0.0.1:{esport}/api/v1/projections/supply-audit", 30)
        row("supply-delta", *(delta_verdict(sa.get("delta"), sa.get("status")) if isinstance(sa, dict) else ("not-measured", f"http-{st}")))
    else:
        row("supply-delta", "not-measured", "no 127.0.0.1:<port>:8200 mapping in the compose")
    aud = (_os.environ.get("TP_AUDITOR_URL") or "http://127.0.0.1:8045").rstrip("/")
    st, la, _h = _get(f"{aud}/api/auditor/latest", 20)
    fr = (la.get("frames") if isinstance(la, dict) else None) or (la if isinstance(la, dict) else {})
    v = fr.get(name) if isinstance(fr, dict) else None
    if isinstance(v, dict):
        row("auditor-verdict", "ok" if str(v.get("status")).upper() == "OK" else "fail", f"{v.get('status')} delta={v.get('delta')}")
    else:
        row("auditor-verdict", "not-measured", f"{aud}: http-{st}, frame {name} absent (not wired into the auditor, or the auditor is elsewhere: TP_AUDITOR_URL)")
    if docker_ok:
        dbs = {d["service"]: d for d in ctx.frame_db_services()}
        es = dbs.get(f"{name}-es-db")
        if es:
            r = _sp.run(["docker", "exec", es["service"], "psql", "-U", es["user"], "-d", es["db"], "-tAc",
                         "SELECT (SELECT count(*) FROM cross_frame_peers)||'|'||(SELECT count(*) FROM foreign_events)||'|'||(SELECT count(*) FROM events)"],
                        capture_output=True, text=True, timeout=30)
            if r.returncode == 0 and "|" in r.stdout:
                peers, foreign, events = r.stdout.strip().split("|")
                row("replication", "ok" if int(peers) > 0 else "warn", f"cross-frame peers={peers} foreign_events={foreign} events={events}" + ("" if int(peers) else " (no peer: standalone or not yet federated)"))
            else:
                row("replication", "not-measured", (r.stderr or "").strip()[-80:] or "psql answered nothing")
        else:
            row("replication", "not-measured", "the event-store database is not named by the env or the container")
    prom = (_os.environ.get("TP_PROMETHEUS_URL") or "http://127.0.0.1:9090").rstrip("/")
    st, tg, _h = _get(f"{prom}/api/v1/targets", 20)
    if st == 200 and isinstance(tg, dict):
        row("scrape-targets", *targets_verdict((tg.get("data") or {}).get("activeTargets"), name))
    else:
        row("scrape-targets", "not-measured", f"{prom}/api/v1/targets: http-{st} (TP_PROMETHEUS_URL names the host's Prometheus)")
    st, ps_, _h = _get(f"{base}/public/status", 90)
    if st == 200 and isinstance(ps_, dict):
        own = [c for c in ps_.get("components", []) if c.get("group") == "core"]
        with_job = [c for c in own if c.get("job")]; known = [c.get("days_known", 0) for c in own]
        row("status-history", "ok" if own and len(with_job) == len(own) and all(k >= 1 for k in known) else ("warn" if own else "not-measured"),
            f"own components {len(own)}, with a job {len(with_job)}, known days {known}")
    else:
        row("status-history", "not-measured", f"/public/status http-{st}")
    roots, polls = [], 0.0
    try:   # /metrics whole; the gauge is exported per worker process (MAX is the bundle); the watcher polls every 30 min
        with _ur.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=timeout_or(20)) as r:
            for line in r.read().decode().splitlines():
                if line.startswith("registry_svid_bundle_roots ") or line.startswith("registry_svid_bundle_roots{"):
                    roots.append(float(line.split()[-1]))
                elif line.startswith("registry_svid_polls_total"):
                    polls += float(line.split()[-1])
    except Exception:  # noqa: BLE001
        pass
    n = int(max(roots)) if roots else 0
    if n >= 1:
        row("bundle-roots", "ok", f"{n} root(s) in the registry's trust bundle (1 = standalone, one more per federated peer; {len(roots)} worker sample(s))")
    elif roots and polls == 0:
        # WARMING, not broken: the watcher's first poll comes 30 minutes after boot (measured: juice at 10 min and the
        # sandbox pair 20 min after a roll read 0 with no poll; EU at 26 h read 4 with 52 polls). A verdict needs the state.
        row("bundle-roots", "not-measured", "the SVID watcher has not completed its first poll since boot (30-minute cadence): the bundle is unread, not empty")
    elif roots:
        row("bundle-roots", "fail", f"0 roots after {int(polls)} poll(s): the watcher polls and holds no trust root — verify against peers cannot succeed")
    else:
        row("bundle-roots", "not-measured", "registry_svid_bundle_roots not exported")
    envs = {k: bool(ctx.env.get(k)) for k in ("PROMETHEUS_URL", "VICTORIA_METRICS_URL")}
    row("observability-env", "ok" if all(envs.values()) else "warn", ", ".join(f"{k}={'set' if v else 'unset'}" for k, v in envs.items()) + ("" if all(envs.values()) else " (unset = no status history / degradation panel not configured; the standup writes them under --wire-prod)"))
    return {"schema_version": __schema_version__, "cli_version": __version__, "kind": "frame", "frame": name, "hostname": socket.gethostname(),
            "verdict": ("fail" if any(c["verdict"] == "fail" for c in checks) else "warn" if any(c["verdict"] == "warn" for c in checks) else "ok"),
            "checks": checks}


def register(app, state, load_contexts, run_with_audit):
    @app.command(name="doctor", help="Comprehensive diagnostic (paste in support tickets). With --frame: the read-only frame checks (rails, posture, hashes, delta, auditor, scrape targets, history).")
    def doctor_cmd():
        out = Output(detect_output_mode(state.json_mode, state.quiet, state.no_color))
        contexts = load_contexts()
        results = [run_with_audit("doctor", ctx.name, _diagnose_frame if ctx.is_frame else _diagnose, ctx) for ctx in contexts]
        if out.mode == "json":
            out.emit_json(results[0] if len(results) == 1 else {"operators": results})
        else:
            for r in results:
                who = r.get("frame") or r.get("operator")
                out.line(f"\n[bold]tp-operator doctor[/] — {who} on {r['hostname']}  (cli {r['cli_version']}{', verdict ' + r['verdict'] if r.get('verdict') else ''})")
                if r.get("kind") == "frame":
                    out.table("frame checks", ["CHECK", "VERDICT", "RESULT"], [[c["check"], c["verdict"], c["result"]] for c in r["checks"]])
                else:
                    out.table("diagnostics", ["CHECK", "RESULT"], [[c["check"], c["result"]] for c in r["checks"]])
        raise typer.Exit(code=0)
