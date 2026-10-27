/**
 * §FESUITE V0595 (his word 2026-10-11, "also correct the avt prose in the docs"): a docs source marks the parts that
 * apply only where a registry switch is on, and a page shows them only where THIS registry says that switch is on.
 *
 *   <!-- on: staking_rewards -->
 *   | a table row | or a paragraph, a list item, a whole section, a line inside a code fence |
 *   <!-- /on -->
 *
 * or inside one line: `... reputation and federation<!-- on: fiat_onramp -->, and the euro purchase lane<!-- /on -->.`
 *
 * The public pages hold their words to the frame's switches (lifecycle 51): where staking rewards are off, a reward rate,
 * a tier read or a distributor is not this registry's to describe, so its parts are left out and the page says which
 * switch left them out. A switch this registry did not say (its configuration unread, or a field it does not publish)
 * shows its parts nowhere and is reported apart: a page never says "off" for a switch it could not read.
 *
 * The markers are always removed, so a renderer with html: false never prints one, and a line a block took whole leaves
 * no line behind, so a table keeps its rows either way. Blocks do not nest; switchBlockProblems() is the source gate
 * (every marker names a known switch, every block closes, none nests).
 */

/** The switches a doc may name, each with the registry-config field that says it and the setting an operator reads. */
export const DOC_SWITCHES = {
  staking_rewards: { field: 'staking_rewards_enabled', env: 'STAKING_REWARDS_ENABLED' },
  agora_distributions: { field: 'agora_distributions_enabled', env: 'AGORA_DISTRIBUTIONS_ENABLED' },
  fiat_onramp: { field: 'fiat_onramp_enabled', env: 'FIAT_ONRAMP_ENABLED' },
} as const
export type DocSwitch = keyof typeof DOC_SWITCHES

/** What this registry said: true on, false off. A switch it did not say is absent. An `on` part shows where its switch
 *  is on; an `off` part (`<!-- off: name -->...<!-- /off -->`) shows where it is off: the words that stand in for an
 *  `on` part, such as a count without the row the `on` part holds. A switch not said shows neither. */
export type KnownSwitches = Partial<Record<DocSwitch, boolean>>

export interface GatedSource {
  /** the source with every marker gone and the parts this registry does not run left out */
  text: string
  /** switches this registry says are off whose parts were left out */
  leftOut: DocSwitch[]
  /** switches whose parts were left out because this registry did not say them (an unread configuration) */
  unread: DocSwitch[]
}

const BLOCK = /<!--\s*(on|off):\s*([a-z_]+)\s*-->([\s\S]*?)<!--\s*\/\1\s*-->/g
const ANY_MARKER = /<!--\s*(?:(on|off):\s*([a-z_]*)|\/(on|off))\s*-->/g
/** stands where a block was, so a line a block took whole can be told from a line that was blank in the source */
const HOLE = '\u0000'
const HOLES = /\u0000/g

const isDocSwitch = (name: string): name is DocSwitch => Object.prototype.hasOwnProperty.call(DOC_SWITCHES, name)

/** The switches as this registry said them, from its public configuration; nothing at all from a read that failed. */
export function knownSwitches(cfg: Record<string, unknown> | null | undefined, readOk: boolean): KnownSwitches {
  const known: KnownSwitches = {}
  if (!readOk || !cfg) return known
  for (const name of Object.keys(DOC_SWITCHES) as DocSwitch[]) {
    const v = cfg[DOC_SWITCHES[name].field]
    if (typeof v === 'boolean') known[name] = v
  }
  return known
}

/** The source as this registry's page shows it. */
export function applySwitchBlocks(source: string, known: KnownSwitches): GatedSource {
  const leftOut = new Set<DocSwitch>()
  const unread = new Set<DocSwitch>()
  if (!source.includes('<!--')) return { text: source, leftOut: [], unread: [] }
  let out = source.replace(BLOCK, (_m, kind: 'on' | 'off', name: string, body: string) => {
    // an unknown name is a source error the gate refuses; at runtime its part hides and names nothing
    if (!isDocSwitch(name)) return HOLE
    const said = known[name]
    if (said === undefined) { unread.add(name); return HOLE }
    if ((kind === 'on') === said) return HOLE + body + HOLE
    // an `on` part this registry runs off is left out and named; an `off` part (the words that stand in for one where
    // the switch is off, a count that leaves a row out) simply does not show where the switch is on
    if (kind === 'on') leftOut.add(name)
    return HOLE
  })
  // a stray marker (an authoring error the gate refuses) is never printed
  out = out.replace(ANY_MARKER, '')
  out = out
    .split('\n')
    .filter((line) => !(line.includes(HOLE) && line.replace(HOLES, '').trim() === ''))
    .join('\n')
    .replace(HOLES, '')
  return { text: out, leftOut: [...leftOut].sort(), unread: [...unread].sort() }
}

/** Every authoring problem in a source's markers; an empty list is a source the pages can trust. */
export function switchBlockProblems(source: string): string[] {
  const problems: string[] = []
  const lineOf = (at: number) => source.slice(0, at).split('\n').length
  // the doc sources hold no other comment: a renderer with html: false would print one, so anything else is an error
  for (const c of source.matchAll(/<!--[\s\S]*?(?:-->|$)/g)) {
    if (!/^<!--\s*(?:(?:on|off):\s*[a-z_]+|\/(?:on|off))\s*-->$/.test(c[0])) problems.push(`line ${lineOf(c.index ?? 0)}: a comment that is not a switch marker: ${c[0].slice(0, 60)}`)
  }
  let open: { kind: string; name: string; at: number } | null = null
  for (const m of source.matchAll(ANY_MARKER)) {
    const line = lineOf(m.index ?? 0)
    if (m[3]) {
      if (!open) problems.push(`line ${line}: a closing marker with no block open`)
      else if (open.kind !== m[3]) problems.push(`line ${line}: "/${m[3]}" closes the "${open.kind}" block that opened on line ${open.at}`)
      open = null
      continue
    }
    const kind = m[1]
    const name = m[2] || ''
    if (!isDocSwitch(name)) problems.push(`line ${line}: "${name}" is not a switch a doc may name (${Object.keys(DOC_SWITCHES).join(', ')})`)
    if (open) problems.push(`line ${line}: a block opened inside the block that opened on line ${open.at} (blocks do not nest)`)
    open = { kind, name, at: line }
  }
  if (open) problems.push(`line ${open.at}: the block for "${open.name}" never closes`)
  return problems
}

/** `off` parts in a source the docs site also renders: it shows every marker's content as written, so an `off` part
 *  would stand there beside the `on` part it replaces (docs-site/sync-content.mjs strips the markers, keeps the parts). */
export const offBlocks = (source: string): number => [...source.matchAll(/<!--\s*off:/g)].length

/** The settings an operator reads for a list of switches, for the page's own sentence. */
export const switchEnvNames = (switches: DocSwitch[]): string[] => switches.map((s) => DOC_SWITCHES[s].env)
