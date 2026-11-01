/**
 * V0652 (af) (order gwo_3b80091fe506da824c40f903): the console's notification settings show every category the catalog
 * sends. The matrix walked a fixed list of six (security, agents, money, contracts, marketplace, ops), so the chat
 * category (approval requests, mentions, direct messages, pings) and every category added after it could be configured
 * nowhere. Now the known ones come in order, an unknown one after them; the broadcasts stay in the strip below, which
 * sets them. And "Quiet mobile" keeps the decisions someone waits on ringing the phone, as its own sentence says.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), patch: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, put: h.put, patch: h.patch } }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showInfo: vi.fn() }) }))
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useRegistryConfig: () => ({ config: ref({}) }),
}))

import NotificationsPanel from './NotificationsPanel.vue'

const eff = { enabled: true, source: 'default', threshold: null }
const type = (key: string, category: string) => ({
  key, category, severity: 'info', mandatory: false, audience: 'developer', legacy_managed: false, emitter: true,
  threshold_kind: 'none', threshold_default: null, coalesce_window_s: 0,
  default_enabled: { inapp: true, push_mobile: true },
  effective: { inapp: eff, email: { ...eff, enabled: false }, push_desktop: eff, push_mobile: eff },
})
const TYPES = [
  type('security.new_login', 'security'),
  type('chat.approval_requested', 'chat'),
  type('chat.mention', 'chat'),
  type('governance.proposal_opened', 'governance'),
  type('org.invitation_received', 'organizations'),
  type('legal.terms_updated', 'legal'),
  type('broadcast.info', 'broadcast'),
  type('zeta.something_new', 'zeta'),
]

async function panel() {
  h.get.mockImplementation(async (url: string) => (url === '/notifications/prefs/effective'
    ? { data: { types: TYPES, mode: 'on' } }
    : { data: {} }))
  const w = mount(NotificationsPanel, { global: { stubs: { ReadFailedNotice: true } } })
  for (let i = 0; i < 3; i++) await flushPromises()
  return w
}
const cats = (w: any) => w.findAll('.np-cat').map((c: any) => c.findAll('.np-mrow').map((r: any) => r.attributes('data-type')))

describe('the notification settings show every category', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.get.mockReset(); h.put.mockReset(); h.patch.mockReset()
  })

  it('the chat, governance, organizations and terms rows are configurable, in order, and an unknown category follows', async () => {
    const w = await panel()
    expect(cats(w)).toEqual([
      ['security.new_login'],
      ['chat.approval_requested', 'chat.mention'],
      ['governance.proposal_opened'],
      ['org.invitation_received'],
      ['legal.terms_updated'],
      ['zeta.something_new'],
    ])
    expect(w.find('[data-type="chat.approval_requested"] input[data-channel="push_mobile"]').exists()).toBe(true)
  })

  it('the broadcasts stay in the strip that sets them', async () => {
    const w = await panel()
    expect(w.find('.np-cat [data-type="broadcast.info"]').exists()).toBe(false)
  })

  it('"Quiet mobile" keeps the decisions someone waits on', async () => {
    const w = await panel()
    h.put.mockResolvedValue({ data: {} })
    await w.findAll('.np-preset-btn').find((b: any) => b.text() === 'Quiet mobile')!.trigger('click')
    await flushPromises()
    const rows = h.put.mock.calls[0][1].rows
    expect(rows[0]).toEqual({ type_key: '*', channel: 'push_mobile', enabled: false })
    expect(rows).toContainEqual({ type_key: 'chat.approval_requested', channel: 'push_mobile', enabled: true })
    // a type this registry does not have is not written
    expect(rows.some((r: any) => r.type_key === 'chat.choice_requested')).toBe(false)
  })
})
