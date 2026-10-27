"""
Request Bodies for API Testing

Central repository of default request bodies for each endpoint.
Extracted from admin_api_test.py for modular access.
"""

import copy
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD  # §SBROTATE


class RequestBodies:
    """Registry of default request bodies for API endpoints"""
    
    def __init__(self):
        self._bodies = self._initialize_bodies()
        # Track last registered account for subsequent auth tests
        self._last_registered = None
        self._sandbox_mode = False
        # P8.27: Dynamic agent DIDs and credentials (set by enable_sandbox_mode)
        self._agent_did = None
        self._agent_002_did = None
        self._client_id = None
        self._client_secret = None

    def enable_sandbox_mode(self, agent_did: str = None, agent_002_did: str = None, client_id: str = None, client_secret: str = None):
        """
        P8.27: Switch request bodies to use sandbox credentials.
        Called twice:
        1. At module load with no args (sets admin/dev creds only)
        2. After get_sandbox_tokens() with real dynamic DIDs + credentials
        
        Args:
            agent_did: Primary agent DID (from onboarding flow)
            agent_002_did: Counterparty agent DID (for disputes/transfers)
            client_id: Primary agent client_id (for auth/agent/token test)
            client_secret: Primary agent client_secret
        """
        self._sandbox_mode = True
        _did = agent_did or "AGENT_NOT_ONBOARDED"
        _did2 = agent_002_did or "AGENT2_NOT_ONBOARDED"
        self._client_id = client_id
        self._client_secret = client_secret
        # Auth (admin/dev creds are static — seeded by test_seed.py)
        self._bodies["/auth/login"] = {
            "username": "admin@test.sandbox",
            "password": SANDBOX_ADMIN_PASSWORD
        }
        # P8.27: Agent auth body — use dynamic credentials from onboarding
        self._bodies["/auth/agent/token"] = {
            "grant_type": "password",
            "username": client_id or "AGENT_NOT_ONBOARDED",
            "password": client_secret or "AGENT_NOT_ONBOARDED"
        }
        self._bodies["/auth/recover-account"] = {
            "email": "admin@test.sandbox",
            "recovery_key": "recovery_key_here"
        }
        # 2FA
        self._bodies["/auth/2fa/setup"] = {"password": SANDBOX_ADMIN_PASSWORD}
        self._bodies["/auth/2fa/disable"] = {"password": SANDBOX_ADMIN_PASSWORD, "code": "123456"}
        self._bodies["/auth/2fa/backup-codes"] = {"password": SANDBOX_ADMIN_PASSWORD, "current_code": "123456"}
        # Contracts — use dynamic agent DID
        self._bodies["/contracts/"]["client_agent_did"] = _did
        self._bodies["/contracts/{contract_id}/accept"]["upgrader_agent_did"] = _did
        # Disputes
        self._bodies["/disputes/"]["complainant_did"] = _did
        self._bodies["/disputes/{dispute_id}/evidence"]["submitter_did"] = _did
        self._bodies["/disputes/enhanced/log"]["defendant_agent_id"] = _did2
        # TEG
        self._bodies["/teg/transfer"]["receiver_agent_id"] = _did2
        self._bodies["/teg/system-transfer"]["to_did"] = _did
        self._bodies["/teg/disputes/log"]["defendant_agent_did"] = _did2
        self._bodies["/teg/attestations/submit"]["target_agent_did"] = _did
        self._bodies["/teg/attestations/submit"]["attestation_data"]["verifier"] = _did
        self._bodies["/teg/transactions/{transaction_id}/reputation-signal"]["metadata"] = {
            "quality_score": 5, "timeliness": "on_time"
        }
        # P8.27: Federation disputes + bulk export
        self._bodies["/federation/disputes/slash-request"]["defendant_did"] = _did
        # Phase E (2026-05-07): rewrite Phase-E placeholder bodies with real DIDs.
        # New endpoints added in this phase use AGENT_DID_PLACEHOLDER /
        # AGENT_002_DID_PLACEHOLDER literally; substitute now so the runner
        # doesn't 422 with "Invalid DID format".
        # Pass-3 fix: only rewrite when REAL DIDs were passed in. enable_sandbox_mode
        # is called twice — once at module load with no args (would otherwise
        # write "AGENT_NOT_ONBOARDED" into bodies, then forget to overwrite if a
        # category runs before the second call). Skip the rewrite on the first
        # (argless) call so the literal "AGENT_DID_PLACEHOLDER" stays in the body
        # and gets caught by existing EF stamps until the real DID lands.
        if agent_did and not agent_did.endswith("_NOT_ONBOARDED"):
            try:
                if "/teg/treasury/fund-agent" in self._bodies:
                    self._bodies["/teg/treasury/fund-agent"]["target_agent_did"] = _did2
                if "/teg/treasury/receive" in self._bodies:
                    self._bodies["/teg/treasury/receive"]["source_agent_did"] = _did2
                if "/onboard/download-bundle" in self._bodies:
                    self._bodies["/onboard/download-bundle"]["agent_did"] = _did
                # §APITEST 2026-09-04 — the families added above take the live DID too.
                for _p, _k in (("/chat/conversations", None),
                               ("/flare-shop/purchase", "buyer_agent_did"),
                               ("/fiat/flare/customize", "agent_did"),
                               ("/fiat/org-topup/checkout-session", "agent_did"),
                               ("/liability/mandates", "agent_did")):
                    if _p in self._bodies:
                        if _k is None:
                            self._bodies[_p]["target"]["agent_did"] = _did
                        else:
                            self._bodies[_p][_k] = _did
                    if client_id:
                        self._bodies["/onboard/download-bundle"]["client_id"] = client_id
                    if client_secret:
                        self._bodies["/onboard/download-bundle"]["client_secret"] = client_secret
                if "/achievements/claim-pending" in self._bodies:
                    self._bodies["/achievements/claim-pending"]["agent_did"] = _did
                if "/achievements/record" in self._bodies:
                    self._bodies["/achievements/record"]["agent_did"] = _did
                if "/agent-builder/generate-template" in self._bodies:
                    self._bodies["/agent-builder/generate-template"]["agent_did"] = _did
                    if client_id:
                        self._bodies["/agent-builder/generate-template"]["client_id"] = client_id
                if "/contracts/cross-registry/proxy" in self._bodies:
                    self._bodies["/contracts/cross-registry/proxy"]["upgrader_agent_did"] = _did
            except Exception:
                pass
        # OAuth — remove client_id/secret from body (sent via Basic auth now)
        self._bodies["/oauth/token/exchange"] = {
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": "SANDBOX_DEV_TOKEN_PLACEHOLDER",
            "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
            "scope": "teg:transfer:execute"
        }
        # §SUITES1018 batch 8: introspection takes FORM fields, the client's own credentials among them
        # (routers/oauth_federation.introspect_token: client_id and client_secret are Form(...)); this body dropped them,
        # so every call was refused 422 before the handler. Its token was the sweep's live developer JWT, sent to a route
        # that reads a token's claims back: a token that is none says the same about the route.
        self._bodies["/oauth/introspect"] = {
            "token": "apitest-not-a-token",
            "token_type_hint": "access_token",
            "client_id": "apitest-none",
            "client_secret": "apitest-none",
        }
        # Store dynamic DIDs for get_body() special handlers
        self._agent_did = _did
        self._agent_002_did = _did2
        import logging
        logging.getLogger(__name__).info(f"P8.27: RequestBodies sandbox mode — agent1={_did[:30]}, agent2={_did2[:30]}")
    
    def _initialize_bodies(self) -> Dict[str, Any]:
        """
        Initialize default request bodies.
        
        This is the complete DEFAULT_REQUEST_BODIES from admin_api_test.py
        """
        return {
            # Auth endpoints - FIXED based on actual schemas. §SUITES1018 batch 8: the login and agent token defaults are
            # placeholders (sandbox mode names the sweep's own accounts); they were literals of retired accounts, found
            # 2026-10-19 on no running registry
            "/auth/login": {
                "username": "apitest-no-such-account@test.sandbox",
                "password": "not-a-password"
            },
            "/auth/register": {
                "name": "Test User",
                "email": "testuser@example.com",
                "password": "TestPass123!",
                "organization": "Test Organization"
            },
            "/auth/agent/token": {
                "username": "apitest-no-such-client",
                "password": "not-a-client-secret",
                "grant_type": "password"
            },
            "/auth/recover-account": {
                "email": "auditor@theprotocol.cloud",
                "recovery_key": "recovery_key_here"
            },
            "/auth/set-new-password": {
                "new_password": "NewPassword123!"
            },
            "/auth/request-password-reset": {
                "email": "user@example.com"
            },
            "/auth/reset-password": {
                "token": "reset-token",
                "new_password": "NewPassword123!"
            },

            # 2026-04-25 — A2A Payment (f045). The {agent_did} target + payment_token
            # placeholders get replaced by the a2a_payment category prereq handler in
            # admin_api_test.py:_setup_a2a_payment which calls /authorize first to obtain
            # a real apt_ token, and substitutes target_agent_did with sandbox agent_002.
            "/a2a-payment/authorize": {
                "target_agent_did": "AGENT_002_DID_PLACEHOLDER",
                "amount": "10.0",
                "ttl_seconds": 900,
            },
            "/a2a-payment/settle": {
                "token": "APT_PLACEHOLDER_FROM_PREREQ",
            },
            "/a2a-payment/release": {
                "token": "APT_PLACEHOLDER_FROM_PREREQ",
            },
            "/a2a-payment/verify": {
                "token": "APT_PLACEHOLDER_FROM_PREREQ",
            },

            # 2026-04-25 — Relay action (cross-agent message relay).
            "/{agent_did}/relay/action": {
                "action": "ping",
                "payload": {"test": True},
            },
            "/auth/api-keys": "My API Key",  # Just a string, not object
            "/auth/generate-api-key": {
                "description": "API Key for testing"
            },
            "/auth/refresh": {
                "refresh_token": "dummy-refresh-token"
            },
            
            # 2FA endpoints - Added proper request bodies
            "/auth/2fa/setup": {
                "password": "AuditorPass123!"  # User's current password
            },
            "/auth/2fa/verify": {
                "code": "123456"  # 6-digit TOTP code
            },
            "/auth/2fa/disable": {
                "password": "AuditorPass123!",
                "code": "123456"  # Optional TOTP or backup code
            },
            "/auth/2fa/validate": {
                "partial_token": "dummy_partial_token_for_testing",
                "code": "123456"  # TOTP code
            },
            "/auth/2fa/recover": {
                "partial_token": "dummy_partial_token_for_testing",  # REQUIRED!
                "backup_code": "XXXX-YYYY"  # Backup recovery code
            },
            "/auth/2fa/backup-codes": {
                "password": "AuditorPass123!",
                "current_code": "123456"  # Current TOTP code
            },
            
            # Agent endpoints
            "/agents/heartbeat": {
                "status": "active",
                "metrics": {
                    "cpu": 50,
                    "memory": 1024
                }
            },
            
            # Agent Builder - FIXED to use correct type
            # §SUITES1018 batch 7: schemas.AgentBuildConfig's own names (agent_name, agent_description; a simple wrapper
            # names its backend and its model, check_conditional_fields): "name"/"description" were refused 422. The
            # route renders a package and returns it; nothing is deployed and no model is called.
            "/agent-builder/generate": {
                "agent_name": "apitest-built-agent",
                "agent_description": "A package the API tester generates and discards",
                "agent_builder_type": "simple_wrapper",
                "wrapper_llm_backend_type": "openai_api",  # P8.24b: Enum values: openai_api, anthropic_api, local_openai_compatible
                "wrapper_model_name": "gpt-4o-mini",
                "wrapper_auth_type": "none",
            },
            
            # Agent Cards - with all required fields
            "/agent-cards/": {
                "card_data": {
                    "name": "Test Agent Card",
                    "description": "Test agent card for API testing",
                    "humanReadableId": "test-agent-card",
                    "schemaVersion": "1.0",
                    "agentVersion": "1.0.0",
                    "url": "https://example.com/agent",
                    "provider": {
                        "name": "Test Provider",
                        "url": "https://example.com"
                    },
                    "capabilities": {
                        "a2aVersion": "1.0",
                        "supportedMessageParts": ["text", "data"],
                        "supportsPushNotifications": True
                    },
                    "authSchemes": [
                        {
                            "scheme": "oauth2",
                            "description": "OAuth2 Client Credentials Grant",
                            "tokenUrl": "https://example.com/token"
                        },
                        {
                            "scheme": "apiKey",
                            "description": "API Key authentication"
                        }
                    ],
                    "tags": ["test", "api-testing"],
                    "skills": [
                        {
                            "id": "test-skill",
                            "name": "Test Skill",
                            "description": "A test skill for API testing"
                        }
                    ]
                }
            },
            
            # Agent Logs - FIXED path
            "/agents/{agent_did}/logs": {
                "level": "INFO",
                "message": "Test log message",
                "source": "test_script",
                "metadata": {}
            },
            
            # Contracts
            "/contracts/": {
                "client_agent_did": "did:cos:fbf7393c-f3c1-ee05-7eb7",  # Will be replaced dynamically
                "scope_description": "Automated test contract for API testing",
                "source_code_repo_url": "https://git.example.org/agentvault/test-repo",
                "source_code_branch": "main",
                "acceptance_criteria": {
                    "test_suite_passes": True,
                    "code_coverage": 80,
                    "documentation_complete": True
                },
                "payment_amount": 1000  # Integer, not string
            },
            "/contracts/{contract_id}/accept": {
                "upgrader_agent_did": "did:cos:fbf7393c-f3c1-ee05-7eb7"
            },
            "/contracts/{contract_id}/submit": {
                "pr_url": "https://github.com/test/repo/pull/1"
            },
            "/contracts/{contract_id}/approve-completion": {},
            "/contracts/malpractice": {
                "contract_id": 1,
                "reason": "Service not delivered"
            },
            
            # Governance
            "/governance/proposals": {
                "title": "Test Proposal",
                "description": "Test proposal description",
                "duration_seconds": 86400  # 24 hours
            },
            "/governance/proposals/{proposal_id}/vote": {
                "vote_in_favor": True  # boolean: True for FOR, False for AGAINST
            },
            "/governance/proposals/{proposal_id}/tally": {},
            
            # Staking
            "/staking/stake": {
                "amount": "100"  # String format for amount
            },
            "/staking/unstake": {
                "amount": "50"  # String format for amount
            },
            "/staking/claim-rewards": {},
            
            # Attestations - correct structure
            "/attestations/submit": {
                "circuit_id": "test-circuit",
                "proof_data": {
                    "proof": "test-proof-data",
                    "public_inputs": {
                        "input1": "value1",
                        "input2": "value2"
                    }
                },
                "public_inputs": {
                    "input1": "value1",
                    "input2": "value2"
                }
            },
            
            # Reputation Signal endpoints: "/token/{transaction_id}/reputation-signal"
            # is defined once, further down (a repeated key here was overridden by it).
            
            # Federation - FIXED paths
            "/admin/federation/peers/{peer_id}/approve": {},
            "/admin/federation/peers/{peer_id}/deactivate": {},
            "/federation/peers/": {
                "name": "Test Federation Peer Registry B",
                "base_url": "http://localhost:8001",
                "admin_contact_email": "test@federation-peer.com",
                "discovery_auth_info": {
                    "type": "api_key",
                    # RegistryAuthInfoApiKey declares NO api_key field, so this value never reached anything; the 2026-08-05
                    # literal was a dead key (401 on all 13 registries, 2026-09-13) and is a placeholder now.
                    "api_key": "apitest-placeholder-not-a-key",
                    "api_key_header_name": "X-API-Key"
                }
            },
            "/federation/peers/{peer_id}": {
                "name": "Updated Test Peer Registry",
                "base_url": "https://updated-peer-registry.example.com",
                "admin_contact_email": "admin@updated-peer-registry.com",
                "discovery_auth_info": {
                    "type": "api_key",
                    "api_key": "updated-test-api-key",
                    "api_key_header_name": "X-API-Key"
                }
            },
            # TEG Policies - add request body for PUT
            "/teg/policies/{policy_id}": {
                "policy_name": "Updated Governance Policy Test",
                "policy_data": {
                    "quorum_percentage": 60,
                    "voting_period_days": 5
                }
            },
            "/internal/federation/query": {
                "search": "test",
                "tags": ["service", "agent"],
                "limit": 10
            },
            "/federation/sync-request": {
                # §SUITES1018: a source that is NOT the caller, refused (403) before any write. The tester speaks as
                # the peer frame, and an accepted sync stamps that peer's last_synced_at (a freshness signal the sweep
                # must not fake); the real sync between the frames runs every ten minutes.
                "source_registry": "spiffe://apitest.invalid/service/registry",
                "agent_cards": [],
                "sync_timestamp": datetime.now(timezone.utc).isoformat()
            },
            
            # TEG Integration - fixed field names
            "/teg/transfer": {
                "receiver_agent_id": "did:cos:test-recipient",  # Different DID to avoid self-transfer
                "amount": "100",
                "currency": "AVT"
            },
            # FIX-19C: TEGSystemTransferRequest only accepts 'amount' + 'purpose' (Pydantic model)
            "/teg/system-transfer": {
                "amount": "100",
                "purpose": "Test system transfer from API tester"
            },
            "/teg/transactions/{transaction_id}/reputation-signal": {
                "signal_type": "positive",
                "signal_value": 1,
                "reason": "Excellent service delivery",
                "metadata": {
                    "quality_score": 5,
                    "timeliness": "on_time"
                }
            },
            "/teg/policies": {
                "policy_code": "GOV_POLICY_001",
                "policy_name": "Governance Policy Test",
                "policy_type": "governance",
                "policy_data": {
                    "quorum_percentage": 51,
                    "voting_period_days": 7
                }
            },
            "/teg/policies/batch": {
                "policies": [{
                    "policy_code": "COMPLIANCE_POLICY_001",
                    "policy_name": "Compliance Policy Test",
                    "policy_type": "compliance",
                    "policy_data": {
                        "max_transaction_amount": "10000",
                        "require_kyc": True
                    }
                }]
            },
            "/teg/disputes/log": {
                "defendant_agent_did": "did:cos:fbf7393c-f3c1-ee05-7eb7",
                "reason_code": "SERVICE_FAILURE",
                "brief_description": "Test dispute"
            },
            "/teg/attestations/submit": {
                "target_agent_did": "did:cos:fbf7393c-f3c1-ee05-7eb7",
                "attestation_type": "identity_verification",
                "attestation_data": {
                    "verification_level": "basic",
                    "timestamp": "2025-01-28T12:00:00Z",
                    "verifier": "did:cos:fbf7393c-f3c1-ee05-7eb7"
                }
            },
            
            # Disputes
            "/disputes/": {
                "complainant_did": "did:cos:fbf7393c-f3c1-ee05-7eb7",  # Will be replaced dynamically
                "defendant_did": "did:cos:test-defendant",  # A different DID for testing
                "dispute_type": "SERVICE",
                "description": "Test dispute for automated API testing",
                "evidence": {
                    "description": "Initial evidence for the dispute",
                    "urls": ["https://example.com/evidence1"]
                }
            },
            # Disputes Enhanced - FIXED for self-dispute
            "/disputes/enhanced/log": {
                "defendant_agent_id": "did:cos:test-defendant",  # Different DID to avoid self-dispute
                "reason_code": "SERVICE_NOT_DELIVERED",  # OWL32: Must be in allowed_reason_codes
                "brief_description": "Test dispute from auditor account"
            },
            "/disputes/{dispute_id}/evidence": {
                "submitter_did": "did:cos:fbf7393c-f3c1-ee05-7eb7",  # Will be replaced dynamically
                "evidence_data": {  # OWL32: Must be evidence_data dict, not flat fields
                    "type": "TEXT",
                    "content": "Test evidence for dispute resolution",
                    "supporting_urls": ["https://example.com/evidence1"]
                }
            },

            
            # === OWL31: Federation Disputes ===
            "/federation/disputes/slash-request": {
                "settlement_id": "test-settlement-001",
                "dispute_id": 1,
                "ruling": "IN_FAVOR_OF_COMPLAINANT",
                "amount": 100,
                "complainant_did": "did:cos:test-complainant",
                "defendant_did": "did:cos:placeholder-for-sandbox",
                "origin_registry_url": "http://registry-test-b:8000",
                "callback_url": "http://registry-test-b:8000/api/v1/federation/disputes/slash-confirmation"
            },
            "/federation/disputes/slash-confirmation": {
                "settlement_id": "test-settlement-001",
                "status": "slashed",
                "amount": 100,
                "slash_event_id": "",
                "slash_tx_id": "test-slash-tx-001",
                "error_message": ""
            },
            "/federation/disputes/settlements/{settlement_id}/approve": {},
            "/federation/disputes/settlements/{settlement_id}/reject": {},
            "/federation/disputes/peer-slash-config/{peer_id}": {
                "auto_slash_enabled": True,
                "auto_slash_max_avt": 500
            },
            # === OWL31: OAuth Federation ===
            "/oauth/token/exchange": {
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": "test-subject-token",
                "subject_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "requested_token_type": "urn:ietf:params:oauth:token-type:access_token",
                "scope": "teg:transfer:execute",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret"  # P8.24b: Also required per validation
            },
            "/oauth/introspect": {
                "token": "test-introspect-token",
                "token_type_hint": "access_token",
                "client_id": "test-client-id",
                "client_secret": "test-client-secret"  # P8.24b: Also required per validation
            },
            # §SUITES1018 batch 8: revocation takes the same form fields (routers/oauth_federation.revoke_token: a token
            # or its jti, and the client's own credentials); it had no body and was refused 422 before the handler. A
            # token that is none: a configured federation answers the client's 401, an unconfigured one its 501.
            "/oauth/revoke": {
                "token": "apitest-not-a-token",
                "client_id": "apitest-none",
                "client_secret": "apitest-none",
            },
            "/oauth/federation/trust": {
                "registry_name": "Test Peer Registry",
                "registry_url": "https://peer.example.com",
                "teg_url": "https://peer.example.com/teg",
                "client_id": "test-client-id",
                "allowed_operations": ["teg:transfer:execute", "teg:balance:read"],
                "public_key_url": "https://peer.example.com/oauth/.well-known/jwks.json"
            },
            # === OWL31: Staking Rewards ===
            "/staking/rewards/distribute/manual": {},
            "/staking/rewards/agents/{agent_did}/auto-compound": {
                "enabled": True
            },

            # Admin
            "/admin/disputes/{dispute_id}/ruling": {
                "ruling": "IN_FAVOR_OF_COMPLAINANT",
                "notes": "Valid complaint - ruled in favor of complainant"
            },
            "/admin/health-check": {},
            "/admin/api-test/test-endpoint": {
                "method": "GET",
                "path": "/health",
                "headers": {},
                "body": None
            },
            "/admin/api-test/test-category": {
                "category": "auth",
                "developer_token": None,
                "agent_token": None
            },
            
            # Agent Cards - PUT endpoint for updates
            "/agent-cards/{card_id}": {
                "card_data": {
                    "description": "Updated description for test agent card",
                    "tags": ["test", "updated"]
                }
            },
            
            # Developers
            "/developers/me/apikeys": {
                "name": "Test API Key",
                "description": "Key for testing"
            },
            "/developers/me/agents/balances": {
                "agent_dids": ["did:agent:123", "did:agent:456"]
            },
            "/developers/webhooks": {
                "url": "https://example.com/webhook",
                "events": ["agent.created", "agent.updated"]
            },
            "/developers/webhooks/{webhook_id}": {
                "url": "https://example.com/webhook-updated",
                "events": ["agent.created", "agent.updated", "agent.deleted"]
            },
            
            # Onboarding - FIXED paths and bodies
            "/onboard/bootstrap/request-token": {},  # Empty body for verified developers
            "/onboard/register": {
                "agent_did_method": "theprotocol",  # DID method (e.g., 'theprotocol')
                "public_key_jwk": None,  # Optional: Agent's public key in JWK format
                "proof_of_work_solution": None  # Optional: Solution to PoW challenge
            },
            "/onboard/create_agent": {
                "agent_did_method": "theprotocol",
                "agent_card": {
                    "name": "Test Agent",
                    "description": "Test agent for onboarding",
                    "humanReadableId": "test-onboarding-agent",
                    "schemaVersion": "1.0",
                    "agentVersion": "1.0.0",
                    "url": "https://example.com/agent",
                    "provider": {
                        "name": "Test Provider",
                        "url": "https://example.com"
                    },
                    "capabilities": {
                        "a2aVersion": "1.0",
                        "supportedMessageParts": ["text", "data"],
                        "supportsPushNotifications": True
                    },
                    "authSchemes": [
                        {
                            "scheme": "oauth2",
                            "description": "OAuth2 Client Credentials Grant",
                            "tokenUrl": "https://example.com/token"
                        },
                        {
                            "scheme": "apiKey",
                            "description": "API Key authentication for programmatic access"
                        }
                    ],
                    "tags": ["test", "onboarding"],
                    "skills": [
                        {
                            "id": "test-skill",
                            "name": "Test Skill",
                            "description": "A test skill for the onboarding agent"
                        }
                    ]
                }
            },
            
            # Reputation - FIXED path and body
            "/token/{transaction_id}/reputation-signal": {
                "signal_value": 1,  # Must be +1 or -1
                "reason": "Excellent service"
            },
            
            # Utils
            "/utils/validate-card": {
                "card_data": {
                    "name": "Test Card",
                    "description": "Test card for validation",
                    "humanReadableId": "test-validation-card",
                    "schemaVersion": "1.0",
                    "agentVersion": "1.0.0",
                    "url": "https://example.com/test-card",
                    "provider": {
                        "name": "Test Provider",
                        "url": "https://example.com"
                    },
                    "capabilities": {
                        "a2aVersion": "1.0",
                        "supportedMessageParts": ["text", "data"],
                        "supportsPushNotifications": True
                    },
                    "authSchemes": [
                        {
                            "scheme": "apiKey",
                            "description": "API Key authentication"
                        }
                    ]
                }
            },
            
            # Organizations
            "/organizations": {
                "name": "Test Organization",
                "description": "Organization created for API testing",
                "website": "https://example.com/test-org",
                "settings": {}
            },
            "/organizations/{org_id}": {
                "name": "Updated Test Organization",
                "description": "Updated description"
            },
            "/organizations/{org_id}/teams": {
                "name": "Test Team {timestamp}",
                "description": "Team created for API testing",
                "permissions": ["read_agents", "create_agents"]
            },
            "/organizations/{org_id}/teams/{team_id}": {
                "name": "Updated Test Team",
                "description": "Updated team description"
            },
            "/organizations/{org_id}/invite": {
                "email": "invite-test@example.com",
                "role": "member"
            },
            "/organizations/{org_id}/teams/{team_id}/members": {
                "developer_id": 1,
                "role": "member"
            },
            "/organizations/{org_id}/teams/{team_id}/members/{developer_id}": {},

            # Agent CI/CD
            "/agents/{agent_did}/pipelines": {
                "pipeline_name": "test-pipeline",
                "pipeline_config": {
                    "stages": [
                        {"name": "test", "steps": [{"command": "pytest tests/"}]},
                        {"name": "build", "steps": [{"command": "docker build ."}]}
                    ]
                },
                "trigger_type": "push",
                "webhook_url": "https://example.com/webhooks/deploy",
                "environment_vars": {"ENV": "test"},
                "notification_config": {
                    "success_url": "https://example.com/success",
                    "failure_url": "https://example.com/failure"
                }
            },
            "/agents/{agent_did}/pipelines/{pipeline_id}": {
                "pipeline_name": "updated-pipeline",
                "pipeline_config": {
                    "stages": [
                        {"name": "lint", "steps": [{"command": "flake8 src/"}]},
                        {"name": "test", "steps": [{"command": "pytest tests/"}]}
                    ]
                },
                "trigger_type": "manual"
            },
            "/agents/{agent_did}/versions": {
                "version": "1.0.1",
                "description": "Test version for API testing",
                "changelog": "Initial test version",
                "config_snapshot": {"features": ["basic"]}
            },
            "/agents/{agent_did}/versions/{version_id}/activate": {},
            "/agents/{agent_did}/versions/{version_id}/rollback": {},
            "/agents/{agent_did}/deployments": {
                "pipeline_id": "00000000-0000-0000-0000-000000000002",  # P8.24b: Must be valid UUID (column is UUID type)
                "environment": "staging"
            },
            "/agents/{agent_did}/deployments/{deployment_id}/status": {
                "status": "completed",
                "message": "Deployment completed successfully"
            },
            "/agents/{agent_did}/deployments/{deployment_id}/logs": {
                "log_entries": [
                    {"timestamp": "2026-01-01T00:00:00Z", "level": "INFO", "message": "Deployment started"},
                    {"timestamp": "2026-01-01T00:01:00Z", "level": "INFO", "message": "Tests passed"}
                ]
            },
            "/pipeline-templates": {
                "name": "Test Pipeline Template",
                "description": "Template for API testing",
                "category": "python",  # P8.24: Required by service - KeyError without it
                "template_config": {
                    "stages": [{"name": "test", "steps": [{"command": "pytest"}]}]
                },
                "price_teg": 0,
                "tags": ["test"]
            },
            "/pipeline-templates/{template_id}/purchase": {
                "buyer_did": "did:cos:test-agent"  # P8.24: Handler reads buyer_did not agent_did
            },

            # Agent Export/Import
            "/agents/export/bulk": {
                "agent_dids": ["placeholder"],
                "options": {"include_metrics": False, "include_versions": True}
            },
            "/agents/import": {
                "export_data": {
                    "export_version": "1.0",
                    "agent": {
                        "name": "Imported Test Agent",
                        "description": "Agent imported for API testing",
                        "type": "service"
                    }
                },
                "options": {"conflict_resolution": "skip", "dry_run": True}
            },
            "/agents/import/validate": {
                "export_data": {
                    "export_version": "1.0",
                    "agent": {
                        "name": "Validate Test Agent",
                        "description": "Agent validated for API testing",
                        "type": "service"
                    }
                },
                "options": {"conflict_resolution": "skip", "dry_run": True}
            },

            # TEG Transactions
            "/teg/batch-transfer": {
                "transfers": [
                    {"to": "did:agent:1", "amount": "100"},
                    {"to": "did:agent:2", "amount": "200"}
                ]
            },
            "/teg/transactions/batch": {
                "transactions": [
                    {
                        "type": "transfer",
                        "receiver_agent_id": "did:cos:test-recipient-1",
                        "amount": "100",
                        "currency": "AVT"
                    },
                    {
                        "type": "transfer",
                        "receiver_agent_id": "did:cos:test-recipient-2",
                        "amount": "200",
                        "currency": "AVT"
                    }
                ]
            },

            # ── Enforcement Admin (OWL Autonomous Campaign 2026-03-08) ──────────
            "/admin/enforcement/policy": {
                "policy_json": {
                    "offense_thresholds": {"level_1": 1, "level_2": 3, "level_3": 5, "level_4": 8},
                    "slash_percentages": {"level_2": 5, "level_3": 10, "level_4": 25},
                    "cooldown_days": {"level_1": 7, "level_2": 14, "level_3": 30},
                    "transaction_fees": {"base_rate_percent": 1.5, "max_rate_percent": 7.5},
                    "reputation_bond": {"amount_avt": 50, "min_transactions": 10, "min_age_days": 30, "min_eigentrust": 0.1}
                },
                "reason": "API test policy update"
            },
            "/admin/enforcement/agents/{agent_did}/slash-stake": {
                "amount": 10,
                "reason": "API test slash (minimal amount)"
            },
            "/admin/enforcement/agents/{agent_did}/record-offense": {
                "offense_type": "dispute_lost",
                "severity": 1,
                "reference": "api-test-offense",
                "disputed_amount": 0
            },
            "/admin/enforcement/agents/{agent_did}/pause-rewards": {
                "duration_days": 1,
                "reason": "API test payout pause"
            },
            "/admin/enforcement/agents/{agent_did}/suspend": {
                "reason": "API test suspension"
            },
            "/admin/enforcement/agents/{agent_did}/reinstate": {
                "reason": "API test reinstatement"
            },
            "/admin/enforcement/pending/{action_id}/reject": {
                "reason": "API test rejection"
            },

            # ── Enforcement Agent ────────────────────────────────────────────────
            "/agents/reputation-bond/deposit": {
                # amount omitted → uses policy default (50 AVT)
            },

            # ── EigenTrust++ Reputation ──────────────────────────────────────────
            "/reputation/admin/trigger-computation": {},

            # ── Phase A (2026-04-22) — diagnostic + federation bodies ───────────
            # admin_diagnostics — Command Center (f050, 2026-04-18)
            "/admin/diagnostics/run": {
                "check_ids": [],           # empty → runs all applicable
                "targets": ["sandbox-a"],  # targets.py adds sandbox-a when CC_TARGET_ENVIRONMENT=sandbox
                "force": False,
            },
            "/admin/diagnostics/run-all": {
                "target": "sandbox-a",
                "force": False,
            },
            "/admin/diagnostics/actions/{action_id}": {
                "target": "sandbox-a",
                "dry_run": True,           # safe default — don't actually remediate
            },

            # federation_topology — WS1/WS2 (2026-04-21)
            "/admin/federation/topology/peers/{peer_id}/probe": {},

            # ── Phase B (2026-04-22) — admin management plane bodies ─────────
            # admin_developers — M1 (2026-04-20)
            "/admin/developers/{developer_id}/suspend": {
                "reason": "API tester suspension trigger — dry run on throwaway dev"
            },
            "/admin/developers/{developer_id}/reinstate": {
                "reason": "API tester reinstate flow — re-enabling after suspend test"
            },
            "/admin/developers/{developer_id}/force-password-reset": {
                "reason": "API tester force-password-reset flow"
            },
            "/admin/developers/{developer_id}/disable-2fa": {
                "reason": "API tester 2FA disable flow"
            },
            "/admin/developers/{developer_id}/force-email-verify": {
                "reason": "API tester email-verify override flow"
            },
            "/admin/developers/{developer_id}/revoke-api-keys": {
                "reason": "API tester key revocation flow"
            },
            "/admin/developers/{developer_id}": {
                # DELETE body: the router names the throwaway made for this row alone (§SUITES1018 batch 8 part 4:
                # __DELETE_DEV_EMAIL__, from the flow values, which every worker reads), otherwise 400 email-mismatch
                "reason": "API tester delete flow — throwaway target",
                "confirm_email": "__DELETE_DEV_EMAIL__"
            },
            "/admin/developers/{developer_id}/admin-flags": {
                # PUT on the sweep's own throwaway (§SUITES1018 batch 8): False, so the route is measured and grants
                # nothing (True went to the tester's own admin and read 400 "cannot modify your own flags"; on a
                # throwaway it would have made an admin of an account nobody signs in to)
                "admin_support": False
            },

            # admin_agents — M2 (2026-04-20)
            "/admin/agents/{target_agent_did}/transfer-ownership": {
                # §SUITES1018 batch 8 (part 8b): to the sweep's own throwaway developer (the router resolves the marker).
                # 1 was the frame admin: every sweep handed it one of its agents (V0625: the agent it acted as, 06:11Z)
                "new_creator_developer_id": "__SWEEP_DEVELOPER_ID__",
                "reason": "API tester ownership-transfer flow"
            },
            "/admin/agents/{target_agent_did}/rotate-credentials": {
                "reason": "API tester credential rotation flow"
            },
            "/admin/agents/{target_agent_did}/force-mtls-enrol": {
                "reason": "API tester mTLS enrollment flow"
            },
            "/admin/agents/{target_agent_did}": {
                # DELETE body — `confirm_did` is rewritten at call time to the
                # agent_002_did in test-endpoint special handler so the endpoint
                # actually validates. Without that, returns 400 (email mismatch).
                "reason": "API tester delete flow — non-primary counterparty agent",
                "confirm_did": "CONFIRM_DID_PLACEHOLDER"
            },
            "/admin/agents/bulk/suspend": {
                # agent_dids list — populated at call time with agent_002_did
                "agent_dids": ["AGENT_002_DID_PLACEHOLDER"],
                "reason": "API tester bulk suspend flow"
            },

            # ── Phase C (2026-04-22) — federation state changes ─────────────
            # frame_invitations public (synthetic trust domain — expected to probe-fail,
            # which is informative). Rate-limited 5/hour.
            "/federation/frame-invitations": {
                "trust_domain": "synthetic-test-invite.test",
                "bundle_endpoint_url": "https://synthetic-test-invite.test:8443",
                "federation_endpoint_url": "https://synthetic-test-invite.test:18443",
                "event_store_url": "https://synthetic-test-invite.test:8200",
                "name": "Synthetic API-Test Invitation",
                "description": "Auto-generated by API tester — not a real peer, probe expected to fail",
                "contact_email": "api-tester@test.sandbox",
                "initiator_nonce": "apitester0000000000000000000000000000000000000000000000000000fff",
            },
            "/federation/frame-invitations/{invitation_id}/finalize": {
                "approver_trust_domain": "synthetic-approver.test",
                "nonce_echo": "apitester0000000000000000000000000000000000000000000000000000fff",
                "bundle_endpoint_url": "https://synthetic-approver.test:8443",
                "federation_endpoint_url": "https://synthetic-approver.test:18443",
            },
            # frame_invitations admin
            "/admin/federation/frame-invitations/{invitation_id}/approve": {
                "review_notes": "API tester approve flow — synthetic invitation"
            },
            "/admin/federation/frame-invitations/{invitation_id}/reject": {
                "reason": "API tester reject flow — synthetic invitation rejected for coverage"
            },
            "/admin/federation/frame-invitations/{invitation_id}/finalize-retry": {},
            "/admin/federation/frames/{peer_id}/revoke": {
                "reason": "API tester revoke flow — reversible test"
            },
            "/admin/federation/frames/{peer_id}/resync-eventstore": {},

            # consul_admin mutating
            "/admin/federation/compliance/enforcement-mode": {
                "mode": "dry_run",
                "reason": "API tester enforcement-mode flip — revert via another call"
            },
            "/admin/federation/compliance/peers/{peer_id}/poll-now": {
                "dry_run_only": True
            },

            # ── Phase D (2026-04-22) — financial flow bodies ─────────────────
            # funding_requests
            "/funding/request": {
                "amount": "500",
                "reason": "API tester auto-created funding request for coverage — safe small amount"
            },
            "/admin/funding/{request_id}/approve": {
                "approved_amount": "500"
            },
            "/admin/funding/{request_id}/reject": {
                "reason": "API tester reject flow — synthetic request"
            },

            # token_bridge — cross-frame (source: sandbox-a, target: sandbox-b)
            "/bridge/transfer": {
                "target_agent_did": "AGENT_002_DID_PLACEHOLDER",
                "amount": 10,
                "target_frame_url": "http://registry-test-b:8000",
                "target_trust_domain": "sandbox-b.test"
            },
            "/bridge/mint-wrapped": {
                # Admin mint — requires a real bridge_tx_id from a prior transfer.
                # Expected to fail until Phase 12 operators.
                "bridge_tx_id": "BRIDGE_TX_ID_PLACEHOLDER",
                "source_agent_did": "AGENT_DID_PLACEHOLDER",
                "target_agent_did": "AGENT_002_DID_PLACEHOLDER",
                "amount": 10,
                "source_frame": "sandbox-a.test"
            },
            # D6-345: a redemption and an unlock name the bridge transfer; owner and amount come from its record.
            "/bridge/redeem": {
                "bridge_tx_id": "BRIDGE_TX_ID_PLACEHOLDER"
            },
            "/bridge/unlock": {
                "bridge_tx_id": "BRIDGE_TX_ID_PLACEHOLDER"
            },

            # ── Phase E (2026-05-07) — empty-body sweep ─────────────────────
            # Adds bodies for endpoints that previously hit the
            # "POST/PUT body required — runner sends empty body" EF stamp at
            # admin_api_test.py:772. Schemas verified against routers/.
            #
            # NB: many of these are validate-only / state-mutating with safe
            # defaults; the tester runs them with synthetic state, so failures
            # downstream are still caught by the existing "fixture data
            # missing" / "state-dep" EF stamps.

            # ─ TEG treasury + cross-registry + staking proxies ─
            "/teg/cross-registry-transfer": {
                # receiver on sandbox-b sandbox; substituted at call time if a
                # cross-frame fixture is seeded. Falls through with sandbox-b
                # placeholder, hits "Fixture data missing" / state-dep otherwise.
                "receiver_did": "did:theprotocol:sandbox-b-counterparty-placeholder",
                "amount": "1",
                "message": "API tester cross-registry transfer probe",
            },
            "/teg/treasury/mint": {
                # Defaults to system treasury per TreasuryMintRequest schema.
                "amount": "1",
                "reason": "API tester mint probe — minimal amount",
            },
            "/teg/treasury/fund-agent": {
                # target_agent_did is rewritten by _setup_admin_agents /
                # _setup_teg etc. when sandbox tokens are seeded; default
                # placeholder triggers "Fixture data missing" if not.
                "target_agent_did": "AGENT_002_DID_PLACEHOLDER",
                "amount": "1",
                "reason": "admin_grant",
            },
            "/teg/treasury/receive": {
                "source_agent_did": "AGENT_002_DID_PLACEHOLDER",
                "amount": "1",
                "reason": "fee_collection",
            },
            "/teg/treasury/cross-teg-fund": {
                # Origin-only restriction: only Registry-A can call. On sandbox-A
                # this triggers "Cross-TEG treasury funding is restricted to the
                # origin registry" → 403 → "Sandbox-only endpoint blocked from
                # prod registry" EF (or 200 if sandbox is REGISTRY_A_NAME).
                "target_registry": "Registry B",
                "amount": "1",
                "reason": "cross_teg_fund",
            },
            "/teg/staking/stake": {
                "amount": "1",
                "lock_period_days": 30,
            },
            "/teg/staking/unstake": {
                # stake_id is required; placeholder lets the validator pass and
                # the TEG layer responds with "stake not found" → state-dep EF.
                "stake_id": "stake-placeholder-not-real",
                "amount": "1",
            },
            "/teg/disputes/{dispute_id}/resolve": {
                "resolution": "RESOLVED_NO_ACTION",
                "resolution_details": "API tester probe — placeholder resolution",
            },

            # ─ Governance: federation propose/vote/veto + auto-tally config ─
            "/governance/federation/propose": {
                # local_proposal_id required; placeholder hits "Local proposal
                # not found" → 404 (covered by state-dep EF on cross-frame).
                "local_proposal_id": 0,
                "duration_seconds": 604800,
            },
            "/governance/federation/proposals/{proposal_id}/vote": {
                "vote_in_favor": True,
                "reason": "API tester probe vote",
            },
            "/governance/federation/proposals/{proposal_id}/veto": {
                "reason": "API tester probe veto",
            },
            "/governance/auto-tally/config": {
                # PUT — partial update; setting same default keeps state stable.
                "enabled": True,
                "interval_seconds": 60,
            },

            # ─ Auth: change/forgot/resend (Body embed=True for email) ─
            # IMPORTANT: change-password mutates the sandbox admin's password
            # which then breaks every subsequent test that logs in. Use a
            # deliberately WRONG current_password so the endpoint 400s with
            # "Current password is incorrect" and our EF stamp catches it
            # — sandbox state preserved, endpoint still exercised.
            "/auth/change-password": {
                "current_password": "DefinitelyWrongCurrentPassword999!",
                "new_password": "Sw3etCypher!Beta47",
            },
            "/auth/forgot-password": {
                # Body(..., embed=True) → wrapped in {"email": ...}
                "email": "admin@test.sandbox",
            },
            "/auth/resend-verification": {
                "email": "admin@test.sandbox",
            },

            # ─ Onboard: reset-credentials (rate-limited 3/hr; password req) ─
            "/onboard/agents/{agent_did}/reset-credentials": {
                "password": SANDBOX_ADMIN_PASSWORD,
            },
            # POST /onboard/download-bundle — bundle download for an agent.
            # BundleRequest needs agent_did + client_id + client_secret. Synthetic
            # placeholders will hit "client_id mismatch" 403 (caught by EF) since
            # we don't have access to the agent's real client_secret.
            "/onboard/download-bundle": {
                "agent_did": "AGENT_DID_PLACEHOLDER",
                "client_id": "agent-synthetic-client-id",
                "client_secret": "tp_secret_synthetic_placeholder_for_api_tester_probe",
                "template_type": "minimal",
            },

            # ─ Developers: PUT /developers/me (DeveloperProfileUpdate) ─
            "/developers/me": {
                "display_name": "API Tester",
                "bio": "Auto-set by API Tester",
                "timezone": "UTC",
            },

            # ─ Webhooks (POST + PUT) ─
            "/webhooks": {
                "url": "https://example.com/api-tester-webhook",
                "events": ["agent.created"],
                "description": "API tester probe webhook",
            },
            "/webhooks/{webhook_id}": {
                "url": "https://example.com/api-tester-webhook-updated",
                "events": ["agent.created", "agent.updated"],
                "is_active": True,
                "description": "API tester probe webhook (updated)",
            },

            # ─ Admin: simulation, broadcast, tutorial, invite-codes, agents/bulk
            "/admin/simulation/start": {
                "mode": "mixed",
                "pairs": 2,
                "cycle_interval": 60,
                "cycles": 1,
                "instances": 1,
                "concurrency": 4,
                "backend_mode": "intra",
                "rate_tps": 0.1,
            },
            "/admin/simulation/fund": {
                "target_balance": 1000,
                "only_depleted": True,
                "depleted_threshold": 50,
            },
            "/admin/simulation/funding-preview": {
                "target_balance": 1000,
                "only_depleted": True,
                "depleted_threshold": 50,
            },
            "/admin/broadcasts": {   # §MCPTEST30 V0640: a direct notice to the sweep's own throwaway developer
                "title": "API Tester Probe",
                "body": "Direct notice from the automated API tester to its own test account; please ignore.",
                "broadcast_type": "info",
                "send_email": False,
                "target_developer_id": "__SWEEP_DEVELOPER_ID__",
            },
            "/admin/tutorial/execute": {
                "method": "GET",
                "path": "/health",
                "body": None,
                "auth_token": None,
                "auth_type": "none",
            },
            "/admin/tutorial/generate-proof": {
                # Deliberately names no tutorial circuit: the route answers 400 with
                # the four v2.0.0 circuits it proves instead of running nargo and bb
                # on every sweep. It reads circuit_id and agent_did (the agent the
                # proof's reference names). The flow_zkp_* flows make real proofs.
                "circuit_id": "test-circuit",
            },
            "/admin/invite-codes/generate": {
                "count": 1,
                "expires_days": 30,
                "note": "API tester batch — single throwaway",
                "max_uses": 1,
            },
            "/admin/agents/bulk/reinstate": {
                "agent_dids": ["AGENT_002_DID_PLACEHOLDER"],
                "reason": "API tester bulk reinstate flow",
            },

            # ─ Admin: support tickets reply/status (under /admin/support/...) ─
            "/admin/support/tickets/{ticket_id}/reply": {
                "message": "API tester admin reply probe.",
            },
            "/admin/support/tickets/{ticket_id}/status": {
                "status": "in_progress",
            },

            # ─ Admin: enforcement registries (peer quarantine/lift/blacklist) ─
            "/admin/enforcement/registries/{peer_id}/quarantine": {
                "reason": "API tester probe quarantine — synthetic, expected to revert.",
                "grace_hours": 24,
            },
            "/admin/enforcement/registries/{peer_id}/lift-quarantine": {
                # 64-char hex sha256 — synthetic but schema-valid.
                "new_policy_hash": "a" * 64,
            },
            "/admin/enforcement/registries/{peer_id}/blacklist": {
                "reason": "API tester probe blacklist — synthetic peer for coverage.",
            },

            # ─ Admin: federation policy + admission + license generate/revoke ─
            "/admin/federation/validate-policy": {
                "policy_json": {
                    "fee_rate": 0.005,
                    "max_fee_rate": 0.05,
                    "min_stake": 100,
                },
            },
            "/admin/federation/request-admission": {
                "registry_name": "synthetic-api-tester-peer",
                "registry_operator_did": "did:theprotocol:synthetic-tester-operator",
                "registry_public_url": "https://synthetic-api-tester.test:8443",
                "admin_contact_email": "api-tester@test.sandbox",
                "operator_identity_proof": {},
                "policy_json": {
                    "fee_rate": 0.005,
                    "max_fee_rate": 0.05,
                    "min_stake": 100,
                },
            },
            "/admin/federation/policy-update-request": {
                "peer_did": "did:theprotocol:synthetic-tester-peer",
                "proposed_policy_json": {
                    "fee_rate": 0.006,
                    "max_fee_rate": 0.05,
                    "min_stake": 100,
                },
                "change_summary": "API tester probe — synthetic policy update.",
            },
            "/admin/federation/licenses/generate": {
                "operator_name": "API Tester Synthetic Op",
                "operator_did": "did:theprotocol:api-tester-synthetic-op",
                "max_agents": 10,
                "max_events_per_minute": 100,
                "federation_tier": "standard",
            },
            "/admin/federation/licenses/{license_id}/revoke": {
                "reason": "API tester probe revoke — synthetic license.",
            },

            # ─ Admin: api-test test-flow (recursive flow runner) ─
            "/admin/api-test/test-flow": {
                # Default to a fast quality-gate flow that exists.
                "flow_name": "flow_idempotency_complete",
            },

            # ─ Admin: event emission policies PUT (idempotent — no-op flip) ─
            # Body uses fields from admin_health.py:1277 (dict body).
            # Setting current values keeps the row stable; the endpoint is
            # idempotent and emits EventEmissionPolicyUpdated either way.
            "/admin/event-emission-policies/{event_type}": {
                "emit_from_teg": False,
                "emit_from_registry": True,
                "skip_in_projection": False,
                "description": "API tester probe — idempotent no-op",
            },

            # ─ Agents/locations PUT (own location) ─
            "/agents/locations/me": {
                "latitude": 47.84,
                "longitude": 12.98,
                "location_label": "API Tester Default — Freilassing, Bavaria",
                "update_agents": False,
            },

            # ─ Agent builder generate-template ─
            # Verified schema (via 422): agent_did + client_id + template_id +
            # agent_name + human_readable_id. Synthetic placeholders → state-dep
            # 4xx caught by existing EF stamps.
            "/agent-builder/generate-template": {
                "template_id": "sovereign-marketplace",
                "agent_did": "AGENT_DID_PLACEHOLDER",
                "client_id": "agent-synthetic-template-probe",
                "agent_name": "API Tester Template Probe",
                "human_readable_id": "api-tester-probe-template",
                "description": "Auto-generated by API tester",
                "configuration": {},
            },

            # ─ Contracts cross-registry proxy ─
            # Verified schema: contract_id (int) + action ∈ {accept, submit} +
            # target_registry_url + upgrader_agent_did (for accept).
            "/contracts/cross-registry/proxy": {
                "contract_id": 1,
                "action": "accept",
                "upgrader_agent_did": "AGENT_DID_PLACEHOLDER",
                "method": "POST",
                "path": "/contracts/1/accept",
                "target_registry_url": "http://registry-test-b:8000",
                "body": None,
            },

            # ─ Achievements ─
            # Sandbox seeds no achievement_rewards rows by default → 404 unknown type.
            # We still POST a sensible body so the runner reaches the validator.
            "/achievements/record": {
                "achievement_type": "tutorial_agent_lifecycle",
                "metadata": {"completion_time_sec": 120},
            },
            # claim-pending requires `agent_did` per 422; supply our primary agent.
            "/achievements/claim-pending": {
                "agent_did": "AGENT_DID_PLACEHOLDER",
            },

            # ─ Operator applications + lifecycle ─
            "/operator-applications": {
                "name": "API Tester Synthetic Op",
                "email": "api-tester@test.sandbox",
                "organization": "API Tester",
                "deployment": "undecided",
                "experience": "beginner",
                "use_case": "Synthetic application created by automated API tester for coverage.",
                # required since §LEGALKIT: without it the route answers 422 on any frame that has no older row
                "accept_operator_terms": True,
            },
            "/operators/activate": {
                "activation_code": "synthetic-activation-code-test",
            },
            "/operators/request-revocation": {
                "reason": "API tester probe — synthetic revocation request.",
            },
            "/admin/operator-applications/{application_id}/approve": {
                "notes": "API tester probe approve — synthetic application.",
            },
            "/admin/operator-applications/{application_id}/reject": {
                "notes": "API tester probe reject — synthetic application.",
            },
            "/admin/operator-applications/{application_id}/revoke-operator": {
                "reason": "API tester probe revoke-operator — synthetic application.",
            },
            "/admin/operator-applications/{application_id}/suspend-operator": {
                "reason": "API tester probe suspend-operator — synthetic application.",
            },

            # ─ Support tickets (developer-facing) ─
            "/support/tickets": {
                "subject": "API Tester Probe Ticket",
                "category": "general",
                "message": "Synthetic ticket from automated API tester — please disregard.",
                "priority": "low",
            },
            "/support/tickets/{ticket_id}/reply": {
                "message": "API tester probe reply.",
            },

            # ── §APITEST 2026-09-04 — families that had NO body at all ──────────
            # The 2026-09-03 baseline answered 422 "Field required: body" on 32
            # rows across chat / liability / devices / flare-shop / fiat. Every
            # one of these bodies was PROBED against a live sandbox until it
            # stopped returning 422; the remaining status (200/403/404/409/503)
            # is a real observation the classifier can bucket. A 422 measures the
            # harness, not the endpoint.
            "/chat/conversations": {
                "kind": "dm",
                "target": {"ptype": "agent", "agent_did": "AGENT_DID_PLACEHOLDER"},
            },
            "/chat/conversations/{conversation_id}/messages": {
                "client_ref": "apitest-msg-1", "body": "API tester probe message.",
            },
            "/chat/conversations/{conversation_id}/read": {"seq": 1},
            "/chat/conversations/{conversation_id}/mute": {"muted": True},
            "/chat/conversations/{conversation_id}/ping": {"client_ref": "apitest-ping-1"},
            "/chat/conversations/{conversation_id}/retention": {"hours": 24},
            # action is an enum; 'mode' needs no target, 'kick' would need a member
            "/chat/conversations/{conversation_id}/room": {"action": "mode", "value": "open"},
            "/chat/conversations/{conversation_id}/support-reply": {"text": "API tester probe reply."},
            # §SUITES1018: an open ticket of the sweep's own developer (the ourchat_chat prereq); ticket 1 was nobody's
            "/chat/conversations/{conversation_id}/support-review": {"ticket_id": "__CHAT_TICKET_ID__"},
            # §SUITES1018: these two went out with no body (422, NOT MEASURED). The sweep's agent holds no APITEST, so the
            # certificate is refused by name before anything is minted; a service call runs only in a paid
            # agent_service thread, which the sweep never opens (it would move money), so its DM is refused first.
            "/chat/conversations/{conversation_id}/certificate": {"symbol": "APITEST", "client_ref": "apitest-cert-1"},
            "/chat/conversations/{conversation_id}/service-call": {"client_ref": "apitest-svc-0001"},
            # §SUITES1018 batch 6: the IRONKEY rows on the sweep's OWN agent (the agent_delegation prereq grants it the
            # owner switch authz.delegate and issues two short tokens; every caveat is fx.quote, a quote read).
            "/agents/act-token": {"act_as": "__ACT_AS__"},
            "/agents/capabilities": {"caveats": {"permissions": ["fx.quote"]}, "max_uses": 1, "ttl_seconds": 600},
            "/agents/capabilities/consume": {"token": "__CAP_TOKEN__", "amount": 0},
            "/agents/capabilities/{token_id}/attenuate": {"caveats": {"permissions": ["fx.quote"]}, "max_uses": 1,
                                                          "ttl_seconds": 300},
            "/agents/{did}/capabilities/issue-as-owner": {"caveats": {"permissions": ["fx.quote"]}, "max_uses": 1,
                                                          "ttl_seconds": 600},
            "/agents/{did}/delegations": {"principal_type": "dev", "principal_ref": "__DEV_PRINCIPAL__",
                                          "permissions": ["fx.quote"], "ttl_hours": 1},
            "/agents/spawn": {"name": "apitest-spawn", "permissions": ["fx.quote"], "ttl_seconds": 600, "max_uses": 1},
            # §SUITES1018 batch 6: writes on a guild order go to the well-formed order of nothing (gwo_apitest_none):
            # each route loads the order first and refuses (404 "Order not found") before anything else.
            "/guild/orders/{oid}/bids": {"price": 1.0, "eta_seconds": 3600, "pitch": "API tester probe bid"},
            "/guild/orders/{oid}/award": {"bid_id": 1},
            "/guild/orders/{oid}/submit": {"deliverable": {"text": "API tester probe deliverable"}},
            "/guild/orders/{oid}/verify": {"accept": False, "stars": 1, "feedback": "API tester probe"},
            # an eval run executes a whole suite against the agent; the sweep names no suite (refused before it runs)
            "/forge/evals/run": {"suite_id": 999999},
            # an announcement to the agent's underwriters (it moves nothing, mints no challenge)
            "/liability/intents": {"action_type": "contracts.milestone.release", "action_ref": "apitest-intent",
                                   "facts_preview": {"note": "API tester probe"}, "ttl": 60},
            # a fresh P-256 key on the sweep's OWN push device (generated per call)
            "/liability/devices/{device_id}/enroll-key": {"pubkey_jwk": "__P256_JWK__"},
            # §SUITES1018 batch 6: pure arithmetic over the active pricing (the route writes nothing)
            "/admin/fiat/pricing/simulate": {"purchases_eur": ["10.00", "25.00"], "starting_treasury_avt": "1000000",
                                             "starting_fee_collector_avt": "0"},
            # the sweep's own ticket (the support prereq): reopening an open one changes nothing; triage sets priority
            "/support/tickets/{ticket_id}/status": {"status": "open"},
            "/admin/support/tickets/{ticket_id}/triage": {"priority": "low"},
            # §SUITES1018 batch 6: clear the per-agent cosmetic overrides on the sweep's OWN agent (it holds none)
            "/fiat/flare/agent/{agent_did}/variant": {"variant": "__clear__"},
            "/fiat/flare/agent/{agent_did}/overlay": {"overlay": "__clear__"},
            "/fiat/flare/agent/{agent_did}/corner-variant": {"variant": "__clear__"},
            # __CONVERSATION_ID__ is replaced with the id captured from
            # POST /chat/conversations, so this acks a REAL thread.
            "/chat/inbox/ack": {"conversation_id": "__CONVERSATION_ID__", "seq": 1},
            "/chat/org-rooms/{org_id}/settings": {"chat_enabled": True, "chat_open_policy": "members"},
            "/chat/pulse/me": {"enabled": False, "show_agents": True, "note": ""},
            "/chat/contact-policy/me": {"policy": "open"},
            "/devices/register": {
                # platform is validated in code against ('android','ios','web')
                "platform": "web", "target": "apitest-device-token-2026", "label": "API tester",
            },
            "/devices/webpush/subscribe": {
                "endpoint": "https://example.test/push/apitest",
                # keys.p256dh + keys.auth are required by the handler, not the schema
                "keys": {
                    "p256dh": ("BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkr"
                               "xZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U"),
                    "auth": "tBHItJI5svbpez7KI4CCXg",
                },
            },
            "/assistant/ask": {"question": "What is my balance?"},
            "/flare-shop/purchase": {"tier": "supporter", "buyer_agent_did": "AGENT_DID_PLACEHOLDER"},
            "/fiat/flare/customize": {
                "agent_did": "AGENT_DID_PLACEHOLDER", "display_name": "API Tester",
                "tagline": "probe", "logo_url": "https://example.test/logo.png",
            },
            "/fiat/org-topup/checkout-session": {
                "org_id": "00000000-0000-4000-8000-000000000000",
                "eur_amount": "10.00", "agent_did": "AGENT_DID_PLACEHOLDER",
            },
            "/operator-portal/self-rename": {"display_name": "apitest-operator"},
            # §SUITES1018 batch 8 (part 3): the liability chain on the sweep's OWN mandate. __SWEEP_MANDATE__ is a mandate
            # the sweep's admin issued for the sweep's agent (base scope, a day long), __ADMIN_TOTP__ a code of the admin's
            # presence secret, re-keyed per code and never verified, so sign-in stays one factor (the router resolves
            # both). The rows sent "000000" and a mandate of nothing: EF on the presence gate, 404 on every mandate.
            "/liability/mandates": {
                "agent_did": "AGENT_DID_PLACEHOLDER", "scope": ["a2a.pay"], "tier": "T1", "expires_in_days": 1,
                "totp_code": "__ADMIN_TOTP__",
            },
            # an amount declares its unit and its counterparty (none), or the route refuses it 422 (I11)
            "/liability/previews": {
                "mandate_id": "__SWEEP_MANDATE__", "action_type": "contract.release",
                "facts": {"amount": "1.0", "currency": "AVT", "counterparty_did": None},
            },
            "/liability/challenges": {
                "mandate_id": "__SWEEP_MANDATE__",
                "action_type": "contract.release",
            },
            "/liability/mandates/{mid}/ceiling": {"scope": "a2a.pay", "max_per_tx": "1.0", "currency": "AVT"},
            "/liability/mandates/{mid}/revoke": {"reason": "apitest: the sweep's own mandate"},
            "/liability/challenges/{chid}/ack": {"surface": "desk", "locale": "en"},
            "/liability/challenges/{chid}/approve": {"totp_code": "__ADMIN_TOTP__"},
            "/liability/challenges/{chid}/deny": {"reason": "not_now"},
            # (a second enroll-key entry here, a fixed key, silently replaced batch 6's fresh key above: one key per
            # dict literal, the last wins. Removed in batch 8.)
            "/liability/devices/{device_id}/webauthn/register": {
                "attestation_object": "YXBpdGVzdA", "client_data_json": "eyJ0eXAiOiJhcGl0ZXN0In0",
            },
        }
    
    def get_body(self, path: str) -> Optional[Any]:
        """Get default request body for a path"""
        import time as _t
        _ts = int(_t.time())

        # §SUITES1018 (2026-10-18): the diagnostics bodies name THIS registry's own target, read at run time (the tester
        # runs inside the registry it sweeps). The literal "sandbox-a" named the retired tier: on sbx-alpha (whose own
        # target is "sandbox-alpha") POST /admin/diagnostics/run answered 404 "no matching targets".
        if path in ("/admin/diagnostics/run", "/admin/diagnostics/run-all") or path.startswith("/admin/diagnostics/actions/"):
            key = path if path in self._bodies else "/admin/diagnostics/actions/{action_id}"
            body = copy.deepcopy(self._bodies.get(key) or {})
            try:
                from agentvault_registry.services.diagnostics.targets import self_target
                me = self_target().get("operator_id")
            except Exception:  # noqa: BLE001 - no self target: the stored body stays, and the row says why
                me = None
            if me:
                if "targets" in body:
                    body["targets"] = [me]
                if "target" in body:
                    body["target"] = me
            return body

        # §SUITES1018 (2026-10-18): the peer-only writes. The tester now calls these AS a peer (auth_manager.
        # federation_spiffe_id), so each body here was read against its handler (routers/federation_sync.py,
        # exchange_federation.py, contract_federation.py, guild.py, agent_delegation_api.py, mail_relay.py,
        # chat_federation.py, federation_ballots.py) and names nothing real: the route refuses it before any side
        # effect, or (dry_run, a status read) acts read-only. NEVER replace one with a real object: canary-refill with
        # an empty body funds every canary sender from the treasury, ironhand-probe without a local source makes a real
        # transfer, mail-relay with a real template sends mail. base.PEER_WRITE_REFUSALS names the refusal each expects;
        # a peer write with no body here is not called at all (base: not measured).
        _peer_writes = {
            "/federation/canary-refill": {"dry_run": True},
            "/federation/canary-fire": {"remote_path_id": -1, "test_id": f"canary-apitest-{_ts}"},
            "/federation/ironhand-probe": {"source_did": "did:theprotocol:apitest-not-local",
                                           "target_did": "did:theprotocol:apitest-not-local-2"},
            "/federation/fx/parked-claim": {"route_id": "apitest-none-01", "router_did": "did:theprotocol:apitest-router"},
            "/federation/fx/parked-resolve": {"route_id": "apitest-none-01", "router_did": "did:theprotocol:apitest-router",
                                              "outcome": "released"},
            "/federation/agora-order": {"agent_did": "did:theprotocol:apitest-none", "listing": "APITESTNONE",
                                        "side": "buy", "qty": 1, "price": "1"},
            "/federation/agora-order-funded": {"order_id": "apitest-none"},
            "/federation/agora-order-status": {"agent_did": "did:theprotocol:apitest-none", "order_ids": ["apitest-none"]},
            "/federation/agora-certificate": {"agent_did": "did:theprotocol:apitest-none", "symbol": "APITESTNONE"},
            "/federation/agora-portfolio": {"agent_did": "did:theprotocol:apitest-none"},
            "/federation/contract-command": {"cid": "ctr_apitest_none", "action": "apitest.noop",
                                             "actor_did": "did:theprotocol:apitest-none"},
            "/federation/guild/orders/{oid}/bid": {"bidder_did": "did:theprotocol:apitest-none",
                                                   "home_registry_url": "https://not-a-peer.example", "price": 1},
            "/federation/guild/orders/{oid}/submit": {"worker_did": "did:theprotocol:apitest-none"},
            "/federation/guild/stake": {"order_id": "gwo_apitest_none", "bidder_did": "did:theprotocol:apitest-none",
                                        "action": "apitest", "host_registry": "https://not-a-peer.example"},
            "/federation/guild/work-credential": {"order_id": "gwo_apitest_none", "host_registry": "https://not-a-peer.example",
                                                  "worker_did": "did:theprotocol:apitest-none",
                                                  "poster_did": "did:theprotocol:apitest-none", "stars": 5, "credential": {}},
            "/federation/guild/notice": {"order_id": "gwo_apitest_none", "kind": "awarded",
                                         "worker_did": "did:theprotocol:apitest-none"},
            "/federation/ironkey/delegation-credential": {"credential_id": "apitest-none", "issuer_registry": "apitest-none",
                                                          "issuer_did": "did:theprotocol:apitest-none",
                                                          "delegate_did": "did:theprotocol:apitest-not-local",
                                                          "permissions": [], "credential": {}},
            # the caller's OWN peer name (the router substitutes it): a revoke naming another issuer is audited as one
            "/federation/ironkey/delegation-revoke": {"credential_id": "apitest-none",
                                                      "issuer_registry": "__PEER_FRAME_NAME__"},
            "/federation/mail-relay": {"template": "apitest-none", "recipient": "apitest@example.com",
                                       "username": "apitest", "token": "apitest-token"},
            "/federation/chat/deliver": {"v": 1, "host_registry": "https://not-a-peer.example"},
            "/federation/chat/state": {"conversation_ref": "apitest-none", "participant_key": "x@https://not-a-peer.example",
                                       "state": "active"},
            "/federation/chat/relay-send": {"conversation_ref": "apitest-none", "sender_key": "h@https://not-a-peer.example",
                                            "client_ref": "apitest-0001"},
            "/federation/governance/ballots": {"envelope": {}},
        }
        if path in _peer_writes:
            return copy.deepcopy(_peer_writes[path])

        # §SUITES1018 (2026-10-18): bodies the 2026-10-18 sweep sent none of (each row a 422 that never reached its
        # handler). Values that change are read at run time inside the registry the tester sweeps.
        # §SUITES1018 batch 7: three more the V0624 sweep sent none of, each read against its handler first.
        # A quote moves no funds (routers/teg_integration.fx_quote); the receiver is one on a peer frame with another
        # unit where the frame has one, else the sweep's local counterparty (rate 1.0, same currency).
        if path == "/teg/fx/quote":
            return {"receiver_did": "__FX_RECEIVER_DID__", "amount": "1"}
        # a read-only relay to the peer frame's market, scoped to the sweep's agent (routers/exchange.passport_order_status)
        if path == "/agora/passport/order-status":
            return {"venue_registry": "__PEER_FRAME_NAME__", "order_ids": ["apitest-none"]}
        # the policy editor's replay: a scratch module, always deleted (routers/admin_opa.opa_simulate). Its package is
        # the sweep's own, never a real one: OPA joins every module of one package, and system.* is refused outright.
        if path == "/admin/opa/simulate":
            return {"rego": "package apitest_sweep_simulation\n\ndefault allow := false\n",
                    "rule_path": "apitest_sweep_simulation/allow", "limit": 5}
        # the sweep agent's own schedule (an upsert per agent and circuit, routers/attestations.create_or_upsert_schedule):
        # an active circuit, the longest interval; the DELETE row disables the same one (routers/admin_api_test
        # ._SWEEP_SCHEDULE)
        if path == "/attestations/schedules":
            return {"circuit_id": "fairMarkupPolicy/v2.0.0", "interval_hours": 720}
        # one role the sweep's agent holds from birth: an active grant is left exactly as it is and the route answers
        # changed: false (routers/agent_authz_api.add_agent_role), so the grant path is measured and nothing changes
        if path == "/agents/{did}/authz/roles":
            return {"role": "client"}
        if path == "/legal/accept":   # the version served NOW: a stale one is refused by design (409)
            try:
                from agentvault_registry.core.legal_versions import current_version
                return {"document": "terms", "version": current_version("terms") or ""}
            except Exception:  # noqa: BLE001
                return {"document": "terms", "version": ""}
        if path == "/public/reach-probe":   # this frame's own public name: the probe answers without dialling itself
            import os as _os
            return {"public_name": (_os.environ.get("SPIRE_TRUST_DOMAIN") or "example.org").strip()}
        if path == "/public/directory/graphql":   # the console's own agent search, three rows
            return {"query": "query($n: Int!) { agents(first: $n) { total edges { did name } } }",
                    "variables": {"n": 3}}
        if path == "/developers/me/agents/{did}/reputation-bond":   # the sweep's agent bonds itself (the self door)
            return {"funder_did": "__AGENT_DID__"}
        if path == "/admin/mcp-tester/emissions-via-target":   # the MCP tester's own read: the last ten minutes' transfers
            from datetime import timedelta as _td
            return {"since": (datetime.now(timezone.utc) - _td(minutes=10)).isoformat(), "dids": [],
                    "expect_types": ["TokensTransferred"], "flow_name": "api-tester"}

        # Special handling for organization POST - unique name each time
        if path == "/organizations":
            body = copy.deepcopy(self._bodies.get(path, {}))
            body["name"] = f"Test Organization {_ts}"
            return body

        # Special handling for organization team POST - unique name
        if "/teams" in path and path.endswith("/teams") and "{org_id}" in path:
            body = copy.deepcopy(self._bodies.get("/organizations/{org_id}/teams", {}))
            body["name"] = f"Test Team {_ts}"
            return body

        # Special handling for CI/CD pipeline POST - unique name
        if path.endswith("/pipelines") and "{agent_did}" in path and "/pipelines/" not in path:
            body = copy.deepcopy(self._bodies.get("/agents/{agent_did}/pipelines", {}))
            body["pipeline_name"] = f"test-pipeline-{_ts}"
            return body

        # Special handling for pipeline template POST - unique name
        if path == "/pipeline-templates":
            body = copy.deepcopy(self._bodies.get(path, {}))
            body["name"] = f"Test Template {_ts}"
            return body

        # Slash-request settlement_id must be unique per call (UNIQUE PK constraint
        # on cross_registry_settlements.id). Body massager generates a fresh UUIDv4
        # suffix; defendant_did is filled later by the FORCE handler in admin_api_test.py.
        if path == "/federation/disputes/slash-request":
            import uuid as _uuid
            body = copy.deepcopy(self._bodies.get(path, {}))
            body["settlement_id"] = f"test-settlement-{_uuid.uuid4().hex[:12]}"
            return body

        # Phase E (2026-05-07): /admin/federation/licenses/generate must use a
        # unique operator_did per call to avoid 409 collision with prior runs.
        if path == "/admin/federation/licenses/generate":
            import uuid as _uuid
            body = copy.deepcopy(self._bodies.get(path, {}))
            body["operator_did"] = f"did:theprotocol:api-tester-{_uuid.uuid4().hex[:12]}"
            body["operator_name"] = f"API Tester Synthetic Op {_ts}"
            return body

        # OAuth federation trust POST — unique registry_url per call to avoid 409
        # collision with prior runs that registered the same URL. The DELETE handler
        # below uses DYNAMIC_VALUES["test_trust_registry_url"] populated by the BFF
        # FORCE handler (admin_api_test.py:_setup_oauth_federation_trust_test).
        if path == "/oauth/federation/trust":
            body = copy.deepcopy(self._bodies.get(path, {}))
            _ts_ms = int(_t.time() * 1000)
            unique_url = f"https://test-peer-{_ts_ms}.example.com"
            body["registry_name"] = f"Test Peer Registry {_ts_ms}"
            body["registry_url"] = unique_url
            body["teg_url"] = f"{unique_url}/teg"
            body["public_key_url"] = f"{unique_url}/oauth/.well-known/jwks.json"
            # Persist for DELETE: caller can read DYNAMIC_VALUES["last_trusted_registry_url"]
            try:
                from agentvault_registry.routers.admin_api_test import DYNAMIC_VALUES as _DV
                _DV["last_trusted_registry_url"] = unique_url
            except Exception:
                pass  # if BFF context not loaded, no-op
            return body

        # Special handling for bulk export - use actual agent DID
        if path == "/agents/export/bulk":
            body = copy.deepcopy(self._bodies.get(path, {}))
            if self._sandbox_mode:
                body["agent_dids"] = [getattr(self, '_agent_did', 'AGENT_NOT_ONBOARDED')]
            return body

        # Special handling for agent card POST - unique humanReadableId each time
        if path == "/agent-cards/" or path == "/agent-cards":
            body = self._bodies.get("/agent-cards/")
            if body:
                body = copy.deepcopy(body)
                body["card_data"]["humanReadableId"] = f"test-agent-card-{_ts}"
                return body

        # Special handling for onboard/create_agent - unique humanReadableId
        if path == "/onboard/create_agent":
            body = self._bodies.get(path)
            if body:
                body = copy.deepcopy(body)
                body["agent_card"]["humanReadableId"] = f"test-onboard-agent-{_ts}"
                return body

        # Special handling for TEG policy POST - unique policy_code to avoid 409
        if path == "/teg/policies":
            body = copy.deepcopy(self._bodies.get(path, {}))
            body["policy_code"] = f"GOV_POLICY_{_ts}"
            return body

        # Special handling for TEG batch policies - unique codes
        if path == "/teg/policies/batch":
            body = copy.deepcopy(self._bodies.get(path, {}))
            if body.get("policies"):
                for i, p in enumerate(body["policies"]):
                    p["policy_code"] = f"BATCH_POLICY_{_ts}_{i}"
            return body

        # Special handling for federation peer POST - unique name/url
        if path == "/federation/peers/" and not self._matches_pattern(path, "/federation/peers/{peer_id}"):
            body = copy.deepcopy(self._bodies.get(path, {}))
            body["name"] = f"Test Federation Peer {_ts}"
            body["base_url"] = f"http://localhost:{9000 + (_ts % 1000)}"
            return body

        # Special handling for register endpoint - generate unique data
        if path == "/auth/register":
            timestamp = int(datetime.now().timestamp())
            self._last_registered = {
                "name": f"Test User {timestamp}",
                "email": f"test{timestamp}@example.com",
                "password": "TestPass123!",
                "organization": "Test Organization"
            }
            return self._last_registered
        
        # Special handling for login - sandbox mode always uses sandbox creds
        elif path == "/auth/login":
            if self._sandbox_mode:
                return {
                    "username": "admin@test.sandbox",
                    "password": SANDBOX_ADMIN_PASSWORD
                }
            elif self._last_registered:
                return {
                    "username": self._last_registered["email"],
                    "password": self._last_registered["password"]
                }
            else:
                return {
                    "username": "auditor@theprotocol.cloud",
                    "password": "AuditorPass123!"
                }
        
        # Special handling for recovery
        elif path == "/auth/recover-account":
            if self._last_registered:
                email = self._last_registered["email"]
            elif self._sandbox_mode:
                email = "admin@test.sandbox"
            else:
                email = "auditor@theprotocol.cloud"
            return {
                "email": email,
                "recovery_key": "recovery_key_here"
            }
        
        # Direct match
        if path in self._bodies:
            return self._bodies[path]
        
        # Pattern matching for paths with parameters
        for pattern, body in self._bodies.items():
            if self._matches_pattern(path, pattern):
                return body
        
        return None
    
    def _matches_pattern(self, path: str, pattern: str) -> bool:
        """Check if a path matches a pattern with parameters"""
        # Simple pattern matching for paths with {param}
        pattern_parts = pattern.split('/')
        path_parts = path.split('/')
        
        if len(pattern_parts) != len(path_parts):
            return False
        
        for i, (pattern_part, path_part) in enumerate(zip(pattern_parts, path_parts)):
            if pattern_part.startswith('{') and pattern_part.endswith('}'):
                # This is a parameter, so any value matches
                continue
            elif pattern_part != path_part:
                return False
        
        return True
    
    def get_all_bodies(self) -> Dict[str, Any]:
        """Get all request bodies"""
        return self._bodies.copy()
    
    def has_body(self, path: str) -> bool:
        """Check if a path has a default body"""
        return self.get_body(path) is not None
    
    def is_form_data(self, path: str) -> bool:
        """Check if endpoint expects form data instead of JSON"""
        # OAuth2 endpoints use form-encoded data
        form_data_paths = [
            "/auth/agent/token",  # OAuth2 token endpoint
            "/auth/login",       # Also uses form data
            # PD (2026-04-22 Pass 2): /oauth/token/exchange removed — its router
            # actually uses a Pydantic BaseModel (TokenExchangeRequest), not Form(...)
            # fields. Sending form-data → 422 "Input should be a valid dictionary".
            # Only /oauth/introspect uses Form(...) params.
            "/oauth/introspect",      # OWL31: RFC 7662 token introspection (Form)
            "/oauth/revoke",          # §SUITES1018 batch 8: RFC 7009 revocation (Form, like introspection)
        ]
        
        for form_path in form_data_paths:
            if self._matches_pattern(path, form_path):
                return True
        
        return False


# Create singleton instance
request_bodies = RequestBodies()
