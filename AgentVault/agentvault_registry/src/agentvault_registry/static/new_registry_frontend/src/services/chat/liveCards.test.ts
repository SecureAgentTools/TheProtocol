import { describe, it, expect } from 'vitest'
import { applyCardUpdate, applyCardUpdates, guildStages, stepTotals } from './liveCards'
import { mergeBySeq } from './catchUp'
import { cardView } from './cards'

/**
 * V0652 (aa) (order gwo_840aa2b590306f7eba147758): cards that live, the console's rules. An update applies by its rev
 * (a newer one replaces the card, an older or equal one changes nothing, so one arriving twice or late never moves a
 * card back); a catch-up read carries a held card's newer rev; the card views read the progress card, the Guild order
 * card and an approval's use. BASE (V0651): liveCards.ts does not exist, mergeBySeq ignores a held message's card.
 */
const msg = (id: string, seq: number, card: any = null, rev = 0) => ({ id, seq, kind: card ? 'card' : 'text', card, card_rev: rev,
  card_updated_at: rev ? '2026-11-01T01:00:00Z' : null })
const running = { v: 1, type: 'progress', data: { title: 'V0651 pair proof', state: 'running' } }
const passed = { v: 1, type: 'progress', data: { title: 'V0651 pair proof', state: 'passed' } }

describe('an update applies by its rev', () => {
  it('a newer rev replaces the card in place: same message, same place', () => {
    const have = [msg('m1', 1), msg('m2', 2, running), msg('m3', 3)]
    const r = applyCardUpdate(have, { id: 'm2', card: passed, card_rev: 1, card_updated_at: '2026-11-01T01:02:00Z' })
    expect(r.changed).toBe(true)
    expect(r.messages.map((m) => m.id)).toEqual(['m1', 'm2', 'm3'])
    expect(r.messages[1].card.data.state).toBe('passed')
    expect(r.messages[1].card_rev).toBe(1)
    expect(r.messages[1].card_updated_at).toBe('2026-11-01T01:02:00Z')
    expect(have[1].card.data.state).toBe('running')                 // the old array is not edited
  })

  it('an older or equal rev, an unknown message and nothing change nothing', () => {
    const have = [msg('m2', 2, passed, 3)]
    expect(applyCardUpdate(have, { id: 'm2', card: running, card_rev: 2 }).changed).toBe(false)
    expect(applyCardUpdate(have, { id: 'm2', card: running, card_rev: 3 }).changed).toBe(false)
    expect(applyCardUpdate(have, { id: 'm9', card: running, card_rev: 9 }).changed).toBe(false)
    expect(applyCardUpdate(have, null).changed).toBe(false)
  })

  it('a list of updates, in order: each counted once', () => {
    const have = [msg('a', 1, running), msg('b', 2, running)]
    const r = applyCardUpdates(have, [{ id: 'a', card: passed, card_rev: 1 }, { id: 'a', card: running, card_rev: 1 },
      { id: 'b', card: passed, card_rev: 2 }])
    expect(r.changed).toBe(2)
    expect(r.messages.map((m) => [m.card.data.state, m.card_rev])).toEqual([['passed', 1], ['passed', 2]])
  })

  it('a catch-up read carries a held card\'s newer rev, and a stale read does not', () => {
    const have = [msg('m1', 1), msg('m2', 2, running, 1)]
    const r = mergeBySeq(have, [msg('m2', 2, passed, 2), msg('m3', 3)])
    expect(r.added).toBe(1)
    expect(r.updated).toBe(1)
    expect(r.messages[1].card.data.state).toBe('passed')
    const stale = mergeBySeq(r.messages, [msg('m2', 2, running, 1)])
    expect(stale.updated).toBe(0)
    expect(stale.messages[1].card.data.state).toBe('passed')
  })
})

describe('the card views', () => {
  it('a progress card: its state, steps and note (an unknown state reads as running, never as a verdict)', () => {
    const v: any = cardView({ v: 1, type: 'progress', data: { title: 'Roll', state: 'failed', note: 'ASIA red',
      steps: [{ label: 'EU', state: 'done' }, { label: 'ASIA', state: 'failed', note: 'health' }, { label: 'ops', state: 'odd' }] } })
    expect(v.type).toBe('progress')
    expect(v.state).toBe('failed')
    expect(v.steps.map((s: any) => s.state)).toEqual(['done', 'failed', 'pending'])
    expect(v.steps[1].note).toBe('health')
    expect((cardView({ v: 1, type: 'progress', data: { title: 'x', state: 'nearly' } }) as any).state).toBe('running')
  })

  it('a Guild order card: its status, bounty, worker and lifecycle', () => {
    const v: any = cardView({ v: 1, type: 'guild.order.live', refs: { order_id: 'gwo_1' }, data: { order_id: 'gwo_1',
      title: 'Build (ad)', status: 'awarded', bounty: '15.0000000000', currency: 'ECU', bids: 2, worker_did: 'did:x:w',
      worker_name: 'session-release', poster_name: 'session-lead',
      events: [{ type: 'posted', at: '2026-10-31T18:07:00Z' }, { type: 'bid', at: null }, { type: 'awarded', at: null }] } })
    expect(v.type).toBe('guild.order.live')
    expect([v.orderId, v.status, v.bounty, v.currency, v.bids, v.workerName, v.posterName])
      .toEqual(['gwo_1', 'awarded', '15', 'ECU', 2, 'session-release', 'session-lead'])
    expect(guildStages(v.events).map((s) => [s.stage, s.reached])).toEqual([['posted', true], ['bid', true],
      ['awarded', true], ['submitted', false], ['settled', false]])
  })

  it("an approval's use, when the card shows it", () => {
    const base = { approval_id: 'apr_1', decision: 'approved', title: 'Roll', decided_by_developer_id: 6 }
    expect((cardView({ v: 1, type: 'approval.decided', data: base }) as any).used).toBeNull()
    const v: any = cardView({ v: 1, type: 'approval.decided', data: { ...base,
      used: { act: 'run_prod651.sh', act_sha256: 'ab'.repeat(32), at: '2026-11-01T05:00:00Z' } } })
    expect(v.used).toEqual({ act: 'run_prod651.sh', actSha256: 'ab'.repeat(32), at: '2026-11-01T05:00:00Z' })
  })

  it('steps counted: done and skipped are not waiting', () => {
    expect(stepTotals([{ state: 'done' }, { state: 'skipped' }, { state: 'failed' }, { state: 'running' }, { state: 'pending' }]))
      .toEqual({ done: 2, failed: 1, running: 1, total: 5 })
  })
})
