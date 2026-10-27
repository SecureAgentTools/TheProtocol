<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { appLocale } from '@/services/appLocale'
// ContractAttestationModal — §VCSIGN: the countersigned attestation contract
// behind a recorded regulatory authorization, fetched from the ISSUING
// registry's public proof endpoint (/api/v1/jurisdiction/contracts/{cid}) and
// re-verified IN THE BROWSER: the digest is recomputed locally over the
// canonical subset and compared against the server's — the same
// verify-it-yourself story as the record form's document hashing. Shared by
// SovereignRegistryCard (any registry's card, incl. GPU views) and
// AdminJurisdiction, so it stays deliberately light: no deps, lazy-loaded,
// self-contained teleported overlay.
import { ref, watch, computed } from 'vue'
import { Teleport } from 'vue'

const props = defineProps<{
  show: boolean
  cid: string | null
  baseUrl?: string | null    // '' / null = this registry; else the issuing registry's origin
  referenceId?: string | null
}>()
const emit = defineEmits<{ 'update:show': [v: boolean] }>()

const loading = ref(false)
const error = ref<string | null>(null)
const data = ref<any>(null)
const localDigest = ref<string | null>(null)
const verify = ref<'pending' | 'match' | 'mismatch' | 'unavailable'>('pending')

const endpointUrl = computed(() => {
  const base = (props.baseUrl || '').replace(/\/+$/, '')
  return `${base}/api/v1/jurisdiction/contracts/${encodeURIComponent(props.cid || '')}`
})

function close() { emit('update:show', false) }
function onKey(e: KeyboardEvent) { if (e.key === 'Escape' && props.show) close() }
watch(() => props.show, (s) => {
  if (typeof window === 'undefined') return
  if (s) { window.addEventListener('keydown', onKey); load() }
  else window.removeEventListener('keydown', onKey)
})

// Mirror of the backend canonicalization (python json.dumps with sort_keys=True,
// separators=(",",":"), ensure_ascii=True), cross-language byte equality proven
// in scratchpad/digest_xlang*.{py,mjs}. python sorts keys RECURSIVELY and terms
// is a nested object on real contracts, so the sort must recurse too; then
// tight JSON + \uXXXX escaping of everything >= 0x7f reproduces the server
// bytes. (Numbers inside terms rely on JS and python sharing shortest
// round-trip float printing, which JSON-round-tripped values do.)
function canonicalValue(v: any): any {
  if (Array.isArray(v)) return v.map(canonicalValue)
  if (v && typeof v === 'object') {
    const sorted: Record<string, any> = {}
    for (const k of Object.keys(v).sort()) sorted[k] = canonicalValue(v[k])
    return sorted
  }
  return v
}
function canonicalAttestationJson(obj: Record<string, any>): string {
  return JSON.stringify(canonicalValue(obj)).replace(/[\u007f-\uffff]/g,
    (ch) => '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0'))
}

async function recompute() {
  verify.value = 'pending'; localDigest.value = null
  if (!data.value?.contract) return
  const subtle = (typeof crypto !== 'undefined' && crypto.subtle) ? crypto.subtle : null
  if (!subtle) { verify.value = 'unavailable'; return }  // non-secure context: say so, never fake a verdict
  try {
    const canonical = canonicalAttestationJson(data.value.contract)
    const buf = await subtle.digest('SHA-256', new TextEncoder().encode(canonical))
    const hex = Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('')
    localDigest.value = 'sha256:' + hex
    verify.value = localDigest.value === data.value.digest ? 'match' : 'mismatch'
  } catch { verify.value = 'unavailable' }
}

async function load() {
  if (!props.cid) return
  loading.value = true; error.value = null; data.value = null; verify.value = 'pending'
  try {
    const resp = await fetch(endpointUrl.value, { headers: { Accept: 'application/json' } })
    if (resp.status === 404) {
      error.value = 'No live authorization references this contract on the issuing registry.'
    } else if (resp.status === 409) {
      let detail = ''
      try { const j = await resp.json(); detail = typeof j?.detail === 'string' ? j.detail : '' } catch { /* keep generic */ }
      error.value = detail || 'The issuing registry reports the countersign cannot currently be verified.'
    } else if (!resp.ok) {
      error.value = `The issuing registry answered HTTP ${resp.status}.`
    } else {
      data.value = await resp.json()
      await recompute()
    }
  } catch {
    error.value = 'Could not reach the issuing registry from this page (network or cross-origin policy). Open the raw endpoint below to verify directly.'
  } finally { loading.value = false }
}

const c = computed<any>(() => data.value?.contract || {})
const termsObj = computed<Record<string, any> | null>(() =>
  (c.value.terms && typeof c.value.terms === 'object' && !Array.isArray(c.value.terms)) ? c.value.terms : null)
const termsText = computed<string | null>(() =>
  typeof c.value.terms === 'string' ? c.value.terms : null)
const meaning = computed<string | null>(() => termsObj.value?.jurisdictional_meaning || null)
const termRows = computed<[string, string][]>(() => {
  if (!termsObj.value) return []
  return Object.entries(termsObj.value)
    .filter(([k]) => k !== 'jurisdictional_meaning')
    .map(([k, v]) => [k, typeof v === 'string' ? v : JSON.stringify(v)] as [string, string])
})
function amountLabel(v: any): string {
  const n = Number(v)
  return Number.isFinite(n) ? String(n) : String(v ?? '')
}
function dt(v: any): string { try { return v ? new Date(v).toLocaleString(appLocale()) : '' } catch { return String(v || '') } }
function short(v: any): string { return String(v || '').replace(/^sha256:/, '').slice(0, 16) + '…' }
</script>

<template>
  <Teleport to="body">
    <transition name="cam-fade">
      <div v-if="show" class="cam-overlay" data-testid="vcsign-modal" @click.self="close">
        <div class="cam-panel" role="dialog" aria-modal="true" aria-label="Countersigned attestation contract">
          <button class="cam-x" data-testid="vcsign-close" @click="close" aria-label="Close">×</button>
          <header class="cam-head">
            <div class="cam-title">Countersigned attestation</div>
            <div v-if="referenceId" class="cam-sub">authorization reference <code>{{ referenceId }}</code></div>
          </header>

          <div v-if="loading" class="cam-state">Fetching the contract from the issuing registry…</div>

          <div v-else-if="error" class="cam-state cam-state--err" data-testid="vcsign-error">
            {{ error }}
            <div class="cam-rawline"><a :href="safeExternalUrl(endpointUrl)" target="_blank" rel="noopener" data-testid="vcsign-raw-link">Open raw endpoint ↗</a></div>
          </div>

          <template v-else-if="data">
            <div class="vcsign-verify cam-verify" :class="'cam-verify--' + verify" data-testid="vcsign-verify">
              <template v-if="verify === 'match'">✓ VERIFIED IN THIS BROWSER: the digest recomputed locally from the bytes below matches the server's.</template>
              <template v-else-if="verify === 'mismatch'">✗ DIGEST MISMATCH: the locally recomputed digest does not match the server's. Treat this attestation as unverified.</template>
              <template v-else-if="verify === 'unavailable'">Local recompute unavailable in this context (no WebCrypto). Compare the digests via the raw endpoint instead.</template>
              <template v-else>Recomputing…</template>
            </div>
            <dl class="cam-digests">
              <div class="cam-row"><dt>Server digest</dt><dd><code data-testid="vcsign-digest-server" :title="data.digest">{{ short(data.digest) }}</code></dd></div>
              <div class="cam-row" v-if="localDigest"><dt>Local recompute</dt><dd><code data-testid="vcsign-digest-local" :title="localDigest">{{ short(localDigest) }}</code></dd></div>
            </dl>

            <section class="cam-sect">
              <div class="cam-facts-title">{{ c.title }}</div>
              <dl class="cam-facts">
                <div class="cam-row"><dt>Contract</dt><dd><code>{{ c.id }}</code> · {{ c.contract_type }} · status {{ data.status }}</dd></div>
                <div class="cam-row"><dt>Attesting party</dt><dd><code class="cam-trunc" :title="c.client_did">{{ c.client_did }}</code></dd></div>
                <div class="cam-row"><dt>Countersigner</dt><dd><code class="cam-trunc" :title="c.provider_did">{{ c.provider_did }}</code></dd></div>
                <div class="cam-row"><dt>Value</dt><dd>{{ amountLabel(c.total_amount) }} (agreement-only: a countersign moves no funds)</dd></div>
                <div class="cam-row" v-if="c.created_at"><dt>Authored</dt><dd>{{ dt(c.created_at) }}</dd></div>
                <div class="cam-row" v-if="c.agreed_at"><dt>Countersigned</dt><dd>{{ dt(c.agreed_at) }}</dd></div>
                <div class="cam-row" v-if="(data.authorization_references || []).length"><dt>Backs</dt>
                  <dd><code v-for="r in data.authorization_references" :key="r" class="cam-refchip">{{ r }}</code></dd></div>
              </dl>
            </section>

            <section v-if="meaning" class="cam-sect">
              <div class="cam-sect-head">What this represents in the jurisdictional sense</div>
              <p class="cam-meaning">{{ meaning }}</p>
            </section>

            <section v-if="termRows.length || termsText" class="cam-sect">
              <div class="cam-sect-head">Terms</div>
              <pre v-if="termsText" class="cam-termstext">{{ termsText }}</pre>
              <dl v-else class="cam-facts">
                <div class="cam-row" v-for="[k, v] in termRows" :key="k"><dt>{{ k.replace(/_/g, ' ') }}</dt><dd class="cam-termval">{{ v }}</dd></div>
              </dl>
            </section>

            <footer class="cam-foot">
              <span>These bytes are public by design: countersigning an attestation publishes it.</span>
              <a :href="safeExternalUrl(endpointUrl)" target="_blank" rel="noopener" data-testid="vcsign-raw-link">Raw endpoint ↗</a>
            </footer>
          </template>
        </div>
      </div>
    </transition>
  </Teleport>
</template>

<style scoped>
.cam-overlay { position: fixed; inset: 0; z-index: 10400; background: rgba(2,8,14,0.72); backdrop-filter: blur(3px); display: flex; align-items: center; justify-content: center; padding: 20px; }
.cam-panel { position: relative; width: min(680px, 94vw); max-height: 86vh; overflow-y: auto; background: linear-gradient(165deg, #0a1520, #060b12); border: 1px solid rgba(45,212,191,0.35); border-radius: 14px; box-shadow: 0 18px 60px rgba(0,0,0,0.6), 0 0 24px rgba(45,212,191,0.12); padding: 20px 22px 16px; color: rgba(235,245,250,0.92); font-size: 0.82rem; }
.cam-x { position: absolute; top: 12px; right: 14px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); color: rgba(255,255,255,0.7); width: 26px; height: 26px; border-radius: 8px; cursor: pointer; }
.cam-x:hover { color: #fff; border-color: rgba(45,212,191,0.6); }
.cam-head { margin-bottom: 12px; padding-right: 32px; }
.cam-title { font-size: 0.95rem; letter-spacing: 0.08em; text-transform: uppercase; color: #2dd4bf; }
.cam-sub { margin-top: 3px; font-size: 0.72rem; color: rgba(235,245,250,0.6); }
.cam-state { padding: 18px 4px; color: rgba(235,245,250,0.75); }
.cam-state--err { color: #fca5a5; }
.cam-rawline { margin-top: 10px; }
.cam-verify { border-radius: 9px; padding: 9px 12px; font-size: 0.74rem; letter-spacing: 0.02em; border: 1px solid; margin-bottom: 10px; }
.cam-verify--match { border-color: rgba(45,212,191,0.55); color: #2dd4bf; background: rgba(45,212,191,0.08); }
.cam-verify--mismatch { border-color: rgba(248,113,113,0.6); color: #f87171; background: rgba(248,113,113,0.08); }
.cam-verify--unavailable, .cam-verify--pending { border-color: rgba(250,204,21,0.4); color: #facc15; background: rgba(250,204,21,0.06); }
.cam-digests { margin: 0 0 6px; }
.cam-sect { margin-top: 12px; border-top: 1px solid rgba(255,255,255,0.07); padding-top: 10px; }
.cam-sect-head { font-size: 0.68rem; letter-spacing: 0.1em; text-transform: uppercase; color: rgba(45,212,191,0.85); margin-bottom: 6px; }
.cam-facts-title { font-weight: 600; margin-bottom: 8px; color: rgba(240,250,255,0.95); }
.cam-facts, .cam-digests { display: grid; gap: 4px; }
.cam-row { display: grid; grid-template-columns: 138px 1fr; gap: 10px; align-items: baseline; }
.cam-row dt { color: rgba(235,245,250,0.5); font-size: 0.7rem; letter-spacing: 0.04em; text-transform: uppercase; }
.cam-row dd { margin: 0; overflow-wrap: anywhere; }
.cam-row code { font-size: 0.74rem; color: #8be9d9; }
.cam-trunc { display: inline-block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }
.cam-refchip { display: inline-block; margin: 0 6px 4px 0; padding: 1px 8px; border-radius: 999px; border: 1px solid rgba(45,212,191,0.4); }
.cam-meaning { margin: 0; line-height: 1.5; color: rgba(235,245,250,0.82); }
.cam-termstext { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 0.74rem; color: rgba(235,245,250,0.8); }
.cam-termval { color: rgba(235,245,250,0.82); }
.cam-foot { margin-top: 14px; padding-top: 10px; border-top: 1px solid rgba(255,255,255,0.07); display: flex; justify-content: space-between; gap: 12px; font-size: 0.68rem; color: rgba(235,245,250,0.5); }
.cam-foot a { color: #2dd4bf; text-decoration: none; }
.cam-foot a:hover { text-decoration: underline; }
.cam-fade-enter-active, .cam-fade-leave-active { transition: opacity 0.16s ease; }
.cam-fade-enter-from, .cam-fade-leave-to { opacity: 0; }
</style>
