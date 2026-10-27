import type { TutorialTrack } from '../types/tutorial.types'
import { SANDBOX_TUTORIAL_LOGIN } from './sandboxLogin'

/**
 * Track 13: AGORA Trading — list an org's stock and trade it
 *
 * The hands-on companion to the AGORA guided tour. A self-contained, end-to-end run:
 *   SETUP (1-4): dev login → bootstrap → create the founder/trader agent → agent JWT
 *   LIST  (5-9): create an organization → fund the agent → create an IPO listing →
 *                admin-approve it → view it
 *   TRADE (10-13): buy from the IPO → place a limit order → see the book → see the portfolio
 *
 * One agent plays founder (funds the listing) AND trader (buys IPO + places orders).
 * Endpoint auth verified from routers/exchange.py + organizations.py + services/exchange_service.py:
 *   POST /organizations                              dev JWT (caller becomes owner)
 *   POST /teg/treasury/fund-agent                    admin dev JWT
 *   POST /exchange/listings                          dev JWT, must be org OWNER; funding_agent_did
 *                                                    must be the caller's own agent; pays LISTING_FEE
 *   POST /exchange/admin/listings/{ref}/approve      admin
 *   POST /exchange/listings/{ref}/launch/buy            agent JWT
 *   POST /exchange/orders                            agent JWT
 *   GET  /exchange/listings/{ref}, /book, /portfolio public / agent
 * Gotcha: approval gates IPO + orders (both 409 until approved+trading). First limit order skips
 *   the price-band check (no prior trade), so any tick-multiple price is accepted.
 */
export const agoraTradingTrack: TutorialTrack = {
  id: 'agora-trading',
  title: 'AGORA Trading',
  subtitle: 'List an org on AGORA and trade it',
  description: "Stand up a company, launch it on AGORA, then buy points and place a limit order: the full listing lifecycle, all settled through one Δ-neutral escrow mover.",
  icon: 'chart-line',
  color: 'cyan',
  gradientFrom: 'from-cyan-500',
  gradientTo: 'to-emerald-600',
  estimatedMinutes: 9,
  prerequisites: ['agent-lifecycle', 'token-economics'],
  completionTitle: 'Market Maker',
  steps: [
    // ─── SETUP ───
    {
      id: 'authenticate',
      stepNumber: 1,
      title: 'Authenticate as Developer',
      subtitle: 'Obtain a sandbox JWT',
      explanation: 'Log in with the pre-provisioned tutorial developer account. This JWT creates the organization, funds the agent (admin), and authorises the listing.',
      apiCall: {
        method: 'POST',
        path: '/auth/login',
        description: 'Authenticate with the sandbox tutorial account',
        body: { ...SANDBOX_TUTORIAL_LOGIN },
        authType: 'none',
      },
      captures: [{ key: 'sandboxDevToken', responsePath: 'access_token', displayLabel: 'Developer JWT', sensitive: true }],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] },
      notes: 'Form-encoded login. This developer becomes the organization owner in Step 5.',
    },
    {
      id: 'bootstrap-agent',
      stepNumber: 2,
      title: 'Bootstrap the Founder Agent',
      subtitle: 'Get a one-time creation credential',
      explanation: 'Request a short-lived bootstrap token. It authorises exactly one agent creation and expires in ~5 minutes.',
      apiCall: {
        method: 'POST',
        path: '/onboard/bootstrap/request-token',
        description: 'Request a bootstrap token',
        body: { agent_type_hint: 'tutorial_founder', requested_by: 'tutorial-user' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [{ key: 'bootstrapToken', responsePath: 'bootstrap_token', displayLabel: 'Bootstrap Token', sensitive: true }],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['bootstrap_token'] },
      requiresStepId: 'authenticate',
    },
    {
      id: 'create-agent',
      stepNumber: 3,
      title: 'Create the Founder / Trader Agent',
      subtitle: 'Birth the agent that lists + trades',
      explanation: 'Create one agent that will both **fund the listing** (founder) and **trade** it. `metadata.teg_enabled: true` provisions its ledger account so it can be funded and escrow trades.',
      apiCall: {
        method: 'POST',
        path: '/onboard/create_agent',
        description: 'Create the founder/trader agent',
        body: {
          agent_did_method: 'theprotocol',
          agent_card: {
            schemaVersion: '1.0',
            agentVersion: '1.0',
            name: 'AGORA Tutorial Trader',
            description: 'Founder + trader agent for the AGORA Trading tutorial: creates a listing and trades it',
            url: 'http://localhost:8100/agents/agora-tutorial-trader',
            humanReadableId: 'agora-tutorial-trader',
            provider: { name: 'Tutorial Developer', organization: 'TheProtocol', contact: 'tutorial-admin@theprotocol.cloud' },
            capabilities: { a2aVersion: '1.0', inbound_protocols: ['cosv1'], outbound_protocols: ['cosv1'], tags: ['tutorial', 'agora', 'trading'] },
            authSchemes: [{ scheme: 'oauth2', client_id: 'pending', tokenUrl: 'http://registry-test:8000/api/v1/auth/agent/token' }],
            service_endpoints: [{ type: 'messaging', url: 'http://localhost:8100/agents/agora-tutorial-trader' }],
            metadata: { status: 'active', teg_enabled: true },
          },
        },
        authType: 'bootstrap',
        authTokenRef: '$bootstrapToken',
      },
      captures: [
        { key: 'traderDid', responsePath: 'agent_did', displayLabel: 'Trader DID' },
        { key: 'traderClientId', responsePath: 'client_id', displayLabel: 'Client ID' },
        { key: 'traderClientSecret', responsePath: 'client_secret', displayLabel: 'Client Secret', sensitive: true },
      ],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['agent_did', 'client_id', 'client_secret'] },
      requiresStepId: 'bootstrap-agent',
      notes: 'client_secret is shown ONCE. The agent now has a DID + a TEG wallet.',
    },
    {
      id: 'agent-token',
      stepNumber: 4,
      title: 'Get the Agent JWT',
      subtitle: 'Authenticate as the trader',
      explanation: 'Exchange the agent client credentials for an **agent JWT**. Buying at launch and placing orders run *as the agent*, so they need this token.',
      apiCall: {
        method: 'POST',
        path: '/auth/agent/token',
        description: 'Exchange client credentials for an agent JWT',
        body: { grant_type: 'password', username: '$traderClientId', password: '$traderClientSecret' },
        bodyDynamic: [
          { jsonPath: 'username', capturedKey: 'traderClientId' },
          { jsonPath: 'password', capturedKey: 'traderClientSecret' },
        ],
        authType: 'none',
      },
      captures: [{ key: 'traderToken', responsePath: 'access_token', displayLabel: 'Agent JWT', sensitive: true }],
      validation: { successStatusCodes: [200], requiredResponseKeys: ['access_token'] },
      requiresStepId: 'create-agent',
    },
    // ─── LIST ───
    {
      id: 'create-org',
      stepNumber: 5,
      title: 'Create an Organization',
      subtitle: 'The entity whose points you list',
      explanation: 'On AGORA, points belong to an **organization**. Create one: you (the developer) become its **owner**, which is required to list it on AGORA. The slug is auto-generated from the name.',
      apiCall: {
        method: 'POST',
        path: '/organizations',
        description: 'Create the issuing organization',
        body: { name: 'Tutorial Trading Co', description: 'Issuer for the AGORA Trading tutorial' },
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [
        { key: 'orgId', responsePath: 'id', displayLabel: 'Organization ID' },
        { key: 'orgSlug', responsePath: 'slug', displayLabel: 'Org Slug' },
      ],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['id'] },
      requiresStepId: 'agent-token',
    },
    {
      id: 'fund-agent',
      stepNumber: 6,
      title: 'Fund the Agent',
      subtitle: 'Treasury grant so it can list + trade',
      explanation: 'Listing charges a fee and trading escrows funds, so top the agent up from the treasury (admin action). The canonical funding endpoint emits a `TokensTransferred` event — Δ stays zero.',
      apiCall: {
        method: 'POST',
        path: '/teg/treasury/fund-agent',
        description: 'Grant the agent 50,000 units from the treasury',
        body: { target_agent_did: '$traderDid', amount: '50000', reason: 'tutorial_grant' },
        bodyDynamic: [{ jsonPath: 'target_agent_did', capturedKey: 'traderDid' }],
        authType: 'admin',
        authTokenRef: '$sandboxDevToken',
      },
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'create-org',
      notes: 'The tutorial account is a sandbox admin, so it can fund agents directly.',
    },
    {
      id: 'create-listing',
      stepNumber: 7,
      title: 'Create the Launch Listing',
      subtitle: 'List it on AGORA',
      explanation: "Create the listing: **total_shares** is the total points outstanding, **ipo_float** is the launch allocation, how many are sold to the public, **ipo_price** is the launch price. `funding_agent_did` must be one of your own agents: it pays the listing fee and holds the treasury position.",
      apiCall: {
        method: 'POST',
        path: '/agora/listings',
        description: 'Create a launch listing for the org',
        body: {
          organization_id: '$orgId',
          symbol: 'TUTCO',
          display_name: 'Tutorial Trading Co',
          total_shares: 1000000,
          ipo_float: 100000,
          ipo_price: '10.0',
          funding_agent_did: '$traderDid',
        },
        bodyDynamic: [
          { jsonPath: 'organization_id', capturedKey: 'orgId' },
          { jsonPath: 'funding_agent_did', capturedKey: 'traderDid' },
        ],
        authType: 'developer',
        authTokenRef: '$sandboxDevToken',
      },
      captures: [
        { key: 'listingId', responsePath: 'id', displayLabel: 'Listing ID' },
        { key: 'listingSymbol', responsePath: 'symbol', displayLabel: 'Ticker' },
      ],
      validation: { successStatusCodes: [200, 201], requiredResponseKeys: ['symbol'] },
      requiresStepId: 'fund-agent',
      notes: 'The listing starts UNAPPROVED — no trading until an admin approves it (next step).',
    },
    {
      id: 'approve-listing',
      stepNumber: 8,
      title: 'Approve the Listing',
      subtitle: 'Admin opens the listing for trading',
      explanation: 'A market admin reviews and **approves** the listing. Approval flips it to `trading` and unlocks the launch and the order book. Both reject with 409 until this runs.',
      apiCall: {
        method: 'POST',
        path: '/agora/admin/listings/$listingSymbol/approve',
        description: 'Admin-approve the listing',
        pathParams: { listing_ref: '$listingSymbol' },
        authType: 'admin',
        authTokenRef: '$sandboxDevToken',
      },
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'create-listing',
      notes: 'On a live market this is a governance/compliance gate; here the tutorial admin approves instantly.',
    },
    {
      id: 'view-listing',
      stepNumber: 9,
      title: 'View the Listing',
      subtitle: 'Confirm it is trading',
      explanation: 'Read the public listing detail: status should now be `trading`, with the launch allocation available and your opening price set.',
      apiCall: {
        method: 'GET',
        path: '/agora/listings/$listingSymbol',
        description: 'Fetch the public listing detail',
        pathParams: { listing_ref: '$listingSymbol' },
        authType: 'none',
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'approve-listing',
    },
    // ─── TRADE ───
    {
      id: 'ipo-buy',
      stepNumber: 10,
      title: 'Buy at Launch',
      subtitle: 'Acquire points at the launch price',
      explanation: 'Buy points directly from the public launch allocation at the launch price. Funds move buyer → escrow → issuer treasury through the one escrow mover, so the books stay balanced.',
      apiCall: {
        method: 'POST',
        path: '/agora/listings/$listingSymbol/launch/buy',
        description: 'Buy 100 points at launch',
        pathParams: { listing_ref: '$listingSymbol' },
        body: { qty: 100 },
        authType: 'agent',
        authTokenRef: '$traderToken',
      },
      captures: [{ key: 'purchaseId', responsePath: 'purchase_id', displayLabel: 'Purchase ID' }],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'view-listing',
      notes: 'Launch settlement is asynchronous (status allocated/refunding); you now hold points to trade.',
    },
    {
      id: 'place-order',
      stepNumber: 11,
      title: 'Place a Limit Order',
      subtitle: 'Rest a bid on the order book',
      explanation: 'Place a **limit buy** — your own price, resting on the book until matched. The price must be a multiple of the tick; the first order skips the volatility band (no prior trade yet). Buy orders escrow the notional up front.',
      apiCall: {
        method: 'POST',
        path: '/agora/orders',
        description: 'Place a resting limit buy order',
        body: { listing: '$listingSymbol', side: 'buy', order_type: 'limit', qty: 10, price: '10.0', client_order_id: 'tut-agora-1', tif: 'gtc', post_only: false },
        bodyDynamic: [{ jsonPath: 'listing', capturedKey: 'listingSymbol' }],
        authType: 'agent',
        authTokenRef: '$traderToken',
      },
      captures: [{ key: 'orderId', responsePath: 'order_id', displayLabel: 'Order ID' }],
      validation: { successStatusCodes: [200, 201] },
      requiresStepId: 'ipo-buy',
      notes: 'No resting sell to match, so the order rests OPEN — exactly what a maker bid looks like.',
    },
    {
      id: 'view-book',
      stepNumber: 12,
      title: 'View the Order Book',
      subtitle: 'See your bid in the depth',
      explanation: 'Read the public order book. Your limit buy should appear on the bid side: live CLOB depth, the same data the AGORA Desk renders.',
      apiCall: {
        method: 'GET',
        path: '/agora/listings/$listingSymbol/book?depth=12',
        description: 'Fetch the live order book',
        pathParams: { listing_ref: '$listingSymbol' },
        authType: 'none',
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'place-order',
    },
    {
      id: 'view-portfolio',
      stepNumber: 13,
      title: 'View Your Holdings',
      subtitle: 'Points held + open orders',
      explanation: "Finally, read the agent's AGORA holdings: your launch points, open orders and P&L. You've listed a company on AGORA and traded it, all settled Δ-neutral.",
      apiCall: {
        method: 'GET',
        path: '/agora/portfolio',
        description: 'Fetch the trader holdings',
        authType: 'agent',
        authTokenRef: '$traderToken',
      },
      validation: { successStatusCodes: [200] },
      requiresStepId: 'view-book',
      notes: 'That is the AGORA loop end-to-end: organization → launch → secondary order. Take the AGORA guided tour to see it in the UI.',
    },
  ],
}
