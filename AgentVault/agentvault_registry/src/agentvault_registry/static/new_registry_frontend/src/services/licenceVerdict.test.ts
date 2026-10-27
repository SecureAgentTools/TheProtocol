import { describe, expect, it } from 'vitest'
import { licenceLabel, licenceLabelRiding, licenceOk, licenceRow, licenceTone, REFUSED_LICENCE_STATES } from './licenceVerdict'

describe('licenceRow: a peer shows OUR verdict, never its own claim as ours', () => {
  it('shows our verdict and labels the card claim when they disagree', () => {
    const r = licenceRow({
      isSelf: false, cardState: 'licensed', ourState: 'revoked',
      ourReason: "genesis.example's list says revoked", ourCheckedAt: '2026-09-28T02:30:00+00:00',
    })!
    expect(r.text).toBe('Revoked')
    expect(r.tone).toBe('refused')
    expect(r.cardSays).toBe('Licensed')
    expect(r.hint).toContain("This registry's own verdict, checked 2026-09-28 02:30 UTC")
    expect(r.hint).toContain("genesis.example's list says revoked")
  })

  it('control: no verdict here is "not evaluated here", never the card claim', () => {
    const r = licenceRow({ isSelf: false, cardState: 'licensed', ourState: null })!
    expect(r.text).toBe('not evaluated here')
    expect(r.tone).toBe('unmeasured')
    expect(r.text).not.toBe('Licensed')
    expect(r.cardSays).toBe('Licensed')
  })

  it('an empty verdict string is no verdict', () => {
    expect(licenceRow({ isSelf: false, cardState: 'licensed', ourState: '  ' })!.tone).toBe('unmeasured')
  })

  it('agreement still names whose statement is which', () => {
    const r = licenceRow({ isSelf: false, cardState: 'licensed', ourState: 'licensed' })!
    expect([r.text, r.tone, r.cardSays]).toEqual(['Licensed', 'ok', 'Licensed'])
    expect(r.hint.startsWith("This registry's own verdict")).toBe(true)
  })

  it('a verdict about a peer whose card has no block (an older image)', () => {
    const r = licenceRow({ isSelf: false, cardState: null, ourState: 'unlicensed' })!
    expect([r.text, r.tone, r.cardSays]).toEqual(['Standalone (not licensed for federation)', 'refused', null])
  })

  it('nothing to say: no block and no verdict hides the row', () => {
    expect(licenceRow({ isSelf: false, cardState: null, ourState: null })).toBeNull()
  })

  it('an unverified verdict (the genesis list unreachable) is neither green nor red', () => {
    expect(licenceRow({ isSelf: false, cardState: 'licensed', ourState: 'unverified' })!.tone).toBe('neutral')
  })
})

describe('licenceRow: on self the card block IS our derivation', () => {
  it('shows the card state with no "as the card states" line', () => {
    const r = licenceRow({ isSelf: true, cardState: 'genesis', ourState: 'genesis' })!
    expect([r.text, r.tone, r.cardSays]).toEqual(['Genesis (the network root)', 'ok', null])
  })

  it('self with no block hides the row', () => {
    expect(licenceRow({ isSelf: true, cardState: null })).toBeNull()
  })
})

describe('labels and tones', () => {
  it('every refused state is red and every other known state is not', () => {
    for (const s of REFUSED_LICENCE_STATES) expect(licenceTone(s)).toBe('refused')
    for (const s of ['genesis', 'licensed']) expect(licenceTone(s)).toBe('ok')
    for (const s of ['unverified', 'same-domain', 'something-new']) expect(licenceTone(s)).toBe('neutral')
  })

  it('an unknown state shows itself rather than a blank', () => {
    expect(licenceLabel('superseded')).toBe('superseded')
    expect(licenceLabel(null)).toBe('—')
    expect(licenceOk('superseded')).toBe(false)
  })
})

describe("an operator's card carries its frame's licence, and says so", () => {
  // measured on production 2026-09-28 (agentvault2-41's visitor probe): lisbon's card read "As the card states: Genesis
  // (the network root)", as if the operator were the root
  it("a peer operator riding the genesis frame names the frame, not itself, as the root", () => {
    const r = licenceRow({ isSelf: false, cardState: 'genesis', ourState: 'same-domain', ridesFrame: 'eu.theprotocol.cloud' })!
    expect(r.cardSays).toBe('Genesis (via its frame, eu.theprotocol.cloud)')
    expect(r.text).toBe('Same trust domain (not a crossing)')
  })

  it("an operator riding a licensed frame, and the operator's own console", () => {
    expect(licenceRow({ isSelf: false, cardState: 'licensed', ourState: 'licensed', ridesFrame: 'asia.theprotocol.cloud' })!.cardSays)
      .toBe('Licensed (via its frame, asia.theprotocol.cloud)')
    expect(licenceRow({ isSelf: true, cardState: 'licensed', ridesFrame: 'asia.theprotocol.cloud' })!.text)
      .toBe('Licensed (via its frame, asia.theprotocol.cloud)')
  })

  it("control: a frame's own card still reads as the root, and no hint changes nothing", () => {
    expect(licenceRow({ isSelf: false, cardState: 'genesis', ourState: 'genesis' })!.cardSays).toBe('Genesis (the network root)')
    expect(licenceRow({ isSelf: true, cardState: 'genesis', ridesFrame: null })!.text).toBe('Genesis (the network root)')
  })

  it('a refused state is never softened by the hint', () => {
    expect(licenceLabelRiding('revoked', 'eu.theprotocol.cloud')).toBe('Revoked')
    expect(licenceLabelRiding('unlicensed', 'eu.theprotocol.cloud')).toBe('Standalone (not licensed for federation)')
  })
})
