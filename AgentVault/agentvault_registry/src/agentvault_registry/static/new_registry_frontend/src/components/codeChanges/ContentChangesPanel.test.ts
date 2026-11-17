/**
 * V0667 D5 (order gwo_d238dcda72add8e05b6d657b): the content changes beside a release line's code changes. The panel lists the line's content changes with our checker's record, the ballot and the applied
 * before and after; a decider votes through an agent (never without one), the deciders undo in one step, the proposer withdraws; a refusal is the registry's sentence where it was asked.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ items: [] as any[], vote: vi.fn(), undo: vi.fn(), withdraw: vi.fn(), listFails: false, record: vi.fn(), download: vi.fn() }))
vi.mock('@/services/api/distributionReports', () => ({ getRecord: (...a: any[]) => h.record(...a), getReport: vi.fn() }))
vi.mock('@/services/contentChanges/download', () => ({ downloadSigned: (...a: any[]) => h.download(...a), fileNameOf: () => 'x' }))
vi.mock('@/services/api/contentChanges', async () => ({
  ...(await vi.importActual<any>('@/services/api/contentChanges')),
  listContentChanges: async () => { if (h.listFails) throw new Error('down'); return h.items },
  voteContentChange: (...a: any[]) => h.vote(...a),
  undoContentChange: (...a: any[]) => h.undo(...a),
  withdrawContentChange: (...a: any[]) => h.withdraw(...a),
}))

import Panel from './ContentChangesPanel.vue'

const stubs = { RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } }
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const ROW = (over: any = {}) => ({ id: 'ct_1', kind: 'console_text', target: 'landing.tagline', title: 'A tagline', state: 'balloting', content: { text: 'Hi' }, checker: { ok: true, rules: ['schema'], bytes: 10 },
  ballot: { cast: 0, deciders: 2, ends: '2026-11-23T10:00:00+00:00', result: null, my_vote: null, can_vote: false }, can_undo: false, proposer_developer_id: 7, before: null, after: null, ...over })
const mountIt = async (props: any = {}) => { const w = mount(Panel, { props: { lineSlug: 'lyceum', me: 7, agentDid: 'did:a:me', canPropose: true, paused: false, ...props }, global: { stubs } }); await flushPromises(); return w }

beforeEach(() => { h.items = []; h.listFails = false; h.vote.mockReset(); h.undo.mockReset(); h.withdraw.mockReset(); h.record.mockReset(); h.download.mockReset() })

describe('the content changes panel', () => {
  it('says there is none yet, and offers the proposal to a member', async () => {
    const w = await mountIt()
    expect(tid(w, 'cnt-none').exists()).toBe(true)
    expect(JSON.parse(tid(w, 'cnt-propose').attributes('data-to')!)).toEqual({ name: 'content-changes-new', query: { line: 'lyceum' } })
  })
  it('offers no proposal on a paused line or to a non-member', async () => {
    expect(tid(await mountIt({ paused: true }), 'cnt-propose').exists()).toBe(false)
    expect(tid(await mountIt({ canPropose: false }), 'cnt-propose').exists()).toBe(false)
  })
  it('shows a change with its kind, state, summary, checker record and ballot', async () => {
    h.items = [ROW()]
    const w = await mountIt()
    const c = tid(w, 'cnt-ct_1')
    expect(c.text()).toContain('Console text'); expect(c.text()).toContain('In its ballot'); expect(c.text()).toContain('A tagline')
    expect(tid(w, 'cnt-summary').text()).toBe('The console text landing.tagline: Hi')
    expect(tid(w, 'cnt-checker').text()).toBe('Our checker passed it: schema (10 bytes).')
    expect(tid(w, 'cnt-ballot').text()).toContain('0 of 2 deciders have voted')
  })
  it('shows the applied before and after, and the undo to those who may', async () => {
    h.items = [ROW({ state: 'applied', before: { value: 'old' }, after: { value: 'Hi' }, can_undo: true })]
    const w = await mountIt()
    expect(tid(w, 'cnt-diff').text()).toContain('old'); expect(tid(w, 'cnt-diff').text()).toContain('Hi')
    expect(tid(w, 'cnt-undo').exists()).toBe(true)
  })
  it('a decider votes through the selected agent, after a confirmation; never changing a vote', async () => {
    h.items = [ROW({ ballot: { ...ROW().ballot, can_vote: true } })]
    h.vote.mockResolvedValue(ROW({ ballot: { ...ROW().ballot, cast: 1, my_vote: 'FOR', can_vote: false } }))
    const w = await mountIt()
    await tid(w, 'cnt-vote-for').trigger('click')
    await tid(w, 'cnt-vote-confirm').trigger('click'); await flushPromises()
    expect(h.vote).toHaveBeenCalledWith('ct_1', true)
    expect(tid(w, 'cnt-voted').exists()).toBe(true); expect(tid(w, 'cnt-vote').exists()).toBe(false)
  })
  it('asks for an agent first when none is chosen', async () => {
    h.items = [ROW({ ballot: { ...ROW().ballot, can_vote: true } })]
    const w = await mountIt({ agentDid: '' })
    expect(tid(w, 'cnt-vote-agent').exists()).toBe(true); expect(tid(w, 'cnt-vote-for').exists()).toBe(false)
  })
  it('undoes in one step after a confirmation, and shows the registry\'s sentence when it refuses', async () => {
    h.items = [ROW({ state: 'applied', before: { value: null }, after: { value: 'Hi' }, can_undo: true })]
    h.undo.mockRejectedValue({ response: { data: { code: 'changed_since', detail: 'the content has been changed by something else since this change: it is not overwritten' } } })
    const w = await mountIt()
    await tid(w, 'cnt-undo').trigger('click'); await tid(w, 'cnt-undo-confirm').trigger('click'); await flushPromises()
    expect(h.undo).toHaveBeenCalledWith('ct_1', '')
    expect(tid(w, 'cnt-refusal-ct_1').text()).toContain('it is not overwritten')
  })
  it('the proposer withdraws while it is in its ballot, nobody else sees the button', async () => {
    h.items = [ROW()]
    h.withdraw.mockResolvedValue(ROW({ state: 'withdrawn' }))
    const w = await mountIt()
    await tid(w, 'cnt-withdraw').trigger('click'); await flushPromises()
    expect(h.withdraw).toHaveBeenCalledWith('ct_1', '')
    expect(tid(await mountIt({ me: 9 }), 'cnt-withdraw').exists()).toBe(false)
  })
  it('says so, with a way to try again, when the list cannot be read', async () => {
    h.listFails = true
    const w = await mountIt()
    expect(tid(w, 'cnt-error').exists()).toBe(true)
  })

  it('V0667 D7: downloads the change\'s signed record, and shows the registry\'s sentence when it refuses', async () => {
    h.items = [ROW()]
    h.record.mockResolvedValue({ kind: 'distribution.change.record', subject: 'ct_1' })
    const w = await mountIt()
    await tid(w, 'cnt-record').trigger('click'); await flushPromises()
    expect(h.record).toHaveBeenCalledWith('lyceum', 'ct_1'); expect(h.download).toHaveBeenCalledWith({ kind: 'distribution.change.record', subject: 'ct_1' })
    h.record.mockRejectedValue({ response: { data: { detail: 'no change of that id on this release line' } } })
    await tid(w, 'cnt-record').trigger('click'); await flushPromises()
    expect(tid(w, 'cnt-refusal-ct_1').text()).toContain('no change of that id')
  })

  it('V0667 D7: a compliance pack says it is the organization\'s own declaration, no other kind does', async () => {
    h.items = [ROW({ id: 'ct_p', kind: 'compliance_pack', target: 'eu-retention', content: { rules: { retention: { audit_log_days: 2555 } } } }), ROW()]
    const w = await mountIt()
    expect(tid(w, 'cnt-ct_p').find('[data-testid="cnt-pack-note"]').text()).toBe('A pack records the organization’s own policy values: stored, voted on and carried in the signed report. No rail enforces it in this release.')
    expect(tid(w, 'cnt-ct_1').find('[data-testid="cnt-pack-note"]').exists()).toBe(false)
  })
})
