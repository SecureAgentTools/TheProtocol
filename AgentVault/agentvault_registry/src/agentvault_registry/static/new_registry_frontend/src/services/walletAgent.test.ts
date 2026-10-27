import { describe, it, expect } from 'vitest'
import { isWalletAgent, walletTags, walletSentence, walletHowItWorks, moveFundsDoor, WALLET_TAG, firstAgentIsWallet } from './walletAgent'

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
  it('the move-funds door is the ONE send door, prefilled', () => {
    expect(moveFundsDoor('did:theprotocol:abc')).toBe('/pocket/pay?to=did%3Atheprotocol%3Aabc')
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
