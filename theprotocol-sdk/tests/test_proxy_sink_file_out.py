"""V0664 (Migrate a system, M1): the writer `file_out`, a sink that writes each mapped record as a line of a CSV or JSONL file in
a folder, for a system that loads files.

Rows go to a `.part` file; on rotation and on stop the part is fsynced and RENAMED (so a closed file is whole or absent) and the
folder's manifest.json is updated: {"files": [{"name", "rows", "sha256"}], "rows": n}. A closed file is uploaded over SFTP when
configured. Exactly once: the proxy's state keeps, per key, the byte offset after its line; at start the part is cut back to the
offset after the last recorded key, so a crash between a write and its state leaves at most one stray line, which is cut and
written again. A dry run writes nothing (not even the folder).
RED on stack master ed708438: theprotocol.proxy.sinks.file_out does not exist.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import types

import pytest

from theprotocol.proxy.plugins import Event, PluginError, Refused
from theprotocol.proxy.testing import FakeContext, check_sink


@pytest.fixture(autouse=True)
def fake_plugins(monkeypatch):
    """The spec tests below name a source and need one: the shared fakes (proxy_fake) stand in."""
    from theprotocol.proxy import plugins
    monkeypatch.setitem(plugins.BUILTINS["source"], "list_source", "proxy_fake:ListSource")
    monkeypatch.setitem(plugins.BUILTINS["sink"], "list_sink", "proxy_fake:ListSink")


def _ev(i=1, **data):
    return Event(event_id=f"evt-{i}", event_type="migration.row", aggregate_id="customers", data=data)


def _sink(folder, ctx=None, **cfg):
    from theprotocol.proxy.sinks.file_out import FileOutSink
    base = {"path": str(folder), "format": "csv", "columns": ["id", "name"]}
    base.update(cfg)
    ctx = ctx or FakeContext()
    return FileOutSink(base, ctx), ctx


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


async def test_it_keeps_the_sink_contract_and_is_a_builtin(tmp_path):
    from theprotocol.proxy import plugins
    from theprotocol.proxy.sinks.file_out import FileOutSink
    assert plugins.BUILTINS["sink"]["file_out"] == "theprotocol.proxy.sinks.file_out:FileOutSink"
    assert plugins.load("sink", "file_out") is FileOutSink
    out = await check_sink(FileOutSink, {"path": str(tmp_path / "out"), "format": "jsonl"}, _ev(1, id=1, name="Ada"))
    assert out.status == "done"


async def test_csv_rows_go_to_a_part_file_and_a_stop_closes_it_with_a_manifest(tmp_path):
    folder = tmp_path / "out"
    sink, _ = _sink(folder)
    await sink.start()
    await sink.deliver(_ev(1, id=1, name="Ada"), key="k1", dry_run=False)
    await sink.deliver(_ev(2, id=2, name="Grace, H."), key="k2", dry_run=False)
    assert (folder / "data-00001.csv.part").exists() and not (folder / "data-00001.csv").exists()   # still open
    await sink.stop()
    done = folder / "data-00001.csv"
    assert done.exists() and not (folder / "data-00001.csv.part").exists()
    rows = list(csv.reader(io.StringIO(done.read_text(encoding="utf-8"))))
    assert rows == [["id", "name"], ["1", "Ada"], ["2", "Grace, H."]]
    man = json.loads((folder / "manifest.json").read_text())
    assert man == {"files": [{"name": "data-00001.csv", "rows": 2, "sha256": _sha(done)}], "rows": 2}


async def test_jsonl_is_one_sorted_json_object_per_line(tmp_path):
    folder = tmp_path / "out"
    sink, _ = _sink(folder, format="jsonl", columns=None)
    await sink.start()
    await sink.deliver(_ev(1, name="Ada", id=1, tags=["a"]), key="k1", dry_run=False)
    await sink.stop()
    (f,) = sorted(folder.glob("data-*.jsonl"))
    assert f.read_text(encoding="utf-8") == '{"id":1,"name":"Ada","tags":["a"]}\n'


async def test_rows_per_file_rotates_and_every_file_is_in_the_manifest(tmp_path):
    folder = tmp_path / "out"
    sink, _ = _sink(folder, rows_per_file=2, file="part-{n:03d}.csv")
    await sink.start()
    for i in range(1, 6):
        await sink.deliver(_ev(i, id=i, name=f"n{i}"), key=f"k{i}", dry_run=False)
    assert sorted(p.name for p in folder.glob("part-*")) == ["part-001.csv", "part-002.csv", "part-003.csv.part"]
    await sink.stop()
    man = json.loads((folder / "manifest.json").read_text())
    assert [f["name"] for f in man["files"]] == ["part-001.csv", "part-002.csv", "part-003.csv"]
    assert [f["rows"] for f in man["files"]] == [2, 2, 1] and man["rows"] == 5
    for f in man["files"]:
        assert f["sha256"] == _sha(folder / f["name"])
    assert (folder / "part-001.csv").read_text().splitlines()[0] == "id,name"        # a header in each file


async def test_one_key_is_one_line(tmp_path):
    folder = tmp_path / "out"
    sink, _ = _sink(folder)
    await sink.start()
    a = await sink.deliver(_ev(1, id=1, name="Ada"), key="same", dry_run=False)
    b = await sink.deliver(_ev(1, id=1, name="Ada"), key="same", dry_run=False)
    await sink.stop()
    assert a.status == b.status == "done"
    assert (folder / "data-00001.csv").read_text().count("Ada") == 1


async def test_a_crash_between_a_write_and_its_state_leaves_a_line_that_is_cut_and_written_again(tmp_path):
    folder = tmp_path / "out"
    ctx = FakeContext()
    sink, _ = _sink(folder, ctx=ctx)
    await sink.start()
    await sink.deliver(_ev(1, id=1, name="Ada"), key="k1", dry_run=False)
    part = folder / "data-00001.csv.part"
    # the crash: a second line reached the file, the state never heard of it, and the process died (no stop())
    with open(part, "a", encoding="utf-8", newline="") as f:
        f.write("2,Grace\n")
    # a restart: a new sink over the SAME state
    sink2, _ = _sink(folder, ctx=ctx)
    await sink2.start()
    assert part.read_text(encoding="utf-8").splitlines() == ["id,name", "1,Ada"]       # cut back to the last recorded key
    await sink2.deliver(_ev(2, id=2, name="Grace"), key="k2", dry_run=False)           # the lost record is delivered again
    await sink2.deliver(_ev(1, id=1, name="Ada"), key="k1", dry_run=False)             # and a repeat of a recorded key is not
    await sink2.stop()
    assert (folder / "data-00001.csv").read_text(encoding="utf-8").splitlines() == ["id,name", "1,Ada", "2,Grace"]


async def test_a_restart_goes_on_in_the_same_file_and_numbering(tmp_path):
    folder = tmp_path / "out"
    ctx = FakeContext()
    s1, _ = _sink(folder, ctx=ctx, rows_per_file=2)
    await s1.start()
    await s1.deliver(_ev(1, id=1, name="a"), key="k1", dry_run=False)
    await s1.stop()                                                                   # closes data-00001.csv with one row
    s2, _ = _sink(folder, ctx=ctx, rows_per_file=2)
    await s2.start()
    await s2.deliver(_ev(2, id=2, name="b"), key="k2", dry_run=False)
    await s2.stop()
    man = json.loads((folder / "manifest.json").read_text())
    assert [f["name"] for f in man["files"]] == ["data-00001.csv", "data-00002.csv"] and man["rows"] == 2


async def test_a_field_that_is_not_a_column_is_refused_by_name_and_a_missing_one_is_empty(tmp_path):
    folder = tmp_path / "out"
    sink, _ = _sink(folder)
    await sink.start()
    with pytest.raises(Refused) as e:
        await sink.deliver(_ev(1, id=1, name="Ada", extra="x"), key="k1", dry_run=False)
    assert "extra" in e.value.detail and "Ada" not in e.value.detail
    await sink.deliver(_ev(2, id=2), key="k2", dry_run=False)
    await sink.stop()
    assert (folder / "data-00001.csv").read_text().splitlines() == ["id,name", "2,"]


async def test_csv_needs_its_columns_and_a_dict_value_is_json_text(tmp_path):
    from theprotocol.proxy.sinks.file_out import FileOutSink
    with pytest.raises(PluginError):
        FileOutSink({"path": str(tmp_path / "o"), "format": "csv"}, FakeContext())
    sink, _ = _sink(tmp_path / "o2", columns=["id", "meta"])
    await sink.start()
    await sink.deliver(_ev(1, id=1, meta={"a": 1}), key="k", dry_run=False)
    await sink.stop()
    assert list(csv.reader(io.StringIO((tmp_path / "o2" / "data-00001.csv").read_text())))[1] == ["1", '{"a":1}']


async def test_a_dry_run_writes_nothing_not_even_the_folder(tmp_path):
    folder = tmp_path / "out"
    ctx = FakeContext(dry_run=True)
    sink, _ = _sink(folder, ctx=ctx)
    await sink.start()
    out = await sink.deliver(_ev(1, id=1, name="Ada"), key="k", dry_run=True)
    await sink.stop()
    assert out.status == "dry_run" and "data-00001.csv" in out.detail and out.data["columns"] == ["id", "name"]
    assert not folder.exists() and ctx.state.data == {}


# ── the SFTP upload ───────────────────────────────────────────────────────────────────────────────────────────

class _FakeSftp:
    uploads = []

    def put(self, local, remote):
        _FakeSftp.uploads.append((remote, open(local, "rb").read()))


def _fake_paramiko(monkeypatch):
    _FakeSftp.uploads = []
    mod = types.ModuleType("paramiko")
    mod.rejected = []

    class SSHClient:
        def load_host_keys(self, path):
            mod.known = path

        def load_system_host_keys(self):
            mod.known = "system"

        def set_missing_host_key_policy(self, policy):
            mod.policy = policy

        def connect(self, **kw):
            mod.last_connect = kw

        def open_sftp(self):
            return _FakeSftp()

        def close(self):
            pass

    class RejectPolicy:
        pass

    mod.SSHClient, mod.RejectPolicy = SSHClient, RejectPolicy
    monkeypatch.setitem(sys.modules, "paramiko", mod)
    return mod


async def test_a_closed_file_is_uploaded_over_sftp_and_the_open_part_is_not(tmp_path, monkeypatch):
    mod = _fake_paramiko(monkeypatch)
    folder = tmp_path / "out"
    ctx = FakeContext(secrets={"env:SFTP_PW": "pw-1"})
    sink, _ = _sink(folder, ctx=ctx, rows_per_file=2, sftp={"host": "files.example.org", "port": 2222, "user": "tp",
                                                            "password": "env:SFTP_PW", "path": "/incoming"})
    await sink.start()
    for i, who in enumerate(("Ada", "Grace", "Edsger"), 1):
        await sink.deliver(_ev(i, id=i, name=who), key=f"k{i}", dry_run=False)         # the 3rd rotates: file 1 is closed and uploaded
    assert [r for r, _ in _FakeSftp.uploads] == ["/incoming/data-00001.csv"]
    await sink.stop()                                                                  # file 2 closed and uploaded
    assert [r for r, _ in _FakeSftp.uploads] == ["/incoming/data-00001.csv", "/incoming/data-00002.csv"]
    assert _FakeSftp.uploads[0][1] == (folder / "data-00001.csv").read_bytes()
    kw = mod.last_connect
    assert (kw["hostname"], kw["port"], kw["username"], kw["password"]) == ("files.example.org", 2222, "tp", "pw-1")
    assert isinstance(mod.policy, mod.RejectPolicy)              # an unknown host key is refused, never added blind


def test_a_literal_sftp_password_is_refused_at_load(tmp_path):
    import proxy_fake as F
    from theprotocol.proxy.spec import SpecError, parse
    doc = F.spec_doc(tmp_path, sinks={"out": {"type": "file_out", "config": {
        "path": str(tmp_path / "o"), "format": "jsonl", "sftp": {"host": "h", "user": "u", "password": "written-out", "path": "/in"}}}})
    with pytest.raises(SpecError) as e:
        parse(doc, base=tmp_path)
    assert "sinks.out.config.sftp.password" in e.value.problems
