-- The rehearsal target (TARGET_ENGINE=sqlite, TARGET_TABLE=orders): the PostgreSQL table's columns in a local file.
CREATE TABLE IF NOT EXISTS orders (
    order_no     INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL,
    ordered_at   TEXT NOT NULL,
    amount       TEXT NOT NULL,
    currency     TEXT NOT NULL,
    status       TEXT NOT NULL
);
