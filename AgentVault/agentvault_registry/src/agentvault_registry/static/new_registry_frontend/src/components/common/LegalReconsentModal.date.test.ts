/**
 * §FESUITE (2026-10-09): the re-consent notice takes its date from the legal config; with that read not answered it
 * said "A new version of the Terms (2.5) applies from . Please read ..." (sweeps/recovery on V0587, 39 admin pages).
 * Without a date it now says the sentence without one.
 */
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'

const legal = vi.hoisted(() => ({ cfg: null as any }))
vi.mock('@/services/legal/config', async () => {
  const { ref: r } = await import('vue')
  return { useLegalConfig: () => ({ config: r(legal.cfg), state: r(legal.cfg ? 'loaded' : 'failed'), reload: vi.fn() }) }
})
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ isAuthenticated: true, user: { tos_current_version: '2.5', tos_reconsent_required: true, reconsent_documents: ['terms'] } }),
}))
vi.mock('@/services/api/client', () => ({ apiClient: { post: vi.fn() } }))

import LegalReconsentModal from './LegalReconsentModal.vue'

const body = (w: any) => w.find('.lrc-body').text()

describe('the re-consent notice and its date', () => {
  it('says no date while the legal config is unread (it said "applies from .")', () => {
    legal.cfg = null
    const w = mount(LegalReconsentModal, { global: { stubs: { Teleport: true } } })
    expect(body(w)).not.toMatch(/applies from\s*\./)
    expect(body(w)).toContain('(2.5) applies.')
    w.unmount()
  })

  it('names the date the registry answered', () => {
    legal.cfg = { tos_version: '2.5', effective: '2026-11-03', effective_label: '3 November 2026' }
    const w = mount(LegalReconsentModal, { global: { stubs: { Teleport: true } } })
    expect(body(w)).toContain('applies from 3 November 2026.')
    w.unmount()
    void ref
  })
})
