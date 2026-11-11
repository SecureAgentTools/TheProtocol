/**
 * V0658 (v), session-lead's seq 2419: what the Forex Desk takes from the door that opened it (?to=&from=, from
 * walletAgent.moveFundsDoor). The sender only when the account owns it; the recipient only when it is a DID. Anything
 * else is ignored, so an address can never pick a sender the account does not hold.
 */
export function forexDoorPrefill(query: Record<string, unknown>, owned: Set<string>): { to: string; from: string } {
  const one = (v: unknown) => (typeof v === 'string' ? v.trim() : '')
  const to = one(query.to), from = one(query.from)
  return { to: to.startsWith('did:') ? to : '', from: owned.has(from) ? from : '' }
}
