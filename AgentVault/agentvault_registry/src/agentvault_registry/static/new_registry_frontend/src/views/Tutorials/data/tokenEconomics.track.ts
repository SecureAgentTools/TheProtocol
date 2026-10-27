import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 2: Token Economics — How money moves between agents
 *
 * 14 steps:
 * SETUP (1-7): Authenticate → Bootstrap A → Create Agent A → Agent A Token →
 *              Bootstrap B → Create Agent B → Agent B Token
 * TOKEN ECONOMICS (8-14): Treasury Balance → Fund A → Fund B → Transfer A→B →
 *                          Transaction History → Fee Config → Reputation Signal
 *
 * Self-contained — creates two agents (Alpha/Beta) from scratch.
 * Prerequisites: ['agent-lifecycle'] (UI soft gate only)
 *
 * Endpoint verification sources:
 * - auth_secure.py: /auth/login (form-encoded), /auth/agent/token (form-encoded)
 * - onboarding.py: /onboard/bootstrap/request-token, /onboard/create_agent
 * - teg_integration.py: /teg/treasury/balance (line 945), /teg/treasury/fund-agent (line 2809),
 *   /teg/transfer (line 533), /teg/transactions (line 687), /teg/fees/config (line 908),
 *   /teg/transactions/{id}/reputation-signal (line 761)
 */
export const tokenEconomicsTrack: TutorialTrack = {
  id: 'token-economics',
  title: 'Units & Fees',
  subtitle: 'How units move between agents',
  description: 'Learn how units move: treasury funding, peer-to-peer transfers, transaction history, fee structure, and reputation signaling between agents.',
  icon: 'coins',
  color: 'amber',
  gradientFrom: 'from-amber-500',
  gradientTo: 'to-orange-600',
  estimatedMinutes: 12,
  prerequisites: ['agent-lifecycle'],
  completionTitle: 'Unit Mover',
  steps: [
    // ═══════════════════════════════════════════════════════
    // SETUP PHASE — Steps 1-7: Create two agents (A and B)
    // ═══════════════════════════════════════════════════════

    // ─── Step 1: Authenticate ───
    {
      id: 'authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT access token',
      explanation: `This step is identical to Track 1. We authenticate with the pre-provisioned tutorial account to get a developer JWT.

The \`/auth/login\` endpoint uses **OAuth2 Password Flow** with form-encoded data. The returned JWT authorizes developer-level operations like bootstrapping agents and funding from treasury.`,
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
      notes: 'Setup step — identical to Track 1. This developer JWT will be used to bootstrap and fund both agents.'
    },

    // ─── Step 2: Bootstrap Token (Agent A) ───
    {
      id: 'bootstrap-agent-a',
      stepNumber: 2,
      title: 'Bootstrap Token (Agent A)',
      subtitle: 'Get a creation credential for the first agent',
      explanation: `Token Economics requires **two agents** — a sender (Alpha) and a receiver (Beta). We start by bootstrapping Agent A.

Each bootstrap token is single-use. We'll need a separate token for each agent we create.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token for Agent A (Token Trader Alpha)',
        body: {
          agent_type_hint: 'tutorial_trader_a',
          requested_by: 'tutorial-user'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'bootstrapTokenA',
          responsePath: 'bootstrap_token',
          displayLabel: 'Bootstrap Token (A)',
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

    // ─── Step 3: Create Agent A ───
    {
      id: 'create-agent-a',
      stepNumber: 3,
      title: 'Create Agent A (Token Trader Alpha)',
      subtitle: 'Birth the first agent — the sender',
      explanation: `Creating **Token Trader Alpha** — this agent will send units in the transfer step.

The \`/onboard/create_agent\` endpoint exchanges the bootstrap token for permanent credentials: an Agent DID, client_id, and client_secret. The Agent Card defines the agent's public profile.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create Agent A using the bootstrap token',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Token Trader Alpha',
            description: 'Sender agent for the Token Economics tutorial: demonstrates transfers of units',
            url: 'http://localhost:8100/agents/token-trader-alpha',
            humanReadableId: 'token-trader-alpha',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'token-economics', 'sender']
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
                url: 'http://localhost:8100/agents/token-trader-alpha'
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
          displayLabel: 'Agent A DID'
        },
        {
          key: 'clientIdA',
          responsePath: 'client_id',
          displayLabel: 'Agent A Client ID'
        },
        {
          key: 'clientSecretA',
          responsePath: 'client_secret',
          displayLabel: 'Agent A Client Secret',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did', 'client_id', 'client_secret']
      },
      requiresStepId: 'bootstrap-agent-a',
      notes: 'Agent A (Token Trader Alpha) is now on the network. Next we get its JWT, then repeat the process for Agent B.'
    },

    // ─── Step 4: Get Agent A Token ───
    {
      id: 'get-agent-a-token',
      stepNumber: 4,
      title: 'Get Agent A Token',
      subtitle: 'Authenticate as Agent A',
      explanation: `Authenticate as Agent A using its client credentials. The \`/auth/agent/token\` endpoint uses **form-encoded** OAuth2 client credentials flow.

Agent A needs its own JWT to perform agent-level operations like initiating transfers.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Get a JWT for Agent A using its client credentials',
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
          displayLabel: 'Agent A JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'create-agent-a',
      notes: 'Agent A is now fully authenticated. Next we create Agent B — the receiver.'
    },

    // ─── Step 5: Bootstrap Token (Agent B) ───
    {
      id: 'bootstrap-agent-b',
      stepNumber: 5,
      title: 'Bootstrap Token (Agent B)',
      subtitle: 'Get a creation credential for the second agent',
      explanation: `Now we bootstrap **Agent B** — the receiver in our transfer. Each agent requires its own bootstrap token.

Same endpoint, same developer auth — just a new single-use token for the second agent.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token for Agent B (Token Trader Beta)',
        body: {
          agent_type_hint: 'tutorial_trader_b',
          requested_by: 'tutorial-user'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'bootstrapTokenB',
          responsePath: 'bootstrap_token',
          displayLabel: 'Bootstrap Token (B)',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['bootstrap_token']
      },
      requiresStepId: 'get-agent-a-token',
      notes: 'Bootstrap tokens expire in 5 minutes. Proceed to Step 6 promptly.'
    },

    // ─── Step 6: Create Agent B ───
    {
      id: 'create-agent-b',
      stepNumber: 6,
      title: 'Create Agent B (Token Trader Beta)',
      subtitle: 'Birth the second agent — the receiver',
      explanation: `Creating **Token Trader Beta** — this agent will receive units in the transfer step.

Same process as Agent A: bootstrap token in the \`Bootstrap-Token\` header, full Agent Card in the body. Different name, different humanReadableId.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create Agent B using the bootstrap token',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Token Trader Beta',
            description: 'Receiver agent for the Token Economics tutorial: receives transfers of units',
            url: 'http://localhost:8100/agents/token-trader-beta',
            humanReadableId: 'token-trader-beta',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'token-economics', 'receiver']
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
                url: 'http://localhost:8100/agents/token-trader-beta'
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
          displayLabel: 'Agent B DID'
        },
        {
          key: 'clientIdB',
          responsePath: 'client_id',
          displayLabel: 'Agent B Client ID'
        },
        {
          key: 'clientSecretB',
          responsePath: 'client_secret',
          displayLabel: 'Agent B Client Secret',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did', 'client_id', 'client_secret']
      },
      requiresStepId: 'bootstrap-agent-b',
      notes: 'Agent B (Token Trader Beta) is now on the network. Both agents are created: time to fund them and start moving units.'
    },

    // ─── Step 7: Get Agent B Token ───
    {
      id: 'get-agent-b-token',
      stepNumber: 7,
      title: 'Get Agent B Token',
      subtitle: 'Authenticate as Agent B',
      explanation: `Authenticate as Agent B using its client credentials. Same flow as Step 4.

We capture Agent B's JWT for completeness, though it's not strictly needed in this track — the sender (Agent A) initiates transfers.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Get a JWT for Agent B using its client credentials',
        body: {
          grant_type: 'password',
          username: '$clientIdB',
          password: '$clientSecretB'
        },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'clientIdB' },
          { jsonPath: 'password', capturedKey: 'clientSecretB' }
        ],
        authType: 'none'
      },
      captures: [
        {
          key: 'agentTokenB',
          responsePath: 'access_token',
          displayLabel: 'Agent B JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'create-agent-b',
      notes: 'Setup complete! Both agents are created and authenticated. Now we explore how units move.'
    },

    // ═══════════════════════════════════════════════════════
    // TOKEN ECONOMICS — Steps 8-14: The real content
    // ═══════════════════════════════════════════════════════

    // ─── Step 8: Check Treasury Balance ───
    {
      id: 'check-treasury',
      stepNumber: 8,
      title: 'Check Treasury Balance',
      subtitle: 'View the frame\'s treasury account',
      explanation: `The **treasury** is the frame's system account for its units. New units are created only there, by the frame's operator, and reach agents as grants from it.

The \`/teg/treasury/balance\` endpoint returns the treasury's current balance. This requires **developer-level** authorization: only registered developers can inspect the treasury.`,
      apiCall: {
        method: 'GET',
        path: '/teg/treasury/balance',
        description: 'Check the network treasury\'s balance',
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'get-agent-b-token',
      notes: 'The treasury balance varies depending on how many grants have been issued. In the sandbox, it starts with a large initial supply.'
    },

    // ─── Step 9: Fund Agent A ───
    {
      id: 'fund-agent-a',
      stepNumber: 9,
      title: 'Fund Agent A (5,000 units)',
      subtitle: 'Grant units from treasury to the sender',
      explanation: `Now we fund **Agent A** with 5,000 units from the network treasury. This is how agents get their first units.

The \`/teg/treasury/fund-agent\` endpoint requires:
- \`target_agent_did\` — which agent to fund
- \`amount\` — how many units (as a string for decimal precision)
- \`reason\` — categorization of the grant
- \`reference_id\` — unique reference for audit trail

This is a **developer-level** operation — agents can't fund themselves from treasury.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Transfer 5,000 units from treasury to Agent A',
        body: {
          target_agent_did: '$agentDidA',
          amount: '5000',
          reason: 'tutorial_grant',
          reference_id: 'tut2-fund-a'
        },
        bodyDynamic: [
          { jsonPath: 'target_agent_did', capturedKey: 'agentDidA' }
        ],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'check-treasury',
      notes: 'Agent A now has 5,000 units (plus any genesis grant from creation). These units are liquid and ready for transfer.'
    },

    // ─── Step 10: Fund Agent B ───
    {
      id: 'fund-agent-b',
      stepNumber: 10,
      title: 'Fund Agent B (5,000 units)',
      subtitle: 'Grant units from treasury to the receiver',
      explanation: `Fund **Agent B** with 5,000 units as well. Both agents need a balance to participate in the economy.

While Agent B will *receive* units in our transfer, having an existing balance shows that transfers add to existing holdings rather than creating balances from zero.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Transfer 5,000 units from treasury to Agent B',
        body: {
          target_agent_did: '$agentDidB',
          amount: '5000',
          reason: 'tutorial_grant',
          reference_id: 'tut2-fund-b'
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
      requiresStepId: 'fund-agent-a',
      notes: 'Both agents are now funded. Agent A: 5,000 units. Agent B: 5,000 units. Time for a peer-to-peer transfer.'
    },

    // ─── Step 11: Transfer A→B ───
    {
      id: 'transfer-a-to-b',
      stepNumber: 11,
      title: 'Transfer Units (A → B)',
      subtitle: 'Send 500 units from Alpha to Beta',
      explanation: `The core of the economy: a **peer-to-peer transfer** between two agents.

The \`/teg/transfer\` endpoint moves units from the **authenticated agent** (the sender) to a receiver. The sender must authenticate with their own Agent JWT.

Request body:
- \`receiver_agent_id\` — the DID of the receiving agent
- \`amount\` — how many units to send (as a string)
- \`message\` — optional note attached to the transaction

The TEG deducts a small transfer fee from the sender. After this transfer:
- Agent A: ~4,499 units (5,000 - 500 - fee)
- Agent B: ~5,500 units (5,000 + 500)`,
      apiCall: {
        method: 'POST',
        path: '/teg/transfer',
        description: 'Transfer 500 units from Agent A to Agent B',
        body: {
          receiver_agent_id: '$agentDidB',
          amount: '500',
          message: 'Tutorial transfer: Alpha pays Beta for services rendered'
        },
        bodyDynamic: [
          { jsonPath: 'receiver_agent_id', capturedKey: 'agentDidB' }
        ],
        authType: 'agent',
        authTokenRef: '$agentTokenA'
      },
      captures: [
        {
          key: 'transferTxId',
          responsePath: 'transaction_id',
          displayLabel: 'Transfer Transaction ID'
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['transaction_id']
      },
      requiresStepId: 'fund-agent-b',
      notes: 'The transfer is atomic — either it completes fully or not at all. The TEG ensures double-spend protection and balance consistency.'
    },

    // ─── Step 12: View Transaction History ───
    {
      id: 'view-transactions',
      stepNumber: 12,
      title: 'View Transaction History',
      subtitle: 'See Agent A\'s ledger of transactions',
      explanation: `Every movement of units is recorded on the agent's **transaction ledger**. The \`/teg/transactions\` endpoint returns a paginated list of all transactions for the authenticated agent.

Each transaction record includes: type (transfer, grant, fee), amount, counterparty, timestamp, and status. This is the agent's financial history — fully transparent and auditable.`,
      apiCall: {
        method: 'GET',
        path: '/teg/transactions',
        description: 'Retrieve Agent A\'s transaction history',
        authType: 'agent',
        authTokenRef: '$agentTokenA'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'transfer-a-to-b',
      notes: 'You should see multiple transactions: the genesis grant (from agent creation), the treasury funding (Step 9), and the transfer to Agent B (Step 11).'
    },

    // ─── Step 13: Check Fee Config ───
    {
      id: 'check-fee-config',
      stepNumber: 13,
      title: 'Check Fee Configuration',
      subtitle: 'View the network\'s transfer fee structure',
      explanation: `The TEG charges a small fee on transfers to fund network operations. The \`/teg/fees/config\` endpoint returns the current fee structure.

This is a **public endpoint** — no authentication required. Anyone can inspect the fee schedule. Fee parameters include:
- **Transfer fee amount** — flat fee per transfer
- **Fee collection address** — where fees accumulate

Fee governance is controlled by the Agent Senate (Track 3: Locks & Governance).`,
      apiCall: {
        method: 'GET',
        path: '/teg/fees/config',
        description: 'View the network\'s current transfer fee configuration',
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'view-transactions',
      notes: 'The fee config is set by governance proposals. In the sandbox, default fees are configured at startup.'
    },

    // ─── Step 14: Reputation Signal ───
    {
      id: 'reputation-signal',
      stepNumber: 14,
      title: 'Send Reputation Signal',
      subtitle: 'Rate the transfer experience',
      explanation: `After a transaction, agents can signal the quality of the interaction via **reputation signals**. This builds the decentralized trust graph.

The \`/teg/transactions/{transaction_id}/reputation-signal\` endpoint accepts:
- \`signal_value\` — \`+1\` (positive) or \`-1\` (negative)

Only the **sender** of a transaction can emit a reputation signal for it. The signal is recorded immutably and affects the receiver's reputation score.

This is the foundation of trustless agent-to-agent commerce — reputation built through real economic interactions.

**Congratulations** — you've completed the Token Economics track! You've seen the full lifecycle: treasury → funding → transfer → history → fees → reputation.`,
      apiCall: {
        method: 'POST',
        path: '/teg/transactions/$transferTxId/reputation-signal',
        description: 'Send a positive reputation signal for the transfer',
        pathParams: { transaction_id: '$transferTxId' },
        body: {
          signal_value: 1
        },
        authType: 'agent',
        authTokenRef: '$agentTokenA'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'check-fee-config',
      notes: 'Track complete! You\'ve explored treasury funding, peer-to-peer transfers, transaction history, fee structure, and reputation signaling. Next up: Locks & Governance, which locks units and votes on network proposals.'
    }
  ]
}
