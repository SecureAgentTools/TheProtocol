"""§SOVKIT K1 (2026-09-14) — the driver's Kafka gate reads `rpk topic list` by its columns, never by position of a
name: the header row is skipped, a row whose second column is not a number is not a topic row, and every topic the
env names must sit at the partitions the env names (the init service's contract)."""
from __future__ import annotations

import importlib.util
import os

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("standup_driver_k1", os.path.join(os.path.dirname(HERE), "standup_driver.py"))
drv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drv)

RPK = """NAME                           PARTITIONS  REPLICAS
_schemas                       1           1
theprotocol.events.financial   4           1
theprotocol.events.governance  4           1
theprotocol.events.system      2           1
"""


def test_rpk_topic_list_is_read_by_column():
    parts = drv.rpk_topic_partitions(RPK)
    assert parts == {"_schemas": 1, "theprotocol.events.financial": 4, "theprotocol.events.governance": 4,
                     "theprotocol.events.system": 2}


def test_a_topic_at_the_wrong_partition_count_is_named():
    parts = drv.rpk_topic_partitions(RPK)
    topics = ["theprotocol.events.financial", "theprotocol.events.governance", "theprotocol.events.system"]
    wrong = {t: parts.get(t) for t in topics if parts.get(t) != 4}
    assert wrong == {"theprotocol.events.system": 2}


def test_an_empty_or_refused_listing_yields_nothing():
    assert drv.rpk_topic_partitions("") == {}
    assert drv.rpk_topic_partitions("unable to request metadata: SASL authentication failed") == {}
