"""
Test Results Analyzer for API Testing

Provides analysis and reporting capabilities for test results.
"""

import json
import logging
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone
from collections import defaultdict, Counter
import statistics

logger = logging.getLogger(__name__)


class TestResultsAnalyzer:
    """Analyzer for API test results with detailed reporting"""
    
    def __init__(self):
        self.results = []
        self.analysis_cache = {}
        
    def load_results(self, results: List[Dict[str, Any]]):
        """Load test results for analysis"""
        self.results = results
        self.analysis_cache.clear()
        logger.info(f"Loaded {len(results)} test results for analysis")
    
    def load_from_file(self, filepath: str):
        """Load test results from JSON file"""
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict) and 'results' in data:
                    self.results = data['results']
                elif isinstance(data, list):
                    self.results = data
                else:
                    raise ValueError("Invalid results format")
                self.analysis_cache.clear()
                logger.info(f"Loaded {len(self.results)} results from {filepath}")
        except Exception as e:
            logger.error(f"Failed to load results from {filepath}: {e}")
            raise
    
    def get_summary(self) -> Dict[str, Any]:
        """Get overall test summary"""
        if 'summary' in self.analysis_cache:
            return self.analysis_cache['summary']
        
        total = len(self.results)
        if total == 0:
            return {"error": "No results to analyze"}
        
        healthy = sum(1 for r in self.results if r.get('healthy', False))
        failed = total - healthy
        
        # Response time statistics
        response_times = [r['responseTime'] for r in self.results if r.get('responseTime') is not None]
        
        summary = {
            "total_endpoints": total,
            "healthy": healthy,
            "failed": failed,
            "success_rate": round((healthy / total * 100), 2),
            "response_time_stats": {
                "min": min(response_times) if response_times else 0,
                "max": max(response_times) if response_times else 0,
                "mean": round(statistics.mean(response_times), 2) if response_times else 0,
                "median": round(statistics.median(response_times), 2) if response_times else 0,
                "p95": round(self._percentile(response_times, 0.95), 2) if response_times else 0,
                "p99": round(self._percentile(response_times, 0.99), 2) if response_times else 0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        self.analysis_cache['summary'] = summary
        return summary
    
    def get_category_breakdown(self) -> Dict[str, Dict[str, Any]]:
        """Get breakdown by category"""
        if 'category_breakdown' in self.analysis_cache:
            return self.analysis_cache['category_breakdown']
        
        # Group by category (extracted from path patterns)
        categories = defaultdict(list)
        for result in self.results:
            category = self._extract_category(result['path'])
            categories[category].append(result)
        
        breakdown = {}
        for category, cat_results in categories.items():
            total = len(cat_results)
            healthy = sum(1 for r in cat_results if r.get('healthy', False))
            
            breakdown[category] = {
                "total": total,
                "healthy": healthy,
                "failed": total - healthy,
                "success_rate": round((healthy / total * 100), 2) if total > 0 else 0,
                "endpoints": [
                    {
                        "method": r['method'],
                        "path": r['path'],
                        "healthy": r.get('healthy', False),
                        "status_code": r.get('statusCode'),
                        "response_time": r.get('responseTime')
                    }
                    for r in cat_results
                ]
            }
        
        self.analysis_cache['category_breakdown'] = breakdown
        return breakdown
    
    def get_failed_endpoints(self) -> List[Dict[str, Any]]:
        """Get all failed endpoints with details"""
        failed = []
        
        for result in self.results:
            if not result.get('healthy', False):
                failed.append({
                    "method": result['method'],
                    "path": result['path'],
                    "status_code": result.get('statusCode'),
                    "error": result.get('error'),
                    "auth_required": result.get('authRequired'),
                    "response_time": result.get('responseTime'),
                    "category": self._extract_category(result['path'])
                })
        
        # Sort by category and path
        failed.sort(key=lambda x: (x['category'], x['path']))
        return failed
    
    def get_auth_analysis(self) -> Dict[str, Any]:
        """Analyze authentication patterns"""
        if 'auth_analysis' in self.analysis_cache:
            return self.analysis_cache['auth_analysis']
        
        auth_types = defaultdict(list)
        auth_failures = defaultdict(int)
        
        for result in self.results:
            auth_type = result.get('authRequired', 'none')
            auth_types[auth_type].append(result)
            
            # Track auth failures
            if not result.get('healthy', False) and result.get('statusCode') in [401, 403]:
                auth_failures[auth_type] += 1
        
        analysis = {}
        for auth_type, results in auth_types.items():
            total = len(results)
            healthy = sum(1 for r in results if r.get('healthy', False))
            failures = auth_failures[auth_type]
            
            analysis[auth_type] = {
                "total": total,
                "healthy": healthy,
                "failed": total - healthy,
                "auth_failures": failures,
                "success_rate": round((healthy / total * 100), 2) if total > 0 else 0,
                "endpoints": [f"{r['method']} {r['path']}" for r in results[:5]]  # Sample
            }
        
        self.analysis_cache['auth_analysis'] = analysis
        return analysis
    
    def get_error_patterns(self) -> Dict[str, List[Dict[str, Any]]]:
        """Identify common error patterns"""
        error_patterns = defaultdict(list)
        
        for result in self.results:
            if not result.get('healthy', False):
                # Categorize by error type
                status_code = result.get('statusCode')
                error_msg = result.get('error', '')
                
                if status_code == 401:
                    pattern = "Authentication Failed"
                elif status_code == 403:
                    pattern = "Authorization Failed"
                elif status_code == 404:
                    pattern = "Not Found"
                elif status_code == 400:
                    pattern = "Bad Request"
                elif status_code == 500:
                    pattern = "Server Error"
                elif "Timeout" in error_msg:
                    pattern = "Timeout"
                elif status_code is None:
                    pattern = "Connection Error"
                else:
                    pattern = f"HTTP {status_code}"
                
                error_patterns[pattern].append({
                    "method": result['method'],
                    "path": result['path'],
                    "error": error_msg,
                    "auth": result.get('authRequired')
                })
        
        return dict(error_patterns)
    
    def get_performance_analysis(self) -> Dict[str, Any]:
        """Analyze performance metrics"""
        if 'performance_analysis' in self.analysis_cache:
            return self.analysis_cache['performance_analysis']
        
        # Group by response time buckets
        buckets = {
            "fast": [],      # < 100ms
            "normal": [],    # 100-500ms
            "slow": [],      # 500-1000ms
            "very_slow": []  # > 1000ms
        }
        
        for result in self.results:
            rt = result.get('responseTime')
            if rt is not None:
                endpoint = f"{result['method']} {result['path']}"
                if rt < 100:
                    buckets["fast"].append((endpoint, rt))
                elif rt < 500:
                    buckets["normal"].append((endpoint, rt))
                elif rt < 1000:
                    buckets["slow"].append((endpoint, rt))
                else:
                    buckets["very_slow"].append((endpoint, rt))
        
        # Sort each bucket by response time
        for bucket in buckets.values():
            bucket.sort(key=lambda x: x[1], reverse=True)
        
        analysis = {
            "fast_endpoints": len(buckets["fast"]),
            "normal_endpoints": len(buckets["normal"]),
            "slow_endpoints": len(buckets["slow"]),
            "very_slow_endpoints": len(buckets["very_slow"]),
            "slowest_endpoints": [
                {"endpoint": ep, "response_time": rt}
                for ep, rt in buckets["very_slow"][:10]
            ],
            "fastest_endpoints": [
                {"endpoint": ep, "response_time": rt}
                for ep, rt in buckets["fast"][:10]
            ]
        }
        
        self.analysis_cache['performance_analysis'] = analysis
        return analysis
    
    def generate_report(self, output_file: Optional[str] = None) -> str:
        """Generate comprehensive test report"""
        report_lines = [
            "# API Test Results Report",
            f"Generated at: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Summary",
            json.dumps(self.get_summary(), indent=2),
            "",
            "## Category Breakdown",
        ]
        
        # Category details
        for category, stats in self.get_category_breakdown().items():
            report_lines.extend([
                f"\n### {category}",
                f"- Total: {stats['total']}",
                f"- Healthy: {stats['healthy']}",
                f"- Failed: {stats['failed']}",
                f"- Success Rate: {stats['success_rate']}%"
            ])
        
        # Failed endpoints
        failed = self.get_failed_endpoints()
        if failed:
            report_lines.extend([
                "",
                "## Failed Endpoints",
                f"Total Failed: {len(failed)}",
                ""
            ])
            
            for endpoint in failed[:20]:  # Limit to first 20
                report_lines.append(
                    f"- {endpoint['method']} {endpoint['path']} "
                    f"(Status: {endpoint.get('status_code', 'N/A')}, "
                    f"Error: {endpoint.get('error', 'Unknown')})"
                )
        
        # Auth analysis
        report_lines.extend([
            "",
            "## Authentication Analysis",
        ])
        
        for auth_type, stats in self.get_auth_analysis().items():
            report_lines.append(
                f"- {auth_type}: {stats['healthy']}/{stats['total']} "
                f"({stats['success_rate']}% success)"
            )
        
        # Performance analysis
        perf = self.get_performance_analysis()
        report_lines.extend([
            "",
            "## Performance Analysis",
            f"- Fast (<100ms): {perf['fast_endpoints']}",
            f"- Normal (100-500ms): {perf['normal_endpoints']}",
            f"- Slow (500-1000ms): {perf['slow_endpoints']}",
            f"- Very Slow (>1000ms): {perf['very_slow_endpoints']}"
        ])
        
        report = "\n".join(report_lines)
        
        if output_file:
            with open(output_file, 'w') as f:
                f.write(report)
            logger.info(f"Report saved to {output_file}")
        
        return report
    
    def _extract_category(self, path: str) -> str:
        """Extract category from endpoint path"""
        # Remove leading slash and API version
        path = path.lstrip('/').replace('api/v1/', '')
        
        # Get first segment as category
        parts = path.split('/')
        if parts:
            category = parts[0]
            # Handle special cases
            if category == "agent" and len(parts) > 1:
                return f"agent_{parts[1]}"
            elif category == "auth" and len(parts) > 1 and parts[1] == "secure":
                return "auth_secure"
            elif category == "federation" and len(parts) > 1:
                return f"federation_{parts[1]}"
            elif category == "admin" and len(parts) > 1:
                return f"admin_{parts[1]}"
            return category
        
        return "unknown"
    
    def _percentile(self, data: List[float], percentile: float) -> float:
        """Calculate percentile of data"""
        if not data:
            return 0
        
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile)
        if index >= len(sorted_data):
            index = len(sorted_data) - 1
        
        return sorted_data[index]
    
    def compare_results(self, other_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare two sets of test results"""
        other_analyzer = TestResultsAnalyzer()
        other_analyzer.load_results(other_results)
        
        current_summary = self.get_summary()
        other_summary = other_analyzer.get_summary()
        
        comparison = {
            "success_rate_change": round(
                current_summary['success_rate'] - other_summary['success_rate'], 2
            ),
            "total_endpoints_change": current_summary['total_endpoints'] - other_summary['total_endpoints'],
            "newly_failing": [],
            "newly_passing": [],
            "still_failing": []
        }
        
        # Create lookup maps
        current_map = {f"{r['method']} {r['path']}": r for r in self.results}
        other_map = {f"{r['method']} {r['path']}": r for r in other_results}
        
        # Find changes
        for key, result in current_map.items():
            if key in other_map:
                other_result = other_map[key]
                if not result['healthy'] and other_result['healthy']:
                    comparison['newly_failing'].append(key)
                elif result['healthy'] and not other_result['healthy']:
                    comparison['newly_passing'].append(key)
                elif not result['healthy'] and not other_result['healthy']:
                    comparison['still_failing'].append(key)
        
        return comparison
