/**
 * V0658 (r): why an organization's mark does not show, for the people who can change it.
 *
 * V0657 (b) states an organization's mark on its agents' cards (here and on every peer) only while the organization is
 * listed (its setting `public_listing`, off by default), and shows a logo only when this registry hosts it
 * (organization_logos, PUT /organizations/{id}/logo). A `logo_url` from before, on any host, is never shown. Nothing on
 * screen said which of these held, so an owner saw no logo anywhere and no reason (the sessions' room, seq 2136).
 *
 * This decides which condition is missing from what the organization's read answers (`listed`, `logo`, `logo_url`),
 * and which old logo address can be offered for upload: the owner's browser shows the image (an https address, the
 * console's pages load https images only) or opens it, and the owner uploads the file. The registry never fetches it.
 */

export interface OrgMarkFacts {
  /** whether the organization is listed, as its read answers it */
  listed?: boolean | null
  /** the logo this registry hosts for it (a path on this registry), or null */
  logo?: string | null
  /** the address it named for its logo before V0657 (b), never shown */
  logo_url?: string | null
}

export interface LegacyLogo {
  /** the address, as an absolute http(s) URL */
  href: string
  /** its host, to name it */
  host: string
  /** whether this console may show it as an image (https only; an http one can only be opened) */
  showable: boolean
}

export interface OrgMarkGaps {
  /** not listed: no agent's card names the organization and nothing about it leaves this registry */
  listing: boolean
  /** no logo hosted here: a listed organization's mark shows its name with a plain glyph */
  logo: boolean
  /** an old logo address whose image the owner can take for the upload, while no logo is hosted */
  legacy: LegacyLogo | null
}

/** An old logo address worth offering: an absolute http(s) URL, else null (nothing to offer). */
export function legacyLogo(logoUrl: unknown): LegacyLogo | null {
  const v = typeof logoUrl === 'string' ? logoUrl.trim() : ''
  if (!v) return null
  let u: URL
  try { u = new URL(v) } catch { return null }
  if (u.protocol !== 'https:' && u.protocol !== 'http:') return null
  return { href: u.toString(), host: u.host, showable: u.protocol === 'https:' }
}

/** Which condition keeps the organization's mark from showing. Listed only on a true, as the server reads it. */
export function orgMarkGaps(facts: OrgMarkFacts | null | undefined): OrgMarkGaps {
  const listing = facts?.listed !== true
  const logo = !(typeof facts?.logo === 'string' && facts.logo.trim() !== '')
  return { listing, logo, legacy: logo ? legacyLogo(facts?.logo_url) : null }
}

/** The mark shows, with its logo: listed, and a logo hosted here. */
export function markShows(gaps: OrgMarkGaps): boolean {
  return !gaps.listing && !gaps.logo
}

/** The missing conditions, in the order they are shown. */
export function missingList(gaps: OrgMarkGaps): Array<'listing' | 'logo'> {
  const out: Array<'listing' | 'logo'> = []
  if (gaps.listing) out.push('listing')
  if (gaps.logo) out.push('logo')
  return out
}

/** The registry's own rule for a logo (routers/organizations.py: PNG or JPEG, at most 256 KB), checked before sending. */
export const LOGO_MAX_BYTES = 256 * 1024

export function logoFileProblem(file: { size: number; type: string }): 'tooBig' | 'wrongType' | null {
  if (file.size > LOGO_MAX_BYTES) return 'tooBig'
  if (!['image/png', 'image/jpeg'].includes(file.type)) return 'wrongType'
  return null
}
