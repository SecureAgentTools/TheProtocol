// EXACT COPY of test logic from ApiTester_VisImp.vue
// DO NOT MODIFY - This preserves the 188/188 passing tests

import { ref } from 'vue'
import { apiClient } from '@/services/api/client'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('ApiTester')

// Form-data endpoints that need special handling
const FORM_DATA_ENDPOINTS = ['/auth/login', '/auth/agent/token']

// Default request bodies for POST/PUT endpoints - EXACT COPY
const DEFAULT_BODIES: Record<string, any> = {
  // Auth endpoints - FIXED based on Phoenix tests
  "/auth/login": {
    "username": "user@example.com",
    "password": "TestPass123!"
  },
  "/auth/register": {
    "name": "Test User",
    "email": "testuser@example.com",
    "password": "TestPass123!",
    "organization": "Test Organization"
  },
  "/auth/agent/token": {
    "username": "client_id",
    "password": "client_secret"
  },
  "/auth/recover-account": {
    "email": "user@example.com",
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
  "/auth/api-keys": "My API Key",  // Just a string, not object
  "/auth/generate-api-key": {
    "description": "API Key for testing"
  },
  
  // Agent endpoints
  "/agents/heartbeat": {
    "status": "active",
    "metrics": {
      "cpu": 50,
      "memory": 1024
    }
  },
  
  // Agent Builder
  "/agent-builder/generate": {
    "name": "Test Agent",
    "description": "Test agent description",
    "type": "service",
    "capabilities": [],
    "configuration": {}
  },
  
  // Agent Cards - with all required fields
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
        "text-generation": {
          "description": "Can generate text"
        }
      },
      "authSchemes": {
        "oauth2": {
          "authorizationUrl": "https://example.com/auth",
          "tokenUrl": "https://example.com/token"
        }
      },
      "metadata": {}
    }
  },
  
  // Agent Logs - FIXED path
  "/agents/{agent_did}/logs": {
    "level": "INFO",
    "message": "Test log message",
    "source": "test_script",
    "metadata": {}
  },
  
  // Contracts
  "/contracts/": {
    "name": "Test Contract",
    "description": "Test contract description",
    "template_id": "basic-service",
    "parties": []
  },
  "/contracts/{contract_id}/accept": {
    "upgrader_agent_did": "did:cos:fbf7393c-f3c1-ee05-7eb7"
  },
  "/contracts/{contract_id}/submit": {
    "pr_url": "https://github.com/test/repo/pull/1"
  },
  "/contracts/{contract_id}/approve-completion": {},
  "/contracts/malpractice": {
    "contract_id": "contract_123",
    "reason": "Service not delivered"
  },
  
  // Governance
  "/governance/proposals": {
    "title": "Test Proposal",
    "description": "Test proposal description",
    "proposal_type": "parameter_change",
    "parameters": {}
  },
  "/governance/proposals/{proposal_id}/vote": {
    "vote": "yes",  // lowercase: yes, no, abstain
    "reason": "Vote reason"
  },
  "/governance/proposals/{proposal_id}/tally": {},
  
  // Staking - Basic
  "/staking/stake": {
    "amount": "100"  // String format for amount
  },
  "/staking/unstake": {
    "amount": "50"  // String format for amount
  },
  
  // CRITICAL - Staking Enhanced (USERS CAN'T CLAIM REWARDS WITHOUT THIS!)
  "/staking/claim-rewards": {},  // Empty body - THIS IS THE MISSING FEATURE!
  
  // Reputation Signal - NEW
  "/token/{transaction_id}/reputation-signal": {
    "signal_value": 1,  // Must be +1 or -1
    "reason": "Excellent service delivery"
  },
  
  // TEG Advanced Transactions - NEW
  "/teg/batch-transfer": {
    "transfers": [
      {"to": "did:cos:recipient1", "amount": "100"},
      {"to": "did:cos:recipient2", "amount": "200"}
    ]
  },
  
  // Organizations - Working endpoints!
  "/organizations": {
    "name": "Test Organization",
    "description": "Organization for testing",
    "type": "company"
  },
  "/organizations/{org_id}": {
    "name": "Updated Organization",
    "description": "Updated description"
  },
  "/organizations/{org_id}/teams": {
    "name": "Development Team",
    "description": "Team for development"
  },
  "/organizations/{org_id}/teams/{team_id}": {
    "name": "Updated Team Name",
    "description": "Updated team description"
  },
  "/organizations/{org_id}/invite": {
    "email": "member@example.com",
    "role": "member"
  },
  "/organizations/{org_id}/teams/{team_id}/members": {
    "developer_id": 1,
    "role": "member"
  },
  
  // Agent Export/Import - Working endpoints!
  "/agents/export/bulk": {
    "agent_dids": ["did:cos:agent1", "did:cos:agent2"],
    "include_credentials": true
  },
  "/agents/import": {
    "export_data": {},
    "override_existing": false
  },
  "/agents/import/validate": {
    "export_data": {}
  },
  "/agents/{agent_did}/clone": {
    "new_name": "Cloned Agent",
    "new_description": "Cloned from original agent"
  },
  
  // Agent CI/CD - Working endpoints!
  "/agents/{agent_did}/pipelines": {
    "pipeline_name": "Test Pipeline",
    "pipeline_config": {
      "stages": [
        {"name": "test", "steps": [{"command": "pytest tests/"}]},
        {"name": "build", "steps": [{"command": "docker build -t agent:latest ."}]},
        {"name": "deploy", "steps": [{"command": "docker push agent:latest"}]}
      ]
    },
    "trigger_type": "push"
  },
  "/agents/{agent_did}/pipelines/{pipeline_id}": {
    "pipeline_name": "Updated Pipeline",
    "pipeline_config": {
      "stages": [
        {"name": "test", "steps": [{"command": "pytest tests/"}]},
        {"name": "build", "steps": [{"command": "docker build -t agent:latest ."}]},
        {"name": "deploy", "steps": [{"command": "docker push agent:latest"}]},
        {"name": "monitor", "steps": [{"command": "curl health-check"}]}
      ]
    },
    "trigger_type": "push"
  },
  "/agents/{agent_did}/versions": {
    "version": "1.0.0",
    "description": "Initial version",
    "changes": ["Initial release"]
  },
  "/agents/{agent_did}/versions/{version_id}/activate": {},
  "/agents/{agent_did}/versions/{version_id}/rollback": {},
  "/agents/{agent_did}/deployments": {
    "version_id": "v1",
    "environment": "production"
  },
  "/agents/{agent_did}/deployments/{deployment_id}/status": {
    "status": "completed",
    "message": "Deployment successful"
  },
  "/agents/{agent_did}/deployments/{deployment_id}/logs": {
    "log_entry": "Deployment step completed",
    "timestamp": "2025-01-30T12:00:00Z"
  },
  "/pipeline-templates": {
    "name": "Standard CI/CD Template",
    "description": "Basic CI/CD pipeline template",
    "config": {
      "stages": ["build", "test", "deploy"]
    }
  },
  "/pipeline-templates/{template_id}/purchase": {
    "payment_method": "tokens"
  },
  
  // Two-Factor Authentication - Working endpoints!
  // D6-782: a 2FA change asks for the password of the account signed in here; the tester fills it in. These two
  // templates carried a real account's password (the sandbox admin's, rotated 2026-08-08) until then.
  "/auth/2fa/setup": {
    "password": "YOUR_CURRENT_PASSWORD"
  },
  "/auth/2fa/verify": {
    "code": "123456"
  },
  "/auth/2fa/disable": {
    "password": "CurrentPassword123!"
  },
  "/auth/2fa/validate": {
    "partial_token": "000000",
    "code": "000000"
  },
  "/auth/2fa/recover": {
    "partial_token": "000000",
    "backup_code": "BACKUP-CODE-001"
  },
  "/auth/2fa/backup-codes": {
    "password": "YOUR_CURRENT_PASSWORD",
    "current_code": "000000"
  },
  
  // Staking Rewards Distribution
  "/staking/rewards/distribute": {
    "distribution_type": "automatic",
    "threshold": "1000"
  },
  
  // Enhanced Disputes - NEW
  "/disputes/enhanced/log": {
    "defendant_agent_id": "did:cos:defendant",
    "reason_code": "SERVICE_FAILURE",
    "brief_description": "Service not delivered as promised"
  },
  

  
  // Attestations - correct structure
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
  
  // Federation - FIXED paths
  "/admin/federation/peers/{peer_id}/approve": {},
  "/admin/federation/peers/{peer_id}/deactivate": {},
  "/federation/peers/": {
    "name": "Test Peer Registry",
    "base_url": "https://peer-registry.example.com",
    "admin_contact_email": "admin@peer-registry.com",
    "discovery_auth_info": {
      "type": "api_key",
      "api_key": "test-api-key",
      "api_key_header_name": "X-API-Key"
    }
  },
  "/internal/federation/query": {
    "search": "test",
    "tags": ["service", "agent"],
    "limit": 10
  },
  "/federation/sync-request": {
    "source_registry": "spiffe://agentvault.com/service/registry-test-b",
    "agent_cards": [],
    "sync_timestamp": "2026-02-27T00:00:00Z"
  },
  
  // TEG Integration - fixed field names
  "/teg/transfer": {
    "receiver_agent_id": "did:cos:fbf7393c-f3c1-ee05-7eb7",
    "amount": "100",
    "currency": "AVT"
  },
  "/teg/system-transfer": {
    "from_did": "did:theprotocol:teg_system_treasury",
    "to_did": "did:cos:fbf7393c-f3c1-ee05-7eb7",
    "amount": "1000",
    "reason": "Test system transfer"
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
        "require_kyc": true
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
  
  // Disputes
  "/disputes/": {
    "defendant_did": "did:cos:fbf7393c-f3c1-ee05-7eb7",
    "dispute_type": "SERVICE",
    "description": "Test dispute"
  },
  "/disputes/{dispute_id}/evidence": {
    "submitter_did": "did:cos:fbf7393c-f3c1-ee05-7eb7",
    "evidence_data": {
      "type": "text",
      "content": "Test evidence"
    }
  },

  
  // Admin
  "/admin/disputes/{dispute_id}/ruling": {
    "ruling": "IN_FAVOR_OF_COMPLAINANT",
    "notes": "Valid complaint - ruled in favor of complainant"
  },
  "/admin/health-check": {
    "developer_token": "PLACEHOLDER_DEV_TOKEN",
    "agent_token": "PLACEHOLDER_AGENT_TOKEN"
  },
  "/admin/api-test/test-endpoint": {
    "method": "GET",
    "path": "/health",
    "headers": {},
    "body": null
  },
  "/admin/api-test/test-category": {
    "category": "auth",
    "developer_token": null,
    "agent_token": null
  },
  
  // Developers
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
  
  // Onboarding - FIXED paths and bodies
  "/onboard/bootstrap/request-token": {},  // Empty body for verified developers
  "/onboard/register": {
    "bootstrap_token": "bst_123456",
    "agent_name": "Test Agent",
    "agent_type": "service",
    "agent_description": "Test agent for onboarding"
  },
  "/onboard/create_agent": {
    "bootstrap_token": "bst_123456",
    "name": "Test Agent",
    "description": "Test agent",
    "humanReadableId": "test-agent",
    "capabilities": {}
  },

  
  // Utils
  "/utils/validate-card": {
    "card_data": {
      "name": "Test Card",
      "description": "Test card for validation",
      "humanReadableId": "test-validation-card"
    }
  },

  "/teg/transactions/batch": {
    "transactions": []
  }
}

// Known Expected Failures — canonical list shared between Display and Container.
// Paths must match endpoint.path exactly as returned by GET /admin/api-test/endpoints.
export const KNOWN_EF_ENDPOINTS = new Set([
  'GET /agent-cards/id/{human_readable_id:path}',
  'POST /auth/2fa/setup',
  'PUT /federation/peers/{peer_id}',
  'POST /oauth/token/exchange',
  'POST /oauth/introspect',
  'DELETE /oauth/federation/trust/{registry_url}',
  'POST /teg/attestations/submit',
])

export interface Endpoint {
  method: string
  path: string
  auth: string
  description: string
  testing?: boolean
  result?: any
  showResponse?: boolean
  showRequest?: boolean
  requestBody?: string
}

export class ApiTestEngine {
  endpointsData = ref<Record<string, Endpoint[]>>({})
  
  async loadEndpoints() {
    const response = await apiClient.get('/admin/api-test/endpoints')
    this.endpointsData.value = response.data.endpoints || {}
    
    // Debug: Log all categories to find missing ones
    import.meta.env.DEV && console.log('ALL CATEGORIES FROM BACKEND:', Object.keys(this.endpointsData.value))
    import.meta.env.DEV && console.log('TOTAL CATEGORIES:', Object.keys(this.endpointsData.value).length)
    let totalEndpoints = 0
    Object.entries(this.endpointsData.value).forEach(([cat, endpoints]: [string, any]) => {
      import.meta.env.DEV && console.log(`${cat}: ${endpoints.length} endpoints`)
      totalEndpoints += endpoints.length
    })
    import.meta.env.DEV && console.log('TOTAL ENDPOINTS:', totalEndpoints)
    
    return this.endpointsData.value
  }
  
  async testEndpoint(endpoint: Endpoint, developerToken: string, agentToken: string, silent = false) {
    endpoint.testing = true
    endpoint.result = null
    
    try {
      // Prepare request body
      let requestBody = null
      if (endpoint.requestBody) {
        try {
          requestBody = JSON.parse(endpoint.requestBody)
          
          // Special handling for health-check endpoint - replace token placeholders
          if (endpoint.path === '/admin/health-check' && requestBody) {
            if (requestBody.developer_token === 'PLACEHOLDER_DEV_TOKEN') {
              requestBody.developer_token = developerToken || undefined
            }
            if (requestBody.agent_token === 'PLACEHOLDER_AGENT_TOKEN') {
              requestBody.agent_token = agentToken || undefined
            }
          }
        } catch (e) {
          endpoint.testing = false
          throw new Error('Invalid JSON in request body')
        }
      }
      
      // Check if form-data endpoint
      const isFormData = FORM_DATA_ENDPOINTS.some(path => 
        endpoint.path.includes(path.split('{')[0])
      )
      
      // Call the backend test endpoint
      const requestData = {
        method: endpoint.method,
        path: endpoint.path,
        body: requestBody,
        isFormData,  // Add flag to indicate form-data
        developer_token: developerToken || undefined,
        agent_token: agentToken || undefined
      }
      
      // Use very long timeout for all test endpoints on slow systems
      // Health check gets extra time since it tests multiple endpoints internally
      const timeout = endpoint.path === '/admin/health-check' ? 600000 : 300000  // 10 min for health, 5 min for others
      const config = { timeout }
      
      // §MCPTEST-FE 2026-08-07 — TRANSPORT RETRY.
      // MEASURED: this browser runs on the Docker host, and Chrome aborts
      // in-flight requests with net::ERR_NETWORK_CHANGED whenever it sees the
      // host's interfaces move (330 containers, veth churn). nginx logs those
      // as 499 (client closed). axios surfaces them as "Network Error" with NO
      // response — 33 of 44 rows in one run. That is a fact about the wire,
      // not about the endpoint, and recording it as a failure is the same lie
      // as the stale-token EF stamps. A response never received is not a
      // measurement: retry it, and if it still never arrives, say UNMEASURED.
      let response: any = null
      let lastErr: any = null
      for (let attempt = 0; attempt < 4; attempt++) {
        try {
          response = await apiClient.post('/admin/api-test/test-endpoint', requestData, config)
          lastErr = null
          break
        } catch (err: any) {
          lastErr = err
          // Only transport failures are retried. A real HTTP response — any
          // status — is a genuine observation and must be kept as-is.
          if (err?.response) break
          await new Promise(r => setTimeout(r, 1500 * (attempt + 1)))
        }
      }
      if (lastErr) throw lastErr

      endpoint.result = response.data
      return endpoint.result
    } catch (error: any) {
      const noResponse = !error?.response
      endpoint.result = {
        healthy: false,
        error: error.message,
        statusCode: error.response?.status,
        // Distinguishes "the endpoint answered badly" from "we never reached
        // it". Unmeasured rows are excluded from the real pass rate instead of
        // being counted against the endpoint.
        transport_error: noResponse,
        unmeasured: noResponse,
      }
      throw error
    } finally {
      endpoint.testing = false
    }
  }
  
  // P8.28: Category execution order — sequential phases prevent DYNAMIC_VALUES races and server starvation
  static CATEGORY_EXECUTION_ORDER: string[] = [
    // Phase 1: Foundation — auth + onboarding (tokens, bootstrap)
    'auth', 'auth_2fa', 'auth_secure', 'onboarding',
    // Phase 2: Core resources — agents, cards, orgs (creates entities other phases depend on)
    'agents', 'agent_cards', 'agent_discovery', 'agents_export_import', 'organizations',
    // Phase 3: Token economics — TEG, staking, tokenomics (depends on funded agents)
    'teg_integration', 'teg_transactions', 'teg_summary_enhanced',
    'staking_enhanced', 'staking_rewards', 'enhanced_tokenomics',
    // Phase 4: Operations — governance, contracts, reputation (depends on staking/funding)
    'governance', 'contracts', 'disputes', 'disputes_enhanced',
    'reputation_signal', 'attestations',
    // Phase 5: CI/CD + agent ops (depends on agents existing)
    'agent_cicd', 'agent_logs', 'agent_builder',
    // Phase 6: Federation + OAuth (independent infrastructure)
    'federation_peers', 'federation_public', 'federation_query',
    'federation_disputes', 'federation_sync', 'oauth_federation',
    'teg_integration_jwt_svid', 'teg_integration_mtls', 'teg_integration_oauth',
    // Phase 7: Admin, system, misc
    'admin', 'admin_api_test', 'admin_federation', 'admin_health',
    'developers', 'metrics', 'system', 'utils', 'websocket',
  ]

  // P8.28: Throttled category execution — max N concurrent requests within a category
  async testCategoryThrottled(endpoints: Endpoint[], developerToken: string, agentToken: string, concurrency = 5) {
    // Initialize request bodies
    endpoints.forEach(endpoint => {
      if (this.shouldShowRequestBody(endpoint) && !endpoint.requestBody) {
        const defaultBody = this.findDefaultBody(endpoint.path)
        if (defaultBody) {
          endpoint.requestBody = JSON.stringify(defaultBody, null, 2)
        }
      }
    })

    // Semaphore-style throttled execution
    const queue = [...endpoints]
    const running: Promise<void>[] = []

    while (queue.length > 0 || running.length > 0) {
      // Fill up to concurrency limit
      while (queue.length > 0 && running.length < concurrency) {
        const ep = queue.shift()!
        const p = this.testEndpoint(ep, developerToken, agentToken, true)
          .catch(() => {}) // swallow individual failures
          .then(() => { running.splice(running.indexOf(p), 1) })
        running.push(p)
      }
      // Wait for at least one to finish before filling again
      if (running.length > 0) {
        await Promise.race(running)
      }
    }
  }

  async testCategory(category: string, endpoints: Endpoint[], developerToken: string, agentToken: string) {
    // P8.28: Throttled — max 5 concurrent within category
    await this.testCategoryThrottled(endpoints, developerToken, agentToken, 5)

    const total = endpoints.length
    const healthy = endpoints.filter(ep => ep.result?.healthy).length

    return { total, healthy }
  }

  async runAllTests(developerToken: string, agentToken: string) {
    // 2026-04-25 — REVERTED to strict sequential. Earlier this session I
    // tried per-category concurrency=4 + parallel phases 6/7 — that hit 38
    // failed (was 21) because ~30 concurrent requests starved the 4-worker
    // backend, causing timeouts and 429 rate-limits, and reputation/agent_cicd
    // background tasks raced. The user explicitly warned this would happen.
    // Going back to sequential is the safe baseline. Speed will come from
    // backend-side optimizations (caching, eager bootstrap) instead.
    try {
      await apiClient.post('/admin/api-test/reset-flow-values')
      log.info('Backend flow values + category prereqs reset for fresh run')
    } catch (e) {
      log.warn('Reset failed, continuing anyway:', e)
    }

    const t0 = performance.now()
    const order = ApiTestEngine.CATEGORY_EXECUTION_ORDER
    const allCategories = Object.keys(this.endpointsData.value)
    const INTRA_CATEGORY_CONCURRENCY = 1  // strict sequential — see header note

    // One archive run per sweep; published after every category so the run is
    // visible while it happens and survives this browser session.
    this.currentRunId = new Date().toISOString().replace(/[:.]/g, '-').replace('Z', 'Z')

    for (const cat of order) {
      const endpoints = this.endpointsData.value[cat]
      if (endpoints && endpoints.length > 0) {
        import.meta.env.DEV && console.log(`Running '${cat}' (${endpoints.length} endpoints)`)
        await this.testCategoryThrottled(endpoints, developerToken, agentToken, INTRA_CATEGORY_CONCURRENCY)
        await this.publishRun('running')
      }
    }

    const orderedSet = new Set(order)
    for (const cat of allCategories) {
      if (!orderedSet.has(cat)) {
        const endpoints = this.endpointsData.value[cat]
        if (endpoints && endpoints.length > 0) {
          import.meta.env.DEV && console.log(`Running unordered '${cat}' (${endpoints.length} endpoints)`)
          await this.testCategoryThrottled(endpoints, developerToken, agentToken, INTRA_CATEGORY_CONCURRENCY)
          await this.publishRun('running')
        }
      }
    }

    const elapsedSec = ((performance.now() - t0) / 1000).toFixed(1)
    import.meta.env.DEV && console.log(`Run All Tests complete in ${elapsedSec}s`)
    await this.publishRun('complete', Number(elapsedSec))
  }

  // ─── §MCPTEST-FE 2026-08-07: run persistence ──────────────────────────
  // The sweep runs in THIS browser. Before this, closing the tab destroyed the
  // result set — a full run was invisible to anyone who did not personally sit
  // through it. Now every category publishes to the server archive, so the run
  // is watchable live from any other browser and survives the session.
  currentRunId: string | null = null

  private flatResults(): any[] {
    const out: any[] = []
    for (const [category, endpoints] of Object.entries(this.endpointsData.value || {})) {
      for (const ep of (endpoints as Endpoint[])) {
        if (!ep?.result) continue
        const r: any = ep.result
        out.push({
          method: ep.method,
          path: ep.path,
          category,
          auth_type: (ep as any).auth_type ?? null,
          healthy: r.healthy === true,
          expected_failure: r.expected_failure === true,
          bucket: r.bucket ?? null,
          ef_reason: r.ef_reason ?? r.expected_failure_reason ?? null,
          status_code: r.status_code ?? r.statusCode ?? null,
          responseTime: r.responseTime ?? r.response_time ?? null,
          error: r.error ?? null,
          unmeasured: r.unmeasured === true,
          not_measured: r.not_measured === true,
          not_measured_reason: r.not_measured_reason ?? null,
          transport_error: r.transport_error === true,
          synthesized_body: r.synthesized_body === true,
          principal_retry: r.principal_retry ?? null,
        })
      }
    }
    return out
  }

  runSummary(): Record<string, any> {
    const rows = this.flatResults()
    // EF is counted BEFORE healthy: the contract layer marks an expected
    // failure as healthy:true, so counting healthy first silently inflates the
    // pass rate. That exact confusion produced a false "100% pass" report.
    // A row we never got a response for measured NOTHING — it belongs in its
    // own bucket, not against the endpoint.
    // §SUITES1018: a row the server did not call (a destructive or cross-frame action, a manual-only route) is
    // NOT MEASURED, with its reason; it is unmeasured too, so it stays out of the rate, and counted on its own.
    const notMeasured = rows.filter(r => r.not_measured).length
    const unmeasured = rows.filter(r => r.unmeasured && !r.not_measured).length
    const scored = rows.filter(r => !r.unmeasured && !r.not_measured)
    const ef = scored.filter(r => r.expected_failure).length
    const passed = scored.filter(r => !r.expected_failure && r.healthy).length
    const failed = scored.filter(r => !r.expected_failure && !r.healthy).length
    return {
      total_measured: scored.length,
      total_rows: rows.length,
      unmeasured,
      not_measured: notMeasured,
      passed,
      failed,
      expected_failures: ef,
      real_pass_rate: (passed + failed) > 0
        ? Number(((passed / (passed + failed)) * 100).toFixed(2)) : 0,
      ef_rate: scored.length > 0 ? Number(((ef / scored.length) * 100).toFixed(2)) : 0,
    }
  }

  async publishRun(status: 'running' | 'complete' | 'failed', elapsedSec?: number) {
    if (!this.currentRunId) return
    try {
      await apiClient.post('/admin/api-test/runs/publish', {
        run_id: this.currentRunId,
        run_kind: 'frontend_baseline',
        status,
        results: this.flatResults(),
        summary: { ...this.runSummary(), elapsed_seconds: elapsedSec ?? null },
      })
    } catch (e) {
      // Publishing is bookkeeping — it must never abort a run in progress.
      log.warn('publishRun failed (run continues):', e)
    }
  }

  async loadLatestRun(): Promise<Record<string, any> | null> {
    try {
      const { data } = await apiClient.get('/admin/api-test/runs/latest', {
        params: { run_kind: 'frontend_baseline' },
      })
      const run = data?.run
      if (!run?.results?.length) return null
      const byKey = new Map<string, any>()
      for (const r of run.results) byKey.set(`${r.method} ${r.path}`, r)
      let hydrated = 0
      for (const endpoints of Object.values(this.endpointsData.value || {})) {
        for (const ep of (endpoints as Endpoint[])) {
          const r = byKey.get(`${ep.method} ${ep.path}`)
          if (r) { ep.result = r; hydrated++ }
        }
      }
      log.info(`Hydrated ${hydrated} results from archived run`, run.summary)
      return run.summary ?? null
    } catch (e) {
      log.warn('loadLatestRun failed:', e)
      return null
    }
  }


  shouldShowRequestBody(endpoint: Endpoint): boolean {
    return ['POST', 'PUT', 'PATCH'].includes(endpoint.method) && endpoint.method !== 'WS'
  }
  
  findDefaultBody(path: string): any {
    // Try exact match first
    if (DEFAULT_BODIES[path]) {
      return DEFAULT_BODIES[path]
    }
    
    // Try pattern matching (remove parameter placeholders)
    const cleanPath = path.replace(/{[^}]+}/g, '')
    for (const [pattern, body] of Object.entries(DEFAULT_BODIES)) {
      const cleanPattern = pattern.replace(/{[^}]+}/g, '')
      if (cleanPath === cleanPattern) {
        return body
      }
    }
    
    return null
  }
  
  getDefaultBody(path: string): string {
    const defaultBody = this.findDefaultBody(path)
    return defaultBody ? JSON.stringify(defaultBody, null, 2) : '{\n  \n}'
  }
  
  formatJson(json: string): string {
    try {
      const parsed = JSON.parse(json)
      return JSON.stringify(parsed, null, 2)
    } catch {
      throw new Error('Invalid JSON')
    }
  }
  
  resetToDefault(endpoint: Endpoint): void {
    const defaultBody = this.findDefaultBody(endpoint.path)
    if (defaultBody) {
      endpoint.requestBody = JSON.stringify(defaultBody, null, 2)
    } else {
      endpoint.requestBody = '{\n  \n}'
    }
  }
  
  // Flow Testing Methods
  async executeFlow(flowName: string, developerToken: string, agentToken: string = ''): Promise<any> {
    try {
      // Execute flow test
      const response = await apiClient.post('/admin/api-test/test-flow', {
        flow_name: flowName,
        developer_token: developerToken,
        agent_token: agentToken
      })
      
      // CRITICAL: Update individual endpoints with flow results
      // This provides real-time visual feedback as the flow executes
      if (response.data.results && Array.isArray(response.data.results)) {
        import.meta.env.DEV && console.log(`Flow returned ${response.data.results.length} results to update in UI`)
        let updatedCount = 0
        let notFoundCount = 0
        
        for (const result of response.data.results) {
          // Extract path and method from the result
          const path = result.path
          const method = result.method
          let found = false
          
          // Search through all categories to find matching endpoint
          for (const category in this.endpointsData.value) {
            const endpoints = this.endpointsData.value[category]
            const endpoint = endpoints.find((e: Endpoint) => {
              if (e.method !== method) return false
              
              // First try exact match
              if (e.path === path) return true
              
              // If endpoint has parameters, try pattern matching
              if (e.path.includes('{') && e.path.includes('}')) {
                // Convert endpoint pattern to regex
                // e.g., /organizations/{org_id} becomes /organizations/[^/]+
                const pattern = e.path.replace(/{[^}]+}/g, '[^/]+')
                const regex = new RegExp('^' + pattern + '$')
                const matches = regex.test(path)
                if (matches) {
                  import.meta.env.DEV && console.log(`Pattern match: ${e.path} matches ${path}`)
                }
                return matches
              }
              
              return false
            })
            
            if (endpoint) {
              // Update the endpoint with the test result
              endpoint.result = {
                healthy: result.healthy,
                statusCode: result.statusCode,
                responseTime: result.responseTime,
                responseData: result.responseData,
                error: result.error,
                expected_failure: result.expected_failure,
                expected_failure_reason: result.expected_failure_reason,
                not_measured: result.not_measured,
                not_measured_reason: result.not_measured_reason,
                unmeasured: result.unmeasured,
              }
              // Mark as not testing anymore
              endpoint.testing = false
              
              import.meta.env.DEV && console.log(`✅ Updated endpoint: ${method} ${path} - ${result.healthy ? 'PASS' : 'FAIL'} (${category})`)
              updatedCount++
              found = true
              break // Found and updated, move to next result
            }
          }
          
          if (!found) {
            log.warn(`❌ Could not find endpoint in UI: ${method} ${path}`)
            notFoundCount++
          }
        }
        
        log.info(`Flow update summary: ${updatedCount} updated, ${notFoundCount} not found`)
      } else {
        log.warn('No results array in flow response:', response.data)
      }
      
      return response.data
    } catch (error: any) {
      console.error('Flow execution error:', error)
      throw error
    }
  }
  
  async getFlowValues(): Promise<any> {
    try {
      const response = await apiClient.get('/admin/api-test/flow-values')
      return response.data.values
    } catch (error: any) {
      console.error('Error fetching flow values:', error)
      return {}
    }
  }
  
  async resetFlowValues(): Promise<void> {
    try {
      await apiClient.post('/admin/api-test/reset-flow-values')
    } catch (error: any) {
      console.error('Error resetting flow values:', error)
      throw error
    }
  }
}
