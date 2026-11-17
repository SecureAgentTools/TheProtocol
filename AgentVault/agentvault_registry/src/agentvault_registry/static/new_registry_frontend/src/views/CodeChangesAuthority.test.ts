/**
 * V0666 (order gwo_e086b25f868da7ec9fce9fd2): governed code names ONE governing registry. On a registry that does not govern, the Code changes list and the propose page say the registry's
 * own sentence with the governing registry's link and offer no way to submit (no propose button, no form); on the governing registry both are exactly as they were; while the answer is
 * unknown (the read failed) the pages behave as before, the registry refusing at every write anyway. The record page's acting controls are guarded by the same rule.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ authority: null as any, auth: { isAuthenticated: true, activeAgent: { did: 'did:a:me' } as any } }))
vi.mock('@/services/api/codeChanges', async () => ({
  ...(await vi.importActual<any>('@/services/api/codeChanges')),
  listChanges: async () => [],
  getBallot: async () => null,
  getAuthority: async () => { if (h.authority instanceof Error) throw h.authority; return h.authority },
}))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: {}, query: {} }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import CodeChanges from './CodeChanges.vue'
import CodeChangeNew from './CodeChangeNew.vue'
import viewSource from './CodeChangeView.vue?raw'
import { resetCodeAuthorityForTests } from '@/services/codeChanges/authority'

const stubs = { Icon: true, CodeChangesTabs: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } }
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const OTHER = { governing: 'EU', self: false, name: 'EU', console: 'https://eu.theprotocol.cloud/', sentence: 'Code changes are governed on EU; open them there: https://eu.theprotocol.cloud/' }
const SELF = { governing: 'EU', self: true, name: 'EU', console: null, sentence: null }

beforeEach(() => { resetCodeAuthorityForTests(); h.authority = SELF })

describe('the Code changes list', () => {
  const mountIt = async () => { const w = mount(CodeChanges, { global: { stubs } }); await flushPromises(); await flushPromises(); return w }

  it('says the sentence with the link and shows no propose button where code is not governed', async () => {
    h.authority = OTHER
    const w = await mountIt()
    expect(tid(w, 'cc-governed-sentence').text()).toBe(OTHER.sentence)
    expect(tid(w, 'cc-governed-link').attributes('href')).toBe('https://eu.theprotocol.cloud/')
    expect(tid(w, 'ccl-propose').exists()).toBe(false)
    expect(w.find('.ccl-empty a, .ccl-empty .primary').exists()).toBe(false)          // the empty state's own invitation is gone too
  })

  it('is unchanged on the governing registry', async () => {
    const w = await mountIt()
    expect(tid(w, 'cc-governed-elsewhere').exists()).toBe(false)
    expect(JSON.parse(tid(w, 'ccl-propose').attributes('data-to')!)).toEqual({ name: 'code-changes-new' })
  })

  it('behaves as before when the answer cannot be read', async () => {
    h.authority = new Error('down')
    const w = await mountIt()
    expect(tid(w, 'cc-governed-elsewhere').exists()).toBe(false)
    expect(tid(w, 'ccl-propose').exists()).toBe(true)
  })
})

describe('the propose page', () => {
  const mountIt = async () => { const w = mount(CodeChangeNew, { global: { stubs } }); await flushPromises(); await flushPromises(); return w }

  it('shows the sentence in place of the form where code is not governed', async () => {
    h.authority = OTHER
    const w = await mountIt()
    expect(tid(w, 'cc-governed-sentence').text()).toBe(OTHER.sentence)
    expect(tid(w, 'ccn-pills').exists()).toBe(false)
    expect(tid(w, 'ccn-step-what').exists()).toBe(false)
    expect(tid(w, 'ccn-title').exists()).toBe(false)
  })

  it('is the guided flow, unchanged, on the governing registry', async () => {
    const w = await mountIt()
    expect(tid(w, 'cc-governed-elsewhere').exists()).toBe(false)
    expect(tid(w, 'ccn-step-what').exists()).toBe(true)
  })
})

describe('the record page', () => {
  const src = viewSource as string
  it('hides each acting control (review, open the ballot, withdraw) by the same rule and shows the banner', () => {
    expect(src).toContain('<GovernedElsewhere v-if="authorityView_.readOnly"')
    expect(src).toMatch(/v-else-if="!authorityView_\.readOnly && canReview\(/)
    expect(src).toMatch(/v-if="!authorityView_\.readOnly && canOpenBallot\(/)
    expect(src).toMatch(/v-if="canWithdraw && !authorityView_\.readOnly"/)
  })
})
