# MERIDIAN: order intents in, signed evidence to the ERP folder

The MERIDIAN blueprint (industrial procurement) as a TheProtocol Proxy recipe: `proxy.yaml` here, a fake of the legacy
system in `fake/`, run on the sandbox end to end before it shipped.

**The legacy side.** The order-management system exports its order intents as JSON arrays into a folder (`/data/oms-out`).

**On TheProtocol.** Each RELEASED intent becomes a `meridian.order_intent` attestation; the ERP's import folder (`/data/erp-in`) receives the hash-chained evidence of every intent, its manifest signed by the proxy's key.

**What it needs.** An agent holding the `attestor` role (the attestation's `reputation.signal`), and an evidence signing key (`tp-proxy keygen /run/secrets/evidence.pem`). Credentials come from the agent's starter files (`.env`, `.env.secret`) by reference;
none is written in the spec.

**Try it locally.** `python fake/fake_oms.py ./oms-out --batch 1 --count 5` writes one export (one HELD intent among them, not attested). Then:

```
tp-proxy validate proxy.yaml
tp-proxy run proxy.yaml --dry-run --once     # what it would send, sending nothing
tp-proxy run proxy.yaml                        # for real
```

**Check it.** `tp-proxy verify /data/erp-in --key <public key>` checks the ERP's copy offline (`tp-proxy keygen` printed the public key); a changed line or another signer fails it with exit code 1 and names the line. A file is read once it has not changed for `settle_seconds` (2): a `--once` run started while the export is still being written passes over it, and the next run reads it.
