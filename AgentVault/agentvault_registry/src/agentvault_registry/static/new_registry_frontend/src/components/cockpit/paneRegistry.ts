/**
 * §COCKPIT P1 (2026-08-31) — the pane registry.
 *
 * R2: a saved layout names panes as STRINGS. A registry where one of those
 * panes cannot exist (a data source this deployment does not serve) must not
 * silently drop the tile the user saved — that is the §DISCREFINE failure in a
 * new costume: a door that quietly is not there. Every pane therefore declares
 * an `available` predicate, and `PaneShell` renders an honest "not available on
 * this registry, and here is why" tile for the ones that answer false.
 *
 * `refreshMode` is rendered as a chip on every pane, because a number with no
 * stated freshness is a number you cannot act on: LIVE = pushed over the shared
 * socket, POLL = re-read on a stated interval, ONCE = read at mount.
 */
import type { Component } from 'vue'
import type { RegistryConfig } from '@/composables/useRegistryConfig'
import { streamableFrames } from '@/composables/useLedgerStream'
import type { AdminAction } from '@/composables/usePermissions'

export type PaneId =
  | 'decisions' | 'agents' | 'denials'
  | 'conservation' | 'money' | 'fleet'
  | 'stop' | 'latency' | 'telemetry' | 'agentops' | 'ledger' | 'channels'
  | 'heartbeat' | 'instructions' | 'market' | 'holdings' | 'receipts'
  // ⚠ A NEW PANE IS TWO PLACES: this union and the PANES record. The registry lookup keeps
  // working when only the record is updated (it is a plain object at runtime), so the miss
  // is invisible until the type checker is asked — `PANES.book` was an error while the
  // pane rendered perfectly. Same family as the three-place column: migration, schema, ORM.
  | 'book' | 'bookmini' | 'chats' | 'failures' | 'earnings' | 'agentlogs' | 'work'
  | 'quickactions'
  // §COCKPITDESK (2026-10-15): seven doors to the views a desk most often sends a person to.
  | 'webhooks' | 'senate' | 'forex' | 'orgs' | 'guildboard' | 'release' | 'settlements'

export type RefreshMode = 'live' | 'poll' | 'once'

export interface PaneContext {
  config: RegistryConfig
  isAdmin: boolean
  /** §COCKPITDESK (2026-10-15) — the admin sub-flag rule (`hasAdminFlag`): an admin pane is available to whoever its
   *  route and its read admit, not to every admin. Absent ⇒ `isAdmin` decides. */
  adminCan?: (action: AdminAction) => boolean
}

const adminFlag = (ctx: PaneContext, action: AdminAction): boolean => (ctx.adminCan ? ctx.adminCan(action) : ctx.isAdmin)

export interface PaneDef {
  id: PaneId
  titleKey: string
  titleFallback: string
  icon: string
  refreshMode: RefreshMode
  /** Seconds between re-reads for `poll` panes. Ignored otherwise. */
  pollSeconds?: number
  loader: () => Promise<Component>
  /** False ⇒ the tile renders the honest unavailable state carrying `unavailableReason`. */
  available: (ctx: PaneContext) => boolean
  unavailableReason: string
  /** Two columns wide on a wide desk. */
  wide?: boolean
  /**
   * §COCKPITPOLISH P3 — TRUE when a control on this pane MAKES SOMETHING HAPPEN.
   *
   * The desk header rendered `read-only` unconditionally, and this file's sibling view
   * still claimed in its own docstring that "every pane is a thin mount over a read".
   * That stopped being true twice: STOP revokes mandates and deactivates agents, the
   * decision queue grants consent, and §COCKPITA's instruct makes an agent act. A badge
   * that is wrong in the REASSURING direction is the worst kind — it tells the viewer
   * nothing here can act while three panes can. Declared per pane so the header counts
   * what is actually on the board instead of asserting a property of the whole surface.
   */
  acts?: boolean
}

export const PANES: Record<PaneId, PaneDef> = {
  decisions: {
    id: 'decisions', titleKey: 'cockpit.pane.decisions', titleFallback: 'Decisions',
    icon: 'mdi:gavel', refreshMode: 'live', pollSeconds: 20, wide: true, acts: true,
    loader: () => import('@/components/cockpit/PaneDecisions.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §RAT (P8b) — the agents YOU own, with metrics and deployment state. Distinct from
   *  `agents` (Agents alive), which is a REGISTRY-WIDE population count: this one is
   *  yours, pinned, and says three separate things about each row instead of one light. */
  agentops: {
    id: 'agentops', titleKey: 'cockpit.pane.agentops', titleFallback: 'Your agents',
    icon: 'mdi:robot-outline', refreshMode: 'poll', pollSeconds: 30, wide: true,
    loader: () => import('@/components/cockpit/PaneAgentOps.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §HEARTBEAT (§COCKPITPOLISH P5c) — HIS ASK. Who called this registry, how recently,
   *  and what our own probe says, side by side. ⚠ There is NO dedicated heartbeat signal:
   *  `POST /agents/heartbeat` merely rides `get_current_agent`, so this measures "it called
   *  us with its own credentials" and the pane prints that sentence rather than implying a
   *  protocol we do not run. Filter chips (LIVE/QUIET/ALL) are Option A of the fork —
   *  parameterised pane instances would have made every saved layout carry `id + params`
   *  forever, a permanent format cost for side-by-side comparison rather than new facts. */
  heartbeat: {
    id: 'heartbeat', titleKey: 'cockpit.pane.heartbeat', titleFallback: 'Heartbeats',
    icon: 'mdi:heart-pulse', refreshMode: 'poll', pollSeconds: 30, wide: true,
    loader: () => import('@/components/cockpit/PaneHeartbeat.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITPOLISH P7.1 — the audit rows the instruct control has written since §COCKPITA
   *  R4 and which nothing rendered. Read-only over a rail that already exists. */
  instructions: {
    id: 'instructions', titleKey: 'cockpit.pane.instructions', titleFallback: 'Instructions sent',
    icon: 'mdi:history', refreshMode: 'poll', pollSeconds: 60,
    loader: () => import('@/components/cockpit/PaneInstructions.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITSHOW C2a — HIS ASK: *"a trading modul … a ticker of what is selling"*.
   *  Public venue data, no acting agent needed. Split from `holdings` on purpose: they
   *  answer different questions AND need different authority. */
  market: {
    id: 'market', titleKey: 'cockpit.pane.market', titleFallback: 'Market',
    icon: 'mdi:chart-line', refreshMode: 'poll', pollSeconds: 45,
    loader: () => import('@/components/cockpit/PaneMarket.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITSHOW C2b — *"showing your holdings"*. 🔴 The ONLY pane on this desk that
   *  follows the header's acting-agent switcher, because `/agora/portfolio` is
   *  agent-tier and answers for whoever holds the JWT. It says so on screen. */
  holdings: {
    id: 'holdings', titleKey: 'cockpit.pane.holdings', titleFallback: 'Your holdings',
    icon: 'mdi:briefcase', refreshMode: 'poll', pollSeconds: 60,
    loader: () => import('@/components/cockpit/PaneHoldings.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITUP U3 — his ask: *"a quick action modul/pane like the bridge has"*. A MOUNT of
   *  `BridgeQuickActions`, not a second copy: same rails, same `AmountActionModal`, same
   *  disabled-and-says-why law. 🔴 `acts: true` — this is the second pane on the desk that
   *  can move money, and the header badge counts it so a board carrying it never reads
   *  "read-only". Follows the header switcher (like `holdings`) and states that on screen. */
  quickactions: {
    id: 'quickactions', titleKey: 'cockpit.pane.quickactions', titleFallback: 'Quick actions',
    icon: 'mdi:lightning-bolt', refreshMode: 'once', acts: true,
    loader: () => import('@/components/cockpit/PaneQuickActions.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITCHATS — his ask: an overview of the latest active conversations, scoped to
   *  the DEVELOPER — "all chats he has access to from his org or agents". A mount over
   *  `GET /chat/conversations`, whose own docstring already promises exactly that scope
   *  ("a developer's inbox spans their own rows plus their local agents' rows"). No second
   *  inbox query: two surfaces answering "what is mine" is how they come to disagree. */
  chats: {
    id: 'chats', titleKey: 'cockpit.pane.chats', titleFallback: 'Conversations',
    icon: 'mdi:chat', refreshMode: 'poll', pollSeconds: 45,
    loader: () => import('@/components/cockpit/PaneChats.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITBOOK — the ACCOUNT-WIDE book, and the deliberate opposite of `holdings`.
   *  🔴 `holdings` follows the acting agent and answered "holds no shares on this venue"
   *  while this account's agents held 2.7M shares across three listings — the acting agent
   *  just was not one of the ~80 that hold any. A per-agent rail cannot answer "what do I
   *  own", so this one is developer-tier and says on screen that it ignores the switcher.
   *  `tall` because an analytics board with a candle chart is the one pane on this desk
   *  whose whole point is a large readable surface. */
  book: {
    id: 'book', titleKey: 'cockpit.pane.book', titleFallback: 'Your book',
    icon: 'mdi:chart-candlestick', refreshMode: 'poll', pollSeconds: 90, wide: true,
    loader: () => import('@/components/cockpit/PaneBook.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** The one-column form of the same rail, for a board that needs the number without the
   *  board. Same endpoint, same rules — never a second answer to the same question. */
  bookmini: {
    id: 'bookmini', titleKey: 'cockpit.pane.bookmini', titleFallback: 'Book value',
    icon: 'mdi:chart-line-variant', refreshMode: 'poll', pollSeconds: 120,
    loader: () => import('@/components/cockpit/PaneBookMini.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITSHOW C3 — the decision TRAIL. The desk had two aggregate views of consent
   *  and no way to see one decision; the receipt is what you produce when someone asks
   *  who agreed and what exactly they saw. Read-only over `/liability/receipts`. */
  receipts: {
    id: 'receipts', titleKey: 'cockpit.pane.receipts', titleFallback: 'Decision trail',
    icon: 'mdi:file-document-multiple-outline', refreshMode: 'poll', pollSeconds: 60, wide: true,
    loader: () => import('@/components/cockpit/PaneReceipts.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  agents: {
    id: 'agents', titleKey: 'cockpit.pane.agents', titleFallback: 'Agents alive',
    icon: 'mdi:robot-outline', refreshMode: 'poll', pollSeconds: 60,
    loader: () => import('@/components/cockpit/PaneAgentsAlive.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  // §COCKPITMODULES M1 — the mirror of `denials`: that pane shows what the gates REFUSED,
  // this shows what the system TRIED AND FAILED. They sit next to each other on purpose.
  // §COCKPITMODULES M2 — the income half of `book`, which shows only assets. Titled "Income" since 2026-10-25 (agentvault2-69's
  // gallery pass, his word "only compliant ones"): nothing is paid for a lock or for membership; the id and key stay.
  earnings: {
    id: 'earnings', titleKey: 'cockpit.pane.earnings', titleFallback: 'Income',
    icon: 'mdi:cash-multiple', refreshMode: 'poll', pollSeconds: 180,
    loader: () => import('@/components/cockpit/PaneEarnings.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  // §COCKPITMODULES M4 — the pair to `channels`: that shows an agent talking, this shows
  // it hurting. ⚠ icon must exist in the LOCAL map; an absent name renders BLANK.
  agentlogs: {
    id: 'agentlogs', titleKey: 'cockpit.pane.agentlogs', titleFallback: 'Agent logs',
    icon: 'mdi:format-list-bulleted', refreshMode: 'poll', pollSeconds: 90,
    loader: () => import('@/components/cockpit/PaneAgentLogs.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  // §COCKPITMODULES M3 — a SUMMARY, not a mount: `BridgeWorkView` is a focus-trapping modal.
  work: {
    id: 'work', titleKey: 'cockpit.pane.work', titleFallback: 'Work',
    icon: 'mdi:hammer-wrench', refreshMode: 'poll', pollSeconds: 120,
    loader: () => import('@/components/cockpit/PaneWork.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  failures: {
    id: 'failures', titleKey: 'cockpit.pane.failures', titleFallback: "What didn't happen",
    icon: 'mdi:alert-circle-outline', refreshMode: 'poll', pollSeconds: 120,
    loader: () => import('@/components/cockpit/PaneFailures.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  denials: {
    id: 'denials', titleKey: 'cockpit.pane.denials', titleFallback: 'Denials',
    icon: 'mdi:shield-alert-outline', refreshMode: 'poll', pollSeconds: 120,
    loader: () => import('@/components/cockpit/PaneDenials.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  conservation: {
    id: 'conservation', titleKey: 'cockpit.pane.conservation', titleFallback: 'Conservation',
    icon: 'mdi:scale-balance', refreshMode: 'poll', pollSeconds: 60,
    loader: () => import('@/components/cockpit/PaneConservation.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  money: {
    id: 'money', titleKey: 'cockpit.pane.money', titleFallback: 'Money in motion',
    icon: 'mdi:swap-horizontal', refreshMode: 'poll', pollSeconds: 45,
    loader: () => import('@/components/cockpit/PaneMoneyInMotion.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  stop: {
    id: 'stop', titleKey: 'cockpit.pane.stop', titleFallback: 'Stop',
    icon: 'mdi:hand-back-left-off-outline', refreshMode: 'live', pollSeconds: 60, acts: true,
    loader: () => import('@/components/cockpit/PaneStop.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  latency: {
    id: 'latency', titleKey: 'cockpit.pane.latency', titleFallback: 'Decision latency',
    icon: 'mdi:speedometer', refreshMode: 'poll', pollSeconds: 60,
    loader: () => import('@/components/cockpit/PaneLatency.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  telemetry: {
    id: 'telemetry', titleKey: 'cockpit.pane.telemetry', titleFallback: 'Consent telemetry',
    icon: 'mdi:chart-box-outline', refreshMode: 'poll', pollSeconds: 90,
    loader: () => import('@/components/cockpit/PaneTelemetry.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  channels: {
    // §COCKPITA R4 — progress (observe) + instruct (act) in ONE module, his call. POLL and
    // not LIVE: progress notes arrive on a Redis ring the desk re-reads, and claiming LIVE
    // on a polled pane is the freshness lie the chip exists to prevent.
    id: 'channels', titleKey: 'cockpit.pane.channels', titleFallback: 'Agent channels',
    icon: 'mdi:swap-horizontal', refreshMode: 'poll', pollSeconds: 20, wide: true, acts: true,
    loader: () => import('@/components/cockpit/PaneChannels.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  ledger: {
    // §COCKPITA R3 — LIVE by construction: it renders the shared socket's stream, so its
    // freshness chip must not claim a poll interval it does not have.
    id: 'ledger', titleKey: 'cockpit.pane.ledger', titleFallback: 'Your live ledger',
    icon: 'mdi:format-list-bulleted', refreshMode: 'live', wide: true,
    loader: () => import('@/components/cockpit/PaneLedger.vue').then(m => m.default),
    // Honest predicate, asked of the SAME function the stream uses to decide what to
    // connect to. If it can stream nothing, the pane says so instead of rendering an
    // empty list that looks like silence.
    available: () => streamableFrames().length > 0,
    unavailableReason: 'This registry does not serve an EventStore stream, so there is no live ledger to show.',
  },
  fleet: {
    id: 'fleet', titleKey: 'cockpit.pane.fleet', titleFallback: 'Fleet health',
    icon: 'mdi:pulse', refreshMode: 'poll', pollSeconds: 60,
    loader: () => import('@/components/cockpit/PaneFleetHealth.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITDESK (2026-10-15) — the endpoints this registry calls for you, the failing ones first. Account-wide. */
  webhooks: {
    id: 'webhooks', titleKey: 'cockpit.pane.webhooks', titleFallback: 'Webhooks',
    icon: 'mdi:webhook', refreshMode: 'poll', pollSeconds: 120,
    loader: () => import('@/components/cockpit/PaneWebhooks.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITDESK (2026-10-15) — proposals open for a vote, the one closing first on top. Public. */
  senate: {
    id: 'senate', titleKey: 'cockpit.pane.senate', titleFallback: 'Senate',
    icon: 'mdi:vote', refreshMode: 'poll', pollSeconds: 120,
    loader: () => import('@/components/cockpit/PaneSenate.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITDESK (2026-10-15) — the pool rates between this frame's currency and the ones it converts to. Public. */
  forex: {
    id: 'forex', titleKey: 'cockpit.pane.forex', titleFallback: 'Exchange rates',
    icon: 'mdi:currency-usd', refreshMode: 'poll', pollSeconds: 60,
    loader: () => import('@/components/cockpit/PaneForex.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITDESK (2026-10-15) — your firms, your role, and the spend approvals their agents wait on (B3 oversight). */
  orgs: {
    id: 'orgs', titleKey: 'cockpit.pane.orgs', titleFallback: 'Organizations',
    icon: 'mdi:account-group', refreshMode: 'poll', pollSeconds: 120,
    loader: () => import('@/components/cockpit/PaneOrgs.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITDESK (2026-10-15) — open work orders, the best-paying first: the work out there, where `work` is yours. */
  guildboard: {
    id: 'guildboard', titleKey: 'cockpit.pane.guildboard', titleFallback: 'Guild board',
    icon: 'mdi:trophy', refreshMode: 'poll', pollSeconds: 180,
    loader: () => import('@/components/cockpit/PaneGuildBoard.vue').then(m => m.default),
    available: () => true,
    unavailableReason: '',
  },
  /** §COCKPITDESK (2026-10-15) — admin: what this registry runs against the signed release channel. */
  release: {
    id: 'release', titleKey: 'cockpit.pane.release', titleFallback: 'Release channel',
    icon: 'mdi:rocket-launch', refreshMode: 'poll', pollSeconds: 300,
    loader: () => import('@/components/cockpit/PaneRelease.vue').then(m => m.default),
    available: (ctx) => adminFlag(ctx, 'platform'),
    unavailableReason: 'Only a registry admin with the platform flag can read the release channel.',
  },
  /** §COCKPITDESK (2026-10-15) — admin: cross-registry settlements, and the ones waiting for a decision. */
  settlements: {
    id: 'settlements', titleKey: 'cockpit.pane.settlements', titleFallback: 'Settlements',
    icon: 'mdi:bank', refreshMode: 'poll', pollSeconds: 120,
    loader: () => import('@/components/cockpit/PaneSettlements.vue').then(m => m.default),
    available: (ctx) => adminFlag(ctx, 'enforcement'),
    unavailableReason: 'Only a registry admin with the enforcement flag can read cross-registry settlements.',
  },
}

export const ALL_PANE_IDS = Object.keys(PANES) as PaneId[]

export function isKnownPane(id: string): id is PaneId {
  return Object.prototype.hasOwnProperty.call(PANES, id)
}

export interface DeskLayout {
  id: string
  name: string
  panes: PaneId[]
  /**
   * §COCKPITTILES T1 — the user's own height for a pane, in ROW UNITS.
   *
   * ⚠ Deliberately a SIDECAR MAP rather than turning `panes` into objects. Every layout
   * already on disk holds plain strings; changing the array's shape would mean a reader
   * that accepts two shapes forever (and a migration nobody can roll back). A map that is
   * simply absent on every existing layout costs nothing, needs no migration, and an
   * unknown id in it is ignored by `rowsFor`.
   */
  sizes?: Record<string, number>
  /** Starter layouts are read-only constants; a saved layout is the user's own. */
  builtin?: boolean
}

/** How many row units a tile may be. A ceiling exists so one pane cannot own the board. */
export const MIN_ROWS = 1
export const MAX_ROWS = 4

/**
 * §COCKPITTILES T1 — each pane's NATURAL height, in row units.
 *
 * Before this, the grid had no row unit at all (`auto-fill` columns, `align-items:start`,
 * no `grid-auto-rows`), so every tile was content-height between PaneShell's 180px floor
 * and its 30rem ceiling. That is why his board showed DECISIONS as one sentence in a huge
 * box beside DENIALS clipped mid-sentence: the two ends of one missing constraint.
 * Heights are multiples of one unit now — which is what "more standardized" means — and a
 * dense pane scrolls inside its own body instead of dragging its row.
 */
export const NATURAL_ROWS: Record<PaneId, number> = {
  // Dense lists and boards: they always have more to show than fits.
  book: 4, denials: 3, receipts: 3, agentlogs: 3, heartbeat: 3, channels: 3, ledger: 3,
  agentops: 3, chats: 3,
  // Two units: a handful of rows plus a lede.
  decisions: 2, earnings: 2, failures: 2, work: 2, agents: 2, market: 2, holdings: 2,
  quickactions: 2,
  stop: 2, latency: 2, telemetry: 2, instructions: 2,
  // One unit: a headline and a sentence. A void the size of a laptop screen was the bug.
  conservation: 1, money: 1, fleet: 1, bookmini: 1,
  // §COCKPITDESK (2026-10-15): a short list with a head and a door; the release channel is four lines.
  webhooks: 2, senate: 2, forex: 2, orgs: 2, guildboard: 2, settlements: 2, release: 1,
}

/** The height actually used: the user's override for this layout, else the natural size. */
export function rowsFor(id: PaneId, layout?: DeskLayout | null): number {
  const raw = layout?.sizes?.[id]
  const n = typeof raw === 'number' && Number.isFinite(raw) ? Math.round(raw) : NATURAL_ROWS[id]
  return Math.min(MAX_ROWS, Math.max(MIN_ROWS, n || 1))
}

/**
 * The four starter layouts. Client constants, never persisted until the user
 * saves one — an unsaved default must not become a row that then has to be
 * migrated forever.
 */
// ⚠ STOP RIDES WITH DECISIONS. Every starter that can ask you to approve something can
// also let you withdraw the authority behind it, in the same view — the moment you want
// to stop is the worst moment to be navigating to find out where stopping lives.
export const STARTER_LAYOUTS: DeskLayout[] = [
  // §COCKPITCHATS — `chats` joins Triage because an unanswered conversation is the same
  // KIND of thing as an unanswered decision: something waiting on a human.
  { id: 'triage',   name: 'Triage',   builtin: true, panes: ['decisions', 'stop', 'denials', 'failures', 'work', 'chats', 'receipts', 'telemetry', 'agents'] },
  { id: 'money',    name: 'Money',    builtin: true, panes: ['money', 'earnings', 'conservation', 'decisions', 'stop'] },
  // §COCKPITSHOW — the trading board. `market` is public and `holdings` follows the acting
  // agent, so the two together answer "what is the venue doing" and "what do I hold on it"
  // without either pretending to answer the other.
  { id: 'trading',  name: 'Trading',  builtin: true, panes: ['market', 'holdings', 'money', 'ledger'] },
  // §COCKPITBOOK — the analytics board. `book` is wide and tall by design; `market` gives
  // it the public tape beside the private position, and `chats` fills the room the board
  // leaves. ⚠ `bookmini` is deliberately NOT here: it answers the SAME question as `book`
  // and polls on a different interval (120s vs 90s), so a board carrying both would show
  // two different market values for the same account at the same moment. It stays in
  // Arrange, for a board that wants the compact form INSTEAD.
  { id: 'analytics', name: 'Analytics', builtin: true, panes: ['book', 'market', 'chats', 'ledger'] },
  // §RAT — HIS ask: Incident showed registry/fleet health and nothing about the agents
  // YOU own. `agentops` sits beside `fleet` so the board answers both "is the registry
  // healthy" and "are my agents running", which are not the same question.
  { id: 'incident', name: 'Incident', builtin: true, panes: ['fleet', 'agentops', 'ledger', 'denials', 'conservation', 'latency', 'agents'] },
  // §COCKPITPOLISH — Build gains HEARTBEATS (who is running right now) and the
  // INSTRUCTIONS log beside the control that writes it. `agents` leaves this layout: it
  // is the compact form of what `heartbeat` now says in full, and two panes answering one
  // question is how they come to disagree. It stays available in Arrange and on Triage.
  { id: 'build',    name: 'Build',    builtin: true, panes: ['heartbeat', 'agentops', 'channels', 'instructions', 'ledger', 'decisions', 'stop'] },
  // §COCKPITDESK (2026-10-15) — what reaches out from this registry and whether it arrives: the endpoints it calls,
  // your agents, their logs and failures, who called in. Nothing on it asks for a decision, so no STOP.
  { id: 'operations', name: 'Operations', builtin: true, panes: ['webhooks', 'agentops', 'failures', 'agentlogs', 'heartbeat', 'fleet'] },
  // §COCKPITDESK (2026-10-15) — the network around you: votes closing, your firms, open work, the rates and the
  // venue. It carries DECISIONS, so it carries STOP.
  { id: 'network', name: 'Network', builtin: true, panes: ['senate', 'orgs', 'guildboard', 'forex', 'market', 'decisions', 'stop'] },
]
