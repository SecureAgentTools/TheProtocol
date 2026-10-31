#!/usr/bin/env python3
"""frame-up: a federated TheProtocol frame on this host, from this export, in one command (§HELLOFRAME 2026-09-18).

    ./frame-up.py --name myframe --public-name frame.example.org --ticker MYF --currency-name "My Unit" \\
                  --admin-email ops@example.org [--mail-server smtp.example.org --mail-port 587 \\
                  --mail-address noreply@example.org --mail-token-file /root/.smtp_token] \\
                  [--stack-root /opt/theprotocol/stack] [--images-prefix theprotocol --version <VERSION file>] \\
                  [--federation-port 8443 --bundle-port 8444 --ledger-port 8445 --edge-https-port 443 --edge-http-port 80] \\
                  [--edge-tls acme|internal] [--posture production|sandbox] [--mint 1000000] [--frame-label ...] [--skip-doctor]
    ./frame-up.py --name myframesbx --sandbox-of myframe --public-name sandbox.frame.example.org --ticker SBX ... \
                  --federation-port 8453 --bundle-port 8454 --ledger-port 8455   (a SANDBOX; frame-sandbox.py is the usual caller)

What it does, in order: frame-doctor's checks; the same standup driver a network-run frame is built with, in its
own-host mode (no host nginx, no host certificate, no other stack read); the public edge (Caddy, this host's ports 80 and
443 by default, a Let's Encrypt certificate for --public-name); a health read through the edge; a summary with the four
public addresses, where the admin's first password was written, and the next command (`frame-federate.py`). With
--sandbox-of <frame> it stands up that frame's SANDBOX instead (§TESTBED): posture sandbox, the MCP/API tester run against
itself (the docker socket in its registry, the fixture accounts seeded), no edge of its own (its console is a site on
the parent's edge, sandboxes/sandbox-<name>.caddy), its operators named under the parent's public name, and the parent's
frame runner adopting it so its console can provision them. Re-running
with the same --name refuses while that frame's containers exist (`frame-down.py` first). Secrets are written to
--secrets-dir (default <stack-root>/<name>-secrets, mode 700) and never printed.
"""
import argparse
import datetime
import re
import importlib.util
import json
import os
import subprocess
import sys
import time
import urllib.request
import ssl

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DRIVER = os.path.join(EXPORT_ROOT, "scripts", "hetzner_demo", "standup_driver.py")
_names_spec = importlib.util.spec_from_file_location("frame_names", os.path.join(EXPORT_ROOT, "scripts", "hetzner_demo", "frame_names.py"))
frame_names = importlib.util.module_from_spec(_names_spec); _names_spec.loader.exec_module(frame_names)   # §TESTBED P0 a


def log(msg):
    print(f"[frame-up {time.strftime('%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def version_of(path):
    try:
        return open(path).read().strip()
    except OSError:
        return "dev"


# The Federation Operator Terms (agentvault2-56, 2026-10-22; his word: "make sure terms are accepted also on framekit
# standup. because there an account is issued"). Joining the network as a frame operator means accepting them
# (PUBLIC_DOCS/11_LEGAL_FOR_OPERATORS.md); every other rail that issues an account records what its person accepted.
# frame-up asks before anything is created and hands the acceptance to the registry, which records it with the first
# admin it creates (operator_seed, TheProtocolReleaseV0632 and later); frame-up.json keeps it for the frame's sandboxes.
TERMS_DOCUMENT = "operators"
TERMS_NAME = "the Federation Operator Terms"
TERMS_URL = "https://theprotocol.cloud/#/legal/operators"


def served_terms_version():
    """The Operator Terms version this export's registry serves (its core/legal_versions.py), or None when unreadable."""
    path = os.path.join(EXPORT_ROOT, "AgentVault", "agentvault_registry", "src", "agentvault_registry", "core",
                        "legal_versions.py")
    try:
        text = open(path).read()
    except OSError:
        return None
    m = re.search(r'^OPERATOR_TERMS_SET_VERSION\s*=\s*"([^"]+)"', text, re.M)
    return m.group(1) if m else None


def terms_acceptance(a, parent, *, interactive, ask=input, now=None):
    """(acceptance, why): what this standup records with the admin it creates, or None and why.

    --sandbox-of: the parent frame's own acceptance (the person accepted once, for the frame and its sandboxes); a parent
    stood up before frame-up asked records none, and neither does its sandbox (frame-sandbox runs without a terminal, so
    this never refuses). Otherwise --accept-terms accepts, a terminal asks, and neither refuses before anything exists.
    --dry-run creates nothing, so it asks nothing."""
    version = served_terms_version()
    named = TERMS_NAME + (f" (set {version})" if version else "")
    if parent is not None:
        inherited = parent.get("terms")
        if not isinstance(inherited, dict) or not inherited.get("accepted_at"):
            return None, (f"{a.sandbox_of} records no acceptance of {TERMS_NAME} (it was stood up before frame-up asked): "
                          f"this sandbox's admin is created without one, and its console asks at the first login")
        return {"document": TERMS_DOCUMENT, "version": inherited.get("version") or version,
                "accepted_at": inherited["accepted_at"], "how": f"the sandbox of {a.sandbox_of}",
                "by": f"frame-up.py {a.version} (the sandbox of {a.sandbox_of}, accepted at its standup)"}, None
    if a.dry_run and not a.accept_terms:
        return None, "a dry run creates nothing, so it accepts nothing (a real run asks, or takes --accept-terms)"
    if a.accept_terms:
        how = "--accept-terms"
    elif interactive:
        print(f"\nJoining TheProtocol's network as a frame operator means accepting {named}: {TERMS_URL}\n"
              f"Your frame's registry records the acceptance with the admin account it creates ({a.admin_email}).")
        if (ask('Type "yes" to accept them, anything else to stop: ') or "").strip().lower() not in ("yes", "y"):
            return None, f"{TERMS_NAME} were not accepted: nothing was created"
        how = "prompt"
    else:
        return None, (f"accepting {named} ({TERMS_URL}) comes first, and this run has no terminal to ask on: read them "
                      f"and run again with --accept-terms. Nothing was created.")
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"document": TERMS_DOCUMENT, "version": version, "accepted_at": stamp, "how": how,
            "by": f"frame-up.py {a.version} ({how})"}, None


def terms_driver_args(terms):
    """The standup driver's arguments that carry the acceptance into the frame's env (FIRST_ADMIN_ACCEPTED*)."""
    if not terms:
        return []
    return ["--admin-accepted", terms["document"], "--admin-accepted-at", terms["accepted_at"],
            "--admin-accepted-by", terms["by"]]


def terms_recorded(name, stack_dir, admin_email, run=subprocess.run):
    """The acceptances the frame's registry recorded for its admin at the standup (via frame_standup), as
    [(document, version, accepted_at)]; None when the frame's database cannot be read. Read in its own database
    container (names only from the env file, never a password)."""
    found = {}
    try:
        with open(os.path.join(stack_dir, ".env.frame-test")) as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k in ("FT_DB_POSTGRES_USER", "FT_DB_POSTGRES_DB"):
                    found[k] = v.strip().strip('"').strip("'")
    except OSError:
        return None
    user = found.get("FT_DB_POSTGRES_USER") or "registry"
    db = found.get("FT_DB_POSTGRES_DB") or "frame_test_registry"
    r = run(["docker", "exec", f"{name}-db", "psql", "-U", user, "-d", db, "-tA", "-F", "\t", "-c",
             "select d.email, a.document, a.version, a.accepted_at from legal_acceptances a "
             "join developers d on d.id = a.developer_id where a.via = 'frame_standup'"],
            capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None
    rows = []
    for line in (r.stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) == 4 and parts[0].strip().lower() == admin_email.strip().lower():
            rows.append((parts[1], parts[2], parts[3]))
    return rows


def terms_line(terms):
    """The summary line about the acceptance, from the record frame-up.json keeps."""
    if not terms:
        return None
    named = TERMS_NAME + (f" (set {terms['version']})" if terms.get("version") else "")
    rec = terms.get("recorded")
    if rec:
        return f"{named} accepted {terms['accepted_at']} ({terms['how']}), recorded with {terms['admin_email']}"
    if rec is None:
        return (f"{named} accepted {terms['accepted_at']} ({terms['how']}); the record could not be read back from the "
                f"frame's database")
    return (f"{named} accepted {terms['accepted_at']} ({terms['how']}), NOT recorded: this registry image predates the "
            f"standup record (TheProtocolReleaseV0632); its console asks the admin at the first login")


def doctor(a):
    spec = importlib.util.spec_from_file_location("frame_doctor", os.path.join(HERE, "frame-doctor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ns = argparse.Namespace(name=a.name, public_name=a.public_name, stack_root=a.stack_root, images_prefix=a.images_prefix, version=a.version,
                            federation_port=a.federation_port, bundle_port=a.bundle_port, ledger_port=a.ledger_port,
                            edge_https_port=a.edge_https_port, edge_http_port=a.edge_http_port, edge_tls=a.edge_tls,
                            min_mem_gib=a.min_mem_gib, min_disk_gb=20, edge_via=getattr(a, "sandbox_of", None))
    return mod.checks(ns)


def pull_images(a, attempts=3):
    """§EXTTEST (beta.26): pull what the standup needs and this host lacks, before the doctor reads the host: the release's
    six images when --images-prefix names a registry, and every public image the frame's templates use. One line per
    attempt and retries with backoff, so one timeout on a slow link no longer becomes a reconcile loop naming ten missing
    services. -> the references still missing"""
    spec = importlib.util.spec_from_file_location("frame_doctor", os.path.join(HERE, "frame-doctor.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    first = a.images_prefix.split("/", 1)[0]
    remote = "/" in a.images_prefix and ("." in first or ":" in first or first == "localhost")
    refs = ([f"{a.images_prefix}/{n}:{a.version}" for n in mod.IMAGES] if remote else []) + list(mod.public_images())

    def present(ref):
        return subprocess.run(["docker", "image", "inspect", ref], capture_output=True).returncode == 0

    todo = [r for r in dict.fromkeys(refs) if not present(r)]
    if todo:
        log(f"pulling {len(todo)} image(s) this host lacks" + (f" (the release's from {a.images_prefix}," if remote else " (")
            + " the public ones from Docker Hub and ghcr.io)")
    for n, ref in enumerate(todo, 1):
        for k in range(1, attempts + 1):
            log(f"pulling {ref} ({n}/{len(todo)}, attempt {k}/{attempts})")
            r = subprocess.run(["docker", "pull", "-q", ref], capture_output=True, text=True)
            if r.returncode == 0:
                break
            tail = (r.stderr or r.stdout or "").strip().splitlines()[-1:] or ["no detail"]
            log(f"pull of {ref} failed: {tail[0][:200]}")
            if k < attempts:
                time.sleep(10 * k)
    return [r for r in todo if not present(r)]


INSTALLER = os.path.join(HERE, "frame-runner-install.py")


def runner_fact_from_output(text, key):
    """A `KEY=value` token on the installer's last line that names it (FRAME_RUNNER_SOCKET_GID=, SOCKET=, OPERATOR_SOCKET_DIR=), or None."""
    for line in reversed((text or "").splitlines()):
        m = re.search(r"(?:^|\s)" + re.escape(key) + r"=(\S+)", line)
        if m:
            return m.group(1)
    return None


def adopt_argv(export_root, name, stack_dir, socket=None):
    """The frame runner's adopt CLI (lane 6): records a frame-up frame so the runner provisions operators for it."""
    argv = [sys.executable, "-u", os.path.join(export_root, "tools", "frame-runner", "frame_runner.py"), "adopt", "--name", name, "--stack-dir", stack_dir]
    if socket:
        argv += ["--socket", socket]
    return argv


def runner_gid_from_output(text):
    """The installer's last line is `FRAME_RUNNER_SOCKET_GID=<gid> SOCKET=... EDGE=...`; the gid, or None when no line says so."""
    for line in reversed((text or "").splitlines()):
        m = re.search(r"\bFRAME_RUNNER_SOCKET_GID=(\d+)\b", line)
        if m:
            return m.group(1)
    return None


def interrupted_stack(stack_root, name):
    """(stack dir, failed step) of an interrupted standup of this name, or None: the newest <name>-<ts> under the root whose
    standup-progress.jsonl ends in a failed step and whose run record exists. A finished standup (last event ok on the last
    step, or a frame-up.json beside it) is not interrupted."""
    cands = frame_names.stack_dirs(stack_root, name, need_file=None)
    for d in reversed(cands):
        sd = os.path.join(stack_root, d)
        prog = os.path.join(sd, "standup-progress.jsonl")
        if not os.path.isfile(prog) or not os.path.isfile(os.path.join(sd, "hetzner-demo-run.json")) or os.path.isfile(os.path.join(sd, "frame-up.json")):
            continue
        last = None
        for line in open(prog):
            line = line.strip()
            if line:
                try:
                    last = json.loads(line)
                except Exception:
                    continue
        if last and last.get("event") == "fail" and last.get("step"):
            return sd, last["step"]
        return None
    return None


def host_public_ip(a):
    """The address the public name resolves to, preferring one this host holds (the doctor's resolver and host list)."""
    try:
        spec = importlib.util.spec_from_file_location("frame_doctor", os.path.join(HERE, "frame-doctor.py"))
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        found = mod.resolve_public(a.public_name); mine = set(mod.host_ipv4s())
        for ip in found:
            if ip in mine:
                return ip
        return found[0] if found else ""
    except Exception:  # noqa: BLE001
        return ""


def prepare_stack_root(path, uid=1000, gid=1000):
    """The stack root the frame and its operators live under. The frame runner's one-shot writes an operator's stack
    beside the frame's as the registry image's own user (uid 1000, never root), so the root must let that user create a
    directory: on the network's host it is deploy:deploy 755; a root created by frame-up as root refused the first
    operator with PermissionError (§HELLOFRAME Phase 2b). Created if absent, owned by the one-shot's user, mode 755."""
    os.makedirs(path, mode=0o755, exist_ok=True)
    try:
        os.chown(path, uid, gid); os.chmod(path, 0o755)
    except PermissionError as e:
        log(f"the stack root {path} could not be given to uid {uid} ({e}); an operator stack written there by the runner will be refused")


def render(src, dst, values):
    text = open(src).read()
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", str(v))
    left = [l for l in text.splitlines() if "{{" in l]
    if left:
        raise SystemExit(f"frame-up: {os.path.basename(src)} kept an unrendered placeholder: {left[0].strip()}")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    open(dst, "w").write(text)


def allocate_ports(a):
    """All nine host ports of the frame, chosen free by the export's own allocator (scripts/hetzner_demo/frame_ports.py,
    the one the standup driver uses), with the two PUBLIC lanes pinned to the ports the caller named: the driver refuses
    --allocate-ports beside a declared FRAME_TEST_PORT_* (two declarations of one fact), so frame-up declares all of them."""
    spec = importlib.util.spec_from_file_location("frame_ports", os.path.join(EXPORT_ROOT, "scripts", "hetzner_demo", "frame_ports.py"))
    fp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fp)
    taken = fp.taken_ports(a.stack_root) if os.path.isdir(a.stack_root) else fp.host_listeners() | fp.container_bindings()
    taken |= {a.federation_port, a.bundle_port, a.ledger_port, a.edge_https_port, a.edge_http_port}
    ports = fp.allocate(taken)
    ports["nginx_fed"] = a.federation_port
    ports["spire_bundle"] = a.bundle_port
    return {fp.ENV_NAMES[k]: str(v) for k, v in ports.items()}, ports


def edge_admin_port(stack_root, start=2019, stop=2100, listeners=None):
    """The loopback port this frame's edge serves Caddy's admin API on: the first in [start, stop) no host listener holds
    and no other frame's frame-up.json records (a stopped edge does not listen, but its port is still its own). Caddy's
    default 2019 is one per host: a second kit frame's edge could not start, and its `caddy reload` would reach the first
    frame's Caddy (§TESTBED P0 g)."""
    if listeners is None:
        spec = importlib.util.spec_from_file_location("frame_ports", os.path.join(EXPORT_ROOT, "scripts", "hetzner_demo", "frame_ports.py"))
        fp = importlib.util.module_from_spec(spec); spec.loader.exec_module(fp)
        listeners = fp.host_listeners()
    recorded = set()
    if stack_root and os.path.isdir(stack_root):
        for d in os.listdir(stack_root):
            try:
                with open(os.path.join(stack_root, d, "frame-up.json")) as f:
                    port = ((json.load(f) or {}).get("edge") or {}).get("admin_port")
                if port:
                    recorded.add(int(port))
            except (OSError, ValueError, TypeError):
                continue
    for port in range(start, stop):
        if port not in listeners and port not in recorded:
            return port
    raise RuntimeError(f"no free loopback port in {start}-{stop - 1} for the edge's admin API")


def parent_frame(stack_root, name):
    """(the parent frame's frame-up.json with its stack_dir, None) or (None, why): the newest <name>-<ts> of that name
    holding a frame-up.json (§TESTBED: a sandbox is stood up next to a frame frame-up stood up)."""
    dirs = frame_names.stack_dirs(stack_root, name, need_file="frame-up.json")
    if not dirs:
        return None, f"no frame named {name} under {stack_root} (no {name}-<ts>/frame-up.json): a sandbox stands next to a frame frame-up stood up"
    sd = os.path.join(stack_root, dirs[-1])
    try:
        with open(os.path.join(sd, "frame-up.json")) as f:
            rec = json.load(f) or {}
    except (OSError, ValueError) as e:
        return None, f"{sd}/frame-up.json is unreadable: {e}"
    rec["stack_dir"] = sd
    return rec, None


def caddy_global_email(caddyfile_text):
    """The ACME address in a Caddyfile's global block (`email x@y`), or ''."""
    m = re.search(r"^\s*email\s+(\S+@\S+)\s*$", caddyfile_text or "", re.M)
    return m.group(1) if m else ""


def site_block(public_name, tls_line, port_registry, port_es):
    """A frame's console as a site on ANOTHER frame's edge: the edge template's own site block (one source), rendered."""
    text = open(os.path.join(HERE, "frame-edge.Caddyfile.tmpl")).read()
    block = text[text.index("{{PUBLIC_NAME}} {"):]
    for k, v in {"PUBLIC_NAME": public_name, "TLS_LINE": tls_line, "PORT_REGISTRY": port_registry, "PORT_ES": port_es}.items():
        block = block.replace("{{" + k + "}}", str(v))
    if "{{" in block:
        raise SystemExit("frame-up: the sandbox's site block kept an unrendered placeholder")
    return block


def sandbox_site_path(parent, name):
    """Where the sandbox's site file goes on the parent's edge: sandboxes/ when the parent's Caddyfile imports it, else
    operators/ (an edge rendered before the sandboxes import, which every edge does import)."""
    pe = parent.get("edge") or {}
    try:
        imports_sbx = "import sandboxes/*.caddy" in open(os.path.join(parent["stack_dir"], "edge", "Caddyfile")).read()
    except OSError:
        imports_sbx = False
    d = (pe.get("sandboxes_dir") or os.path.join(parent["stack_dir"], "edge", "sandboxes")) if imports_sbx else \
        (pe.get("operators_dir") or os.path.join(parent["stack_dir"], "edge", "operators"))
    return os.path.join(d, f"sandbox-{name}.caddy")


def caddy(container, verb):
    """`caddy validate|reload` in an edge container (the Caddyfile names its own admin address). (rc, tail)."""
    try:
        r = subprocess.run(["docker", "exec", container, "caddy", verb, "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"],
                           capture_output=True, text=True, timeout=90)
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)[-300:]
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()[-300:]


def console_url(a):
    """The console's public address: the edge's HTTPS port, or --public-https-port where a front door the host runs (a
    reverse proxy holding 443) serves the edge on another port."""
    port = getattr(a, "public_https_port", None) or a.edge_https_port
    return f"https://{a.public_name}" + ("" if port == 443 else f":{port}")


def reach_check(a):
    """§EXTREACH design A: ask the network whether the internet reaches the four lanes (frame-reach.py). A warning,
    never a refusal: the frame is up either way, and the lines say which forward is missing."""
    if a.edge_tls == "internal":
        log("reach check: skipped (internal TLS: a test frame; run ./frame-reach.py once it has a public name)")
        return None
    spec = importlib.util.spec_from_file_location("frame_reach", os.path.join(HERE, "frame-reach.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ports = {"console": a.public_https_port or a.edge_https_port, "federation": a.federation_port,
             "bundle": a.bundle_port, "ledger": a.ledger_port}
    rc, _ = mod.check_and_report(a.public_name, ports, a.reach_probe or mod.DEFAULT_PROBE)
    return rc


def health(url, tls):
    ctx = ssl.create_default_context()
    if tls == "internal":
        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    for _ in range(36):
        try:
            with urllib.request.urlopen(url, timeout=10, context=ctx) as resp:
                return resp.status
        except Exception:  # noqa: BLE001
            time.sleep(5)
    return None


def sandbox_edge_and_record(a, parent, stack_dir, ports, runner, t0, terms=None):
    """§TESTBED: the sandbox's console as a site on the parent's edge (validated before the reload, reverted when refused),
    its health through that edge, and its frame-up.json, which names the PARENT's edge container and operators dir so the
    runner writes the sandbox's operators' sites there too."""
    pe = parent.get("edge") or {}
    try:
        caddyfile = open(os.path.join(parent["stack_dir"], "edge", "Caddyfile")).read()
    except OSError:
        caddyfile = ""
    acme = caddy_global_email(caddyfile)
    tls_line = "tls internal" if a.edge_tls == "internal" else (f"tls {acme}" if acme else "")
    path = sandbox_site_path(parent, a.name)
    os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
    prior = open(path).read() if os.path.isfile(path) else None
    with open(path, "w") as f:
        f.write(f"# {a.name}: the SANDBOX of {a.sandbox_of} (frame-up --sandbox-of, §TESTBED); removed by frame-down --name {a.name}\n")
        f.write(site_block(a.public_name, tls_line, ports["registry"], ports["es"]))
    os.chmod(path, 0o644)
    rc, tail = caddy(pe["container"], "validate")
    if rc != 0:
        if prior is None:
            os.remove(path)
        else:
            open(path, "w").write(prior)
        log(f"the parent's edge refused the sandbox's site ({tail}); the site file was reverted, the sandbox stands without "
            f"a console: frame-down.py --name {a.name}"); return 1
    rc, tail = caddy(pe["container"], "reload")
    if rc != 0:
        log(f"the parent's edge did not reload ({tail}); {a.public_name} opens at that edge's next reload")
    status = health(console_url(a) + "/health", a.edge_tls)
    record = {"name": a.name, "public_name": a.public_name, "stack_dir": stack_dir, "secrets_dir": a.secrets_dir,
              "console": console_url(a), "sandbox_of": a.sandbox_of, "parent_stack_dir": parent["stack_dir"],
              "federation_lane": f"https://{a.public_name}:{a.federation_port}",
              "bundle_endpoint": f"https://{a.public_name}:{a.bundle_port}/", "ledger_gateway": f"https://{a.public_name}:{a.ledger_port}",
              "edge": {"via": a.sandbox_of, "tls": a.edge_tls, "acme_email": acme, "http_port": a.edge_http_port,
                       "https_port": a.edge_https_port, "public_https_port": a.public_https_port,
                       "container": pe["container"], "site_file": path,
                       "operators_dir": pe.get("operators_dir") or os.path.join(parent["stack_dir"], "edge", "operators"),
                       "admin_port": pe.get("admin_port"), "reload": pe.get("reload")},
              "runner": runner, "tester": {"self": True, "fixtures_file": os.path.join(a.secrets_dir, f".{a.name}_tester_fixtures.secret.json")},
              "images": f"{a.images_prefix}/*:{a.version}", "ports": ports, "edge_health": status, "seconds": int(time.time() - t0),
              "terms": terms}
    with open(os.path.join(stack_dir, "frame-up.json"), "w") as f:
        json.dump(record, f, indent=1)
    log(f"health through {a.sandbox_of}'s edge: {status if status else 'no answer in 180 s'}")
    print("\nThe sandbox is up." if status == 200 else "\nThe sandbox started, but the edge did not answer yet.")
    print(f"  console            {record['console']}   (a site on {a.sandbox_of}'s edge)")
    print(f"  tester             {record['console']}/#/admin/mcp-tester   (it runs against this sandbox itself)")
    print(f"  admin login        {a.admin_email}; the first password is in {a.secrets_dir} (mode 600)")
    if terms_line(terms):
        print(f"  terms              {terms_line(terms)}")
    print(f"  lanes              federation {a.federation_port}, bundle {a.bundle_port}, ledger {a.ledger_port}")
    print(f"  stack directory    {stack_dir}")
    print(f"  remove             ./frame-down.py --name {a.name}")
    return 0 if status == 200 else 1


def apply_legal_env(a, stack_dir):
    """§LEGALKIT: the operator's legal facts ride in the frame's env (LEGAL_* lines, PUBLIC_DOCS/11_LEGAL_FOR_OPERATORS.md).
    Appended after the standup so the standup driver stays what it is; the registry is recreated once so the legal
    pages, the mail footer, security.txt and the API document read them. LEGAL_SUITE_MODE stays `operator`: a frame
    you run never claims the software author's suite, and the file cannot switch it."""
    src = a.legal_env
    if not os.path.isfile(src):
        log(f"--legal-env {src} is not a file"); return 2
    lines = []
    for raw in open(src, encoding="utf-8").read().splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if not k.startswith("LEGAL_") or k == "LEGAL_SUITE_MODE":
            log(f"--legal-env: skipping {k} (only LEGAL_* keys are taken; the suite mode stays operator)"); continue
        lines.append(f"{k}={v.strip()}")
    if not lines:
        log("--legal-env: no LEGAL_* lines to apply"); return 0
    envp = os.path.join(stack_dir, ".env.frame-test")
    if not os.path.isfile(envp):
        log(f"no {envp}"); return 2
    cur = open(envp, encoding="utf-8").read()
    have = {l.split("=", 1)[0] for l in cur.splitlines() if "=" in l}
    add = [l for l in lines if l.split("=", 1)[0] not in have]
    with open(envp, "a", encoding="utf-8") as fh:
        fh.write(("" if cur.endswith("\n") else "\n") + "# legal facts (--legal-env)\nLEGAL_SUITE_MODE=operator\n" + "\n".join(add) + "\n")
    os.chmod(envp, 0o600)
    log(f"legal facts: {len(add)} line(s) appended to {envp}; recreating the registry so it reads them")
    reg = f"{a.name}-registry"
    proj = subprocess.run(["docker", "inspect", reg, "--format", "{{index .Config.Labels \"com.docker.compose.project\"}}"],
                          capture_output=True, text=True).stdout.strip()
    compose = os.path.join(stack_dir, "docker-compose.frame-test.yml")
    argv = ["docker", "compose"] + (["-p", proj] if proj else []) + ["-f", compose, "--env-file", envp,
            "up", "-d", "--no-deps", "--no-build", "--force-recreate", reg]
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"the registry recreate after --legal-env failed: {(r.stderr or r.stdout)[-400:]}"); return 3
    for _ in range(36):
        time.sleep(5)
        h = subprocess.run(["docker", "inspect", reg, "--format", "{{.State.Health.Status}}"], capture_output=True, text=True).stdout.strip()
        if h == "healthy":
            log("the registry is healthy with the legal facts"); return 0
    log("the registry did not report healthy within 180 s after the legal recreate; check `docker logs " + reg + "`"); return 4


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True, help="the frame's short name (containers, stack dir): lowercase letters, digits, dashes")
    ap.add_argument("--public-name", required=True, help="the frame's public DNS name; it is also the SPIFFE trust domain")
    ap.add_argument("--ticker", required=True, help="the frame's currency ticker, e.g. MYF")
    ap.add_argument("--currency-name", required=True, help="the currency's long name, e.g. 'My Unit'")
    ap.add_argument("--admin-email", required=True, help="the frame admin's login (the first password is generated and written to --secrets-dir)")
    ap.add_argument("--frame-label", default=None, help="the display name (default: derived from --name)")
    ap.add_argument("--description", default=None)
    ap.add_argument("--location-label", default="Somewhere")
    ap.add_argument("--operator-label", default=None)
    ap.add_argument("--lat", default="0.0"); ap.add_argument("--lng", default="0.0")
    ap.add_argument("--website", default=None)
    ap.add_argument("--accept-terms", action="store_true",
                    help="you accept the Federation Operator Terms (https://theprotocol.cloud/#/legal/operators); without it "
                         "frame-up asks on the terminal, and refuses where there is none. The registry records the "
                         "acceptance with the admin account it creates")
    ap.add_argument("--legal-env", default=None, help="a file of LEGAL_* lines (the operator's legal name, address, mailboxes, document links; see PUBLIC_DOCS/11_LEGAL_FOR_OPERATORS.md); appended to the frame's env after standup and the registry recreated once so its legal pages, mail footer and security.txt name you")
    ap.add_argument("--theme", choices=["neural", "sovereign"], default="neural")
    ap.add_argument("--mint", default="1000000", help="the initial supply issued into the frame's treasury")
    ap.add_argument("--posture", choices=["production", "sandbox"], default="production")
    ap.add_argument("--stack-root", default=os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack"))
    ap.add_argument("--secrets-dir", default=None, help="where the admin and service-account secrets are written (default <stack-root>/<name>-secrets)")
    ap.add_argument("--images-prefix", default=os.getenv("IMAGE_REGISTRY", "theprotocol"))
    ap.add_argument("--version", default=version_of(os.path.join(HERE, "VERSION")))
    ap.add_argument("--federation-port", type=int, default=8443, help="the mTLS federation lane peers dial")
    ap.add_argument("--bundle-port", type=int, default=8444, help="the SPIRE bundle endpoint peers fetch")
    ap.add_argument("--ledger-port", type=int, default=8445, help="the ledger's mTLS gateway peers and operators write to")
    ap.add_argument("--edge-https-port", type=int, default=443)
    ap.add_argument("--edge-http-port", type=int, default=80)
    ap.add_argument("--edge-tls", choices=["acme", "internal"], default="acme", help="acme = Let's Encrypt on 80/443; internal = Caddy's own CA (tests)")
    ap.add_argument("--public-https-port", type=int, default=None,
                    help="the port the public reaches this edge's HTTPS on (default --edge-https-port); different only where a "
                         "front door you run (a reverse proxy already holding 443) forwards to the edge")
    ap.add_argument("--acme-email", default=None, help="the address Let's Encrypt writes to (default --admin-email)")
    ap.add_argument("--mail-server", default=os.getenv("FRAME_MAIL_SERVER"))
    ap.add_argument("--mail-port", default=os.getenv("FRAME_MAIL_PORT", "587"))
    ap.add_argument("--mail-address", default=os.getenv("FRAME_MAIL_ADDRESS"))
    ap.add_argument("--mail-token-file", default=None, help="a file holding the SMTP password (never given on the command line)")
    ap.add_argument("--min-mem-gib", type=float, default=8)
    ap.add_argument("--max-load", type=int, default=40)
    ap.add_argument("--with-runner", action="store_true",
                    help="also install the frame runner (systemd, root) so this frame can provision its own cloud operators; "
                         "runs scripts/distribution/frame-runner-install.py BEFORE the frame is rendered and gives the frame the "
                         "runner's socket group")
    ap.add_argument("--runner-socket-group", default="deploy", help="the host group that owns the runner's operator socket (--with-runner)")
    ap.add_argument("--runner-instance", default=None,
                    help="--with-runner: install the runner as a named INSTANCE (its own unit, policy, sockets and state beside a runner "
                         "this host already runs); unset = the host's single runner")
    ap.add_argument("--sandbox-of", default=None,
                    help="stand this frame up as the SANDBOX of the named frame on this host (§TESTBED): posture sandbox, the "
                         "tester against itself, its console a site on the parent's edge, the parent's runner adopting it")
    ap.add_argument("--tester-fixture-secrets", default=None,
                    help="--sandbox-of: the fixture secrets a sandbox pair shares (frame-sandbox.py writes the file)")
    ap.add_argument("--skip-doctor", action="store_true")
    ap.add_argument("--skip-reach", action="store_true",
                    help="do not ask the network whether the internet reaches the four lanes (frame-reach.py)")
    ap.add_argument("--reach-probe", default=None, help="the network's reach probe (frame-reach.py's default)")
    ap.add_argument("--dry-run", action="store_true", help="print the runner installer's and the driver's commands, run nothing")
    a = ap.parse_args()

    if not os.path.isfile(DRIVER):
        raise SystemExit(f"frame-up: the standup driver is not at {DRIVER}; run this from the export's scripts/distribution.")
    a.frame_label = a.frame_label or a.name.replace("-", " ").title()
    a.description = a.description or f"{a.frame_label}: a sovereign TheProtocol frame at {a.public_name}."
    a.operator_label = a.operator_label or a.frame_label
    a.website = a.website or console_url(a)
    a.secrets_dir = a.secrets_dir or os.path.join(a.stack_root, f"{a.name}-secrets")
    a.acme_email = a.acme_email or a.admin_email

    parent = None
    if a.sandbox_of:
        parent, why = parent_frame(a.stack_root, a.sandbox_of)
        if not parent:
            log(f"--sandbox-of: {why}"); return 2
        if parent.get("sandbox_of"):
            log(f"--sandbox-of: {a.sandbox_of} is itself the sandbox of {parent['sandbox_of']}; a sandbox has no sandboxes"); return 2
        if a.name == a.sandbox_of:
            log("--sandbox-of names this frame itself"); return 2
        if a.with_runner:
            log("--sandbox-of rides the parent's frame runner; --with-runner would reinstall it (and rewrite its policy)"); return 2
        pe = parent.get("edge") or {}
        if not pe.get("container"):
            log(f"--sandbox-of: {a.sandbox_of}'s frame-up.json names no edge container; its console cannot carry a sandbox"); return 2
        a.posture = "sandbox"
        a.edge_tls = pe.get("tls") or a.edge_tls
        a.edge_https_port = int(pe.get("https_port") or a.edge_https_port)
        a.edge_http_port = int(pe.get("http_port") or a.edge_http_port)
        a.public_https_port = int(pe.get("public_https_port") or pe.get("https_port") or a.edge_https_port)
        a.website = console_url(a)
    terms, why = terms_acceptance(a, parent, interactive=sys.stdin.isatty())
    if terms is None:
        if parent is None and not a.dry_run:
            log(why); return 2
        log(f"note: {why}")
    else:
        log(f"terms: {TERMS_NAME} accepted ({terms['how']}); the registry records it with {a.admin_email} when it creates "
            f"that account")
    prepare_stack_root(a.stack_root)
    resume = interrupted_stack(a.stack_root, a.name)   # an interrupted standup of this name: its containers and ports are expected
    if not a.dry_run:
        missing = pull_images(a)
        if missing:
            for ref in missing:
                log(f"NOT READY: {ref} could not be pulled after retries; check the network and run frame-up again "
                    f"(what was pulled stays).")
            return 1
    if not a.skip_doctor:
        problems, notes = doctor(a)
        for n in notes:
            log(f"note: {n}")
        if problems:
            for p in problems:
                log(f"NOT READY: {p}")
            return 1
        log("frame-doctor: ready")
    mine = frame_names.frame_resources(a.name, a.stack_root, kinds=("containers",))["containers"]   # exactly: `a` never counts `a-b`'s
    if not resume and mine:
        log(f"{len(mine)} container(s) of a frame named {a.name} already exist on this host ({', '.join(mine[:3])}"
            f"{', ...' if len(mine) > 3 else ''}): run frame-down.py --name {a.name} first, or choose another name.")
        return 1
    mail_token = ""
    if a.mail_token_file:
        try:
            mail_token = open(a.mail_token_file).read().strip()
        except OSError as e:
            log(f"the mail token file could not be read: {e}"); return 1
    if a.posture == "production" and (a.location_label == "Somewhere" or (str(a.lat) == "0.0" and str(a.lng) == "0.0")):
        log("a production frame publishes its operator's location on its signed card, and every peer reads it as a fact: give "
            "--location-label, --lat and --lng (the defaults are a placeholder). --posture sandbox keeps the placeholder.")
        return 2
    if a.posture == "production" and not (a.mail_server and a.mail_address and mail_token):
        log("a production posture needs a mail relay (--mail-server, --mail-address, --mail-token-file): verification mail and "
            "operator mail have nowhere to go without one. Give the relay, or use --posture sandbox for a frame that mails nobody.")
        return 1

    env = dict(os.environ)
    env.update({
        "FRAME_REPO_ROOT": EXPORT_ROOT, "FRAME_STACK_ROOT": a.stack_root, "FRAME_HOST_STACK_MOUNT": a.stack_root,
        "FRAME_SECRETS_DIR": a.secrets_dir, "FRAME_MIN_FREE_GB": "20",
        "FRAME_TEST_AUDITOR_IMAGE": f"{a.images_prefix}/auditor:{a.version}",
        "FRAME_TEST_DIRECTORY_IMAGE": f"{a.images_prefix}/directory:{a.version}",
        "FRAME_CERT_WRITER_IMAGE": f"{a.images_prefix}/cert-writer:{a.version}",
        "PYTHONUNBUFFERED": "1",
    })
    if a.mail_server and a.mail_address and mail_token:
        env.update({"FRAME_MAIL_SERVER": a.mail_server, "FRAME_MAIL_PORT": str(a.mail_port),
                    "FRAME_MAIL_ADDRESS": a.mail_address, "FRAME_MAIL_TOKEN": mail_token})
    if resume:
        log(f"an interrupted standup of {a.name} is at {resume[0]} (it failed at step '{resume[1]}'): resuming it with its own ports "
            f"and secrets; run frame-down.py --name {a.name} first for a fresh one")
        chosen = {}
    else:
        try:
            port_env, chosen = allocate_ports(a)
        except Exception as e:  # noqa: BLE001 — the allocator's sentence is the point
            log(f"no free port set for the frame's loopback doors: {e}"); return 1
        env.update(port_env)
    runner = {"installed": False, "socket_gid": None}
    if parent and (parent.get("runner") or {}).get("installed"):
        # the PARENT's runner: its socket group and operator socket dir are this sandbox's too, and it adopts the sandbox
        # after the standup so the sandbox's own console can provision its operators (§TESTBED)
        pr = parent["runner"]
        runner = {"installed": False, "via_parent": a.sandbox_of, "socket_gid": pr.get("socket_gid"), "socket": pr.get("socket"),
                  "operator_socket_dir": pr.get("operator_socket_dir"), "instance": pr.get("instance")}
        if pr.get("socket_gid") is not None:
            env["FRAME_RUNNER_SOCKET_GID"] = str(pr["socket_gid"])
        if pr.get("operator_socket_dir"):
            env["FRAME_RUNNER_OPERATOR_SOCKET_DIR"] = pr["operator_socket_dir"]
    if a.with_runner:
        if not os.path.isfile(INSTALLER):
            log(f"--with-runner: the runner installer is not at {INSTALLER} in this export; the frame can be stood up without it "
                f"(drop --with-runner) and the runner installed later from an export that carries it."); return 1
        inst = [sys.executable, "-u", INSTALLER, "--stack-root", a.stack_root, "--export-root", EXPORT_ROOT, "--posture", a.posture,
                "--images-prefix", a.images_prefix, "--version", a.version, "--socket-group", a.runner_socket_group,
                "--edge", "caddy", "--domain", a.public_name, "--max-load", str(a.max_load), "--min-mem-gib", str(a.min_mem_gib),
                "--min-free-gb", "20"]
        if a.runner_instance:
            inst += ["--instance", a.runner_instance]
        if a.mail_server and a.mail_address and a.mail_token_file:
            inst += ["--mail-server", a.mail_server, "--mail-port", str(a.mail_port), "--mail-address", a.mail_address,
                     "--mail-token-file", a.mail_token_file]
        if a.dry_run:
            print(" ".join(inst))
        else:
            log("frame runner: installing (systemd service, the operator socket, the runner policy)")
            ri = subprocess.run(inst, capture_output=True, text=True)
            sys.stdout.write(ri.stdout); sys.stderr.write(ri.stderr)
            if ri.returncode != 0:
                why = {2: "refused before writing anything", 3: "a step failed", 4: "the runner never answered its ping"}.get(ri.returncode, "failed")
                log(f"the runner installer {why} (exit {ri.returncode}); nothing of the frame was started"); return ri.returncode
            gid = runner_gid_from_output(ri.stdout)
            if gid is None:
                log("the runner installer exited 0 but its last line named no FRAME_RUNNER_SOCKET_GID; refusing to render a frame "
                    "whose socket group would be a guess"); return 1
            env["FRAME_RUNNER_SOCKET_GID"] = gid
            runner = {"installed": True, "socket_gid": int(gid), "socket": runner_fact_from_output(ri.stdout, "SOCKET"),
                      "operator_socket_dir": runner_fact_from_output(ri.stdout, "OPERATOR_SOCKET_DIR")}
            if runner["operator_socket_dir"]:
                env["FRAME_RUNNER_OPERATOR_SOCKET_DIR"] = runner["operator_socket_dir"]
            log(f"frame runner: installed; the frame joins socket group {gid}" + (f", operator socket dir {runner['operator_socket_dir']}" if runner["operator_socket_dir"] else ""))
    if chosen:
        log(f"ports: loopback doors {', '.join(f'{k}={v}' for k, v in chosen.items() if k not in ('nginx_fed', 'spire_bundle'))}; "
            f"public lanes federation={chosen['nginx_fed']} bundle={chosen['spire_bundle']} ledger={a.ledger_port}")
    os.makedirs(a.secrets_dir, mode=0o700, exist_ok=True); os.chmod(a.secrets_dir, 0o700)
    argv = [sys.executable, "-u", DRIVER,
            "--own-host", "--stack-root", a.stack_root,
            "--name", a.name, "--frame-label", a.frame_label, "--trust-domain", a.public_name,
            "--public-url", console_url(a),
            "--es-public-url", f"https://{a.public_name}:{a.ledger_port}",
            "--federation-public-url", f"https://{a.public_name}:{a.federation_port}",
            "--es-mtls-port", str(a.ledger_port), "--bundle-public-url", f"https://{a.public_name}:{a.bundle_port}/",
            "--operator-images-prefix", a.images_prefix, "--host-public-ip", host_public_ip(a),
            "--ticker", a.ticker, "--currency-name", a.currency_name, "--mint", str(a.mint),
            "--admin-email", a.admin_email, "--admin-name", f"{a.frame_label} Admin",
            "--theme", a.theme, "--description", a.description, "--operator-label", a.operator_label,
            "--location-label", a.location_label, "--lat", str(a.lat), "--lng", str(a.lng), "--website", a.website,
            "--registry-image", f"{a.images_prefix}/registry:{a.version}", "--teg-image", f"{a.images_prefix}/teg-layer:{a.version}",
            "--es-image", f"{a.images_prefix}/event-store:{a.version}", "--cert-writer-image", f"{a.images_prefix}/cert-writer:{a.version}",
            "--posture", a.posture, "--env-label", a.posture, "--max-load", str(a.max_load),
            "--min-mem-gib", str(a.min_mem_gib), "--secrets-dir", a.secrets_dir]
    argv += terms_driver_args(terms)
    if parent:
        argv += ["--tester-self", "--operator-domain-suffix", parent.get("public_name") or ""]
        if a.tester_fixture_secrets:
            argv += ["--tester-fixture-secrets", a.tester_fixture_secrets]
    if resume:
        argv += ["--resume-stack-dir", resume[0], "--resume-from", resume[1]]
    if a.dry_run:
        print(" ".join(argv)); log("dry run: nothing started"); return 0
    log(f"standup: {a.name} at {a.public_name} ({a.ticker}), stack root {a.stack_root}, images {a.images_prefix}/*:{a.version}")
    t0 = time.time()
    r = subprocess.run(argv, env=env)
    if r.returncode != 0:
        log(f"the standup driver exited {r.returncode} after {int(time.time() - t0)} s; read its log above (the last lines name the step). "
            f"A partial stack can be removed with frame-down.py --name {a.name}.")
        return r.returncode
    stacks = frame_names.stack_dirs(a.stack_root, a.name, need_file="hetzner-demo-run.json")
    if not stacks:
        log(f"the driver finished but no stack directory {a.name}-<ts> with a run record is under {a.stack_root}"); return 1
    stack_dir = os.path.join(a.stack_root, stacks[-1])
    if terms:
        terms = {**terms, "admin_email": a.admin_email, "recorded": terms_recorded(a.name, stack_dir, a.admin_email)}
        log(f"terms: {terms_line(terms)}")
    if a.legal_env:
        rc = apply_legal_env(a, stack_dir)
        if rc:
            return rc
    if runner.get("installed") or runner.get("via_parent"):
        # lane 6: the runner provisions operators only for frames it knows; a frame-up frame is ADOPTED (root, the full socket)
        ad = subprocess.run(adopt_argv(EXPORT_ROOT, a.name, stack_dir, runner.get("socket")), capture_output=True, text=True)
        if ad.returncode != 0:
            log(f"the frame runner did not adopt {a.name} (exit {ad.returncode}: {(ad.stderr or ad.stdout)[-300:].strip()}); the frame is up, "
                f"but Frame Management cannot provision operators for it until `frame_runner.py adopt --name {a.name} --stack-dir {stack_dir}` succeeds")
            return 1
        log(f"frame runner: adopted {a.name} ({(ad.stdout or '').strip()[:120]})")
        runner["adopted"] = True
    meta = json.load(open(os.path.join(stack_dir, "hetzner-demo-run.json")))
    ports = meta.get("ports") or {}
    if not ports.get("registry") or not ports.get("es"):
        log(f"the run record at {stack_dir} carries no registry/es ports; the edge cannot be rendered"); return 1
    if parent:
        return sandbox_edge_and_record(a, parent, stack_dir, ports, runner, t0, terms)
    # the edge; operators/ is where the runner writes one site block per cloud operator (Phase 2b), sandboxes/ where
    # frame-sandbox.py writes the sandboxes' (§TESTBED), both empty until then
    os.makedirs(os.path.join(stack_dir, "edge", "operators"), exist_ok=True)
    os.makedirs(os.path.join(stack_dir, "edge", "sandboxes"), exist_ok=True)
    try:
        admin_port = edge_admin_port(a.stack_root)
    except RuntimeError as e:
        log(f"the edge cannot be rendered: {e}"); return 1
    values = {"NAME": a.name, "STACK_DIR": stack_dir, "PUBLIC_NAME": a.public_name, "HTTP_PORT": a.edge_http_port, "ADMIN_PORT": admin_port,
              "HTTPS_PORT": a.edge_https_port, "PORT_REGISTRY": ports["registry"], "PORT_ES": ports["es"],
              "TLS_LINE": "tls internal" if a.edge_tls == "internal" else f"tls {a.acme_email}",
              "ACME_EMAIL_LINE": f"email {a.acme_email}" if a.edge_tls == "acme" else "# internal CA: no ACME account"}
    render(os.path.join(HERE, "frame-edge.Caddyfile.tmpl"), os.path.join(stack_dir, "edge", "Caddyfile"), values)
    render(os.path.join(HERE, "frame-edge.compose.yml.tmpl"), os.path.join(stack_dir, "edge", "docker-compose.edge.yml"), values)
    up = subprocess.run(["docker", "compose", "-p", f"{a.name}-edge", "-f", os.path.join(stack_dir, "edge", "docker-compose.edge.yml"), "up", "-d"],
                        capture_output=True, text=True)
    if up.returncode != 0:
        log(f"the edge did not start: {(up.stderr or up.stdout)[-400:]}"); return 1
    ctx = ssl.create_default_context()
    if a.edge_tls == "internal":
        ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
    status = None
    for _ in range(36):
        try:
            with urllib.request.urlopen(console_url(a) + "/health", timeout=10, context=ctx) as resp:
                status = resp.status; break
        except Exception:
            time.sleep(5)
    record = {"name": a.name, "public_name": a.public_name, "stack_dir": stack_dir, "secrets_dir": a.secrets_dir,
              "console": console_url(a), "federation_lane": f"https://{a.public_name}:{a.federation_port}",
              "bundle_endpoint": f"https://{a.public_name}:{a.bundle_port}/", "ledger_gateway": f"https://{a.public_name}:{a.ledger_port}",
              "edge": {"tls": a.edge_tls, "http_port": a.edge_http_port, "https_port": a.edge_https_port,
                       "container": f"{a.name}-edge", "operators_dir": os.path.join(stack_dir, "edge", "operators"),
                       "sandboxes_dir": os.path.join(stack_dir, "edge", "sandboxes"), "admin_port": admin_port,
                       "public_https_port": a.public_https_port or a.edge_https_port,
                       "reload": f"docker exec {a.name}-edge caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile"},
              "runner": {**runner, "instance": a.runner_instance},
              "images": f"{a.images_prefix}/*:{a.version}", "ports": ports, "edge_health": status, "seconds": int(time.time() - t0),
              "terms": terms}
    with open(os.path.join(stack_dir, "frame-up.json"), "w") as f:
        json.dump(record, f, indent=1)
    log(f"health through the edge: {status if status else 'no answer in 180 s (the certificate may still be pending; check `docker logs ' + a.name + '-edge`)'}")
    print("\nYour frame is up." if status == 200 else "\nYour frame started, but the edge did not answer yet.")
    print(f"  console            {record['console']}")
    print(f"  federation lane    {record['federation_lane']}   (mTLS, peers dial it)")
    print(f"  bundle endpoint    {record['bundle_endpoint']}   (peers fetch your SPIRE trust bundle)")
    print(f"  ledger gateway     {record['ledger_gateway']}   (mTLS, peers and your operators write to it)")
    print(f"  admin login        {a.admin_email}; the first password is in {a.secrets_dir} (mode 600, yours alone)")
    if terms_line(terms):
        print(f"  terms              {terms_line(terms)}")
    print(f"  stack directory    {stack_dir}")
    print("  firewall           open only the edge ports and the three lanes above; everything else stays on loopback")
    print(f"  next               ./frame-federate.py --stack-dir {stack_dir} --with https://<peer console> \\")
    print(f"                         --admin-secret-file {a.secrets_dir}/.{a.name}_frame_admin.secret.json   (join a peer; it waits for their")
    print(f"                     approve up to --timeout-min and exits 4 while the invitation is still pending: re-run it, it resumes)")
    print(f"                     ./frame-down.py --name {a.name}                                             (remove everything)")
    if status == 200 and not a.skip_reach:
        print()
        reach_check(a)
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
