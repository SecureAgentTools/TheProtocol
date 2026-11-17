"""The scratch twins a dry run writes to, under KIT/.migrate/scratch/: nothing in a dry run reaches the real target.

    sql_upsert  ->  sql_upsert itself, engine sqlite, path scratch.sqlite, the table (its last name part) created here
                    from the mapped columns, the key its primary key
    file_out    ->  file_out itself, into a folder under scratch/ (no SFTP upload)
    rest        ->  RestScratchSink: the rest writer's own url and body, appended to <sink>.requests.jsonl, never sent

RestScratchSink is put among the built-in sinks only while a dry run builds its proxy (`registered()`), so no proxy.yaml
can name it.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Sequence

from ..plugins import BUILTINS, Event, Outcome
from ..sinks.rest import RestSink

SCRATCH_REST = "migrate_scratch_rest"


class RestScratchSink(RestSink):
    name = SCRATCH_REST
    description = "Used by tp-proxy migrate dry-run only: what the rest writer would send, written to a file."
    config_schema: Mapping[str, Any] = {
        **RestSink.config_schema,
        "required": ["url", "requests_file"],
        "properties": {**RestSink.config_schema["properties"], "requests_file": {"type": "string"}},
    }

    async def deliver(self, event: Event, *, key: str, dry_run: bool) -> Outcome:
        if dry_run:
            return await super().deliver(event, key=key, dry_run=True)
        data = dict(event.data)
        line = {"method": self.config.get("method") or "POST", "url": self._url(data), "idempotency_key": key,
                "body": json.loads(self._body(data))}
        with open(self.config["requests_file"], "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        return Outcome.done(key, "written to the scratch requests file")


@contextlib.contextmanager
def registered() -> Iterator[None]:
    had = BUILTINS["sink"].get(SCRATCH_REST)
    BUILTINS["sink"][SCRATCH_REST] = "theprotocol.proxy.migrate.scratch:RestScratchSink"
    try:
        yield
    finally:
        if had is None:
            BUILTINS["sink"].pop(SCRATCH_REST, None)
        else:  # pragma: no cover
            BUILTINS["sink"][SCRATCH_REST] = had


def create_table(path: Path, table: str, columns: Sequence[str], key: Sequence[str]) -> None:
    """The scratch table: every column untyped (SQLite keeps each value as it is given), the key its primary key."""
    q = lambda n: '"' + str(n).replace('"', '""') + '"'  # noqa: E731
    cols: List[str] = list(dict.fromkeys([*key, *columns]))
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(f"CREATE TABLE IF NOT EXISTS {q(table)} ({', '.join(q(c) for c in cols)}, "
                     f"PRIMARY KEY ({', '.join(q(k) for k in key)}))")
        conn.commit()
    finally:
        conn.close()


def twin(sink_type: str, name: str, config: Mapping[str, Any], scratch: Path, columns: Sequence[str]
         ) -> Dict[str, Any]:
    """The scratch sink section standing in for a writer (its type and config)."""
    if sink_type == "sql_upsert":
        table = str(config["table"]).split(".")[-1]
        cfg = {"engine": "sqlite", "path": str(scratch / "scratch.sqlite"), "table": table, "key": list(config["key"])}
        for k in ("columns", "on_conflict", "preimage", "timeout_seconds"):
            if k in config:
                cfg[k] = config[k]
        create_table(scratch / "scratch.sqlite", table, list(config.get("columns") or columns), list(config["key"]))
        return {"type": "sql_upsert", "config": cfg}
    if sink_type == "file_out":
        cfg = {k: v for k, v in config.items() if k != "sftp"}
        cfg["path"] = str(scratch / name)
        Path(cfg["path"]).mkdir(parents=True, exist_ok=True)
        return {"type": "file_out", "config": cfg}
    if sink_type == "rest":
        cfg = {k: v for k, v in config.items() if k != "bearer"}
        cfg["requests_file"] = str(scratch / f"{name}.requests.jsonl")
        return {"type": SCRATCH_REST, "config": cfg}
    raise ValueError(sink_type)  # pragma: no cover - the kit rules refuse any other writer first
