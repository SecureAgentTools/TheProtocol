import type { GuidedTour } from '../tour.types'

// AGORA — "From window-shopping to your first trade". Walks the real Discover Stocks →
// Exchange Desk → order ticket → (founder) list-your-org path. Anchors are added as
// data-tour attrs in StockDiscovery.vue, ExchangeDesk.vue and DashboardSidebar.vue.
export const agoraTour: GuidedTour = {
  id: 'agora',
  title: 'AGORA Market',
  subtitle: 'From window-shopping to your first trade',
  icon: 'mdi:chart-line',
  accent: '#00e5c7',
  estMinutes: 6,
  steps: [
    {
      id: 'intro', title: 'Welcome to AGORA', placement: 'center',
      body: '**AGORA** is the on-platform market: organizations list points, agents trade them. Launches, a live order book, distributions, even cross-frame "passport" trading.\n\nThis tour spotlights the **real** interface as you go. Use **Next** (or →) to move along; **Skip** any time.',
    },
    {
      // §WALLETAGENT (2026-09-02) — HIS ask: the agent-gated tours start by guiding the creation of
      // the wallet agent and explain it short and analytical. `create-wallet` opens the quick
      // modal in wallet mode when no agent is active, and simply continues when one is.
      id: 'wallet', title: 'You act as your wallet agent here', placement: 'center',
      body: 'An **agent** is an identity on this registry: a DID, credentials and a ledger account. It does not have to be software.\n\n' +
        'Your **wallet agent** is your first identity: it holds your funds, pays and votes with its own address, under your name. ' +
        'Later you can create more capable agents and move funds to them with one transfer, or run your own agent with this identity\'s credentials — it becomes that agent, balance and history included.\n\n' +
        'If you have no agent yet, the button below creates your wallet agent; if you already act as one, just continue.',
      cta: { label: 'Create my wallet agent', do: 'create-wallet' },
    },
    {
      // §FESUITE: the sidebar names each item's anchor after its path ('nav-' + path); AGORA Listings moved from /stocks to
      // /agora/listings, so 'nav-stocks' pointed at nothing on every frame.
      id: 'nav', title: 'Find the market', anchor: 'nav-agora-listings', placement: 'right', route: '/agora/listings',
      body: 'It all starts at **AGORA Listings** in the sidebar. This page is public: browse listings across every federated market before you place a single order.',
    },
    {
      id: 'index', title: 'The AGORA-10 index', anchor: 'agora-index,agora-hero', placement: 'bottom',
      body: 'The **AGORA-10** strip is a value-weighted index of the network\'s top tickers. Click a chip to jump straight to that listing. The tiles below summarise listings, total market cap and 24h notional across all markets.',
      live: { method: 'GET', path: '/agora/index', label: 'Fetch the live AGORA-10 ▸' },
    },
    {
      id: 'card', title: 'A listing card', anchor: 'agora-stock-card,agora-hero', placement: 'auto',
      body: 'Each card is one organization\'s listing: last price, 24h change, a sparkline, and its home market. **Local** listings trade right here; **foreign** ones you buy with a one-click **passport** relay to their home frame.',
      live: { method: 'GET', path: '/agora/listings', label: 'List live markets ▸' },
    },
    {
      id: 'trade-btn', title: 'To the trading desk', anchor: 'agora-trade-btn,agora-hero', placement: 'auto',
      body: '**Trade on the Desk** opens the full order ticket for this listing. Let\'s head there.',
      cta: { label: 'Open the Desk →', do: 'click-anchor' },
    },
    {
      id: 'desk', title: 'The AGORA Desk', anchor: 'agora-ticket', placement: 'left', route: '/agora', requireAgent: true,
      body: 'This is the **AGORA Desk**. You trade here **as one of your agents** (the switcher up top). Right rail = your **order ticket**; center = chart + order book; left rail = every market.',
    },
    {
      id: 'book', title: 'The order book', anchor: 'agora-orderbook', placement: 'right',
      body: 'The **order book** shows live bids (green) and asks (red) with depth. Click any price level to pre-fill it into your ticket — perfect for hitting a specific bid or ask.',
    },
    {
      id: 'side', title: 'Buy or sell', anchor: 'agora-side', placement: 'left',
      body: 'Build an order by choosing a **side**: **Buy** to acquire points, **Sell** to offload them.',
    },
    {
      id: 'type', title: 'Order type', anchor: 'agora-type', placement: 'left',
      body: '**LIMIT** sets your own price and rests on the book until matched. **MARKET** fills immediately at the best price. Limit is the safer first move.',
    },
    {
      id: 'qty', title: 'Size the order', anchor: 'agora-qty', placement: 'left',
      body: 'Enter a **quantity** of points (a LIMIT order also needs a price above). **MAX** sizes to your balance, and the receipt previews notional + fee before you commit. No surprises.',
    },
    {
      id: 'place', title: 'Place it', anchor: 'agora-place', placement: 'top',
      body: '**PLACE** submits your order. Anything over ~10k notional asks you to confirm first. Once matched it lands in **My Open Orders** and your **Holdings** just below the ticket.',
    },
    {
      id: 'list', optional: true, /* §WALLETAGENT 2026-09-02: needs data a fresh account lacks (engine gate) */ title: 'Founders: list your org', anchor: 'agora-list-org', placement: 'bottom',
      body: 'Run an organization? **LIST YOUR ORG** opens a launch: pick total points, the launch allocation and a launch price. After a market admin approves it, buyers fund the launch and secondary trading opens.',
    },
    {
      id: 'outro', title: 'You\'ve got the map', placement: 'center',
      body: 'That\'s AGORA end-to-end: **discover → trade → list**. Points are the registry ledger and every cent moves through one escrow mover, so the books always balance (Δ=0).\n\nExplore a market whenever you\'re ready. You now know your way around.',
    },
  ],
}
