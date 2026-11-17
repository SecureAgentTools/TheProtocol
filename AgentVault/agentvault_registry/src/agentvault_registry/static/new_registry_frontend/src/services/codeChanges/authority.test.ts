// V0666 (order gwo_e086b25f868da7ec9fce9fd2): the console shows the registry's sentence and no way to submit where code is not governed; nothing changes on the governing registry; an unknown answer
// behaves as before (the registry refuses at every write anyway).
import { beforeEach, describe, expect, it, vi } from 'vitest'

const getAuthority = vi.fn()
vi.mock('@/services/api/codeChanges', () => ({ getAuthority: (...a: unknown[]) => getAuthority(...a) }))

import { authorityView, resetCodeAuthorityForTests, useCodeAuthority } from './authority'

const OTHER = { governing: 'eu', self: false, name: 'eu', console: 'https://eu.theprotocol.cloud/', sentence: 'Code changes are governed on eu; open them there: https://eu.theprotocol.cloud/' }

describe('authorityView', () => {
  it('is read-only with the registry\'s own sentence and link when this registry does not govern', () => {
    expect(authorityView(OTHER)).toEqual({ readOnly: true, sentence: OTHER.sentence, link: 'https://eu.theprotocol.cloud/' })
  })
  it('is unchanged on the governing registry', () => {
    expect(authorityView({ governing: 'eu', self: true, name: 'eu', console: null, sentence: null })).toEqual({ readOnly: false, sentence: '', link: null })
  })
  it('behaves as before while the answer is unknown (not read, or the read failed)', () => {
    expect(authorityView(null).readOnly).toBe(false)
    expect(authorityView(undefined).readOnly).toBe(false)
  })
  it('says a sentence even when the registry sent none (an older registry without the field)', () => {
    expect(authorityView({ ...OTHER, sentence: null, console: null }).sentence).toBe('Code changes are governed on eu; open them there.')
  })
})

describe('useCodeAuthority', () => {
  beforeEach(() => { getAuthority.mockReset(); resetCodeAuthorityForTests() })
  it('reads once and shares the answer', async () => {
    getAuthority.mockResolvedValue(OTHER)
    const a = useCodeAuthority(); const b = useCodeAuthority()
    await a.load()
    expect(getAuthority).toHaveBeenCalledTimes(1)
    expect(a.authority.value?.self).toBe(false); expect(b.authority.value).toBe(a.authority.value)
  })
  it('leaves the answer unknown when the read fails', async () => {
    getAuthority.mockRejectedValue(new Error('down'))
    const a = useCodeAuthority()
    await a.load()
    expect(a.authority.value).toBeNull(); expect(authorityView(a.authority.value).readOnly).toBe(false)
  })
})
