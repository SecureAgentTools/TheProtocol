# sql-to-postgres: customers from an old SQL table to PostgreSQL

A free starter template for `tp-proxy migrate`: `migration.yaml` and `proxy.yaml` here, a synthetic sample in
`sample/`, stand-ins for both systems in `fake/`.

**What it moves.** One table of customers (PostgreSQL, MySQL, SQL Server or SQLite) into `public.customers` on
PostgreSQL, one row to one row, upserted by the old id (`id` becomes `legacy_id`). On the way: the name is trimmed
(the old system padded it), a date written `dd.mm.yyyy` becomes a real `date`, a one-letter status code becomes a word
(`A` active, `I` inactive, `B` blocked; case and spaces do not matter), the address is lower-cased. A row whose date
is not `dd.mm.yyyy` or whose status code is none of the three is refused, named in the report with its reason, and
not written: fix it in the old system and load again.

**What it needs.** On the old system, a login that may only read the customers table. On PostgreSQL, the table
(`fake/target_postgresql.sql`) and a login allowed to INSERT, UPDATE, SELECT and DELETE it and nothing else. Install
the proxy with the driver of each engine you use: `pip install "theprotocol-sdk[proxy-postgresql]"` (add
`proxy-mysql` or `proxy-sqlserver` for such a source; SQLite needs none). Passwords are given as references only,
`env:NAME` or `file:/path`, never as values: `--set SOURCE_PASSWORD=env:LEGACY_DB_PASSWORD --set
TARGET_PASSWORD=env:TARGET_DB_PASSWORD` (a dry run on the sample needs neither).

**Try it free.** No account and no system at all; the dry run reads the sample and writes only under `.migrate/`:

```
pip install "theprotocol-sdk[proxy]"
tp-proxy migrate check proxy/migrations/sql-to-postgres
tp-proxy migrate dry-run proxy/migrations/sql-to-postgres --sample
```

The sample has 480 customers, 7 of them refused on purpose (4 dates that are not `dd.mm.yyyy`, 3 unknown status
codes), so the report shows what a refusal looks like. Then against your own old system, still writing nothing to
the new one: `tp-proxy migrate dry-run proxy/migrations/sql-to-postgres --params my.params` (KEY=VALUE lines, for
example `SOURCE_ENGINE=mysql`, `SOURCE_HOST=...`, `SOURCE_PASSWORD=env:LEGACY_DB_PASSWORD`).

**The real run.** `load` first lists every place the rows go and who named it (you, with `--set` or `--params`, or
the template's own default); read the list, then confirm it with `--confirm-destinations`. A kit fetched from the
library refuses a destination its template named until you set that parameter yourself. From the SDK's folder (`K` is the kit; a `.migrate/` folder in it keeps the state and the reports).
Working files (databases, exports, `my.params`) stay outside the kit's folder: a kit holds its own text files only,
and `load` refuses a folder holding anything else. Rehearse on files first:

```
K=proxy/migrations/sql-to-postgres; mkdir -p try
python3 $K/fake/make_legacy.py $K/sample/customers.jsonl try/legacy.db
python3 $K/fake/make_target.py try/target.db
export LEGACY_DB_PASSWORD=unused-by-sqlite TARGET_DB_PASSWORD=unused-by-sqlite
printf 'SOURCE_PATH=try/legacy.db\nSOURCE_PASSWORD=env:LEGACY_DB_PASSWORD\nTARGET_ENGINE=sqlite\nTARGET_PATH=try/target.db\nTARGET_TABLE=customers\nTARGET_PASSWORD=env:TARGET_DB_PASSWORD\n' > try/my.params
tp-proxy migrate plan      $K --params try/my.params    # rows and fields per source, fields with no source
tp-proxy migrate load      $K --params try/my.params --confirm-destinations   # exactly once, resumable, old rows kept
tp-proxy migrate reconcile $K --params try/my.params    # both sides read back, compared by id and legacy_id
```

Then against your own systems: a `my.params` naming your old database (`SOURCE_ENGINE`, `SOURCE_HOST`,
`SOURCE_DATABASE`, `SOURCE_USER`, `SOURCE_TABLE`) and PostgreSQL (`TARGET_HOST`, `TARGET_PORT`, `TARGET_DATABASE`,
`TARGET_USER`), the two passwords as references, the table made from `fake/target_postgresql.sql`; the same three
commands, and `tp-proxy migrate certify $K --identity proxy.yaml` for a migration certificate on the ledger.

**Check it.** `reconcile` passes with missing, extra and mismatched all 0 on the three fields it compares (the name,
the date and the status, after the mapping's cleaning). The way back:
`tp-proxy migrate rollback $K --yes --params try/my.params` puts every row the load changed back as it was and
deletes the rows that were not there before; the next load starts from the beginning again.