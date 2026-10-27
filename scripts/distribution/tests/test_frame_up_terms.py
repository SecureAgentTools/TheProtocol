"""frame-up asks for the Federation Operator Terms before it creates the frame and its admin account (agentvault2-56,
2026-10-22; his word: "make sure terms are accepted also on framekit standup. because there an account is issued").

Pinned: --accept-terms accepts; a terminal asks and only "yes" accepts; no flag and no terminal refuses before anything
exists; a dry run asks nothing; a sandbox inherits its parent frame's acceptance and never refuses (frame-sandbox runs
without a terminal); the driver receives the acceptance; the read-back finds only the admin's own rows.
"""
import argparse
import datetime
import importlib.util
import os
import pathlib
import types

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("frame_up_terms", os.path.join(HERE, "..", "frame-up.py"))
fu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fu)

NOW = datetime.datetime(2026, 10, 22, 13, 0, 0, tzinfo=datetime.timezone.utc)


def _args(**over):
    base = dict(accept_terms=False, dry_run=False, admin_email="ops@example.org", version="1.0.0-beta.23",
                sandbox_of=None)
    base.update(over)
    return argparse.Namespace(**base)


def _export(tmp_path, monkeypatch, version="2.4"):
    core = tmp_path / "AgentVault" / "agentvault_registry" / "src" / "agentvault_registry" / "core"
    core.mkdir(parents=True)
    (core / "legal_versions.py").write_text(f'DOCUMENTS_VERSION = "2.5"\nOPERATOR_TERMS_SET_VERSION = "{version}"\n')
    monkeypatch.setattr(fu, "EXPORT_ROOT", str(tmp_path))


def test_the_flag_accepts_at_the_version_the_kit_serves(tmp_path, monkeypatch):
    _export(tmp_path, monkeypatch)
    terms, why = fu.terms_acceptance(_args(accept_terms=True), None, interactive=False, now=NOW)
    assert why is None
    assert terms == {"document": "operators", "version": "2.4", "accepted_at": "2026-10-22T13:00:00Z",
                     "how": "--accept-terms", "by": "frame-up.py 1.0.0-beta.23 (--accept-terms)"}


def test_a_terminal_asks_and_only_yes_accepts(tmp_path, monkeypatch, capsys):
    _export(tmp_path, monkeypatch)
    terms, _ = fu.terms_acceptance(_args(), None, interactive=True, ask=lambda _q: " Yes ", now=NOW)
    assert terms["how"] == "prompt" and terms["accepted_at"] == "2026-10-22T13:00:00Z"
    shown = capsys.readouterr().out
    assert "the Federation Operator Terms (set 2.4)" in shown and fu.TERMS_URL in shown and "ops@example.org" in shown
    for answer in ("no", "", "accept", None):
        terms, why = fu.terms_acceptance(_args(), None, interactive=True, ask=lambda _q, a=answer: a, now=NOW)
        assert terms is None and "not accepted" in why


def test_no_flag_and_no_terminal_refuses_before_anything_exists(tmp_path, monkeypatch):
    _export(tmp_path, monkeypatch)
    terms, why = fu.terms_acceptance(_args(), None, interactive=False, now=NOW)
    assert terms is None and "--accept-terms" in why and "Nothing was created" in why


def test_a_dry_run_asks_nothing(tmp_path, monkeypatch):
    _export(tmp_path, monkeypatch)
    terms, why = fu.terms_acceptance(_args(dry_run=True), None, interactive=True,
                                     ask=lambda _q: (_ for _ in ()).throw(AssertionError("asked")), now=NOW)
    assert terms is None and "dry run" in why
    assert fu.terms_acceptance(_args(dry_run=True, accept_terms=True), None, interactive=False, now=NOW)[0]


def test_an_unreadable_version_still_names_the_document(tmp_path, monkeypatch):
    monkeypatch.setattr(fu, "EXPORT_ROOT", str(tmp_path))
    terms, _ = fu.terms_acceptance(_args(accept_terms=True), None, interactive=False, now=NOW)
    assert terms["document"] == "operators" and terms["version"] is None


def test_a_sandbox_inherits_its_parents_acceptance_and_never_refuses(tmp_path, monkeypatch):
    _export(tmp_path, monkeypatch)
    parent = {"terms": {"document": "operators", "version": "2.4", "accepted_at": "2026-10-20T08:00:00Z"}}
    terms, why = fu.terms_acceptance(_args(sandbox_of="myframe"), parent, interactive=False, now=NOW)
    assert why is None and terms["accepted_at"] == "2026-10-20T08:00:00Z" and terms["version"] == "2.4"
    assert "the sandbox of myframe" in terms["by"]
    terms, why = fu.terms_acceptance(_args(sandbox_of="myframe"), {"name": "myframe"}, interactive=False, now=NOW)
    assert terms is None and "myframe records no acceptance" in why


def test_the_driver_receives_the_acceptance():
    terms = {"document": "operators", "accepted_at": "2026-10-22T13:00:00Z", "by": "frame-up.py x (prompt)"}
    assert fu.terms_driver_args(terms) == ["--admin-accepted", "operators", "--admin-accepted-at", "2026-10-22T13:00:00Z",
                                           "--admin-accepted-by", "frame-up.py x (prompt)"]
    assert fu.terms_driver_args(None) == []


def test_the_driver_writes_the_three_lines_only_when_given():
    src = (pathlib.Path(HERE).parents[1] / "hetzner_demo" / "standup_driver.py").read_text()
    for flag in ("--admin-accepted", "--admin-accepted-at", "--admin-accepted-by"):
        assert f'ap.add_argument("{flag}", default=""' in src
    block = src[src.index('if (getattr(args, "admin_accepted", "") or "").strip():'):][:600]
    for key in ("FIRST_ADMIN_ACCEPTED", "FIRST_ADMIN_ACCEPTED_AT", "FIRST_ADMIN_ACCEPTED_BY"):
        assert f'("{key}",' in block


def test_the_read_back_finds_only_the_admins_own_rows(tmp_path):
    (tmp_path / ".env.frame-test").write_text("FT_DB_POSTGRES_USER=registry\nFT_DB_POSTGRES_DB=frame_test_registry\n")
    seen = {}

    def run(argv, **kw):
        seen["argv"] = argv
        out = ("ops@example.org\toperators\t2.4\t2026-10-22 13:00:00+00\n"
               "someone@else.org\toperators\t2.4\t2026-10-22 13:00:00+00\n")
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
    rows = fu.terms_recorded("myframe", str(tmp_path), "OPS@example.org", run=run)
    assert rows == [("operators", "2.4", "2026-10-22 13:00:00+00")]
    assert seen["argv"][:4] == ["docker", "exec", "myframe-db", "psql"]
    assert "frame_standup" in seen["argv"][-1] and "ops@example.org" not in " ".join(seen["argv"])
    failed = fu.terms_recorded("myframe", str(tmp_path), "ops@example.org",
                               run=lambda *a, **k: types.SimpleNamespace(returncode=2, stdout="", stderr="x"))
    assert failed is None
    assert fu.terms_recorded("myframe", str(tmp_path / "nowhere"), "ops@example.org", run=run) is None


def test_the_summary_line_says_whether_the_registry_recorded_it():
    base = {"version": "2.4", "accepted_at": "2026-10-22T13:00:00Z", "how": "prompt", "admin_email": "ops@example.org"}
    assert "recorded with ops@example.org" in fu.terms_line({**base, "recorded": [("operators", "2.4", "t")]})
    assert "NOT recorded" in fu.terms_line({**base, "recorded": []})
    assert "could not be read back" in fu.terms_line({**base, "recorded": None})
    assert fu.terms_line(None) is None
