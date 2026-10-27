import type { GuidedTour } from '../tour.types'

// Pocket — THE one mobile walkthrough (Commander directive 2026-07-09: exactly one
// full pass through the app; replayable from More → App tour). Auto-starts once on a
// user's first Pocket visit (PocketShell sets `pk_tour_done`). Anchors are `pk-*`
// data-tour attrs across PocketShell / Home / Trade / Earn / Agents / Approvals / More.
// Pocket routes live under /pocket/* inside PocketShell (GuidedTour is mounted there).
//
// §POCKETBRIDGE5 W-T — brought current with batches 3-5: the walkthrough now
// covers the synced watchlist + price alerts, POST A JOB, the assistant, the
// typed notification doors and the dispute record. A tour that describes last
// month's app is the §BRIDGE P4 mc-pulse defect wearing friendlier clothes.
export const pocketTour: GuidedTour = {
  id: 'pocket',
  title: 'Pocket walkthrough',
  subtitle: 'Your agent economy, in your pocket',
  icon: 'mdi:cellphone',
  accent: '#00d4ff',
  estMinutes: 4,
  steps: [
    {
      id: 'intro', title: 'Welcome to Pocket', placement: 'center',
      body: "Pocket is the **simple face** of TheProtocol — your agents, money and safety controls laid out for one thumb.\n\nThis is the only tour you need: one pass through every tab. Use **Next** (or →); **Skip** any time — you can replay it later from **More → App tour**.",
    },
    {
      // §WALLETAGENT — the first-run card exists only for an account with no agent, so the step
      // is OPTIONAL: skipped for everyone who already has one.
      id: 'wallet', title: 'Your wallet agent', anchor: 'ph-first-run', route: '/pocket/home', placement: 'bottom', optional: true,
      body: 'Everything in Pocket (sending, hiring, voting) is done as one of your agents. Your **wallet agent** is the first: an identity with a DID, credentials and a ledger account, no code required. ' +
        'It holds your funds; later you can move them to more capable agents with one transfer, or reuse this identity in an agent you run.',
      cta: { label: 'Create my wallet agent', do: 'create-wallet' },
    },
    {
      id: 'balance', title: 'Your total balance', anchor: 'pk-home-hero', placement: 'bottom', route: '/pocket/home',
      body: "Everything you hold, in your registry's own unit: liquid plus **locked**, across **all your agents** combined.\n\nBelow it, **today's flow** for the agent you're acting as: what settled in and out since midnight (and the chip says when its window is clipped). The eye hides the numbers when someone's looking over your shoulder.",
    },
    {
      id: 'actions', title: 'Send · Receive · Lock', anchor: 'pk-home-actions', placement: 'bottom',
      body: "The everyday moves live here: **Send** units to any agent, **Receive** with a QR, **Lock** units for governance weight, where this registry opens locks.\n\n**Advanced** is the door to the full Mission Control — the operator cockpit — whenever Pocket feels too small.",
    },
    {
      // §POCKETBRIDGE #PK29 — the lightbridge quick actions, in the walkthrough.
      id: 'quickactions', title: 'Quick actions — the lightbridge', anchor: 'pk-home-qa', placement: 'bottom',
      body: "The same command strip the bridge runs, thumb-shaped: **REQUEST** funding (or **FUND**, for admins), **SEND**, and doors to **VOTE**, **BID** and **POST WORK**.\n\nTap an account below to **target** it — the strip always says who is acting and on whom, and a blocked button tells you why.",
    },
    {
      id: 'accounts', title: 'Accounts', anchor: 'pk-home-recent', placement: 'top',
      body: "Your agents, **ranked by balance across your whole fleet** — like accounts in a wallet. Tap one to target it for the quick actions; tap **See all** for the full roster.",
    },
    {
      id: 'needsyou', title: 'NEEDS YOU — your command queue', anchor: 'pk-attn', placement: 'bottom',
      body: "Everything **blocked on a decision from you**, across every registry you hold an agent on: contracts offered, work to verify, **open votes**, bids to award, **open disputes**.\n\nRows are doors — a dispute row lands **on the dispute record itself**, a guild row on its order. The badge stays empty until a source has actually answered.",
    },
    {
      id: 'alerts', title: 'Alerts — notifications that go somewhere', anchor: 'pk-bell', placement: 'bottom',
      body: "Your typed notifications land here and **tapping one takes you to the thing itself**: a fill to Trade, guild news to Payments, a dispute to its record.\n\n**Price alerts** you set on Trade live here too (the registry watches the local market even while the app is closed). Pair a device under **More → Devices & alerts** for push.",
    },
    {
      id: 'tabbar', title: 'Getting around', anchor: 'pk-tabbar', placement: 'top',
      body: "Six tabs, thumb-reachable: **Home**, **Trade**, **Payments**, **Agents**, **Approvals**, **More**. Let's walk the rest.",
    },
    {
      id: 'trade', title: 'Trade: the AGORA market', anchor: 'pk-trade', placement: 'bottom', route: '/pocket/trade',
      body: "An order-book market for the points of **agent organizations**. Live candles, depth, and a tape: tap any ticker to see its chart and place a buy or sell **as one of your agents**. Fills come back as receipts: the price paid, exactly.",
    },
    {
      id: 'tradetools', title: 'Watchlist · alerts · your book', anchor: 'pk-trade-tools', placement: 'bottom',
      body: "Star a ticker and the **watchlist syncs to your account**: same stars on your desktop. Set a **price alert** and the registry watches the local market for you.\n\nYour positions carry a value line and a 24h read that **states its own limits** (which positions it covers, and when there's no history yet).",
    },
    {
      id: 'earn', title: 'Payments: the work exchange', anchor: 'pk-earn', placement: 'bottom', route: '/pocket/payments',
      body: "The Guild: an open labor market where agents **post bounties, bid, deliver and get paid** from escrow. Completed work builds a reputation that travels with the agent across registries.",
    },
    {
      // §TOURTRUTH (2026-09-02) — the Earn tab bar (and its Post button) renders only for a vault that holds an agent credential.
      id: 'post', optional: true, title: 'Post a job', anchor: 'pk-earn-post', placement: 'bottom',
      body: "The poster half, on your phone: title, spec, bounty — posting **escrows the bounty** (that's the money moment, so it asks for your biometric when the lock is armed) and it comes **back in full** if you cancel while the order is still open.",
    },
    {
      id: 'agents', title: 'Your agents', anchor: 'pk-agents', placement: 'bottom', route: '/pocket/agents',
      body: "Every agent you own — balance, status and details in one place. Agents are the **actors** here: they hold the money, do the work, and trade the markets. You're the one holding their leash.",
    },
    {
      id: 'assistant', title: 'The assistant — three brains', anchor: 'pk-assistant', placement: 'bottom', route: '/pocket/assistant',
      body: "Ask or command. **Commands** is a deterministic grammar — instant, free, on-device. **Claude** (when your operator has wired the bridge) and **your own API key** can actually converse.\n\nThe iron rule: brains **fill tickets and open doors — only YOU confirm money**. Hold the mic to talk, where your browser supports it.",
    },
    {
      id: 'approvals', title: 'Approvals — the leash', anchor: 'pk-appr-picker', placement: 'bottom', route: '/pocket/approvals',
      body: "IRONKEY oversight. Pick an agent to see every **delegation grant** and **capability permit** it holds — the exact authority it's been given — and revoke any single one instantly.",
    },
    {
      id: 'panic', title: 'The EMERGENCY freeze', anchor: 'pk-panic', placement: 'bottom',
      body: "The control you hope to never need. Lost your phone? An agent acting strange? This **freezes all delegated authority on every agent you own** — one action, biometric + typed confirmation, no undo.\n\nIt's always right here, and also under **More → Emergency**.",
    },
    {
      id: 'more', title: 'More — devices, security, Advanced', anchor: 'pk-more-adv', placement: 'top', route: '/pocket/more',
      body: "Pair your phone for push alerts, flip the **biometric lock**, review activity, **connect your Claude** to the pocket toolset — and switch to **Advanced mode** for the full Mission Control. Pocket and Advanced are the same account, two depths.",
    },
    {
      id: 'outro', title: "That's Pocket", placement: 'center',
      body: "Balance and today's flow up top, markets and work in the middle, the assistant one tab away, the leash and the **EMERGENCY freeze** under Approvals.\n\nReplay this any time from **More → App tour**. Welcome aboard.",
    },
  ],
}
