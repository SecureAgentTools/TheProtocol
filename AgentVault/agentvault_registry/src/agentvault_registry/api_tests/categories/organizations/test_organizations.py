"""
Organizations Category Tests with Flow Testing

Tests for organization and team management endpoints with complete flow testing.
"""

import logging
from typing import List, Optional, Dict, Any
import time
from datetime import datetime, timezone

from agentvault_registry.api_tests.base import APITestBase

logger = logging.getLogger(__name__)


class TestOrganizations(APITestBase):
    """
    Test suite for organizations endpoints with flow testing capability.
    
    Implements complete organization lifecycle:
    1. Create organization
    2. List organizations
    3. Get organization details
    4. Update organization
    5. Create team
    6. Manage team members
    7. Send invitations
    8. Accept invitations
    9. Cleanup
    """
    
    CATEGORY_NAME = "organizations"
    
    # Priority endpoints for quick testing
    PRIORITY_ENDPOINTS = [
        "/organizations",  # POST - Create
        "/organizations",  # GET - List
        "/organizations/{org_id}",  # GET - Details
        "/organizations/{org_id}",  # DELETE - Cleanup
    ]
    
    # Flow values storage (references global DYNAMIC_VALUES)
    flow_values = {}
    # Store token for cleanup
    _developer_token = None
    
    async def setup(self):
        """Setup for organizations testing"""
        await self.setup_category(self.CATEGORY_NAME)
        logger.info("Organizations test setup complete")
        
        # Initialize flow values dictionary locally
        self.flow_values = {}
    
    async def teardown(self):
        """Cleanup after organizations testing"""
        # Clean up any created organizations
        if self.flow_values.get("org_id") and self._developer_token:
            try:
                await self.cleanup_organization(self.flow_values["org_id"], self._developer_token)
            except Exception as e:
                logger.warning(f"Failed to cleanup organization: {e}")
    
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
        flow_results = await self.test_organization_flow(developer_token)
        
        # OWL32 FIX: Return standard format so runner can parse it.
        standard_results["flow_tests"] = flow_results
        return standard_results
    
    async def test_organization_flow(self, developer_token: str) -> Dict[str, Any]:
        """
        Execute complete organization management flow.
        
        Flow sequence:
        1. Create organization → stores org_id, slug
        2. List organizations → verify created
        3. Get by ID → verify details
        4. Get by slug → verify same result
        5. Update organization → verify changes
        6. Create team → stores team_id
        7. List teams → verify created
        8. Get team details → verify
        9. Update team → verify changes
        10. Send invitation → stores invitation_token
        11. Accept invitation → creates membership
        12. List members → verify both members
        13. Add team member → verify added
        14. Remove team member → verify removed
        15. Delete organization → cleanup
        """
        logger.info("="*60)
        logger.info("Starting Organizations Flow Test")
        logger.info("="*60)
        
        # Store token for potential cleanup
        self._developer_token = developer_token
        
        results = []
        flow_success = True
        
        try:
            # Step 1: Create organization
            logger.info("Step 1: Creating organization...")
            create_result = await self.test_endpoint(
                method="POST",
                path="/organizations",
                auth_type="developer",
                body={
                    "name": f"Test Org {int(time.time())}",
                    "description": "Organization created for flow testing",
                    "type": "enterprise"
                },
                developer_token=developer_token
            )
            results.append({"step": 1, "name": "Create Organization", **create_result})
            
            if create_result.get("healthy") and create_result.get("responseData"):
                org_data = create_result["responseData"]
                self.flow_values["org_id"] = org_data.get("id")
                self.flow_values["org_slug"] = org_data.get("slug")
                logger.info(f"✅ Created organization: {self.flow_values['org_id']}")
            else:
                logger.error("❌ Failed to create organization")
                flow_success = False
                return {"success": False, "results": results, "error": "Failed at step 1"}
            
            # Step 2: List organizations
            logger.info("Step 2: Listing organizations...")
            list_result = await self.test_endpoint(
                method="GET",
                path="/organizations",
                auth_type="developer",
                developer_token=developer_token
            )
            results.append({"step": 2, "name": "List Organizations", **list_result})
            
            if list_result.get("healthy"):
                orgs = list_result.get("responseData", [])
                if any(org.get("id") == self.flow_values["org_id"] for org in orgs):
                    logger.info(f"✅ Organization found in list")
                else:
                    logger.warning("⚠️ Organization not found in list")
            
            # Step 3: Get organization by ID
            logger.info("Step 3: Getting organization by ID...")
            get_result = await self.test_endpoint(
                method="GET",
                path=f"/organizations/{self.flow_values['org_id']}",
                auth_type="developer",
                developer_token=developer_token
            )
            results.append({"step": 3, "name": "Get Organization by ID", **get_result})
            
            if get_result.get("healthy"):
                logger.info("✅ Retrieved organization by ID")
            else:
                logger.warning("⚠️ Failed to get organization by ID")
            
            # Step 4: Get organization by slug
            if self.flow_values.get("org_slug"):
                logger.info("Step 4: Getting organization by slug...")
                slug_result = await self.test_endpoint(
                    method="GET",
                    path=f"/organizations/slug/{self.flow_values['org_slug']}",
                    auth_type="developer",
                    developer_token=developer_token
                )
                results.append({"step": 4, "name": "Get Organization by Slug", **slug_result})
                
                if slug_result.get("healthy"):
                    logger.info("✅ Retrieved organization by slug")
            
            # Step 5: Update organization
            logger.info("Step 5: Updating organization...")
            update_result = await self.test_endpoint(
                method="PUT",
                path=f"/organizations/{self.flow_values['org_id']}",
                auth_type="developer",
                body={
                    "description": "Updated description for flow testing",
                    # a catalog key: settings here are validated like PUT .../settings (§SECFIX D6-492); the
                    # free-form `feature_flags` this step sent was stored and read by nothing
                    "settings": {"contract_offer_ttl_days": 30}
                },
                developer_token=developer_token
            )
            results.append({"step": 5, "name": "Update Organization", **update_result})
            
            if update_result.get("healthy"):
                logger.info("✅ Updated organization")
            
            # Step 6: Create team
            logger.info("Step 6: Creating team...")
            team_result = await self.test_endpoint(
                method="POST",
                path=f"/organizations/{self.flow_values['org_id']}/teams",
                auth_type="developer",
                body={
                    "name": "Engineering Team",
                    "description": "Test team for flow testing",
                    "permissions": ["read", "write"]
                },
                developer_token=developer_token
            )
            results.append({"step": 6, "name": "Create Team", **team_result})
            
            if team_result.get("healthy") and team_result.get("responseData"):
                team_data = team_result["responseData"]
                self.flow_values["team_id"] = team_data.get("id")
                logger.info(f"✅ Created team: {self.flow_values['team_id']}")
            
            # Step 7: List teams
            if self.flow_values.get("team_id"):
                logger.info("Step 7: Listing teams...")
                teams_result = await self.test_endpoint(
                    method="GET",
                    path=f"/organizations/{self.flow_values['org_id']}/teams",
                    auth_type="developer",
                    developer_token=developer_token
                )
                results.append({"step": 7, "name": "List Teams", **teams_result})
                
                if teams_result.get("healthy"):
                    logger.info("✅ Listed teams")
                
                # Step 8: Get team details
                logger.info("Step 8: Getting team details...")
                team_detail_result = await self.test_endpoint(
                    method="GET",
                    path=f"/organizations/{self.flow_values['org_id']}/teams/{self.flow_values['team_id']}",
                    auth_type="developer",
                    developer_token=developer_token
                )
                results.append({"step": 8, "name": "Get Team Details", **team_detail_result})
                
                if team_detail_result.get("healthy"):
                    logger.info("✅ Retrieved team details")
                
                # Step 9: Update team
                logger.info("Step 9: Updating team...")
                update_team_result = await self.test_endpoint(
                    method="PUT",
                    path=f"/organizations/{self.flow_values['org_id']}/teams/{self.flow_values['team_id']}",
                    auth_type="developer",
                    body={
                        "description": "Updated team description",
                        "permissions": ["read", "write", "admin"]
                    },
                    developer_token=developer_token
                )
                results.append({"step": 9, "name": "Update Team", **update_team_result})
                
                if update_team_result.get("healthy"):
                    logger.info("✅ Updated team")
            
            # Step 10: Send invitation to auditor account
            logger.info("Step 10: Sending invitation to auditor@theprotocol.cloud...")
            invite_result = await self.test_endpoint(
                method="POST",
                path=f"/organizations/{self.flow_values['org_id']}/invite",
                auth_type="developer",
                body={
                    "email": "auditor@theprotocol.cloud",  # Invite auditor account
                    "role": "member",
                    "team_ids": [self.flow_values.get("team_id")] if self.flow_values.get("team_id") else []
                },
                developer_token=developer_token
            )
            results.append({"step": 10, "name": "Send Invitation", **invite_result})
            
            if invite_result.get("healthy"):
                invite_data = invite_result.get("responseData")
                logger.info(f"Invitation response data: {invite_data}")
                
                if invite_data:
                    # Check if API returns the actual token (backend fix)
                    if "token" in invite_data:
                        # Backend has been fixed to return token!
                        self.flow_values["invitation_token"] = invite_data.get("token")
                        logger.info(f"✅ Sent invitation with token: {self.flow_values.get('invitation_token', 'N/A')[:20]}...")
                    elif "invitation_id" in invite_data:
                        # Old API only returns invitation_id (UUID), not the actual token
                        # The accept endpoint needs the token, not the ID
                        # This will fail until backend returns the token
                        self.flow_values["invitation_id"] = invite_data.get("invitation_id")
                        logger.warning(f"⚠️ API returned invitation_id but not token - accept will fail")
                        logger.info(f"📝 Invitation ID: {self.flow_values.get('invitation_id', 'N/A')}")
                else:
                    logger.warning("⚠️ Invitation succeeded but no response data returned")
            
            # Step 11: Accept invitation (requires token, not invitation_id)
            if self.flow_values.get("invitation_token"):
                logger.info("Step 11a: Logging in as auditor@theprotocol.cloud to accept invitation...")
                # Login as auditor to accept the invitation
                auditor_login_result = await self.test_endpoint(
                    method="POST",
                    path="/auth/login",
                    auth_type="none",
                    body={
                        "username": "auditor@theprotocol.cloud",
                        "password": "AuditorPass123!"
                    },
                    is_form_data=True
                )
                
                auditor_token = None
                if auditor_login_result.get("healthy") and auditor_login_result.get("responseData"):
                    auditor_token = auditor_login_result["responseData"].get("access_token")
                    if auditor_token:
                        logger.info("✅ Successfully logged in as auditor")
                    else:
                        logger.error("❌ Failed to get auditor token")
                
                if auditor_token:
                    logger.info("Step 11b: Accepting invitation as auditor...")
                    accept_result = await self.test_endpoint(
                        method="POST",
                        path=f"/organizations/invitations/{self.flow_values['invitation_token']}/accept",
                        auth_type="developer",
                        body={},
                        developer_token=auditor_token  # Use auditor's token to accept
                    )
                    results.append({"step": 11, "name": "Accept Invitation", **accept_result})
                    
                    if accept_result.get("healthy"):
                        logger.info("✅ Accepted invitation")
                else:
                    logger.warning("⏭️ Skipping invitation acceptance - couldn't login as auditor")
                    results.append({
                        "step": 11,
                        "name": "Accept Invitation",
                        "path": "/organizations/invitations/{token}/accept",
                        "method": "POST",
                        "healthy": False,
                        "statusCode": 401,
                        "error": "Could not login as auditor to accept invitation"
                    })
            else:
                # Skip acceptance if we don't have the token
                logger.warning("⏭️ Skipping invitation acceptance - API doesn't return token (backend fix needed)")
                # Create a proper result that will update the UI
                skip_result = {
                    "path": "/organizations/invitations/{token}/accept",
                    "method": "POST",
                    "authRequired": "developer",
                    "healthy": False,
                    "statusCode": 400,
                    "responseTime": 0,
                    "responseData": {
                        "error": "Cannot test - API doesn't return invitation token",
                        "note": "Backend must return 'token' field in invitation response",
                        "backend_logs_show": "Token is created but not returned in API response"
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": "API design issue - token not returned"
                }
                results.append({"step": 11, "name": "Accept Invitation", **skip_result})
            
            # Step 12: List members
            logger.info("Step 12: Listing members...")
            members_result = await self.test_endpoint(
                method="GET",
                path=f"/organizations/{self.flow_values['org_id']}/members",
                auth_type="developer",
                developer_token=developer_token
            )
            results.append({"step": 12, "name": "List Members", **members_result})
            
            if members_result.get("healthy"):
                members = members_result.get("responseData", [])
                logger.info(f"✅ Listed {len(members)} members")
                if members:
                    self.flow_values["member_id"] = members[0].get("developer_id")
            
            # Step 13: Add team member
            if self.flow_values.get("team_id") and self.flow_values.get("member_id"):
                logger.info("Step 13: Adding team member...")
                add_member_result = await self.test_endpoint(
                    method="POST",
                    path=f"/organizations/{self.flow_values['org_id']}/teams/{self.flow_values['team_id']}/members",
                    auth_type="developer",
                    body={
                        "developer_id": self.flow_values["member_id"],
                        "role": "member"
                    },
                    developer_token=developer_token
                )
                results.append({"step": 13, "name": "Add Team Member", **add_member_result})
                
                if add_member_result.get("healthy"):
                    logger.info("✅ Added team member")
                
                # Step 14: Remove team member
                logger.info("Step 14: Removing team member...")
                remove_member_result = await self.test_endpoint(
                    method="DELETE",
                    path=f"/organizations/{self.flow_values['org_id']}/teams/{self.flow_values['team_id']}/members/{self.flow_values['member_id']}",
                    auth_type="developer",
                    developer_token=developer_token
                )
                results.append({"step": 14, "name": "Remove Team Member", **remove_member_result})
                
                if remove_member_result.get("healthy"):
                    logger.info("✅ Removed team member")
            
            # Step 15: Delete organization (cleanup)
            logger.info("Step 15: Deleting organization (cleanup)...")
            delete_result = await self.test_endpoint(
                method="DELETE",
                path=f"/organizations/{self.flow_values['org_id']}",
                auth_type="developer",
                developer_token=developer_token
            )
            results.append({"step": 15, "name": "Delete Organization", **delete_result})
            
            if delete_result.get("healthy"):
                logger.info("✅ Deleted organization (cleanup complete)")
                # Clear flow values
                self.flow_values["org_id"] = None
                self.flow_values["org_slug"] = None
                self.flow_values["team_id"] = None
                self.flow_values["invitation_token"] = None
                self.flow_values["member_id"] = None
            
        except Exception as e:
            logger.error(f"Flow test error: {e}")
            flow_success = False
        
        # Calculate summary
        total_steps = len(results)
        successful_steps = sum(1 for r in results if r.get("healthy"))
        
        logger.info("="*60)
        logger.info(f"Organizations Flow Test Complete: {successful_steps}/{total_steps} steps passed")
        logger.info("="*60)
        
        return {
            "flow_name": "organizations_complete",
            "success": flow_success and successful_steps == total_steps,
            "total_steps": total_steps,
            "successful_steps": successful_steps,
            "results": results,
            "flow_values": {
                "org_id": self.flow_values.get("org_id"),
                "team_id": self.flow_values.get("team_id"),
                "org_slug": self.flow_values.get("org_slug")
            }
        }
    
    async def cleanup_organization(self, org_id: str, developer_token: str = None):
        """Helper to cleanup an organization"""
        try:
            await self.test_endpoint(
                method="DELETE",
                path=f"/organizations/{org_id}",
                auth_type="developer",
                developer_token=developer_token
            )
            logger.info(f"Cleaned up organization: {org_id}")
        except Exception as e:
            logger.warning(f"Failed to cleanup organization {org_id}: {e}")
    
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
