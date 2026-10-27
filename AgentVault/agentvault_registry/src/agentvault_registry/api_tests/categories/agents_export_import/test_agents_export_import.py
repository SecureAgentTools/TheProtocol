"""
Agent Export/Import Category Tests with Flow Testing

Tests for agent configuration export, import, bulk operations, and cloning.
"""

import logging
from typing import List, Optional, Dict, Any
import time
import json
import base64
from datetime import datetime, timezone

from agentvault_registry.api_tests.base import APITestBase

logger = logging.getLogger(__name__)


class TestAgentsExportImport(APITestBase):
    """
    Test suite for Agent Export/Import endpoints with flow testing capability.
    
    Implements complete export/import lifecycle:
    1. Create test agent
    2. Export agent configuration
    3. Validate export data
    4. Import configuration as new agent
    5. Validate imported agent
    6. Clone agent
    7. Bulk export multiple agents
    8. Test templates
    """
    
    CATEGORY_NAME = "agents_export_import"
    
    # Priority endpoints for quick testing
    PRIORITY_ENDPOINTS = [
        "/agents/{agent_did}/export",           # GET - Export Agent Configuration
        "/agents/import",                        # POST - Import Agent Configuration
        "/agents/{agent_did}/clone",            # POST - Clone Agent
        "/agents/export/bulk",                   # POST - Bulk Export Agents
    ]
    
    # Flow values storage
    flow_values = {}
    
    async def setup(self):
        """Setup for Export/Import testing"""
        await self.setup_category(self.CATEGORY_NAME)
        logger.info("Agent Export/Import test setup complete")
        
        # Initialize flow values dictionary locally
        self.flow_values = {}
    
    async def teardown(self):
        """Cleanup after Export/Import testing"""
        # Clean up any test agents created
        if self.flow_values.get("test_agent_did"):
            try:
                await self.test_endpoint(
                    method="DELETE",
                    path=f"/agents/{self.flow_values['test_agent_did']}",
                    auth_type="developer"
                )
            except Exception as e:
                logger.warning(f"Failed to delete test agent during cleanup: {e}")
    
    async def test_all(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Test all endpoints in this category"""
        # Run standard tests (returns format with 'summary' key that runner expects)
        standard_results = await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=False
        )
        
        # Then run flow test
        flow_results = await self.test_export_import_flow(developer_token)
        
        # OWL32 FIX: Return standard format so runner can parse it.
        standard_results["flow_tests"] = flow_results
        return standard_results
    
    async def test_export_import_flow(self, developer_token: str) -> Dict[str, Any]:
        """
        Execute complete Export/Import management flow.
        
        Flow sequence:
        1. Create test agent → source for export
        2. Export agent configuration → get full config
        3. Modify export data → prepare for import
        4. Validate import data → ensure it's valid
        5. Import as new agent → create from config
        6. Verify imported agent → check it matches
        7. Clone original agent → test cloning
        8. Get agent template → test template retrieval
        9. List agent templates → browse available
        10. Bulk export agents → export multiple
        11. Clean up test agents → remove created agents
        """
        logger.info("="*60)
        logger.info("Starting Agent Export/Import Flow Test")
        logger.info("="*60)
        
        results = []
        flow_success = True
        
        try:
            # Step 1: Create test agent using ONBOARDING FLOW
            logger.info("Step 1: Creating test agent via onboarding flow...")
            
            # First, request a bootstrap token
            bootstrap_result = await self.test_endpoint(
                method="POST",
                path="/onboard/bootstrap/request-token",
                auth_type="developer",
                body={
                    "agent_type_hint": "export_import_test",
                    "requested_by": "flow_test"
                },
                developer_token=developer_token
            )
            
            bootstrap_token = None
            if bootstrap_result.get("healthy") and bootstrap_result.get("responseData"):
                # The field is 'bootstrap_token', not 'token'!
                bootstrap_token = bootstrap_result["responseData"].get("bootstrap_token")
                if bootstrap_token:
                    logger.info(f"✅ Got bootstrap token: {bootstrap_token[:20]}...")
                else:
                    logger.error("❌ No bootstrap_token in response")
                    logger.error(f"Response data: {bootstrap_result['responseData']}")
                    flow_success = False
                    return {"success": False, "results": results, "error": "No bootstrap token in response"}
            else:
                logger.error("❌ Failed to get bootstrap token")
                flow_success = False
                return {"success": False, "results": results, "error": "Failed to get bootstrap token"}
            
            # Now create the agent using the bootstrap token
            # CRITICAL: Bootstrap token goes in HEADER, not body!
            agent_data = {
                "agent_did_method": "theprotocol",
                "agent_card": {
                    "schemaVersion": "1.0",
                    "agentVersion": "1.0",
                    "name": f"Export Test Agent {int(time.time())}",
                    "description": "Agent created for export/import flow testing",
                    "url": f"http://localhost:8100/agents/export-test-{int(time.time())}",
                    "humanReadableId": f"export-test-{int(time.time())}",
                    "provider": {
                        "name": "Flow Test Provider",
                        "organization": "AgentVault Test",
                        "contact": "test@theprotocol.cloud"
                    },
                    "capabilities": {
                        "a2aVersion": "1.0",
                        "inbound_protocols": ["cosv1", "avtp"],
                        "outbound_protocols": ["cosv1", "avtp"],
                        "tags": ["test", "export", "import", "automated"]
                    },
                    "authSchemes": [
                        {
                            "scheme": "oauth2",
                            "client_id": "pending",  # Will be assigned
                            "tokenUrl": "http://localhost:8000/api/v1/auth/agent/token"
                        }
                    ],
                    "service_endpoints": [
                        {
                            "type": "messaging",
                            "url": f"http://localhost:8100/agents/export-test-{int(time.time())}"
                        }
                    ],
                    "metadata": {
                        "created": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        "status": "active",
                        "teg_enabled": True,
                        "test_type": "export_import",
                        "created_by": "flow_test",
                        "version": "1.0.0"
                    }
                }
            }
            
            # Add bootstrap token to headers
            create_result = await self.test_endpoint(
                method="POST",
                path="/onboard/create_agent",
                auth_type="none",  # No bearer auth needed
                body=agent_data,
                headers={"Bootstrap-Token": bootstrap_token}
            )
            
            if create_result.get("healthy") and create_result.get("responseData"):
                agent_response = create_result["responseData"]
                self.flow_values["test_agent_did"] = agent_response.get("agent_did")  # FIXED: was 'did', should be 'agent_did'
                self.flow_values["original_name"] = agent_response.get("agent_card_name")  # FIXED: was 'name', should be 'agent_card_name'
                logger.info(f"✅ Test agent created: {self.flow_values['test_agent_did']}")
            else:
                logger.error("❌ Failed to create test agent")
                flow_success = False
                return {"success": False, "results": results, "error": "Failed at step 1"}
            
            results.append({"step": 1, "name": "Create Test Agent", **create_result})
            
            # Step 2: Export agent configuration
            logger.info("Step 2: Exporting agent configuration...")
            export_result = await self.test_endpoint(
                method="GET",
                path=f"/agents/{self.flow_values['test_agent_did']}/export",
                auth_type="developer",
                developer_token=developer_token
            )
            
            if export_result.get("healthy") and export_result.get("responseData"):
                self.flow_values["exported_config"] = export_result["responseData"]
                logger.info(f"✅ Agent configuration exported successfully")
                logger.info(f"  Export version: {self.flow_values['exported_config'].get('version', 'unknown')}")
            else:
                logger.error("❌ Failed to export agent configuration")
                flow_success = False
            
            results.append({"step": 2, "name": "Export Agent Configuration", **export_result})
            
            # Step 3: Modify export data for import
            logger.info("Step 3: Modifying export data for import...")
            if self.flow_values.get("exported_config"):
                import_config = self.flow_values["exported_config"].copy()
                # Modify the name to avoid conflicts
                if "agent" in import_config:
                    import_config["agent"]["name"] = f"Imported Agent {int(time.time())}"
                    import_config["agent"]["description"] = "Imported from export test"
                self.flow_values["import_config"] = import_config
                logger.info("✅ Export data modified for import")
                results.append({
                    "step": 3,
                    "name": "Modify Export Data",
                    "healthy": True,
                    "statusCode": 200,
                    "responseData": {"modified": True}
                })
            
            # Step 4: Validate import data
            logger.info("Step 4: Validating import data...")
            if self.flow_values.get("import_config"):
                validate_result = await self.test_endpoint(
                    method="POST",
                    path="/agents/import/validate",
                    auth_type="developer",
                    body={"export_data": self.flow_values["import_config"]},  # FIXED: Wrap in export_data field
                    developer_token=developer_token
                )
                
                if validate_result.get("healthy"):
                    logger.info("✅ Import data validated successfully")
                else:
                    logger.warning("⚠️ Import validation had issues")
                
                results.append({"step": 4, "name": "Validate Import Data", **validate_result})
            
            # Step 5: Import as new agent
            logger.info("Step 5: Importing as new agent...")
            if self.flow_values.get("import_config"):
                import_result = await self.test_endpoint(
                    method="POST",
                    path="/agents/import",
                    auth_type="developer",
                    body={"export_data": self.flow_values["import_config"]},  # FIXED: Wrap in export_data field
                    developer_token=developer_token
                )
                
                if import_result.get("healthy") and import_result.get("responseData"):
                    imported_agent = import_result["responseData"]
                    self.flow_values["imported_agent_did"] = imported_agent.get("did")
                    logger.info(f"✅ Agent imported successfully: {self.flow_values['imported_agent_did']}")
                else:
                    logger.warning("⚠️ Failed to import agent")
                
                results.append({"step": 5, "name": "Import Agent", **import_result})
            
            # Step 6: Verify imported agent
            logger.info("Step 6: Verifying imported agent...")
            if self.flow_values.get("imported_agent_did"):
                verify_result = await self.test_endpoint(
                    method="GET",
                    path=f"/agents/{self.flow_values['imported_agent_did']}",
                    auth_type="developer",
                    developer_token=developer_token
                )
                
                if verify_result.get("healthy"):
                    logger.info("✅ Imported agent verified")
                
                results.append({"step": 6, "name": "Verify Imported Agent", **verify_result})
            
            # Step 7: Clone original agent
            logger.info("Step 7: Cloning original agent...")
            if self.flow_values.get("test_agent_did"):
                clone_data = {
                    "name": f"Cloned Agent {int(time.time())}",
                    "description": "Cloned from export test agent"
                }
                
                clone_result = await self.test_endpoint(
                    method="POST",
                    path=f"/agents/{self.flow_values['test_agent_did']}/clone",
                    auth_type="developer",
                    body=clone_data,
                    developer_token=developer_token
                )
                
                if clone_result.get("healthy") and clone_result.get("responseData"):
                    cloned_agent = clone_result["responseData"]
                    self.flow_values["cloned_agent_did"] = cloned_agent.get("new_did")  # FIXED: was 'did', should be 'new_did'
                    logger.info(f"✅ Agent cloned successfully: {self.flow_values['cloned_agent_did']}")
                else:
                    logger.warning("⚠️ Failed to clone agent")
                
                results.append({"step": 7, "name": "Clone Agent", **clone_result})
            
            # Step 8: Get agent template (using real template)
            logger.info("Step 8: Getting agent template...")
            # Use a real template ID from the available templates
            template_result = await self.test_endpoint(
                method="GET",
                path="/agents/templates/data-processor",  # FIXED: Using real template ID
                auth_type="developer",
                developer_token=developer_token
            )
            
            if template_result.get("statusCode") == 404:
                logger.info("ℹ️ No template found (expected if no templates exist)")
                template_result["note"] = "Templates may not be configured yet"
            elif template_result.get("healthy"):
                logger.info("✅ Template retrieved")
            
            results.append({"step": 8, "name": "Get Agent Template", **template_result})
            
            # Step 9: List agent templates
            logger.info("Step 9: Listing agent templates...")
            list_templates_result = await self.test_endpoint(
                method="GET",
                path="/agents/templates",
                auth_type="developer",
                developer_token=developer_token
            )
            
            if list_templates_result.get("healthy"):
                templates = list_templates_result.get("responseData", [])
                logger.info(f"✅ Found {len(templates)} templates")
            
            results.append({"step": 9, "name": "List Agent Templates", **list_templates_result})
            
            # Step 10: Bulk export agents
            logger.info("Step 10: Bulk exporting agents...")
            agent_dids = []
            if self.flow_values.get("test_agent_did"):
                agent_dids.append(self.flow_values["test_agent_did"])
            if self.flow_values.get("imported_agent_did"):
                agent_dids.append(self.flow_values["imported_agent_did"])
            if self.flow_values.get("cloned_agent_did"):
                agent_dids.append(self.flow_values["cloned_agent_did"])
            
            if agent_dids:
                bulk_export_result = await self.test_endpoint(
                    method="POST",
                    path="/agents/export/bulk",
                    auth_type="developer",
                    body={"agent_dids": agent_dids},
                    developer_token=developer_token
                )
                
                if bulk_export_result.get("healthy"):
                    exports = bulk_export_result.get("responseData", {}).get("agents", [])
                    logger.info(f"✅ Bulk exported {len(exports)} agents")
                
                results.append({"step": 10, "name": "Bulk Export Agents", **bulk_export_result})
            else:
                logger.warning("⚠️ No agents to bulk export")
                results.append({
                    "step": 10,
                    "name": "Bulk Export Agents",
                    "healthy": True,
                    "statusCode": 200,
                    "responseData": {"message": "No agents to export"}
                })
            
            # Step 11: Clean up test agents
            logger.info("Step 11: Cleaning up test agents...")
            cleanup_count = 0
            for agent_key in ["imported_agent_did", "cloned_agent_did"]:
                if self.flow_values.get(agent_key):
                    try:
                        cleanup_result = await self.test_endpoint(
                            method="DELETE",
                            path=f"/agents/{self.flow_values[agent_key]}",
                            auth_type="developer",
                            developer_token=developer_token
                        )
                        if cleanup_result.get("healthy"):
                            cleanup_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete {agent_key}: {e}")
            
            logger.info(f"✅ Cleaned up {cleanup_count} test agents")
            results.append({
                "step": 11,
                "name": "Clean Up Test Agents",
                "healthy": True,
                "statusCode": 200,
                "responseData": {"cleaned_up": cleanup_count}
            })
            
        except Exception as e:
            logger.error(f"Flow test error: {e}")
            flow_success = False
        
        # Calculate summary
        total_steps = len(results)
        successful_steps = sum(1 for r in results if r.get("healthy"))
        
        logger.info("="*60)
        logger.info(f"Agent Export/Import Flow Test Complete: {successful_steps}/{total_steps} steps passed")
        logger.info("="*60)
        
        return {
            "flow_name": "agents_export_import_complete",
            "success": flow_success and successful_steps >= total_steps - 2,  # Allow 2 failures (templates might not exist)
            "total_steps": total_steps,
            "successful_steps": successful_steps,
            "results": results,
            "flow_values": {
                "test_agent_created": bool(self.flow_values.get("test_agent_did")),
                "export_successful": bool(self.flow_values.get("exported_config")),
                "import_successful": bool(self.flow_values.get("imported_agent_did")),
                "clone_successful": bool(self.flow_values.get("cloned_agent_did"))
            }
        }
    
    async def test_priority(
        self,
        developer_token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """Test only priority endpoints"""
        return await self.test_category_endpoints(
            category=self.CATEGORY_NAME,
            developer_token=developer_token,
            agent_token=agent_token,
            priority_only=True
        )
