"""§ONESHOT (2026-09-12) — a frame may declare that it sends no mail, and the production validator honours it.

The validator treats any frame with a public BASE_URL as production and required SMTP or a parent relay,
so a mail-less sandbox frame (the standup driver's honest "no relay supplied" branch) restart-looped at
import — the first §ONESHOT proof run found it, on a branch nobody had exercised since 09-07. The three
shapes are pinned here: SMTP passes, MAIL_DISABLED passes, neither refuses with a sentence that names the
flag, and the flag beside a configured relay is refused as a contradiction.
"""
import os

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
os.environ.setdefault("API_KEY_SECRET", "x" * 48)

from agentvault_registry.config import Settings  # noqa: E402

BASE = dict(DATABASE_URL="postgresql+asyncpg://u:p@localhost/db", API_KEY_SECRET="k" * 48,
            BASE_URL="https://juice.theprotocol.cloud", ALLOWED_ORIGINS=["https://juice.theprotocol.cloud"],
            IS_CENTRAL_REGISTRY=False, MAIL_SERVER=None, MAIL_USERNAME=None, MAIL_FROM=None,
            MAIL_RELAY_PARENT_URL=None, MAIL_RELAY_LICENSE=None)


def _settings(**over):
    kw = dict(BASE); kw.update(over)
    return Settings(_env_file=None, **kw)


def test_a_public_frame_with_no_mail_shape_is_refused_and_told_about_the_flag():
    with pytest.raises(ValueError) as e:
        _settings().validate_production_config()
    assert "MAIL_DISABLED" in str(e.value) and "Email configuration incomplete" in str(e.value)


def test_a_declared_mail_less_frame_boots():
    _settings(MAIL_DISABLED=True).validate_production_config()


def test_smtp_still_passes_and_the_flag_beside_it_is_a_contradiction():
    _settings(MAIL_SERVER="smtp.example", MAIL_USERNAME="u", MAIL_FROM="noreply@juice.example").validate_production_config()
    with pytest.raises(ValueError) as e:
        _settings(MAIL_SERVER="smtp.example", MAIL_USERNAME="u", MAIL_FROM="noreply@juice.example", MAIL_DISABLED=True).validate_production_config()
    assert "contradicts" in str(e.value)


def test_the_flag_defaults_off():
    assert Settings.model_fields["MAIL_DISABLED"].default is False
