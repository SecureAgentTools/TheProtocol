/**
 * §FESUITE V0578 (2026-10-06, agentvault2-09): the API tester's group cards.
 *
 * The curated groups name what a person looks for; the catalog the registry serves decides what is in them. The lists
 * were written against an older catalog: on sbx-beta 126 of the 158 categories it serves (916 of 1,255 endpoints) were in
 * no card, and three cards opened to nothing ("Authentication" asked for auth/auth_secure/auth_2fa while the registry
 * serves authentication and two_factor_authentication). Now every category the registry lists lands in exactly one
 * group: its curated list first, then the group's name rule, then "Everything else"; a group with no endpoint on this
 * registry is not drawn.
 */
export interface GroupDef {
  name: string
  icon: string
  description: string
  /** the categories this group was written for (a name the registry does not serve is ignored) */
  categories: string[]
  /** a served category no curated list names joins the first group whose rule matches it */
  rule?: RegExp
}

export interface Group {
  name: string
  icon: string
  description: string
  categories: string[]
}

export const EVERYTHING_ELSE = 'Everything else'

export function groupCategories(defs: GroupDef[], endpoints: Record<string, unknown[] | undefined> | null | undefined): Group[] {
  const served = Object.keys(endpoints || {})
  const taken = new Set<string>()
  const out: Group[] = defs.map((d) => ({ name: d.name, icon: d.icon, description: d.description, categories: [] }))
  defs.forEach((d, i) => {
    for (const c of d.categories) {
      if (served.includes(c) && !taken.has(c)) { out[i].categories.push(c); taken.add(c) }
    }
  })
  for (const k of served) {
    if (taken.has(k)) continue
    const i = defs.findIndex((d) => !!d.rule && d.rule.test(k))
    if (i >= 0) { out[i].categories.push(k); taken.add(k) }
  }
  const rest = served.filter((k) => !taken.has(k))
  if (rest.length) {
    out.push({ name: EVERYTHING_ELSE, icon: 'folder', description: 'Every other category this registry serves', categories: rest })
  }
  return out.filter((g) => g.categories.some((c) => ((endpoints || {})[c] || []).length > 0))
}
