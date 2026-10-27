import { describe, expect, it } from 'vitest'
import { ledgerEventLabel } from './ledgerEventLabel'

describe('ledgerEventLabel: a ledger event type as a person reads it', () => {
  it('says units and locked where the ledger says tokens and staked', () => {
    expect(ledgerEventLabel('TokensTransferred')).toBe('Units transferred')
    expect(ledgerEventLabel('TokensIssued')).toBe('Units issued')
    expect(ledgerEventLabel('TokensStaked')).toBe('Units locked')
    expect(ledgerEventLabel('TokensUnstaked')).toBe('Units unlocked')
  })

  it('reads every other type as words, acronyms kept', () => {
    expect(ledgerEventLabel('TransactionFeeCollected')).toBe('Transaction fee collected')
    expect(ledgerEventLabel('ExchangeTradeExecuted')).toBe('Exchange trade executed')
    expect(ledgerEventLabel('A2APaymentAuthorized')).toBe('A2A payment authorized')
    expect(ledgerEventLabel('FxSwapSettled')).toBe('Fx swap settled')
    expect(ledgerEventLabel('TEGOutboxDrained')).toBe('TEG outbox drained')
  })

  it('never shows a stake or token word for the ledger types the console lists', () => {
    const types = ['TokensTransferred', 'TokensIssued', 'TokensStaked', 'TokensUnstaked', 'TokensBurned', 'StakingRewardsDistributed',
      'TransactionFeeCollected', 'LedgerBalanceChanged', 'CrossRegistryTransferCompleted', 'ExchangeOrderPlaced']
    for (const t of types) expect(ledgerEventLabel(t)).not.toMatch(/\b(stak(e|ed|es|ing)|tokens?)\b/i)
  })

  it('answers an empty or missing type with nothing, and an odd one with itself', () => {
    expect(ledgerEventLabel('')).toBe('')
    expect(ledgerEventLabel(undefined)).toBe('')
    expect(ledgerEventLabel('---')).toBe('---')
  })
})
