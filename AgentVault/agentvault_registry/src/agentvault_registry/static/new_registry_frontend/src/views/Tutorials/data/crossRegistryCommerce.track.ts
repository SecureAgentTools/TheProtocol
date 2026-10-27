import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 8: Cross-Registry Commerce — Cross-registry agent discovery + token transfer
 *
 * 13 steps:
 * AUTH (1-2): Developer JWT (Reg A) → Developer JWT (Reg B)
 * ONBOARD SENDER (3-6): Bootstrap → Create Agent → Get Token → Fund (Registry A)
 * ONBOARD RECEIVER (7-10): Bootstrap → Create Agent → Get Token → Fund (Registry B)
 * COMMERCE (11-13): Balance before → Cross-registry transfer → Balance after
 *
 * Both agents are onboarded via proper API flow — no fake pre-seeded agents.
 * The sender lives on Registry A, the receiver on Registry B.
 * Cross-registry transfers use the 2PC (two-phase commit) protocol via TEG.
 *
 * Endpoint verification sources:
 * - auth_secure.py: /auth/login, /auth/agent/token
 * - onboarding.py: /onboard/bootstrap/request-token, /onboard/create_agent
 * - teg_integration.py: /teg/treasury/fund-agent, /teg/balance,
 *                       /teg/cross-registry-transfer, /teg/transactions
 */
export const crossRegistryCommerceTrack: TutorialTrack = {
  id: 'cross-registry-commerce',
  title: 'Cross-Registry Commerce',
  subtitle: 'Federation value in action',
  description: 'Create agents on two different registries, fund them, and transfer units across the federation boundary. See the real value of federation — sovereign registries connected through bilateral mTLS enabling cross-network commerce.',
  icon: 'arrow-right-left',
  color: 'teal',
  gradientFrom: 'from-teal-500',
  gradientTo: 'to-cyan-600',
  estimatedMinutes: 12,
  prerequisites: ['agent-lifecycle', 'federation'],
  completionTitle: 'Bridge Builder',
  steps: [
    // ═══════════════════════════════════════════════════════
    // AUTH PHASE — Steps 1-2: Authenticate on both registries
    // ═══════════════════════════════════════════════════════

    // ─── Step 1: Authenticate (Registry A) ───
    {
      id: 'xrc-authenticate-a',
      stepNumber: 1,
      title: 'Authenticate (Registry A)',
      subtitle: 'Obtain a JWT from the primary registry',
      explanation: `Cross-registry commerce requires agents on **two different registries**. We start by authenticating on Registry A — the default sandbox where our sending agent will live.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with Registry A (sandbox)',
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
      notes: 'Registry A developer JWT. We\'ll use this to onboard the sender agent.'
    },

    // ─── Step 2: Authenticate (Registry B) ───
    {
      id: 'xrc-authenticate-b',
      stepNumber: 2,
      title: 'Authenticate (Registry B)',
      subtitle: 'Obtain a JWT from the second registry',
      explanation: `Now we authenticate on **Registry B** — the federated peer registry. This is a **direct call** to Registry B's API.

Same credentials work on both registries because the tutorial admin account is seeded on both. The JWTs are different — each registry signs with its own secret.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with Registry B (sandbox) — direct call',
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
      requiresStepId: 'xrc-authenticate-a',
      notes: 'Registry B developer JWT. We\'ll use this to onboard the receiver agent on the peer registry.'
    },

    // ═══════════════════════════════════════════════════════
    // ONBOARD SENDER — Steps 3-6: Create agent on Registry A
    // ═══════════════════════════════════════════════════════

    // ─── Step 3: Bootstrap Sender ───
    {
      id: 'xrc-bootstrap-sender',
      stepNumber: 3,
      title: 'Bootstrap Sender Agent',
      subtitle: 'Request a bootstrap token on Registry A',
      explanation: `We need a real agent on Registry A to act as the **sender**. First, get a bootstrap token — a single-use credential that authorizes agent creation.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request bootstrap token for sender agent on Registry A',
        body: {
          agent_type_hint: 'commerce_sender',
          requested_by: 'tutorial-cross-registry'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'senderBootstrapToken',
          responsePath: 'bootstrap_token',
          displayLabel: 'Sender Bootstrap Token',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['bootstrap_token']
      },
      requiresStepId: 'xrc-authenticate-b',
      notes: 'Bootstrap token expires in 5 minutes. Move quickly to create the agent.'
    },

    // ─── Step 4: Create Sender Agent ───
    {
      id: 'xrc-create-sender',
      stepNumber: 4,
      title: 'Create Sender Agent',
      subtitle: 'Onboard the sender on Registry A',
      explanation: `Create the **sender agent** on Registry A. This agent will hold units and send them across the federation boundary to an agent on Registry B.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create sender agent on Registry A',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Commerce Sender',
            description: 'Tutorial agent — sends cross-registry transfers',
            url: 'http://localhost:8100/agents/commerce-sender',
            humanReadableId: 'commerce-sender',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'commerce', 'sender']
            },
            authSchemes: [
              {
                scheme: 'oauth2',
                client_id: 'pending',
                tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token'
              }
            ],
            service_endpoints: [
              { type: 'messaging', url: 'http://localhost:8100/agents/commerce-sender' }
            ],
            metadata: { status: 'active', teg_enabled: true }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$senderBootstrapToken'
      },
      captures: [
        { key: 'senderDid', responsePath: 'agent_did', displayLabel: 'Sender DID' },
        { key: 'senderClientId', responsePath: 'client_id', displayLabel: 'Sender Client ID' },
        { key: 'senderClientSecret', responsePath: 'client_secret', displayLabel: 'Sender Secret', sensitive: true }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did', 'client_id', 'client_secret']
      },
      requiresStepId: 'xrc-bootstrap-sender',
      notes: 'Sender agent created on Registry A with a real DID. Save the client_secret — shown only once.'
    },

    // ─── Step 5: Get Sender Token ───
    {
      id: 'xrc-sender-token',
      stepNumber: 5,
      title: 'Get Sender Token',
      subtitle: 'Authenticate as the sender agent',
      explanation: `Authenticate as the sender agent to get an agent JWT for TEG operations (balance, transfers).`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Authenticate as the sender agent',
        body: {
          grant_type: 'password',
          username: '$senderClientId',
          password: '$senderClientSecret'
        },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'senderClientId' },
          { jsonPath: 'password', capturedKey: 'senderClientSecret' }
        ],
        authType: 'none'
      },
      captures: [
        { key: 'senderAgentToken', responsePath: 'access_token', displayLabel: 'Sender Agent JWT', sensitive: true }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'xrc-create-sender',
      notes: 'The sender can now act on the network — checking balance, initiating transfers.'
    },

    // ─── Step 6: Fund Sender ───
    {
      id: 'xrc-fund-sender',
      stepNumber: 6,
      title: 'Fund Sender Agent',
      subtitle: 'Give the sender units for the transfer',
      explanation: `The sender needs units to transfer across the federation boundary. We fund it with 500 units from the treasury: enough for the cross-registry transfer plus fees.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Fund sender with 500 units from treasury',
        body: {
          target_agent_did: '$senderDid',
          amount: '500',
          reason: 'tutorial_grant',
          reference_id: 'tutorial-xrc-fund-sender'
        },
        bodyDynamic: [
          { jsonPath: 'target_agent_did', capturedKey: 'senderDid' }
        ],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'xrc-sender-token',
      notes: 'Sender now has 500 units. Next we create the receiver on Registry B.'
    },

    // ═══════════════════════════════════════════════════════
    // ONBOARD RECEIVER — Steps 7-9: Create agent on Registry B
    // ═══════════════════════════════════════════════════════

    // ─── Step 7: Bootstrap Receiver on Registry B ───
    {
      id: 'xrc-bootstrap-receiver',
      stepNumber: 7,
      title: 'Bootstrap Receiver Agent (Registry B)',
      subtitle: 'Request a bootstrap token on the peer registry',
      explanation: `Now we create the **receiver agent** on **Registry B** — the federated peer. This is a **direct call** to Registry B's API.

The receiver agent will live on a completely different registry with its own database, JWT secrets, and TEG instance. The cross-registry transfer protocol bridges these two sovereign systems.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request bootstrap token on Registry B — direct call',
        body: {
          agent_type_hint: 'commerce_receiver',
          requested_by: 'tutorial-cross-registry'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevTokenB',
        targetBase: '/sandbox-b'
      },
      captures: [
        { key: 'receiverBootstrapToken', responsePath: 'bootstrap_token', displayLabel: 'Receiver Bootstrap Token', sensitive: true }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['bootstrap_token']
      },
      requiresStepId: 'xrc-fund-sender',
      notes: 'Bootstrap token from Registry B. Move quickly — it expires in 5 minutes.'
    },

    // ─── Step 8: Create Receiver Agent on Registry B ───
    {
      id: 'xrc-create-receiver',
      stepNumber: 8,
      title: 'Create Receiver Agent (Registry B)',
      subtitle: 'Onboard the receiver on the peer registry',
      explanation: `Create the **receiver agent** on Registry B. This agent will receive units from the sender on Registry A via the cross-registry 2PC protocol.

This is a **direct call** to Registry B — the agent lives entirely on the peer registry.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create receiver agent on Registry B — direct call',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Commerce Receiver',
            description: 'Tutorial agent — receives cross-registry transfers',
            url: 'http://localhost:8101/agents/commerce-receiver',
            humanReadableId: 'commerce-receiver',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'commerce', 'receiver']
            },
            authSchemes: [
              {
                scheme: 'oauth2',
                client_id: 'pending',
                tokenUrl: 'http://registry-test-b:8000/api/v1/auth/agent/token'
              }
            ],
            service_endpoints: [
              { type: 'messaging', url: 'http://localhost:8101/agents/commerce-receiver' }
            ],
            metadata: { status: 'active', teg_enabled: true }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$receiverBootstrapToken',
        targetBase: '/sandbox-b'
      },
      captures: [
        { key: 'receiverDid', responsePath: 'agent_did', displayLabel: 'Receiver DID' },
        { key: 'receiverClientId', responsePath: 'client_id', displayLabel: 'Receiver Client ID' },
        { key: 'receiverClientSecret', responsePath: 'client_secret', displayLabel: 'Receiver Secret', sensitive: true }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did', 'client_id', 'client_secret']
      },
      requiresStepId: 'xrc-bootstrap-receiver',
      notes: 'Receiver agent created on Registry B. Two agents now exist on two different sovereign registries — connected only by federation.'
    },

    // ─── Step 9: Fund Receiver on Registry B ───
    {
      id: 'xrc-fund-receiver',
      stepNumber: 9,
      title: 'Fund Receiver (Registry B)',
      subtitle: 'Ensure the receiver exists in Registry B\'s TEG',
      explanation: `Fund the receiver with a small amount from Registry B's treasury. This ensures the receiver has a TEG account on Registry B and can receive cross-registry transfers.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Fund receiver with 10 units on Registry B (direct call)',
        body: {
          target_agent_did: '$receiverDid',
          amount: '10',
          reason: 'tutorial_grant',
          reference_id: 'tutorial-xrc-fund-receiver'
        },
        bodyDynamic: [
          { jsonPath: 'target_agent_did', capturedKey: 'receiverDid' }
        ],
        authType: 'developer',
        authTokenRef: '$sandboxDevTokenB',
        targetBase: '/sandbox-b'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'xrc-create-receiver',
      notes: 'Receiver funded on Registry B. Both agents are now ready for the cross-registry transfer.'
    },

    // ═══════════════════════════════════════════════════════
    // COMMERCE — Steps 10-13: The actual cross-registry transfer
    // ═══════════════════════════════════════════════════════

    // ─── Step 10: Check Balance Before ───
    {
      id: 'xrc-balance-before',
      stepNumber: 10,
      title: 'Check Balance (Before)',
      subtitle: 'Record the sender\'s balance before transfer',
      explanation: `Before sending units across registries, let's check the sender's current balance. This gives us a baseline to verify the transfer worked.`,
      apiCall: {
        method: 'GET',
        path: '/teg/balance',
        description: 'Check sender agent balance before cross-registry transfer',
        authType: 'agent',
        authTokenRef: '$senderAgentToken'
      },
      captures: [
        { key: 'balanceBefore', responsePath: 'balance', displayLabel: 'Balance Before Transfer' }
      ],
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'xrc-fund-receiver',
      notes: 'Record this balance — after the transfer, we\'ll verify the deduction.'
    },

    // ─── Step 11: Cross-Registry Transfer ───
    {
      id: 'xrc-transfer',
      stepNumber: 11,
      title: 'Cross-Registry Transfer',
      subtitle: 'Send units across the registry boundary',
      explanation: `The main event: sending units from an agent on **Registry A** to an agent on **Registry B**. This uses the **2PC (two-phase commit) protocol**:

1. Registry A debits the sender via its TEG
2. Registry A notifies Registry B via the federation mTLS channel
3. Registry B credits the receiver via its own TEG
4. Both registries record the transaction in their respective Event Stores

The \`/teg/cross-registry-transfer\` endpoint handles all of this atomically. If any step fails, the entire transaction rolls back.

This is the **Sovereign Settlement Protocol** in action — trustless, atomic value transfer across sovereign registry boundaries.`,
      apiCall: {
        method: 'POST',
        path: '/teg/cross-registry-transfer',
        description: 'Transfer 50 units from Registry A agent to Registry B agent',
        body: {
          receiver_did: '$receiverDid',
          amount: '50',
          message: 'Cross-registry payment from tutorial'
        },
        bodyDynamic: [
          { jsonPath: 'receiver_did', capturedKey: 'receiverDid' }
        ],
        authType: 'agent',
        authTokenRef: '$senderAgentToken'
      },
      captures: [
        { key: 'crossRegTxId', responsePath: 'transaction_id', displayLabel: 'Cross-Registry Transaction ID' }
      ],
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'xrc-balance-before',
      notes: '50 units transferred across the registry boundary! The 2PC protocol ensures atomicity — either both sides commit or neither does.'
    },

    // ─── Step 12: Check Balance After ───
    {
      id: 'xrc-balance-after',
      stepNumber: 12,
      title: 'Check Balance (After)',
      subtitle: 'Verify the transfer deducted correctly',
      explanation: `Check the sender's balance again. It should be reduced by **50 units** (plus any transaction fee).

The difference between the before and after balances proves the cross-registry transfer was real — actual value moved across the federation boundary.`,
      apiCall: {
        method: 'GET',
        path: '/teg/balance',
        description: 'Check sender agent balance after cross-registry transfer',
        authType: 'agent',
        authTokenRef: '$senderAgentToken'
      },
      captures: [
        { key: 'balanceAfter', responsePath: 'balance', displayLabel: 'Balance After Transfer' }
      ],
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'xrc-transfer',
      notes: 'Compare with Step 10. The balance should be ~50 units lower plus any applicable transaction fee.'
    },

    // ─── Step 13: View Transaction History ───
    {
      id: 'xrc-tx-history',
      stepNumber: 13,
      title: 'View Transaction History',
      subtitle: 'See the cross-registry transfer in the ledger',
      explanation: `The final step — viewing the sender's transaction history to see the cross-registry transfer recorded in the ledger.

The \`/teg/transactions\` endpoint returns the agent's transaction history. Our cross-registry transfer should appear with its unique transaction ID.

**Congratulations** — you've completed the Cross-Registry Commerce track! You created agents on two sovereign registries, funded them, and transferred real value across the federation boundary using the 2PC protocol.`,
      apiCall: {
        method: 'GET',
        path: '/teg/transactions?limit=5',
        description: 'View recent transaction history including cross-registry transfer',
        authType: 'agent',
        authTokenRef: '$senderAgentToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'xrc-balance-after',
      notes: 'Track complete! The transaction history shows the cross-registry transfer with full audit trail — transaction ID, timestamp, amount, and counterparty DID across the federated network.'
    }
  ]
}
