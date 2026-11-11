import { describe, it, expect } from 'vitest'
import { isWalletAgent, walletTags, walletSentence, walletHowItWorks, moveFundsDoor, WALLET_TAG, firstAgentIsWallet } from './walletAgent'
import * as uiMode from './uiMode'

const t = (_k: string, fb: string) => fb

describe('§WALLETAGENT — one marker, one sentence', () => {
  it('reads the marker from a card or from a list row carrying the card', () => {
    expect(isWalletAgent({ tags: ['wallet'] })).toBe(true)
    expect(isWalletAgent({ card_data: { tags: ['Wallet', 'x'] } })).toBe(true)
    expect(isWalletAgent({ card_data: { tags: ['oracle'] } })).toBe(false)
    expect(isWalletAgent({ card_data: {} })).toBe(false)
    expect(isWalletAgent(null)).toBe(false)
    expect(walletTags()).toEqual([WALLET_TAG])
  })
  it('the sentence is three lines and the how-it-works four, all with a fallback', () => {
    expect(walletSentence(t)).toHaveLength(3)
    expect(walletHowItWorks(t)).toHaveLength(4)
    expect(walletSentence(t)[0]).toMatch(/identity/)
  })
  it('the move-funds door is the ONE send door, prefilled (in Pocket)', () => {
    const doors = uiMode as unknown as Record<string, any>
    doors.bindDoorRouter?.({ currentRoute: { value: { path: '/pocket/home', meta: { shell: 'pocket' } } } })
    try {
      expect(moveFundsDoor('did:theprotocol:abc')).toBe('/pocket/pay?to=did%3Atheprotocol%3Aabc')
      // Pocket's own send picks its sender: the wallet is not carried there
      expect(moveFundsDoor('did:theprotocol:abc', 'did:theprotocol:wallet')).toBe('/pocket/pay?to=did%3Atheprotocol%3Aabc')
    } finally { doors.bindDoorRouter?.(null) }
  })
  // V0658 (v), session-lead's seq 2419: the same rule as the other doors. RED on 041b3e9ac: always /pocket/pay.
  it('pressed in the desktop console it opens the Forex Desk, from the wallet, whatever is saved', () => {
    const doors = uiMode as unknown as Record<string, any>
    doors.bindDoorRouter?.({ currentRoute: { value: { path: '/mission-control', meta: { shell: 'desktop' } } } })
    localStorage.setItem(uiMode.UI_MODE_KEY, 'pocket')
    try {
      expect(moveFundsDoor('did:theprotocol:abc', 'did:theprotocol:wallet'))
        .toBe('/forex?to=did%3Atheprotocol%3Aabc&from=did%3Atheprotocol%3Awallet')
      expect(moveFundsDoor('did:theprotocol:abc')).toBe('/forex?to=did%3Atheprotocol%3Aabc')
    } finally { doors.bindDoorRouter?.(null); localStorage.clear() }
  })
})

describe('§FESUITE (V0577): the first agent is the wallet only over a read that answered', () => {
  it('no agents read: the first agent is the wallet', () => {
    expect(firstAgentIsWallet([], false)).toBe(true)
  })
  it('agents read: not the first agent', () => {
    expect(firstAgentIsWallet([{ did: 'did:theprotocol:a' }], false)).toBe(false)
  })
  it('a read that failed is not "no agents"', () => {
    expect(firstAgentIsWallet([], true)).toBe(false)
  })
})
