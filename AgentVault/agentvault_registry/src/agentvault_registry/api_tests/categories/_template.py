"""
Category Test Template

Base template for creating category-specific test modules.
Copy this file and customize for each category.
"""

import logging
from typing import List, Optional

from ..base import APITestBase

logger = logging.getLogger(__name__)


class CategoryTestTemplate(APITestBase):
    """
    Template for category-specific tests.
    
    To use:
    1. Copy this file to test_<category>.py
    2. Rename class to Test<Category>
    3. Set CATEGORY_NAME
    4. Define PRIORITY_ENDPOINTS if needed
    5. Customize setup() if needed
    """
    
    # REQUIRED: Set the category name
    CATEGORY_NAME = "template"  # Change this!
    
    # OPTIONAL: Define priority endpoints to test first
    PRIORITY_ENDPOINTS = []  # e.g., ["/agents/me", "/agents/heartbeat"]
    
    # OPTIONAL: Set rate limit for this category (requests per minute)
    RATE_LIMIT = 100
    
    # OPTIONAL: Set custom timeout for slow endpoints
    TIMEOUT = 60.0
    
    async def setup(self):
        """
        Category-specific setup.
        
        Override this method to:
        - Set up test data
        - Configure special authentication
        - Initialize category-specific resources
        """
        await super().setup_category(self.CATEGORY_NAME)
        
        # Example: Create test data
        # self.test_agent_id = await self.create_test_agent()
        
        # Example: Configure special headers
        # self.custom_headers = {"X-Special-Header": "value"}
    
    async def teardown(self):
        """
        Category-specific cleanup.
        
        Override this method to:
        - Clean up test data
        - Release resources
        """
        # Example: Delete test data
        # if hasattr(self, 'test_agent_id'):
        #     await self.delete_test_agent(self.test_agent_id)
        pass
    
    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Test all endpoints in this category"""
        return await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=False
        )
    
    async def test_priority(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Test only priority endpoints in this category"""
        if not self.PRIORITY_ENDPOINTS:
            logger.warning(f"No priority endpoints defined for {self.CATEGORY_NAME}")
            return await self.test_all(developer_token, agent_token)
        
        return await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=True
        )
    
    async def test_specific_endpoint(
        self,
        method: str,
        path: str,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        body: Optional[dict] = None
    ):
        """Test a specific endpoint with custom parameters"""
        # Get endpoint info
        endpoint_info = self.endpoints_registry.get_endpoint(method, path)
        if not endpoint_info:
            logger.warning(f"Endpoint {method} {path} not found in registry")
            auth_type = self.auth_manager.infer_auth_type(method, path)
        else:
            auth_type = endpoint_info['auth']
        
        # Use custom body or default
        if body is None and method in ['POST', 'PUT', 'PATCH']:
            body = self.request_bodies.get_body(path)
        
        return await self.test_endpoint(
            method=method,
            path=path,
            auth_type=auth_type,
            body=body,
            developer_token=developer_token,
            agent_token=agent_token,
            timeout=self.TIMEOUT
        )
    
    # Add category-specific helper methods below
    # Example:
    # async def create_test_agent(self) -> str:
    #     """Create a test agent for this category"""
    #     # Implementation here
    #     pass
