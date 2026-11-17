# csv-to-postgres: order exports (CSV files) to PostgreSQL

A free starter template for `tp-proxy migrate`: `migration.yaml` and `proxy.yaml` here, a synthetic export in
`sample/`, stand-ins for both systems in `fake/`.

**What it moves.** Every row of the CSV order exports in one folder into `public.orders` on PostgreSQL, upserted by
the order number (an export read again moves nothing twice). On the way: the amount becomes an exact decimal rounded
to 2 places (half to even), the old system's local time (`YYYY-MM-DD HH:MM`, Europe/Berlin unless `SOURCE_TZ` says
otherwise) becomes UTC, the currency is trimmed and upper-cased. A row whose amount is no number or whose time is in
another format is refused, named in the report, and not written.

**What it needs.** Read access to the export folder. On PostgreSQL, the table (`fake/target_postgresql.sql`) and a
login allowed to INSERT, UPDATE, SELECT and DELETE it and nothing else: `pip install
"theprotocol-sdk[proxy-postgresql]"`, its password as a reference (`--set TARGET_PASSWORD=env:TARGET_DB_PASSWORD`; a dry run needs none). The
exports must be complete before the run (it reads the folder once). On an SFTP server instead of a folder: install
`proxy-sftp`, replace the `exports` source with

```yaml
  exports:
    type: sftp
    config: {host: '${SFTP_HOST}', username: '${SFTP_USER}', private_key: '${SFTP_KEY}', known_hosts: '${SFTP_KNOWN_HOSTS}',
             path: '${EXPORT_DIR}', format: csv, suffix: .csv, id_field: order_no, after_read: leave, poll_seconds: 0}
```

and declare the four new parameters in `migration.yaml` (`SFTP_KEY` with `secret: true`, given as `file:/path`;
`SFTP_KNOWN_HOSTS` with no default, an absolute path to the server's host key file).
Every host and path stays a parameter, so the kit can be published (a template names no destination of its own);
`after_read: leave` keeps the files where they are, so `reconcile` can read them again, and the account needs read
access only. The sample stands in for either.

**Try it free.** No account and no system at all; the dry run reads the sample and writes only under `.migrate/`:

```
pip install "theprotocol-sdk[proxy]"
tp-proxy migrate check proxy/migrations/csv-to-postgres
tp-proxy migrate dry-run proxy/migrations/csv-to-postgres --sample
```

The sample has 360 orders, 5 refused on purpose (3 amounts that are no number, 2 times in another format). Then
against your own exports, still writing nothing to the database: `tp-proxy migrate dry-run
proxy/migrations/csv-to-postgres --set EXPORT_DIR=/path/to/exports`.

**The real run.** `load` first lists every place the rows go and who named it (you, with `--set` or `--params`, or
the template's own default); read the list, then confirm it with `--confirm-destinations`. A kit fetched from the
library refuses a destination its template named until you set that parameter yourself. From the SDK's folder (`K` is the kit; a `.migrate/` folder in it keeps the state and the reports).
Working files (databases, exports, `my.params`) stay outside the kit's folder: a kit holds its own text files only,
and `load` refuses a folder holding anything else. Rehearse on files first:

```
K=proxy/migrations/csv-to-postgres; mkdir -p try
python3 $K/fake/make_export.py $K/sample/orders.csv try/export --files 3
python3 $K/fake/make_target.py try/target.db
export TARGET_DB_PASSWORD=unused-by-sqlite
printf 'EXPORT_DIR=try/export\nTARGET_ENGINE=sqlite\nTARGET_PATH=try/target.db\nTARGET_TABLE=orders\nTARGET_PASSWORD=env:TARGET_DB_PASSWORD\n' > try/my.params
tp-proxy migrate plan      $K --params try/my.params    # rows and fields in the folder, fields with no source
tp-proxy migrate load      $K --params try/my.params --confirm-destinations   # exactly once, resumable, old rows kept
tp-proxy migrate reconcile $K --params try/my.params    # both sides read back, compared by order number
```

Then against your own exports and PostgreSQL: a `my.params` with `EXPORT_DIR`, `TARGET_HOST`, `TARGET_PORT`,
`TARGET_DATABASE`, `TARGET_USER` and the password as a reference, the table made from `fake/target_postgresql.sql`;
the same three commands, and `tp-proxy migrate certify $K --identity proxy.yaml` for a migration certificate.

**Check it.** `reconcile` passes with missing, extra and mismatched all 0 on the time, the amount and the customer.
The way back: `tp-proxy migrate rollback $K --yes --params try/my.params` puts every order the load changed back as it was
and deletes the ones that were not there before.
