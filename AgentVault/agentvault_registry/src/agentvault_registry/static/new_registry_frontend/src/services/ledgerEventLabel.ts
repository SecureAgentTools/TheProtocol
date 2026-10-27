/**
 * A ledger event's type, as a person reads it (agentvault2-56, 2026-10-23; his word: the console says locked and units,
 * not staked and tokens). `TokensTransferred` reads "Units transferred", `TokensStaked` "Units locked",
 * `ExchangeTradeExecuted` "Exchange trade executed", `A2APaymentAuthorized` "A2A payment authorized".
 *
 * Only the label changes. The ledger's own event names stay exactly as they are: history, projections, emission
 * policies, exports and every API carry them, so a screen that shows the label keeps the raw name on hover.
 */
import { labelName } from './ledgerNames'

const SWAP: Record<string, string> = {
  Tokens: 'Units',
  Token: 'Unit',
  Staked: 'Locked',
  Unstaked: 'Unlocked',
  Stake: 'Lock',
  Unstake: 'Unlock',
  Staking: 'Locking',
}

// one word each: an acronym (A2A, TEG, FX in capitals), a capitalised word, or a lowercase run
const WORD = /[A-Z0-9]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+/g

export function ledgerEventLabel(type: string | null | undefined): string {
  if (!type) return ''
  // W4 phase 1: a renamed event reads in its new name's words under either name (RewardsDistributed: "Lock payouts
  // distributed"), AGORA's too (ExchangeDividendPaid: "Exchange distribution paid")
  const words = labelName(type).match(WORD)
  if (!words) return type
  return words
    .map((w) => SWAP[w] ?? w)
    .map((w, i) => (i === 0 || /^[A-Z0-9]{2,}$/.test(w) ? w : w.toLowerCase()))
    .join(' ')
}
