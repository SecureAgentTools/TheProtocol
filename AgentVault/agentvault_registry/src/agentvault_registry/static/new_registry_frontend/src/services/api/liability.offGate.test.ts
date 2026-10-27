import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (2026-10-10, the operator batch) — where a registry runs no liability mandates (registry-config
 * `liability_mode: 'off'`), the console does not ask the routes that would refuse: each answers what the route would
 * have (its 404, which every caller already reads as "off"), and nothing is sent. Measured on the sandbox operators:
 * the Cockpit and Pocket Approvals sent 4 refused reads per visit. Account security is never gated: the challenge and
 * device-key routes work on every registry and are asked as before.
 */
const h = vi.hoisted(() => ({ cfg: {} as Record<string, unknown>, get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('@/composables/useRegistryConfig', () => ({ registryConfigWithin: async () => h.cfg }))
vi.mock('./client', () => ({ apiClient: { get: h.get, post: h.post, put: h.put } }))

import { liabilityApi, LIABILITY_OFF_DETAIL } from './liability'

describe('a registry that runs no liability mandates is not asked for them', () => {
  beforeEach(() => {
    h.get.mockReset().mockResolvedValue({ data: { receipts: [], count: 0 } })
    h.post.mockReset().mockResolvedValue({ data: {} })
    h.put.mockReset().mockResolvedValue({ data: {} })
  })

  it("off: the gated calls answer the route's own 404 and send nothing", async () => {
    h.cfg = { liability_mode: 'off' }
    const calls = [
      () => liabilityApi.receipts({ limit: 40 }), () => liabilityApi.posture(), () => liabilityApi.pendingIntents(),
      () => liabilityApi.delegatable(), () => liabilityApi.myMandates(), () => liabilityApi.getMandate('m-1'),
      () => liabilityApi.createChallenge({ mandate_id: 'm-1', action_type: 'support_reply' }),
    ]
    for (const call of calls) {
      const e: any = await call().catch((x) => x)
      expect(e?.response?.status).toBe(404)
      expect(e?.response?.data?.detail).toBe(LIABILITY_OFF_DETAIL)
    }
    expect(h.get).not.toHaveBeenCalled()
    expect(h.post).not.toHaveBeenCalled()
  })

  it('off: account security still asks (the challenges, the device keys)', async () => {
    h.cfg = { liability_mode: 'off' }
    h.get.mockResolvedValue({ data: { challenges: [], count: 0 } })
    await liabilityApi.pendingChallenges()
    await liabilityApi.webauthnSelfOptions()
    await liabilityApi.revokeDeviceKey(4)
    expect(h.get).toHaveBeenCalledWith('/liability/challenges/pending')
    expect(h.get).toHaveBeenCalledWith('/liability/webauthn/options')
    expect(h.post).toHaveBeenCalledWith('/liability/devices/4/revoke-key')
  })

  it('on, or an older registry that says nothing: asked as before', async () => {
    for (const cfg of [{ liability_mode: 'enforce' }, { liability_mode: 'shadow' }, {}]) {
      h.cfg = cfg
      h.get.mockClear()
      await liabilityApi.receipts({ limit: 40 })
      expect(h.get).toHaveBeenCalledWith('/liability/receipts', { params: { limit: 40 } })
    }
  })
})
