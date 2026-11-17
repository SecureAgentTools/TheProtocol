# sql-to-rest: products from an old SQL table to a REST API

A free starter template for `tp-proxy migrate`: `migration.yaml` and `proxy.yaml` here, a synthetic sample in
`sample/`, stand-ins for both systems in `fake/` (the new system is a small products API, `fake/products_api.py`).

**What it moves.** One table of products (PostgreSQL, MySQL, SQL Server or SQLite) to a products API: one `POST
/products` per product, the mapped fields as the JSON body (`id`, `sku`, `name`, `price`, `active`), the record's key
in the `Idempotency-Key` header, so an API that keeps it answers a repeat without storing it twice. On the way: the
price, which the old system kept as text, becomes exact digits rounded to 2 places (sent as a JSON string, so no
digit is lost), the 0/1 flag becomes `true`/`false`, the SKU is trimmed and upper-cased. A row whose price is no
number or whose flag is neither is refused, named in the report, and not sent.

**What it needs.** On the old system, a login that may only read the products table (`proxy-postgresql`,
`proxy-mysql` or `proxy-sqlserver` for its driver; SQLite needs none). On the API, a token allowed to create
products, as a reference (`--set PRODUCTS_TOKEN=env:PRODUCTS_API_TOKEN`; a dry run needs none). For `reconcile`, a way to read every product back:
`migration.yaml`'s `reconcile.target.read` names it (`GET ${PRODUCTS_URL}`, the list under `items`); an API that
reads elsewhere gets a parameter of its own there, and a header whose value is a reference if the read needs one.

**Try it free.** No account and no system at all; the dry run reads the sample and sends nothing (it writes the
requests it would send to `.migrate/scratch/catalog.requests.jsonl`):

```
pip install "theprotocol-sdk[proxy]"
tp-proxy migrate check proxy/migrations/sql-to-rest
tp-proxy migrate dry-run proxy/migrations/sql-to-rest --sample
```

The sample has 240 products, 5 refused on purpose (3 prices that are no number, 2 flags that are neither 0 nor 1).

**The real run.** `load` first lists every place the rows go and who named it (you, with `--set` or `--params`, or
the template's own default); read the list, then confirm it with `--confirm-destinations`. A kit fetched from the
library refuses a destination its template named until you set that parameter yourself. From the SDK's folder (`K` is the kit; a `.migrate/` folder in it keeps the state and the reports).
Working files (databases, exports, `my.params`) stay outside the kit's folder: a kit holds its own text files only,
and `load` refuses a folder holding anything else. Against the fake first:

```
K=proxy/migrations/sql-to-rest; mkdir -p try
python3 $K/fake/make_legacy.py $K/sample/products.jsonl try/legacy.db
export PRODUCTS_API_TOKEN=try-me LEGACY_DB_PASSWORD=unused-by-sqlite
python3 $K/fake/products_api.py --port 8765 &
printf 'SOURCE_PATH=try/legacy.db\nSOURCE_PASSWORD=env:LEGACY_DB_PASSWORD\nPRODUCTS_URL=http://127.0.0.1:8765/products\nPRODUCTS_TOKEN=env:PRODUCTS_API_TOKEN\n' > try/my.params
tp-proxy migrate load      $K --params try/my.params --confirm-destinations
tp-proxy migrate reconcile $K --params try/my.params
```

Then against your own systems: the same `my.params` with your `SOURCE_ENGINE`, `SOURCE_HOST`, `SOURCE_DATABASE`,
`SOURCE_USER` added and `PRODUCTS_URL` set to your API, and `tp-proxy migrate certify $K --identity proxy.yaml` for a migration
certificate on the ledger.

**Check it.** `reconcile` passes with missing, extra and mismatched all 0 on the name, the price and the flag. The way
back is manual (`rollback: manual`; `tp-proxy migrate rollback` refuses and names this file): an API is not a table
whose old rows can be put back. DELETE each product the load created (each one carries the old table's id: `DELETE
/products/<id>` on the fake), or restore the API's own backup taken before the load.
