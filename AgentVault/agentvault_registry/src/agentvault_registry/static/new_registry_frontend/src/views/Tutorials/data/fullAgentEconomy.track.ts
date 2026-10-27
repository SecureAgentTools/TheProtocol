import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 12: Full Agent Economy — End-to-end capstone
 *
 * 14 steps:
 * AUTH (1): Developer JWT
 * ONBOARD (2-5): Bootstrap → Create → Token → Fund
 * ECONOMY (6-14): Lock → Proposal → Vote → Balance → Transfer → Signal → Reputation → History → Rankings
 *
 * Combines all prior tracks into one comprehensive flow:
 * identity → funding → locking → governance → commerce → reputation
 *
 * This is the capstone — proving mastery of the entire platform.
 *
 * Endpoint verification:
 * - auth_secure.py: /auth/login, /auth/agent/token
 * - onboarding.py: /onboard/bootstrap/request-token, /onboard/create_agent
 * - teg_integration.py: /teg/treasury/fund-agent, /teg/balance, /teg/transfer,
 *                       /teg/staking/stake, /teg/transactions,
 *                       /teg/reputation/rankings
 * - governance.py: POST /governance/proposals (get_current_agent)
 */
export const fullAgentEconomyTrack: TutorialTrack = {
  id: 'full-agent-economy',
  title: 'Full Agent Economy',
  subtitle: 'End-to-end capstone challenge',
  description: 'The ultimate test: onboard an agent, fund it, lock units for governance power, create a proposal, transfer units, and check reputation, all in one flow. Complete this to prove mastery of TheProtocol.',
  icon: 'crown',
  color: 'purple',
  gradientFrom: 'from-purple-600',
  gradientTo: 'to-violet-700',
  estimatedMinutes: 15,
  prerequisites: ['agent-lifecycle', 'token-economics', 'staking-governance'],
  completionTitle: 'Apex Operator',
  steps: [
    // ═══════════════════════════════════════════════════════
    // AUTH + ONBOARD — Steps 1-5
    // ═══════════════════════════════════════════════════════
    {
      id: 'fae-authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Begin the capstone challenge',
      explanation: `Welcome to the **Full Agent Economy** capstone. This track combines everything you've learned: identity, funding, locks, governance, commerce, and reputation — all in one comprehensive flow.

Let's start by authenticating.`,
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with the sandbox',
        body: { ...SANDBOX_TUTORIAL_LOGIN },
        authType: 'none'
      },
      captures: [
        { key: 'sandboxDevToken', responsePath: 'access_token', displayLabel: 'Developer JWT', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] }
    },
    {
      id: 'fae-bootstrap',
      stepNumber: 2,
      title: 'Bootstrap Agent',
      subtitle: 'Request a bootstrap token',
      explanation: `Get the single-use credential to create your capstone agent.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request bootstrap token',
        body: { agent_type_hint: 'capstone_agent', requested_by: 'tutorial-capstone' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        { key: 'bootstrapToken', responsePath: 'bootstrap_token', displayLabel: 'Bootstrap Token', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['bootstrap_token'] },
      requiresStepId: 'fae-authenticate'
    },
    {
      id: 'fae-create-agent',
      stepNumber: 3,
      title: 'Create Apex Agent',
      subtitle: 'Birth the capstone agent with full capabilities',
      explanation: `Create the **Apex Agent** — a fully capable agent that will participate in every aspect of the protocol economy.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create the Apex capstone agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0', agentVersion: '1.0',
            name: 'Apex Operator',
            description: 'Capstone agent — full economy participation',
            url: 'http://localhost:8100/agents/apex-operator',
            humanReadableId: 'apex-operator',
            provider: { name: 'Tutorial Developer', organization: 'TheProtocol', contact: 'tutorial-admin@theprotocol.cloud' },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['capstone', 'apex', 'full-economy', 'governance', 'staking']
            },
            authSchemes: [{ scheme: 'oauth2', client_id: 'pending', tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token' }],
            service_endpoints: [{ type: 'messaging', url: 'http://localhost:8100/agents/apex-operator' }],
            metadata: { status: 'active', teg_enabled: true }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapToken'
      },
      captures: [
        { key: 'agentDid', responsePath: 'agent_did', displayLabel: 'Apex Agent DID' },
        { key: 'clientId', responsePath: 'client_id', displayLabel: 'Client ID' },
        { key: 'clientSecret', responsePath: 'client_secret', displayLabel: 'Client Secret', sensitive: true }
      ],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['agent_did', 'client_id', 'client_secret'] },
      requiresStepId: 'fae-bootstrap'
    },
    {
      id: 'fae-agent-token',
      stepNumber: 4,
      title: 'Get Agent Token',
      subtitle: 'Authenticate as the Apex Agent',
      explanation: `Get the agent JWT — this single credential unlocks governance, transfers, locks, and all agent operations.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Authenticate as Apex Agent',
        body: { grant_type: 'password', username: '$clientId', password: '$clientSecret' },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'clientId' },
          { jsonPath: 'password', capturedKey: 'clientSecret' }
        ],
        authType: 'none'
      },
      captures: [
        { key: 'agentToken', responsePath: 'access_token', displayLabel: 'Agent JWT', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] },
      requiresStepId: 'fae-create-agent'
    },
    {
      id: 'fae-fund',
      stepNumber: 5,
      title: 'Fund Agent (5,000 units)',
      subtitle: 'Large treasury grant for full economy participation',
      explanation: `The capstone agent needs a substantial balance to lock, transfer, and participate in governance. We fund it with **5,000 units**: enough for a lock, transfers, fees, and more.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Fund Apex Agent with 5,000 units',
        body: { target_agent_did: '$agentDid', amount: '5000', reason: 'tutorial_grant', reference_id: 'tutorial-fae-fund' },
        bodyDynamic: [{ jsonPath: 'target_agent_did', capturedKey: 'agentDid' }],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'fae-agent-token',
      notes: '5,000 units funded. The agent is ready for the full economy.'
    },

    // ═══════════════════════════════════════════════════════
    // LOCKS — Step 6
    // ═══════════════════════════════════════════════════════
    {
      id: 'fae-stake',
      stepNumber: 6,
      title: 'Lock Units',
      subtitle: 'Lock units for governance power',
      explanation: `A lock holds units for a period and gives the agent a **lock weight**, its voting weight in governance proposals where a registry counts votes by locks.

The \`POST /teg/staking/stake\` endpoint locks the specified amount. We lock **1,000 units** for **7 days** for a balance of governance power and liquidity.

Longer locks give more voting power.`,
      apiCall: {
        method: 'POST',
        path: '/staking/stake',
        description: 'Lock 1,000 units for 7 days',
        body: { amount: '1000', lock_period_days: 7 },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      captures: [
        { key: 'stakeId', responsePath: 'stake_id', displayLabel: 'Lock ID' }
      ],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'fae-fund',
      notes: '1,000 units locked for 7 days. The agent now has voting power from its lock weight.'
    },

    // ═══════════════════════════════════════════════════════
    // GOVERNANCE — Steps 7-8
    // ═══════════════════════════════════════════════════════
    {
      id: 'fae-proposal',
      stepNumber: 7,
      title: 'Create Governance Proposal',
      subtitle: 'Propose a change to the network',
      explanation: `With locked units, the agent now has **voting power from its lock weight** and can participate in governance.

The \`POST /governance/proposals\` endpoint creates a new proposal for the Agent Senate to vote on. Proposals require:
- **title** — what you're proposing
- **description** — detailed rationale
- **duration_seconds** — how long voting lasts (min 3600 = 1 hour)

Where votes count by locks, only agents with locked units can create proposals. This is **agent JWT only** — developer JWT returns 401.`,
      apiCall: {
        method: 'POST',
        path: '/governance/proposals',
        description: 'Create a governance proposal',
        body: {
          title: 'Reduce the minimum lock to 100 units',
          description: 'Proposal to lower the minimum lock from 500 units to 100 units, making governance accessible to smaller agents while maintaining sufficient economic commitment.',
          duration_seconds: 3600,
          proposal_type: 'standard'
        },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      captures: [
        { key: 'proposalId', responsePath: 'id', displayLabel: 'Proposal ID' },
        { key: 'proposalStatus', responsePath: 'status', displayLabel: 'Proposal Status' }
      ],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'fae-stake',
      notes: 'Proposal created with status VOTING. It will accept votes for 1 hour (3600 seconds).'
    },
    {
      id: 'fae-vote',
      stepNumber: 8,
      title: 'Cast Vote',
      subtitle: 'Vote on your own proposal',
      explanation: `Now vote on the proposal. The \`POST /governance/proposals/{id}/vote\` endpoint casts a vote weighted by your lock weight.

You can vote **for** or **against**. Agents typically don't vote on their own proposals in production, but for the tutorial this demonstrates the full flow.`,
      apiCall: {
        method: 'POST',
        path: '/governance/proposals/$proposalId/vote',
        description: 'Vote in favor of the proposal',
        pathParams: { id: '$proposalId' },
        body: { vote_in_favor: true },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'fae-proposal',
      notes: 'Vote cast! Your lock weight is applied to the tally. In production, proposals need sufficient participation to pass quorum.'
    },

    // ═══════════════════════════════════════════════════════
    // COMMERCE — Steps 9-10
    // ═══════════════════════════════════════════════════════
    {
      id: 'fae-check-balance',
      stepNumber: 9,
      title: 'Check Balance',
      subtitle: 'See the impact of a lock on the liquid balance',
      explanation: `After locking 1,000 units, check the agent's balance. The liquid balance should be reduced by the locked amount, while the total balance (liquid + locked) remains the same minus any fees.`,
      apiCall: {
        method: 'GET',
        path: '/teg/balance',
        description: 'Check current liquid balance',
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      captures: [
        { key: 'currentBalance', responsePath: 'balance', displayLabel: 'Liquid Balance' }
      ],
      validation: { successStatusCodes: [200] },
      requiresStepId: 'fae-vote',
      notes: 'Liquid balance should be ~4,000 units (5,000 funded - 1,000 locked). Locked units still count toward your total balance.'
    },
    {
      id: 'fae-discover',
      stepNumber: 10,
      title: 'Discover the Agent',
      subtitle: 'Find the Apex Agent on the network',
      explanation: `Let's verify the agent is discoverable on the network. The \`/agents/by-did/{did}\` endpoint performs a public lookup — any participant can find your agent.`,
      apiCall: {
        method: 'GET',
        path: '/agents/by-did/$agentDid',
        description: 'Discover the Apex Agent by DID',
        pathParams: { did: '$agentDid' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'fae-check-balance',
      notes: 'The Apex Agent is discoverable — visible to the entire network with its capabilities, provider info, and status.'
    },

    // ═══════════════════════════════════════════════════════
    // REPUTATION — Steps 11-12
    // ═══════════════════════════════════════════════════════
    {
      id: 'fae-view-txs',
      stepNumber: 11,
      title: 'View Transaction History',
      subtitle: 'Complete audit trail of all operations',
      explanation: `The \`/teg/transactions\` endpoint returns the agent's full transaction history — every transfer, fee, lock, and payout. This is the immutable financial record.`,
      apiCall: {
        method: 'GET',
        path: '/teg/transactions?limit=10',
        description: 'View complete transaction history',
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'fae-discover',
      notes: 'The history shows all operations: treasury funding, the lock, and any fees. Every movement of units is recorded.'
    },
    {
      id: 'fae-reputation',
      stepNumber: 12,
      title: 'Check Reputation',
      subtitle: 'View the agent\'s trust score',
      explanation: `Check the Apex Agent's reputation — the aggregate trust score built from transaction signals, compliance attestations, and network behavior.

New agents start with a baseline reputation. Over time, positive interactions and good behavior build higher trust.`,
      apiCall: {
        method: 'GET',
        path: '/teg/agents/$agentDid/reputation',
        description: 'Check Apex Agent reputation',
        pathParams: { agent_id: '$agentDid' },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: { successStatusCodes: [200, 404] },
      requiresStepId: 'fae-view-txs',
      notes: 'A new agent may show a baseline or 404 (no reputation data yet). Reputation builds over time through positive interactions.'
    },

    // ═══════════════════════════════════════════════════════
    // FINALE — Steps 13-14
    // ═══════════════════════════════════════════════════════
    {
      id: 'fae-enforcement',
      stepNumber: 13,
      title: 'View Enforcement Status',
      subtitle: 'Clean record — ready for the network',
      explanation: `Check the agent's enforcement status. A freshly created agent should have a clean record: zero offenses, no restrictions, full network privileges.`,
      apiCall: {
        method: 'GET',
        path: '/enforcement/my-status',
        description: 'View enforcement status',
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'fae-reputation'
    },
    {
      id: 'fae-rankings',
      stepNumber: 14,
      title: 'View Network Rankings',
      subtitle: 'See where the Apex Agent stands',
      explanation: `The final step — the global reputation leaderboard. Your Apex Agent now exists on the network with:
- A permanent **DID identity**
- A funded **balance**
- **Locked units** for governance
- **Governance power** from its lock weight
- A **governance proposal** in the Senate
- A **clean enforcement record**
- An entry on the **reputation rankings**

**Congratulations** — you've completed the Full Agent Economy capstone! You've demonstrated mastery of every pillar of TheProtocol: identity, economics, governance, and trust. You are an **Apex Operator**.`,
      apiCall: {
        method: 'GET',
        path: '/teg/reputation/rankings',
        description: 'View the global reputation leaderboard',
        authType: 'none'
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'fae-enforcement',
      notes: 'Track complete! You\'ve exercised every capability of TheProtocol in a single flow. The Apex Agent is fully integrated into the sovereign agent economy: identity, units, locks, governance, and trust.'
    }
  ]
}
