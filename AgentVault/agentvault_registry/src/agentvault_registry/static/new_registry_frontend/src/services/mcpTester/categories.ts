// §MCPTEST30 (V0535, agentvault2-b4): the category of a result row that is not a tool.
//
// The view groups the All tools table by rules that read TOOL names (`theprotocol_getMyAgents` -> "Agents"). Three kinds
// of row are not tools, and each fell into one bucket: a federation suite run's 586 rows
// (`federation_suite: <group>/<test>`, 159 groups) into "Other", a strict run's 437 probe rows (`hygiene: ...`) into
// "Admin · Other", and the console suite's rows (`ui:<lifecycle>.<step>`) into "Other" until agentvault2-44 named them.
// Categories stay English, like the tool categories beside them; the visible label drops the prefix its category says.
import { familyOf, probeSubject } from './probeFamilies'

const UI_ROW = /^ui:([^.]+)\./
const FEDERATION_ROW = /^federation_suite: ([^/]+)\//

function words(id: string): string {
  return id.replace(/_/g, ' ').replace(/\s+/g, ' ').trim()
}

/** The category of a row that is not a tool, or null for a tool row (the view's own rules decide those). */
export function rowCategory(rowName: string): string | null {
  // §FESUITE (agentvault2-44): a console lifecycle row is `ui:<lifecycle>.<step>`; its category is the lifecycle
  const ui = UI_ROW.exec(rowName)
  if (ui) return 'Console · ' + ui[1].replace(/_/g, ' ')
  const fed = FEDERATION_ROW.exec(rowName)
  if (fed) {
    // "federation_handshake" reads "Federation · handshake", "cross_frame_economic_flows" "Federation · cross frame ..."
    const group = words(fed[1].replace(/^federation_/, ''))
    return 'Federation · ' + (group || words(fed[1]))
  }
  const family = familyOf(rowName)
  if (family) return 'Probe · ' + family.label.fallback
  return null
}

/** What a row shows in its table cell: the part its category does not already say (the full name stays its id). */
export function rowLabel(rowName: string): string {
  const fed = FEDERATION_ROW.exec(rowName)
  if (fed) return rowName.slice(fed[0].length)
  const ui = UI_ROW.exec(rowName)
  if (ui) return rowName.slice(ui[0].length)
  if (familyOf(rowName)) return probeSubject(rowName)
  return rowName.replace(/^theprotocol[._]/i, '')
}

// ── what a run's rows are ────────────────────────────────────────────────────────────────────────────────────────────
// §MCPTEST30 (V0536): the hero said "586 tool rows, 0 probe checks" of a federation run (its rows are the suite's
// tests), would have said the same of the console suite's steps, and "0 explicit contracts" of the suites that count no
// contracts. A row is a tool row, a probe check, a federation test or a console step.

export interface RowKinds {
  rows: number
  tools: number
  probes: number
  families: number
  federation: number
  console: number
  /** §MCPTEST30 (V0539): rows the run counted that its list does not carry (All tools read 749 beside "750 rows") */
  unlisted: number
}

/** `total` is the run's own count, so the parts add up to it: a row the summary counts and the list lacks (the cloud-op
 *  token-scope row before V0536) is counted as a tool row. */
export function rowKinds(names: readonly string[], total: number): RowKinds {
  let probes = 0
  let federation = 0
  let consoleSteps = 0
  const families = new Set<string>()
  for (const n of names) {
    const f = familyOf(n)
    if (f) {
      probes += 1
      families.add(f.id)
    } else if (FEDERATION_ROW.test(n)) {
      federation += 1
    } else if (UI_ROW.test(n)) {
      consoleSteps += 1
    }
  }
  const rows = Math.max(total, names.length)
  return { rows, tools: Math.max(0, rows - probes - federation - consoleSteps), probes, families: families.size,
    federation, console: consoleSteps, unlisted: rows - names.length }
}

export interface CountPhrase { key: string; fallback: string; params: Record<string, number> }

/** The non-zero kinds, each in its own words (one and many are separate keys: a parameter cannot carry a plural). */
export function rowKindPhrases(k: RowKinds): CountPhrase[] {
  const out: CountPhrase[] = []
  if (k.tools > 0) {
    out.push(k.tools === 1
      ? { key: 'mcpTester.rows.tool', fallback: '1 tool row', params: {} }
      : { key: 'mcpTester.rows.tools', fallback: '{n} tool rows', params: { n: k.tools } })
  }
  if (k.probes > 0) {
    out.push(k.probes === 1
      ? { key: 'mcpTester.rows.probe', fallback: '1 probe check in 1 family', params: {} }
      : k.families === 1
        ? { key: 'mcpTester.rows.probesOneFamily', fallback: '{n} probe checks in 1 family', params: { n: k.probes } }
        : { key: 'mcpTester.rows.probes', fallback: '{n} probe checks in {families} families',
            params: { n: k.probes, families: k.families } })
  }
  if (k.federation > 0) {
    out.push(k.federation === 1
      ? { key: 'mcpTester.rows.federationTest', fallback: '1 federation test', params: {} }
      : { key: 'mcpTester.rows.federationTests', fallback: '{n} federation tests', params: { n: k.federation } })
  }
  if (k.console > 0) {
    out.push(k.console === 1
      ? { key: 'mcpTester.rows.consoleStep', fallback: '1 console step', params: {} }
      : { key: 'mcpTester.rows.consoleSteps', fallback: '{n} console steps', params: { n: k.console } })
  }
  if (k.unlisted > 0) {
    out.push(k.unlisted === 1
      ? { key: 'mcpTester.rows.unlisted', fallback: '1 not in the list', params: {} }
      : { key: 'mcpTester.rows.unlistedMany', fallback: '{n} not in the list', params: { n: k.unlisted } })
  }
  return out
}

/** §MCPTEST30 (V0539): the Probes tab's count line, each count in its own words ("1 FAMILIES · 2 CHECKS"). */
export function probeMetaPhrases(families: number, checks: number, bugFinds: number): CountPhrase[] {
  return [
    families === 1
      ? { key: 'mcpTester.probes.family', fallback: '1 family', params: {} }
      : { key: 'mcpTester.probes.families', fallback: '{n} families', params: { n: families } },
    checks === 1
      ? { key: 'mcpTester.probes.check', fallback: '1 check', params: {} }
      : { key: 'mcpTester.probes.checks', fallback: '{n} checks', params: { n: checks } },
    { key: 'mcpTester.probes.bugFinds', fallback: '{n} BUG-FIND', params: { n: bugFinds } },
  ]
}
