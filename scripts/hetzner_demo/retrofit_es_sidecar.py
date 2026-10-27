#!/usr/bin/env python3
"""§SOVKIT K2 (2026-09-14, his word "4 sidecars only"): give an EXISTING frame the event store's mTLS sidecar the template
ships, and nothing else of the kit.

The sandbox pair (sbx-alpha, sbx-beta) was born 2026-09-03, before §MTLSGAP put `nginx-event-store` into the template: both
run nginx-federation and nginx-teg, their store's mTLS is terminated by the HOST vhost only, and their registry and TEG write
plain http + key. This tool renders, FROM THE TEMPLATE ITSELF (one rule at the source), the sidecar's compose block in the
D12 shape, its conf, the env lines it interpolates, and the SPIRE `entry update` that adds the `<name>-nginx-event-store`
DNS SAN to the frame's registry entry (the cert-writer's one SVID serves every sidecar; a caller that verifies the hostname
gets a mismatch without the SAN, §XFRAMETEG). Everything is derived from the frame's own stack: the nginx-teg block names
the stack dir, the certs volume and the two networks; the env carries the proxy marker (ES_PROXY_TRUST_SECRET) the flip
wrote; the store's env says EVENTSTORE_MTLS_REQUIRED.

  retrofit_es_sidecar.py <stack_dir>            render only: writes <stack_dir>/retrofit-es-sidecar/{service.yml,
                                                nginx-event-store-frame-test.conf,env.lines,spire-entry-update.sh,plan.json}
                                                and prints the plan (never a secret)
  retrofit_es_sidecar.py <stack_dir> --apply    + bak compose and env, insert the block before the top-level `volumes:`,
                                                append the env lines, write the conf into the stack dir, run the entry
                                                update, `docker compose config`; prints the two commands the window runs
                                                (start the sidecar; flip TEG's and registry's EVENT_STORE_URL as on orchard)

Refuses when the compose already has the block, when the env lacks the marker, when the store's env lacks
EVENTSTORE_MTLS_REQUIRED=true, or when the nginx-teg block does not name a certs volume and two networks.

§MTLSHOPS T2 (S4, 2026-09-15): the template's sidecar now reaches the store through its unix socket (a volume the store and
the sidecar share). This tool retrofits a frame whose store still listens on TCP, so it refuses a socket-shaped template
rather than render a gateway to a socket that frame does not have; a frame on the socket store is built from the template.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "templates", "frame-test")
COMPOSE_TMPL = os.path.join(TEMPLATE_DIR, "docker-compose.frame-test.yml.tmpl")
CONF_TMPL = os.path.join(TEMPLATE_DIR, "nginx-event-store-frame-test.conf.tmpl")
MARKER_KEYS = ("ES_PROXY_TRUST_SECRET", "FT_ES_ES_PROXY_TRUST_SECRET")
SECRET_RE = re.compile(r"^[A-Za-z0-9._~-]{32,}$")


class Refused(Exception):
    pass


def _env_kv(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def service_block(compose_text: str, service: str) -> str:
    """The text of ONE top-level service block (two-space key at column 0 up to the next one)."""
    blocks = re.split(r"(?m)^(?=  [a-zA-Z{][^\n]*:\s*$)", compose_text)
    hits = [b for b in blocks if b.startswith(f"  {service}:")]
    if len(hits) != 1:
        raise Refused(f"service block {service!r} found {len(hits)} times")
    return hits[0]


def template_es_block() -> str:
    return service_block(open(COMPOSE_TMPL, encoding="utf-8").read(), "{{REGISTRY_NAME}}-nginx-event-store")


def derive(stack_dir: str) -> dict:
    """Everything the template's placeholders need, read from the frame's own stack (never invented)."""
    cf = os.path.join(stack_dir, "docker-compose.frame-test.yml"); ef = os.path.join(stack_dir, ".env.frame-test")
    for p in (cf, ef):
        if not os.path.isfile(p):
            raise Refused(f"missing {p}")
    compose = open(cf, encoding="utf-8").read(); env = _env_kv(open(ef, encoding="utf-8").read())
    m = re.search(r"(?m)^  ([a-z][a-z0-9-]*)-nginx-teg:\s*$", compose)
    if not m:
        raise Refused("no <name>-nginx-teg block: this tool derives the sidecar's shape from it")
    name = m.group(1)
    if re.search(rf"(?m)^  {re.escape(name)}-nginx-event-store:\s*$", compose):
        raise Refused(f"{name}-nginx-event-store already exists in the compose")
    teg = service_block(compose, f"{name}-nginx-teg")
    vol = re.search(r"^\s+- ([A-Za-z0-9_]+_svid_certs_[0-9]+):/certs:ro\s*$", teg, re.M)
    if not vol:
        raise Refused("the nginx-teg block mounts no <prefix>_svid_certs_<ts> volume at /certs")
    certs_volume = vol.group(1)
    conf_mount = re.search(r"^\s+- (/[^:\s]+)/nginx-teg-frame-test\.conf:", teg, re.M)
    if not conf_mount:
        raise Refused("the nginx-teg block mounts no host conf: cannot derive the stack dir the compose names")
    host_stack_dir = conf_mount.group(1)
    nets = re.findall(r"^\s+- ([A-Za-z0-9_.-]+)\s*$", teg.split("networks:", 1)[1].split("depends_on:", 1)[0], re.M) if "networks:" in teg else []
    if len(nets) != 2:
        raise Refused(f"the nginx-teg block joins {len(nets)} networks, expected the frame network and the identity network")
    marker = next((env[k] for k in MARKER_KEYS if env.get(k)), "")
    if not SECRET_RE.fullmatch(marker):
        raise Refused("the env carries no proxy marker of the right shape (ES_PROXY_TRUST_SECRET, 32+ of [A-Za-z0-9._~-]): flip the store first")
    store = service_block(compose, f"{name}-event-store")
    store_env_ok = bool(re.search(r"EVENTSTORE_MTLS_REQUIRED:\s*\$\{[A-Z_]+\}|EVENTSTORE_MTLS_REQUIRED:\s*\"?true", store)) or env.get("EVENTSTORE_MTLS_REQUIRED", "").lower() == "true" or env.get("FT_ES_EVENTSTORE_MTLS_REQUIRED", "").lower() == "true"
    if not store_env_ok:
        raise Refused("the store is not on the mTLS-required posture (no EVENTSTORE_MTLS_REQUIRED=true in its block or env)")
    if not re.search(r"(?m)^volumes:\s*$", compose):
        raise Refused("the compose has no top-level volumes: section to insert the block before")
    return {"name": name, "stack_dir": stack_dir, "host_stack_dir": host_stack_dir, "certs_volume": certs_volume,
            "net": nets[0], "identity_net": nets[1], "marker": marker, "env_present": {k: (k in env) for k in
            ("FT_CERT_DIR", "FT_NGES_RELOAD_SEC", "FT_NGES_SERVICE_NAME", "FT_NGES_PROXY_TRUST_SECRET", "FT_EVENT_STORE_MTLS_URL")}}


SOCKET_SHAPE = "a unix socket (§MTLSHOPS T2): this tool retrofits a frame whose store listens on TCP; build a T2 frame from the template instead"


def render_block(d: dict) -> str:
    b = template_es_block()
    if "_sock_event-store_" in b:
        raise Refused("the template's store sidecar mounts the store's socket, " + SOCKET_SHAPE)
    b = b.replace("{{REGISTRY_NAME}}", d["name"]).replace("{{STACK_DIR}}", d["host_stack_dir"])
    b = b.replace("{{VOL_PREFIX}}_svid_certs_{{TS}}", d["certs_volume"])
    b = b.replace("{{NET_NAME}}", d["net"]).replace("{{IDENTITY_NET_NAME}}", d["identity_net"])
    left = re.findall(r"\{\{[A-Z_]+\}\}", b)
    if left:
        raise Refused(f"placeholders left unrendered: {sorted(set(left))}")
    return b


def render_conf(d: dict) -> str:
    c = open(CONF_TMPL, encoding="utf-8").read().replace("{{REGISTRY_NAME}}", d["name"])
    if "proxy_pass http://unix:" in c:
        raise Refused("the template's store sidecar conf proxies to " + SOCKET_SHAPE)
    if "{{" in c:
        raise Refused("the conf template carries a placeholder this tool does not know")
    if 'proxy_set_header X-ES-Proxy-Auth "${ES_PROXY_TRUST_SECRET}";' not in c:
        raise Refused("the conf template no longer sets the proxy marker: refusing to render a leg without it")
    return c


def env_lines(d: dict) -> list:
    """The FT_* lines the block interpolates; only the ones the env lacks. The secret is the frame's own marker."""
    want = [("FT_CERT_DIR", "/certs"), ("FT_NGES_RELOAD_SEC", "300"), ("FT_NGES_SERVICE_NAME", f"{d['name']}-nginx-event-store"),
            ("FT_NGES_PROXY_TRUST_SECRET", d["marker"]), ("FT_EVENT_STORE_MTLS_URL", f"https://{d['name']}-nginx-event-store:8443")]
    return [f"{k}={v}" for k, v in want if not d["env_present"].get(k)]


def parse_entry_show(text: str) -> dict:
    e = {"selectors": [], "dns": [], "federates_with": []}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":"); k = k.strip(); v = v.strip()
        if k == "Entry ID": e["entry_id"] = v
        elif k == "SPIFFE ID": e["spiffe_id"] = v
        elif k == "Parent ID": e["parent_id"] = v
        elif k == "X509-SVID TTL": e["ttl"] = v
        elif k == "Selector": e["selectors"].append(v)
        elif k == "FederatesWith": e["federates_with"].append(v)
        elif k == "DNS name": e["dns"].append(v)
    if not all(e.get(k) for k in ("entry_id", "spiffe_id", "parent_id")):
        raise Refused("entry show did not carry Entry ID, SPIFFE ID and Parent ID")
    return e


def entry_update_argv(e: dict, new_dns: str) -> list:
    """The provisioner's argv shape (`_entry_argv` in frame_test_provisioner.py): -entryID first, then -spiffeID/-parentID,
    every -selector, every -dns (the new SAN appended once), -x509SVIDTTL, every -federatesWith as spiffe://<td>."""
    dns = list(e["dns"]) + ([] if new_dns in e["dns"] else [new_dns])
    argv = ["/opt/spire/bin/spire-server", "entry", "update", "-entryID", e["entry_id"], "-spiffeID", e["spiffe_id"], "-parentID", e["parent_id"]]
    for s in e["selectors"]:
        argv += ["-selector", s]
    ttl = e.get("ttl", "")
    if ttl and ttl != "default":
        argv += ["-x509SVIDTTL", str(ttl)]
    for n in dns:
        argv += ["-dns", n]
    for td in e["federates_with"]:
        argv += ["-federatesWith", td if td.startswith("spiffe://") else f"spiffe://{td}"]
    return argv


def registry_spiffe_id(stack_dir: str, name: str) -> tuple:
    env = _env_kv(open(os.path.join(stack_dir, ".env.frame-test"), encoding="utf-8").read())
    td = env.get("SPIRE_TRUST_DOMAIN") or env.get("FT_TRUST_DOMAIN") or env.get("TRUST_DOMAIN") or ""
    if not td:
        raise Refused("the env names no trust domain (SPIRE_TRUST_DOMAIN)")
    return td, f"spiffe://{td}/service/{name}-registry"


def render(stack_dir: str) -> dict:
    d = derive(stack_dir)
    out_dir = os.path.join(stack_dir, "retrofit-es-sidecar"); os.makedirs(out_dir, exist_ok=True)
    block = render_block(d); conf = render_conf(d); lines = env_lines(d)
    td, sid = registry_spiffe_id(stack_dir, d["name"])
    show = subprocess.run(["docker", "exec", f"{d['name']}-spire-server", "/opt/spire/bin/spire-server", "entry", "show", "-spiffeID", sid],
                          capture_output=True, text=True, timeout=60)
    if show.returncode != 0 or "Entry ID" not in show.stdout:
        raise Refused(f"entry show for {sid} answered rc={show.returncode}: {(show.stderr or show.stdout)[-200:]}")
    e = parse_entry_show(show.stdout)
    new_dns = f"{d['name']}-nginx-event-store"
    argv = entry_update_argv(e, new_dns)
    open(os.path.join(out_dir, "service.yml"), "w", encoding="utf-8").write(block)
    open(os.path.join(out_dir, "nginx-event-store-frame-test.conf"), "w", encoding="utf-8").write(conf)
    fd = os.open(os.path.join(out_dir, "env.lines"), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("".join(l + "\n" for l in lines))
    open(os.path.join(out_dir, "spire-entry-update.sh"), "w", encoding="utf-8").write(
        "#!/bin/sh\n# rendered by retrofit_es_sidecar.py; the registry entry gains the DNS SAN the sidecar's hostname verification needs\n"
        f"docker exec {d['name']}-spire-server " + " ".join(argv) + "\n")
    plan = {"name": d["name"], "stack_dir": stack_dir, "host_stack_dir": d["host_stack_dir"], "certs_volume": d["certs_volume"],
            "networks": [d["net"], d["identity_net"]], "trust_domain": td, "registry_entry": e["entry_id"],
            "dns_before": e["dns"], "dns_after": list(e["dns"]) + ([] if new_dns in e["dns"] else [new_dns]),
            "federates_with": e["federates_with"], "env_lines_added": [l.split("=", 1)[0] for l in lines],
            "marker_len": len(d["marker"]), "rendered": sorted(os.listdir(out_dir))}
    open(os.path.join(out_dir, "plan.json"), "w", encoding="utf-8").write(json.dumps(plan, indent=1))
    return plan


def apply(stack_dir: str) -> dict:
    plan = render(stack_dir)
    name = plan["name"]; out_dir = os.path.join(stack_dir, "retrofit-es-sidecar")
    cf = os.path.join(stack_dir, "docker-compose.frame-test.yml"); ef = os.path.join(stack_dir, ".env.frame-test")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    shutil.copy2(cf, f"{cf}.bak-pre-es-sidecar-{stamp}"); shutil.copy2(ef, f"{ef}.bak-pre-es-sidecar-{stamp}")
    compose = open(cf, encoding="utf-8").read()
    block = open(os.path.join(out_dir, "service.yml"), encoding="utf-8").read()
    if not block.endswith("\n"):
        block += "\n"
    parts = re.split(r"(?m)^(volumes:\s*)$", compose, maxsplit=1)
    if len(parts) != 3:
        raise Refused("the top-level volumes: section was not found exactly once")
    compose2 = parts[0].rstrip("\n") + "\n\n" + block + "\n" + parts[1] + parts[2]
    open(cf, "w", encoding="utf-8").write(compose2)
    lines = open(os.path.join(out_dir, "env.lines"), encoding="utf-8").read()
    with open(ef, "a", encoding="utf-8") as f:
        f.write(f"\n# §SOVKIT K2 ({stamp}): the event store's mTLS sidecar, retrofitted from the template (retrofit_es_sidecar.py)\n" + lines)
    conf_dst = os.path.join(stack_dir, "nginx-event-store-frame-test.conf")
    shutil.copy2(os.path.join(out_dir, "nginx-event-store-frame-test.conf"), conf_dst); os.chmod(conf_dst, 0o644)
    upd = subprocess.run(["sh", os.path.join(out_dir, "spire-entry-update.sh")], capture_output=True, text=True, timeout=120)
    if upd.returncode != 0:
        raise Refused(f"spire entry update rc={upd.returncode}: {(upd.stderr or upd.stdout)[-300:]}")
    cfg = subprocess.run(["docker", "compose", "-f", cf, "--env-file", ef, "config", "--quiet"], capture_output=True, text=True, timeout=120)
    if cfg.returncode != 0:
        raise Refused(f"docker compose config refused the edited compose: {cfg.stderr[-400:]}")
    plan["applied"] = {"compose_bak": f"{cf}.bak-pre-es-sidecar-{stamp}", "env_bak": f"{ef}.bak-pre-es-sidecar-{stamp}", "conf": conf_dst,
                       "entry_updated": True, "compose_config": "ok"}
    plan["window_commands"] = [
        f"docker compose -f {cf} --env-file {ef} up -d --no-deps --no-build --pull never {name}-nginx-event-store",
        f"# then, in the same window and as on orchard: {name}-teg and {name}-registry EVENT_STORE_URL -> ${{FT_EVENT_STORE_MTLS_URL}} (the auditor, if any, stays plain), one --no-deps recreate each",
    ]
    return plan


def main(argv: list) -> int:
    if len(argv) < 2:
        print(__doc__); return 2
    stack_dir = os.path.abspath(argv[1]); do_apply = "--apply" in argv[2:]
    try:
        plan = apply(stack_dir) if do_apply else render(stack_dir)
    except Refused as exc:
        print(f"REFUSED: {exc}"); return 3
    print(json.dumps(plan, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
