// §REPBOND (2026-09-05) — the reputation bond: the registry holds a provider's bond in escrow.
// ONE client for the four rails the app uses; the rule lives in services/reputation_bond.py.
import { apiClient } from './client'

export interface BondMaturity {
  min_transactions: number; min_age_days: number
  /** §BONDFILL-3 — the relative trust gate replaced the retired absolute trust threshold. */
  min_trust_percentile: number; min_rated_peers: number; min_ranked_population: number
  /** The share unlocked at maturity (0-80: matured never means unbonded). */
  releases_percent: number
}
export interface BondConfig {
  mode: 'off' | 'shadow' | 'enforce'
  amount: string
  currency: string
  treasury_backstop: boolean
  release_cooldown_days: number
  maturity: BondMaturity
  extension_uri: string
  sites: string[]
  registry: string
}
export interface BondProgress {
  transactions: number; transactions_required: number
  age_days: number; age_days_required: number
  /** §BONDFILL-3 — EVIDENCE: distinct counterparties, owned by other developers, who rated it. */
  rated_peers: number | null; rated_peers_required: number
  /** STANDING: share of the frame's ranked agents at or below this one (cume_dist, 0-100). */
  trust_percentile: number | null; trust_percentile_required: number
  /** `waived` = too few agents ranked for a percentile to mean anything (measured, and said so);
   *  `unknown` = not measured at all (a v1 snapshot), which never passes. Different states. */
  trust_percentile_state: 'measured' | 'waived' | 'unknown' | string
  trust_population: number | null; trust_population_required: number
  /** Information only — nothing gates on the absolute value any more. */
  eigentrust: number
  met: { transactions: boolean; age: boolean; trust: boolean }
  matured: boolean
  percent: number
  /** §BONDFILL — the unmet gates, furthest-behind first. Named by the rule that owns the
   *  arithmetic so no surface has to re-derive which condition is actually holding the bond
   *  back; `percent` alone is one number over three unrelated conditions and cannot say.
   *  Additive: a mirror running an older origin build sends a progress object without it. */
  blocking?: Array<'transactions' | 'age' | 'eigentrust' | string>
  /** Who computed this. `registry` = this frame's own live ledger. `card` = resolved from the
   *  origin's attested snapshot on the signed card, with the AGE recomputed here from
   *  `locked_at` so the segment a reader can verify itself is never stale. */
  source?: 'registry' | 'card' | string
  /** When the origin's counters were true. Null on a locally computed block, which is now. */
  as_of?: string | null
}
export interface BondInfo {
  status: 'none' | 'pending' | 'locked' | 'matured' | 'released' | 'forfeited' | 'voided' | string
  is_bonded: boolean
  amount: string | null
  currency: string | null
  required_amount?: string | null
  locked_at: string | null
  matured_at: string | null
  released_at?: string | null
  funded_by: 'self' | 'wallet' | 'treasury' | null
  funder_did?: string | null
  /** §BONDFILL-3 — `amount` is what is HELD; the original is held + what came back. */
  original_amount?: string | null
  partial_released_amount?: string | null
  partial_released_at?: string | null
  /** What the bar draws, decided once in the backend so every surface agrees:
   *  burning = matured and all of it still at stake (a costly signal: it could come back and has
   *  not) · embers = the maturity share was unlocked · extinguished = released, the exit. */
  fire?: 'burning' | 'embers' | 'extinguished' | null
  /** Whether the maturity unlock can be pressed now, and the one reason if not. Null on mirrors. */
  unlock?: UnlockBlock | null
  progress: BondProgress | null
  /** §DISCMIX adds 'index' for a row that came only through the federated directory. */
  source: 'registry' | 'card' | 'index' | string
  registry?: string | null
}
export interface UnlockBlock {
  percent: number
  amount: string | null
  keeps: string | null
  available: boolean
  reason: 'not_matured' | 'already_unlocked' | 'frame_releases_nothing' | 'treasury_backstop' | 'cooldown' | null | string
  after: string | null
}
export interface ReputationBlock {
  agent_did?: string
  bond: BondInfo
  is_bonded: boolean
  volume: string | null
  transactions: number | null
  eigentrust: number | null
  staked?: string | null
  mode?: string
  treasury_backstop?: boolean
  config?: BondConfig
  source?: string
}

const enc = (s: string) => encodeURIComponent(s)

export const reputationBondApi = {
  getConfig: () => apiClient.get('/reputation-bond/config').then(r => r.data as BondConfig),
  getAgentReputation: (did: string) =>
    apiClient.get(`/agents/${enc(did)}/reputation`).then(r => r.data as ReputationBlock),
  myAgentBond: (did: string) =>
    apiClient.get(`/developers/me/agents/${enc(did)}/reputation-bond`).then(r => r.data as ReputationBlock),
  /** Fund the bond from an agent the developer owns; funder === did means "from its own balance". */
  bondFromWallet: (did: string, funderDid: string, amount?: string) =>
    apiClient.post(`/developers/me/agents/${enc(did)}/reputation-bond`, { funder_did: funderDid, amount: amount || null })
      .then(r => r.data as { bond_id: string; status: string; amount: string; funded_by: string; reputation: ReputationBlock }),
  /** §BONDFILL-3 — at maturity, take the declared share back and STAY bonded. `release` is the exit. */
  unlock: (did: string) =>
    apiClient.post(`/developers/me/agents/${enc(did)}/reputation-bond/unlock`)
      .then(r => r.data as { bond_id: string; status: string; unlocked: string; still_held: string; currency: string;
                             unlocked_at: string | null; paid_to: string; fire: string | null; reputation: ReputationBlock }),
  /** The DEMONSTRATION path: the treasury underwrites the bond (only while the registry allows it). */
  bondBackstop: (did: string) =>
    apiClient.post(`/developers/me/agents/${enc(did)}/reputation-bond/backstop`)
      .then(r => r.data as { bond_id: string; status: string; amount: string; funded_by: string; note: string; reputation: ReputationBlock }),
}

/** §REPBOND (agentvault2-56, 2026-10-23; his words: "people cant get stuck on bond issues while discoverying/learning the
 *  protocol", "i just want it to be smooth for new people"). Where the registry enforces the bond, discovery shows an agent
 *  only while its bond is locked or matured (services/reputation_bond.sql_card_is_bonded, every card, not only paid ones),
 *  so an owner told "listed" alone was told less than the truth. */
export function hiddenUntilBonded(block: { mode?: string | null; bond?: { status?: string | null } | null } | null | undefined): boolean {
  return block?.mode === 'enforce' && !['locked', 'matured'].includes(block?.bond?.status || 'none')
}

export function bondStatusKey(status: string | null | undefined): string {
  return status || 'none'
}
