# Migration templates: free starters

Three kits for `tp-proxy migrate` (V0664, "Migrate a system"), each a folder holding `migration.yaml` (the manifest,
schema `theprotocol.migration/v1`), `proxy.yaml` (the proxy spec that reads the old system and writes the new one),
`README.md`, a synthetic `sample/` (invented rows, a few refused on purpose so a dry run shows its reasons) and
stand-ins for both systems in `fake/`. Each one runs a dry run on its sample with no account and no system at all:

```
# from 0.10 the kits are in the pip package: one command writes one to a folder (offline), and tp-proxy migrate new --list-starters
# names the three; in 0.9.0 and before, clone the repository for them, or take the same kits free from EU's library
# with  tp-proxy migrate get <id> --registry https://eu.theprotocol.cloud --out <kit>
pip install "theprotocol-sdk[proxy]"
tp-proxy migrate new --from-starter sql-to-postgres my-move
tp-proxy migrate check   my-move
tp-proxy migrate dry-run my-move --sample
# in a clone of the repository the same kits are where they have always been
tp-proxy migrate check   proxy/migrations/<kit>
tp-proxy migrate dry-run proxy/migrations/<kit> --sample
```

| kit | from | to | rollback |
|---|---|---|---|
| [sql-to-postgres/](sql-to-postgres/README.md) | a customers table (PostgreSQL, MySQL, SQL Server or SQLite) | `public.customers` on PostgreSQL, upserted by the old id; `dd.mm.yyyy` dates, status codes, padded names | auto |
| [csv-to-postgres/](csv-to-postgres/README.md) | a folder (or SFTP folder) of CSV order exports | `public.orders` on PostgreSQL; amounts rounded to 2, local Berlin times to UTC | auto |
| [sql-to-rest/](sql-to-rest/README.md) | a products table | a REST API (`POST /products`, the record key as Idempotency-Key), read back with `GET /products` | manual |

The samples are made by `make_samples.py` (a fixed seed; run it again after changing it).

Your own: `tp-proxy migrate new <name> --from sql|file --to sql|rest` writes a kit skeleton; copy one of these and
change its mapping; `tp-proxy migrate publish` puts it in the template library, free or for a price, forkable.
