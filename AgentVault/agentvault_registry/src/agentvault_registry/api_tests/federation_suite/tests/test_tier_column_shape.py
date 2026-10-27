"""U5 (2026-09-05) — make the tier's column SHAPE visible, and hold mig 0174.

WHY THIS EXISTS. §CAPSEARCH applied a jsonb type-inspection function to the
card-data column in the discovery query without casting it. Postgres resolves
function types for the WHOLE statement at parse time, branch taken or not, so on
the four older Frame-A operators — where that column was provisioned as plain
`json` — `/agent-cards/discover` answered **500 for three days**, with or
without `q`.

⚠ The call is DESCRIBED and not quoted here on purpose. The source-level gate
scans string constants and cannot strip docstrings (the real SQL lives in
strings, so ignoring strings would ignore every call site) — it caught this very
file when an earlier draft spelled the call out. Prose beside a cast names the
CLASS, never the call. That is the gate's own rule and it applies to its
neighbours too.

Every test in this suite passed throughout, because the sandbox frames are
`jsonb` and the suite only ever ran here. A suite that exercises ONE column
shape cannot see a defect that lives in the difference between shapes, and
nothing in the run said which shape it had been standing on.

Two things follow, and this file does both:

  1. PUBLISH the census. `last_state` carries every json-family column and its
     type, so a reader diffing this tier against production has the number
     instead of an assumption. 39 columns here are plain `json` BY DESIGN —
     mig 0174 converged seven, not all — so "everything is jsonb" would be a
     false assertion, and asserting it would be worse than asserting nothing.

  2. ASSERT what 0174 actually promised: those seven are `jsonb` here. That is
     R57's convergence, held as a standing check rather than a one-off from the
     night it rolled.

The source-level sibling (`tests/test_discover_sql_json_columns.py`) refuses an
uncast `jsonb_*()` on `card_data` in code. This one measures the DATABASE. Both
are needed: the source gate cannot see a column that changed type under it, and
this one cannot see SQL that has not run yet.
"""
from __future__ import annotations

import json

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import AssertionResult
from agentvault_registry.api_tests.multiframe_helpers import (
    REG_DB_A, run_psql_in_db_container,
)

# Exactly the list mig 0174 converts (alembic/versions/0174_json_columns_to_jsonb.py).
# A table absent on this tier is not a failure — 0174 skips what is not there.
MIG_0174_COLUMNS = [
    ("agent_cards", "card_data"),
    ("developers", "backup_codes"),
    ("developers", "trusted_devices"),
    ("developer_achievements", "metadata_json"),
    ("agent_cards_orphan_backup_v0052", "card_data"),
    ("developers_ghost_backup_v0052", "backup_codes"),
    ("developers_ghost_backup_v0052", "trusted_devices"),
]

_CENSUS_SQL = (
    "SELECT json_agg(json_build_object('t', table_name, 'c', column_name, "
    "'d', data_type) ORDER BY table_name, column_name) "
    "FROM information_schema.columns "
    "WHERE table_schema = 'public' AND data_type IN ('json', 'jsonb');"
)


@federation_test(
    name="tier_json_column_shape_census_and_0174_convergence",
    category="tier_shape",
    budget_sec=20.0,
    severity="high",
    tags=["schema", "jsoncast", "r57"],
)
async def test_tier_column_shape(rig):
    rc, out = run_psql_in_db_container(REG_DB_A, _CENSUS_SQL, db_name=None)
    if rc != 0 or not (out or "").strip():
        return AssertionResult(
            passed=False,
            description="read the json-family column census from the registry DB",
            budget_sec=20.0, elapsed_sec=0.0, polling_attempts=1,
            failure_detail=(
                f"could not read information_schema from {REG_DB_A!r} (rc={rc}): "
                f"{(out or '')[:300]}. An unreadable shape is not a green shape — "
                f"this row is red so the census is never silently absent."
            ),
        )

    rows = json.loads(out.strip())
    shape = {f"{r['t']}.{r['c']}": r["d"] for r in rows}
    n_json = sum(1 for v in shape.values() if v == "json")
    n_jsonb = sum(1 for v in shape.values() if v == "jsonb")

    unconverged = [
        f"{t}.{c}" for t, c in MIG_0174_COLUMNS
        if shape.get(f"{t}.{c}") == "json"          # absent ⇒ 0174 skipped it, fine
    ]
    present = [f"{t}.{c}" for t, c in MIG_0174_COLUMNS if f"{t}.{c}" in shape]

    return AssertionResult(
        passed=not unconverged,
        description="mig 0174's seven json columns are jsonb on this tier",
        budget_sec=20.0, elapsed_sec=0.0, polling_attempts=1,
        last_state={
            "db_container": REG_DB_A,
            "json_columns": n_json,
            "jsonb_columns": n_jsonb,
            "mig_0174_present_here": present,
            # The full census, so a shape difference against another node is a
            # diff and not an argument.
            "plain_json_columns": sorted(k for k, v in shape.items() if v == "json"),
        },
        failure_detail=None if not unconverged else (
            f"mig 0174 columns still plain `json` here: {unconverged}. An uncast "
            f"`jsonb_*()` against any of them answers 500 at PARSE time, for every "
            f"caller, whether or not the branch is taken — that is §JSONCAST."
        ),
    )
