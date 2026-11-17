"""`tp-proxy migrate new`: a kit skeleton per kind pair (sql to sql, file to sql, sql to rest), each with a synthetic
sample, so `check` passes and `dry-run --sample` runs on it as written. Every value in the samples is invented."""
from __future__ import annotations

import json
from typing import Dict

_SAMPLE_ROWS = [
    {"id": 1, "name": "Ada Example", "email": "ada@example.invalid", "created_at": "2024-01-05"},
    {"id": 2, "name": "Bert Sample", "email": "bert@example.invalid", "created_at": "2024-02-11"},
    {"id": 3, "name": "Cleo Placeholder", "email": "cleo@example.invalid", "created_at": "2024-03-19"},
]

_SQL_SOURCE = """\
  old:
    type: sqlpoll
    config:
      # postgresql, mysql or sqlserver: host, port, database, user and password (a reference) instead of path
      engine: sqlite
      path: ${SOURCE_PATH}
      table: customers
      cursor: id
      poll_seconds: 0
"""

_FILE_SOURCE = """\
  old:
    type: filedrop
    config:
      path: ${SOURCE_DIR}
      format: csv
      settle_seconds: 0
"""

_SQL_SINK = """\
  new:
    type: sql_upsert
    config:
      engine: postgresql
      host: ${TARGET_HOST}
      database: ${TARGET_DATABASE}
      user: ${TARGET_USER}
      password: ${TARGET_PASSWORD}
      table: ${TARGET_TABLE}
      key: [legacy_id]
      on_conflict: update
"""

_REST_SINK = """\
  new:
    type: rest
    config:
      url: ${TARGET_URL}
      method: PUT
      bearer: ${TARGET_TOKEN}
"""


def _readme(title: str, src: str, dst: str, rollback: str) -> str:
    back = ("rollback: auto. `tp-proxy migrate rollback --yes` puts every row the load changed back as it was "
            "(the writer kept each key's row before it wrote) and deletes the rows that were not there."
            if rollback == "auto" else
            "rollback: manual. The target is not a SQL table, so nothing is restored automatically: DELETE "
            "every object the load created (the requests carry the old id), or restore the target's backup.")
    return f"""# {title}

What it moves: the customers of {src} into {dst}, one row to one row, upserted by the old id.

What it needs:

- on the old system, a login that may only read the customers table (or the folder the export lands in);
- on the new system, a login limited to the target table.

Try it free, with no system at all:

    tp-proxy migrate check .
    tp-proxy migrate dry-run . --sample

Then against your own systems: give the parameters (`--set NAME=VALUE` or `--params FILE`; passwords as
references, `env:NAME` or `file:/path`), `plan`, `dry-run` (it writes only under `.migrate/scratch/`), `load`,
`reconcile`, and `certify` for a migration certificate on the ledger.

The way back: {back}
"""


def _manifest(name: str, title: str, from_kind: str, to_kind: str, params: str, target_key: str, rollback: str,
              sample: str, sample_format: str, target_fields: str) -> str:
    return f"""schema: theprotocol.migration/v1
name: {name}
title: {title}
summary: One table to one {'table' if to_kind == 'sql' else 'API'}, written by the old id
from: {{kind: {from_kind}, what: a customers {'table' if from_kind == 'sql' else 'export (CSV files)'}}}
to: {{kind: {to_kind}, what: {'a customers table' if to_kind == 'sql' else 'a customers API'}}}
parameters:
{params}load:
  mappings: [customers]
  batch_rows: 1000
reconcile:
  - mapping: customers
    source: {{key: [id], fields: [name, email, created_at]}}
    target: {{key: [{target_key}], fields: [{target_fields}]}}
    pairs: {{name: full_name, email: email, created_at: created}}
sample:
  old: {{file: {sample}, format: {sample_format}}}
cutover:
  checklist: [Stop writes to the old system, Load again (only changes move), Reconcile again, Point the readers at the new system]
rollback: {rollback}
"""


def skeleton(name: str, from_kind: str, to_kind: str) -> Dict[str, str]:
    title = f"Customers from {'a SQL table' if from_kind == 'sql' else 'CSV files'} to " \
            f"{'PostgreSQL' if to_kind == 'sql' else 'a REST API'}"
    src_params = ("  SOURCE_PATH: {description: 'the old SQLite file (another engine: edit the source)', default: legacy.db}\n"
                  if from_kind == "sql" else
                  "  SOURCE_DIR: {description: the folder the old system exports CSV files into, default: export}\n")
    if to_kind == "sql":
        dst_params = ("  TARGET_HOST: {description: the new database server, default: localhost}\n"
                      "  TARGET_DATABASE: {description: the new database, default: app}\n"
                      "  TARGET_USER: {description: a login limited to the target table, default: tp_migrate}\n"
                      "  TARGET_PASSWORD: {description: its password, secret: true}\n"
                      "  TARGET_TABLE: {default: public.customers}\n")
        sink, key, rollback, fields = _SQL_SINK, "legacy_id", "auto", "full_name, email, created"
        mapping_fields = ("      legacy_id: $.payload{d}.id\n      full_name: $.payload{d}.name\n"
                          "      email: $.payload{d}.email\n      created: $.payload{d}.created_at\n")
    else:
        dst_params = ("  TARGET_URL: {description: 'where each customer is PUT ({legacy_id} is filled in)', "
                      "default: 'https://api.example.invalid/customers/{legacy_id}'}\n"
                      "  TARGET_TOKEN: {description: the API's bearer token, secret: true}\n")
        sink, key, rollback, fields = _REST_SINK, "legacy_id", "manual", "full_name, email, created"
        mapping_fields = ("      legacy_id: $.payload{d}.id\n      full_name: $.payload{d}.name\n"
                          "      email: $.payload{d}.email\n      created: $.payload{d}.created_at\n")
    d = ".data" if from_kind == "file" else ""
    source = _SQL_SOURCE if from_kind == "sql" else _FILE_SOURCE
    proxy = (f"version: 1\nname: {name}\n# system to system: no registry and no identity (nothing here calls "
             f"TheProtocol)\nsources:\n{source}sinks:\n{sink}mappings:\n  - name: customers\n    version: 1\n"
             f"    from: old\n    to: new\n    fields:\n{mapping_fields.format(d=d)}")
    if from_kind == "sql":
        sample_file, fmt = "sample/customers.jsonl", "jsonl"
        sample = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in _SAMPLE_ROWS)
    else:
        sample_file, fmt = "sample/customers.csv", "csv"
        sample = "id,name,email,created_at\n" + "".join(
            f"{r['id']},{r['name']},{r['email']},{r['created_at']}\n" for r in _SAMPLE_ROWS)
    return {
        "migration.yaml": _manifest(name, title, from_kind, to_kind, src_params + dst_params, key, rollback,
                                    sample_file, fmt, fields),
        "proxy.yaml": proxy,
        "README.md": _readme(title, "the old system", "the new one", rollback),
        sample_file: sample,
    }
