# Migrate a System

**Checked against the source** on 2026-11-14: the SDK's `theprotocol/proxy/migrate/` (the `tp-proxy migrate` commands, the kit schema, the reports, the reconcile, the destinations check), the three writers in `theprotocol/proxy/sinks/` and the mapping's value nodes in `theprotocol/proxy/mapping.py`, as of the V0664 SDK chain. Every command below was run as printed against that source, on the kit's own sample data and on a SQLite file standing in for the old system and another for the new one, with the output copied from the run (a path is shortened to `…`). The template library's `publish` and `get` were run against the sandbox registry as a bonded agent, and its purchase, the sale of a fork, `certify` and the start of a workflow were driven there with three agents of three different developers (the supply delta read 0.0 on both ledgers after each money step). The commands are in SDK 0.9.0; the proxy itself has been on PyPI since 0.8.0. The load speed is a measurement of the same chain on PostgreSQL 16 (see How Fast It Is).

## Why It Matters

The proxy of the previous chapter sits beside a legacy system and bridges it: the system stays, and what it writes becomes attestations and payments on TheProtocol. Often the better answer is to replace the system. Its data then has to move, and moving it is where projects lose weeks: a spreadsheet of field names, a one-off script nobody can run twice, a count at the end that nobody trusts.

`tp-proxy migrate` is that move as a kit you can run, check and hand on. A kit says where the data is now (system A), where it goes (system B) and how each field changes on the way. The engine reads A, maps each field, writes B once per row, reads both sides back and compares them, and at the end signs a certificate that names every report it rests on. The engine is free and open source, and a dry run on a kit's sample data needs no account and no system at all.

## Try It Free

Three commands, on your own machine, with nothing connected. The first installs the SDK with the proxy, the second writes a kit with sample data for a table-to-table move, the third runs that kit on its sample:

```bash
pip install "theprotocol-sdk[proxy]"
tp-proxy migrate new my-move --from sql --to sql
tp-proxy migrate dry-run my-move --sample
```

The second prints the kit's files and its content hash. The third prints:

```text
dry_run (sample): pass
  source old: 3 rows, fields created_at, email, id, name
  mapping customers: taken 3, mapped 3, rejected 0
  target new (scratch): written 3, unchanged 0, failed 0, waiting 0
  reconcile customers: pass: source 3, target 3, missing 0, extra 0, mismatched 0
  report: …/my-move/.migrate/reports/dry_run-20261114T144255137596Z.json
```

The dry run wrote only under `my-move/.migrate/scratch/`: the target was a scratch copy with the new system's columns, never a real database, and nothing was sent to TheProtocol. The sample is synthetic. The exit code was 0.

Three ready kits are free to start from: `sql-to-postgres` (a customers table into PostgreSQL), `csv-to-postgres` (a folder of CSV order exports into PostgreSQL) and `sql-to-rest` (a products table into a REST API). Each runs `dry-run --sample` with no account and no system, and refuses a few sample rows on purpose to show its reasons. From SDK 0.10 they are in the pip package, one command away and offline (SDK 0.9.0, the one on PyPI until 0.10 is released, does not have them: see below). `new --list-starters` names the three, and `new --from-starter` writes one to a folder (`./NAME` by default):

```text
$ tp-proxy migrate new --list-starters
sql-to-postgres  Customers from an old SQL table to PostgreSQL
csv-to-postgres  Order exports (CSV files) to PostgreSQL
sql-to-rest      Products from an old SQL table to a REST API
$ tp-proxy migrate new --from-starter sql-to-postgres my-move
kit: …/my-move
starter: sql-to-postgres
files: ["README.md", "fake/make_legacy.py", "fake/make_target.py", "fake/target_postgresql.sql", "fake/target_sqlite.sql", "migration.yaml", "proxy.yaml", "sample/customers.jsonl"]
content_hash: cd7dafaca8b6f8d45c99ecad2457876c18d6fb25a34b0bbe711aa684ca497edb
next: ["tp-proxy migrate check …/my-move", "tp-proxy migrate dry-run …/my-move --sample"]
```

Both exited 0. The files are the repository's, one for one (a test builds the package and compares them byte for byte). `new --from-starter` never writes over a folder that holds anything: run again on `my-move` it printed `…/my-move is not empty (--force writes over it)` and exited 1. A name that is not one of the three exits 2 and names them: `'sql-to-oracle' is not a starter kit: the starters are sql-to-postgres, csv-to-postgres, sql-to-rest`. Both commands take `--json`. A dry run of the written kit on its sample moved 473 of 480 rows, refused 7 (4 for `signed_up`, a date not in the format `%d.%m.%Y`, and 3 for `status`, no map entry and no `map_default`), and its reconcile passed; the exit code was 0.

Before 0.10, and anywhere you do not have the package, they are in two places: the repository, under `theprotocol-sdk/proxy/migrations/`, and EU's template library (`#/migrate` on eu.theprotocol.cloud), where `tp-proxy migrate get <id> --registry https://eu.theprotocol.cloud --out <folder>` downloads one without an account.

::: tip Exit codes
`0` the step passed or is done. `1` a check failed or was refused. `2` a usage or spec error. `3` not measured: the step could not compare, and says what was missing. Every command takes `--json` and prints its answer or report as JSON on stdout.
:::

## The Kit

A kit is a folder:

| file | |
|---|---|
| `migration.yaml` | required: the manifest (below) |
| `proxy.yaml` | required: a proxy spec (version 1) that reads system A and writes system B; `${NAME}` placeholders name the manifest's parameters |
| `README.md` | required: what it moves, what it needs, and the way back if the rollback is manual |
| `sample/<file>` | one file of synthetic data for each source, so that anyone can try the kit free; never real data |
| `LICENSE` | optional: the author's terms |

The caps, checked by the command and again by a registry that stores a kit: at most 64 files, each at most 256 KiB and 2 MiB in all, UTF-8 text only, and paths of letters, digits, dot, underscore and hyphen (no `..`, no leading slash or dot).

The manifest of the scaffold above:

```yaml
schema: theprotocol.migration/v1
name: my-move
title: Customers from a SQL table to PostgreSQL
summary: One table to one table, written by the old id
from: {kind: sql, what: a customers table}
to: {kind: sql, what: a customers table}
parameters:
  SOURCE_PATH: {description: 'the old SQLite file (another engine: edit the source)', default: legacy.db}
  TARGET_HOST: {description: the new database server, default: localhost}
  TARGET_DATABASE: {description: the new database, default: app}
  TARGET_USER: {description: a login limited to the target table, default: tp_migrate}
  TARGET_PASSWORD: {description: its password, secret: true}
  TARGET_TABLE: {default: public.customers}
load:
  mappings: [customers]
  batch_rows: 1000
reconcile:
  - mapping: customers
    source: {key: [id], fields: [name, email, created_at]}
    target: {key: [legacy_id], fields: [full_name, email, created]}
    pairs: {name: full_name, email: email, created_at: created}
sample:
  old: {file: sample/customers.jsonl, format: jsonl}
cutover:
  checklist: [Stop writes to the old system, Load again (only changes move), Reconcile again, Point the readers at the new system]
rollback: auto
```

| field | what it holds |
|---|---|
| `name`, `title`, `summary` | the template's identity: a lower-case name of letters, digits and hyphens, and the words a gallery shows |
| `from`, `to` | the kind of each side (`sql`, `file` or `rest`), what it is, and for a SQL side the engines the kit supports |
| `parameters` | what a person fills in: each has a description, an optional default, an optional `enum`, and `secret: true` for a credential |
| `load` | the mappings of `proxy.yaml` that form the load, in order, and `batch_rows`: how many rows the load writes in one transaction (at most 10,000) and how many keys make a batch whose checksum a report keeps |
| `reconcile` | for each mapping: the key and the fields to read back from A, the key and the fields on B, and which field of A is compared with which of B |
| `sample` | the sample file for each source, which `--sample` reads instead of the source |
| `cutover` | the checklist a person works through when the real move happens |
| `rollback` | `auto` (a SQL target: the old rows are put back) or `manual` (the README names the way back) |
| `workflow` | optional: the steps when the template runs as a workflow (see For AI Agents) |

**Parameters and secrets.** A parameter is given with `--set NAME=VALUE` or `--params FILE` (one `KEY=VALUE` per line). A parameter whose default is a whole number or `true`/`false` takes that type (so `port: ${SOURCE_PORT}` passes a number where the spec wants one), and a value that does not parse is refused. A parameter marked `secret: true` must be given as a reference, `env:NAME` or `file:/path`, and a literal value is refused: a kit never carries a password, and neither does a report. A `--sample` run needs no secret at all.

```bash
tp-proxy migrate check my-move
```

`check` prints whether the manifest and the spec are valid with the parameters filled, the kit's content hash, how many files and bytes it holds, which parameter came from a default and which was not given, where the kit would write and read (the destinations, below) and any note about the kit. Run it before anything else; it touches nothing.

## What Moves, Field by Field

A mapping gives each target field a source field or a value node. The plain form, `full_name: $.payload.name`, copies. A value node changes the value on the way, with no code and no scripting: the steps run in a fixed order and a refusal names the field and the rule, never the value.

| key | what it does |
|---|---|
| `path` | where the value is in the record (`$.payload.name`) |
| `default`, `required: false` | a value to use, or a null to accept, when the record lacks the path |
| `null_if` | a value, or a list of them, that becomes null (`"-"`, `""`) |
| `trim`, `case` | strip spaces; `upper`, `lower` or `title` |
| `regex`, `group` | the part of the text the pattern matches, taken from the named or numbered group |
| `map`, `map_default` | translate codes (`A` to `active`); what an unlisted code becomes (without `map_default` it is refused) |
| `as` | the type: `text`, `int`, `decimal`, `float`, `bool`, `date`, `datetime` or `json` |
| `format`, `tz` | the strptime format of a date or datetime in the old system, and the zone of a datetime that has none |
| `round` | digits, half to even |
| `concat`, `sep` | several fields joined with a separator |

An example that uses all of them. The old system's row:

```json
{"id": 1, "name": "  ada example ", "email": "ADA@Example.invalid", "created_at": "05.01.2024", "balance": "1234.567", "status": "A", "phone": "tel: +49 30 1234", "city": "Berlin", "country": "DE", "note": "-"}
```

and the mapping:

```yaml
    fields:
      legacy_id: {path: $.payload.id, as: int}
      full_name: {path: $.payload.name, trim: true, case: title}
      email: {path: $.payload.email, case: lower}
      created: {path: $.payload.created_at, as: date, format: "%d.%m.%Y"}
      balance: {path: $.payload.balance, as: decimal, round: 2}
      status: {path: $.payload.status, map: {A: active, I: inactive}, map_default: unknown}
      phone: {path: $.payload.phone, regex: '\+[0-9 ]+', group: 0, default: ""}
      place: {concat: [$.payload.city, $.payload.country], sep: ", "}
      note: {path: $.payload.note, null_if: ["-", ""], required: false}
```

The dry run wrote this row to the scratch target:

```text
{'legacy_id': 1, 'full_name': 'Ada Example', 'email': 'ada@example.invalid', 'created': '2024-01-05', 'balance': '1234.57', 'status': 'active', 'phone': '+49 30 1234', 'place': 'Berlin, DE', 'note': None}
```

A row the mapping cannot map is not written and is not lost silently. With the second row's date changed to `2024-01-05`, which the format `%d.%m.%Y` does not match:

```text
a record the mapping cannot map: to the dead letters
dry_run (sample): pass
  source old: 2 rows, fields balance, city, country, created_at, email, id, name, note, phone, status
  mapping customers: taken 2, mapped 1, rejected 1
    1 x created: not a date in the format %d.%m.%Y
  target new (scratch): written 1, unchanged 0, failed 0, waiting 0
  reconcile customers: pass: source 1, target 1, missing 0, extra 0, mismatched 0
```

The refusal names the field (`created`) and the rule, and counts how many rows it applied to; no value is in the report. Read the `rejected` line before you read the verdict.

::: warn Money as decimal text, not as a number
`as: decimal` gives the exact digits as text (`"1234.57"`): in a SQL column the database turns it into its numeric type with those digits, and at a REST or JSONL target it is a JSON string. `as: float` gives a JSON number, exact to 15 significant digits, for a target that needs a number. A money amount should be a decimal: a plain binary number cannot hold `0.1` exactly.
:::

## The Three Writers

A kit writes system B with one of three sinks. Each receives the mapped fields of one record at a time and each keeps the proxy's promise that a record is written once, however often it is read.

**`sql_upsert`** writes a row by its key into PostgreSQL, MySQL, SQL Server or SQLite: `INSERT ... ON CONFLICT`, `ON DUPLICATE KEY UPDATE` or `MERGE` as the engine has it, every value a parameter, every name checked and quoted.

| config | |
|---|---|
| `engine`, `host`, `port`, `database`, `user`, `password` (a reference), or `path` for SQLite | the connection; `connect_args` carries a driver's other settings, such as TLS |
| `table`, `key` | the target table, with its schema if it needs one, and the unique key columns: the row a record is |
| `columns` | an allow-list: only these columns are written |
| `on_conflict` | `update` (the default) or `skip` |
| `preimage` | `true` (the default): keep each key's first row, which is what the rollback restores |

**`rest`** sends the mapped fields as the body of an HTTP request to the new system's API: `url` (with `{field}` placeholders filled from the mapped fields and URL-encoded), `method` (`POST`, `PUT` or `PATCH`), `headers`, `bearer`, `idempotency_header` (the record's key goes out in it; `Idempotency-Key` by default) and `reference_path` (where the id the other side made is in its answer, `$.id` by default). A 2xx is done; 408, 425, 429 and 5xx are tried again, honouring `Retry-After`; any other answer refuses the record and keeps at most 300 characters of it.

**`file_out`** writes CSV or JSON Lines files into a folder, for a system that loads files: `path`, `format`, `columns` (for CSV), `rows_per_file`, and `sftp` to upload each closed file. A file is written as `.part` and renamed once whole; the folder's `manifest.json` lists each file with its rows and SHA-256.

## Plan, Dry Run, Load, Reconcile

Against your own systems the sequence is the same four steps, each a command and each leaving a report in `KIT/.migrate/reports/`. The old system is read with a read-only login, and the new system's login is limited to the target tables.

```bash
tp-proxy migrate plan KIT       # what is in the old system, and which target fields have no source
tp-proxy migrate dry-run KIT    # the whole load into scratch targets, then the reconcile against them
tp-proxy migrate load KIT --confirm-destinations   # the real load: exactly once, and resumable
tp-proxy migrate reconcile KIT  # both sides read back and compared
```

`plan` reports the rows and fields of each source and how well the mapping covers them. `dry-run` is the load run into scratch copies under `KIT/.migrate/scratch/`, so the real target is never touched; it is the step to repeat until `rejected` reads 0. `load` writes the real target, after you have read where the rows go (below). It is exactly once per row (a crash, a restart or a second run does not write a row twice) and resumable, and for a SQL target it keeps each key's first row for the way back.

`reconcile` reads both sides back by their own logins and compares them by key with a sorted merge, row by row: it counts the keys missing on one side or the other and the rows whose compared fields differ, and keeps a checksum of each batch of keys on both sides. Before comparing it makes the two sides comparable: a datetime (and an ISO text with a zone) becomes UTC with a `Z` on both sides, since a `timestamptz` column reads back in the server's zone, and a numeric column compares by value (`10` and `10.00` are the same). The same example, run for real on a SQLite file for each system:

```text
load: pass
  source old: 3 rows, fields created_at, email, id, name
  mapping customers: taken 3, mapped 3, rejected 0
  target new: written 3, unchanged 0, failed 0, waiting 0
  writes to sqlite:…/new.db table customers  [new: set by you]
  reads from sqlite:…/legacy.db table customers  [old: set by you]
reconcile: pass
  reconcile customers: pass: source 3, target 3, missing 0, extra 0, mismatched 0
```

**Where the rows go.** Before a real load, every place the kit writes to and reads from is listed after the parameters are filled, and says who named it: you (the host, database or path came from a parameter you gave with `--set` or `--params`) or the template (a literal in `proxy.yaml`, or a parameter's default). `check` prints the list, and `load` refuses to start until you confirm it with `--confirm-destinations` (or answer yes to the list on a terminal):

```text
tp-proxy migrate: load sends your rows to the destinations below: read them, then load again with --confirm-destinations
tp-proxy migrate: writes to sqlite:…/new.db table customers  [new: set by you]
tp-proxy migrate: reads from sqlite:…/legacy.db table customers  [old: set by you]
```

The exit code was 1. For a kit you fetched from a library (`get` or `fork`) a destination the template named refuses the load even when confirmed, until you set that parameter yourself: a template from a stranger never sends your data anywhere you did not name. A dry run is safe from the start, since it writes only to its scratch copies.

A source or a writer that cannot be reached ends the command at once, naming the part and the error's class and never a value: `tp-proxy migrate dry-run` with a wrong `SOURCE_PATH` prints `source old (sqlpoll) cannot be read: the database file /nonexistent/legacy.db does not exist` and exits 1. A mapping whose writer refuses row after row stops with its breaker, and a source that fails five times in a row ends the run.

**"Not measured" is not "passed".** When a step cannot compare (a source that could not be read, a reconcile whose key is missing on one side), it says so and exits with `3`; it never reports a pass for something it did not measure. The certificate refuses unless the reconcile passed.

::: info The cutover
The manifest's `cutover` checklist is what a person works through when the real move happens: stop writes to the old system, load again (only what changed moves), reconcile again, and point the readers at the new system. A load can be repeated as often as needed before that; a key already written is written once.
:::

## How Fast It Is

Measured on 2026-11-15 on the SDK of V0666, on one 12-core server with nothing heavy running beside it, with 100,000 synthetic rows from PostgreSQL 16 through the starter kit for a SQL table (`batch_rows: 1000`):

| step | target | time | rate |
|---|---|---|---|
| load (a read-only login on the old system; an upsert with each key's first row kept for the way back) | PostgreSQL 16 | 33 s | about 3,000 rows per second |
| load, the same source | SQLite | 27 s | about 3,700 rows per second |
| reconcile of the same 100,000 rows | PostgreSQL 16 | 9 s | about 10,700 rows per second |
| load with `batch_rows: 1` (every row its own transaction) | PostgreSQL 16 | 372 s | about 270 rows per second |

So 100,000 rows take about half a minute to load and 10 seconds to reconcile; a million rows would take about six minutes. The load writes in batches: up to `batch_rows` rows (at most 10,000) go into the target in one transaction, and the proxy's state file records the batch in a few transactions, not one per row. A source that reads a page of rows or a whole file at once (the SQL source, the file drop) hands them over a batch at a time. Every other source hands over one row at a time. The load stays exactly once and resumable: a run that is stopped at any point loses nothing and repeats nothing, and a row the target refuses is set aside alone while the rest of its batch is written. Plan for the figure above, measure your own systems with the dry run (it runs the same path into scratch copies), and run the first real load on a copy. These are measurements of one setup, not a guarantee.

## The Way Back

A kit's `rollback` says which kind it has.

**`auto`** is for SQL targets: `load` kept the first row of every key it wrote (or the fact that the key had none) in its state file, before the write committed. `rollback` puts them back, newest first, and deletes the rows the load created. It asks for `--yes`:

```text
tp-proxy migrate: rollback puts the target's rows back as they were before the load: give --yes
rollback: pass
  target new: written 0, unchanged 0, failed 0, waiting 0
  restored 3 rows
```

After the rollback the target is as it was, and a reconcile says so by failing, with the three rows missing:

```text
reconcile: fail
  reconcile customers: fail: source 3, target 0, missing 3, extra 0, mismatched 0
```

The load's state file is archived as `state.rolled-back-<UTC>.db`, so the next load starts fresh and keeps its first rows again.

**`manual`** is for a REST or file target, where nothing can be put back by the engine: `rollback` refuses and names the kit's README, which must say how to undo the load for that system (delete the created records, drop the loaded file).

## The Certificate

`certify` makes the proof, and refuses unless there is a load report, a reconcile report that passed and is newer than the load, and every report is for this version of the kit (its content hash):

```bash
tp-proxy migrate certify KIT --identity proxy.yaml
```

It sends an attestation of the type `migration.certificate` to the registry as the agent named in the identity file, the only step of the move that calls TheProtocol. Its claim names the template (the content hash of the kit), the hash of each report it rests on (the inventory, the dry run, the load and the reconcile), the verdict, how many rows moved and how many were rejected, and when it finished. A report holds counts, field names and hashes and never a value, so the certificate can be shown to a customer, an auditor or a regulator without showing a single customer's data.

`certify` keeps the exact data it submitted in `KIT/.migrate/certificate.json`, beside the attestation's id. If the kit came from a library, it also posts the id and that data to the template's page; its answer says in `library` whether the run was counted or why not.

The proof is checked without us. A report's `report_sha256` is the SHA-256 of the report's canonical JSON (sorted keys, no spaces, UTF-8) without that field, and the certificate's claim names the hash of each report it rests on. This script, run in the kit's folder, recomputes every report's hash and compares each with the claim:

```python
import glob, hashlib, json

def canon(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

claim = json.load(open(".migrate/certificate.json"))["attestation_data"]["claim"]
named = set(claim["reports"].values())
for path in sorted(glob.glob(".migrate/reports/*.json")):
    report = json.load(open(path))
    held = report.pop("report_sha256")
    ok = hashlib.sha256(canon(report)).hexdigest() == held
    print(path, "holds" if ok else "CHANGED", "(in the claim)" if held in named else "")
```

A report that was edited after the fact prints `CHANGED`, and a claim that names a hash no report has shows as a hash with no `(in the claim)` line. The registry holds the SHA-256 of the same attestation data, so a changed claim fails at once too.

## The Template Library

A kit written for one move works for the next person with the same two systems. A registry that has the template library switched on (`WORKFLOW_TEMPLATES_ENABLED`; its public registry configuration says `workflow_templates_enabled`, and while it is off the routes answer 503) keeps kits as templates: anyone can publish one, free or for a price, and anyone can fork one.

```bash
tp-proxy migrate publish KIT --identity identity.yaml --visibility public --price 1 --changelog "first version"
tp-proxy migrate get wtpl_… --registry https://api.theprotocol.cloud --out my-copy
```

`identity.yaml` is a spec that names the registry and the publishing agent by references (`agent_did`, `client_id` and a `client_secret` that is a `file:` or `env:` reference, as in the proxy's own spec). Publishing a kit as a bonded agent at a price of 1 printed:

```text
template_id: wtpl_e92d4f66e080aff2c53a
version: 1
content_hash: 31fcaf21d4e7069f664469a25654b8d7e16b95f12fd6b0227f6173d1a3d2dc49
created: True
```

and the exit code was 0. Without a credential, the registry's list (`GET /api/v1/workflow-templates`) and a template's page (`GET /api/v1/workflow-templates/{id}`) answer, and a paid template's kit answers 402. `get` says so, and says what to do:

```text
tp-proxy migrate: the template wtpl_e92d4f66e080aff2c53a is paid: buy it first (as the agent --identity names)
```

The exit code was 1. As the owner, `tp-proxy migrate get wtpl_… --identity identity.yaml --out getown` wrote the four files of the kit, printed the template's id, version and content hash, and suggested the dry run on the sample; the exit code was 0.

`publish` creates a template from the kit (visibility `public` and free unless you say otherwise), or, for a kit that was published or fetched from a library before (the folder remembers it in `.migrate/template.json`), adds the kit as a new version of that template; either way it publishes the version, and `--visibility`, `--price` and `--fork-share-bps` change the listing. `get` downloads a version's kit (the current one, or `--version N`), checks its content hash and writes the files to `--out`; it needs `--identity` (the agent whose units pay) only for a paid template. `fork` makes a fork in the library and then gets its kit (see Forks below).

- **Who sees a template.** Its visibility is `public` (everyone, and the gallery), `unlisted` (anyone who has its id), `org` (the agents of its organization) or `private` (its owner). A draft version is the owner's alone.
- **A bond to publish.** Publishing a template, or giving it a price, needs the agent that does it to hold a reputation bond, the registry's gate to providing anything to others. A draft needs none and neither does a fork, so you can write and try a template, and fork one, before you bond.
- **Free or paid.** The author sets the price or leaves it free, and a template's page shows its structure either way: the steps, the parameter names, the kinds of connector, the number of mapped fields. A free, visible template's files are visible to everyone; a paid one's files are for its owner and its buyers, and anyone else asking for them gets 402 with a pointer to the purchase. A version, once published, never changes again: a change is a new version, and each one carries the content hash that `get` checks.
- **What a buyer gets.** The kit, in full, and the right to fork it. A purchase is made once per buyer (a second one answers that it is already bought) as the agent that holds the units, through the registry's escrow: the buyer's price is deposited and paid out to the author, with no fee, and a purchase the escrow cannot take (not enough units) is refused with 402 before anything moves. There is no purchase command in `tp-proxy migrate`: a buyer buys in the console or with the MCP tool `theprotocol_purchaseWorkflowTemplate`, and then `get` works.
- **Forks.** A fork is a private, free copy of the parent's current version, made by an agent that may use the parent (free, its own or bought) and holds the `contract.template.publish` permission; it names its parent. It is made with `tp-proxy migrate fork <id> --identity <proxy.yaml>` (the copy's slug is the parent's with `-fork`, or `--slug NAME`; the same command run again returns the same fork), or with the MCP tool `theprotocol_forkWorkflowTemplate` (the template's id; a `slug` for the copy is optional, made from the parent's like the CLI's when left out, and is a lower-case name of 2 to 119 letters, digits and hyphens), which answered, for a template of mine, `{"template_id": "wtpl_b67e9760719d6fb679c6", "version": 1, "forked_from": "wtpl_e92d4f66e080aff2c53a", "forked_from_version": 1, "published": false}`: a private draft that is yours to change and publish. The parent's author sets the share of each sale of a fork that goes back to them, in basis points (0 to 5000, 2000 by default), and a sale of the fork pays the fork's author the rest. One level of parent only.
- **Certified runs.** After a run that passed, `certify` makes the attestation and, for a kit from a library, also sends it to the template's page; its answer says in `library` whether it was counted or why not. A run that passed on sbx-alpha (473 rows moved, 7 rejected, the reconcile passed) printed the attestation's id and `"library": "counted"`, and the template's certified count went from 0 to 1; the registry counts distinct developers, not runs, so a second run by the same developer does not raise it.
- **No copy protection.** A kit is text. Whoever holds it can read it and copy it; a price pays for the author's work and the maintenance of the template, not for a secret. Do not put anything in a kit you would not give to a buyer.

A registry refuses a kit that breaks the caps, that fails the manifest's schema or its checks, that carries a secret value where a credential belongs, or that names a destination of its own, and it names the file, the field and the rule, never a value. A destination is any host, address or path in a source or a sink (a REST `url`, a database `host`, `database` or `path`, a `file_out` folder or SFTP host, a file drop's folder): in a published kit each one must be a `${PARAMETER}` the manifest declares, a default for a host, address or path may be local only (`localhost`, `127.0.0.1`, `::1` or a relative path inside the kit), and after a URL's parameter only a path or a query may follow.

## For AI Agents

An IT department's agents can run all of it. Every command answers `--json`: a report is a JSON document with the same fields as the text shown above, and the exit code carries the verdict, so an agent branches on `3` (not measured) as it does on `1` (failed). The template library has MCP tools alongside the commands. `theprotocol_listWorkflowTemplates` and `theprotocol_getWorkflowTemplate` read the library's public routes, which need no credential. They take no agent JWT (the MCP endpoint itself still wants a bearer token on every call, as for every tool); on sbx-alpha the list with `kind` set to `migration` returned the library's templates, and the page of an id that does not exist answered the tool error `HTTP 404: no template with that id`. `theprotocol_getWorkflowTemplateVersion`, `theprotocol_purchaseWorkflowTemplate`, `theprotocol_forkWorkflowTemplate`, `theprotocol_instantiateWorkflowTemplate`, `theprotocol_createWorkflowTemplate` and `theprotocol_publishWorkflowTemplateVersion` act as the agent whose JWT is given. A template can also run as a workflow: its manifest's `workflow` section names the steps (a dry run by a runner, a reconcile by a different agent), and `theprotocol_instantiateWorkflowTemplate` (or the registry's instantiate route) starts a V0663 workflow draft from it, given a total budget: each step's budget is its share of the total, the draft carries the template's id, version and content hash, and nothing is posted until the workflow is advanced; its steps are Guild orders. The independent reconcile is the point: the agent that loaded the data is not the one that says the data arrived.

## Safety

- **A read-only login on the old system.** The source is only read. Give it a login that cannot write.
- **A login limited to the target tables on the new one.** The writers need to insert and update the table in `table` and nothing else.
- **The data stays on your machines.** The engine runs where you run it. A registry sees the template, the certificate and the report hashes; it never sees a row.
- **Reports carry no values.** A report holds counts, field names and hashes; a refusal names the field and the rule.
- **A template never sends your data anywhere you did not name.** A published kit names no destination of its own. `load` lists every destination the kit would write to or read from, says who named each, and starts only when you confirm the list; for a kit from a library it refuses a destination the template named until you set that parameter yourself with `--set`.
- **A kit from a stranger cannot act as your agent or move value.** A kit's `proxy.yaml` holds no action and no `theprotocol_events` source, and its sinks are `sql_upsert`, `file_out` or `rest` only. A kit reads system A and writes system B and nothing else; the one step that calls TheProtocol, `certify`, is yours and uses your identity file.
- **Read before you load.** A kit is text: read `proxy.yaml` and the README, and run the dry run on the sample first.
