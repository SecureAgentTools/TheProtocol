"""§BATCH3 item 4 — the standup driver follows D12: a frame compose is topology only.

Measured on the live sandbox pair (2026-09-05): the rendered composes carried literals
(FRAME_CURRENCY: SBXA, PUBLIC_URL: https://sandbox-a…) where the template interpolates
${FT_*} — the driver's upsert_inline_env rewrote each interpolation into a literal.
Run: python3 -m pytest scripts/hetzner_demo/tests -q   (from the stack root)
"""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("standup_driver", HERE.parent / "standup_driver.py")
drv = importlib.util.module_from_spec(spec); spec.loader.exec_module(drv)

COMPOSE = (
    "services:\n"
    "  demo-registry:\n"
    "    container_name: demo-registry\n"
    "    environment:\n"
    "      BASE_URL: ${FT_REG_BASE_URL}\n"
    "      FRAME_CURRENCY: ${FT_REG_FRAME_CURRENCY}\n"
    "      OLD_LITERAL: http://old\n"
    "  demo-teg:\n"
    "    container_name: demo-teg\n"
    "    environment:\n"
    "      TEG_TOKEN_SIGNING_KEY: ${FT_TEG_TEG_TOKEN_SIGNING_KEY}\n"
    "      TEG_BALANCE_OUTBOX_ENABLED: ${FT_TEG_TEG_BALANCE_OUTBOX_ENABLED}\n"
)
REG = drv.svc_anchor("demo-registry"); TEG = drv.svc_anchor("demo-teg")


def setup_function(_):
    drv.PENDING_ENV_REDIRECTS.clear()


def test_interpolated_key_keeps_its_interpolation_and_the_literal_goes_to_the_env():
    out = drv.upsert_inline_env(COMPOSE, REG, "BASE_URL", "https://demo.example")
    assert out == COMPOSE                                  # compose untouched
    assert drv.PENDING_ENV_REDIRECTS == [("FT_REG_BASE_URL", "https://demo.example")]
    env = drv.flush_env_redirects("EXISTING=1\n")
    assert "FT_REG_BASE_URL=https://demo.example\n" in env and drv.PENDING_ENV_REDIRECTS == []


def test_an_interpolation_as_the_new_value_is_topology_and_still_lands_inline():
    out = drv.upsert_inline_env(COMPOSE, TEG, "TEG_TOKEN_SIGNING_KEY", "${TEG_TOKEN_SIGNING_KEY}")
    assert "TEG_TOKEN_SIGNING_KEY: ${TEG_TOKEN_SIGNING_KEY}\n" in out
    assert drv.PENDING_ENV_REDIRECTS == []


def test_control_a_literal_existing_value_is_still_replaced_inline():
    out = drv.upsert_inline_env(COMPOSE, REG, "OLD_LITERAL", "http://new")
    assert "OLD_LITERAL: http://new\n" in out and drv.PENDING_ENV_REDIRECTS == []


def test_a_key_the_template_lacks_is_added_as_an_interpolation_plus_env_line():
    out = drv.upsert_inline_env(COMPOSE, REG, "NEW_KEY", '"https://x"')
    assert "      NEW_KEY: ${FT_REG_NEW_KEY}\n" in out
    assert drv.PENDING_ENV_REDIRECTS == [("FT_REG_NEW_KEY", '"https://x"')]
    assert "FT_REG_NEW_KEY=https://x\n" in drv.flush_env_redirects("")   # YAML quotes stripped for .env


def test_env_value_quoting():
    assert drv.env_value_for('"true"') == "true"
    assert drv.env_value_for('{"frame-c": "https://h:1"}') == "'" + '{"frame-c": "https://h:1"}' + "'"
    assert drv.env_value_for("SBXA") == "SBXA"


def test_rendered_compose_after_a_driver_pass_carries_no_literal_for_interpolated_keys():
    out = COMPOSE
    for k, v in [("BASE_URL", "https://demo.example"), ("FRAME_CURRENCY", "SBXA")]:
        out = drv.upsert_inline_env(out, REG, k, v)
    out = drv.upsert_inline_env(out, TEG, "TEG_BALANCE_OUTBOX_ENABLED", '"true"')
    assert "SBXA" not in out and "demo.example" not in out and '"true"' not in out
    env = drv.flush_env_redirects("")
    assert {"FT_REG_BASE_URL=https://demo.example", "FT_REG_FRAME_CURRENCY=SBXA", "FT_TEG_TEG_BALANCE_OUTBOX_ENABLED=true"} <= set(env.splitlines())
