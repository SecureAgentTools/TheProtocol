/**
 * V0657 (b), session-code 2026-11-06: an agent's organization, as its HOME registry states it (orgs v2, items 1-4, 12).
 *
 * The mark rides the card as a top-level extension (`https://theprotocol.cloud/extensions/v1/org`), derived by the
 * agent's home registry and copied as it is by every peer's mirror. It is there only while the organization is listed
 * and the agent shows it; a card without it says nothing about any organization. `provider.name` is something else:
 * free text the card's author typed, which any card can set to any name, so it is shown as the agent's own words.
 *
 * The logo is the one the home registry hosts. A path on this origin is used as it is; an absolute address only when it
 * is https and under the home's own origin (`home.origin`), so a card can never send a viewer's browser elsewhere.
 */

export const ORG_EXTENSION_URI = 'https://theprotocol.cloud/extensions/v1/org'

export interface OrgMarkHome {
  name?: string | null
  origin?: string | null
  console?: string | null
}

export interface OrgMark {
  id: string
  slug: string
  name: string
  logo: string | null
  home: OrgMarkHome | null
  /** the organization's page on its home's console, for a person (absolute), when its home names its console */
  page: string | null
}

const str = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null)

/** The mark a card carries, or null. Accepts card_data as an object or a JSON string. */
export function orgMarkOf(cardData: unknown): OrgMark | null {
  let cd: any = cardData
  if (typeof cd === 'string') {
    try { cd = JSON.parse(cd) } catch { return null }
  }
  const exts = cd && typeof cd === 'object' && Array.isArray(cd.extensions) ? cd.extensions : []
  const ext = exts.find((e: any) => e && typeof e === 'object' && e.uri === ORG_EXTENSION_URI)
  return orgMarkFromParams(ext && typeof ext.params === 'object' ? ext.params : null)
}

/** The mark from its fields as the block carries them (the discover list answers them as `org`), or null. */
export function orgMarkFromParams(p: any): OrgMark | null {
  if (!p || typeof p !== 'object') return null
  const id = str(p.id)
  const name = str(p.name)
  if (!id || !name) return null
  const home = p.home && typeof p.home === 'object'
    ? { name: str(p.home.name), origin: str(p.home.origin), console: str(p.home.console) }
    : null
  return { id, slug: str(p.slug) || '', name, logo: str(p.logo), home, page: str(p.page) }
}

/** The logo address the console may load: a path on this origin, or https under the mark's home origin. */
export function safeLogo(mark: Pick<OrgMark, 'logo' | 'home'> | null | undefined): string | null {
  const logo = mark?.logo
  if (!logo) return null
  if (logo.startsWith('/api/v1/organizations/') && !logo.startsWith('//')) return logo
  let u: URL
  try { u = new URL(logo) } catch { return null }
  if (u.protocol !== 'https:') return null
  const origin = mark?.home?.origin
  if (!origin) return null
  let o: URL
  try { o = new URL(origin) } catch { return null }
  if (u.origin !== o.origin || !u.pathname.startsWith('/api/v1/organizations/')) return null
  return u.toString()
}

/** Where a click on the mark goes: this console's page for an organization of this registry, else its home's page
 *  (absolute, opened apart), else nowhere. */
export function orgMarkLink(mark: OrgMark | null | undefined, local: boolean):
  { kind: 'route'; to: { name: string; query: Record<string, string> } } | { kind: 'external'; href: string } | null {
  if (!mark) return null
  if (local && mark.slug) return { kind: 'route', to: { name: 'public-firms', query: { org: mark.slug } } }
  if (mark.page) {
    try {
      const u = new URL(mark.page)
      if (u.protocol === 'https:' || u.protocol === 'http:') return { kind: 'external', href: u.toString() }
    } catch { /* not an address */ }
  }
  return null
}
