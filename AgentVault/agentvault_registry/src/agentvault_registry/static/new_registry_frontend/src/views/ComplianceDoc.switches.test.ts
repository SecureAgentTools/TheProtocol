/**
 * §FESUITE V0595 (his word 2026-10-11, "also correct the avt prose in the docs"): a compliance document shows the parts
 * about the staking reward engine only where this registry says staking rewards are on. Lifecycle 51 read them on
 * sbx-beta, a frame with production's switches (fes-20261011T032003Z-17e0): 27 sentences across the documents, each a
 * hit on a frame without rewards. Off, the parts are left out and the page names the switch; unread, it names none and
 * says it could not read; on, the document reads as before.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'

const h = vi.hoisted(() => ({ known: null as unknown as { value: Record<string, boolean> }, loaded: null as unknown as { value: boolean }, slug: 'ai-system-lifecycle' }))
vi.mock('vue-router', () => ({ useRoute: () => reactive({ params: { slug: h.slug } }), RouterLink: { template: '<a><slot /></a>' } }))
vi.mock('@/services/legal/config', () => ({ useLegalConfig: () => ({ config: ref(null) }) }))
vi.mock('@/composables/useI18n', () => ({
  useI18n: () => ({
    t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k),
    tp: (_k: string, fb: string, p: Record<string, string>) => fb.replace(/\{(\w+)\}/g, (_m, n) => p[n] ?? ''),
  }),
}))
vi.mock('@/composables/docs/useDocSwitches', () => ({ useDocSwitches: () => ({ known: h.known, loaded: h.loaded }) }))

import ComplianceDoc from './ComplianceDoc.vue'

async function doc(slug: string, known: Record<string, boolean>, loaded = true) {
  h.slug = slug
  h.known.value = known
  h.loaded.value = loaded
  const w = mount(ComplianceDoc, { global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } } })
  await flushPromises()
  return w
}

describe('a compliance document follows the reward switch', () => {
  beforeEach(() => {
    h.known = ref({}) as never
    h.loaded = ref(true) as never
  })

  it('off: the reward engine\'s parts are left out, and the page names the switch that left them out', async () => {
    const w = await doc('ai-system-lifecycle', { staking_rewards: false, fiat_onramp: false, agora_distributions: false })
    const text = w.find('.cpd-content').text()
    expect(text).not.toMatch(/payout on locked units|payout rate|reward rate|staking rewards?|apy-tiers/i)
    expect(text, 'the rest of the document is still there').toMatch(/Component 4: Collusion Detector/)
    expect(w.find('.cpd-content').html(), 'a marker reached the page').not.toMatch(/&lt;!--|<!--/)
    expect(w.find('[data-testid="docs-switch-left-out"]').text()).toMatch(/STAKING_REWARDS_ENABLED is on are left out/)
    expect(w.find('[data-testid="docs-switch-unread"]').exists()).toBe(false)
  })

  it('on: the document reads as before, with no note', async () => {
    const w = await doc('ai-system-lifecycle', { staking_rewards: true })
    expect(w.find('.cpd-content').text()).toMatch(/Component 3: Payout on Locked Units/)
    expect(w.find('[data-testid="docs-switch-note"]').exists()).toBe(false)
  })

  it('unread: its parts stay out and the page says it could not read, never "off"', async () => {
    const w = await doc('iso-42001-alignment', {})
    expect(w.find('.cpd-content').text()).not.toMatch(/payout on locked units|dynamic reward rate/i)
    expect(w.find('[data-testid="docs-switch-unread"]').exists()).toBe(true)
    expect(w.find('[data-testid="docs-switch-left-out"]').exists(), 'an unread switch said "off"').toBe(false)
  })

  it('before the read settles the page names nothing it left out', async () => {
    const w = await doc('risk-assessment-framework', {}, false)
    expect(w.find('[data-testid="docs-switch-note"]').exists()).toBe(false)
    expect(w.find('.cpd-content').text(), 'the register row (the version history may name it)').not.toMatch(/R-AI-04\s+(Payout on locked units|Dynamic reward rate)/)
  })

  it('the risk summary counts the rows the register shows', async () => {
    const off = (await doc('risk-assessment-framework', { staking_rewards: false })).find('.cpd-content').text()
    expect(off).toMatch(/LOW \(1-6\)\s*8\s/)
    expect(off).toMatch(/R-AI-01, R-AI-03, R-AI-06, R-OP-02/)
    expect(off).not.toMatch(/R-AI-04\s+(Payout on locked units|Dynamic reward rate)/)
    const on = (await doc('risk-assessment-framework', { staking_rewards: true })).find('.cpd-content').text()
    expect(on).toMatch(/LOW \(1-6\)\s*9\s/)
    expect(on).toMatch(/R-AI-01, R-AI-03, R-AI-04, R-AI-06/)
  })
})
