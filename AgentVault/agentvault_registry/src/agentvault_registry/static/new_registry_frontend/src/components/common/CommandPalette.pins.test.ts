/**
 * V0662 sidebar (order gwo_0feb166a01e2ff611e154361): the command palette can pin. A Navigate row whose page the sidebar
 * lists carries a pin mark (its state in data-pinned; out of the accessibility tree, the option says "pinned" in words,
 * since a button beside or inside an option would break the listbox), and Alt+P pins or unpins the selected row; both go through the
 * sidebar's own pins (services/nav/navPins), so a pin made here shows in the Pinned block. A page the sidebar does not
 * list offers no pin (the Pinned block could not show it). Red on f569f6a6e: no pin anywhere in the palette.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive, ref } from 'vue'

const h = vi.hoisted(() => ({ pinned: null as any, toggle: null as any }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }), useRoute: () => reactive({ path: '/mission-control' }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ setBrandTheme: vi.fn(), customThemeHex: null, showSuccess: vi.fn(), showError: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAdmin: false, isAuthenticated: true, user: { id: 6 }, logout: vi.fn() }) }))
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => {
  const { computed } = await import('vue')
  return { ...(await importOriginal<Record<string, unknown>>()),
    useRegistryConfig: () => ({ config: computed(() => ({})), localCurrency: computed(() => 'ECU') }) }
})
vi.mock('@/services/nav/navPins', () => ({
  useNavPins: () => ({ pins: h.pinned, isPinned: (p: string) => h.pinned.value.includes(p), toggle: h.toggle, load: async () => {} }),
}))

import CommandPalette from './CommandPalette.vue'

async function openWith(q: string) {
  const w = mount(CommandPalette, { attachTo: document.body, global: { stubs: { ConfirmActionModal: true, Teleport: true } } })
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))
  await flushPromises()
  await w.find('input').setValue(q)
  await flushPromises()
  return w
}

describe('pinning from the palette', () => {
  beforeEach(() => {
    h.pinned = ref(['/mission-control'])
    h.toggle = vi.fn(async () => 'saved')
  })

  it('a row the sidebar lists has a pin mark; it pins that page', async () => {
    const w = await openWith('webhooks')
    try {
      const pin = w.find('[data-testid="cmdk-pin-/webhooks"]')
      expect(pin.exists()).toBe(true)
      expect(pin.attributes('data-pinned')).toBe('false')
      await pin.trigger('click')
      expect(h.toggle).toHaveBeenCalledWith('/webhooks')
    } finally { w.unmount() }
  })

  it('Alt+P pins or unpins the selected row', async () => {
    const w = await openWith('webhooks')
    try {
      window.dispatchEvent(new KeyboardEvent('keydown', { key: 'p', altKey: true }))
      await flushPromises()
      expect(h.toggle).toHaveBeenCalledWith('/webhooks')
    } finally { w.unmount() }
  })

  it('a pinned page says so; a page the sidebar does not list offers no pin', async () => {
    const w = await openWith('dashboard')
    try {
      expect(w.find('[data-testid="cmdk-pin-/mission-control"]').attributes('data-pinned')).toBe('true')
    } finally { w.unmount() }
    const w2 = await openWith('api keys')
    try {
      expect(w2.text()).toContain('API Keys')
      expect(w2.find('[data-testid="cmdk-pin-/api-keys"]').exists()).toBe(false)
    } finally { w2.unmount() }
  })
})
