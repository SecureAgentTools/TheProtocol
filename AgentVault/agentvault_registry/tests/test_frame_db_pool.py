"""§DBPOOL (2026-10-10): a frame is born with its registry's database pool sized to its database.

With DB_POOL_SIZE / DB_MAX_OVERFLOW unset, database.pool_settings keeps 40 idle and 80 in all per gunicorn worker, and a
SQLAlchemy QueuePool never gives a connection back, so a frame's workers held their burst high-water mark against the
database's max_connections of 100: the sandbox pair (8 workers) filled theirs between rolls (named at V0571 and V0575;
102/100 overnight before V0589; counted per process on 2026-10-10: 4 to 9 per worker, all idle in the pools, no leak).
The provisioner now renders the two from the frame's worker count.
RED control: the tree before §DBPOOL has no registry_pool and renders neither value.
"""
import os
import pathlib
import re

from agentvault_registry.services import frame_test_provisioner as prov


def _ctx(**kw):
    return prov.FrameTestContext(ts=1, **kw)


def test_the_pool_stays_inside_the_budget_for_every_worker_count():
    for workers in range(1, 17):
        pool, over = prov.registry_pool(workers)
        assert pool >= 1 and over >= 0, (workers, pool, over)
        assert workers * (pool + over) <= prov.REGISTRY_DB_BUDGET, (workers, pool, over)


def test_the_measured_frames():
    assert prov.registry_pool(8) == (5, 5), "the sandbox pair"
    assert prov.registry_pool(4) == (10, 10), "EU and ASIA, and the template's default"
    assert prov.registry_pool(1) == (40, 40), "one worker keeps database.pool_settings' own defaults"


def test_the_template_values_carry_the_pool():
    for workers in (4, 8):
        values = prov._template_values(_ctx(workers_reg=workers))
        assert (values["DB_POOL_SIZE"], values["DB_MAX_OVERFLOW"]) == prov.registry_pool(workers)
    default = prov._template_values(_ctx())
    assert (default["DB_POOL_SIZE"], default["DB_MAX_OVERFLOW"]) == prov.registry_pool(prov.DEFAULT_WORKERS_REG)


def test_every_placeholder_in_the_env_template_is_rendered():
    """The env template may only name values the provisioner supplies: a placeholder it does not know is written into the
    frame's env literally (database.pool_settings would read '{{DB_POOL_SIZE}}' and fall back to 40 / 40)."""
    here = pathlib.Path(prov.__file__).resolve()
    roots = [pathlib.Path(os.environ["R50_TREE"])] if os.environ.get("R50_TREE") else []
    roots += [p for p in here.parents if (p / "templates" / "frame-test").is_dir()]
    tmpl = next((r / "templates" / "frame-test" / "frame-test.env.tmpl" for r in roots
                 if (r / "templates" / "frame-test" / "frame-test.env.tmpl").is_file()), None)
    if tmpl is None:   # CI's AgentVault checkout has no stack tree (R50's class): the tests above stand alone
        return
    asked = set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", tmpl.read_text()))
    assert asked, "the env template names no placeholder at all: the wrong file"
    missing = asked - set(prov._template_values(_ctx()))
    assert not missing, f"the env template asks for values the provisioner does not render: {sorted(missing)}"
