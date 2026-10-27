#!/usr/bin/env python3
"""Can the internet reach this frame? (§EXTREACH design A, agentvault2-5b, 2026-10-14)

A peer federates with a frame only through four public lanes: the console (443), the federation gateway (8443), the
SPIRE bundle endpoint (8444) and the ledger gateway (8445). From this host nothing can tell whether the internet gets
in: the router's port forwarding, the provider's firewall (a cloud "security group") and carrier NAT are all outside
it. This asks the network to dial back (POST <probe>/api/v1/public/reach-probe) and prints, for every lane that does
not answer, the one thing to fix. frame-up.py runs it at its end; run it again after changing a forward.

    ./frame-reach.py --public-name frame.example.org
    ./frame-reach.py --public-name frame.example.org --bundle-port 8454 --json

Exit: 0 every lane answers; 1 at least one does not; 2 the probe could not judge (no answer, not offered, refused).
Docker publishes the lanes past the host firewall (ufw does not see docker-published ports), so the host firewall is
rarely the cause; the router, the provider's firewall and the DNS record usually are.
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request

DEFAULT_PROBE = "https://eu.theprotocol.cloud/api/v1/public/reach-probe"
LABEL = {"console": "console", "federation": "federation gateway", "bundle": "SPIRE bundle endpoint",
         "ledger": "ledger gateway"}


def fix_for(row, name, address):
    """One sentence: what to change so this lane answers."""
    port, role, v = row.get("port"), row.get("role"), row.get("verdict")
    if v == "timeout":
        return (f"nothing reached {name}:{port} from the internet: forward TCP {port} to this machine (your router's "
                f"port forwarding, or your provider's firewall / security group)")
    if v == "refused":
        return (f"{address} answered on {port}, but nothing listens there: is the frame running, and does it publish "
                f"{port} (frame-up's --{role}-port)? A forward may also point at another machine")
    if v == "not_tls":
        return f"something other than the frame answers on {port}: another service holds the port, or the forward points elsewhere"
    if v == "certificate_invalid":
        return (f"the console's certificate is not valid for {name} yet: Let's Encrypt needs ports 80 and 443 reachable "
                f"and the A record pointing here; the edge retries on its own")
    if v == "wrong_name":
        return f"port {port} answers with a certificate for another name: the forward reaches another frame or service"
    if v == "not_a_bundle":
        return f"port {port} answers TLS but is not a SPIRE bundle endpoint: the forward points at the wrong container"
    return (f"the dial to {name}:{port} failed ({row.get('detail') or v}): check that {name} points at this machine "
            f"and that TCP {port} is forwarded to it")


REFUSAL = {
    "no_address": "{name} has no A record the network can see: create one pointing at {caller}, the address this "
                  "machine called from (behind NAT: the router's public address), then wait for it to propagate",
    "private_address": "{name} resolves to a private address ({addresses}), which the internet cannot reach: point "
                       "the A record at the public address ({caller})",
    "this_server": "{name} resolves to the probing server itself; the probe dials other hosts only",
    "custom_ports_need_own_address": "lanes moved off 443/8443/8444/8445 are dialled only when {name} resolves to the "
                                     "address asking ({caller}): run this on the frame's own host (behind NAT: one "
                                     "whose public address is the A record), or check the default ports",
}


def post(url, payload, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json",
                                          "User-Agent": "frame-reach/1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except Exception as e:  # noqa: BLE001 - the failure is what we report
        return None, {"error": f"{type(e).__name__}: {str(e)[:160]}"}


def check_and_report(name, ports, probe=DEFAULT_PROBE, out=print, send=post):
    """(exit code, the probe's answer). Prints one line per lane and one fix per lane that does not answer."""
    st, j = send(probe, {"public_name": name, "ports": ports})
    if st != 200:
        why = (j or {}).get("detail") or (j or {}).get("error") or f"HTTP {st}"
        if isinstance(why, dict):
            why = why.get("detail") or json.dumps(why)[:160]
        if st == 404:
            why = "the network serves no probe at this address yet: it arrives with a later release"
        out(f"reach check: could not be judged ({why}); the network's probe is {probe}")
        return 2, j
    if j.get("refusal"):
        msg = REFUSAL.get(j["refusal"], "{name}: " + str(j.get("detail") or j["refusal"]))
        out("reach check: " + msg.format(name=name, caller=j.get("caller_address") or "?",
                                         addresses=", ".join(j.get("addresses") or []) or "none"))
        return (1 if j["refusal"] in ("no_address", "private_address") else 2), j
    address, caller = j.get("address"), j.get("caller_address")
    out(f"reach check: the network dialled {name} at {address} (from outside, just now):")
    bad = []
    for row in j.get("results") or []:
        ok = row.get("verdict") == "ok"
        out(f"  {'ok  ' if ok else 'FAIL'} {LABEL.get(row.get('role'), row.get('role')):<22} {row.get('port'):<6} "
            f"{row.get('detail', '')}")
        if not ok:
            bad.append(row)
    if address and caller and not j.get("name_points_at_caller"):
        out(f"  note: {name} resolves to {address}, but this machine called from {caller}; behind NAT that is fine "
            f"only if {address} is the router's public address")
    for row in bad:
        out(f"  fix  {fix_for(row, name, address)}")
    if bad:
        out(f"  then run ./frame-reach.py --public-name {name} again")
        return 1, j
    out("  every lane answers: a peer can federate with this frame")
    return 0, j


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--public-name", required=True, help="the frame's public name (its trust domain)")
    ap.add_argument("--console-port", type=int, default=443, help="the console's PUBLIC https port")
    ap.add_argument("--federation-port", type=int, default=8443)
    ap.add_argument("--bundle-port", type=int, default=8444)
    ap.add_argument("--ledger-port", type=int, default=8445)
    ap.add_argument("--probe", default=DEFAULT_PROBE, help=f"the network's probe (default {DEFAULT_PROBE})")
    ap.add_argument("--json", action="store_true", help="print the probe's answer as JSON as well")
    a = ap.parse_args()
    ports = {"console": a.console_port, "federation": a.federation_port, "bundle": a.bundle_port, "ledger": a.ledger_port}
    rc, j = check_and_report(a.public_name, ports, a.probe)
    if a.json:
        print(json.dumps(j, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
