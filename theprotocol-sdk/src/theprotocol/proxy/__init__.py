"""TheProtocol Proxy: give a legacy system an agent identity on TheProtocol, and translate in both directions.

    legacy system ──source──▶ [ mapping ] ──action──▶ TheProtocol      (inbound: attest, ask, pay, deliver)
    legacy system ◀──sink──── [ mapping ] ◀──events── TheProtocol      (outbound: evidence, settlement, cards)

The plugin interface (sources, actions, sinks, found by entry point) is in theprotocol.proxy.plugins; the contract tests
every plugin passes are in theprotocol.proxy.testing. The runtime is theprotocol.proxy.runtime.Proxy, run from a spec
(theprotocol.proxy.spec.read) or by the tp-proxy command (theprotocol.proxy.cli).
"""
from .plugins import (
    BASES,
    GROUPS,
    INTERFACE_VERSION,
    Action,
    Event,
    Outcome,
    PluginError,
    ProxyContext,
    Record,
    Refused,
    Retry,
    Sink,
    Source,
    StateStore,
    available,
    load,
    problems,
)

__all__ = [
    "BASES", "GROUPS", "INTERFACE_VERSION", "Action", "Event", "Outcome", "PluginError", "ProxyContext", "Record",
    "Refused", "Retry", "Sink", "Source", "StateStore", "available", "load", "problems",
]
