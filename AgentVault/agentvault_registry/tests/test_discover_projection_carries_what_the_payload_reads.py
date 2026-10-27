"""§CARDLINK (2026-09-08) — every key the discover payload reads must survive the projection.

WHAT HAPPENED. `endpoint_health` needed a column in THREE places, not two: the slim CTE that
computes it, the outer `SELECT … FROM base` that carries it out, and the payload dict that names
it. I did the CTE and the payload. `/agent-cards/discover` then answered **500** with
`NoSuchColumnError: Could not locate column in row for column 'last_health'` on a live frame,
and `/health` was 200 the whole time — §DISCECHO's lesson, and §EXCISION-10's field-by-field
mapper one layer further out.

WHY A TEST AND NOT A NOTE. The roll's public-rail smoke DID catch it, but only after the
recreate: the frame served 500s for a minute and had to be rolled back. This asks the same
question before anything is built.

⚠ THIS IS A SOURCE-RELATION CHECK, and doctrine's warning applies — a source-reading gate finds
its own documentation first. So it reads only the two REGIONS that must agree, ignores comments,
and carries the control below: `test_the_check_can_fail` builds the pre-fix text and asserts this
gate rejects it. A gate that cannot fail measures nothing.
"""
import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1]
       / "src/agentvault_registry/routers/agent_cards.py").read_text()


def _strip_sql_comments(sql: str) -> str:
    return "\n".join(l.split("--")[0] for l in sql.splitlines())


def _page_projection(src: str) -> str:
    """The `SELECT … FROM base` that feeds the payload rows — comments removed."""
    m = re.search(r"SELECT id, agent_did, name, description.*?FROM base", src, re.S)
    assert m, "the discover page query moved — find it before trusting this gate"
    return _strip_sql_comments(m.group(0))


def _payload_keys(src: str) -> set:
    """Every `r["…"]` the item dict reads."""
    m = re.search(r"for r in page_rows:(.*?)\n    total = int\(page_rows", src, re.S)
    assert m, "the discover payload loop moved — find it before trusting this gate"
    return set(re.findall(r'r\["([a-z_0-9]+)"\]', m.group(1)))


def _missing(src: str) -> set:
    proj = _page_projection(src)
    return {k for k in _payload_keys(src)
            if not re.search(rf"\b{re.escape(k)}\b", proj)}


def test_every_key_the_payload_reads_is_projected():
    missing = _missing(SRC)
    assert not missing, (
        "discover's payload reads columns the page projection does not carry: "
        f"{sorted(missing)}. That is a 500 on the public rail, not a missing field — "
        "add them to the `SELECT … FROM base` list."
    )


def test_the_check_can_fail():
    """The control. Remove a column from the projection and this gate must notice."""
    broken = SRC.replace("                   last_health, last_health_at,\n", "", 1)
    assert broken != SRC, "the pre-fix shape could not be reconstructed — control not run"
    assert "last_health" in _missing(broken), (
        "the gate did not notice a column the payload reads being dropped from the projection, "
        "so it would not have caught the 500 it exists for"
    )
