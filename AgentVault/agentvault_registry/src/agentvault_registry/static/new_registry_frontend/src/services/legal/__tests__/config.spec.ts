import { describe, it, expect } from 'vitest'
import { providerTokens, resolveLegalTokens, UNRESOLVED, type ProviderFacts } from '../config'

const facts: ProviderFacts = {
  legal_name: 'Test Person', legal_form: 'sole proprietor', trading_as: 'Test Trading', street: 'Example Street 1',
  postal_code: '12345', city: 'Testtown', country: 'Germany', country_code: 'DE', legal_email: 'legal@example.invalid',
  privacy_email: null, security_email: 'sec@example.invalid', support_email: null, supervisory_authority: 'Some Authority, Some Street 2, 99999 Somewhere',
  governing_law: 'the Federal Republic of Germany', venue: 'Sometown, Germany', business_days: 'Monday to Friday', vat_id: null,
  small_business: false, editorial_person: null,
  address_line: 'Example Street 1, 12345 Testtown, Germany',
  full_line: 'Test Person, trading as "Test Trading", Example Street 1, 12345 Testtown, Germany',
  address_block: 'Test Person\nExample Street 1\n12345 Testtown\nGermany',
}

describe('legal tokens', () => {
  it('resolves every token from the facts, with the privacy mailbox falling back to the legal one', () => {
    const tok = providerTokens(facts)
    const out = resolveLegalTokens('Controller: {PROVIDER_FULL}. Mail {PRIVACY_EMAIL}; venue {VENUE}; unit {LOCAL_UNIT}; law {GOVERNING_LAW}', tok, 'ECU')
    expect(out).toBe('Controller: Test Person, trading as "Test Trading", Example Street 1, 12345 Testtown, Germany. Mail legal@example.invalid; venue Sometown, Germany; unit ECU; law the Federal Republic of Germany')
    expect(tok.EDITORIAL_ADDRESS_BLOCK).toBe('Test Person\nExample Street 1\n12345 Testtown\nGermany')
    expect(tok.JURISDICTION).toBe('Germany')
  })

  it('never invents: with no facts every token is the visible gap, not a default', () => {
    const tok = providerTokens(null)
    const out = resolveLegalTokens('{PROVIDER_FULL} / {LEGAL_EMAIL}', tok, 'AVT')
    expect(out).toBe(`${UNRESOLVED} / ${UNRESOLVED}`)
    expect(out).not.toMatch(/theprotocol|Jeziorny|Freilassing/i)
  })

  it('control: an unknown token stays visible, and text without tokens is untouched', () => {
    const tok = providerTokens(facts)
    expect(resolveLegalTokens('see {NO_SUCH_TOKEN} here', tok, 'AVT')).toBe('see {NO_SUCH_TOKEN} here')
    expect(resolveLegalTokens('plain sentence', tok, 'AVT')).toBe('plain sentence')
    expect(resolveLegalTokens('', tok, 'AVT')).toBe('')
  })

  it('prints a phone as the imprint\'s second channel only where the frame publishes one (§COOKIES)', () => {
    const text = 'E-Mail: {LEGAL_EMAIL}{IMPRINT_PHONE_LINE} / Contact: {LEGAL_EMAIL}{IMPRINT_PHONE_EN} (72 h)'
    expect(resolveLegalTokens(text, providerTokens(facts), 'ECU'))
      .toBe('E-Mail: legal@example.invalid / Contact: legal@example.invalid (72 h)')
    expect(resolveLegalTokens(text, providerTokens({ ...facts, phone: ' +49 30 1234567 ' }), 'ECU'))
      .toBe('E-Mail: legal@example.invalid\nTelefon: +49 30 1234567 / Contact: legal@example.invalid, phone +49 30 1234567 (72 h)')
    // the control: without any facts the email is the visible gap, while the phone is simply absent, never invented
    expect(resolveLegalTokens('{LEGAL_EMAIL}{IMPRINT_PHONE_LINE}{IMPRINT_PHONE_EN}', providerTokens(null), 'ECU')).toBe(UNRESOLVED)
    expect(resolveLegalTokens('{IMPRINT_PHONE_LINE}', providerTokens({ ...facts, phone: '   ' }), 'ECU')).toBe('')
  })
})
