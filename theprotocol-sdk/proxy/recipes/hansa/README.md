# HANSA: gate-out events to attestations, the ERP receives the chain

The HANSA blueprint (port logistics) as a TheProtocol Proxy recipe: `proxy.yaml` here, a fake of the legacy
system in `fake/`, run on the sandbox end to end before it shipped.

**The legacy side.** The terminal operating system posts each gate event, HMAC-signed with `GATE_HMAC`, to `/in/gate`.

**On TheProtocol.** Each gate-OUT becomes a `hansa.gate_out` attestation, and the ERP's API receives one signed POST per event, the record's key as its `Idempotency-Key`.

**What it needs.** An agent with the `attestor` role; `GATE_HMAC` shared with the TOS, `ERP_HMAC` with the ERP; the ERP's endpoint written in the sink's `url`. Credentials come from the agent's starter files (`.env`, `.env.secret`) by reference;
none is written in the spec.

**Try it locally.** `python fake/mock_erp.py --listen 127.0.0.1:8720` is an ERP that checks the signature and keeps each event once; `python fake/fake_tos.py http://127.0.0.1:8711/in/gate --count 6` posts six events (two gate-INs, not attested). Then:

```
tp-proxy validate proxy.yaml
tp-proxy run proxy.yaml --dry-run            # what it would send, sending nothing (Ctrl-C to stop: a receiver never finishes, so --once does not end here)
tp-proxy run proxy.yaml                        # for real
```

**Check it.** The ERP's file (`erp-received.jsonl`) holds each gate-out once; the attestations are on the agent's record.
