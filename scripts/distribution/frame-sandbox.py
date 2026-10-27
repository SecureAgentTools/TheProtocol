#!/usr/bin/env python3
"""frame-sandbox: a SANDBOX beside a frame this host runs, stood up from this export, so a change can be tested before it
is suggested (§TESTBED 2026-09-19).

    ./frame-sandbox.py up     --for myframe [--frames 1|2] [--operators] [--stack-root /opt/theprotocol/stack]
    ./frame-sandbox.py down   --for myframe
    ./frame-sandbox.py status --for myframe [--json]

A sandbox is a frame of its own (frame-up --sandbox-of): posture sandbox, its console a site on the frame's edge at
sandbox.<public name> (sandbox-b.<public name> for the second), its registry running the MCP and API testers against
ITSELF (the docker socket, the fixture accounts), nothing shared with the frame it serves but the host, the edge and
the frame runner. Every write a test makes lands in the sandbox. Everything is stood up through the lanes a stranger
uses, so the tests mean something:

  plan        names, public names (the frame's `*.<public name>` record covers them), free lanes, the host's headroom
  frame_a     frame-up --sandbox-of (the export's own standup)
  frame_b     the second sandbox, with --frames 2
  federate    frame-federate.py from A to B, B's admin approving through B's own admin API (the invitation rail)
  operator_a  with --operators: a cloud operator on A, the way any operator joins a frame: a developer account, the
  operator_b  application, the admin's approval, the activation, the provisioning (the frame runner does the host work)
  fixtures    the federation suite's fixtures on A (both frames, both operators) and A's registry recreated
  ready       each sandbox answers its seeded tester login; the consoles and testers are listed

With 2 frames and operators the federation suite runs too (it needs exactly that: two federated frames and one operator
each, measured); one frame is the lifecycle sweep. A step that already stands is skipped, so `up` again after a failure
resumes. `down` tears the operators down through their frames' own admin API, then frame-down removes each sandbox.
Progress lines (--progress-file) are the driver's shape: {ts, step, event: start|end|skip|fail|note|live, sentence};
the frame runner serves them to the frame's MCP tester view. Secrets are read from their files and never printed.
"""
import argparse
import importlib.util
import json
import os
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


frame_names = _load("frame_names", os.path.join(EXPORT_ROOT, "scripts", "hetzner_demo", "frame_names.py"))
frame_ports = _load("frame_ports", os.path.join(EXPORT_ROOT, "scripts", "hetzner_demo", "frame_ports.py"))

STEPS_UP = ("plan", "frame_a", "frame_b", "federate", "operator_a", "operator_b", "fixtures", "ready")
STEPS_DOWN = ("operators", "frame_b", "frame_a", "firewall")
FIXTURE_KEYS = ("SANDBOX_ADMIN_PASSWORD", "SANDBOX_DEVELOPER_PASSWORD", "SANDBOX_TUTORIAL_PASSWORD",
                "SANDBOX_NON_ADMIN_PASSWORD", "SANDBOX_RESET_SECRET", "API_TEST_PROXY_INTERNAL_KEY")


class StepFailed(Exception):
    pass


class Progress:
    """One JSON object per line, appended; the standup driver's shape plus `note` (a sentence inside a running step)."""

    def __init__(self, path):
        self.path = os.path.abspath(path) if path else None
        self.current = None

    def emit(self, step, event, sentence="", **extra):
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "step": step, "event": event}
        if sentence:
            rec["sentence"] = str(sentence)[:600]
        rec.update(extra)
        print(f"[frame-sandbox {rec['ts'][11:19]}Z] {step} {event}{': ' + rec['sentence'] if sentence else ''}", flush=True)
        if self.path:
            with open(self.path, "a") as f:
                f.write(json.dumps(rec) + "\n")

    def start(self, step):
        self.current = step
        self.emit(step, "start")

    def note(self, sentence):
        self.emit(self.current or "run", "note", sentence)

    def end(self, sentence=""):
        if self.current:
            self.emit(self.current, "end", sentence)
        self.current = None

    def skip(self, step, why):
        self.emit(step, "skip", why)

    def fail(self, sentence):
        self.emit(self.current or "run", "fail", sentence, verdict="refused")
        self.current = None


# ── small helpers ───────────────────────────────────────────────────────────────────────────────────────────────────
def read_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def http(method, url, body=None, headers=None, form=False, timeout=90):
    """(status, parsed body). TLS is not verified: every call here goes to a loopback door of this host."""
    h = dict(headers or {})
    data = None
    if body is not None:
        data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=timeout,
                                    context=ctx) as r:
            raw = r.read().decode() or "{}"
            return r.status, (json.loads(raw) if raw.strip()[:1] in ("{", "[") else raw[:400])
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace") or "{}"
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw[:400]
    except Exception as e:  # noqa: BLE001 — the status 0 and the class name are the answer
        return 0, {"error": f"{type(e).__name__}: {e}"[:300]}


def detail(body):
    if isinstance(body, dict):
        for k in ("detail", "message", "error", "refused"):
            if body.get(k):
                return str(body[k])[:300]
    return str(body)[:300]


def newest_record(stack_root, name):
    """The newest frame-up.json of a frame (with its stack_dir), or None."""
    for d in reversed(frame_names.stack_dirs(stack_root, name, need_file="frame-up.json")):
        rec = read_json(os.path.join(stack_root, d, "frame-up.json"))
        if isinstance(rec, dict):
            rec["stack_dir"] = os.path.join(stack_root, d)
            return rec
    return None


def container_running(name):
    r = subprocess.run(["docker", "inspect", name, "--format", "{{.State.Running}}"], capture_output=True, text=True, timeout=30)
    return r.returncode == 0 and r.stdout.strip() == "true"


def docker_socket_gid():
    try:
        return os.stat("/var/run/docker.sock").st_gid
    except OSError:
        return None


class Frame:
    """What this script needs of one frame on this host: its record, its loopback door, its admin's login."""

    def __init__(self, stack_root, name):
        self.name = name
        self.rec = newest_record(stack_root, name) or {}
        self.run_meta = read_json(os.path.join(self.rec.get("stack_dir", ""), "hetzner-demo-run.json")) or {}

    @property
    def exists(self):
        return bool(self.rec)

    @property
    def base(self):
        port = (self.rec.get("ports") or self.run_meta.get("ports") or {}).get("registry")
        return f"http://127.0.0.1:{port}" if port else ""

    def admin(self):
        sec = read_json(os.path.join(self.rec.get("secrets_dir", ""), f".{self.name}_frame_admin.secret.json")) or {}
        return sec.get("admin_email"), sec.get("admin_password")

    def token(self):
        email, pw = self.admin()
        if not email or not pw:
            raise StepFailed(f"{self.name}: its admin secret file has no login")
        st, body = http("POST", self.base + "/api/v1/auth/login", {"username": email, "password": pw}, form=True)
        if st != 200 or not isinstance(body, dict) or not body.get("access_token"):
            raise StepFailed(f"{self.name}: the admin login answered HTTP {st} ({detail(body)})")
        return {"Authorization": f"Bearer {body['access_token']}"}

    def healthy(self):
        return bool(self.base) and http("GET", self.base + "/health", timeout=15)[0] == 200


# ── the host's firewall ─────────────────────────────────────────────────────────────────────────────────────────────
# A sandbox pair and its operators dial each other through their PUBLIC lanes (a federation lane, a bundle endpoint, a
# ledger gateway: the addresses their cards publish), so a container on this host connects to this host's public address.
# Measured on the proof host 2026-09-19: with ufw active every such connection timed out until the ports were allowed
# (Northwind needed the same rule by hand). Where ufw is active, frame-sandbox opens exactly the ports it allocated, each
# rule commented with the sandbox's name, recorded, and removed at `down` (and by frame-down from the frame's record).
def ufw_active():
    if not shutil.which("ufw"):
        return False
    r = subprocess.run(["ufw", "status"], capture_output=True, text=True, timeout=30)
    return r.returncode == 0 and "Status: active" in (r.stdout or "")


def port_specs(ports):
    """Contiguous ranges of ports as ufw specs: [28553, 28554, 28555] -> ['28553:28555/tcp']."""
    out, run_start, prev = [], None, None
    for p in sorted(set(int(x) for x in ports)):
        if run_start is None:
            run_start = prev = p
        elif p == prev + 1:
            prev = p
        else:
            out.append(f"{run_start}:{prev}/tcp" if prev > run_start else f"{run_start}/tcp")
            run_start = prev = p
    if run_start is not None:
        out.append(f"{run_start}:{prev}/tcp" if prev > run_start else f"{run_start}/tcp")
    return out


def firewall_file(stack_root, parent):
    return os.path.join(stack_root, f".frame-sandbox-{parent}.firewall.json")


def open_ports(stack_root, parent, owner, ports, progress):
    """Allow `ports` in ufw for `owner` (a sandbox or an operator), recorded in the set's firewall file; [] without ufw."""
    if not ufw_active():
        return []
    path = firewall_file(stack_root, parent)
    doc = read_json(path) or {}
    opened = []
    for spec in port_specs(ports):
        r = subprocess.run(["ufw", "allow", spec, "comment", f"frame-sandbox {owner} (removed with it)"],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            opened.append(spec)
        else:
            raise StepFailed(f"ufw refused to allow {spec} for {owner}: {(r.stderr or r.stdout).strip()[-200:]}")
    doc[owner] = sorted(set(doc.get(owner, [])) | set(opened))
    with open(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
        json.dump(doc, f, indent=1)
    if opened:
        progress.note(f"the host's firewall (ufw) allows {', '.join(opened)} for {owner}")
    return opened


def close_ports(stack_root, parent, progress):
    path = firewall_file(stack_root, parent)
    doc = read_json(path) or {}
    if doc and shutil.which("ufw"):
        for owner, specs in doc.items():
            for spec in specs:
                subprocess.run(["ufw", "delete", "allow", spec], capture_output=True, text=True, timeout=60)
            progress.note(f"the firewall rules for {owner} are removed ({', '.join(specs)})")
    try:
        os.remove(path)
    except OSError:
        pass


def lanes_reachable(from_container, host, ports):
    """Which of `ports` on `host` a container can open a TCP connection to (the path peers and operators take)."""
    code = ("import socket,sys\nbad=[]\nfor p in sys.argv[2:]:\n s=socket.socket(); s.settimeout(5)\n"
            " try: s.connect((sys.argv[1], int(p)))\n except Exception: bad.append(p)\n finally: s.close()\nprint(' '.join(bad))")
    r = subprocess.run(["docker", "exec", from_container, "python3", "-c", code, host, *[str(p) for p in ports]],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None
    return [int(x) for x in (r.stdout or "").split()]


# ── the plan ────────────────────────────────────────────────────────────────────────────────────────────────────────
def sandbox_names(parent, frames):
    pub = parent["public_name"]
    out = [{"key": "a", "name": f"{parent['name']}sbx", "public_name": f"sandbox.{pub}", "ticker": "SBX",
            "label": f"{label_of(parent)} Sandbox", "operator": f"{parent['name']}sbxop"}]
    if frames == 2:
        out.append({"key": "b", "name": f"{parent['name']}sbxb", "public_name": f"sandbox-b.{pub}", "ticker": "SBB",
                    "label": f"{label_of(parent)} Sandbox B", "operator": f"{parent['name']}sbxbop"})
    return out


def label_of(rec):
    return rec["name"].replace("-", " ").title()


def free_lanes(start, taken, count=3, step=10, tries=200):
    """`count` consecutive ports from the first base (start, start+step, ...) whose ports are all free."""
    base = start
    for _ in range(tries):
        want = set(range(base, base + count))
        if not want & taken:
            return list(range(base, base + count))
        base += step
    raise StepFailed(f"no {count} consecutive free ports from {start}")


def resolves_here(host):
    """The public resolver's A answers for a name, and whether one of them is this host (the doctor's own helpers)."""
    doctor = _load("frame_doctor", os.path.join(HERE, "frame-doctor.py"))
    answers = doctor.resolve_public(host)
    return answers, bool(set(answers) & set(doctor.host_ipv4s()))


def lanes_of(rec):
    """(federation, bundle, ledger) ports a standing sandbox recorded, or None."""
    def port(url):
        m = re.search(r":(\d+)/?$", url or "")
        return int(m.group(1)) if m else None
    got = (port(rec.get("federation_lane")), port(rec.get("bundle_endpoint")), port(rec.get("ledger_gateway")))
    return got if all(got) else None


def partial_lanes(stack_root, name):
    """(federation, bundle, ledger) ports of a sandbox whose standup stopped before frame-up wrote its record, or None:
    the driver's run meta names them (ports.nginx_fed, ports.spire_bundle, the ledger's port in es_public_url). A resume
    must reuse them, because the rendered stack publishes those ports: fresh ones would be recorded while the old ones
    stay published (measured 2026-09-19 on the dev4 sandbox: frame-up.json said 28563-28565, the containers published
    28553-28555, and the firewall held both while the record named one)."""
    for d in reversed(frame_names.stack_dirs(stack_root, name, need_file="hetzner-demo-run.json")):
        meta = read_json(os.path.join(stack_root, d, "hetzner-demo-run.json")) or {}
        ports = meta.get("ports") or {}
        m = re.search(r":(\d+)/?$", meta.get("es_public_url") or "")
        got = (ports.get("nginx_fed"), ports.get("spire_bundle"), int(m.group(1)) if m else None)
        if all(got):
            return tuple(int(x) for x in got)
    return None


def fixture_secrets_file(stack_root, first):
    """The fixture secrets a sandbox SET shares (one pair logs into both frames as the same sandbox admin): in the first
    sandbox's secrets directory, created once, mode 600; frame-down of that sandbox removes it."""
    d = os.path.join(stack_root, f"{first}-secrets")
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    path = os.path.join(d, ".sandbox_set_fixtures.secret.json")
    if not os.path.isfile(path):
        pw = lambda: secrets.token_urlsafe(18) + "-Aa1"   # noqa: E731
        doc = {"SANDBOX_ADMIN_PASSWORD": pw(), "SANDBOX_DEVELOPER_PASSWORD": pw(), "SANDBOX_TUTORIAL_PASSWORD": pw(),
               "SANDBOX_NON_ADMIN_PASSWORD": pw(), "SANDBOX_RESET_SECRET": secrets.token_hex(32),
               "API_TEST_PROXY_INTERNAL_KEY": secrets.token_hex(32)}
        with open(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
            json.dump(doc, f, indent=1)
    os.chmod(path, 0o600)
    return path


# ── the steps ───────────────────────────────────────────────────────────────────────────────────────────────────────
def run_frame_up(a, parent, sb, lanes, fixtures, progress):
    """frame-up --sandbox-of, streaming its output into this job's log and its driver's step names into notes."""
    prefix, version = (parent.get("images") or "theprotocol/*:dev").split("/*:", 1) if "/*:" in (parent.get("images") or "") else ("theprotocol", "dev")
    argv = [sys.executable, "-u", os.path.join(HERE, "frame-up.py"), "--name", sb["name"], "--sandbox-of", parent["name"],
            "--public-name", sb["public_name"], "--ticker", sb["ticker"], "--currency-name", "Sandbox Unit",
            "--admin-email", f"admin@{sb['public_name']}", "--frame-label", sb["label"],
            "--description", f"{sb['label']}: the test sandbox of {label_of(parent)}; every write here is a test's.",
            "--federation-port", str(lanes[0]), "--bundle-port", str(lanes[1]), "--ledger-port", str(lanes[2]),
            "--stack-root", a.stack_root, "--images-prefix", prefix, "--version", version,
            "--tester-fixture-secrets", fixtures, "--max-load", str(a.max_load)]
    env = {k: v for k, v in os.environ.items() if not k.startswith("FRAME_MAIL_")}   # a sandbox mails nobody
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    seen = {"step": None}
    stop = threading.Event()

    def follow():   # the driver's own step names, from the progress file it writes beside the new stack
        while not stop.wait(5):
            dirs = frame_names.stack_dirs(a.stack_root, sb["name"], need_file=None)
            if not dirs:
                continue
            path = os.path.join(a.stack_root, dirs[-1], "standup-progress.jsonl")
            try:
                lines = open(path).read().splitlines()
            except OSError:
                continue
            for line in reversed(lines):
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("event") == "start" and e.get("step") and e["step"] != seen["step"]:
                    seen["step"] = e["step"]
                    progress.note(f"{sb['name']}: the standup is at '{e['step']}'")
                break
    t = threading.Thread(target=follow, daemon=True)
    t.start()
    tail = []
    for line in proc.stdout:
        sys.stdout.write(line)
        tail = (tail + [line.rstrip()])[-6:]
    rc = proc.wait()
    stop.set()
    if rc != 0:
        why = next((l for l in reversed(tail) if l.strip()), "no output")
        raise StepFailed(f"frame-up for {sb['name']} exited {rc}: {why[-300:]}")


def step_frame(a, parent, sb, fixtures, taken, progress):
    have = Frame(a.stack_root, sb["name"])
    if have.exists and have.rec.get("edge_health") == 200 and have.healthy():
        progress.skip(f"frame_{sb['key']}", f"{sb['name']} stands ({have.rec.get('console')})")
        return have
    progress.start(f"frame_{sb['key']}")
    answers, here = resolves_here(sb["public_name"])
    if not here:
        raise StepFailed(f"{sb['public_name']} resolves to {', '.join(answers) or 'nothing'}, not to this host: the frame's "
                         f"`*.{parent['public_name']}` record must point here (a sandbox is named under it)")
    stale = (lanes_of(have.rec) if have.exists else None) or partial_lanes(a.stack_root, sb["name"])
    fed_start = int((re.search(r":(\d+)", parent.get("federation_lane") or "") or [None, 8443])[1]) + 10
    lanes = stale or free_lanes(fed_start, taken)
    taken.update(lanes)
    progress.note(f"{sb['name']} at {sb['public_name']}, lanes {lanes[0]}/{lanes[1]}/{lanes[2]} (federation, bundle, ledger)")
    opened = open_ports(a.stack_root, parent["name"], sb["name"], lanes, progress)
    run_frame_up(a, parent, sb, lanes, fixtures, progress)
    have = Frame(a.stack_root, sb["name"])
    if not have.exists or not have.healthy():
        raise StepFailed(f"{sb['name']} stood up but its registry does not answer /health on {have.base or 'no door'}")
    if opened:   # frame-down removes what the frame's own record names
        fu_path = os.path.join(have.rec["stack_dir"], "frame-up.json")
        fu = read_json(fu_path) or {}
        fu["firewall"] = {"ufw": opened}
        with open(fu_path, "w") as f:
            json.dump(fu, f, indent=1)
    bad = lanes_reachable(f"{sb['name']}-registry", sb["public_name"], lanes)
    if bad:
        raise StepFailed(f"{sb['name']}'s lanes {', '.join(map(str, bad))} do not answer from a container on this host "
                         f"(through {sb['public_name']}): this host's firewall drops that traffic; allow those ports")
    progress.end(f"{sb['name']} is up: {have.rec.get('console')}")
    return have


def invitations(fr, headers):
    st, body = http("GET", fr.base + "/api/v1/admin/federation/frame-invitations?status=all&limit=200", headers=headers)
    if st != 200:
        raise StepFailed(f"{fr.name}: the invitation list answered HTTP {st} ({detail(body)})")
    items = body if isinstance(body, list) else (body.get("items") or body.get("invitations") or []) if isinstance(body, dict) else []
    return [i for i in items if isinstance(i, dict)]


def registry_name(fr):
    """The name a frame publishes on its own signed card (identity.registry_name), which is what its peers list it by."""
    st, card = http("GET", fr.base + "/.well-known/registry-card.json", timeout=30)
    return str(((card or {}).get("identity") or {}).get("registry_name") or "") if st == 200 and isinstance(card, dict) else ""


def peer_statuses(fr):
    """{registry_name: peer_status} of a frame's public peer listing (the rows carry registry_name, peer_status,
    federation_status and public_url, measured on larchsbx; a fresh peer's public_url can still be empty)."""
    st, body = http("GET", fr.base + "/api/v1/federation/registries")
    rows = body if isinstance(body, list) else (body.get("registries") or body.get("items") or []) if isinstance(body, dict) else []
    return {str(r.get("registry_name") or ""): str(r.get("peer_status") or "").upper() for r in rows if isinstance(r, dict)}


def federated(a_fr, b_fr):
    """True when each frame lists the other, by the name the other publishes, as an ACTIVE peer (the rail's end state)."""
    na, nb = registry_name(a_fr), registry_name(b_fr)
    return bool(na and nb) and peer_statuses(a_fr).get(nb) == "ACTIVE" and peer_statuses(b_fr).get(na) == "ACTIVE"


def step_federate(a, a_fr, b_fr, parent, progress):
    if federated(a_fr, b_fr):
        progress.skip("federate", f"{a_fr.name} and {b_fr.name} hold each other as active peers")
        return
    progress.start("federate")
    port = parent.get("public_https_port") or (parent.get("edge") or {}).get("public_https_port") or (parent.get("edge") or {}).get("https_port") or 443
    peer_console = f"https://{b_fr.rec['public_name']}" + ("" if int(port) == 443 else f":{port}")
    argv = [sys.executable, "-u", os.path.join(HERE, "frame-federate.py"), "--stack-dir", a_fr.rec["stack_dir"],
            "--with", peer_console, "--admin-secret-file", os.path.join(a_fr.rec["secrets_dir"], f".{a_fr.name}_frame_admin.secret.json"),
            "--description", f"{a_fr.name} and {b_fr.name}: the sandbox pair of {parent['name']}", "--timeout-min", str(a.federate_timeout_min)]
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail, approved = [], {"id": None}
    stop = threading.Event()

    def approve():   # B's admin approves the invitation from A through B's own admin API (the rail's one human step)
        hb = None
        while not stop.wait(5):
            try:
                hb = hb or b_fr.token()
                for inv in invitations(b_fr, hb):
                    if str(inv.get("initiator_trust_domain") or "").lower() == a_fr.rec["public_name"].lower() and \
                            str(inv.get("status") or "").lower() == "pending" and inv.get("id") != approved["id"]:
                        st, body = http("POST", b_fr.base + f"/api/v1/admin/federation/frame-invitations/{inv['id']}/approve",
                                        {"notes": "frame-sandbox: the sandbox pair"}, headers=hb, timeout=300)
                        approved["id"] = inv["id"]
                        progress.note(f"{b_fr.name}'s admin approved {a_fr.name}'s invitation: HTTP {st}"
                                      + ("" if st == 200 else f" ({detail(body)})"))
            except StepFailed as exc:
                progress.note(f"approving on {b_fr.name}: {exc}")
                hb = None
    t = threading.Thread(target=approve, daemon=True)
    t.start()
    for line in proc.stdout:
        sys.stdout.write(line)
        tail = (tail + [line.rstrip()])[-6:]
    rc = proc.wait()
    stop.set()
    if rc != 0:
        why = next((l for l in reversed(tail) if l.strip()), "no output")
        raise StepFailed(f"frame-federate exited {rc} ({ {2: 'refused', 3: 'a step failed', 4: 'the approval did not arrive in time'}.get(rc, 'failed') }): {why[-300:]}")
    for _ in range(24):
        if federated(a_fr, b_fr):
            break
        time.sleep(5)
    else:
        raise StepFailed(f"frame-federate finished, but {a_fr.name} and {b_fr.name} do not both list the other as an active peer")
    progress.end(f"{a_fr.name} and {b_fr.name} are federated")


def operator_rows(fr, headers):
    st, body = http("GET", fr.base + "/api/v1/admin/cloud-operators", headers=headers)
    items = body if isinstance(body, list) else (body.get("items") or body.get("operators") or []) if isinstance(body, dict) else []
    return [r for r in items if isinstance(r, dict)]


def published_public_ports(prefix):
    """Host ports the containers named <prefix>* publish on every address (0.0.0.0 / [::]): the ones a peer dials."""
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"], capture_output=True, text=True, timeout=60).stdout
    ports = set()
    for line in (out or "").splitlines():
        name, _, spec = line.partition("\t")
        if name.startswith(prefix):
            ports |= {int(m) for m in re.findall(r"(?:0\.0\.0\.0|\[::\]):(\d+)->", spec)}
    return sorted(ports)


def operator_up(slug):
    names = [l.split("\t") for l in subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
                                                   capture_output=True, text=True, timeout=60).stdout.splitlines()
             if l.startswith(f"cloud-op-{slug}-")]
    return len(names) >= 3 and all(s.startswith("Up") for _, s in names), len(names)


def operator_dev_password(stack_root, first, slug):
    """The password of an operator's developer account on its sandbox, kept in the set's secrets (mode 600) so a resumed
    `up` logs in as the account an earlier attempt registered, rather than guessing a reset route."""
    path = os.path.join(stack_root, f"{first}-secrets", ".sandbox_set_operators.secret.json")
    doc = read_json(path) or {}
    if not doc.get(slug):
        doc[slug] = "Op-" + secrets.token_urlsafe(18) + "-9a"
        with open(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
            json.dump(doc, f, indent=1)
    os.chmod(path, 0o600)
    return doc[slug]


def operator_code_file(stack_root, first):
    return os.path.join(stack_root, f"{first}-secrets", ".sandbox_set_operator_codes.secret.json")


def keep_activation_code(stack_root, first, app_id, code):
    """An approve hands the one-time activation code over ONCE. It is written to the set's secrets (mode 600) BEFORE the
    activation spends it, so a try that dies between the two can still activate on the next one: a secret is kept
    before the change that depends on it, never after (the §BATCH3 rotation lesson)."""
    path = operator_code_file(stack_root, first)
    doc = read_json(path) or {}
    doc[app_id] = code
    with open(os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600), "w") as f:
        json.dump(doc, f, indent=1)
    os.chmod(path, 0o600)


def kept_activation_code(stack_root, first, app_id):
    return (read_json(operator_code_file(stack_root, first)) or {}).get(app_id)


def live_applications(body, slug):
    """The applications an earlier try left for this operator's name, newest first; rejected and revoked ones are over
    and never resumed."""
    apps = body.get("applications") if isinstance(body, dict) else None
    apps = [x for x in (apps or []) if isinstance(x, dict) and x.get("name") == slug and x.get("id")
            and str(x.get("status") or "").lower() not in ("rejected", "revoked")]
    return sorted(apps, key=lambda x: str(x.get("created_at") or ""), reverse=True)


def application_stage(app):
    """Where an application stands, in the order the operator lane walks it: "pending" (to approve), "approved" (to
    activate with the code the approve gave), "activated" (to provision), "provisioned" (its stack was asked for)."""
    if app.get("cloud_hosted") and not app.get("cloud_torn_down_at"):
        return "provisioned"
    if app.get("activated_at"):
        return "activated"
    return "pending" if str(app.get("status") or "").lower() == "pending" else "approved"


def step_operator(a, fr, sb, first, parent_name, progress):
    step = f"operator_{sb['key']}"
    slug = sb["operator"]
    ok, _n = operator_up(slug)
    if ok:
        progress.skip(step, f"{slug} runs on {fr.name}")
        return
    progress.start(step)
    A = fr.token()
    email = f"{slug}@{fr.rec['public_name']}"
    pw = operator_dev_password(a.stack_root, first, slug)
    st, reg = http("POST", fr.base + "/api/v1/auth/register", {"name": f"{slug} operator", "email": email, "password": pw,
                                                               "tos_accepted": True}, timeout=120)
    if st not in (200, 201) and "already" not in detail(reg).lower():
        raise StepFailed(f"{fr.name}: registering the operator's developer answered HTTP {st} ({detail(reg)})")
    st, lst = http("GET", fr.base + f"/api/v1/admin/developers?search={urllib.parse.quote(email)}&limit=5", headers=A)
    items = (lst.get("items") or lst.get("developers") or []) if isinstance(lst, dict) else (lst if isinstance(lst, list) else [])
    dev = next((d for d in items if isinstance(d, dict) and d.get("email") == email), None)
    if not dev:
        raise StepFailed(f"{fr.name}: the operator's developer {email} is not listed after registering")
    http("POST", fr.base + f"/api/v1/admin/developers/{dev['id']}/force-email-verify", {}, headers=A)
    st, lg = http("POST", fr.base + "/api/v1/auth/login", {"username": email, "password": pw}, form=True)
    if st != 200 or not isinstance(lg, dict) or not lg.get("access_token"):
        raise StepFailed(f"{fr.name}: the operator's developer could not log in (HTTP {st}, {detail(lg)})")
    D = {"Authorization": f"Bearer {lg['access_token']}"}
    progress.note(f"{slug}: a developer account on {fr.name}, verified by its admin")
    # A resumed `up` continues the application an earlier try left, from the stage it reached: a second application
    # for the same name would be refused (a pending one exists) or would leave the first one's stack half-made.
    st, body = http("GET", fr.base + "/api/v1/admin/operator-applications", headers=A)
    if st != 200:
        raise StepFailed(f"{fr.name}: listing its operator applications answered HTTP {st} ({detail(body)})")
    earlier = live_applications(body, slug)
    if earlier:
        app = earlier[0]
        progress.note(f"{slug}: application {app['id']} from an earlier try is {application_stage(app)}; continuing from there")
    else:
        st, app = http("POST", fr.base + "/api/v1/operator-applications",
                       {"name": slug, "email": email, "organization": f"{sb['label']} operator", "deployment": "cloud",
                        "experience": "advanced", "use_case": f"the cloud operator of {fr.name}, for the federation suite"})
        if st not in (200, 201) or not isinstance(app, dict) or not app.get("id"):
            raise StepFailed(f"{fr.name}: the operator application answered HTTP {st} ({detail(app)})")
    app_id = app["id"]
    stage = application_stage(app)
    if stage == "pending":
        st, ans = http("POST", fr.base + f"/api/v1/admin/operator-applications/{app_id}/approve",
                       {"notes": "frame-sandbox: the sandbox's own operator"}, headers=A)
        code = ans.get("activation_code") if isinstance(ans, dict) else None
        if st != 200 or not code:
            raise StepFailed(f"{fr.name}: approving the application answered HTTP {st} ({detail(ans)})")
        keep_activation_code(a.stack_root, first, app_id, code)
        progress.note(f"{slug}: application {app_id} approved; activating (the bundle is built by the frame runner)")
        stage = "approved"
    if stage == "approved":
        code = kept_activation_code(a.stack_root, first, app_id)
        if not code:
            raise StepFailed(f"{fr.name}: application {app_id} for {slug} was approved by an earlier try and never "
                             f"activated, and its one-time activation code was not kept. Tear the sandboxes down and "
                             f"provision them again")
        st, act = http("POST", fr.base + "/api/v1/operators/activate", {"activation_code": code}, headers=D, timeout=1200)
        if st != 200:
            raise StepFailed(f"{fr.name}: the activation answered HTTP {st} ({detail(act)})")
        if isinstance(act, dict) and not act.get("bundle_path"):
            # activation keeps going when its bundle fails (by design); the provisioning below rebuilds it through the
            # frame runner and answers with the runner's own reason if that fails too
            progress.note(f"{slug}: activated, but the activation built no bundle; the provisioning rebuilds it")
        else:
            progress.note(f"{slug}: activated; provisioning its stack (the frame runner's operator job)")
        stage = "activated"
    if stage == "activated":
        st, prov = http("POST", fr.base + f"/api/v1/admin/cloud-operators/{app_id}/provision?"
                        + urllib.parse.urlencode({"location_label": sb["label"]}), {}, headers=A, timeout=2700)
        if st != 200:
            raise StepFailed(f"{fr.name}: provisioning {slug} answered HTTP {st} ({detail(prov)})")
    else:
        progress.note(f"{slug}: provisioned by an earlier try; waiting for its containers")
    deadline = time.time() + a.operator_timeout_min * 60
    while time.time() < deadline:
        ok, n = operator_up(slug)
        if ok:
            break
        time.sleep(10)
    else:
        raise StepFailed(f"{slug}: provisioned, but its containers are not all up after {a.operator_timeout_min} min ({n} found)")
    ports = published_public_ports(f"cloud-op-{slug}-")
    if ports:
        open_ports(a.stack_root, parent_name, slug, ports, progress)
    progress.end(f"{slug} runs on {fr.name} (cloud-op-{slug}-*)")


def runner_state_dir(parent):
    inst = ((parent.get("runner") or {}).get("instance") or "")
    return f"/var/lib/theprotocol/frame-runner-{inst}" if inst else "/var/lib/theprotocol/frame-runner"


def operator_login(parent, slug):
    """(email, password) of an operator's first-boot admin: the runner's provision job result (root-only) for the password,
    the operator's own env file for the address."""
    email = None
    env = os.path.join(os.path.dirname(parent["stack_dir"]), f"cloud-op-{slug}", ".env.operator")
    try:
        for line in open(env):
            if line.startswith(("FIRST_ADMIN_EMAIL=", "ADMIN_EMAIL=")):
                email = line.split("=", 1)[1].strip().strip('"')
                break
    except OSError:
        pass
    best = None
    jobs = os.path.join(runner_state_dir(parent), "jobs")
    for jid in (os.listdir(jobs) if os.path.isdir(jobs) else []):
        job = read_json(os.path.join(jobs, jid, "job.json")) or {}
        spec = read_json(os.path.join(jobs, jid, "spec.json")) or {}
        if job.get("op") != "operator_provision" or spec.get("safe_name") != slug:
            continue
        res = read_json(os.path.join(jobs, jid, "result.json")) or job.get("result") or {}
        pw = (res or {}).get("admin_password")
        if pw and (best is None or job.get("created", "") > best[0]):
            best = (job.get("created", ""), pw)
    return email or f"admin@cloud-op-{slug}.dev", (best[1] if best else None)


def upsert_env(path, pairs):
    text = open(path).read()
    for k, v in pairs:
        line = f"{k}={v}"
        if re.search(rf"^{re.escape(k)}=.*$", text, re.M):
            text = re.sub(rf"^{re.escape(k)}=.*$", lambda _m: line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + "\n" + line + "\n"
    with open(path, "w") as f:
        f.write(text)


def recreate_registry(fr):
    sd = fr.rec["stack_dir"]
    r = subprocess.run(["docker", "compose", "-f", "docker-compose.frame-test.yml", "--env-file", ".env.frame-test", "up", "-d",
                        "--no-deps", "--force-recreate", f"{fr.name}-registry"], cwd=sd, capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise StepFailed(f"recreating {fr.name}-registry failed: {(r.stderr or r.stdout)[-300:]}")
    for _ in range(60):
        if fr.healthy():
            return
        time.sleep(5)
    raise StepFailed(f"{fr.name}-registry was recreated but does not answer /health after 300 s")


def join_network(container, network):
    r = subprocess.run(["docker", "network", "connect", network, container], capture_output=True, text=True, timeout=60)
    return r.returncode == 0 or "already exists" in (r.stderr or "")


def step_fixtures(a, parent, frames, sets):
    """The federation suite's fixtures on A: both frames, both operators, B's store. Only with 2 frames and operators
    (the suite needs exactly that); with one frame the tester's own fixtures, written at standup, are the whole set."""
    fr_a, fr_b = frames["a"], frames["b"]
    ea, pa = fr_a.admin()
    eb, pb = fr_b.admin()
    slug_a, slug_b = sets[0]["operator"], sets[1]["operator"]
    oa, opa = operator_login(parent, slug_a)
    ob, opb = operator_login(parent, slug_b)
    if not (opa and opb):
        raise StepFailed("an operator's first-boot admin password is not in the frame runner's job results "
                         f"({slug_a}: {'found' if opa else 'missing'}, {slug_b}: {'found' if opb else 'missing'})")
    es_b_key = None
    for line in open(os.path.join(fr_b.rec["stack_dir"], ".env.frame-test")):
        if line.startswith("EVENT_STORE_INTERNAL_API_KEY="):
            es_b_key = line.split("=", 1)[1].strip()
    b = fr_b.name
    pairs = [("API_TEST_FED_A_CONTAINER", f"{fr_a.name}-registry"), ("API_TEST_FED_A_EMAIL", ea), ("API_TEST_FED_A_PASSWORD", pa),
             ("API_TEST_FED_B_CONTAINER", f"{b}-registry"), ("API_TEST_FED_B_EMAIL", eb), ("API_TEST_FED_B_PASSWORD", pb),
             ("API_TEST_FED_A_PEER_MATCH", sets[0]["label"].lower()), ("API_TEST_FED_B_PEER_MATCH", sets[1]["label"].lower()),
             ("API_TEST_FED_ALPHA_CONTAINER", f"cloud-op-{slug_a}-registry"), ("API_TEST_FED_ALPHA_DB", f"cloud-op-{slug_a}-db"),
             ("API_TEST_FED_ALPHA_TEG", f"cloud-op-{slug_a}-teg"), ("API_TEST_FED_ALPHA_EMAIL", oa), ("API_TEST_FED_ALPHA_PASSWORD", opa),
             ("API_TEST_FED_DELTA_CONTAINER", f"cloud-op-{slug_b}-registry"), ("API_TEST_FED_DELTA_DB", f"cloud-op-{slug_b}-db"),
             ("API_TEST_FED_DELTA_TEG", f"cloud-op-{slug_b}-teg"), ("API_TEST_FED_DELTA_EMAIL", ob), ("API_TEST_FED_DELTA_PASSWORD", opb),
             ("API_TEST_TGT_B_REGISTRY", f"{b}-registry"), ("API_TEST_TGT_B_TEG", f"{b}-teg"), ("API_TEST_TGT_B_ES", f"{b}-event-store"),
             ("API_TEST_TGT_B_ES_DB", f"{b}-es-db"), ("API_TEST_TGT_B_INTERNAL_URL", f"http://{b}-registry:8000"),
             ("API_TEST_TGT_B_EXTERNAL_HOST", f"http://{b}-registry:8000"), ("API_TEST_REG_DB_CONTAINER_B", f"{b}-db"),
             ("SANDBOX_B_INTERNAL_URL", f"http://{b}-registry:8000"),
             # B's store listens only behind its mTLS gateway (nothing on :8200 in a kit frame); A's registry reads it with
             # its own SVID, which B's gateway verifies against the federated bundle, and probes the handshake there too
             ("API_TEST_EVENT_STORE_B_URL", f"https://{b}-nginx-event-store:8443"),
             ("API_TEST_ES_MTLS_GATEWAY_B", f"https://{b}-nginx-event-store:8443")]
    if es_b_key:
        pairs.append(("API_TEST_EVENT_STORE_B_API_KEY", es_b_key))
    upsert_env(os.path.join(fr_a.rec["stack_dir"], ".env.frame-test"), pairs)
    recreate_registry(fr_a)
    # A's registry reaches B's registry and store by name: on B's frame network, joined after every recreate of A's
    # registry (a compose recreate drops a `network connect`; the join is recorded in A's frame-up.json for that)
    b_net = b.replace("-", "_") + "_network"
    if not join_network(f"{fr_a.name}-registry", b_net):
        raise StepFailed(f"{fr_a.name}-registry could not join {b_net}")
    fu_path = os.path.join(fr_a.rec["stack_dir"], "frame-up.json")
    fu = read_json(fu_path) or {}
    fu.setdefault("tester", {})["joins"] = [b_net]
    fu["tester"]["pair"] = {"b": b, "operators": [slug_a, slug_b]}
    with open(fu_path, "w") as f:
        json.dump(fu, f, indent=1)


def operator_base(slug):
    """The operator registry's door on this host: the bridge address its 8000 is published on (under the kit's edge the
    provisioner binds it to the docker bridge gateway, never every interface)."""
    out = subprocess.run(["docker", "inspect", f"cloud-op-{slug}-registry", "--format", "{{json .NetworkSettings.Ports}}"],
                         capture_output=True, text=True, timeout=60).stdout
    try:
        binds = (json.loads(out or "{}") or {}).get("8000/tcp") or []
    except ValueError:
        binds = []
    for b in binds:
        if b.get("HostPort"):
            host = b.get("HostIp") or "127.0.0.1"
            return f"http://{'127.0.0.1' if host in ('0.0.0.0', '::') else host}:{b['HostPort']}"
    return None


def step_settle(a, parent, sets, progress):
    """The pair's topology as the federation suite reads it: each operator lists its parent, the other sandbox and the
    other operator ACTIVE. The sibling operator arrives through the registry-card fan-out about two minutes after
    provisioning, so a suite started at once read a missing peer (measured on dev3: 2 of 3). Waits, says so, and never
    fails the provision over it: the sandbox is usable, only that one check would read red."""
    doors = {}
    for sb in sets:
        slug = sb["operator"]
        email, pw = operator_login(parent, slug)
        base = operator_base(slug)
        if not (pw and base):
            progress.note(f"{slug}: its admin login or door is not readable here; the topology is not waited for")
            return
        st, lg = http("POST", base + "/api/v1/auth/login", {"username": email, "password": pw}, form=True)
        if st != 200 or not isinstance(lg, dict) or not lg.get("access_token"):
            progress.note(f"{slug}: its admin could not log in (HTTP {st}); the topology is not waited for")
            return
        doors[slug] = (base, {"Authorization": f"Bearer {lg['access_token']}"})
        http("POST", base + "/api/v1/federation/sync/trigger", {"cascade": False}, headers=doors[slug][1])
    deadline, counts = time.time() + a.settle_timeout_min * 60, {}
    while True:
        for slug, (base, hdr) in doors.items():
            st, body = http("GET", base + "/api/v1/admin/federation-sync/peers", headers=hdr)
            peers = body if isinstance(body, list) else ((body or {}).get("peers") or []) if isinstance(body, dict) else []
            counts[slug] = sum(1 for x in peers if isinstance(x, dict) and x.get("status") == "ACTIVE")
        if all(c >= 3 for c in counts.values()):
            progress.note(f"each operator lists its parent, the other sandbox and the other operator ({counts})")
            return
        if time.time() >= deadline:
            progress.note(f"the operators have not all found each other after {a.settle_timeout_min} min ({counts} of 3 "
                          f"active peers): the sandboxes are usable; the federation suite's peer-set check reads red "
                          f"until they do")
            return
        progress.note(f"waiting for the operators to find each other through the card fan-out ({counts} of 3)")
        time.sleep(30)


def step_ready(frames, fixtures_path, progress):
    fx = read_json(fixtures_path) or {}
    for key, fr in frames.items():
        st, body = http("POST", fr.base + "/api/v1/auth/login", {"username": "admin@test.sandbox",
                                                                "password": fx.get("SANDBOX_ADMIN_PASSWORD", "")}, form=True)
        if st != 200:
            raise StepFailed(f"{fr.name}: the tester's seeded admin cannot log in (HTTP {st}, {detail(body)}): the suite would "
                             f"refuse to start")
        progress.note(f"{fr.name}: the tester's seeded admin logs in")


# ── the commands ────────────────────────────────────────────────────────────────────────────────────────────────────
def cmd_up(a, progress):
    parent = newest_record(a.stack_root, a.for_frame)
    progress.start("plan")
    if not parent:
        raise StepFailed(f"no frame named {a.for_frame} under {a.stack_root} (frame-up writes <name>-<ts>/frame-up.json)")
    if parent.get("sandbox_of"):
        raise StepFailed(f"{a.for_frame} is itself a sandbox (of {parent['sandbox_of']})")
    if a.operators and a.frames == 1:
        progress.note("one frame with an operator: the lifecycle sweep's cloud-operator flows get a subject; the federation "
                      "suite needs two frames")
    if docker_socket_gid() is None:
        raise StepFailed("/var/run/docker.sock is not here: a sandbox's tester reaches its containers through it")
    sets = sandbox_names(parent, a.frames)
    taken = set(frame_ports.taken_ports(a.stack_root)) | frame_ports.host_listeners()
    fixtures = fixture_secrets_file(a.stack_root, sets[0]["name"])
    progress.end(f"{len(sets)} sandbox(es) of {parent['name']}: {', '.join(s['name'] + ' at ' + s['public_name'] for s in sets)}"
                 f"{'; with cloud operators' if a.operators else ''}")
    frames = {}
    for sb in sets:
        frames[sb["key"]] = step_frame(a, parent, sb, fixtures, taken, progress)
    if a.frames == 1:
        progress.skip("frame_b", "one frame asked for")
        progress.skip("federate", "one frame asked for")
    else:
        step_federate(a, frames["a"], frames["b"], parent, progress)
    for sb in (sets if a.operators else []):
        step_operator(a, frames[sb["key"]], sb, sets[0]["name"], parent["name"], progress)
    if not a.operators:
        progress.skip("operator_a", "no operators asked for")
        progress.skip("operator_b", "no operators asked for")
    elif a.frames == 1:
        progress.skip("operator_b", "one frame asked for")
    if a.frames == 2 and a.operators:
        progress.start("fixtures")
        step_fixtures(a, parent, frames, sets)
        progress.end("the federation suite's fixtures are on the first sandbox; its registry was recreated")
    else:
        progress.skip("fixtures", "the federation suite needs two frames with an operator each; the lifecycle sweep's "
                                  "fixtures were written at standup")
    progress.start("ready")
    step_ready(frames, fixtures, progress)
    if a.frames == 2 and a.operators:
        step_settle(a, parent, sets, progress)
    progress.end()
    live = {k: {"name": fr.name, "console": fr.rec.get("console"), "tester": (fr.rec.get("console") or "") + "/#/admin/mcp-tester"}
            for k, fr in frames.items()}
    progress.emit("ready", "live", f"{len(frames)} sandbox(es) of {parent['name']} ready", sandboxes=live,
                  suites=["lifecycle"] + (["federation"] if a.frames == 2 and a.operators else []))
    return 0


def cmd_down(a, progress):
    parent = newest_record(a.stack_root, a.for_frame) or {"name": a.for_frame}
    names = [f"{a.for_frame}sbxb", f"{a.for_frame}sbx"]
    progress.start("operators")
    for name in names:
        fr = Frame(a.stack_root, name)
        if not fr.exists or not fr.healthy():
            continue
        try:
            A = fr.token()
        except StepFailed as exc:
            progress.note(f"{name}: {exc}; its operators are removed with it by frame-down")
            continue
        for row in operator_rows(fr, A):
            rid = row.get("id") or row.get("application_id")
            if not rid:
                continue
            st, body = http("POST", fr.base + f"/api/v1/admin/cloud-operators/{rid}/teardown", {"purge": False}, headers=A, timeout=1800)
            progress.note(f"{name}: operator {row.get('slug') or row.get('name') or rid} torn down through its frame: HTTP {st}"
                          + ("" if st == 200 else f" ({detail(body)})"))
    progress.end()
    for name, step in zip(names, ("frame_b", "frame_a")):
        if not frame_names.stack_dirs(a.stack_root, name, need_file=None) and \
                not frame_names.frame_resources(name, a.stack_root, kinds=("containers",))["containers"]:
            progress.skip(step, f"{name} is not on this host")
            continue
        progress.start(step)
        r = subprocess.run([sys.executable, "-u", os.path.join(HERE, "frame-down.py"), "--name", name, "--stack-root", a.stack_root, "--yes"],
                           capture_output=True, text=True, timeout=1800)
        sys.stdout.write(r.stdout)
        if r.returncode != 0:
            raise StepFailed(f"frame-down --name {name} exited {r.returncode}: {(r.stdout or r.stderr).strip()[-300:]}")
        progress.end(f"{name} removed")
    if os.path.isfile(firewall_file(a.stack_root, a.for_frame)):
        progress.start("firewall")
        close_ports(a.stack_root, a.for_frame, progress)
        progress.end("the rules frame-sandbox opened are removed")
    else:
        progress.skip("firewall", "no firewall rules were opened for these sandboxes")
    progress.emit("firewall", "live", f"the sandboxes of {parent['name']} are gone")
    return 0


def cmd_status(a):
    out = []
    for name in (f"{a.for_frame}sbx", f"{a.for_frame}sbxb"):
        fr = Frame(a.stack_root, name)
        if fr.exists:
            out.append({"name": name, "console": fr.rec.get("console"), "healthy": fr.healthy(), "stack_dir": fr.rec.get("stack_dir")})
    if a.json:
        print(json.dumps({"frame": a.for_frame, "sandboxes": out}, indent=1))
    else:
        for s in out or [{"name": "(none)", "console": "", "healthy": ""}]:
            print(f"{s['name']:<24} {'healthy' if s['healthy'] else 'DOWN' if s['healthy'] is False else ''}  {s['console']}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["up", "down", "status"])
    ap.add_argument("--for", dest="for_frame", required=True, help="the frame this host runs whose sandbox this is")
    ap.add_argument("--frames", type=int, choices=[1, 2], default=1, help="1 (the lifecycle sweep) or 2 federated (the federation suite too)")
    ap.add_argument("--operators", action="store_true", help="a cloud operator on each sandbox (the federation suite needs them)")
    ap.add_argument("--stack-root", default=os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack"))
    ap.add_argument("--progress-file", default=None, help="append progress lines here (the frame runner passes its job's)")
    ap.add_argument("--max-load", type=int, default=40)
    ap.add_argument("--federate-timeout-min", type=int, default=20)
    ap.add_argument("--operator-timeout-min", type=int, default=20)
    ap.add_argument("--settle-timeout-min", type=int, default=6,
                    help="with 2 frames and operators: how long ready waits for the operators to find each other")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,24}[a-z0-9]", a.for_frame):   # room for the sbxbop suffix within a frame name's 32
        print(f"--for {a.for_frame!r}: not a frame name (lowercase letters, digits, dashes; at most 26)"); return 2
    if a.command == "status":
        return cmd_status(a)
    if os.geteuid() != 0:
        print("frame-sandbox stands frames up and down: run it as root (the frame runner does)"); return 2
    progress = Progress(a.progress_file)
    try:
        return cmd_up(a, progress) if a.command == "up" else cmd_down(a, progress)
    except StepFailed as exc:
        progress.fail(str(exc))
        return 3
    except Exception as exc:  # noqa: BLE001 — the job's last line must name what broke, never a bare traceback
        progress.fail(f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    sys.exit(main())
