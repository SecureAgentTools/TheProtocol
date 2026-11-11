# The Proxy

**Checked against the source** on 2026-11-09: the SDK's `theprotocol/proxy/` (the spec, the runtime, the outbox, the
built-in sources, actions and sinks, the command line) and its eight recipes in `proxy/recipes/`. Every command below
was run as printed against the SDK source, and each recipe was driven end to end on the sandbox with its own fake of
the system it connects (2026-11-08). The proxy is not yet in a release on PyPI: it ships with the first SDK release
after 0.7.6, and until then installs from the SDK's source.

## Why It Matters

Most of what a business would prove or settle on TheProtocol already happens in a system that knows nothing about it:
an order system that releases orders, a terminal that gates containers out, a meter that reads every quarter hour, a
mediation system that rates calls. Rewriting those systems is not an option. The proxy sits beside one: it gives the
system an agent identity on TheProtocol, reads what the system already writes (a file, a webhook, a database table, an
MQTT topic, an SFTP folder) and turns each record into a call on TheProtocol: a signed attestation, a contract
milestone's evidence, a payment under a mandate. In the other direction it hands TheProtocol's own events (a payment
received, a payment settled) to the legacy system: a signed webhook, an accounting journal, an evidence export.

You write no code. You write one file, `proxy.yaml`, and the proxy keeps three promises about it: each record is sent
once (a crash, a restart or a repeat delivery does not send it twice), a secret is never written in it, and the agent
holds only the authority its mappings need.

## Install

From the SDK's source (the `proxy` extras; `proxy-mqtt`, `proxy-sftp`, `proxy-sql` and its per-database variants add
the sources that need a client library):

```bash
pip install "./theprotocol-sdk[proxy]"
tp-proxy --help
```

The proxy runs as its own agent. Create the agent in the console (or with Agent Forge's starter) and keep its
`client_id` and `client_secret` where the spec can name them: an environment variable or a file.

## The Spec

A spec names the registry, the agent, where the proxy keeps its state, and four kinds of parts: **sources** (where
records come from), **actions** (calls on TheProtocol), **sinks** (deliveries to a legacy system) and **mappings**
(which records go where, and how their fields are built). This one attests each released order a file drop holds:

```yaml
version: 1
name: orders-to-attestations
registry: https://api.theprotocol.cloud
identity:
  agent_did: env:AGENT_DID
  client_id: env:CLIENT_ID
  client_secret: env:CLIENT_SECRET
state: ./orders-state.db
sources:
  oms:
    type: filedrop
    config: {path: ./oms-out, format: json, suffix: .json, id_field: intent_id}
actions:
  attest:
    type: attestation
    config: {attestation_type: example.order_released}
    limits: {per_minute: 60}
sinks: {}
mappings:
  - name: released
    version: 1
    from: oms
    to: attest
    when: {path: $.payload.data.status, equals: RELEASED}
    fields:
      order: $.payload.data.order_id
      sku: $.payload.data.sku
      quantity: $.payload.data.quantity
      plant: PLANT-NORTH
```

```bash
tp-proxy validate proxy.yaml
```

`validate` checks the spec against the core's schema and every part's configuration against its own, and names the
first thing it refuses by its path in the file.

**References, never secrets.** A credential is written as `env:NAME` (an environment variable), `file:/path` (a file's
content) or `file:/path#KEY` (one `KEY=value` line of a dotenv file, such as the starter's `.env.secret`). A literal
value where a secret belongs is refused when the spec loads.

**Mappings.** `from` names a source; `to` names an action (inbound) or a sink (outbound). `when` takes one condition on
the record: `{path, equals}`, `{path, in}` or `{path, exists}`. Each field is a JSONPath into the record
(`$.payload...`), a literal, or `{path, default}` for a field a record may lack. A mapping's `version` is part of every
record's key: raise it when a mapping changes what it sends, and a record read again (a `run --replay` of a source
from an earlier point) is sent under the new meaning instead of being taken for the one already sent.

**What a source hands a mapping.** A file drop and an SFTP folder: `{file, row, data}` (SFTP adds the file's `sha256`),
the row under `data`, every CSV value a string. A webhook: the posted body. MQTT: `{topic, levels, data, encoding}`. An
SQL poll: the row itself. TheProtocol's own events: the event's data.

## Exactly Once

Every record a mapping takes becomes one row in the proxy's outbox (SQLite, in `state`) under a key built from the
source, the record's id, the mapping and its version. The row is written before anything is sent, and it is sent with
its key as the `Idempotency-Key`. A record read twice (a file read again after a restart, a webhook retried by its
sender, an MQTT message delivered again) finds its key already there and is not sent twice. A crash between the send and
the outbox's "done" sends the row again on the next start; the registry answers a repeated key with its first answer, so
it is still once. Measured on the sandbox: a proxy stopped between sending an attestation and marking it done sent it
again on restart, and the registry held the same eight attestations, not nine.

What could not be sent stays in the outbox and is retried with backoff (`retry`); what the other side refuses outright,
or what is still failing after the last attempt, becomes a dead letter:

```bash
tp-proxy status proxy.yaml          # the outbox, the switches, each mapping's breaker
tp-proxy dead proxy.yaml            # the dead letters, each with its reason
tp-proxy replay proxy.yaml --key <key>   # send one dead letter again (or --mapping NAME, or --all)
tp-proxy pause proxy.yaml released  # stop sending one mapping's rows (resume undoes it); without a name: all
```

A mapping whose calls keep failing is stopped by its **breaker** (`breaker: {refusals, failures, cooldown_s}`) and
says why in `status`, instead of turning a whole backlog into dead letters.

## Running It

```bash
tp-proxy run proxy.yaml --dry-run --once   # map and print what it would send, send nothing
tp-proxy run proxy.yaml                    # for real, as a service (/health and /metrics on service.listen)
```

`--once` stops when every source has finished and nothing is due. A file drop finishes when it has read the files that
are there; an SFTP folder or an SQL table finishes only with `poll_seconds: 0` (read once); a receiver (a webhook,
MQTT, TheProtocol's events) never finishes, so a spec with one runs until stopped, dry or not. A file is read once it has
not changed for `settle_seconds` (2 by default) or once its marker file exists (`require_marker`): a `--once` run started
while an export is still being written passes over it, and the next run reads it.

## Least Authority

The proxy's agent holds only the permissions its mappings need. `tp-proxy init` writes a spec from the agent's
starter folder and asks the registry about the agent: that it issues the agent a token, the agent's card and bond, and
the permissions each action needs, which the owner grants in the console (the agent's access panel). An attestation
needs `reputation.signal` (the `attestor` role carries it and nothing else); a call the agent may not make is refused
by the registry and becomes a dead letter that names the refusal. A milestone's evidence is delivered as the
contract's provider.

A **payment** needs three things the owner sets in the console, and the proxy refuses to start without them: a Cockpit
mandate for `a2a.pay` named in the action's `mandate:`, the agent's spend cap at or under that mandate's limits, and
the action's own `max_amount` (and optionally `per_day`). A record over `max_amount` is never paid: it becomes a dead
letter. Each payment is authorized under the mandate (`X-Liability-Mandate`) and settled with the record's key as its
task id, so the registry's `payment.settled` notice names the record it paid.

## Evidence You Can Check Without Us

The `evidence` sink writes each record it receives as a line of a hash chain (each line names the hash of the one
before) and signs a manifest of the files with an Ed25519 key you hold. Anyone with the folder and your public key
checks it offline:

```bash
tp-proxy keygen ./evidence.pem      # prints the public key
tp-proxy verify ./erp-in --key <public key>
```

`verify` answers `holds: true` with the line count and the chain's head, or `holds: false` naming each problem, with
exit code 1: a line that was changed (its own hash no longer matches, nor the manifest's hash of its file), an evidence file
(`evidence-*.jsonl`) missing or one the manifest does not name, a file with more or fewer lines than the manifest says, or a manifest signed
by a key other than the one you named.

## The Built-In Parts

| kind | type | what it does |
|---|---|---|
| source | `filedrop` | rows of CSV, JSON, JSON Lines or XML files in a folder |
| source | `sftp` | the same from an SFTP server: key login, the host key pinned in `known_hosts`, each file moved or marked once read |
| source | `sqlpoll` | new rows of a table past a cursor column (SQLite; PostgreSQL, MySQL and SQL Server with the `proxy-sql` extras) |
| source | `mqtt` | messages on topic filters (QoS 1, a kept session) |
| source | `webhook` | JSON posted to a path, checked against an HMAC-SHA256 signature |
| source | `logtail` | new lines of a log file, across rotation |
| source | `theprotocol_events` | the registry's own webhooks (`payment.received`, `payment.settled` and the rest), checked against the webhook's secret |
| action | `attestation` | a signed fact, its data hashed onto the ledger |
| action | `milestone_evidence` | a contract milestone's delivery, as its provider |
| action | `payment` | a payment under a mandate, never above `max_amount` |
| action | `a2a_task` | an A2A call to another agent |
| action | `chat_message` | a message in a chat room |
| sink | `webhook` | a signed POST to the legacy system (`X-Signature-256`, the record's key as `Idempotency-Key`) |
| sink | `journal` | accounting lines as CSV, or camt.053 for accounting systems that import account statements |
| sink | `evidence` | the signed hash chain above |
| sink | `calendar`, `email_digest` | an ICS calendar file, one event per delivery; a digest of the deliveries by mail at an interval |

## Eight Recipes

The SDK's `proxy/recipes/` holds a ready spec for each of the eight blueprints, a fake of the legacy system it connects
and a README. Each was driven on the sandbox with its fake; the two that move units kept the ledgers' supply delta at 0.

| recipe | the legacy system | on TheProtocol |
|---|---|---|
| MERIDIAN | an order system's nightly JSON export | released orders attested; each exported as signed evidence for the ERP |
| HANSA | a terminal's gate events (webhook) | gate-outs attested and sent, signed, to the ERP; gate-ins left |
| DYNAMO | smart meters over MQTT | every reading attested, its meter taken from the topic |
| BAZAAR | a shop's inventory events, and TheProtocol's `payment.received` | inventory attested; the warehouse told to fulfil only once the shop agent's payment has arrived |
| SCRIVENER | a practice-management system's matter events | a matter's life attested (a filing with its document's SHA-256) and exported as evidence |
| LYCEUM | a student-record system's CSV of awards | each awarded credential attested; a revoked one left for the console |
| KEYSTONE | a site test logger's runs on SFTP | a passed acceptance test delivered as a contract milestone's evidence; a failed run delivers nothing |
| TRUNK | a mediation system's settlement table | each rated event paid to the partner's agent under a mandate; the journal booked from `payment.settled`, so only what settled |

Try one without a registry: LYCEUM's fake writes an export and the dry run shows what would be sent.

```bash
cd theprotocol-sdk/proxy/recipes/lyceum
python fake/fake_sis.py ./sis-out --count 5 --run T1
sleep 3     # the export settles (settle_seconds is 2): a fresh file is passed over
sed -e 's#/data/sis-out#./sis-out#' -e 's#/data/lyceum-state.db#./lyceum-state.db#' proxy.yaml > local.yaml
AGENT_DID=did:theprotocol:example CLIENT_ID=example CLIENT_SECRET=example-secret-of-32-characters-x \
  tp-proxy run local.yaml --dry-run --once --no-service
```

Four of the five rows are awarded and four attestations would be sent; the revoked row is left out.

**Two things the recipes taught.** TheProtocol's webhooks are the owner's, not the agent's: an owner with several
agents receives every agent's payments, so a mapping that acts on `payment.received` or `payment.settled` names its own
agent in its `when` (BAZAAR, TRUNK). And a journal books what settled, never what was only asked for: TRUNK's first
version booked every rated row, and the sandbox drive showed a payment the proxy had refused (over `max_amount`) booked
as a debit all the same. It now books from `payment.settled`.
