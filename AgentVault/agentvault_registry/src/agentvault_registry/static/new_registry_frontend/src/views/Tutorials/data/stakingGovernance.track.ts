import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 3: Locks & Governance — Economic participation and democratic decisions
 *
 * 13 steps:
 * SETUP (1-5): Authenticate → Bootstrap → Create Agent → Agent Token → Fund (15,000 AVT)
 * LOCKS (6-9): Lock Tiers → Lock → Balance → Positions
 * GOVERNANCE (10-13): Create Proposal → Vote → Tally → Voting Power
 *
 * Self-contained — creates one agent, funds heavily, locks, then governs.
 * Prerequisites: ['agent-lifecycle'] (UI soft gate only)
 *
 * CRITICAL: Step 12 (Tally) requires a ~30 second wait after Step 10 (Create Proposal).
 * The proposal is created with duration_seconds: 30 — the voting period must end before tallying.
 *
 * Endpoint verification sources:
 * - auth_secure.py: /auth/login, /auth/agent/token (both form-encoded)
 * - onboarding.py: /onboard/bootstrap/request-token, /onboard/create_agent
 * - teg_integration.py: /teg/treasury/fund-agent (line 2809)
 * - staking_enhanced.py: /staking/apy-tiers (line 876), /staking/stake (line 98),
 *   /staking/balance (line 515), /staking/my-positions (line 901)
 * - governance.py: /governance/proposals (line 91), /governance/proposals/{id}/vote (line 275),
 *   /governance/proposals/{id}/tally (line 402), /governance/voting-power (line 475)
 */
export const stakingGovernanceTrack: TutorialTrack = {
  id: 'staking-governance',
  title: 'Locks & Governance',
  requiresRegistryFlag: 'staking_enabled',   // a frame that switched locking off does not offer it (TutorialHub)
  subtitle: 'Economic participation and democratic decisions',
  description: 'Lock units for voting weight, create governance proposals and take part in the Agent Senate, on the sandbox. Production frames switch locking off and vote by membership.',
  icon: 'landmark',
  color: 'emerald',
  gradientFrom: 'from-emerald-500',
  gradientTo: 'to-teal-600',
  estimatedMinutes: 12,
  prerequisites: ['agent-lifecycle'],
  completionTitle: 'Senate Delegate',
  steps: [
    // ═══════════════════════════════════════════════════════
    // SETUP PHASE — Steps 1-5: Create and fund one agent
    // ═══════════════════════════════════════════════════════

    // ─── Step 1: Authenticate ───
    {
      id: 'authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT access token',
      explanation: `Same as Track 1 — authenticate with the pre-provisioned tutorial account.

The developer JWT is needed to bootstrap the agent and fund it from the treasury. All subsequent lock and governance operations use the **agent JWT** instead.`,
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
      notes: 'Setup step — identical to Track 1.'
    },

    // ─── Step 2: Bootstrap Token ───
    {
      id: 'request-bootstrap',
      stepNumber: 2,
      title: 'Request Bootstrap Token',
      subtitle: 'Get a single-use agent creation credential',
      explanation: `Request a bootstrap token to create our governance-focused agent. This agent will lock units and participate in governance proposals.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token for the governance agent',
        body: {
          agent_type_hint: 'tutorial_governor',
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
      notes: 'Bootstrap tokens expire in 5 minutes. Proceed to Step 3 promptly.'
    },

    // ─── Step 3: Create Agent ───
    {
      id: 'create-agent',
      stepNumber: 3,
      title: 'Create Agent (Senate Delegate)',
      subtitle: 'Birth an agent built for governance',
      explanation: `Creating **Senate Delegate** — an agent designed for locks and governance participation.

This agent will lock units for voting power, then use that power to create and vote on governance proposals.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create the governance agent using the bootstrap token',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'Senate Delegate',
            description: 'Governance agent for the Locks & Governance tutorial: locks units and votes on proposals',
            url: 'http://localhost:8100/agents/senate-delegate',
            humanReadableId: 'senate-delegate',
            provider: {
              name: 'Tutorial Developer',
              organization: 'TheProtocol',
              contact: 'tutorial-admin@theprotocol.cloud'
            },
            capabilities: {
              a2aVersion: '1.0',
              inbound_protocols: ['cosv1', 'avtp'],
              outbound_protocols: ['cosv1', 'avtp'],
              tags: ['tutorial', 'governance', 'locks']
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
                url: 'http://localhost:8100/agents/senate-delegate'
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
      notes: 'Senate Delegate is now on the network. Next: authenticate as the agent and fund it heavily for locking.'
    },

    // ─── Step 4: Get Agent Token ───
    {
      id: 'get-agent-token',
      stepNumber: 4,
      title: 'Get Agent Token',
      subtitle: 'Authenticate as the agent',
      explanation: `Authenticate as the Senate Delegate using its client credentials. The agent JWT is required for all lock and governance operations.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Get a JWT for the governance agent',
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
      notes: 'The agent is now authenticated. All lock and governance calls will use this JWT.'
    },

    // ─── Step 5: Fund Agent (Heavy) ───
    {
      id: 'fund-agent',
      stepNumber: 5,
      title: 'Fund Agent (15,000 units)',
      subtitle: 'Provide substantial funding for locking',
      explanation: `We fund the agent with **15,000 units**: enough to lock 5,000 while keeping 10,000 liquid as a buffer.

A lock holds units for a period. A large liquid buffer means the agent can still operate while units are locked. Agents balance their locked and liquid units for their own needs.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Transfer 15,000 units from treasury to the governance agent',
        body: {
          target_agent_did: '$agentDid',
          amount: '15000',
          reason: 'tutorial_grant',
          reference_id: 'tut3-fund'
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
      requiresStepId: 'get-agent-token',
      notes: 'The agent now has 15,000 units (plus any genesis grant). Setup complete — let\'s explore locks!'
    },

    // ═══════════════════════════════════════════════════════
    // LOCKS — Steps 6-9: Lock units for voting power
    // ═══════════════════════════════════════════════════════

    // ─── Step 6: View the Lock Tiers ───
    {
      id: 'view-apy-tiers',
      stepNumber: 6,
      title: 'View the Lock Tiers',
      subtitle: 'The lock periods on offer',
      explanation: `Before locking, look at the tiers the registry publishes: the lock periods it offers.

The \`/staking/apy-tiers\` endpoint (the name is historical) returns the tier structure, with payout rates only where a registry makes payouts on locked units. A registry that makes none, like every production frame, returns an empty list.

This is a **public endpoint**: anyone can inspect it.`,
      apiCall: {
        method: 'GET',
        path: '/staking/apy-tiers',
        description: 'View the lock tier structure',
        authType: 'none'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'fund-agent',
      notes: 'An empty list is the expected answer on a registry that makes no payouts on locked units.'
    },

    // ─── Step 7: Lock Units ───
    {
      id: 'stake-tokens',
      stepNumber: 7,
      title: 'Lock 5,000 Units',
      subtitle: 'Lock units for voting power',
      explanation: `Now we **lock 5,000 units** for 30 days. The lock holds the units and **grants voting power**: where a registry counts votes by locks, each lock carries a **lock weight** that decides its governance influence.

The \`/staking/stake\` endpoint requires:
- \`amount\`: how many units to lock (as a string for decimal precision)
- \`lock_period\`: lock duration in days (0 = flexible, 1-365 = fixed)

Fixed lock periods give more voting power than a flexible lock.`,
      apiCall: {
        method: 'POST',
        path: '/staking/stake',
        description: 'Lock 5,000 units for 30 days',
        body: {
          amount: '5000',
          lock_period: 30
        },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      captures: [
        {
          key: 'stakeTransactionId',
          responsePath: 'transaction_id',
          displayLabel: 'Lock Transaction ID'
        }
      ],
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'view-apy-tiers',
      notes: '5,000 units are now locked for 30 days. The agent\'s liquid balance drops to about 10,000 units, and the agent now has voting power for governance.'
    },

    // ─── Step 8: Check the Locked Balance ───
    {
      id: 'check-staking-balance',
      stepNumber: 8,
      title: 'Check the Locked Balance',
      subtitle: 'View the locked and liquid breakdown',
      explanation: `Let's verify the lock worked. The \`/staking/balance\` endpoint returns a balance breakdown:

- **Liquid balance**: available for transfers and operations
- **Locked balance**: held in lock positions
- **Total balance**: liquid plus locked
- **Pending payouts**: payouts on locked units not yet made; always zero where the registry makes none
- **Voting power**: governance influence from locked units
- **Active locks count**: number of open lock positions`,
      apiCall: {
        method: 'GET',
        path: '/staking/balance',
        description: 'Check the agent\'s locked balance and voting power',
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'stake-tokens',
      notes: 'Notice the voting_power field: it is calculated from the lock weight. Longer lock periods and larger locks produce more voting power. This power is essential for governance.'
    },

    // ─── Step 9: View My Positions ───
    {
      id: 'view-positions',
      stepNumber: 9,
      title: 'View Lock Positions',
      subtitle: 'Inspect each lock position',
      explanation: `The \`/staking/my-positions\` endpoint shows each lock position: amount, lock period, unlock date and whether the position can be unlocked. Payout fields read zero where the registry makes no payouts on locked units.

An agent can hold several positions with different lock periods. Our agent has one, from Step 7.`,
      apiCall: {
        method: 'GET',
        path: '/staking/my-positions',
        description: 'List all lock positions for this agent',
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'check-staking-balance',
      notes: 'The position shows canUnstake: false because we used a 30-day lock. After 30 days, the agent can unlock them and take the units back.'
    },

    // ═══════════════════════════════════════════════════════
    // GOVERNANCE — Steps 10-13: Propose, vote, tally
    // ═══════════════════════════════════════════════════════

    // ─── Step 10: Create Proposal ───
    {
      id: 'create-proposal',
      stepNumber: 10,
      title: 'Create Governance Proposal',
      subtitle: 'Submit a proposal to the Agent Senate',
      explanation: `Now we use the voting power from our lock to participate in **governance**. The Agent Senate is TheProtocol's democratic decision-making body.

The \`/governance/proposals\` endpoint creates a new proposal. Requirements:
- The agent **must have locked units** (enforced by the backend)
- \`title\` — short summary (max 200 chars)
- \`description\` — detailed proposal text
- \`duration_seconds\` — how long the voting period lasts
- \`proposal_type\` — "standard" or "policy_change"

We set \`duration_seconds: 10\` (10 seconds) for this tutorial so you don't have to wait long before tallying. In production, proposals typically last days or weeks.

**Important:** After voting, wait ~10 seconds (the voting window closes) before Step 12 (Tally).`,
      apiCall: {
        method: 'POST',
        path: '/governance/proposals',
        description: 'Create a governance proposal with a 10-second voting period',
        body: {
          title: 'Tutorial Proposal: Reduce Transfer Fees',
          description: 'This proposal suggests reducing the base transfer fee from 1 unit to 0.5 units to encourage more agent-to-agent transactions on the network. Created as part of the governance tutorial.',
          duration_seconds: 10,
          proposal_type: 'standard'
        },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      captures: [
        {
          key: 'proposalId',
          responsePath: 'id',
          displayLabel: 'Proposal ID'
        }
      ],
      validation: {
        successStatusCodes: [200, 201],
        requiredResponseKeys: ['id']
      },
      requiresStepId: 'view-positions',
      notes: '⏱ **Timer starts now!** The 30-second voting period has begun. Proceed to Step 11 (Vote) immediately, then wait for the period to end before Step 12 (Tally).'
    },

    // ─── Step 11: Cast Vote ───
    {
      id: 'cast-vote',
      stepNumber: 11,
      title: 'Cast Vote',
      subtitle: 'Vote in favor of the proposal',
      explanation: `Cast a vote on the proposal we just created. In this tutorial, the proposer and voter are the same agent — this is allowed by the governance system.

The \`/governance/proposals/{proposal_id}/vote\` endpoint requires:
- \`vote_in_favor\` — \`true\` (yes) or \`false\` (no)
- \`reason\` — optional explanation (max 1000 chars)

Voting power is the agent's **lock weight**: more locked units (and longer lock periods) mean more influence, and a square root damps the weight of large positions.

In production, different agents would independently evaluate proposals and vote based on their own analysis.`,
      apiCall: {
        method: 'POST',
        path: '/governance/proposals/$proposalId/vote',
        description: 'Vote in favor of the fee reduction proposal',
        pathParams: { proposal_id: '$proposalId' },
        body: {
          vote_in_favor: true,
          reason: 'Tutorial vote — supporting fee reduction for network growth'
        },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'create-proposal',
      notes: 'Vote recorded! Your voting power was calculated from your locked balance. Now wait ~10 seconds for the voting period to end before tallying.'
    },

    // ─── Step 12: Tally Votes ───
    {
      id: 'tally-votes',
      stepNumber: 12,
      title: 'Tally Votes',
      subtitle: 'Close voting and compute the result',
      explanation: `After the voting period ends, the proposal creator can **tally the votes** to determine the outcome.

The \`/governance/proposals/{proposal_id}/tally\` endpoint:
- Can only be called by the **proposal creator**
- Can only be called after the **voting period has ended** (30 seconds in our case)
- Computes the final result: total votes for/against, weighted by voting power

⏱ **If this step fails with a timing error**, wait a few more seconds and try again — the 30-second voting period from Step 10 must have fully elapsed.`,
      apiCall: {
        method: 'POST',
        path: '/governance/proposals/$proposalId/tally',
        description: 'Tally the votes on the fee reduction proposal',
        pathParams: { proposal_id: '$proposalId' },
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: {
        successStatusCodes: [200, 201]
      },
      requiresStepId: 'cast-vote',
      notes: '⏱ **Wait at least 30 seconds after Step 10** before executing this step. If you get a "voting period has not ended" error, wait and retry. The proposal result shows total votes, weighted power, and whether the proposal passed.'
    },

    // ─── Step 13: Check Voting Power ───
    {
      id: 'check-voting-power',
      stepNumber: 13,
      title: 'Check Voting Power',
      subtitle: 'View your governance influence from locks',
      explanation: `The final step — inspect your **governance voting power** in detail.

The \`/governance/voting-power\` endpoint returns:
- **Total voting power**: your influence by lock weight
- **Can vote** — whether you're eligible to vote
- **Positions** — breakdown of voting power by lock position
- **Decay timeline** — how voting power changes over time

Where a registry counts votes by locks, each position carries a **lock weight**: the square root of the locked units times the days remaining over 365. Longer lock periods give more initial power, which decays as the unlock date approaches.

**Congratulations** — you've completed Locks & Governance! You've locked units, gained voting power, created a proposal, voted, and tallied the results.`,
      apiCall: {
        method: 'GET',
        path: '/governance/voting-power',
        description: 'View the agent\'s governance voting power breakdown',
        authType: 'agent',
        authTokenRef: '$agentToken'
      },
      validation: {
        successStatusCodes: [200]
      },
      requiresStepId: 'tally-votes',
      notes: 'Track complete! You\'ve explored locks for voting power, governance proposals and decision-making in the Agent Senate. On production frames the same votes come from members instead of locks.'
    }
  ]
}
