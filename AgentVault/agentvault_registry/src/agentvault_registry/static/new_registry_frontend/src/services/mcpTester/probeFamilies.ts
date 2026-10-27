// §MCPTEST30 (V0535, agentvault2-b4): the MCP tester's probe families, as the console shows them.
//
// A probe row is named `<family>: <subject>` (`hygiene: discoverAgents`, `pagination: getAdminAgents`) and is recorded at
// the admin tier. The view's category rules read TOOL names, so every probe row (437 of the 1,184 rows in round 10's
// first run) fell into "Admin · Other", the bucket nobody opens, while the probes are where the tester's findings come
// from. Each family carries one sentence saying what its pass means, taken from the probe's own module docstring.
import type { Phrase } from './role'

export interface ProbeFamily {
  /** the row-name prefix before ': ' */
  id: string
  label: Phrase
  /** what a passing row of this family means */
  proves: Phrase
}

const family = (id: string, label: string, proves: string): ProbeFamily => ({
  id,
  label: { key: `mcpTester.probes.${id}.label`, fallback: label },
  proves: { key: `mcpTester.probes.${id}.proves`, fallback: proves },
})

/** In reading order: what the tester sends, what it reads back, what it races, what it trusts. */
export const PROBE_FAMILIES: readonly ProbeFamily[] = [
  family('hygiene', 'Input hygiene', 'A read tool\'s route checks the text it is handed before its SQL does.'),
  family('write_hygiene', 'Write hygiene', 'A write\'s route checks the text it stores before its database does.'),
  family('types', 'Type confusion', 'An argument of the wrong JSON type is the caller\'s error (-32602), never the server\'s.'),
  family('range', 'Value range', 'A value its type can carry but the database cannot is refused, never a 5xx.'),
  family('amount', 'Amount bounds', 'An amount no ledger can hold (negative, zero, NaN, Infinity) is refused before money moves.'),
  family('bounds', 'Page bounds', 'A zero, negative or huge page size or offset is refused or capped, never a 5xx.'),
  family('pagination', 'Pagination', 'A paginated feed is a partition: two pages of n hold exactly the rows of one page of 2n.'),
  family('list_detail', 'List and detail', 'Every id a list tool advertises opens at its detail tool.'),
  family('filter', 'Filter honesty', 'A list tool\'s filter is applied, never dropped.'),
  family('enum', 'Enum vocabulary', 'Every value a tool\'s enum filter advertises is one its route applies.'),
  family('owner_scoping', 'Owner scoping', 'Another principal asking for the runner\'s objects is refused, or sees none of their values.'),
  family('scope', 'Key scopes', 'An API key\'s scopes bound what it reaches through MCP.'),
  family('token_scope', 'Token scope', 'An operator admin\'s token is refused at its parent frame: the two registries never accept each other\'s tokens.'),
  family('revocation', 'Revocation', 'A credential stops working the moment it is revoked, on every worker.'),
  family('race', 'Unique races', 'A unique name asked for twice gives one object and one refusal, never a server error.'),
  family('overdraft', 'Overdraft', 'Two spends the balance can cover only one of: one moves, never both.'),
  family('idempotency', 'Idempotency', 'A money call retried with the same key moves money once.'),
  family('a2a_race', 'A2A settle race', 'One payment authorization pays at most once, however its settles and releases race.'),
  family('ledger', 'Ledger agreement', 'The TEG and the EventStore agree on what the run moved.'),
  family('enfprop', 'Enforcement', 'An enforced payee is refused while the enforcement stands, and an active one is not.'),
  family('commons', 'Commons ballots', 'A member\'s points count for another developer\'s work, and the close of a season tallies the members\' ballots.'),
  family('admin_effect', 'Admin actions', 'An admin action on the run\'s own object does what it says, and a read afterwards shows it.'),
  // §MCPTEST30 (V0636): the refusal an earned lifecycle keeps beside a tool's success, and three families that fell
  // into Admin · Other (zk v2 since V0612, chat since V0556, achievements)
  family('refusal', 'Refusals', 'A tool refuses the input its rule forbids, beside the success that measures it.'),
  family('earned', 'Proven successes', 'A tool did its job in a lifecycle, beside the refusal its contract pins.'),
  family('zk_v2', 'ZK attestations v2', 'A proof by the registry\'s own prover is verified once, and its replays and forgeries are refused.'),
  family('chat', 'Chat', 'A thread is read only by its participants.'),
  family('achievements', 'Achievements', 'An achievement nobody reached pays nothing: the catalog holds no entry that pays.'),
  family('mcp_protocol', 'MCP protocol', 'The MCP server\'s own protocol answers as the specification says.'),
  family('mcp_tester', 'Tester censuses', 'The tester\'s own censuses: credentials handed out, result shapes, database headroom.'),
]

const BY_ID: ReadonlyMap<string, ProbeFamily> = new Map(PROBE_FAMILIES.map((f) => [f.id, f]))
const PREFIXED = /^([a-z][a-z0-9_]*): /

/** The family a result row belongs to, or null for a tool row (`theprotocol_*`, `ui:*`) or an unknown prefix. */
export function familyOf(rowName: string): ProbeFamily | null {
  const m = PREFIXED.exec(rowName)
  if (m) return BY_ID.get(m[1]) ?? null
  // the zk v2 rows name their family with a space (zk_v2_attestations.PREFIX)
  if (rowName.startsWith('zk v2: ')) return BY_ID.get('zk_v2') ?? null
  // the enforcement-propagation rows predate the `<family>: ` convention
  if (rowName.startsWith('enfprop_')) return BY_ID.get('enfprop') ?? null
  return null
}

/** The subject of a probe row: what follows the family prefix (the whole name when there is none). */
export function probeSubject(rowName: string): string {
  if (rowName.startsWith('zk v2: ')) return rowName.slice('zk v2: '.length)
  const m = PREFIXED.exec(rowName)
  return m ? rowName.slice(m[0].length) : rowName
}

export interface ProbeRow {
  tool: string
  healthy: boolean
  skipped: boolean
  error: string | null
}

export interface FamilyTally {
  family: ProbeFamily
  total: number
  passed: number
  /** failing rows whose reason is a BUG-FIND (a defect the probe names) */
  bugFinds: number
  /** failing rows that are not BUG-FINDs */
  failed: number
  /** NOT MEASURED: the probe could not decide (an empty list, a busy registry, a missing fixture) */
  notMeasured: number
}

/** One tally per family present in the rows, in PROBE_FAMILIES order; tool rows are ignored. */
export function tallyFamilies(rows: readonly ProbeRow[]): FamilyTally[] {
  const tallies = new Map<string, FamilyTally>()
  for (const r of rows) {
    const f = familyOf(r.tool)
    if (!f) continue
    let t = tallies.get(f.id)
    if (!t) {
      t = { family: f, total: 0, passed: 0, bugFinds: 0, failed: 0, notMeasured: 0 }
      tallies.set(f.id, t)
    }
    t.total += 1
    if (r.skipped) t.notMeasured += 1
    else if (r.healthy) t.passed += 1
    else if ((r.error || '').startsWith('BUG-FIND')) t.bugFinds += 1
    else t.failed += 1
  }
  return PROBE_FAMILIES.filter((f) => tallies.has(f.id)).map((f) => tallies.get(f.id)!)
}
