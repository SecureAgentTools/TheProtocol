/**
 * services/bridge/attention.ts — §BRIDGE R14.3, the derivation half.
 *
 * 🔴 WHY THIS IS A SEPARATE, PURE MODULE AND NOT A COMPUTED IN THE COMPONENT.
 *
 * The first version derived these lists inline with `(contracts.value || []).filter(...)`.
 * `contractsV2Api.mine()` returns `{ items: ContractV2[] }`, NOT an array, so the
 * `|| []` guard — which only defends against null, never against the wrong TYPE —
 * passed the envelope straight through and `.filter` threw inside a computed.
 *
 * A computed that throws is caught by the app's error boundary, and the boundary
 * blanks the WHOLE VIEW. Measured on the live canary: Mission Control unmounted
 * ~15-25s after load, `bridge-root` gone, `__bridge` undefined, no 4xx, no
 * pageerror — the stage, the ledger and every rail destroyed by a bad read in a
 * side panel. A control experiment on the `:pre-r14` image survived the same
 * flow for 40s, which is how this was attributed rather than guessed at.
 *
 * So the shape handling lives here, where it is pure, unit-tested, mutation-
 * verified, and structurally incapable of taking the bridge down: every entry
 * point coerces, nothing assumes, and an unrecognised shape yields an empty
 * result instead of an exception.
 */

export interface AttentionMilestone { contractId: string; title: string; seq: number; amount: string; currency: string; contractTitle: string }
export interface AttentionOffer { id: string; title: string; amount: string; currency: string }

/**
 * Accept anything the contracts rail might hand back and return a real array.
 * Known shapes: `{items: [...]}` (what `/contracts/v2/mine` returns), a bare
 * array, or nothing. Anything else is not guessed at — it is treated as empty.
 */
export function coerceContracts(input: any): any[] {
  if (Array.isArray(input)) return input
  if (input && Array.isArray(input.items)) return input.items
  if (input && Array.isArray(input.contracts)) return input.contracts
  return []
}

/** Contracts OFFERED to this agent and not yet answered. */
export function offersAwaiting(input: any, actingDid: string | null): AttentionOffer[] {
  if (!actingDid) return []
  return coerceContracts(input)
    .filter(c => c && c.status === 'offered' && c.provider_did === actingDid)
    .map(c => ({ id: String(c.id), title: String(c.title ?? ''), amount: String(c.total_amount ?? ''), currency: String(c.currency ?? '') }))
}

/**
 * Work SUBMITTED to this agent as the client, awaiting release or rejection.
 * The sharpest row on the panel: money is parked in escrow while this sits.
 */
export function milestonesAwaiting(input: any, actingDid: string | null): AttentionMilestone[] {
  if (!actingDid) return []
  const out: AttentionMilestone[] = []
  for (const c of coerceContracts(input)) {
    if (!c || c.client_did !== actingDid) continue
    const ms = Array.isArray(c.milestones) ? c.milestones : []
    for (const m of ms) {
      if (m && m.status === 'submitted') {
        out.push({
          contractId: String(c.id), contractTitle: String(c.title ?? ''),
          title: String(m.title ?? ''), seq: Number(m.seq),
          amount: String(m.amount ?? ''), currency: String(c.currency ?? ''),
        })
      }
    }
  }
  return out
}

/** Open disputes, from whatever the disputes rail returned. */
export function openDisputeCount(input: any): number {
  const arr = Array.isArray(input) ? input : []
  return arr.filter(d => d && (d.status === 'open' || d.status === 'investigating')).length
}


/* ═══════════════════════════════════════════════════════════════════════════
 * §BRIDGE R15.1 — GROWING "NEEDS YOU" INTO A REAL COMMAND QUEUE.
 *
 * Same discipline as everything above: pure, total, and defensive. These run
 * inside computeds on the bridge, and R14 established what a throw costs here —
 * the error boundary blanks the stage, the ledger and every rail. So every
 * entry point coerces, nothing assumes a shape, and an unrecognised input
 * yields an empty result rather than an exception.
 *
 * `nowMs` is a PARAMETER, never `Date.now()` inside. A deadline feature whose
 * clock cannot be moved can only be tested by waiting.
 * ═══════════════════════════════════════════════════════════════════════════ */

const arr = (x: any): any[] => (Array.isArray(x) ? x : (x && Array.isArray(x.items) ? x.items : []))
const str = (x: any): string => (x === null || x === undefined ? '' : String(x))
const ms = (x: any): number | null => {
  if (!x) return null
  const t = Date.parse(String(x))
  return Number.isFinite(t) ? t : null
}

export interface AttentionVote { id: string; title: string; closesInMs: number | null }

/**
 * Open proposals this agent has NOT voted on.
 *
 * The bridge already fetches proposals for its senate strip, but it never
 * compares them against your own votes — so it can show you a live proposal
 * and still not tell you that the decision is yours and the clock is running.
 * Anything already decided, already voted, or already closed is not attention.
 */
export function votesAwaiting(proposals: any, myVotes: any, nowMs: number): AttentionVote[] {
  const voted = new Set<string>()
  for (const v of arr(myVotes && (myVotes as any).votes ? (myVotes as any).votes : myVotes)) {
    const id = str(v?.proposalId ?? v?.proposal_id ?? v?.proposal?.id)
    if (id) voted.add(id)
  }
  const out: AttentionVote[] = []
  for (const p of arr(proposals)) {
    if (!p) continue
    const status = str(p.status).toLowerCase()
    if (status !== 'active' && status !== 'voting') continue
    const id = str(p.id)
    if (!id || voted.has(id)) continue
    const end = ms(p.votingEnd ?? p.endTime ?? p.voting_end)
    // A closed vote is history, not a request.
    if (end !== null && end <= nowMs) continue
    out.push({ id, title: str(p.title), closesInMs: end === null ? null : end - nowMs })
  }
  return out
}

export interface GuildAwaiting {
  bidsToAward: Array<{ id: string; title: string; bids: number }>
  awardedToYou: Array<{ id: string; title: string; bounty: string; currency: string }>
  toVerify: Array<{ id: string; title: string; bounty: string; currency: string }>
}

/**
 * The three guild states that are blocked on a human, from ONE `guild/mine`
 * call the WORK modal already makes:
 *   · you posted work and bids are in       -> you must award
 *   · work was awarded to you               -> you must deliver
 *   · a worker submitted                    -> you must verify (and money moves)
 * Everything else about an order is status, not a request.
 */
export function guildAwaiting(mine: any, actingDid: string | null): GuildAwaiting {
  const empty: GuildAwaiting = { bidsToAward: [], awardedToYou: [], toVerify: [] }
  if (!actingDid) return empty
  const orders = arr(mine && (mine as any).orders ? (mine as any).orders : mine)
  const out: GuildAwaiting = { bidsToAward: [], awardedToYou: [], toVerify: [] }
  for (const o of orders) {
    if (!o) continue
    const st = str(o.status).toLowerCase()
    const poster = str(o.poster_did), worker = str(o.worker_did)
    const base = { id: str(o.id), title: str(o.title), bounty: str(o.bounty), currency: str(o.currency) }
    if (poster === actingDid && st === 'open' && Number(o.bid_count || 0) > 0) {
      out.bidsToAward.push({ id: base.id, title: base.title, bids: Number(o.bid_count) })
    } else if (worker === actingDid && (st === 'awarded' || st === 'in_progress')) {
      out.awardedToYou.push(base)
    } else if (poster === actingDid && (st === 'submitted' || st === 'delivered')) {
      out.toVerify.push(base)
    }
  }
  return out
}

/**
 * Offers YOU sent that are about to lapse. Not a request from someone else —
 * a thing that quietly stops being true if you ignore it, which is exactly the
 * class of item a command queue exists to surface.
 */
export function offersExpiring(contracts: any, actingDid: string | null, nowMs: number, withinMs = 48 * 3600_000):
  Array<{ id: string; title: string; expiresInMs: number }> {
  if (!actingDid) return []
  const out: Array<{ id: string; title: string; expiresInMs: number }> = []
  for (const c of coerceContracts(contracts)) {
    if (!c || c.status !== 'offered' || c.client_did !== actingDid) continue
    const exp = ms(c.offer_expires_at)
    if (exp === null) continue
    const left = exp - nowMs
    if (left > 0 && left <= withinMs) out.push({ id: str(c.id), title: str(c.title), expiresInMs: left })
  }
  return out
}

/** Claimable staking rewards, as a number. Balances arrive in scientific
 *  notation on this network ("1E+3"), so parseFloat, never parseInt. */
export function claimableRewards(stats: any): number {
  const v = parseFloat(str(stats?.availableRewards ?? stats?.available_rewards ?? ''))
  return Number.isFinite(v) && v > 0 ? v : 0
}

/** Attestations lapsing inside the window. An expired attestation is not a
 *  request either — by then the decision has been made for you. */
export function attestationsExpiring(records: any, nowMs: number, withinMs = 14 * 24 * 3600_000):
  Array<{ id: string; expiresInMs: number }> {
  const out: Array<{ id: string; expiresInMs: number }> = []
  for (const a of arr(records && (records as any).attestations ? (records as any).attestations : records)) {
    if (!a) continue
    const exp = ms(a.expires_at ?? a.valid_until)
    if (exp === null) continue
    const left = exp - nowMs
    if (left > 0 && left <= withinMs) out.push({ id: str(a.id ?? a.attestation_id), expiresInMs: left })
  }
  return out
}

/** Human "2d 4h" / "3h" / "12m". Returns '' when there is no deadline to state. */
export function humanLeft(msLeft: number | null | undefined): string {
  if (msLeft === null || msLeft === undefined || !Number.isFinite(msLeft) || msLeft <= 0) return ''
  const m = Math.floor(msLeft / 60000)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  return `${Math.floor(h / 24)}d ${h % 24}h`
}


/* ═══════════════════════════════════════════════════════════════════════════
 * §BRIDGE R15.4 — ATTENTION ACROSS THE REGISTRIES YOU CAN ACT ON.
 *
 * "your agents" is not a single-registry fact. The queue above reads THIS
 * origin only, so work waiting on another registry is invisible from a deck
 * whose whole job is telling you what is waiting.
 *
 * WHERE THE REGISTRY LIST COMES FROM, AND WHY NOT THE DIRECTORY.
 * `/admin/command/registry-directory` is admin-gated, so it cannot drive a
 * feature every developer should have. The imported agent CREDENTIALS already
 * carry `registry_url` — and that is also the only correct source: R11 #12
 * measured that the four renamed peers answer on their ORIGINAL host, so a URL
 * built from a registry's display name points at nothing. Read the address the
 * credential was issued with; never construct one.
 *
 * It also scopes itself honestly: these are exactly the registries you hold an
 * agent on, which is exactly where something can be waiting on you.
 * ═══════════════════════════════════════════════════════════════════════════ */

export interface ForeignGroup { origin: string; host: string; agents: any[] }

/**
 * Group stored credentials by foreign origin. Same-origin agents are NOT
 * foreign and must never be re-fetched over the network — the local queue
 * already covers them.
 */
export function foreignRegistryGroups(all: any, currentOrigin: string, cap = 6): ForeignGroup[] {
  const byOrigin = new Map<string, any[]>()
  const creds = all && typeof all === 'object' ? Object.values(all) : []
  for (const c of creds as any[]) {
    if (!c || !c.client_id || !c.client_secret) continue      // cannot mint: not reachable
    const raw = str(c.registry_url)
    if (!raw) continue
    let origin = ''
    try { origin = new URL(raw).origin } catch { continue }   // never guess at a malformed URL
    if (!origin || origin === currentOrigin) continue
    if (!byOrigin.has(origin)) byOrigin.set(origin, [])
    byOrigin.get(origin)!.push(c)
  }
  const out: ForeignGroup[] = []
  for (const [origin, agents] of byOrigin) {
    let host = origin
    try { host = new URL(origin).host } catch { /* keep the origin */ }
    out.push({ origin, host, agents })
  }
  // Bounded on purpose: this fans out real requests, and a fleet of fifteen
  // registries must not turn opening a panel into fifteen round trips.
  return out.sort((a, b) => a.host.localeCompare(b.host)).slice(0, cap)
}

/** Total "needs you" on one foreign registry, from the SAME derivations the
 *  local queue uses — so the two can never drift apart. */
export function foreignNeedsCount(contracts: any, guildMine: any, did: string | null): number {
  const g = guildAwaiting(guildMine, did)
  return offersAwaiting(contracts, did).length
    + milestonesAwaiting(contracts, did).length
    + g.bidsToAward.length + g.awardedToYou.length + g.toVerify.length
}
