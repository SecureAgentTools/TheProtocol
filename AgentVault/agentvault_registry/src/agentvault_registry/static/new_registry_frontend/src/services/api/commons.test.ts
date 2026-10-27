import { describe, it, expect, vi } from 'vitest'

vi.mock('./client', () => ({ apiClient: {} }))

import { CommonsApi } from './commons'

/**
 * §MEMBERSHIP phase C (2026-10-02, plan § 2.5) — the commons routes as the console calls them: every worded refusal comes
 * back as a value (and carries no global toast), the ballot's step-up is the vote's 428, anything else still throws.
 */
function refused(status: number, body: Record<string, unknown>) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: body } })
}
const STEP_UP = { error: 'step_up_required', message: 'Confirm this vote on your phone', step_up: {
  reason: 'commons_ballot', challenge_id: 'ch_9', challenge_hash: 'h', ttl_seconds: 120, methods: ['device'],
  facts: { kind: 'commons.ballot', season_id: 4, total_points: 60 } } }

describe('CommonsApi reads', () => {
  it('lists the seasons; a registry without the commons answers "disabled", not an error', async () => {
    const get = vi.fn().mockResolvedValueOnce({ data: { seasons: [{ id: 4, status: 'open' }], currency: 'SBXA' } })
      .mockRejectedValueOnce(refused(403, { error: 'commons_disabled', message: 'commons_disabled: ...' }))
    const api = new CommonsApi({ get } as any)
    expect(await api.seasons()).toEqual({ state: 'ok', seasons: [{ id: 4, status: 'open' }], currency: 'SBXA' })
    expect(get.mock.calls[0][1].expectedStatuses).toEqual([403])
    expect((await api.seasons()).state).toBe('disabled')
  })

  it('control: any other failure still throws (a 500 is not "the commons is off")', async () => {
    const api = new CommonsApi({ get: vi.fn().mockRejectedValue(refused(500, { detail: 'boom' })) } as any)
    await expect(api.seasons()).rejects.toThrow('HTTP 500')
  })

  it('a season comes back complete even when the server leaves fields out', async () => {
    const get = vi.fn().mockResolvedValue({ data: { id: 4, status: 'closed', submissions: [{ id: 1, title: 'x' }], tally: { awarded: '5' } } })
    const out = await new CommonsApi({ get } as any).season(4)
    expect(out.state).toBe('ok')
    if (out.state !== 'ok') return
    expect(out.season.submissions[0].evidence).toEqual([])
    expect(out.season.submissions[0].mine).toBe(false)
    expect(out.season.tally?.rows).toEqual([])
    expect(out.season.ballots).toBeNull()
    expect(out.season.ballot_points).toBe(100)
  })

  it('my side of a season: the saved ballot and my submissions; null where the commons is off', async () => {
    const get = vi.fn()
      .mockResolvedValueOnce({ data: { season_id: 4, status: 'open', is_member: true, my_submissions: [{ id: 2, title: 'mine' }],
        my_ballot: { allocations: { 1: 60 }, total_points: 60, updated_at: '2026-10-02T10:00:00Z' } } })
      .mockRejectedValueOnce(refused(403, { error: 'commons_disabled', message: '' }))
    const api = new CommonsApi({ get } as any)
    const m = await api.mine(4)
    expect(get).toHaveBeenCalledWith('/commons/seasons/4/mine', expect.anything())
    expect(m).toEqual({ seasonId: 4, status: 'open', isMember: true,
      mySubmissions: [{ id: 2, title: 'mine', evidence: [], mine: true, award: null }],
      myBallot: { allocations: { 1: 60 }, totalPoints: 60, updatedAt: '2026-10-02T10:00:00Z' } })
    expect(await api.mine(4)).toBeNull()
  })
})

describe('CommonsApi acts', () => {
  it('a submission: 201 is "submitted", a worded refusal is a value with its code', async () => {
    const post = vi.fn()
      .mockResolvedValueOnce({ data: { id: 7, season_id: 4, kind: 'change', title: 'Docs', status: 'submitted', submitter_did: 'did:a' } })
      .mockRejectedValueOnce(refused(429, { error: 'too_many_submissions', message: 'too_many_submissions: ...' }))
    const api = new CommonsApi({ post } as any)
    const body = { kind: 'change', title: 'Docs', evidence: [{ type: 'commit', ref: 'abc' }] }
    expect(await api.submit(4, body)).toEqual({ kind: 'submitted', submission: { id: 7, seasonId: 4, kind: 'change', title: 'Docs', status: 'submitted', submitterDid: 'did:a' } })
    expect(post.mock.calls[0][0]).toBe('/commons/seasons/4/submissions')
    expect(post.mock.calls[0][1]).toEqual({ kind: 'change', title: 'Docs', description: '', evidence: [{ type: 'commit', ref: 'abc' }] })
    expect(post.mock.calls[0][2].expectedStatuses).toContain(429)
    const r = await api.submit(4, body)
    expect(r).toMatchObject({ kind: 'refused', status: 429, error: 'too_many_submissions' })
  })

  it('a ballot: saved; a 428 is the step-up; the proof goes out with the SAME allocations', async () => {
    const post = vi.fn()
      .mockRejectedValueOnce(refused(428, STEP_UP))
      .mockResolvedValueOnce({ data: { season_id: 4, allocations: { 1: 60 }, total_points: 60, digest: 'd1' } })
    const api = new CommonsApi({ post } as any)
    const first = await api.ballot(4, { 1: 60 })
    expect(first.kind).toBe('step_up')
    if (first.kind === 'step_up') expect(first.stepUp.challengeId).toBe('ch_9')
    const second = await api.ballot(4, { 1: 60 }, { challengeId: 'ch_9' })
    expect(second).toEqual({ kind: 'saved', seasonId: 4, allocations: { 1: 60 }, totalPoints: 60, digest: 'd1' })
    expect(post.mock.calls[1][1]).toEqual({ allocations: { 1: 60 }, challenge_id: 'ch_9' })
    expect(post.mock.calls[0][2].expectedStatuses).toContain(428)
  })

  it('a ballot\'s member refusals are their own outcomes; own_submission names the ids to drop', async () => {
    const post = vi.fn()
      .mockRejectedValueOnce(refused(403, { error: 'not_a_member', message: 'm', missing: ['bond'], next_step: 'post_bond' }))
      .mockRejectedValueOnce(refused(403, { error: 'second_factor_required', message: 's' }))
      .mockRejectedValueOnce(refused(422, { error: 'own_submission', message: 'o', submission_ids: ['2'] }))
    const api = new CommonsApi({ post } as any)
    expect(await api.ballot(4, { 2: 10 })).toEqual({ kind: 'not_member', missing: ['bond'], nextStep: 'post_bond', message: 'm' })
    expect(await api.ballot(4, { 2: 10 })).toEqual({ kind: 'second_factor_required', message: 's' })
    expect(await api.ballot(4, { 2: 10 })).toEqual({ kind: 'refused', status: 422, error: 'own_submission', message: 'o', submissionIds: ['2'] })
  })

  it('control: a 428 that is not a step-up body, and a 500, still throw', async () => {
    const post = vi.fn().mockRejectedValueOnce(refused(428, { detail: 'precondition' })).mockRejectedValueOnce(refused(500, {}))
    const api = new CommonsApi({ post } as any)
    await expect(api.ballot(4, { 1: 1 })).rejects.toThrow('HTTP 428')
    await expect(api.ballot(4, { 1: 1 })).rejects.toThrow('HTTP 500')
  })
})

describe('CommonsApi admin', () => {
  it('open sends the window, a positive seed and an explicit fee part only', async () => {
    const post = vi.fn().mockResolvedValue({ data: { id: 5, status: 'open' } })
    const api = new CommonsApi({ post } as any)
    await api.open({ title: 'Autumn', durationDays: 14, seed: '0', feeSharePercent: '' })
    expect(post).toHaveBeenLastCalledWith('/admin/commons/seasons', { title: 'Autumn', duration_days: 14 }, expect.anything())
    await api.open({ durationDays: 30, seed: '250', feeSharePercent: '40' })
    expect(post).toHaveBeenLastCalledWith('/admin/commons/seasons', { title: '', duration_days: 30, seed: '250', fee_share_percent: '40' }, expect.anything())
  })

  it('an unreadable fee collector (503) is a worded refusal, not a crash', async () => {
    const post = vi.fn().mockRejectedValue(refused(503, { error: 'fee_collector_unreadable', message: 'fee_collector_unreadable: retry' }))
    const out = await new CommonsApi({ post } as any).open({ durationDays: 30 })
    expect(out).toMatchObject({ kind: 'refused', status: 503, error: 'fee_collector_unreadable' })
  })

  it('close, strike, pay and cancel name the season and carry what each needs', async () => {
    const post = vi.fn().mockResolvedValue({ data: { id: 5, status: 'closed', submissions: [] } })
    const api = new CommonsApi({ post } as any)
    const closed = await api.close(5)
    expect(closed.kind === 'ok' && closed.data.submissions).toEqual([])
    await api.strike(5, 9, 'the commit does not exist')
    expect(post).toHaveBeenLastCalledWith('/admin/commons/seasons/5/strike', { submission_id: 9, reason: 'the commit does not exist' }, expect.anything())
    await api.pay(5)
    expect(post).toHaveBeenLastCalledWith('/admin/commons/seasons/5/pay', {}, expect.anything())
    await api.cancel(5, 'opened by mistake')
    expect(post).toHaveBeenLastCalledWith('/admin/commons/seasons/5/cancel', { reason: 'opened by mistake' }, expect.anything())
    await api.writeOff(5, 12, 'paid by hand on the treasury rail')
    expect(post).toHaveBeenLastCalledWith('/admin/commons/seasons/5/awards/12/write-off', { reason: 'paid by hand on the treasury rail' }, expect.anything())
  })
})
