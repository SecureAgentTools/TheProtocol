"""§MTLSHOPS T3 and (a) (2026-09-15, agentvault2-b5; his decision (a), agentvault2-85's calls): the host auditor slot wire()
writes for a frame, by what the frame's compose shows and what the running host auditor lists.

- A frame whose databases take TLS clients with a frame certificate only (T3) gets a public_only slot at its public es
  address when the host auditor lists the shape; otherwise no slot, and the log and the result say why.
- A frame whose store listens on a unix socket only (T2 S4) gets a public_read slot when the shape is listed; otherwise
  today's slot, and the log says its live read cannot reach the store.
- A frame from an older template keeps today's slot and the host auditor is not asked (CONTROL: passes on master too), as
  do facts with no stack dir (CONTROL).
RED on master's sidecars: the T3 and T2 cases (master never asks for shapes and never writes a public slot).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sidecars  # noqa: E402

T3_DB = "  f-db:\n    command: postgres -c shared_buffers=128MB -c ssl=on -c hba_file=/opt/data-tls/pg_hba.conf\n"
T2_STORE = ("  f-db:\n    command: postgres -c shared_buffers=128MB\n  f-event-store:\n    command: [\"sh\", \"-c\", \"umask 000 && "
            "rm -f /sock/event-store/event-store.sock && exec uvicorn src.main:app --uds /sock/event-store/event-store.sock "
            "--workers 2\"]\n")
OLDER_DB = "  f-db:\n    command: postgres -c shared_buffers=128MB -c effective_cache_size=512MB -c work_mem=4MB\n"
SHAPES = ["public_only", "public_read"]
PUBLIC = "https://f-es.example.test"


def _wire(tmp_path, monkeypatch, compose, shapes=None, stack=True, public=PUBLIC):
    sd = tmp_path / "f-1789500000"
    sd.mkdir()
    (sd / "docker-compose.frame-test.yml").write_text("services:\n" + compose)
    calls, lines, asked = [], [], []
    monkeypatch.setattr(sidecars.extras, "auditor_slot", lambda *a, **k: calls.append((a, k)))

    def shapes_of(url, *a, **k):
        asked.append(url)
        assert shapes is not None, "the host auditor must not be asked for this frame"
        return list(shapes)

    monkeypatch.setattr(sidecars.extras, "auditor_slot_shapes", shapes_of, raising=False)
    m = {"auditor": {"compose": str(tmp_path / "auditor" / "docker-compose.yml"), "admin_url": "http://127.0.0.1:9"}}
    f = {"name": "f", "frame_label": "F", "env_label": "sandbox", "ticker": "FTC"}
    if public:
        f["es_public_url"] = public
    if stack:
        f["stack_dir"] = str(sd)
    done = sidecars.wire(m, f, only={"auditor"}, log=lines.append)
    return done, calls, lines, asked


def test_red_a_t3_frame_gets_a_public_only_slot_when_the_host_auditor_lists_the_shape(tmp_path, monkeypatch):
    done, calls, _, asked = _wire(tmp_path, monkeypatch, T3_DB, shapes=SHAPES)
    assert asked == ["http://127.0.0.1:9"] and len(calls) == 1
    kw = calls[0][1]
    assert kw["public_only"] is True and kw["public_read"] is False and kw["public_url"] == PUBLIC
    assert done["auditor_slot"] == "public_only"


def test_red_a_t3_frame_gets_no_slot_when_the_host_auditor_does_not_list_the_shape_and_says_so(tmp_path, monkeypatch):
    done, calls, lines, _ = _wire(tmp_path, monkeypatch, T3_DB, shapes=[])
    assert calls == []
    assert done["auditor_slot"].startswith("not written")
    assert "does not list the public_only slot shape" in done["auditor_slot"]
    assert any("host auditor slot NOT written for f" in line for line in lines)


def test_red_a_t3_frame_without_a_public_es_address_gets_no_slot_and_says_so(tmp_path, monkeypatch):
    done, calls, _, _ = _wire(tmp_path, monkeypatch, T3_DB, shapes=SHAPES, public="")
    assert calls == [] and "no public es address" in done["auditor_slot"]


def test_red_a_t2_frame_gets_a_public_read_slot_when_the_shape_is_listed(tmp_path, monkeypatch):
    done, calls, _, _ = _wire(tmp_path, monkeypatch, T2_STORE, shapes=SHAPES)
    kw = calls[0][1]
    assert kw.get("public_read") is True and kw.get("public_only") is False and kw.get("public_url") == PUBLIC
    assert done["auditor_slot"] == "public_read"


def test_red_a_t2_frame_keeps_todays_slot_without_the_shape_and_says_its_live_read_cannot_reach_the_store(tmp_path, monkeypatch):
    done, calls, lines, _ = _wire(tmp_path, monkeypatch, T2_STORE, shapes=[])
    kw = calls[0][1]
    assert kw.get("public_read") is False and kw.get("public_only") is False and kw.get("public_url") == ""
    assert done["auditor_slot"] is True
    assert any("written without public_read" in line for line in lines)


def test_control_a_frame_from_an_older_template_keeps_its_slot_and_the_host_auditor_is_not_asked(tmp_path, monkeypatch):
    done, calls, _, asked = _wire(tmp_path, monkeypatch, OLDER_DB, shapes=None)
    assert len(calls) == 1 and done["auditor_slot"] is True and asked == []
    assert calls[0][1].get("public_only", False) is False and calls[0][1].get("public_read", False) is False


def test_control_facts_with_no_stack_dir_keep_the_slot_as_before(tmp_path, monkeypatch):
    done, calls, _, asked = _wire(tmp_path, monkeypatch, T3_DB, shapes=None, stack=False)
    assert len(calls) == 1 and done["auditor_slot"] is True and asked == []
