/**
 * services/commons/commons.ts — §MEMBERSHIP phase C (2026-10-02): the commons as the console reads it.
 *
 * The commons (routers/commons.py, services/commons.py): a share of this registry's fee income becomes a SEASON's
 * budget; anyone with a verified developer account SUBMITS work already done, with evidence; MEMBERS spread up to 100
 * points over the submissions in one BALLOT (never their own developer's work, replaceable until the close); at the
 * close each submission gets the MEDIAN of its non-zero points (only where enough members gave any), the budget is
 * shared by those medians with a cap per developer, and the AWARDS are paid through the reward funding waterfall.
 *
 * Pure: types, the season's phase, the ballot's arithmetic and the refusal codes. The words people read are members,
 * season, ballot, points, budget, award; never a share of anything, a yield or a return.
 */

export type SeasonStatus = 'open' | 'closed' | 'paid' | 'cancelled'

export interface SeasonSummary {
  id: number
  title: string
  status: SeasonStatus
  currency: string
  opens_at: string | null
  ends_at: string | null
  /** decimal strings, as the server writes them (never floats) */
  budget: string | null
  seed: string | null
  fee_share_percent: string | null
  fee_collector_balance_at_open: string | null
  recipient_cap_percent: string | null
  min_voters: number
  ballot_points: number
  closed_at: string | null
  paid_at: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  /** the rules snapshotted when the season opened (max_submissions_per_developer, membership, ...) */
  rules?: Record<string, unknown>
}

/** A row of GET /commons/seasons: the summary plus three counts. */
export interface SeasonListItem extends SeasonSummary {
  paid_total: string | null
  submissions: number
  ballots: number
}

export interface Evidence { type: string; ref: string; url?: string | null }

export interface Award {
  /** the award's own id (the write-off names it); absent on registries whose detail does not carry it yet */
  id?: number
  median_points: string | null
  voters: number
  share: string | null
  amount: string | null
  /** pending until paid; partial when the waterfall paid less than the award; failed when the payment raised;
   *  written_off when an admin settled a failed award without a commons payment */
  status: 'pending' | 'paid' | 'partial' | 'failed' | 'written_off' | string
  funded_amount: string | null
  shortfall: string | null
  paid_at: string | null
  /** set when a payment run first sent it: a pending award WITH this clock is a payment whose answer was lost */
  attempted_at?: string | null
  written_off_at?: string | null
  written_off_reason?: string | null
}

/** A payment that failed, or was sent and never answered: a run may send it again, or an admin writes it off. */
export function awaitsDecision(a: Award | null | undefined): boolean {
  return !!a && (a.status === 'failed' || (a.status === 'pending' && !!a.attempted_at))
}

/** Once any award of the season was sent (or settled), its tally is fixed: no strike, no cancel (the server refuses). */
/** §MEMBERSHIP (V0565; agentvault2-09's finding on season 3): the name a submission is shown by. Agent card names are not
 *  unique (the DID is the only address), so three members whose agents share a card name read as ONE recipient taking
 *  60 % under a 20 % cap. A name stands alone where no OTHER submitter of the season shares it (one member's several
 *  submissions are one submitter); where another does, the DID's tail follows it; without a name, the DID. */
export function submitterLabel(s: Pick<Submission, 'submitter_did' | 'submitter_name'>,
                               all: ReadonlyArray<Pick<Submission, 'submitter_did' | 'submitter_name'>>): string {
  const name = (s.submitter_name || '').trim()
  if (!name) return s.submitter_did
  const key = name.toLowerCase()
  const namesakes = [...new Set(all.filter(x => (x.submitter_name || '').trim().toLowerCase() === key).map(x => x.submitter_did))]
  if (namesakes.length < 2) return name
  // the panel's short-DID tail; longer only where two namesakes' tails collide
  const tail = (d: string, n: number) => d.slice(-n)
  const n = namesakes.filter(d => tail(d, 6) === tail(s.submitter_did, 6)).length > 1 ? 12 : 6
  return `${name} · …${tail(s.submitter_did, n)}`
}

export function paymentStarted(subs: Array<{ award: Award | null }> | null | undefined): boolean {
  return (subs || []).some((s) => !!s.award && (s.award.status !== 'pending' || !!s.award.attempted_at))
}

export interface Submission {
  id: number
  kind: string
  title: string
  description: string
  evidence: Evidence[]
  submitter_did: string
  submitter_name: string
  status: 'submitted' | 'struck' | 'withdrawn' | string
  struck_reason: string | null
  created_at: string | null
  /** true only where the server knew the viewer (the public read does not) */
  mine: boolean
  award: Award | null
}

export interface TallyRow {
  submission_id: number
  voters: number
  median_points: string | null
  share: string | null
  amount: string | null
  capped: boolean
  /** why a submission got nothing: no member gave it points, or fewer members than the season's minimum */
  reason: 'no_points' | 'too_few_voters' | null
}

export interface Tally {
  ballots_cast: number
  ballots_counted: number
  awarded: string | null
  unallocated: string | null
  rows: TallyRow[]
  tallied_at: string | null
}

export interface PublishedBallot { voter_did: string; allocations: Record<string, number>; total_points: number }

export interface SeasonDetail extends SeasonSummary {
  tally: Tally | null
  submissions: Submission[]
  ballots_cast: number
  /** published once the season closes: who gave what is the transparency that makes a ring visible */
  ballots: PublishedBallot[] | null
  my_ballot: { allocations: Record<string, number>; total_points: number; updated_at: string | null } | null
}

/** What the admin controls ask the panel to do (admin_treasury; the server re-checks every one). */
export type CommonsAdminAct =
  | { kind: 'open'; body: { title?: string; durationDays?: number; endsAt?: string; seed?: string; feeSharePercent?: string } }
  | { kind: 'close' }
  | { kind: 'pay' }
  | { kind: 'cancel'; reason: string }

/** The kinds of work and of evidence the server takes (services/commons.py KINDS, EVIDENCE_TYPES). */
export const SUBMISSION_KINDS = ['guild_order', 'change', 'translation', 'operations', 'help', 'other'] as const
export const EVIDENCE_TYPES = ['guild_order', 'url', 'commit', 'ticket', 'document', 'other'] as const
export const MAX_EVIDENCE = 10
export const BALLOT_POINTS = 100

/**
 * Where a season stands for the person looking at it:
 *   open      submissions and ballots are taken
 *   ended     still `open` on the server, but its window has passed: the server refuses both, an admin closes it
 *   closed    the tally is fixed, the awards wait for payment
 *   paid      every award was paid (some may be partial; the row says)
 *   cancelled nothing was paid
 */
export type SeasonPhase = 'open' | 'ended' | 'closed' | 'paid' | 'cancelled'

export function seasonPhase(s: Pick<SeasonSummary, 'status' | 'ends_at'> | null | undefined, nowMs: number = Date.now()): SeasonPhase | null {
  if (!s) return null
  if (s.status === 'open') {
    const end = s.ends_at ? Date.parse(s.ends_at) : NaN
    return Number.isFinite(end) && nowMs > end ? 'ended' : 'open'
  }
  if (s.status === 'closed' || s.status === 'paid' || s.status === 'cancelled') return s.status
  return null
}

/** The season the page leads with: the one still running or waiting for payment, else the newest. */
export function leadSeason<T extends Pick<SeasonSummary, 'id' | 'status'>>(seasons: T[] | null | undefined): T | null {
  const list = seasons || []
  return list.find((s) => s.status === 'open') || list.find((s) => s.status === 'closed') || list[0] || null
}

/** A ballot as the server takes it: whole positive points only, keyed by submission id. */
export function cleanAllocations(alloc: Record<string | number, unknown>): Record<string, number> {
  const out: Record<string, number> = {}
  for (const [k, v] of Object.entries(alloc || {})) {
    const n = Math.floor(Number(v))
    if (Number.isFinite(n) && n > 0) out[String(k)] = n
  }
  return out
}

export function ballotTotal(alloc: Record<string | number, unknown>): number {
  return Object.values(cleanAllocations(alloc)).reduce((a, b) => a + b, 0)
}

/** Points still free in this ballot (never below zero; an over-full ballot is reported by `ballotProblem`). */
export function pointsLeft(alloc: Record<string | number, unknown>, max: number = BALLOT_POINTS): number {
  return Math.max(0, max - ballotTotal(alloc))
}

/** Why this ballot cannot be sent yet, before any server is asked (the server checks the same and more). */
export function ballotProblem(alloc: Record<string | number, unknown>, max: number = BALLOT_POINTS): 'empty' | 'over' | null {
  const total = ballotTotal(alloc)
  if (total <= 0) return 'empty'
  if (total > max) return 'over'
  return null
}

/**
 * One field of the ballot moved: clamp it to whole points from 0 to what the other fields leave, so the form can
 * never hold more than `max` in all (a typed 80 beside 30 already given becomes 70).
 */
export function setPoints(alloc: Record<string, number>, id: string | number, value: unknown, max: number = BALLOT_POINTS): Record<string, number> {
  const key = String(id)
  const others = ballotTotal(Object.fromEntries(Object.entries(alloc || {}).filter(([k]) => k !== key)))
  const n = Math.floor(Number(value))
  const v = Number.isFinite(n) ? Math.min(Math.max(0, n), Math.max(0, max - others)) : 0
  const next = { ...(alloc || {}) }
  if (v > 0) next[key] = v
  else delete next[key]
  return next
}

/** A url the server will take as evidence: https only (services/commons.py `evidence_url`). */
export function evidenceUrlOk(url: string | null | undefined): boolean {
  const u = (url || '').trim()
  return u === '' || /^https:\/\/\S+$/i.test(u)
}

/** The submit form's own checks, the same the server applies (it remains the authority). */
export function submissionProblem(form: { kind: string; title: string; evidence: Evidence[] }): string | null {
  if (!(SUBMISSION_KINDS as readonly string[]).includes(form.kind)) return 'unknown_kind'
  const t = (form.title || '').trim()
  if (t.length < 3 || t.length > 200) return 'title_length'
  const ev = (form.evidence || []).filter((e) => (e.ref || '').trim() || (e.url || '').trim())
  if (ev.length === 0) return 'evidence_required'
  if (ev.length > MAX_EVIDENCE) return 'too_much_evidence'
  for (const e of ev) {
    if (!(EVIDENCE_TYPES as readonly string[]).includes(e.type)) return 'evidence_shape'
    if (!(e.ref || '').trim()) return 'evidence_shape'
    if (!evidenceUrlOk(e.url)) return 'evidence_url'
  }
  return null
}

/** Evidence rows as the server takes them: blank rows dropped, text trimmed, an empty url left out. */
export function cleanEvidence(rows: Evidence[]): Evidence[] {
  return (rows || [])
    .filter((e) => (e.ref || '').trim() || (e.url || '').trim())
    .map((e) => {
      const url = (e.url || '').trim()
      return url ? { type: e.type, ref: e.ref.trim(), url } : { type: e.type, ref: e.ref.trim() }
    })
}

/** The refusal codes of routers/commons.py the screen names in its own words (anything else shows the server's). */
export const REFUSAL_CODES = [
  'commons_disabled', 'season_not_found', 'season_not_open', 'season_live', 'season_not_closed', 'season_settled',
  'season_partly_paid', 'ends_in_past', 'negative_seed', 'empty_budget', 'developer_not_eligible', 'agent_not_active',
  'unknown_kind', 'title_length', 'evidence_required', 'too_much_evidence', 'evidence_shape', 'evidence_url',
  'too_many_submissions', 'not_a_member', 'empty_ballot', 'ballot_shape', 'negative_points', 'too_many_points',
  'unknown_submission', 'own_submission', 'submission_not_found', 'reason_required',
  'second_factor_required', 'no_developer', 'fee_collector_unreadable', 'payment_started', 'award_not_found',
  'award_not_failed',
] as const
export type RefusalCode = typeof REFUSAL_CODES[number]

export function isKnownRefusal(code: unknown): code is RefusalCode {
  return typeof code === 'string' && (REFUSAL_CODES as readonly string[]).includes(code)
}
