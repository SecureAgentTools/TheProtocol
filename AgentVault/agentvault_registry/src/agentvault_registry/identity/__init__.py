"""Identity management for AgentVault Registry

This module provides SPIFFE/SPIRE identity integration for the Registry backend,
enabling mTLS client connections to the TEG Layer API.
"""

# Import the actual svid_client if available
try:
    from .svid_client import svid_client, SVIDClient
except ImportError:
    # Provide a mock implementation for Docker deployment without pyspiffe
    class MockSVIDClient:
        """Mock SVID client for environments without SPIFFE/SPIRE"""
        
        def is_initialized(self) -> bool:
            """Always return False in mock mode"""
            return False
        
        def initialize(self) -> bool:
            """Always return False in mock mode"""
            return False
        
        def get_spiffe_id(self) -> None:
            """Return None in mock mode"""
            return None
        
        def get_client_cert_config(self) -> None:
            """Return None in mock mode"""
            return None
    
    # Create the mock instance
    svid_client = MockSVIDClient()
    SVIDClient = MockSVIDClient

__all__ = [
    'svid_client',
    'SVIDClient'
]
