/**
 * V0657 (a), disputes v2: the ruling screen.
 *  - RulingPanel: the three rulings (the console offered two, item 6), the ruler's reason (item 5), a Guild order's
 *    split, and what the ruling does BEFORE the click, read from the server's preview (item 7): who gets what, each
 *    reputation change, the enforcement step; confirm only with a ruling, a reason and a preview that answered.
 *  - DisputeEvidence: the order as evidence (item 8): linked, "nothing was handed in" when nothing was, the deadline.
 *  - CorrectionPanel: the correction rail, its preview, why required.
 *  - RulerQueue: one queue, and a record for a disputed order that has none (item 3).
 * RED on origin/v0656/cut: none of these components exist.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  previewRuling: vi.fn(), previewCorrection: vi.fn(), correctRuling: vi.fn(), rulerQueue: vi.fn(), fileQueueRecord: vi.fn(),
  updateRuling: vi.fn(),
}))
vi.mock('@/services/api/disputes', async (orig) => ({
  ...(await orig<Record<string, unknown>>()),
  disputesApi: { previewRuling: h.previewRuling, previewCorrection: h.previewCorrection, correctRuling: h.correctRuling,
    rulerQueue: h.rulerQueue, fileQueueRecord: h.fileQueueRecord },
}))
vi.mock('@/stores/disputes', () => ({ useDisputesStore: () => ({ updateRuling: h.updateRuling }) }))

import RulingPanel from './RulingPanel.vue'
import DisputeEvidence from './DisputeEvidence.vue'
import CorrectionPanel from './CorrectionPanel.vue'
import RulerQueue from './RulerQueue.vue'

const POSTER = 'did:theprotocol:eu.theprotocol.cloud:8db7b75e-6d87-4a1e-b530-42effe5787ab'
const WORKER = 'did:theprotocol:eu.theprotocol.cloud:0fc15206-ca13-4257-884f-656866dd1bb1'
const dispute = (over: Record<string, any> = {}) => ({
  id: '12', status: 'open', claimant_did: POSTER, respondent_did: WORKER, claimant_name: 'session-lead',
  respondent_name: 'session-tester', reason: 'x', description: 'x', evidence: [], created_at: 'now', updated_at: 'now',
  guild_order_id: 'gwo_x', ...over,
}) as any
const guildPreview = {
  dispute_id: 12, ruling: 'IN_FAVOR_OF_COMPLAINANT', ruling_words: 'in favour of the complainant',
  money: { kind: 'guild_split', moves: true, escrow: '25', worker_gets: '0', poster_gets: '25', currency: 'ECU', handed_in: false,
    stake: { amount: '5', goes_to: 'the poster (slashed)' } },
  reputation: [{ did: WORKER, name: 'session-tester', change: -10, why: 'missed the deadline (the ruling)' }],
  enforcement: { agent_did: WORKER, agent_name: 'session-tester', offense_count_before: 0, escalation_level: 1, action: 'warn' },
}
const stubs = { RouterLink: { template: '<a :data-to="JSON.stringify(to)"><slot /></a>', props: ['to'] } }

describe('RulingPanel', () => {
  beforeEach(() => { setActivePinia(createPinia()); Object.values(h).forEach((f) => f.mockReset()) })

  it('offers the three rulings, by the parties\' names', () => {
    const w = mount(RulingPanel, { props: { dispute: dispute() } })
    const choices = w.findAll('[data-ruling]')
    expect(choices.map((c) => c.attributes('data-ruling'))).toEqual(['IN_FAVOR_OF_COMPLAINANT', 'IN_FAVOR_OF_DEFENDANT', 'DISMISSED'])
    expect(choices[0].text()).toContain('session-lead')
    expect(choices[1].text()).toContain('session-tester')
  })

  it('shows what the ruling does before the click, and confirms only with a reason', async () => {
    h.previewRuling.mockResolvedValue(guildPreview)
    h.updateRuling.mockResolvedValue({ dispute: dispute({ status: 'resolved' }) })
    const w = mount(RulingPanel, { props: { dispute: dispute() } })
    await w.find('[data-ruling="IN_FAVOR_OF_COMPLAINANT"] input').setValue(true)
    await flushPromises()
    expect(h.previewRuling).toHaveBeenCalledWith('12', 'IN_FAVOR_OF_COMPLAINANT', null)
    expect(w.find('[data-testid="ruling-money"]').text()).toContain('the poster gets 25')
    expect(w.find('[data-testid="ruling-money"]').text()).toContain('Nothing was handed in')
    expect(w.find('[data-testid="ruling-reputation"]').text()).toContain('session-tester: -10')
    expect(w.find('[data-testid="ruling-enforcement"]').text()).toContain('level 1, warn')
    const confirm = w.find('[data-testid="ruling-confirm"]')
    expect(confirm.attributes('disabled'), 'no reason yet').toBeDefined()
    await w.find('[data-testid="ruling-note"]').setValue('The deadline passed with nothing handed in.')
    expect(confirm.attributes('disabled')).toBeUndefined()
    await confirm.trigger('click')
    await flushPromises()
    expect(h.updateRuling).toHaveBeenCalledWith('12', 'IN_FAVOR_OF_COMPLAINANT', 'The deadline passed with nothing handed in.', null)
    expect(w.emitted('done')).toBeTruthy()
  })

  it('the ruler\'s split goes to the preview and to the ruling', async () => {
    h.previewRuling.mockResolvedValue(guildPreview)
    h.updateRuling.mockResolvedValue({})
    const w = mount(RulingPanel, { props: { dispute: dispute() } })
    await w.find('[data-ruling="DISMISSED"] input').setValue(true)
    await w.find('[data-testid="ruling-split-on"]').setValue(true)
    await w.find('[data-testid="ruling-split"]').setValue('40')
    await flushPromises()
    expect(h.previewRuling).toHaveBeenLastCalledWith('12', 'DISMISSED', 0.4)
    await w.find('[data-testid="ruling-note"]').setValue('Half the work was done.')
    await w.find('[data-testid="ruling-confirm"]').trigger('click')
    await flushPromises()
    expect(h.updateRuling).toHaveBeenCalledWith('12', 'DISMISSED', 'Half the work was done.', 0.4)
  })

  it('a dispute about no order offers no split, and a preview that failed rules nothing', async () => {
    h.previewRuling.mockRejectedValue({ response: { data: { detail: 'Dispute 12 is already ruled' } } })
    const w = mount(RulingPanel, { props: { dispute: dispute({ guild_order_id: null }) } })
    expect(w.find('[data-testid="ruling-split-on"]').exists()).toBe(false)
    await w.find('[data-ruling="IN_FAVOR_OF_DEFENDANT"] input').setValue(true)
    await w.find('[data-testid="ruling-note"]').setValue('Reason enough.')
    await flushPromises()
    expect(w.find('[data-testid="ruling-preview"]').attributes('data-state')).toBe('failed')
    expect(w.find('[data-testid="ruling-confirm"]').attributes('disabled')).toBeDefined()
  })
})

describe('DisputeEvidence', () => {
  it('links the order and says nothing was handed in', () => {
    const w = mount(DisputeEvidence, { global: { stubs }, props: { dispute: dispute({ guild_order: {
      id: 'gwo_x', title: 'Fix the board', status: 'disputed', bounty: '25', currency: 'ECU', escrow_held: '25',
      deadline: '2026-11-05T17:00:00Z', handed_in: false, spec: 'Make it pass.', events: [{ seq: 1, event_type: 'posted' }] } }) } })
    expect(w.find('[data-testid="dispute-order-link"]').attributes('data-to')).toContain('"order":"gwo_x"')
    expect(w.find('[data-testid="dispute-handin"]').text()).toBe('Nothing was handed in.')
    expect(w.text()).toContain('Make it pass.')
  })

  it('a contract dispute has its link (contract_ref)', () => {
    const w = mount(DisputeEvidence, { global: { stubs }, props: { dispute: dispute({ guild_order_id: null, contract_ref: 'ctr_abc' }) } })
    expect(w.find('[data-testid="dispute-contract-link"]').attributes('data-to')).toContain('ctr_abc')
  })
})

describe('CorrectionPanel', () => {
  beforeEach(() => { setActivePinia(createPinia()); Object.values(h).forEach((f) => f.mockReset()) })

  it('offers the other rulings, previews the correction and needs a reason', async () => {
    h.previewCorrection.mockResolvedValue({ from_ruling: 'IN_FAVOR_OF_COMPLAINANT', to_ruling: 'IN_FAVOR_OF_DEFENDANT',
      reverse_reputation: [{ did: WORKER, change: -10 }], reverse_enforcement: [{ action_id: 'ea_1', agent_did: WORKER, action: 'warn' }],
      apply_reputation: [{ did: WORKER, change: 2, why: 'the ruling went its way' }], money: 'none' })
    h.correctRuling.mockResolvedValue({ ok: true })
    const d = dispute({ status: 'resolved', ruling: 'IN_FAVOR_OF_COMPLAINANT', parties: {
      complainant: { did: POSTER, name: 'session-lead' }, defendant: { did: WORKER, name: 'session-tester' } } })
    const w = mount(CorrectionPanel, { props: { dispute: d } })
    expect(w.findAll('[data-ruling]').map((c) => c.attributes('data-ruling'))).toEqual(['IN_FAVOR_OF_DEFENDANT', 'DISMISSED'])
    await w.find('[data-ruling="IN_FAVOR_OF_DEFENDANT"] input').setValue(true)
    await flushPromises()
    const text = w.find('[data-testid="correction-preview"]').text()
    expect(text).toContain('session-tester: +10 reputation given back')
    expect(text).toContain('the warn is reversed')
    expect(text).toContain('moves no money')
    const confirm = w.find('[data-testid="correction-confirm"]')
    await w.find('[data-testid="correction-note"]').setValue('too short')
    expect(confirm.attributes('disabled')).toBeDefined()
    await w.find('[data-testid="correction-note"]').setValue('It delivered and was paid.')
    await confirm.trigger('click')
    await flushPromises()
    expect(h.correctRuling).toHaveBeenCalledWith('12', 'IN_FAVOR_OF_DEFENDANT', 'It delivered and was paid.')
  })
})

describe('RulerQueue', () => {
  beforeEach(() => { setActivePinia(createPinia()); Object.values(h).forEach((f) => f.mockReset()) })

  it('lists every kind, and gives an order without a record its record', async () => {
    h.rulerQueue.mockResolvedValue({ items: [
      { kind: 'dispute', id: 1, dispute_id: 1, title: 'Fix the board', reason_text: 'The worker handed nothing in by the deadline',
        complainant_did: POSTER, complainant_name: 'session-lead', defendant_did: WORKER, defendant_name: 'session-tester',
        at_stake: { amount: '25', currency: 'ECU', what: 'the order\'s escrow' } },
      { kind: 'guild', id: 'gwo_orphan', dispute_id: null, title: 'Lost record', reason_text: 'No open dispute record' },
    ] })
    h.fileQueueRecord.mockResolvedValue({ dispute_id: 31 })
    const w = mount(RulerQueue)
    await flushPromises()
    const rows = w.findAll('[data-testid="ruler-queue-row"]')
    expect(rows.map((r) => r.attributes('data-kind'))).toEqual(['dispute', 'guild'])
    expect(rows[0].text()).toContain('session-tester')
    await w.find('[data-testid="ruler-queue-open"]').trigger('click')
    expect(w.emitted('open')![0]).toEqual([1])
    await w.find('[data-testid="ruler-queue-file"]').trigger('click')
    await flushPromises()
    expect(h.fileQueueRecord).toHaveBeenCalledWith('guild', 'gwo_orphan')
    expect(w.emitted('open')![1]).toEqual([31])
  })
})
