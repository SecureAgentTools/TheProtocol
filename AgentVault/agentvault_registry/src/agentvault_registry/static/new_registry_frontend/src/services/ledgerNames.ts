/**
 * W4 phase 1 (agentvault2-aa, 2026-10-25): the ledger's event names, old and new, read as one, in the console.
 *
 * His words that day to agentvault2-69: "i want the illegal wording completly gone before opening" and, on the ledger,
 * "just use the new wording and make it accept both or something" (sessionlogs2026/PLAN_2026-10-25_COMPLIANT_OPENING.md,
 * W4). Phase 2 lets an emitter write UnitsTransferred for TokensTransferred (and the rest below); before any emitter does,
 * every screen that compares an event type, or looks one up in a table keyed by it, reads both names the same. This is the
 * registry's map (agentvault_registry/core/ledger_names.py), data for data; ledgerNames.test.ts pins it.
 *
 * A screen asks `liveOld(t)` before a comparison or a lookup in a table keyed by the old names (a new name reads as its
 * old one; any other name, a legacy spelling included, stays as it is), `liveNames(t)` to read a count kept per name, and
 * `expandLive(names)` for a set. `labelName(t)` is the name a label is made from: an event's new name, AGORA's too (his
 * AGORA word list of 2026-09-21), so a row written under the old name reads in the new words too.
 */

/** old name -> new name (what the emitters write today -> what phase 2 writes) */
export const RENAMED: Readonly<Record<string, string>> = {
  TokensTransferred: 'UnitsTransferred',
  TokensIssued: 'UnitsIssued',
  TokensStaked: 'UnitsLocked',
  TokensUnstaked: 'UnitsUnlocked',
  StakeForceUnstaked: 'LockForceUnlocked',
  RewardsDistributed: 'LockPayoutsDistributed',
  RewardsAutoCompounded: 'LockPayoutsRelocked',
  RewardsAutoCompoundSkipped: 'LockPayoutRelockSkipped',
  TokensBridgeLocked: 'UnitsBridgeLocked',
  TokensBridgeUnlocked: 'UnitsBridgeUnlocked',
}

/** AGORA's, by his AGORA word list of 2026-09-21: readers know them from phase 1 on, phase 2 writes them */
export const AGORA_RENAMED: Readonly<Record<string, string>> = {
  ExchangeDividendDeclared: 'ExchangeDistributionDeclared',
  ExchangeDividendPaid: 'ExchangeDistributionPaid',
  ExchangeSharesIssued: 'ExchangePointsIssued',
  ExchangeSharesSplit: 'ExchangePointsSplit',
  ExchangeShareRefloated: 'ExchangePointsRefloated',
}

/** older spellings some stores still hold, as the registry's map names them (a screen reads them as it always did) */
export const LEGACY: Readonly<Record<string, string>> = {
  TokenTransferred: 'TokensTransferred',
  RewardDistributed: 'RewardsDistributed',
  StakeRewardDistributed: 'RewardsDistributed',
}

const ALL_RENAMED: Readonly<Record<string, string>> = { ...RENAMED, ...AGORA_RENAMED }
const NEW_TO_OLD: Readonly<Record<string, string>> = Object.fromEntries(
  Object.entries(ALL_RENAMED).map(([oldName, newName]) => [newName, oldName]),
)

/** A new name as its old one; any other name (an old name, a legacy spelling, an unrenamed event) as it is. */
export function liveOld(name: string | null | undefined): string {
  if (!name) return ''
  return NEW_TO_OLD[name] ?? name
}

/** The names an emitter may write for an event, today or in phase 2: the old name, then its new one. */
export function liveNames(name: string): string[] {
  const old = liveOld(name)
  return ALL_RENAMED[old] ? [old, ALL_RENAMED[old]] : [old]
}

/** Every live name of every event named (a set to test membership against). */
export function expandLive(names: Iterable<string>): Set<string> {
  const out = new Set<string>()
  for (const n of names) for (const m of liveNames(n)) out.add(m)
  return out
}

/** The name a label is made from: the new name of a renamed event (AGORA's included), any other name as it is. */
export function labelName(name: string | null | undefined): string {
  const old = liveOld(name)
  return ALL_RENAMED[old] ?? (name || '')
}
