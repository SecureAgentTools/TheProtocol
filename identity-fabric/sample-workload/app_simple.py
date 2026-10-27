"""
AgentVault Sample SPIFFE Workload - Simplified for OPA Testing
Demonstrates OPA policy checks with mock JWT claims
"""

import logging
import time
import os
import json
import requests
import base64
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('agentvault.sample_workload')

class AgentVaultWorkload:
    """Sample workload demonstrating OPA policy integration"""
    
    def __init__(self):
        self.spiffe_id = "spiffe://agentvault.com/sample-workload"
        self.jwt_token = None
        
    def generate_mock_jwt(self):
        """Generate a mock JWT for testing OPA integration"""
        # Mock JWT claims that would normally come from SPIRE
        claims = {
            "sub": self.spiffe_id,
            "aud": ["agentvault-service"],
            "exp": int(time.time()) + 300,  # 5 minutes from now
            "iat": int(time.time()),
            "iss": "spiffe://agentvault.com"
        }
        
        # In production, this would be a real JWT from SPIRE
        # For now, we'll create a mock JWT structure
        header = {"alg": "RS256", "typ": "JWT"}
        
        # Base64 encode the parts (without signature for mock)
        header_encoded = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')
        signature = "mock_signature"  # In production, this would be a real signature
        
        self.jwt_token = f"{header_encoded}.{payload_encoded}.{signature}"
        
        logger.info("Generated mock JWT-SVID")
        logger.info(f"JWT SPIFFE ID: {claims['sub']}")
        logger.info(f"JWT Audience: {claims['aud']}")
        logger.info(f"JWT Expiry: {datetime.fromtimestamp(claims['exp'])}")
        logger.info(f"JWT Token (first 50 chars): {self.jwt_token[:50]}...")
        
        return claims
    
    def check_opa_policy(self, claims):
        """Query OPA for authorization decision based on JWT claims"""
        try:
            logger.info(f"JWT Claims: {json.dumps(claims, indent=2)}")
            
            # Prepare OPA query
            opa_url = "http://opa:8181/v1/data/workload/access/allow"
            opa_input = {"input": claims}
            
            logger.info(f"Querying OPA at {opa_url}")
            logger.info(f"OPA Input: {json.dumps(opa_input, indent=2)}")
            
            # Query OPA
            response = requests.post(
                opa_url,
                json=opa_input,
                headers={"Content-Type": "application/json"},
                timeout=5
            )
            
            if response.status_code == 200:
                result = response.json()
                allowed = result.get("result", False)
                
                if allowed:
                    logger.info("Policy decision: [ALLOW]")
                else:
                    logger.info("Policy decision: [DENY]")
                    
                    # Also query debug info
                    debug_url = "http://opa:8181/v1/data/workload/access/debug_info"
                    debug_response = requests.post(debug_url, json=opa_input, timeout=5)
                    if debug_response.status_code == 200:
                        debug_info = debug_response.json().get("result", {})
                        logger.info(f"Debug info: {json.dumps(debug_info, indent=2)}")
                
                return allowed
            else:
                logger.error(f"OPA query failed with status {response.status_code}: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"Error querying OPA: {e}")
            return False

def main():
    """Main execution function"""
    logger.info("=== AgentVault Sample SPIFFE Workload Starting ===")
    logger.info(f"Process ID: {os.getpid()}")
    logger.info(f"SPIFFE_ENDPOINT_SOCKET: {os.environ.get('SPIFFE_ENDPOINT_SOCKET', 'not set')}")
    
    workload = AgentVaultWorkload()
    
    # Wait a bit for OPA to be ready
    logger.info("Waiting for OPA to be ready...")
    time.sleep(10)
    
    # Generate mock JWT claims
    logger.info("Generating mock JWT-SVID...")
    claims = workload.generate_mock_jwt()
    
    # Check OPA policy
    logger.info("\n=== Checking OPA Policy ===")
    if workload.check_opa_policy(claims):
        logger.info("✓ OPA policy check passed")
    else:
        logger.info("✗ OPA policy check failed")
    
    # Keep the container running for observation
    logger.info("Workload will continue running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
            logger.info(f"Workload alive - SPIFFE ID: {workload.spiffe_id}")
    except KeyboardInterrupt:
        logger.info("Shutting down sample workload...")

if __name__ == "__main__":
    main()
