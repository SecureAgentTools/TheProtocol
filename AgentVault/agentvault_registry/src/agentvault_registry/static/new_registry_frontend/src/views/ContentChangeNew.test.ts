/**
 * V0667 D5 (order gwo_d238dcda72add8e05b6d657b): proposing a content change. The form builds the proposal for each kind and sends nothing while anything is missing; our checker's refusal is shown with its reasons
 * and the page stays; on a registry that does not govern code the sentence replaces the form.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ propose: vi.fn(), push: vi.fn(), authority: null as any, query: {} as Record<string, string>, auth: { isAuthenticated: true, activeAgent: { did: 'did:a:me' } as any } }))
vi.mock('@/services/api/contentChanges', async () => ({ ...(await vi.importActual<any>('@/services/api/contentChanges')), proposeContentChange: (...a: any[]) => h.propose(...a) }))
vi.mock('@/services/api/codeChanges', async () => ({ ...(await vi.importActual<any>('@/services/api/codeChanges')), getAuthority: async () => h.authority }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: {}, query: h.query }), useRouter: () => ({ push: h.push, replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import ContentChangeNew from './ContentChangeNew.vue'
import { resetCodeAuthorityForTests } from '@/services/codeChanges/authority'

const stubs = { RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } }
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const mountIt = async () => { const w = mount(ContentChangeNew, { global: { stubs } }); await flushPromises(); await flushPromises(); return w }
const OTHER = { governing: 'EU', self: false, name: 'EU', console: 'https://eu.theprotocol.cloud/', sentence: 'Code changes are governed on EU; open them there: https://eu.theprotocol.cloud/' }

beforeEach(() => { resetCodeAuthorityForTests(); h.propose.mockReset(); h.push.mockReset(); h.authority = { governing: 'EU', self: true, name: 'EU', console: null, sentence: null }; h.query = { line: 'lyceum', title: 'Quiet releases' }; h.auth = { isAuthenticated: true, activeAgent: { did: 'did:a:me' } } })

describe('the content change proposal', () => {
  it('opens prefilled from the room\'s door: the line and the title', async () => {
    const w = await mountIt()
    expect((tid(w, 'cnn-line').element as HTMLInputElement).value).toBe('lyceum')
    expect((tid(w, 'cnn-title').element as HTMLInputElement).value).toBe('Quiet releases')
  })
  it('sends nothing while anything is missing, and says what', async () => {
    const w = await mountIt()
    await tid(w, 'cnn-form').trigger('submit')
    expect(h.propose).not.toHaveBeenCalled()
    expect(tid(w, 'cnn-problems').exists()).toBe(true)
  })
  it('proposes a console text and goes back to the line', async () => {
    h.propose.mockResolvedValue({ id: 'ct_1' })
    const w = await mountIt()
    await tid(w, 'cnn-target').setValue('landing.tagline'); await tid(w, 'cnn-text').setValue('Quiet releases.'); await tid(w, 'cnn-problem').setValue('Because we like them.')
    await tid(w, 'cnn-form').trigger('submit'); await flushPromises()
    expect(h.propose).toHaveBeenCalledWith({ code_distribution: 'lyceum', kind: 'console_text', target: 'landing.tagline', title: 'Quiet releases', problem: 'Because we like them.', content: { text: 'Quiet releases.' } })
    expect(h.push).toHaveBeenCalledWith({ name: 'contributions', query: { line: 'lyceum' } })
  })
  it('a branding change has no target field', async () => {
    const w = await mountIt()
    await tid(w, 'cnn-kind').setValue('branding')
    expect(tid(w, 'cnn-target').exists()).toBe(false)
    expect(tid(w, 'cnn-accent').exists()).toBe(true)
  })
  it('shows our checker\'s refusal with its reasons and stays on the page', async () => {
    h.propose.mockRejectedValue({ response: { data: { code: 'checker_refused', detail: 'a secret is written out at text (secret)', reasons: ['a secret is written out at text (secret)', 'second reason'] } } })
    const w = await mountIt()
    await tid(w, 'cnn-target').setValue('landing.tagline'); await tid(w, 'cnn-text').setValue('x'); await tid(w, 'cnn-problem').setValue('y')
    await tid(w, 'cnn-form').trigger('submit'); await flushPromises()
    expect(tid(w, 'cnn-refusal').text()).toContain('a secret is written out'); expect(tid(w, 'cnn-refusal').text()).toContain('second reason')
    expect(h.push).not.toHaveBeenCalled()
  })
  it('without an agent the submit is disabled and says why', async () => {
    h.auth = { isAuthenticated: true, activeAgent: null }
    const w = await mountIt()
    expect(tid(w, 'cnn-submit').attributes('disabled')).toBeDefined(); expect(tid(w, 'cnn-signin').exists()).toBe(true)
  })
  it('on a registry that does not govern code shows the sentence in place of the form', async () => {
    h.authority = OTHER
    const w = await mountIt()
    expect(tid(w, 'cc-governed-sentence').text()).toBe(OTHER.sentence)
    expect(tid(w, 'cnn-form').exists()).toBe(false)
  })
})

describe('the content change proposal from a room', () => {
  it('names the room it came from, and sends it, so the change is announced there', async () => {
    h.query = { line: 'lyceum', title: 'Quiet releases', room: 'room-1' }
    h.propose.mockResolvedValue({ id: 'ct_1' })
    const w = await mountIt()
    expect(tid(w, 'cnn-room').exists()).toBe(true)
    await tid(w, 'cnn-target').setValue('landing.tagline'); await tid(w, 'cnn-text').setValue('Quiet releases.'); await tid(w, 'cnn-problem').setValue('Because.')
    await tid(w, 'cnn-form').trigger('submit'); await flushPromises()
    expect(h.propose).toHaveBeenCalledWith(expect.objectContaining({ room_id: 'room-1', code_distribution: 'lyceum' }))
  })
  it('sends no room when it did not come from one', async () => {
    h.propose.mockResolvedValue({ id: 'ct_1' })
    const w = await mountIt()
    expect(tid(w, 'cnn-room').exists()).toBe(false)
    await tid(w, 'cnn-target').setValue('landing.tagline'); await tid(w, 'cnn-text').setValue('x'); await tid(w, 'cnn-problem').setValue('y')
    await tid(w, 'cnn-form').trigger('submit'); await flushPromises()
    expect(h.propose.mock.calls[0][0]).not.toHaveProperty('room_id')
  })
})

describe('V0667 D7: the compliance pack form', () => {
  it('says in one sentence that a pack is the organization\'s own declaration and that no rail enforces it, only for that kind', async () => {
    const w = await mountIt()
    expect(tid(w, 'cnn-pack-note').exists()).toBe(false)
    await tid(w, 'cnn-kind').setValue('compliance_pack')
    expect(tid(w, 'cnn-pack-note').text()).toBe('A pack records the organization’s own policy values: stored, voted on and carried in the signed report. No rail enforces it in this release.')
    expect(tid(w, 'cnn-rules').exists()).toBe(true)
  })
  it('sends the pack\'s rules as the content, with a neutral name', async () => {
    h.propose.mockResolvedValue({ id: 'ct_1' })
    const w = await mountIt()
    await tid(w, 'cnn-kind').setValue('compliance_pack')
    await tid(w, 'cnn-target').setValue('eu-retention'); await tid(w, 'cnn-rules').setValue('{"retention":{"audit_log_days":2555}}'); await tid(w, 'cnn-problem').setValue('Our retention.')
    await tid(w, 'cnn-form').trigger('submit'); await flushPromises()
    expect(h.propose).toHaveBeenCalledWith(expect.objectContaining({ kind: 'compliance_pack', target: 'eu-retention', content: { rules: { retention: { audit_log_days: 2555 } } } }))
  })
})
