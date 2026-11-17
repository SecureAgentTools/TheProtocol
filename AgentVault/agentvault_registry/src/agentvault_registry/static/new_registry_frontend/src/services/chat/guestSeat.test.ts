import { describe, it, expect } from 'vitest'
import { canSeatGuests, guestTarget } from './guestSeat'

/** V0662 (OurChat lane): guest seat, the console's rules. BASE (2d8181416): the module does not exist. */

describe('whom a person named', () => {
  it('an agent DID', () => {
    expect(guestTarget('did:theprotocol:eu.test:quantum-session')).toEqual({ agent_did: 'did:theprotocol:eu.test:quantum-session' })
    expect(guestTarget('  did:cos:453d4a48  ')).toEqual({ agent_did: 'did:cos:453d4a48' })
  })
  it('a developer id', () => {
    expect(guestTarget('42')).toEqual({ developer_id: 42 })
    expect(guestTarget(' 7 ')).toEqual({ developer_id: 7 })
  })
  it('nothing for anything else: names, markup, zero, negative, a path, too long, empty', () => {
    for (const bad of ['Mira', '0', '-3', '4.5', '12345678901', '<b>', 'did:', 'did:x y', '../x', '', '   ', null, undefined]) {
      expect(guestTarget(bad as any), String(bad)).toBeNull()
    }
  })
})

describe('who is offered the controls', () => {
  it('the room\'s operator only', () => {
    expect(canSeatGuests({ my_is_operator: true })).toBe(true)
    expect(canSeatGuests({ my_is_operator: false })).toBe(false)
    expect(canSeatGuests({})).toBe(false)
    expect(canSeatGuests(null)).toBe(false)
  })
})
