import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): Settings → Location's place search over a failed (502) or switched-off
 * (404) search drew nothing, exactly what an answered search with no place drew (both drew nothing at all). It says which
 * now, with agentvault2-b2's searchPlaces (the registry card editor's): "No place found", "This frame does not search
 * places", or the read failed (Try again). An answered search still lists its places (the control).
 */
const h = vi.hoisted(() => ({ fetch: vi.fn() }))
vi.mock('@/services/api/client', () => {
  const c = { get: vi.fn(async (url: string) => ({ data: String(url).includes('api-keys') ? [] : {} })), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }
  return { apiClient: c, default: c }
})
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { developer_id: 1, email: 'dev@example.org', is_admin: false }, token: 'tok', isAdmin: false }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn() }) }))
vi.mock('@/services/api/inviteCodes', () => ({ getRegistrationConfig: vi.fn().mockResolvedValue({}) }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: { tab: 'location' }, path: '/settings' }),
  useRouter: () => ({ replace: vi.fn().mockResolvedValue(undefined), push: vi.fn().mockResolvedValue(undefined) }),
}))

import Settings from './Settings.vue'

const opts = {
  global: {
    stubs: { Icon: true, MultiFrameConsole: true, TwoFactorSettings: true, ConfirmActionModal: true, ThemeStudio: true,
      NotificationsPanel: true, PocketNotificationLog: true, InvitationsPanel: true, SpendApprovalsPanel: true,
      UserAvatar: true, McpAuditLogPanel: true, Teleport: true, teleport: true, RouterLink: true },
  },
}
const has = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"]`).exists()
function geocodeAnswers(res: () => Promise<unknown>) {
  h.fetch.mockImplementation(async (url: string) => (String(url).includes('/public/geocode') ? res() : { ok: false, status: 404, json: async () => ({}) }))
}
async function search(w: ReturnType<typeof mount>, q: string) {
  await w.find('input[placeholder="e.g. Frankfurt, Germany"]').setValue(q)
  // the button beside the input, by its word (the base has no test id on it: the control must fail on the claim)
  const btn = w.findAll('button').find((b) => b.text().trim() === 'Search')
  if (!btn) throw new Error('no Search button')
  await btn.trigger('click')
  await flushPromises()
}

describe('Settings → Location says what the place search answered', () => {
  beforeEach(() => { h.fetch.mockReset(); vi.stubGlobal('fetch', h.fetch) })
  afterEach(() => { vi.unstubAllGlobals() })

  it('a 502: the search says it failed, and Try again searches again', async () => {
    geocodeAnswers(async () => ({ ok: false, status: 502, json: async () => ({ detail: 'upstream' }) }))
    const w = mount(Settings, opts)
    await flushPromises()
    await search(w, 'Frankfurt')
    expect(has(w, 'st-geo-failed'), 'a failed search').toBe(true)
    expect(has(w, 'st-geo-none'), 'never "no place found" over a failed search').toBe(false)
    geocodeAnswers(async () => ({ ok: true, status: 200, json: async () => [{ display_name: 'Frankfurt, Hesse, Germany', lat: '50.11', lon: '8.68' }] }))
    await w.find('[data-testid="st-geo-failed"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.findAll('.geocode-result-btn').length).toBe(1)
    w.unmount()
  })

  it('no answer at all: failed as well; a 404: this frame does not search places', async () => {
    geocodeAnswers(async () => { throw new TypeError('Failed to fetch') })
    const w = mount(Settings, opts)
    await flushPromises()
    await search(w, 'Lisbon')
    expect(has(w, 'st-geo-failed')).toBe(true)
    geocodeAnswers(async () => ({ ok: false, status: 404, json: async () => ({ detail: 'Not Found' }) }))
    await search(w, 'Lisboa')
    expect(has(w, 'st-geo-off')).toBe(true)
    expect(has(w, 'st-geo-failed')).toBe(false)
    w.unmount()
  })

  it('control: an answered empty search says no place; an answered one lists its places', async () => {
    geocodeAnswers(async () => ({ ok: true, status: 200, json: async () => [] }))
    const w = mount(Settings, opts)
    await flushPromises()
    await search(w, 'Nowhereville')
    expect(has(w, 'st-geo-none')).toBe(true)
    geocodeAnswers(async () => ({ ok: true, status: 200, json: async () => [{ display_name: 'Brussels, Belgium', lat: '50.85', lon: '4.35' }] }))
    await search(w, 'Brussels')
    expect(w.findAll('.geocode-result-btn').length).toBe(1)
    expect(has(w, 'st-geo-none') || has(w, 'st-geo-failed') || has(w, 'st-geo-off')).toBe(false)
    w.unmount()
  })
})
