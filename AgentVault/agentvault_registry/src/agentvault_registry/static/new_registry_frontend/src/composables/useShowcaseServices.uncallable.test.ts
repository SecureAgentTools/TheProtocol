/**
 * §MCPTEST30 (V0641, D6-831, agentvault2-66 2026-10-25): the showcase page reads which entries this frame can make a
 * paid call to from the catalogue (`callable: false` with its `reason`), and a call that refuses itself up front keeps
 * the run off for that entry with the call's own words. A registry that sends no `callable` field (an older one, or a
 * check that could not run) leaves every entry as it was.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

vi.mock('@/composables/useFrameManifest', () => ({ currentOwnCurrency: () => 'SBXA' }))

import { useShowcaseServices } from './useShowcaseServices'

const WHY = 'did:theprotocol:w holds no reputation bond.'
const NO_PAYER = 'This frame has no showcase payer of its own and names no showcase relay, so a paid showcase call cannot be made here.'

function fetchAnswering(agents: unknown[], call?: { status: number; body: unknown }) {
  return vi.fn(async (url: string) => {
    if (String(url).includes('/public/showcase/agents')) {
      return { ok: true, status: 200, json: async () => ({ agents, count: agents.length }) } as any
    }
    return { ok: (call?.status ?? 200) < 300, status: call?.status ?? 200, json: async () => call?.body ?? {} } as any
  })
}

async function mounted() {
  let api: ReturnType<typeof useShowcaseServices> | null = null
  const C = defineComponent({ setup() { api = useShowcaseServices(); return () => h('div') } })
  const w = mount(C)
  await flushPromises()
  return { api: api!, w }
}

afterEach(() => { vi.unstubAllGlobals() })

describe('which entries the page offers a run for', () => {
  it('an entry the catalogue says cannot be called carries its reason', async () => {
    vi.stubGlobal('fetch', fetchAnswering([
      { id: 'weather', price: '0.5', currency: 'SBXA', callable: false, reason: WHY },
      { id: 'ip', price: '0.1', currency: 'SBXA', callable: true, reason: null },
    ]))
    const { api, w } = await mounted()
    expect(api.services.find(s => s.id === 'weather')!.uncallable).toBe(WHY)
    expect(api.services.find(s => s.id === 'ip')!.uncallable).toBeUndefined()
    w.unmount()
  })

  it('a call that refuses itself keeps the run off with its words', async () => {
    vi.stubGlobal('fetch', fetchAnswering([{ id: 'weather', price: '0.5', currency: 'SBXA' }],
      { status: 503, body: { error: NO_PAYER, service: 'weather', callable: false } }))
    const { api, w } = await mounted()
    const weather = api.services.find(s => s.id === 'weather')!
    weather.value = 'Berlin'
    await api.call(weather)
    expect(api.results.weather.error).toBe(NO_PAYER)
    expect(weather.uncallable).toBe(NO_PAYER)
    w.unmount()
  })

  it('control: a catalogue without the field leaves the entries as they were', async () => {
    vi.stubGlobal('fetch', fetchAnswering([{ id: 'weather', price: '0.5', currency: 'SBXA' }]))
    const { api, w } = await mounted()
    expect(api.services.find(s => s.id === 'weather')!.uncallable).toBeUndefined()
    expect(api.services.find(s => s.id === 'weather')!.priceNative).toBe('0.5')
    w.unmount()
  })
})
