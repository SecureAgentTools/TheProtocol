/**
 * §FESUITE (V0578): the EventStore explorer's frame buttons stay live while a read is out (its other controls do not).
 * A switch to another frame left the previous frame's events on screen under the new frame's button ("Showing 1 events
 * from ASIA") until the new read answered, and a slower read landing after a later one replaced it: the events of one
 * frame drawn under another. Events are now drawn only under the frame they were read from, and a superseded read never
 * lands.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { computed, reactive } from 'vue'

const h = vi.hoisted(() => ({ frameGet: vi.fn() }))
vi.mock('@/services/api/eventStoreAdmin', async (orig) => ({
  ...(await orig<any>()),
  eventStoreAdminService: { emissionPolicyTypes: async () => [], stats: async () => ({}) },
}))
vi.mock('@/composables/useAdminFrames', () => {
  const local = { key: 'local', label: 'EU', sub: '', accentHex: '#0ff', isLocal: true, frameParam: 'local' }
  const asia = { key: 'asia', label: 'ASIA', sub: '', accentHex: '#f00', isLocal: false, frameParam: 'local' }
  class FrameNotConnectedError extends Error {}
  return {
    FrameNotConnectedError,
    useAdminFrames: () => ({
      selectableFrames: computed(() => [local, asia]),
      resolveOption: (k: string) => (k === 'asia' ? asia : local),
      frameGet: (...a: unknown[]) => h.frameGet(...a),
      ensureTargets: async () => {},
    }),
  }
})
vi.mock('@/stores/ui', () => ({ useUIStore: () => reactive({ showError: vi.fn(), setActiveFrame: vi.fn(), activeFrame: null }) }))
vi.mock('vue-router', () => ({ useRoute: () => reactive({ query: {} }), useRouter: () => ({ replace: vi.fn(async () => {}), push: vi.fn(async () => {}) }) }))

import AdminEvents from './AdminEvents.vue'

const ev = (type: string, i: number) => ({ id: `${type}-${i}`, event_type: type, aggregate_id: `agg-${type}-${i}`, timestamp: '2026-10-05T15:00:00Z' })
const answer = (type: string) => ({ events: [ev(type, 1)], count: 1 })

let w: VueWrapper
async function explorer() {
  w = mount(AdminEvents, { global: { stubs: { Icon: true, JsonViewer: true, RouterLink: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
async function frame(label: string) {
  const b = w.findAll('.ae-frame-switch .ae-frame-btn').find(x => x.text().toLowerCase().includes(label.toLowerCase()))
  expect(b, `no ${label} frame button`).toBeTruthy()
  await b!.trigger('click')
  await flushPromises()
}
const main = () => w.find('.ae-main').text()

describe("the EventStore explorer draws a frame's events only under that frame", () => {
  beforeEach(() => { h.frameGet.mockReset() })

  it("while ASIA's read is out, EU's events are not shown under the ASIA button", async () => {
    h.frameGet.mockImplementation(async (key: string) => (key === 'local' ? answer('EuOnlyEvent') : new Promise(() => {})))
    await explorer()
    expect(main()).toContain('EuOnlyEvent')
    await frame('asia')
    expect(main(), "drew EU's events under the ASIA button while ASIA's read was out").not.toContain('EuOnlyEvent')
  })

  it("a late answer for a frame already left never lands under the frame now selected", async () => {
    let releaseAsia!: (v: unknown) => void
    h.frameGet.mockImplementation((key: string) => (key === 'local'
      ? Promise.resolve(answer('EuOnlyEvent'))
      : new Promise(r => { releaseAsia = r })))
    await explorer()
    await frame('asia')    // ASIA's read: slow
    await frame('EU')      // back to EU: answers at once
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(main()).toContain('EuOnlyEvent')
    releaseAsia(answer('AsiaOnlyEvent'))
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(main(), "ASIA's late answer replaced EU's events under the EU button").not.toContain('AsiaOnlyEvent')
    expect(main()).toContain('EuOnlyEvent')
  })

  it("an answered switch shows the new frame's events", async () => {
    h.frameGet.mockImplementation(async (key: string) => (key === 'local' ? answer('EuOnlyEvent') : answer('AsiaOnlyEvent')))
    await explorer()
    await frame('asia')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(main()).toContain('AsiaOnlyEvent')
    expect(main()).not.toContain('EuOnlyEvent')
  })
})
