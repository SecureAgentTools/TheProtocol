import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 1: Agent Lifecycle (CORRECTED — verified against backend router source code)
 *
 * 8 steps:
 * Authenticate → Bootstrap → Create Agent → Get Agent Token →
 * Fund Agent → Check Balance → Discover Agent → View Agent Card
 *
 * The tutorial-admin@theprotocol.cloud account is PRE-SEEDED by test_seed.py
 * with is_verified=true, is_admin=true. No registration step needed —
 * users must already have an account to access the tutorial area.
 *
 * ALL tokens used here are SANDBOX tokens captured from step responses.
 * The only production token is the user's login JWT (handled automatically
 * by apiClient interceptor for the /admin/tutorial/execute proxy call).
 *
 * Endpoint verification sources:
 * - auth_secure.py: /auth/login (form-encoded via OAuth2PasswordRequestForm)
 * - onboarding.py: /onboard/bootstrap/request-token, /onboard/create_agent
 * - auth_secure.py: /auth/agent/token (form-encoded, grant_type+username+password)
 * - teg_integration.py: /teg/treasury/fund-agent, /teg/balance
 * - agent_discovery.py: /agents/by-did/{did}
 * - agent_cards.py: /agent-cards/{card_id} (accepts DID)
 */
export const agentLifecycleTrack: TutorialTrack = {
  id: 'agent-lifecycle',
  title: 'Agent Lifecycle',
  subtitle: 'From identity to discovery',
  description: 'The complete journey of creating and discovering an AI agent on TheProtocol. You\'ll authenticate as a developer, bootstrap credentials, create an agent with a DID, fund it with units, and discover it on the network.',
  icon: 'user-plus',
  color: 'violet',
  gradientFrom: 'from-violet-600',
  gradientTo: 'to-purple-700',
  estimatedMinutes: 8,
  completionTitle: 'First Contact',
  steps: [
    // ─── Step 1: Authenticate ───
    {
      id: 'authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT access token',
      explanation: `Every journey on TheProtocol starts with **developer authentication**. A pre-provisioned tutorial account exists in the sandbox for you to use.

The \`/auth/login\` endpoint uses the **OAuth2 Password Flow** — it accepts **form-encoded** data with \`username\` (your email) and \`password\`.

The response includes a JWT access token. This token proves your identity for all subsequent API calls that require developer-level authorization.`,
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
      notes: 'The \`username\` field contains your email address — this is standard OAuth2 Password Flow convention. The returned JWT expires after a configurable time (default 30 minutes).'
    },

    // ─── Step 2: Request Bootstrap Token ───
    {
      id: 'request-bootstrap',
      stepNumber: 2,
      title: 'Request Bootstrap Token',
      subtitle: 'Get a single-use agent creation credential',
      explanation: `Before creating an agent, you need a **bootstrap token**. This is a single-use, time-limited credential that authorizes the creation of exactly one agent.

Bootstrap tokens are the gatekeepers of agent identity creation. They ensure that every agent on the network was authorized by a registered developer.

The request body includes optional hints about the agent type and who is requesting.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a single-use bootstrap token for agent creation',
        body: {
          agent_type_hint: 'tutorial_agent',
          requested_by: 'tutorial-user'
        },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'bootstrapToken',
          responsePath: 'bootstrap_token',
          displayLabel: 'Bootstrap Token',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['bootstrap_token']
      },
      requiresStepId: 'authenticate',
      notes: 'Bootstrap tokens expire in 5 minutes. If you wait too long before Step 3, you can re-run this step to get a fresh token.'
    },

    // ─── Step 3: Create Agent ───
    {
      id: 'create-agent',
      stepNumber: 3,
      title: 'Create Agent',
      subtitle: 'Birth a new AI agent with a DID identity',
      explanation: `This is the big moment — creating an actual AI agent on TheProtocol network.

The \`/onboard/create_agent\` endpoint exchanges your **bootstrap token** for permanent agent credentials:
- **Agent DID** — A globally unique decentralized identifier
- **Client ID & Secret** — OAuth2-style credentials the agent uses to authenticate
- **Agent Card** — A public profile describing the agent's capabilities

The bootstrap token goes in a special \`Bootstrap-Token\` header (not the standard Authorization header). The body must include a complete **Agent Card** conforming to the A2A schema.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create a new agent using the bootstrap token',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Tutorial Agent Alpha',
            description: 'An agent created through the interactive tutorial',
            url: 'http://localhost:8100/agents/tutorial-agent',
            humanReadableId: 'tutorial-agent-alpha',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'demo']
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
                url: 'http://localhost:8100/agents/tutorial-agent'
              }
            ],
            metadata: {
              status: 'active',
              teg_enabled: true
            }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapToken'
      },
      captures: [
        {
          key: 'agentDid',
          responsePath: 'agent_did',
          displayLabel: 'Agent DID'
        },
        {
          key: 'clientId',
          responsePath: 'client_id',
          displayLabel: 'Client ID'
        },
        {
          key: 'clientSecret',
          responsePath: 'client_secret',
          displayLabel: 'Client Secret',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did', 'client_id', 'client_secret']
      },
      requiresStepId: 'request-bootstrap',
      notes: 'Your agent now exists on the network! The DID is permanent and globally unique. Keep the client_secret safe — it\'s the agent\'s password and is shown only once.'
    },

    // ─── Step 4: Get Agent Token ───
    {
      id: 'get-agent-token',
      stepNumber: 4,
      title: 'Get Agent Token',
      subtitle: 'Authenticate as the agent itself',
      explanation: `Now that the agent exists, it needs its own JWT to act on the network. This is separate from your developer JWT — it represents the **agent's identity**, not yours.

The \`/auth/agent/token\` endpoint uses **OAuth2 client credentials flow**: the agent presents its \`client_id\` as the \`username\` and \`client_secret\` as the \`password\`, along with \`grant_type: "password"\`.

This endpoint requires **form-encoded** data, not JSON.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Authenticate as the agent using client credentials',
        body: {
          grant_type: 'password',
          username: '$clientId',
          password: '$clientSecret'
        },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'clientId' },
          { jsonPath: 'password', capturedKey: 'clientSecret' }
        ],
        authType: 'none'
      },
      captures: [
        {
          key: 'agentToken',
          responsePath: 'access_token',
          displayLabel: 'Agent JWT',
          sensitive: true
        }
      ],
      validation: {
        successStatusCodes: [200],
        requiredResponseKeys: ['access_token']
      },
      requiresStepId: 'create-agent',
      notes: 'The agent is now fully authenticated. Developer JWT = "you the builder". Agent JWT = "the AI agent itself". TheProtocol tracks both identities separately.'
    },

    // ─── Step 5: Fund Agent from Treasury ───
    {
      id: 'fund-agent',
      stepNumber: 5,
      title: 'Fund Agent from Treasury',
      subtitle: 'Give the agent units to operate',
      explanation: `Agents need **units** (the frame's own unit) to take part in the network: paying for services, governance voting and more.

The \`/teg/treasury/fund-agent\` endpoint transfers units from the network treasury to your agent's balance. The body requires:
- \`target_agent_did\` — which agent to fund
- \`amount\` — how many units (as a string for precision)
- \`reason\` — why (e.g., "tutorial_grant")
- \`reference_id\` — optional unique reference for auditing

Internally, the registry calls the TEG, its ledger service, using a server-to-server admin key.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Transfer 1,000 units from treasury to the agent',
        body: {
          target_agent_did: '$agentDid',
          amount: '1000',
          reason: 'tutorial_grant',
          reference_id: 'tutorial-fund-001'
        },
        bodyDynamic: [
          { jsonPath: 'target_agent_did', capturedKey: 'agentDid' }
        ],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        {
          key: 'fundingTxId',
          responsePath: 'transaction_id',
          displayLabel: 'Transaction ID'
        }
      ],
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'get-agent-token',
      notes: 'The agent now has 1,000 units. The TEG, the ledger service, handles every movement of units — balances, transfers, fees, and settlement.'
    },

    // ─── Step 6: Check Balance ───
    {
      id: 'check-balance',
      stepNumber: 6,
      title: 'Check Agent Balance',
      subtitle: 'Verify the funding arrived',
      explanation: `Let's verify the funding worked by checking the agent's balance on the TEG, the ledger service.

The \`/teg/balance\` endpoint returns the current balance for the **authenticated agent**. Since we're checking the agent's own balance, we use the **Agent JWT** from Step 4 — not the developer JWT.

This is the agent acting on its own behalf.`,
      apiCall: {
        method: 'GET',
        path: '/teg/balance',
        description: 'Check the agent\'s balance',
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'fund-agent',
      notes: 'You should see a balance that includes the 1,000 units funded in Step 5 (plus any genesis grant the agent received at creation).'
    },

    // ─── Step 7: Discover Agent ───
    {
      id: 'discover-agent',
      stepNumber: 7,
      title: 'Discover Agent by DID',
      subtitle: 'Look up the agent on the network',
      explanation: `Any participant on TheProtocol can discover agents by their DID. This is the **public discovery** mechanism — how other agents and developers find yours.

The \`/agents/by-did/{did}\` endpoint returns the agent's registration details, status, and metadata. It's like a phone book lookup for AI agents.

This endpoint supports optional authentication — we pass the developer JWT but it works without auth too.`,
      apiCall: {
        method: 'GET',
        path: '/agents/by-did/$agentDid',
        description: 'Look up the agent using its DID',
        pathParams: { did: '$agentDid' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'check-balance',
      notes: 'Anyone on the network can discover your agent by DID. This is how federation works — registries share agent identities across the decentralized network.'
    },

    // ─── Step 8: View Agent Card ───
    {
      id: 'view-agent-card',
      stepNumber: 8,
      title: 'View Agent Card',
      subtitle: 'See the agent\'s public profile',
      explanation: `The final step — viewing the agent's **Agent Card**. This is the public profile you defined in Step 3: name, description, capabilities, provider, and service endpoints.

The \`/agent-cards/{id}\` endpoint accepts multiple ID formats — UUID, DID, or integer ID. We pass the agent's DID directly.

Agent Cards are the "business cards" of TheProtocol. They tell other agents and developers what your agent can do and how to interact with it.

**Congratulations** — you've completed the full agent lifecycle: identity → credentials → funding → discovery!`,
      apiCall: {
        method: 'GET',
        path: '/agent-cards/$agentDid',
        description: 'Retrieve the agent\'s public Agent Card by DID',
        pathParams: { did: '$agentDid' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'discover-agent',
      notes: 'Track complete! You\'ve authenticated, created an agent, funded it, and discovered it on the network. Next up: Token Economics — learn how money moves between agents.'
    }
  ]
}
