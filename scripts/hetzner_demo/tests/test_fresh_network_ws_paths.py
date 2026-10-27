"""§FRAMELIC findings row 178 — `ws_path` is CONSOLE-RELATIVE, and getting that wrong makes a
console draw itself twice.

The FE streams one socket per frame and dedups by key AND by same-origin path. Its LOCAL seed
always uses `/ws/events`. So a frame that names ITSELF in its own FRESH_NETWORK_JSON with
`/ws/events-<self>` presents a path the seed has never seen — dedup cannot fire, the console
opens the same EventStore twice, and the frame appears as two tiles. Measured on EU (his eye:
"eu is already local so its doubled in the live ledger").

⚠ These legs FAIL against a builder that gives the own frame a `/ws/events-<self>` path.
"""
import json
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "scripts" / "hetzner_demo"))

import standup_driver as drv  # noqa: E402


def _args(peers):
    a = types.SimpleNamespace(name="eu", frame_label="EU", ticker="ECU", env_label="sandbox",
                              public_url="https://eu.theprotocol.cloud/", es_public_url="https://eu-es.theprotocol.cloud/")
    a._peer_ledgers = peers
    return a


def test_the_own_frame_streams_the_LOCAL_socket():
    out = json.loads(drv._fresh_network_json(_args({"asia": 8471})))
    me = next(f for f in out if f["slug"] == "eu")
    assert me["ws_path"] == "/ws/events", \
        "the own frame must use the local socket or the console draws itself twice"


def test_each_peer_gets_its_own_lane():
    out = json.loads(drv._fresh_network_json(_args({"asia": 8471, "brrr": 8481})))
    assert {f["slug"]: f["ws_path"] for f in out if f["slug"] != "eu"} == \
        {"asia": "/ws/events-asia", "brrr": "/ws/events-brrr"}


def test_paths_are_unique_so_dedup_cannot_collapse_two_real_frames():
    out = json.loads(drv._fresh_network_json(_args({"asia": 8471, "brrr": 8481})))
    paths = [f["ws_path"] for f in out]
    assert len(paths) == len(set(paths)), f"two frames share a socket path: {paths}"


def test_no_peers_means_one_entry_on_the_local_socket():
    """The control: a lone frame still names itself, still on /ws/events, so its tile is the
    seed's tile rather than a second one."""
    out = json.loads(drv._fresh_network_json(_args({})))
    assert len(out) == 1 and out[0]["ws_path"] == "/ws/events"


def test_every_entry_names_public_addresses_never_a_docker_port():
    """§MTLSHOPS T2 (S4): a frame's registry and store listen on sockets, so a docker name's plain port answers nothing."""
    out = json.loads(drv._fresh_network_json(_args({"asia": 8471})))
    me = next(f for f in out if f["slug"] == "eu")
    assert me["registry_url"] == "https://eu.theprotocol.cloud" and me["es_url"] == "https://eu-es.theprotocol.cloud"
    for f in out:
        assert f["registry_url"].startswith("https://") and f["es_url"].startswith("https://"), f
        assert ":8000" not in f["registry_url"] and ":8200" not in f["es_url"], f


def test_a_peer_currency_is_omitted_rather_than_guessed():
    """§LOCTRUTH: a value invented for legibility must never be published as fact. The driver
    knows its OWN currency and cannot know a peer's."""
    out = json.loads(drv._fresh_network_json(_args({"asia": 8471})))
    me = next(f for f in out if f["slug"] == "eu")
    peer = next(f for f in out if f["slug"] == "asia")
    assert me.get("currency") == "ECU"
    assert "currency" not in peer, "the driver cannot know a peer's currency; it must not invent one"
