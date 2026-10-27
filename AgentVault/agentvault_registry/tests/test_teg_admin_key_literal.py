"""§MONEY-M3a (2026-09-03) — R26: the TEG admin key has NO fallback literal in the registry tree.

Five call sites read ``settings.TEG_ADMIN_API_KEY`` (a DECLARED field, config.py); before this
batch they read ``getattr(settings, 'TEG_ADMIN_API_KEY', '<a known dev key>')`` — dead as a
fallback (the field always exists) and live as a credential string in every shipped image.
A ``getattr`` with a non-empty default is refused so the literal cannot return by that door.
The literal is written SPLIT here so this file can never match its own gate."""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
FRAG = "development-admin-" + "api-key-change-in-production"
GETATTR_DEFAULT = re.compile(
    r"getattr\(\s*settings\s*,\s*['\"]TEG_ADMIN_API_KEY['\"]\s*,\s*['\"][^'\"]+['\"]", re.S)


def _py_files():
    return [p for p in SRC.rglob("*.py") if p.is_file() and ".bak" not in p.name and "tests" not in p.parts]


def test_population_is_the_whole_package():
    assert len(_py_files()) > 500


def test_no_fallback_literal_anywhere():
    hits = [str(p.relative_to(SRC)) for p in _py_files() if FRAG in p.read_text(errors="ignore")]
    assert hits == [], hits


def test_no_getattr_with_a_default_value():
    hits = [str(p.relative_to(SRC)) for p in _py_files()
            if GETATTR_DEFAULT.search(p.read_text(errors="ignore"))]
    assert hits == [], hits


def test_the_setting_is_declared():
    cfg = (SRC / "config.py").read_text()
    assert re.search(r"^\s+TEG_ADMIN_API_KEY:\s*str\s*=", cfg, re.M)
