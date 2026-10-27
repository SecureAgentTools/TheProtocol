/**
 * §SHOWN P3 (2026-08-31) — WHAT WAS ON THE SCREEN, hashed.
 *
 * 🔴 THE PROBLEM THIS SOLVES. `challenge_presentations` records `render_version`
 * and `locale`. Those identify the TEMPLATE, not the INSTANCE — they cannot tell
 * "2.00 BVT to Acme" from "2.00 AVT to Acme". That is §FOREIGNACT exactly: the
 * ledgers were right and the label lied, and a human authorised something other
 * than what they read. A chain without this proves only that the server was
 * self-consistent, which is the easy half.
 *
 * 🔴 WHY IT HASHES RESOLVED VALUES AND NOT DOM TEXT. The plan allowed either. DOM
 * text is not stabilisable here for a decisive reason: the decision card contains a
 * COUNTDOWN. Hashing everything painted would produce a different hash every second,
 * and a hash that flaps is worse than none — it trains everyone to ignore the
 * mismatch that matters. So the unit of hashing is the ordered list of FACT LINES
 * the renderer was handed: post-i18n, post-number-formatting, post-unit-resolution,
 * and free of chrome that is not a fact.
 *
 * 🔴 THE DISCIPLINE THAT MAKES IT TRUE. `buildPresentation()` produces the lines,
 * the component RENDERS those same lines, and `presentationHash()` hashes that same
 * array. There is no second description of "what we showed" that could drift from
 * the first. If a renderer ever paints a fact this function did not return, the hash
 * stops meaning what it claims — so panes render `lines`, never `facts` directly.
 *
 * ⚠ Trust level: CLIENT-ASSERTED, always, and stored and rendered as such (R5). It
 * is still decisive — a mismatch between what the server would render and what the
 * client says it rendered IS the finding — but it must never sit indistinguishably
 * beside a server-attested timestamp in a chain whose whole claim is provable intent.
 */

export interface PresentedLine {
  /** Stable machine key — never translated, so a locale change moves `label`/`value`, not this. */
  key: string
  /** Exactly the label painted, in the viewer's locale. */
  label: string
  /** Exactly the value painted, including its unit — or the honest absence of one. */
  value: string
}

// ASCII unit/record separators, built by code point so this source stays plain text.
// Control characters ON PURPOSE: they cannot occur in a rendered label or value, so
// no line can impersonate a line boundary. A comma-joined hash would be forgeable by
// a counterparty name that contains a comma.
const US = String.fromCharCode(31)
const RS = String.fromCharCode(30)

/** The exact bytes that get hashed. Exported so a server-side re-render can be compared. */
export function canonicalPresentation(lines: PresentedLine[], locale: string): string {
  return [
    `locale${US}${locale}`,
    ...lines.map(l => `${l.key}${US}${l.label}${US}${l.value}`),
  ].join(RS)
}

/**
 * sha256 of the canonical presentation, hex.
 *
 * Returns null when the platform cannot compute one (`crypto.subtle` is undefined
 * outside a secure context). NULL IS THE HONEST ANSWER — the receipt then says the
 * client could not attest what it showed, which is a different and weaker claim than
 * silence, and a very different one from a hash that happens to match.
 */
export async function presentationHash(lines: PresentedLine[], locale: string): Promise<string | null> {
  const subtle = (globalThis.crypto && (globalThis.crypto as any).subtle) || null
  if (!subtle) return null
  try {
    const bytes = new TextEncoder().encode(canonicalPresentation(lines, locale))
    const digest = await subtle.digest('SHA-256', bytes)
    return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('')
  } catch {
    return null
  }
}

/** The version of THIS renderer. Bumped when the set or order of lines changes —
 *  a hash mismatch across a render_version boundary is expected, not a finding.
 *  /2 (§MEMBERSHIP, 2026-10-02): a member's binding vote or commons ballot is shown with what it decides (the
 *  proposal and the choice, or the season and the points), and the verb falls back to the facts' `action`. */
export const RENDER_VERSION = 'cockpit-decision/2'

type T = (key: string, fallback: string) => string

/**
 * The lines a human is shown for one decision, in paint order.
 *
 * §FACTS2 makes `currency` present on new challenges and absent on legacy ones. The
 * unit-unrecorded case is rendered as a VALUE here, not omitted, because "this
 * amount declared no unit" is itself part of what the human saw and has to be part
 * of what they are held to.
 */
export function buildPresentation(facts: Record<string, any>, t: T): PresentedLine[] {
  const lines: PresentedLine[] = []
  const push = (key: string, label: string, value: string | null | undefined) => {
    if (value === null || value === undefined || value === '') return
    lines.push({ key, label, value })
  }

  push('verb', t('cockpit.shown.action', 'Action'), String(facts.verb || facts.action_type || facts.action || ''))

  // §MEMBERSHIP: a binding vote (kind governance.vote) or a commons ballot (kind commons.ballot) carries what it
  // decides; the member signs exactly these lines, so each one is part of what they are held to. Only those two
  // kinds get them: a money decision renders exactly the lines it always had.
  const governing = facts.kind === 'governance.vote' || facts.kind === 'commons.ballot'
  if (governing && (facts.proposal_title || facts.proposal_id)) {
    const id = facts.proposal_id !== undefined && facts.proposal_id !== null ? `#${facts.proposal_id}` : ''
    push('proposal', t('cockpit.shown.proposal', 'Proposal'), [id, facts.proposal_title].filter(Boolean).join(' '))
  }
  if (governing && (facts.choice === 'for' || facts.choice === 'against')) {
    push('choice', t('cockpit.shown.choice', 'Your vote'),
         facts.choice === 'for' ? t('cockpit.shown.choiceFor', 'For') : t('cockpit.shown.choiceAgainst', 'Against'))
  }
  if (governing && facts.season_id !== undefined && facts.season_id !== null) {
    push('season', t('cockpit.shown.season', 'Commons season'), [`#${facts.season_id}`, facts.season_title].filter(Boolean).join(' '))
  }
  if (governing && facts.total_points !== undefined && facts.total_points !== null) {
    push('points', t('cockpit.shown.points', 'Points given'), String(facts.total_points))
  }
  if (governing) {
    push('weight', t('cockpit.shown.weight', 'Vote weight'), facts.weight ? String(facts.weight) : null)
    push('registry', t('cockpit.shown.registry', 'Registry'), facts.registry ? String(facts.registry) : null)
  }

  const amount = facts.amount
  if (amount !== null && amount !== undefined && amount !== '') {
    const ccy = String(facts.currency || '').trim()
    push('amount', t('cockpit.shown.amount', 'Amount'),
         ccy ? `${amount} ${ccy}` : `${amount} ${t('cockpit.decisions.unitUnrecorded', 'unit unrecorded')}`)
  }

  if ('counterparty_did' in facts) {
    const cp = facts.counterparty_did
    push('counterparty', t('cockpit.shown.counterparty', 'Counterparty'),
         cp ? String(cp) : t('cockpit.shown.noCounterparty', 'none at this stage'))
  }
  push('counterparty_home', t('cockpit.shown.counterpartyHome', 'Counterparty home'),
       facts.counterparty_home_registry ? String(facts.counterparty_home_registry) : null)
  push('action_ref', t('cockpit.shown.reference', 'Reference'), facts.action_ref ? String(facts.action_ref) : null)
  push('agent', t('cockpit.shown.agent', 'Acting agent'), facts.agent_did ? String(facts.agent_did) : null)
  push('mandate', t('cockpit.shown.mandate', 'Under mandate'), facts.mandate_id ? String(facts.mandate_id) : null)
  return lines
}
