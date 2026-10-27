"""§LOCTRUTH — a globe-legibility city must never be published as an agent's location.

`core/operator_default_locations.pick_default_location` spreads operator glyphs across the Cesium globe
so they do not stack on the mainframe (§pass66). `federation_sync` stamps the DEVELOPER's lat/lng onto
every agent card it exports, so if an auto-picked city reaches the developer row it leaves the globe and
becomes a geographic FACT on a signed, federated card. Measured on the EU/ASIA pair before this: agents
of the `hochiminh` operator published "Lagos, Nigeria"; `shenzhen` published Chicago; `lisbon` Madrid;
`amsterdam` Vancouver — each operator's own registry card carried its real city all along.

These pin the SOURCE, because the behaviour needs a provisioned operator to observe and a fixture with a
declared location passes either way — the same reason the pagination tiebreak had to be pinned on the
compiled statement.
"""
import inspect
import re


def test_provisioner_takes_declaredness_and_gates_the_developer_stamp():
    from agentvault_registry.services import cloud_provisioner

    src = inspect.getsource(cloud_provisioner.provision_cloud_operator)
    assert "location_is_declared" in src.split("\n\n")[0] or "location_is_declared" in src[:4000], \
        "provision_cloud_operator no longer takes location_is_declared"
    m = re.search(r"if latitude is not None and longitude is not None([^\n:]*):", src)
    assert m, "the developer lat/lng stamp is gone or reshaped — re-read before deleting this test"
    assert "location_is_declared" in m.group(1), (
        "the admin developer is stamped with a location that may have been auto-picked; an agent card "
        "exported from that developer would publish a globe-legibility city as its own address"
    )


def test_both_provisioning_paths_pass_declaredness():
    from agentvault_registry.routers import cloud_operators, operator_self_service

    for mod, name in ((cloud_operators, "admin"), (operator_self_service, "self-service")):
        src = inspect.getsource(mod)
        assert "location_is_declared=_declared" in src, f"the {name} path does not tell the provisioner"
        assert "_declared = " in src, f"the {name} path never computes declared-ness"
