import { describe, it, expect, vi, beforeEach } from 'vitest'

/**
 * Quick onboarding (2026-10-09): the request agentApi.resetCredentials makes, which is what decides how the console's
 * client treats the answer.
 *
 *   - `_skipLogoutOn401`: the reset's 401 is the step-up answer (`step_up_required` plus a challenge). Without the
 *     flag the client asks the session, refreshes it and SENDS THE POST AGAIN, which mints a second challenge and
 *     spends a second attempt of the registry's 3-per-hour limit (every request counts there).
 *   - `expectedStatuses`: the dialog answers 400, 401, 403, 404, 422 and 429 in its own words; a status left out gets
 *     the client's global error toast on top of that sentence (a 429 used to get an "Error" toast beside it).
 *   - the body carries the account password and only the proofs that were given: no empty totp_code or challenge_id.
 *
 * The page's own tests mock this module wholesale, so they cannot see any of it: this file is where it is held.
 */
const h = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { post: h.post } }))
vi.mock('./peerDirect', () => ({ mintAgentTokenAt: vi.fn() }))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { storeCredentials: vi.fn() } }))

import { agentApi } from './agents'

const DID = 'did:theprotocol:0f0e0d0c-0b0a-4000-8000-000000000001'
const ANSWER = { agent_did: DID, client_id: 'agent-new', client_secret: 'tp_secret_new', previous_client_id: 'agent-old' }

beforeEach(() => { h.post.mockReset(); h.post.mockResolvedValue({ data: ANSWER }) })

describe('agentApi.resetCredentials', () => {
  it('posts to the reset rail with the password only, and returns what the registry answered', async () => {
    const a = await agentApi.resetCredentials(DID, { password: 'my-password' })
    expect(a).toEqual(ANSWER)
    const [url, body] = h.post.mock.calls[0]
    expect(url).toBe(`/onboard/agents/${encodeURIComponent(DID)}/reset-credentials`)
    expect(body).toEqual({ password: 'my-password' })
  })

  it('a second factor travels only when given: no empty totp_code or challenge_id keys', async () => {
    await agentApi.resetCredentials(DID, { password: 'pw', totp_code: '123456', challenge_id: 'lch_1' })
    expect(h.post.mock.calls[0][1]).toEqual({ password: 'pw', totp_code: '123456', challenge_id: 'lch_1' })
    await agentApi.resetCredentials(DID, { password: 'pw', totp_code: '', challenge_id: 'lch_2' })
    expect(h.post.mock.calls[1][1]).toEqual({ password: 'pw', challenge_id: 'lch_2' })
  })

  it('the request config: the step-up 401 is never refreshed and resent, and every refusal the dialog says is expected', async () => {
    await agentApi.resetCredentials(DID, { password: 'pw' })
    const cfg = h.post.mock.calls[0][2] as { _skipLogoutOn401?: boolean; expectedStatuses?: number[] }
    expect(cfg._skipLogoutOn401).toBe(true)
    expect(cfg.expectedStatuses).toEqual(expect.arrayContaining([400, 401, 403, 404, 422, 429]))
  })
})
