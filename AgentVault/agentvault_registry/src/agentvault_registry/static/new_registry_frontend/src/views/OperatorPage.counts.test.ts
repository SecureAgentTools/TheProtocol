import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): the public operator page's hero counts ("operators live", "frames paired")
 * come from the frame manifest and read '…' until it answers. A failed manifest read (or a registry that states none)
 * settled the manifest without one, and '…' stayed for good: a count still loading that nobody was reading. '…' is the
 * in-flight state only now; a settled read without a manifest says '—'; an answered manifest shows its counts (control).
 */
const h = vi.hoisted(() => ({ manifest: null as unknown, settled: false }))
vi.mock('@/composables/useFrameManifest', async () => {
  const { computed } = await import('vue')
  return {
    useFrameManifest: () => ({
      manifest: computed(() => h.manifest),
      settled: computed(() => h.settled),
      frames: computed(() => (h.manifest ? [{ key: 'eu' }, { key: 'asia' }] : [])),
    }),
  }
})
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }), useRoute: () => ({ query: {} }) }))

import OperatorPage from './OperatorPage.vue'

const opts = { global: { stubs: { Icon: true, RouterLink: true, 'router-link': true, Teleport: true, teleport: true } } }
const counts = (w: ReturnType<typeof mount>) => w.findAll('.op-proof-val').slice(0, 2).map((e) => e.text())

describe('the operator page counts say what the manifest answered', () => {
  // no IntersectionObserver: the strip is shown at once with its values (happy-dom's observer never fires, so the
  // tick-up would hold every count at its starting 0)
  beforeEach(() => { h.manifest = null; h.settled = false; vi.stubGlobal('IntersectionObserver', undefined) })
  afterEach(() => { vi.unstubAllGlobals() })

  it('in flight: the counts read "…"', async () => {
    const w = mount(OperatorPage, opts)
    await flushPromises()
    expect(counts(w)).toEqual(['…', '…'])
    w.unmount()
  })

  it('the read settled without a manifest (failed, or none stated): the counts read "—", never "…" for good', async () => {
    h.settled = true
    const w = mount(OperatorPage, opts)
    await flushPromises()
    expect(counts(w)).toEqual(['—', '—'])
    w.unmount()
  })

  it('control: an answered manifest shows its counts', async () => {
    h.settled = true
    h.manifest = { self: { key: 'eu', role: 'frame' }, peers: [{ key: 'amsterdam', role: 'operator' }, { key: 'asia', role: 'frame' }] }
    const w = mount(OperatorPage, opts)
    await flushPromises()
    expect(counts(w)).toEqual(['1', '2'])
    w.unmount()
  })
})
