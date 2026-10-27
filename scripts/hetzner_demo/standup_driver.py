#!/usr/bin/env python3
"""
Hetzner Frame LIVE-DEMO standup driver (host-side; NO image rebuild involved).
Plan: sessionlogs2026/STRATEGY_2026-07-26_HETZNER_FRAME_LIVE_DEMO.md

STATUS: UNTESTED until R1 (host load must be sane; FE session owns builds).
R1 must verify: issuance emit lands in ES (canary), inline-env upserts render valid
YAML, ES/TEG port publishing, cloud-op Beat B preconditions, first-boot timing.

Design rules honored:
  * Never edits shared templates — renders via services/frame_test_provisioner,
    then mutates ONLY the rendered copies in the per-run stack dir.
  * Every text mutation is anchored + match-count-asserted (abort on 0 or >1).
  * NO personal data in defaults (tests run as admin@hetzner-frame.dev).
  * EMISSION GATE before any issuance the audience sees: ES + Redpanda + TEG health,
    then a 1.0-unit canary issuance whose TokensIssued MUST appear in the frame's
    own EventStore and whose supply-audit MUST read delta=0 — else HARD ABORT.
    (Commander directive 2026-07-26: outbox confirmed BEFORE issuance, otherwise
    the first issuance itself creates a breach on the demo frame.)
"""
import argparse
import base64
import importlib.util
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from decimal import Decimal

# §HELLOFRAME (2026-09-18): the checkout this driver reads its templates and the provisioner from. On this host it is
# this checkout; on a stranger's host it is the export's root (frame-up sets FRAME_REPO_ROOT for every module).
REPO = os.getenv("FRAME_REPO_ROOT", "/opt/theprotocol/stack/Agentvault2")
SRC = f"{REPO}/AgentVault/agentvault_registry/src/agentvault_registry"
TEMPLATES = f"{REPO}/templates/frame-test"
NGINX_AVAIL = "/etc/nginx/sites-available"
NGINX_ENABLED = "/etc/nginx/sites-enabled"
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("standup_extras", os.path.join(os.path.dirname(os.path.abspath(__file__)), "standup_extras.py"))
_fspec = _ilu.spec_from_file_location("standup_federate", os.path.join(os.path.dirname(os.path.abspath(__file__)), "standup_federate.py"))
federate = _ilu.module_from_spec(_fspec); _fspec.loader.exec_module(federate)   # §ONESHOT P2.1: the `federate` step
_sspec = _ilu.spec_from_file_location("sidecars", os.path.join(os.path.dirname(os.path.abspath(__file__)), "sidecars.py"))
sidecars = _ilu.module_from_spec(_sspec); _sspec.loader.exec_module(sidecars)   # §ONESHOT P2.2: the sidecar manifest
extras = _ilu.module_from_spec(_spec); _spec.loader.exec_module(extras)   # §BATCH10: the one-pass standup steps
_pspec = _ilu.spec_from_file_location("frame_ports", os.path.join(os.path.dirname(os.path.abspath(__file__)), "frame_ports.py"))
frame_ports = _ilu.module_from_spec(_pspec); _pspec.loader.exec_module(frame_ports)   # §FRAMEPROV P1: --allocate-ports
_nspec = _ilu.spec_from_file_location("frame_names", os.path.join(os.path.dirname(os.path.abspath(__file__)), "frame_names.py"))
frame_names = _ilu.module_from_spec(_nspec); _nspec.loader.exec_module(frame_names)   # §TESTBED P0 a: exact frame ownership
_tspec = _ilu.spec_from_file_location("template_shape", os.path.join(os.path.dirname(os.path.abspath(__file__)), "template_shape.py"))
template_shape = _ilu.module_from_spec(_tspec); _tspec.loader.exec_module(template_shape)   # §MTLSHOPS T2: the resume guard
# §SANDBOXSTANDUP 2026-09-03 — parameterised so a SECOND frame can stand up beside the first.
# Every default below is the Hetzner demo's original value, so that path is byte-identical.
# §ONESHOT (2026-09-12): the vhost names, the bundle PEM and the certificate default to THIS frame's
# (`vhost_names(name)`, `/etc/nginx/<name>-spire-bundle.pem`, `/etc/letsencrypt/live/<public host>/`);
# the env overrides stay for the retired hetzner frame's revival. A default naming a frame that no longer
# exists died at the `vhosts` step of every fresh run or wrote the wrong PEM (the scout's finding).
VHOSTS = [v for v in os.getenv("FRAME_VHOSTS", "").split(",") if v.strip()]


def frame_vhosts(name):
    return VHOSTS or list(extras.vhost_names(name).values())


def frame_bundle_pem(name):
    return os.getenv("FRAME_SPIRE_BUNDLE_PEM") or f"/etc/nginx/{name}-spire-bundle.pem"


def frame_tls_cert(public_url):
    host = urllib.parse.urlparse(public_url or "").hostname or ""
    return os.getenv("FRAME_TLS_CERT") or f"/etc/letsencrypt/live/{host}/fullchain.pem"

IMAGE_MAP = {
    # rendered-template image -> prod image (sed on the RENDERED compose only;
    # sandbox keeps its -test images, the FE session's builds are untouched)
    "agentvault2-registry-test:latest": "agentvault2-registry-a:latest",
    "agentvault2-teg-layer-test:latest": "agentvault2-teg-layer:latest",
    "agentvault2-event-store-test:latest": "agentvault2-event-store:latest",
    # cert-writer: only -test variants exist locally (infra glue, 4w old is OK).
    # Left unmapped on purpose; revisit at R1 if SVID writing misbehaves.
}

PORTS = {"registry":     int(os.getenv("FRAME_TEST_PORT_REGISTRY",     "8150")),
         "teg":          int(os.getenv("FRAME_TEST_PORT_TEG",          "8162")),
         "es":           int(os.getenv("FRAME_TEST_PORT_EVENTSTORE",   "8261")),
         "spire_grpc":   int(os.getenv("FRAME_TEST_PORT_SPIRE_GRPC",   "8191")),
         "spire_bundle": int(os.getenv("FRAME_TEST_PORT_SPIRE_BUNDLE", "8465")),
         "nginx_fed":    int(os.getenv("FRAME_TEST_PORT_NGINX_FED",    "30463"))}

# §OPSPIRE — do NOT "fix" the child operator's SPIRE_SERVER_ADDRESS. The template's
# `host.docker.internal` is CORRECT here: the provisioner injects
# `extra_hosts: host.docker.internal:host-gateway` on the op's spire-agent, and with
# that mapping the address resolves to 172.17.0.1 and :8191 connects fine (verified
# from inside cloud-op-op-demo_operator-net). An op spire-agent crash-looping on
# "failed to dial host.docker.internal:8191 … authentication handshake failed" is
# NOT an address problem — the gRPC dial deadline is the SYMPTOM and the truncated
# tail is the cause: `x509: certificate signed by unknown authority`, i.e. a STALE
# spire-agent-data volume making it verify the new frame's SVID against a dead
# frame's CA. Fix the volume (see teardown), not the address.


# §FRAMEPROV P1 (2026-09-13): machine-readable output for the admin UI's runner. `--plan` prints ONE JSON document on
# stdout, so the log goes to stderr in that mode; `--progress-file` records every step boundary as a JSON line, and a
# refusal records itself before the process exits.
LOG_TO_STDERR = False
PROGRESS = None        # a Progress when --progress-file (or the stack dir) gives one
_PLAN_REFUSALS = None  # not None while plan() collects refusals instead of exiting


class PlanRefusal(Exception):
    """die() inside plan(): the sentence is collected, the process goes on."""


def log(msg):
    print(f"[standup] {msg}", file=sys.stderr if LOG_TO_STDERR else sys.stdout, flush=True)


def die(msg, code=1):
    if _PLAN_REFUSALS is not None:
        raise PlanRefusal(str(msg))
    print(f"[standup] FATAL: {msg}", file=sys.stderr, flush=True)
    if PROGRESS is not None:
        PROGRESS.fail(str(msg))
    sys.exit(code)


class Progress:
    """§FRAMEPROV P1: one JSON object per line, appended: {ts, step, event: start|end|skip|fail|live, verdict, sentence}.
    Sentences are the driver's own refusal text, truncated; the live record carries addresses only, never a secret."""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.current = None
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def emit(self, step, event, verdict="", sentence="", **extra):
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "step": step, "event": event}
        if verdict:
            record["verdict"] = verdict
        if sentence:
            record["sentence"] = str(sentence)[:600]
        record.update(extra)
        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def start(self, step):
        self.current = step
        self.emit(step, "start")

    def end(self, verdict="ok"):
        if self.current is not None:
            self.emit(self.current, "end", verdict)
            self.current = None

    def skip(self, step, reason):
        self.emit(step, "skip", sentence=reason)

    def fail(self, sentence):
        self.emit(self.current or "run", "fail", "refused", sentence)
        self.current = None


def load_provisioner():
    os.environ.setdefault("FRAME_TEST_TEMPLATE_DIR", TEMPLATES)
    # §SANDBOXSTANDUP 2026-09-03 — the module is loaded BY PATH, so it has no package context, but it
    # does an absolute `from agentvault_registry.core import operator_mail` (added in the V0171-era
    # reality sync, i.e. AFTER the July Hetzner runs). Without the package root on sys.path the driver
    # dies at import and never reaches a single stage. operator_mail pulls only stdlib, so putting
    # .../src on the path costs nothing and needs no Settings.
    pkg_root = os.path.dirname(SRC)          # .../AgentVault/agentvault_registry/src
    if pkg_root not in sys.path:
        sys.path.insert(0, pkg_root)
    path = f"{SRC}/services/frame_test_provisioner.py"
    spec = importlib.util.spec_from_file_location("frame_test_provisioner", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── anchored text mutation helpers ────────────────────────────────────────

def replace_once(text, old, new, label):
    n = text.count(old)
    if n != 1:
        die(f"mutation '{label}': anchor matched {n}x (need exactly 1): {old[:80]!r}")
    return text.replace(old, new, 1)


def upsert_env_line(env_text, key, value):
    """Replace `KEY=...` if present (any value), else append. Idempotent."""
    pat = re.compile(rf"^{re.escape(key)}=.*$", re.M)
    line = f"{key}={value}"
    if pat.search(env_text):
        # a function, not the string: re.sub reads backslashes and group references in a replacement STRING, so a
        # value carrying one (a secret, a JSON document) would be written altered and read back "wrong" (§SHOWCASEPAY)
        return pat.sub(lambda _m: line, env_text, count=1)
    return env_text.rstrip("\n") + f"\n{line}\n"


def svc_anchor(name):
    """NEWLINE-TERMINATED container_name anchor.

    §R1 BUG (caught live): `container_name: <frame>-teg` is a SUBSTRING of
    `container_name: <frame>-teg-db`, and teg-db appears FIRST in the file, so a
    bare `find()` silently injected the TEG's env (incl. the Δ-critical
    TEG_BALANCE_OUTBOX_ENABLED) into the POSTGRES container instead — the
    standing "anchor on strings unique to the target" gotcha. Terminating with
    \\n makes `-teg\\n` unable to match `-teg-db\\n`.
    """
    return f"container_name: {name}\n"


# §BATCH3 item 4 / D12 (2026-09-05): a frame compose is TOPOLOGY ONLY — values live in .env.frame-test.
# The template now interpolates ${FT_<SVC>_<KEY>} for every value (V0221 D12), so a driver that rewrote
# `KEY: ${FT_REG_KEY}` into `KEY: https://literal` was undoing D12 one key at a time (measured on the
# live sandbox pair: FRAME_CURRENCY / PUBLIC_URL literals in the rendered composes). Rule: when the
# rendered compose already interpolates a key, the LITERAL goes to the env file under that variable
# and the compose line is left alone; an interpolation as the new value (`${TEG_TOKEN_SIGNING_KEY}`) is
# topology and still lands inline; a key the template lacks is added as an interpolation plus its env
# line. Redirects queue here and mutate_rendered flushes them after the compose pass.
PENDING_ENV_REDIRECTS = []
_INTERP_VALUE = re.compile(r'^"?\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-[^}]*)?\}"?\s*(?:#.*)?$')
_SVC_PREFIX = (("-event-store\n", "ES"), ("-registry\n", "REG"), ("-teg-db\n", "TEGDB"), ("-teg\n", "TEG"),
               ("-registry-db\n", "DB"), ("-db\n", "DB"), ("-redis\n", "REDIS"), ("-spire-server\n", "SPIRE"),
               ("-spire-agent\n", "SPIREAGENT"), ("-nginx\n", "NGINX"))


def env_value_for(value):
    """A YAML-quoted inline value ("true") becomes the bare env value (true); a value carrying
    double quotes (JSON) is single-quoted so the .env parser takes it literally."""
    v = str(value)
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"' and '"' not in v[1:-1]:
        return v[1:-1]
    if '"' in v and "'" not in v:
        return "'" + v + "'"
    return v


def service_prefix(service_anchor):
    for suffix, pfx in _SVC_PREFIX:
        if service_anchor.endswith(suffix):
            return pfx
    return None


def flush_env_redirects(env_text):
    """Write every queued (VAR, value) into the env text, once, and clear the queue."""
    global PENDING_ENV_REDIRECTS
    for var, value in PENDING_ENV_REDIRECTS:
        env_text = upsert_env_line(env_text, var, env_value_for(value))
    n = len(PENDING_ENV_REDIRECTS)
    PENDING_ENV_REDIRECTS = []
    if n:
        log(f"D12: {n} value(s) redirected to the env file (compose keeps its ${{FT_*}} interpolations)")
    return env_text


def upsert_inline_env(compose_text, service_anchor, key, value, must_exist=None):
    """Upsert `      KEY: value` inside ONE service's environment block.
    service_anchor MUST be newline-terminated + unique (see svc_anchor)."""
    n_anchor = compose_text.count(service_anchor)
    if n_anchor != 1:
        die(f"inline-env: anchor matched {n_anchor}x (need exactly 1): {service_anchor!r}")
    ai = compose_text.find(service_anchor)
    if ai < 0:
        die(f"inline-env: service anchor not found: {service_anchor!r}")
    head, tail = compose_text[:ai], compose_text[ai:]
    # bound the service block: until the next top-level service (two-space key) after anchor
    m_next = re.search(r"\n  [A-Za-z{][^\n]*:\s*\n", tail[1:])
    block_end = (1 + m_next.start()) if m_next else len(tail)
    block, rest = tail[:block_end], tail[block_end:]
    kv_pat = re.compile(rf"^(\s+){re.escape(key)}:\s.*$", re.M)
    n = len(kv_pat.findall(block))
    if n > 1:
        die(f"inline-env: key {key} matched {n}x in service block")
    new_is_interp = _INTERP_VALUE.match(str(value)) is not None
    if n == 1:
        cur = kv_pat.search(block).group(0).split(":", 1)[1].strip()
        m_cur = _INTERP_VALUE.match(cur)
        if m_cur and not new_is_interp:
            # D12: the compose already interpolates this key — the literal belongs in the env file
            PENDING_ENV_REDIRECTS.append((m_cur.group(1), value))
            return compose_text
        block = kv_pat.sub(rf"\g<1>{key}: {value}", block, count=1)
    else:
        if must_exist:
            die(f"inline-env: expected existing key {key} in block, none found")
        env_anchor = "\n    environment:\n"
        if env_anchor not in block:
            die(f"inline-env: no environment: block near {service_anchor!r}")
        pfx = service_prefix(service_anchor)
        if pfx and not new_is_interp:
            # D12: a key the template lacks is added as an interpolation + its env line, never a literal
            var = f"FT_{pfx}_{key}"
            PENDING_ENV_REDIRECTS.append((var, value))
            block = block.replace(env_anchor, env_anchor + f"      {key}: ${{{var}}}\n", 1)
        else:
            block = block.replace(env_anchor, env_anchor + f"      {key}: {value}\n", 1)
    return head + block + rest


def ensure_host_port(compose_text, service_anchor, mapping):
    """Ensure the service publishes `mapping` (e.g. '127.0.0.1:8150:8000').
    If a ports: block exists in the service block, append the mapping if absent;
    else create the block right after container_name."""
    if mapping in compose_text:
        return compose_text
    n_anchor = compose_text.count(service_anchor)
    if n_anchor != 1:
        die(f"ensure_port: anchor matched {n_anchor}x (need exactly 1): {service_anchor!r}")
    ai = compose_text.find(service_anchor)
    if ai < 0:
        die(f"ensure_port: anchor not found: {service_anchor!r}")
    head, tail = compose_text[:ai], compose_text[ai:]
    m_next = re.search(r"\n  [A-Za-z{][^\n]*:\s*\n", tail[1:])
    block_end = (1 + m_next.start()) if m_next else len(tail)
    block, rest = tail[:block_end], tail[block_end:]
    if re.search(r"^\s{4}ports:\s*$", block, re.M):
        block = re.sub(r"^(\s{4}ports:\s*)$",
                       rf"\g<1>\n      - \"{mapping}\"", block, count=1, flags=re.M)
    else:
        # anchor is newline-terminated, so the inserted block must NOT start with
        # another \n and MUST end with one — otherwise the next key gets welded
        # onto the mapping line ("- \"…\"    restart: unless-stopped") and the
        # YAML dies at parse time.
        block = block.replace(service_anchor,
                              service_anchor + f"    ports:\n      - \"{mapping}\"\n", 1)
    return head + block + rest


# ── HTTP helpers (stdlib only) ────────────────────────────────────────────

def http(method, url, body=None, headers=None, timeout=20, form=False):
    headers = dict(headers or {})
    data = None
    if body is not None:
        if form:
            data = body.encode() if isinstance(body, str) else body
            headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        else:
            data = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw.decode() or "null")
            except Exception:
                return r.status, raw.decode(errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw or "null")
        except Exception:
            return e.code, raw
    except Exception as e:
        return 0, str(e)


def _registry_boot_probe(name, port):
    """§ONESHOT F3 — a health wait that can only end in a pass is a mask: the registry sat in a gunicorn
    restart loop ("Worker failed to boot", Settings() refusing a value) for five minutes of `HTTP 0` before
    the driver gave up with a sentence about migrations. Read the container's state and its log on every
    miss and REFUSE at once, naming the line the app printed."""
    ok, detail = _h(f"http://127.0.0.1:{port}/health")
    if ok:
        return ok, detail
    st = subprocess.run(["docker", "inspect", f"{name}-registry", "--format", "{{.State.Restarting}} {{.RestartCount}}"],
                        capture_output=True, text=True).stdout.split()
    if len(st) == 2 and (st[0] == "true" or int(st[1]) >= 2):
        logs = subprocess.run(["docker", "logs", "--tail", "200", f"{name}-registry"], capture_output=True, text=True)
        text = (logs.stdout or "") + (logs.stderr or "")
        if "Failed to instantiate Settings" in text or "Worker failed to boot" in text:
            lines = [l.strip() for l in text.splitlines() if "validation error" in l or "value is not" in l or "Field required" in l or "Worker failed to boot" in l]
            die(f"{name}-registry is restart-looping at boot (restarts={st[1]}): {(lines or ['see docker logs'])[0][:220]} — "
                f"the rendered env refuses at import; fix the value, then --resume-stack-dir <dir> --resume-from compose")
    return ok, detail


def wait_for(desc, fn, tries=60, sleep=3):
    for i in range(tries):
        ok, detail = fn()
        if ok:
            log(f"{desc}: OK ({detail})")
            return True
        if i % 10 == 0:
            log(f"{desc}: waiting… ({detail})")
        time.sleep(sleep)
    log(f"{desc}: TIMEOUT")
    return False


def port_free(p):
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex(("127.0.0.1", p)) != 0
    finally:
        s.close()


# ── stages ────────────────────────────────────────────────────────────────

def preflight(args):
    problems, facts = preflight_problems(args)
    if problems:
        for p in problems:
            log(f"PREFLIGHT FAIL: {p}")
        die("preflight failed")
    log(f"preflight OK (load1={facts['load1']}, avail={facts['avail_gib']}GiB, free={facts['free_gb']}GB)")


def preflight_problems(args):
    """The preflight checks, RETURNED (§FRAMEPROV P1: `--plan` reports them, the run refuses on them). Read-only: /proc,
    `docker image|network inspect`, `docker ps`, `ss`, the sidecar manifest, a peer's /health. -> (problems, facts)"""
    problems = []
    for name, p in PORTS.items():
        if not port_free(p):
            problems.append(f"port {p} ({name}) BUSY")
    with open("/proc/loadavg") as f:
        load1 = float(f.read().split()[0])
    if load1 > args.max_load:
        problems.append(f"load1={load1} > {args.max_load} (override --max-load)")
    avail_kb = 0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable"):
                avail_kb = int(line.split()[1])
    if avail_kb < 15 * 1024 * 1024:   # the standing gate (load < 40, >= 15 GB) — was 8 GiB
        problems.append(f"MemAvailable={avail_kb//1024//1024}GiB < 15GiB (the standing build/recreate gate)")
    if not getattr(args, "own_host", False) and not os.path.islink("/host-stack"):
        problems.append("/host-stack symlink missing (ln -sfn /opt/theprotocol/stack /host-stack)")
    if not os.path.isdir(TEMPLATES):
        problems.append(f"templates missing: {TEMPLATES}")
    for img in set(IMAGE_MAP.values()) | {"docker:cli", "alpine/openssl:latest", args.cert_writer_image}:
        rc = subprocess.run(["docker", "image", "inspect", img],
                            capture_output=True).returncode
        if rc != 0:
            problems.append(f"image missing: {img}")
    try:   # this frame's containers by their compose project label (a frame `a` is not `a-b`), §TESTBED P0 a
        mine = frame_names.frame_resources(args.name, getattr(args, "stack_root", None), kinds=("containers",))["containers"]
    except Exception as exc:  # noqa: BLE001 — an unreadable docker is a refusal, never a pass
        mine = [f"(docker did not answer: {exc})"]
    if mine:
        problems.append(f"containers of a frame named '{args.name}' already exist ({', '.join(mine[:3])}"
                        f"{', ...' if len(mine) > 3 else ''}): teardown first")
    # §BATCH5 (2026-09-05): the operator port range (--cloud-port-base, 100 ports per operator: base+0 registry, +43
    # federation, +80 teg) must have at least TWO free blocks on the HOST. Two sandbox frames were both handed the default
    # base and the second could never provision an operator ("port range exhausted (beta limit: 2)") — measured on JUICE.
    _busy = set()
    for _o in subprocess.run(["ss", "-Hltn"], capture_output=True, text=True).stdout.splitlines():
        try: _busy.add(int(_o.split()[3].rsplit(":", 1)[1]))
        except Exception: pass
    _free_blocks = [b for b in range(args.cloud_port_base, args.cloud_port_base + 300, 100) if not any((b + off) in _busy for off in (0, 43, 80))]
    if len(_free_blocks) < 2:
        problems.append(f"operator port range {args.cloud_port_base}-{args.cloud_port_base + 299} has {len(_free_blocks)} free block(s) on the host — every frame needs its OWN --cloud-port-base (>= 2 free blocks)")
    cert = frame_tls_cert(args.public_url)
    if args.enable_vhost and not os.path.exists(cert):
        if getattr(args, "acme", False):
            log(f"preflight: cert {cert} not present yet — issued during the run (--acme); DNS is checked there")
        else:
            problems.append(f"cert missing: {cert}")
    # ── §ONESHOT P2.4 (2026-09-12) — the runbook's PREFLIGHT-CANDIDATE rows, as checks that name the fix ──
    import shutil
    _free_gb = shutil.disk_usage("/").free // (1024 ** 3); _min_free = int(os.getenv("FRAME_MIN_FREE_GB", "60"))
    if _free_gb < _min_free:
        problems.append(f"disk: {_free_gb} GB free on / < {_min_free} GB (FRAME_MIN_FREE_GB) — a frame is two images, "
                        f"eight volumes and a ledger; clean images BY ID against the protected set first "
                        f"(scratchpad/.diskcleanup_prep_20260908/ holds the census shape), never `docker system prune`")
    _running = subprocess.run(["docker", "ps", "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    _sim = [x for x in _running if "eigentrust-sim" in x]
    if _sim and getattr(args, "posture", "") == "production":
        problems.append(f"the sim is running ({_sim[0]}) — runbook §0.6: no eigentrust-sim during a production standup; stop it from the FE first")
    elif _sim:
        log(f"preflight: the sim is running ({_sim[0]}) — a sandbox standup goes on; the load gate is what protects the box")
    if getattr(args, "identity_net", None) and getattr(args, "identity_net_external", False):
        if subprocess.run(["docker", "network", "inspect", args.identity_net], capture_output=True).returncode != 0:
            problems.append(f"identity net {args.identity_net} does not exist — it is created BEFORE the first frame and every "
                            f"member declares it (runbook §10.1): docker network create {args.identity_net}")
    if getattr(args, "posture", "sandbox") == "production":   # (spelled apart from build_ctx's relay check, which a test anchors on)
        for _img in (args.registry_image, args.teg_image, args.es_image):
            if str(_img).endswith(":latest"):
                problems.append(f"{_img}: `:latest` is the last local build of ANY session, not a promotable image — name a "
                                f"tag built from a clean checkout and boot-gated (runbook §9.0)")
    _wired, _only = wiring(args)
    if _wired:
        try:
            _m = sidecars.load()
            for _p in sidecars.require(_m, need_apex=bool((_m.get("apex") or {}).get("vhosts")), only=_only):
                problems.append(f"{'--wire-prod' if _only is None else '--wire-only'}: {_p}")
        except sidecars.SidecarsMissing as _e:
            problems.append(str(_e))
    for _pd in (getattr(args, "federate_with", None) or []):
        try:
            _pf = federate.frame_facts(_pd)
        except Exception as _e:  # noqa: BLE001 — the sentence is the point
            problems.append(f"--federate-with {_pd}: not a stack this driver stood up ({type(_e).__name__}: {str(_e)[:90]})")
            continue
        _hc = federate._code(f"{federate.base(_pf)}/health")
        if _hc != 200:
            problems.append(f"--federate-with {_pf['name']}: its registry at 127.0.0.1:{_pf['registry_port']} answers {_hc}, not 200 — "
                            f"stand the peer up (or resume it) before federating with it")
        if _pf.get("td") == args.trust_domain:
            problems.append(f"--federate-with {_pf['name']} carries this frame's own trust domain {args.trust_domain}")
    try:
        _aio_max = int(open("/proc/sys/fs/aio-max-nr").read()); _aio_nr = int(open("/proc/sys/fs/aio-nr").read())
        if _aio_max - _aio_nr < 22000:   # two redpandas' worth of slots (~11k each, runbook row 41)
            problems.append(f"fs.aio-max-nr={_aio_max} leaves {_aio_max - _aio_nr} AIO slots and every redpanda needs ~11k — "
                            f"raise it (/etc/sysctl.d/99-theprotocol-aio.conf: fs.aio-max-nr = 1048576; sysctl --system)")
    except (OSError, ValueError):
        log("preflight: /proc/sys/fs/aio-* unreadable — the AIO ceiling was NOT checked")
    return problems, {"load1": load1, "avail_gib": avail_kb // 1024 // 1024, "free_gb": _free_gb}


# core/mainframe_gate.is_mainframe's builtin allowlist, mirrored for the check below (a test pins the two against each
# other): the gate allows a REGISTRY_NAME in this list or in MAINFRAME_REGISTRY_NAMES, AND'd with IS_CENTRAL_REGISTRY=true
MAINFRAME_BUILTIN_NAMES = ("registry-a", "frame-b", "frame-c", "registry-test", "registry-test-b", "registry-test-c")


def mainframe_identity_problems(environment):
    """§FRAMEPROV P4 (2026-09-13): the issuance and operator provisioning gate's rule, asked of the environment a registry
    PROCESS will see. Measured on plum: REGISTRY_NAME="Plum Proof" with MAINFRAME_REGISTRY_NAMES=plum booted, passed every
    health check and refused its own canary issuance with 503 at the emission step. Returns the refusals; [] means allowed."""
    if isinstance(environment, list):   # compose's list form, KEY=VALUE
        environment = dict(item.split("=", 1) for item in environment if "=" in item)
    env = environment or {}
    problems = []
    if str(env.get("IS_CENTRAL_REGISTRY", "false")).lower() != "true":
        problems.append(f"IS_CENTRAL_REGISTRY is {env.get('IS_CENTRAL_REGISTRY')!r}, not true")
    name = str(env.get("REGISTRY_NAME") or "").lower()
    listed = tuple(n.strip().lower() for n in str(env.get("MAINFRAME_REGISTRY_NAMES") or "").split(",") if n.strip())
    if name not in MAINFRAME_BUILTIN_NAMES + listed:
        problems.append(f"REGISTRY_NAME {env.get('REGISTRY_NAME')!r} is not in MAINFRAME_REGISTRY_NAMES "
                        f"{env.get('MAINFRAME_REGISTRY_NAMES')!r}")
    return problems


# ── §TESTBED (2026-09-19): a SANDBOX that runs the MCP/API tester against ITSELF ─────────────────────────────────────
# The suite executes inside whichever registry receives test-flow and reaches every subject container by `docker exec`
# (measured), so a sandbox's own console driving its own registry needs: the fixture accounts (seeded from env
# passwords), the reset secret, the proxy key, its own container names, its own store's address and key, and the socket.
# One set of fixture secrets is shared by a sandbox PAIR (frame-sandbox.py generates it once): the federation suite logs
# into both frames with the same sandbox admin.
TESTER_FIXTURE_SECRET_KEYS = ("SANDBOX_ADMIN_PASSWORD", "SANDBOX_DEVELOPER_PASSWORD", "SANDBOX_TUTORIAL_PASSWORD",
                              "SANDBOX_NON_ADMIN_PASSWORD", "SANDBOX_RESET_SECRET", "API_TEST_PROXY_INTERNAL_KEY")


def new_tester_fixture_secrets():
    """Fresh fixture secrets. Passwords carry an upper, a lower, a digit and a dash (the registration policy's special
    set includes '-'); nothing a .env file or compose interpolation would eat ($, #, quotes)."""
    pw = lambda: secrets.token_urlsafe(18).replace("$", "").replace("#", "") + "-Aa1"   # noqa: E731
    return {"SANDBOX_ADMIN_PASSWORD": pw(), "SANDBOX_DEVELOPER_PASSWORD": pw(), "SANDBOX_TUTORIAL_PASSWORD": pw(),
            "SANDBOX_NON_ADMIN_PASSWORD": pw(), "SANDBOX_RESET_SECRET": secrets.token_hex(32),
            "API_TEST_PROXY_INTERNAL_KEY": secrets.token_hex(32)}


def load_tester_fixture_secrets(path):
    """The fixture secrets of a sandbox SET (frame-sandbox.py writes the file, mode 600); every key present or a refusal."""
    with open(path) as f:
        doc = json.load(f)
    missing = [k for k in TESTER_FIXTURE_SECRET_KEYS if not str(doc.get(k) or "").strip()]
    if missing:
        raise ValueError(f"{path} lacks {', '.join(missing)}")
    return {k: str(doc[k]) for k in TESTER_FIXTURE_SECRET_KEYS}


# §NIGHTPROV (2026-09-27, his words "the frame runner may build sandbox-posture frames at night"): the host sidecar pieces
# a frame is wired into. --wire-prod = every piece (the fleet's frames, unchanged); --wire-only = the named ones. A nightly
# sandbox pair takes sni + bundle: it federates through this host's stream SNI map and its ES vhosts verify the pair's
# roots, while the host's Prometheus, the public auditor, the apex vhosts and the production compose never hear of it.
WIRE_PIECES = ("prometheus", "auditor", "sni", "bundle", "apex", "directory")


def wire_only_pieces(args):
    """The --wire-only set, or None when the flag is not given. Pure."""
    raw = (getattr(args, "wire_only", "") or "").strip()
    return {x.strip() for x in raw.split(",") if x.strip()} if raw else None


def wiring(args):
    """(whether this run wires the frame into the host at all, the `only` set sidecars.wire/require take: None = every
    piece). Pure."""
    if getattr(args, "wire_prod", False):
        return True, None
    only = wire_only_pieces(args)
    return bool(only), only


def wires(args, piece):
    """Whether this run writes the frame's slot in `piece`. Pure."""
    wired, only = wiring(args)
    return wired and (only is None or piece in only)


def tester_self_env(name, es_internal_key, fixture_secrets):
    """The env lines a sandbox's registry needs to run the testers against itself. Pure. The B side of the lifecycle's
    parity walk stays unset here (frame-sandbox.py names the peer of a pair after both frames exist)."""
    lines = [
        ("SEED_TEST_ACCOUNTS", "true"),   # the compose substitutes it into the registry's start command (test_seed)
        ("SANDBOX_ADMIN_EMAIL", "admin@test.sandbox"),
        ("API_TEST_TGT_A_REGISTRY", f"{name}-registry"), ("API_TEST_TGT_A_TEG", f"{name}-teg"),
        ("API_TEST_TGT_A_ES", f"{name}-event-store"), ("API_TEST_TGT_A_ES_DB", f"{name}-es-db"),
        ("API_TEST_TGT_A_INTERNAL_URL", "http://localhost:8000"), ("API_TEST_TGT_A_EXTERNAL_HOST", "http://localhost:8000"),
        ("API_TEST_REG_DB_CONTAINER", f"{name}-db"),
        ("SANDBOX_A_INTERNAL_URL", "http://registry-test:8000"),
        # the target is this registry's own `registry-test` alias, so the derived store would be the retired tier's name:
        # name this frame's store explicitly (§EMITDIAG: a store a probe cannot read is said so, never guessed). A kit
        # store listens only behind its mTLS gateway (nothing on :8200, measured on larchsbx 2026-09-19), which answers
        # the registry's own SVID; the key stays for a store that takes it
        ("API_TEST_EVENT_STORE_URL", f"https://{name}-nginx-event-store:8443"),
        ("API_TEST_EVENT_STORE_API_KEY", es_internal_key),
        # the emission check's handshake probe: the same gateway, verified with this frame's own SPIRE bundle (unset, the
        # check reads NOT MEASURED; a kit frame always has the gateway)
        ("API_TEST_ES_MTLS_GATEWAY_A", f"https://{name}-nginx-event-store:8443"),
        ("API_TEST_SANDBOX_TARGET_HINTS", "registry-test"),
    ]
    lines += [(k, fixture_secrets[k]) for k in TESTER_FIXTURE_SECRET_KEYS]
    return lines


def mutate_rendered(ctx, args):
    env_path = os.path.join(ctx.stack_dir_container, ".env.frame-test")
    compose_path = os.path.join(ctx.stack_dir_container, "docker-compose.frame-test.yml")
    env = open(env_path).read()
    for k, v in [
        ("FRAME_CURRENCY", args.ticker),
        ("IS_CENTRAL_REGISTRY", "true"),
        ("FIRST_ADMIN_EMAIL", args.admin_email),
        ("FIRST_ADMIN_PASSWORD", args.admin_password),
        ("FIRST_ADMIN_NAME", args.admin_name),
        ("PUBLIC_URL", args.public_url),
        ("VERSION", _version_tag(args)),
        ("IMAGE_TAG", args.image_tag),
        ("GENESIS_GRANT_AMOUNT", "1000.0"),
        ("FT_REG_PUSH_NTFY_PUBLIC_URL", args.push_public_url or ""),
        # §HELLOFRAME: the registry card's federation.spire_bundle_endpoint reads SPIRE_BUNDLE_ENDPOINT; without it the
        # card synthesises a well-known path no route serves (Phase 3 measurement 4, shape 2)
        ("SPIRE_BUNDLE_ENDPOINT", (getattr(args, "bundle_public_url", "") or "").strip()),
        # findings row 170 — one flag writes BOTH halves of the discovery strip: this key (which
        # the console's public config publishes as `directory_url`) and the /directory/ proxy lane
        # on the console vhost. Unset ⇒ neither, and the strip honestly does not render.
        # §MTLSGAP (2026-09-08) — the console addresses the index as a REGISTRY path, and the
        # registry dials it over mTLS with its own SVID. Before this it was a plain-http loopback
        # proxy on the console vhost with no identity either end; and because the capability needed
        # three hand-added halves, a clean reprovision removed the whole feature without erroring
        # (§FRAMELIC). A lane that does not exist cannot be forgotten.
        ("FT_REG_DIRECTORY_PUBLIC_URL", "/api/v1/public/directory" if args.directory_upstream else ""),
        ("FT_REG_DIRECTORY_MTLS_URL", args.directory_upstream or ""),
        # findings row 178 — ws_path is CONSOLE-RELATIVE. On its OWN console a frame's ledger is
        # the LOCAL socket `/ws/events`, the same path the FE's local seed uses, so path-dedup
        # collapses the two into ONE tile. Give the frame its own `/ws/events-<self>` lane here
        # instead and the console streams that EventStore twice and draws itself twice — measured
        # on EU. Peers keep their own lane. This is the half the flag's help text promised and
        # the driver did not write: the claim shipped before the code did.
        ("FT_REG_FRESH_NETWORK_JSON", _fresh_network_json(args)),
        ("FT_REG_DISCOVERY_VIA_DIRECTORY", "true" if args.directory_upstream else "false"),
        ("ENABLE_SANDBOX_PROVISIONER_TEST", "false"),
        ("FEDERATION_INTERNAL_SECRET", secrets.token_hex(24)),  # never sandbox's shared secret
        # §MONEY-M3a (R26/R32, 2026-09-03) made these REQUIRED on the TEG with no default —
        # `Settings()` raises `2 validation errors ... avtp_system_api_key / teg_token_signing_key`
        # at import, the TEG never binds :8080, its healthcheck never passes, and because the
        # registry is gated on `teg: service_healthy` the REGISTRY SITS IN `Created` FOREVER.
        # The frame-test template predates that hardening. Generate them per frame; they are the
        # frame's OWN keys and must never be copied from another frame.
        ("TEG_TOKEN_SIGNING_KEY", secrets.token_hex(32)),
        ("TEG_AVTP_SYSTEM_API_KEY", secrets.token_hex(32)),
        # §task1 (2026-07-26) — SAFETY: cloud_provisioner's teardown purge path
        # (`_purge_op_rows_all_frames`) defaults to the PRODUCTION mainframe A/B/C
        # registry+ES DB containers, and the provisioner holds the host docker
        # socket, so a purge=True teardown driven from THIS demo frame would exec
        # psql DELETEs against prod DBs (harmless only because our slug is unique).
        # Pin both lists to the frame's OWN DBs so the demo can never reach out.
        ("TEARDOWN_FRAME_REG_DBS", f"{args.name}-db:registry:frame_test_registry"),
        ("TEARDOWN_FRAME_ES_DBS", f"{args.name}-es-db:eventstore:frame_test_events"),
        # §R1 (2026-07-26) — `config.validate_production_config()` runs AT IMPORT and
        # flips to production-mode when BASE_URL is not localhost (which it is here:
        # https://hetzner.theprotocol.cloud). It then HARD-REQUIRES mail config, and
        # — because we also set IS_CENTRAL_REGISTRY=true for the mint/provision gates —
        # FEDERATION_HEALTH_CHECK_SECRET. Missing either = ValueError at import =
        # registry crash-loop (same class as the §V0160 ALLOWED_ORIGINS gotcha, which
        # we already satisfy with an explicit origin). The frame IS production-shaped,
        # so satisfy the requirements rather than weakening BASE_URL.
        # §R1 — `core/mainframe_gate.is_mainframe()` is a NAME ALLOWLIST AND'd with IS_CENTRAL_REGISTRY. The allowlist is
        # not written here any more: §FRAMEPROV P4 (2026-09-13) measured this bare line shadowed by the compose's
        # `MAINFRAME_REGISTRY_NAMES: ${FT_REG_MAINFRAME_REGISTRY_NAMES}` (an environment block beats env_file), so no
        # process ever read it. The provisioner renders FT_REG_MAINFRAME_REGISTRY_NAMES from build_ctx's two names, and
        # mainframe_identity_problems() refuses a resolved compose whose registry the gate would refuse.
        ("FEDERATION_HEALTH_CHECK_SECRET", secrets.token_hex(24)),
        # findings row 181 — MAIL: the REAL relay when one was supplied, and EMPTY when it was
        # not. The old defaults named `mailpit:1025` and `noreply@<frame>.dev`: a host that does
        # not resolve from the frame's own network and an address nobody owns. Nothing errored,
        # because nothing tried — a frame can hold a mail configuration for a day and only
        # discover it is fiction when the first registrant gets no mail (row 173, measured on
        # EU and ASIA). An EMPTY MAIL_SERVER is the honest state for a mail-less frame: it makes
        # the absence visible to battery leg 15 and to `email_utils`, instead of dressing it up
        # as a working relay. `--posture production` now refuses a standup with no relay at all.
        ("MAIL_SERVER", os.getenv("FRAME_MAIL_SERVER", "") or os.getenv("DEMO_MAIL_SERVER", "")),
        ("MAIL_PORT", os.getenv("FRAME_MAIL_PORT", "") or os.getenv("DEMO_MAIL_PORT", "587")),
        ("MAIL_USERNAME", os.getenv("FRAME_MAIL_ADDRESS", "")),
        ("MAIL_PASSWORD", os.getenv("FRAME_MAIL_TOKEN", "")),
        # the ENVELOPE SENDER must be an address the relay's credential owns, so it follows the
        # supplied identity; only a mail-less frame falls back to its own name (and then sends
        # nothing anyway). The FRAME's identity travels in MAIL_FROM_NAME, never in the sender.
        # §ONESHOT F3 (2026-09-12): the mail-less fallback was `noreply@<name>.invalid` (§FRAMELIC row 181,
        # "unroutable by construction") and email-validator 2.3.0 in the image REFUSES `.invalid` as a
        # special-use name, so Settings() raised and the registry restart-looped on every mail-less standup
        # since 09-07 — nobody ran one until the §ONESHOT proof pair. RFC 2606's `.example` is equally
        # unroutable AND accepted by the validator (probed in the V0351 image: .invalid/.test/.local/.localhost
        # rejected, .example accepted). MAIL_SERVER stays EMPTY: that is where the honesty lives.
        ("MAIL_FROM", os.getenv("FRAME_MAIL_ADDRESS", "") or f"noreply@{args.name}.example"),
        # §ONESHOT (2026-09-12): the DECLARED mail-less shape (V0352 `MAIL_DISABLED`). The registry's
        # production validator refused a public frame with no SMTP and no relay, so the honest empty
        # MAIL_SERVER above had never booted a frame; now the frame says what it is.
        ("MAIL_DISABLED", "false" if all([os.getenv("FRAME_MAIL_SERVER", ""), os.getenv("FRAME_MAIL_ADDRESS", ""), os.getenv("FRAME_MAIL_TOKEN", "")]) else "true"),
        ("MAIL_STARTTLS", "true" if os.getenv("FRAME_MAIL_SERVER", "") else "false"),
        ("MAIL_SSL_TLS", "false"),
        # §LANTERNT3 (2026-09-16) — THE RELAY A FRAME HANDS ITS OWN OPERATORS.
        # `MAIL_*` above is the frame's own relay. What an operator provisioned through the frame's
        # Operator Management rail inherits is `OPERATOR_MAIL_*`, read by
        # core/operator_mail.shared_identity() inside the REGISTRY container at cloud-provision time —
        # different variables entirely. Measured 2026-09-16: 0 of 4 required OPERATOR_MAIL_* set on
        # lantern, eu AND asia, and the template rendered none, so shared_identity() returns None on
        # every frame we run. That is not a lockout (mail_env_lines makes the §OPGUIDE-2 shape
        # unrepresentable: no relay => REQUIRE_EMAIL_VERIFICATION=false and invite codes FORCED), but it
        # does mean a frame-provisioned operator is born invite-only and mail-less while the four live
        # EU/ASIA operators — provisioned by this driver, not by that rail — run open with a working
        # relay. Same values, ALL-OR-NOTHING: a mail-less frame writes them empty so shared_identity()
        # reads absent rather than half-configured, which it warns about and refuses anyway.
        ("OPERATOR_MAIL_SERVER", os.getenv("FRAME_MAIL_SERVER", "")),
        ("OPERATOR_MAIL_PORT", os.getenv("FRAME_MAIL_PORT", "") or "587"),
        ("OPERATOR_MAIL_USERNAME", os.getenv("FRAME_MAIL_ADDRESS", "")),
        ("OPERATOR_MAIL_PASSWORD", os.getenv("FRAME_MAIL_TOKEN", "")),
        ("OPERATOR_MAIL_FROM", os.getenv("FRAME_MAIL_ADDRESS", "")),
        ("OPERATOR_MAIL_FROM_NAME", args.frame_label or "TheProtocol"),
        ("OPERATOR_MAIL_STARTTLS", "true" if os.getenv("FRAME_MAIL_SERVER", "") else "false"),
        ("OPERATOR_MAIL_SSL_TLS", "false"),
        # ── §FLAG-TRANSPORT (2026-07-26, Commander: "look for flags you have not
        # transported to the new frame; frame-c has the most") — every key below is
        # present on the LIVE sovereign frame-c but absent from the ephemeral
        # frame-test template, and is safe + meaningful for a standalone frame.
        # Deliberately NOT transported (and why) is documented in the plan §18:
        #   EXCHANGE_*/FX_*/TREASURY_MM  → AGORA + cross-frame; off for crypto-hygiene
        #   ZKP_*/FORGE_*/EVALS_*  → need sidecars/arena infra we don't ship
        #   OPA_* → SHIPPED since §SOVKIT (2026-09-14): the template carries the frame's own OPA sidecar and the
        #     three OPA_* keys (shadow); nothing here transports them from a production node any more
        #   CANARY_*/COMMAND_RELAY/CROSS_FRAME_* → need peers; frame is standalone
        #   AGENT_RBAC_MODE/AGENT_DELEGATION_MODE=enforce → would DENY fresh demo
        #     agents (legacy-full backfill only covers pre-mig-0107 agents)
        #   API_TEST_EXECUTION_ENABLED/SANDBOX_BYPASS_RATE_LIMIT → prod stance is OFF
        #   TEG_MTLS_REQUIRED → frame-c fronts its TEG with an `nginx-teg` mTLS
        #     sidecar that this template has NO equivalent of; setting it without the
        #     sidecar would reject every registry→TEG call. See plan §18.
        ("REGISTRY_SIGNING_KEY_PASSPHRASE", secrets.token_urlsafe(32)),
        ("REGISTRY_SIGNING_KEY_REQUIRE_ENCRYPTION", "true"),
        ("TWO_FACTOR_ENCRYPTION_KEY", base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()),
        ("MINT_PROXY_SECRET", args.mint_proxy_secret),
        ("TEG_MINT_REQUIRE_PROXY", "true"),
        ("TEG_BALANCE_OUTBOX_ENABLED", "true"),
        # §OPSPIRE — `cloud_provisioner.py` copies THIS registry's SPIRE_SERVER_*
        # verbatim into every child operator's agent.conf. Left at the template's
        # sandbox default (host.docker.internal) the child's spire-agent crash-loops
        # on dial, cert-writer never starts, and its registry sits in `Created`
        # forever. Live ops use the public edge (op-berlin → spire.theprotocol.cloud
        # :8444) from the same kind of isolated operator-net, so we do the same.
        ("MCP_AUDIT_LOGGING_ENABLED", "true"),
        ("FEDERATION_INGEST_FAIL_CLOSED", "true"),
        ("FEDERATION_CARD_GC_ENABLED", "true"),
        ("FEDERATION_LICENSE_ROTATE_SELF_ENABLED", "true"),
        ("REGISTRY_ADMISSION_ENABLED", "true"),
        ("REGISTRY_ADMISSION_CLIENT_LIMIT", "6"),
        ("REGISTRY_ADMISSION_INTERNAL_LIMIT", "6"),
        ("REGISTRY_ADMISSION_RETRY_AFTER", "2"),
        ("REACTOR_HANDLER_CONCURRENCY", "100"),
        ("REACTOR_CREDIT_ASYNC_BULK_ENABLED", "true"),
        ("REACTOR_CREDIT_ASYNC_FLUSH_MS", "200"),
        ("REACTOR_POLLING_BACKSTOP_LOOKBACK_SEC", "1800"),
        ("SAGA_ADAPTIVE_CONC_ENABLED", "true"),
        ("SAGA_REFUND_BATCH", "100"),
        ("SAGA_REFUND_CONCURRENCY", "5"),
        ("CAPABILITY_CIRCUIT_BREAKER_ENABLED", "true"),
        ("AGENT_RBAC_DEFAULT_ROLES", "trader,client,staker"),
        ("A2A_SETTLE_VIA_SMART_SEND", "true"),
        ("NOTIFY_V2_MODE", "shadow"),
        ("MAIL_FROM_NAME", args.frame_label),
        # Flagship product surfaces worth having live for the demo
        ("GUILD_ENABLED", "true"),
        ("GUILD_FEE_BPS", "250"),
        ("CONTRACTS_V2_ENABLED", "true"),
        ("CONTRACT_TEMPLATES_ENABLED", "true"),
        # ── §FRAMELIC 2026-09-07 ──────────────────────────────────────────────────────────
        # Row 52: the IMAGE is a value, and D12 says values live in the env file while the
        # compose stays topology. The rendered compose interpolates ${FT_REG_IMAGE}, so a
        # version move on a frame is ONE key, not a compose edit plus two env keys.
        ("FT_REG_IMAGE", args.registry_image),
        ("FT_TEG_IMAGE", args.teg_image),
        ("FT_ES_IMAGE", args.es_image),   # §SOVKIT: the store's image, same shape
        # Row 34: a fresh frame must not load PRODUCTION's canary mTLS map out of the image.
        # The baked `/app/config/canary_mtls_map.mainnet-2026.json` names Frame A's senders;
        # a frame with no cross-frame canary paths needs an EMPTY map, not somebody else's.
        ("CANARY_MTLS_MAP_FILE", "/app/config/canary_mtls_map.frame-local.json"),
        # Row 62: the frame's own face.
        ("FT_REG_VISUAL_THEME", args.theme),
        # Row 66: the limiter is LIVE on a production frame. `--tester-fixtures` is refused
        # on that posture (above), so this is never overwritten to true behind our back.
        ("FT_REG_SANDBOX_BYPASS_RATE_LIMIT", "false" if args.posture == "production" else "true"),
        ("SANDBOX_BYPASS_RATE_LIMIT", "false" if args.posture == "production" else "true"),
        # §FRAMELIC — execution is ON only when a tester console target is named, and then the
        # target is the SANDBOX: this frame drives the tester, it is never the tester's subject.
        ("API_TEST_EXECUTION_ENABLED",
         "true" if (args.tester_console or args.posture != "production") else "false"),
        # §TESTBED P0 h (2026-09-19): the compose maps `API_TEST_EXECUTION_ENABLED: ${FT_REG_API_TEST_EXECUTION_ENABLED}`
        # (row 144's class), so the bare key above never reached the container and a sandbox-posture frame kept execution
        # OFF (measured on the kit template). The carrier the compose reads, with the same rule.
        ("FT_REG_API_TEST_EXECUTION_ENABLED",
         "true" if (args.tester_console or args.posture != "production") else "false"),
        # §TESTBED P1: the frame DECLARES what it is (core/frame_posture.py): a production frame's registry then refuses
        # to execute the test suite even if the execution flag is ever switched on by mistake (the second lock)
        ("FRAME_POSTURE", args.posture),
    # §FRAMELIC (2026-09-07, findings row 144) — a raw key in the env FILE is SHADOWED by the
    # compose `environment:` block for every key the template maps (`API_TEST_TARGET_URL:
    # ${FT_REG_API_TEST_TARGET_URL}`), so writing the bare name silently loses. Write the
    # FT_REG_ carrier the compose actually reads, AND the raw name for anything unmapped.
    ] + ([("FT_REG_API_TEST_TARGET_URL", args.tester_console.rstrip("/")),
          ("FT_REG_API_TEST_EXECUTION_ENABLED", "true"),
          ("API_TEST_TARGET_URL", args.tester_console.rstrip("/")),
          # §FRAMELIC row 136 — the tester's "am I aimed at a sandbox?" predicate is a name list,
          # and a name list goes stale. Name THIS target explicitly rather than hoping the image's
          # default happens to contain it: an unrecognised sandbox loses sandbox-mode request
          # bodies silently, so the run looks fine and tests less.
          ("API_TEST_SANDBOX_TARGET_HINTS",
           urllib.parse.urlparse(args.tester_console).hostname or args.tester_console)]
         # §EMITDIAG 2026-09-07 (his report: "ES query unavailable for
         # A2APaymentAuthorized ... i am sure this is emitted" — it was).
         # A CONSOLE THAT DRIVES ANOTHER FRAME MUST READ *THAT* FRAME'S EVENTSTORE.
         # The sweep executes against --tester-console, so its events land in the
         # TARGET's store, never this frame's. The registry derives the URL from the
         # target (`<prefix>-registry` → `<prefix>-event-store`), but the store's
         # internal key is a SECRET of the target and cannot be derived — without it
         # every poll 403s and all 93 event-types read 'unknown'. Same half-a-
         # capability shape as the FX router flag: the console claimed emission
         # verification while missing the one thing that makes it possible.
         + ([("API_TEST_EVENT_STORE_API_KEY", args.tester_console_es_key)]
            if (args.tester_console_es_key or "").strip() else [])
         + ([("API_TEST_EVENT_STORE_URL", args.tester_console_es_url.rstrip("/"))]
            if (args.tester_console_es_url or "").strip() else [])
         if (args.tester_console or "").strip() else []
    ) + ([("FEDERATION_LICENSE_KEY", args.federation_license_key)]
         if (args.federation_license_key or "").strip() else []
    ) + ([("SHOWCASE_CATALOG_JSON",
           json.dumps(json.loads(open(args.showcase_catalog_json).read()), separators=(",", ":")))]
         if args.showcase_catalog_json else []
    ):
        env = upsert_env_line(env, k, v)
    # The frame kit's standup (agentvault2-56, 2026-10-22; his word: "make sure terms are accepted also on framekit
    # standup. because there an account is issued"): frame-up.py asked the person running it to accept the Federation
    # Operator Terms before anything existed, and passes the acceptance here; the registry's operator_seed records it
    # with the first admin it creates (TheProtocolReleaseV0632 and later). Only frame-up passes it: a frame the network
    # runs carries no such line.
    if (getattr(args, "admin_accepted", "") or "").strip():
        for k, v in [("FIRST_ADMIN_ACCEPTED", args.admin_accepted.strip()),
                     ("FIRST_ADMIN_ACCEPTED_AT", (args.admin_accepted_at or "").strip()),
                     ("FIRST_ADMIN_ACCEPTED_BY", (args.admin_accepted_by or "").strip())]:
            env = upsert_env_line(env, k, v)
    # §FRAMEKIT P3.1 (2026-09-12) — where the frame reads its own observability. PROMETHEUS_URL (the
    # status page's history, eight admin panels) and VICTORIA_METRICS_URL (the degradation panel) come
    # from sidecars/sidecars.json under --wire-prod; without it the template's placeholders stay
    # commented and the frame reports "not configured" instead of dialing a code default that
    # resolves on nobody's network (the flagship: 0 of 90 days on every status component).
    if wires(args, "prometheus"):
        _mlines = sidecars.metrics_env_lines(sidecars.load())
        # §SOVKIT (2026-09-14): the frame ships its OWN Prometheus and the template renders an active
        # PROMETHEUS_URL naming it; the host manifest may add its long-term store (VICTORIA_METRICS_URL) but
        # no longer overwrites the frame's own history source. A frame is sovereign about where it reads itself.
        _own = re.search(r"^PROMETHEUS_URL=(\S+)$", env, re.M)
        if _own:
            _mlines = [(k, v) for k, v in _mlines if k != "PROMETHEUS_URL"]
            log(f"observability: the frame's own PROMETHEUS_URL ({_own.group(1)}) kept; the host manifest adds only the rest")
        for k, v in _mlines:
            env = upsert_env_line(env, k, v)
        log(f"observability addresses from sidecars.json: {', '.join(k for k, _ in _mlines) or 'none (no prometheus.query_url)'}")
    if getattr(args, "tester_self", False):
        _es_key = (re.search(r"^EVENT_STORE_INTERNAL_API_KEY=(\S+)$", env, re.M) or [None, ""])[1]
        if not _es_key:
            die("--tester-self: the rendered env carries no EVENT_STORE_INTERNAL_API_KEY for the tester's store reads")
        _fx = (load_tester_fixture_secrets(args.tester_fixture_secrets) if args.tester_fixture_secrets
               else new_tester_fixture_secrets())
        for k, v in tester_self_env(args.name, _es_key, _fx):
            env = upsert_env_line(env, k, v)
        _sd = getattr(args, "secrets_dir", None) or ""
        if _sd:
            _fp = os.path.join(_sd, f".{args.name}_tester_fixtures.secret.json")
            with open(os.open(_fp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
                json.dump(_fx, f, indent=1)
            os.chmod(_fp, 0o600)
        log(f"tester (self): fixture accounts, reset secret, proxy key, this frame's containers and store"
            f"{' (the set shared from ' + args.tester_fixture_secrets + ')' if args.tester_fixture_secrets else ''}"
            f"; secrets file {'written in ' + _sd if _sd else 'NOT written (no --secrets-dir)'}")
    open(env_path, "w").write(env)
    log("env mutations applied")
    kit_write_auditor_frames(ctx, env, args)

    comp = open(compose_path).read()
    for old, new in IMAGE_MAP.items():
        if old in comp:
            comp = comp.replace(old, new)
            log(f"image: {old} -> {new}")
    reg_anchor = svc_anchor(f"{args.name}-registry")
    es_anchor = svc_anchor(f"{args.name}-event-store")
    comp = ensure_host_port(comp, reg_anchor, f"127.0.0.1:{PORTS['registry']}:8000")
    # §MTLSHOPS T2 (S4, 2026-09-15): the store's host door is the edge's (the template publishes 127.0.0.1:<es>:8200 there)
    for k, v in [
        ("BASE_URL", args.public_url),
        ("PUBLIC_URL", args.public_url),
        # container_name: lines are already rendered with the slug, so overriding
        # the REGISTRY_NAME the PROCESS sees only changes what the signed card
        # publishes ("Hetzner Frame" instead of "hetzner-frame").
        ("REGISTRY_NAME", f'"{args.frame_label}"'),
        ("ALLOWED_ORIGINS", f"'[\"{args.public_url}\"]'"),
        ("FRAME_CURRENCY", args.ticker),
        ("IS_CENTRAL_REGISTRY", '"true"'),
        # §HELLOFRAME (own-host): an operator of a stranger's frame is named under THAT frame's public name, never under
        # our zone (Phase 1 surprise 5), and there is no host nginx for the provisioner to write a vhost into
        # §TESTBED: a SANDBOX's operators are named one label under its PARENT's public name (--operator-domain-suffix),
        # so the one `*.<parent>` record the kit asks for covers them and the parent's edge serves them
        ("CLOUD_DOMAIN_SUFFIX", f'"{args.operator_domain_suffix}"' if (getattr(args, "operator_domain_suffix", "") or "").strip()
                                else f'"{urllib.parse.urlparse(args.public_url).hostname}"' if getattr(args, "own_host", False) else '"op.theprotocol.cloud"'),
        ("SKIP_NGINX_VHOST", '"true"' if getattr(args, "own_host", False) else '"false"'),
        # §HELLOFRAME lane 6 (own-host only; a network frame's compose stays byte-identical): the operator's images come
        # from the export's local tag namespace (no pull token), the operators list probes the host at its public address,
        # and the kit's Prometheus has no host port an operator could reach, so its URL is EMPTY (no history, honestly)
        *([("OPERATOR_IMAGES_PREFIX", f'"{args.operator_images_prefix}"'),
           ("FRAME_STACK_ROOT", f'"{args.stack_root}"'),
           ("CLOUD_OP_HEALTH_HOST_IP", f'"{args.host_public_ip}"'),
           ("OPERATOR_PROMETHEUS_URL", '""')] if getattr(args, "own_host", False) else []),
        # see _free_cloud_port_base(): keep the child operator off ports a stray
        # host process already owns (the allocator only sees docker-published ones)
        ("CLOUD_PORT_MIN", f'"{args.cloud_port_base}"'),
        # §FRAMELIC (2026-09-07, findings row 141) — §BATCH5 widened this from two blocks to three
        # because two was not enough. Three is not enough either: the allocator now legitimately
        # REFUSES a block the daemon has wedged (row 133), and tonight it refused two in a row, so
        # a frame with two operators had one block left and the second operator got
        # "port range exhausted (beta limit: 3)". Blocks are free; a standup that cannot retry is
        # not. Eight by default, and `--cloud-port-span` for a host that needs a different shape.
        ("CLOUD_PORT_MAX", f'"{args.cloud_port_base + args.cloud_port_span - 1}"'),
        ("VERSION", _version_tag(args)),
        ("IMAGE_TAG", args.image_tag),
        # The bilateral peer identity. The frame-test template leaves this as the
        # SANDBOX's ("Sandbox-A"), which is wrong in BOTH places it is read:
        #   • main.py adds BILATERAL_PEER_NAME to `_self_names`, the set used to skip
        #     self-reference echoes in federation topology — so it must be OUR name.
        #   • cloud_provisioner.py seeds the CHILD operator's `peer_registries` row from
        #     (BILATERAL_PEER_NAME, BILATERAL_PEER_URL) — i.e. the child's pointer back
        #     at its parent frame. Frame A's default is "Registry-A" for exactly this
        #     reason: both readings agree only when the value is the frame's OWN name.
        # Blanking the URL is NOT the safe option (I tried it, hence the noise): the op
        # then gets an EMPTY base_url and its federation_sync throws
        # "Request URL is missing an 'http://' or 'https://' protocol" every cycle.
        # And leaving it UNSET is worse still — `REGISTRY_A_PUBLIC_URL` defaults to
        # **https://api.theprotocol.cloud**, so a demo op would peer with PRODUCTION
        # Frame A (same cross-frame contamination class as the EventStore URL).
        ("BILATERAL_PEER_NAME", f'"{args.frame_label}"'),
        ("BILATERAL_PEER_URL", f'"{args.federation_public_url}"'),  # §BATCH5: the mTLS address, never the 443 console
        # standalone frame: no cross-TEG partner (kept empty on purpose)
        ("PARTNER_TEG_URL", '""'),
        # §OPSPIRE — the CHILD operator's EventStore URL. A cloud-op has no ES of its
        # own; its balance outbox + reactors emit to the PARENT frame's ES, so this
        # value has to be reachable from the op's ISOLATED bridge. Two traps:
        #   • the template sets this to the INTERNAL container name
        #     (http://<frame>-event-store:8200). The child inherits it verbatim and
        #     cannot resolve it — measured on the clean run, from the op's OWN
        #     containers: TEG and registry both got "Temporary failure in name
        #     resolution". Silent by construction: the outbox logs its startup, not
        #     the delivery failures.
        #   • leaving it UNSET is WORSE. `_frame_public_es_url()` only maps the three
        #     KNOWN prod trust domains; an unknown one (ours) falls back to
        #     **https://events.theprotocol.cloud — FRAME A's EventStore**. A demo op
        #     would emit financial events into the production ledger (§pass78c
        #     clone-bug class).
        # MUST be set here, in the compose inline `environment:` block: this service
        # also has an env_file, and compose inline env WINS over env_file. Setting it
        # only in .env.frame-test looks applied and silently loses (how this defect
        # survived a green run).
        # §BATCH5 (2026-09-05, his word "fix the driver to not hardcode es url but ask and fail without a fresh one"):
        # the frame's PUBLIC EventStore host is a REQUIRED per-run argument (--es-public-url), validated in main();
        # the demo-day literal that the first JUICE standup inherited (its operators would have emitted into the
        # hetzner ES) is gone. Unset or a production ledger host is a refusal, never a fallback.
        ("EVENT_STORE_PUBLIC_URL", '"' + args.es_public_url + '"'),
    ]:
        comp = upsert_inline_env(comp, reg_anchor, k, v)
    if getattr(args, "tester_fixtures", False):   # §BATCH10 finding 22: the testers' fixture posture behind ONE flag
        for k, v in extras.tester_fixture_env().items():
            comp = upsert_inline_env(comp, reg_anchor, k, f'"{v}"')
        log(f"tester fixtures: {len(extras.tester_fixture_env())} env keys in the registry service")
    comp = upsert_inline_env(comp, es_anchor, "FRAME_CURRENCY", args.ticker)

    # §R1 — THE Δ-CRITICAL ONE. The frame-test template omits
    # `TEG_BALANCE_OUTBOX_ENABLED`, so the TEG's balance outbox never starts and NO
    # `LedgerBalanceChanged` events reach the ES. `TokensIssued` still lands (via the
    # registry/Kafka path), so an issuance drives tokens_issued UP while total_circulating
    # stays 0 ⇒ **delta = issuance amount = an instant supply-invariant BREACH on the
    # frame**. Caught live by the emission gate (issued 0→1, delta 1.0). Every real
    # deployment sets this true (Frame A, frame-c, every cloud-op); only the ephemeral
    # test template lacked it because those frames never issued.
    teg_anchor = svc_anchor(f"{args.name}-teg")
    comp = upsert_inline_env(comp, teg_anchor, "TEG_BALANCE_OUTBOX_ENABLED", '"true"')
    comp = upsert_inline_env(comp, teg_anchor, "FRAME_CURRENCY", args.ticker)
    # R26/R32: required, no default. `${...}` so the value stays in the .env, not the compose.
    comp = upsert_inline_env(comp, teg_anchor, "TEG_TOKEN_SIGNING_KEY", "${TEG_TOKEN_SIGNING_KEY}")
    comp = upsert_inline_env(comp, teg_anchor, "AVTP_SYSTEM_API_KEY", "${TEG_AVTP_SYSTEM_API_KEY}")
    # §FLAG-TRANSPORT — TEG-side parity with live frame-c. MINT_PROXY_SECRET must be
    # the SAME value the registry holds (issuance-proxy lockdown §pass73.3.19: the TEG
    # only accepts an issue from the registry's proxy). NOT transported:
    # TEG_MTLS_REQUIRED (needs the nginx-teg sidecar this stack doesn't have).
    for k, v in [
        ("MINT_PROXY_SECRET", args.mint_proxy_secret),
        ("TEG_MINT_REQUIRE_PROXY", '"true"'),
        ("TEG_HOME_FRAME_GUARD_ENABLED", '"true"'),
        ("ESCROW_RECONCILER_ENABLED", '"true"'),
        ("ESCROW_RECONCILER_DRY_RUN", '"false"'),
        ("TEG_BULK_USE_ASYNC_DB", '"true"'),
    ]:
        comp = upsert_inline_env(comp, teg_anchor, k, v)

    # §FLAG-TRANSPORT — ES-side parity. KNOWN_INTERNAL_SERVICES is NOT written here any more
    # (§ONESHOT F2, 2026-09-12): the template carries the §MTLSGAP-corrected value
    # (`<name>-registry,registry,teg-layer` = the SPIFFE entries the selectors create, T:154) and
    # the D12 redirect used to overwrite it with the compose LABELS this loop derived
    # (`registry-<name>,teg-core-<name>,teg-<name>`) — the exact shape runbook §15 calls wrong.
    # EU/ASIA carried the right value only because it was hand-edited after their standup; the
    # sandbox pair carries the wrong one live. R10 gates the template, not the rendered env.
    for k, v in [
        ("KAFKA_CONSUMER_BATCH_SIZE", '"200"'),
        ("KAFKA_CONSUMER_BATCH_TIMEOUT_MS", '"300"'),
        ("EVENTSTORE_WS_AUTH_REQUIRED", '"false"'),
        ("EVENTSTORE_JWT_AUDIENCE", f"spiffe://{args.trust_domain}/eventstore"),
        ("EVENTSTORE_JWT_JWKS_URL", f"http://{args.name}-registry:8000/api/v1/spire/jwks"),
    ]:
        comp = upsert_inline_env(comp, es_anchor, k, v)
    if ",sandbox-a.test" in comp:
        comp = comp.replace(",sandbox-a.test", "")
        log("TRUSTED_SPIFFE_DOMAINS: dropped sandbox-a.test")
    if getattr(args, "es_mtls_port", 0):
        # §HELLOFRAME (2026-09-18, own-host): the ledger's mTLS gateway gets a HOST port. On this host the ES public URL is a
        # host vhost proxying the loopback store; a stranger's host has no host nginx, so peers (and the frame's own
        # operator) dial nginx-event-store's 8443 directly, verified by SVID as always. One `ports:` block on the
        # existing service, no new service: the template's service set (R31) is unchanged.
        _esgw = f"\n  {args.name}-nginx-event-store:\n"
        _cn = f"    container_name: {args.name}-nginx-event-store\n"
        assert comp.count(_esgw) == 1 and comp.count(_cn) == 1, "the ledger gateway's block was not found exactly once"
        comp = comp.replace(_cn, _cn + f'    ports:\n      - "{int(args.es_mtls_port)}:8443"\n')
        log(f"own-host: nginx-event-store publishes host port {int(args.es_mtls_port)} (the ledger's public mTLS door)")
    open(compose_path, "w").write(comp)
    env = flush_env_redirects(env)
    open(env_path, "w").write(env)

    # Standing doctrine: validate compose with `docker compose config`, NEVER a
    # YAML parser (a parser tolerates duplicate keys Docker rejects). Catches a
    # malformed mutation HERE instead of 90s later as a confusing compose-up
    # failure — which is exactly how the ports-insertion bug surfaced in R1.
    chk = subprocess.run(
        ["docker", "compose", "-f", compose_path, "--env-file", env_path, "config"],
        capture_output=True, text=True)
    if chk.returncode != 0:
        die("post-mutation `docker compose config` FAILED (mutation produced invalid "
            f"compose):\n{(chk.stderr or '')[:600]}")
    log("compose mutations applied + `docker compose config` validated")
    # §FRAMEPROV P4 (2026-09-13): the gate's question asked of the RESOLVED compose, the environment the process will see,
    # never of the env file (a value written to a carrier nobody reads is exactly the defect this refuses).
    resolved = subprocess.run(
        ["docker", "compose", "-f", compose_path, "--env-file", env_path, "config", "--format", "json"],
        capture_output=True, text=True)
    try:
        registry_env = json.loads(resolved.stdout)["services"][f"{args.name}-registry"].get("environment")
    except (ValueError, KeyError, TypeError):
        die(f"the resolved compose has no {args.name}-registry service environment: the mainframe gate was NOT checked")
    problems = mainframe_identity_problems(registry_env)
    if problems:
        die("the registry would refuse its own issuance and operator provisioning (core/mainframe_gate.py): " + "; ".join(problems))
    log(f"mainframe gate: {args.name}-registry carries its REGISTRY_NAME in MAINFRAME_REGISTRY_NAMES, IS_CENTRAL_REGISTRY=true")


LEDGER_ATOMIC_SQL = (
    "SELECT (s.tokens_issued - s.tokens_destroyed + s.transit_net) - "
    "COALESCE((SELECT SUM(liquid_balance + staked_balance) FROM materialized_balances),0), "
    "s.tokens_issued FROM supply_summary s WHERE s.id=1;"
)
LEDGER_EPSILON = Decimal("0.000001")


def _ledger_read(name):
    """The frame's own ledger in ONE statement off its EventStore Postgres (the method the independent auditor uses):
    ((atomic delta, tokens issued) as Decimals, ""), or (None, what the read printed)."""
    r = subprocess.run(
        ["docker", "exec", f"{name}-es-db", "psql", "-U", "eventstore",
         "-d", "frame_test_events", "-tAF,", "-c", LEDGER_ATOMIC_SQL],
        capture_output=True, text=True, timeout=20)
    out = (r.stdout or "").strip()
    if r.returncode != 0 or "," not in out:
        return None, f"psql rc={r.returncode} {(r.stderr or out)[:80]}"
    d_str, issued_str = out.split(",")[:2]
    try:
        return (Decimal(d_str), Decimal(issued_str)), ""
    except ArithmeticError:
        return None, f"unparseable ledger read: {out[:80]}"


def _show_mint_landed(args, issued_before, minted):
    """§FRAMESHOWCASE (2026-09-14): the show issuance is in the frame's own ledger at delta 0. A pass that issued: issued rose
    by exactly what it issued. A pass that issued nothing (an earlier pass did): at least the whole show issuance is issued.
    The two transports land independently, so this waits with the emission gate's patience."""
    def _landed():
        read, detail = _ledger_read(args.name)
        if read is None:
            return False, detail
        delta, issued = read
        if issued_before is None:
            ok = issued >= minted
        else:
            ok = abs((issued - issued_before) - minted) <= LEDGER_EPSILON
        return ok and abs(delta) <= LEDGER_EPSILON, f"issued {issued_before} -> {issued} (this pass {minted}) atomic_delta={delta}"
    if not wait_for("the genesis supply in the frame's ledger (issued up by it, delta 0)", _landed, tries=120, sleep=5):
        die("GENESIS SUPPLY is not in the frame's own ledger at delta 0 (issued did not rise by it, or the delta is not "
            "0); read the frame's supply audit before resuming")
    log("GENESIS SUPPLY is in the frame's own ledger at delta 0")


def emission_gate(args, admin_jwt, mint=True, on_minted=None):
    """Commander directive: confirm registry->ES (Kafka) AND TEG->ES (outbox)
    BEFORE any visible issuance. Canary-issues 1.0 and requires the event + delta=0.

    §FRAMEPROV P1: `mint=False` (a resume after the canary was accepted but before the gate passed) verifies the frame's
    own ledger WITHOUT a second canary: at least 1.0 issued and the atomic delta 0. `on_minted` is called the moment the
    canary answers 200, so the run meta records it even if the wait below dies."""
    reg = f"http://127.0.0.1:{PORTS['registry']}"
    es = f"http://127.0.0.1:{PORTS['es']}"

    if not wait_for("ES /health", lambda: _h(f"{es}/health")):
        die("emission gate: EventStore not healthy")
    # §R1 — the TEG is INTERNAL-ONLY by design; there is no host port to curl. §MTLSHOPS T2 (S4): it listens only on its
    # unix socket (shared with its terminators), so the check asks the socket from inside the container.
    if not wait_for("TEG /health (in-container, its socket)",
                    lambda: _exec_http(f"{args.name}-teg", "http://localhost/health", unix_socket="/sock/teg/teg.sock")):
        die("emission gate: TEG not healthy")
    rp = subprocess.run(["docker", "exec", f"{args.name}-redpanda",
                         "rpk", "cluster", "health"], capture_output=True, text=True)
    if "Healthy:" not in rp.stdout and rp.returncode != 0:
        die(f"emission gate: redpanda unhealthy: {rp.stdout[-200:]}{rp.stderr[-200:]}")
    log("redpanda cluster health OK")

    # §SINGLE-WRITER CUTOVER (§pass73.3.19) — ALL THREE live frames run
    # projection_config.single_writer=true; the fresh-DB default is FALSE. With it
    # false, BOTH the legacy typed handler (TokensIssued) AND the L2 outbox handler
    # (LedgerBalanceChanged) write balances, so every issuance is counted TWICE: a 6.0
    # issuance showed tokens_issued=12.0 and a materialized treasury of 12.0 against a
    # TEG truth of 6.0. It stays Δ-consistent (both sides double) so the invariant
    # still reads 0, but every absolute figure we'd show is 2x reality. Flipping it
    # is the documented cutover and is safe HERE precisely because the frame is
    # brand new: zero history to re-baseline, and the outbox is enabled above.
    sw = subprocess.run(
        ["docker", "exec", f"{args.name}-es-db", "psql", "-U", "eventstore",
         "-d", "frame_test_events", "-tAc",
         "UPDATE projection_config SET single_writer=true, updated_at=NOW() WHERE id=1 "
         "RETURNING single_writer;"],
        capture_output=True, text=True, timeout=30)
    if sw.returncode != 0 or "t" not in (sw.stdout or ""):
        die(f"single_writer cutover FAILED (would double-count every issuance): "
            f"rc={sw.returncode} {(sw.stderr or sw.stdout)[:200]}")
    log("projection single_writer=true (cutover applied — no double-counting)")

    st, base = http("GET", f"{es}/api/v1/projections/supply-audit")
    log(f"supply-audit pre-canary: {st} {base if isinstance(base, str) else json.dumps(base)[:200]}")
    if st != 200 or not isinstance(base, dict):
        die("emission gate: supply-audit unreadable BEFORE the canary — refusing to issue")
    issued_before = float(base.get("tokens_issued") or 0)

    if mint:
        st, r = http("POST", f"{reg}/api/v1/teg/treasury/mint",
                     {"amount": "1.0", "reason": "emission-canary"},
                     headers={"Authorization": f"Bearer {admin_jwt}"}, timeout=60)
        if st != 200:
            die(f"emission gate: canary issuance HTTP {st}: {r}")
        if on_minted is not None:
            on_minted()
        log("canary issuance accepted; verifying it LANDED in the EventStore…")
    else:
        issued_before = 0.0   # the canary landed in an earlier pass: the ledger must hold at least it, at delta 0
        log("canary issued in an earlier pass (run meta): verifying the ledger WITHOUT a second issuance")

    # §R1 — verify via the PUBLIC supply-audit projection rather than the events
    # list (`/api/v1/events` is auth-gated by verify_event_auth and 403s an
    # unauthenticated probe — that 403 says nothing about whether the event
    # landed). Watching `tokens_issued` rise by the canary amount proves the
    # registry→ES emit ACTUALLY landed AND was projected; requiring delta==0 in
    # the same read proves the TEG→ES balance outbox agrees. One check, both
    # transports, no credentials needed.
    # Authoritative check = the ATOMIC single-statement delta straight off the
    # frame's ES Postgres (the method the independent auditor uses). The HTTP
    # /supply-audit reads issued and circulating in TWO separate queries, so it
    # can report a transient non-zero delta that is pure read-skew (documented in
    # CLAUDE.md PART 4). R1 also showed the two halves land minutes apart on a
    # cold frame — the emit is prompt, the balance side is completed by a periodic
    # sync — so the window has to be generous or the gate lies about a healthy frame.
    def _projected():
        read, detail = _ledger_read(args.name)
        if read is None:
            return False, detail
        delta, issued = float(read[0]), float(read[1])
        ok = (issued - issued_before) >= 0.999 and abs(delta) < 1e-9
        return ok, f"issued {issued_before}→{issued} atomic_delta={delta}"
    # Patience: the two transports land INDEPENDENTLY (registry→ES emit is prompt;
    # the TEG balance outbox flushes on its own cadence), so there is a legitimate
    # window where `issued` has risen but `circulating` has not and delta reads
    # non-zero. R1 measured convergence past the old 60s budget — 3 min is the
    # honest bound. NOTE: issued/circulating BOTH move by the issuance amount via
    # TokensIssued *and* LedgerBalanceChanged, so the magnitudes double
    # symmetrically and Δ still settles at 0 (verified live on a fresh frame).
    if not wait_for("canary projected (issued up, delta 0)", _projected, tries=120, sleep=5):
        die("emission gate: the canary issuance did NOT project into the frame's own "
            "EventStore (issued did not rise, or delta != 0) — the registry→ES emit "
            "or the TEG→ES balance outbox is broken; DO NOT ISSUE")
    log("EMISSION GATE PASSED — canary projected into the frame's own ES, delta=0")


def _h(url):
    st, _ = http("GET", url, timeout=5)
    return (st == 200), f"HTTP {st}"


def _version_tag(args) -> str:
    """What an operator's compose pulls: `<prefix>/registry:${VERSION}`. On the network the docker tag IS the card's constant;
    under --own-host (§HELLOFRAME) the export's images are tagged by release (theprotocol/registry:1.0.0-beta.4) while the
    card keeps the constant, so VERSION is the docker tag of the registry image the frame runs."""
    if getattr(args, "own_host", False) and ":" in (args.registry_image or "").rsplit("/", 1)[-1]:
        return args.registry_image.rsplit(":", 1)[1]
    return args.image_tag


def _bundled_tag_of_image(image: str):
    """The BUNDLED_IMAGE_TAG constant inside a local registry image (the version the card should report)."""
    return extras.image_constant(image)   # §HELLOFRAME: imported from the image (a release image has no .py to grep)


def _newest_common_operator_tag():
    """Newest image tag present locally for ALL THREE operator images."""
    sets = []
    for img in ("registry", "teg-layer", "cert-writer"):
        r = subprocess.run(["docker", "images", "--format", "{{.Tag}}",
                            f"images.theprotocol.cloud/{img}"],
                           capture_output=True, text=True)
        sets.append({t.strip() for t in (r.stdout or "").splitlines() if t.strip()})
    common = set.intersection(*sets) if sets and all(sets) else set()
    versioned = sorted(t for t in common if "V0" in t)
    return versioned[-1] if versioned else (sorted(common)[-1] if common else None)


def _free_cloud_port_base(start=31100, end=39900, span=100, taken=None):
    """Pick a cloud port base whose window is free on the HOST.

    §BEAT-B — the provisioner's own allocator only scans DOCKER-published ports,
    so it happily picked 31000 while a stray host `node` process (an FE preview
    server) held it, and the operator's registry container then failed to bind.
    Checking real host listeners avoids handing the provisioner a doomed base.

    §FRAMEPROV P1 (2026-09-13): it answered a question preflight does not ask. It checked ONE block in 31100-31280 and
    returned `start` when none was free, while preflight refuses a base whose three-block window holds fewer than TWO
    free blocks. Measured live: every frame planned without --cloud-port-base on this host was refused ("31100-31399 has
    0 free block(s)"), the EU/ASIA operators and the sandbox pair holding that window. It now asks preflight's question
    (its first block free, at least two of three free) over 31100-39800, against every port a listener, a container
    (running or stopped) or a stack's run meta holds.
    """
    taken = frame_ports.taken_ports() if taken is None else set(taken)
    for base in range(start, end, span):
        window = (base, base + span, base + 2 * span)
        free = [b for b in window if not any((b + off) in taken for off in (0, 43, 80))]
        if base in free and len(free) >= 2:
            return base
    return start


def _exec_http(container, url, tls=False, unix_socket=None):
    """HTTP check from INSIDE a container (for services with no host port). tls: present the container's own /certs SVID and
    verify against its bundle (§MTLSHOPS T2: the kit's OPA, Prometheus and Alertmanager require a client certificate)."""
    try:
        _opts = "--cacert /certs/bundle.0.pem --cert /certs/svid.0.pem --key /certs/svid.0.key " if tls else ""
        if unix_socket:   # §MTLSHOPS T2 (S4): an app that listens only on its socket is asked there
            _opts += f"--unix-socket {unix_socket} "
        r = subprocess.run(
            ["docker", "exec", container, "sh", "-c",
             f'curl -s -o /dev/null -w "%{{http_code}}" {_opts}{url}'],
            capture_output=True, text=True, timeout=15)
        code = (r.stdout or "").strip()
        return code == "200", f"HTTP {code or 'n/a'}"
    except Exception as e:
        return False, f"exec failed: {str(e)[:60]}"


def _container_healthy(container):
    """The container's own healthcheck verdict, for a terminator whose /health listens on its loopback only."""
    try:
        r = subprocess.run(
            ["docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}", container],
            capture_output=True, text=True, timeout=15)
        status = (r.stdout or "").strip() or f"inspect rc={r.returncode}"
        return status == "healthy", f"health {status}"
    except Exception as e:
        return False, f"inspect failed: {str(e)[:60]}"


def http_ok(url, timeout=8):
    """(ok, detail) for a loopback GET: 200 is the only ok. Used by the kit gates; no body is read."""
    try:
        import urllib.request as _ur
        with _ur.urlopen(_ur.Request(url, method="GET"), timeout=timeout) as r:
            return r.status == 200, f"HTTP {r.status}"
    except Exception as e:  # noqa: BLE001 — a probe reports what it saw
        code = getattr(e, "code", None)
        return False, f"HTTP {code}" if code else f"{type(e).__name__}"


def _env_kv(env_text):
    """KEY -> value from a rendered env file (first definition wins; quotes stripped)."""
    out = {}
    for line in env_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k not in out:
            out[k] = v.strip().strip("'").strip('"')
    return out


def kit_write_auditor_frames(ctx, env_text, args):
    """§SOVKIT (2026-09-14) — the solo auditor's ONE frame: this one. Written from the rendered env (the DB names and the
    read-only role's password the provisioner created) into <stack>/kit/auditor/frames/
    frames.json (600) BEFORE compose up, so the auditor boots with its frame; the read-only role itself is created by
    kit_gates() once the databases are healthy, and the auditor's lazily-created pools pick it up on their next try.
    Nothing here is printed: the file holds a password. §MTLSHOPS T2 (S4, 2026-09-15): the frame's url is the store's mTLS
    sidecar, which the auditor reads with its own SVID, so no store key is written."""
    kv = _env_kv(env_text)
    name = args.name
    ro_pw = kv.get("AUDITOR_RO_PASSWORD", "")
    if not ro_pw:
        die("kit: AUDITOR_RO_PASSWORD missing from the rendered env (the template renders it)")
    def dsn(container, user_key, db_key):
        return f"postgresql://auditor_ro:{ro_pw}@{name}-{container}:5432/{kv.get(db_key, '')}"
    entry = {
        "id": name, "name": getattr(args, "frame_label", None) or name, "mode": "prod",
        # §OPDIST (2026-09-16), agentvault2-6a measured it on lantern: this read AVT while the frame's rendered env
        # carries FRAME_CURRENCY=LNT and its card says LNT. The env TEXT this function parses is the one that exists
        # at THIS point in the standup, and the frame's own ticker reaches those keys later — so a TEMPLATE DEFAULT
        # was published as the frame's currency, and the auditor keys `fx_reserve_floor` on it, which makes it a
        # claim rather than a label (§LOCTRUTH: a value invented for one purpose becoming a fact in another).
        # The ticker the standup was GIVEN is the authority; the env keys stay as the fallback for a caller that
        # somehow has no ticker, and an empty result is left empty rather than defaulted to anything.
        "currency": ((getattr(args, "ticker", "") or "").strip()
                     or kv.get("FT_FRAME_CURRENCY") or kv.get("FRAME_CURRENCY") or "").upper(),
        "url": f"https://{name}-nginx-event-store:8443",
        "dsn": dsn("es-db", "FT_ESDB_POSTGRES_USER", "FT_ESDB_POSTGRES_DB"),
        "reg_dsn": dsn("db", "FT_DB_POSTGRES_USER", "FT_DB_POSTGRES_DB"),
        "teg_dsn": dsn("teg-db", "FT_TEGDB_POSTGRES_USER", "FT_TEGDB_POSTGRES_DB"),
        "fx_router_did": kv.get("FT_REG_FX_ROUTER_DID", ""),
    }
    frames_dir = os.path.join(ctx.stack_dir_container, "kit", "auditor", "frames")
    os.makedirs(frames_dir, exist_ok=True)
    path = os.path.join(frames_dir, "frames.json")
    with open(path, "w") as f:
        json.dump([entry], f, indent=1)
    # 0600, matching this function's own docstring: the file holds three read-only database passwords, the auditor
    # reads it as uid 0 so nothing about its access changes, and the host carries a `deploy` login (agentvault2-6a).
    # "The dir is the guard" was true of the directory and not of the file, which is the weaker half of the pair.
    os.chmod(path, 0o600)
    os.chmod(frames_dir, 0o755)
    log(f"kit: auditor frames file written ({path}, one entry: {name}, {entry['currency'] or 'no currency'}, dsn+reg_dsn+teg_dsn on the read-only role)")


def auditor_live_read_error(latest, frame_id):
    """§MTLSHOPS T2 (S4, 2026-09-15): the error of the auditor's latest live read of `frame_id`, from GET /api/auditor/latest:
    "" when that read succeeded, its error text when it failed, None when the frame has no row yet. When the live read
    fails and the atomic read works, the row's status mirrors the atomic read (TheAuditor main.py), so only
    extra_data.live_error tells a lost certificate from a healthy auditor (agentvault2-85). §MTLSHOPS (a) (2026-09-15,
    agentvault2-85): a live read that did not run (extra_data.live_skipped, a slot the auditor may not read) is not one that
    succeeded, so its recorded reason is returned as the error."""
    row = latest.get(frame_id) if isinstance(latest, dict) else None
    if not isinstance(row, dict):
        return None
    extra = row.get("extra_data")
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except ValueError:
            extra = {}
    skipped = extra.get("live_skipped") if isinstance(extra, dict) else None
    if skipped:
        return f"the live read did not run: {skipped}"
    err = row.get("live_error") or (extra.get("live_error") if isinstance(extra, dict) else None)
    return str(err) if err else ""


def auditor_live_read_probe(port, frame_id):
    """§MTLSHOPS (2026-09-15, b5): the kit gate's wait_for probe for the auditor's live read, as (ok, detail) like every other
    probe. wait_for unpacks a pair, and the probe this replaces returned a bare bool (bfda1e6), which would have raised
    TypeError on its first try in every standup and resume that reached the kit gates. Contract R33 holds every probe to
    the pair."""
    st, body = http("GET", f"http://127.0.0.1:{port}/api/auditor/latest", timeout=10)
    err = auditor_live_read_error(body if st == 200 else None, frame_id)
    if err == "":
        return True, "no live_error on the latest row"
    return False, (f"live_error: {err}" if err else f"no audit row for {frame_id} yet (HTTP {st})")


def kit_create_ro_roles(ctx, args):
    """The read-only role the solo auditor logs in with, in each of the frame's three databases. Idempotent; run as the
    owner; the password is hex (the provisioner makes it with token_hex) so it is safe to inline; psql reads the SQL on stdin
    (docker exec -i: the heredoc trap)."""
    kv = _env_kv(open(os.path.join(ctx.stack_dir_container, ".env.frame-test")).read())
    ro_pw = kv["AUDITOR_RO_PASSWORD"]
    assert re.fullmatch(r"[0-9a-f]{16,}", ro_pw), "the read-only password must be hex (it is inlined in SQL)"
    done = []
    for container, user_key, db_key in (("db", "FT_DB_POSTGRES_USER", "FT_DB_POSTGRES_DB"),
                                         ("teg-db", "FT_TEGDB_POSTGRES_USER", "FT_TEGDB_POSTGRES_DB"),
                                         ("es-db", "FT_ESDB_POSTGRES_USER", "FT_ESDB_POSTGRES_DB")):
        user, db = kv.get(user_key, ""), kv.get(db_key, "")
        if not (user and db):
            die(f"kit: {user_key}/{db_key} missing from the env")
        sql = (
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auditor_ro') THEN "
            f"EXECUTE format('CREATE ROLE auditor_ro LOGIN PASSWORD %L', '{ro_pw}'); END IF; END $$;\n"
            f"GRANT CONNECT ON DATABASE \"{db}\" TO auditor_ro;\n"
            f"GRANT USAGE ON SCHEMA public TO auditor_ro;\n"
            f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO auditor_ro;\n"
            f"ALTER DEFAULT PRIVILEGES FOR ROLE \"{user}\" IN SCHEMA public GRANT SELECT ON TABLES TO auditor_ro;\n"
        )
        r = subprocess.run(["docker", "exec", "-i", f"{args.name}-{container}", "psql", "-q", "-U", user, "-d", db, "-v", "ON_ERROR_STOP=1"],
                           input=sql, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            die(f"kit: read-only role in {args.name}-{container} refused: {(r.stderr or r.stdout)[-300:]}")
        done.append(container)
    log(f"kit: read-only role auditor_ro granted SELECT in {', '.join(done)}")


def rpk_topic_partitions(rpk_topic_list_output):
    """`rpk topic list` -> {topic: partitions}. The first line is the header (NAME PARTITIONS REPLICAS); a line whose
    second column is not a number is not a topic row."""
    out = {}
    for ln in (rpk_topic_list_output or "").splitlines()[1:]:
        cols = ln.split()
        if len(cols) >= 2 and cols[1].isdigit():
            out[cols[0]] = int(cols[1])
    return out



def expected_frame_services(compose_path, env_path):
    """§PROVSHOW (2026-09-15): the services a rendered frame compose declares, asked of `docker compose config --services`,
    never a count kept in this file. An empty list means the compose could not be read, and the caller says so."""
    try:
        r = subprocess.run(["docker", "compose", "-f", compose_path, "--env-file", env_path, "config", "--services"],
                           capture_output=True, text=True, timeout=120)
    except Exception:  # noqa: BLE001 — an unreadable compose is reported by the caller, not raised
        return []
    return [x.strip() for x in (r.stdout or "").splitlines() if x.strip()] if r.returncode == 0 else []


def parse_container_states(text, name):
    """`docker ps -a --format '{{.Names}}\t{{.State}}\t{{.Status}}'` lines -> {container: (state, exit code or None)}, only
    for containers named `<name>-...` (a substring filter also returns other frames whose names contain it)."""
    out = {}
    for line in (text or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0].startswith(f"{name}-"):
            continue
        m = re.search(r"Exited \((\d+)\)", parts[2] if len(parts) > 2 else "")
        out[parts[0].strip()] = (parts[1].strip().lower(), int(m.group(1)) if m else None)
    return out


def frame_container_states(name, project=None):
    """The frame's containers and their states: by its compose project label when the stack's project is known (a frame
    `a` never reads the containers of a frame `a-b`, §TESTBED P0 a), else by the `<name>-` name filter."""
    flt = ["--filter", f"label=com.docker.compose.project={project}"] if project else ["--filter", f"name={name}-"]
    r = subprocess.run(["docker", "ps", "-a", *flt, "--format", "{{.Names}}\t{{.State}}\t{{.Status}}"],
                       capture_output=True, text=True, timeout=60)
    return parse_container_states(r.stdout, name)


def frame_stack_gaps(expected, states):
    """The services of a rendered frame that are not up, as [(service, why)]. A one-shot `-init` service is up once it
    EXITED 0; every other service must be running. Created (where an aborted `compose up` leaves the dependents),
    restarting, exited and missing all count, so a half-started stack is never judged complete by how many containers run."""
    gaps = []
    for svc in expected:
        st = states.get(svc)
        if st is None:
            gaps.append((svc, "missing"))
        elif st[0] == "running":
            continue
        elif svc.endswith("-init") and st[0] == "exited" and st[1] == 0:
            continue
        else:
            gaps.append((svc, st[0] if st[1] is None else f"{st[0]}({st[1]})"))
    return gaps

def detachment_of(inspect):
    """Why a container docker calls running is not up, or None, from one `docker inspect` object. A start that could not
    program its published ports (`failed to bind host port ...: address already in use`) leaves the container created,
    and the next `compose up -d` starts it with NO network and nothing published (measured 2026-09-19 on
    larchsbx-nginx-edge: 127.0.0.1:8752 was held for an instant by an outgoing connection, on a host whose ephemeral port
    range starts at 1024). It runs and its own healthcheck passes while every door through it is dead, so a census of
    states calls it up; the kit's Grafana check then failed three minutes later, naming Grafana."""
    if ((inspect.get("State") or {}).get("Status") or "") != "running":
        return None
    hc, ns = inspect.get("HostConfig") or {}, inspect.get("NetworkSettings") or {}
    mode = str(hc.get("NetworkMode") or "")
    if mode in ("host", "none") or mode.startswith("container:"):
        return None
    if not (ns.get("Networks") or {}):
        return "running with no network"
    published = ns.get("Ports") or {}
    missing = [f"{(b[0].get('HostIp') or '0.0.0.0')}:{b[0].get('HostPort')}"
               for port, b in sorted((hc.get("PortBindings") or {}).items()) if b and not published.get(port)]
    return f"running with {', '.join(missing)} unpublished" if missing else None


def frame_container_detachments(name, project=None):
    """{container: why} for the frame's RUNNING containers that are not really up (detachment_of)."""
    flt = ["--filter", f"label=com.docker.compose.project={project}"] if project else ["--filter", f"name={name}-"]
    r = subprocess.run(["docker", "ps", "-q", *flt], capture_output=True, text=True, timeout=60)
    ids = (r.stdout or "").split()
    if not ids:
        return {}
    r = subprocess.run(["docker", "inspect", *ids], capture_output=True, text=True, timeout=60)
    try:
        objs = json.loads(r.stdout or "[]")
    except ValueError:
        return {}
    out = {}
    for obj in objs:
        cname = (obj.get("Name") or "").lstrip("/")
        why = detachment_of(obj) if cname.startswith(f"{name}-") else None
        if why:
            out[cname] = why
    return out


def reconcile_command(detached):
    """The reconcile's compose call: `up -d` starts what is created or missing; a service that RUNS without its network is
    left alone by it (it is running), so exactly those are recreated too, --no-deps."""
    up = "docker compose -f docker-compose.frame-test.yml --env-file .env.frame-test up -d"
    return up + (f" && {up} --no-deps --force-recreate {' '.join(detached)}" if detached else "")


def data_tls_clients(container, user, db):
    """§MTLSHOPS T3 (2026-09-15, agentvault2-b5): (ok, detail) for one database: at least one TCP client on TLS with a client
    certificate and none without TLS, read from its own pg_stat_ssl over the local socket (no password is involved)."""
    q = ("select (count(*) filter (where s.ssl and s.client_serial is not null))::text || '|' || "
         "(count(*) filter (where not s.ssl))::text from pg_stat_ssl s join pg_stat_activity a using (pid) "
         "where a.client_addr is not null")
    try:
        r = subprocess.run(["docker", "exec", container, "psql", "-U", user, "-d", db, "-tAc", q],
                           capture_output=True, text=True, timeout=30)
    except Exception as e:  # noqa: BLE001 — a probe reports what it saw
        return False, f"psql failed: {str(e)[:60]}"
    if r.returncode != 0:
        return False, f"psql rc {r.returncode}: {(r.stderr or '').strip()[:80]}"
    tls, _, plain = (r.stdout or "").strip().partition("|")
    return (tls.isdigit() and int(tls) >= 1 and plain == "0"), f"verified TLS clients {tls or '?'}, plain TCP clients {plain or '?'}"


def data_tls_refusal(container, conninfo, words):
    """§MTLSHOPS T3: (refused, detail) for a client the database must turn away, asked from inside its own container so the
    refusal is the hba's and not a missing route. `words` must appear in psql's error."""
    try:
        r = subprocess.run(["docker", "exec", container, "psql", conninfo, "-w", "-tAc", "select 1"],
                           capture_output=True, text=True, timeout=30)
    except Exception as e:  # noqa: BLE001
        return False, f"psql failed: {str(e)[:60]}"
    err = (r.stderr or "").strip().splitlines()
    return (r.returncode != 0 and words in (r.stderr or "")), (err[-1][:140] if err else f"rc {r.returncode} with no error")


# §MTLSHOPS T3: run inside the registry container with its own REDIS_URL; prints booleans only (the URL holds a password)
REDIS_TLS_PROBE = r"""
import json, os, socket, ssl, urllib.parse
import redis
url = os.environ["REDIS_URL"]
u = urllib.parse.urlparse(url)
def answered(connect):
    try:
        s = connect()
    except Exception:
        return False
    try:
        s.sendall(b"PING\r\n")
        return s.recv(64).startswith(b"+PONG")
    except Exception:
        return False
    finally:
        s.close()
out = {}
try:
    out["tls_client"] = redis.from_url(url, socket_timeout=5).ping() is True
except Exception as e:
    out["tls_client"] = False
    out["tls_client_error"] = type(e).__name__
out["plain_answered"] = answered(lambda: socket.create_connection((u.hostname, u.port or 6379), 5))
tls = ssl.create_default_context(cafile="/certs/bundle.0.pem")
out["certless_tls_answered"] = answered(lambda: tls.wrap_socket(socket.create_connection((u.hostname, u.port or 6379), 5), server_hostname=u.hostname))
print(json.dumps(out))
"""


def redis_tls_verdict(container):
    """§MTLSHOPS T3: (ok, detail) from `container` (the registry): its own REDIS_URL client answers PING over TLS, and a plain
    TCP client and a TLS client with no certificate get no answer."""
    try:
        r = subprocess.run(["docker", "exec", container, "python", "-c", REDIS_TLS_PROBE], capture_output=True, text=True, timeout=60)
        v = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        return False, f"probe failed: {str(e)[:80]}"
    ok = v.get("tls_client") is True and v.get("plain_answered") is False and v.get("certless_tls_answered") is False
    return ok, ", ".join(f"{k} {v[k]}" for k in sorted(v))


def kit_data_tls_gate(ctx, args):
    """§MTLSHOPS T3 (2026-09-15, agentvault2-b5): the frame's Postgres and Redis take TLS only, measured at both ends.

    Each database shows certificate-verified TLS clients and no plain one in its own pg_stat_ssl, and refuses a plain TCP
    client and a TLS client with no certificate. The registry's own Redis client answers PING over TLS while a plain and a
    certificate-less client get nothing. Only counts and verdicts are printed: every password stays in the containers."""
    name = args.name
    for container, user, db in ((f"{name}-db", "registry", "frame_test_registry"), (f"{name}-teg-db", "teg", "frame_test_teg"),
                                (f"{name}-es-db", "eventstore", "frame_test_events")):
        if not wait_for(f"data tls: {container} serves its TCP clients on TLS with a client certificate",
                        lambda c=container, u=user, d=db: data_tls_clients(c, u, d), tries=40, sleep=3):
            die(f"data tls: {container} never showed a certificate-verified TLS client with no plain one "
                f"({data_tls_clients(container, user, db)[1]})")
        for label, conninfo, words in (
                ("a plain TCP client", f"host=127.0.0.1 dbname={db} user={user} sslmode=disable connect_timeout=5", "no encryption"),
                ("a TLS client with no certificate", f"host={container} dbname={db} user={user} sslmode=require connect_timeout=5",
                 "certificate")):
            refused, detail = data_tls_refusal(container, conninfo, words)
            if not refused:
                die(f"data tls: {container} did not refuse {label} ({detail})")
    if not wait_for("data tls: the registry's Redis client answers over TLS; a plain and a certificate-less client get nothing",
                    lambda: redis_tls_verdict(f"{name}-registry"), tries=20, sleep=3):
        die(f"data tls: {name}-redis did not take TLS only ({redis_tls_verdict(f'{name}-registry')[1]})")
    log("data tls: the three databases and Redis take TLS only: certificate-verified clients seen, plain TCP and "
        "certificate-less TLS refused")


def kit_kafka_gate(ctx, args):
    """§SOVKIT K1 (2026-09-14, his word "2 yes": Kafka is PRIVATE to the event store) — the ledger bus is the store's
    alone, MEASURED before the standup goes on: the topics exist with the partitions the env names (the init service
    ran), the broker refuses an anonymous client and a wrong password, the registry container cannot reach the broker
    (the ledger network has two members), the store reports SASL_SSL with record auth enforced, and its consumer group
    is Stable. Every rpk call runs inside the broker container on its own RPK_* lines (the template); nothing here
    prints a credential."""
    kv = _env_kv(open(os.path.join(ctx.stack_dir_container, ".env.frame-test")).read())
    topics = [t.strip() for t in kv.get("FT_KAFKA_TOPICS", "").split(",") if t.strip()]
    parts = int(kv.get("FT_KAFKA_PARTITIONS", "0") or 0)
    if not topics or parts < 1:
        die("kit/kafka: FT_KAFKA_TOPICS / FT_KAFKA_PARTITIONS missing from the rendered env")
    rp, reg = f"{args.name}-redpanda", f"{args.name}-registry"

    def rpk(*a, env=None, timeout=30):
        # an in-container `timeout` around rpk: a subprocess timeout on `docker exec` ends the docker CLI, not the rpk
        # inside the container (85's forged produce landed minutes after the driver's 60 s timeout, 2026-09-14); a request
        # rpk hangs on (a refused SASL) must die IN the container, not outlive the gate
        cmd = (["docker", "exec"] + [x for k, v in (env or {}).items() for x in ("-e", f"{k}={v}")]
               + [rp, "timeout", str(max(5, timeout - 5)), "rpk", *a])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    # 0. the CLUSTER's own answer to the three properties the block seeds. Redpanda imports `redpanda.enable_sasl`,
    #    `superusers` and `auto_create_topics_enabled` from the yaml only when it bootstraps a FRESH data dir; on an
    #    existing cluster the controller log owns them and the seeds are ignored (agentvault2-85's sbx-alpha incident
    #    2026-09-14 21:38Z: the listener demanded a SASL the cluster had disabled, ILLEGAL_SASL_STATE for every client).
    #    So the gate asks the cluster, never the command line.
    _user = kv.get("FT_ES_KAFKA_SASL_USERNAME", "es") or "es"
    _want = {"enable_sasl": lambda v: v.strip().lower() == "true",
             "superusers": lambda v: _user in v,
             "auto_create_topics_enabled": lambda v: v.strip().lower() == "false"}
    for _prop, _ok in _want.items():
        _rc, _out = rpk("cluster", "config", "get", _prop)
        if _rc != 0 or not _ok(_out):
            die(f"kit/kafka: the CLUSTER reports {_prop}={_out.strip()[-80:]!r} (rc={_rc}); the yaml seeds only take at a fresh bootstrap: "
                f"`rpk cluster config set {_prop} ...` inside {rp} is the fix on an existing data dir")
    # 1. the topics, at the partitions the env names (the init service is one-shot; its log is the diagnosis)
    rc, out = rpk("topic", "list")
    if rc != 0:
        die(f"kit/kafka: rpk topic list refused inside {rp} (its RPK_* lines, or the bootstrap user): {out[-200:]}")
    seen = rpk_topic_partitions(out)
    wrong = {t: seen.get(t) for t in topics if seen.get(t) != parts}
    if wrong:
        die(f"kit/kafka: topics not at {parts} partitions: {wrong} — docker logs {rp}-init")
    # 2. anonymous and a wrong password are refused (the two negative controls of the SASL claim)
    # (a refusal is a failure that NAMES the reason; a broker that is down fails every probe and proves nothing)
    # the two negative controls run from a FRESH rpk container with no RPK_* env at all (inside the broker container
    # rpk keeps the store's credentials and refuses an empty SCRAM user itself, which proves nothing about the broker);
    # the wrong-password control runs inside, on the container's own user. Measured on the rendered template.
    _ledger_net, _certs_vol = f"{ctx.net_name}_ledger", f"{ctx.vol_prefix}_svid_certs_{ctx.ts}"
    def _fresh_rpk(*flags):
        # --entrypoint rpk: the image's entrypoint prepends `rpk` itself (a bare `rpk topic list` becomes `rpk rpk ...`)
        r = subprocess.run(["docker", "run", "--rm", "--network", _ledger_net, "-v", f"{_certs_vol}:/certs:ro", "--entrypoint", "timeout",
                            "redpandadata/redpanda:v26.2.3", "45", "rpk", "topic", "list", *flags], capture_output=True, text=True, timeout=60)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    _refusal = re.compile(r"SASL|authentication|tls alert|handshake|invalid large response|closed the connection", re.I)
    for _label, (_rc, _out) in (("an ANONYMOUS client over TLS", _fresh_rpk("-X", f"brokers={rp}:9092", "-X", "tls.enabled=true", "-X", "tls.ca=/certs/bundle.0.pem")),
                                ("a PLAINTEXT client", _fresh_rpk("-X", f"brokers={rp}:9092")),
                                ("a WRONG password", rpk("topic", "list", env={"RPK_PASS": "not-the-password-0123456789"}))):
        if _rc == 0:
            die(f"kit/kafka: the broker answered {_label}: SASL over TLS is not required on :9092")
        if not _refusal.search(_out):
            die(f"kit/kafka: {_label} failed for a reason that is not the refusal: {_out.strip()[-160:]}")
    # 3. the registry cannot reach the broker (it is not on the ledger network; docker DNS does not even resolve it)
    r = subprocess.run(["docker", "exec", reg, "python3", "-c",
                        "import socket\ntry:\n    socket.create_connection(('" + rp + "', 9092), 3); print('REACHED')\n"
                        "except Exception as e:\n    print('UNREACHABLE', type(e).__name__)"],
                       capture_output=True, text=True, timeout=30)
    if "UNREACHABLE" not in (r.stdout or ""):
        die(f"kit/kafka: the REGISTRY container reaches {rp}:9092 — the broker is not private to the store: {(r.stdout or r.stderr)[-200:]}")
    # 4. the store's own posture, read from its /health (names and booleans, never a credential)
    # §MTLSHOPS T2 (S4, 2026-09-15): through the edge's loopback door (the store listens on a socket)
    _st, h = http("GET", f"http://127.0.0.1:{PORTS['es']}/health", timeout=10)
    h = h if isinstance(h, dict) else {}
    kc, ra = h.get("kafka_client") or {}, h.get("kafka_record_auth") or {}
    if kc.get("protocol") != "SASL_SSL" or not kc.get("sasl_user_set") or not kc.get("ca_file_set"):
        die(f"kit/kafka: the store's /health does not report SASL_SSL with a user and a CA file: kafka_client={kc}")
    if ra.get("mode") != "enforce" or ra.get("key") == "missing":
        die(f"kit/kafka: the store's record auth is not enforced with a key: kafka_record_auth={ra}")
    # 5. the consumer group joined (Stable); lag is reported, not gated (a fresh frame has nothing to lag on)
    def _group():
        rc2, out2 = rpk("group", "describe", kv.get("FT_ES_KAFKA_CONSUMER_GROUP", "") or "eventstore-consumer")
        st = re.search(r"^\s*STATE\s+(\S+)", out2, re.M | re.I)
        return (rc2 == 0 and bool(st) and st.group(1).lower() == "stable"), (st.group(1) if st else out2.strip()[-80:])
    if not wait_for("kit/kafka: the store's consumer group Stable", _group, tries=20, sleep=3):
        die(f"kit/kafka: the store's consumer group never reached Stable — docker logs {args.name}-event-store")
    log(f"kit/kafka: broker private to the store (cluster: enable_sasl true, superusers has {_user}, auto-create off): {len(topics)} topics x {parts} partitions, anonymous refused, wrong password refused, "
        f"registry cannot reach {rp}, store SASL_SSL + record auth enforce ({ra.get('key')} key), consumer group Stable")


def kit_gates(ctx, args):
    """§SOVKIT (2026-09-14) — every kit component answers before the standup goes on. A frame that ships a
    component it cannot reach is the flagship's measurement again (0 of 90 days on every status component)."""
    # the frame's own Prometheus is named ONCE, in the rendered env (PROMETHEUS_URL, the template's active line the
    # driver keeps under --wire-prod); the readiness probe asks that address, never a second copy of it.
    _kit_env = _env_kv(open(os.path.join(ctx.stack_dir_container, ".env.frame-test")).read())
    _kit_prom = _kit_env.get("PROMETHEUS_URL", "").rstrip("/")
    if not _kit_prom:
        die("kit: the rendered env names no PROMETHEUS_URL (the template's active line is missing)")
    # §MTLSHOPS T2: OPA's address is read from the same env the registry reads (FT_REG_OPA_URL), never a second copy; an
    # https kit is asked with the registry container's own SVID, which OPA's authz and Prometheus/Alertmanager's allowed
    # SANs accept.
    _kit_opa = _kit_env.get("FT_REG_OPA_URL", "").rstrip("/")
    if not _kit_opa:
        die("kit: the rendered env names no FT_REG_OPA_URL")
    _kit_tls = _kit_prom.startswith("https://")
    reg = f"{args.name}-registry"
    if not wait_for("kit: opa /health (from the registry container)",
                    lambda: _exec_http(reg, f"{_kit_opa}/health", tls=_kit_opa.startswith("https://")), tries=20, sleep=3):
        die(f"kit: {args.name}-opa never answered /health — docker logs {args.name}-opa")
    if not wait_for("kit: prometheus /-/ready",
                    lambda: _exec_http(reg, f"{_kit_prom}/-/ready", tls=_kit_tls), tries=30, sleep=3):
        die(f"kit: {args.name}-prometheus never became ready — docker logs {args.name}-prometheus")
    if not wait_for("kit: alertmanager /-/ready",
                    lambda: _exec_http(reg, f"{'https' if _kit_tls else 'http'}://{args.name}-alertmanager:9093/-/ready",
                                       tls=_kit_tls), tries=20, sleep=3):
        die(f"kit: {args.name}-alertmanager never became ready")
    if not wait_for("kit: grafana /api/health",
                    lambda: http_ok(f"http://127.0.0.1:{ctx.port_grafana}/api/health"), tries=40, sleep=3):
        die(f"kit: grafana never answered on 127.0.0.1:{ctx.port_grafana}")
    kit_create_ro_roles(ctx, args)
    if not wait_for("kit: auditor /health",
                    lambda: http_ok(f"http://127.0.0.1:{ctx.port_auditor}/health"), tries=40, sleep=3):
        die(f"kit: the solo auditor never answered on 127.0.0.1:{ctx.port_auditor}")
    # §MTLSHOPS T2 (S4, 2026-09-15, agentvault2-85): "OK" cannot prove the auditor's read through the store's mTLS sidecar
    # (its status mirrors the atomic read when that read fails); the latest row's live_error can.
    if not wait_for("kit: the auditor's live read through the store's mTLS sidecar (no live_error on its latest row)",
                    lambda: auditor_live_read_probe(ctx.port_auditor, args.name), tries=40, sleep=3):
        die(f"kit: the solo auditor's live read never succeeded ({auditor_live_read_probe(ctx.port_auditor, args.name)[1]}): "
            f"it reads {args.name}-nginx-event-store with its own SVID")
    if not wait_for("kit: directory read leg (nginx-directory's own healthcheck: its /health listens on its loopback)",
                    lambda: _container_healthy(f"{args.name}-directory-nginx"), tries=40, sleep=3):
        die(f"kit: {args.name}-directory-nginx never became healthy, and two states look alike here: the container never "
            f"started (Created after an aborted compose up; docker ps -a --filter name={args.name}-directory) or its cert-writer has no "
            f"SVID yet (the spire step)")
    # the ONE probe that proves the index is reachable over mTLS with the registry's own SVID: the registry's
    # public proxy answers only when its dial to https://<name>-directory-nginx:8443 verified and was verified
    if not wait_for("kit: directory over mTLS (GET /api/v1/public/directory/health through the registry)",
                    lambda: http_ok(f"http://127.0.0.1:{PORTS['registry']}/api/v1/public/directory/health"), tries=40, sleep=5):
        die("kit: the registry cannot read its own Directory over mTLS (docker logs the registry and the directory sidecar)")
    log("kit: opa, prometheus, alertmanager, grafana, the solo auditor and the Directory (over mTLS) all answer")


def admin_login(args):
    reg = f"http://127.0.0.1:{PORTS['registry']}"
    body = f"username={urllib.parse.quote(args.admin_email)}&password={urllib.parse.quote(args.admin_password)}"
    st, r = http("POST", f"{reg}/api/v1/auth/login", body, form=True)
    if st != 200 or not isinstance(r, dict) or "access_token" not in r:
        die(f"admin login failed HTTP {st}: {r}")
    return r["access_token"]


def resolve_logo(path):
    """Locate the logo file, tolerating a renamed asset.

    HARD-WON: the default here once said `hetzner-logo.png` while the asset on
    disk shipped as `hetzner-logo-PLACEHOLDER.png`, and the old code SILENTLY
    skipped the upload ("logo: SKIPPED") — so every frame ever stood up with a
    blank orb on the globe and nobody noticed for five runs. Never skip a
    branding step quietly: fall back to any *logo*.(png|jpg) beside the expected
    path, and if there is still nothing, the caller SHOUTS.
    """
    if path and os.path.exists(path):
        return path
    d = os.path.dirname(path or "") or f"{REPO}/scripts/hetzner_demo/assets"
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if re.search(r"logo.*\.(png|jpe?g)$", f, re.I):
                return os.path.join(d, f)
    return None


def admin_pass(args, jwt, mint=True, on_minted=None, minted_before="0"):
    """The card, the logo, the show issuance. §FRAMEPROV P1: `mint=False` skips the show issuance (an earlier pass made it: run
    meta `show_minted`). §FRAMESHOWCASE (2026-09-14): the show issuance goes in pieces no larger than the registry's per-call
    ceiling; `on_minted(total)` runs after every accepted piece with the running total, and `minted_before` (run meta
    `show_minted_amount`) is what an earlier pass already issued, so a resume issues only the rest."""
    reg = f"http://127.0.0.1:{PORTS['registry']}"
    H = {"Authorization": f"Bearer {jwt}"}
    # Field names verified against the SERVED card: the operator block uses
    # `display_name` (not `label`) + `company` + `location_label`; a wrong key is
    # silently ignored and the card keeps showing the seeded admin ("Test Admin").
    card_body = {
        "description": args.description,
        "operator": {
            "display_name": args.operator_label,
            "company": args.operator_label,
            "location_label": args.location_label,
            "latitude": args.lat,
            "longitude": args.lng,
        },
        "links": {"website": args.website},
    }
    # Cosmetic flare axes (catalogs in core/registry_identity.py). The overlay is
    # only rendered on top of an encirclement, so sending one without the other
    # is a silent no-op — send them together or not at all.
    for k, v in extras.card_extras(getattr(args, "card_json", None)).items():   # §BATCH10: tags · links (no github) · commitments
        card_body[k] = ({**card_body.get(k, {}), **v} if isinstance(v, dict) and isinstance(card_body.get(k), dict) else v)
    visual = {}
    # §FRAMELIC row 62 — two frames born from one driver wore the SAME mark until his eye caught
    # it. The theme is a birth property, so the driver carries it instead of a later hand-patch.
    if getattr(args, "theme", None):
        visual["theme"] = args.theme
    if args.flare_encirclement:
        visual["flare_encirclement_variant"] = args.flare_encirclement
    if args.flare_overlay:
        if not args.flare_encirclement:
            die("--flare-overlay needs --flare-encirclement (an overlay alone renders nothing)")
        visual["flare_encirclement_overlay"] = args.flare_overlay
    if visual:
        card_body["visual"] = visual
    st, r = http("PUT", f"{reg}/api/v1/admin/registry-card", card_body, headers=H)
    log(f"card PUT: HTTP {st}" + ("" if st == 200 else f" {r}"))

    logo_path = resolve_logo(args.logo)
    if logo_path:
        boundary = "----hetznerdemo" + secrets.token_hex(8)
        raw = open(logo_path, "rb").read()
        fname = os.path.basename(logo_path)
        ctype = "image/png" if fname.lower().endswith("png") else "image/jpeg"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n").encode() \
               + raw + f"\r\n--{boundary}--\r\n".encode()
        # form=True is LOAD-BEARING: without it http() runs json.dumps() over these
        # multipart BYTES and raises TypeError *outside* its try block, killing the
        # standup. It stayed latent only because the path bug above meant this line
        # never executed once.
        st, r = http("POST", f"{reg}/api/v1/admin/registry-card/icon", body, form=True,
                     headers={**H, "Content-Type": f"multipart/form-data; boundary={boundary}"})
        log(f"logo upload: HTTP {st} from {fname}" + ("" if st == 200 else f" {r}"))
        # HTTP 200 is not proof. The globe reads visual.icon_url off the SERVED
        # card and nothing else, so verify the URL actually spliced in.
        _st, card = http("GET", f"{reg}/.well-known/registry-card.json")
        icon = ((card or {}).get("visual") or {}).get("icon_url") if isinstance(card, dict) else None
        if icon:
            log(f"logo published: {icon}")
        else:
            log(f"!! LOGO NOT IN SERVED CARD after HTTP {st} — globe will show no logo")
    else:
        log(f"!! LOGO NOT FOUND (looked for {args.logo!r}, then *logo*.png beside it) "
            f"— frame will stand up with NO logo on the globe")

    target = Decimal(str(args.mint or "0"))
    if target <= 0:
        return
    before = Decimal(str(minted_before or "0"))
    if not mint or before >= target:
        log(f"GENESIS SUPPLY {args.mint} {args.ticker}: made in an earlier pass (run meta), not issued twice")
        _show_mint_landed(args, issued_before=None, minted=target)
        return
    # §FRAMESHOWCASE (2026-09-14, his "your recommendation. but not cap at 1m"): hansa asked for 5,000,000, the rail
    # refused the one call above its ceiling, and this step logged the refusal and went on, so the frame came up with an
    # empty treasury. Now: pieces within the ceiling the registry itself reports, a refused piece stops the step, and the
    # frame's own ledger must show the issuance at delta 0.
    ceiling, source = extras.registry_mint_ceiling(args.name)
    read, detail = _ledger_read(args.name)
    if read is None:
        die(f"GENESIS SUPPLY: the frame's own ledger is unreadable BEFORE the issuance ({detail}); refusing to issue")
    issued_before = read[1]
    log(f"GENESIS SUPPLY {target} {args.ticker}: in pieces of at most {ceiling} (the ceiling from {source})"
        + (f", after {before} issued in an earlier pass" if before > 0 else ""))

    def _post(amount_text, reason_text):
        return http("POST", f"{reg}/api/v1/teg/treasury/mint", {"amount": amount_text, "reason": reason_text},
                    headers=H, timeout=90)

    minted, made, err = extras.mint_in_pieces(_post, target, ceiling,
                                              f"Genesis supply of {args.ticker} for the {args.frame_label}",
                                              minted_before=before, on_piece=on_minted)
    if err:
        die(f"GENESIS SUPPLY stopped at {minted} of {target} {args.ticker} after {made} accepted piece(s) in this pass: {err}. "
            "A resume from admin issues only the rest.")
    log(f"GENESIS SUPPLY {target} {args.ticker}: {made} piece(s) accepted in this pass, {minted} issued in all")
    _show_mint_landed(args, issued_before=issued_before, minted=minted - before)


def _op_admin_login(base: str, admin_email: str, admin_pw: str, tries: int = 8, sleep: int = 15):
    """§ONESHOT (2026-09-12) — a freshly provisioned operator answers /health and then times out its
    first admin login (HTTP 0 = no answer within 30 s) while its workers warm: measured on every proof
    operator ("NO ICON — admin login 0", "self-echo: … admin login 0 — NOT checked"). Ask again for two
    minutes before concluding; return (token or None, last status)."""
    st = 0
    # this module's http(form=True) takes a PRE-ENCODED string (admin_login builds one); a dict went out
    # raw, the operator answered "400 error parsing the body" and the client saw 0 — for two minutes,
    # on every operator, and the icon step had been doing the same since it was written (F9).
    body = urllib.parse.urlencode({"username": admin_email, "password": admin_pw})
    for _ in range(tries):
        st, r = http("POST", f"{base}/api/v1/auth/login", body, form=True)
        if st == 200 and isinstance(r, dict) and r.get("access_token"):
            return r["access_token"], st
        if st not in (0, 502, 503, 504):
            return None, st
        time.sleep(sleep)
    return None, st


def _op_icon(base: str, admin_email: str, admin_pw: str, theme: str, slug: str) -> None:
    """Upload this frame's mark onto the OPERATOR's own registry card.

    The FE renders a peer as flare -> `visual.icon_url` -> plain orb, so an operator whose card
    carries only a theme falls through to the orb no matter how healthy it is. Verified by
    re-reading the SERVED card rather than by the upload's status, because the console reads
    `visual.icon_url` off that card and nothing else — an HTTP 200 here is not proof (row 153).
    """
    import uuid as _uuid
    logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets",
                        f"protocol-mark-{theme}.png")
    if not os.path.exists(logo):
        log(f"  operator {slug}: NO ICON — asset missing: {logo}")
        return
    _tok, st = _op_admin_login(base, admin_email, admin_pw)
    if not _tok:
        log(f"  operator {slug}: NO ICON — admin login {st} (after two minutes of asking)")
        return
    r = {"access_token": _tok}
    H = {"Authorization": f"Bearer {r['access_token']}"}
    b = _uuid.uuid4().hex
    raw = open(logo, "rb").read()
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"icon.png\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + raw + f"\r\n--{b}--\r\n".encode()
    # form=True is LOAD-BEARING: without it http() json.dumps() these multipart BYTES and raises
    # OUTSIDE its try block, killing the standup (the frame path's own hard-won comment).
    st, _ = http("POST", f"{base}/api/v1/admin/registry-card/icon", body, form=True,
                 headers={**H, "Content-Type": f"multipart/form-data; boundary={b}"})
    _st, card = http("GET", f"{base}/.well-known/registry-card.json")
    icon = ((card or {}).get("visual") or {}).get("icon_url") if isinstance(card, dict) else None
    log(f"  operator {slug}: icon upload HTTP {st}, published={icon or 'MISSING'}")


def provision_child_operator(args, jwt):
    """BEAT B — the frame provisions its OWN child cloud operator.

    Mirrors exactly what the FE Operator Management flow does:
      apply -> approve (activation code is shown ONCE in this response)
            -> activate (frame's SPIRE issues the operator's identity;
                         the docker pull token is shown ONCE here)
            -> cloud-provision (brings up the 9-container op, writes its nginx
                         vhost + stream-map entry, and syncs the federation
                         license into the FRAME's OWN EventStore)
    """
    reg = f"http://127.0.0.1:{PORTS['registry']}"
    H = {"Authorization": f"Bearer {jwt}"}
    slug = args.operator_slug
    log(f"BEAT B — provisioning child operator '{slug}' from the frame")

    st, app = http("POST", f"{reg}/api/v1/operator-applications", {
        "name": slug,
        "email": f"operator@{args.name}.dev",
        "organization": "Demo Operator",
        "deployment": "cloud",
        "experience": "demo",
        "use_case": "Showcase: a sovereign frame provisioning its own child registry.",
    })
    if st not in (200, 201) or not isinstance(app, dict) or not app.get("id"):
        die(f"operator apply failed HTTP {st}: {str(app)[:250]}")
    app_id = app["id"]
    log(f"  applied: {app_id}")

    st, appr = http("POST", f"{reg}/api/v1/admin/operator-applications/{app_id}/approve",
                    {"notes": "demo showcase"}, headers=H)
    if st != 200 or not isinstance(appr, dict):
        die(f"operator approve failed HTTP {st}: {str(appr)[:250]}")
    code = appr.get("activation_code")
    if not code:
        die("approve returned no activation_code (it is shown ONCE — cannot continue)")
    log("  approved (activation code captured)")

    st, act = http("POST", f"{reg}/api/v1/operators/activate",
                   {"activation_code": code}, headers=H, timeout=240)
    if st != 200 or not isinstance(act, dict):
        die(f"operator activate failed HTTP {st}: {str(act)[:250]}")
    log(f"  activated — frame SPIRE issued fingerprint {(act.get('spire_fingerprint') or '')[:16]}…")

    # §PRESTAGE (Commander 2026-07-27, depth 'activated'): stop HERE so the live
    # call opens the frame's own Operator Management with the operator already
    # sitting activated in the queue — one Provision click on camera finishes it
    # via the NORMAL product flow. Nothing container-side has happened yet.
    if getattr(args, "prestage_operator", None) == "activated":
        log(f"  PRESTAGED at 'activated' — provision '{slug}' live from the frame UI "
            f"(Operator Management → Provision)")
        return {"application_id": app_id, "slug": slug, "prestaged": "activated",
                "port": args.cloud_port_base, "containers": 0, "provision_http": None}

    # The provision is long-running and holds a DB session; it MUST finish before
    # the connection is reaped, which is why the image tag has to be real (a bad
    # tag => minutes of compose retries => rolled-back license/peer rows).
    st, prov = http("POST", f"{reg}/api/v1/admin/cloud-operators/{app_id}/provision",
                    {}, headers=H, timeout=900)
    # A 500 here is NOT proof of failure: under host load the provisioner's
    # in-request orchestration outlives its DB session ("connection is closed")
    # and returns 500 *after* having created the stack. Gate on the operator's
    # REAL health instead of the HTTP status.
    if st != 200:
        log(f"  provision returned HTTP {st} — verifying by container state instead "
            f"(known: long provision outlives its DB session)")

    op_dir = f"/opt/theprotocol/stack/cloud-op-{slug}"
    if not os.path.isdir(op_dir):
        die(f"cloud-provision produced no stack dir at {op_dir}: {str(prov)[:300]}")

    # §V0085 doctrine — a compose straggler left in `Created` is NETWORK-LESS;
    # `docker start` would bring it up with no project network and it would
    # crash-loop on `could not translate host name "pgbouncer"`. ONLY
    # `compose up -d --force-recreate` re-attaches the networks. Observed live:
    # under load the provisioner's own reconcile reached 6/9, and one
    # force-recreate pass took it to 10/10 healthy.
    def _running():
        r = subprocess.run(["docker", "ps", "--format", "{{.Names}}",
                            "--filter", f"name=cloud-op-{slug}-"],
                           capture_output=True, text=True)
        return len([x for x in (r.stdout or "").split() if x])

    def _compose(cmd):
        return subprocess.run(
            ["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock",
             "-v", f"{op_dir}:{op_dir}", "-w", op_dir, "docker:cli", "sh", "-c",
             f"docker compose -f docker-compose.operator.yml --env-file .env.operator {cmd}"],
            capture_output=True, text=True, timeout=900)

    # Reconcile is a LOOP, not a single pass. Under host load the operator's TEG
    # takes minutes to go healthy, and `compose up` ABORTS THE WHOLE RUN the moment
    # a dependency's health-wait times out ("dependency failed to start ... is
    # unhealthy") — leaving registry + both nginx sidecars in `Created`. Nothing is
    # actually broken; the run just gave up early. Re-issuing `up -d` once the slow
    # dep reports healthy completes the stack. Observed live: pass 1 stopped at 7/10
    # with teg still starting, teg went healthy ~5 min later, and the very next
    # `up -d` took it to 10/10. First pass force-recreates (a `Created` straggler is
    # NETWORK-LESS per §V0085 and must be recreated, never `docker start`ed);
    # later passes are plain `up -d` so healthy containers are not churned.
    for attempt in range(1, 6):
        n = _running()
        if n >= 9:
            break
        log(f"  reconcile pass {attempt}: {n} up — `compose up -d"
            f"{' --force-recreate' if attempt == 1 else ''}`")
        _compose("up -d --force-recreate" if attempt == 1 else "up -d")
        if _running() >= 9:
            break
        time.sleep(60)

    # §FRAMELIC (2026-09-07, findings row 138) — THE PORT THE PROVISIONER GAVE, NOT THE ONE WE ASKED FOR.
    # `--cloud-port-base` is a REQUEST; `allocate_port_block` decides, and since the bind probe
    # (row 133) it legitimately says no to a wedged block and moves on. Polling the requested port
    # meant the driver sat on `/health: waiting… (HTTP 0)` for five minutes against an operator
    # that was up and answering 200 on the port it was actually given. Fourth instance tonight of
    # one fact computed in two places — read it back from the response that KNOWS.
    op_port = int((prov or {}).get("registry_port") or (prov or {}).get("cloud_port_base")
                  or (prov or {}).get("port") or args.cloud_port_base)
    if op_port != args.cloud_port_base:
        log(f"  operator {slug}: provisioner allocated :{op_port} (we asked for :{args.cloud_port_base})")
    if not wait_for(f"operator {slug} /health",
                    lambda: _h(f"http://127.0.0.1:{op_port}/health"), tries=60, sleep=5):
        # §ONESHOT (2026-09-12) — say what the operator's containers look like, not only that the port is
        # silent: the proof met an operator whose registry was healthy and on NO network (the provisioner's
        # `compose up` failed twice at container creation and its reconcile left the registry detached), so
        # its nginx-federation crash-looped on `host not found in upstream "registry"` and the port answered 0.
        _census = []
        for _c in subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}|{{.Status}}"], capture_output=True, text=True).stdout.splitlines():
            if _c.startswith(f"cloud-op-{slug}-"):
                _n, _, _st = _c.partition("|")
                _nets = subprocess.run(["docker", "inspect", _n, "--format", "{{range $k,$v := .NetworkSettings.Networks}}{{$k}} {{end}}"],
                                       capture_output=True, text=True).stdout.split()
                _census.append(f"{_n.replace('cloud-op-' + slug + '-', '')}: {_st.split(' (')[0]}, nets={_nets or ['NONE']}")
        die(f"operator {slug} never became healthy on :{op_port} ({_running()} containers up) — " + "; ".join(_census))
    log(f"  operator {slug} LIVE: {_running()} containers, /health 200 on :{op_port}")
    _creds = {k: (prov or {}).get(k) for k in ("admin_email", "admin_password")}
    if not _creds.get("admin_password"):   # §BATCH10 finding 39: the provisioner reads the password from the operator's boot banner —
        try:                               # when ITS compose-up failed it saw none; the banner is still in the container's log
            _lg = subprocess.run(["docker", "logs", "--tail", "5000", f"cloud-op-{slug}-registry"], capture_output=True, text=True)
            _m = re.search(r"FIRST-BOOT ADMIN PASSWORD:\s*(\S+)", (_lg.stdout or "") + (_lg.stderr or ""))
            if _m:
                _creds["admin_password"] = _m.group(1); _creds["admin_email"] = _creds.get("admin_email") or f"admin@cloud-op-{slug}.dev"
                log(f"  operator {slug}: admin credentials recovered from the boot banner (the provision response carried none)")
        except Exception as _e:
            log(f"  operator {slug}: banner read failed: {str(_e)[:80]}")
    if prov is not None and isinstance(prov, dict):
        prov.update({k: v for k, v in _creds.items() if v})
    # findings row 188 — GIVE THE OPERATOR A FACE. The frame gets its mark uploaded post-boot
    # (--logo, row 153); the operator provisioner never did, so every operator this cluster has
    # stood up was iconless BY CONSTRUCTION and rendered a plain orb on Federation Peers. The
    # card is where a logo lives, so this must happen after the operator is serving its own card.
    # Best-effort on purpose: a missing face is cosmetic and must never fail a standup that has
    # already provisioned a working operator — but it is COUNTED and named, because a silent
    # skip here is exactly how the gap survived (§FXSTRAND: the state must be visible).
    try:
        _icon_admin = (prov or {}).get("admin_email")
        _icon_pw = (prov or {}).get("admin_password")
        if _icon_admin and _icon_pw:
            _op_icon(f"http://127.0.0.1:{op_port}", _icon_admin, _icon_pw, args.theme, slug)
        else:
            log(f"  operator {slug}: NO ICON — the provision response carried no admin credentials")
    except Exception as _ie:  # noqa: BLE001
        log(f"  operator {slug}: NO ICON — {type(_ie).__name__}: {str(_ie)[:90]}")

    return {"application_id": app_id, "slug": slug, "port": op_port,
            "containers": _running(), "provision_http": st,
            **{k: (prov or {}).get(k) for k in ("admin_email", "admin_password", "federation_license_key", "domain", "registry_port")}}


def export_spire_bundle(args):
    """Publish THIS frame's SPIRE CA where the public ES vhost can verify against it.

    A cloud-op authenticates to its parent frame's EventStore by SPIFFE SVID — NOT by
    any shared key. Measured on the live fleet: op-berlin's EVENT_STORE_INTERNAL_API_KEY
    does NOT match Frame A's ES key, and op-berlin still logs ZERO 403s. The production
    `events.theprotocol.cloud` vhost is what makes that work: `ssl_verify_client` plus
    the three `X-SSL-Client-{Cert,Verify,S-DN}` headers, which carry the op's SVID
    through to the ES (`verify_event_auth` method 1). The `hetzner-es` vhost mirrors it.

    This MUST run every standup: `spire-server` creates a BRAND-NEW CA per frame, so a
    bundle left over from a previous run makes nginx advertise the wrong issuer and the
    op silently stops presenting its cert → straight back to 403s on every ES read.

    A one-shot write is NOT enough after standup either: SPIRE rotates its CA (~every
    few days) and a stale bundle 400s EVERY mTLS client at nginx — topology emits, the
    TEG balance outbox AND all reactor WS feeds (§CAROTFIX 2026-08-02). The 5-minute
    root-crontab entry refreshing /etc/nginx/hetzner-frame-spire-bundle.pem from
    `hetzner-frame-spire-server bundle show` is the durable fix; keep it installed.
    """
    out = frame_bundle_pem(args.name)
    # §ONESHOT P2.2 — when the frame is already under the 5-minute refresh (sidecars.register_bundle ran at
    # the vhosts step) the file is the refresh's to write; a second writer for one file is the class
    # "one fact, two places". The one-shot export stays only as the fallback for a host with no manifest.
    if os.path.exists(out) and open(out).read().count("BEGIN CERTIFICATE") >= 1:
        log(f"spire bundle {out} present ({open(out).read().count('BEGIN CERTIFICATE')} cert(s)) — under the refresh, not re-exported")
        return
    r = subprocess.run(["docker", "exec", f"{args.name}-spire-server",
                        "/opt/spire/bin/spire-server", "bundle", "show"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or "BEGIN CERTIFICATE" not in (r.stdout or ""):
        die(f"spire bundle export failed: {(r.stderr or r.stdout or '')[:200]}")
    open(out, "w").write(r.stdout)
    os.chmod(out, 0o644)
    log(f"spire bundle exported → {out} ({r.stdout.count('BEGIN CERTIFICATE')} cert(s))")


def enable_vhosts(args):
    export_spire_bundle(args)
    for v in frame_vhosts(args.name):
        src, dst = f"{NGINX_AVAIL}/{v}", f"{NGINX_ENABLED}/{v}"
        # §BATCH5 (2026-09-05): a vhost PRE-STAGED as a regular file in sites-enabled (the runbook's way: cloned from a
        # working shape, certificate already issued) is "already enabled" — the old `islink` test tried to symlink over it
        # and the driver died AFTER the frame was up, issued and bundled (FileExistsError). Never overwrite what the
        # operator staged; only create the symlink when nothing is there and sites-available has the file.
        if os.path.islink(dst) or os.path.exists(dst):
            log(f"vhost {v}: already in sites-enabled ({'symlink' if os.path.islink(dst) else 'file'}) — kept")
            continue
        if not os.path.exists(src):
            die(f"vhost {v}: neither pre-staged in sites-enabled nor present in sites-available — stage it first (runbook §0.3)")
        os.symlink(src, dst)
    if subprocess.run(["nginx", "-t"], capture_output=True).returncode != 0:
        die("nginx -t failed after enabling vhosts (symlinks left for inspection)")
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    log("vhosts enabled + nginx reloaded")


def build_ctx(args, ts, prov):
    """§BATCH10 finding 49b — ONE constructor for the provisioner context, used by the full run AND the resume branch
    (a resumed run once rebuilt a bare context: no public_hostname → the SPIRE entry lost the frame's DNS name → the
    federation certificate could not be verified for the public address)."""
    # §FRAMEPROV P4 (2026-09-13): the label is the name the registry PROCESS carries (REGISTRY_NAME, a compose mutation in
    # mutate_rendered), so the provisioner must render it into the two allowlists keyed on that name:
    # MAINFRAME_REGISTRY_NAMES (the issuance and operator provisioning gate) and CROSS_TEG_FUND_ORIGIN_ALLOWLIST. Left at its
    # default (the slug), a label other than the slug ("Plum Proof") booted a frame whose own issuance answered 503.
    ctx = prov.FrameTestContext(ts=ts, registry_name=args.name,
                                trust_domain=args.trust_domain,
                                mainframe_display_name=args.frame_label or "")
    # host-driver: both path views are the SAME host path (/host-stack symlink
    # makes the module's container-path assumptions valid on the host too)
    ctx.stack_dir_host = f"{args.stack_root}/{args.name}-{ts}"
    ctx.stack_dir_container = ctx.stack_dir_host
    ctx.cert_writer_image = args.cert_writer_image
    if getattr(args, "registry_workers", 0):   # §NIGHTPROV: the nightly pair takes its tester host's count (the runner's policy)
        ctx.workers_reg = int(args.registry_workers)
    if getattr(args, "bundle_public_url", ""):
        # §HELLOFRAME: the bundle endpoint a FOREIGN peer fetches and the approver hands back in its callback (Phase 3
        # measurement 4: every frame advertised the docker-internal name); the provisioner keeps a value already set
        ctx.frame_local_bundle_endpoint_url = args.bundle_public_url.strip()

    # §SANDBOXSTANDUP 2026-09-03 — the provisioner validates its inputs BEFORE it writes anything
    # (frame_test_provisioner.validate_provisioning_inputs), and the driver never supplied two of
    # them, so `write_stack_files` refused every run:
    #   1. public_hostname — becomes BASE_URL, ALLOWED_ORIGINS and a WebAuthn rp-id candidate.
    #      Derive it from --public-url; a frame without it answers on a host its own credentials
    #      will not validate against.
    #   2. a mail relay — `first_party=True` normally inherits the shared relay via
    #      operator_mail.shared_identity(), but that reads env this HOST script does not carry
    #      (the registry container does). With no relay, require_email_verification=True is the
    #      §OPGUIDE-2 lockout: every self-registered account is permanently locked out.
    #      So: supply FRAME_MAIL_SERVER/ADDRESS/TOKEN to keep verification on (what PRODUCTION
    #      wants), or leave them unset and the frame runs invite-gated with verification OFF
    #      (what a sandbox wants). Never half-configured — the validator refuses that too.
    # findings row 174 — parsed ONCE so the vhost lanes and the JSON entries cannot disagree
    _peer_ledgers: dict = {}
    for spec in (args.peer_ledger or []):
        n, _, prt = str(spec).partition(":")
        if not n.strip() or not prt.strip().isdigit():
            log(f"!! --peer-ledger {spec!r} is not NAME:ES_PORT — ignored")
            continue
        _peer_ledgers[n.strip()] = int(prt)
    args._peer_ledgers = _peer_ledgers
    if _peer_ledgers:
        log(f"peer ledgers: {_peer_ledgers} — console vhost lanes + FRESH_NETWORK_JSON entries")

    ctx.public_hostname = urllib.parse.urlparse(args.public_url).hostname or ""
    # §FRAMELIC (2026-09-07, findings row 125) — TWO NAMES FOR ONE FACT, ONE OF THEM WIRED.
    # `--es-public-url` is REQUIRED and validated hard (https, a real host, refused if it names a
    # production ledger or the frame's own host) — and then it was never handed to the provisioner,
    # which has its own `ctx.event_store_public_url` and falls back to the INTERNAL container name.
    # That fallback is written into the frame's env as EVENT_STORE_PUBLIC_URL, and
    # `cloud_provisioner` hands it to every operator this frame provisions as EVENT_STORE_URL —
    # a name that does not resolve from operator-net. The provisioner WARNED on every standup
    # ("its reactors will report 0 subscriptions"); the warning was true and nobody was listening,
    # because the driver looked like it had already supplied the value under the other name.
    ctx.event_store_public_url = (args.es_public_url or "").strip().rstrip("/")
    _mail = (os.getenv("FRAME_MAIL_SERVER", ""), os.getenv("FRAME_MAIL_ADDRESS", ""),
             os.getenv("FRAME_MAIL_TOKEN", ""))
    if all(_mail):
        ctx.mail_server, ctx.mail_address, ctx.mail_token = _mail
        try:
            ctx.mail_port = int(os.getenv("FRAME_MAIL_PORT", "587"))
        except ValueError:
            ctx.mail_port = 587
        ctx.require_email_verification = True
        log(f"mail relay supplied ({ctx.mail_server}:{ctx.mail_port}) — email verification ON")
    else:
        # findings row 181 — a PRODUCTION posture without a relay is a frame that cannot mail.
        # The else-branch below is correct and stays (verification ON with no relay is the
        # §OPGUIDE-2 lockout), but a production standup that silently lands here comes up
        # mail-dead AND invite-gated while wearing production's limiter and flags, and nothing
        # says so — measured on EU/ASIA, which ran for a day with MAIL_SERVER=mailpit, a host
        # that does not resolve from the frame's own network (row 173). Refuse it at the input
        # instead of discovering it when the first registrant gets no mail.
        if getattr(args, "posture", "") == "production":
            log("!! --posture production requires a mail relay: set FRAME_MAIL_SERVER, "
                "FRAME_MAIL_ADDRESS and FRAME_MAIL_TOKEN (optionally FRAME_MAIL_PORT, default "
                "587). Without them the frame cannot send mail at all — not verification, not "
                "password reset, not frame invitations, not operator applications — and it "
                "would come up invite-gated with verification OFF. Use --posture sandbox for a "
                "frame that is deliberately mail-less.")
            raise SystemExit(2)
        ctx.require_email_verification = False
        log("no FRAME_MAIL_* relay supplied — email verification OFF (invite-gated frame)")
    log(f"public_hostname: {ctx.public_hostname}")
    if args.grant_host_reach:
        ctx.grant_host_reach = True
        ctx.host_reach_confirmation = prov.HOST_REACH_CONFIRMATION_PHRASE
        log("HOST REACH GRANTED — docker.sock + /host-stack + /host-nginx-sites will be mounted "
            "into this frame's registry (required to provision a cloud operator from it)")
    if getattr(args, "tester_self", False) or getattr(args, "grant_host_reach", False):
        try:   # the socket's group on THIS host: the registry (uid 1000) joins it to use the mount
            ctx.docker_socket_gid = str(os.stat("/var/run/docker.sock").st_gid)
        except OSError as exc:
            die(f"the docker socket's group could not be read ({exc}); a tester that cannot docker exec cannot run")
    if getattr(args, "tester_self", False):   # §TESTBED: the socket alone, for a sandbox's own tester
        ctx.grant_docker_socket = True
        ctx.host_reach_confirmation = prov.HOST_REACH_CONFIRMATION_PHRASE
        log("tester (self): the registry gets the docker socket (and nothing else of the host): root on this host, "
            "for a SANDBOX whose tester reaches its own containers")
        # §F6 stage 5 (2026-09-27): the "HOST REACH GRANTED" line used to be printed HERE, in the socket-only branch,
        # and never by --grant-host-reach: every nightly frame's log claimed /host-stack and /host-nginx-sites while
        # its registry held only the tester's socket (measured on nt260927x5a/b). It lives with the grant now.
    elif args.with_operator:
        die("--with-operator needs --grant-host-reach: the operator bundle is built through the "
            "host Docker API, and without it activation silently produces no bundle and the "
            "provision fails with 'Bundle not found at None'.")

    IMAGE_MAP["agentvault2-registry-test:latest"] = args.registry_image
    IMAGE_MAP["agentvault2-teg-layer-test:latest"] = args.teg_image
    IMAGE_MAP["agentvault2-event-store-test:latest"] = args.es_image
    log(f"images: registry={args.registry_image} teg={args.teg_image} event_store={args.es_image} cert_writer={args.cert_writer_image}")
    # §ONESHOT P2.1 — ONE flag names the peer; every peer-dependent value is READ from its stack (never
    # typed twice: the FX peer spec, the router DID, the trusted domain, the ledger lane, the identity net).
    for _pd in (getattr(args, "federate_with", None) or []):
        _pf = federate.frame_facts(_pd)
        if not (args.fx_peer or "").strip() and _pf.get("router_did", "").startswith("did:") and _pf.get("ticker") and _pf.get("es_public_url"):
            args.fx_peer = f"{_pf['name']}:{_pf['ticker']}:{_pf['es_public_url']}"
            args.fx_peer_router_did = _pf["router_did"]
            log(f"federate-with: FX peer derived from {_pf['name']}'s stack ({_pf['ticker']})")
        elif not (args.fx_peer or "").strip():
            log(f"federate-with: {_pf['name']} has no @fx_router DID in its env — no FX peer rendered for it (the federate step says so too)")
        if _pf.get("td") and _pf["td"] not in [d.strip() for d in (args.extra_trusted_spiffe_domains or "").split(",")]:
            args.extra_trusted_spiffe_domains = ",".join([x for x in [(args.extra_trusted_spiffe_domains or "").strip(), _pf["td"]] if x])
        if _pf.get("es_port") and _pf["name"] not in (args._peer_ledgers or {}):
            args._peer_ledgers[_pf["name"]] = int(_pf["es_port"])
            log(f"federate-with: peer ledger lane {_pf['name']}:{_pf['es_port']} derived from its compose")
        if not args.identity_net and _pf.get("identity_net"):
            args.identity_net = _pf["identity_net"]; args.identity_net_external = True
            log(f"federate-with: identity net {_pf['identity_net']} taken from {_pf['name']} (external)")
        elif args.identity_net and _pf.get("identity_net") and args.identity_net != _pf["identity_net"]:
            die(f"--identity-net {args.identity_net} differs from {_pf['name']}'s {_pf['identity_net']}: a pair must share one identity net")
    if (args.fx_peer or "").strip():
        _parts = args.fx_peer.strip().split(":", 2)
        if len(_parts) != 3 or not all(_parts) or not _parts[2].startswith("https://"):
            die(f"--fx-peer must be SLUG:CCY:https://<peer es>, got {args.fx_peer!r}")
        ctx.fx_peer_slug, ctx.fx_peer_currency, ctx.fx_peer_es_url = _parts[0].lower(), _parts[1].upper(), _parts[2].rstrip("/")
        # findings row 191 — REFUSE an FX peer with no router DID rather than render a half peer.
        # The half-rendered entry is what took three live attempts to diagnose, and each failure
        # named a different cause; a frame that declares an FX partner it cannot pay is the
        # §FXSTRAND shape again (a flag whose precondition nobody supplied).
        ctx.fx_peer_router_did = (args.fx_peer_router_did or "").strip()
        if not ctx.fx_peer_router_did.startswith("did:"):
            die("--fx-peer needs --fx-peer-router-did <the PEER frame's @fx_router DID>: the FX core "
                "swap sends to that DID, so without it the peer entry is a route to nobody. Read it "
                "from the peer's GET /api/v1/teg/fx/route/status (`router_did`).")
        log(f"fx peer: {ctx.fx_peer_slug} ({ctx.fx_peer_currency}) es={ctx.fx_peer_es_url} "
            f"router={ctx.fx_peer_router_did[-12:]}")
    if args.extra_trusted_spiffe_domains.strip():
        ctx.extra_trusted_spiffe_domains = [d.strip() for d in args.extra_trusted_spiffe_domains.split(",") if d.strip()]
        log(f"extra trusted spiffe domains: {ctx.extra_trusted_spiffe_domains}")
    if args.identity_net:
        ctx.identity_net_name = args.identity_net
        ctx.identity_net_external = bool(args.identity_net_external)
        log(f"identity network: {ctx.identity_net_name} (external={ctx.identity_net_external})")

    ctx.finalize_derivations()

    return ctx


def posture_gate(args):
    """§ONESHOT P2.4 — runbook §4 (the acceptance shape) as a gate: the limiter posture the frame CLAIMS, the
    appended XFF element, and the five public rails. Presented as an EXTERNAL caller (a bare loopback call is
    the exempt internal lane and correctly returns no header)."""
    port = PORTS["registry"]
    # measured 2026-09-12 on sbx-alpha, sbx-beta and the proof frame: a BYPASSED limiter (`limiter.enabled =
    # False`, §RATEFIX) sends NO header at all; the doctrine's "999999" is the pre-§RATEFIX monkey-patch era.
    # Production: 1200 (measured on EU). Anything else is a posture the frame does not carry.
    want = ("1200",) if getattr(args, "posture", "") == "production" else ("none", "999999")
    r = subprocess.run(["curl", "-sD-", "-o", "/dev/null", "--max-time", "10", "-H", "X-Real-IP: 198.51.100.7",
                        f"http://127.0.0.1:{port}/health"], capture_output=True, text=True)
    got = ""
    for line in r.stdout.splitlines():
        if line.lower().startswith("x-ratelimit-limit:"):
            got = line.split(":", 1)[1].strip()
    if (got or "none") not in want:
        die(f"posture gate: x-ratelimit-limit={got or 'none'} for an external caller, the {args.posture} posture wants {'/'.join(want)} "
            f"(1200 = limits live; none = SANDBOX_BYPASS_RATE_LIMIT, the limiter disabled) — the frame does not carry the posture it claims")
    since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 2))
    subprocess.run(["curl", "-s", "-o", "/dev/null", "--max-time", "10", "-H", "X-Forwarded-For: 203.0.113.77, 198.51.100.50",
                    f"http://127.0.0.1:{port}/health"], capture_output=True)
    time.sleep(1)
    logs = subprocess.run(["docker", "logs", "--since", since, f"{args.name}-registry"], capture_output=True, text=True)
    hits = (logs.stdout + logs.stderr).count("198.51.100.50")
    if hits < 1:
        die("posture gate: the APPENDED X-Forwarded-For element (198.51.100.50) never reached the log — the registry trusts "
            "the element the caller wrote (§XFFTRUST); gunicorn's FORWARDED_ALLOW_IPS or the vhost is wrong")
    for rail in ("agent-cards/discover?limit=1", "agent-cards/?limit=1", "public/registry-config", "federation/registries", "reputation-bond/config"):
        st, _ = http("GET", f"http://127.0.0.1:{port}/api/v1/{rail}", timeout=25)
        if st != 200:
            die(f"posture gate: public rail /{rail} answered {st} (§DISCECHO: /health was 200 the whole time)")
    log(f"posture gate: limiter {got or 'none'} ({args.posture}), XFF appended element logged ×{hits}, five public rails 200")


def deactivate_self_echo_rows(args, op_slugs):
    """§ONESHOT P2.4 — runbook §8.5 as code: the parent's registry-card fan-out carries an operator's OWN card back
    and the operator inserts its own name as a `discovered` peer, then dials itself (401, parked). Deactivate it
    through the admin rail on the OPERATOR, never delete (a deleted row is re-inserted by the next fan-out). The
    row appears only after a fan-out cycle, so `none yet` is a state, not a pass."""
    if not op_slugs:
        return
    path = os.path.join(extras.SECRETS_DIR, f".{args.name.lower()}_ops.secret.json")   # §FRAMEPROV P1: --secrets-dir
    try:
        creds = json.load(open(path))
    except OSError:
        log(f"self-echo: {path} not readable — the operators' rows were NOT checked"); return
    for slug in op_slugs:
        c = creds.get(slug) or {}
        port = c.get("registry_port")
        if not (port and c.get("admin_email") and c.get("admin_password")):
            log(f"self-echo: no operator admin record for {slug} — NOT checked"); continue
        b = f"http://127.0.0.1:{port}"
        _tok, st = _op_admin_login(b, c["admin_email"], c["admin_password"])
        if not _tok:
            log(f"self-echo: {slug} admin login {st} after two minutes — NOT checked"); continue
        H = {"Authorization": f"Bearer {_tok}"}
        # the row appears with the parent's next fan-out (measured: ONE second after provisioning on juiceop,
        # and the gate had already looked) — so look for up to one fan-out cycle before concluding "none"
        mine = []
        for _attempt in range(7):
            st, peers = http("GET", f"{b}/api/v1/admin/federation/peers/all", headers=H, timeout=60)
            items = (peers.get("items") or []) if isinstance(peers, dict) else []
            mine = [p for p in items if isinstance(p, dict) and str(p.get("name", "")).lower() == slug.lower()
                    and str(p.get("status", "")).upper() == "ACTIVE"]
            if mine:
                break
            time.sleep(25)
        if not mine:
            log(f"self-echo: {slug} has no active row naming itself within a fan-out cycle (150 s) — none to deactivate; "
                f"the row can still arrive later (the product inserts it, runbook §8.5)"); continue
        for p in mine:
            st, _ = http("POST", f"{b}/api/v1/admin/federation/peers/{p['id']}/deactivate?reason=self_echo_row_from_parent_fanout",
                         {}, headers=H, timeout=30)
            log(f"self-echo: {slug} row {p['id']} ({p.get('peer_type')}) deactivated: HTTP {st}")


class StepTracker:
    """§FRAMEPROV P1: post_boot's do(step), plus what a machine needs to follow a run and resume it safely.

    do(step) answers what the inline do() answered (--resume-from, --resume-until), and also: the first True for a step
    closes the step before it (end ok, added to steps_done, on_done persists the run meta) and opens this one; a False is
    recorded once as a skip with its reason; and a step in MINTING_STEPS that an earlier pass completed answers False,
    so a resume never issues twice."""
    MINTING_STEPS = ("emission", "admin")

    def __init__(self, steps, resume_from=None, until=None, done=(), progress=None, on_done=None):
        self.steps = list(steps)
        self.resume_from = resume_from
        self.until = until
        self.done = list(done or [])
        self.progress = progress
        self.on_done = on_done
        self.current = None
        self._skipped = set()

    def _refusal(self, step):
        i = self.steps.index(step)
        if self.until and i > self.steps.index(self.until):
            return f"after --resume-until {self.until}"
        if self.resume_from is not None and i < self.steps.index(self.resume_from):
            return f"before --resume-from {self.resume_from}"
        if step in self.MINTING_STEPS and step in self.done:
            return "completed in an earlier pass, and it issues units: a resume never runs it twice"
        return ""

    def do(self, step):
        reason = self._refusal(step)
        if reason:
            if step not in self._skipped:
                self._skipped.add(step)
                if self.progress is not None:
                    self.progress.skip(step, reason)
            return False
        if self.current != step:
            self._close()
            self.current = step
            if self.progress is not None:
                self.progress.start(step)
        return True

    def _close(self):
        if self.current is None:
            return
        if self.current not in self.done:
            self.done.append(self.current)
            if self.on_done is not None:
                self.on_done(list(self.done))
        if self.progress is not None:
            self.progress.end("ok")
        self.current = None

    def finish(self):
        self._close()


def _write_meta(ctx, meta):
    """The run meta, rewritten whole (the file every lifecycle command keys on)."""
    with open(os.path.join(ctx.stack_dir_host, "hetzner-demo-run.json"), "w") as f:
        f.write(json.dumps(meta, indent=2))


def _mark_meta(ctx, meta, key):
    """§FRAMEPROV P1: record a one-time act (a mint) the moment it happened, so a resume can see it."""
    meta[key] = True
    _write_meta(ctx, meta)


def _mark_minted(ctx, meta, total, target):
    """§FRAMESHOWCASE (2026-09-14): the show issuance's running total after every accepted piece, and `show_minted` only once
    the whole genesis supply is in, so a resume sees exactly what landed and issues the rest."""
    meta["show_minted_amount"] = str(total)
    if Decimal(str(total)) >= Decimal(str(target)):
        meta["show_minted"] = True
    _write_meta(ctx, meta)


def register_entries_before_compose(ctx, prov, args, attempts=6, pause=10):
    """§MTLSHOPS (2026-09-15, b5): the frame's SPIRE entries, registered before a `compose up` that has to converge.

    Since T2 the kit (opa, prometheus, alertmanager, grafana-egress), nginx-ntfy, the auditor and nginx-auditor wait
    service_healthy on the kit or auditor cert-writer, and since S5 the broker waits on redpanda-tls. Each is healthy only
    once its SVID exists, and an SVID exists only once its entry does. `compose up -d` waits on such a dependency with no
    end (lab, compose v2: killed at 240 s with the dependant still Created; the same up converged in 1 s once the
    dependency could become healthy). The entries used to be registered only in post_boot's spire step, after a reconcile
    that needs every service running, so a fresh standup could not complete. This starts the SPIRE server and agent alone
    (neither waits on an SVID) and registers the entries, created or updated where they exist (the spire step runs the same
    call again). An entry the server refused refuses the standup at once, naming it: the service behind it would wait for
    ever, and asking again does not change the server's answer. Only an agent that has not attested yet is asked again."""
    stack = ctx.stack_dir_host
    spire = [f"{args.name}-spire-server", f"{args.name}-spire-agent"]
    r = subprocess.run(["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock",
                        "-v", f"{stack}:{stack}", "-w", stack, "docker:cli", "docker", "compose",
                        "-f", "docker-compose.frame-test.yml", "--env-file", ".env.frame-test", "up", "-d", *spire],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        out = ((r.stderr or "") + (r.stdout or "")).strip()
        return False, f"`compose up -d {' '.join(spire)}` answered rc {r.returncode}: {out[-240:]}"
    detail = ""
    for _ in range(attempts):
        ok, detail = prov.register_test_frame_spire_entries(ctx)
        if ok and "FAILED" not in detail:
            return True, detail
        if ok:
            return False, f"the SPIRE server refused an entry: {detail}"
        time.sleep(pause)
    return False, f"the entries were not registered after {attempts} tries: {detail}"


def post_boot(args, ctx, meta, resume_from=None, prov=None):
    """§BATCH10 — every step from the compose reconcile on, in order. `resume_from` names the first step to run again.

    §ONESHOT (2026-09-12) — WHERE THE RUNBOOK'S SECTIONS LIVE NOW (RUNBOOK_2026-09-05_FRESH_FRAME_STANDUP.md):
      preflight()      §0.4 ports · §0.5 images (`:latest` refused on production) · §0.6 headroom (load < 40, ≥ 15 GB,
                       the sim, disk ≥ 60 GB) · §10.1 the identity net exists · §11.1 the AIO ceiling · the sidecar
                       manifest when --wire-prod · the peer stack when --federate-with · §1 the flag refusals in main()
      compose/spire    §11.2 · seed/login/emission  §11.2 (the Δ gate is emission_gate)
      vhosts           §0.2 (--acme) · §0.3 (--render-vhosts) · §9.2 the per-net federated bundle (sidecars.register_bundle)
      admin            §11.2 the card, logo, issuance · jurisdiction  §12b service accounts · §12 the FX router · §12c the licence
      federate         §9.3–9.6 · §10.2 · §11.3 — standup_federate.py (--federate-with), before the operators
      operators        §5 · §8.2–8.4 · §9.8 · §15.5–15.6 · canary  §11.2 · wire  §5b · §10.3 · §15.4 (sidecars.wire)
      mtls             §15 census · §4 posture (posture_gate) · §16.6 card addresses · §8.5 self-echo rows
    Still a hand or his: §5 `docker login images.theprotocol.cloud` on the host · §6 teardown (teardown_hetzner_frame.sh,
    which now unwires) · §9.7/12 the FX dust proofs (scratchpad) · §10.3 the registry-a recreate (deliberate) ·
    §15.7 one published agent per operator (needs a bond) · §16.8 Sheldon.
    (an interrupted standup resumes here instead of a full redo: --resume-stack-dir + --resume-from)."""
    _STEPS = ["compose", "spire", "seed", "login", "emission", "vhosts", "admin", "jurisdiction", "federate", "operators", "canary", "wire", "mtls"]
    _until = getattr(args, "resume_until", None)

    def _persist_steps(done):
        meta["steps_done"] = done
        _write_meta(ctx, meta)
    # §FRAMEPROV P1: the same answers as the old inline do(), plus progress events, steps_done in the run meta, and a
    # resume that never re-runs a step that issues once an earlier pass completed it (StepTracker.MINTING_STEPS)
    tracker = StepTracker(_STEPS, resume_from=resume_from, until=_until, done=meta.get("steps_done") or [],
                          progress=PROGRESS, on_done=_persist_steps)
    do = tracker.do
    # §RECONCILE — the frame needs the same loop the child operator got.
    # `compose up` ABORTS THE WHOLE RUN when any dependency's health-wait times
    # out. Observed live at host load ~110: "dependency failed to start:
    # container <frame>-redpanda is unhealthy" left the stack at 7/13 and the
    # driver treated a slow bus as a dead frame. Nothing was broken; compose
    # simply gave up early. Re-issuing `up -d` once the slow service reports
    # healthy completes the stack, so retry before declaring anything.
    def _frame_up():
        r = subprocess.run(["docker", "ps", "--format", "{{.Names}}",
                            "--filter", f"name={args.name}-"],
                           capture_output=True, text=True)
        return len([x for x in (r.stdout or "").split() if x])

    # §PROVSHOW (2026-09-15): the reconcile asks the RENDERED compose which services must be up, never a literal count. The
    # first standup since the kit and K1 (lantern) aborted on "container lantern-redpanda is unhealthy" (the broker restarts
    # until its cert-writer has written the SVID) and left redpanda-init, the store, its sidecar, the Directory and its
    # sidecar Created; 20 other containers ran, 20 >= 13, so the old loop judged the stack complete and never re-issued
    # `up -d`, and the Directory gate timed out 3 minutes later blaming SPIRE.
    _expected = expected_frame_services(os.path.join(ctx.stack_dir_host, "docker-compose.frame-test.yml"),
                                        os.path.join(ctx.stack_dir_host, ".env.frame-test"))

    _project = os.path.basename(ctx.stack_dir_host.rstrip("/"))

    def _gaps():
        if not _expected:
            return None
        g = frame_stack_gaps(_expected, frame_container_states(args.name, _project))
        seen = {svc for svc, _ in g}
        # §TESTBED (2026-09-19): a container that runs without its network is not up either (detachment_of)
        return g + [(svc, why) for svc, why in sorted(frame_container_detachments(args.name, _project).items())
                    if svc in _expected and svc not in seen]

    def _complete():
        g = _gaps()
        return g == [] if g is not None else _frame_up() >= 13

    # §MTLSHOPS (2026-09-15): the reconcile converges only once the SPIRE entries exist (register_entries_before_compose). A
    # fresh run registered them before its compose up and recorded it; a resume of a run with no such record registers them
    # here, before the loop re-issues compose up.
    if do("compose") and not meta.get("spire_entries_before_compose"):
        ok, detail = register_entries_before_compose(ctx, prov, args)
        if not ok:
            die(f"spire entries before the reconcile: {detail}")
        log(f"spire entries before the reconcile: {detail}")
        _mark_meta(ctx, meta, "spire_entries_before_compose")
    for attempt in range(1, 5):
        if not do("compose"):
            break
        if _complete():
            break
        g = _gaps()
        what = ", ".join(f"{svc} {why}" for svc, why in g[:10]) if g else f"{_frame_up()}/13 up (the compose's service list could not be read)"
        detached = [svc for svc, why in (g or []) if why.startswith("running with")]
        log(f"  reconcile pass {attempt}: not up: {what} — re-issuing `compose up -d`"
            + (f", recreating {', '.join(detached)}" if detached else ""))
        subprocess.run(
            ["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock",
             "-v", f"{ctx.stack_dir_host}:{ctx.stack_dir_host}", "-w", ctx.stack_dir_host,
             "docker:cli", "sh", "-c", reconcile_command(detached)],
            capture_output=True, text=True, timeout=900)
        if _complete():
            break
        time.sleep(45)
    _final, _left = _frame_up(), _gaps()
    if _expected:
        log(f"  frame containers running: {_final}; services not up of {len(_expected)}: {_left or 'none'}")
    else:
        log(f"  frame containers up: {_final}/13 (the compose's service list could not be read)")
    if (_left if _expected else _final < 13):
        die(f"frame stack incomplete after reconcile ({_left if _expected else f'{_final}/13'}) — check "
            f"`docker ps -a --filter name={args.name}-` before retrying")
    if do("spire"):
        ok, detail = prov.register_test_frame_spire_entries(ctx)
        log(f"spire entries: {ok} {detail}")

    if not wait_for("registry /health",
                    lambda: _registry_boot_probe(args.name, PORTS['registry']),
                    tries=100, sleep=3):
        die("registry never became healthy — inspect docker logs "
            f"{args.name}-registry (first boot replays ~136 migrations)")
    kit_gates(ctx, args)
    kit_kafka_gate(ctx, args)   # §SOVKIT K1: the ledger bus is the store's alone, measured
    kit_data_tls_gate(ctx, args)   # §MTLSHOPS T3: the data services take TLS only, measured at both ends

    # §R1 — the SHARED template's startup chain is
    #   … && python -m test_seed && python -m operator_seed || true && … uvicorn
    # `test_seed` is SANDBOX-specific and crashes on a fresh sovereign frame
    # (psycopg2 StringDataRightTruncation: value too long for varchar(32)), which
    # aborts the && chain BEFORE operator_seed — and the trailing `|| true` masks
    # the whole thing, so the registry comes up HEALTHY with an EMPTY developers
    # table and every login 401s. Run the (idempotent) seed ourselves rather than
    # editing the shared template that the sandbox lifecycle tests also render.
    seed = subprocess.run(
        ["docker", "exec", f"{args.name}-registry", "sh", "-c",
         "cd /app && PYTHONPATH=/app/src python -m agentvault_registry.operator_seed"],
        capture_output=True, text=True, timeout=120) if do("seed") else subprocess.CompletedProcess([], 0, "already seeded (resume)", "")
    log(f"operator_seed: rc={seed.returncode} "
        f"{(seed.stdout or seed.stderr or '').strip().splitlines()[-1][:120] if (seed.stdout or seed.stderr).strip() else ''}")
    if seed.returncode != 0:
        die(f"operator admin seed failed: {(seed.stderr or '')[:300]}")

    jwt = admin_login(args)
    log("operator admin login OK (all admin sub-flags seeded by operator_seed)")

    if do("emission"):
        emission_gate(args, jwt, mint=not meta.get("canary_minted"), on_minted=lambda: _mark_meta(ctx, meta, "canary_minted"))

    # §FRAMEPROV P1: the push port the COMPOSE publishes is the provisioner's (ctx.port_ntfy, env default 8199); this
    # line's own default was 8399, so a run without FRAME_TEST_PORT_NTFY rendered a push vhost to a port nothing served
    _ports_full = dict(PORTS); _ports_full["push"] = int(getattr(ctx, "port_ntfy", 0) or os.getenv("FRAME_TEST_PORT_NTFY", "8399"))
    # §ONESHOT P2.2 — the ES vhost verifies peers against the federated bundle OF THIS FRAME'S IDENTITY
    # NET (one file per net, refreshed every 5 minutes; F1 in FINDINGS_2026-09-12_ONESHOT.md). It must
    # exist before nginx -t reads the vhost, so the frame's bundle is registered here, not at `wire`.
    _bundle_pem = extras.FEDERATED_BUNDLE_PEM
    # §HELLOFRAME (own-host, 2026-09-18, the fresh session's read): a stranger's host has no host nginx and no sidecar manifest;
    # the ES gateway is the frame's own compose sidecar, so neither the manifest registration nor the one-shot export into
    # /etc/nginx belongs here (it wrote /etc/nginx/<name>-spire-bundle.pem on the stranger's host and warned about --wire-prod).
    if do("vhosts") and getattr(ctx, "identity_net_name", None) and not getattr(args, "own_host", False):
        try:
            _m = sidecars.load()
            _bundle_pem = sidecars.register_bundle(_m, args.name, ctx.identity_net_name, log=log)["federated_pem"]
        except sidecars.SidecarsMissing as _e:
            log(f"!! {_e} — falling back to the one-shot bundle export (it rots at the next CA rotation)")
            export_spire_bundle(args)
    if do("vhosts") and getattr(args, "render_vhosts", False):   # §BATCH10 finding 2 / runbook §0.2-0.3 as code
        # §SOVKIT T2/T5: the es vhost includes /etc/nginx/snippets/es-proxy-auth-<name>.conf, so the snippet (600, the
        # frame's ES_PROXY_TRUST_SECRET, never logged) exists BEFORE nginx -t reads the vhost.
        _esk = _env_kv(open(os.path.join(ctx.stack_dir_container, ".env.frame-test")).read()).get("FT_ES_ES_PROXY_TRUST_SECRET", "")
        log(f"es proxy marker snippet: {extras.write_es_proxy_snippet(args.name, _esk)} (600)")
        extras.render_vhosts(args.name, _ports_full, with_tls=False,
                             directory_upstream=args.directory_upstream,
                             peer_ledgers=getattr(args, '_peer_ledgers', {}), bundle_pem=_bundle_pem)
        if getattr(args, "acme", False):
            extras.issue_cert(args.name)
        extras.render_vhosts(args.name, _ports_full,
                             with_tls=os.path.exists(frame_tls_cert(args.public_url)),
                             directory_upstream=args.directory_upstream,
                             peer_ledgers=getattr(args, '_peer_ledgers', {}), bundle_pem=_bundle_pem)
    if do("vhosts") and args.enable_vhost:
        enable_vhosts(args)
        wait_for("public URL", lambda: _h(f"{args.public_url}/health"), tries=10, sleep=2)

    if args.admin_pass and do("admin"):
        admin_pass(args, jwt, mint=not meta.get("show_minted"), on_minted=lambda total: _mark_minted(ctx, meta, total, args.mint),
                   minted_before=meta.get("show_minted_amount", "0"))
    if args.admin_pass and do("jurisdiction"):
        _reg = f"http://127.0.0.1:{PORTS['registry']}"; _H = {"Authorization": f"Bearer {jwt}"}
        _jpath = getattr(args, "jurisdiction_json", None)
        if _jpath:
            extras.put_jurisdiction(_reg, _H, _jpath)
        else:
            # §FRAMELIC / row 64 — his "jurisdiction everything aprove as DEMO similar to
            # registry-a but you can refine". registry-a publishes four regulated actions in
            # SHADOW plus four attestations with reference ids and evidence hashes; a fresh
            # frame published the profile NAME and nothing else. Born complete, and refined:
            # the authority is named for THIS frame, and the reference ids carry it.
            _authority = f"{args.frame_label} Demo Authority"
            _jurisdiction_label = f"{args.frame_label} (demo)"
            _profile = extras.demo_jurisdiction_profile(
                frame_label=args.frame_label,
                profile_name=os.getenv("FRAME_JURISDICTION_PROFILE_NAME", f"{args.name}-provider-no-fiat"),
                jurisdiction_label=_jurisdiction_label, authority=_authority,
            )
            _tmp = f"/tmp/{args.name}-jurisdiction.json"
            open(_tmp, "w").write(json.dumps(_profile))
            extras.put_jurisdiction(_reg, _H, _tmp)
            os.unlink(_tmp)
            extras.put_regulatory_authorizations(_reg, _H, extras.demo_authorizations(
                frame_label=args.frame_label, jurisdiction_label=_jurisdiction_label,
                authority=_authority))
        # TIER 1 item 1 (2026-09-08) — persist the FRAME ADMIN where every other frame credential
        # lives. It was never missing: it is FIRST_ADMIN_PASSWORD in the stack's .env.frame-test
        # (600), which prod_seed.py seeds the account from. It was merely not in sessionlogs2026/,
        # so the evening a session needed ASIA's admin it found only a stale rehearsal-pair file,
        # concluded the account had none, and reset both frames to recover access it already had.
        try:
            _fa_path = extras.write_frame_admin_secret(
                args.name, args.admin_email, args.admin_password,
                registry_port=PORTS.get("registry"), domain=getattr(args, "domain", None),
                stack_dir=ctx.stack_dir_host,
            )
            log(f"frame admin written to {_fa_path} (600)")
        except Exception as _fa_e:  # noqa: BLE001 — never fail a standup over a convenience copy
            log(f"!! frame admin secret write failed: {_fa_e} — the value is still in .env.frame-test")

        # HIS DECISION 2026-09-07 — the Commander onboards nothing. Four purpose-named service
        # developers, each with only its rail's authority and its agents hidden from discovery.
        _svc: dict = {}
        if getattr(args, "service_accounts", True):
            _svc = extras.create_service_accounts(_reg, _H, args.name)
            if _svc:
                _svc_path = os.path.join(extras.SECRETS_DIR, f".{args.name}_service_accounts.secret.json")   # §FRAMEPROV P1: --secrets-dir
                open(_svc_path, "w").write(json.dumps(_svc, indent=1))
                os.chmod(_svc_path, 0o600)
                log(f"service accounts: {len(_svc)} written to {_svc_path} (600)")
        # ── findings row 191 — MINT THE FX ROUTER, THEN TURN ITS FLAG ON ────────────────
        # §FXSTRAND made the template honest (FX_ROUTE_ENABLED=false until the identity exists,
        # CI gate R9). This is the half that lets it be true: the standup CREATES the agent the
        # route engine needs, writes its DID, and flips the flag in the same pass — so a frame is
        # never again born declaring a capability whose precondition nobody supplied.
        # Ordered BEFORE `operators` on purpose: an operator inherits the gateway DID from here.
        if getattr(args, "fx_router", True) and _svc.get("svc-provisioning"):
            _sp = _svc["svc-provisioning"]
            _st, _lr = extras.http("POST", f"{_reg}/api/v1/auth/login",
                                   {"username": _sp["email"], "password": _sp["password"]}, form=True)
            _sjwt = (_lr or {}).get("access_token") if isinstance(_lr, dict) else None
            if not _sjwt:
                log(f"!! fx_router: svc-provisioning login {_st} — route engine stays OFF")
            else:
                _fxdid = extras.mint_fx_router(_reg, {"Authorization": f"Bearer {_sjwt}"},
                                               args.name, args.ticker, public_url=args.public_url)
                if _fxdid:
                    _envp = os.path.join(ctx.stack_dir_container, ".env.frame-test")
                    _txt = open(_envp).read()
                    for _k, _v in (("FT_REG_FX_ROUTER_DID", _fxdid), ("FT_REG_FX_ROUTE_ENABLED", "true")):
                        if re.search(rf"(?m)^{_k}=.*$", _txt):
                            _txt = re.sub(rf"(?m)^{_k}=.*$", f"{_k}={_v}", _txt)
                        else:
                            _txt += f"\n{_k}={_v}\n"
                    open(_envp, "w").write(_txt)
                    # read back — a sed/regex that matched nothing exits happy (findings row 189)
                    _ok = all(f"{_k}={_v}" in open(_envp).read()
                              for _k, _v in (("FT_REG_FX_ROUTER_DID", _fxdid), ("FT_REG_FX_ROUTE_ENABLED", "true")))
                    if not _ok:
                        die("fx_router: the env carrier did not take the DID — refusing to claim FX is on")
                    subprocess.run(
                        ["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock",
                         "-v", f"{ctx.stack_dir_host}:{ctx.stack_dir_host}", "-w", ctx.stack_dir_host,
                         "docker:cli", "sh", "-c",
                         "docker compose -f docker-compose.frame-test.yml --env-file .env.frame-test "
                         f"up -d --no-deps --force-recreate {args.name}-registry"],
                        capture_output=True, text=True, timeout=900)
                    wait_for("registry after fx wiring", lambda: _h(f"http://127.0.0.1:{PORTS['registry']}/health"),
                             tries=40, sleep=5)
                    log(f"FX route engine ON for {args.name} (router {_fxdid[-12:]})")
        # §SHOWCASEPAY (2026-09-26) — THE SHOWCASE'S PAYER. A frame that runs showcase agents pays for its own demo
        # calls. No standup ever created this identity, so on EU and ASIA every call from /services, the runner embedded
        # in /blueprints, the landing page and /monetize answered 402 (the rail's payer login failed, no token, the
        # agent refused) and the relay it fell back to names api.theprotocol.cloud, which since §APEXEU is EU itself.
        # Created by svc-provisioning, floated from the treasury through the canonical fund rail (FLOW 4), and its
        # credential written to the env file the registry alone reads, then dropped from memory.
        if getattr(args, "showcase_catalog_json", None) and _svc.get("svc-provisioning") \
                and Decimal(str(getattr(args, "showcase_payer_float", "0") or "0")) > 0:
            _sp = _svc["svc-provisioning"]
            _st, _lr = extras.http("POST", f"{_reg}/api/v1/auth/login",
                                   {"username": _sp["email"], "password": _sp["password"]}, form=True)
            _pjwt = (_lr or {}).get("access_token") if isinstance(_lr, dict) else None
            _payer = extras.mint_showcase_payer(_reg, {"Authorization": f"Bearer {_pjwt}"}, args.name, args.ticker,
                                                public_url=args.public_url) if _pjwt else {}
            if not _payer:
                log(f"!! showcase payer not created (svc-provisioning login {_st}): the showcase's calls will answer 402")
            else:
                _float = str(args.showcase_payer_float)
                extras.fund_agent_in_pieces(_reg, _H, _payer["did"], _float, _float, f"showcase-payer-{args.name}")
                _envp = os.path.join(ctx.stack_dir_container, ".env.frame-test")
                _lines = extras.showcase_payer_env_lines(_payer)
                _txt = open(_envp).read()
                for _k, _v in _lines:
                    _txt = upsert_env_line(_txt, _k, _v)
                open(_envp, "w").write(_txt)
                _back = open(_envp).read()
                if not all(re.search(rf"(?m)^{re.escape(_k)}={re.escape(_v)}$", _back) for _k, _v in _lines):
                    die("showcase payer: the env carrier did not take the payer — refusing to claim the showcase works")
                _payer, _lines = None, None   # the credential lives in the env file now, and only there
                subprocess.run(
                    ["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock",
                     "-v", f"{ctx.stack_dir_host}:{ctx.stack_dir_host}", "-w", ctx.stack_dir_host,
                     "docker:cli", "sh", "-c",
                     "docker compose -f docker-compose.frame-test.yml --env-file .env.frame-test "
                     f"up -d --no-deps --force-recreate {args.name}-registry"],
                    capture_output=True, text=True, timeout=900)
                wait_for("registry after the showcase payer", lambda: _h(f"http://127.0.0.1:{PORTS['registry']}/health"),
                         tries=40, sleep=5)
                log(f"showcase payer wired for {args.name} (float {_float} {args.ticker})")
        extras.version_gate(_reg, args.registry_image)   # §BATCH10 finding 12: the card reports the image's own constant

    # §ONESHOT P2.1 (2026-09-12) — federate with each named peer, BEFORE the operators so an operator
    # born here inherits the federation (federation_from_spire_server); the peer's operators existed at
    # its approve and the approve pass federated their entries. The step does the whole post-approve
    # state on BOTH frames (see standup_federate.py) and refuses unless the three layers verify.
    if do("federate") and getattr(args, "federate_with", None):
        # the peer's approve dials THIS frame's federation address (https://<host>:8443) through the host's
        # stream SNI map; the line is written at `wire`, which runs AFTER this step — so write it now
        # (idempotent; `wire` writes it again as a no-op). Without it the dial falls through to Frame A's nginx.
        if wires(args, "sni"):
            extras.sni_route(args.name, PORTS["nginx_fed"] if "nginx_fed" in PORTS else int(os.getenv("FRAME_TEST_PORT_NGINX_FED", "30663")))
        _fed = federate.run(args, ctx, meta, PORTS, log_fn=log)
        meta["federated_with"] = sorted(_fed.get("peers", {}).keys())
        open(os.path.join(ctx.stack_dir_host, "hetzner-demo-run.json"), "w").write(json.dumps(meta, indent=2))

    op_result = None
    _ops_done = [x for x in (meta.get("operator_slugs") or []) if x]   # a resumed run already has some
    # §ONESHOT (2026-09-12) — the operators' secret file is PER RUN: it accumulated the dead operators of
    # every earlier frame of the same name (juiceop-a/-b/-b-owner from 09-05), which a reader then treated
    # as this frame's. A fresh run (not a resume) parks the old file beside itself and starts clean.
    if do("operators") and resume_from is None:
        _osf = os.path.join(extras.SECRETS_DIR, f".{args.name.lower()}_ops.secret.json")   # §FRAMEPROV P1: --secrets-dir
        if os.path.exists(_osf):
            os.replace(_osf, f"{_osf}.bak-pre-{meta.get('ts', 'run')}"); log(f"operators secret file parked as .bak-pre-{meta.get('ts', 'run')} (a fresh run starts clean)")
    # §FRAMELIC (2026-09-07, findings row 158) — before a single operator is provisioned, prove
    # this frame actually HOLDS its SPIFFE identity. The registry races its own SPIRE agent at
    # first boot, loses by ~12 seconds, falls back to mock SVIDs and latches: the frame then looks
    # perfectly healthy and federates with nobody. Placed here because an operator provisioned
    # under a mock-identity parent inherits a trust relationship its parent cannot use.
    if do("operators"):
        if not extras.assert_real_svid(args.name, ctx.stack_dir_host, log=log):
            die("frame registry is running on MOCK SVIDs — it cannot present a client certificate, "
                "so every federation call will be refused with 400 by the peer's mTLS edge. "
                "Refusing to provision operators under an identity-less frame.")

    if do("operators") and getattr(args, "operators_json", None):   # §BATCH10: every operator, in order, its secrets in ONE shape, its card location set
        _ops = json.loads(open(args.operators_json).read()) if os.path.exists(args.operators_json) else json.loads(args.operators_json)
        for _op in _ops:
            if resume_from is not None and _op["slug"] in _ops_done:
                # §FRAMEPROV P1: an operator an earlier pass provisioned (run meta) is never provisioned twice on a
                # resume; its mTLS gate is asked again
                log(f"  operator {_op['slug']}: provisioned in an earlier pass (run meta); its mTLS gate is asked again, the provision is not")
                extras.assert_operator_mtls(_op["slug"], log=log)
                continue
            args.with_operator = True; args.operator_slug = _op["slug"]; args.cloud_port_base = int(_op["port_base"])
            op_result = provision_child_operator(args, jwt)
            extras.ops_secret_file(args.name, _op["slug"], op_result)
            # §ONESHOT (2026-09-12) — record the operator the moment it EXISTS, before the card and the
            # gates below can refuse: an operator provisioned but unrecorded was orphaned by the teardown
            # (measured: juiceop, 10 containers, its vhost and SNI line, after the mTLS gate refused it).
            if _op["slug"] not in _ops_done: _ops_done.append(_op["slug"])
            meta["operator_slugs"] = _ops_done; meta["operator_slug"] = _op["slug"]
            open(os.path.join(ctx.stack_dir_host, "hetzner-demo-run.json"), "w").write(json.dumps(meta, indent=2))
            _body = {"display_name": _op.get("label") or f"{_op['slug']} operator",
                     "description": _op.get("description") or f"Cloud operator {_op['slug']} of the {args.frame_label} frame, located in {_op.get('location_label')}.",
                     "operator": {"display_name": _op.get("label") or _op["slug"], "company": args.operator_label,
                                  "location_label": _op.get("location_label"), "latitude": _op.get("latitude"), "longitude": _op.get("longitude")},
                     "tags": _op.get("tags") or ["cloud-operator", args.name],
                     "links": {"website": args.website}}
            if op_result.get("admin_email") and op_result.get("admin_password"):
                extras.put_operator_card(f"http://127.0.0.1:{op_result['port']}", op_result["admin_email"], op_result["admin_password"], _body)
            else:
                log(f"  !! operator {_op['slug']}: no admin credentials in the provision response — card location NOT set")
            # §MTLSGAP row 203 (2026-09-08) — an operator is not provisioned until it can prove
            # mTLS on both its rails AND reach ITS OWN parent over TLS. Every operator of the
            # EU/ASIA cluster was born with a plaintext, unresolvable CENTRAL_REGISTRY_URL and no
            # MAINFRAME_PUBLIC_URL, so its portal actions fell back to a hardcoded literal naming
            # FRAME A — a frame being retired that was never their parent. Nobody found out,
            # because a wrong parent still answers 200. Checked here, per operator, before the
            # standup counts it as done.
            extras.assert_operator_mtls(_op["slug"], log=log)
            if _op["slug"] not in _ops_done: _ops_done.append(_op["slug"])
        meta["operator_slugs"] = _ops_done; meta["operator_slug"] = _ops_done[-1] if _ops_done else None
        open(os.path.join(ctx.stack_dir_host, "hetzner-demo-run.json"), "w").write(json.dumps(meta, indent=2))
    elif do("operators") and args.with_operator:
        op_result = provision_child_operator(args, jwt)
        # Record the child operator in the run meta so teardown can purge it by NAME.
        # It must never be discovered by globbing `cloud-op-op-*` — that pattern also
        # matches the 13 PRODUCTION operators (op-berlin, op-london, op-doha …).
        meta["operator_slug"] = op_result["slug"]
        _ops_done.append(op_result["slug"])
        open(os.path.join(ctx.stack_dir_host, "hetzner-demo-run.json"),
             "w").write(json.dumps(meta, indent=2))

    if do("canary") and (getattr(args, "tester_network", "") or "").strip():
        extras.join_tester_network(args.name, ctx.stack_dir_host, args.tester_network.strip(), log=log)

    if do("canary") and getattr(args, "canary_local_paths", 0):
        extras.seed_local_canary_paths(f"http://127.0.0.1:{PORTS['registry']}", {"Authorization": f"Bearer {jwt}"},
                                       f"{args.name}-db", "frame_test_registry", "registry", args.name, count=args.canary_local_paths)
    _wired, _only = wiring(args)
    if do("wire") and _wired:   # §BATCH10 findings 2, 7, 8, 16: the production side from the frame's own names
        # §ONESHOT P2.2 (2026-09-12) — the seven bare host writes became ONE manifest (sidecars/sidecars.json)
        # and one writer; a host without a piece gets a sentence naming it, before anything is written.
        # §NIGHTPROV: --wire-only names the pieces; --wire-prod is every one (_only None), exactly as before.
        _m = sidecars.load()
        _need_apex = bool((_m.get("apex") or {}).get("vhosts"))
        if _only is None or "prometheus" in _only:
            sidecars.prepare_targets_dir(_m)   # §FRAMEKIT P3.1: readable by the user Prometheus runs as, before require() asks
        _problems = sidecars.require(_m, need_apex=_need_apex, only=_only)
        if _problems:
            for _p in _problems:
                log(f"[wire] REFUSED — {_p}")
            die(f"{'--wire-prod' if _only is None else '--wire-only'} refused: the sidecars above are missing on this host "
                "(the frame itself is up; fix them and resume with --resume-from wire)")
        sidecars.wire(_m, {"name": args.name, "frame_label": args.frame_label, "env_label": args.env_label,
                           "ticker": args.ticker, "currency_name": args.currency_name, "role": args.role,
                           "public_url": args.public_url, "es_public_url": args.es_public_url, "es_port": PORTS["es"],
                           "fed_port": PORTS["nginx_fed"] if "nginx_fed" in PORTS else int(os.getenv("FRAME_TEST_PORT_NGINX_FED", "30663")),
                           "identity_net": getattr(ctx, "identity_net_name", None) or "", "operators": _ops_done, "stack_dir": ctx.stack_dir_host},
                      only=_only, log=log)

    # §MTLSGAP (2026-09-08), his word: "it can never mint a frame like this." The LAST thing before
    # the frame is called live is a census of its own gateways, from the RUNNING containers — not
    # from the template, which R10 already gates. The EventStore had no gateway on every frame this
    # driver ever built and nothing reported it, because a plaintext hop raises nothing, logs
    # nothing and passes every health check. So the driver looks, and refuses.
    if do("mtls"):
        extras.assert_mtls_everywhere(args.name, log=log)
        posture_gate(args)                                                              # runbook §4 as code
        extras.assert_card_addresses(f"http://127.0.0.1:{PORTS['registry']}", log=log)  # runbook §16.6 as code
        deactivate_self_echo_rows(args, _ops_done)                                      # runbook §8.5 as code

    tracker.finish()
    if PROGRESS is not None:
        PROGRESS.emit("live", "live", "ok", name=args.name, stack_dir=ctx.stack_dir_host,
                      urls={"console": args.public_url, "card": f"{args.public_url}/.well-known/registry-card.json",
                            "ledger": args.es_public_url})
    print("\n" + "=" * 68)
    print(f"  {args.frame_label} IS LIVE")
    print("=" * 68)
    print(f"  UI:            {args.public_url}/ui")
    print(f"  Globe:         {args.public_url}/ui#/agentworld")
    print(f"  Card:          {args.public_url}/.well-known/registry-card.json")
    print(f"  Ledger audit:  {args.es_public_url}/api/v1/projections/supply-audit")
    try:
        _ha_slot = sidecars.host_auditor_frame(sidecars.load(), args.name) if wires(args, "auditor") else None
    except Exception:  # noqa: BLE001 (a host without the manifest: the line then says the auditor was not asked)
        _ha_slot = (False, None)
    _host_auditor = host_auditor_summary(wires(args, "auditor"), ctx.stack_dir_host, _ha_slot)
    if _host_auditor:
        print(_host_auditor)
    if getattr(args, "own_host", False):   # §HELLOFRAME: on an own host the secrets dir is the one answer, and frame-down the one teardown
        print(f"  Operator:      {args.admin_email}  (password in {getattr(args, 'secrets_dir', '') or os.path.dirname(ctx.stack_dir_host)}/.{args.name}_frame_admin.secret.json — never printed)")
    else:
        print(f"  Operator:      {args.admin_email}  (password in {ctx.stack_dir_host}/.env.frame-test — never printed)")
    if op_result and op_result.get("prestaged"):
        print(f"  Child op:      '{op_result['slug']}' PRESTAGED at {op_result['prestaged']} — "
              f"provision it live: {args.public_url}/ui#/operator-management")
    print(f"  Currency:      {args.ticker} ({args.currency_name}); treasury issued {args.mint} + 1.0 canary")
    print(f"  Stack dir:     {ctx.stack_dir_host}")
    if getattr(args, "own_host", False):
        print(f"  Teardown:      scripts/distribution/frame-down.py --name {args.name} --stack-root {os.path.dirname(ctx.stack_dir_host)}")
    else:
        print(f"  Teardown:      scripts/hetzner_demo/teardown_hetzner_frame.sh {ctx.stack_dir_host}")
    print("=" * 68)



def host_auditor_summary(wire_prod: bool, stack_dir: str, slot=None) -> str:
    """§MTLSHOPS T3 (2026-09-15, agentvault2-85's input): the summary names what the host auditor watches of a frame whose
    databases take TLS clients with a frame certificate only, so a row missing on the host auditor reads as designed rather
    than as a fault. Read from the frame's rendered compose and from the host auditor's own frame list (`slot`, as
    sidecars.host_auditor_frame answers: (reachable, entry)), not from this run, so a resume past the wire step says it
    too. Empty when the host is not wired or the frame's databases take other clients."""
    if not wire_prod or not sidecars.frame_data_takes_tls_clients_only({"stack_dir": stack_dir or ""}):
        return ""
    reachable, entry = slot if slot else (False, None)
    if reachable and entry and entry.get("public_only"):
        return ("  Host auditor:  this frame's public supply audit only (§MTLSHOPS (a)). Its databases take TLS clients with a\n"
                "                 frame certificate only; the frame's own auditor does the exact check and holds its attestation.")
    if not reachable:
        return ("  Host auditor:  not asked (its frame list did not answer). This frame's databases take TLS clients with a frame\n"
                "                 certificate only; the frame's own auditor does the exact check.")
    return ("  Host auditor:  no slot for this frame yet (§MTLSHOPS T3). Its databases take TLS clients with a frame certificate\n"
            "                 only; the frame's own auditor does the exact check. The host's public-only slot (his decision (a))\n"
            "                 is written once the host auditor lists that shape.")


def _fresh_network_json(args) -> str:
    """The frames this console names, each with the socket path THIS console serves for it.

    own  -> `/ws/events`          (the local socket; the FE's seed dedups it away)
    peer -> `/ws/events-<name>`   (matching the vhost lane --peer-ledger renders)

    A peer's facts beyond its name are DERIVED from the standup's own naming conventions;
    anything the driver cannot know (a peer's currency) is OMITTED rather than guessed — a wrong
    currency on a ledger tile is §LOCTRUTH's class, a value invented for legibility and then
    published as fact.
    """
    import json as _json
    peers = getattr(args, "_peer_ledgers", {}) or {}
    label = (getattr(args, "frame_label", "") or args.name)
    group = getattr(args, "env_label", "") or "sandbox"
    out = [{
        "name": label.upper(), "slug": args.name, "currency": args.ticker,
        "role": "frame", "group": group,
        "console": args.public_url.rstrip("/"),
        "status_url": args.public_url.rstrip("/") + "/#/status",
        # §MTLSHOPS T2 (S4, 2026-09-15): public addresses; a docker name reaches a frame's plain port, which S4 removes
        "registry_url": args.public_url.rstrip("/"),
        "es_url": (getattr(args, "es_public_url", "") or "").rstrip("/"),
        "ws_path": "/ws/events",
    }]
    for pname in sorted(peers):
        out.append({
            "name": pname.upper(), "slug": pname, "role": "frame", "group": group,
            "console": f"https://{pname}.theprotocol.cloud",
            "status_url": f"https://{pname}.theprotocol.cloud/#/status",
            "registry_url": f"https://{pname}.theprotocol.cloud",
            "es_url": f"https://{pname}-es.theprotocol.cloud",
            "ws_path": f"/ws/events-{pname}",
        })
    return _json.dumps(out, separators=(",", ":"))


def validate_args(args):
    """§FRAMEPROV P1 (2026-09-13): the argument refusals main() died on, RETURNED in the order the run asks them, with the
    derived values written back onto args (the logo by theme, the normalised ledger URL, the federation address). main()
    dies on the first; plan() reports every one. One place for each sentence."""
    refusals = []
    # §NIGHTPROV: --wire-only names pieces the manifest knows, and never beside --wire-prod (two wirings for one frame)
    _wo = wire_only_pieces(args)
    if _wo is not None:
        _unknown = sorted(_wo - set(WIRE_PIECES))
        if _unknown:
            refusals.append(f"--wire-only {args.wire_only!r}: unknown piece(s) {', '.join(_unknown)}; the pieces are "
                            f"{', '.join(WIRE_PIECES)}")
        if getattr(args, "wire_prod", False):
            refusals.append("--wire-prod and --wire-only name two wirings for one frame; give one (--wire-prod is every piece)")
    # §NIGHTPROV: a worker count the registry's command line carries as written; 0 leaves the provisioner's default
    _rw = getattr(args, "registry_workers", 0) or 0
    if _rw and not 1 <= _rw <= 16:
        refusals.append(f"--registry-workers {_rw}: a registry runs 1 to 16 gunicorn workers (0 = the provisioner's default)")
    # §FRAMEPROV P4 (2026-09-13): the label is carried in MAINFRAME_REGISTRY_NAMES, which the issuance gate splits on ",", so a
    # label with a comma boots a frame that refuses its own issuance and operator provisioning.
    if "," in (args.frame_label or ""):
        refusals.append(f"--frame-label {args.frame_label!r} contains a comma: the mainframe gate splits its name list on commas, "
                        f"so this frame would refuse its own issuance and operator provisioning")
    # §MTLSGAP: the index verifies its clients, so a plain host:port (the pre-2026-09-08 shape of this flag) would be
    # written into DIRECTORY_MTLS_URL and every dial would fail at the handshake, with the strip rendering empty and
    # nothing saying why. Refused at the door rather than shipping a flag whose precondition it cannot supply.
    if args.directory_upstream and not args.directory_upstream.startswith("https://"):
        refusals.append("--directory-upstream must be an https:// URL of the index's mTLS gateway "
                        "(e.g. https://directory-nginx:8443); the index runs ssl_verify_client on, so a "
                        "plain host:port cannot reach it")
    # §FRAMELIC row 153: the mark follows the theme unless the caller names a file.
    if not args.logo:
        args.logo = f"{REPO}/scripts/hetzner_demo/assets/protocol-mark-{args.theme}.png"
    # §FRAMELIC row 66: a posture and a fixture set that contradict each other is two declarations disagreeing;
    # refuse instead of picking one. The testers belong on the sandbox tier.
    if getattr(args, "tester_self", False):
        if args.posture == "production":
            refusals.append("--tester-self mounts the docker socket and runs the testers against this frame: a production "
                            "frame never does either. Stand a sandbox up beside it (frame-sandbox.py) and test there.")
        if (args.tester_console or "").strip():
            refusals.append("--tester-self and --tester-console name two different targets for this frame's tester; give one")
        if args.tester_fixture_secrets and not os.path.isfile(args.tester_fixture_secrets):
            refusals.append(f"--tester-fixture-secrets {args.tester_fixture_secrets} is not a file")
        args.tester_fixtures = True
    if args.posture == "production" and args.tester_fixtures:
        refusals.append("--tester-fixtures carries SANDBOX_BYPASS_RATE_LIMIT + API_TEST_EXECUTION_ENABLED, which a "
                        "production frame must not have (row 66). Run the testers against the sandbox tier and "
                        "proxy the console at them, or stand this frame up with --posture sandbox.")
    # §BATCH5: the EventStore public URL: ask, validate, refuse. Never guess.
    _es = (args.es_public_url or "").strip()
    _es_host = urllib.parse.urlparse(_es).hostname or ""
    if not _es or not _es.startswith("https://") or not _es_host:
        refusals.append("--es-public-url (or FRAME_ES_PUBLIC_URL) is REQUIRED and must be an https URL: this frame's PUBLIC EventStore host. "
                        "There is no default on purpose (unset ⇒ Frame A's ledger; the old literal ⇒ the hetzner ES).")
    _prod_ledgers = {"events.theprotocol.cloud", "events-b.theprotocol.cloud", "events-c.theprotocol.cloud", "hetzner-es.theprotocol.cloud"}
    if _es_host in _prod_ledgers:
        refusals.append(f"--es-public-url names a PRODUCTION (or retired demo) ledger host: {_es_host}. A fresh frame gets its OWN EventStore host.")
    _pub_parsed = urllib.parse.urlparse(args.public_url)
    if _es_host and _es_host == (_pub_parsed.hostname or ""):
        # §HELLOFRAME (own-host): one public name, the ledger's mTLS gateway on its own PORT (no host vhost exists there)
        if not (getattr(args, "own_host", False) and urllib.parse.urlparse(_es).port not in (None, 443, _pub_parsed.port)):
            refusals.append(f"--es-public-url must not be the frame's own registry host ({_es_host}); the EventStore has its own vhost.")
    args.es_public_url = _es.rstrip("/")
    # §BATCH5: the federation address the operators dial. Derived from the public host by default.
    _fed = (args.federation_public_url or "").strip().rstrip("/")
    if not _fed:
        _fed = f"https://{urllib.parse.urlparse(args.public_url).hostname or ''}:8443"
    _fp = urllib.parse.urlparse(_fed)
    if _fp.scheme != "https" or not _fp.hostname:
        refusals.append(f"--federation-public-url must be an https URL with a host, got {_fed!r}")
    elif _fp.port in (None, 443):
        refusals.append(f"--federation-public-url {_fed!r} is the plain 443 console; the operators' pull needs the mTLS "
                        "federation port (the host SNI router on 8443, or the frame's own published nginx-federation port)")
    args.federation_public_url = _fed
    return refusals


def derive_run_values(args, interactive=True):
    """§FRAMEPROV P1 (2026-09-13): the values main() derives before anything is written: the ticker, the generated
    secrets, the operator port base, the image's version constant, the operator images' pullability. Shared with plan()
    (interactive=False: a missing ticker is a refusal, never a prompt). Returns refusals; main() dies on the first."""
    refusals = []
    if not args.ticker and interactive:
        args.ticker = input("Currency ticker (ask Micha!) [HETZ]: ").strip().upper() or "HETZ"
    if not args.ticker:
        refusals.append("--ticker is required (the run would prompt for it)")
    args.ticker = (args.ticker or "").upper()
    if not args.admin_password:
        args.admin_password = secrets.token_urlsafe(16)
    if not args.mint_proxy_secret:
        args.mint_proxy_secret = secrets.token_hex(24)
    if args.cloud_port_base is None:  # §BATCH6: the allocator fills in only when the operator was not given a range
        args.cloud_port_base = _free_cloud_port_base()
    log(f"operator port base: {args.cloud_port_base} (range {args.cloud_port_base}-{args.cloud_port_base + 299})")
    if not args.image_tag:
        # §BEAT-B — VERSION/IMAGE_TAG is NOT cosmetic: the provisioner copies it into
        # the child operator's .env.operator, and the op's compose resolves
        # `images.theprotocol.cloud/{registry,teg-layer,cert-writer}:${VERSION}`.
        # A made-up tag (the old "hetzner-demo" fallback) makes every op compose-up
        # fail on an unpullable image, which retries for minutes and then kills the
        # provision's DB session mid-flight (rolling back the license + peer rows
        # while the ES sync had already succeeded — a half-provisioned operator).
        # So default to the newest tag that ACTUALLY exists locally for ALL THREE.
        # §BATCH5 (2026-09-05): the frame reports IMAGE_TAG over the image's own constant (registry_identity.get_software_version:
        # IMAGE_TAG env beats BUNDLED_IMAGE_TAG), and _newest_common_operator_tag() sorts tag STRINGS — "Pass-…V0133" sorts
        # after "MoreCompliant…V0223", so the JUICE frame reported a V0133-era version. The honest default is the constant
        # baked into the registry image the frame will actually run.
        # §FRAMELIC (2026-09-07, findings row 126 — row 12 made concrete): §BATCH5 fixed the
        # SORTING and left the SUBJECT wrong. This asked `agentvault2-registry-a:latest` — a
        # hardcoded name that has nothing to do with `--registry-image`, the image this frame is
        # actually about to run. Standing up EU on a V0250 image therefore stamped IMAGE_TAG=V0226
        # into all three carriers, and `IMAGE_TAG` env BEATS `BUNDLED_IMAGE_TAG` (PART 1, "TWO WAYS
        # THE VERSION STRING LIES"), so the brand-new frame published V0226 for life. Ask the image
        # we were TOLD to use; `:latest` stays as the fallback for a caller that named none.
        args.image_tag = (_bundled_tag_of_image(args.registry_image)
                          or _bundled_tag_of_image("agentvault2-registry-a:latest")
                          or _newest_common_operator_tag() or "stable")
        log(f"version constant read from {args.registry_image}: {args.image_tag}")

    # §FRAMELIC (2026-09-07, findings row 130) — THE VERSION MUST BE PULLABLE BEFORE AN OPERATOR
    # IS PROMISED IT. `VERSION` is copied into every child operator's `.env.operator`, and the
    # operator compose resolves `images.theprotocol.cloud/{registry,teg-layer,cert-writer}:${VERSION}`
    # from the REMOTE registry — not from this host's local images. Fixing row 126 (derive the
    # constant from the image we will actually run) immediately exposed this: the correct constant
    # named a tag nobody had pushed, so the operator's compose-up retried an unpullable image for
    # minutes and the provision died mid-flight. The old bug had HIDDEN this one, because the stale
    # constant happened to name a tag a previous batch had pushed.
    #
    # This is a preflight, not a push: pushing on someone's behalf during a standup is a surprise.
    # It REFUSES with the three commands that fix it, before anything is provisioned.
    if getattr(args, "operators_json", None) or getattr(args, "with_operator", False):
        _missing = [r for r in ("registry", "teg-layer", "cert-writer")
                    if subprocess.run(["docker", "manifest", "inspect",
                                       f"images.theprotocol.cloud/{r}:{args.image_tag}"],
                                      capture_output=True, timeout=90).returncode != 0]
        if _missing:
            refusals.append("this frame will provision operators, and its VERSION names images that are NOT in "
                f"images.theprotocol.cloud: {', '.join(_missing)} at tag {args.image_tag}. An operator "
                "compose-up would retry an unpullable image and take the provision's DB session down "
                "with it. Push them first:\n" +
                "\n".join(f"  docker tag <local {r}> images.theprotocol.cloud/{r}:{args.image_tag} && "
                           f"docker push images.theprotocol.cloud/{r}:{args.image_tag}" for r in _missing))
        if not _missing:
            log(f"preflight: all three operator images are pullable at {args.image_tag}")
    return refusals


def _apply_allocated_ports(args):
    """§FRAMEPROV P1: --allocate-ports writes PORTS and FRAME_TEST_PORT_* for THIS process, before the provisioner is
    loaded (it reads them at import). Refused beside a declared FRAME_TEST_PORT_*: two declarations of one fact."""
    declared = sorted(v for v in frame_ports.ENV_NAMES.values() if os.getenv(v))
    if declared:
        die(f"--allocate-ports beside {', '.join(declared)}: two declarations of this frame's ports; drop one")
    try:
        ports = frame_ports.allocate(frame_ports.taken_ports())
    except frame_ports.NoFreePorts as exc:
        die(str(exc))
    for key, env_name in frame_ports.ENV_NAMES.items():
        os.environ[env_name] = str(ports[key])
    for key in PORTS:
        PORTS[key] = ports[key]
    log(f"ports allocated: {ports}")
    return ports


def default_bundle_public_url(args):
    """§F6 WP6.5/A4 (2026-09-27): the SPIRE bundle endpoint a frame ADVERTISES (the invitation rail hands it to a peer as
    FRAME_LOCAL_BUNDLE_ENDPOINT_URL, the card publishes it as SPIRE_BUNDLE_ENDPOINT) when the caller names none: the
    frame's public host and the host port its SPIRE server's bundle endpoint is published on (PORTS['spire_bundle'];
    the template publishes it on every frame). The provisioner's fallback, https://<name>-spire-server:8443/, is a name
    on the frame's own compose network: no peer frame (another compose project on this host, or another host) resolves
    it, so a federation relationship could be created and never refreshed. Measured: every runner-built frame and
    sbx-beta advertised it (the throwaways' was set by hand), while https://sandbox-b.theprotocol.cloud:8565/ answered
    sbx-beta's bundle to a container on sbx-alpha's network (2026-09-27 02:30Z). A caller's --bundle-public-url wins; a
    frame with no public host keeps the old fallback."""
    named = (getattr(args, "bundle_public_url", "") or "").strip()
    if named:
        return named
    host = urllib.parse.urlsplit((getattr(args, "public_url", "") or "").strip()).hostname
    return f"https://{host}:{PORTS['spire_bundle']}/" if host else ""


def _published_port(container):
    """§PROVSHOW (2026-09-15): the host port of a container's published mapping (`docker port <container>`), or None."""
    try:
        r = subprocess.run(["docker", "port", container], capture_output=True, text=True, timeout=20)
    except Exception:  # noqa: BLE001 — an unanswerable docker port is None, reported by the caller
        return None
    for line in (r.stdout or "").splitlines():
        m = re.search(r":(\d+)\s*$", line.strip())
        if m:
            return int(m.group(1))
    return None


def _restore_ports_from_meta(meta):
    """§FRAMEPROV P1: a resume uses the ports the frame was stood up with (the run meta), not whatever the caller's env
    or the fixed defaults say. Written before the provisioner is loaded, which reads them at import."""
    ports = meta.get("ports") if isinstance(meta.get("ports"), dict) else {}
    for key, value in ports.items():
        if key in PORTS and isinstance(value, int):
            PORTS[key] = value
            os.environ[frame_ports.ENV_NAMES[key]] = str(value)
    if isinstance(meta.get("port_push"), int):
        os.environ[frame_ports.ENV_NAMES["push"]] = str(meta["port_push"])
    # §PROVSHOW (2026-09-15): the kit's loopback doors. A meta written before this change has neither, and the first resume
    # of lantern probed grafana on the provisioner's default 8201 (Frame B's store answered 404) while lantern's grafana
    # served 8551. The meta's value first, else the running container's published port; never the default in silence.
    _name = meta.get("name") or ""
    for _key in ("grafana", "auditor"):
        _value, _source = meta.get(f"port_{_key}"), "the run meta"
        if not isinstance(_value, int):
            _value, _source = (_published_port(f"{_name}-{_key}") if _name else None), f"{_name}-{_key}'s published port"
            if isinstance(_value, int):
                meta[f"port_{_key}"] = _value
        if isinstance(_value, int):
            os.environ[frame_ports.ENV_NAMES[_key]] = str(_value)
            log(f"kit port {_key}: {_value} (from {_source})")
        else:
            log(f"kit port {_key}: UNKNOWN (no port_{_key} in the run meta and {_name}-{_key} publishes none); its kit gate "
                f"will probe the provisioner's default")
    if ports:
        log(f"ports from the run meta: {dict(PORTS)}")


def _use_secrets_dir(path, create):
    """§FRAMEPROV P1: --secrets-dir. Every module instance that names SECRETS_DIR gets the same directory (the driver,
    standup_federate and sidecars each load their own copy of standup_extras)."""
    path = os.path.abspath(path)
    if create:
        os.makedirs(path, mode=0o700, exist_ok=True)
    for mod in (extras, federate, getattr(federate, "extras", None), sidecars, getattr(sidecars, "extras", None)):
        if mod is not None and hasattr(mod, "SECRETS_DIR"):
            mod.SECRETS_DIR = path
    return path


def dns_readiness(args):
    """§FRAMEPROV P1: the four names the vhosts and the certificate need (standup_extras.issue_cert's list), asked of
    1.1.1.1 the way issue_cert asks, and whether the certificate is on disk. A missing name REFUSES when the run would
    need it now (--acme with no certificate yet); otherwise it is a warning."""
    hosts = [f"{args.name}.{extras.DOMAIN}", f"{args.name}-es.{extras.DOMAIN}",
             f"{args.name}-spire.{extras.DOMAIN}", f"{args.name}-push.{extras.DOMAIN}"]
    records, missing = {}, []
    for host in hosts:
        answers = []
        for rtype in ("A", "CNAME"):
            try:
                out = subprocess.run(["dig", "+short", "@1.1.1.1", host, rtype], capture_output=True, text=True, timeout=15).stdout
            except (OSError, subprocess.TimeoutExpired):
                out = ""
            answers += [x for x in (out or "").split() if x]
        records[host] = answers
        if not answers:
            missing.append(host)
    cert = frame_tls_cert(args.public_url)
    cert_present = os.path.exists(cert)
    refusals, warnings = [], []
    if missing and getattr(args, "acme", False) and not cert_present and getattr(args, "dns_by_runner", False):
        # §FRAMEPROV P5: the frame runner creates the names at Start and waits for 1.1.1.1 before this driver runs
        warnings.append(f"{', '.join(missing)} do not resolve at 1.1.1.1 yet: the frame runner creates them and waits "
                        f"for 1.1.1.1 before the standup starts, then --acme issues {cert}")
    elif missing and getattr(args, "acme", False) and not cert_present:
        refusals.append(f"DNS first: {', '.join(missing)} do not resolve at 1.1.1.1, and --acme needs all four names to issue {cert}")
    elif missing:
        warnings.append(f"{', '.join(missing)} do not resolve at 1.1.1.1 (the frame's vhosts and certificate name them)")
    public_host = urllib.parse.urlparse(args.public_url or "").hostname or ""
    if getattr(args, "render_vhosts", False) and public_host != f"{args.name}.{extras.DOMAIN}":
        warnings.append(f"--render-vhosts writes the vhosts for {args.name}.{extras.DOMAIN}, but --public-url names {public_host}")
    return {"records": records, "cert": {"path": cert, "present": cert_present}, "refusals": refusals, "warnings": warnings}


def plan(args):
    """§FRAMEPROV P1 (2026-09-13): everything the run would refuse, and everything it would derive, WITHOUT writing.

    The admin UI shows this before its Start button enables. The same checks as the run, in the run's order and from the
    same functions (validate_args, derive_run_values, preflight_problems, build_ctx, dns_readiness), every refusal
    collected instead of exiting. Reads only: /proc, `docker image|network inspect`, `docker ps`, `ss`, `dig`, the image's
    version constant (`docker run --rm`), the operator images' manifests, a peer's /health. Prints ONE JSON document on
    stdout (everything else goes to stderr) and returns the exit code: 0 ok, 2 refused."""
    import contextlib
    global LOG_TO_STDERR, _PLAN_REFUSALS
    LOG_TO_STDERR = True
    _PLAN_REFUSALS = []
    refusals, warnings, derived, ctx = [], [], {}, None
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if getattr(args, "resume_stack_dir", None):
                refusals.append("--plan plans a new frame; it does not combine with --resume-stack-dir")
            refusals += validate_args(args)
            refusals += derive_run_values(args, interactive=False)
            if args.allocate_ports:
                try:
                    _apply_allocated_ports(args)
                except PlanRefusal as exc:
                    refusals.append(str(exc))
            args.bundle_public_url = default_bundle_public_url(args)   # §F6 WP6.5/A4
            derived["bundle_public_url"] = args.bundle_public_url or None
            problems, facts = preflight_problems(args)
            refusals += problems
            derived["host"] = facts
            try:
                ctx = build_ctx(args, int(time.time()), load_provisioner())
            except PlanRefusal as exc:
                refusals.append(str(exc))
            except SystemExit:
                refusals.append("--posture production requires a mail relay: set FRAME_MAIL_SERVER, FRAME_MAIL_ADDRESS "
                                "and FRAME_MAIL_TOKEN, or plan a sandbox posture")
            except Exception as exc:  # noqa: BLE001 — a plan reports what it could not build, it does not crash
                refusals.append(f"the provisioner context could not be built: {type(exc).__name__}: {str(exc)[:200]}")
            dns = dns_readiness(args)
            refusals += dns["refusals"]
            warnings += dns["warnings"]
            derived["dns"] = dns["records"]
            derived["certificate"] = dns["cert"]
    except PlanRefusal as exc:
        refusals.append(str(exc))
    finally:
        _PLAN_REFUSALS = None
    ports = dict(PORTS)
    ports["push"] = int(getattr(ctx, "port_ntfy", 0) or os.getenv("FRAME_TEST_PORT_NTFY", "8199"))
    derived.update({
        "name": args.name, "frame_label": args.frame_label, "trust_domain": args.trust_domain,
        "public_url": args.public_url, "es_public_url": args.es_public_url,
        "federation_public_url": args.federation_public_url, "push_public_url": args.push_public_url,
        "stack_dir": f"/opt/theprotocol/stack/{args.name}-<ts>", "ports": ports,
        "operator_port_base": args.cloud_port_base, "image_tag": args.image_tag,
        "images": {"registry": args.registry_image, "teg": args.teg_image, "event_store": args.es_image},
        "posture": args.posture, "env_label": args.env_label, "theme": args.theme,
        "own_host": bool(getattr(args, "own_host", False)), "stack_root": args.stack_root,
        "es_mtls_port": int(getattr(args, "es_mtls_port", 0) or 0),
        "secrets_dir": os.path.abspath(args.secrets_dir) if args.secrets_dir else extras.SECRETS_DIR,
        "vhosts": frame_vhosts(args.name), "federate_with": list(args.federate_with or []),
        "wire_prod": bool(args.wire_prod), "wire_only": sorted(wire_only_pieces(args) or []),
    })
    print(json.dumps({"ok": not refusals, "refusals": refusals, "warnings": warnings, "derived": derived}, indent=1))
    return 0 if not refusals else 2


def _pre(step):
    """§FRAMEPROV P1: the steps before post_boot (validate, preflight, render, compose-up) as progress events: close the
    open one, open the next (None only closes)."""
    if PROGRESS is not None:
        PROGRESS.end("ok")
        if step:
            PROGRESS.start(step)


def build_parser():
    """§FRAMEPROV P1: the parser, callable without running anything (the plan and progress tests build args from it)."""
    ap = argparse.ArgumentParser(description="Hetzner Frame live-demo standup")
    ap.add_argument("--name", default="hetzner-frame")
    ap.add_argument("--frame-label", default="Hetzner Frame")
    ap.add_argument("--trust-domain", default="hetzner.theprotocol.cloud")
    ap.add_argument("--ticker", default=None, help="asked LIVE; prompts if omitted")
    ap.add_argument("--currency-name", default="Hetzner Token")
    # §FRAMELIC (2026-09-07, findings row 153) — DEFAULT TO THE PROTOCOL MARK, BY THEME.
    # The default used to be `hetzner-logo.png` (this driver was born as the Hetzner demo
    # standup), so EU and ASIA both stood up wearing another company's logo on their
    # registry cards and on the globe. His words: "eu and asia have hetzner logo instead
    # of protocol logo as we agreed. this is bad." It was fixed by hand on the previous
    # pair and the fix died with the teardown — which is the whole reason it belongs here
    # and not in a runbook step ("update the driver. so if we might have to reprovision
    # clean we can do it again smoothly, not like this").
    # Unset ⇒ resolved from --theme after parsing: neural or sovereign.
    ap.add_argument("--logo", default=None,
                    help="PNG/JPEG <=500KB for the card + globe avatar. Default: the "
                         "Protocol mark matching --theme (neural or sovereign). Missing "
                         "file = loud warning, never a silent skip.")
    # Cosmetic flare axes — catalogs live in core/registry_identity.py
    # (FLARE_ENCIRCLEMENT_VARIANTS / FLARE_ENCIRCLEMENT_OVERLAYS).
    ap.add_argument("--flare-encirclement", default="inferno",
                    help="Encirclement ring variant (inferno|sauron|aurora|matrix|...). "
                         "Empty string disables.")
    ap.add_argument("--flare-overlay", default="panic-a",
                    help="Broken-machine overlay ON TOP of the encirclement "
                         "(panic-a|panic-b|panic-c|glitch|cascade|...). Empty string disables.")
    ap.add_argument("--lat", type=float, default=49.1157, help="Gunzenhausen HQ")
    ap.add_argument("--lng", type=float, default=10.7539)
    ap.add_argument("--operator-label", default="Hetzner Online GmbH")
    ap.add_argument("--location-label", default="Gunzenhausen, Bavaria")
    ap.add_argument("--website", default="https://www.hetzner.com")
    ap.add_argument("--description",
                    default="Sovereign region of TheProtocol network, dedicated to Hetzner. "
                            "Hosted and operated by TheProtocol.")
    # NO personal data in defaults (Commander 2026-07-26)
    ap.add_argument("--admin-email", default="admin@hetzner-frame.dev")
    ap.add_argument("--admin-name", default="Hetzner Frame Admin")
    ap.add_argument("--admin-password", default=None)
    ap.add_argument("--admin-accepted", default="",
                    help="frame-up.py: the documents the person accepted before the standup (\"operators\"); the registry "
                         "records them with the first admin it creates")
    ap.add_argument("--admin-accepted-at", default="", help="frame-up.py: when they were accepted (ISO 8601, UTC)")
    ap.add_argument("--admin-accepted-by", default="", help="frame-up.py: how (the tool, its kit version and the way asked)")
    ap.add_argument("--mint", default="1000000")
    ap.add_argument("--image-tag", default=None,
                    help="VERSION/IMAGE_TAG reported on the card; default = current registry-a tag")
    ap.add_argument("--public-url", default="https://hetzner.theprotocol.cloud")
    ap.add_argument("--es-public-url", default=os.getenv("FRAME_ES_PUBLIC_URL") or None,
                    help="REQUIRED: this frame's PUBLIC EventStore https URL (its operators emit their ledger events there). "
                         "No default on purpose — unset once fell back to Frame A's ledger (§pass78c), and a demo literal "
                         "once pointed a fresh frame at the hetzner ES (§BATCH5).")
    ap.add_argument("--federation-public-url", default=os.getenv("FRAME_FEDERATION_PUBLIC_URL") or None,
                    help="this frame's mTLS federation address as its OPERATORS dial it (their peer row for the parent, "
                         "BILATERAL_PEER_URL). Default: https://<public-url host>:8443 — the host SNI router, which reaches the "
                         "frame's nginx-federation once the parent-side entry exists (scripts/extend_stream_sni_map.sh <host> <fed port>). "
                         "NEVER the plain 443 console: the pull presents a SPIRE client cert, a 443 vhost that does not verify "
                         "client certs answers 401 and the operator backs off for 33 minutes (§BATCH5, measured on the JUICE pair).")
    ap.add_argument("--push-public-url", default=os.getenv("FRAME_PUSH_PUBLIC_URL") or None,
                    help="optional: the frame's public ntfy (push) https URL; empty leaves push internal-only")
    # Load gate calibrated to THIS box, not to a generic idle host: ~290-320
    # containers put the steady-state 1-min load at ~45-75 on 24 threads, and the
    # sim deadman (the real danger line) trips at >220. A gate of 8-12 (the old
    # chained-frame-test default) can never pass here and would just block runs.
    # RAM is the binding constraint for a 13-container frame (~3 GiB), enforced
    # separately at >=8 GiB MemAvailable.
    ap.add_argument("--with-operator", action=argparse.BooleanOptionalAction, default=False,
                    help="Beat B: after the frame is green, provision a child cloud operator")
    ap.add_argument("--operator-slug", default="op-demo",
                    help="child operator slug (NO personal data in tests)")
    ap.add_argument("--prestage-operator", choices=["activated"], default=None,
                    help="with --with-operator: stop the child at this stage instead of "
                         "provisioning (showcase preload — 'activated' leaves the operator "
                         "waiting in the frame UI's Operator Management for one live "
                         "Provision click)")
    ap.add_argument("--mint-proxy-secret", default=None,
                    help="shared registry<->TEG mint-proxy secret (generated if unset)")
    # §SANDBOXSTANDUP 2026-09-03 — OPT-IN host reach. Without it the frame's registry has no
    # docker.sock, `operator_provisioner.export_trust_bundle` cannot reach the daemon, and
    # `POST /operators/activate` SWALLOWS that failure (routers/operator_applications.py:1205 —
    # "provisioning failure does NOT block activation"), returning 200 with bundle_path=None.
    # The lie only surfaces later at provision: "Bundle not found at None. Run activation first."
    # ⚠ Granting it is root on THIS host for whoever holds the frame's admin credential
    # (PART 11b). It is what the three production frames already carry, and it is the only way
    # the product's own cloud-operator provisioning can work. Default OFF, on purpose.
    ap.add_argument("--cloud-port-base", type=int, default=(int(os.getenv("FRAME_CLOUD_PORT_BASE")) if os.getenv("FRAME_CLOUD_PORT_BASE") else None),
                    help="first host port of this frame's OPERATOR range (three 100-port blocks: base+0 registry, +43 federation, "
                         "+80 TEG per operator); unique per frame — JUICE 31300, BRRR 31600. Probed at preflight: < 2 free blocks refuses. "
                         "(§BATCH6: the definition had been lost by an afternoon edit while the range logic still read args.cloud_port_base.)")
    ap.add_argument("--cloud-port-span", type=int, default=int(os.getenv("FRAME_CLOUD_PORT_SPAN", "800")),
                    help="row 141: the width of this frame's operator port window (default 800 = "
                         "eight 100-port blocks). Must leave room for the blocks the daemon has "
                         "wedged from earlier teardowns, which the allocator now correctly refuses.")
    ap.add_argument("--grant-host-reach", action="store_true", default=False,
                    help="mount docker.sock + /host-stack + /host-nginx-sites into the frame registry "
                         "(required for --with-operator; root on this host for that frame's admin)")
    # §SANDBOXSTANDUP 2026-09-03 — a SHARED identity network so two frames' SPIRE servers can
    # reach each other for the federation RELATIONSHIP (`spire-server federation create`, the
    # https_spiffe refresh poll). It must live in the COMPOSE: a runtime `docker network connect`
    # is wiped by the next --force-recreate, and the failure only surfaces ~2 weeks later as
    # cross-TEG CERTIFICATE_VERIFY_FAILED. The provisioner already supports it
    # (FrameTestContext.identity_net_name / identity_net_external); the driver never exposed it.
    # Teardown deliberately does NOT remove a shared (external) net.
    ap.add_argument("--registry-image", default=os.getenv("FRAME_REGISTRY_IMAGE") or "agentvault2-registry-a:latest",
                    help="local registry image for this frame (default agentvault2-registry-a:latest = the last LOCAL build, "
                         "whatever session made it; a promotable frame names a deliberate tag, e.g. agentvault2-registry-a:fresh)")
    ap.add_argument("--es-image", default=os.getenv("FRAME_ES_IMAGE") or "agentvault2-event-store-test:latest",
                    help="local event-store image for this frame (§SOVKIT: the :sovkit1 line requires mTLS and the proxy "
                         "marker; the default is the last LOCAL build, for a hand-run standup only)")
    ap.add_argument("--teg-image", default=os.getenv("FRAME_TEG_IMAGE") or "agentvault2-teg-layer:latest",
                    help="local TEG image for this frame (default agentvault2-teg-layer:latest)")
    ap.add_argument("--cert-writer-image", default=os.getenv("FRAME_CERT_WRITER_IMAGE", "agentvault2-cert-writer-test-a:spire1153"),
                    help="§HELLOFRAME: the SVID writer six sidecars run (build.sh's PREFIX/cert-writer in the export; this host's local build tag by default)")
    # §HELLOFRAME (2026-09-18): a frame on a stranger's own host. No /host-stack symlink, no host nginx or certificate
    # (the edge is the export's own, a sibling compose project frame-up brings up), the stacks under --stack-root, the
    # ledger's mTLS gateway on a host port. Everything host-shaped stays opt-in and off (--render-vhosts, --acme,
    # --wire-prod, --federate-with, --with-operator); this flag only removes what a foreign host cannot have.
    ap.add_argument("--own-host", action=argparse.BooleanOptionalAction, default=False,
                    help="the frame lives on its operator's own host: no /host-stack, no host vhost or certificate; --stack-root and --es-mtls-port apply")
    ap.add_argument("--operator-images-prefix", default=os.getenv("FRAME_OPERATOR_IMAGES_PREFIX", ""),
                    help="§HELLOFRAME (own-host): the tag namespace the frame's operators pull their images from (the export's, local)")
    ap.add_argument("--host-public-ip", default=os.getenv("FRAME_HOST_PUBLIC_IP", ""),
                    help="§HELLOFRAME (own-host): the address the frame's public name resolves to (CLOUD_OP_HEALTH_HOST_IP)")
    ap.add_argument("--stack-root", default=os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack"),
                    help="where the frame's stack directory is created (default /opt/theprotocol/stack, FRAME_STACK_ROOT)")
    ap.add_argument("--es-mtls-port", type=int, default=0,
                    help="own-host: publish nginx-event-store's 8443 on this host port (0 = not published)")
    ap.add_argument("--bundle-public-url", default=os.getenv("FRAME_BUNDLE_PUBLIC_URL", ""),
                    help="own-host: the PUBLIC https address of this frame's SPIRE bundle endpoint (https://<name>:<port>/); it is what the "
                         "invitation rail advertises and the card publishes. Default (§F6 WP6.5/A4): the --public-url host with this frame's "
                         "published bundle port; the docker-internal name only when there is no public host (no peer frame resolves it)")
    ap.add_argument("--extra-trusted-spiffe-domains", default=os.getenv("FRAME_EXTRA_TRUSTED_SPIFFE_DOMAINS") or "",
                    help="comma-separated peer trust domains this frame's EventStore accepts over mTLS (its federated peers); "
                         "the ES vhost bundle must carry each peer's root as well")
    ap.add_argument("--federate-with", action="append", default=[], metavar="PEER_STACK_DIR",
                    help="§ONESHOT: federate bilaterally with the frame stood up from this stack dir (repeatable; a third peer "
                         "appends). Runs as the `federate` step after `jurisdiction`; implies --fx-peer/--fx-peer-router-did, "
                         "--extra-trusted-spiffe-domains, --peer-ledger and --identity-net from the peer's stack when not given, "
                         "and asks the peer to issue this frame's licence before the first boot when --federation-license-key is unset.")
    ap.add_argument("--fx-anchor", default="", help="§ONESHOT: the FX pool's anchor currency (default: the FIRST peer's, it stood first)")
    ap.add_argument("--federate-licence-plan", default=os.getenv("FRAME_FEDERATE_LICENCE_PLAN") or "",
                    help="§FEDLICENCE: when a --federate-with peer is the network's genesis and this frame holds no network "
                         "licence, the genesis issues one under this plan at its approve (private | educational | research | "
                         "non-profit | enterprise | government); empty = none is asked for, and a genesis that enforces refuses")
    ap.add_argument("--fx-peer", default=os.getenv("FRAME_FX_PEER") or "",
                    help="SLUG:CCY:ES_URL of the FX partner frame (e.g. juice:JUICE:https://juice-es.theprotocol.cloud); renders the six "
                         "FX keys so the frame is stood up already pointed at its partner (the reserve keeper still needs its PUT after "
                         "federation, runbook §9.6). Empty = FX off.")
    ap.add_argument("--fx-router", action=argparse.BooleanOptionalAction, default=True,
                    help="create this frame's @fx_router and turn FX_ROUTE_ENABLED on (findings row 191). "
                         "--no-fx-router leaves the route engine off, which is what the template ships.")
    ap.add_argument("--fx-peer-router-did", default=os.getenv("FRAME_FX_PEER_ROUTER_DID") or "",
                    help="the PEER frame's @fx_router agent DID. The route engine makes it the RECEIVER of the "
                         "FX core swap (`gd[\"router_did\"]`), so an --fx-peer without it renders a peer entry "
                         "that converts into a transfer to nobody. It is created on the OTHER frame, so it cannot "
                         "be derived here — pass it, exactly like the federation licence key. (findings row 191)")
    ap.add_argument("--identity-net", default=None,
                    help="name of an identity network shared with the peer frame (must already exist "
                         "when --identity-net-external is set)")
    ap.add_argument("--identity-net-external", action="store_true", default=False,
                    help="treat --identity-net as pre-existing (external) instead of creating it per frame")
    ap.add_argument("--max-load", type=float, default=40.0, help="§ONESHOT: the standing gate is load < 40 (was 110)")
    ap.add_argument("--enable-vhost", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--admin-pass", action=argparse.BooleanOptionalAction, default=True,
                    help="card+logo+show-mint after the emission gate")
    # §BATCH10 — the one-pass standup (each flag = a finding batch 9 closed by hand; see standup_extras.py)
    ap.add_argument("--card-json", default=None, help="JSON with display_name/tags/links/commitments merged into the card PUT (no github_source)")
    ap.add_argument("--jurisdiction-json", default=None, help="the jurisdiction profile document, PUT to /admin/jurisdiction/profile")
    ap.add_argument("--operators-json", default=None, help='[{"slug","port_base","label","location_label","latitude","longitude","description"}] — every operator, provisioned in order, its card location set')
    ap.add_argument("--render-vhosts", action="store_true", default=False, help="render the five vhosts from templates/frame-test/vhosts (acme first, tls after --acme)")
    ap.add_argument("--acme", action="store_true", default=False, help="issue the one certificate with four SANs (DNS must resolve)")
    ap.add_argument("--dns-by-runner", action="store_true", default=False,
                    help="§FRAMEPROV P5: the frame runner creates the four names and waits for 1.1.1.1 before this run, so "
                         "a plan under --acme warns about a name that does not resolve yet instead of refusing")
    ap.add_argument("--tester-fixtures", action="store_true", default=False, help="the API/MCP testers' fixture posture in the registry env (finding 22)")
    ap.add_argument("--operator-domain-suffix", default="",
                    help="the domain this frame's cloud operators are named under (<slug>.<suffix>); default: the frame's own "
                         "public host on --own-host. A sandbox names its PARENT's (frame-up --sandbox-of, §TESTBED)")
    ap.add_argument("--tester-self", action="store_true", default=False,
                    help="§TESTBED: this SANDBOX runs the MCP/API tester against itself: implies --tester-fixtures, seeds the "
                         "fixture accounts, names its own containers and store, and mounts the docker socket into its registry "
                         "(root on this host). Posture sandbox only.")
    ap.add_argument("--tester-fixture-secrets", default=None,
                    help="--tester-self: a JSON file of the fixture secrets a sandbox PAIR shares (frame-sandbox.py writes it); "
                         "unset = generated for this frame")
    ap.add_argument("--canary-local-paths", type=int, default=0, help="seed N local canary paths (sender/receiver agents, funded) so the canaries fire")
    ap.add_argument("--wire-prod", action="store_true", default=False, help="Prometheus jobs, the auditor slot, the apex/api ledger route, the FRESH_NETWORK_JSON entry, the identity-nets file")
    ap.add_argument("--registry-workers", type=int, default=0, metavar="N",
                    help="§NIGHTPROV: the registry's gunicorn workers (1-16); 0 = the provisioner's default "
                         "(FRAME_TEST_WORKERS_REG, else 4). The runner passes a nightly pair's from its policy")
    ap.add_argument("--wire-only", default="", metavar="PIECES",
                    help="§NIGHTPROV: wire only these host sidecar pieces (comma list of " + ", ".join(WIRE_PIECES) + "); "
                         "a nightly sandbox pair takes sni,bundle. Not with --wire-prod (every piece)")
    # §FRAMELIC (2026-09-07) — the four flags a PRODUCTION standup needs that the rehearsal
    # supplied by hand. Each closes a numbered row of FINDINGS_2026-09-06_REPROVISIONING.md.
    ap.add_argument("--posture", default="sandbox", choices=["sandbox", "production"],
                    help="row 66: a PRODUCTION frame never carries SANDBOX_BYPASS_RATE_LIMIT or "
                         "API_TEST_EXECUTION_ENABLED — the limiter must be live and the tester must "
                         "run against the sandbox tier, not against this frame. `--tester-fixtures` "
                         "on a production posture is REFUSED rather than silently downgraded.")
    ap.add_argument("--theme", default="neural", choices=["neural", "sovereign"],
                    help="row 62: this frame's mark and palette. Two frames born from one driver "
                         "wore the same face until his eye caught it.")
    ap.add_argument("--service-accounts", action=argparse.BooleanOptionalAction, default=True,
                    help="HIS DECISION 2026-09-07: create svc-provisioning / svc-sim / svc-canary / "
                         "svc-market for this frame, each with only its rail's authority and its "
                         "agents hidden from discovery. The Commander onboards nothing.")
    ap.add_argument("--federation-license-key", default=os.getenv("FRAME_FEDERATION_LICENSE_KEY") or "",
                    help="§FRAMELIC: the licence THIS frame presents, issued by the anchor frame "
                         "before standup. Seeded into the env so the frame is licensed from its "
                         "first boot rather than from its first federation.")
    # §FRAMELIC row 159 — the tester's target reached over a DIRECT container lane, because a
    # public vhost's proxy_read_timeout kills a sweep at five minutes (row 146). Naming the
    # network here makes the join part of the standup instead of a hand-fix that dies at teardown.
    ap.add_argument("--peer-ledger", action="append", default=[], metavar="NAME:ES_PORT",
                    help="a PEER frame whose ledger this console should stream, e.g. asia:8471. "
                         "Writes the /ws/events-<name> same-origin proxy into the console vhost AND "
                         "the peer's entry (with that ws_path) into FRESH_NETWORK_JSON — both halves "
                         "or neither (findings row 174). Repeatable. Unset: own ledger only.")
    ap.add_argument("--directory-upstream", default="",
                    help="the mTLS URL of the federated index (the Directory) this frame reads, e.g. "
                         "https://directory-nginx:8443. ONE flag writes all of it: DIRECTORY_MTLS_URL "
                         "(what the registry dials, presenting its own SVID), DIRECTORY_PUBLIC_URL="
                         "/api/v1/public/directory (what the console asks for, same-origin through "
                         "`location /`) and DISCOVERY_VIA_DIRECTORY. Unset: no index, no strip. "
                         "§MTLSGAP — must be https://, because the index verifies its clients.")
    ap.add_argument("--tester-network", default=os.getenv("FRAME_TESTER_NETWORK") or "",
                    help="docker network to join so the tester's target is reachable directly "
                         "(e.g. sbx_alpha_network); joined in the compose so it survives a recreate")
    ap.add_argument("--tester-console", default=os.getenv("FRAME_TESTER_CONSOLE_TARGET") or "",
                    help="his 2026-09-07 word: run the API/MCP testers FROM this frame's console but "
                         "EXECUTED against the sandbox tier, so the run history lands here while "
                         "nothing is ever tested against this frame. Takes the sandbox registry's "
                         "URL (e.g. http://172.17.0.1:8150). This is NOT --tester-fixtures: it "
                         "enables execution and points the target elsewhere, and deliberately does "
                         "NOT turn on this frame's rate-limit bypass or its sandbox admin fixtures.")
    ap.add_argument("--tester-console-es-key", default=os.getenv("FRAME_TESTER_CONSOLE_ES_KEY") or "",
                    help="the TARGET frame's EventStore internal key (its "
                         "API_TEST_EVENT_STORE_API_KEY). Required for the console to VERIFY "
                         "emissions: the sweep's events land in the target's store, and that "
                         "store's key cannot be derived. Without it every emission axis reads "
                         "'unknown' — now with an HTTP 403 named beside it, rather than silently.")
    ap.add_argument("--tester-console-es-url", default=os.getenv("FRAME_TESTER_CONSOLE_ES_URL") or "",
                    help="override the target's EventStore URL. Normally UNSET: the registry "
                         "derives it from --tester-console (`<prefix>-registry` → "
                         "`<prefix>-event-store:8200`), so the rule lives in one place. Set this "
                         "only for a target that does not follow that naming.")
    ap.add_argument("--showcase-payer-float", default=os.getenv("FRAME_SHOWCASE_PAYER_FLOAT", "100"),
                    help="§SHOWCASEPAY: the treasury float given to the showcase payer created when --showcase-catalog-json "
                         "is set (0 = create no payer; the showcase's calls then answer 402)")
    ap.add_argument("--showcase-catalog-json", default=None,
                    help="row: his \"showcase shows its own agents\" — a JSON catalog of THIS "
                         "frame's showcase agents; unset leaves the showcase off rather than "
                         "publishing Frame A's eleven agents at Frame A's addresses.")
    ap.add_argument("--env-label", default="sandbox", help="the frame's group on the landing page / status page / auditor (sandbox | candidate | prod)")
    ap.add_argument("--role", default="", help="the one-line role shown on the landing page")
    ap.add_argument("--resume-stack-dir", default=None,
                    help="§BATCH10: resume an INTERRUPTED standup on this stack dir (the frame is already up); every step before --resume-from is skipped")
    ap.add_argument("--resume-until", default=None, help="§BATCH10: stop after this step (e.g. re-run only `spire`)")
    ap.add_argument("--resume-from", default="jurisdiction", choices=["compose", "spire", "seed", "login", "emission", "vhosts", "admin", "jurisdiction", "federate", "operators", "canary", "wire", "mtls"])
    # §FRAMEPROV P1 (2026-09-13): what the admin UI's runner needs from this driver
    ap.add_argument("--plan", action="store_true", default=False,
                    help="run every argument refusal and preflight check, derive the ports, URLs and images, check DNS and "
                         "the certificate, print ONE JSON document on stdout and exit 0 (ok) or 2 (refused). Writes nothing.")
    ap.add_argument("--progress-file", default=os.getenv("FRAME_PROGRESS_FILE") or None,
                    help="append one JSON line per step boundary: {ts, step, event: start|end|skip|fail|live, verdict, "
                         "sentence}. Unset: <stack dir>/standup-progress.jsonl once the stack dir exists")
    ap.add_argument("--allocate-ports", action="store_true", default=False,
                    help="take the seven host ports from frame_ports.py (free on this host and unclaimed by any stack) "
                         "instead of FRAME_TEST_PORT_* or the fixed defaults; refused beside a declared FRAME_TEST_PORT_*")
    ap.add_argument("--secrets-dir", default=None,
                    help="where this frame's secret files go (created 0700). Default: FRAME_SECRETS_DIR, else sessionlogs2026/")
    return ap


def kit_directory_default(args):
    """§SOVKIT S5 (2026-09-14, measured on orchard): the kit ships the frame's OWN Directory behind its mTLS read leg, so
    a standup that names no --directory-upstream reads that leg; the flag still names another index when given. Without
    this the "one flag writes all three or none" rule (§FRAMELIC) blanked DIRECTORY_MTLS_URL, DIRECTORY_PUBLIC_URL and
    DISCOVERY_VIA_DIRECTORY on a frame that had just started its own index: the registry proxy said configured=false
    and Discovery never asked it."""
    if not getattr(args, "directory_upstream", ""):
        args.directory_upstream = f"https://{args.name}-directory-nginx:8443"
    return args.directory_upstream


def resume_shape_refusal(stack_dir, name, templates=None):
    """§MTLSHOPS T2 (2026-09-15, with agentvault2-85): the sentence refusing a resume of a stack another template
    generation rendered, or None. A resume runs THIS driver and provisioner on the stack, so a frame built before them
    (lantern predates T2) would be half-converted; template_shape.py compares the generation line and the service set."""
    tmpl = os.path.join(templates or TEMPLATES, "docker-compose.frame-test.yml.tmpl")
    why = template_shape.stack_template_mismatch(stack_dir, tmpl, name)
    if not why:
        return None
    try:
        with open(tmpl, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""
    return template_shape.refusal_sentence(name, why, text)


def main():
    global PROGRESS
    ap = build_parser()
    args = ap.parse_args()
    if args.own_host:
        # §HELLOFRAME: no host vhost and no host certificate exist on a stranger's host; the edge is a sibling project
        args.enable_vhost = False
    kit_directory_default(args)   # the frame's own Directory leg unless the caller names another index
    if args.plan:
        sys.exit(plan(args))
    if args.progress_file:
        PROGRESS = Progress(args.progress_file)
    _pre("validate")
    for _refusal in validate_args(args):
        die(_refusal)
    log(f"es_public_url: {args.es_public_url}")
    log(f"federation_public_url (BILATERAL_PEER_URL): {args.federation_public_url}")

    for _refusal in derive_run_values(args):
        die(_refusal)
    if args.secrets_dir:
        _use_secrets_dir(args.secrets_dir, create=True)
        log(f"secrets dir: {extras.SECRETS_DIR} (0700)")

    if getattr(args, "resume_stack_dir", None):   # §BATCH10 finding 31: an interrupted standup resumes, it is not redone
        _sd = args.resume_stack_dir.rstrip("/")
        meta = json.load(open(os.path.join(_sd, "hetzner-demo-run.json")))
        # §MTLSHOPS T2 (2026-09-15): refuse, before anything loads, a stack another template generation rendered (R31)
        _shape_refusal = resume_shape_refusal(_sd, meta.get("name") or args.name)
        if _shape_refusal:
            die(_shape_refusal, code=2)
        _restore_ports_from_meta(meta)   # §FRAMEPROV P1: a resume uses the ports the frame was stood up with
        _e = {}
        for _line in open(os.path.join(_sd, ".env.frame-test")):
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1); _e[_k.strip()] = _v.strip().strip('"')
        args.admin_email = _e.get("FIRST_ADMIN_EMAIL", args.admin_email); args.admin_password = _e.get("FIRST_ADMIN_PASSWORD", getattr(args, "admin_password", None))
        # §F6 WP6.5/A4: a resume keeps the bundle endpoint the frame was BORN with (its own env), never a new default
        if not (getattr(args, "bundle_public_url", "") or "").strip():
            args.bundle_public_url = _e.get("FRAME_LOCAL_BUNDLE_ENDPOINT_URL", "")
        prov = load_provisioner()
        ctx = build_ctx(args, int(meta["ts"]), prov)
        ctx.stack_dir_host = _sd; ctx.stack_dir_container = _sd
        log(f"RESUME on {_sd} from step '{args.resume_from}' (frame {meta.get('name')} ts {meta.get('ts')}); nothing before it runs again")
        if PROGRESS is None:   # §FRAMEPROV P1: a resumed CLI run keeps its progress beside its run meta
            PROGRESS = Progress(os.path.join(_sd, "standup-progress.jsonl"))
        _pre(None)
        post_boot(args, ctx, meta, resume_from=args.resume_from, prov=prov)
        return
    _pre("preflight")
    if args.allocate_ports:
        _apply_allocated_ports(args)
    args.bundle_public_url = default_bundle_public_url(args)   # §F6 WP6.5/A4
    log(f"bundle endpoint advertised: {args.bundle_public_url or 'none named and no public host: the compose-internal fallback'}")
    preflight(args)
    _pre("render")
    prov = load_provisioner()
    ts = int(time.time())
    ctx = build_ctx(args, ts, prov)
    log(f"stack dir: {ctx.stack_dir_host}")
    ok, detail = prov.generate_spire_x509pop_certs(ctx)
    if not ok:
        die(f"spire certs: {detail}")
    log(f"spire certs: {detail}")
    ok, detail = prov.write_stack_files(ctx)
    if not ok:
        die(f"stack files: {detail}")
    log(f"stack files: {detail}")

    # §ONESHOT P2.1 — the anchor issues the joining frame's licence BEFORE it exists (§12c's order,
    # done by the driver instead of by hand); the approve later finds the live licence and reuses it.
    if (getattr(args, "federate_with", None) or []) and not (args.federation_license_key or "").strip():
        _lk = federate.pre_issue_license(args.federate_with[0], args.name, args.trust_domain)
        if _lk:
            args.federation_license_key = _lk
    mutate_rendered(ctx, args)

    meta = {"name": args.name, "ts": ts, "stack_dir": ctx.stack_dir_host,
            "trust_domain": args.trust_domain, "ticker": args.ticker, "currency_name": args.currency_name,
            "admin_email": args.admin_email, "public_url": args.public_url,
            # §ONESHOT P2.1 — a peer's federate step reads these instead of guessing them
            "frame_label": args.frame_label, "env_label": getattr(args, "env_label", "sandbox"),
            "es_public_url": args.es_public_url, "federation_public_url": args.federation_public_url,
            "ports": dict(PORTS), "port_push": ctx.port_ntfy, "port_grafana": ctx.port_grafana, "port_auditor": ctx.port_auditor, "steps_done": []}
    open(os.path.join(ctx.stack_dir_host, "hetzner-demo-run.json"), "w").write(json.dumps(meta, indent=2))
    if PROGRESS is None:   # §FRAMEPROV P1: a CLI run keeps its progress beside its run meta
        PROGRESS = Progress(os.path.join(ctx.stack_dir_host, "standup-progress.jsonl"))
        PROGRESS.start("render")

    _pre("compose-up")
    # §MTLSHOPS (2026-09-15): the SPIRE entries go in before the full compose up (register_entries_before_compose says why)
    ok, detail = register_entries_before_compose(ctx, prov, args)
    if not ok:
        die(f"spire entries before compose up: {detail}")
    log(f"spire entries before compose up: {detail}")
    _mark_meta(ctx, meta, "spire_entries_before_compose")
    log("compose up — narrate the architecture now; this is the ~90-180s window")
    # provision_frame_test RAISES on a compose abort, so the reconcile below has
    # to sit in the failure path too — putting it after a bare call meant a slow
    # redpanda killed the whole run before the retry could ever execute.
    try:
        res = prov.provision_frame_test(ctx, timeout_seconds=420)
        log(f"provision result: containers={res.containers_started} (13 = registry healthy)")
    except Exception as e:
        log(f"provision raised ({str(e).splitlines()[0][:120]}) — reconciling before judging it")

    _pre(None)
    post_boot(args, ctx, meta, prov=prov)


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  (used in admin_login)
    try:
        main()
    except SystemExit:
        raise
    except BaseException as _exc:  # noqa: BLE001 — record the crash for a runner, then fail exactly as before
        if PROGRESS is not None:
            PROGRESS.fail(f"{type(_exc).__name__}: {str(_exc)[:400]}")
        raise
