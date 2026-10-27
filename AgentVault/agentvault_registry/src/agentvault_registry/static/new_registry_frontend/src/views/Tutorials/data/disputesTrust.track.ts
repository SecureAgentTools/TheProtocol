import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 5: Disputes & Trust — The decentralized justice system
 *
 * 12 steps:
 * SETUP (1-6): Auth → Bootstrap A → Create Agent A → Bootstrap B → Create Agent B → Fund Defendant
 * DISPUTES (7-12): File Dispute → Submit Evidence → View Dispute → Admin Ruling →
 *                   View Settlement → Check Reputation
 *
 * Two agents: Complainant (A) and Defendant (B).
 * Disputes router auth (verified 2026-05-06):
 *   - GET / + GET /{id}            → developer JWT
 *   - POST / + POST /{id}/evidence → agent JWT (complainant_did/submitter_did
 *     derived from the authenticated agent — no impersonation)
 *   - GET /agent/{did}             → agent JWT, self-only (D1 fix 2026-05-06)
 *   - PUT /admin/disputes/{id}/ruling → admin (require_admin_flag)
 * Defendant funded so compensation system can deduct AVT upon ruling.
 *
 * CRITICAL NOTES:
 * - Step 8 (Evidence) must include amount_disputed: 500 in evidence_data — read by extract_disputed_amount()
 * - Step 10 (Ruling) is PUT with ruling as QUERY PARAM in URL, body is null
 * - Step 12 (Reputation) checks defendant's reputation_score (should be lower after ruling)
 *
 * Variables: $sandboxDevToken, $bootstrapTokenA, $agentDidA, $bootstrapTokenB, $agentDidB, $disputeId
 *
 * Endpoint verification sources:
 * - auth_secure.py: /auth/login (form-encoded)
 * - onboarding.py: /onboard/bootstrap/request-token, /onboard/create_agent
 * - teg_integration.py: /teg/treasury/fund-agent
 * - disputes.py: POST /disputes/, POST /disputes/{id}/evidence, GET /disputes/{id}
 * - admin.py: PUT /admin/disputes/{id}/ruling?ruling=...
 * - agent_discovery.py: GET /agents/by-did/{did}
 */
export const disputesTrustTrack: TutorialTrack = {
  id: 'disputes-trust',
  title: 'Disputes & Trust',
  subtitle: 'The decentralized justice system',
  description: 'File disputes between agents, submit evidence, issue admin rulings, and see the impact on reputation scores and compensation in units: TheProtocol\'s decentralized conflict resolution.',
  icon: 'scale',
  color: 'rose',
  gradientFrom: 'from-rose-500',
  gradientTo: 'to-red-600',
  estimatedMinutes: 12,
  prerequisites: ['agent-lifecycle'],
  completionTitle: 'Justice Served',
  steps: [
    // ═══════════════════════════════════════════════════════
    // SETUP PHASE — Steps 1-6: Create two agents, fund defendant
    // ═══════════════════════════════════════════════════════

    // ─── Step 1: Authenticate ───
    {
      id: 'authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT access token',
      explanation: `Same as previous tracks — authenticate with the pre-provisioned tutorial account.

The developer JWT is needed to bootstrap agents and fund them from the treasury. The dispute system itself uses **DIDs directly** (no JWT auth), but agent creation and funding still require developer credentials.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with the sandbox using the tutorial developer account',
        body: {
          ...SANDBOX_TUTORIAL_LOGIN
        },
        authType: 'none'
      },
      captures: [
        {
          key: 'sandboxDevToken',
          responsePath: 'access_token',
          displayLabel: 'Sandbox Developer JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      notes: 'Setup step — identical to Track 1. This JWT handles agent creation and treasury funding.'
    },

    // ─── Step 2: Bootstrap Token (Agent A — Complainant) ───
    {
      id: 'bootstrap-agent-a',
      stepNumber: 2,
      title: 'Bootstrap Token (Complainant)',
      subtitle: 'Get a creation credential for the complainant agent',
      explanation: `The dispute system requires **two agents** — a complainant who files the dispute and a defendant who is accused.

We start by bootstrapping **Agent A** — the complainant. This is the agent that will file the dispute and submit evidence.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token for Agent A (Dispute Complainant)',
        body: {
          agent_type_hint: 'tutorial_complainant',
          requested_by: 'tutorial-user'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'bootstrapTokenA',
          responsePath: 'bootstrap_token',
          displayLabel: 'Bootstrap Token (Complainant)',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['bootstrap_token']
      },
      requiresStepId: 'authenticate',
      notes: 'Bootstrap tokens expire in 5 minutes. Proceed to Step 3 promptly.'
    },

    // ─── Step 3: Create Agent A (Complainant) ───
    {
      id: 'create-agent-a',
      stepNumber: 3,
      title: 'Create Complainant Agent',
      subtitle: 'Birth the agent who will file the dispute',
      explanation: `Creating **Dispute Complainant** — this agent will file a dispute against another agent and submit evidence supporting their claim.

We capture the **Agent DID** — this is the only credential we need for the dispute system, which uses DID-based identification rather than JWT authentication.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create Agent A (Dispute Complainant) using the bootstrap token',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Dispute Complainant',
            description: 'Complainant agent for the Disputes & Trust tutorial — files disputes and submits evidence',
            url: 'http://localhost:8100/agents/dispute-complainant',
            humanReadableId: 'dispute-complainant',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'disputes', 'complainant']
            },
            authSchemes: [
              {
                scheme: 'oauth2',
                client_id: 'pending',
                tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token'
              }
            ],
            service_endpoints: [
              {
                type: 'messaging',
                url: 'http://localhost:8100/agents/dispute-complainant'
              }
            ],
            metadata: {
              status: 'active',
              teg_enabled: true
            }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapTokenA'
      },
      captures: [
        {
          key: 'agentDidA',
          responsePath: 'agent_did',
          displayLabel: 'Complainant DID'
        },
        {
          key: 'clientIdA',
          responsePath: 'client_id',
          displayLabel: 'Complainant Client ID'
        },
        {
          key: 'clientSecretA',
          responsePath: 'client_secret',
          displayLabel: 'Complainant Client Secret',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did']
      },
      requiresStepId: 'bootstrap-agent-a',
      notes: 'Agent A (Dispute Complainant) is on the network. We captured its client credentials so we can get an agent token — filing a dispute is authenticated as the complainant.'
    },

    // ─── Step 3b: Authenticate as the Complainant (Agent A JWT) ───
    {
      id: 'get-agent-a-token',
      stepNumber: 4,
      title: 'Authenticate as the Complainant',
      subtitle: "Get Agent A's JWT to file the dispute",
      explanation: `Filing a dispute is an **authenticated** action — the registry records the complainant from the caller's identity, not from the request body. So Agent A exchanges its client credentials for an **agent JWT** via \`POST /auth/agent/token\`.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Exchange Agent A client credentials for an agent JWT',
        body: {
          grant_type: 'password',
          username: '$clientIdA',
          password: '$clientSecretA'
        },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'clientIdA' },
          { jsonPath: 'password', capturedKey: 'clientSecretA' }
        ],
        authType: 'none'
      },
      captures: [
        {
          key: 'agentTokenA',
          responsePath: 'access_token',
          displayLabel: 'Complainant Agent JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'create-agent-a',
      notes: 'Agent A is authenticated. This JWT files the dispute and submits evidence — the registry binds those actions to the complainant identity.'
    },

    // ─── Step 4: Bootstrap Token (Agent B — Defendant) ───
    {
      id: 'bootstrap-agent-b',
      stepNumber: 5,
      title: 'Bootstrap Token (Defendant)',
      subtitle: 'Get a creation credential for the defendant agent',
      explanation: `Now we bootstrap **Agent B** — the defendant in our dispute. This agent will be accused of failing to deliver a service.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token for Agent B (Dispute Defendant)',
        body: {
          agent_type_hint: 'tutorial_defendant',
          requested_by: 'tutorial-user'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'bootstrapTokenB',
          responsePath: 'bootstrap_token',
          displayLabel: 'Bootstrap Token (Defendant)',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['bootstrap_token']
      },
      requiresStepId: 'create-agent-a',
      notes: 'Bootstrap tokens expire in 5 minutes. Proceed to Step 5 promptly.'
    },

    // ─── Step 5: Create Agent B (Defendant) ───
    {
      id: 'create-agent-b',
      stepNumber: 6,
      title: 'Create Defendant Agent',
      subtitle: 'Birth the agent who will face the dispute',
      explanation: `Creating **Dispute Defendant** — this agent will be the subject of a dispute filed by the complainant.

Again, we only need the **DID** — no agent token required for dispute operations.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create Agent B (Dispute Defendant) using the bootstrap token',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Dispute Defendant',
            description: 'Defendant agent for the Disputes & Trust tutorial — subject of a dispute filing',
            url: 'http://localhost:8100/agents/dispute-defendant',
            humanReadableId: 'dispute-defendant',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'disputes', 'defendant']
            },
            authSchemes: [
              {
                scheme: 'oauth2',
                client_id: 'pending',
                tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token'
              }
            ],
            service_endpoints: [
              {
                type: 'messaging',
                url: 'http://localhost:8100/agents/dispute-defendant'
              }
            ],
            metadata: {
              status: 'active',
              teg_enabled: true
            }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapTokenB'
      },
      captures: [
        {
          key: 'agentDidB',
          responsePath: 'agent_did',
          displayLabel: 'Defendant DID'
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did']
      },
      requiresStepId: 'bootstrap-agent-b',
      notes: 'Agent B (Dispute Defendant) is now on the network. Both agents are created — now we fund the defendant so the compensation system can work.'
    },

    // ─── Step 6: Fund Defendant ───
    {
      id: 'fund-defendant',
      stepNumber: 7,
      title: 'Fund Defendant (5,000 units)',
      subtitle: 'Provide units for compensation to work',
      explanation: `We fund **Agent B (the defendant)** with 5,000 units from the treasury. Why?

When a dispute ruling is **in favor of the complainant**, the compensation system **takes units from the defendant's balance** and pays the complainant. If the defendant holds no units, compensation fails.

By funding the defendant, we ensure the full dispute lifecycle works end-to-end: filing → evidence → ruling → **compensation** → reputation impact.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Transfer 5,000 units to the defendant for compensation purposes',
        body: {
          target_agent_did: '$agentDidB',
          amount: '5000',
          reason: 'tutorial_grant',
          reference_id: 'tut5-fund-defendant'
        },
        bodyDynamic: [
          { jsonPath: 'target_agent_did', capturedKey: 'agentDidB' }
        ],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'create-agent-b',
      notes: 'Setup complete! The defendant has 5,000 units. When the ruling favors the complainant, 500 units (the disputed amount from evidence) are paid as compensation.'
    },

    // ═══════════════════════════════════════════════════════
    // DISPUTES — Steps 7-12: The justice system in action
    // ═══════════════════════════════════════════════════════

    // ─── Step 7: File Dispute ───
    {
      id: 'file-dispute',
      stepNumber: 8,
      title: 'File Dispute',
      subtitle: 'Open a case between two agents',
      explanation: `Now the real action begins — **filing a dispute**. The complainant (Agent A) accuses the defendant (Agent B) of wrongdoing.

The \`POST /disputes/\` endpoint is **authenticated as the complainant** (Agent A's JWT from the previous step):
- the **complainant** is taken from your authenticated agent identity (not the request body)
- \`defendant_did\` — who is being accused

The backend validates that both agents exist and that complainant ≠ defendant.

The dispute starts with status **OPEN** and no ruling.`,
      apiCall: {
        method: 'POST',
        path: '/disputes/',
        description: 'File a dispute: Complainant (Agent A) vs Defendant (Agent B)',
        body: {
          complainant_did: '$agentDidA',
          defendant_did: '$agentDidB'
        },
        bodyDynamic: [
          { jsonPath: 'complainant_did', capturedKey: 'agentDidA' },
          { jsonPath: 'defendant_did', capturedKey: 'agentDidB' }
        ],
        authType: 'agent',
        authTokenRef: '$agentTokenA'
      },
      captures: [
        {
          key: 'disputeId',
          responsePath: 'id',
          displayLabel: 'Dispute ID'
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['id']
      },
      requiresStepId: 'fund-defendant',
      notes: 'Dispute filed! Status is OPEN. The dispute ID will be used in all subsequent steps. Filed under the complainant JWT — the registry binds the case to Agent A.'
    },

    // ─── Step 8: Submit Evidence ───
    {
      id: 'submit-evidence',
      stepNumber: 9,
      title: 'Submit Evidence',
      subtitle: 'Attach evidence to support the complaint',
      explanation: `The complainant submits **evidence** to support their case. The \`POST /disputes/{id}/evidence\` endpoint accepts:

- \`submitter_did\` — must be a party to the dispute (complainant or defendant)
- \`evidence_data\` — a free-form JSON object containing the evidence details

**Critical field: \`amount_disputed\`** — This value inside \`evidence_data\` is read by the compensation system's \`extract_disputed_amount()\` function. When a ruling favors the complainant, this amount determines how many units the complainant is compensated with.

Our evidence describes a service delivery failure with 500 units at stake.`,
      apiCall: {
        method: 'POST',
        path: '/disputes/$disputeId/evidence',
        description: 'Submit evidence from the complainant',
        pathParams: { id: '$disputeId' },
        body: {
          submitter_did: '$agentDidA',
          evidence_data: {
            reason_code: 'SERVICE_NOT_DELIVERED',
            description: 'Agent B committed to process a data analysis task but failed to deliver results within the agreed timeframe.',
            amount_disputed: 500,
            transaction_reference: 'tutorial-dispute-evidence',
            impact: {
              total_avt_at_risk: 500,
              service_type: 'data_analysis'
            }
          }
        },
        bodyDynamic: [
          { jsonPath: 'submitter_did', capturedKey: 'agentDidA' }
        ],
        authType: 'agent',
        authTokenRef: '$agentTokenA'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'file-dispute',
      notes: 'Evidence submitted! The amount_disputed: 500 is critical — when the ruling favors the complainant, the complainant is compensated with exactly 500 units, taken from the defendant.'
    },

    // ─── Step 9: View Dispute ───
    {
      id: 'view-dispute',
      stepNumber: 10,
      title: 'View Dispute',
      subtitle: 'See the full dispute with evidence attached',
      explanation: `Before the admin ruling, let's view the complete dispute record. The \`GET /disputes/{id}\` endpoint returns:

- **Dispute details** — complainant DID, defendant DID, status, ruling
- **Evidence array** — all submitted evidence with timestamps
- **Timestamps** — created_at, updated_at

The dispute is currently OPEN with no ruling. The evidence we submitted in Step 8 should be visible in the evidence array.`,
      apiCall: {
        method: 'GET',
        path: '/disputes/$disputeId',
        description: 'View the complete dispute record',
        pathParams: { id: '$disputeId' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'submit-evidence',
      notes: 'The dispute shows status: OPEN and ruling: null. Evidence is attached with the amount_disputed field visible. Ready for the admin to issue a ruling.'
    },

    // ─── Step 10: Admin Ruling ───
    {
      id: 'admin-ruling',
      stepNumber: 11,
      title: 'Admin Ruling',
      subtitle: 'Issue a ruling in favor of the complainant',
      explanation: `The admin issues a **ruling** on the dispute. This is the most impactful step — it triggers:

1. **Status change** — Dispute moves from OPEN to CLOSED
2. **Reputation changes** — Complainant gains reputation, defendant loses reputation
3. **Compensation** — units taken from the defendant and paid to the complainant, by \`amount_disputed\`

The \`PUT /admin/disputes/{id}/ruling\` endpoint takes the ruling as a **query parameter** in the URL:
- \`IN_FAVOR_OF_COMPLAINANT\` — complainant wins (reputation +10/-20, compensation applied)
- \`IN_FAVOR_OF_DEFENDANT\` — defendant wins (reputation reversed)
- \`DISMISSED\` — case dismissed (no changes)

**Note:** The ruling is in the URL query string, not the request body. The body is null/empty.`,
      apiCall: {
        method: 'PUT',
        path: '/admin/disputes/$disputeId/ruling?ruling=IN_FAVOR_OF_COMPLAINANT',
        description: 'Issue ruling in favor of the complainant (admin)',
        pathParams: { id: '$disputeId' },
        body: null,
        authType: 'admin',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'view-dispute',
      notes: 'Ruling issued! Check the response for reputation_changes (complainant +2, defendant -10) and compensation (500 units, taken from the defendant and paid to the complainant). The dispute is now CLOSED.'
    },

    // ─── Step 11: View Settlement ───
    {
      id: 'view-settlement',
      stepNumber: 12,
      title: 'View Settlement',
      subtitle: 'See the closed dispute with ruling applied',
      explanation: `Re-fetch the dispute to see the final state after the ruling. The dispute should now show:

- **status: CLOSED** — no longer accepting evidence or changes
- **ruling: IN_FAVOR_OF_COMPLAINANT** — the admin's decision
- **All evidence** — preserved in the record

This is the same endpoint as Step 9, but the data has changed. The dispute lifecycle is complete: OPEN → evidence → ruling → **CLOSED**.`,
      apiCall: {
        method: 'GET',
        path: '/disputes/$disputeId',
        description: 'View the dispute after ruling — now in CLOSED state',
        pathParams: { id: '$disputeId' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'admin-ruling',
      notes: 'The dispute is now CLOSED with a ruling. Compare this response with Step 9 — the status and ruling fields have changed. The evidence is preserved as an immutable record.'
    },

    // ─── Step 12: Check Reputation ───
    {
      id: 'check-reputation',
      stepNumber: 13,
      title: 'Check Defendant Reputation',
      subtitle: 'See the impact of the ruling on trust scores',
      explanation: `The final step — checking the **reputation impact** of the ruling on the defendant.

The \`GET /agents/by-did/{did}\` endpoint returns the agent's full profile, including \`reputation_score\`. After an unfavorable ruling:

- **Defendant (Agent B):** reputation decreases by 20 points (from initial 100 → 80)
- **Complainant (Agent A):** reputation increases by 10 points (from initial 100 → 110)

Reputation is the foundation of **trustless agent commerce** — agents with low reputation scores may be avoided by others. The dispute system creates real economic and reputational consequences for bad behavior.

**Congratulations** — you've completed the Disputes & Trust track! You've seen the full justice lifecycle: dispute filing → evidence → admin ruling → compensation → reputation impact.`,
      apiCall: {
        method: 'GET',
        path: '/agents/by-did/$agentDidB',
        description: 'Check the defendant\'s reputation score after the ruling',
        pathParams: { did: '$agentDidB' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'view-settlement',
      notes: 'Track complete! The defendant\'s reputation_score should be lower than the initial 100. This permanent record incentivizes good behavior — every dispute leaves a mark on the trust graph.'
    }
  ]
}
