/**
 * §COCKPITPOLISH P2 (2026-08-31) — ONE definition of "which of my agents matter now",
 * asked by every picker on the app.
 *
 * WHY THIS FILE EXISTS. Both agent selectors — the cockpit's instruct picker and the
 * global header `AgentSwitcher` — built their default list from RECENCY OF CREATION, and
 * on registry-a that is a list of fixtures. Measured 2026-08-31 on developer 10:
 *
 *     newest 25 by created_at   →  <no name>, <no name>, forge-a-gen-1..15, api-theprotocol-cloud
 *     name says fixture         →  182 agents
 *     called us in last 15 min  →   21 agents  ← the four Ironhands, all eleven sovereigns,
 *                                                the mTLS senders, two service agents
 *
 * The second list is the one a human wants and the first is what they got. The fix is a
 * ranking, and it lives HERE rather than in each picker because two pickers with two
 * orderings agree on the day they ship and drift by Friday (§FANOUTFIX: when a widening
 * fix adds a new predicate, grep for every other site still asking the old question).
 *
 * 🔴 TWO HONESTY CONSTRAINTS THIS MODULE IS BUILT AROUND.
 *
 * 1. THERE IS NO DEDICATED HEARTBEAT SIGNAL. `POST /agents/heartbeat` does nothing but
 *    stamp `last_active_at` through the ordinary `get_current_agent` dependency — its own
 *    docstring says so — so ANY authenticated call from the agent stamps it identically.
 *    Everything here therefore means exactly "it called this registry with its own
 *    credentials", and the words rendered beside it say that and no more. Implying a
 *    liveness protocol we do not run would be inventing a rail (§HIRECOHERE's blank
 *    promise, one layer down).
 *
 * 2. RANKING IS NOT FILTERING. Sinking an agent is reversible by scrolling; hiding it is
 *    not. Nothing in this module removes a row — the fixtures sink because they are not
 *    alive, which needs no name heuristic and cannot mis-classify an agent the operator
 *    genuinely named "canary-something". Callers that CAP a list must say so and say by
 *    how much; a name you cannot see is not a name that does not exist.
 */

export type LivenessTier = 'fresh' | 'recent' | 'quiet' | 'silent' | 'never'

/** Seconds. Chosen against the measured population, not picked round: 21 agents fall
 *  inside RECENT on registry-a and 39 inside QUIET, so the bands actually separate. */
export const FRESH_S = 2 * 60
export const RECENT_S = 15 * 60
export const QUIET_S = 24 * 60 * 60

export interface RankableAgent {
  did?: string | null
  name?: string | null
  status?: string | null
  last_active_at?: string | null
  last_health?: string | null
  last_health_at?: string | null
  hasCredentials?: boolean
  hasInvalidCredentials?: boolean
  client_id?: string | null
  client_secret?: string | null
  card_data?: any
}

/** Seconds since the agent last called us, or null when it never has.
 *  ⚠ Returns null for an unparseable timestamp too — a date we cannot read is not a
 *  date of zero, and `NaN` compared against a threshold is silently false. */
export function secondsSinceCall(a: RankableAgent, nowMs = Date.now()): number | null {
  if (!a?.last_active_at) return null
  const t = new Date(a.last_active_at).getTime()
  if (!Number.isFinite(t)) return null
  return Math.max(0, Math.round((nowMs - t) / 1000))
}

export function livenessTier(a: RankableAgent, nowMs = Date.now()): LivenessTier {
  const s = secondsSinceCall(a, nowMs)
  if (s === null) return 'never'
  if (s < FRESH_S) return 'fresh'
  if (s < RECENT_S) return 'recent'
  if (s < QUIET_S) return 'quiet'
  return 'silent'
}

/** The probe half — WE called IT. Deliberately a separate axis from the above: the two
 *  directions disagreeing is the interesting case, not an inconsistency to smooth over
 *  (§COCKPITA R3). `undefined` means never probed, which is not "unhealthy". */
export function probeVerdict(a: RankableAgent): 'healthy' | 'unhealthy' | 'unreachable' | null {
  const v = (a?.last_health || '').toLowerCase()
  return v === 'healthy' || v === 'unhealthy' || v === 'unreachable' ? v : null
}

export function hasUsableCredentials(a: RankableAgent): boolean {
  if (a?.hasInvalidCredentials) return false
  return !!(a?.hasCredentials || (a?.client_id && a?.client_secret))
}

/** A name a human typed, as opposed to a DID stub or the placeholder the list renders
 *  when no card exists. Used only as a low tiebreak — never to exclude anything. */
export function hasRealName(a: RankableAgent): boolean {
  const n = String(a?.name || a?.card_data?.name || '').trim()
  if (!n) return false
  if (n.startsWith('did:')) return false
  return n.toLowerCase() !== '<no name>'
}

/**
 * Higher sorts first. The order the plan settled on, and the reason for each step:
 *
 *   6  the agent you are ACTING AS         — it is the answer to "where am I?"
 *   5  called us inside 15 minutes         — the working fleet, measured at 21 rows
 *   4  probed healthy, or called inside 24h — alive on either axis
 *   3  holds usable credentials            — you can act as it even if it is idle
 *   2  carries a human-given name
 *   1  active enforcement status
 *   0  everything else
 *
 * ⚠ `status` is an ENFORCEMENT state written by the enforcement rail and by soft-delete,
 * never by the owner (§AGENTCOCKPIT). It earns one point as a tiebreak and no more —
 * a revoked agent is still shown, because the operator asking "where did it go?" is
 * exactly the person who needs to see it.
 */
export function rankScore(
  a: RankableAgent,
  opts: { activeDid?: string | null; nowMs?: number; credentialsFirst?: boolean } = {},
): number {
  const nowMs = opts.nowMs ?? Date.now()
  if (opts.activeDid && a?.did && a.did === opts.activeDid) return 6
  // ⚠ THE TWO PICKERS ASK DIFFERENT QUESTIONS, so the rail carries both orderings rather
  // than letting either hand-roll a comparator (§FANOUTFIX). The header switcher answers
  // "which agent may I ACT AS", and that is decided by credentials — an agent whose secret
  // you do not hold cannot be switched to at all, however alive it is. The cockpit's
  // instruct picker answers "which agent may I INSTRUCT", where the card and the server
  // decide and liveness is the useful order. `credentialsFirst` selects which, and both
  // still fall through to the SAME liveness ladder below.
  if (opts.credentialsFirst && hasUsableCredentials(a)) {
    const tier = livenessTier(a, nowMs)
    return tier === 'fresh' || tier === 'recent' ? 5.5 : 5.25
  }
  const tier = livenessTier(a, nowMs)
  if (tier === 'fresh' || tier === 'recent') return 5
  if (probeVerdict(a) === 'healthy' || tier === 'quiet') return 4
  if (hasUsableCredentials(a)) return 3
  if (hasRealName(a)) return 2
  if ((a?.status || '') === 'active') return 1
  return 0
}

/** Stable sort, newest-call first inside a tier so the top of the list keeps moving with
 *  the fleet rather than freezing on whichever live agent happens to sort first. */
export function rankAgents<T extends RankableAgent>(
  list: T[],
  opts: { activeDid?: string | null; nowMs?: number; credentialsFirst?: boolean } = {},
): T[] {
  const nowMs = opts.nowMs ?? Date.now()
  return [...(list || [])].sort((a, b) => {
    const d = rankScore(b, { ...opts, nowMs }) - rankScore(a, { ...opts, nowMs })
    if (d !== 0) return d
    const sa = secondsSinceCall(a, nowMs)
    const sb = secondsSinceCall(b, nowMs)
    if (sa === null && sb === null) return 0
    if (sa === null) return 1
    if (sb === null) return -1
    return sa - sb
  })
}

/** How many of the ranked rows are actually alive — the number a pane prints so the
 *  human can tell "nothing is running" from "I am only showing you eight rows". */
export function countLive(list: RankableAgent[], nowMs = Date.now()): number {
  return (list || []).filter(a => {
    const tier = livenessTier(a, nowMs)
    return tier === 'fresh' || tier === 'recent'
  }).length
}

/** The default query BOTH pickers issue. One object so the two cannot drift apart. */
export const LIVE_LIST_PARAMS = { sort: 'live' as const, limit: 25, topLevelOnly: true }
