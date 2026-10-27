import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the Compliance Monitor's degradation-signals panel and its peer-trust
 * section hid themselves over a failed read, as if this page did not ask those questions at all. Each now keeps its
 * heading and says the read failed (Try again); a registry without the route (404) still shows neither, as before.
 */
const h = vi.hoisted(() => ({ get: vi.fn(), peerTrust: vi.fn() }))
vi.mock('@/services/api/client', () => {
  const c = { get: h.get, post: vi.fn() }
  return { default: c, apiClient: c }   // the view takes the default export
})
vi.mock('@/services/api/consulApi', () => {
  const no = () => Promise.reject(Object.assign(new Error('x'), { response: { status: 502 } }))
  return { consulApi: {
    getPeerTrust: h.peerTrust, getMode: no, getOverview: no, getEvents: no, getDrifts: no, getTrustBundleMatrix: no,
    getPeerDetailByOperator: no, acceptBaseline: no, blacklist: no, liftQuarantine: no, manualQuarantine: no,
    pollPeerNow: no, previewQuarantine: no, runDriftScan: no, setMode: no, triggerFederationSync: no,
  } }
})
vi.mock('@/composables/useFrameManifest', async () => {
  const { ref } = await import('vue')
  return { useFrameManifest: () => ({ frames: ref([]), byKey: () => null }) }
})
vi.mock('@/composables/useLiveRefresh', async () => {
  const { ref } = await import('vue')
  return { useLiveRefresh: () => ({ lastFetchedAt: ref(null), lastRefreshedLabel: ref(''), nextRefreshInSeconds: ref(0), paused: ref(false), markFetched: () => {} }) }
})
vi.mock('@/composables/usePermissions', () => ({ usePermissions: () => ({ can: () => true }) }))

import ComplianceMonitor from './ComplianceMonitor.vue'

const stubs = { Icon: true, CMEnforcementToggle: true, CMBlacklistModal: true, CMLiftDialog: true, CMPeerDrawer: true,
  ConfirmActionModal: true, teleport: true }
const failure = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('the Compliance Monitor says when a panel read failed', () => {
  beforeEach(() => { setActivePinia(createPinia()); h.get.mockReset(); h.peerTrust.mockReset() })

  it('a 502: both panels keep their heading and say the read failed', async () => {
    h.get.mockRejectedValue(failure(502))
    h.peerTrust.mockRejectedValue(failure(502))
    const w = mount(ComplianceMonitor, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="cm-degradation-unread"] [data-read-failed]').exists()).toBe(true)
    expect(w.find('[data-testid="cm-peer-trust-unread"] [data-read-failed]').exists()).toBe(true)
    w.unmount()
  })

  it('a registry without the routes (404): neither panel shows, as before', async () => {
    h.get.mockRejectedValue(failure(404))
    h.peerTrust.mockRejectedValue(failure(404))
    const w = mount(ComplianceMonitor, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-testid="cm-degradation-unread"]').exists(), 'degradation').toBe(false)
    expect(w.find('[data-testid="cm-peer-trust-unread"]').exists()).toBe(false)
    w.unmount()
  })
})
