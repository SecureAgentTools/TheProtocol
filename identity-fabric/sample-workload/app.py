"""
AgentVault Sample SPIFFE Workload
Demonstrates SVID fetching using pySpiffe and OPA policy checks
"""

import logging
import time
import os
import json
import requests
import base64
from datetime import datetime
from spiffe.workloadapi import default_workload_api_client
from spiffe.spiffe_id.spiffe_id import SpiffeId
from spiffe.bundle.x509_bundle.x509_bundle_set import X509BundleSet
from spiffe.svid.x509_svid import X509Svid
from spiffe.svid.jwt_svid import JwtSvid
from spiffe.exceptions import SpiffeError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('agentvault.sample_workload')

class AgentVaultWorkload:
    """Sample workload demonstrating SPIFFE identity integration"""
    
    def __init__(self):
        self.spiffe_id = None
        self.x509_svid = None
        self.jwt_svid = None
        
    def fetch_x509_svid(self):
        """Fetch X.509 SVID from SPIRE Agent"""
        try:
            # Get default workload API client
            with default_workload_api_client() as client:
                # Fetch X.509 SVID
                x509_context = client.fetch_x509_context()
                
                # Get the first (default) SVID
                self.x509_svid = x509_context.default_svid()
                self.spiffe_id = self.x509_svid.spiffe_id
                
                logger.info("Successfully fetched X.509 SVID")
                logger.info(f"SPIFFE ID: {self.spiffe_id}")
                logger.info(f"Certificate Serial Number: {self.x509_svid.leaf.serial_number}")
                logger.info(f"Certificate Not Before: {self.x509_svid.leaf.not_valid_before}")
                logger.info(f"Certificate Not After: {self.x509_svid.leaf.not_valid_after}")
                
                return True
        except SpiffeError as e:
            logger.error(f"Failed to fetch X.509 SVID: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error fetching X.509 SVID: {e}")
            return False
    
    def fetch_jwt_svid(self):
        """Fetch JWT SVID from SPIRE Agent"""
        try:
            with default_workload_api_client() as client:
                # Define audience for JWT SVID
                audience = ["agentvault-service"]
                
                # Fetch JWT SVID
                jwt_svid = client.fetch_jwt_svid(audiences=audience)
                self.jwt_svid = jwt_svid[0]  # Get first SVID
                
                logger.info("Successfully fetched JWT SVID")
                logger.info(f"JWT SPIFFE ID: {self.jwt_svid.spiffe_id}")
                logger.info(f"JWT Audience: {self.jwt_svid.audience}")
                logger.info(f"JWT Expiry: {self.jwt_svid.expiry}")
                logger.info(f"JWT Token (first 50 chars): {self.jwt_svid.token[:50]}...")
                
                return True
        except SpiffeError as e:
            logger.error(f"Failed to fetch JWT SVID: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error fetching JWT SVID: {e}")
            return False
    
    def watch_x509_updates(self):
        """Watch for X.509 SVID updates"""
        try:
            logger.info("Starting X.509 SVID watcher...")
            with default_workload_api_client() as client:
                # This would typically run in a separate thread
                for x509_context in client.watch_x509_context():
                    svid = x509_context.default_svid()
                    logger.info(f"X.509 SVID updated - SPIFFE ID: {svid.spiffe_id}")
                    logger.info(f"New expiry: {svid.leaf.not_valid_after}")
                    
                    # For demo, break after first update
                    break
        except Exception as e:
            logger.error(f"Error in X.509 watcher: {e}")
    
    def check_opa_policy(self):
        """Query OPA for authorization decision based on JWT SVID"""
        if not self.jwt_svid:
            logger.error("No JWT SVID available for policy check")
            return False
        
        try:
            # Decode JWT to get claims (without verification - OPA will do that)
            # Split JWT and decode payload
            jwt_parts = self.jwt_svid.token.split('.')
            if len(jwt_parts) != 3:
                logger.error("Invalid JWT format")
                return False
            
            # Decode payload (add padding if necessary)
            payload = jwt_parts[1]
            payload += '=' * (4 - len(payload) % 4)  # Add padding
            claims = json.loads(base64.urlsafe_b64decode(payload))
            
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
    
    # Wait a bit for SPIRE Agent to be ready
    logger.info("Waiting for SPIRE Agent to be ready...")
    time.sleep(10)
    
    # Attempt to fetch SVIDs
    retry_count = 0
    max_retries = 5
    
    while retry_count < max_retries:
        logger.info(f"Attempt {retry_count + 1} to fetch SVIDs...")
        
        # Try to fetch X.509 SVID
        if workload.fetch_x509_svid():
            logger.info("✓ X.509 SVID fetched successfully")
            
            # Try to fetch JWT SVID
            if workload.fetch_jwt_svid():
                logger.info("✓ JWT SVID fetched successfully")
                
                # Check OPA policy
                logger.info("\n=== Checking OPA Policy ===")
                if workload.check_opa_policy():
                    logger.info("✓ OPA policy check passed")
                else:
                    logger.info("✗ OPA policy check failed")
                
                break
        
        retry_count += 1
        if retry_count < max_retries:
            logger.info(f"Retrying in 5 seconds...")
            time.sleep(5)
    
    if workload.spiffe_id:
        logger.info("=== SVID Fetch Summary ===")
        logger.info(f"Workload SPIFFE ID: {workload.spiffe_id}")
        logger.info("Identity successfully established!")
        
        # Demonstrate watching for updates
        workload.watch_x509_updates()
    else:
        logger.error("Failed to establish SPIFFE identity after all retries")
    
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
