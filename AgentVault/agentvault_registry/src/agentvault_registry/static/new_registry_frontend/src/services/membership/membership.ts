/**
 * §MEMBERSHIP (2026-10-02) — the console's half of "membership and the commons", the staking replacement
 * (sessionlogs2026/DESIGN_2026-10-02_STAKING_REPLACEMENT.md § 12; the contract is
 * sessionlogs2026/PLAN_2026-10-02_MEMBERSHIP_COMMONS.md § 2).
 *
 * A developer is a MEMBER of a registry while one of their agents holds a reputation bond there (funded by the agent
 * or the owner's wallet, never the treasury, at least the published age old). One member, one vote, weighted by
 * tenure from 1.0 to 2.0. Binding votes may need a step-up: the server answers 428 with a challenge the member
 * approves on an enrolled phone (or with a one-time code), and the client sends the vote again with the proof.
 *
 * Pure: the mode readers, the shapes of the two membership routes and the parser of the 428 body. Every reader
 * treats an absent switch as TODAY's behaviour, so a registry without the membership image renders exactly as before.
 */
import type { RegistryConfig } from '@/composables/useRegistryConfig'

export type GovernanceWeightMode = 'lock' | 'member'
export type PresenceMode = 'off' | 'conditional' | 'required'

/** `member` only where the registry says so; anything else (absent, unknown, an older registry) is today's `lock`. */
export function governanceMode(cfg: RegistryConfig | null | undefined): GovernanceWeightMode {
  return cfg?.governance_weight_mode === 'member' ? 'member' : 'lock'
}

export function presenceMode(cfg: RegistryConfig | null | undefined): PresenceMode {
  const v = cfg?.governance_presence_mode
  return v === 'conditional' || v === 'required' ? v : 'off'
}

/** The commons pages exist only where the registry says true; absent is false. */
export function commonsEnabled(cfg: RegistryConfig | null | undefined): boolean {
  return cfg?.commons_enabled === true
}

/** What the server names as absent when a developer is not (yet) a member (services/membership.py, membership/v1). */
export type MissingReason =
  | 'bond' | 'bond_age' | 'bond_matured' | 'bond_funded_by_treasury' | 'agent_suspended'
  | 'developer_unverified' | 'developer_suspended'
  /** membership/fixes-v1 (agentvault2-33, V0551): the account's deletion is pending or done */
  | 'deletion_pending'

/** The ONE thing to do next, as a code the console translates (`next_step_text` is English for API and MCP readers
 *  and is never rendered here). Checked by the server in the order a person would act. */
export type NextStep =
  | 'none' | 'post_bond' | 'wait_until' | 'use_own_funds' | 'wait_for_maturity' | 'resolve_agent'
  | 'verify_email' | 'contact_support'
  /** membership/fixes-v1 (V0551): a developer whose deletion is pending is no member until they cancel it */
  | 'cancel_deletion'

/** GET /membership/stats (public). */
export interface MembershipStats {
  mode: GovernanceWeightMode
  members: number
  joined_30d: number
  left_30d: number
  network_points: number
  points_per_weight: number
  min_bond_age_days: number
  requires_matured_bond: boolean
  tenure_full_days: number
  max_weight: number
  presence_mode: PresenceMode
  as_of: string
}

export interface MembershipAgent {
  did: string
  name: string
  bond_status: string | null
  funded_by: string | null
  locked_at: string | null
  qualifies_at: string | null
  qualifies: boolean
  reasons: string[]
}

/** GET /membership/me (developer token). */
export interface MyMembership {
  mode: GovernanceWeightMode
  is_member: boolean
  member_since: string | null
  weight: number
  /** weight x 100, the integer the ledger stores */
  points: number
  tenure_days: number
  tenure_full_days: number
  min_bond_age_days: number
  requires_matured_bond: boolean
  presence_mode: PresenceMode
  /** at most 20 bonds since membership/v1 ed6fca4a: qualifying first, then those about to qualify (soonest first) */
  agents: MembershipAgent[]
  /** every bond the developer holds here; the verdict above reads all of them, the list shows a slice */
  agents_total: number
  /** how many of them count for membership */
  agents_qualifying: number
  /** how many `agents` lists (agents_total when nothing was cut) */
  agents_shown: number
  missing: string[]
  next_step: NextStep
  next_step_at: string | null
  /** the server's English sentence for the step; the console shows it only for a code it does not know yet */
  next_step_text: string | null
}

/** "1.37" ("1,37" in German): the weight a member's vote carries, two decimals in the reader's locale, never a bare
 *  float. The locale is the app's (services/appLocale.ts), passed in so this stays pure. */
export function weightLabel(weight: number | null | undefined, locale = 'en'): string {
  const w = typeof weight === 'number' && Number.isFinite(weight) ? weight : 0
  try {
    return new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(w)
  } catch {
    return w.toFixed(2)
  }
}

/** A vote total or a quorum in member mode, as the floor speaks it: the ledger counts points (weight x points_per_weight,
 *  100 by default), every other place on the floor names weights, so "108 points" reads "1.08", never "108.00", which a
 *  reader takes for 108 votes. A missing or non-numeric total reads 0.00. */
export function memberVoteFigure(points: string | number | null | undefined, pointsPerWeight: number | null | undefined,
                                 locale = 'en'): string {
  const p = typeof points === 'number' ? points : parseFloat(String(points ?? ''))
  const per = typeof pointsPerWeight === 'number' && pointsPerWeight > 0 ? pointsPerWeight : 100
  return weightLabel(Number.isFinite(p) ? p / per : 0, locale)
}

/** How far a member has grown toward full weight, 0..1 (weight 1.0 at the start, 2.0 after `fullDays`). */
export function tenureProgress(tenureDays: number | null | undefined, fullDays: number | null | undefined): number {
  const d = Math.max(0, Number(tenureDays) || 0)
  const f = Number(fullDays) || 0
  if (f <= 0) return 1
  return Math.min(1, d / f)
}

/** The challenge of a 428 `step_up_required` answer (plan § 2.4, the credential reset's body). */
export interface StepUpChallenge {
  reason: string
  challengeId: string
  challengeHash: string
  facts: Record<string, unknown>
  expiresAt: string | null
  ttlSeconds: number | null
  methods: string[]
  how: string | null
}

/** Read a 428 body; null when it is not a step-up answer (so the caller treats it as an ordinary refusal). */
export function parseStepUp(body: unknown): StepUpChallenge | null {
  const b = (body && typeof body === 'object' ? body : null) as Record<string, any> | null
  if (!b || b.error !== 'step_up_required') return null
  const s = (b.step_up && typeof b.step_up === 'object' ? b.step_up : null) as Record<string, any> | null
  if (!s || typeof s.challenge_id !== 'string' || !s.challenge_id) return null
  return {
    reason: typeof s.reason === 'string' ? s.reason : '',
    challengeId: s.challenge_id,
    challengeHash: typeof s.challenge_hash === 'string' ? s.challenge_hash : '',
    facts: s.facts && typeof s.facts === 'object' ? (s.facts as Record<string, unknown>) : {},
    expiresAt: typeof s.expires_at === 'string' ? s.expires_at : null,
    ttlSeconds: typeof s.ttl_seconds === 'number' ? s.ttl_seconds : null,
    methods: Array.isArray(s.methods) ? s.methods.filter((m: unknown) => typeof m === 'string') : [],
    how: typeof s.how === 'string' ? s.how : null,
  }
}

/** Seconds until the challenge expires (0 when it has, or when the server named no expiry and no ttl). */
export function secondsLeft(ch: StepUpChallenge, nowMs: number = Date.now(), issuedAtMs?: number): number {
  if (ch.expiresAt) {
    const ms = Date.parse(ch.expiresAt)
    if (Number.isFinite(ms)) return Math.max(0, Math.floor((ms - nowMs) / 1000))
  }
  if (ch.ttlSeconds != null && issuedAtMs != null) {
    return Math.max(0, Math.floor(ch.ttlSeconds - (nowMs - issuedAtMs) / 1000))
  }
  return 0
}
