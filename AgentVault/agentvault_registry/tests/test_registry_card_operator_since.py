"""§FESUITE (2026-10-10, lifecycle 87): "operator since" stays on the published card after a save in the card editor.

It is not editable (the card PUT forbids it), so it can only be derived, and it was derived only while the stored
operator block had neither developer_id nor contact_email. The card editor's save writes both, so the FIRST save
dropped it from the published card for good: measured on sbx-beta (the suite's first edit), while EU, ASIA and
sbx-alpha, never saved through the editor, still carry it. The persona logic is operator_persona(); the build calls it.
"""
import ast
import datetime
import pathlib
import types

from agentvault_registry.services import registry_card_builder as rcb

SRC = pathlib.Path(rcb.__file__)
ADMIN = types.SimpleNamespace(id=3, name="Frame Admin", email="admin@frame.dev", bio=None,
                              created_at=datetime.datetime(2026, 9, 3, 19, 47, 46, tzinfo=datetime.timezone.utc))
SINCE = "2026-09-03T19:47:46+00:00"


def test_a_card_nobody_edited_takes_the_admins_persona():
    block = rcb.operator_persona({}, ADMIN)
    assert block["operator_since"] == SINCE and block["display_name"] == "Frame Admin" and block["developer_id"] == 3


def test_after_a_save_in_the_editor_the_date_is_still_derived():
    # what the editor's save leaves stored: developer_id and every field it sends, contact_email null
    saved = {"developer_id": 3, "display_name": "Frame Admin", "contact_email": None, "bio": None, "company": None,
             "url": None, "github_url": None, "twitter_handle": None, "timezone": None, "location_label": "Brussels",
             "latitude": 50.85, "longitude": 4.35, "successor_contact": None}
    assert rcb._persona_needs_admin(saved) is True
    block = rcb.operator_persona(saved, ADMIN)
    assert block["operator_since"] == SINCE
    assert block["location_label"] == "Brussels" and block["contact_email"] is None   # the operator's fields win


def test_control_a_stored_date_is_kept_and_needs_no_admin():
    stored = {"developer_id": 3, "contact_email": None, "operator_since": "2026-01-01T00:00:00+00:00"}
    assert rcb._persona_needs_admin(stored) is False
    assert rcb.operator_persona(stored, ADMIN)["operator_since"] == "2026-01-01T00:00:00+00:00"


def test_no_admin_leaves_the_block_as_stored():
    assert rcb.operator_persona({"developer_id": 3}, None) == {"developer_id": 3}


def test_the_build_asks_the_persona():
    tree = ast.parse(SRC.read_text())
    build = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "build_registry_card")
    names = {n.func.id for n in ast.walk(build) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert {"operator_persona", "_persona_needs_admin"} <= names
