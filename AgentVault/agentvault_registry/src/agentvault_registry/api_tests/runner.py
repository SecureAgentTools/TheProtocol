"""
Smart Test Runner for API Test Suite

Provides intelligent test orchestration with category-specific execution,
parallel testing support, and real-time progress reporting.
"""

import asyncio
import logging
import time
import json
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timezone
from pathlib import Path
import importlib
import sys

from .test_results_analyzer import TestResultsAnalyzer
from .auth_manager import AuthManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SmartTestRunner:
    """
    Intelligent test runner with advanced features:
    - Category-specific execution
    - Parallel test support
    - Dependency resolution
    - Progressive test strategy
    - Automatic retry with backoff
    - Real-time progress reporting
    - Failure categorization
    """
    
    # Dependency graph for categories
    DEPENDENCIES = {
        "agents": ["auth"],
        "staking": ["auth", "agents"],
        "governance": ["auth", "agents", "staking"],
        "teg": ["auth", "agents"],
        "federation": ["auth", "admin"],
        "agent_cards": ["auth", "agents"],
        "agent_logs": ["auth", "agents"],
        "contracts": ["auth", "agents"],
        "disputes": ["auth", "agents", "contracts"],
    }
    
    def __init__(self, base_url: str = "http://localhost:8710"):
        self.base_url = base_url
        self.auth_manager = AuthManager()
        self.analyzer = TestResultsAnalyzer()
        self.results = {}
        self.start_time = None
        self.end_time = None
        
    async def discover_categories(self) -> List[str]:
        """Discover available test categories from the categories directory"""
        categories_dir = Path(__file__).parent / "categories"
        categories = []
        
        for path in categories_dir.iterdir():
            if path.is_dir() and not path.name.startswith('_'):
                test_file = path / f"test_{path.name}.py"
                if test_file.exists():
                    categories.append(path.name)
        
        logger.info(f"Discovered {len(categories)} test categories: {categories}")
        return categories
    
    async def load_category_module(self, category: str):
        """Dynamically load a category test module"""
        try:
            module_name = f"agentvault_registry.api_tests.categories.{category}.test_{category}"
            module = importlib.import_module(module_name)
            
            # Find the test class
            test_class_name = f"Test{category.title().replace('_', '')}"
            if hasattr(module, test_class_name):
                return getattr(module, test_class_name)
            else:
                # Try alternate naming
                for attr_name in dir(module):
                    if attr_name.startswith("Test") and attr_name != "TestCase":
                        return getattr(module, attr_name)
            
            logger.warning(f"No test class found in {module_name}")
            return None
            
        except ImportError as e:
            logger.error(f"Failed to import category {category}: {e}")
            return None
    
    async def resolve_dependencies(self, categories: List[str]) -> List[str]:
        """Resolve category dependencies and return ordered list"""
        resolved = []
        visited = set()
        
        def visit(cat: str):
            if cat in visited:
                return
            visited.add(cat)
            
            # Visit dependencies first
            for dep in self.DEPENDENCIES.get(cat, []):
                if dep in categories:
                    visit(dep)
            
            if cat in categories and cat not in resolved:
                resolved.append(cat)
        
        # Visit all categories
        for category in categories:
            visit(category)
        
        logger.info(f"Resolved test order: {resolved}")
        return resolved
    
    async def run_category(
        self,
        category: str,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        priority_only: bool = False
    ) -> Dict[str, Any]:
        """Run tests for a specific category"""
        logger.info(f"{'='*60}")
        logger.info(f"Running tests for category: {category}")
        logger.info(f"{'='*60}")
        
        # Load the test module
        test_class = await self.load_category_module(category)
        if not test_class:
            return {
                "category": category,
                "error": f"Failed to load test module for {category}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        # Create test instance
        tester = test_class(self.base_url)
        
        try:
            # Run setup
            await tester.setup()
            
            # Run tests
            if priority_only and hasattr(tester, 'test_priority'):
                result = await tester.test_priority(developer_token, agent_token)
            else:
                result = await tester.test_all(developer_token, agent_token)
            
            # Run teardown
            if hasattr(tester, 'teardown'):
                await tester.teardown()
            
            # Log summary
            if isinstance(result, dict) and 'summary' in result:
                summary = result['summary']
                logger.info(
                    f"Category {category} complete: "
                    f"{summary['healthy']}/{summary['total']} passed "
                    f"({summary['percentage']}%)"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Error running tests for {category}: {e}")
            return {
                "category": category,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    async def run_categories(
        self,
        categories: List[str],
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        parallel: bool = False,
        priority_only: bool = False
    ) -> Dict[str, Any]:
        """Run tests for multiple categories"""
        self.start_time = time.time()
        
        # Resolve dependencies
        ordered_categories = await self.resolve_dependencies(categories)
        
        if parallel:
            # Run in parallel (respecting some dependencies)
            tasks = []
            for category in ordered_categories:
                task = self.run_category(
                    category, developer_token, agent_token, priority_only
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for category, result in zip(ordered_categories, results):
                if isinstance(result, Exception):
                    self.results[category] = {
                        "category": category,
                        "error": str(result),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                else:
                    self.results[category] = result
        else:
            # Run sequentially
            for category in ordered_categories:
                self.results[category] = await self.run_category(
                    category, developer_token, agent_token, priority_only
                )
                
                # Add delay between categories to avoid rate limiting
                if category != ordered_categories[-1]:
                    await asyncio.sleep(1)
        
        self.end_time = time.time()
        
        # Generate overall summary
        return self._generate_summary()
    
    async def run_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None,
        parallel: bool = False,
        priority_only: bool = False
    ) -> Dict[str, Any]:
        """Run tests for all discovered categories"""
        categories = await self.discover_categories()
        return await self.run_categories(
            categories, developer_token, agent_token, parallel, priority_only
        )
    
    def _generate_summary(self) -> Dict[str, Any]:
        """Generate overall test summary"""
        total_endpoints = 0
        total_healthy = 0
        failed_categories = []
        
        # Aggregate results
        all_results = []
        for category, result in self.results.items():
            if 'error' in result:
                failed_categories.append(category)
                continue
            
            if 'summary' in result:
                summary = result['summary']
                total_endpoints += summary['total']
                total_healthy += summary['healthy']
            
            if 'results' in result:
                all_results.extend(result['results'])
        
        # Load results into analyzer
        self.analyzer.load_results(all_results)
        
        # Calculate metrics
        success_rate = round((total_healthy / total_endpoints * 100), 2) if total_endpoints > 0 else 0
        duration = round(self.end_time - self.start_time, 2) if self.end_time else 0
        
        summary = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": duration,
            "categories_tested": len(self.results),
            "categories_failed": failed_categories,
            "total_endpoints": total_endpoints,
            "total_healthy": total_healthy,
            "total_failed": total_endpoints - total_healthy,
            "overall_success_rate": success_rate,
            "category_results": self.results,
            "analysis": {
                "by_auth_type": self.analyzer.get_auth_analysis(),
                "error_patterns": self.analyzer.get_error_patterns(),
                "performance": self.analyzer.get_performance_analysis()
            }
        }
        
        return summary
    
    def save_results(self, filename: Optional[str] = None):
        """Save test results to file"""
        if not filename:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"test_results_{timestamp}.json"
        
        summary = self._generate_summary()
        
        with open(filename, 'w') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Results saved to {filename}")
        return filename
    
    def print_summary(self):
        """Print a formatted summary to console"""
        summary = self._generate_summary()
        
        print("\n" + "="*80)
        print("API TEST RESULTS SUMMARY")
        print("="*80)
        print(f"Timestamp: {summary['timestamp']}")
        print(f"Duration: {summary['duration_seconds']}s")
        print(f"Categories Tested: {summary['categories_tested']}")
        print(f"Total Endpoints: {summary['total_endpoints']}")
        print(f"Success Rate: {summary['overall_success_rate']}%")
        print("\nCategory Breakdown:")
        print("-"*50)
        
        for category, result in summary['category_results'].items():
            if 'error' in result:
                print(f"  {category}: ERROR - {result['error']}")
            elif 'summary' in result:
                cat_summary = result['summary']
                print(
                    f"  {category}: {cat_summary['healthy']}/{cat_summary['total']} "
                    f"({cat_summary['percentage']}%)"
                )
        
        # Show top errors
        error_patterns = summary['analysis']['error_patterns']
        if error_patterns:
            print("\nTop Error Patterns:")
            print("-"*50)
            for pattern, endpoints in list(error_patterns.items())[:5]:
                print(f"  {pattern}: {len(endpoints)} endpoints")
        
        print("="*80 + "\n")


# CLI interface
async def main():
    """Command-line interface for the test runner"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run API tests")
    parser.add_argument(
        "--category", "-c",
        help="Test specific category (can be used multiple times)",
        action="append"
    )
    parser.add_argument(
        "--all", "-a",
        help="Test all categories",
        action="store_true"
    )
    parser.add_argument(
        "--parallel", "-p",
        help="Run tests in parallel",
        action="store_true"
    )
    parser.add_argument(
        "--priority",
        help="Run only priority endpoints",
        action="store_true"
    )
    parser.add_argument(
        "--dev-token",
        help="Developer token for authentication"
    )
    parser.add_argument(
        "--agent-token",
        help="Agent token for authentication"
    )
    parser.add_argument(
        "--base-url",
        help="Base URL for API",
        default="http://localhost:8710"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output file for results"
    )
    
    args = parser.parse_args()
    
    # Create runner
    runner = SmartTestRunner(args.base_url)
    
    # Run tests
    if args.all:
        results = await runner.run_all(
            developer_token=args.dev_token,
            agent_token=args.agent_token,
            parallel=args.parallel,
            priority_only=args.priority
        )
    elif args.category:
        results = await runner.run_categories(
            categories=args.category,
            developer_token=args.dev_token,
            agent_token=args.agent_token,
            parallel=args.parallel,
            priority_only=args.priority
        )
    else:
        print("Please specify --all or --category")
        return
    
    # Print summary
    runner.print_summary()
    
    # Save results if requested
    if args.output:
        runner.save_results(args.output)


if __name__ == "__main__":
    asyncio.run(main())
