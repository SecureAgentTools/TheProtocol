"""tp-proxy: run TheProtocol Proxy.

    tp-proxy init --from ./my-agent      onboard: a proxy.yaml beside the Agent Forge starter's .env and .env.secret,
                                         then the registry's checks (the credentials, the card, the bond, the roles)
    tp-proxy validate [proxy.yaml]       the spec as the proxy reads it, or every problem with its path
    tp-proxy run [proxy.yaml]            run it (--dry-run: map and print what it would send, sending nothing;
                                         --replay SOURCE=POINT: that source reads again from POINT)
    tp-proxy status [proxy.yaml]         the outbox, the switches, the breakers (also while it runs)
    tp-proxy dead [proxy.yaml]           the dead letters, with the other side's answer
    tp-proxy replay [proxy.yaml] --all   send dead letters again after a fix (--mapping M, --key K)
    tp-proxy pause [proxy.yaml] [M]      stop sending (all, or one mapping); records are still taken in
    tp-proxy resume [proxy.yaml] [M]     send again (a mapping's resume also closes its breaker)
    tp-proxy verify DIR                  check an evidence export offline (--key: the signer you expect;
                                         --webhook-secret REF: the registry's signature on every delivery too)
    tp-proxy keygen PATH                 a new Ed25519 key for the evidence export (PEM, 0600); prints its public key

The spec defaults to ./proxy.yaml (or TP_PROXY_SPEC). Exit codes: 0 done, 1 failed, 2 the spec is refused, 3 the
registry refused the proxy's credentials.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .identity import Identity, IdentityError
from .outbox import Outbox
from .plugins import PluginError, load
from .spec import Spec, SpecError, dotenv_value, read

EXIT_FAILED, EXIT_SPEC, EXIT_CREDENTIALS = 1, 2, 3


def _spec_path(arg: Optional[str]) -> str:
    return arg or os.environ.get("TP_PROXY_SPEC") or "proxy.yaml"


def _out(doc: Any) -> None:
    print(json.dumps(doc, indent=1, default=str, ensure_ascii=False))


def _read(path: str, *, plugins: bool = True) -> Spec:
    return read(path, check_plugins=plugins)


def _outbox(spec: Spec) -> Outbox:
    p = Path(spec.state_path)
    if not p.exists():
        raise SpecError([f"{p}: no outbox yet (the proxy has not run)"])
    return Outbox(str(p))


# ── init ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

SKELETON = """\
# TheProtocol Proxy for {title}, written by tp-proxy init.
# The credentials stay in {secret_file}: this file only names them. Change the source, the action and the mapping
# for your system, then: tp-proxy validate, tp-proxy run --dry-run, tp-proxy run.
version: 1
name: {name}
registry: {registry}
identity:
  agent_did: {did}
  client_id: {client_id}
  client_secret: {client_secret}
  mtls: {{enabled: false, dir: ./certs}}
state: ./proxy-state.db
sources:
  inbox:
    type: webhook
    config: {{listen: "127.0.0.1:8711", path: /in, id_field: id}}
actions:
  attest:
    type: attestation
    config: {{attestation_type: example.reading}}
    limits: {{per_minute: 60}}
sinks: {{}}
mappings:
  - name: inbox-attest
    version: 1
    from: inbox
    to: attest
    fields: {{reading: $.payload}}
retry: {{first_s: 2, max_s: 300, attempts: 8}}
breaker: {{refusals: 5, failures: 10, cooldown_s: 30}}
service: {{listen: "127.0.0.1:9108"}}
"""


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip()).strip("-._").lower()
    return (s or "proxy")[:63]


def write_skeleton(starter: Path, out: Path, *, force: bool = False) -> Dict[str, str]:
    """proxy.yaml from the starter's .env (its agent and registry) and the path of its .env.secret."""
    env_file, secret_file = starter / ".env", starter / ".env.secret"
    try:
        env = env_file.read_text(encoding="utf-8")
    except OSError as e:
        raise SpecError([f"{env_file}: {e.strerror or e} (tp-proxy init --from names the starter's folder)"])
    try:
        secret_text = secret_file.read_text(encoding="utf-8")
    except OSError as e:
        raise SpecError([f"{secret_file}: {e.strerror or e} (the starter's download carries it)"])
    did, registry = (dotenv_value(env, "AGENT_DID") or "").strip(), (dotenv_value(env, "REGISTRY_URL") or "").strip()
    problems = []
    if not did.startswith("did:"):
        problems.append(f"{env_file}: AGENT_DID is not a DID")
    if not re.match(r"^https?://", registry):
        problems.append(f"{env_file}: REGISTRY_URL is not an http(s) address")
    for key in ("CLIENT_ID", "CLIENT_SECRET"):
        if not (dotenv_value(secret_text, key) or "").strip():
            problems.append(f"{secret_file}: no {key}")
    if out.exists() and not force:
        problems.append(f"{out}: there is a spec already (--force writes over it)")
    if problems:
        raise SpecError(problems)
    rel = os.path.relpath(secret_file.resolve(), out.parent.resolve())
    title = (dotenv_value(env, "AGENT_NAME") or "").strip() or did
    text = SKELETON.format(title=title, secret_file=rel, name=json.dumps(_slug(title)), registry=json.dumps(registry),
                           did=json.dumps(did), client_id=json.dumps(f"file:{rel}#CLIENT_ID"),
                           client_secret=json.dumps(f"file:{rel}#CLIENT_SECRET"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return {"spec": str(out), "agent_did": did, "registry": registry, "credentials": str(secret_file)}


def _permissions(spec: Spec) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for name, ps in spec.actions.items():
        try:
            cls = load("action", ps.type)
        except PluginError:
            continue
        out[name] = sorted(cls.needs)
    return out


async def onboard(spec: Spec, *, transport: Optional[httpx.AsyncBaseTransport] = None) -> Dict[str, Any]:
    """The registry's answers for this proxy's agent: its token (the credentials), its card, its bond, and what its
    actions need. Raises IdentityError when the registry does not issue the token."""
    did = str(spec.value(spec.identity["agent_did"]))
    ident = Identity(spec.registry, did, str(spec.value(spec.identity["client_id"])),
                     str(spec.value(spec.identity["client_secret"])), transport=transport)
    token = await ident.token()
    report: Dict[str, Any] = {"credentials": f"the registry at {spec.registry} issued a token for {did}"}
    async with httpx.AsyncClient(transport=transport, timeout=20.0) as http:
        r = await http.get(f"{spec.registry}/api/v1/agent-cards/{did}")
        if r.status_code == 200:
            card = r.json() if r.content else {}
            report["card"] = {"active": bool(card.get("is_active", True)), "name": (card.get("card_data") or {}).get("name")}
        else:
            report["card"] = {"missing": f"the registry has no card for {did} (HTTP {r.status_code})"}
        r = await http.get(f"{spec.registry}/api/v1/agents/reputation-bond/status",
                           headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            b = r.json()
            report["bond"] = {"status": b.get("status"), "amount": b.get("amount"), "currency": b.get("currency")}
        elif r.status_code == 404:
            d = (r.json() or {}).get("detail") if r.content else None
            need = d if isinstance(d, dict) else {}
            report["bond"] = {"status": "none", "required_for_a_provider": need.get("required_amount"),
                              "currency": need.get("currency"),
                              "note": "a proxy that only attests needs none; a provider is found and paid once bonded"}
        else:
            report["bond"] = {"unknown": f"HTTP {r.status_code}"}
    needs = _permissions(spec)
    report["permissions"] = {
        "needed": needs,
        "how": "the owner grants them in the console (the agent's access panel): the attestor role carries "
               "reputation.signal and nothing else",
    }
    return report


# ── the commands ─────────────────────────────────────────────────────────────────────────────────────────────────────

def cmd_init(a, transport=None) -> int:
    starter = Path(a.source or ".").resolve()
    out = Path(a.out).resolve() if a.out else starter / "proxy.yaml"
    written = write_skeleton(starter, out, force=a.force)
    _out({"written": written})
    if a.no_check:
        return 0
    spec = _read(str(out))
    try:
        report = asyncio.run(onboard(spec, transport=transport))
    except IdentityError as e:
        _out({"refused": e.detail})
        return EXIT_CREDENTIALS
    _out(report)
    return 0


def cmd_validate(a) -> int:
    spec = _read(_spec_path(a.spec))
    _out({"valid": True, "name": spec.name, "registry": spec.registry,
          "sources": {n: p.type for n, p in spec.sources.items()},
          "actions": {n: p.type for n, p in spec.actions.items()},
          "sinks": {n: p.type for n, p in spec.sinks.items()},
          "mappings": [{"name": m.name, "version": m.version, "from": m.source, "to": m.action, "kind": m.kind}
                       for m in spec.mappings],
          "permissions": _permissions(spec)})
    return 0


def cmd_run(a, transport=None) -> int:
    from .logs import setup
    from .runtime import Proxy
    spec = _read(_spec_path(a.spec))
    replays = []
    for item in a.replay or []:
        src, sep, point = item.partition("=")
        if not sep or src not in spec.sources:
            raise SpecError([f"--replay {item!r}: SOURCE=POINT, with one of the spec's sources ({', '.join(spec.sources)})"])
        replays.append((src, point))

    def report(doc: Dict[str, Any]) -> None:
        print(json.dumps(doc, default=str, ensure_ascii=False), flush=True)

    async def main() -> int:
        proxy = Proxy(spec, dry_run=a.dry_run, transport=transport, report=report if a.dry_run else None,
                      service=False if a.no_service else None)
        setup(secrets=lambda: (*spec.secret_values(), *proxy.identity.secrets()), level=a.log_level)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except (NotImplementedError, RuntimeError):  # pragma: no cover - not on this platform
                pass
        try:
            await proxy.start()
            for src, point in replays:
                await proxy.sources[src].rewind(point)
            await proxy.run(until_idle=a.once, stop=stop)
        except IdentityError as e:
            print(json.dumps({"refused": e.detail}), file=sys.stderr)
            return EXIT_CREDENTIALS
        finally:
            await proxy.stop()
            proxy.close()
        return 0

    return asyncio.run(main())


def _status_doc(spec: Spec, o: Outbox) -> Dict[str, Any]:
    sw = o.switches()
    return {"name": spec.name, "state": spec.state_path, "outbox": o.counts(),
            "paused": bool(sw.get("pause")),
            "mappings": {m.name: {**o.counts_by_mapping().get(m.name, {"pending": 0, "done": 0, "dead": 0}),
                                  "paused": bool(sw.get(f"pause:{m.name}")), "breaker": sw.get(f"breaker:{m.name}")}
                         for m in spec.mappings}}


def cmd_status(a) -> int:
    spec = _read(_spec_path(a.spec), plugins=False)
    o = _outbox(spec)
    try:
        _out(_status_doc(spec, o))
    finally:
        o.close()
    return 0


def cmd_dead(a) -> int:
    spec = _read(_spec_path(a.spec), plugins=False)
    o = _outbox(spec)
    try:
        for r in o.dead_letters(mapping=a.mapping, limit=a.limit):
            print(json.dumps({"key": r.key, "mapping": r.mapping, "record_id": r.record_id, "attempts": r.attempts,
                              "why": r.last_error, "answer": r.answer}, default=str, ensure_ascii=False))
    finally:
        o.close()
    return 0


def cmd_replay(a) -> int:
    if not (a.all or a.mapping or a.key):
        raise SpecError(["replay what: --all, --mapping M or --key K"])
    spec = _read(_spec_path(a.spec), plugins=False)
    o = _outbox(spec)
    try:
        n = o.replay(keys=a.key or (), mapping=a.mapping)
    finally:
        o.close()
    _out({"replayed": n})
    return 0


def cmd_switch(a, on: bool) -> int:
    spec = _read(_spec_path(a.spec), plugins=False)
    if a.mapping and a.mapping not in {m.name for m in spec.mappings}:
        raise SpecError([f"no mapping called {a.mapping!r} ({', '.join(m.name for m in spec.mappings)})"])
    o = _outbox(spec)
    try:
        if on:
            o.set_switch(f"pause:{a.mapping}" if a.mapping else "pause", True)
        elif getattr(a, "all", False):
            for name in list(o.switches()):
                o.set_switch(name, None)
        elif a.mapping:
            o.set_switch(f"pause:{a.mapping}", None)
            o.set_switch(f"breaker:{a.mapping}", None)
        else:
            o.set_switch("pause", None)
        _out(_status_doc(spec, o))
    finally:
        o.close()
    return 0


def cmd_verify(a) -> int:
    from .evidence import verify
    from .spec import resolve
    secret = resolve(a.webhook_secret, base=Path.cwd()) if a.webhook_secret else None
    problems, summary = verify(a.dir, public_key=a.key, webhook_secret=secret)
    _out({"holds": not problems, "problems": problems, **summary})
    return 0 if not problems else EXIT_FAILED


def cmd_keygen(a) -> int:
    from .evidence import keygen
    _out({"written": a.path, "public_key": keygen(a.path)})
    return 0


def cmd_quantum_card(a) -> int:
    """Print the quantum workload card extension for the backend this spec runs.

    Generated from the backend's own facts rather than typed, so a card cannot drift away from the machine
    it describes. The receipt's schema version and signing algorithm belong to the receipt builder; pass
    them until that module ships, and this refuses rather than inventing them."""
    from .quantum.backends import backend_from
    from .quantum.card import extension_for

    spec = _read(_spec_path(a.spec))
    sections = [p for p in list(spec.sinks.values()) + list(spec.sources.values())
                if p.type in ("quantum_submit", "quantum_results")]
    if not sections:
        _out({"error": "this spec runs no quantum backend: it has no quantum_submit sink and no "
                       "quantum_results source"})
        return EXIT_FAILED
    chosen = sections[0]
    if a.section:
        chosen = next((p for p in sections if p.name == a.section), None)
        if chosen is None:
            _out({"error": f"the spec has no quantum section named {a.section!r}",
                  "sections": [p.name for p in sections]})
            return EXIT_FAILED

    receipt = None
    if a.receipt_schema_version or a.receipt_signing_algorithm:
        receipt = {"schema_version": a.receipt_schema_version,
                   "signing_algorithm": a.receipt_signing_algorithm}
    try:
        ext = extension_for(backend_from(chosen.config.get("backend") or {}),
                            roles=[r.strip() for r in (a.roles or "provider,meter").split(",") if r.strip()],
                            receipt=receipt,
                            verification_rungs=[int(r) for r in (a.rungs or "1").split(",") if r.strip()],
                            residency=[r.strip() for r in (a.residency or "EU").split(",") if r.strip()])
    except Exception as exc:
        _out({"error": str(exc), "section": chosen.name})
        return EXIT_FAILED
    _out({"section": chosen.name, "extension": ext})
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tp-proxy", description="TheProtocol Proxy: a legacy system's agent identity "
                                "on TheProtocol, translating in both directions.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init", help="write proxy.yaml from the Agent Forge starter's .env and check it on the registry")
    s.add_argument("--from", dest="source", help="the starter's folder (default: here)")
    s.add_argument("--out", help="where to write the spec (default: <starter>/proxy.yaml)")
    s.add_argument("--force", action="store_true", help="write over an existing spec")
    s.add_argument("--no-check", action="store_true", help="write the spec only, ask the registry nothing")
    s = sub.add_parser("validate", help="check the spec and its plugins")
    s.add_argument("spec", nargs="?")
    s = sub.add_parser("run", help="run the proxy")
    s.add_argument("spec", nargs="?")
    s.add_argument("--dry-run", action="store_true", help="map and print what it would send; send nothing")
    s.add_argument("--once", action="store_true", help="stop once every source has finished and nothing is due")
    s.add_argument("--replay", action="append", metavar="SOURCE=POINT", help="read a source again from a point")
    s.add_argument("--no-service", action="store_true", help="no /health and /metrics listener")
    s.add_argument("--log-level", default=os.environ.get("TP_PROXY_LOG_LEVEL", "info"))
    s = sub.add_parser("status", help="the outbox, the switches, the breakers")
    s.add_argument("spec", nargs="?")
    s = sub.add_parser("dead", help="list the dead letters")
    s.add_argument("spec", nargs="?")
    s.add_argument("--mapping")
    s.add_argument("--limit", type=int, default=1000)
    s = sub.add_parser("replay", help="send dead letters again")
    s.add_argument("spec", nargs="?")
    s.add_argument("--mapping")
    s.add_argument("--key", action="append")
    s.add_argument("--all", action="store_true")
    s = sub.add_parser("verify", help="check an evidence export offline")
    s.add_argument("dir")
    s.add_argument("--key", help="the signer's public key (base64) you expect")
    s.add_argument("--webhook-secret", help="a reference (env:NAME, file:/path) to the registry webhook's secret")
    s = sub.add_parser("quantum-card", help="print the quantum workload card extension for this spec's backend")
    s.add_argument("spec", nargs="?")
    s.add_argument("--section", help="which quantum section to read, when the spec has several")
    s.add_argument("--roles", help="the roles the agent holds (default provider,meter)")
    s.add_argument("--rungs", help="the verification rungs offered (default 1)")
    s.add_argument("--residency", help="jurisdiction codes the data stays in (default EU)")
    s.add_argument("--receipt-schema-version", help="the receipt builder's schema version")
    s.add_argument("--receipt-signing-algorithm", help="the receipt builder's signing algorithm")
    s = sub.add_parser("keygen", help="write a new Ed25519 signing key for the evidence export")
    s.add_argument("path")
    for name, help_ in (("pause", "stop sending (all mappings, or one)"), ("resume", "send again")):
        s = sub.add_parser(name, help=help_)
        s.add_argument("spec", nargs="?", help="the spec (default ./proxy.yaml)")
        s.add_argument("mapping", nargs="?")
        if name == "resume":
            s.add_argument("--all", action="store_true", help="every pause and every breaker")
    return p


def main(argv: Optional[List[str]] = None, *, transport: Optional[httpx.AsyncBaseTransport] = None) -> int:
    a = parser().parse_args(argv)
    if a.cmd in ("pause", "resume") and a.spec and not a.mapping and not re.search(r"\.(ya?ml|json)$", a.spec):
        a.spec, a.mapping = None, a.spec      # `tp-proxy pause gate-out`: one argument that is not a spec file
    try:
        if a.cmd == "init":
            return cmd_init(a, transport)
        if a.cmd == "validate":
            return cmd_validate(a)
        if a.cmd == "run":
            return cmd_run(a, transport)
        if a.cmd == "status":
            return cmd_status(a)
        if a.cmd == "dead":
            return cmd_dead(a)
        if a.cmd == "replay":
            return cmd_replay(a)
        if a.cmd in ("pause", "resume"):
            return cmd_switch(a, a.cmd == "pause")
        if a.cmd == "verify":
            return cmd_verify(a)
        if a.cmd == "keygen":
            return cmd_keygen(a)
        if a.cmd == "quantum-card":
            return cmd_quantum_card(a)
    except SpecError as e:
        print(str(e), file=sys.stderr)
        return EXIT_SPEC
    except PluginError as e:
        print(f"tp-proxy: {e}", file=sys.stderr)
        return EXIT_FAILED
    return EXIT_FAILED  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
