"""§FRAMEPROV P1 (2026-09-13): a frame's host ports (seven, nine since §SOVKIT), free on THIS host and claimed by no other stack.

Why it exists: the driver's ports came from FRAME_TEST_PORT_* with fixed defaults (standup_driver.py `PORTS`), so two
frames stood up without hand-picked ports collide, and the admin UI's runner has no human to pick them.

A port is TAKEN when any of these holds it:
  * a listening TCP socket on the host (`ss -Hltn`);
  * a host binding of ANY container, running or stopped (`docker inspect` HostConfig.PortBindings): a stopped frame
    takes its ports back the moment it starts;
  * a port recorded in any stack dir's run meta (`hetzner-demo-run.json`: "ports" and "port_push").

The layout mirrors the proof pair (juice: registry 8750, es 8761, teg 8762, spire bundle 8765, spire grpc 8791, ntfy
8799, federation 30763): one base, fixed offsets, the federation port in the 30xxx band. Read-only.
"""
import glob
import json
import os
import re
import subprocess
from typing import Dict, Iterable, Set

# §SOVKIT (2026-09-14): the kit adds two loopback doors, grafana and the solo auditor (opa, prometheus, alertmanager
# and the directory publish nothing on the host).
OFFSETS = {"registry": 0, "es": 11, "teg": 12, "spire_bundle": 15, "spire_grpc": 41, "push": 49, "grafana": 51, "auditor": 52}
FED_BAND = 30000
ENV_NAMES = {"registry": "FRAME_TEST_PORT_REGISTRY", "teg": "FRAME_TEST_PORT_TEG", "es": "FRAME_TEST_PORT_EVENTSTORE",
             "spire_grpc": "FRAME_TEST_PORT_SPIRE_GRPC", "spire_bundle": "FRAME_TEST_PORT_SPIRE_BUNDLE",
             "nginx_fed": "FRAME_TEST_PORT_NGINX_FED", "push": "FRAME_TEST_PORT_NTFY",
             "grafana": "FRAME_TEST_PORT_GRAFANA", "auditor": "FRAME_TEST_PORT_AUDITOR"}
BASES = tuple(range(8500, 9900, 100))
STACK_ROOT = "/opt/theprotocol/stack"


class NoFreePorts(RuntimeError):
    """No base in the range has all nine ports free."""


def layout(base: int) -> Dict[str, int]:
    ports = {key: base + off for key, off in OFFSETS.items()}
    ports["nginx_fed"] = FED_BAND + (base - 8000) + 13
    return ports


def host_listeners() -> Set[int]:
    out = subprocess.run(["ss", "-Hltn"], capture_output=True, text=True).stdout
    taken: Set[int] = set()
    for line in out.splitlines():
        fields = line.split()
        if len(fields) >= 4:
            m = re.search(r":(\d+)$", fields[3])
            if m:
                taken.add(int(m.group(1)))
    return taken


def container_bindings() -> Set[int]:
    ids = subprocess.run(["docker", "ps", "-aq"], capture_output=True, text=True).stdout.split()
    taken: Set[int] = set()
    if not ids:
        return taken
    out = subprocess.run(["docker", "inspect", "--format", "{{json .HostConfig.PortBindings}}", *ids],
                         capture_output=True, text=True).stdout
    for line in out.splitlines():
        try:
            bindings = json.loads(line) or {}
        except ValueError:
            continue
        for hosts in bindings.values():
            for h in hosts or []:
                port = str((h or {}).get("HostPort") or "")
                if port.isdigit():
                    taken.add(int(port))
    return taken


def recorded_stack_ports(stack_root: str = STACK_ROOT) -> Set[int]:
    taken: Set[int] = set()
    for meta_path in glob.glob(os.path.join(stack_root, "*", "hetzner-demo-run.json")):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (OSError, ValueError):
            continue
        values = list((meta.get("ports") or {}).values()) + [meta.get("port_push"), meta.get("port_grafana"), meta.get("port_auditor")]
        taken.update(v for v in values if isinstance(v, int))
    return taken


def taken_ports(stack_root: str = STACK_ROOT) -> Set[int]:
    return host_listeners() | container_bindings() | recorded_stack_ports(stack_root)


def allocate(taken: Iterable[int], bases: Iterable[int] = BASES) -> Dict[str, int]:
    taken = set(taken)
    bases = list(bases)
    if not bases:
        raise NoFreePorts("no port bases to choose from")
    for base in bases:
        ports = layout(base)
        if not taken.intersection(ports.values()):
            return ports
    raise NoFreePorts(f"no base in {bases[0]}..{bases[-1]} has all nine ports free on this host "
                      f"(offsets {sorted(OFFSETS.values())} and the {FED_BAND}+ federation port)")
