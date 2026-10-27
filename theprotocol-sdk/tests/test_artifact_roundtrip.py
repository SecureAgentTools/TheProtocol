"""Regression tests for the v1_compat artifact serializer hardening (2026-06-21).

Before the fix, task_to_v1 ran ``str(a.content)`` on every artifact, turning a
structured dict into a single-quoted Python repr (invalid JSON) and losing the
data shape. These tests lock in: dict → DataPart, str → TextPart, other JSON
values → JSON-encoded text, plus the canonical ``artifactId`` key and the
``Task`` populate_by_name footgun fix.
"""
import datetime

from theprotocol.models.a2a_protocol import Task, Artifact, TaskState
from theprotocol.models.v1_compat import task_to_v1


def _task(content):
    now = datetime.datetime(2026, 1, 1, 0, 0, 0)
    return Task(
        id="t1", state=TaskState.COMPLETED, created_at=now, updated_at=now,
        artifacts=[Artifact(id="a1", type="application/json", content=content)],
    )


def test_dict_artifact_survives_as_data_part():
    payload = {"temp_c": 21.5, "city": "Berlin", "forecast": [1, 2, 3]}
    art = task_to_v1(_task(payload))["artifacts"][0]
    assert art["artifactId"] == "a1"
    assert art["artifact_id"] == "a1"  # back-compat alias retained
    assert art["parts"][0].get("data") == payload  # NOT a str() repr


def test_string_artifact_is_text_part():
    art = task_to_v1(_task("hello world"))["artifacts"][0]
    assert art["parts"][0].get("text") == "hello world"


def test_list_artifact_is_json_not_python_repr():
    art = task_to_v1(_task([1, 2, 3]))["artifacts"][0]
    assert art["parts"][0].get("text") == "[1, 2, 3]"


def test_task_accepts_field_names_not_only_aliases():
    now = datetime.datetime(2026, 1, 1)
    t = Task(id="x", state=TaskState.WORKING, created_at=now, updated_at=now)
    assert t.id == "x" and t.state == TaskState.WORKING
