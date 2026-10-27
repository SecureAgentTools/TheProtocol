"""§MTLSHOPS T2 (2026-09-15, with agentvault2-85) — a resume never runs today's driver on another generation's stack.

The runner's op_resume and the driver's --resume-stack-dir branch both ask template_shape.py. These pin each of its two
checks in tests of their own (so a copy with one check removed fails only that check's tests), the refusal sentence, the
real template's generation line, and the driver's resume branch end to end. The runner's wiring is in its own suite.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
_spec = importlib.util.spec_from_file_location("template_shape", HERE / "template_shape.py")
ts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ts)

TEMPLATE = """# fixture compose template
# frame-template-generation: mtlshops-t2
services:
  {{REGISTRY_NAME}}-registry:
    image: r
    volumes:
      - data:/app/data
  # {{REGISTRY_NAME}}-commented-out:
  {{REGISTRY_NAME}}-nginx-edge:
    image: n
volumes:
  {{VOL_PREFIX}}_data_{{TS}}:
networks:
  {{NET_NAME}}:
    external: true
"""
MARKER = "# frame-template-generation: mtlshops-t2\n"


def rendered(name="sbx"):
    return TEMPLATE.replace("{{REGISTRY_NAME}}", name)


def lantern_shaped(name="sbx"):
    """Both witnesses differ: no generation line, and a dropped service in place of the edge."""
    return rendered(name).replace(MARKER, "").replace(f"  {name}-nginx-edge:\n", f"  {name}-pgbouncer:\n")


def test_a_stack_of_todays_generation_and_services_resumes():
    assert ts.template_shape_mismatch(rendered(), TEMPLATE, "sbx") == []


def test_generation_a_stack_with_no_generation_line_is_refused():
    why = ts.template_shape_mismatch(rendered().replace(MARKER, ""), TEMPLATE, "sbx")
    assert why == ["template generation: the stack was rendered from unmarked, today's template is mtlshops-t2"]


def test_generation_a_stack_of_another_generation_is_refused():
    why = ts.template_shape_mismatch(rendered().replace("mtlshops-t2", "mtlshops-t1"), TEMPLATE, "sbx")
    assert why == ["template generation: the stack was rendered from mtlshops-t1, today's template is mtlshops-t2"]


def test_services_a_service_the_template_gained_is_named():
    why = ts.template_shape_mismatch(rendered().replace("  sbx-nginx-edge:\n    image: n\n", ""), TEMPLATE, "sbx")
    assert why == ["services today's template renders and the stack lacks: sbx-nginx-edge"]


def test_services_a_service_the_template_dropped_is_named():
    stack = rendered().replace("volumes:\n  {{VOL_PREFIX}}", "  sbx-pgbouncer:\n    image: p\nvolumes:\n  {{VOL_PREFIX}}")
    why = ts.template_shape_mismatch(stack, TEMPLATE, "sbx")
    assert why == ["services the stack runs and today's template no longer renders: sbx-pgbouncer"]


def test_volumes_networks_and_comments_are_not_services():
    assert ts.compose_services(TEMPLATE) == {"{{REGISTRY_NAME}}-registry", "{{REGISTRY_NAME}}-nginx-edge"}


def test_an_unreadable_side_refuses_it_never_passes(tmp_path):
    why = ts.stack_template_mismatch(str(tmp_path), str(tmp_path / "missing.tmpl"), "sbx")
    assert why and "cannot be read" in why[0]


def test_the_refusal_sentence_names_the_way_out():
    s = ts.refusal_sentence("lantern", ["template generation: the stack was rendered from unmarked, today's template "
                                        "is mtlshops-t2"], TEMPLATE)
    assert s.startswith("lantern cannot be resumed: template generation")
    assert "re-render lantern onto the mtlshops-t2 template first" in s and "needs the Commander's word" in s
    assert "§MTLSHOPS T6" in s and "tear it down and stand it up again" in s


def test_the_real_template_names_its_generation_once():
    text = (ROOT / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl").read_text()
    assert ts.GENERATION_RE.findall(text) == ["f5-per-service"]  # §F5 2026-09-26: one identity per service (six writer services gained; a resume of a mtlshops-t3 stack is refused)


def test_lanterns_shape_is_refused_against_the_real_template():
    """lantern was rendered before T1 took pgbouncer out and before T2 added the edge: refused, whichever witness speaks."""
    text = (ROOT / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl").read_text()
    stack = ts.GENERATION_RE.sub("", text.replace("{{REGISTRY_NAME}}", "lantern"))   # unmarked, whatever today's line is
    stack = stack.replace("  lantern-nginx-edge:\n", "  lantern-pgbouncer:\n", 1)
    assert ts.template_shape_mismatch(stack, text, "lantern")


# ── the driver's resume branch, end to end ─────────────────────────────────────────────────────────────────────────────

class _Died(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.msg, self.code = msg, code


class _LoadedTheProvisioner(Exception):
    pass


@pytest.fixture()
def drv():
    spec = importlib.util.spec_from_file_location("standup_driver_resume_guard", HERE / "standup_driver.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_resume(drv, monkeypatch, tmp_path, stack_text):
    stack = tmp_path / "lantern-1789436785"
    stack.mkdir()
    (stack / "hetzner-demo-run.json").write_text(json.dumps({"name": "lantern", "ts": 1789436785}))
    (stack / "docker-compose.frame-test.yml").write_text(stack_text)
    (stack / ".env.frame-test").write_text("FIRST_ADMIN_EMAIL=a@b.c\n")
    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "docker-compose.frame-test.yml.tmpl").write_text(TEMPLATE)
    monkeypatch.setattr(drv, "TEMPLATES", str(templates))
    monkeypatch.setattr(drv, "validate_args", lambda a: [])
    monkeypatch.setattr(drv, "derive_run_values", lambda a: [])
    monkeypatch.setattr(drv, "kit_directory_default", lambda a: None)

    def died(msg, code=1):
        raise _Died(msg, code)

    def loaded():
        raise _LoadedTheProvisioner()

    monkeypatch.setattr(drv, "die", died)
    monkeypatch.setattr(drv, "load_provisioner", loaded)
    monkeypatch.setattr(sys, "argv", ["standup_driver.py", "--name", "lantern", "--resume-stack-dir", str(stack),
                                      "--resume-from", "wire"])
    drv.main()


def test_the_hand_run_resume_branch_refuses_before_it_loads_the_provisioner(drv, monkeypatch, tmp_path):
    with pytest.raises(_Died) as died:
        _run_resume(drv, monkeypatch, tmp_path, lantern_shaped("lantern"))
    assert died.value.code == 2 and died.value.msg.startswith("lantern cannot be resumed")
    assert "re-render lantern onto the mtlshops-t2 template first" in died.value.msg


def test_the_hand_run_resume_branch_lets_todays_shape_through(drv, monkeypatch, tmp_path):
    with pytest.raises(_LoadedTheProvisioner):
        _run_resume(drv, monkeypatch, tmp_path, rendered("lantern"))


def test_the_driver_asks_before_anything_in_its_resume_branch_loads():
    src = (HERE / "standup_driver.py").read_text()
    branch = re.search(r'_sd = args\.resume_stack_dir\.rstrip\("/"\)(.*?)post_boot\(args, ctx, meta, resume_from=', src, re.S)
    assert branch, "the driver's resume branch moved"
    body = branch.group(1)
    assert body.index("resume_shape_refusal(") < body.index("load_provisioner()")
    assert "die(_shape_refusal, code=2)" in body[:body.index("load_provisioner()")]
