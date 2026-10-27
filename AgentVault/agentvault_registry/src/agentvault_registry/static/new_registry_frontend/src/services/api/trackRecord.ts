/**
 * §AGENTDISC #188 — track-record attestation client + IN-BROWSER verification.
 *
 * Two independent proofs per engagement receipt:
 *   1. Digest binding — recompute sha256 over the canonical `guild.receipt.v1`
 *      subset and compare against the digest listed on the discovery row AND the
 *      one the receipt endpoint serves. Canonical convention mirrors the backend
 *      (python json.dumps sort_keys=True, separators=(',',':'), ensure_ascii):
 *      recursive key sort + JSON.stringify + \uXXXX escape of every UTF-16 code
 *      unit >= 0x7f — the SAME cross-language contract §VCSIGN proved byte-equal
 *      (ContractAttestationModal).
 *   2. Ed25519 attestation — verify the work-credential bundle signature against
 *      the registry's published attestation-signer pubkey via SubtleCrypto
 *      Ed25519. Browsers without Ed25519 in WebCrypto report 'unsupported'
 *      honestly (the digest binding still stands on its own).
 */
import { apiClient } from './client'

export interface TrackRecordCompact {
  jobs: number
  stars: number | null
  five_star: number
  on_time_met: number
  on_time_of: number
  traveled: number
  cross_registry: number
  disputes: number
  open_disputes?: number
  lost_disputes?: number
  last_verified_at: string | null
}

/**
 * §BRIDGE R13 #8 — the ONE place that turns the endpoint's `summary` into the
 * compact shape every consumer reads.
 *
 * `GET /agents/{did}/track-record` answers with `summary.jobs_verified`,
 * `summary.cross_registry_jobs`, `summary.disputes.{open,lost}` and so on, while
 * `TrackRecordCompact`, `earnedMarks()` and `TopologyHoverLabel` all read
 * `jobs`, `cross_registry`, `open_disputes`. The file already carries a warning
 * about precisely this: an earlier cut spelled one name in one place and the
 * other elsewhere, and the globe silently rendered no earned mark at all. One
 * fact, one name, one converter.
 */
export function compactFromSummary(resp: any): TrackRecordCompact | null {
  const sm = resp?.summary ?? resp
  if (!sm || typeof sm !== 'object') return null
  const n = (v: unknown, d = 0): number => { const x = Number(v); return Number.isFinite(x) ? x : d }
  const vol = Array.isArray(sm.volume) ? sm.volume[0] : null
  return {
    jobs: n(sm.jobs_verified),
    stars: sm.avg_stars === null || sm.avg_stars === undefined ? null : n(sm.avg_stars, 0),
    five_star: n(sm.five_star),
    on_time_met: n(sm.on_time?.met),
    on_time_of: n(sm.on_time?.of),
    traveled: n(sm.traveled_jobs),
    cross_registry: n(sm.cross_registry_jobs),
    disputes: n(sm.disputes?.total),
    open_disputes: n(sm.disputes?.open),
    lost_disputes: n(sm.disputes?.lost),
    last_verified_at: sm.last_verified_at ?? null,
    // Extra fields the hover label reads. Harmless to the compact consumers.
    ...(vol ? { volume_total: vol.total, volume_currency: vol.currency } : {}),
    ...(sm.distinct_posters !== undefined ? { distinct_posters: n(sm.distinct_posters) } : {}),
  } as TrackRecordCompact
}

// ─── §AGENTDISC #190 — earned marks (ledger-derived, never purchasable) ──────
//
// HARD RULE: earned marks and cosmetic flares are DISTINCT visual classes. These
// derive purely from the registry-attested track record; the flare system (paid
// cosmetics) must never imitate them and vice versa. Thresholds start at ONE
// verified job — the cliff that matters is zero vs proven; most agents have zero.

export type EarnedTier =
  'proven' | 'established' | 'seasoned' | 'veteran'
  | 'expert' | 'master' | 'sovereign' | null

// §MARKCOLLAR-2 (2026-08-16) — SEVEN steps. Three meant a 12-job agent and a
// 49-job agent wore the same mark for most of a working life; six still left a
// long flat stretch at the top. The ladder is front-loaded (zero-to-one is the
// cliff that matters most) and then keeps rewarding endurance, with headroom
// above anything on the network today so the top tier stays worth reaching.
// `rank` drives the edge ticks, so the tier survives monochrome; the numeral
// on the mark always states the exact count, so nobody has to decode a hue.
export const EARNED_TIERS: {
  tier: Exclude<EarnedTier, null>; min: number; rank: number; label: string
}[] = [
  { tier: 'sovereign',   min: 250, rank: 7, label: 'Sovereign' },
  { tier: 'master',      min: 100, rank: 6, label: 'Master' },
  { tier: 'expert',      min: 50,  rank: 5, label: 'Expert' },
  { tier: 'veteran',     min: 25,  rank: 4, label: 'Veteran' },
  { tier: 'seasoned',    min: 10,  rank: 3, label: 'Seasoned' },
  { tier: 'established', min: 5,   rank: 2, label: 'Established' },
  { tier: 'proven',      min: 1,   rank: 1, label: 'Proven' },
]

/** Ascending ladder — what a legend should walk a reader through. */
export const EARNED_TIERS_ASC = [...EARNED_TIERS].reverse()

export interface EarnedMarks {
  tier: EarnedTier
  /** 1..6, drives the pip count so the tier survives monochrome and xs sizes */
  rank: number
  /** verified jobs, shown as the numeral on the collar */
  jobs: number
  /** holds at least one cross-registry verified engagement (trust that travels) */
  cross: boolean
  /** currently in an OPEN guild dispute — rendered honestly, not hidden */
  disputedOpen: boolean
  /** a dispute was LOST — permanent on the record, quieter than an open one */
  disputedLost: boolean
}

export function earnedMarks(tr: TrackRecordCompact | null | undefined): EarnedMarks {
  const none: EarnedMarks = {
    tier: null, rank: 0, jobs: 0, cross: false, disputedOpen: false, disputedLost: false,
  }
  if (!tr || !tr.jobs) return none
  const step = EARNED_TIERS.find(s => tr.jobs >= s.min)
  if (!step) return none
  return {
    tier: step.tier,
    rank: step.rank,
    jobs: tr.jobs,
    cross: (tr.cross_registry || 0) > 0,
    disputedOpen: (tr.open_disputes || 0) > 0,
    disputedLost: (tr.lost_disputes || 0) > 0,
  }
}

export interface TrackRecordSummary {
  jobs_verified: number
  local_jobs: number
  traveled_jobs: number
  avg_stars: number | null
  five_star: number
  on_time: { met: number; of: number }
  disputes: { total: number; lost: number; open?: number }
  volume: { currency: string; total: string; jobs: number }[]
  cross_registry_jobs: number
  distinct_hosts: number
  distinct_posters: number
  repeat_poster_jobs: number
  first_verified_at: string | null
  last_verified_at: string | null
}

export interface TrackRecordRow {
  kind: 'local' | 'traveled'
  order_id: string
  title?: string | null
  poster_did: string
  bounty: string | null
  currency: string | null
  stars: number | null
  settled_at?: string | null
  received_at?: string | null
  contract_id?: string | null
  on_time?: boolean | null
  counterparty_home_registry?: string | null
  host_registry?: string
  receipt_digest?: string
  verified?: boolean
}

export interface TrackRecordResponse {
  did: string
  summary: TrackRecordSummary
  recent: TrackRecordRow[]
  /** §AGENTDISC #197 — registry-observed liveness; null for federated mirrors */
  liveness?: { probe: string | null; last_seen: string | null; live_24h: boolean } | null
  credential_pubkey: { pubkey_b64?: string; pubkey_id?: string; alg?: string }
  attested_by: { registry: string | null; url: string | null }
  receipt_kind: string
}

export interface TrackRecordReceipt {
  kind: 'local' | 'traveled'
  subset?: Record<string, any>
  digest?: string
  credential?: Record<string, any> | null
  credential_reissued?: boolean
  credential_note?: string | null
  credential_pubkey?: { pubkey_b64?: string; pubkey_id?: string; alg?: string }
  contract_id?: string | null
  bundle?: Record<string, any>
  host_registry?: string
  verify_at_origin?: string | null
  verified_at_ingestion?: boolean
  attested_by?: { registry: string | null; url: string | null }
}

export async function fetchTrackRecord(did: string, recent = 10): Promise<TrackRecordResponse> {
  const resp = await apiClient.get(`/agents/${encodeURIComponent(did)}/track-record`, {
    params: { recent },
  })
  return resp.data
}

export async function fetchReceipt(did: string, orderId: string): Promise<TrackRecordReceipt> {
  const resp = await apiClient.get(
    `/agents/${encodeURIComponent(did)}/track-record/receipts/${encodeURIComponent(orderId)}`,
  )
  return resp.data
}

// ─── canonical JSON (the cross-language contract) ────────────────────────────

function canonicalValue(v: any): any {
  if (Array.isArray(v)) return v.map(canonicalValue)
  if (v && typeof v === 'object') {
    const sorted: Record<string, any> = {}
    for (const k of Object.keys(v).sort()) sorted[k] = canonicalValue(v[k])
    return sorted
  }
  return v
}

/** python json.dumps(obj, sort_keys=True, separators=(',',':')) with ensure_ascii —
 *  \uXXXX-escape every UTF-16 code unit >= 0x7f (surrogate halves escape
 *  individually, exactly like CPython's astral-plane surrogate-pair escapes). */
export function canonicalReceiptJson(obj: Record<string, any>): string {
  return JSON.stringify(canonicalValue(obj)).replace(
    /[\u007f-\uffff]/g,
    (c) => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0'),
  )
}

export async function sha256DigestOf(subset: Record<string, any>): Promise<string> {
  const bytes = new TextEncoder().encode(canonicalReceiptJson(subset))
  const hash = await crypto.subtle.digest('SHA-256', bytes)
  return 'sha256:' + Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, '0')).join('')
}

// ─── Ed25519 credential verification ─────────────────────────────────────────

function b64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

export type CredentialVerdict = 'valid' | 'invalid' | 'unsupported'

/** Verify an attestation-signer bundle: replace `signature` with '', canonicalize,
 *  Ed25519-verify the detached signature against the published raw pubkey. */
export async function verifyCredentialEd25519(
  bundle: Record<string, any>,
  pubkeyB64: string,
): Promise<CredentialVerdict> {
  try {
    if (!bundle || typeof bundle.signature !== 'string' || !pubkeyB64) return 'invalid'
    const sig = b64ToBytes(bundle.signature)
    const cleaned = { ...bundle, signature: '' }
    const payload = new TextEncoder().encode(canonicalReceiptJson(cleaned))
    let key: CryptoKey
    try {
      key = await crypto.subtle.importKey(
        'raw', b64ToBytes(pubkeyB64) as unknown as BufferSource,
        { name: 'Ed25519' } as any, false, ['verify'],
      )
    } catch {
      return 'unsupported'
    }
    const ok = await crypto.subtle.verify(
      { name: 'Ed25519' } as any, key,
      sig as unknown as BufferSource, payload as unknown as BufferSource,
    )
    return ok ? 'valid' : 'invalid'
  } catch {
    return 'unsupported'
  }
}
