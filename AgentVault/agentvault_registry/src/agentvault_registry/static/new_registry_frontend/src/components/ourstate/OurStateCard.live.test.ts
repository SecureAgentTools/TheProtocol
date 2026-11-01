import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import OurStateCard from './OurStateCard.vue'

/**
 * V0652 (aa) (order gwo_840aa2b590306f7eba147758): the cards that live, drawn. A progress card shows its state, its
 * steps (each by its shape and its word) and how far it is; a Guild order card its status, bounty, worker and the
 * stages it reached, with the door to the order; an approval card the act it opened; any card updated in place says so,
 * with a History button. BASE (V0651): the three types render as "Unsupported card", and no card says it changed.
 */
const opts = { global: { stubs: { Icon: true, OurStateIdentity: true } } }

describe('a progress card', () => {
  it('its state, its steps by shape and word, and the count', () => {
    const w = mount(OurStateCard, { props: { card: { v: 1, type: 'progress', data: { title: 'V0651 pair proof', state: 'running',
      note: 'federation suite next', steps: [{ label: 'console', state: 'done' }, { label: 'pair', state: 'running' },
        { label: 'federation', state: 'pending' }, { label: 'MCP', state: 'skipped', note: 'not in this proof' }] } } }, ...opts })
    expect(w.find('[data-testid="osc-progress-running"]').text()).toContain('In progress')
    expect(w.find('[data-testid="osc-progress-count"]').text()).toContain('2 of 4 steps')
    expect([0, 1, 2, 3].map((i) => w.find(`[data-testid="osc-step-${i}"]`).attributes('data-state')))
      .toEqual(['done', 'running', 'pending', 'skipped'])
    expect(w.find('[data-testid="osc-step-1"]').text()).toContain('running')
    expect(w.find('[data-testid="osc-step-3"]').text()).toContain('not in this proof')
    expect(w.text()).toContain('federation suite next')
    expect(w.find('[data-testid="osc-unknown"]').exists()).toBe(false)
  })

  it('a verdict reads as the verdict', () => {
    const w = mount(OurStateCard, { props: { card: { v: 1, type: 'progress', data: { title: 'Roll', state: 'failed' } } }, ...opts })
    expect(w.find('[data-testid="osc-progress-failed"]').text()).toContain('Failed')
    expect(w.find('[data-testid="osc-progress-count"]').exists()).toBe(false)    // no steps, no count
  })
})

describe('a Guild order card', () => {
  const card = (status: string, events: string[], extra: Record<string, unknown> = {}) => ({ v: 1, type: 'guild.order.live',
    refs: { order_id: 'gwo_1' }, data: { order_id: 'gwo_1', title: 'Build (ad)', status, bounty: '15', currency: 'ECU', bids: 1,
      poster_name: 'session-lead', events: events.map((type) => ({ type, at: '2026-10-31T18:07:00Z' })), ...extra } })

  it('its status, bounty, poster, the stages reached, and the door to the order', async () => {
    const w = mount(OurStateCard, { props: { card: card('awarded', ['posted', 'bid', 'awarded'],
      { worker_did: 'did:x:w', worker_name: 'session-release' }) }, ...opts })
    expect(w.find('[data-testid="osc-guild-status"]').text()).toContain('awarded')
    expect(w.text()).toContain('15 ECU')
    expect(w.text()).toContain('posted by session-lead')
    expect(w.find('[data-testid="osc-guild-worker"]').text()).toContain('session-release')
    expect(['posted', 'bid', 'awarded', 'submitted', 'settled'].map((s) =>
      w.find(`[data-testid="osc-stage-${s}"]`).classes().includes('on'))).toEqual([true, true, true, false, false])
    await w.find('[data-testid="osc-guild-open"]').trigger('click')
    expect(w.emitted('open-work')).toEqual([[{ kind: 'guild.order', ref: 'gwo_1' }]])
  })

  it('settled reads as settled, every stage lit', () => {
    const w = mount(OurStateCard, { props: { card: card('settled', ['posted', 'bid', 'awarded', 'submitted', 'settled']) }, ...opts })
    expect(w.find('[data-testid="osc-guild-status"]').attributes('data-status')).toBe('settled')
    expect(w.findAll('.osc-stage.on')).toHaveLength(5)
  })
})

describe("an approval's use and a card that changed", () => {
  it('the approval card says what it opened', () => {
    const w = mount(OurStateCard, { props: { card: { v: 1, type: 'approval.decided', data: { approval_id: 'apr_1',
      decision: 'approved', title: 'Roll V0651', decided_by_developer_id: 6, decided_by_name: 'maintainer', role: 'owner',
      used: { act: 'run_prod651.sh', act_sha256: 'ab'.repeat(32), at: '2026-11-01T05:00:00Z' } } } }, ...opts })
    expect(w.find('[data-testid="osc-approval-used"]').text()).toContain('Used for run_prod651.sh')
  })

  it('an approval not used says nothing about a use', () => {
    const w = mount(OurStateCard, { props: { card: { v: 1, type: 'approval.decided', data: { approval_id: 'apr_1',
      decision: 'approved', title: 'Roll V0651', decided_by_developer_id: 6 } } }, ...opts })
    expect(w.find('[data-testid="osc-approval-used"]').exists()).toBe(false)
  })

  it('a card updated in place says how often, and History asks for its history', async () => {
    const card = { v: 1, type: 'progress', data: { title: 'Roll', state: 'running' } }
    const w = mount(OurStateCard, { props: { card, rev: 3, updatedAt: '2026-11-01T01:05:00Z' }, ...opts })
    expect(w.find('[data-testid="osc-live"]').text()).toContain('Updated 3 times')
    await w.find('[data-testid="osc-history"]').trigger('click')
    expect(w.emitted('history')).toHaveLength(1)
    const once = mount(OurStateCard, { props: { card, rev: 1, updatedAt: '2026-11-01T01:05:00Z' }, ...opts })
    expect(once.find('[data-testid="osc-live"]').text()).toContain('Updated once')
    const posted = mount(OurStateCard, { props: { card }, ...opts })
    expect(posted.find('[data-testid="osc-live"]').exists()).toBe(false)      // as posted: no line
  })
})
