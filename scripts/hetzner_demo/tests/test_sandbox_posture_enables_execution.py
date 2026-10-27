"""§TESTBED P0 h (2026-09-19): a sandbox-posture frame has tester execution ON. The compose maps the key through its
FT_REG_ carrier, so the driver must write THAT carrier; the bare key alone was shadowed (the kit's sandbox kept it off)."""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DRIVER = os.path.join(os.path.dirname(HERE), "standup_driver.py")
COMPOSE = os.path.join(os.path.dirname(ROOT), "templates", "frame-test", "docker-compose.frame-test.yml.tmpl")


def test_the_compose_reads_the_carrier():
    assert re.search(r"API_TEST_EXECUTION_ENABLED:\s*\$\{FT_REG_API_TEST_EXECUTION_ENABLED\}", open(COMPOSE).read())


def test_the_driver_writes_the_carrier_with_the_posture_rule():
    fn = open(DRIVER).read()
    fn = fn[fn.index("def mutate_rendered("):]
    m = re.search(r'\("FT_REG_API_TEST_EXECUTION_ENABLED",\s*"true" if \(args\.tester_console or args\.posture != "production"\) else "false"\)', fn)
    assert m, "the carrier the compose reads must follow the posture: ON for sandbox, OFF for production"


def test_every_frame_declares_its_posture():
    """§TESTBED P1: FRAME_POSTURE is the declaration the registry's test-execution gate reads (core/frame_posture.py)."""
    fn = open(DRIVER).read()
    fn = fn[fn.index("def mutate_rendered("):]
    assert re.search(r'\("FRAME_POSTURE",\s*args\.posture\)', fn)
