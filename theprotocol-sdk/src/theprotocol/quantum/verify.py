"""Check a quantum job offline, with no registry: python -m theprotocol.quantum.verify (V0660 (b)).

    python -m theprotocol.quantum.verify AGREEMENT.json CHAIN.json EVIDENCE.json [--keys KEYS.json]

AGREEMENT.json is the acceptance test the run was bound to (a registry serves it at
GET /api/v1/quantum/acceptance/{rail}/{ref}), CHAIN.json the receipt chain, EVIDENCE.json what the template recomputes
the verdict from. KEYS.json maps each participant's DID to the public keys (Ed25519 JWKs) it signs with, for example
from GET /api/v1/agents/{did}/public-key; without it the chain is checked whole, but who holds each key is not.

It prints the report as JSON and exits 0 when the job is checked and passed, 1 when it is checked and failed, 2 when
it is refused (the problems say why). The check is receipts.check_job, the same code a registry runs at its verify and
release steps. Needs the cryptography package (theprotocol-sdk[anp]).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .receipts import check_job


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m theprotocol.quantum.verify",
                                 description="Check a quantum job's receipt chain and recompute its verdict, offline.")
    ap.add_argument("agreement")
    ap.add_argument("chain")
    ap.add_argument("evidence")
    ap.add_argument("--keys", help="a JSON object: each participant DID to a list of Ed25519 JWKs")
    args = ap.parse_args(argv)
    keys = None
    if args.keys:
        raw = _load(args.keys)
        keys = {d: (v if isinstance(v, list) else [v]) for d, v in raw.items()} if isinstance(raw, dict) else {}
    report = check_job(_load(args.agreement), _load(args.chain), _load(args.evidence), keys=keys)
    json.dump(report.as_dict(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    if not report.ok:
        return 2
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
