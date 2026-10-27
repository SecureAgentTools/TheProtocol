import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (2026-10-10, the operator batch) — where a registry does not run the contract template library
 * (registry-config `contract_templates_enabled: false`, the sandbox operators), a template call is not sent: it answers
 * what the route would (its 503, which the library tab reads as "disabled here"). Measured: Contracts and the desk each
 * sent a refused read per visit on both operators. The contracts themselves are not gated (operators run them).
 */
const h = vi.hoisted(() => ({ cfg: {} as Record<string, unknown>, get: vi.fn(), post: vi.fn() }))
vi.mock('@/composables/useRegistryConfig', () => ({ registryConfigWithin: async () => h.cfg }))
vi.mock('./client', () => ({ apiClient: { get: h.get, post: h.post, patch: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ agentToken: null, activeAgent: null }) }))

import { contractsV2Api, TEMPLATES_OFF_DETAIL } from './contractsV2'

describe('a registry without the template library is not asked for it', () => {
  beforeEach(() => {
    h.get.mockReset().mockResolvedValue({ data: { items: [], next_cursor: null } })
    h.post.mockReset().mockResolvedValue({ data: {} })
  })

  it("off: the library's calls answer its own 503 and send nothing", async () => {
    h.cfg = { contract_templates_enabled: false }
    for (const call of [() => contractsV2Api.listTemplates({ limit: 24 }), () => contractsV2Api.getTemplate('t-1'),
      () => contractsV2Api.forkTemplate('t-1', { slug: 'x' })]) {
      const e: any = await call().catch((x) => x)
      expect(e?.response?.status).toBe(503)
      expect(e?.response?.data?.detail).toBe(TEMPLATES_OFF_DETAIL)
    }
    expect(h.get).not.toHaveBeenCalled()
    expect(h.post).not.toHaveBeenCalled()
  })

  it('off: a contract itself is still asked (operators run contracts)', async () => {
    h.cfg = { contract_templates_enabled: false }
    h.get.mockResolvedValue({ data: { items: [] } })
    await contractsV2Api.mine()
    expect(h.get).toHaveBeenCalled()
  })

  it('on, or an older registry: asked as before', async () => {
    for (const cfg of [{ contract_templates_enabled: true }, {}]) {
      h.cfg = cfg
      h.get.mockClear()
      await contractsV2Api.listTemplates({ limit: 24 })
      expect(h.get).toHaveBeenCalledWith('/contracts/templates', expect.objectContaining({ params: { limit: 24 } }))
    }
  })
})
