"""
Legacy Compatibility Layer

Provides backward compatibility with the original admin_api_test.py
to ensure smooth migration and allow rollback if needed.
"""

import logging
from typing import Dict, List, Optional, Any
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .runner import SmartTestRunner
from .endpoints_registry import EndpointsRegistry
from .request_bodies import RequestBodies

logger = logging.getLogger(__name__)


class LegacyAPITestAdapter:
    """
    Adapter that provides the same interface as the original admin_api_test.py
    but uses the new modular test infrastructure.
    """
    
    def __init__(self):
        self.runner = SmartTestRunner()
        self.endpoints_registry = EndpointsRegistry()
        self.request_bodies = RequestBodies()
        
        # Expose the registries as the legacy variables
        self.ALL_ENDPOINTS = self.endpoints_registry.get_all_endpoints()
        self.DEFAULT_REQUEST_BODIES = self.request_bodies.get_all_bodies()
    
    async def test_all_api_endpoints(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Legacy function that tests all API endpoints.
        
        This maintains the same interface as the original function.
        """
        logger.info("Running tests via legacy compatibility layer")
        
        # Run all tests
        results = await self.runner.run_all(
            developer_token=developer_token,
            agent_token=agent_token,
            parallel=False,  # Legacy was sequential
            priority_only=False
        )
        
        # Transform results to legacy format
        all_results = []
        for category_data in results.get('category_results', {}).values():
            if 'results' in category_data:
                all_results.extend(category_data['results'])
        
        # Calculate summary in legacy format
        total = len(all_results)
        healthy = sum(1 for r in all_results if r.get('healthy', False))
        
        return {
            "timestamp": results.get('timestamp'),
            "total_endpoints": total,
            "healthy_endpoints": healthy,
            "unhealthy_endpoints": total - healthy,
            "success_percentage": round((healthy / total * 100) if total > 0 else 0, 1),
            "results": all_results
        }
    
    async def test_single_endpoint(
        self,
        method: str,
        path: str,
        auth_type: str = "none",
        body: Optional[Dict[str, Any]] = None,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        is_form_data: bool = False
    ) -> Dict[str, Any]:
        """
        Legacy function to test a single endpoint.
        
        This maintains the same interface as the original function.
        """
        # Extract category from path
        category = self._extract_category(path)
        
        # Load the appropriate test module
        test_class = await self.runner.load_category_module(category)
        if not test_class:
            # Fallback to base tester
            from .base import APITestBase
            tester = APITestBase(self.runner.base_url)
        else:
            tester = test_class(self.runner.base_url)
        
        # Run the test
        result = await tester.test_endpoint(
            method=method,
            path=path,
            auth_type=auth_type,
            body=body,
            developer_token=developer_token,
            agent_token=agent_token,
            is_form_data=is_form_data
        )
        
        return result
    
    def _extract_category(self, path: str) -> str:
        """Extract category from endpoint path"""
        path = path.lstrip('/').replace('api/v1/', '')
        parts = path.split('/')
        
        if parts:
            category = parts[0]
            # Handle special cases
            if category == "agent" and len(parts) > 1:
                if parts[1] == "cards":
                    return "agent_cards"
                elif parts[1] == "logs":
                    return "agent_logs"
            return category
        
        return "unknown"


# Global instance for legacy compatibility
legacy_adapter = LegacyAPITestAdapter()

# Expose legacy functions at module level
ALL_ENDPOINTS = legacy_adapter.ALL_ENDPOINTS
DEFAULT_REQUEST_BODIES = legacy_adapter.DEFAULT_REQUEST_BODIES


async def test_all_api_endpoints(
    developer_token: Optional[str] = None,
    agent_token: Optional[str] = None
) -> Dict[str, Any]:
    """Legacy entry point for testing all endpoints"""
    return await legacy_adapter.test_all_api_endpoints(developer_token, agent_token)


async def test_single_endpoint(
    method: str,
    path: str,
    auth_type: str = "none",
    body: Optional[Dict[str, Any]] = None,
    developer_token: Optional[str] = None,
    agent_token: Optional[str] = None,
    is_form_data: bool = False
) -> Dict[str, Any]:
    """Legacy entry point for testing single endpoint"""
    return await legacy_adapter.test_single_endpoint(
        method, path, auth_type, body, developer_token, agent_token, is_form_data
    )


# Migration helper
def check_migration_readiness() -> Dict[str, Any]:
    """
    Check if the new modular system is ready to replace the legacy system.
    
    Returns a report on migration readiness.
    """
    import importlib.util
    from pathlib import Path
    
    readiness = {
        "ready": True,
        "issues": [],
        "modules_found": [],
        "modules_missing": []
    }
    
    # Check core modules
    core_modules = [
        "base", "auth_manager", "endpoints_registry", 
        "request_bodies", "test_results_analyzer", "runner"
    ]
    
    for module in core_modules:
        module_path = Path(__file__).parent / f"{module}.py"
        if module_path.exists():
            readiness["modules_found"].append(module)
        else:
            readiness["modules_missing"].append(module)
            readiness["ready"] = False
            readiness["issues"].append(f"Core module missing: {module}")
    
    # Check category modules
    categories_dir = Path(__file__).parent / "categories"
    if not categories_dir.exists():
        readiness["ready"] = False
        readiness["issues"].append("Categories directory missing")
    else:
        # Check for at least one category implementation
        category_count = 0
        for path in categories_dir.iterdir():
            if path.is_dir() and not path.name.startswith('_'):
                test_file = path / f"test_{path.name}.py"
                if test_file.exists():
                    category_count += 1
                    readiness["modules_found"].append(f"category:{path.name}")
        
        if category_count == 0:
            readiness["ready"] = False
            readiness["issues"].append("No category test modules found")
    
    # Check if endpoints match
    try:
        registry = EndpointsRegistry()
        new_count = registry.get_total_endpoint_count()
        
        # TODO: Compare with original count (187)
        if new_count < 187:
            readiness["issues"].append(
                f"Endpoint count mismatch: {new_count} vs 187 original"
            )
    except Exception as e:
        readiness["ready"] = False
        readiness["issues"].append(f"Failed to load endpoints registry: {e}")
    
    return readiness


if __name__ == "__main__":
    # Test migration readiness
    readiness = check_migration_readiness()
    print("Migration Readiness Check:")
    print(f"Ready: {readiness['ready']}")
    print(f"Modules Found: {len(readiness['modules_found'])}")
    print(f"Issues: {len(readiness['issues'])}")
    
    if readiness['issues']:
        print("\nIssues:")
        for issue in readiness['issues']:
            print(f"  - {issue}")
