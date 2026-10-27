"""
TEG (Token Economy Graph) Test Module

Tests for all TEG-related endpoints including transfers, policies, 
disputes, attestations, and governance integration.

This is the highest priority category due to current validation errors.
"""

import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone

from ..base import APITestBase

logger = logging.getLogger(__name__)


class TestTEG(APITestBase):
    """
    Test suite for TEG (Token Economy Graph) endpoints.
    
    TEG is currently the most problematic category with validation errors,
    so this module includes extensive error handling and debugging.
    """
    
    CATEGORY_NAME = "teg"
    
    # Priority endpoints - test these first for quick validation
    PRIORITY_ENDPOINTS = [
        "/teg/balance/{chain_id}/{wallet_address}",  # Read-only, should work
        "/teg/analytics/summary",                      # Public endpoint
        "/teg/policies",                               # List policies (GET)
        "/teg/transfer",                               # Core functionality
        "/teg/wallets",                                # List wallets
    ]
    
    # TEG has strict rate limits
    RATE_LIMIT = 60  # 60 requests per minute
    
    # Some TEG operations may be slower
    TIMEOUT = 15.0
    
    # Test wallet addresses
    TEST_WALLETS = {
        "primary": "0x1234567890123456789012345678901234567890",
        "secondary": "0x0987654321098765432109876543210987654321",
        "tertiary": "0xabcdef1234567890abcdef1234567890abcdef12"
    }
    
    # Test chain IDs
    TEST_CHAINS = ["ethereum", "polygon", "arbitrum"]
    
    async def setup(self):
        """Set up TEG-specific test environment"""
        await super().setup_category(self.CATEGORY_NAME)
        
        # TEG requires special headers for some operations
        self.teg_headers = {
            "X-TEG-Version": "1.0",
            "X-Chain-Priority": "ethereum"
        }
        
        logger.info("TEG test setup complete")
    
    async def test_balance_endpoints(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Test balance checking endpoints specifically"""
        results = []
        
        # Test balance checks for different chains and wallets
        for chain in self.TEST_CHAINS[:1]:  # Test just one chain first
            for wallet_type, address in list(self.TEST_WALLETS.items())[:1]:  # Test one wallet
                result = await self.test_endpoint(
                    method="GET",
                    path=f"/teg/balance/{chain}/{address}",
                    auth_type="none",  # Balance checks are public
                    developer_token=developer_token,
                    agent_token=agent_token
                )
                results.append(result)
                logger.info(
                    f"Balance check for {wallet_type} on {chain}: "
                    f"{'SUCCESS' if result['healthy'] else 'FAILED'}"
                )
        
        return results
    
    async def test_transfer_validation(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test transfer endpoint with various validation scenarios"""
        test_cases = [
            # Valid transfer
            {
                "name": "Valid Transfer",
                "body": {
                    "from_wallet": self.TEST_WALLETS["primary"],
                    "to_wallet": self.TEST_WALLETS["secondary"],
                    "amount": "100.0",
                    "chain_id": "ethereum",
                    "memo": "Valid test transfer"
                }
            },
            # Invalid amount format
            {
                "name": "Invalid Amount",
                "body": {
                    "from_wallet": self.TEST_WALLETS["primary"],
                    "to_wallet": self.TEST_WALLETS["secondary"],
                    "amount": "invalid",
                    "chain_id": "ethereum",
                    "memo": "Invalid amount test"
                }
            },
            # Missing required field
            {
                "name": "Missing To Wallet",
                "body": {
                    "from_wallet": self.TEST_WALLETS["primary"],
                    "amount": "50.0",
                    "chain_id": "ethereum"
                }
            }
        ]
        
        results = []
        for test_case in test_cases:
            logger.info(f"Testing transfer scenario: {test_case['name']}")
            result = await self.test_endpoint(
                method="POST",
                path="/teg/transfer",
                auth_type="agent",
                body=test_case["body"],
                developer_token=developer_token,
                agent_token=agent_token
            )
            
            # Add test case name to result
            result["test_case"] = test_case["name"]
            results.append(result)
            
            # Log detailed error info for debugging
            if not result['healthy']:
                logger.error(
                    f"Transfer test '{test_case['name']}' failed: "
                    f"Status={result.get('statusCode')}, "
                    f"Error={result.get('error')}, "
                    f"Response={result.get('responseData')}"
                )
        
        return {
            "test_type": "transfer_validation",
            "scenarios_tested": len(test_cases),
            "results": results
        }
    
    async def test_policy_management(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test policy CRUD operations"""
        results = {}
        
        # 1. List existing policies
        list_result = await self.test_endpoint(
            method="GET",
            path="/teg/policies",
            auth_type="agent",
            developer_token=developer_token,
            agent_token=agent_token
        )
        results["list_policies"] = list_result
        
        # 2. Create a new policy
        create_body = {
            "name": "Test TEG Policy",
            "description": "Automated test policy",
            "rules": [
                {
                    "condition": "amount > 1000",
                    "action": "require_approval"
                },
                {
                    "condition": "recipient_new",
                    "action": "delay_24h"
                }
            ],
            "active": True
        }
        
        create_result = await self.test_endpoint(
            method="POST",
            path="/teg/policies",
            auth_type="agent",
            body=create_body,
            developer_token=developer_token,
            agent_token=agent_token
        )
        results["create_policy"] = create_result
        
        # 3. If creation succeeded, test update and delete
        if create_result['healthy'] and create_result.get('responseData'):
            policy_id = create_result['responseData'].get('id', 'test-policy-123')
            
            # Update policy
            update_body = {**create_body, "active": False}
            update_result = await self.test_endpoint(
                method="PUT",
                path=f"/teg/policies/{policy_id}",
                auth_type="agent",
                body=update_body,
                developer_token=developer_token,
                agent_token=agent_token
            )
            results["update_policy"] = update_result
            
            # Delete policy
            delete_result = await self.test_endpoint(
                method="DELETE",
                path=f"/teg/policies/{policy_id}",
                auth_type="agent",
                developer_token=developer_token,
                agent_token=agent_token
            )
            results["delete_policy"] = delete_result
        
        return results
    
    async def test_wallet_operations(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Test wallet linking and management"""
        results = {}
        
        # List current wallets
        list_result = await self.test_endpoint(
            method="GET",
            path="/teg/wallets",
            auth_type="agent",
            developer_token=developer_token,
            agent_token=agent_token
        )
        results["list_wallets"] = list_result
        
        # Link a wallet
        link_body = {
            "wallet_address": self.TEST_WALLETS["primary"],
            "chain_id": "ethereum",
            "signature": "0x" + "a" * 130  # Mock signature
        }
        
        link_result = await self.test_endpoint(
            method="POST",
            path="/teg/wallets/link",
            auth_type="agent",
            body=link_body,
            developer_token=developer_token,
            agent_token=agent_token
        )
        results["link_wallet"] = link_result
        
        # Unlink wallet (only if link succeeded)
        if link_result['healthy']:
            unlink_body = {
                "wallet_address": self.TEST_WALLETS["primary"],
                "chain_id": "ethereum"
            }
            
            unlink_result = await self.test_endpoint(
                method="POST",
                path="/teg/wallets/unlink",
                auth_type="agent",
                body=unlink_body,
                developer_token=developer_token,
                agent_token=agent_token
            )
            results["unlink_wallet"] = unlink_result
        
        return results
    
    async def diagnose_validation_errors(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Special diagnostic function to identify validation error patterns.
        
        This helps debug the current TEG validation issues.
        """
        diagnostics = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "validation_errors": [],
            "successful_requests": [],
            "auth_issues": [],
            "recommendations": []
        }
        
        # Test a minimal valid request
        minimal_transfer = {
            "from_wallet": self.TEST_WALLETS["primary"],
            "to_wallet": self.TEST_WALLETS["secondary"],
            "amount": "1.0",
            "chain_id": "ethereum"
        }
        
        result = await self.test_endpoint(
            method="POST",
            path="/teg/transfer",
            auth_type="agent",
            body=minimal_transfer,
            developer_token=developer_token,
            agent_token=agent_token
        )
        
        if not result['healthy']:
            diagnostics["validation_errors"].append({
                "endpoint": "/teg/transfer",
                "request": minimal_transfer,
                "response": result.get('responseData'),
                "status": result.get('statusCode')
            })
            
            # Analyze error response
            if result.get('responseData') and isinstance(result['responseData'], dict):
                error_detail = result['responseData'].get('detail', '')
                if 'validation' in str(error_detail).lower():
                    diagnostics["recommendations"].append(
                        "Schema validation failure detected. Check request body structure."
                    )
                elif 'auth' in str(error_detail).lower():
                    diagnostics["auth_issues"].append(error_detail)
                    diagnostics["recommendations"].append(
                        "Authentication issue detected. Verify agent token is valid."
                    )
        else:
            diagnostics["successful_requests"].append("/teg/transfer")
        
        # Test other problematic endpoints
        problem_endpoints = [
            ("GET", "/teg/policies"),
            ("GET", "/teg/disputes"),
            ("GET", "/teg/attestations")
        ]
        
        for method, path in problem_endpoints:
            result = await self.test_endpoint(
                method=method,
                path=path,
                auth_type="agent",
                developer_token=developer_token,
                agent_token=agent_token
            )
            
            if not result['healthy']:
                diagnostics["validation_errors"].append({
                    "endpoint": f"{method} {path}",
                    "response": result.get('responseData'),
                    "status": result.get('statusCode')
                })
            else:
                diagnostics["successful_requests"].append(f"{method} {path}")
        
        # Generate recommendations based on findings
        if len(diagnostics["validation_errors"]) > len(diagnostics["successful_requests"]):
            diagnostics["recommendations"].append(
                "Majority of TEG endpoints failing. Check TEG service health and configuration."
            )
        
        if diagnostics["auth_issues"]:
            diagnostics["recommendations"].append(
                "Multiple auth failures. Ensure agent token has TEG permissions."
            )
        
        return diagnostics
    
    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Override to add TEG-specific headers"""
        # First run diagnostics
        logger.info("Running TEG diagnostics...")
        diagnostics = await self.diagnose_validation_errors(developer_token, agent_token)
        
        if diagnostics["recommendations"]:
            logger.warning(f"TEG Diagnostics: {', '.join(diagnostics['recommendations'])}")
        
        # Then run standard tests
        return await super().test_all(developer_token, agent_token)


# Convenience function for direct module execution
async def run_teg_tests(
    base_url: str = "http://localhost:8710",
    developer_token: Optional[str] = None,
    agent_token: Optional[str] = None
):
    """Run TEG tests standalone"""
    tester = TestTEG(base_url)
    await tester.setup()
    
    try:
        # Run diagnostics first
        logger.info("Running TEG diagnostics...")
        diagnostics = await tester.diagnose_validation_errors(developer_token, agent_token)
        logger.info(f"Diagnostics complete: {len(diagnostics['validation_errors'])} errors found")
        
        # Run full test suite
        logger.info("Running full TEG test suite...")
        results = await tester.test_all(developer_token, agent_token)
        
        # Run specific focused tests
        logger.info("Running balance endpoint tests...")
        balance_results = await tester.test_balance_endpoints(developer_token, agent_token)
        
        return {
            "diagnostics": diagnostics,
            "full_results": results,
            "balance_tests": balance_results
        }
    finally:
        await tester.teardown()


if __name__ == "__main__":
    import sys
    
    # Allow passing tokens via command line
    dev_token = sys.argv[1] if len(sys.argv) > 1 else None
    agent_token = sys.argv[2] if len(sys.argv) > 2 else None
    
    results = asyncio.run(run_teg_tests(
        developer_token=dev_token,
        agent_token=agent_token
    ))
    
    print(f"\nTEG Test Results:")
    print(f"- Validation Errors: {len(results['diagnostics']['validation_errors'])}")
    print(f"- Total Endpoints Tested: {results['full_results']['summary']['total']}")
    print(f"- Success Rate: {results['full_results']['summary']['percentage']}%")
