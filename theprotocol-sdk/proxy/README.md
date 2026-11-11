# TheProtocol Proxy

A small process beside a legacy system that gives the system an agent identity on TheProtocol and translates in both
directions. It runs where the system runs (on premises, a VM, a Raspberry Pi), dials out only (unless you turn on its
webhook receiver), and sends only what its mapping names. The legacy system stays the operational truth; the ledger
becomes the shared record.

```
legacy system ──source──▶ [ mapping ] ──action──▶ TheProtocol      (inbound: attest, ask, pay, deliver)
legacy system ◀──sink──── [ mapping ] ◀──events── TheProtocol      (outbound: evidence, settlement, cards)
                  durable outbox · exactly-once keys · dry-run · replay · metrics
```

## Start

The proxy is an agent: create one in the console (Agent Forge's starter) and download it. The download's `.env` names
the agent and its registry; its `.env.secret` holds the agent's credentials.

```
pip install "theprotocol-sdk[proxy]"
tp-proxy init --from ./my-agent        # writes ./my-agent/proxy.yaml, then asks the registry about the agent
tp-proxy validate my-agent/proxy.yaml
tp-proxy run my-agent/proxy.yaml --dry-run    # maps and prints what it would send; sends nothing
tp-proxy run my-agent/proxy.yaml
```

`init` reports what the registry says: whether the credentials work, the agent's card, its bond, and the permissions
the spec's actions need. The attestation action needs `reputation.signal`; the owner grants the `attestor` role, which
carries that and nothing else.

## The spec

One file per proxy (`proxy.yaml`; see `proxy.example.yaml`): its sources, mappings, actions, sinks and limits. A secret
is never written in it. Where the spec holds a credential it takes a reference: `env:NAME`, `file:/path` or
`file:/path#KEY` (one line of a dotenv file, such as the starter's `.env.secret`). A literal secret is refused at load,
with its path.

## What the core guarantees

- **Exactly once.** Each record's key is a hash of the source, the record's id, the mapping's name and its version. A
  record read twice is kept once. A record is in the outbox (SQLite, WAL) before its source's cursor moves. Every call
  carries the key as its `Idempotency-Key`, so a call whose answer was lost is sent again with the same key and the
  registry answers it as a repeat.
- **Dead letters and replay.** A refusal (an answer a retry will not change) moves the record to the dead letters with
  the registry's answer. `tp-proxy dead` lists them; `tp-proxy replay --all` (or `--mapping M`, `--key K`) sends them
  again after a fix. A record its mapping cannot map is dead from the start, and a replay maps it with the fixed spec.
  `tp-proxy run --replay SOURCE=POINT` makes a source read again from a point it understands.
- **A breaker per mapping.** Repeated refusals stop a mapping until `tp-proxy resume MAPPING`, and `tp-proxy status`
  says why. Repeated transient failures (the registry down) cool it down, and it tries again by itself.
- **Limits.** Each action and sink has a calls-per-minute limit (`limits: {per_minute: N}`). `tp-proxy pause [MAPPING]`
  stops sending while records are still taken in.
- **Run it like a service.** `/health` and `/metrics` (Prometheus) on `service.listen`, JSON logs with no secret in
  them, and an optional IRONHAND mTLS identity (`identity.mtls.enabled`), renewed before it expires.

## In a container

```
docker compose up -d                   # compose.yaml: proxy.yaml, and the starter's .env and .env.secret beside it
docker compose exec proxy tp-proxy status
```

The image is built for amd64 and arm64 from `theprotocol-sdk/`:
`docker buildx build --platform linux/amd64,linux/arm64 -f proxy/Dockerfile -t theprotocol-proxy:dev .`

## Connectors

Sources, actions and sinks are plugins (Python entry points in the groups `theprotocol.proxy.sources`,
`theprotocol.proxy.actions` and `theprotocol.proxy.sinks`). The interface and its rules are in
`theprotocol.proxy.plugins`, and every plugin passes the contract tests in `theprotocol.proxy.testing`. The built-ins:

| kind | type | what it does |
|---|---|---|
| source | `webhook` | an HTTP receiver for anything that can POST JSON (HMAC-signed; 202 once the record is kept) |
| source | `theprotocol_events` | the registry's webhooks: TheProtocol's events, each delivery's signature checked |
| action | `attestation` | one signed fact per record (needs `reputation.signal`: the `attestor` role) |
| action | `a2a_task` | a task to a named agent (A2A `message/send`), free agents only |
| action | `payment` | a payment authorization and its settle, only under a Cockpit mandate |
| action | `milestone_evidence` | a contract milestone delivered with the record as its evidence |
| action | `chat_message` | a message or a card into a chat thread or room |
| sink | `webhook` | each event POSTed to a system's API, the record's key as its `Idempotency-Key` |
| sink | `evidence` | hash-chained JSONL and a signed manifest (optionally mirrored to SFTP or S3) |
| sink | `journal` | accounting lines: a CSV journal, or an ISO 20022 camt.053 statement, per day |
| sink | `calendar` | an ICS calendar, one event per delivery |
| sink | `email_digest` | a digest mail of the events every interval |

## Paying, only under a mandate

A `payment` action names a Cockpit mandate (`mandate: lm_...`) and its own limits (`max_amount`, optionally
`per_day`). It does not start unless the registry answers that the mandate underwrites this agent and covers payments,
the action's `max_amount` is at or under the mandate's `max_per_tx`, and the agent has an IRONKEY spend cap that sits
at or under the mandate's limits (its owner sets one in the console). Every authorization names the mandate
(`X-Liability-Mandate`), so the registry checks that mandate for the call, its standing consents and step-ups
included, wherever it runs. Authorize and settle carry the record's key: a payment is made once.

## A quantum backend

`pip install "theprotocol-sdk[proxy-quantum]"`, then `proxy/proxy.quantum.example.yaml`. OpenQASM 3 arrives
as an event, the circuit runs, the shots are metered as they run, and each finished job is reported with its
counts.

It is **asynchronous**, and that is not a simplification. A real QPU queues — the quantum card extension
carries `queue.status` and `estimated_wait_seconds` — so there is no "circuit in, counts out" call: the
`quantum_submit` sink submits, the `quantum_results` source reads what finished, and the `quantum_report`
action reports it. A job id is the stable record id, so the core's exactly-once keys cover the whole path
and a replayed event never re-runs paid work.

```
tp-proxy quantum-card proxy.quantum.example.yaml \
    --receipt-schema-version 1.0 --receipt-signing-algorithm Ed25519
```

generates the card's quantum workload extension **from the backend's own facts**, so a provider publishes a
card it did not type and cannot forget to update. It refuses rather than inventing: a stub cloud adapter
states no device facts, and a missing receipt block names the module those constants belong to.

**What the meter proves, and what it does not.** `accurateResourceUsagePolicy/v2.0.0` binds a reported shot
count to a committed meter log. Its own limits note says a verifier compares the commitment with one the
meter *published*, and the reason is worth knowing: a provider free to choose the logged units after seeing
its own report can always satisfy the tolerance rule. So the commitment is made when the work runs, and a
job that was never metered cannot be reported at all. The claim's `log_commitment` reads `NOT_COMPUTED`
until `nargo` and `bb` are installed — the pre-image is carried so a prover can compute it, and nothing is
written under the circuit's name that this recipe did not compute itself.

**Simulators, and your own hardware.** The built-in simulator is a small pure-python state-vector
simulator: it exists so the recipe runs with nothing installed, and it is not fast. There is deliberately
no accelerated-simulator extra, because an accelerated path that cannot be tested here is one we will not
claim; `kind` takes a `"module:Class"` path to your own `Backend` instead, and the `qpu` adapters are stubs
that refuse to run. The reader refuses a gate it does not implement by name, rather than running the
circuit approximately and returning counts that look like a result.

## Evidence, checked offline

```
tp-proxy keygen /run/secrets/evidence.pem       # the export's signing key; prints its public key
tp-proxy verify /data/evidence --key <public key> --webhook-secret env:TP_WEBHOOK_SECRET
```

Each event is one line whose hash covers its content and the line before, across the day files; `manifest.json`
names every file and the chain's head, embeds the registry's signed card when asked, and is signed by the proxy's
key. `verify` needs no network. It names a changed, removed or moved line, a file the manifest does not list, a
manifest signed by another key than the one you expect, and, with the webhook's secret, any delivery the registry
did not sign.
