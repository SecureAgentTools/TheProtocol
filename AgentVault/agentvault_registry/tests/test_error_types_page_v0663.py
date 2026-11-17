"""D6-712 (V0663, gwo_49ccc7efec6ae43112f5bd72; the lead's decision: keep the emitted types, no API change): every error `type` a
registry or a TEG can send has a section on the error types reference page.

errors.py builds each error's RFC 7807 `type` as https://docs.theprotocol.cloud/errors/<type>, and those URLs answered 404. The docs
site now emits a small page per type at /errors/<type>/ pointing at its section of reference/errors.md (the docs one source); this
test holds the source side: the page has a `## <type>` heading for each token the code can emit (the status map, the explicit
error_type= arguments, and the generic fallback "error"), so a new type added to the code with no section on the page fails here.
RED control: against b27f2ebaf there is no reference/errors.md.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REG = ROOT / "src" / "agentvault_registry"
PAGE = REG / "static" / "new_registry_frontend" / "src" / "assets" / "docs" / "reference" / "errors.md"
TEG = ROOT.parent / "agentvault_teg_layer_mvp" / "src"


def _emitted(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    types = set(re.findall(r'^\s*\d{3}:\s*"([a-z_]+)"', text, re.M))                  # the status -> type map
    types |= set(re.findall(r'error_type\s*=\s*"([a-z_]+)"', text))                    # explicit types
    types.add("error")                                                                  # create_error_response's fallback
    return types


def _sources() -> list[Path]:
    out = [p for p in REG.rglob("*.py") if "/tests/" not in str(p) and "error_type" in p.read_text(encoding="utf-8")]
    if TEG.exists():
        out += [p for p in TEG.rglob("errors.py")]
    return out


def test_the_page_exists_and_has_a_section_per_type_the_code_can_emit():
    assert PAGE.exists(), "reference/errors.md is the page /errors/<type> points at"
    headings = set(re.findall(r"^## ([a-z_]+)\s*$", PAGE.read_text(encoding="utf-8"), re.M))
    emitted: set[str] = set()
    for p in _sources():
        emitted |= _emitted(p)
    assert len(emitted) >= 11, f"the scan found too few types to trust: {sorted(emitted)}"
    missing = sorted(emitted - headings)
    assert not missing, f"error types with no section on reference/errors.md: {missing}"


def test_no_section_names_a_type_the_code_never_sends():
    headings = set(re.findall(r"^## ([a-z_]+)\s*$", PAGE.read_text(encoding="utf-8"), re.M))
    emitted: set[str] = set()
    for p in _sources():
        emitted |= _emitted(p)
    assert sorted(headings - emitted) == [], "a section for a type nothing sends"


def test_the_api_chapter_no_longer_says_a_type_is_not_a_page():
    text = (PAGE.parent.parent / "oracle" / "09_api.md").read_text(encoding="utf-8")
    assert "it is an identifier, not a page you can open" not in text
    assert "docs.theprotocol.cloud/reference/errors" in text
