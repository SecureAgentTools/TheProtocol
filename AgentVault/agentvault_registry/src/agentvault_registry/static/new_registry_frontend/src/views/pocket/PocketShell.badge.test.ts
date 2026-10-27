/**
 * §FESUITE (V0578): Pocket's shell puts the NEEDS YOU count on the installed app's icon (navigator.setAppBadge), and a 0
 * clears it. The count arrives null while NEEDS YOU loads and when every read failed; the shell read null as 0 and
 * cleared the icon badge: the phone said nothing needs you over reads that never answered. An unanswered count now
 * leaves the icon as it was; an answered 0 still clears it.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { computed, reactive, ref } from 'vue'

vi.mock('vue-router', () => ({
  useRoute: () => reactive({ path: '/pocket/home', fullPath: '/pocket/home', query: {} }),
  useRouter: () => ({ push: vi.fn(async () => {}), replace: vi.fn(async () => {}) }),
}))
vi.mock('@/composables/usePocketLock', () => ({
  usePocketLock: () => ({ arm() {}, locked: ref(false), busy: ref(false), unlock: async () => true }),
  maybeUnsealDeviceKeyVault: async () => {},
}))
vi.mock('@/composables/useAlive', () => ({ useAlive: () => () => true }))
vi.mock('@/composables/usePocketAgent', () => ({ usePocketAgent: () => ({ restoreActing: async () => {}, credAgents: computed(() => []) }) }))
vi.mock('@/stores/notifications', () => ({ useNotificationStore: () => ({ fetchUnread: async () => {}, unreadCount: 0, items: [] }) }))
vi.mock('@/composables/useLedgerStream', () => ({ useLedgerStream: () => ({ setMineDids() {} }) }))
vi.mock('@/composables/useVoice', () => ({ useVoice: () => ({ listening: ref(false), interim: ref(''), supported: false, start() {}, stop() {} }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => reactive({ showQuickAgentModal: false, openQuickAgentModal() {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: false, activeAgent: null }) }))
vi.mock('@/views/Tutorials/guided/tourStore', () => ({ useGuidedTourStore: () => ({ isActive: false, start() {} }) }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: async () => ({ data: {} }) } }))

import PocketShell from './PocketShell.vue'
import BridgeAttention from '@/components/bridge/BridgeAttention.vue'

const nav = navigator as any
beforeEach(() => {
  try { localStorage.setItem('pk_tour_done', '1') } catch { /* fine */ }
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })))
  nav.setAppBadge = vi.fn(async () => {})
  nav.clearAppBadge = vi.fn(async () => {})
})
afterEach(() => { vi.unstubAllGlobals(); delete nav.setAppBadge; delete nav.clearAppBadge })

async function shell() {
  const w = shallowMount(PocketShell, { global: { stubs: { RouterView: true, 'router-view': true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}

describe("Pocket's app icon badge follows NEEDS YOU's answered count", () => {
  it('an unanswered count does not clear the icon badge', async () => {
    const w = await shell()
    const attention = w.findComponent(BridgeAttention)
    attention.vm.$emit('count', 3)
    await flushPromises()
    expect(nav.setAppBadge).toHaveBeenLastCalledWith(3)
    nav.clearAppBadge.mockClear()
    attention.vm.$emit('count', null)
    await flushPromises()
    expect(nav.clearAppBadge, 'cleared the icon badge (nothing needs you) over a count that never answered').not.toHaveBeenCalled()
  })

  it('an answered 0 clears it', async () => {
    const w = await shell()
    const attention = w.findComponent(BridgeAttention)
    attention.vm.$emit('count', 2)
    await flushPromises()
    attention.vm.$emit('count', 0)
    await flushPromises()
    expect(nav.clearAppBadge).toHaveBeenCalled()
  })
})
