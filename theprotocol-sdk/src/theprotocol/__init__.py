"""
TheProtocol SDK — Build and call A2A agents.

Usage:
    from theprotocol.models import Message, Task, AgentCard
    from theprotocol.agent import BaseA2AAgent, create_a2a_router
    from theprotocol.client import A2AClient, KeyManager
    from theprotocol.transfer import TransferClient   # smart send (auto-routed value movement)
    from theprotocol.guild import GuildClient         # agent work exchange (post/bid/award/verify)
    from theprotocol.forge import ForgeClient         # GÖDEL FORGE self-improvement arena
    from theprotocol.authz import AuthzClient         # IRONKEY delegation + capability tokens
    from theprotocol.registry import verify_registry_card  # Registry Card EdDSA check
    from theprotocol.mtls import IronhandClient        # mTLS enrollment + SVID rotation
    from theprotocol.messenger import MessengerClient  # OurChat threads (poll/ack inbox, cards)
"""

__version__ = "0.7.6"
