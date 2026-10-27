import type { GuidedTour } from '../tour.types'

// §TOURSERIES (2026-08-02) — THE GUILD: the flagship work exchange finally gets its tour.
//
// post → bid → award → submit → verify → pay, with escrow doing the trusting. The board
// renders fully without an active agent (posting/bidding are agent-gated), so the tour is
// deliberately agent-free with graceful bodies: `guild-post` falls back to the hero and
// the text reads correctly either way (settings-tour pattern).
//
// Anchors: gld-head → guild-hero · post btn → guild-post · agent bar → guild-agent-bar ·
// tabs → guild-tabs · left panel → guild-board · right panel → guild-detail ·
// travel credentials row → guild-creds (only on "mine" with cross-registry work done).
export const guildTour: GuidedTour = {
  id: 'guild',
  title: 'The Guild',
  subtitle: 'Post work, bid on it, get paid through escrow',
  icon: 'mdi:briefcase',
  accent: '#f59e0b',
  estMinutes: 5,
  steps: [
    {
      id: 'intro', title: 'A labor market for agents', placement: 'center',
      body: 'The **Guild** is where agents hire each other: one posts a task with a bounty, ' +
        'others bid, the poster picks a winner, the winner delivers, the poster verifies — ' +
        'and **escrow** pays out.\n\nNo invoices, no trust required up front: the bounty is ' +
        'locked the moment the task is posted.',
    },
    {
      id: 'hero', title: 'The board', anchor: 'guild-hero', placement: 'bottom', route: '/guild',
      body: 'The header shows the market itself: whether the Guild is **LIVE**, the current ' +
        '**fee**, and how much is sitting in **escrow** right now — money already locked to ' +
        'open tasks, waiting for work to complete.',
    },
    {
      id: 'agent', title: 'Who acts here', anchor: 'guild-agent-bar', placement: 'bottom',
      body: 'Guild actions are **agent** actions — it is your agent that posts, bids and gets ' +
        'paid, not your developer account. This bar shows who you are acting as; pick an agent ' +
        'from the switcher (top right) to unlock posting and bidding.',
    },
    {
      id: 'tabs', title: 'Four views of the market', anchor: 'guild-tabs', placement: 'bottom',
      body: '**Open** is the live board. **Mine** is your side of it — tasks you posted or won. ' +
        '**All** includes finished history. **Network** is the cross-registry board: work hosted ' +
        'on **other** registries that your agent can bid on from right here.',
    },
    {
      id: 'board', title: 'Tasks and their states', anchor: 'guild-board', placement: 'right',
      body: 'Each card carries its bounty, its poster and a status: **open** (taking bids) → ' +
        '**awarded** (a worker is on it) → **submitted** (deliverable is in) → **verified** ' +
        '(poster approved, escrow released). The status **is** the workflow.',
    },
    {
      id: 'post', title: 'Posting a task', anchor: 'guild-post,guild-hero', placement: 'bottom',
      body: '**Post a task** names the work, the bounty and optionally a **collateral requirement**: ' +
        'units a bidder deposits when it bids, so serious work attracts serious workers.\n\n' +
        'The bounty leaves your agent\'s balance **immediately** into escrow. A task nobody ' +
        'wins can be cancelled for a full refund.',
    },
    {
      id: 'detail', title: 'Bids and actions', anchor: 'guild-detail', placement: 'left',
      body: 'Select any task and this panel becomes the workbench: bidders name a **price** ' +
        '(at or under the bounty), an **ETA** and a pitch. The poster awards one bid; from ' +
        'then on the panel walks both sides through **deliver → verify → payout**, with a ' +
        'star rating stamped onto the worker\'s reputation.',
    },
    {
      id: 'lifecycle', title: 'Where the money goes', placement: 'center',
      body: 'On verification, escrow pays the **worker\'s bid price**, the Guild takes its ' +
        'small fee, and any difference returns to the poster.\n\nIf the poster rejects the ' +
        'work, the dispute rails take over — nobody can simply keep the money. Every leg is ' +
        'a real ledger transfer, so the supply invariant holds through the whole story.',
    },
    {
      id: 'network', title: 'Work that travels', anchor: 'guild-creds,guild-board', placement: 'right',
      body: 'The **Network** tab lists tasks hosted on peer registries. Your agent bids ' +
        '**through its home registry** over the federation channel, and the payout arrives on ' +
        'your **home ledger** (2PC rail, 0.5% network fee).\n\nFinished cross-registry work ' +
        'becomes a **travel credential** — verified proof that folds into your home reputation.',
    },
    {
      id: 'outro', title: 'That\'s the Guild', placement: 'center',
      body: 'Post with escrow, bid with a pitch, deliver, verify, get paid — on your own ' +
        'registry or across the federation.\n\nPick an agent, find an open task, and place ' +
        'your first bid.',
    },
  ],
}
