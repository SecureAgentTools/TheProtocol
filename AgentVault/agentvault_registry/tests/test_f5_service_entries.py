"""§F5 (2026-09-26): one identity per service. The provisioner's registration plan is pinned without a SPIRE server.

The live change was driven on the sandbox pair by scratchpad/f5/f5.py with exactly these selectors, DNS names and the
never-federated broker; a frame born from the template must register the same, or the writers the template starts fetch
nothing and the frame boots looking healthy while every sidecar waits for a certificate that never comes.
"""
import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "src", "agentvault_registry", "services", "frame_test_provisioner.py")


def _mod():
    spec = importlib.util.spec_from_file_location("frame_test_provisioner", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_plan_names_one_writer_selector_and_only_the_served_names_per_service():
    m = _mod()
    plan = m.planned_service_entries("eu.theprotocol.cloud", "eu", "eu.theprotocol.cloud")
    by_id = {spiffe.split("/service/")[1]: (label, sel, dns) for label, spiffe, sel, dns in plan}
    assert set(by_id) == {"event-store", "eu-nginx-event-store", "eu-nginx-teg", "eu-nginx-federation", "eu-redpanda"}
    for name, (label, sel, dns) in by_id.items():
        assert sel.startswith("docker:label:com.agentvault.service:svid-writer-") and sel.endswith("-eu"), sel
        assert label.startswith("svid-writer-")
    # a client identity carries no DNS name; a server carries exactly the name it serves
    assert by_id["event-store"][2] == []
    assert by_id["eu-nginx-event-store"][2] == ["eu-nginx-event-store"]
    assert by_id["eu-nginx-teg"][2] == ["eu-nginx-teg"]
    assert by_id["eu-nginx-federation"][2] == ["eu-nginx-federation", "eu.theprotocol.cloud"]  # a peer dials the public host too
    assert by_id["eu-redpanda"][2] == ["eu-redpanda"]
    # the selectors are the labels the template's writers carry (persist_template.py / f5.py agree on this spelling)
    assert by_id["eu-nginx-event-store"][1].endswith(":svid-writer-nginx-event-store-eu")
    assert by_id["eu-redpanda"][1].endswith(":svid-writer-redpanda-eu")


def test_no_public_host_means_no_second_name_on_the_federation_gateway():
    m = _mod()
    plan = {s.split("/service/")[1]: d for _l, s, _sel, d in m.planned_service_entries("x.example", "x", "")}
    assert plan["x-nginx-federation"] == ["x-nginx-federation"]


def test_the_broker_and_the_data_identity_are_never_federated_and_the_rest_are():
    m = _mod()
    assert m.never_federated("service/x-redpanda") is True
    assert m.never_federated("service/data") is True
    for path in ("service/teg-layer", "service/event-store", "service/x-nginx-federation", "service/x-registry", "service/registry",
                 "service/redpanda", "operator/op/registry"):
        assert m.never_federated(path) is False, path


def test_a_client_entry_is_created_without_dns_and_a_rekey_passes_only_the_new_selector():
    m = _mod()
    argv = m.spire_entry_argv("create", spiffe_id="spiffe://x/service/teg-layer", parent_id="spiffe://x/spire/agent/x509pop/abc",
                              selectors=["docker:label:com.agentvault.service:svid-writer-teg-x"], dns=[], ttl="14400",
                              federates_with=["y.example"])
    assert "-dns" not in argv and argv.count("-selector") == 1 and "-federatesWith" in argv
    assert argv[argv.index("-selector") + 1] == "docker:label:com.agentvault.service:svid-writer-teg-x"
    # an update REPLACES: the DNS list passed is the whole list (an empty one takes every name off)
    upd = m.spire_entry_argv("update", entry_id="e1", spiffe_id="spiffe://x/service/x-registry", parent_id="p",
                             selectors=["docker:label:com.agentvault.service:svid-writer-x"], dns=[], ttl="14400", federates_with=[])
    assert upd[:4] == ["/opt/spire/bin/spire-server", "entry", "update", "-entryID"] and "-dns" not in upd
