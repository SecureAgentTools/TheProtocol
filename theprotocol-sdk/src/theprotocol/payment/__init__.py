"""
TheProtocol A2A Payment Module — f045

Provides payment verification middleware for agents and a client helper
for acquiring payment tokens before A2A calls.

Usage (agent-side — enforce payment on all A2A calls):

    from theprotocol.payment import PaymentVerifier
    from theprotocol.agent import create_a2a_router
    from fastapi import Depends

    verifier = PaymentVerifier(
        registry_url="https://api.theprotocol.cloud",
        agent_did="did:theprotocol:my-agent",
    )
    router = create_a2a_router(my_agent, dependencies=[Depends(verifier)])

Usage (caller-side — get a payment token before calling an agent):

    from theprotocol.payment import PaymentClient

    client = PaymentClient("https://api.theprotocol.cloud")
    token = await client.get_token(agent_jwt, target_did="...", amount="0.5")
    # Pass token as X-Payment-Token header in A2A request
"""

from .verifier import PaymentVerifier
from .client import PaymentClient
from .authenticator import A2AAuthenticator
from .mtls_client import MtlsAgentClient

__all__ = ["PaymentVerifier", "PaymentClient", "A2AAuthenticator", "MtlsAgentClient"]
