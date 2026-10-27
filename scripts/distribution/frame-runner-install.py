#!/usr/bin/env python3
"""frame-runner-install.py — put the frame runner on a host stood up from the export (§HELLOFRAME lane 6, 2026-09-18).

A frame on a stranger's host provisions its own cloud operators the way every runner-built frame does: its registry
holds no docker socket and asks the frame runner over a unix socket; the runner does the host work in a one-shot.
frame-up calls this script BEFORE it renders the frame, so the runner's socket group exists when the compose is
rendered (the registry joins that group to reach the socket) and so the policy names the edge the host really has.

What it does, in order, and nothing else:
  1. checks the export root carries what the runner needs (its own two files, its unit, the driver, the teardown and
     the compose template) — an incomplete export is refused before anything is written;
  2. creates the socket group when it is absent (the runner chowns its sockets to it at start and fails without it);
  3. writes the policy /etc/theprotocol/frame-runner.json (the previous one backed up beside it): the image allowlist
     from --images-prefix and --version, the posture, the edge, the domain, the gates and the mail relay; keys this
     script does not manage (a dns block, say) are carried over from the previous policy;
  4. writes the systemd unit from the export's OWN unit file, with ExecStart and every runner path pointing into the
     export root (the runner's defaults name /opt/theprotocol/stack/Agentvault2, which a stranger's host lacks);
  5. daemon-reload, enable --now (a restart when it already ran), waits for the operator socket and asks it
     operator_ping as uid 0: the answer must name the edge this policy wrote, or the install is not done.

The LAST LINE on stdout is the contract frame-up reads:
    FRAME_RUNNER_SOCKET_GID=<gid> SOCKET=<the full socket> OPERATOR_SOCKET=<the operator socket> \
    OPERATOR_SOCKET_DIR=<its directory, the one a frame's registry mounts at /run/theprotocol> EDGE=<edge>
Exit codes: 0 done · 2 usage, not root, or an incomplete export root · 3 a host step failed (group, a file, systemd)
· 4 the runner is installed but did not answer, or answered another edge than the policy names.
--dry-run prints the policy, the unit and the last line and touches nothing; --no-start writes everything and skips 5.
--instance <name> installs a SECOND runner beside a host's production one (the network's own host, where frame-up is
proven): unit theprotocol-frame-runner-<name>, policy /etc/theprotocol/frame-runner-<name>.json, sockets under
/run/theprotocol/<name>/, state /var/lib/theprotocol/frame-runner-<name>; the paths come from the runner's own
instance_paths(), so the two cannot disagree. Without it every path is the single runner's, byte-identical.
Standard library only: this runs on a host that has nothing of ours installed yet.
"""
import argparse
import datetime
import grp
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time

POLICY = "/etc/theprotocol/frame-runner.json"                       # the single runner's; an instance derives its own
PROTECTED = "/etc/theprotocol/protected-frames.list"                 # shared by every instance on a host, on purpose
UNIT_DIR = "/etc/systemd/system"
UNIT_PATH = f"{UNIT_DIR}/theprotocol-frame-runner.service"
UNIT_NAME = "theprotocol-frame-runner"
OPERATOR_SOCKET = "/run/theprotocol/operator/frame-runner.sock"
EDGES = ("nginx", "caddy")
POSTURES = ("production", "sandbox")
# the runner's policy keys and the image name each one allowlists, under the prefix the export loaded them with
IMAGE_KEYS = (("registry", "registry"), ("teg", "teg-layer"), ("event_store", "event-store"),
              ("auditor", "auditor"), ("directory", "directory"))
# what the runner needs from the export root, by the names its Config defaults use
EXPORT_FILES = ("tools/frame-runner/frame_runner.py", "tools/frame-runner/frame_dns.py",
                "tools/frame-runner/theprotocol-frame-runner.service", "scripts/hetzner_demo/standup_driver.py",
                "scripts/hetzner_demo/teardown_hetzner_frame.sh",
                "templates/frame-test/docker-compose.frame-test.yml.tmpl")
MANAGED_KEYS = ("_written_by", "_instance", "images", "posture", "wire_prod", "socket_group", "allowed_uids", "edge",
                "domain", "max_load", "min_mem_gib", "min_free_gb", "sandboxes")
EXIT_OK, EXIT_USAGE, EXIT_HOST, EXIT_RUNNER = 0, 2, 3, 4


class Refused(Exception):
    def __init__(self, code, why):
        super().__init__(why)
        self.code, self.why = code, why


# ---- pure ------------------------------------------------------------------------------------------------------

def parse_uids(text):
    """"0,1000" -> [0, 1000]; refuses anything that is not a non-negative integer (a uid list is a decision)."""
    out = []
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise Refused(EXIT_USAGE, f"--allowed-uids: {part!r} is not a uid")
        out.append(int(part))
    if not out:
        raise Refused(EXIT_USAGE, "--allowed-uids names no uid")
    return sorted(set(out))


def image_lists(prefix, version, overrides=None):
    """The runner's allowlist, one list per key. A key an override names takes that comma list verbatim; the rest
    are `<prefix>/<name>:<version>` when a version is given, else EMPTY (an empty registry list is a runner that
    offers Frame Management nothing to build with, which is right for a host that builds its frame with frame-up).
    Never :latest — a tag is a name, an allowlist entry is a decision (the runner's own example says so)."""
    overrides = overrides or {}
    prefix = str(prefix or "").strip().strip("/")
    out = {}
    for key, name in IMAGE_KEYS:
        raw = overrides.get(key)
        if raw:
            tags = [t.strip() for t in str(raw).split(",") if t.strip()]
        elif version:
            tags = [f"{prefix}/{name}:{version}" if prefix else f"{name}:{version}"]
        else:
            tags = []
        for t in tags:
            if t.endswith(":latest") or ":" not in t.rsplit("/", 1)[-1]:
                raise Refused(EXIT_USAGE, f"image {t!r} for {key}: an allowlist entry needs a tag and never :latest")
        out[key] = tags
    return out


def build_policy(a, existing=None):
    """The policy the runner reads at start. Managed keys come from the flags; every other key of an existing
    policy (a dns block, a plan timeout) is carried over unchanged; a mail block is written when --mail-server is
    given and otherwise carried over."""
    pol = {k: v for k, v in dict(existing or {}).items() if k not in MANAGED_KEYS}
    pol["_written_by"] = (f"frame-runner-install.py on {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
                          f"(export {a.export_root})")
    if getattr(a, "instance", ""):
        pol["_instance"] = a.instance
    pol["images"] = image_lists(a.images_prefix, a.version, {
        "registry": a.image_registry, "teg": a.image_teg, "event_store": a.image_event_store,
        "auditor": a.image_auditor, "directory": a.image_directory})
    pol["posture"] = a.posture
    pol["wire_prod"] = False                 # a stranger's host has none of the network's sidecars to wire into
    pol["socket_group"] = a.socket_group
    pol["allowed_uids"] = parse_uids(a.allowed_uids)
    pol["edge"] = a.edge
    pol["domain"] = a.domain
    pol["max_load"] = float(a.max_load)
    pol["min_mem_gib"] = float(a.min_mem_gib)
    pol["min_free_gb"] = float(a.min_free_gb)
    # §TESTBED: the frame's console may stand its own sandbox up through this runner (the MCP tester view's panel)
    pol["sandboxes"] = not getattr(a, "no_sandboxes", False)
    if a.mail_server:
        if not a.mail_address:
            raise Refused(EXIT_USAGE, "--mail-server needs --mail-address (the sender the relay accepts)")
        pol["mail"] = {"server": a.mail_server, "address": a.mail_address, "port": int(a.mail_port),
                       "token_file": a.mail_token_file}
    return pol


def render_unit(base, *, export_root, python, config=POLICY, stack_root, protected=PROTECTED, paths=None):
    """The export's own unit text with ExecStart and the runner's paths pointing INTO the export root. Every
    Environment=FRAME_RUNNER_* line of a previous render is dropped first, so a second install is idempotent.
    `paths` (an instance's, from the runner's instance_paths) scopes the unit: its Description, RuntimeDirectory,
    StateDirectory and the four FRAME_RUNNER_{INSTANCE,SOCKET,OPERATOR_SOCKET,STATE} lines; None = the single runner,
    whose unit is byte-identical to the render without this argument."""
    lines = [l for l in base.splitlines() if not l.startswith("Environment=FRAME_RUNNER_")]
    at = next((i for i, l in enumerate(lines) if l.startswith("ExecStart=")), None)
    if at is None:
        raise Refused(EXIT_USAGE, "the export's unit file has no ExecStart line; this is not the runner's unit")
    inst = (paths or {}).get("instance") or ""
    if inst:
        def _scoped(line):
            if line.startswith("Description="):
                return f"{line} [instance {inst}]"
            if line == "RuntimeDirectory=theprotocol":
                return f"RuntimeDirectory={paths['runtime_dir']}"
            if line == "StateDirectory=theprotocol/frame-runner":
                return f"StateDirectory={paths['state_dir']}"
            return line
        lines = [_scoped(l) for l in lines]
        for want in (f"RuntimeDirectory={paths['runtime_dir']}", f"StateDirectory={paths['state_dir']}"):
            if want not in lines:
                raise Refused(EXIT_USAGE, f"the export's unit file has no line to scope for {want}; this is not the "
                                          f"runner's unit as shipped")
        config = paths["config"]
    tools = os.path.join(export_root, "tools", "frame-runner")
    env = {}
    if inst:
        env.update({"FRAME_RUNNER_INSTANCE": inst, "FRAME_RUNNER_SOCKET": paths["socket"],
                    "FRAME_RUNNER_OPERATOR_SOCKET": paths["operator_socket"], "FRAME_RUNNER_STATE": paths["state"]})
    env.update({
        "FRAME_RUNNER_CONFIG": config,
        "FRAME_RUNNER_DRIVER": os.path.join(export_root, "scripts", "hetzner_demo", "standup_driver.py"),
        "FRAME_RUNNER_TEARDOWN": os.path.join(export_root, "scripts", "hetzner_demo", "teardown_hetzner_frame.sh"),
        "FRAME_RUNNER_TEMPLATE": os.path.join(export_root, "templates", "frame-test",
                                              "docker-compose.frame-test.yml.tmpl"),
        "FRAME_RUNNER_STACK_ROOT": stack_root,
        "FRAME_RUNNER_PROTECTED_LIST": protected,
        "FRAME_RUNNER_PYTHON": python,
    })
    lines[at] = f"ExecStart={python} -u {os.path.join(tools, 'frame_runner.py')} serve"
    lines[at + 1:at + 1] = [f"Environment={k}={v}" for k, v in env.items()]
    return "\n".join(lines) + "\n"


def check_export_root(root):
    """The files the runner's Config defaults name, relative to the export root; returns the missing ones."""
    return [rel for rel in EXPORT_FILES if not os.path.exists(os.path.join(root, rel))]


def last_line(gid, edge, *, socket="/run/theprotocol/frame-runner.sock", operator_socket=OPERATOR_SOCKET):
    """One line frame-up splits on spaces: the gid the frame's registry joins, the FULL socket (what `adopt --socket`
    takes), the operator socket and its DIRECTORY (what the frame's compose mounts at /run/theprotocol), the edge."""
    return (f"FRAME_RUNNER_SOCKET_GID={gid} SOCKET={socket} OPERATOR_SOCKET={operator_socket} "
            f"OPERATOR_SOCKET_DIR={os.path.dirname(operator_socket)} EDGE={edge}")


# ---- the host --------------------------------------------------------------------------------------------------

def say(msg):
    print(f"[frame-runner-install] {msg}", flush=True)


def ensure_group(name, dry):
    try:
        return grp.getgrnam(name).gr_gid
    except KeyError:
        pass
    if dry:
        say(f"would create the system group {name}")
        return -1
    r = subprocess.run(["groupadd", "--system", name], capture_output=True, text=True)
    if r.returncode != 0:
        raise Refused(EXIT_HOST, f"groupadd {name} failed: {(r.stderr or r.stdout).strip()[-300:]}")
    say(f"created the system group {name}")
    return grp.getgrnam(name).gr_gid


def write_file(path, text, mode, dry, *, label):
    """Write when the content differs, backing the previous file up beside it first; say what happened."""
    current = None
    if os.path.exists(path):
        with open(path) as f:
            current = f.read()
    if current == text:
        say(f"{label}: {path} already has this content")
        return False
    if dry:
        say(f"would write {label} to {path}" + (" (backing the current one up)" if current is not None else ""))
        return True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if current is not None:
        bak = f"{path}.bak-pre-install-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
        shutil.copy2(path, bak)
        say(f"{label}: backed the previous {path} up to {bak}")
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode), "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    say(f"{label}: wrote {path} ({mode:o})")
    return True


def systemctl(*args):
    r = subprocess.run(["systemctl", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise Refused(EXIT_HOST, f"systemctl {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[-300:]}")
    return (r.stdout or "").strip()


def wait_for(path, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.5)
    return os.path.exists(path)


_RUNNER = {}


def runner_module(export_root):
    """The runner's own module, loaded from the export root: ONE definition of the instance paths and of the wire
    format, no second copy here to rot. Loaded once."""
    if "mod" not in _RUNNER:
        tools = os.path.join(export_root, "tools", "frame-runner")
        if tools not in sys.path:
            sys.path.insert(0, tools)
        spec = importlib.util.spec_from_file_location("frame_runner", os.path.join(tools, "frame_runner.py"))
        fr = importlib.util.module_from_spec(spec)
        sys.modules["frame_runner"] = fr
        try:
            spec.loader.exec_module(fr)
        except Exception as exc:  # noqa: BLE001 — the export's runner does not load: nothing to install
            raise Refused(EXIT_USAGE, f"the export's tools/frame-runner/frame_runner.py cannot be loaded "
                                      f"({type(exc).__name__}: {exc}); this export is not one this installer serves")
        _RUNNER["mod"] = fr
    return _RUNNER["mod"]


def runner_paths(export_root, instance):
    """The paths this install owns, from the runner's own rule; `instance` "" = the single runner."""
    fr = runner_module(export_root)
    if not hasattr(fr, "instance_paths"):
        if instance:
            raise Refused(EXIT_USAGE, "the export's runner predates instances (no instance_paths); drop --instance")
        p = {"unit": UNIT_NAME, "config": POLICY, "socket": "/run/theprotocol/frame-runner.sock",
             "operator_socket": OPERATOR_SOCKET, "state": "/var/lib/theprotocol/frame-runner",
             "runtime_dir": "theprotocol", "state_dir": "theprotocol/frame-runner"}
    else:
        try:
            p = dict(fr.instance_paths(instance))
        except ValueError as exc:
            raise Refused(EXIT_USAGE, str(exc))
    p["instance"] = instance
    p["unit_path"] = os.path.join(UNIT_DIR, f"{p['unit']}.service")
    return p


def operator_ping(export_root, socket_path, timeout=20):
    """Ask the runner's operator socket with the runner's OWN client, loaded from the export root."""
    return runner_module(export_root).call(socket_path, {"op": "operator_ping"}, timeout)


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--export-root", required=True, help="the unpacked export (holds tools/, scripts/, templates/)")
    ap.add_argument("--stack-root", required=True, help="where frames and their operators live (frame-up's --stack-root)")
    ap.add_argument("--posture", choices=POSTURES, default="production")
    ap.add_argument("--images-prefix", default="agentvault2", help="the tag namespace the export loaded the images under")
    ap.add_argument("--version", default="", help="the images' tag; empty = no allowlist entries derived")
    for key, _ in IMAGE_KEYS:
        ap.add_argument(f"--image-{key.replace('_', '-')}", default="", dest=f"image_{key}",
                        help=f"explicit comma list for images.{key} (overrides the prefix/version form)")
    ap.add_argument("--socket-group", default="deploy")
    ap.add_argument("--allowed-uids", default="0,1000")
    ap.add_argument("--edge", choices=EDGES, default="nginx")
    ap.add_argument("--domain", default="", help="the frame's public name (the runner's `domain`)")
    ap.add_argument("--max-load", default="40")
    ap.add_argument("--min-mem-gib", default="15")
    ap.add_argument("--min-free-gb", default="60")
    ap.add_argument("--mail-server", default="")
    ap.add_argument("--mail-address", default="")
    ap.add_argument("--mail-port", default="587")
    ap.add_argument("--mail-token-file", default="/root/.noreply_smtp_token")
    ap.add_argument("--python", default="/usr/bin/python3")
    ap.add_argument("--socket-timeout", default="30", help="seconds to wait for the operator socket after start")
    ap.add_argument("--instance", default="", help="a SECOND runner beside this host's own, scoped by this name "
                                                   "(unit, policy, sockets, state); empty = the single runner")
    ap.add_argument("--no-sandboxes", action="store_true",
                    help="do not let the frame's console stand sandboxes up through this runner (on by default: §TESTBED)")
    ap.add_argument("--dry-run", action="store_true", help="print the policy, the unit and the last line; touch nothing")
    ap.add_argument("--no-start", action="store_true", help="write everything, skip systemd and the ping")
    return ap


def run(a):
    a.export_root = os.path.realpath(a.export_root)
    a.stack_root = os.path.realpath(a.stack_root)
    missing = check_export_root(a.export_root)
    if missing:
        raise Refused(EXIT_USAGE, f"the export root {a.export_root} lacks {missing}; nothing was written")
    if not a.dry_run and os.geteuid() != 0:
        raise Refused(EXIT_USAGE, "run this as root: it writes /etc and talks to systemd")
    paths = runner_paths(a.export_root, a.instance.strip())
    existing = {}
    if os.path.exists(paths["config"]):
        try:
            with open(paths["config"]) as f:
                existing = json.load(f) or {}
        except (OSError, ValueError) as exc:
            raise Refused(EXIT_HOST, f"{paths['config']} exists and could not be read ({exc}); fix or move it first")
    policy = build_policy(a, existing)
    with open(os.path.join(a.export_root, "tools", "frame-runner", "theprotocol-frame-runner.service")) as f:
        unit = render_unit(f.read(), export_root=a.export_root, python=a.python, stack_root=a.stack_root,
                           config=paths["config"], paths=paths if paths["instance"] else None)
    contract = dict(socket=paths["socket"], operator_socket=paths["operator_socket"])

    gid = ensure_group(a.socket_group, a.dry_run)
    if paths["instance"]:
        say(f"instance {paths['instance']}: unit {paths['unit']}, policy {paths['config']}, sockets under "
            f"{os.path.dirname(paths['socket'])}/, state {paths['state']}")
    if a.dry_run:
        say(f"dry run: the policy that would be written to {paths['config']}")
        print(json.dumps(policy, indent=2))
        say(f"dry run: the unit that would be written to {paths['unit_path']}")
        print(unit, end="")
        print(last_line(gid, a.edge, **contract))
        return EXIT_OK

    os.makedirs(os.path.dirname(paths["config"]), exist_ok=True)
    write_file(paths["config"], json.dumps(policy, indent=2) + "\n", 0o640, False, label="policy")
    if not os.path.exists(PROTECTED):
        write_file(PROTECTED, "# frames the runner refuses to tear down, one name per line\n", 0o644, False,
                   label="protected list")
    changed = write_file(paths["unit_path"], unit, 0o644, False, label="unit")
    unit_name = paths["unit"]
    if a.no_start:
        say("--no-start: the unit is written and not started")
        print(last_line(gid, a.edge, **contract))
        return EXIT_OK

    systemctl("daemon-reload")
    active = subprocess.run(["systemctl", "is-active", "--quiet", unit_name]).returncode == 0
    if active and changed:
        systemctl("restart", unit_name)
        say(f"restarted {unit_name} (the unit changed)")
    elif active:
        say(f"{unit_name} is running; the runner re-reads its policy at its next start")
    else:
        systemctl("enable", "--now", unit_name)
        say(f"enabled and started {unit_name}")
    op_sock = paths["operator_socket"]
    if not wait_for(op_sock, float(a.socket_timeout)):
        raise Refused(EXIT_RUNNER, f"{op_sock} did not appear within {a.socket_timeout}s; "
                                   f"journalctl -u {unit_name} says why")
    # §TESTBED (2026-09-19): a RE-install restarts a running runner, and the old socket FILE stays on disk until the new
    # process re-binds it: the first ping met ConnectionRefusedError in the same second as the restart and the whole
    # frame-up refused (measured, larch). A refused or vanished socket inside the timeout is a runner still starting.
    deadline = time.time() + float(a.socket_timeout)
    while True:
        try:
            answer = operator_ping(a.export_root, op_sock)
            break
        except (ConnectionRefusedError, FileNotFoundError) as exc:
            if time.time() >= deadline:
                raise Refused(EXIT_RUNNER, f"operator_ping on {op_sock} failed for {a.socket_timeout}s: {type(exc).__name__}: {exc}")
            time.sleep(0.5)
        except Exception as exc:  # noqa: BLE001 — the socket exists and refused or hung: not installed until it answers
            raise Refused(EXIT_RUNNER, f"operator_ping on {op_sock} failed: {type(exc).__name__}: {exc}")
    result = answer.get("result") if isinstance(answer, dict) else None
    if not isinstance(answer, dict) or answer.get("ok") is not True or not isinstance(result, dict):
        raise Refused(EXIT_RUNNER, f"operator_ping was refused: {json.dumps(answer)[:300]}")
    if result.get("edge") != a.edge:
        raise Refused(EXIT_RUNNER, f"the running runner answers edge={result.get('edge')!r}, the policy says "
                                   f"{a.edge!r}: an older runner is serving, restart it")
    say(f"the runner answers operator_ping: version {result.get('version')}, edge {result.get('edge')}, "
        f"ops {result.get('ops')}")
    print(last_line(gid, a.edge, **contract))
    return EXIT_OK


def main(argv=None):
    a = build_parser().parse_args(argv)
    try:
        return run(a)
    except Refused as exc:
        say(f"REFUSED ({exc.code}): {exc.why}")
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
