"""§SOVKIT K1 (2026-09-14) — the consumer-lag check names the broker from the target, never from a hand list.

The check used to try four legacy names (`agentvault_redpanda`, `redpanda`, ...) and answered "no redpanda/kafka
container found — Kafka may be disabled" on every runner-built frame, whose broker is `<frame>-redpanda`. Now the
containers map decides: an explicit `redpanda` key first, then the event store's and the registry's names with their
suffix swapped, and the legacy list last.
"""
from agentvault_registry.services.diagnostics.checks import kafka_lag


def test_a_runner_built_frame_names_its_own_broker_first():
    t = {"role": "mainframe", "operator_id": "orchard", "containers": {
        "registry": "orchard-registry", "event_store": "orchard-event-store"}}
    names = kafka_lag._candidate_containers(t)
    assert names[0] == "orchard-redpanda"
    assert names.count("orchard-redpanda") == 1, "the store's and the registry's derivations collapse to one name"
    assert names[-4:] == list(kafka_lag.KAFKA_CONTAINER_CANDIDATES)


def test_frame_a_derives_agentvault_redpanda_and_an_explicit_key_wins():
    a = {"role": "mainframe", "operator_id": "registry-a", "containers": {
        "registry": "agentvault_registry_a", "event_store": "agentvault_event_store"}}
    assert kafka_lag._candidate_containers(a)[0] == "agentvault_redpanda"
    e = {"role": "mainframe", "operator_id": "x", "containers": {"redpanda": "my-broker", "registry": "x-registry"}}
    assert kafka_lag._candidate_containers(e)[:2] == ["my-broker", "x-redpanda"]


def test_a_target_without_a_containers_map_still_gets_the_legacy_list():
    assert kafka_lag._candidate_containers({"role": "mainframe", "operator_id": "y"}) == list(kafka_lag.KAFKA_CONTAINER_CANDIDATES)
