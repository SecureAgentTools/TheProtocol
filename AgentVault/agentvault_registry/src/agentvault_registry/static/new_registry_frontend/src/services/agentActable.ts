/**
 * §MCPTEST30 (V0640): an agent the server lists as revoked or suspended cannot act, by any road.
 *
 * The owner rail refuses it (routers/developers.owner_mint_refusal: 403 "This agent is revoked: it cannot act, so no
 * token is minted.") and a saved secret no longer signs it in, yet the store's canActAs asked only "yours, here, a DID",
 * so the switcher and the picker offered every listed row. GET /developers/me/agents lists every status, newest first,
 * and names each row's `status`: on sbx-beta (2026-10-24) the shared admin's ten newest agents were deleted throwaways,
 * and the console suite's owner-rail step met ten 403s before it could act at all. A row built from a saved secret
 * reads 'unknown': the registry decides those.
 */
export type CannotAct = 'revoked' | 'suspended'

/** Why the agent cannot act at all ('revoked' or 'suspended', the server's words), or null when nothing says so. */
export function cannotActReason(agent: any): CannotAct | null {
  for (const v of [agent?.status, agent?.enforcement_status]) {
    const s = String(v ?? '').trim().toLowerCase()
    if (s === 'revoked') return 'revoked'
    if (s === 'suspended') return 'suspended'
  }
  return null
}

/** The sentence the console says for it. */
export function cannotActSentence(agent: any, reason: CannotAct): string {
  const label = agent?.name || agent?.did || 'This agent'
  return reason === 'revoked'
    ? `${label} has been deleted (revoked): it cannot act any more.`
    : `${label} is suspended on its registry: it cannot act while the suspension holds.`
}
