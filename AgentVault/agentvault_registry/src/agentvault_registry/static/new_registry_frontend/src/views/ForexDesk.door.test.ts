/**
 * V0658 (v), session-lead's seq 2419: "Move funds from your wallet agent" pressed in the desktop console opens the
 * Forex Desk (the desktop's send surface) with ?to=<the new agent>&from=<the wallet>. The desk takes both from its
 * address: the sender only when the account owns it, the recipient only when it is a DID. It reads them on arrival
 * AND when the address changes under a mounted desk (vue-router reuses the component on a query-only change).
 * RED on 041b3e9ac: the desk read no address at all.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const helper = async () => (await import('@/services/forexDoor').catch(() => ({}))) as Record<string, any>

describe('the Forex Desk takes its sender and recipient from the door that opened it', () => {
  it('a DID recipient and an owned sender are taken', async () => {
    const { forexDoorPrefill } = await helper()
    expect(typeof forexDoorPrefill).toBe('function')
    const owned = new Set(['did:theprotocol:wallet', 'did:theprotocol:new'])
    expect(forexDoorPrefill({ to: 'did:theprotocol:new', from: 'did:theprotocol:wallet' }, owned))
      .toEqual({ to: 'did:theprotocol:new', from: 'did:theprotocol:wallet' })
  })
  it('a sender the account does not own, or a recipient that is no DID, is not taken', async () => {
    const { forexDoorPrefill } = await helper()
    const owned = new Set(['did:theprotocol:wallet'])
    expect(forexDoorPrefill({ to: 'javascript:alert(1)', from: 'did:theprotocol:someone-else' }, owned))
      .toEqual({ to: '', from: '' })
    expect(forexDoorPrefill({ to: ['did:a', 'did:b'], from: undefined }, owned)).toEqual({ to: '', from: '' })
    expect(forexDoorPrefill({}, owned)).toEqual({ to: '', from: '' })
  })
  it('the desk applies it on arrival and on a query change', () => {
    const src = readFileSync(resolve(__dirname, 'ForexDesk.vue'), 'utf8')
    expect(src).toMatch(/import \{ forexDoorPrefill \} from '@\/services\/forexDoor'/)
    const mounted = src.slice(src.indexOf('onMounted(async () => {'), src.indexOf('onUnmounted('))
    expect(mounted).toContain('await applyDoor()')
    expect(src).toMatch(/watch\(\(\) => \[route\.query\.to, route\.query\.from\]/)
  })
})
