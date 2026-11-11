# LYCEUM: awarded credentials from the student-record export

The LYCEUM blueprint (education) as a TheProtocol Proxy recipe: `proxy.yaml` here, a fake of the legacy
system in `fake/`, run on the sandbox end to end before it shipped.

**The legacy side.** The student-record system exports the credentials it has awarded as a CSV (`award_id`, a pseudonymous `holder_pseudonym`, `credential`, `eqf_level`, `ects`, `awarded_on`, `status`) into `/data/sis-out`.

**On TheProtocol.** Each AWARDED row becomes a `lyceum.credential_awarded` attestation a verifier can check without asking the school. A REVOKED row is left out: revocation is a deliberate act in the console.

**What it needs.** An agent with the `attestor` role. The export names no student by name or birth date. Credentials come from the agent's starter files (`.env`, `.env.secret`) by reference;
none is written in the spec.

**Try it locally.** `python fake/fake_sis.py ./sis-out --count 5` writes one export (its last row REVOKED). Then:

```
tp-proxy validate proxy.yaml
tp-proxy run proxy.yaml --dry-run --once     # what it would send, sending nothing
tp-proxy run proxy.yaml                        # for real
```

**Check it.** The attestations are on the agent's record, one per awarded row. A file is read once it has not changed for `settle_seconds` (2): a `--once` run started while the export is still being written passes over it, and the next run reads it.
