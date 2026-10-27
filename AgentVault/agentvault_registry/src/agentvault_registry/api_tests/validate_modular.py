"""
Quick validation script to test the modular API test system.

This script tests that the new infrastructure works correctly
by running TEG category tests.
"""

import asyncio
import sys
import os
import logging

# Add parent directory to Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agentvault_registry.api_tests.runner import SmartTestRunner
from agentvault_registry.api_tests.categories.teg.test_teg import TestTEG

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def validate_teg_module():
    """Validate that the TEG test module works correctly"""
    logger.info("="*60)
    logger.info("VALIDATING TEG TEST MODULE")
    logger.info("="*60)
    
    # Get tokens from command line or environment
    dev_token = sys.argv[1] if len(sys.argv) > 1 else os.getenv('DEV_TOKEN')
    agent_token = sys.argv[2] if len(sys.argv) > 2 else os.getenv('AGENT_TOKEN')
    
    if not dev_token:
        logger.warning("No developer token provided. Some tests may fail.")
    if not agent_token:
        logger.warning("No agent token provided. Agent endpoints will fail.")
    
    try:
        # Test 1: Create TEG tester instance
        logger.info("\n1. Creating TEG tester instance...")
        tester = TestTEG()
        logger.info("✓ TEG tester created successfully")
        
        # Test 2: Run setup
        logger.info("\n2. Running TEG setup...")
        await tester.setup()
        logger.info("✓ Setup completed")
        
        # Test 3: Test a single endpoint
        logger.info("\n3. Testing single TEG endpoint (balance check)...")
        result = await tester.test_endpoint(
            method="GET",
            path="/teg/balance/ethereum/0x1234567890123456789012345678901234567890",
            auth_type="none",
            developer_token=dev_token,
            agent_token=agent_token
        )
        logger.info(f"✓ Single endpoint test completed. Healthy: {result['healthy']}")
        if not result['healthy']:
            logger.warning(f"  Error: {result.get('error')}")
            logger.warning(f"  Response: {result.get('responseData')}")
        
        # Test 4: Run diagnostics
        logger.info("\n4. Running TEG diagnostics...")
        diagnostics = await tester.diagnose_validation_errors(dev_token, agent_token)
        logger.info(f"✓ Diagnostics completed. Found {len(diagnostics['validation_errors'])} errors")
        
        if diagnostics['recommendations']:
            logger.info("  Recommendations:")
            for rec in diagnostics['recommendations']:
                logger.info(f"    - {rec}")
        
        # Test 5: Test priority endpoints
        logger.info("\n5. Testing priority TEG endpoints...")
        priority_results = await tester.test_priority(dev_token, agent_token)
        if 'summary' in priority_results:
            summary = priority_results['summary']
            logger.info(
                f"✓ Priority tests completed: {summary['healthy']}/{summary['total']} passed "
                f"({summary['percentage']}%)"
            )
        
        # Test 6: Use the smart runner
        logger.info("\n6. Testing smart runner with TEG category...")
        runner = SmartTestRunner()
        runner_results = await runner.run_category("teg", dev_token, agent_token, priority_only=True)
        
        if 'error' in runner_results:
            logger.error(f"✗ Runner failed: {runner_results['error']}")
        else:
            logger.info("✓ Smart runner executed successfully")
        
        logger.info("\n" + "="*60)
        logger.info("VALIDATION COMPLETE")
        logger.info("="*60)
        
        return True
        
    except Exception as e:
        logger.error(f"Validation failed with error: {e}", exc_info=True)
        return False


async def validate_runner():
    """Validate the smart runner functionality"""
    logger.info("\n" + "="*60)
    logger.info("VALIDATING SMART RUNNER")
    logger.info("="*60)
    
    runner = SmartTestRunner()
    
    # Test category discovery
    logger.info("\n1. Testing category discovery...")
    categories = await runner.discover_categories()
    logger.info(f"✓ Discovered {len(categories)} categories: {categories}")
    
    # Test dependency resolution
    logger.info("\n2. Testing dependency resolution...")
    test_categories = ["teg", "agents", "auth"]
    resolved = await runner.resolve_dependencies(test_categories)
    logger.info(f"✓ Resolved order: {resolved}")
    
    return True


async def main():
    """Main validation function"""
    logger.info("Starting modular test system validation...\n")
    
    # Validate TEG module
    teg_valid = await validate_teg_module()
    
    # Validate runner
    runner_valid = await validate_runner()
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("VALIDATION SUMMARY")
    logger.info("="*60)
    logger.info(f"TEG Module: {'PASS' if teg_valid else 'FAIL'}")
    logger.info(f"Smart Runner: {'PASS' if runner_valid else 'FAIL'}")
    logger.info("="*60)
    
    if teg_valid and runner_valid:
        logger.info("\n✅ All validations passed! The modular system is ready.")
        logger.info("\nNext steps:")
        logger.info("1. Run full TEG tests: python -m agentvault_registry.api_tests.runner -c teg")
        logger.info("2. Add more category modules (auth, agents, etc.)")
        logger.info("3. Run all tests: python -m agentvault_registry.api_tests.runner --all")
    else:
        logger.error("\n❌ Some validations failed. Please check the errors above.")


if __name__ == "__main__":
    asyncio.run(main())
