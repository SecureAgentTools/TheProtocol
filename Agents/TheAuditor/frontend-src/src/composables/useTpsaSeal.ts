// useTpsaSeal (§PASSPORTSELL session, 2026-08-22) — the ONE TPSA-1 in-browser
// verification state, shared by the seal strip (AttestationSeal.vue) and the
// header badge (TpsaBadge.vue). Module-scope singleton: clicking either control
// re-verifies and BOTH render the same result — two views, one proof.
import { computed, ref } from 'vue'
import { useAuditorStore } from '@/stores/auditorStore'

export interface SealResult { frame: string; state: 'pending' | 'ok' | 'fail' | 'own'; detail: string; seq?: number }

// §LEGACYTIER 2026-09-09: this was a literal ['frame-a','frame-b','frame-c'] named PROD_FRAMES,
// written when those three WERE production. Once EU/ASIA became the prod tier it silently kept
// showing the legacy frames' chips and sequence numbers under the PROD toggle — a gate pinning a
// value it can derive. The frames to verify are exactly the CURRENT tier's frames, and only when
// that tier signs at all (attestModes, server-derived).
function framesToVerify(): string[] {
  const store = useAuditorStore()
  if (!store.attestModes.includes(store.mode)) return []
  return store.frames.filter(f => f.mode === store.mode && !f.public_only).map(f => f.id)
}

// §MTLSHOPS (a) (2026-09-15, agentvault2-85): a public-only frame is not attested by this host (a TPSA-1 attestation claims
// the atomic check); its own auditor holds the chain. It is shown as such and never counts as a failed verification.
function ownAuditorFrames(): string[] {
  const store = useAuditorStore()
  if (!store.attestModes.includes(store.mode)) return []
  return store.frames.filter(f => f.mode === store.mode && f.public_only).map(f => f.id)
}

const results = ref<SealResult[]>([])
const busy = ref(false)
const verified = ref(false)
const kid = ref('')
const unsupported = ref(false)
const lastVerifiedAt = ref('')

function b64uToBytes(s: string): Uint8Array {
  const pad = s.length % 4 === 0 ? '' : '='.repeat(4 - (s.length % 4))
  const bin = atob(s.replace(/-/g, '+').replace(/_/g, '/') + pad)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

async function sha256hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))
  return Array.from(new Uint8Array(d)).map(b => b.toString(16).padStart(2, '0')).join('')
}

async function verifyFrame(frame: string, keys: Map<string, CryptoKey>): Promise<SealResult> {
  const res = await fetch(`/api/auditor/attestations?frame=${frame}&limit=5`)
  const body = await res.json()
  const atts: any[] = body.attestations || []
  if (!atts.length) return { frame, state: 'fail', detail: 'no attestations on the chain yet' }
  // The seal speaks for the VERDICTS on the page, so it verifies the newest AUDIT
  // attestation; provenance entries (baseline_set etc.) are chain members the
  // link-check still walks over, but they carry no verdict to seal.
  const idx = atts.findIndex(x => x.kind === 'audit')
  if (idx === -1) return { frame, state: 'fail', detail: 'no audit attestation in the latest window' }
  const a = atts[idx]
  const payloadBytes = new TextEncoder().encode(a.payload)
  if ((await sha256hex(a.payload)) !== a.digest)
    return { frame, state: 'fail', detail: 'digest does not match payload bytes' }
  const key = keys.get(a.kid)
  if (!key) return { frame, state: 'fail', detail: `kid ${a.kid} not in JWKS` }
  const sigOk = await crypto.subtle.verify('Ed25519', key, b64uToBytes(a.signature) as unknown as BufferSource, payloadBytes as unknown as BufferSource)
  if (!sigOk) return { frame, state: 'fail', detail: 'Ed25519 signature INVALID' }
  const parsed = JSON.parse(a.payload)
  if (atts[idx + 1] && parsed.prev_hash !== atts[idx + 1].digest)
    return { frame, state: 'fail', detail: 'chain BROKEN: prev_hash does not match previous digest' }
  return {
    frame, state: 'ok', seq: parsed.as_of_event_seq || undefined,
    detail: `signature + digest + chain verified in this browser at ${new Date().toISOString().slice(11, 19)}Z (attested ${String(parsed.ts || '').slice(0, 19)}Z)`,
  }
}

async function verifyAll() {
  if (busy.value) return
  busy.value = true
  try {
    const jwks = await (await fetch('/.well-known/auditor-jwks.json')).json()
    const keys = new Map<string, CryptoKey>()
    for (const k of jwks.keys || []) {
      try {
        keys.set(k.kid, await crypto.subtle.importKey('jwk', k as JsonWebKey, 'Ed25519', false, ['verify']))
      } catch {
        unsupported.value = true
        return
      }
    }
    kid.value = (jwks.keys || [])[0]?.kid || ''
    const frames = framesToVerify()
    const verifiedHere = await Promise.all(frames.map(f =>
      verifyFrame(f, keys).catch(e => ({ frame: f, state: 'fail' as const, detail: String(e) }))))
    results.value = [...verifiedHere, ...ownAuditorFrames().map(f => ({
      frame: f, state: 'own' as const,
      detail: "a public-only frame: its own auditor holds the attestation; this host reads its public supply audit only and does not attest it",
    }))]
    verified.value = true
    lastVerifiedAt.value = new Date().toISOString().slice(11, 19) + 'Z'
  } finally {
    busy.value = false
  }
}

// One word the badge can wear: what does the whole seal currently say?
const summary = computed<'busy' | 'unsupported' | 'pending' | 'ok' | 'fail'>(() => {
  if (unsupported.value) return 'unsupported'
  if (busy.value) return 'busy'
  if (!verified.value) return 'pending'
  // `every` over an empty array is TRUE, so a run that verified NOTHING would report 'ok'.
  // Pair it with the count: no frames checked is 'pending', never a green seal.
  const here = results.value.filter(r => r.state !== 'own')
  if (!here.length) return 'pending'
  return here.every(r => r.state === 'ok') ? 'ok' : 'fail'
})

export function useTpsaSeal() {
  return { results, busy, verified, kid, unsupported, lastVerifiedAt, summary, verifyAll }
}
