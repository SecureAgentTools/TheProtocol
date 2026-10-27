"""§F6 stage 5 (2026-09-27, his words "finish f6 with the parallel session"): the frame template's registry holds no host
reach of its own and sends every host job to the frame runner (contract rule R38).

Stage 3 took the docker socket, the host stack and the host's nginx sites off sbx-beta's registry (17:49:14Z) and stage 4
the x509pop CA, each with the operator lifecycle proven through the runner (the b1opa/b1opb proofs). This pins the same
posture into every frame the template builds: no such mount as a line of the registry's own (a host-reach grant arrives
only through {{REGISTRY_HOST_MOUNTS}}, rendered behind the provisioner's confirmation phrase), and HOST_REACH_PREFER plus
the four F6 switches interpolated from FT_REG_* and set to runner, because each one's default reaches for a socket.
Every control below builds a template that must fail, and fails for the reason it names.
"""
from __future__ import annotations

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("frame_template_contract_r38", ROOT / ".forgejo" / "checks" / "frame_template_contract.py")
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)

TPL = (ROOT / "templates" / "frame-test" / "docker-compose.frame-test.yml.tmpl").read_text(encoding="utf-8")
ENV = (ROOT / "templates" / "frame-test" / "frame-test.env.tmpl").read_text(encoding="utf-8")
REG_ENV_ANCHOR = "      HOST_REACH_PREFER: ${FT_REG_HOST_REACH_PREFER}\n"
REG_VOL_ANCHOR = "      - {{STACK_DIR}}/operator-bundles:/app/operator-bundles\n"


def test_the_template_holds_no_host_reach_and_routes_to_the_runner():
    assert contract.f6_host_reach_contract(TPL, ENV) == []


def test_the_registry_block_is_the_one_measured():
    reg = contract._service_block(TPL, "registry")
    assert reg and REG_ENV_ANCHOR in reg and REG_VOL_ANCHOR in reg, "the anchors the controls edit sit in the registry block"
    assert contract._service_block(TPL, "no-such-service") is None


def _with_mount(line):
    assert TPL.count(REG_VOL_ANCHOR) == 1
    return TPL.replace(REG_VOL_ANCHOR, REG_VOL_ANCHOR + f"      - {line}\n")


def test_control_the_old_ca_mount_is_caught():
    out = contract.f6_host_reach_contract(_with_mount("{{STACK_DIR}}/x509pop-certs:/opt/spire-ca:ro"), ENV)
    assert len(out) == 1 and "/opt/spire-ca" in out[0]


def test_control_a_literal_socket_or_host_dir_is_caught():
    for line, word in (("/var/run/docker.sock:/var/run/docker.sock:ro", "docker.sock"),
                       ("/opt/theprotocol/stack:/host-stack", "/host-stack"),
                       ("/etc/nginx/sites-enabled:/host-nginx-sites", "/host-nginx-sites")):
        out = contract.f6_host_reach_contract(_with_mount(line), ENV)
        assert len(out) == 1 and word in out[0], (line, out)


def test_a_comment_naming_the_old_mount_is_not_a_mount():
    commented = TPL.replace(REG_VOL_ANCHOR, REG_VOL_ANCHOR + "      # was: - {{STACK_DIR}}/x509pop-certs:/opt/spire-ca:ro\n")
    assert contract.f6_host_reach_contract(commented, ENV) == []


def test_another_services_socket_is_not_the_registrys():
    # the SPIRE agent keeps its own docker socket (the workload attestor) in its own block; R38 reads the registry only
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in TPL
    assert contract.f6_host_reach_contract(TPL, ENV) == []


def test_control_a_switch_left_at_its_default_is_caught():
    for sw in contract._F6_SWITCHES:
        env = ENV.replace(f"FT_REG_{sw}=runner\n", f"FT_REG_{sw}=local\n")
        assert env != ENV
        out = contract.f6_host_reach_contract(TPL, env)
        assert out == [f"the env template must set FT_REG_{sw}=runner"], (sw, out)


def test_control_a_switch_missing_from_the_registry_environment_is_caught():
    for sw in contract._F6_SWITCHES:
        line = f"      {sw}: ${{FT_REG_{sw}}}\n"
        assert TPL.count(line) == 1, sw
        out = contract.f6_host_reach_contract(TPL.replace(line, ""), ENV)
        assert len(out) == 1 and sw in out[0] and "environment" in out[0], (sw, out)


def test_control_an_inline_value_instead_of_the_interpolation_is_caught():
    line = "      OPERATOR_LIFECYCLE_VIA: ${FT_REG_OPERATOR_LIFECYCLE_VIA}\n"
    out = contract.f6_host_reach_contract(TPL.replace(line, "      OPERATOR_LIFECYCLE_VIA: runner\n"), ENV)
    assert len(out) == 1 and "OPERATOR_LIFECYCLE_VIA" in out[0]
