/**
 * V0667 the developer passport, step 1 (order gwo_fb84e57318de0802725ab511; session-lead seq 5361: "on the Code changes view beside the governing sentence, as
 * the repository-account button is"; seq 5367: the press links the repository account too). On a registry that does not govern code:
 *
 *   - nothing while the state is unknown, where this registry governs code, or when the read fails (a visitor, a refusal)
 *   - not taking part: one button, "Take part on <governing>". Mounting or opening it changes nothing; the press shows EXACTLY the card the governing registry
 *     would receive (every field of the registry's own preview), says what it never receives and that votes stay with its members, and only "Take part"
 *     sets the consent
 *   - with no agent to act through, the panel says so and offers no consent
 *   - taking part: says from where to where, "Stop taking part" takes it back, and the repository account reads and links THROUGH the passport (the
 *     existing link component with the passport's own link call)
 *   - a refusal is the registry's sentence, and nothing changes on screen
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ get: null as any, set: null as any, repo: null as any, link: null as any }))
vi.mock('@/services/api/codePassport', () => ({
  getPassport: (...a: any[]) => h.get(...a), setPassport: (...a: any[]) => h.set(...a),
  getPassportRepo: (...a: any[]) => h.repo(...a), linkPassportRepo: (...a: any[]) => h.link(...a),
}))

import CodePassportPress from './CodePassportPress.vue'

const CARD = { schema: 'devcard/0.1', purpose: 'code_governance', developer_ref: '42', display_name: 'Ada', home_registry: 'ASIA', standing: 'active',
  agent_did: 'did:theprotocol:asia:abc', issued_at: '2026-11-16T12:00:00+00:00' }
const state = (over: Record<string, any> = {}) => ({ governing: 'EU', self_governing: false, available: true, home: 'ASIA', consented: false, consented_at: null, preview: CARD,
  votes: 'members_only', ...over })
const REPO = { enabled: true, host: 'https://code.theprotocol.cloud', linked: false, username: null, state: null, shares: ['one'], pending: null, terms_version: '2.5' }
const LinkStub = { name: 'RepoAccountLink', props: ['status', 'link'], template: '<div data-testid="stub-repo" />' }
const mountIt = () => mount(CodePassportPress, { global: { stubs: { Icon: true, RepoAccountLink: LinkStub } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the passport press', () => {
  beforeEach(() => {
    h.get = vi.fn(async () => state()); h.set = vi.fn(async (on: boolean) => state({ consented: on, consented_at: on ? '2026-11-16T12:01:00+00:00' : null }))
    h.repo = vi.fn(async () => REPO); h.link = vi.fn()
  })

  it('shows nothing where this registry governs code, or when the state cannot be read', async () => {
    h.get = vi.fn(async () => state({ self_governing: true, available: false }))   // the registry answers both from one rule
    let n = mountIt(); await flushPromises()
    expect(tid(n, 'cp-root').exists()).toBe(false)
    h.get = vi.fn(async () => state({ available: false }))                // no registry governs code: no passport anywhere
    let w = mountIt(); await flushPromises()
    expect(tid(w, 'cp-root').exists()).toBe(false)
    h.get = vi.fn(async () => { throw Object.assign(new Error('401'), { response: { status: 401 } }) })
    w = mountIt(); await flushPromises()
    expect(tid(w, 'cp-root').exists()).toBe(false)
  })

  it('not taking part: one button; opening changes nothing; the press shows the whole card, what is never sent, and that votes stay with the members', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'cp-open').text()).toBe('Take part on EU')
    expect(tid(w, 'cp-panel').exists()).toBe(false)
    await tid(w, 'cp-open').trigger('click')
    expect(h.set).not.toHaveBeenCalled()
    const card = tid(w, 'cp-card').text()
    for (const v of ['Ada', '42', 'ASIA', 'active', 'did:theprotocol:asia:abc']) expect(card).toContain(v)
    const panel = tid(w, 'cp-panel').text()
    expect(panel).toContain('never your e-mail address')
    expect(panel).toContain("votes stay with EU's members")
    expect(h.repo).not.toHaveBeenCalled()
    await tid(w, 'cp-confirm').trigger('click'); await flushPromises()
    expect(h.set).toHaveBeenCalledWith(true)
    expect(tid(w, 'cp-taking-part').text()).toContain('You take part on EU from ASIA')
  })

  it('with no agent to act through, the panel says so and offers no consent', async () => {
    h.get = vi.fn(async () => state({ preview: null }))
    const w = mountIt(); await flushPromises()
    await tid(w, 'cp-open').trigger('click')
    expect(tid(w, 'cp-no-agent').exists()).toBe(true)
    expect(tid(w, 'cp-confirm').exists()).toBe(false)
  })

  it('taking part: stop takes it back, and the repository account reads and links through the passport', async () => {
    h.get = vi.fn(async () => state({ consented: true, consented_at: '2026-11-16T12:01:00+00:00' }))
    const w = mountIt(); await flushPromises()
    expect(h.repo).toHaveBeenCalledTimes(1)
    const stub = w.findComponent(LinkStub)
    expect(stub.props('status')).toEqual(REPO)
    await stub.props('link')('ada-asia', '2.5')
    expect(h.link).toHaveBeenCalledWith('ada-asia', '2.5')
    await tid(w, 'cp-stop').trigger('click'); await flushPromises()
    expect(h.set).toHaveBeenCalledWith(false)
    expect(tid(w, 'cp-open').exists()).toBe(true)
  })

  it('a refusal is the registry\'s sentence and changes nothing', async () => {
    h.set = vi.fn(async () => { throw Object.assign(new Error('x'), { response: { status: 403, data: { code: 'no_agent', detail: 'create an agent first' } } }) })
    const w = mountIt(); await flushPromises()
    await tid(w, 'cp-open').trigger('click')
    await tid(w, 'cp-confirm').trigger('click'); await flushPromises()
    expect(tid(w, 'cp-error').text()).toContain('create an agent first')
    expect(tid(w, 'cp-taking-part').exists()).toBe(false)
  })
})
