// V0662 console polish, item 5 (order gwo_0aa7b875cbf65b6347f5f775): an agent's roles in the console's words.
//
// The roles come from the API by their names and keep them there (a role is a permission bundle the registry
// resolves: IRONKEY, PART 14). The console says LOCKED for what the ledger calls staked (i18n/vocabulary.test.ts), so
// the locking role reads as the words for locking units, its API name on the hover as data (the form
// services/permissionLabel uses for a permission). Every other role reads as its name.

type T = (key: string, fallback: string) => string

// keyed by the API's role name; the words carry no API name of their own (the vocabulary gate reads every string)
const ROLE_WORDS: Record<string, [string, string]> = {
  staker: ['agentRoles.lockUnits', 'locks units'],
}

export function roleLabel(role: string, t: T): string {
  const w = ROLE_WORDS[role]
  return w ? t(w[0], w[1]) : role
}

/** The hover for a role the console words differently: its API name. Empty for a role shown by its name. */
export function roleTitle(role: string, t: T): string {
  return ROLE_WORDS[role] ? `${role}: ${t('agentRoles.apiName', 'its name in the API')}` : ''
}
