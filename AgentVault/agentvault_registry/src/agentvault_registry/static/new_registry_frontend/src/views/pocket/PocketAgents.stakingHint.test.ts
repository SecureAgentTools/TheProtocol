/**
 * §LEDGERGATE (V0601): Pocket's My agents names staking in its hint ("Full agent management (forge, cards, evals,
 * staking) lives in Advanced mode") only where the registry says staking is open, as the Pocket home's own staking doors
 * do. EU and ASIA, where STAKING_ENABLED is false, said it on every phone (found on journal 51's figures). RED on
 * fe/batch-v0600 (the hint names staking whatever the registry says).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, reactive, ref } from 'vue'

const h = vi.hoisted(() => ({ cfg: { value: {} as Record<string, unknown> } }))
vi.mock('@/composables/useRegistryConfig', async (orig) => ({
  ...(await orig<typeof import('@/composables/useRegistryConfig')>()), useRegistryConfig: () => ({ config: h.cfg }),
}))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: async () => ({ items: [], total: 0 }) } }))
vi.mock('@/services/api/developers', () => ({ developerApi: { getAgentBalancesBatch: async () => ({ balances: {} }) } }))
vi.mock('@/services/pocketMarks', () => ({ marksForMany: () => {} }))
vi.mock('vue-router', () => ({ useRoute: () => reactive({ query: {} }), useRouter: () => ({ replace: vi.fn(async () => {}), push: vi.fn(async () => {}) }) }))
vi.mock('@/composables/usePullToRefresh', () => ({
  usePullToRefresh: () => ({ ptrH: ref(0), ptrArmed: ref(false), onTouchStart() {}, onTouchMove() {}, onTouchEnd() {} }),
}))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ amount: (v: unknown) => String(v), localCurrency: computed(() => 'ECU') }) }))
vi.mock('@/composables/useActingContext', () => ({ useActingContext: () => ({ actingCurrencyLabel: computed(() => 'ECU') }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => reactive({ agentCreatedTick: 0, openQuickAgentModal: () => {} }) }))

import PocketAgents from './PocketAgents.vue'

async function hint(cfg: Record<string, unknown>) {
  h.cfg.value = cfg
  const w = mount(PocketAgents, { global: { stubs: { Icon: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w.find('.pg-hint').text()   // the class, not the testid: the same element on fe/batch-v0600, so RED there is about the word
}

describe("Pocket's My agents names staking only where the registry runs it", () => {
  beforeEach(() => { h.cfg.value = {} })

  it('says locks where locking is open (never staking: his word 2026-10-25)', async () => {
    const text = await hint({ staking_enabled: true })
    expect(text).toContain('locks')
    expect(text).not.toMatch(/staking/i)
  })

  it('does not say staking where staking is off', async () => {
    const text = await hint({ staking_enabled: false })
    expect(text).not.toMatch(/locks|staking/i)
    expect(text).toContain('forge, cards, evals')
  })

  it('does not say staking before the registry has said it runs it', async () => {
    expect(await hint({})).not.toMatch(/locks|staking/i)
  })
})
