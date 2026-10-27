/**
 * §TWOAGENT G1 household/V0436 — what a counterparty IS, in the three forms the server sends: a developer (by id), an
 * agent (by DID) or a principal on a PEER registry (`ptype: 'remote'`, named by its ADDRESS, `remote_key`). The
 * thread header, the inbox row and the block door each asked this by hand, and each read a remote counterparty as a
 * developer with no id: the identity looked up nothing and the block answered 422.
 */
export interface CounterpartyLike {
  ptype?: string | null
  developer_id?: number | null
  agent_did?: string | null
  remote_key?: string | null
}

export type IdentityKind = 'developer' | 'agent' | 'remote'

export interface BlockTarget {
  ptype: IdentityKind
  developer_id?: number
  agent_did?: string
  remote_key?: string
}

/** The kind the identity component renders: a remote principal is its own kind (no local lookup exists for it). */
export function identityKind(ptype: string | null | undefined): IdentityKind {
  if (ptype === 'agent') return 'agent'
  if (ptype === 'remote') return 'remote'
  return 'developer'
}

/** The id the identity component resolves: a DID, a developer id, or a peer registry principal's address. */
export function identityPid(cp: CounterpartyLike | null | undefined): string | number {
  if (!cp) return ''
  if (cp.ptype === 'agent') return cp.agent_did || ''
  if (cp.ptype === 'remote') return cp.remote_key || ''
  return cp.developer_id ?? ''
}

/** The body of POST/DELETE /chat/blocks for this counterparty, or null when the row does not carry what a block
 *  needs (never send a request that can only answer 422). */
export function blockTargetFor(cp: CounterpartyLike | null | undefined): BlockTarget | null {
  if (!cp) return null
  if (cp.ptype === 'agent') return cp.agent_did ? { ptype: 'agent', agent_did: cp.agent_did } : null
  if (cp.ptype === 'remote') return cp.remote_key ? { ptype: 'remote', remote_key: cp.remote_key } : null
  if (cp.ptype === 'developer') return cp.developer_id != null ? { ptype: 'developer', developer_id: cp.developer_id } : null
  return null
}

export interface RemoteAddress {
  /** The one form the server keys a peer-registry principal by (lower-case, `id@scheme://host`). */
  key: string
  id: string
  origin: string
  isAgent: boolean
}

/**
 * §TWOAGENT G1 (V0437) — an ADDRESS on another registry, as a person types it: `name@https://their.registry`,
 * `name@their.registry`, `@name@their.registry` or `did:…@https://their.registry`. Split on the LAST '@' (the server's
 * rule), so a handle can never smuggle a second address. A bare handle is NOT an address (null): it is looked up here.
 */
export function parseRemoteAddress(raw: string | null | undefined): RemoteAddress | null {
  const s = String(raw || '').trim().replace(/^@+/, '')
  const at = s.lastIndexOf('@')
  if (at <= 0 || at === s.length - 1) return null
  const id = s.slice(0, at).replace(/^@+/, '').trim()
  let base = s.slice(at + 1).trim().replace(/\/+$/, '')
  if (!id || !base) return null
  if (!/^https?:\/\//i.test(base)) base = `https://${base}`
  let origin: string
  try {
    const u = new URL(base)
    if (!u.hostname.includes('.')) return null
    origin = `${u.protocol.toLowerCase()}//${u.host.toLowerCase()}`
  } catch {
    return null
  }
  return { key: `${id.toLowerCase()}@${origin}`, id, origin, isAgent: /^did:/i.test(id) }
}

/**
 * §TWOAGENT G1 (V0437) — the server's consent question before an agent's OWNER is announced to the other side of a
 * cross-registry thread: a 409 whose detail leads with `household_join_confirm:`. Returns the sentence to show, or null.
 */
export function householdJoinPrompt(err: any): string | null {
  if (!err || Number(err.status) !== 409) return null
  const d = String(err.detail || '')
  const code = 'household_join_confirm:'
  return d.startsWith(code) ? d.slice(code.length).trim() : null
}
