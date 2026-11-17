/**
 * V0663 (his yes seq 3068, "empty lists that say why"): the sentences behind the EmptyReason line, pure and node-testable so
 * each list's reason is a unit test and not a screenshot. A reason names what is actually the case: which filters narrowed
 * a list, that nobody has joined yet, that the ledger has not moved since the page opened.
 */

export interface DiscoveryEmptyState {
  query: string
  registry: string                 // 'all' | 'local' | 'federated'
  frames: number                   // frames picked in the frame filter
  tags: string[]                   // the tag filters, single and multiple together
  pricing: string
  certified: boolean
  online: boolean
  quantum: boolean                 // any quantum filter set
}

/** What narrows a Discovery search, as short noun phrases a person would recognise from the filter panel. */
export function discoveryActiveFilters(s: DiscoveryEmptyState): string[] {
  const out: string[] = []
  if (s.query.trim()) out.push(`the search "${s.query.trim()}"`)
  if (s.registry === 'local') out.push('this registry only')
  else if (s.registry === 'federated') out.push('federated agents only')
  if (s.frames > 0) out.push(s.frames === 1 ? 'one frame' : `${s.frames} frames`)
  const tags = s.tags.filter((t) => t.trim())
  if (tags.length) out.push(tags.length === 1 ? `the tag "${tags[0]}"` : `${tags.length} tags`)
  if (s.pricing) out.push(`the pricing "${s.pricing}"`)
  if (s.certified) out.push('certified only')
  if (s.online) out.push('online only')
  if (s.quantum) out.push('the quantum filters')
  return out
}

const joinAnd = (xs: string[]): string => (xs.length <= 1 ? xs.join('') : `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`)

/** Why a Discovery search came back empty: the filters that were on, or that the registry lists no agents. */
export function discoveryEmptyReason(s: DiscoveryEmptyState): { kind: 'filtered' | 'none-yet'; reason: string; active: string[] } {
  const active = discoveryActiveFilters(s)
  if (active.length === 0) return { kind: 'none-yet', reason: 'No filter is on: this registry lists no agents that match the default view yet.', active }
  return {
    kind: 'filtered',
    reason: `Nothing matches ${joinAnd(active)}. Each one narrows the list; clearing them shows every agent.`,
    active,
  }
}

/** Why a bridge ledger list is empty: not connected yet, or connected and nothing has moved (mine: nothing of yours). */
export function ledgerEmptyReason(o: { connected: boolean; scope: 'all' | 'mine' | string; scopeNote?: string | null }): { kind: 'waiting' | 'quiet'; reason: string } {
  if (!o.connected) return { kind: 'waiting', reason: 'Connecting to the ledger stream: the first events arrive once it is up.' }
  if (o.scope === 'mine') {
    return { kind: 'quiet', reason: o.scopeNote || 'None of your agents has moved anything since this page opened.' }
  }
  return { kind: 'quiet', reason: 'The ledger is quiet: no event has moved since this page opened.' }
}
