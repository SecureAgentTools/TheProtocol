"""
Auth Test Module

Tests for authentication and authorization endpoints including
login, registration, token management, and API keys.
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

# OWL32 FIX: Was '../enhanced_base' (categories level) but file is at api_tests level
from ...enhanced_base import EnhancedAPITestBase

logger = logging.getLogger(__name__)


class TestAuth(EnhancedAPITestBase):
    """
    Test suite for authentication endpoints.
    
    Auth is foundational - many other categories depend on successful auth.
    """
    
    CATEGORY_NAME = "auth"
    
    # Priority endpoints - test these first
    PRIORITY_ENDPOINTS = [
        "/auth/login",           # Basic login
        "/auth/agent/token",     # Agent authentication
        "/auth/profile",         # Verify auth works
        "/auth/logout",          # Cleanup
    ]
    
    # Auth has lower rate limits
    RATE_LIMIT = 30  # 30 requests per minute
    
    # Test credentials
    TEST_USERS = {
        "valid": {
            "username": "test@example.com",
            "password": "TestPass123!"
        },
        "invalid": {
            "username": "invalid@example.com",
            "password": "WrongPassword"
        },
        "agent": {
            "username": "test_client_id",
            "password": "test_client_secret"
        }
    }
    
    async def setup(self):
        """Set up auth test environment"""
        await super().setup_category(self.CATEGORY_NAME)
        
        # Store tokens obtained during testing
        self.obtained_tokens = {
            "developer": None,
            "agent": None,
            "api_key": None
        }
        
        logger.info("Auth test setup complete")
    
    async def test_login_flow(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test complete login/logout flow"""
        results = {}
        
        # 1. Test login with valid credentials
        login_result = await self.test_endpoint(
            method="POST",
            path="/auth/login",
            auth_type="none",
            body=self.TEST_USERS["valid"],
            is_form_data=True  # Login uses form data
        )
        results["login_valid"] = login_result
        
        if login_result['healthy'] and login_result.get('responseData'):
            # Extract token if provided
            response_data = login_result['responseData']
            if isinstance(response_data, dict):
                token = response_data.get('access_token') or response_data.get('token')
                if token:
                    self.obtained_tokens['developer'] = token
                    logger.info("Successfully obtained developer token from login")
        
        # 2. Test login with invalid credentials
        invalid_result = await self.test_endpoint(
            method="POST",
            path="/auth/login",
            auth_type="none",
            body=self.TEST_USERS["invalid"],
            is_form_data=True
        )
        results["login_invalid"] = invalid_result
        
        # Verify this returns 401 or 400
        if invalid_result['statusCode'] in [400, 401]:
            invalid_result['healthy'] = True  # This is expected behavior
            logger.info("Invalid login correctly rejected")
        
        # 3. Test profile access with token
        if self.obtained_tokens['developer'] or developer_token:
            profile_result = await self.test_endpoint(
                method="GET",
                path="/auth/profile",
                auth_type="developer",
                developer_token=self.obtained_tokens['developer'] or developer_token
            )
            results["profile_access"] = profile_result
        
        # 4. Test logout
        if self.obtained_tokens['developer'] or developer_token:
            logout_result = await self.test_endpoint(
                method="POST",
                path="/auth/logout",
                auth_type="developer",
                developer_token=self.obtained_tokens['developer'] or developer_token
            )
            results["logout"] = logout_result
        
        return results
    
    async def test_agent_authentication(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test agent token endpoint"""
        results = {}
        
        # Test agent token generation
        agent_auth_result = await self.test_endpoint(
            method="POST",
            path="/auth/agent/token",
            auth_type="none",
            body=self.TEST_USERS["agent"],
            is_form_data=True  # Agent token uses form data
        )
        results["agent_token"] = agent_auth_result
        
        if agent_auth_result['healthy'] and agent_auth_result.get('responseData'):
            # Extract agent token
            response_data = agent_auth_result['responseData']
            if isinstance(response_data, dict):
                token = response_data.get('access_token') or response_data.get('token')
                if token:
                    self.obtained_tokens['agent'] = token
                    logger.info("Successfully obtained agent token")
        
        return results
    
    async def test_registration_flow(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test user registration"""
        # Generate unique email to avoid conflicts
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        test_email = f"test_{timestamp}@example.com"
        
        registration_body = {
            "name": f"Test User {timestamp}",
            "email": test_email,
            "password": "TestPass123!",
            "organization": "Test Organization"
        }
        
        result = await self.test_endpoint(
            method="POST",
            path="/auth/register",
            auth_type="none",
            body=registration_body
        )
        
        # Log registration attempt
        if result['healthy']:
            logger.info(f"Successfully registered user: {test_email}")
        else:
            # Check if it's a duplicate user error (which is OK)
            if result.get('statusCode') == 400:
                response_data = result.get('responseData', {})
                if isinstance(response_data, dict):
                    error = response_data.get('error', {})
                    if 'already exists' in str(error).lower():
                        result['healthy'] = True  # Expected behavior
                        logger.info("User already exists - this is OK")
        
        return {"registration": result}
    
    async def test_password_reset_flow(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test password reset workflow"""
        results = {}
        
        # 1. Request password reset
        reset_request = await self.test_endpoint(
            method="POST",
            path="/auth/request-password-reset",
            auth_type="none",
            body={"email": self.TEST_USERS["valid"]["username"]}
        )
        results["request_reset"] = reset_request
        
        # 2. Test reset with token (would need actual token in real scenario)
        reset_body = {
            "token": "test-reset-token",
            "new_password": "NewTestPass123!"
        }
        
        reset_result = await self.test_endpoint(
            method="POST",
            path="/auth/reset-password",
            auth_type="none",
            body=reset_body
        )
        results["reset_password"] = reset_result
        
        # This might fail with invalid token, which is expected
        if reset_result.get('statusCode') in [400, 401]:
            reset_result['healthy'] = True  # Expected without valid token
            logger.info("Password reset with test token correctly rejected")
        
        return results
    
    async def test_api_key_management(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test API key endpoints"""
        results = {}
        
        # Need developer token for API key management
        token = self.obtained_tokens['developer'] or developer_token
        if not token:
            logger.warning("No developer token available for API key tests")
            return {"error": "No developer token available"}
        
        # 1. List API keys
        list_result = await self.test_endpoint(
            method="GET",
            path="/auth/api-keys",
            auth_type="developer",
            developer_token=token
        )
        results["list_api_keys"] = list_result
        
        # 2. Create API key (note: this endpoint expects just a string)
        create_result = await self.test_endpoint(
            method="POST",
            path="/auth/api-keys",
            auth_type="developer",
            body="Test API Key",  # Just a string
            developer_token=token
        )
        results["create_api_key"] = create_result
        
        if create_result['healthy'] and create_result.get('responseData'):
            # Store the API key if returned
            response_data = create_result['responseData']
            if isinstance(response_data, dict):
                key = response_data.get('key') or response_data.get('api_key')
                if key:
                    self.obtained_tokens['api_key'] = key
                    logger.info("Successfully created API key")
        
        return results
    
    async def test_token_refresh(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test token refresh endpoint"""
        token = self.obtained_tokens['developer'] or developer_token
        if not token:
            logger.warning("No token available for refresh test")
            return {"error": "No token available"}
        
        result = await self.test_endpoint(
            method="POST",
            path="/auth/refresh",
            auth_type="developer",
            developer_token=token
        )
        
        if result['healthy'] and result.get('responseData'):
            logger.info("Token refresh successful")
        
        return {"token_refresh": result}
    
    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Override to run auth-specific test flows"""
        logger.info("Running comprehensive auth tests...")
        
        # Run specific test flows
        all_results = {}
        
        # 1. Login flow (foundational)
        logger.info("Testing login flow...")
        login_results = await self.test_login_flow(developer_token, agent_token)
        all_results.update(login_results)
        
        # 2. Agent authentication
        logger.info("Testing agent authentication...")
        agent_results = await self.test_agent_authentication(developer_token, agent_token)
        all_results.update(agent_results)
        
        # 3. Registration
        logger.info("Testing registration...")
        reg_results = await self.test_registration_flow(developer_token, agent_token)
        all_results.update(reg_results)
        
        # 4. Password reset
        logger.info("Testing password reset...")
        reset_results = await self.test_password_reset_flow(developer_token, agent_token)
        all_results.update(reset_results)
        
        # 5. API keys (if we have a token)
        if self.obtained_tokens['developer'] or developer_token:
            logger.info("Testing API key management...")
            api_key_results = await self.test_api_key_management(developer_token, agent_token)
            all_results.update(api_key_results)
        
        # 6. Token refresh
        if self.obtained_tokens['developer'] or developer_token:
            logger.info("Testing token refresh...")
            refresh_results = await self.test_token_refresh(developer_token, agent_token)
            all_results.update(refresh_results)
        
        # Now run standard endpoint tests
        logger.info("Running standard endpoint tests...")
        standard_results = await super().test_all(
            developer_token or self.obtained_tokens['developer'],
            agent_token or self.obtained_tokens['agent']
        )
        
        # Combine results
        return {
            **standard_results,
            "detailed_tests": all_results,
            "obtained_tokens": {
                k: bool(v) for k, v in self.obtained_tokens.items()
            }
        }
    
    def get_obtained_tokens(self) -> Dict[str, Optional[str]]:
        """Get tokens obtained during testing for use by other categories"""
        return self.obtained_tokens.copy()


# Convenience function for standalone execution
async def run_auth_tests(
    base_url: str = "http://localhost:8710",
    developer_token: Optional[str] = None,
    agent_token: Optional[str] = None
):
    """Run auth tests standalone"""
    tester = TestAuth(base_url)
    await tester.setup()
    
    try:
        results = await tester.test_all(developer_token, agent_token)
        
        # Log summary
        logger.info("\nAuth Test Summary:")
        logger.info(f"- Tokens obtained: {results.get('obtained_tokens', {})}")
        
        if 'summary' in results:
            summary = results['summary']
            logger.info(
                f"- Endpoints: {summary['healthy']}/{summary['total']} passed "
                f"({summary['percentage']}%)"
            )
        
        return results
    finally:
        await tester.teardown()


if __name__ == "__main__":
    import sys
    
    # Allow passing tokens via command line
    dev_token = sys.argv[1] if len(sys.argv) > 1 else None
    agent_token = sys.argv[2] if len(sys.argv) > 2 else None
    
    asyncio.run(run_auth_tests(
        developer_token=dev_token,
        agent_token=agent_token
    ))
