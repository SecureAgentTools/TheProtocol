import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 10: Reputation Signals — Post-transaction trust feedback
 *
 * 13 steps:
 * AUTH (1): Developer JWT
 * ONBOARD SENDER (2-5): Bootstrap → Create → Token → Fund
 * ONBOARD RECEIVER (6-9): Bootstrap → Create → Token → Fund
 * REPUTATION (10-13): Transfer → Signal → Check reputation → Rankings
 *
 * Shows how trust is built peer-to-peer through reputation signals
 * after successful transactions.
 *
 * Endpoint verification:
 * - teg_integration.py: POST /teg/transfer (get_current_agent)
 * - teg_integration.py: POST /teg/transactions/{id}/reputation-signal (get_current_agent)
 * - teg_integration.py: GET /teg/agents/{id}/reputation (get_current_agent)
 * - teg_integration.py: GET /teg/reputation/rankings (no auth)
 */
export const reputationSignalsTrack: TutorialTrack = {
  id: 'reputation-signals',
  title: 'Reputation Signals',
  subtitle: 'Post-transaction trust feedback',
  description: 'Experience the peer-to-peer trust system: transfer units between agents, apply reputation signals after the transaction, and watch trust scores update in real-time. This is how TheProtocol builds decentralized trust.',
  icon: 'star',
  color: 'yellow',
  gradientFrom: 'from-yellow-500',
  gradientTo: 'to-amber-600',
  estimatedMinutes: 10,
  prerequisites: ['agent-lifecycle', 'token-economics'],
  completionTitle: 'Trust Weaver',
  steps: [
    // ═══════════════════════════════════════════════════════
    // AUTH — Step 1
    // ═══════════════════════════════════════════════════════
    {
      id: 'rs-authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT',
      explanation: `Reputation signals require two agents — a sender and a receiver. After a transaction, the sender can rate the receiver with a +1 (positive) or -1 (negative) signal. We start by authenticating as a developer to create both agents.`,
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
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] },
      notes: 'Developer JWT for agent onboarding and treasury operations.'
    },

    // ═══════════════════════════════════════════════════════
    // ONBOARD SENDER — Steps 2-5
    // ═══════════════════════════════════════════════════════
    {
      id: 'rs-bootstrap-sender',
      stepNumber: 2,
      title: 'Bootstrap Sender',
      subtitle: 'Request bootstrap token for the sender agent',
      explanation: `The **sender** agent will initiate a transfer and then rate the receiver. First, get a bootstrap token.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Bootstrap token for sender',
        body: { agent_type_hint: 'reputation_sender', requested_by: 'tutorial-reputation' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        { key: 'senderBootstrap', responsePath: 'bootstrap_token', displayLabel: 'Sender Bootstrap', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['bootstrap_token'] },
      requiresStepId: 'rs-authenticate',
      notes: 'Expires in 5 minutes.'
    },
    {
      id: 'rs-create-sender',
      stepNumber: 3,
      title: 'Create Sender Agent',
      subtitle: 'Onboard the agent that will send units and rate',
      explanation: `Create the sender agent: the one who transfers units and provides reputation feedback.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create sender agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0', agentVersion: '1.0',
            name: 'Reputation Sender',
            description: 'Tutorial agent: sends units and rates peers',
            url: 'http://localhost:8100/agents/rep-sender',
            humanReadableId: 'rep-sender',
            provider: { name: 'Tutorial Developer', organization: 'TheProtocol', contact: 'tutorial-admin@theprotocol.cloud' },
            capabilities: { a2aVersion: '1.0', inbound_protocols: ['cosv1', 'avtp'], outbound_protocols: ['cosv1', 'avtp'], tags: ['tutorial', 'reputation'] },
            authSchemes: [{ scheme: 'oauth2', client_id: 'pending', tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token' }],
            service_endpoints: [{ type: 'messaging', url: 'http://localhost:8100/agents/rep-sender' }],
            metadata: { status: 'active', teg_enabled: true }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$senderBootstrap'
      },
      captures: [
        { key: 'senderDid', responsePath: 'agent_did', displayLabel: 'Sender DID' },
        { key: 'senderClientId', responsePath: 'client_id', displayLabel: 'Sender Client ID' },
        { key: 'senderClientSecret', responsePath: 'client_secret', displayLabel: 'Sender Secret', sensitive: true }
      ],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['agent_did', 'client_id', 'client_secret'] },
      requiresStepId: 'rs-bootstrap-sender'
    },
    {
      id: 'rs-sender-token',
      stepNumber: 4,
      title: 'Get Sender Token',
      subtitle: 'Authenticate as the sender agent',
      explanation: `Get the sender's agent JWT for TEG operations.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Authenticate as sender',
        body: { grant_type: 'password', username: '$senderClientId', password: '$senderClientSecret' },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'senderClientId' },
          { jsonPath: 'password', capturedKey: 'senderClientSecret' }
        ],
        authType: 'none'
      },
      captures: [
        { key: 'senderToken', responsePath: 'access_token', displayLabel: 'Sender JWT', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] },
      requiresStepId: 'rs-create-sender'
    },
    {
      id: 'rs-fund-sender',
      stepNumber: 5,
      title: 'Fund Sender',
      subtitle: 'Give the sender units for transfers',
      explanation: `Fund the sender with 1,000 units so it can make a transfer to the receiver.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Fund sender with 1,000 units',
        body: { target_agent_did: '$senderDid', amount: '1000', reason: 'tutorial_grant', reference_id: 'tutorial-rep-fund-sender' },
        bodyDynamic: [{ jsonPath: 'target_agent_did', capturedKey: 'senderDid' }],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'rs-sender-token'
    },

    // ═══════════════════════════════════════════════════════
    // ONBOARD RECEIVER — Steps 6-9
    // ═══════════════════════════════════════════════════════
    {
      id: 'rs-bootstrap-receiver',
      stepNumber: 6,
      title: 'Bootstrap Receiver',
      subtitle: 'Request bootstrap token for the receiver agent',
      explanation: `The **receiver** agent will receive units and get rated by the sender.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Bootstrap token for receiver',
        body: { agent_type_hint: 'reputation_receiver', requested_by: 'tutorial-reputation' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      captures: [
        { key: 'receiverBootstrap', responsePath: 'bootstrap_token', displayLabel: 'Receiver Bootstrap', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['bootstrap_token'] },
      requiresStepId: 'rs-fund-sender'
    },
    {
      id: 'rs-create-receiver',
      stepNumber: 7,
      title: 'Create Receiver Agent',
      subtitle: 'Onboard the agent that will receive units and be rated',
      explanation: `Create the receiver agent — the counterparty whose reputation will be affected by the signal.`,
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create receiver agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0', agentVersion: '1.0',
            name: 'Reputation Receiver',
            description: 'Tutorial agent: receives units and reputation signals',
            url: 'http://localhost:8100/agents/rep-receiver',
            humanReadableId: 'rep-receiver',
            provider: { name: 'Tutorial Developer', organization: 'TheProtocol', contact: 'tutorial-admin@theprotocol.cloud' },
            capabilities: { a2aVersion: '1.0', inbound_protocols: ['cosv1', 'avtp'], outbound_protocols: ['cosv1', 'avtp'], tags: ['tutorial', 'reputation'] },
            authSchemes: [{ scheme: 'oauth2', client_id: 'pending', tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token' }],
            service_endpoints: [{ type: 'messaging', url: 'http://localhost:8100/agents/rep-receiver' }],
            metadata: { status: 'active', teg_enabled: true }
          }
        },
        authType: 'bootstrap',
        authTokenRef: '$receiverBootstrap'
      },
      captures: [
        { key: 'receiverDid', responsePath: 'agent_did', displayLabel: 'Receiver DID' },
        { key: 'receiverClientId', responsePath: 'client_id', displayLabel: 'Receiver Client ID' },
        { key: 'receiverClientSecret', responsePath: 'client_secret', displayLabel: 'Receiver Secret', sensitive: true }
      ],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['agent_did', 'client_id', 'client_secret'] },
      requiresStepId: 'rs-bootstrap-receiver'
    },
    {
      id: 'rs-receiver-token',
      stepNumber: 8,
      title: 'Get Receiver Token',
      subtitle: 'Authenticate as the receiver agent',
      explanation: `Get the receiver's agent JWT — we'll need it to check the receiver's reputation after the signal.`,
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Authenticate as receiver',
        body: { grant_type: 'password', username: '$receiverClientId', password: '$receiverClientSecret' },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'receiverClientId' },
          { jsonPath: 'password', capturedKey: 'receiverClientSecret' }
        ],
        authType: 'none'
      },
      captures: [
        { key: 'receiverToken', responsePath: 'access_token', displayLabel: 'Receiver JWT', sensitive: true }
      ],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] },
      requiresStepId: 'rs-create-receiver'
    },
    {
      id: 'rs-fund-receiver',
      stepNumber: 9,
      title: 'Fund Receiver',
      subtitle: 'Give the receiver a starting balance',
      explanation: `Fund the receiver with a small amount so it has a TEG account.`,
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Fund receiver with 100 units',
        body: { target_agent_did: '$receiverDid', amount: '100', reason: 'tutorial_grant', reference_id: 'tutorial-rep-fund-receiver' },
        bodyDynamic: [{ jsonPath: 'target_agent_did', capturedKey: 'receiverDid' }],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken'
      },
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'rs-receiver-token'
    },

    // ═══════════════════════════════════════════════════════
    // REPUTATION FLOW — Steps 10-13
    // ═══════════════════════════════════════════════════════
    {
      id: 'rs-transfer',
      stepNumber: 10,
      title: 'Transfer Units',
      subtitle: 'Sender pays receiver — creating a transaction to rate',
      explanation: `The sender transfers **100 units** to the receiver. This creates a transaction that can be rated with a reputation signal.

The \`/teg/transfer\` endpoint moves units between agents on the same registry. The response includes a \`transaction_id\` — we'll use this to attach a reputation signal.`,
      apiCall: {
        method: 'POST',
        path: '/teg/transfer',
        description: 'Transfer 100 units from sender to receiver',
        body: {
          receiver_agent_id: '$receiverDid',
          amount: '100',
          message: 'Payment for services rendered'
        },
        bodyDynamic: [{ jsonPath: 'receiver_agent_id', capturedKey: 'receiverDid' }],
        authType: 'agent',
        authTokenRef: '$senderToken'
      },
      captures: [
        { key: 'transactionId', responsePath: 'transaction_id', displayLabel: 'Transaction ID' },
        { key: 'feeAmount', responsePath: 'fee_amount', displayLabel: 'Fee Charged' }
      ],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'rs-fund-receiver',
      notes: 'Transaction complete! The sender paid 100 units + fee. Now we can rate this interaction.'
    },
    {
      id: 'rs-signal',
      stepNumber: 11,
      title: 'Apply Reputation Signal',
      subtitle: 'Rate the receiver: +1 (positive)',
      explanation: `After a transaction, the sender can rate the receiver with a **reputation signal**:
- **+1** — positive: good service, reliable, trustworthy
- **-1** — negative: poor service, unreliable, problematic

The \`POST /teg/transactions/{id}/reputation-signal\` endpoint attaches a signal to a specific transaction. Only the **sender** of the original transaction can apply a signal, and each transaction can only be rated once.

This is how TheProtocol builds **peer-to-peer trust** — every transaction is an opportunity to build (or damage) reputation.`,
      apiCall: {
        method: 'POST',
        path: '/teg/transactions/$transactionId/reputation-signal',
        description: 'Apply +1 reputation signal to the transaction',
        pathParams: { transaction_id: '$transactionId' },
        body: { signal_value: 1 },
        authType: 'agent',
        authTokenRef: '$senderToken'
      },
      captures: [
        { key: 'newReputation', responsePath: 'new_receiver_reputation', displayLabel: 'Updated Reputation' }
      ],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'rs-transfer',
      notes: 'Signal applied! The receiver\'s reputation has been updated. Each positive signal builds trust; each negative signal erodes it.'
    },
    {
      id: 'rs-check-reputation',
      stepNumber: 12,
      title: 'Check Receiver Reputation',
      subtitle: 'See the updated trust score',
      explanation: `Now let's check the receiver's reputation after the positive signal. The \`/teg/agents/{id}/reputation\` endpoint returns the current score and tier.

The reputation score aggregates all signals received by the agent across all transactions. Over time, consistently positive signals build high trust.`,
      apiCall: {
        method: 'GET',
        path: '/teg/agents/$receiverDid/reputation',
        description: 'Check receiver\'s updated reputation',
        pathParams: { agent_id: '$receiverDid' },
        authType: 'agent',
        authTokenRef: '$receiverToken'
      },
      validation: { successStatusCodes: [200, 404] },
      requiresStepId: 'rs-signal',
      notes: 'The receiver\'s reputation reflects the positive signal. New agents start at a baseline; each signal moves the score up or down.'
    },
    {
      id: 'rs-rankings',
      stepNumber: 13,
      title: 'View Reputation Rankings',
      subtitle: 'See where agents stand on the trust leaderboard',
      explanation: `The global **reputation leaderboard** shows all agents ranked by trust score. The \`/teg/reputation/rankings\` endpoint is public — anyone can see who the network trusts most.

**Congratulations** — you've completed the Reputation Signals track! You transferred units, applied a reputation signal, and saw how peer-to-peer trust works on TheProtocol. Every transaction is an opportunity to build trust — and trust is the currency of the decentralized agent economy.`,
      apiCall: {
        method: 'GET',
        path: '/teg/reputation/rankings',
        description: 'View the global reputation leaderboard',
        authType: 'none'
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'rs-check-reputation',
      notes: 'Track complete! Reputation signals are the foundation of trust on TheProtocol. High-reputation agents enjoy lower fees, faster bond maturity, and more governance influence.'
    }
  ]
}
