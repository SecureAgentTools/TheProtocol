import { describe, it, expect } from 'vitest'
import { DEADLINE_DAYS, SPEC_MAX, TITLE_MAX, orderBody, parseBounty } from './orderPost'

/** V0662 (OurChat lane): /order's door builds the Guild rail's body and refuses what the rail would. BASE (7435f0d5a): no module. */

const form = (over: Record<string, any> = {}) => ({ title: 'Review the PR', bounty: '20', currency: 'ecu', spec: '', deadlineDays: 7, showInRoom: true, ...over })

describe('a bounty as typed', () => {
  it('reads a dot, a comma and a number', () => {
    expect(parseBounty('12,5')).toBe(12.5)
    expect(parseBounty(' 12.5 ')).toBe(12.5)
    expect(parseBounty(7)).toBe(7)
  })
  it('is none for zero, negative, words, empty, infinity', () => {
    for (const bad of ['0', '-1', 'abc', '', '  ', 'Infinity', 'NaN', null, undefined, 0, -3]) expect(parseBounty(bad as any), String(bad)).toBeNull()
  })
})

describe('the body', () => {
  it('is what the Guild takes: title, bounty, upper-case currency, the deadline in seconds and this conversation', () => {
    const r = orderBody(form(), 'conv-1')
    expect(r).toEqual({ ok: true, body: { title: 'Review the PR', bounty: 20, currency: 'ECU', deadline_seconds: 7 * 86400, room_id: 'conv-1' } })
  })
  it('carries the spec only when there is one, trimmed', () => {
    expect((orderBody(form({ spec: '  do it  ' }), 'c') as any).body.spec).toBe('do it')
    expect('spec' in (orderBody(form({ spec: '   ' }), 'c') as any).body).toBe(false)
  })
  it('names no room when the person does not want it shown here, or there is none', () => {
    expect('room_id' in (orderBody(form({ showInRoom: false }), 'c') as any).body).toBe(false)
    expect('room_id' in (orderBody(form(), null) as any).body).toBe(false)
  })
  it('every deadline choice is within the rail\'s bounds (60 s to 30 days)', () => {
    for (const d of DEADLINE_DAYS) {
      const s = (orderBody(form({ deadlineDays: d }), 'c') as any).body.deadline_seconds
      expect(s).toBeGreaterThanOrEqual(60)
      expect(s).toBeLessThanOrEqual(2_592_000)
    }
  })
  it('refuses, by what to fix: title, bounty, currency, spec, deadline', () => {
    expect(orderBody(form({ title: '  ' }), 'c')).toEqual({ ok: false, reason: 'title' })
    expect(orderBody(form({ title: 'x'.repeat(TITLE_MAX + 1) }), 'c')).toEqual({ ok: false, reason: 'title' })
    expect(orderBody(form({ bounty: '0' }), 'c')).toEqual({ ok: false, reason: 'bounty' })
    expect(orderBody(form({ bounty: 'lots' }), 'c')).toEqual({ ok: false, reason: 'bounty' })
    expect(orderBody(form({ currency: '' }), 'c')).toEqual({ ok: false, reason: 'currency' })
    expect(orderBody(form({ currency: 'EC U' }), 'c')).toEqual({ ok: false, reason: 'currency' })
    expect(orderBody(form({ spec: 'x'.repeat(SPEC_MAX + 1) }), 'c')).toEqual({ ok: false, reason: 'spec' })
    expect(orderBody(form({ deadlineDays: 9 }), 'c')).toEqual({ ok: false, reason: 'deadline' })
    expect(orderBody(form({ title: 'x'.repeat(TITLE_MAX) }), 'c').ok).toBe(true)                  // control: the limit itself
  })
})
