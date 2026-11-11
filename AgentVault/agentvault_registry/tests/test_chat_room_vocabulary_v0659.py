"""V0659 (f) on the sandbox (2026-11-08, its federation legs): opening a room answered 409, "new row for relation
conversations violates check constraint ck_conversations_kind". The Postgres CHECKs on the chat tables live only in the
migrations (0155 created them, 0164 widened the kinds for support), so the SQLite tests, which build the tables from the
models, never met them: 'room' was not an allowed kind, and 'moderator' not an allowed participant role.

Pinned here without a database: the LAST migration that (re)defines each constraint allows every value the room code
writes. Red on the branch before 0214 (the last kind list is 0164's, the last role list 0155's).
"""
from __future__ import annotations

import pathlib
import re

from agentvault_registry.services import chat_rooms as rooms

VERSIONS = pathlib.Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _last_allowed(constraint: str, column: str) -> tuple[str, set[str]]:
    """The values the newest migration that defines `constraint` allows for `column` (IN ('a','b',...))."""
    found = None
    for f in sorted(VERSIONS.glob("0*.py")):
        src = f.read_text(encoding="utf-8").split("def downgrade")[0]   # what the upgrade leaves, never the way back
        for m in re.finditer(rf"{column}\s+IN\s*\(([^)]*)\)[^\n]*\n?[^\n]*{constraint}|{constraint}[^\n]*\n?[^\n]*{column}\s+IN\s*\(([^)]*)\)",
                             src):
            body = m.group(1) or m.group(2)
            found = (f.name, set(re.findall(r"'([^']+)'", body)))
    assert found, f"no migration defines {constraint}"
    return found


def test_a_room_is_an_allowed_conversation_kind():
    where, kinds = _last_allowed("ck_conversations_kind", "kind")
    assert "room" in kinds, f"{where} allows {sorted(kinds)}: no 'room'"
    assert {"dm", "agent_service", "org", "system", "group", "support"} <= kinds, f"{where} dropped a kind: {sorted(kinds)}"


def test_every_role_the_room_code_seats_is_allowed():
    where, roles = _last_allowed("ck_conv_part_role", "role")
    wanted = set(rooms.OPERATOR_ROLES) | {"member"}
    assert wanted <= roles, f"{where} allows {sorted(roles)}; the room code seats {sorted(wanted)}"


def test_the_products_kind_list_is_the_databases():
    """One list of conversation kinds in the code, the database CHECK's own (session-code's seq 2511: the federation
    suite's closed-vocabulary test kept a literal of its own, which 'room' broke on the sandbox). The newest migration's
    ck_conversations_kind and chat_service.CONVERSATION_KINDS are the same set."""
    from agentvault_registry.services import chat_service as cs
    where, kinds = _last_allowed("ck_conversations_kind", "kind")
    assert set(cs.CONVERSATION_KINDS) == kinds, f"{where} allows {sorted(kinds)}; the code lists {sorted(cs.CONVERSATION_KINDS)}"
