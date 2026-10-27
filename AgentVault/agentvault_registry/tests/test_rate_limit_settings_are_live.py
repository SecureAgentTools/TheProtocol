"""§DOCSFIX D6-315 / CB-223 (2026-10-16): the configuration declares only rate-limit settings that limit something.

`RATE_LIMIT_ADMIN`, `RATE_LIMIT_DEVELOPER`, `RATE_LIMIT_AGENT` and `RATE_LIMIT_PUBLIC` were declared in config.py and
read into middleware/rate_limiter.py's `RATE_LIMITS` dict, which nothing consulted: slowapi applies limits per route,
and the module said itself that they were "not wired into the per-endpoint decorators". An operator who set one changed
nothing, and the operator configuration page listed them. They are gone, with the dict; what limits is the default
(`RATE_LIMIT_DEFAULT`, on the shared limiter) and the per-route decorators.
"""
from __future__ import annotations

from agentvault_registry.config import Settings, settings
from agentvault_registry.middleware import rate_limiter as RL

ROLE_SETTINGS = ("RATE_LIMIT_ADMIN", "RATE_LIMIT_DEVELOPER", "RATE_LIMIT_AGENT", "RATE_LIMIT_PUBLIC")


def test_the_role_settings_no_route_applies_are_not_declared():
    declared = set(Settings.model_fields)
    assert "RATE_LIMIT_DEFAULT" in declared, "the read is real: the live setting is found"
    assert [n for n in ROLE_SETTINGS if n in declared] == []


def test_the_unconsumed_role_dict_is_gone():
    assert not hasattr(RL, "RATE_LIMITS")


def test_the_default_still_limits_every_route():
    assert settings.RATE_LIMIT_DEFAULT == "1200/minute"
    limits = [str(lim.limit) for group in RL.shared_limiter._default_limits for lim in group]
    assert limits == ["1200 per 1 minute"], limits
