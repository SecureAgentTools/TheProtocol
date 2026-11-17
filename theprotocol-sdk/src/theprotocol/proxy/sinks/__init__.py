"""The proxy's WRITERS (V0664, Migrate a system, M1): sinks that put each mapped record into the new system.

    sql_upsert   a table of PostgreSQL, MySQL, SQL Server or SQLite, upserted by key, the oldest pre-image of each key kept
    rest         an HTTP API: the mapped fields are the body, the record's key the Idempotency-Key
    file_out     CSV or JSONL files in a folder, rotated, with a manifest of rows and sha256, optionally uploaded over SFTP

They are found as built-ins (theprotocol.proxy.plugins.BUILTINS) and like every sink deliver one key once, write nothing in a
dry run and refuse a literal credential at load. Their modules load without any database driver: a driver is imported
only when a writer starts.
"""
from .file_out import FileOutSink
from .rest import RestSink
from .sql_upsert import SqlUpsertSink, restore_preimages

__all__ = ["FileOutSink", "RestSink", "SqlUpsertSink", "restore_preimages"]
