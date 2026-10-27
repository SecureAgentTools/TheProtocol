"""§TESTBED P5 (2026-09-19): /health shows what a kit image was built from, when its build wrote BUILD_INFO.json."""
import json

from agentvault_registry import main as m


def _reset():
    m._KIT_BUILD_INFO_CACHE.clear()


def test_the_build_info_fields_a_report_needs(tmp_path, monkeypatch):
    f = tmp_path / "BUILD_INFO.json"
    f.write_text(json.dumps({"kit_version": "1.0.0-beta.6", "tree_digest": "a" * 64, "release_digest": "b" * 64,
                             "modified": True, "changed_files": 2, "built_at": "2026-09-19T18:00:00Z",
                             "changed_sample": ["README.md"], "files": 8964}))
    monkeypatch.setenv("KIT_BUILD_INFO_PATH", str(f))
    _reset()
    b = m._kit_build_info()
    assert b == {"kit_version": "1.0.0-beta.6", "tree_digest": "a" * 64, "release_digest": "b" * 64,
                 "modified": True, "changed_files": 2, "built_at": "2026-09-19T18:00:00Z"}


def test_no_file_no_block(tmp_path, monkeypatch):
    monkeypatch.setenv("KIT_BUILD_INFO_PATH", str(tmp_path / "absent.json"))
    _reset()
    assert m._kit_build_info() is None
