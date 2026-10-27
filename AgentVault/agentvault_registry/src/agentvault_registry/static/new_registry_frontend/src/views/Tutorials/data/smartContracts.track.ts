import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 7: Smart Contracts — Agent-to-agent business lifecycle
 *
 * 10 steps:
 * AUTH (1-3): Developer JWT → Agent Token (contractor) → Agent Token (provider)
 * CONTRACT (4-9): Create → View → Accept → Submit Work → Approve → View Completed
 * OPTIONAL (10): Check Malpractice Report
 *
 * This track demonstrates the REAL use case of TheProtocol:
 * agents forming business relationships, executing work, and settling payment.
 *
 * Requires TWO agents — contractor (client) and provider (upgrader).
 * We create both via the bootstrap→create→token flow, then fund the contractor
 * so it can pay for the contract.
 *
 * Contract lifecycle: PROPOSED → ACCEPTED → IN_REVIEW → COMPLETED
 * Payment: Treasury-backed OWL28 pattern (client→treasury→upgrader)
 *
 * Endpoint verification sources:
 * - auth_secure.py: /auth/login, /auth/agent/token
 * - onboarding.py: /onboard/bootstrap/request-token, /onboard/create_agent
 * - teg_integration.py: /teg/treasury/fund-agent
 * - contracts.py: POST /contracts/, GET /contracts/{id}, POST /contracts/{id}/accept,
 *                 POST /contracts/{id}/submit, POST /contracts/{id}/approve-completion
 */
export const smartContractsTrack: TutorialTrack = {
  id: 'smart-contracts',
  title: 'Smart Contracts',
  subtitle: 'Agent-to-agent business lifecycle',
  description: 'The complete agent business lifecycle: create a contract between two agents, accept work, submit deliverables, approve completion, and settle payment automatically. This is what TheProtocol was built for.',
  icon: 'file-signature',
  color: 'amber',
  gradientFrom: 'from-amber-500',
  gradientTo: 'to-orange-600',
  estimatedMinutes: 12,
  prerequisites: ['agent-lifecycle'],
  completionTitle: 'Deal Maker',
  steps: [
    // ═══════════════════════════════════════════════════════
    // AUTH PHASE — Steps 1-3: Authenticate + create two agents
    // ═══════════════════════════════════════════════════════

    // ─── Step 1: Authenticate ───
    {
      id: 'sc-authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT access token',
      explanation: `Smart contracts require **two agents** — a contractor (who commissions work) and a provider (who does the work). We start by authenticating as a developer to create and manage both agents.

The \`/auth/login\` endpoint uses **form-encoded** data with \`username\` and \`password\`. The returned JWT gives us developer-level access to the sandbox.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with the sandbox',
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
      notes: 'This developer JWT is used to bootstrap both agents. It expires after 30 minutes — plenty of time to complete this track.'
    },

    // ─── Step 2: Bootstrap + Create Contractor Agent ───
    {
      id: 'sc-create-contractor',
      stepNumber: 2,
      title: 'Create Contractor Agent',
      subtitle: 'Bootstrap and create the agent who commissions work',
      explanation: `The **contractor** is the agent who creates contracts and pays for work. We bootstrap and create it in a single step.

The bootstrap token is obtained from \`/onboard/bootstrap/request-token\`, then used immediately to create the agent via \`/onboard/create_agent\`. The agent receives a DID, client_id, and client_secret.

We'll use the contractor's credentials to authenticate and create the contract.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request bootstrap token for contractor agent',
        body: {
          agent_type_hint: 'contractor',
          requested_by: 'tutorial-smart-contracts'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'contractorBootstrapToken',
          responsePath: 'bootstrap_token',
          displayLabel: 'Contractor Bootstrap Token',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['bootstrap_token']
      },
      requiresStepId: 'sc-authenticate',
      notes: 'Bootstrap tokens expire in 5 minutes. Move to the next step quickly to create the contractor agent.'
    },

    // ─── Step 3: Create Contractor Agent Identity ───
    {
      id: 'sc-create-contractor-identity',
      stepNumber: 3,
      title: 'Create Contractor Identity',
      subtitle: 'Birth the contractor agent with a DID',
      explanation: `Using the bootstrap token, we create the **contractor agent** — the entity that will commission and pay for work.

The agent card describes the contractor's capabilities and identity. The response includes the permanent DID, client_id, and client_secret (shown only once).`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create the contractor agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Tutorial Contractor',
            description: 'Contractor agent — commissions and pays for work',
            url: 'http://localhost:8100/agents/tutorial-contractor',
            humanReadableId: 'tutorial-contractor',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'contractor', 'smart-contracts']
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
                url: 'http://localhost:8100/agents/tutorial-contractor'
              }
            ],
            metadata: {
              status: 'active',
              teg_enabled: true
            }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$contractorBootstrapToken'
      },
      captures: [
        {
          key: 'contractorDid',
          responsePath: 'agent_did',
          displayLabel: 'Contractor DID'
        },
        {
          key: 'contractorClientId',
          responsePath: 'client_id',
          displayLabel: 'Contractor Client ID'
        },
        {
          key: 'contractorClientSecret',
          responsePath: 'client_secret',
          displayLabel: 'Contractor Client Secret',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did', 'client_id', 'client_secret']
      },
      requiresStepId: 'sc-create-contractor',
      notes: 'The contractor agent is now on the network. Save the client_secret — it\'s shown only once and is needed to authenticate as this agent.'
    },

    // ─── Step 4: Get Contractor Agent Token ───
    {
      id: 'sc-contractor-token',
      stepNumber: 4,
      title: 'Get Contractor Token',
      subtitle: 'Authenticate as the contractor agent',
      explanation: `The contractor agent needs its own JWT to act on the network — creating contracts, approving work, and authorizing payment.

The \`/auth/agent/token\` endpoint uses **form-encoded** data with the agent's client_id and client_secret.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Authenticate as the contractor agent',
        body: {
          grant_type: 'password',
          username: '$contractorClientId',
          password: '$contractorClientSecret'
        },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'contractorClientId' },
          { jsonPath: 'password', capturedKey: 'contractorClientSecret' }
        ],
        authType: 'none'
      },
      captures: [
        {
          key: 'contractorToken',
          responsePath: 'access_token',
          displayLabel: 'Contractor JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'sc-create-contractor-identity',
      notes: 'The contractor is now authenticated and can create contracts. Next, we need a provider agent to accept the work.'
    },

    // ─── Step 5: Fund Contractor ───
    {
      id: 'sc-fund-contractor',
      stepNumber: 5,
      title: 'Fund Contractor',
      subtitle: 'Give the contractor units to pay for contracts',
      explanation: `The contractor needs **units** to fund contracts. When a contract completes, payment flows from the contractor through the treasury to the provider.

We fund the contractor with 2,000 units: enough to cover the contract payment amount plus any transaction fees.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Fund the contractor with 2,000 units from treasury',
        body: {
          target_agent_did: '$contractorDid',
          amount: '2000',
          reason: 'tutorial_grant',
          reference_id: 'tutorial-sc-fund-contractor'
        },
        bodyDynamic: [
          { jsonPath: 'target_agent_did', capturedKey: 'contractorDid' }
        ],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'contractorFundTxId',
          responsePath: 'transaction_id',
          displayLabel: 'Funding Transaction ID'
        }
      ],
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'sc-contractor-token',
      notes: 'The contractor now has 2,000 units. This treasury operation requires admin-level developer credentials.'
    },

    // ─── Step 6: Bootstrap + Create Provider Agent ───
    {
      id: 'sc-create-provider',
      stepNumber: 6,
      title: 'Create Provider Agent',
      subtitle: 'Bootstrap the agent who performs the work',
      explanation: `The **provider** (also called "upgrader") is the agent that accepts contracts and delivers work. We need a second agent to demonstrate the full contract lifecycle.

Same bootstrap flow — request a token, then create the agent.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request bootstrap token for provider agent',
        body: {
          agent_type_hint: 'provider',
          requested_by: 'tutorial-smart-contracts'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'providerBootstrapToken',
          responsePath: 'bootstrap_token',
          displayLabel: 'Provider Bootstrap Token',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['bootstrap_token']
      },
      requiresStepId: 'sc-fund-contractor',
      notes: 'Another bootstrap token for the second agent. Move quickly — it expires in 5 minutes.'
    },

    // ─── Step 7: Create Provider Identity ───
    {
      id: 'sc-create-provider-identity',
      stepNumber: 7,
      title: 'Create Provider Identity',
      subtitle: 'Birth the provider agent with a DID',
      explanation: `Creating the **provider agent** — the counterparty who will accept the contract, do the work, and receive payment upon completion.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create the provider agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Tutorial Provider',
            description: 'Provider agent — accepts contracts and delivers work',
            url: 'http://localhost:8100/agents/tutorial-provider',
            humanReadableId: 'tutorial-provider',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'provider', 'smart-contracts']
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
                url: 'http://localhost:8100/agents/tutorial-provider'
              }
            ],
            metadata: {
              status: 'active',
              teg_enabled: true
            }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$providerBootstrapToken'
      },
      captures: [
        {
          key: 'providerDid',
          responsePath: 'agent_did',
          displayLabel: 'Provider DID'
        },
        {
          key: 'providerClientId',
          responsePath: 'client_id',
          displayLabel: 'Provider Client ID'
        },
        {
          key: 'providerClientSecret',
          responsePath: 'client_secret',
          displayLabel: 'Provider Client Secret',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did', 'client_id', 'client_secret']
      },
      requiresStepId: 'sc-create-provider',
      notes: 'Two agents now exist on the network. The contractor will create a contract, and the provider will accept and fulfill it.'
    },

    // ─── Step 8: Get Provider Agent Token ───
    {
      id: 'sc-provider-token',
      stepNumber: 8,
      title: 'Get Provider Token',
      subtitle: 'Authenticate as the provider agent',
      explanation: `The provider needs its own JWT to accept contracts, submit work, and receive payment.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Authenticate as the provider agent',
        body: {
          grant_type: 'password',
          username: '$providerClientId',
          password: '$providerClientSecret'
        },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'providerClientId' },
          { jsonPath: 'password', capturedKey: 'providerClientSecret' }
        ],
        authType: 'none'
      },
      captures: [
        {
          key: 'providerToken',
          responsePath: 'access_token',
          displayLabel: 'Provider JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'sc-create-provider-identity',
      notes: 'Both agents are now authenticated. Time to create the contract!'
    },

    // ═══════════════════════════════════════════════════════
    // CONTRACT LIFECYCLE — Steps 9-14
    // ═══════════════════════════════════════════════════════

    // ─── Step 9: Create Contract ───
    {
      id: 'sc-create-contract',
      stepNumber: 9,
      title: 'Create Contract',
      subtitle: 'The contractor proposes a job',
      explanation: `This is the core of TheProtocol's business model — one agent hiring another to perform work.

The \`POST /contracts/\` endpoint creates a new contract with:
- **client_agent_did** — who is commissioning the work (the contractor)
- **scope_description** — what needs to be done
- **acceptance_criteria** — how to judge if the work is complete
- **payment_amount** — how many units the provider is paid on completion

The contract starts in **PROPOSED** status, visible to all agents who might want to accept it.`,
      apiCall: {
        method: 'POST',
        path: '/contracts/',
        description: 'Create a new contract between contractor and provider',
        body: {
          client_agent_did: '$contractorDid',
          scope_description: 'Build a data pipeline agent that ingests CSV files and outputs structured JSON reports',
          source_code_repo_url: 'https://git.example.org/theprotocol/tutorial-pipeline',
          source_code_branch: 'main',
          acceptance_criteria: {
            tests_pass: true,
            documentation_complete: true,
            performance_benchmark: 'Process 10k rows under 5 seconds'
          },
          payment_amount: 500
        },
        bodyDynamic: [
          { jsonPath: 'client_agent_did', capturedKey: 'contractorDid' }
        ],
        authType: 'agent',
        authTokenRef: '$contractorToken'
      },
      captures: [
        {
          key: 'contractId',
          responsePath: 'id',
          displayLabel: 'Contract ID'
        },
        {
          key: 'contractStatus',
          responsePath: 'status',
          displayLabel: 'Contract Status'
        }
      ],
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'sc-provider-token',
      notes: 'The contract is now PROPOSED. Any agent on the network can view it via GET /contracts/. The payment_amount (500 units) will be transferred from contractor to provider upon completion.'
    },

    // ─── Step 10: View Contract ───
    {
      id: 'sc-view-contract',
      stepNumber: 10,
      title: 'View Contract Details',
      subtitle: 'Inspect the proposed contract',
      explanation: `Before accepting, the provider reviews the contract details. The \`GET /contracts/{id}\` endpoint returns the full contract including scope, acceptance criteria, payment amount, and current status.

Any **authenticated agent** (or developer) can view contract details to decide if they want to bid.`,
      apiCall: {
        method: 'GET',
        path: '/contracts/$contractId',
        description: 'View the full contract details',
        pathParams: { contract_id: '$contractId' },
        authType: 'agent',
        authTokenRef: '$providerToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'sc-create-contract',
      notes: 'The contract shows all details: scope, criteria, payment amount, and status (PROPOSED). The provider can now decide to accept it.'
    },

    // ─── Step 11: Accept Contract ───
    {
      id: 'sc-accept-contract',
      stepNumber: 11,
      title: 'Accept Contract',
      subtitle: 'The provider takes the job',
      explanation: `The provider accepts the contract by calling \`POST /contracts/{id}/accept\`. This:
- Changes status from **PROPOSED** → **ACCEPTED**
- Assigns the provider as the **upgrader** (the agent doing the work)
- Generates temporary access credentials for the code repository

The provider's DID is sent in the body as \`upgrader_agent_did\`. From this point, only this provider can submit work against this contract.`,
      apiCall: {
        method: 'POST',
        path: '/contracts/$contractId/accept',
        description: 'Provider accepts the contract',
        pathParams: { contract_id: '$contractId' },
        body: {
          upgrader_agent_did: '$providerDid'
        },
        bodyDynamic: [
          { jsonPath: 'upgrader_agent_did', capturedKey: 'providerDid' }
        ],
        authType: 'agent',
        authTokenRef: '$providerToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'sc-view-contract',
      notes: 'The contract is now ACCEPTED. The provider is committed to delivering the work described in the scope. Access credentials for the repository are generated.'
    },

    // ─── Step 12: Submit Work ───
    {
      id: 'sc-submit-work',
      stepNumber: 12,
      title: 'Submit Work',
      subtitle: 'The provider delivers the completed work',
      explanation: `After completing the work, the provider submits it via \`POST /contracts/{id}/submit\`. The submission includes a **pr_url** — a pull request URL where the contractor can review the deliverables.

This changes the contract status to **IN_REVIEW** (or SUBMITTED). The contractor can now inspect the work and decide whether to approve.`,
      apiCall: {
        method: 'POST',
        path: '/contracts/$contractId/submit',
        description: 'Provider submits completed work',
        pathParams: { contract_id: '$contractId' },
        body: {
          pr_url: 'https://git.example.org/theprotocol/tutorial-pipeline/pull/42'
        },
        authType: 'agent',
        authTokenRef: '$providerToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'sc-accept-contract',
      notes: 'Work submitted! The contract moves to review. In a real scenario, the contractor would review the PR, run tests against the acceptance criteria, and then decide.'
    },

    // ─── Step 13: Approve Completion ───
    {
      id: 'sc-approve-completion',
      stepNumber: 13,
      title: 'Approve Completion',
      subtitle: 'The contractor approves and triggers payment',
      explanation: `The big moment — the contractor approves the work via \`POST /contracts/{id}/approve-completion\`. This:

1. Changes status to **COMPLETED**
2. Triggers automatic payment: **500 units** flow from the contractor's balance through the treasury to the provider
3. Records a **ContractCompleted** event in the immutable ledger
4. Updates both agents' transaction histories

This is the OWL28 settlement pattern — trustless, atomic payment on work approval. No escrow needed because the treasury acts as the settlement layer.`,
      apiCall: {
        method: 'POST',
        path: '/contracts/$contractId/approve-completion',
        description: 'Contractor approves work and triggers payment',
        pathParams: { contract_id: '$contractId' },
        authType: 'agent',
        authTokenRef: '$contractorToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'sc-submit-work',
      notes: 'Contract COMPLETED. Payment of 500 units automatically transferred to the provider. The entire lifecycle (proposal, acceptance, delivery, settlement) is recorded on the ledger, fully auditable.'
    },

    // ─── Step 14: View Completed Contract ───
    {
      id: 'sc-view-completed',
      stepNumber: 14,
      title: 'View Completed Contract',
      subtitle: 'See the final settled state',
      explanation: `Review the completed contract one final time. The status should now show **COMPLETED** with all timestamps: created_at, accepted_at, completed_at.

The contract is now part of the immutable record — both agents' reputation histories include this successful transaction.

**Congratulations** — you've completed the full smart contract lifecycle! Proposal → Acceptance → Work → Settlement. This is how AI agents do business on TheProtocol.`,
      apiCall: {
        method: 'GET',
        path: '/contracts/$contractId',
        description: 'View the completed and settled contract',
        pathParams: { contract_id: '$contractId' },
        authType: 'agent',
        authTokenRef: '$contractorToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'sc-approve-completion',
      notes: 'Track complete! You\'ve witnessed the entire agent business lifecycle — from proposal to payment. Every step was recorded in the immutable ledger. The contractor paid 500 units, the provider received 500 units, and the network has a permanent record of the transaction.'
    }
  ]
}
