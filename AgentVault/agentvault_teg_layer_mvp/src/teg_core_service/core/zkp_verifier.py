"""ZKP Verification Module for TEG Core Service

This module handles verification of Zero-Knowledge Proofs submitted as attestations.
For MVP, it simulates Noir verification via CLI or Python bindings.
"""
import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

from .config import get_settings

logger = logging.getLogger(__name__)


class ZKPVerifier:
    """Handles ZKP verification for various circuit types"""

    # §ATTESTREWARD (2026-10-13): every check below is a SIMULATION. No proof is verified cryptographically (a 32+ char
    # string starting "VALID_" passes), so nothing that pays may act on a True from here; the attestation endpoint reads
    # this flag and pays no reward while it is set. A real verifier (nargo, or the registry's verify_proof_detailed
    # from fix/zk-v2) sets it False.
    SIMULATED = True

    def __init__(self):
        self.settings = get_settings()
        # Use the circuits directory relative to the module
        base_path = Path(__file__).parent.parent.parent.parent
        self.circuit_registry_path = base_path / "circuits"
        
    def _load_circuit_metadata(self, circuit_id: str) -> Optional[Dict]:
        """Load circuit metadata from registry"""
        try:
            # Parse circuit_id format: PolicyName/version
            parts = circuit_id.split("/")
            if len(parts) != 2:
                logger.error(f"Invalid circuit_id format: {circuit_id}")
                return None
                
            policy_name, version = parts
            metadata_path = self.circuit_registry_path / policy_name / version / "metadata.json"
            
            if not metadata_path.exists():
                logger.error(f"Circuit metadata not found: {metadata_path}")
                return None
                
            with open(metadata_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading circuit metadata: {e}")
            return None
    
    def _get_verification_key_path(self, circuit_id: str) -> Optional[Path]:
        """Get path to verification key for circuit"""
        parts = circuit_id.split("/")
        if len(parts) != 2:
            return None
            
        policy_name, version = parts
        key_path = self.circuit_registry_path / policy_name / version / "verification_key.bin"
        return key_path if key_path.exists() else None
    
    def verify_fair_markup_proof(self, public_inputs: Dict, proof_value: str) -> bool:
        """Verify a Proof-of-Fair-Markup ZKP
        
        Args:
            public_inputs: Dictionary containing:
                - policy_parameters_hash
                - self_attested_total_component_costs
                - offered_price
            proof_value: The proof string/bytes
            
        Returns:
            bool: True if proof is valid, False otherwise
        """
        try:
            # For MVP, we simulate verification with basic checks
            # In production, this would use Noir CLI or Python bindings
            
            # Basic validation
            required_inputs = ["policy_parameters_hash", "self_attested_total_component_costs", "offered_price"]
            for input_name in required_inputs:
                if input_name not in public_inputs:
                    logger.error(f"Missing required public input: {input_name}")
                    return False
            
            # Validate numeric values
            costs = float(public_inputs["self_attested_total_component_costs"])
            price = float(public_inputs["offered_price"])
            
            if costs <= 0 or price <= 0:
                logger.error("Invalid cost or price values")
                return False
            
            if price < costs:
                logger.error("Price cannot be less than costs")
                return False
            
            # For MVP, we simulate verification by checking if proof_value is non-empty
            # and contains expected structure
            if not proof_value or len(proof_value) < 32:
                logger.error("Invalid proof value")
                return False
            
            # Simulate calling Noir verifier
            # In production: subprocess.run(["nargo", "verify", ...])
            logger.info("ZKP verification simulated (MVP mode)")
            
            # For MVP testing, accept proofs that start with "VALID_"
            if proof_value.startswith("VALID_"):
                return True
            
            # For MVP testing, reject proofs that start with "INVALID_"
            if proof_value.startswith("INVALID_"):
                return False
                
            # Default to False for MVP - invalid proofs should fail
            return False
            
        except Exception as e:
            logger.error(f"Error during ZKP verification: {e}")
            return False
    
    def verify_positive_balance_proof(self, public_inputs: Dict, proof_value: str) -> bool:
        """Verify a Proof-of-Positive-Balance ZKP
        
        Args:
            public_inputs: Dictionary containing:
                - agent_id: The agent's identifier
            proof_value: The proof string/bytes
            
        Returns:
            bool: True if proof is valid, False otherwise
        """
        try:
            # Basic validation
            required_inputs = ["agent_id"]
            for input_name in required_inputs:
                if input_name not in public_inputs:
                    logger.error(f"Missing required public input: {input_name}")
                    return False
            
            # Validate agent_id is non-empty
            agent_id = public_inputs.get("agent_id", "")
            if not agent_id:
                logger.error("Invalid agent ID")
                return False
            
            # For MVP, we simulate verification by checking if proof_value is non-empty
            # and contains expected structure
            if not proof_value or len(proof_value) < 32:
                logger.error("Invalid proof value")
                return False
            
            # Simulate calling Noir verifier
            # In production: subprocess.run(["nargo", "verify", ...])
            logger.info("ZKP verification simulated for positive balance proof (MVP mode)")
            
            # For MVP testing, accept proofs that start with "VALID_"
            if proof_value.startswith("VALID_"):
                return True
            
            # For MVP testing, reject proofs that start with "INVALID_"
            if proof_value.startswith("INVALID_"):
                return False
                
            # Default to False for MVP - invalid proofs should fail
            return False
            
        except Exception as e:
            logger.error(f"Error during positive balance ZKP verification: {e}")
            return False
    
    def verify_resource_usage_proof(self, public_inputs: Dict, proof_value: str) -> bool:
        """Verify a Proof-of-Accurate-Resource-Usage ZKP
        
        Args:
            public_inputs: Dictionary containing:
                - policy_parameters_hash
                - avtp_transaction_id
                - reported_resource_units_used
            proof_value: The proof string/bytes
            
        Returns:
            bool: True if proof is valid, False otherwise
        """
        try:
            # Basic validation
            required_inputs = ["policy_parameters_hash", "avtp_transaction_id", "reported_resource_units_used"]
            for input_name in required_inputs:
                if input_name not in public_inputs:
                    logger.error(f"Missing required public input: {input_name}")
                    return False
            
            # Validate transaction ID is non-zero
            tx_id = int(public_inputs["avtp_transaction_id"])
            if tx_id <= 0:
                logger.error("Invalid transaction ID")
                return False
            
            # Validate resource units is non-negative
            units = int(public_inputs["reported_resource_units_used"])
            if units < 0:
                logger.error("Resource units cannot be negative")
                return False
            
            # For MVP, we simulate verification by checking if proof_value is non-empty
            # and contains expected structure
            if not proof_value or len(proof_value) < 32:
                logger.error("Invalid proof value")
                return False
            
            # Simulate calling Noir verifier
            # In production: subprocess.run(["nargo", "verify", ...])
            logger.info("ZKP verification simulated for resource usage proof (MVP mode)")
            
            # For MVP testing, accept proofs that start with "VALID_"
            if proof_value.startswith("VALID_"):
                return True
            
            # For MVP testing, reject proofs that start with "INVALID_"
            if proof_value.startswith("INVALID_"):
                return False
                
            # Default to False for MVP - invalid proofs should fail
            return False
            
        except Exception as e:
            logger.error(f"Error during resource usage ZKP verification: {e}")
            return False
    
    def verify_proof(self, circuit_id: str, public_inputs: Dict, proof_value: str) -> bool:
        """Generic proof verification dispatcher
        
        Args:
            circuit_id: Circuit identifier (e.g., "fairMarkupPolicy/v1.0.0")
            public_inputs: Public inputs for the circuit
            proof_value: The proof to verify
            
        Returns:
            bool: True if proof is valid, False otherwise
        """
        # For MVP, handle circuit_id matching more flexibly
        # Map known circuit IDs to their handlers
        circuit_handlers = {
            "fairMarkupPolicy/v1.0.0": self.verify_fair_markup_proof,
            "resourceUsagePolicy/v1.0.0": self.verify_resource_usage_proof,
            "proofOfPositiveBalance/v1.0.0": self.verify_positive_balance_proof,
        }
        
        # Try direct match first
        if circuit_id in circuit_handlers:
            return circuit_handlers[circuit_id](public_inputs, proof_value)
        
        # Try to load metadata for unknown circuits
        # For simple circuit_id without version, try to match by circuit name
        if "/" not in circuit_id:
            # Try with default version
            circuit_id_with_version = f"{circuit_id}/v1.0.0"
        else:
            circuit_id_with_version = circuit_id
            
        # Load circuit metadata to determine proof type
        metadata = self._load_circuit_metadata(circuit_id_with_version)
        if metadata:
            # Get circuit name from metadata or parse from circuit_id
            circuit_name = metadata.get("circuitId", "")
            policy_name = metadata.get("PolicyName", circuit_name)
            
            # Route to appropriate verifier based on policy name
            if policy_name == "Proof-of-Fair-Markup":
                return self.verify_fair_markup_proof(public_inputs, proof_value)
            elif policy_name == "Proof-of-Accurate-Resource-Usage":
                return self.verify_resource_usage_proof(public_inputs, proof_value)
            elif circuit_name == "proofOfPositiveBalance" or policy_name == "Proof of Positive Balance":
                return self.verify_positive_balance_proof(public_inputs, proof_value)
        
        # For MVP, if we can't determine the circuit type, check proof prefix
        # This allows tests to work even without metadata files
        if proof_value.startswith("VALID_"):
            return True
        elif proof_value.startswith("INVALID_"):
            return False
        
        logger.error(f"Unknown circuit type: {circuit_id}")
        return False


# Singleton instance
_verifier: Optional[ZKPVerifier] = None


def get_zkp_verifier() -> ZKPVerifier:
    """Get singleton ZKP verifier instance"""
    global _verifier
    if _verifier is None:
        _verifier = ZKPVerifier()
    return _verifier
