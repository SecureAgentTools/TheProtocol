#!/usr/bin/env python3
"""frame-down: remove a frame this host runs, completely (§HELLOFRAME 2026-09-18).

    ./frame-down.py --name myframe [--stack-root /opt/theprotocol/stack] [--keep-secrets] [--with-sandbox] [--yes]

Brings the edge project and the frame's stack down with their volumes, removes the frame's cloud operators it finds
under the stack root (their SPIRE agent names this frame's trust domain) with their sites on the edge, removes the stack
directory and, unless --keep-secrets, the secrets directory. DNS records and the firewall are yours: it prints what it
did not touch. A frame with SANDBOXES (frame-up --sandbox-of, §TESTBED) is refused until they are gone; --with-sandbox
removes them first. A sandbox's own removal also takes its site off the parent's edge and its record out of the
parent's frame runner.
"""
import argparse
import glob
import importlib.util
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPORT_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_spec = importlib.util.spec_from_file_location("frame_names", os.path.join(EXPORT_ROOT, "scripts", "hetzner_demo", "frame_names.py"))
frame_names = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(frame_names)   # §TESTBED P0 a: exact ownership


def run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def frame_record(stack_root, name):
    """The newest frame-up.json of this frame (with its stack_dir), or {}."""
    for d in reversed(frame_names.stack_dirs(stack_root, name, need_file="frame-up.json")):
        try:
            with open(os.path.join(stack_root, d, "frame-up.json")) as f:
                rec = json.load(f) or {}
            rec["stack_dir"] = os.path.join(stack_root, d)
            return rec
        except (OSError, ValueError):
            continue
    return {}


def sandboxes_of(stack_root, name):
    """Every frame on this host whose frame-up.json says it is the sandbox of <name> (§TESTBED)."""
    out = set()
    for d in (os.listdir(stack_root) if os.path.isdir(stack_root) else []):
        p = os.path.join(stack_root, d, "frame-up.json")
        if os.path.isfile(p):
            try:
                with open(p) as f:
                    rec = json.load(f) or {}
            except (OSError, ValueError):
                continue
            if rec.get("sandbox_of") == name and rec.get("name") and rec.get("name") != name:
                out.add(rec["name"])
    return sorted(out)


def edge_reload(container):
    if not container:
        return "no edge container named"
    r = run(["docker", "exec", container, "caddy", "reload", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"], timeout=90)
    return "reloaded" if r.returncode == 0 else f"reload failed ({((r.stdout or '') + (r.stderr or '')).strip()[-160:]})"


def unadopt(rec, name):
    """Take the frame's record out of the runner that adopted it (the parent's, for a sandbox), once its registry is gone."""
    rn = rec.get("runner") or {}
    if not (rn.get("installed") or rn.get("via_parent") or rn.get("adopted")):
        return None
    cli = os.path.join(EXPORT_ROOT, "tools", "frame-runner", "frame_runner.py")
    argv = [sys.executable, cli, "unadopt", "--name", name] + (["--socket", rn["socket"]] if rn.get("socket") else [])
    r = run(argv, timeout=90)
    return (r.stdout or "").strip()[-200:] if r.returncode == 0 else f"not unadopted (exit {r.returncode}: {(r.stderr or r.stdout or '').strip()[-200:]})"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--stack-root", default=os.getenv("FRAME_STACK_ROOT", "/opt/theprotocol/stack"))
    ap.add_argument("--keep-secrets", action="store_true")
    ap.add_argument("--with-sandbox", action="store_true", help="also remove this frame's sandboxes (first)")
    ap.add_argument("--yes", action="store_true", help="do not ask")
    a = ap.parse_args()
    sbx = sandboxes_of(a.stack_root, a.name)
    if sbx and not a.with_sandbox:
        print(f"{a.name} has sandbox(es) {', '.join(sbx)}: remove them first (frame-down.py --name <sandbox>) or pass "
              f"--with-sandbox to remove them with it."); return 2
    if not a.yes and sys.stdin.isatty() and sbx:
        if input(f"remove {a.name} AND its sandbox(es) {', '.join(sbx)}, volumes included? [y/N] ").strip().lower() != "y":
            return 1
    worst = 0
    for s in sbx:
        print(f"== sandbox {s} of {a.name}")
        worst = max(worst, down(a, s, ask=False))
    print(f"== frame {a.name}") if sbx else None
    return max(worst, down(a, a.name, ask=not sbx))


def down(a, name, ask=True):
    rec = frame_record(a.stack_root, name)
    # exactly this frame's: its <name>-<ts> stack dirs and what carries its compose project labels (never a name prefix:
    # `--name a` must leave a frame named `a-b` alone, §TESTBED P0 a)
    stacks = frame_names.stack_dirs(a.stack_root, name)
    # §EXTTEST (beta.26): a standup that failed before rendering its compose leaves a <name>-<ts> dir without one, and its
    # secrets dir; both were invisible here ("nothing of a frame named ..."), and frame-up neither resumed nor removed them
    unfinished = [d for d in frame_names.stack_dirs(a.stack_root, name, need_file=None) if d not in stacks]
    has_secrets = os.path.isdir(os.path.join(a.stack_root, f"{name}-secrets")) and not a.keep_secrets
    res = frame_names.frame_resources(name, a.stack_root)
    containers = res["containers"]
    if not stacks and not unfinished and not has_secrets and not containers and not res["volumes"] and not res["networks"]:
        print(f"nothing of a frame named {name} on this host (no stack dir under {a.stack_root}, no secrets dir, no containers, volumes or networks)."); return 0
    print(f"frame {name}: stack dirs {stacks or 'none'}, unfinished stack dirs {unfinished or 'none'}, secrets dir "
          f"{'yes' if has_secrets else 'no'}, containers {len(containers)}, volumes {len(res['volumes'])}, networks {len(res['networks'])}")
    if ask and not a.yes and sys.stdin.isatty():
        if input("remove all of it, volumes included? [y/N] ").strip().lower() != "y":
            return 1
    td = None
    edge_changed = []
    for s in stacks:
        stack_dir = os.path.join(a.stack_root, s)
        try:
            td = json.load(open(os.path.join(stack_dir, "hetzner-demo-run.json"))).get("trust_domain")
        except (OSError, ValueError):
            pass
        edge = os.path.join(stack_dir, "edge", "docker-compose.edge.yml")
        if os.path.isfile(edge):
            r = run(["docker", "compose", "-p", f"{name}-edge", "-f", edge, "down", "-v", "--remove-orphans"])
            print(f"edge project down: rc={r.returncode}")
        env = os.path.join(stack_dir, ".env.frame-test")
        r = run(["docker", "compose", "-f", os.path.join(stack_dir, "docker-compose.frame-test.yml"), "--env-file", env,
                 "down", "-v", "--remove-orphans"] if os.path.isfile(env) else
                ["docker", "compose", "-f", os.path.join(stack_dir, "docker-compose.frame-test.yml"), "down", "-v", "--remove-orphans"], cwd=stack_dir)
        print(f"stack {s} down: rc={r.returncode}" + ("" if r.returncode == 0 else f" ({(r.stderr or '')[-200:]})"))
    # operators of this frame: their SPIRE agent conf names the frame's trust domain
    if td:
        for d in sorted(os.listdir(a.stack_root)):
            op = os.path.join(a.stack_root, d)
            conf = os.path.join(op, "spire", "agent.conf")
            if d.startswith("cloud-op-") and os.path.isfile(conf) and f'"{td}"' in open(conf).read():
                files = ["-f", "docker-compose.operator.yml"]
                # THE SAME FILE SET THE `up` READ (the frame runner's operator_teardown rule): every override the
                # provisioning one-shot copied into the stack declares its own services and volumes (db-TLS since V0391,
                # OPA's opa-certs and push's ntfy-cache since V0582), and `down -v` removes only the volumes of the files
                # it is given: naming the db-TLS file alone left the OPA's and the relay's volumes behind.
                for extra in sorted(glob.glob(os.path.join(op, "docker-compose.operator.*.yml"))):
                    files += ["-f", os.path.basename(extra)]
                r = run(["docker", "compose", "-p", d, *files, "--env-file", ".env.operator", "down", "-v", "--remove-orphans"], cwd=op)
                print(f"operator {d} down: rc={r.returncode}")
                shutil.rmtree(op, ignore_errors=True)
                # its site on the edge the runner wrote it into (a sandbox's operators live on the PARENT's edge)
                site = os.path.join(((rec.get("edge") or {}).get("operators_dir") or ""), f"{d[len('cloud-op-'):]}.caddy")
                if (rec.get("edge") or {}).get("operators_dir") and os.path.isfile(site):
                    os.remove(site); edge_changed.append(site)
    # whatever a failed up left behind: this frame's project labels, or (unlabelled) its name and no other frame's
    for n in frame_names.frame_resources(name, a.stack_root)["containers"]:
        run(["docker", "rm", "-f", n])
    left_now = frame_names.frame_resources(name, a.stack_root)
    for v in left_now["volumes"]:
        run(["docker", "volume", "rm", v])
    for n in left_now["networks"]:
        # a network this frame owns can still hold ANOTHER frame's container (frame-sandbox joins the first sandbox's
        # registry to the second's network for the federation suite; measured: larchsbxb_network outlived its frame
        # because larchsbx-registry was still attached when it was removed). It goes with the network.
        attached = run(["docker", "network", "inspect", n, "--format",
                        "{{range $id, $c := .Containers}}{{$c.Name}} {{end}}"]).stdout.split()
        for c in attached:
            run(["docker", "network", "disconnect", "-f", n, c])
            print(f"network {n}: disconnected {c} (another frame's container had joined it)")
        r = run(["docker", "network", "rm", n])
        if r.returncode != 0:
            print(f"network {n}: not removed ({(r.stderr or r.stdout).strip()[-160:]})")
    for s in stacks + unfinished:
        shutil.rmtree(os.path.join(a.stack_root, s), ignore_errors=True)
    for stray in (f"/etc/nginx/{name}-spire-bundle.pem",):   # written by standups before 2026-09-18 on an own host; removed with the frame
        if os.path.isfile(stray):
            os.remove(stray); print(f"removed {stray}")
    secrets = os.path.join(a.stack_root, f"{name}-secrets")
    if os.path.isdir(secrets) and not a.keep_secrets:
        shutil.rmtree(secrets, ignore_errors=True); print(f"secrets removed: {secrets}")
    # a sandbox's console is a site on its parent's edge (§TESTBED): take it off, with its operators' sites, and reload
    edge = rec.get("edge") or {}
    if rec.get("sandbox_of") and edge.get("site_file") and os.path.isfile(edge["site_file"]):
        os.remove(edge["site_file"]); edge_changed.append(edge["site_file"])
    if edge_changed and edge.get("via"):
        print(f"{rec['sandbox_of']}'s edge: removed {', '.join(os.path.basename(x) for x in edge_changed)}; {edge_reload(edge.get('container'))}")
    # the host firewall rules this frame's standup opened and recorded (frame-sandbox.py: a sandbox's lanes)
    specs = ((rec.get("firewall") or {}).get("ufw") or []) if isinstance(rec.get("firewall"), dict) else []
    if specs and shutil.which("ufw"):
        for spec in specs:
            run(["ufw", "delete", "allow", spec], timeout=60)
        print(f"firewall: removed the ufw rules {', '.join(specs)}")
    left = frame_names.frame_resources(name, a.stack_root)["containers"]
    if not left:
        note = unadopt(rec, name)
        if note:
            print(f"frame runner: {note}")
    print(f"done: containers left {len(left)}; not touched: your DNS record for the frame's name and your firewall rules.")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
