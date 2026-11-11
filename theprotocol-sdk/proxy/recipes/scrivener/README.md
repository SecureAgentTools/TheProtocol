# SCRIVENER: matter events in, the DMS's evidence out

The SCRIVENER blueprint (legal services) as a TheProtocol Proxy recipe: `proxy.yaml` here, a fake of the legacy
system in `fake/`, run on the sandbox end to end before it shipped.

**The legacy side.** The practice-management system posts each matter event (opened, a filing with the filed document's SHA-256, a deadline met, closed), HMAC-signed with `PMS_HMAC`, to `/in/matters`.

**On TheProtocol.** Each event becomes a `scrivener.matter_event` attestation, and the document-management system's import folder receives the signed, hash-chained history of the matter: a court or an auditor checks it offline.

**What it needs.** An agent with the `attestor` role; an evidence signing key; `PMS_HMAC`. To mirror the evidence to an SFTP server, set the evidence sink's `mirror` (the `proxy-sftp` extra). Credentials come from the agent's starter files (`.env`, `.env.secret`) by reference;
none is written in the spec.

**Try it locally.** `python fake/fake_pms.py http://127.0.0.1:8711/in/matters --matter M-2026-0042` posts one matter's four events. Then:

```
tp-proxy validate proxy.yaml
tp-proxy run proxy.yaml --dry-run            # what it would send, sending nothing (Ctrl-C to stop: a receiver never finishes, so --once does not end here)
tp-proxy run proxy.yaml                        # for real
```

**Check it.** `tp-proxy verify /data/dms-import --key <public key>` names any changed, removed or moved line.
