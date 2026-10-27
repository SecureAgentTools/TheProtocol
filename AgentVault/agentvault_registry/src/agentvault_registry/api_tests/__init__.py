"""
API Test Suite Package

A modular, category-based test framework for the AgentVault Registry API.
"""

from .base import APITestBase
from .auth_manager import AuthManager
from .endpoints_registry import EndpointsRegistry
from .request_bodies import RequestBodies
from .test_results_analyzer import TestResultsAnalyzer

__version__ = "1.0.0"
__all__ = [
    "APITestBase",
    "AuthManager", 
    "EndpointsRegistry",
    "RequestBodies",
    "TestResultsAnalyzer"
]
