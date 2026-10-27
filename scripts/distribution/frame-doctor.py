#!/usr/bin/env python3
"""frame-doctor: is this host ready to run a federated TheProtocol frame? (§HELLOFRAME 2026-09-18)

Every check answers with one sentence a person can act on. Nothing is written. Exit 0 = ready, 1 = not ready,
2 = usage. `frame-up` runs the same checks before it touches anything.

    ./frame-doctor.py --public-name frame.example.org [--stack-root /opt/theprotocol/stack]
                      [--images-prefix theprotocol] [--version 1.0.0-beta.4]
                      [--federation-port 8443] [--bundle-port 8444] [--ledger-port 8445]
                      [--edge-https-port 443] [--edge-http-port 80] [--min-mem-gib 8] [--min-disk-gb 20]
"""
import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
IMAGES = ("registry", "teg-layer", "event-store", "auditor", "directory", "cert-writer")
PUBLIC_IMAGES = ("docker:cli", "alpine/openssl:latest", "ghcr.io/spiffe/spire-server:1.15.3",
                 "ghcr.io/spiffe/spire-agent:1.15.3", "nginx:1.30.5-alpine")


def run(argv, timeout=60):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", f"{argv[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{argv[0]}: timed out"


def version_of(path):
    try:
        return open(path).read().strip()
    except OSError:
        return "dev"


def host_ipv4s():
    rc, out, _ = run(["ip", "-4", "-o", "addr"])
    ips = set()
    for line in out.splitlines():
        parts = line.split()
        if "inet" in parts:
            ips.add(parts[parts.index("inet") + 1].split("/")[0])
    return ips


def resolve_public(name):
    """The A record as PUBLIC resolvers see it: the union of what 1.1.1.1 and 8.8.8.8 answer (dig, when it exists; a
    record created minutes ago can be missing at one anycast node and present at the other), else this host's resolver."""
    if shutil.which("dig"):
        found = []
        for resolver in ("1.1.1.1", "8.8.8.8"):
            rc, out, _ = run(["dig", "+short", f"@{resolver}", "A", name], timeout=20)
            found += [l.strip() for l in out.splitlines() if l.strip() and l.strip()[0].isdigit()]
        return sorted(set(found))
    try:
        return sorted({ai[4][0] for ai in socket.getaddrinfo(name, None, socket.AF_INET)})
    except socket.gaierror:
        return []


def _owned(cname, project, name):
    """A container is the frame's by its compose project label (<name>-<ts> or <name>-edge) when it carries one, else by
    its name (§TESTBED P0 a: `hello` must not count the ports of a frame named `hello-b`)."""
    if project:
        return project == f"{name}-edge" or bool(re.fullmatch(re.escape(name) + r"-\d+", project))
    return cname.startswith(f"{name}-")


def held_ports_from_docker_ps(text, name, edge_ports=()):
    """Host ports bound by the frame's containers in `docker ps --format '{{.Names}}\t{{.Ports}}\t<project label>'` output
    (the third column optional), plus the edge ports when <name>-edge runs (host network mode publishes nothing docker can
    list). Pure: parses the text it is given."""
    held = set()
    for line in (text or "").splitlines():
        cols = line.split("\t")
        cname, ports = cols[0], (cols[1] if len(cols) > 1 else "")
        project = cols[2].strip() if len(cols) > 2 else ""
        if not _owned(cname, project, name):
            continue
        if cname == f"{name}-edge":
            held.update(int(p) for p in edge_ports)
        for m in re.finditer(r":(\d+)->\d+/(?:tcp|udp)", ports):
            held.add(int(m.group(1)))
    return held


def ports_held_by(name, edge_ports=()):
    if not name:
        return set()
    try:
        out = subprocess.run(["docker", "ps", "--format", '{{.Names}}\t{{.Ports}}\t{{.Label "com.docker.compose.project"}}'],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:  # noqa: BLE001
        return set()
    return held_ports_from_docker_ps(out, name, edge_ports)


COMPOSE_MIN = (2, 24)


def compose_version_problem(short):
    """None when `docker compose version --short` names 2.24 or newer, else the sentence to act on. CB-076: only the
    major was compared, so 2.20 passed a check whose own message asks for 2.24 (and a leading "v" raised)."""
    m = re.match(r"v?(\d+)\.(\d+)", (short or "").strip())
    if not m:
        return f"`docker compose version --short` printed {short!r}, not a version: 2.24 or newer is needed."
    if (int(m.group(1)), int(m.group(2))) < COMPOSE_MIN:
        return f"docker compose {short.strip()} is too old; 2.24 or newer is needed."
    return None


def port_free(port):
    rc, out, _ = run(["ss", "-Hltn"])
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[3].rsplit(":", 1)[-1] == str(port):
            return False
    return True


def checks(a):
    problems, notes = [], []
    # the tools
    for tool, hint in (("docker", "install Docker Engine (https://docs.docker.com/engine/install/)"),
                       ("ss", "install iproute2"), ("ip", "install iproute2"), ("openssl", "install openssl")):
        if not shutil.which(tool):
            problems.append(f"`{tool}` is not on PATH: {hint}.")
    if sys.version_info < (3, 10):
        problems.append(f"python3 is {sys.version.split()[0]}; the frame driver needs 3.10 or newer.")
    rc, out, err = run(["docker", "version", "--format", "{{.Server.Version}}"])
    if rc != 0:
        problems.append(f"the Docker daemon does not answer ({err.splitlines()[-1] if err else 'no detail'}): start it, and run this as a user who may use it.")
    rc, out, err = run(["docker", "compose", "version", "--short"])
    if rc != 0:
        problems.append("`docker compose` (the v2 plugin) is missing: install docker-compose-plugin.")
    elif compose_version_problem(out):
        problems.append(compose_version_problem(out))
    # the export tree
    for rel in ("scripts/hetzner_demo/standup_driver.py", "templates/frame-test/docker-compose.frame-test.yml.tmpl",
                "templates/frame-test/frame-test.env.tmpl", "templates/frame-test/kit",
                "AgentVault/agentvault_registry/src/agentvault_registry/services/frame_test_provisioner.py",
                "nginx/nginx-entrypoint.sh", "scripts/distribution/nginx-templates"):
        if not os.path.exists(os.path.join(EXPORT_ROOT, rel)):
            problems.append(f"the export is incomplete: {rel} is missing under {EXPORT_ROOT}.")
    # the images build.sh made, and the public ones the standup pulls
    for name in IMAGES:
        ref = f"{a.images_prefix}/{name}:{a.version}"
        if run(["docker", "image", "inspect", ref])[0] != 0:
            problems.append(f"image {ref} is not on this host: run `./build.sh` in scripts/distribution first (or name --images-prefix/--version).")
    missing_public = [ref for ref in PUBLIC_IMAGES if run(["docker", "image", "inspect", ref])[0] != 0]
    if missing_public:
        notes.append(f"{len(missing_public)} public image(s) will be pulled at standup ({', '.join(missing_public)}): the host needs Docker Hub and ghcr.io.")
    # the host
    try:
        mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo") if l.startswith(("MemAvailable", "MemTotal"))}
        avail_gib = mem.get("MemAvailable", 0) / 1048576
        if avail_gib < a.min_mem_gib:
            problems.append(f"MemAvailable is {avail_gib:.1f} GiB; a frame (32 containers) needs at least {a.min_mem_gib} GiB free.")
    except OSError:
        notes.append("memory could not be read (/proc/meminfo).")
    root = a.stack_root if os.path.isdir(a.stack_root) else os.path.dirname(a.stack_root.rstrip("/")) or "/"
    free_gb = shutil.disk_usage(root).free // (1024 ** 3)
    if free_gb < a.min_disk_gb:
        problems.append(f"{free_gb} GB free under {root}; a frame needs at least {a.min_disk_gb} GB (images, eight volumes, a ledger).")
    if os.path.isdir(a.stack_root) and not os.access(a.stack_root, os.W_OK):
        problems.append(f"{a.stack_root} is not writable by this user.")
    if os.geteuid() != 0:
        notes.append("not running as root: the standup needs to write the stack directory and talk to the Docker socket.")
    # the ports. A SANDBOX (frame-up --sandbox-of) has no edge of its own: its console is a site on the parent's edge,
    # so the two edge ports are the parent's and busy by design; only its three machine lanes must be free (§TESTBED)
    via = getattr(a, "edge_via", None)
    held = ports_held_by(getattr(a, "name", None), (a.edge_https_port, a.edge_http_port))
    lanes = (("federation lane", a.federation_port), ("SPIRE bundle endpoint", a.bundle_port), ("ledger gateway", a.ledger_port))
    edges = () if via else (("edge https", a.edge_https_port), ("edge http", a.edge_http_port))
    if via:
        notes.append(f"the console is a site on {via}'s edge (ports {a.edge_https_port}/{a.edge_http_port}); only the three lanes are checked.")
    for label, port in edges + lanes:
        if not port_free(port):
            if port in held:
                notes.append(f"port {port} ({label}) is held by an interrupted standup of {a.name}: frame-up resumes it (frame-down first for a fresh one).")
            else:
                problems.append(f"port {port} ({label}) is already listening on this host: free it or choose another with the matching option.")
    if len({a.edge_https_port, a.edge_http_port, a.federation_port, a.bundle_port, a.ledger_port}) != 5:
        problems.append("the five public ports must be distinct.")
    # the name
    ips = host_ipv4s()
    answers = resolve_public(a.public_name)
    # With --edge-tls internal (a test frame, Caddy's own CA) nothing needs the public name to resolve yet: no ACME
    # order, no peer dialing it by name. The name still has to resolve before frame-federate.py, so it is a NOTE
    # here, not a refusal (measured 2026-09-20: a legal-env proof frame on 127.0.0.1 refused on the A record alone).
    dns_is_note = getattr(a, "edge_tls", "acme") == "internal"
    sink = notes if dns_is_note else problems
    if not answers:
        sink.append(f"{a.public_name} has no A record at a public resolver" + (
            " (internal TLS: not needed for this frame until it federates)." if dns_is_note else
            ": create one pointing at this host, then wait for it to propagate."))
    elif not (set(answers) & ips):
        sink.append(f"{a.public_name} resolves to {', '.join(answers)}, which is not an address of this host ({', '.join(sorted(ips)) or 'none found'}); "
                    + ("with internal TLS this only matters once the frame federates." if dns_is_note else
                       "point the A record here (a host behind NAT needs the public address forwarded to it)."))
    if a.edge_tls == "acme" and (a.edge_http_port != 80 or a.edge_https_port != 443):
        notes.append("ACME (Let's Encrypt) needs ports 80 and 443 on the public address; with other ports use --edge-tls internal (a private CA, for tests).")
    return problems, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--public-name", required=True, help="the frame's public DNS name (also its trust domain)")
    ap.add_argument("--name", default=None, help="the frame's short name: a port its own containers hold (an interrupted standup) is a note, not a refusal")
    ap.add_argument("--stack-root", default=os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack"))
    ap.add_argument("--images-prefix", default=os.getenv("IMAGE_REGISTRY", "theprotocol"))
    ap.add_argument("--version", default=version_of(os.path.join(HERE, "VERSION")))
    ap.add_argument("--federation-port", type=int, default=8443)
    ap.add_argument("--bundle-port", type=int, default=8444)
    ap.add_argument("--ledger-port", type=int, default=8445)
    ap.add_argument("--edge-https-port", type=int, default=443)
    ap.add_argument("--edge-http-port", type=int, default=80)
    ap.add_argument("--edge-tls", choices=["acme", "internal"], default="acme")
    ap.add_argument("--min-mem-gib", type=float, default=8)
    ap.add_argument("--min-disk-gb", type=int, default=20)
    ap.add_argument("--json", action="store_true", help="machine-readable result")
    a = ap.parse_args()
    problems, notes = checks(a)
    if a.json:
        print(json.dumps({"ready": not problems, "problems": problems, "notes": notes, "export_root": EXPORT_ROOT}, indent=1))
    else:
        for p in problems:
            print(f"NOT READY: {p}")
        for n in notes:
            print(f"note: {n}")
        print("READY: this host can run a frame (checked: docker and the compose plugin, python, the export's files and the six images, "
              "memory and disk, the stack root, the five public ports and the DNS name)." if not problems else f"{len(problems)} thing(s) to fix before frame-up.")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
