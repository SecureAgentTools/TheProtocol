# KEYSTONE: a passed test run as a milestone's evidence

The KEYSTONE blueprint (construction) as a TheProtocol Proxy recipe: `proxy.yaml` here, a fake of the legacy
system in `fake/`, run on the sandbox end to end before it shipped.

**The legacy side.** The site's sensor logger exports each test run as a CSV to an SFTP server (`/exports`, a `.done` marker once complete): measurement rows, then an acceptance row (passed) or a rejection row (failed) naming the contract and its milestone.

**On TheProtocol.** A passed run's acceptance row is delivered as that milestone's evidence, by the contractor's agent (`milestone_evidence`), so the client releases the milestone payment on a measurement. A failed run delivers nothing.

**What it needs.** A contract (contracts v2) whose provider is the proxy's agent; the SFTP account's key and the server's host key (`known_hosts`). Install the `proxy-sftp` extra. Credentials come from the agent's starter files (`.env`, `.env.secret`) by reference;
none is written in the spec.

**Try it locally.** `python fake/fake_logger.py /exports --contract <id> --milestone 0 --strength 41.5` writes a passed run (35 MPa is the limit; `--strength 30` writes a failed one). Then:

```
tp-proxy validate proxy.yaml
tp-proxy run proxy.yaml --dry-run --once     # what it would send, sending nothing
tp-proxy run proxy.yaml                        # for real
```

**Check it.** The contract shows the milestone delivered, its deliverable carrying the run; a failed run delivers nothing; each file read is moved into `done/` on the server. The source polls every `poll_seconds` (60): for a one-off run (`--once`) set `poll_seconds: 0`, or `--once` never ends; the server account needs write access to the export folder for the move (without it the file stays, is named in the log, and is not read twice).
