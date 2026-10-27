"""§ONESHOT P2.2 (2026-09-12) — the sidecars a frame is wired into, named in ONE manifest.

WHY. `--wire-prod` used to be seven bare writes into files this host happens to have (the Prometheus
config, the auditor's env and compose, the two apex vhosts, the stream SNI map, registry-a's compose
line, two lists under /etc/theprotocol) and each raised a Python path when the file was missing
(FileNotFoundError, AssertionError) — a stranger's host got a traceback, not a sentence. Teardown removed
none of them, so a reprovision walked into its own litter. And the per-frame SPIRE bundle every ES vhost
verifies peers against was exported once and never refreshed (F1 in FINDINGS_2026-09-12_ONESHOT.md).

NOW. `sidecars/sidecars.json` names where each artifact lives on THIS host (the live auditor, directory,
Prometheus, the bundle lists and refresh script, the SNI script, the apex vhosts); a stranger's host
names the compose project in `sidecars/docker-compose.sidecars.yml` instead (`sidecars.json.example`).
`require()` answers with sentences, `wire()` writes the frame's slot into each artifact (idempotent),
`unwire()` removes exactly that slot and nothing shared, `register_bundle()` puts the frame's SPIRE
bundle under the 5-minute refresh and builds the federated bundle OF ITS IDENTITY NET (one file per
net: a sandbox pair's roots never enter the production pair's client-CA file).
Relative paths in the manifest resolve against the stack root.

§FRAMEKIT P3.1 (2026-09-12). Three things the P2 shape could not do, each measured on the live cluster:
  · the flagship's public status page showed 0 of 90 days on EVERY component (`job: null` on all eight):
    a frame's registry reads Prometheus by the name in PROMETHEUS_URL (code default `prometheus:9090`),
    and the container Prometheus was joined to `eu_network` WITHOUT that alias. Joins now carry the
    aliases the code's defaults use (`prometheus.aliases`, `metrics_store.aliases`), and the driver
    writes PROMETHEUS_URL / VICTORIA_METRICS_URL into the frame's env from this manifest
    (`metrics_env_lines`) so the frame never depends on a default it cannot resolve.
  · a compose recreate of Prometheus (or the auditor, or the metrics store) drops every network that was
    joined by `docker network connect` — the §pass23 10-hour ServiceDown storm. `reconcile()` derives the
    networks each sidecar must share from what it is CONFIGURED to read (the scrape targets, the
    auditor's frame list) and re-joins them, idempotently; run it after any sidecar recreate.
  · file_sd targets carried no `job` label, so on a file_sd host every target sat under the one job
    `frames` and the status page (which keys history on `<slug>-registry`) found nothing. A target's
    own `job` label beats the scrape config's job_name in Prometheus; `file_sd_targets()` writes it.
"""
import contextlib
import fcntl
import importlib.util as _ilu
import json
import os
import re
import subprocess
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = _ilu.spec_from_file_location("standup_extras", os.path.join(_HERE, "standup_extras.py"))
extras = _ilu.module_from_spec(_spec); _spec.loader.exec_module(extras)   # type: ignore[union-attr]

REPO = extras.REPO
DOMAIN = extras.DOMAIN
MANIFEST = os.path.join(REPO, "sidecars", "sidecars.json")


class SidecarsMissing(SystemExit):
    """Raised with ONE sentence naming what is missing and how to get it."""


def load(path: Optional[str] = None) -> Dict[str, Any]:
    p = path or os.getenv("FRAME_SIDECARS_MANIFEST") or MANIFEST
    if not os.path.exists(p):
        raise SidecarsMissing(f"--wire-prod needs the sidecar manifest {p}: copy sidecars/sidecars.json.example beside it and "
                              f"name where the auditor, Prometheus, the bundle refresh and the SNI script live on this host "
                              f"(or stand up sidecars/docker-compose.sidecars.yml and point the manifest at it)")
    m = json.load(open(p))
    m["_path"] = p
    return m


def resolve(m: Dict[str, Any], p: str) -> str:
    return p if os.path.isabs(p) else os.path.join(REPO, p)


def _running(container: str) -> bool:
    r = subprocess.run(["docker", "inspect", container, "--format", "{{.State.Running}}"], capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def require(m: Dict[str, Any], *, need_apex: bool = False, need_directory: bool = False,
            only: Optional[set] = None) -> List[str]:
    """Every reason --wire-prod cannot proceed, as sentences. Empty = go. `only` restricts the questions to the pieces
    `wire(only=...)` will write (§NIGHTPROV: a nightly sandbox pair wires sni + bundle and asks nothing of the auditor,
    Prometheus or the apex it never touches); None = every piece, as before."""
    out: List[str] = []
    want = (lambda k: only is None or k in only)
    a = (m.get("auditor") or {}) if want("auditor") else {}   # parenthesised: `x or {} if c else {}` binds as `x or ({} ...)`
    for k in (("env", "compose") if want("auditor") else ()):
        if not a.get(k) or not os.path.exists(resolve(m, a[k])):
            out.append(f"the auditor's {k} file ({a.get(k)}) is not there: the frame cannot get an auditor slot — "
                       f"stand up the auditor (Agents/TheAuditor or the sidecar compose project) and name it in the manifest")
            break
    if a.get("container") and not _running(a["container"]):
        out.append(f"the auditor container {a['container']} is not running: `docker compose up -d` it first, "
                   f"or the slot would be written to a stopped instance")
    if want("prometheus"):
        pr = m.get("prometheus") or {}
        if pr.get("mode", "static-yml") == "static-yml":
            if not pr.get("config") or not os.path.exists(resolve(m, pr["config"])):
                out.append(f"the Prometheus config ({pr.get('config')}) is not there: nothing can scrape the frame — "
                           f"name it in the manifest or use the sidecar compose project's file_sd mode")
        else:
            d = resolve(m, pr.get("targets_dir", ""))
            if not pr.get("targets_dir") or not os.path.isdir(d):
                out.append(f"the Prometheus file_sd targets dir ({pr.get('targets_dir')}) is not there: create it and mount it "
                           f"into Prometheus (the sidecar compose project does)")
            elif pr.get("container") and _running(pr["container"]):
                # the dir exists on the host; the question is whether THIS Prometheus can READ it — as the user it runs
                # as (nobody), through its compose mount. `ls`, not `test -d`: a 750 root dir passes a stat and fails a read.
                r = subprocess.run(["docker", "exec", pr["container"], "sh", "-c", f"ls {pr.get('mounted_at', '/etc/prometheus/targets')} >/dev/null"],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    out.append(f"the Prometheus container {pr['container']} cannot read the targets dir at "
                               f"{pr.get('mounted_at', '/etc/prometheus/targets')} ({(r.stderr or '').strip()[-80:] or 'not mounted'}): "
                               f"a targets file written there scrapes nothing — mount `{pr.get('targets_dir')}` (and recreate Prometheus, "
                               f"then `sidecars.py reconcile`), or `chmod 755` it: Prometheus runs as nobody and this box's umask writes 750")
        if pr.get("container") and not _running(pr["container"]):
            out.append(f"the Prometheus container {pr['container']} is not running: the frame's scrape job would reload nothing")
        if not pr.get("query_url"):
            out.append("the manifest names no prometheus.query_url: the frame's status page would read its history from a code "
                       "default (`http://prometheus:9090`) that resolves on nobody's network — name the URL a frame reaches Prometheus at")
        ms = m.get("metrics_store") or {}
        if ms.get("container") and not _running(ms["container"]):
            out.append(f"the metrics store container {ms['container']} is not running: the frame's degradation panel would read nothing")
    if want("bundle"):
        b = m.get("bundles") or {}
        if not b.get("refresh") or not os.access(resolve(m, b["refresh"]), os.X_OK):
            out.append(f"the SPIRE bundle refresh script ({b.get('refresh')}) is not installed: `install -m 755 "
                       f"scripts/deploy/frame-spire-bundle.sh /usr/local/bin/` and add its cron line (F1)")
        if b.get("cron_marker"):
            r = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
            if b["cron_marker"] not in (r.stdout or ""):
                out.append(f"no crontab line runs {b['cron_marker']}: a one-shot bundle rots at the next CA rotation — "
                           f"add `0-59/5 * * * * {b.get('refresh')}` through `crontab <file>` (never in place)")
    if want("sni"):
        s = m.get("sni") or {}
        if not s.get("script") or not os.path.exists(resolve(m, s["script"])):
            out.append(f"the SNI map script ({s.get('script')}) is not there: without a stream SNI line the frame's mTLS "
                       f"federation address falls through to another frame's nginx")
        if s.get("conf") and not os.path.exists(s["conf"]):
            out.append(f"the stream SNI map {s['conf']} is not there: this host's nginx has no mTLS federation stream — "
                       f"a frame cannot be reached on :8443 here")
    if need_apex and want("apex"):
        ap = m.get("apex") or {}
        for v in ap.get("vhosts") or []:
            if not os.path.exists(os.path.join(extras.NGINX_ENABLED, v)):
                out.append(f"the apex vhost {v} is not enabled on this host: the landing page cannot stream the frame's ledger")
        if ap.get("prod_compose") and not os.path.exists(resolve(m, ap["prod_compose"])):
            out.append(f"the production compose ({ap['prod_compose']}) is not there: FRESH_NETWORK_JSON has no home")
    if need_directory and want("directory"):
        d = m.get("directory") or {}
        if not d.get("env") or not os.path.exists(resolve(m, d["env"])):
            out.append(f"the Directory's env ({d.get('env')}) is not there: the frame cannot be anchored in the index")
    return out


# ── the SPIRE bundles: per frame, and a federated file per identity net ──────────────────────────

def federated_bundle_for_net(m: Dict[str, Any], net: str) -> Tuple[str, str]:
    b = m.get("bundles") or {}
    by_net = b.get("federated_by_net") or {}
    if net in by_net:
        return by_net[net]["list"], by_net[net]["pem"]
    tag = re.sub(r"[^a-z0-9]+", "-", (net or "default").lower()).strip("-")
    return f"/etc/theprotocol/{tag}-federated-bundle.list", f"/etc/nginx/{tag}-federated-spire-bundle.pem"


def _append_line(path: str, line: str, mode: int = 0o640) -> bool:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = [l.rstrip("\n") for l in open(path)] if os.path.exists(path) else []
    if line in lines:
        return False
    open(path, "w").write("\n".join([*lines, line]) + "\n"); os.chmod(path, mode)
    return True


def _remove_lines(path: str, pred) -> int:
    if not os.path.exists(path):
        return 0
    lines = [l.rstrip("\n") for l in open(path)]
    keep = [l for l in lines if not pred(l)]
    if len(keep) != len(lines):
        open(path, "w").write("\n".join(keep) + ("\n" if keep else ""))
    return len(lines) - len(keep)


# §NIGHTPROV (2026-10-06, agentvault2-09): the lock frame-spire-bundle.sh holds for its whole run. A teardown takes it
# while a frame's lines and files go, so a refresh run that read the list a moment earlier cannot write the frame's
# pem back after it was removed: nightly nt261006's 01:05:00Z tick was still walking the list when nt261006a's teardown
# removed its line and pem (01:05:02Z), fetched from the still-running server, found the file absent ("was 0 / 0
# valid") and wrote it back; the pair's leftover check failed on it. The same path in the shell script.
FRAME_SPIRE_BUNDLE_LOCK = os.getenv("FRAME_SPIRE_BUNDLE_LOCK", "/run/lock/theprotocol-frame-spire-bundle.lock")


@contextlib.contextmanager
def _bundle_writer_lock(log=extras.log, timeout: float = 180.0):
    """Hold FRAME_SPIRE_BUNDLE_LOCK (flock, the same lock `flock(1)` takes in the refresh script). Yields whether it is
    held. It guards a race, it grants nothing: a lock that cannot be opened, or is not free within `timeout`, is
    logged and the step goes on without it. Never call the refresh script while holding it (the refresh waits on it)."""
    fd = None
    try:
        fd = os.open(FRAME_SPIRE_BUNDLE_LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as exc:
        log(f"sidecars: {FRAME_SPIRE_BUNDLE_LOCK} not opened ({exc}); going on without the refresh lock")
    held = False
    if fd is not None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                held = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    log(f"sidecars: {FRAME_SPIRE_BUNDLE_LOCK} still held after {timeout:.0f} s; going on without it")
                    break
                time.sleep(0.5)
    try:
        yield held
    finally:
        if fd is not None:
            os.close(fd)   # closing the descriptor releases the flock


def register_bundle(m: Dict[str, Any], name: str, net: str, *, log=extras.log) -> Dict[str, str]:
    """The frame's per-frame PEM under the 5-minute refresh, its identity net's federated bundle rebuilt.
    Returns {'pem': per-frame pem, 'federated_pem': the net's file the ES vhost must name}."""
    b = m["bundles"]
    pem = f"/etc/nginx/{name}-spire-bundle.pem"
    fl, fpem = federated_bundle_for_net(m, net)
    a1 = _append_line(resolve(m, b["frames_list"]), f"{pem} {name}-spire-server")
    a2 = _append_line(fl, pem)
    a3 = _append_line(resolve(m, b["federated_lists"]), f"{fl} {fpem}")
    r = subprocess.run([resolve(m, b["refresh"])], env={**os.environ, "FORCE": "1"}, capture_output=True, text=True, timeout=300)
    roots = open(pem).read().count("BEGIN CERTIFICATE") if os.path.exists(pem) else 0
    froots = open(fpem).read().count("BEGIN CERTIFICATE") if os.path.exists(fpem) else 0
    log(f"sidecars: bundle {pem} ({roots} root(s)) under refresh (list {'added' if a1 else 'present'}); federated {fpem} "
        f"({froots} root(s), net {net}, list {'added' if a2 else 'present'}, registered {'added' if a3 else 'present'}); refresh rc={r.returncode}")
    if roots < 1 or froots < 1:
        raise SystemExit(f"sidecars: the refresh produced no roots for {name} ({r.stdout[-200:]}{r.stderr[-200:]}) — "
                         f"is {name}-spire-server running?")
    return {"pem": pem, "federated_pem": fpem, "federated_list": fl}


def unregister_bundle(m: Dict[str, Any], name: str, net: str, *, log=extras.log) -> None:
    b = m["bundles"]
    pem = f"/etc/nginx/{name}-spire-bundle.pem"
    fl, fpem = federated_bundle_for_net(m, net)
    # the lines and the files go under the refresh script's own lock (see _bundle_writer_lock); the refresh this
    # function runs afterwards takes that lock itself, so it is released first
    with _bundle_writer_lock(log):
        n1 = _remove_lines(resolve(m, b["frames_list"]), lambda l: l.split(" ")[0] == pem)
        n2 = _remove_lines(fl, lambda l: l.strip() == pem)
        left = [l for l in open(fl)] if os.path.exists(fl) else []
        left = [l for l in left if l.strip() and not l.startswith("#")]
        # never delete a file a vhost still names: nginx -t fails for the WHOLE host on a missing
        # ssl_client_certificate (measured 2026-09-12: a torn-down node's vhost still named the pem)
        still = subprocess.run(["grep", "-rl", pem, extras.NGINX_ENABLED], capture_output=True, text=True).stdout.split()
        if os.path.exists(pem) and still:
            log(f"sidecars: {pem} is still named by {still} — kept (disable that vhost first, then remove the file)")
        elif os.path.exists(pem):
            os.remove(pem)
        if not left:
            _remove_lines(resolve(m, b["federated_lists"]), lambda l: l.split(" ")[0] == fl)
            for p in (fl, fpem):
                if os.path.exists(p):
                    os.remove(p)
    if left:
        subprocess.run([resolve(m, b["refresh"])], env={**os.environ, "FORCE": "1"}, capture_output=True, text=True, timeout=300)
        log(f"sidecars: bundle of {name} unregistered ({n1}+{n2} line(s)); {fpem} rebuilt from {len(left)} remaining frame(s)")
    else:
        subprocess.run(["nginx", "-t"], capture_output=True)
        log(f"sidecars: bundle of {name} unregistered; net {net} had no other frame — {fl} and {fpem} removed")


# ── wire / unwire ───────────────────────────────────────────────────────────────────────────────

# ── networks: a sidecar must share a network with every container it reads by name ─────────────

def net_membership(container: str) -> Dict[str, List[str]]:
    """{network: [aliases]} the container is on now (empty when it does not exist)."""
    r = subprocess.run(["docker", "inspect", container, "--format", "{{json .NetworkSettings.Networks}}"], capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        return {}
    try:
        nets = json.loads(r.stdout)
    except ValueError:
        return {}
    return {n: list((v or {}).get("Aliases") or []) for n, v in (nets or {}).items()}


def join_plan(current: Dict[str, List[str]], net: str, aliases: List[str]) -> str:
    """ok | connect | reconnect — the decision, pure. A join that lacks an alias the code's defaults
    resolve (`prometheus`, `victoriametrics`) is a join the frame cannot use, so it is redone WITH them."""
    if net not in current:
        return "connect"
    have = set(current.get(net) or [])
    return "ok" if set(aliases) <= have else "reconnect"


def network_exists(net: str) -> bool:
    return subprocess.run(["docker", "network", "inspect", net], capture_output=True).returncode == 0


def ensure_on_network(container: str, net: str, aliases: List[str], *, log=extras.log) -> str:
    """Put `container` on `net` carrying `aliases`; idempotent; returns the plan that was applied
    (ok / connect / reconnect / no-such-network / no-such-container)."""
    if not network_exists(net):
        return "no-such-network"
    cur = net_membership(container)
    if not cur and not _running(container):
        return "no-such-container"
    plan = join_plan(cur, net, aliases)
    if plan == "ok":
        return plan
    if plan == "reconnect":
        subprocess.run(["docker", "network", "disconnect", net, container], capture_output=True)
    cmd = ["docker", "network", "connect"]
    for a in aliases:
        cmd += ["--alias", a]
    r = subprocess.run(cmd + [net, container], capture_output=True, text=True)
    if r.returncode != 0 and "already exists" not in (r.stderr or ""):
        log(f"sidecars: {container} could not join {net}: {(r.stderr or '').strip()[-160:]}")
        return "failed"
    log(f"sidecars: {container} {plan}ed to {net}" + (f" as {'/'.join(aliases)}" if aliases else ""))
    return plan


def frame_net_name(name: str) -> str:
    """The docker network a frame's containers live on. The provisioner names it
    `<registry_name with '-' -> '_'>_network` (services/frame_test_provisioner.py:355 `self.net_name`), so
    `sbx-alpha` lives on `sbx_alpha_network` — a rule this module got wrong for every hyphenated name
    until 2026-09-12 (the P2 proof pair, juice and brrr, carried no hyphen and never hit it)."""
    return f"{name.replace('-', '_')}_network"


def frame_networks(f: Dict[str, Any]) -> Tuple[str, List[str]]:
    """(the frame's own network, [each operator's network])."""
    return frame_net_name(f["name"]), [f"cloud-op-{op}_operator-net" for op in f.get("operators") or []]


# ── Prometheus: the frame's targets, with the job names the status page asks for ────────────

def prepare_targets_dir(m: Dict[str, Any]) -> Optional[str]:
    """The file_sd targets dir readable by the user Prometheus runs as (nobody): 755 on the dir, 644 on every
    file. This box's umask 027 writes 750/640 and the discovery then logs "Error adding file watch ...
    permission denied" every refresh while every target sits undiscovered. Returns the dir (None in static mode)."""
    pr = m.get("prometheus") or {}
    if pr.get("mode", "static-yml") == "static-yml" or not pr.get("targets_dir"):
        return None
    d = resolve(m, pr["targets_dir"])
    os.makedirs(d, exist_ok=True)
    os.chmod(d, 0o755)
    for fn in os.listdir(d):
        fp = os.path.join(d, fn)
        if os.path.isfile(fp):
            os.chmod(fp, 0o644)
    return d


def file_sd_targets(f: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One target group per component. The `job` label is deliberate: Prometheus lets a target's own
    label beat the scrape config's job_name, and the registry's status page keys a component's history
    on `<slug>-registry` / `<slug>-teg` / `<slug>-event-store` / `<op>-registry` (public_status.py) —
    the same names the static-yml writer has always used, so a host can move between the two modes."""
    name, env = f["name"], f.get("env_label") or "sandbox"
    out = []
    for comp, port in (("registry", 8000), ("teg", 8080), ("event-store", 8200)):
        out.append({"targets": [f"{name}-{comp}:{port}"],
                    "labels": {"job": f"{name}-{comp}", "component": comp, "frame": name, "env": env}})
    for op in f.get("operators") or []:
        for comp, port in (("registry", 8000), ("teg", 8080)):
            out.append({"targets": [f"cloud-op-{op}-{comp}:{port}"],
                        "labels": {"job": f"{op}-{comp}", "component": comp, "frame": op, "parent": name, "env": env}})
    return out


def networks_for_targets(targets: List[Dict[str, Any]]) -> List[str]:
    """The docker networks a scraper must share to reach these targets by container name: a frame
    component lives on `<frame>_network`, an operator's on `cloud-op-<op>_operator-net`."""
    nets: List[str] = []
    for t in targets or []:
        lab = t.get("labels") or {}
        frame = lab.get("frame")
        if not frame:
            continue
        net = f"cloud-op-{frame}_operator-net" if lab.get("parent") else frame_net_name(frame)
        if net not in nets:
            nets.append(net)
    return nets


_STATIC_JOB_RE = re.compile(r"^  - job_name: '(?P<job>[^']+)'\n(?P<body>(?:(?!  - job_name: ).*\n?)*)", re.M)


def static_yml_frame_targets(config_text: str) -> List[Dict[str, Any]]:
    """The frame-shaped jobs of a static prometheus.yml (those whose labels carry `frame:`) in the
    file_sd target shape, so `reconcile` can treat both modes as one list."""
    out: List[Dict[str, Any]] = []
    for mm in _STATIC_JOB_RE.finditer(config_text):
        body = mm.group("body")
        tm = re.search(r"targets:\s*\[\s*'([^']+)'", body)
        fm = re.search(r"frame:\s*'([^']+)'", body)
        cm = re.search(r"component:\s*'([^']+)'", body)
        if not (tm and fm):
            continue
        labels = {"job": mm.group("job"), "frame": fm.group(1), "component": cm.group(1) if cm else ""}
        if tm.group(1).startswith("cloud-op-"):
            labels["parent"] = "?"
        out.append({"targets": [tm.group(1)], "labels": labels})
    return out


def wired_targets(m: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every frame-shaped target this host's Prometheus is configured to scrape: the file_sd files
    (when the manifest has a targets dir) plus the static config's frame jobs (when it names one)."""
    pr = m.get("prometheus") or {}
    out: List[Dict[str, Any]] = []
    if pr.get("targets_dir") and os.path.isdir(resolve(m, pr["targets_dir"])):
        for fn in sorted(os.listdir(resolve(m, pr["targets_dir"]))):
            if fn.endswith(".json"):
                try:
                    out += json.load(open(os.path.join(resolve(m, pr["targets_dir"]), fn)))
                except ValueError:
                    extras.log(f"sidecars: {fn} is not valid JSON — skipped by reconcile")
    if pr.get("config") and os.path.exists(resolve(m, pr["config"])):
        out += static_yml_frame_targets(open(resolve(m, pr["config"])).read())
    return out


def auditor_override_expected(m: Dict[str, Any]) -> List[str]:
    """§MTLSHOPS (a) (2026-09-15, agentvault2-85): the networks the host auditor's untracked compose override should hold,
    derived from its frames file (the slots whose store or database reads need a frame network, auditor_frame_networks),
    less the networks its tracked compose already joins. One idempotent derivation, so a lost override is one render away."""
    a = m.get("auditor") or {}
    comp = resolve(m, a["compose"])
    tracked = set(re.findall(r"^      - ([A-Za-z0-9_.-]+)\s*$", open(comp).read(), re.M)) if os.path.exists(comp) else set()
    return [n for n in auditor_frame_networks(m) if n not in tracked]


def render_auditor_override_from_frames(m: Dict[str, Any]) -> List[str]:
    """§MTLSHOPS (a): render the host auditor's override from its frames file (auditor_override_expected); returns the
    networks it now holds."""
    a = m.get("auditor") or {}
    nets = auditor_override_expected(m)
    extras.render_auditor_override(os.path.dirname(resolve(m, a["compose"])), a.get("service", "auditor-agent"), nets)
    return nets


def auditor_override_parity(m: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """§MTLSHOPS (a) (agentvault2-85): (equal, the override's networks, the networks derived from the frames file)."""
    a = m.get("auditor") or {}
    have = sorted(extras.auditor_override_networks(os.path.dirname(resolve(m, a["compose"]))))
    want = sorted(auditor_override_expected(m))
    return have == want, have, want


def keyless_extra_slots(frames_file: str) -> List[str]:
    """§MTLSHOPS (a) (2026-09-15, agentvault2-85): the ids of the host auditor's frames-file slots that carry no key.

    A host auditor image from before mtlshops/aud-public fills a keyless slot's key with its mode key and sends that key to
    the slot's URL, and a public_only or public_read slot names a URL someone else serves. So the (a) rollback strips such
    slots before an older image starts, and refuses to start it while any remains. A missing file answers []; an unreadable
    one answers ["<unreadable frames file>"], which a caller must treat as a refusal. Only ids are returned, never values."""
    if not frames_file or not os.path.exists(frames_file):
        return []
    try:
        frames = json.load(open(frames_file))
    except (OSError, ValueError):
        return ["<unreadable frames file>"]
    if not isinstance(frames, list):
        return ["<unreadable frames file>"]
    return [str(f.get("id")) for f in frames if isinstance(f, dict) and not f.get("key")]


def strip_keyless_extra_slots(frames_file: str, log=extras.log) -> List[str]:
    """§MTLSHOPS (a) (2026-09-15, agentvault2-85): the (a) rollback's first step. Removes every slot without a key from the
    host auditor's frames file (atomic write, 600) and returns the ids removed; refuses (raises) on a file it cannot read,
    because an unread file cannot be proven safe for an older image."""
    before = keyless_extra_slots(frames_file)
    if before == ["<unreadable frames file>"]:
        raise ValueError(f"{frames_file}: unreadable, so it cannot be proven free of keyless slots")
    if not before:
        return []
    frames = json.load(open(frames_file))
    keep = [f for f in frames if not (isinstance(f, dict) and not f.get("key"))]
    tmp = frames_file + ".tmp"
    with open(tmp, "w") as fh:
        fh.write(json.dumps(keep, indent=1) + "\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, frames_file)
    log(f"sidecars: removed {len(before)} keyless slot(s) from the host auditor's frames file: {', '.join(before)}")
    return before


def auditor_frame_networks(m: Dict[str, Any]) -> List[str]:
    """The frame networks the auditor's own frame list names (each entry's EventStore URL is
    `http://<name>-event-store:8200`, and that container lives on `<name>_network`)."""
    a = m.get("auditor") or {}
    frames: List[Dict[str, Any]] = []
    fp = resolve(m, a["frames_file"]) if a.get("frames_file") else ""
    if fp and os.path.exists(fp):
        try:
            frames = json.load(open(fp))
        except ValueError:
            frames = []
    elif a.get("env") and os.path.exists(resolve(m, a["env"])):
        mm = re.search(r"^AUDITOR_EXTRA_FRAMES_JSON=(.*)$", open(resolve(m, a["env"])).read(), re.M)
        try:
            frames = json.loads(mm.group(1)) if mm and mm.group(1).strip() else []
        except ValueError:
            frames = []
    nets: List[str] = []
    for fr in frames if isinstance(frames, list) else []:
        host = re.sub(r"^https?://", "", str(fr.get("url") or "")).split(":")[0]
        mm = re.match(r"^(.+)-event-store$", host)
        name = mm.group(1) if mm else ""
        # §MTLSHOPS (a): a public_read slot's url is the frame's public address, but its DSNs still read over the frame's
        # network; a public_only slot has neither and joins nothing
        if not name and fr.get("id") and any(fr.get(k) for k in ("dsn", "reg_dsn", "teg_dsn")):
            name = str(fr["id"])
        if name and frame_net_name(name) not in nets:
            nets.append(frame_net_name(name))
    return nets


def reconcile(m: Dict[str, Any], *, log=extras.log) -> Dict[str, Any]:
    """Re-join every sidecar to every network it must share, from what each is configured to read.
    Idempotent (every join is a plan: ok / connect / reconnect); run after any sidecar recreate,
    because compose recreates a container with its compose networks only."""
    done: Dict[str, Any] = {"prometheus": {}, "metrics_store": {}, "auditor": {}}
    pr = m.get("prometheus") or {}
    targets = wired_targets(m)
    nets = [n for n in networks_for_targets(targets) if network_exists(n)]
    if pr.get("container"):
        for n in nets:
            done["prometheus"][n] = ensure_on_network(pr["container"], n, list(pr.get("aliases") or []), log=log)
        for n in pr.get("extra_networks") or []:   # e.g. the default bridge: no alias allowed there, joined bare
            done["prometheus"][n] = ensure_on_network(pr["container"], n, [], log=log)
    ms = m.get("metrics_store") or {}
    if ms.get("container"):
        for n in nets:
            if n.endswith("_network"):   # frames read the store; operators carry no such URL
                done["metrics_store"][n] = ensure_on_network(ms["container"], n, list(ms.get("aliases") or []), log=log)
    a = m.get("auditor") or {}
    if a.get("container"):
        for n in auditor_frame_networks(m):
            if network_exists(n):
                done["auditor"][n] = ensure_on_network(a["container"], n, [], log=log)
    summary = {k: {"ok": sum(1 for v in d.values() if v == "ok"), "joined": sum(1 for v in d.values() if v in ("connect", "reconnect")),
                   "failed": sum(1 for v in d.values() if v == "failed")} for k, d in done.items()}
    log(f"sidecars: reconcile {json.dumps(summary)}")
    done["summary"] = summary
    return done


def metrics_env_lines(m: Dict[str, Any]) -> List[Tuple[str, str]]:
    """The two env lines a frame needs to read its own observability, from the manifest: PROMETHEUS_URL
    (the status page's 30-day history, the eight admin panels) and VICTORIA_METRICS_URL (the degradation
    panel's four signals; the long-term store when the host has one, else Prometheus itself — both speak
    /api/v1/query). Empty when the manifest names no query_url: the frame then reports "not configured"
    rather than dialing a default."""
    pr = m.get("prometheus") or {}
    q = (pr.get("query_url") or "").strip().rstrip("/")
    if not q:
        return []
    ms = m.get("metrics_store") or {}
    return [("PROMETHEUS_URL", q), ("VICTORIA_METRICS_URL", (ms.get("url") or "").strip().rstrip("/") or q)]


def _prom_remove_jobs(path: str, jobs: List[str]) -> int:
    s = open(path).read(); n = 0
    for job in jobs:
        pat = re.compile(rf"^  - job_name: '{re.escape(job)}'\n(?:(?!  - job_name: ).*\n?)*", re.M)
        s, k = pat.subn("", s); n += k
    if n:
        extras._bak(path, "unwire")
        open(path, "w").write(s)
    return n


def _prom_reload(m: Dict[str, Any]) -> int:
    pr = m.get("prometheus") or {}
    if not pr.get("container"):
        return -1
    r = subprocess.run(["docker", "exec", pr["container"], "wget", "-q", "--post-data=", "-O", "-",
                        "http://localhost:9090/-/reload"], capture_output=True, text=True)
    return r.returncode


def _auditor_remove_slot(m: Dict[str, Any], slug: str, net: str) -> Tuple[bool, bool]:
    a = m["auditor"]; envp = resolve(m, a["env"]); comp = resolve(m, a["compose"])
    removed = False
    # §FRAMEKIT P3.1: the frames FILE first (the auditor re-reads it on reload), then the env carrier if it still names the slot
    ff = resolve(m, a["frames_file"]) if a.get("frames_file") else ""
    if ff and os.path.exists(ff):
        try:
            frames = json.load(open(ff))
        except ValueError:
            frames = []
        keep = [f for f in frames if f.get("id") != slug]
        if len(keep) != len(frames):
            tmp = ff + ".tmp"; open(tmp, "w").write(json.dumps(keep, indent=1) + "\n"); os.chmod(tmp, 0o600); os.replace(tmp, ff); removed = True
    s = open(envp).read() if os.path.exists(envp) else ""
    mm = re.search(r"^AUDITOR_EXTRA_FRAMES_JSON=(.*)$", s, re.M)
    if mm:
        frames = json.loads(mm.group(1)) if mm.group(1).strip() else []
        keep = [f for f in frames if f.get("id") != slug]
        if len(keep) != len(frames):
            s = s[:mm.start()] + "AUDITOR_EXTRA_FRAMES_JSON=" + json.dumps(keep, separators=(",", ":")) + s[mm.end():]
            open(envp, "w").write(s); os.chmod(envp, 0o600); removed = True
    t = open(comp).read(); net_removed = False
    # §MTLSHOPS (a): a join lives in the untracked override; one from before that change may still be in the tracked compose
    _joined = extras.auditor_override_networks(os.path.dirname(comp))
    if net in _joined:
        extras.render_auditor_override(os.path.dirname(comp), a.get("service", "auditor-agent"), [n for n in _joined if n != net])
        net_removed = True
    if f"      - {net}\n" in t or re.search(rf"^  {re.escape(net)}:\n    external: true\n", t, re.M):
        extras._bak(comp, f"unwire-{slug}")
        t = t.replace(f"      - {net}\n", "")
        t = re.sub(rf"^  {re.escape(net)}:\n    external: true\n", "", t, flags=re.M)
        open(comp, "w").write(t); net_removed = True
    if removed or net_removed:
        rc = subprocess.run(["docker", "compose", "config", "-q"], cwd=os.path.dirname(comp), capture_output=True, text=True)
        assert rc.returncode == 0, f"auditor compose invalid after unwire: {rc.stderr[-300:]}"
        if a.get("container"):
            subprocess.run(["docker", "network", "disconnect", net, a["container"]], capture_output=True)
        st, _body = (extras.auditor_reload(a.get("admin_url") or "http://127.0.0.1:8045", extras._auditor_admin_token(os.path.dirname(comp)))
                     if ff else (0, ""))
        if st != 200:   # an older auditor, no token, or no frames file: the recreate is the only way the change reaches it
            extras.log(f"sidecars: auditor reload answered {st} ({str(_body)[:100]}) — recreating the auditor instead")
            subprocess.run(["docker", "compose", "up", "-d", "--no-deps", "--force-recreate", a.get("service", "auditor-agent")],
                           cwd=os.path.dirname(comp), capture_output=True, text=True)
        else:
            extras.log(f"sidecars: auditor reloaded in place after removing {slug}: {str(_body)[:120]}")
    return removed, net_removed


def _apex_remove_ws(m: Dict[str, Any], slug: str) -> int:
    n = 0
    for v in (m.get("apex") or {}).get("vhosts") or []:
        p = os.path.join(extras.NGINX_ENABLED, v)
        if not os.path.exists(p):
            continue
        s = open(p).read()
        pat = re.compile(rf"^    location /ws/events-{re.escape(slug)} \{{\n(?:.*\n)*?    \}}\n", re.M)
        s2, k = pat.subn("", s)
        if k:
            extras._bak(p, f"unwire-{slug}"); open(p, "w").write(s2); n += k
    if n:
        rc = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
        assert rc.returncode == 0, f"nginx -t failed after removing /ws/events-{slug}: {rc.stderr[-300:]}"
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
    return n


def _fresh_network_remove(m: Dict[str, Any], slug: str) -> bool:
    p = resolve(m, (m.get("apex") or {}).get("prod_compose", "docker-compose.production.yml"))
    if not os.path.exists(p):
        return False
    s = open(p).read()
    mm = re.search(r"^(\s+)FRESH_NETWORK_JSON: '(.*)'$", s, re.M)
    if not mm:
        return False
    frames = json.loads(mm.group(2)); keep = [f for f in frames if f.get("slug") != slug]
    if len(keep) == len(frames):
        return False
    extras._bak(p, f"unwire-{slug}")
    open(p, "w").write(s[:mm.start()] + f"{mm.group(1)}FRESH_NETWORK_JSON: '{json.dumps(keep, separators=(',', ':'))}'" + s[mm.end():])
    return True


def frame_data_takes_tls_clients_only(f: Dict[str, Any]) -> bool:
    """§MTLSHOPS T3 (2026-09-15): True when the frame's rendered compose runs its Postgres on the data-tls hba, which takes
    TLS clients with a frame certificate only. No stack dir, or an unreadable compose, answers False (the slot is written
    as before)."""
    sd = (f.get("stack_dir") or "").rstrip("/")
    if not sd:
        return False
    try:
        comp = open(os.path.join(sd, "docker-compose.frame-test.yml")).read()
    except OSError:
        return False
    return "-c hba_file=/opt/data-tls/pg_hba.conf" in comp


def frame_store_is_socket_only(f: Dict[str, Any]) -> bool:
    """§MTLSHOPS (a) (2026-09-15): True when the frame's rendered compose runs its event store on a unix socket only (T2 S4),
    so the host auditor's http://<f>-event-store:8200 reaches nothing and its live read goes to the frame's public supply
    audit instead. No stack dir, or an unreadable compose, answers False."""
    sd = (f.get("stack_dir") or "").rstrip("/")
    if not sd:
        return False
    try:
        comp = open(os.path.join(sd, "docker-compose.frame-test.yml")).read()
    except OSError:
        return False
    return "uvicorn src.main:app --uds /sock/event-store/event-store.sock" in comp


def host_auditor_frame(m: Dict[str, Any], frame_id: str, timeout: int = 10) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """§MTLSHOPS (a): (reachable, entry) for `frame_id` from the host auditor's GET /api/auditor/frames. reachable is False
    when the auditor did not answer, so a caller can tell "no slot" from "not asked"."""
    a = m.get("auditor") or {}
    url = f"{(a.get('admin_url') or 'http://127.0.0.1:8045').rstrip('/')}/api/auditor/frames"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            frames = json.loads(r.read().decode() or "[]")
    except Exception:  # noqa: BLE001
        return False, None
    for fr in frames if isinstance(frames, list) else []:
        if isinstance(fr, dict) and fr.get("id") == frame_id:
            return True, fr
    return True, None


def wire(m: Dict[str, Any], f: Dict[str, Any], *, only: Optional[set] = None, log=extras.log) -> Dict[str, Any]:
    """The frame's slot in every sidecar. `f`: name, frame_label, env_label, ticker, currency_name, role, public_url,
    es_public_url, es_port, fed_port, identity_net, operators. Idempotent; each artifact's own writer is.
    `only` restricts the pass to named pieces (prometheus, auditor, sni, bundle, apex, directory) — how a frame
    that predates a piece is wired into it after the fact (`sidecars.py wire <stack dir> --only prometheus`)."""
    done: Dict[str, Any] = {}
    want = (lambda k: only is None or k in only)
    pr = m.get("prometheus") or {}
    own_net, op_nets = frame_networks(f)
    if want("prometheus"):
        if pr.get("mode", "static-yml") == "static-yml":
            done["prometheus_jobs"] = extras.prometheus_jobs(f["name"], f["env_label"], f.get("operators") or [], prom_path=resolve(m, pr["config"]),
                                                             join=lambda c, n, _a: ensure_on_network(c, n, list(pr.get("aliases") or []), log=log))
        else:
            td = prepare_targets_dir(m) or resolve(m, pr["targets_dir"]); tp = os.path.join(td, f"{f['name']}.json")
            targets = file_sd_targets(f)
            tmp = tp + ".tmp"
            open(tmp, "w").write(json.dumps(targets, indent=1) + "\n"); os.chmod(tmp, 0o644); os.replace(tmp, tp)   # atomic
            if pr.get("container"):
                done["prometheus_joins"] = {net: ensure_on_network(pr["container"], net, list(pr.get("aliases") or []), log=log)
                                            for net in [own_net] + op_nets}
            done["prometheus_targets"] = tp
            done["prometheus_reload_rc"] = _prom_reload(m)
            log(f"sidecars: prometheus file_sd targets {tp} ({len(targets)} target(s), jobs {[t['labels']['job'] for t in targets]})")
        ms = m.get("metrics_store") or {}
        if ms.get("container"):
            done["metrics_store"] = ensure_on_network(ms["container"], own_net, list(ms.get("aliases") or []), log=log)
    a = m.get("auditor") or {}
    if want("auditor"):
        # §MTLSHOPS (a) (2026-09-15, his decision; agentvault2-85's calls). A frame whose databases take TLS clients with a
        # frame certificate only (T3) gets a public_only slot: the host auditor holds no frame certificate, so it reads the
        # frame's public supply audit and nothing else, and the frame's own solo auditor does the exact check. A frame whose
        # store listens on a unix socket only (T2 S4) gets a public_read slot: its live read goes to the public supply audit
        # with no key while its DSNs keep the atomic check. Either shape is written only when the running host auditor lists
        # it; otherwise the T3 frame gets no slot and the T2 frame today's slot, and both say why.
        admin = a.get("admin_url") or "http://127.0.0.1:8045"
        t3 = frame_data_takes_tls_clients_only(f)
        shape = "public_only" if t3 else ("public_read" if frame_store_is_socket_only(f) else "")
        why = ""
        if shape and not f.get("es_public_url"):
            why = "the frame has no public es address"
        elif shape and shape not in extras.auditor_slot_shapes(admin):
            why = f"the running host auditor does not list the {shape} slot shape"
        if t3 and why:
            log(f"sidecars: host auditor slot NOT written for {f['name']}: its databases take only TLS clients with a frame "
                f"certificate (§MTLSHOPS T3) and the host auditor holds none; its public-only slot is not written because "
                f"{why}; its own solo auditor does the exact check")
            done["auditor_slot"] = f"not written: the frame's databases take TLS clients with a frame certificate only, and {why}"
        else:
            if why:
                log(f"sidecars: host auditor slot for {f['name']} written without public_read because {why}: its store "
                    f"listens on a unix socket only, so its live read records a live_error while its DSNs keep the atomic check")
            _orig = (extras.AUDITOR_DIR,)
            extras.AUDITOR_DIR = os.path.dirname(resolve(m, a["compose"]))
            try:
                extras.auditor_slot(f["name"], f["frame_label"], f["ticker"], f"{f['name']}-event-store", f"{f['name']}-es-db",
                                    mode="sandbox" if f["env_label"] != "prod" else "prod",
                                    frames_file=resolve(m, a["frames_file"]) if a.get("frames_file") else "",
                                    admin_url=admin,
                                    auditor_container=a.get("container") or "auditor-agent", auditor_service=a.get("service") or "auditor-agent",
                                    public_url=(f.get("es_public_url") or "") if shape and not why else "",
                                    public_only=shape == "public_only" and not why,
                                    public_read=shape == "public_read" and not why)
            finally:
                extras.AUDITOR_DIR = _orig[0]
            done["auditor_slot"] = shape if shape and not why else True
    if want("sni"):
        done["sni"] = extras.sni_route(f["name"], int(f["fed_port"]))
    if want("bundle") and f.get("identity_net"):
        done["identity_net"] = extras.identity_nets_append(f["identity_net"], path=resolve(m, m.get("identity_nets", extras.IDENTITY_NETS_FILE)))
        done["bundle"] = register_bundle(m, f["name"], f["identity_net"], log=log)
    if want("apex") and (m.get("apex") or {}).get("vhosts"):
        done["apex_ws"] = extras.apex_ws_routes(f["name"], int(f["es_port"]), vhosts=tuple(m["apex"]["vhosts"]))
        done["fresh_network"] = extras.fresh_network_upsert(
            {"name": f["frame_label"], "slug": f["name"], "group": f["env_label"], "currency": f["ticker"],
             "currency_name": f.get("currency_name") or "", "role": f.get("role") or f"{f['env_label']} frame",
             "console": f["public_url"], "registry_url": f["public_url"], "es_url": f["es_public_url"],
             "status_url": f"{f['public_url']}/status", "ws_path": f"/ws/events-{f['name']}", "operators": f.get("operators") or []},
            compose_path=resolve(m, m["apex"].get("prod_compose", "docker-compose.production.yml")))
    d = m.get("directory") or {}
    if not want("directory"):
        return done
    if d.get("anchors_managed") and d.get("env"):
        envp = resolve(m, d["env"]); s = open(envp).read()
        mm = re.search(r"^DIRECTORY_ANCHORS=(.*)$", s, re.M)
        cur = [x.strip() for x in (mm.group(1) if mm else "").split(",") if x.strip()]
        if f["public_url"] not in cur:
            cur.append(f["public_url"]); line = "DIRECTORY_ANCHORS=" + ",".join(cur)
            s = (s[:mm.start()] + line + s[mm.end():]) if mm else s.rstrip("\n") + "\n" + line + "\n"
            open(envp, "w").write(s); done["directory_anchor"] = True
            log(f"sidecars: directory anchor {f['public_url']} added ({len(cur)} anchors; recreate {d.get('container', 'the directory')} to take it)")
    else:
        log("sidecars: directory anchors are not managed by this manifest (his D11: the index's home is his) — not touched")
    return done


def unwire(m: Dict[str, Any], f: Dict[str, Any], *, log=extras.log) -> Dict[str, Any]:
    """Remove exactly this frame's slot from each sidecar. Never a shared line, never another frame's."""
    done: Dict[str, Any] = {}
    pr = m.get("prometheus") or {}
    jobs = [f"{f['name']}-registry", f"{f['name']}-teg", f"{f['name']}-event-store"]
    for op in f.get("operators") or []:
        jobs += [f"{op}-registry", f"{op}-teg"]
    if pr.get("mode", "static-yml") == "static-yml":
        done["prometheus_jobs_removed"] = _prom_remove_jobs(resolve(m, pr["config"]), jobs)
    else:
        tp = os.path.join(resolve(m, pr["targets_dir"]), f"{f['name']}.json")
        done["prometheus_targets_removed"] = os.path.exists(tp) and (os.remove(tp) or True)
        if pr.get("config") and os.path.exists(resolve(m, pr["config"])):   # a frame wired before this host moved to file_sd
            done["prometheus_jobs_removed"] = _prom_remove_jobs(resolve(m, pr["config"]), jobs)
    own_net, op_nets = frame_networks(f)
    if pr.get("container"):
        for net in [own_net] + op_nets:
            subprocess.run(["docker", "network", "disconnect", net, pr["container"]], capture_output=True)
    ms = m.get("metrics_store") or {}
    if ms.get("container"):
        subprocess.run(["docker", "network", "disconnect", own_net, ms["container"]], capture_output=True)
    done["prometheus_reload_rc"] = _prom_reload(m)
    done["auditor_slot_removed"], done["auditor_net_removed"] = _auditor_remove_slot(m, f["name"], f"{f['name']}_network")
    s = m.get("sni") or {}
    r = subprocess.run(["bash", resolve(m, s["script"]), "--remove", f"{f['name']}.{DOMAIN}"], capture_output=True, text=True)
    done["sni_removed_rc"] = r.returncode
    done["apex_ws_removed"] = _apex_remove_ws(m, f["name"])
    done["fresh_network_removed"] = _fresh_network_remove(m, f["name"])
    if f.get("identity_net"):
        unregister_bundle(m, f["name"], f["identity_net"], log=log)
        # the identity-net opt-in line goes only when the net has no container left (a sibling frame may still use it)
        r = subprocess.run(["docker", "network", "inspect", f["identity_net"], "--format", "{{len .Containers}}"], capture_output=True, text=True)
        left = r.stdout.strip() if r.returncode == 0 else "gone"
        if left in ("0", "gone"):
            done["identity_net_line_removed"] = _remove_lines(resolve(m, m.get("identity_nets", extras.IDENTITY_NETS_FILE)),
                                                              lambda l: l.strip() == f["identity_net"])
        else:
            log(f"sidecars: identity net {f['identity_net']} still has {left} container(s) — its opt-in line stays")
    # the frame's own five vhosts and its docker networks (the old teardown removed the hetzner names only)
    removed_vh = 0
    for fname in extras.vhost_names(f["name"]).values():
        for d in (extras.NGINX_ENABLED, extras.NGINX_AVAIL):
            p = os.path.join(d, fname)
            if os.path.lexists(p):
                os.remove(p); removed_vh += 1
    # §SOVKIT T2/T5: the es vhost's proxy-marker snippet goes with the vhost that included it (a dangling include
    # would fail every later nginx -t on this host). Removed AFTER the vhosts and BEFORE the config test.
    done["es_proxy_snippet_removed"] = extras.remove_es_proxy_snippet(f["name"])
    if removed_vh:
        rc = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
        assert rc.returncode == 0, f"nginx -t failed after removing {f['name']}'s vhosts: {rc.stderr[-300:]}"
        subprocess.run(["systemctl", "reload", "nginx"], check=True)
    done["vhosts_removed"] = removed_vh
    for net in (frame_net_name(f["name"]), frame_net_name(f["name"]) + "_identity"):
        r = subprocess.run(["docker", "network", "rm", net], capture_output=True, text=True)
        done.setdefault("networks_removed", []).append((net, r.returncode == 0))
    log(f"sidecars: unwired {f['name']}: {done}")
    return done


def status(m: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"manifest": m.get("_path"), "problems": require(m)}
    b = m.get("bundles") or {}
    fl = resolve(m, b.get("frames_list", "")) if b.get("frames_list") else ""
    out["frames_under_refresh"] = [l.split(" ")[0] for l in open(fl) if l.strip() and not l.startswith("#")] if fl and os.path.exists(fl) else []
    # what reconcile would do: every network a sidecar must share, and whether it does (with the aliases)
    pr = m.get("prometheus") or {}; ms = m.get("metrics_store") or {}; a = m.get("auditor") or {}
    nets = [n for n in networks_for_targets(wired_targets(m)) if network_exists(n)]
    out["scraped_networks"] = nets
    if pr.get("container"):
        cur = net_membership(pr["container"])
        out["prometheus_joins"] = {n: join_plan(cur, n, list(pr.get("aliases") or [])) for n in nets}
        out["prometheus_joins"].update({n: join_plan(cur, n, []) for n in pr.get("extra_networks") or []})
    if ms.get("container"):
        cur = net_membership(ms["container"])
        out["metrics_store_joins"] = {n: join_plan(cur, n, list(ms.get("aliases") or [])) for n in nets if n.endswith("_network")}
    if a.get("container"):
        cur = net_membership(a["container"])
        out["auditor_joins"] = {n: join_plan(cur, n, []) for n in auditor_frame_networks(m) if network_exists(n)}
    out["metrics_env_lines"] = metrics_env_lines(m)
    return out


def frame_from_stack(sd: str, operators: Optional[List[str]] = None) -> Dict[str, Any]:
    """The wire()/unwire() facts of a frame this driver stood up, from its stack dir (meta + env + compose).
    Older metas (the 09-03 sandbox pair) lack ports/env_label/operator_slugs: the compose and the env fill in,
    and `operators` names the operators the meta does not."""
    _spec = _ilu.spec_from_file_location("standup_federate", os.path.join(_HERE, "standup_federate.py"))
    federate = _ilu.module_from_spec(_spec); _spec.loader.exec_module(federate)   # type: ignore[union-attr]
    f = federate.frame_facts(sd)
    meta = json.load(open(os.path.join(sd.rstrip("/"), "hetzner-demo-run.json")))
    comp = open(os.path.join(sd.rstrip("/"), "docker-compose.frame-test.yml")).read()
    mm = re.search(r"127\.0\.0\.1:(\d+):8443", comp)
    f["fed_port"] = (meta.get("ports") or {}).get("nginx_fed") or (int(mm.group(1)) if mm else 0)
    f["role"] = meta.get("role") or f"{f['env_label']} frame"
    f["operators"] = [x for x in (operators if operators is not None else (meta.get("operator_slugs") or [])) if x]
    return f


if __name__ == "__main__":
    import sys
    m = load(sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--manifest" else None)
    cmd = [x for x in sys.argv[1:] if not x.startswith("--manifest") and x != m.get("_path")]
    if not cmd or cmd[0] == "status":
        print(json.dumps(status(m), indent=1))
    elif cmd[0] == "require":
        p = require(m, need_apex="--apex" in cmd)
        print("\n".join(p) if p else "sidecars: everything --wire-prod needs is here"); sys.exit(1 if p else 0)
    elif cmd[0] == "unwire-net" and len(cmd) >= 2:
        net = cmd[1]
        r = subprocess.run(["docker", "network", "inspect", net, "--format", "{{len .Containers}}"], capture_output=True, text=True)
        left = r.stdout.strip() if r.returncode == 0 else "gone"
        if left in ("0", "gone"):
            k = _remove_lines(resolve(m, m.get("identity_nets", extras.IDENTITY_NETS_FILE)), lambda l: l.strip() == net)
            print(f"sidecars: identity net {net} is empty ({left}) — opt-in line removed: {k}")
        else:
            print(f"sidecars: identity net {net} still has {left} container(s) — its opt-in line stays")
    elif cmd[0] == "unwire" and len(cmd) >= 2:
        sd = cmd[1]
        meta = json.load(open(os.path.join(sd, "hetzner-demo-run.json")))
        env = {}
        for line in open(os.path.join(sd, ".env.frame-test")):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"')
        f = {"name": meta["name"], "identity_net": env.get("FT_REG_IDENTITY_NETWORK") or env.get("IDENTITY_NETWORK") or "",
             "operators": [x for x in (meta.get("operator_slugs") or []) if x]}
        print(json.dumps(unwire(m, f), indent=1, default=str))
    elif cmd[0] == "wire" and len(cmd) >= 2:
        # `wire <stack dir> [--only prometheus,auditor,...] [--operators a,b]`: a frame that predates a sidecar piece
        only = None; ops = None
        for i, x in enumerate(cmd):
            if x == "--only" and i + 1 < len(cmd):
                only = {y.strip() for y in cmd[i + 1].split(",") if y.strip()}
            if x == "--operators" and i + 1 < len(cmd):
                ops = [y.strip() for y in cmd[i + 1].split(",") if y.strip()]
        f = frame_from_stack(cmd[1], operators=ops)
        prepare_targets_dir(m)
        problems = require(m, need_apex=(only is None or "apex" in only) and bool((m.get("apex") or {}).get("vhosts")))
        if problems:
            print("\n".join(problems)); sys.exit(1)
        print(json.dumps(wire(m, f, only=only), indent=1, default=str))
    elif cmd[0] == "reconcile":
        print(json.dumps(reconcile(m), indent=1, default=str))
    else:
        print("usage: sidecars.py [--manifest PATH] status | require [--apex] | wire <stack dir> [--only a,b] [--operators x,y] | "
              "reconcile | unwire <stack dir> | unwire-net <net>"); sys.exit(1)
