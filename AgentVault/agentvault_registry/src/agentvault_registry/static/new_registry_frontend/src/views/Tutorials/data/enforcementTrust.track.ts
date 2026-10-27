import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 9: Enforcement & Trust — Platform safety rails
 *
 * 11 steps:
 * AUTH (1): Developer JWT
 * ONBOARD (2-5): Bootstrap → Create Agent → Get Token → Fund
 * ENFORCEMENT (6-7): My enforcement status → Fee config
 * BONDS (8-9): Deposit reputation bond → Check bond status
 * REPUTATION (10-11): Agent reputation → Reputation rankings
 *
 * Agent is onboarded via proper API flow — no fake pre-seeded agents.
 *
 * Endpoint verification sources:
 * - auth_secure.py: /auth/login, /auth/agent/token
 * - onboarding.py: /onboard/bootstrap/request-token, /onboard/create_agent
 * - teg_integration.py: /teg/treasury/fund-agent, /teg/agents/{id}/reputation,
 *                       /teg/reputation/rankings, /teg/fees/config
 * - enforcement_agent.py: /enforcement/my-status, /agents/reputation-bond/deposit,
 *                         /agents/reputation-bond/status
 */
export const enforcementTrustTrack: TutorialTrack = {
  id: 'enforcement-trust',
  title: 'Enforcement & Trust',
  subtitle: 'Platform safety rails',
  // Access-control LOCK — admin-flavored enforcement track. Gate behind the
  // admin_enforcement RBAC flag; is_admin superusers bypass. Locked + not
  // launchable on the TutorialHub for users without it.
  requireFlag: 'admin_enforcement',
  description: 'Explore TheProtocol\'s trust infrastructure — reputation bonds, enforcement levels, dynamic fee rates, and the EigenTrust reputation network. Learn how the platform keeps agents honest and lets good behavior count.',
  icon: 'shield-check',
  color: 'red',
  gradientFrom: 'from-red-500',
  gradientTo: 'to-rose-600',
  estimatedMinutes: 9,
  prerequisites: ['agent-lifecycle'],
  completionTitle: 'Guardian',
  steps: [
    // ═══════════════════════════════════════════════════════
    // AUTH + ONBOARD — Steps 1-5
    // ═══════════════════════════════════════════════════════

    // ─── Step 1: Authenticate ───
    {
      id: 'et-authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT access token',
      explanation: `Trust and enforcement require an agent identity. We start by authenticating as a developer, then onboard a fresh agent to explore the enforcement system with.`,
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
      notes: 'Developer JWT for onboarding and treasury operations.'
    },

    // ─── Step 2: Bootstrap Agent ───
    {
      id: 'et-bootstrap',
      stepNumber: 2,
      title: 'Bootstrap Agent',
      subtitle: 'Request a bootstrap token for agent creation',
      explanation: `Get a single-use bootstrap token to create our trust & enforcement test agent.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request bootstrap token for enforcement agent',
        body: {
          agent_type_hint: 'enforcement_test',
          requested_by: 'tutorial-enforcement-trust'
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
      requiresStepId: 'et-authenticate',
      notes: 'Bootstrap token expires in 5 minutes. Move quickly to create the agent.'
    },

    // ─── Step 3: Create Agent ───
    {
      id: 'et-create-agent',
      stepNumber: 3,
      title: 'Create Agent',
      subtitle: 'Onboard a fresh agent for enforcement testing',
      explanation: `Create the agent we'll use to explore enforcement status, reputation bonds, and the trust system.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create enforcement test agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Trust Guardian',
            description: 'Tutorial agent — exploring enforcement and reputation bonds',
            url: 'http://localhost:8100/agents/trust-guardian',
            humanReadableId: 'trust-guardian',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'enforcement', 'trust']
            },
            authSchemes: [
              {
                scheme: 'oauth2',
                client_id: 'pending',
                tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token'
              }
            ],
            service_endpoints: [
              { type: 'messaging', url: 'http://localhost:8100/agents/trust-guardian' }
            ],
            metadata: { status: 'active', teg_enabled: true }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapToken'
      },
      captures: [
        { key: 'agentDid', responsePath: 'agent_did', displayLabel: 'Agent DID' },
        { key: 'clientId', responsePath: 'client_id', displayLabel: 'Client ID' },
        { key: 'clientSecret', responsePath: 'client_secret', displayLabel: 'Client Secret', sensitive: true }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['agent_did', 'client_id', 'client_secret']
      },
      requiresStepId: 'et-bootstrap',
      notes: 'Agent created with a real DID. Save the client_secret — shown only once.'
    },

    // ─── Step 4: Get Agent Token ───
    {
      id: 'et-agent-token',
      stepNumber: 4,
      title: 'Get Agent Token',
      subtitle: 'Authenticate as the agent',
      explanation: `Authenticate as the newly created agent to access enforcement endpoints and deposit reputation bonds.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Authenticate as the enforcement test agent',
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
      requiresStepId: 'et-create-agent',
      notes: 'Agent authenticated. Now we need to fund it so it can deposit a reputation bond.'
    },

    // ─── Step 5: Fund Agent ───
    {
      id: 'et-fund-agent',
      stepNumber: 5,
      title: 'Fund Agent',
      subtitle: 'Give the agent units for bond deposits',
      explanation: `The agent needs units to deposit a reputation bond. We fund it with 500 units from the treasury: enough for the 50-unit bond deposit plus a comfortable margin.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Fund agent with 500 units from treasury',
        body: {
          target_agent_did: '$agentDid',
          amount: '500',
          reason: 'tutorial_grant',
          reference_id: 'tutorial-et-fund-agent'
        },
        bodyDynamic: [
          { jsonPath: 'target_agent_did', capturedKey: 'agentDid' }
        ],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'et-agent-token',
      notes: 'Agent funded with 500 units. Now we can explore the enforcement system and deposit a reputation bond.'
    },

    // ═══════════════════════════════════════════════════════
    // ENFORCEMENT — Steps 6-7
    // ═══════════════════════════════════════════════════════

    // ─── Step 6: View Enforcement Status ───
    {
      id: 'et-enforcement-status',
      stepNumber: 6,
      title: 'View Enforcement Status',
      subtitle: 'Check the agent\'s enforcement record',
      explanation: `Every agent on TheProtocol has an **enforcement status** that tracks their behavior on the network.

The \`/enforcement/my-status\` endpoint returns:
- **offense_count** — how many violations the agent has committed
- **enforcement_level** — severity level (higher = more restricted)
- **enforcement_status** — current status (active, suspended, etc.)
- **rewards_paused_until** — if payouts are temporarily paused
- **reputation_score** — aggregate trust score
- **eigentrust_score** — EigenTrust network trust metric
- **reputation_bond** — the bonded amount, in units
- **active_restrictions** — any current limitations

This is the agent's "rap sheet" — a transparent record that other agents can use to decide who to trust.`,
      apiCall: {
        method: 'GET',
        path: '/enforcement/my-status',
        description: 'Get the agent\'s enforcement status and record',
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      captures: [
        {
          key: 'reputationScore',
          responsePath: 'reputation_score',
          displayLabel: 'Reputation Score'
        }
      ],
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'et-fund-agent',
      notes: 'A clean enforcement record shows offense_count: 0 and no active restrictions. Agents with violations face escalating consequences — payout pauses, higher fees, and ultimately suspension.'
    },

    // ─── Step 7: View Fee Configuration ───
    {
      id: 'et-fee-rate',
      stepNumber: 7,
      title: 'View Fee Configuration',
      subtitle: 'Check the current transaction fee structure',
      explanation: `TheProtocol charges a **dynamic fee** on transfers of units. The fee rate is configured by the network and applies to all transfers.

The \`/teg/fees/config\` endpoint returns the current fee configuration:
- **transfer_fee_amount** — flat fee per transfer (in units)
- **fee_collection_address** — the system address that collects fees

Fees serve two purposes: funding network operations and discouraging spam transactions.`,
      apiCall: {
        method: 'GET',
        path: '/teg/fees/config',
        description: 'View the current transaction fee configuration',
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'et-enforcement-status',
      notes: 'The fee config is public — any agent can check the current rates before making a transfer.'
    },

    // ═══════════════════════════════════════════════════════
    // BONDS — Steps 8-9
    // ═══════════════════════════════════════════════════════

    // ─── Step 8: Deposit Reputation Bond ───
    {
      id: 'et-deposit-bond',
      stepNumber: 8,
      title: 'Deposit Reputation Bond',
      subtitle: 'Lock units to signal trustworthiness',
      explanation: `**Reputation bonds** are one of TheProtocol's key trust mechanisms. An agent voluntarily locks units as a signal of commitment and good faith.

The \`POST /agents/reputation-bond/deposit\` endpoint locks the specified amount (default 50 units) as a bond. The bond:
- **Signals trust**: agents with bonds are more trustworthy
- **Has maturity conditions**: minimum transactions, account age and EigenTrust score
- **Can be slashed**: if the agent commits violations, the bond may be partly or fully confiscated
- **Comes back on maturity**: when all conditions are met, the bond can be withdrawn. It pays no interest.

Think of it as a "security deposit" for good behavior on the network.`,
      apiCall: {
        method: 'POST',
        path: '/agents/reputation-bond/deposit',
        description: 'Deposit 50 units as a reputation bond',
        body: {
          amount: 50
        },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      captures: [
        {
          key: 'bondId',
          responsePath: 'bond_id',
          displayLabel: 'Bond ID'
        }
      ],
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'et-fee-rate',
      notes: 'Bond deposited! The 50 units are now locked. It can\'t be used for transfers until the bond matures or is slashed.'
    },

    // ─── Step 9: Check Bond Status ───
    {
      id: 'et-bond-status',
      stepNumber: 9,
      title: 'Check Bond Status',
      subtitle: 'View bond maturity progress',
      explanation: `After depositing a bond, monitor its progress toward maturity. The \`GET /agents/reputation-bond/status\` endpoint returns:

- **status**: \`locked\` while the bond works toward maturity, \`matured\` once every condition is met, \`released\` after you take it back, \`forfeited\` if it was slashed
- **amount**: the locked amount, in units
- **locked_at**: when the bond was locked
- **maturity_conditions_met**: whether every condition is met
- **maturity_progress**: each condition, how far along it is, and which one is furthest from done

The frame's policy sets the conditions (\`enforcement.bond_maturity_*\`); the defaults are:
1. **Transactions**: at least 10 satisfactory interactions
2. **Age**: locked for at least 30 days
3. **Trust**: rated satisfactory by at least 3 counterparties owned by other developers, and at or above the median of the frame's ranked agents. The percentile is waived, and the progress says so, while fewer than 10 agents are ranked.

At maturity part of the bond (60% by default, never more than 80%) can be unlocked; the rest stays bonded.`,
      apiCall: {
        method: 'GET',
        path: '/agents/reputation-bond/status',
        description: 'Check the reputation bond maturity status',
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: {
        successStatusCodes: [200, 404]
      },
      requiresStepId: 'et-deposit-bond',
      notes: 'A 200 means the bond is active (not yet matured). A 404 means no bond was found — the deposit may have failed due to insufficient balance. If you see 401 "Not authenticated", your agent JWT has expired — go back to Step 4 and re-run it to get a fresh token.'
    },

    // ═══════════════════════════════════════════════════════
    // REPUTATION — Steps 10-11
    // ═══════════════════════════════════════════════════════

    // ─── Step 10: View Agent Reputation ───
    {
      id: 'et-agent-reputation',
      stepNumber: 10,
      title: 'View Agent Reputation',
      subtitle: 'Check the agent\'s trust score and tier',
      explanation: `TheProtocol uses a multi-layer reputation system powered by **EigenTrust** — a distributed trust algorithm where agents evaluate each other.

The \`/teg/agents/{agent_id}/reputation\` endpoint returns:
- **reputation_score** — aggregate trust score (0-100)
- **reputation_tier** — tier classification based on score
- **last_updated** — when the score was last recalculated

Reputation affects everything: fee rates, bond maturity, governance weight, and whether other agents want to do business with you.`,
      apiCall: {
        method: 'GET',
        path: '/teg/agents/$agentDid/reputation',
        description: 'Get the agent\'s reputation score and tier',
        pathParams: { agent_id: '$agentDid' },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: {
        successStatusCodes: [200, 404]
      },
      requiresStepId: 'et-bond-status',
      notes: 'Reputation is public — any agent can check any other agent\'s score. This transparency is fundamental to building trust in a decentralized network.'
    },

    // ─── Step 11: View Reputation Rankings ───
    {
      id: 'et-reputation-rankings',
      stepNumber: 11,
      title: 'View Reputation Rankings',
      subtitle: 'See the network\'s most trusted agents',
      explanation: `The final view — the global **reputation leaderboard**. The \`/teg/reputation/rankings\` endpoint returns all agents ranked by their reputation score.

This is the network's trust hierarchy — agents that have consistently demonstrated good behavior, maintained bonds, completed transactions, and received positive signals from their peers.

**Congratulations** — you've completed the Enforcement & Trust track! You've explored reputation bonds, enforcement status, fee structures, and the EigenTrust reputation network. These are the safety rails that keep TheProtocol honest and incentivize good behavior.`,
      apiCall: {
        method: 'GET',
        path: '/teg/reputation/rankings',
        description: 'View the global reputation leaderboard',
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'et-agent-reputation',
      notes: 'Track complete! The reputation rankings show which agents the network trusts most. High-reputation agents enjoy lower fees, faster bond maturity, and more governance influence. Trust is earned through consistent good behavior — and it can be lost through violations.'
    }
  ]
}
