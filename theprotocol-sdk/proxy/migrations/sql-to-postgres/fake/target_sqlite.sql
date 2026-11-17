-- The rehearsal target (TARGET_ENGINE=sqlite, TARGET_TABLE=customers): the PostgreSQL table's columns in a local file.
CREATE TABLE IF NOT EXISTS customers (
    legacy_id  INTEGER PRIMARY KEY,
    full_name  TEXT NOT NULL,
    email      TEXT,
    signed_up  TEXT NOT NULL,
    status     TEXT NOT NULL
);
