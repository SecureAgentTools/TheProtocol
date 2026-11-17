import { config } from '@/config'

/**
 * What UserAvatar needs to draw an agent as its owner dressed it (agentvault2-56, 2026-10-23: the agent page
 * drew SYBIL as a letter, missing the custom avatar SYBIL and others have). One rule for every view that shows an agent's face: Discovery's agent view and the agent page.
 *
 * The flare arrives in two shapes (§FLARESHOP): nested in the card (`card_data.flare`, which Discovery's enrichment keeps
 * as `rawCardData.flare`) and hoisted to the top level of a discover row. Either may be the one present, so the nested
 * value wins and the hoisted one fills in.
 */
export function agentAvatarUser(a: any): Record<string, any> | null {
  if (!a) return null
  const f: any = a.rawCardData?.flare || a.card_data?.flare || {}
  const pick = (nested: any, hoisted: any) => nested ?? hoisted ?? null
  return {
    name: a.name,
    did: a.did || a.agent_did,
    flare_tier: pick(f.tier, a.flare_tier),
    flare_granted_at: pick(f.granted_at, a.flare_granted_at),
    flare_id: pick(f.id, a.flare_id),
    flare_display_name: pick(f.display_name, a.flare_display_name),
    flare_tagline: pick(f.tagline, a.flare_tagline),
    flare_logo_url: pick(f.logo_url, a.flare_logo_url),
    flare_link_url: pick(f.link_url, a.flare_link_url),
    flare_cause: pick(f.cause, a.flare_cause),
    flare_accent_color: pick(f.accent_color, a.flare_accent_color),
    flare_encirclement_variant: pick(f.encirclement_variant, a.flare_encirclement_variant),
    flare_encirclement_overlay: pick(f.encirclement_overlay, a.flare_encirclement_overlay),
    flare_corner_variant: pick(f.corner_variant, a.flare_corner_variant),
    bears_corner_flare: !!(f.bears_corner_flare ?? a.bears_corner_flare),
    bears_encirclement_flare: !!(f.bears_encirclement_flare ?? a.bears_encirclement_flare),
    selected_corner_flare: pick(f.selected_corner_flare, a.selected_corner_flare),
    selected_encirclement_flare: pick(f.selected_encirclement_flare, a.selected_encirclement_flare),
  }
}

/** The address the agent's card names for its picture, as written (its owner's edit field shows it). Never an image
 *  source: draw it through agentAvatarUrl or cardIconSrc. */
export function rawCardIcon(a: any): string | null {
  const cd: any = a?.rawCardData || a?.card_data || {}
  const v = cd.iconUrl || cd.icon_url || a?.icon_url
  return typeof v === 'string' && v.trim() ? v : null
}

/** A short, stable version of an icon address, so a card that names another icon gets another image address and the
 *  browser does not show the one it cached (FNV-1a, 32 bit). */
function iconVersion(address: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < address.length; i++) {
    h ^= address.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(36)
}

/**
 * V0662, item 14: where the console draws a card's icon from. Never the address the card names (every reader's
 * browser dialled it, and whoever runs that host learned who looked): the registry this console talks to fetched it
 * once through its outbound guard and serves it from its own origin (GET /agent-cards/{did}/icon). Null, with no
 * icon or no DID to ask by, draws the initial. services/cardIconSites.test.ts keeps every view on this.
 */
export function cardIconSrc(did: unknown, iconUrl: unknown): string | null {
  if (typeof iconUrl !== 'string' || !iconUrl.trim()) return null
  if (typeof did !== 'string' || !/^did:[a-z0-9]+:\S+$/i.test(did)) return null
  return `${config.api.baseURL}/agent-cards/${encodeURIComponent(did)}/icon?v=${iconVersion(iconUrl.trim())}`
}

/** The agent's own picture, from whichever place its card or its row carries it, drawn from the registry; null draws
 *  the initial. */
export function agentAvatarUrl(a: any): string | null {
  const cd: any = a?.rawCardData || a?.card_data || {}
  return cardIconSrc(a?.did || a?.agent_did || cd.did, rawCardIcon(a))
}
