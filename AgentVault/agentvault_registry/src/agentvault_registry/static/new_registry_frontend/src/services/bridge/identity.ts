/**
 * services/bridge/identity.ts — §BRIDGE R9. ONE classifier for "what is this
 * string, and what may I do with it?", asked everywhere a party is handled.
 *
 * WHY THIS EXISTS (measured, 2026-08-19, not theorised):
 * the bridge asked `GET /agents/by-did/342df814-cbd0-4ab2-8614-79a57e06a5c4` —
 * a bare UUID no party field on this network ever carries — and the fleet log
 * offered that same UUID as an "open this agent" door, so the Commander clicked
 * it and got *"Agent card not found"*. R8 tried to fix it inside `toVerb` alone
 * and FAILED TWICE OVER: once because a ternary's false branch swallowed the
 * `|| aggregate_id` fallback and re-admitted the UUID, and once because
 * `partyDids()` and the stage's resolver still collected and queried it. A rule
 * enforced in one of N places is not enforced (§FANOUTFIX).
 *
 * So: every consumer asks THIS module, and the questions are separated —
 *   - `key`     : may I use it to answer "is this mine?"   (yes, for anything)
 *   - `canOpen` : may I hand it to a card / route / by-did (DIDs only)
 *   - `canPay`  : may I aim money at it                    (DIDs, never system)
 * A UUID is a perfectly good identity for MATCHING and a terrible one for a
 * NETWORK CALL, and conflating the two is what put a UUID in a treasury dialog.
 */

export type IdentityKind = 'did' | 'wallet' | 'uuid' | 'system' | 'none'

export interface Identity {
  kind: IdentityKind
  /** The value as it arrived (trimmed), or null. */
  raw: string | null
  /** Set only for `did` — the ONLY value that may reach a by-did lookup. */
  did: string | null
  /** Lowercase matching key; usable for set membership, never for a request. */
  key: string | null
  /** Short human-facing text. Never a bare 36-char UUID. */
  label: string
  /** May be handed to an agent card / detail modal / route. */
  canOpen: boolean
  /** May be the target of a money action. */
  canPay: boolean
}

const DID_RE = /^did:[a-z0-9]+:/i
// §TRUSTCHAIN P4.6 (2026-09-12) — a DEVELOPER WALLET is a DID on the wire and not an agent.
// The backend mints `did:theprotocol:<email with @ -> _at_>` as the developer's TEG account
// (identifiers.developer_teg_did), so it appears as a payer/payee on real transfers; asking
// `/agents/by-did/` for it is a guaranteed 404 (measured on the dashboard, §MARKSURFACES). It
// may receive money; it may not be opened as an agent.
const WALLET_RE = /^did:theprotocol:[^:\s]+_at_[^:\s]+$/i
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** System accounts are real parties on the wire; they are simply not agents. */
const SYSTEM_PREFIXES = ['teg:system:', 'agora-gateway-', 'system:']
const SYSTEM_SUFFIXES = ['-treasury', '_treasury']

export function isDidLike(v: unknown): v is string {
  return typeof v === 'string' && DID_RE.test(v.trim())
}

export function isUuidLike(v: unknown): boolean {
  return typeof v === 'string' && UUID_RE.test(v.trim())
}

export function isSystemAccount(v: unknown): boolean {
  if (typeof v !== 'string') return false
  const s = v.trim().toLowerCase()
  if (!s) return false
  return SYSTEM_PREFIXES.some(p => s.startsWith(p)) || SYSTEM_SUFFIXES.some(p => s.endsWith(p))
}

/** `did:theprotocol:342df814-…a5c4` -> `did:theproto…a5c4`; a UUID -> `#342df814`. */
export function shortLabel(raw: string, kind: IdentityKind): string {
  const s = raw.trim()
  if (kind === 'system') {
    // `teg:system:fee_collector` reads better as its tail than as its scheme.
    const tail = s.split(':').pop() || s
    return tail.replace(/[_-]+/g, ' ')
  }
  if (kind === 'uuid') return `#${s.slice(0, 8)}`
  if (s.length <= 24) return s
  return `${s.slice(0, 14)}…${s.slice(-4)}`
}

const NONE: Identity = {
  kind: 'none', raw: null, did: null, key: null, label: '', canOpen: false, canPay: false,
}

export function classifyIdentity(raw: unknown): Identity {
  if (typeof raw !== 'string') return NONE
  const s = raw.trim()
  if (!s) return NONE
  const key = s.toLowerCase()

  if (isSystemAccount(s)) {
    return { kind: 'system', raw: s, did: null, key, label: shortLabel(s, 'system'), canOpen: false, canPay: false }
  }
  if (WALLET_RE.test(s)) {
    // A developer's wallet: payable, never an agent door, and never labelled with the email it encodes.
    return { kind: 'wallet', raw: s, did: s, key, label: 'developer wallet', canOpen: false, canPay: true }
  }
  if (DID_RE.test(s)) {
    return { kind: 'did', raw: s, did: s, key, label: shortLabel(s, 'did'), canOpen: true, canPay: true }
  }
  if (UUID_RE.test(s)) {
    // Identity yes, door no. This is the exact value that 404'd.
    return { kind: 'uuid', raw: s, did: null, key, label: shortLabel(s, 'uuid'), canOpen: false, canPay: false }
  }
  // Anything else (human-readable ids, names): matchable, not a door.
  return { kind: 'none', raw: s, did: null, key, label: shortLabel(s, 'none'), canOpen: false, canPay: false }
}

/** The DID, or null — the ONLY safe argument for `/agents/by-did/{…}`. */
export function didOrNull(raw: unknown): string | null {
  const id = classifyIdentity(raw)
  return id.kind === 'did' ? id.did : null
}

/** First openable DID out of several candidates (row -> door). */
export function firstOpenable(...candidates: unknown[]): string | null {
  for (const c of candidates) {
    const d = didOrNull(c)
    if (d) return d
  }
  return null
}
