/**
 * V0665 (order gwo_fbadffa68e593603d0c59b66): the people of a code change, named. The registry's read carries the proposer's agent name (proposer_name; proposer_gone only when the
 * agent itself is gone: no agent row, or revoked) and each review its reviewer's public name (reviewer_name: the display name, else "Member #<id>"), beside the ids. The page shows the NAME, and a tail only where two shown
 * names are the same (PART 1's rule: append the DID tail only where a name is not unique): an agent's tail is the end of its DID, a reviewer's is the member's number.
 * The whole DID is the element's title and what the Copy control copies. Pure: the views draw what this decides.
 */
type T = (key: string, fallback: string, params?: Record<string, any>) => string
type Rec = Record<string, any>

export interface Person {
  /** who the person is, whatever their name: the DID of an agent, "member:<id>" of a reviewer (two people with one name differ here) */
  id: string
  /** the name the registry gave, or null */
  name: string | null
  /** an agent the registry no longer finds (deleted or never carded) */
  gone: boolean
  /** the whole DID, for the title and the Copy control (agents only) */
  did: string | null
  /** the member number, for a reviewer */
  member: number | null
}

export const proposerOf = (r: Rec): Person => ({ id: String(r.proposer_did || ''), name: typeof r.proposer_name === 'string' && r.proposer_name.trim() ? r.proposer_name.trim() : null,
  gone: 'proposer_gone' in r ? r.proposer_gone === true : (typeof r.proposer_name !== 'string' && 'proposer_name' in r), did: r.proposer_did ? String(r.proposer_did) : null, member: null })

export const reviewerOf = (rv: Rec): Person => ({ id: `member:${rv.reviewer_developer_id}`, name: typeof rv.reviewer_name === 'string' && rv.reviewer_name.trim() ? rv.reviewer_name.trim() : null,
  gone: false, did: null, member: typeof rv.reviewer_developer_id === 'number' ? rv.reviewer_developer_id : null })

/** The end of a DID, for telling two agents of one name apart: its last six characters. */
export const didTail = (did: string | null): string => (did ? `…${did.slice(-6)}` : '')

/** The ids of people whose shown name is shared with someone else (different people, same words): only those get a tail. */
export function sameNames(people: Person[], t: T): Set<string> {
  const byWord = new Map<string, Set<string>>()
  for (const p of people) {
    const w = wordsOf(p, t).toLowerCase()
    if (!byWord.has(w)) byWord.set(w, new Set())
    byWord.get(w)!.add(p.id)
  }
  const out = new Set<string>()
  for (const ids of byWord.values()) if (ids.size > 1) ids.forEach((i) => out.add(i))
  return out
}

/** The words for a person with no tail: their name; an agent that is gone says so; a member with no public name is "Member #n". */
export function wordsOf(p: Person, t: T): string {
  if (p.name) return p.name
  if (p.did !== null) return p.gone ? t('codeChanges.agentGone', 'An agent that no longer exists') : t('codeChanges.agentUnnamed', 'An agent with no name')
  return t('codeChanges.member', 'Member #{id}', { id: p.member ?? '?' })
}

export interface Label { text: string; tail: string; full: string | null }
/** What to draw for a person: the words, a tail only when `shared`, and the whole DID (null for a member). */
export function labelOf(p: Person, shared: Set<string>, t: T): Label {
  const named = !!p.name
  return { text: wordsOf(p, t), tail: shared.has(p.id) && (named || p.gone) ? (p.did ? didTail(p.did) : p.member !== null ? `#${p.member}` : '') : '', full: p.did }
}
