import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 6: Federated Settlements — Cross-registry sovereign dispute resolution
 *
 * 18 steps:
 * SETUP (1-7): Auth both registries → Create complainant on A → Create defendant on B → Fund defendant
 * SLASH CONFIG (8-11): View/set auto-slash on A for peer B → View/set auto-slash on B for peer A
 * DISPUTE + RULING (12-14): File dispute → Evidence → Ruling triggers cross-registry settlement
 * VERIFICATION (15-18): View settlements on A → View settlements on B → Check balances on both
 *
 * DUAL-REGISTRY MODEL:
 * - Registry A (registry-test, port 8002) — complainant's home, proxy target
 * - Registry B (registry-test-b, port 8003) — defendant's home, direct calls
 *
 * The Sovereign Settlement Protocol:
 * 1. Ruling on A detects defendant is NOT local → cross-registry path
 * 2. Slash request sent to B via mTLS federation infrastructure
 * 3. B auto-slashes defendant (amount ≤ threshold) → deducts liquid_balance
 * 4. B callbacks A with confirmation → A pays the complainant from its own system accounts
 * 5. Both registries record settlement independently (A=SETTLED, B=SLASHED)
 *
 * Variables: $sandboxDevToken, $sandboxDevTokenB, $bootstrapTokenA, $agentDidA,
 *            $bootstrapTokenB, $agentDidB, $peerId, $peerIdB, $disputeId
 *
 * Prerequisites: disputes-trust (understand local disputes) + federation (understand dual-registry)
 *
 * Endpoint verification sources:
 * - auth_secure.py: /auth/login (form-encoded)
 * - onboarding.py: /onboard/bootstrap/request-token, /onboard/create_agent
 * - teg_integration.py: /teg/treasury/fund-agent
 * - disputes.py: POST /disputes/, POST /disputes/{id}/evidence
 * - admin.py: PUT /admin/disputes/{id}/ruling → triggers process_compensation()
 * - federation_disputes.py: GET /settlements, GET /peer-slash-config, PUT /peer-slash-config/{id}
 * - agent_discovery.py: GET /agents/by-did/{did}
 */
export const federatedSettlementsTrack: TutorialTrack = {
  id: 'federated-settlements',
  title: 'Federated Settlements',
  subtitle: 'Cross-registry sovereign dispute resolution',
  // Access-control LOCK — this track drives admin-only calls (e.g. the dispute
  // ruling that triggers cross-registry settlement). Gate behind the
  // admin_enforcement RBAC flag; is_admin superusers bypass. Locked + not
  // launchable on the TutorialHub for users without it.
  requireFlag: 'admin_enforcement',
  description: 'The Champions League of decentralized justice — file a dispute where the complainant and defendant are on different registries, configure auto-slash thresholds, and watch the Sovereign Settlement Protocol resolve it across federation boundaries with real movements of units on both sides.',
  icon: 'shield-check',
  color: 'purple',
  gradientFrom: 'from-purple-500',
  gradientTo: 'to-pink-600',
  estimatedMinutes: 15,
  prerequisites: ['disputes-trust', 'federation'],
  completionTitle: 'Sovereign Arbiter',
  steps: [
    // ═══════════════════════════════════════════════════════
    // SETUP PHASE — Steps 1-7: Two registries, two agents
    // ═══════════════════════════════════════════════════════

    // ─── Step 1: Authenticate (Registry A) ───
    {
      id: 'authenticate-a',
      stepNumber: 1,
      title: 'Authenticate (Registry A)',
      subtitle: 'Obtain a JWT from the complainant\'s registry',
      explanation: `Federated settlements involve **two independent registries** — each with its own agents, balances, and jurisdiction.

We start by authenticating on **Registry A** — this is where the complainant agent will live and where we'll file the dispute and issue the ruling.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with Registry A (registry-test)',
        body: {
          ...SANDBOX_TUTORIAL_LOGIN
        },
        authType: 'none'
      },
      captures: [
        {
          key: 'sandboxDevToken',
          responsePath: 'access_token',
          displayLabel: 'Registry A Developer JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      notes: 'This JWT is signed by Registry A. It cannot be used on Registry B: each registry accepts only the JWTs it signed itself.'
    },

    // ─── Step 2: Authenticate (Registry B — direct call) ───
    {
      id: 'authenticate-b',
      stepNumber: 2,
      title: 'Authenticate (Registry B)',
      subtitle: 'Obtain a JWT from the defendant\'s registry',
      explanation: `Now we authenticate on **Registry B** — the defendant's home registry. This is a **direct API call** to \`Registry B (sandbox)\`.

Same credentials, different registry. We need this JWT to create and fund the defendant agent on Registry B.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with Registry B (registry-test-b) — direct call',
        body: {
          ...SANDBOX_TUTORIAL_LOGIN
        },
        authType: 'none',
        targetBase: '/sandbox-b',
        formEncoded: true
      },
      captures: [
        {
          key: 'sandboxDevTokenB',
          responsePath: 'access_token',
          displayLabel: 'Registry B Developer JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'authenticate-a',
      notes: 'Direct call to port 8003. The JWT returned is only valid on Registry B.'
    },

    // ─── Step 3: Bootstrap Complainant (Registry A) ───
    {
      id: 'bootstrap-complainant',
      stepNumber: 3,
      title: 'Bootstrap Complainant (Registry A)',
      subtitle: 'Get a creation credential for the complainant',
      explanation: `The **complainant** lives on Registry A. We bootstrap an agent here — this agent will file the dispute.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token for the complainant on Registry A',
        body: {
          agent_type_hint: 'tutorial_settlement_complainant',
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
      requiresStepId: 'authenticate-b',
      notes: 'Bootstrap tokens expire in 5 minutes. Proceed to Step 4 promptly.'
    },

    // ─── Step 4: Create Complainant (Registry A) ───
    {
      id: 'create-complainant',
      stepNumber: 4,
      title: 'Create Complainant Agent (Registry A)',
      subtitle: 'Birth the agent who will file the cross-registry dispute',
      explanation: `Creating **Settlement Complainant** on Registry A. This agent will file a dispute against an agent living on a *different registry*. We only need the DID — disputes use DID-based identification.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create the complainant agent on Registry A',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Settlement Complainant',
            description: 'Complainant agent for the Federated Settlements tutorial — files cross-registry disputes',
            url: 'http://localhost:8100/agents/settlement-complainant',
            humanReadableId: 'settlement-complainant',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'federated-settlements', 'complainant']
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
                url: 'http://localhost:8100/agents/settlement-complainant'
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
          displayLabel: 'Complainant DID (Registry A)'
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did']
      },
      requiresStepId: 'bootstrap-complainant',
      notes: 'The complainant lives on Registry A. When the dispute is filed, Registry A will detect the defendant is foreign and trigger the cross-registry settlement protocol.'
    },

    // ─── Step 5: Bootstrap Defendant (Registry B — direct) ───
    {
      id: 'bootstrap-defendant',
      stepNumber: 5,
      title: 'Bootstrap Defendant (Registry B)',
      subtitle: 'Get a creation credential on the second registry',
      explanation: `Now we create the **defendant** on **Registry B** — a completely different registry with its own database and jurisdiction.

This is a **direct API call** to Registry B. The defendant agent will only exist in Registry B's database — Registry A has no record of it.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token on Registry B — direct call',
        body: {
          agent_type_hint: 'tutorial_settlement_defendant',
          requested_by: 'tutorial-user'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevTokenB',
        targetBase: '/sandbox-b'
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
      requiresStepId: 'create-complainant',
      notes: 'Direct call to Registry B (port 8003). Bootstrap tokens expire in 5 minutes.'
    },

    // ─── Step 6: Create Defendant (Registry B — direct) ───
    {
      id: 'create-defendant',
      stepNumber: 6,
      title: 'Create Defendant Agent (Registry B)',
      subtitle: 'Birth the agent on a foreign registry',
      explanation: `Creating **Settlement Defendant** on Registry B. This agent lives entirely in Registry B's jurisdiction — Registry A cannot modify its balance directly.

This is the core sovereignty principle: **no registry can touch another registry's agents**. When a dispute involves agents on different registries, the settlement must be coordinated through the federation protocol.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create the defendant agent on Registry B — direct call',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Settlement Defendant',
            description: 'Defendant agent for the Federated Settlements tutorial — subject of cross-registry dispute',
            url: 'http://localhost:8100/agents/settlement-defendant',
            humanReadableId: 'settlement-defendant',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'federated-settlements', 'defendant']
            },
            authSchemes: [
              {
                scheme: 'oauth2',
                client_id: 'pending',
                tokenUrl: 'http://registry-test-b:8000/api/v1/auth/agent/token'
              }
            ],
            service_endpoints: [
              {
                type: 'messaging',
                url: 'http://localhost:8100/agents/settlement-defendant'
              }
            ],
            metadata: {
              status: 'active',
              teg_enabled: true
            }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapTokenB',
        targetBase: '/sandbox-b'
      },
      captures: [
        {
          key: 'agentDidB',
          responsePath: 'agent_did',
          displayLabel: 'Defendant DID (Registry B)'
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did']
      },
      requiresStepId: 'bootstrap-defendant',
      notes: 'The defendant exists ONLY on Registry B. Registry A has no record of this agent — when the ruling is issued on A, it will discover the defendant is foreign and initiate the Sovereign Settlement Protocol.'
    },

    // ─── Step 7: Fund Defendant (Registry B — direct) ───
    {
      id: 'fund-defendant',
      stepNumber: 7,
      title: 'Fund Defendant (5,000 units on Registry B)',
      subtitle: 'Provide units so the slash can deduct',
      explanation: `We fund the defendant with 5,000 units on **Registry B's TEG**. This is a direct call to Registry B's treasury.

The defendant needs units so the **auto-slash** can deduct from it. When the cross-registry settlement triggers, Registry B will deduct from this balance — it has full jurisdiction over its own agents.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Fund the defendant with 5,000 units on Registry B (direct call)',
        body: {
          target_agent_did: '$agentDidB',
          amount: '5000',
          reason: 'tutorial_grant',
          reference_id: 'tut6-fund-defendant'
        },
        bodyDynamic: [
          { jsonPath: 'target_agent_did', capturedKey: 'agentDidB' }
        ],
        authType: 'developer',
        authTokenRef: '$sandboxDevTokenB',
        targetBase: '/sandbox-b'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'create-defendant',
      notes: 'Setup complete! Complainant on Registry A, defendant on Registry B with 5,000 units. Now we configure the auto-slash threshold before filing the dispute.'
    },

    // ═══════════════════════════════════════════════════════
    // SLASH CONFIG — Steps 8-9: Configure auto-slash threshold
    // ═══════════════════════════════════════════════════════

    // ─── Step 8: View Peer Slash Config ───
    {
      id: 'view-peer-config',
      stepNumber: 8,
      title: 'View Peer Slash Config',
      subtitle: 'Inspect auto-slash thresholds for federated peers',
      explanation: `Before filing the dispute, let's configure the **auto-slash threshold** on Registry A.

The \`/federation/disputes/peer-slash-config\` endpoint shows all active federation peers with their auto-slash settings:
- **auto_slash_enabled** — whether slash requests from this peer are auto-approved
- **auto_slash_max_avt** — the most units that can be auto-slashed without admin review

When a cross-registry ruling triggers a slash request, Registry B checks these thresholds. If the amount is under the threshold, it auto-slashes. Over the threshold, it parks the request for admin approval.

We need the peer's **ID** from this list to configure it in the next step.`,
      apiCall: {
        method: 'GET',
        path: '/federation/disputes/peer-slash-config',
        description: 'List all peers with their auto-slash configuration (admin)',
        authType: 'admin',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'peerId',
          responsePath: 'peers.0.id',
          displayLabel: 'Federation Peer ID'
        }
      ],
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'fund-defendant',
      notes: 'The peer list shows the mTLS-connected registries. Capture the first peer\'s ID — we\'ll use it to set the auto-slash threshold.'
    },

    // ─── Step 9: Update Slash Config ───
    {
      id: 'update-slash-config',
      stepNumber: 9,
      title: 'Set Auto-Slash Threshold (1,000 units)',
      subtitle: 'Configure automatic cross-registry slash approval',
      explanation: `Now we configure Registry A's auto-slash settings for this peer. We're setting:

- **auto_slash_enabled: true** — enable automatic slash processing
- **auto_slash_max_avt: 1000** — auto-approve slashes up to 1,000 units

Our dispute will involve 500 units, which is **under** the 1,000-unit threshold. This means Registry B will auto-slash without requiring admin approval — the entire settlement happens automatically.

If we set the threshold to 100 units instead, our 500-unit slash would require manual admin approval on Registry B (the \`/settlements/{id}/approve\` endpoint).`,
      apiCall: {
        method: 'PUT',
        path: '/federation/disputes/peer-slash-config/$peerId',
        description: 'Set auto-slash threshold to 1,000 units for the federated peer',
        pathParams: { peer_id: '$peerId' },
        body: {
          auto_slash_enabled: true,
          auto_slash_max_avt: 1000
        },
        authType: 'admin',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'view-peer-config',
      notes: 'Auto-slash configured on Registry A! Slash requests of up to 1,000 units from peer B will be processed automatically. Now we need to do the same on Registry B for peer A.'
    },

    // ─── Step 10: View Peer Slash Config (Registry B — direct) ───
    {
      id: 'view-peer-config-b',
      stepNumber: 10,
      title: 'View Peer Slash Config (Registry B)',
      subtitle: 'Check auto-slash thresholds on the defendant\'s registry',
      explanation: `The slash request travels from **Registry A to Registry B**. Registry B is the defendant's home — it receives the slash request and decides whether to auto-approve or park it for admin review.

We need to configure Registry B's auto-slash settings for its peer (Registry A). Without this, Registry B will park every incoming slash request as PENDING_ADMIN_APPROVAL, and no automatic settlement will happen.

This is a **direct call** to Registry B's admin endpoint.`,
      apiCall: {
        method: 'GET',
        path: '/federation/disputes/peer-slash-config',
        description: 'List peers with auto-slash config on Registry B (admin) — direct call',
        authType: 'admin',
        authTokenRef: '$sandboxDevTokenB',
        targetBase: '/sandbox-b'
      },
      captures: [
        {
          key: 'peerIdB',
          responsePath: 'peers.0.id',
          displayLabel: 'Registry B Peer ID (for Registry A)'
        }
      ],
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'update-slash-config',
      notes: 'Registry B\'s peer list shows the mTLS-connected registries it knows about. Capture the peer ID so we can configure auto-slash in the next step.'
    },

    // ─── Step 11: Update Slash Config (Registry B — direct) ───
    {
      id: 'update-slash-config-b',
      stepNumber: 11,
      title: 'Set Auto-Slash on Registry B (1,000 units)',
      subtitle: 'Enable automatic slash processing for incoming requests from Registry A',
      explanation: `Now we configure **Registry B's** auto-slash settings for the peer representing Registry A. This is the bilateral counterpart to Step 9.

Without this step, when Registry A sends a slash request after the ruling, Registry B would park it as PENDING_ADMIN_APPROVAL instead of auto-slashing. The entire Sovereign Settlement Protocol depends on **both registries** having auto-slash configured for each other.

We set the same threshold: **auto_slash_enabled: true**, **auto_slash_max_avt: 1000**. Our 500-unit dispute is under the threshold, so it will auto-slash.`,
      apiCall: {
        method: 'PUT',
        path: '/federation/disputes/peer-slash-config/$peerIdB',
        description: 'Set auto-slash threshold on Registry B for peer A — direct call',
        pathParams: { peer_id: '$peerIdB' },
        body: {
          auto_slash_enabled: true,
          auto_slash_max_avt: 1000
        },
        authType: 'admin',
        authTokenRef: '$sandboxDevTokenB',
        targetBase: '/sandbox-b'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'view-peer-config-b',
      notes: 'Both registries now have auto-slash configured! Registry A auto-slashes for peer B, Registry B auto-slashes for peer A. The bilateral trust is established — time to file the dispute.'
    },

    // ═══════════════════════════════════════════════════════
    // DISPUTE + RULING — Steps 12-14: The cross-registry trigger
    // ═══════════════════════════════════════════════════════

    // ─── Step 12: File Dispute ───
    {
      id: 'file-dispute',
      stepNumber: 12,
      title: 'File Cross-Registry Dispute',
      subtitle: 'Complainant on Registry A vs defendant on Registry B',
      explanation: `This is where it gets interesting — filing a dispute where the **complainant and defendant are on different registries**.

The \`POST /disputes/\` endpoint on Registry A accepts both DIDs. The dispute is filed locally on Registry A. The system doesn't validate whether the defendant exists locally at filing time — that check happens at ruling time.

**Key insight:** The DID for the defendant (\`$agentDidB\`) was created on Registry B. Registry A has no record of this agent in its local database. This is exactly what triggers the cross-registry settlement protocol when the ruling is issued.`,
      apiCall: {
        method: 'POST',
        path: '/disputes/',
        description: 'File a dispute: Complainant (Registry A) vs Defendant (Registry B)',
        body: {
          complainant_did: '$agentDidA',
          defendant_did: '$agentDidB'
        },
        bodyDynamic: [
          { jsonPath: 'complainant_did', capturedKey: 'agentDidA' },
          { jsonPath: 'defendant_did', capturedKey: 'agentDidB' }
        ],
        authType: 'none'
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
      requiresStepId: 'update-slash-config-b',
      notes: 'Dispute filed! The complainant DID is local to Registry A, the defendant DID is from Registry B. This cross-registry pairing will trigger the Sovereign Settlement Protocol at ruling time.'
    },

    // ─── Step 13: Submit Evidence ───
    {
      id: 'submit-evidence',
      stepNumber: 13,
      title: 'Submit Evidence',
      subtitle: 'Attach evidence with a disputed amount of 500 units',
      explanation: `The complainant submits evidence. The critical field is \`amount_disputed: 500\`. It determines how many units will be slashed from the defendant and paid to the complainant.

In the cross-registry flow, this amount travels through the entire settlement chain:
1. \`extract_disputed_amount()\` reads 500 from evidence
2. Slash request sends 500 to Registry B
3. Registry B deducts 500 from defendant's balance
4. Confirmation sends 500 back to Registry A
5. Registry A pays 500 to the complainant from its own system accounts`,
      apiCall: {
        method: 'POST',
        path: '/disputes/$disputeId/evidence',
        description: 'Submit evidence from the complainant',
        pathParams: { id: '$disputeId' },
        body: {
          submitter_did: '$agentDidA',
          evidence_data: {
            reason_code: 'SERVICE_NOT_DELIVERED',
            description: 'Cross-registry service failure — defendant on Registry B failed to deliver contracted data analysis within the agreed SLA timeframe.',
            amount_disputed: 500,
            transaction_reference: 'tutorial-federated-dispute-evidence',
            impact: {
              total_avt_at_risk: 500,
              service_type: 'cross_registry_data_analysis'
            }
          }
        },
        bodyDynamic: [
          { jsonPath: 'submitter_did', capturedKey: 'agentDidA' }
        ],
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'file-dispute',
      notes: 'Evidence submitted with amount_disputed: 500 units. This amount will be slashed from the defendant on Registry B and paid to the complainant on Registry A.'
    },

    // ─── Step 14: Admin Ruling (triggers cross-registry settlement) ───
    {
      id: 'admin-ruling',
      stepNumber: 14,
      title: 'Admin Ruling (Triggers Settlement)',
      subtitle: 'The ruling fires the Sovereign Settlement Protocol',
      explanation: `This is the **most powerful step in the entire tutorial system**. The admin ruling triggers a cascade of cross-registry operations:

1. \`process_compensation()\` looks up the defendant DID in Registry A's local Agent table
2. **Defendant not found** → cross-registry path activated
3. Emits \`DisputeCompensationRequest\` event to EventStore (informational record)
4. Creates \`CrossRegistrySettlement\` record (status: PENDING_SLASH)
5. Sends \`POST /federation/disputes/slash-request\` to Registry B via **mTLS federation**
6. Registry B receives, checks auto-slash threshold (500 ≤ 1000) → **auto-approves**
7. Registry B deducts 500 units from the defendant via TEG treasury/receive
8. Registry B emits \`DisputeSlash\` event, callbacks Registry A via mTLS
9. Registry A receives confirmation → pays 500 units to the complainant from its fee account, then its treasury
10. Registry A emits the \`DisputeCompensationMinted\` event (a historical name: nothing is minted) → settlement SETTLED

All of this happens **within seconds** — the mTLS infrastructure handles the cross-registry communication automatically.`,
      apiCall: {
        method: 'PUT',
        path: '/admin/disputes/$disputeId/ruling?ruling=IN_FAVOR_OF_COMPLAINANT',
        description: 'Issue ruling — triggers the cross-registry Sovereign Settlement Protocol',
        pathParams: { id: '$disputeId' },
        body: null,
        authType: 'admin',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'submit-evidence',
      notes: 'Ruling issued! The response shows the compensation result including cross_registry: true and the settlement_id. By the time you see this response, the entire slash → callback → payment flow may already be complete. Let\'s verify in the next steps.'
    },

    // ═══════════════════════════════════════════════════════
    // VERIFICATION — Steps 15-18: Verify settlement on both sides
    // ═══════════════════════════════════════════════════════

    // ─── Step 15: View Settlements on Registry A ───
    {
      id: 'view-settlements-a',
      stepNumber: 15,
      title: 'View Settlements (Registry A)',
      subtitle: 'Check the settlement status on the complainant\'s registry',
      explanation: `Now let's verify the settlement completed. The \`/federation/disputes/settlements\` endpoint on Registry A shows all cross-registry settlement records.

Registry A's settlement should show:
- **status: SETTLED**: compensation paid to the local complainant
- **slashed_amount: 500**: confirmed by Registry B's callback
- **minted_amount: 500**: the amount paid (a historical field name; nothing is minted)
- **mint_tx_id**: the TEG transaction that paid the complainant

This is Registry A's view: "I requested a slash, it was confirmed, and I paid compensation to my agent."`,
      apiCall: {
        method: 'GET',
        path: '/federation/disputes/settlements',
        description: 'View cross-registry settlements on Registry A',
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'admin-ruling',
      notes: 'Registry A shows SETTLED — the full cycle completed. The stats section shows aggregated settlement data across all disputes.'
    },

    // ─── Step 16: View Settlements on Registry B (direct) ───
    {
      id: 'view-settlements-b',
      stepNumber: 16,
      title: 'View Settlements (Registry B)',
      subtitle: 'Check the settlement status on the defendant\'s registry',
      explanation: `Now the other side — Registry B's settlement record. This is a **direct call** to Registry B.

Registry B's settlement should show:
- **status: SLASHED** — the defendant's units were deducted
- **slashed_amount: 500** — the amount taken from the defendant
- **slash_tx_id** — the local transaction for the deduction

This is Registry B's view: "I received a slash request, verified it, auto-slashed my local agent, and sent confirmation back."

**Two sovereign ledgers:** Registry A says SETTLED (I got paid), Registry B says SLASHED (I deducted). Together they form the complete picture of the cross-registry settlement.`,
      apiCall: {
        method: 'GET',
        path: '/federation/disputes/settlements',
        description: 'View cross-registry settlements on Registry B — direct call',
        authType: 'none',
        targetBase: '/sandbox-b'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'view-settlements-a',
      notes: 'Registry B shows SLASHED — it performed the sovereign deduction. Compare with Registry A\'s SETTLED status from Step 13. Two independent records, one coordinated settlement.'
    },

    // ─── Step 17: Check Complainant Balance (Registry A) ───
    {
      id: 'check-complainant-balance',
      stepNumber: 17,
      title: 'Check Complainant Balance (Registry A)',
      subtitle: 'Verify the complainant received compensation',
      explanation: `Let's verify the **complainant's balance** on Registry A. The \`/agents/by-did/{did}\` endpoint returns the agent's current \`liquid_balance\`.

The complainant should have received 500 units of compensation (plus any genesis grant from creation). It did not "move" from Registry B: Registry A paid it from its own system accounts (the fee account first, then the treasury), and Registry B moved the slashed amount from the defendant to its own treasury. A settlement creates and destroys no units; each registry books only its own side.`,
      apiCall: {
        method: 'GET',
        path: '/agents/by-did/$agentDidA',
        description: 'Check the complainant\'s balance after settlement',
        pathParams: { did: '$agentDidA' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'view-settlements-b',
      notes: 'The complainant\'s liquid_balance includes the 500 units of compensation plus any genesis grant from creation. Registry A paid the compensation from its own system accounts.'
    },

    // ─── Step 18: Check Defendant Balance (Registry B — direct) ───
    {
      id: 'check-defendant-balance',
      stepNumber: 18,
      title: 'Check Defendant Balance (Registry B)',
      subtitle: 'Verify the defendant was slashed',
      explanation: `The final step — checking the **defendant's balance** on Registry B. This is a **direct call** to Registry B.

The defendant started with 5,000 units (from Step 7). After the auto-slash, the balance should be **4,500 units** (5,000 - 500). The 500 units were deducted by Registry B's own TEG treasury/receive endpoint — full local jurisdiction.

**Congratulations** — you've completed the Federated Settlements track! You've witnessed the Champions League of decentralized justice:
- Two agents on two sovereign registries
- A cross-registry dispute filed and ruled on Registry A
- Automatic settlement via mTLS federation infrastructure
- Defendant slashed on Registry B, complainant compensated on Registry A
- Both registries maintain independent settlement records
- No registry ever touched another registry's agents directly`,
      apiCall: {
        method: 'GET',
        path: '/agents/by-did/$agentDidB',
        description: 'Check the defendant\'s balance on Registry B after the slash — direct call',
        pathParams: { did: '$agentDidB' },
        authType: 'developer',
        authTokenRef: '$sandboxDevTokenB',
        targetBase: '/sandbox-b'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'check-complainant-balance',
      notes: 'Track complete! The defendant\'s liquid_balance should be 4,500 units (5,000 - 500 slashed). The Sovereign Settlement Protocol maintained full registry sovereignty while resolving a cross-border dispute. This is TheProtocol\'s federation in action.'
    }
  ]
}
