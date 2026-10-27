"""frame_names: which stack directories, containers, volumes and networks belong to a frame, decided EXACTLY
(§TESTBED P0 a, 2026-09-19).

A frame named <name> is the compose projects its standup created: the stack directory <stack-root>/<name>-<unix ts>
(compose names the project after it) and the edge project <name>-edge. Every container, volume and network compose
creates carries the label com.docker.compose.project, so ownership is that label, never a name prefix. Before this,
`frame-down --name a` also removed a frame named `a-b`: its stack directory, containers (`a-b-*`), volumes and networks
(`a_b_*`) all start with the prefixes the teardown matched. A resource WITHOUT the label (something a failed standup
left) is this frame's only when its name carries the frame's prefix AND no other frame on the host claims a longer
prefix of it.

Loaded by path (like frame_ports.py) by the standup driver and by the kit's frame-up, frame-down and frame-doctor.
"""
import os
import re
import subprocess

LABEL = "com.docker.compose.project"
_PROJECT_RE = re.compile(r"(.+)-(?:\d+|edge)")


def stack_re(name):
    return re.compile(re.escape(name) + r"-\d+")


def is_stack_dir_name(d, name):
    """True for <name>-<digits> only: `a-1789` is frame a's, `a-b-1789` and `ab-1789` are not."""
    return bool(stack_re(name).fullmatch(d or ""))


def stack_dirs(stack_root, name, need_file="docker-compose.frame-test.yml"):
    """The frame's stack directory basenames under the root (each holding need_file when one is named), oldest first."""
    if not stack_root or not os.path.isdir(stack_root):
        return []
    out = []
    for d in os.listdir(stack_root):
        p = os.path.join(stack_root, d)
        if is_stack_dir_name(d, name) and os.path.isdir(p) and (not need_file or os.path.isfile(os.path.join(p, need_file))):
            out.append(d)
    return sorted(out, key=lambda d: int(d.rsplit("-", 1)[1]))


def owns_project(project, name):
    """True when a compose project label is this frame's: its stack project <name>-<digits> or its edge <name>-edge."""
    return bool(project) and (project == f"{name}-edge" or is_stack_dir_name(project, name))


def frame_of_project(project):
    """The frame a project label names (<frame>-<digits> or <frame>-edge), or None for any other project."""
    m = _PROJECT_RE.fullmatch(project or "")
    return m.group(1) if m else None


def _prefix(name, sep):
    return (name if sep == "-" else name.replace("-", "_")) + sep


def claims(obj_name, name, others, sep):
    """An UNLABELLED resource is <name>'s when its name starts with the frame's prefix (`<name>-` for containers,
    `<name_>_` for volumes and networks) and no other frame's longer prefix also matches it."""
    mine = _prefix(name, sep)
    if not (obj_name or "").startswith(mine):
        return False
    for o in others:
        theirs = _prefix(o, sep)
        if len(theirs) > len(mine) and obj_name.startswith(theirs):
            return False
    return True


def other_frames(name, inventory, stack_root=None):
    """Every other frame this host knows of: named by a project label on any resource, or by a stack directory."""
    found = set()
    for rows in (inventory or {}).values():
        for _obj, lab in rows:
            f = frame_of_project(lab)
            if f and f != name:
                found.add(f)
    if stack_root and os.path.isdir(stack_root):
        for d in os.listdir(stack_root):
            m = re.fullmatch(r"(.+)-\d+", d)
            if m and m.group(1) != name and os.path.isfile(os.path.join(stack_root, d, "docker-compose.frame-test.yml")):
                found.add(m.group(1))
    return found


def select(inventory, name, stack_root=None):
    """Pure over an inventory {containers|volumes|networks: [(name, project label)]}: the frame's resources by kind,
    plus the project labels that carried them."""
    others = other_frames(name, inventory, stack_root)
    out = {"projects": set()}
    for kind, sep in (("containers", "-"), ("volumes", "_"), ("networks", "_")):
        picked = []
        for obj, lab in (inventory or {}).get(kind, []):
            if lab:
                if owns_project(lab, name):
                    picked.append(obj)
                    out["projects"].add(lab)
            elif claims(obj, name, others, sep):
                picked.append(obj)
        out[kind] = sorted(picked)
    return out


def _rows(argv, timeout=120):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"`{' '.join(argv[:3])}` failed: {(r.stderr or r.stdout or '').strip()[-200:]}")
    rows = []
    for line in (r.stdout or "").splitlines():
        obj, _, lab = line.partition("\t")
        if obj.strip():
            rows.append((obj.strip(), lab.strip()))
    return rows


def host_inventory(kinds=("containers", "volumes", "networks")):
    """Every container (running or not), volume and network on this host with its compose project label (only the
    kinds asked: a preflight that refuses on containers reads no volumes)."""
    lab = '{{.Label "' + LABEL + '"}}'
    argv = {"containers": ["docker", "ps", "-a", "--format", "{{.Names}}\t" + lab],
            "volumes": ["docker", "volume", "ls", "--format", "{{.Name}}\t" + lab],
            "networks": ["docker", "network", "ls", "--format", "{{.Name}}\t" + lab]}
    return {k: _rows(argv[k]) for k in kinds}


def frame_resources(name, stack_root=None, inventory=None, kinds=("containers", "volumes", "networks")):
    """select() over this host's live inventory (or the one given)."""
    return select(host_inventory(kinds) if inventory is None else inventory, name, stack_root)
