import type { AxiosInstance } from 'axios'
import { apiClient } from './client'
import { parseStepUp, type StepUpChallenge } from '@/services/membership/membership'
import type { Evidence, SeasonDetail, SeasonListItem, SeasonSummary, Submission } from '@/services/commons/commons'

/**
 * §MEMBERSHIP phase C (2026-10-02) — the commons routes of plan § 2.5 (routers/commons.py).
 *
 *   GET  /commons/seasons, /commons/seasons/{id}      public
 *   GET  /commons/seasons/{id}/mine                   developer or agent token: the viewer's submissions and ballot
 *   POST /commons/seasons/{id}/submissions            the acting agent's token
 *   POST /commons/seasons/{id}/ballot                 the acting agent's token, members only, may answer 428
 *   POST /admin/commons/seasons[/{id}/close|strike|pay|cancel|awards/{award}/write-off]   the developer token (admin_treasury)
 *
 * Every refusal the server words ({"error", "message"}, with its own status) comes back as a value, so the page can
 * say what happened and what to do next; the statuses it expects carry no global toast. Anything else still throws.
 * Which token a call carries is the server's own map (authTiers.generated.json), never decided here.
 */

/** A worded refusal: the code word, the server's sentence, and the extra fields some refusals carry. */
export interface CommonsRefused {
  kind: 'refused'
  status: number
  error: string
  message: string
  /** unknown_submission / own_submission: the submission ids the ballot must drop */
  submissionIds: string[]
}

export type SeasonsAnswer =
  | { state: 'ok'; seasons: SeasonListItem[]; currency: string }
  | { state: 'disabled'; message: string }

export type SeasonAnswer =
  | { state: 'ok'; season: SeasonDetail }
  | { state: 'disabled'; message: string }
  | { state: 'not_found'; message: string }

export type BallotOutcome =
  | { kind: 'saved'; seasonId: number; allocations: Record<string, number>; totalPoints: number; digest: string }
  | { kind: 'step_up'; stepUp: StepUpChallenge; message: string }
  | { kind: 'not_member'; missing: string[]; nextStep: string | null; message: string }
  | { kind: 'second_factor_required'; message: string }
  | CommonsRefused

/** GET /commons/seasons/{id}/mine: the viewer is always a developer (the token's own, or the agent's developer). */
export interface MySeasonView {
  seasonId: number
  status: string
  mySubmissions: Submission[]
  myBallot: { allocations: Record<string, number>; totalPoints: number; updatedAt: string | null } | null
  isMember: boolean
}

export interface SubmittedWork { id: number; seasonId: number; kind: string; title: string; status: string; submitterDid: string }
export type SubmitOutcome = { kind: 'submitted'; submission: SubmittedWork } | CommonsRefused

export interface PaymentRow { recipient_did: string; amount: string | null; funded?: string | null; status: string; error?: string }
/** A failed award past the ledger's memory of its key: a run never sends it again, a person decides (write-off). */
export interface DecisionRow { award_id: number; recipient_did: string; amount: string | null; status: string; first_attempt_at: string | null }
export interface PayResult { season: SeasonSummary; payments: PaymentRow[]; unpaid_awards: number; needs_decision?: DecisionRow[]; decision?: string }
export type AdminOutcome<T> = { kind: 'ok'; data: T } | CommonsRefused

const WORDED = [400, 403, 404, 409, 422, 429]

function refusal(e: any): CommonsRefused | null {
  const status = e?.response?.status
  const d = e?.response?.data
  if (!status || !d || typeof d !== 'object' || typeof d.error !== 'string') return null
  const ids = Array.isArray(d.submission_ids) ? d.submission_ids.map((x: unknown) => String(x)) : []
  return { kind: 'refused', status, error: d.error, message: typeof d.message === 'string' ? d.message : '', submissionIds: ids }
}

function list<T>(x: unknown): T[] { return Array.isArray(x) ? (x as T[]) : [] }

/** A season as the page reads it: arrays always arrays, counts always numbers (an older or partial answer renders). */
export function normaliseSeason(raw: any): SeasonDetail {
  const d = (raw && typeof raw === 'object' ? raw : {}) as Record<string, any>
  return {
    ...(d as SeasonSummary),
    min_voters: Number(d.min_voters) || 0,
    ballot_points: Number(d.ballot_points) || 100,
    tally: d.tally && typeof d.tally === 'object' ? { ...d.tally, rows: list(d.tally.rows) } : null,
    submissions: list<any>(d.submissions).map((x) => ({ ...x, evidence: list(x?.evidence), mine: !!x?.mine, award: x?.award ?? null })),
    ballots_cast: Number(d.ballots_cast) || 0,
    ballots: Array.isArray(d.ballots) ? d.ballots : null,
    my_ballot: d.my_ballot && typeof d.my_ballot === 'object' ? d.my_ballot : null,
  }
}

export class CommonsApi {
  private readonly injected?: AxiosInstance
  private get client(): AxiosInstance { return this.injected ?? apiClient }

  constructor(client?: AxiosInstance) {
    this.injected = client
  }

  async seasons(limit = 20): Promise<SeasonsAnswer> {
    try {
      const { data } = await this.client.get('/commons/seasons', { params: { limit }, expectedStatuses: [403] })
      return { state: 'ok', seasons: list<SeasonListItem>(data?.seasons), currency: String(data?.currency || '') }
    } catch (e: any) {
      const r = refusal(e)
      if (r && r.error === 'commons_disabled') return { state: 'disabled', message: r.message }
      throw e
    }
  }

  async season(id: number | string): Promise<SeasonAnswer> {
    try {
      const { data } = await this.client.get(`/commons/seasons/${id}`, { expectedStatuses: [403, 404] })
      return { state: 'ok', season: normaliseSeason(data) }
    } catch (e: any) {
      const r = refusal(e)
      if (r && r.error === 'commons_disabled') return { state: 'disabled', message: r.message }
      if (r && r.error === 'season_not_found') return { state: 'not_found', message: r.message }
      throw e
    }
  }

  /**
   * The signed-in developer's own side of a season (developer or agent token; the console sends its developer token):
   * their submissions, the ballot a member would replace, and whether they are a member now. `null` when the commons
   * is off or the season does not exist (the public read already says which).
   */
  async mine(seasonId: number): Promise<MySeasonView | null> {
    try {
      const { data } = await this.client.get(`/commons/seasons/${seasonId}/mine`, { expectedStatuses: [403, 404] })
      const d = (data || {}) as Record<string, any>
      const b = d.my_ballot && typeof d.my_ballot === 'object' ? d.my_ballot : null
      return {
        seasonId: Number(d.season_id ?? seasonId),
        status: String(d.status || ''),
        mySubmissions: list<any>(d.my_submissions).map((x) => ({ ...x, evidence: list(x?.evidence), mine: true, award: x?.award ?? null })),
        myBallot: b ? { allocations: (b.allocations && typeof b.allocations === 'object') ? b.allocations : {},
          totalPoints: Number(b.total_points) || 0, updatedAt: typeof b.updated_at === 'string' ? b.updated_at : null } : null,
        isMember: !!d.is_member,
      }
    } catch (e: any) {
      const r = refusal(e)
      if (r && (r.error === 'commons_disabled' || r.error === 'season_not_found')) return null
      throw e
    }
  }

  /** Work already done, with its evidence, by the acting agent (any verified developer; not only members). */
  async submit(seasonId: number, body: { kind: string; title: string; description?: string; evidence: Evidence[] }): Promise<SubmitOutcome> {
    try {
      const { data } = await this.client.post(`/commons/seasons/${seasonId}/submissions`,
        { kind: body.kind, title: body.title, description: body.description || '', evidence: body.evidence },
        { expectedStatuses: WORDED })
      return { kind: 'submitted', submission: {
        id: Number(data?.id), seasonId: Number(data?.season_id), kind: String(data?.kind || ''), title: String(data?.title || ''),
        status: String(data?.status || ''), submitterDid: String(data?.submitter_did || ''),
      } }
    } catch (e: any) {
      const r = refusal(e)
      if (r) return r
      throw e
    }
  }

  /**
   * A member's ballot: up to 100 points over the season's submissions. Where the registry asks, the first call answers
   * 428 with a challenge; the caller has it approved and sends the SAME allocations again with `challengeId` or
   * `totpCode` (the approval is bound to these exact allocations).
   */
  async ballot(seasonId: number, allocations: Record<string, number>, extra: { totpCode?: string; challengeId?: string } = {}): Promise<BallotOutcome> {
    const body: Record<string, unknown> = { allocations }
    if (extra.totpCode) body.totp_code = extra.totpCode
    if (extra.challengeId) body.challenge_id = extra.challengeId
    try {
      const { data } = await this.client.post(`/commons/seasons/${seasonId}/ballot`, body,
        { expectedStatuses: [...WORDED, 428] })
      return {
        kind: 'saved', seasonId: Number(data?.season_id ?? seasonId),
        allocations: (data?.allocations && typeof data.allocations === 'object') ? data.allocations : allocations,
        totalPoints: Number(data?.total_points) || 0, digest: String(data?.digest || ''),
      }
    } catch (e: any) {
      const status = e?.response?.status
      const d = e?.response?.data || {}
      const message = typeof d.message === 'string' ? d.message : ''
      if (status === 428) {
        const stepUp = parseStepUp(d)
        if (stepUp) return { kind: 'step_up', stepUp, message }
      }
      if (status === 403 && d.error === 'not_a_member') {
        return { kind: 'not_member', missing: list<string>(d.missing), nextStep: typeof d.next_step === 'string' ? d.next_step : null, message }
      }
      if (status === 403 && d.error === 'second_factor_required') return { kind: 'second_factor_required', message }
      const r = refusal(e)
      if (r) return r
      throw e
    }
  }

  // ── admin_treasury ────────────────────────────────────────────────────────

  private async admin<T>(path: string, body: Record<string, unknown> = {}): Promise<AdminOutcome<T>> {
    try {
      // 503 fee_collector_unreadable: the ledger did not report the fee collector, so no budget could be set
      const { data } = await this.client.post(path, body, { expectedStatuses: [...WORDED, 503] })
      return { kind: 'ok', data: data as T }
    } catch (e: any) {
      const r = refusal(e)
      if (r) return r
      throw e
    }
  }

  /** Open a season: its budget is a share of the fee collector's balance now, plus an optional seed from the treasury. */
  open(body: { title?: string; durationDays?: number; endsAt?: string; seed?: string; feeSharePercent?: string }): Promise<AdminOutcome<SeasonSummary>> {
    const b: Record<string, unknown> = { title: body.title || '' }
    if (body.endsAt) b.ends_at = body.endsAt
    else if (body.durationDays) b.duration_days = body.durationDays
    if (body.seed && Number(body.seed) > 0) b.seed = body.seed
    if (body.feeSharePercent !== undefined && body.feeSharePercent !== '') b.fee_share_percent = body.feeSharePercent
    return this.admin<SeasonSummary>('/admin/commons/seasons', b)
  }

  async close(seasonId: number): Promise<AdminOutcome<SeasonDetail>> {
    const out = await this.admin<SeasonDetail>(`/admin/commons/seasons/${seasonId}/close`)
    return out.kind === 'ok' ? { kind: 'ok', data: normaliseSeason(out.data) } : out
  }

  strike(seasonId: number, submissionId: number, reason: string): Promise<AdminOutcome<{ id: number; status: string; struck_reason: string }>> {
    return this.admin(`/admin/commons/seasons/${seasonId}/strike`, { submission_id: submissionId, reason })
  }

  /** Pays every award a run may send: never sent, or failed inside the retry window (the same key, so a payment that
   *  did land is not paid twice). Older failures come back in `needs_decision`. */
  pay(seasonId: number): Promise<AdminOutcome<PayResult>> {
    return this.admin(`/admin/commons/seasons/${seasonId}/pay`)
  }

  /** Settle a failed award without a commons payment; the reason is kept on the award (pay it by hand if it is owed). */
  writeOff(seasonId: number, awardId: number, reason: string): Promise<AdminOutcome<{ id: number; status: string; unpaid_awards: number }>> {
    return this.admin(`/admin/commons/seasons/${seasonId}/awards/${awardId}/write-off`, { reason })
  }

  cancel(seasonId: number, reason: string): Promise<AdminOutcome<SeasonSummary>> {
    return this.admin(`/admin/commons/seasons/${seasonId}/cancel`, { reason })
  }
}

export const commonsApi = new CommonsApi()
