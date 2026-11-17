"""V0667 (order gwo_4d55fcc1535962f55866740c, session-volume): the provisioner writes 5 x 50 MB of logs into the registry and the teg-layer of every operator compose it adapts.

The operators' bundle compose wrote no `logging:` at all, so an operator's registry and TEG kept whatever the HOST's docker daemon defaults to (50m x 5 on this box today): true while nobody edits
/etc/docker/daemon.json, and invisible to anyone reading the compose. V0666's console proof lost a traceback to a 10m x 3 rotation on the frames; the frames' template now writes 50m x 5 (stack
contract rule R44) and the stack's operator template does too. This pins the PROVISIONER's half: whatever template it is given (an older bundle with none, a block of 10m x 3), what it hands back
carries the written 50m x 5 on those two services and on no others, idempotently, and says so when it cannot (a template without the service).

The module is loaded by path: core/operator_compose.py imports only the standard library.
"""
import importlib.util
import pathlib
import re

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "core" / "operator_compose.py"
if _SRC.exists():
    _spec = importlib.util.spec_from_file_location("operator_compose_logkeep", _SRC)
    oc = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(oc)
else:
    from agentvault_registry.core import operator_compose as oc

KEEP = '    logging:\n      driver: json-file\n      options:\n        max-size: "50m"\n        max-file: "5"\n'

BARE = """services:
  registry:
    image: images.example/registry:x
    container_name: ${REGISTRY_NAME:-operator}-registry
    restart: unless-stopped
    ports:
      - "12000:8000"
  teg-layer:
    image: images.example/teg-layer:x
    container_name: ${REGISTRY_NAME:-operator}-teg
    restart: unless-stopped
    ports:
      - "12080:8080"
  nginx-federation:
    container_name: ${REGISTRY_NAME:-operator}-nginx-federation
    restart: unless-stopped
    ports:
      - "12443:8443"
  db:
    image: postgres:18
    restart: unless-stopped
"""

SMALL = BARE.replace("    ports:\n      - \"12080:8080\"\n", '    logging:\n      driver: json-file\n      options:\n        max-size: "10m"\n        max-file: "3"\n    ports:\n      - "12080:8080"\n')


def _adapt(text):
    return oc.adapt_operator_compose(text, safe="probe", domain="probe.op.example", reg_port=31000, fed_port=31443, teg_port=31080, worker_count=2, identity_network="probe-identity")


def _logging_of(compose, service):
    blk = re.search(rf"(?ms)^  {re.escape(service)}:\n(.*?)(?=^  \S|\Z)", compose)
    if not blk:
        return None
    m = re.search(r'max-size:\s*"?([^"\s]+)"?\s*\n\s*max-file:\s*"?(\d+)', blk.group(1))
    return (m.group(1), int(m.group(2))) if m else None


def test_a_bundle_with_no_logging_gets_the_written_block_on_the_registry_and_the_teg_layer_only():
    out, notes = _adapt(BARE)
    assert _logging_of(out, "registry") == ("50m", 5) and _logging_of(out, "teg-layer") == ("50m", 5)
    assert _logging_of(out, "nginx-federation") is None and _logging_of(out, "db") is None, "no other service of the operator is touched"
    assert out.count("max-size") == 2
    assert any("logging" in n and "50m x 5" in n for n in notes), notes


def test_a_small_block_is_replaced_never_doubled():
    out, _notes = _adapt(SMALL)
    assert _logging_of(out, "teg-layer") == ("50m", 5) and out.count("max-size") == 2 and '"10m"' not in out


def test_a_block_that_already_keeps_at_least_that_is_left_as_written():
    big = BARE.replace("    ports:\n      - \"12080:8080\"\n", '    logging:\n      driver: json-file\n      options:\n        max-size: "200m"\n        max-file: "10"\n    ports:\n      - "12080:8080"\n')
    out, _n = _adapt(big)
    assert _logging_of(out, "teg-layer") == ("200m", 10) and _logging_of(out, "registry") == ("50m", 5)


def test_it_is_idempotent_and_the_second_adaptation_writes_nothing_new():
    once, _ = oc.ensure_log_keep(BARE)
    twice, notes = oc.ensure_log_keep(once)
    assert twice == once and notes == []


def test_the_block_sits_right_after_restart_and_a_service_without_one_gets_it_under_its_name():
    out, _ = oc.ensure_log_keep(BARE)
    assert "    restart: unless-stopped\n" + KEEP in out
    bare2 = "services:\n  registry:\n    ports:\n      - \"1:1\"\n  teg-layer:\n    ports:\n      - \"2:2\"\n"
    out2, _ = oc.ensure_log_keep(bare2)
    assert _logging_of(out2, "registry") == ("50m", 5) and _logging_of(out2, "teg-layer") == ("50m", 5)


def test_a_template_without_the_service_is_a_note_never_an_exception():
    out, notes = oc.ensure_log_keep("services:\n  registry:\n    image: x\n    restart: unless-stopped\n")
    assert _logging_of(out, "registry") == ("50m", 5) and any("teg-layer" in n and "not found" in n for n in notes), notes


def test_the_step_adds_the_two_blocks_and_changes_no_other_line():
    with_step, _ = _adapt(BARE)
    assert with_step.replace("\n".join(oc.LOG_KEEP_BLOCK) + "\n", "").count("logging:") == 0
    only_step, _ = oc.ensure_log_keep(BARE)
    assert only_step.replace("\n".join(oc.LOG_KEEP_BLOCK) + "\n", "") == BARE, "removing the two blocks returns the template byte for byte"
