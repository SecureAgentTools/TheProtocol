/**
 * What Settings does with the ?tab= in its address (§FESUITE, 2026-10-04, his word "settings ... needs some polish").
 *
 * The address names the tab that is open. Before this, a deep link (?tab=notifications) stayed in the address after
 * another tab was clicked, so a reload or a copied link went back to it; and a ?tab= this viewer cannot see stayed in
 * the address beside a different tab. The Invitations tab exists only once the registration config has answered
 * (an invite-gated registry and a viewer who may manage invites), so its deep link waits for that read instead of being
 * judged against a list that does not hold it yet.
 */
export type TabQueryAction = 'open' | 'wait' | 'drop' | 'none'

/**
 * @param requested the ?tab= value as the router gives it (a string, an array, null or undefined)
 * @param visible the tab keys this viewer has now
 * @param undecided the tab keys whose existence a read still decides
 */
export function tabQueryAction(requested: unknown, visible: readonly string[], undecided: readonly string[] = []): TabQueryAction {
  if (typeof requested !== 'string' || requested === '') return 'none'
  if (visible.includes(requested)) return 'open'
  if (undecided.includes(requested)) return 'wait'
  return 'drop'
}

/** The query that names `key` as the open tab; every other parameter stays as it was. */
export function queryForTab<Q extends Record<string, unknown>>(query: Q, key: string): Q & { tab: string } {
  return { ...query, tab: key }
}
