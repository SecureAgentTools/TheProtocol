"""§DOCSFIX CB-355: security.txt names the languages of the frame that serves it, not always English and German.

`Preferred-Languages: en, de` was a literal, so a frame run by someone else (LEGAL_SUITE_MODE operator, the default)
told reporters it reads German. It now follows the provider: LEGAL_SECURITY_LANGUAGES where set; English and German on
a `theprotocol` frame (the production frames, unchanged); otherwise no line (RFC 9116: a reporter then assumes
English).
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ci:ci@localhost:5432/ci")
os.environ.setdefault("API_KEY_SECRET", "ci-dummy-secret-0123456789abcdef")

from agentvault_registry.routers import public_badge as pb  # noqa: E402

# the authors' suite mode, named once: the export's G12 refuses the mode written as a literal setting in a shipped file
AUTHORS_SUITE = "theprotocol"
VARS = ["SECURITY_CONTACT_EMAIL", "LEGAL_SECURITY_EMAIL", "LEGAL_CONTACT_EMAIL", "LEGAL_SUITE_MODE",
        "LEGAL_SECURITY_POLICY_URL", "LEGAL_SECURITY_LANGUAGES", "PUBLIC_UI_URL", "BASE_URL"]


def _frame(monkeypatch, **env):
    for v in VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("LEGAL_SECURITY_EMAIL", "sec@example.invalid")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return [ln for ln in pb._build_security_txt().splitlines() if ln.startswith("Preferred-Languages:")]


def test_an_operators_frame_names_no_language_it_did_not_choose(monkeypatch):
    assert _frame(monkeypatch) == []


def test_the_authors_frames_keep_english_and_german(monkeypatch):
    assert _frame(monkeypatch, LEGAL_SUITE_MODE=AUTHORS_SUITE) == ["Preferred-Languages: en, de"]


def test_a_frame_states_its_own_languages(monkeypatch):
    assert _frame(monkeypatch, LEGAL_SECURITY_LANGUAGES="en, fr") == ["Preferred-Languages: en, fr"]
    assert _frame(monkeypatch, LEGAL_SUITE_MODE=AUTHORS_SUITE, LEGAL_SECURITY_LANGUAGES="en") == [
        "Preferred-Languages: en"]
