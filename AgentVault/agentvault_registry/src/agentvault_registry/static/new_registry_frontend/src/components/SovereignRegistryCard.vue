<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { appLocale } from '@/services/appLocale'
// SovereignRegistryCard — reusable, read-only viewer for a v0.4 Registry Card.
// (formerly RegistryCardModal). Shows the FULL signed card for a registry —
// the local one or a federated peer — fetched via registryCardView (public
// endpoint). Self-contained teleported overlay, AAA+ "sovereign codex" aesthetic.
// Reused by AgentWorld, GalacticMap, UniverseView and Discovery on node/orb click.
import { ref, watch, computed, defineAsyncComponent } from 'vue'
import { Teleport } from 'vue'
import { registryCardView, type RegistrySourceEnvelope } from '@/services/api/registryCardView'
import { licenceLabel as licLabel, licenceOk as licOk, licenceRow } from '@/services/licenceVerdict'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'

// §VCSIGN: lazy — this component rides inside the GPU views' stacks, and the
// attestation modal only matters after a click on a countersigned chip.
const ContractAttestationModal = defineAsyncComponent(() =>
  import('@/components/common/ContractAttestationModal.vue'))

import { useFederationTopology } from '@/composables/useFederationTopology'
import { hasAdminFlag } from '@/composables/usePermissions'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{
  show: boolean
  peerName?: string | null     // source registry name; null/"Local" → this registry
  fallbackName?: string | null // shown in the header while loading
}>()
const emit = defineEmits<{ 'update:show': [v: boolean] }>()

const loading = ref(false)
const error = ref<string | null>(null)
const env = ref<RegistrySourceEnvelope | null>(null)
let lastKey = ''

function close() { emit('update:show', false) }

async function load() {
  const key = (props.peerName || '').trim().toLowerCase()
  if (env.value && lastKey === key) return       // cached for this source
  loading.value = true; error.value = null; env.value = null
  try {
    env.value = await registryCardView.fetchSource(props.peerName)
    lastKey = key
  } catch (e: any) {
    error.value = e?.response?.status === 404
      ? 'This registry has not shared a signed card yet.'
      : 'Could not load the registry card.'
  } finally { loading.value = false }
}

watch(() => props.show, (s) => { if (s) { load(); if (canReadPeerTrust.value) fetchTopology().catch(() => {}) } })

function onKey(e: KeyboardEvent) { if (e.key === 'Escape' && props.show) close() }
watch(() => props.show, (s) => {
  if (typeof window === 'undefined') return
  if (s) window.addEventListener('keydown', onKey)
  else window.removeEventListener('keydown', onKey)
})

// ── card accessors ─────────────────────────────────────────────────────────
const card = computed<any>(() => env.value?.card || {})
const ident = computed(() => card.value.identity || {})
const op = computed(() => card.value.operator || {})
const vis = computed(() => card.value.visual || {})
const caps = computed(() => card.value.capabilities || {})
const fees = computed(() => card.value.fees || {})
const fed = computed(() => card.value.federation || {})
// §FEDLICENCE (2026-09-28): the derived, signed network licence (and on an operator its own operator licence)
const lic = computed(() => ((fed.value as any).licence || {}) as Record<string, any>)
const opLic = computed(() => (lic.value.operator || null) as Record<string, any> | null)
const pol = computed(() => card.value.policy || {})
const econ = computed(() => card.value.economic || {})
const stats = computed(() => card.value.stats || {})
const links = computed(() => card.value.links || {})
const commit = computed(() => card.value.commitments || {})
const life = computed(() => card.value.lifecycle || {})
// The registry's OWN declaration of the feature scope it runs, signed into its card.
// Absent block = no profile declared (which is a different statement from 'all allowed').
const juris = computed<any>(() => (card.value as any)?.compliance?.jurisdiction_profile || null)
// REGAUTH (card v0.6): declared regulated actions + recorded regulatory
// authorizations. Authorizations publish even without a profile (they are an
// attestation in their own right), so the section keys on either.
const regActions = computed<[string, any][]>(() => Object.entries(juris.value?.regulated_actions || {}))
const regAuths = computed<any[]>(() => (card.value as any)?.compliance?.regulatory_authorizations || [])
// §VCSIGN: the countersigned chip opens the attestation contract, fetched from
// the card's OWN registry, and re-verifies its digest in this browser.
const attestShow = ref(false)
const attestCid = ref<string | null>(null)
const attestRef = ref<string | null>(null)
// §TRUSTWIRE — our own Bayesian observation of this peer, read from OUR peer row rather than from
// the card we just fetched. Three states, never two: a peer nobody has transacted with is
// UNMEASURED and must not wear the colour of a peer we have downgraded.
// The row reads the ADMIN topology rail (admin_federation); the public topology carries no trust evidence. So only a
// viewer holding the flag asks: a visitor asking was a 401 on every card opened on the public Discovery page, and a
// signed-in non-admin was refused 403 and shown "unmeasured" from a public row that never carried the numbers.
const auth = useAuthStore()
const canReadPeerTrust = computed(() => hasAdminFlag(auth.user, 'federation'))
const { allPeers, fetchTopology } = useFederationTopology({ admin: true })
const peerTrust = computed(() => {
  if (!canReadPeerTrust.value) return null
  const name = (props.peerName || '').trim().toLowerCase()
  if (!name) return null
  const row: any = (allPeers.value || []).find(
    (p: any) => String(p?.name || '').trim().toLowerCase() === name)
  if (!row) return null
  // Neither the verdict nor the interaction count: a public row (the composable's fallback when the rail refuses
  // a flag the frontend believed in). It carries no evidence, so it is not graded at all.
  if (!(row.trust && typeof row.trust === 'object') && !('total_interactions' in row)) return null
  const n = Number(row.total_interactions ?? 0) || 0

  // §TRUSTPOLICY (2026-09-11) — ONE MODEL, ONE IMPLEMENTATION. The topology rail now carries the
  // backend's verdict, computed against THIS FRAME'S declared thresholds. This block used to be a
  // THIRD opinion on the same question (after the evaluator and FederationDiscovery), with 75/40
  // cut-offs that belonged to nobody's policy, so a frame that tightened its thresholds would see
  // the number go amber on one screen and stay green on another.
  const v: any = row.trust
  if (v && typeof v === 'object' && v.state && v.state !== 'unavailable') {
    if (v.state === 'unmeasured') {
      return { text: 'unmeasured', cls: 'rcm-trust--unmeasured', hint: String(v.reason || '') }
    }
    const pctV = Math.round((Number(row.bayesian_discount ?? 0.5) || 0.5) * 100)
    return {
      text: v.state === 'ok' ? `${pctV}%` : `${pctV}% · ${v.state}`,
      cls: v.state === 'restricted' || v.state === 'suspended' ? 'rcm-trust--low'
        : v.state === 'warn' ? 'rcm-trust--mid' : 'rcm-trust--good',
      hint: String(v.reason || '') + (v.enforced ? '' : ' (observing only — this frame is not acting on it)'),
    }
  }

  if (!n) {
    return {
      text: 'unmeasured', cls: 'rcm-trust--unmeasured',
      hint: 'No settled cross-registry interaction with this peer has been recorded yet. An absence of evidence, not a judgement.',
    }
  }
  const lost = Number(row.disputes_lost_with ?? 0) || 0
  const pct = Math.round((Number(row.bayesian_discount ?? 0.5) || 0.5) * 100)
  return {
    text: `${pct}%`,
    cls: pct >= 75 ? 'rcm-trust--good' : pct >= 40 ? 'rcm-trust--mid' : 'rcm-trust--low',
    hint: `Beta(1,1) point estimate over ${n} settled interactions, ${lost} of which we lost a dispute on. Our own observation, not this registry's claim.`,
  }
})

const isLocalSource = computed(() => !props.peerName || /^local$/i.test(String(props.peerName)))
// §FEDLICENCE (agentvault2-a4's review item 5): a peer signs its own card, so for a peer the licence row shows THIS
// registry's verdict (the envelope, from our peer row) and the card's own value on a row of its own; the rule lives in
// services/licenceVerdict.ts. On self the card's block IS our own derivation.
const licIsSelf = computed(() => env.value?.is_self === true)
const licRow = computed(() => licenceRow({
  isSelf: licIsSelf.value,
  cardState: lic.value.state,
  ourState: env.value?.licence_state,
  ourReason: env.value?.licence_reason,
  ourCheckedAt: env.value?.licence_checked_at,
  // an operator's card carries its frame's licence (and its own operator licence beside it); operators share their
  // frame's trust domain, so the card's own trust domain names that frame
  ridesFrame: opLic.value && opLic.value.hash ? String(ident.value.trust_domain || lic.value.network || '') : null,
}))
const LIC_TONE_CLASS: Record<string, string> = { ok: 'rcm-ok', refused: 'rcm-bad', neutral: 'rcm-dim', unmeasured: 'rcm-unmeasured' }
const attestBase = computed(() => {
  if (isLocalSource.value) return ''
  const pu = ident.value.public_url
  try { if (pu) { const p = new URL(pu); return `${p.protocol}//${p.hostname}` } } catch { /* fall through */ }
  return ''
})
function openAttestation(a: any) {
  attestCid.value = a.contract_ref || null
  attestRef.value = a.reference_id || null
  attestShow.value = true
}
// Quarantine is the single most consequential fact on a peer's card and it was not rendered
// anywhere: a quarantined registry is severed from the economic rails. Surface it loudly.
const lifeStatus = computed(() => String((card.value.lifecycle || {}).status || '').toLowerCase())
const isQuarantined = computed(() => lifeStatus.value.includes('quarantin') || lifeStatus.value === 'blacklisted')
const sig = computed(() => card.value.signature || {})

const headerName = computed(() =>
  ident.value.display_name || ident.value.registry_name || env.value?.name || props.fallbackName || 'Registry')
const tier = computed(() => ident.value.tier || null)
const persona = computed(() => vis.value.persona || vis.value.tagline || null)
const verified = computed(() => env.value?.card_signature_verified === true)
const sovereign = computed(() => fed.value.is_sovereign_frame === true || /sovereign|mainframe/i.test(String(tier.value || '')))
const orbC = computed(() => vis.value.orb_color || '#00d2d2')
const orbG = computed(() => vis.value.orb_glow_color || orbC.value)
const orbStyle = computed(() => ({
  background: `radial-gradient(circle at 34% 28%, #ffffffcc, ${orbC.value} 62%, ${orbG.value})`,
  boxShadow: `0 0 22px ${orbG.value}, 0 0 48px ${orbG.value}66, inset 0 0 14px #ffffff55`,
}))
const haloStyle = computed(() => ({
  background: `conic-gradient(from 0deg, ${orbC.value}00, ${orbG.value}cc, ${orbC.value}00 60%)`,
}))
const heroTint = computed(() => ({
  background: `radial-gradient(120% 160% at 0% 0%, ${orbG.value}22, transparent 55%),
               linear-gradient(110deg, ${orbC.value}1f, transparent 62%)`,
}))
// §2026-06-14 — the card's icon_url is stored same-origin-relative; when this modal
// shows a PEER's card from another registry the relative path 404s against the viewer's
// origin → the avatar falls back to initials. Resolve a relative icon against the card's
// OWN host (scheme+hostname from identity.public_url — port dropped; icons serve on 443)
// so the peer's avatar (e.g. Frame-B's Saul) renders here exactly like the hover does.
const resolvedIconUrl = computed<string | undefined>(() => {
  const u = vis.value.icon_url
  if (!u) return undefined
  if (/^https?:\/\//i.test(u)) return u
  const pu = ident.value.public_url
  if (u.startsWith('/') && pu) {
    try { const p = new URL(pu); return `${p.protocol}//${p.hostname}${u}` } catch { /* fall through */ }
  }
  return u
})

// ── formatting helpers ───────────────────────────────────────────────────────
function dt(v: any): string { if (!v) return '—'; try { return new Date(v).toLocaleString(appLocale()) } catch { return String(v) } }
function pct(v: any): string { return (v === null || v === undefined || v === '') ? '—' : `${v}%` }
function yn(v: any): string { return v === true ? 'Yes' : v === false ? 'No' : '—' }
function shortHash(h: any): string { return typeof h === 'string' && h.length > 16 ? h.slice(0, 16) + '…' : String(h || '—') }
function val(v: any): string {
  if (v === null || v === undefined || v === '') return '—'
  // §2026-06-14 — objects (e.g. operator.support_contact = {email, matrix, signal})
  // were rendered via String() → "[object Object]". Surface the useful string bits.
  if (typeof v === 'object') {
    const parts = Object.values(v).filter((x) => typeof x === 'string' && x.trim())
    return parts.length ? parts.join(' · ') : '—'
  }
  return String(v)
}
function arr(v: any): string[] { return Array.isArray(v) ? v.filter(x => x !== null && x !== undefined && x !== '') : [] }
function hostBase(): string { return (env.value?.base_url || ident.value.public_url || '').replace(/^https?:\/\//, '') }
const copied = ref(false)
async function copy(s?: string | null) { try { if (s) { await navigator.clipboard.writeText(s); copied.value = true; setTimeout(() => copied.value = false, 1200) } } catch { /* ignore */ } }
</script>

<template>
  <Teleport to="body">
    <transition name="rcm-fade">
      <div v-if="show" class="rcm-overlay" @click.self="close">
        <div class="rcm-panel" :class="{ 'rcm-panel--sov': sovereign }" role="dialog" aria-label="Registry card" @click.stop>

          <!-- Hero header -->
          <header class="rcm-hero" :style="heroTint">
            <div class="rcm-hero-sheen"></div>
            <div class="rcm-orbwrap">
              <!-- Restore the registry's encirclement flare (blackhole/glitch/etc.)
                   — the signature sovereign visual. Falls back to icon, then orb. -->
              <FlareEncirclement
                v-if="vis.flare_encirclement_variant"
                tier="shadow_chancellor"
                :variant="vis.flare_encirclement_variant"
                :overlay="vis.flare_encirclement_overlay || null"
                :avatar-url="resolvedIconUrl"
                :initials="(headerName || 'R').slice(0,2).toUpperCase()"
                size="lg"
              />
              <UserAvatar
                v-else-if="vis.icon_url"
                :avatar-url="resolvedIconUrl"
                :display-name="headerName"
                size="lg"
              />
              <template v-else>
                <div class="rcm-halo" :style="haloStyle"></div>
                <div class="rcm-orb" :style="orbStyle"></div>
              </template>
            </div>
            <div class="rcm-hero-main">
              <div class="rcm-hero-titlerow">
                <h2 class="rcm-title">{{ headerName }}</h2>
                <span v-if="tier" class="rcm-tier" :class="{ 'rcm-tier--sov': sovereign }">{{ tier }}</span>
                <span v-if="env && env.is_self" class="rcm-selfchip">this registry</span>
              </div>
              <div v-if="persona" class="rcm-persona">{{ persona }}</div>
              <div class="rcm-hero-chips">
                <span v-if="ident.trust_domain" class="rcm-hpill rcm-hpill--td" :title="'Trust domain'">{{ ident.trust_domain }}</span>
                <span v-if="ident.software_version" class="rcm-hpill" :title="'Software version'">{{ ident.software_version }}</span>
                <span v-if="ident.founded_at" class="rcm-hpill" :title="'Founded'">since {{ new Date(ident.founded_at).getFullYear() }}</span>
              </div>
            </div>
            <div class="rcm-hero-right">
              <!-- §TRUSTWIRE (2026-09-10) — OUR observed trust in this peer. It sits apart from the
                   signed seal on purpose: everything else on this card is what THEY publish about
                   themselves, and this one line is what WE have observed about them. It is never on
                   their registry card, and it never could be. -->
              <div v-if="!isLocalSource && peerTrust" class="rcm-trust" :class="peerTrust.cls" :title="peerTrust.hint">
                <span class="rcm-trust-lbl">our trust</span>
                <span class="rcm-trust-val" data-testid="rcm-peer-trust">{{ peerTrust.text }}</span>
              </div>
              <div v-if="env" class="rcm-seal" :class="verified ? 'rcm-seal--ok' : 'rcm-seal--warn'"
                   :title="'Card signature ' + (verified ? 'verified · ' + (sig.alg || '') : 'not verified')">
                <span class="rcm-seal-glyph">{{ verified ? '🛡' : '⚠' }}</span>
                <span class="rcm-seal-txt">{{ verified ? 'SIGNED' : 'UNVERIFIED' }}</span>
                <span v-if="verified && sig.alg" class="rcm-seal-alg">{{ sig.alg }}</span>
              </div>
            </div>
            <button class="rcm-x" @click="close" aria-label="Close">✕</button>
          </header>

          <!-- Body -->
          <div class="rcm-body">
            <div v-if="loading" class="rcm-state">
              <div class="rcm-spinner"></div><span>Loading sovereign card…</span>
            </div>
            <div v-else-if="error" class="rcm-state rcm-state--err">{{ error }}</div>

            <template v-else-if="env">
              <p v-if="card.description" class="rcm-desc">{{ card.description }}</p>
              <div v-if="arr(card.tags).length" class="rcm-chips">
                <span v-for="t in arr(card.tags)" :key="t" class="rcm-chip">{{ t }}</span>
              </div>

              <div v-if="isQuarantined" class="rcm-quarantine" role="alert">
                <strong>{{ lifeStatus.toUpperCase() }}</strong>
                <span>This registry is severed from the federated economic rails.<template v-if="life.quarantine_reason"> Reason: {{ life.quarantine_reason }}.</template></span>
              </div>

              <div class="rcm-grid">
                <!-- Identity -->
                <section class="rcm-sec">
                  <h3 class="rcm-sec-h"><i class="rcm-bar rcm-bar--id"></i>Identity</h3>
                  <dl>
                    <div class="rcm-row"><dt>Registry</dt><dd>{{ val(ident.registry_name) }}</dd></div>
                    <div class="rcm-row"><dt>Trust domain</dt><dd class="rcm-mono">{{ val(ident.trust_domain) }}</dd></div>
                    <div class="rcm-row"><dt>Tier</dt><dd>{{ val(ident.tier) }}</dd></div>
                    <div class="rcm-row"><dt>Software</dt><dd class="rcm-mono">{{ val(ident.software_version) }}</dd></div>
                    <div class="rcm-row"><dt>SPIFFE</dt><dd class="rcm-mono rcm-trunc" :title="ident.spiffe_id">{{ val(ident.spiffe_id) }}</dd></div>
                    <div class="rcm-row" v-if="ident.public_url"><dt>Public URL</dt><dd><a :href="safeExternalUrl(ident.public_url)" target="_blank" rel="noopener" class="rcm-link">{{ hostBase() }} ↗</a></dd></div>
                    <div class="rcm-row"><dt>Founded</dt><dd>{{ dt(ident.founded_at) }}</dd></div>
                  </dl>
                </section>

                <!-- Operator -->
                <section class="rcm-sec" v-if="op.display_name || op.bio || op.company || op.url || op.support_contact">
                  <h3 class="rcm-sec-h"><i class="rcm-bar rcm-bar--op"></i>Operator</h3>
                  <dl>
                    <div class="rcm-row"><dt>Name</dt><dd>{{ val(op.display_name) }}</dd></div>
                    <div class="rcm-row" v-if="op.company"><dt>Company</dt><dd>{{ val(op.company) }}</dd></div>
                    <div class="rcm-row" v-if="op.location_label"><dt>Location</dt><dd>{{ val(op.location_label) }}</dd></div>
                    <div class="rcm-row" v-if="op.url"><dt>Website</dt><dd><a :href="safeExternalUrl(op.url)" target="_blank" rel="noopener" class="rcm-link">{{ op.url }} ↗</a></dd></div>
                    <div class="rcm-row" v-if="op.github_url"><dt>GitHub</dt><dd><a :href="safeExternalUrl(op.github_url)" target="_blank" rel="noopener" class="rcm-link">{{ op.github_url }} ↗</a></dd></div>
                    <div class="rcm-row" v-if="op.support_contact"><dt>Support</dt><dd class="rcm-mono">{{ val(op.support_contact) }}</dd></div>
                    <div class="rcm-row" v-if="op.operator_since"><dt>Since</dt><dd>{{ dt(op.operator_since) }}</dd></div>
                  </dl>
                  <p v-if="op.bio" class="rcm-bio">{{ op.bio }}</p>
                </section>

                <!-- Capabilities -->
                <section class="rcm-sec">
                  <h3 class="rcm-sec-h"><i class="rcm-bar rcm-bar--cap"></i>Capabilities</h3>
                  <dl>
                    <div class="rcm-row"><dt>Federation</dt><dd>{{ yn(caps.federation_enabled) }}</dd></div>
                    <div class="rcm-row"><dt>Issuance</dt><dd>{{ val(caps.minting_capability) }}</dd></div>
                    <div class="rcm-row"><dt>Bridge</dt><dd>{{ val(caps.bridge_capability) }}</dd></div>
                    <div class="rcm-row"><dt>Fiat on-ramp</dt><dd>{{ yn(caps.fiat_onramp_enabled) }}</dd></div>
                  </dl>
                  <div class="rcm-chips rcm-chips--tight" v-if="arr(caps.a2a_versions_supported).length || arr(caps.supports_payment_protocol).length">
                    <span v-for="a in arr(caps.a2a_versions_supported)" :key="'a2a'+a" class="rcm-chip rcm-chip--dim">A2A {{ a }}</span>
                    <span v-for="p in arr(caps.supports_payment_protocol)" :key="'pp'+p" class="rcm-chip rcm-chip--dim">{{ p }}</span>
                    <span v-for="z in arr(caps.zkp_phases_enabled)" :key="'zkp'+z" class="rcm-chip rcm-chip--dim">ZKP {{ z }}</span>
                  </div>
                </section>

                <!-- Economics & Fees -->
                <section class="rcm-sec rcm-sec--fx">
                  <h3 class="rcm-sec-h"><i class="rcm-bar rcm-bar--fx"></i>Economics &amp; Fees</h3>
                  <div class="rcm-ccy-row">
                    <span class="rcm-ccy-badge">{{ val(fees.settlement_currency) }}</span>
                    <span class="rcm-ccy-cap">settlement currency</span>
                    <span v-if="fees.fx?.enabled" class="rcm-fxon">⇄ FX on</span>
                  </div>
                  <dl>
                    <div class="rcm-row"><dt>Intra fee</dt><dd>{{ pct(fees.intra_registry?.base_rate_percent) }} <span class="rcm-dim">(max {{ pct(fees.intra_registry?.max_rate_percent) }})</span></dd></div>
                    <div class="rcm-row"><dt>Cross fee</dt><dd>{{ pct(fees.cross_registry?.base_rate_percent) }} → {{ val(fees.cross_registry?.fee_recipient) }}</dd></div>
                    <div class="rcm-row"><dt>Supply</dt><dd><span class="rcm-supply" :class="econ.supply_invariant_status === 'OK' ? 'rcm-ok' : 'rcm-dim'"><i class="rcm-supply-dot" :class="econ.supply_invariant_status === 'OK' ? 'rcm-supply-dot--ok' : ''"></i>{{ val(econ.supply_invariant_status) }}</span> <span class="rcm-dim" v-if="econ.supply_invariant_delta !== undefined">Δ {{ val(econ.supply_invariant_delta) }}</span></dd></div>
                    <div class="rcm-row" v-if="econ.total_circulating"><dt>Circulating</dt><dd>{{ val(econ.total_circulating) }}</dd></div>
                    <div class="rcm-row" v-if="econ.external_auditor_endpoint"><dt>Auditor</dt><dd><a :href="safeExternalUrl(econ.external_auditor_endpoint)" target="_blank" rel="noopener" class="rcm-link rcm-trunc">{{ econ.external_auditor_endpoint }} ↗</a></dd></div>
                  </dl>
                  <p v-if="econ.supply_note" class="rcm-note">{{ econ.supply_note }}</p>
                </section>

                <!-- Federation -->
                <section class="rcm-sec">
                  <h3 class="rcm-sec-h"><i class="rcm-bar rcm-bar--fed"></i>Federation</h3>
                  <dl>
                    <div class="rcm-row"><dt>Protocol</dt><dd>{{ val(fed.protocol_version) }}</dd></div>
                    <div class="rcm-row"><dt>Issuing authority</dt><dd>{{ yn(fed.is_genesis_registry) }}</dd></div>
                    <div class="rcm-row"><dt>Sovereign frame</dt><dd>{{ yn(fed.is_sovereign_frame) }}</dd></div>
                    <div class="rcm-row"><dt>Active peers</dt><dd>{{ val(fed.active_peer_count) }}</dd></div>
                    <!-- §FEDLICENCE (his word 2026-09-28): three different licences meet on this card, so each row names its own. The
                         old unsigned status string is the legacy federation key's; the network licence below is the
                         derived, issuer-signed one; Commitments' row is the SOFTWARE licence (AGPL). -->
                    <div class="rcm-row" v-if="fed.license_status"><dt>Legacy licence</dt><dd>{{ val(fed.license_status) }}</dd></div>
                    <div class="rcm-row" v-if="licRow" data-testid="rcm-licence"><dt>Network licence</dt><dd :title="licRow.hint"><span :class="LIC_TONE_CLASS[licRow.tone]" data-testid="rcm-licence-verdict">{{ licRow.text }}</span><span class="rcm-dim" v-if="!licIsSelf"> · our verdict</span><span class="rcm-dim" v-if="licIsSelf && lic.plan && lic.state !== 'genesis'"> · {{ lic.plan }}</span><span class="rcm-dim" v-if="licIsSelf && lic.issuer && lic.state !== 'genesis'"> · signed by {{ lic.issuer }}</span></dd></div>
                    <div class="rcm-row" v-if="licRow && licRow.cardSays" data-testid="rcm-licence-card-says"><dt>As the card states</dt><dd><span class="rcm-dim">{{ licRow.cardSays }}</span><span class="rcm-dim" v-if="lic.plan && lic.state !== 'genesis'"> · {{ lic.plan }}</span><span class="rcm-dim" v-if="lic.issuer && lic.state !== 'genesis'"> · signed by {{ lic.issuer }}</span></dd></div>
                    <div class="rcm-row" v-if="lic.hash"><dt>Licence hash</dt><dd class="rcm-mono" :title="lic.hash">{{ shortHash(lic.hash) }}</dd></div>
                    <div class="rcm-row" v-if="lic.expires_at"><dt>Licence expires</dt><dd>{{ String(lic.expires_at).slice(0, 10) }}</dd></div>
                    <div class="rcm-row" v-if="opLic && opLic.hash" data-testid="rcm-operator-licence"><dt>Operator licence</dt><dd><span :class="licIsSelf && licOk(opLic.state) ? 'rcm-ok' : 'rcm-dim'">{{ licLabel(opLic.state) }}</span><span class="rcm-dim" v-if="opLic.plan"> · {{ opLic.plan }}</span> <span class="rcm-mono rcm-dim" :title="opLic.hash">{{ shortHash(opLic.hash) }}</span><span class="rcm-dim" v-if="!licIsSelf"> · as the card states</span></dd></div>
                  </dl>
                  <div class="rcm-chips rcm-chips--tight" v-if="arr(fed.supported_auth_methods).length">
                    <span v-for="m in arr(fed.supported_auth_methods)" :key="m" class="rcm-chip rcm-chip--dim">{{ m }}</span>
                  </div>
                </section>

                <!-- Network stats -->
                <section class="rcm-sec rcm-sec--net" v-if="stats.agent_count !== undefined || stats.developer_count !== undefined">
                  <h3 class="rcm-sec-h"><i class="rcm-bar rcm-bar--stat"></i>Network</h3>
                  <div class="rcm-stats">
                    <div class="rcm-stat"><span class="rcm-stat-n">{{ val(stats.agent_count) }}</span><span class="rcm-stat-l">agents</span></div>
                    <div class="rcm-stat"><span class="rcm-stat-n">{{ val(stats.sovereign_agent_count) }}</span><span class="rcm-stat-l">sovereign</span></div>
                    <div class="rcm-stat"><span class="rcm-stat-n">{{ val(stats.developer_count) }}</span><span class="rcm-stat-l">devs</span></div>
                    <div class="rcm-stat"><span class="rcm-stat-n">{{ val(stats.active_peers) }}</span><span class="rcm-stat-l">peers</span></div>
                  </div>
                </section>

                <!-- Commitments -->
                <section class="rcm-sec" v-if="commit.open_source_license || commit.uptime_sla_pct !== undefined">
                  <h3 class="rcm-sec-h"><i class="rcm-bar rcm-bar--commit"></i>Commitments</h3>
                  <dl>
                    <div class="rcm-row"><dt>Software licence</dt><dd>{{ val(commit.open_source_license) }}</dd></div>
                    <div class="rcm-row"><dt>Uptime SLA</dt><dd>{{ pct(commit.uptime_sla_pct) }}</dd></div>
                    <div class="rcm-row"><dt>Incident SLA</dt><dd>{{ commit.incident_disclosure_sla_hours ? commit.incident_disclosure_sla_hours + 'h' : '—' }}</dd></div>
                    <div class="rcm-row"><dt>GDPR</dt><dd>{{ yn(commit.gdpr_compliant) }}</dd></div>
                    <div class="rcm-row"><dt>Key rotation</dt><dd>{{ commit.key_rotation_max_days ? commit.key_rotation_max_days + 'd' : '—' }}</dd></div>
                    <div class="rcm-row" v-if="commit.data_residency"><dt>Data residency</dt><dd>{{ commit.data_residency }}</dd></div>
                    <div class="rcm-row" v-if="commit.breach_disclosure_policy"><dt>Breach policy</dt><dd class="rcm-trunc" :title="commit.breach_disclosure_policy">{{ commit.breach_disclosure_policy }}</dd></div>
                  </dl>
                </section>

                <!-- Jurisdiction profile: read-only, operator-declared, signed into the card.
                     This is the section that makes the declaration checkable by whoever is
                     inspecting the registry, which is the entire point of publishing it. -->
                <section class="rcm-sec" v-if="juris || regAuths.length">
                  <h3 class="rcm-sec-h"><i class="rcm-bar rcm-bar--commit"></i>Jurisdiction profile</h3>
                  <dl v-if="juris">
                    <div class="rcm-row"><dt>Declared</dt><dd>{{ val(juris.name) }}<template v-if="juris.version"> (v{{ juris.version }})</template></dd></div>
                    <div class="rcm-row">
                      <dt>Denied</dt>
                      <dd v-if="(juris.features_denied || []).length" class="rcm-denied">{{ (juris.features_denied || []).join(', ') }}</dd>
                      <dd v-else>none</dd>
                    </div>
                    <div class="rcm-row" v-if="juris.declared_at"><dt>Declared at</dt><dd>{{ dt(juris.declared_at) }}</dd></div>
                    <div class="rcm-row" v-if="juris.profile_hash"><dt>Hash</dt><dd class="rcm-mono rcm-trunc" :title="juris.profile_hash">{{ String(juris.profile_hash).replace(/^sha256:/,'').slice(0,12) }}…</dd></div>
                  </dl>
                  <!-- REGAUTH (card v0.6): which lifecycle acts this deployment declares as
                       requiring state approval, and the approvals it attests to holding. -->
                  <dl v-if="regActions.length" data-testid="rcm-regulated">
                    <div class="rcm-row" v-for="[act, e] in regActions" :key="act">
                      <dt>Regulated</dt>
                      <dd><span class="rcm-mono">{{ act }}</span> · {{ val(e?.authority) }}
                        <span class="rcm-regmode" :class="e?.mode === 'enforce' ? 'rcm-regmode--enforce' : ''">{{ e?.mode || 'shadow' }}</span>
                      </dd>
                    </div>
                  </dl>
                  <div v-if="regAuths.length" class="rcm-regauths" data-testid="rcm-regauths">
                    <div class="rcm-row" v-for="a in regAuths" :key="(a.reference_id || '') + (a.subject_ref || '')">
                      <dt>Authorized</dt>
                      <dd>
                        <span class="rcm-mono">{{ a.action }}</span><template v-if="a.subject_ref"> ({{ a.subject_ref }})</template>
                        · {{ val(a.authority) }}<template v-if="a.jurisdiction">, {{ a.jurisdiction }}</template>
                        · ref <span class="rcm-mono">{{ a.reference_id }}</span>
                        <template v-if="a.valid_until"> · until {{ dt(a.valid_until) }}</template>
                        <span v-if="a.evidence_hash" class="rcm-regtier" :title="'Approval document hash on file: ' + a.evidence_hash">doc-hash</span>
                        <button v-if="a.contract_ref" type="button" class="rcm-regtier rcm-regtier--verify" data-testid="rcm-countersigned"
                                :title="'Countersigned contract ' + a.contract_ref + ': click to fetch it and verify the digest in this browser'"
                                @click.stop="openAttestation(a)">countersigned</button>
                      </dd>
                    </div>
                  </div>
                  <p class="rcm-note" data-testid="rc-jurisdiction-note">Declared by this registry's operator. It states the scope the operator runs
                    here; it is not a statement by TheProtocol about that operator's law. Authorization references are
                    the operator's own attestation, covered by the card signature and verified by nobody; on a pilot
                    deployment they may be placeholders naming no real authority. TheProtocol approves, certifies and
                    endorses nothing about an operator's legal or regulatory status, and none of this is legal advice.</p>
                </section>
              </div>

              <!-- Footer meta -->
              <div class="rcm-meta">
                <span v-if="env.card_etag" class="rcm-meta-item rcm-meta-copy" :title="copied ? 'Copied' : env.card_etag" @click="copy(env.card_etag)">{{ copied ? 'copied ✓' : 'etag ' + env.card_etag.replace(/^sha256:/,'').slice(0,10) + '… ⧉' }}</span>
                <span v-if="env.card_last_pulled_at" class="rcm-meta-item">pulled {{ dt(env.card_last_pulled_at) }}</span>
                <span v-if="sig.alg" class="rcm-meta-item">{{ sig.alg }}</span>
                <span class="rcm-meta-spacer"></span>
                <a v-if="env.public_card_url" :href="safeExternalUrl(env.public_card_url)" target="_blank" rel="noopener" class="rcm-rawlink">View raw card ↗</a>
              </div>
            </template>
          </div>
        </div>
      </div>
    </transition>
  </Teleport>
  <ContractAttestationModal v-model:show="attestShow" :cid="attestCid" :base-url="attestBase" :reference-id="attestRef" />
</template>

<style scoped>
.rcm-trust { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; margin-bottom: 6px; font-size: 11px; }
.rcm-trust-lbl { text-transform: uppercase; letter-spacing: .06em; opacity: .6; font-size: 9px; }
.rcm-trust-val { font-weight: 700; font-variant-numeric: tabular-nums; }
.rcm-trust--good .rcm-trust-val { color: var(--nc-success, #34d399); }
.rcm-trust--mid .rcm-trust-val { color: var(--nc-warning, #fbbf24); }
.rcm-trust--low .rcm-trust-val { color: var(--nc-danger, #f87171); }
/* unmeasured is an absence, not a low score: it must not borrow a low score's colour */
.rcm-trust--unmeasured .rcm-trust-val { color: var(--nc-text-muted, #94a3b8); font-style: italic; font-weight: 500; }
.rcm-overlay {
  position: fixed; inset: 0; z-index: 10200;
  background: radial-gradient(140% 120% at 50% 0%, rgba(10,14,28,0.72), rgba(3,4,10,0.86));
  backdrop-filter: blur(7px);
  display: flex; align-items: flex-start; justify-content: center;
  padding: 5vh 16px; overflow-y: auto;
}
.rcm-panel {
  width: 100%; max-width: 900px;
  background: linear-gradient(180deg, rgba(20,22,34,0.985), rgba(11,12,20,0.985));
  border: 1px solid rgba(var(--nc-primary-rgb,0,210,210), 0.24);
  border-radius: 18px;
  box-shadow: 0 36px 110px -24px rgba(0,0,0,0.85), 0 0 0 1px rgba(255,255,255,0.03) inset,
              0 0 60px -30px rgba(var(--nc-primary-rgb,0,210,210),0.5);
  overflow: hidden; position: relative;
}
.rcm-panel--sov { border-color: rgba(245,158,11,0.45); box-shadow: 0 36px 110px -24px rgba(0,0,0,0.85), 0 0 0 1px rgba(255,255,255,0.03) inset, 0 0 70px -28px rgba(245,158,11,0.55); }
/* Hero */
.rcm-hero {
  display: flex; align-items: center; gap: 18px;
  padding: 22px 24px 20px; position: relative; overflow: hidden;
  border-bottom: 1px solid rgba(255,255,255,0.07);
}
.rcm-hero-sheen { position: absolute; inset: 0; background: linear-gradient(75deg, transparent 30%, rgba(255,255,255,0.06) 48%, transparent 60%); transform: translateX(-40%); animation: rcm-sheen 6s ease-in-out infinite; pointer-events: none; }
@keyframes rcm-sheen { 0%,100% { transform: translateX(-60%); opacity:0; } 45%,55% { opacity:1; } 80% { transform: translateX(120%); opacity:0; } }
.rcm-orbwrap { position: relative; width: 66px; height: 66px; flex-shrink: 0; display: grid; place-items: center; }
.rcm-halo { position: absolute; inset: -7px; border-radius: 50%; filter: blur(3px); opacity: 0.85; animation: rcm-spin 7s linear infinite; }
.rcm-orb { width: 60px; height: 60px; border-radius: 50%; position: relative; outline: 1px solid rgba(255,255,255,0.18); outline-offset: 2px; }
.rcm-hero-main { flex: 1; min-width: 0; }
.rcm-hero-titlerow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.rcm-title { font-size: 1.4rem; font-weight: 850; margin: 0; letter-spacing: -0.015em;
  background: linear-gradient(92deg, #fff, rgba(var(--nc-primary-rgb,0,210,210),0.92)); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
.rcm-tier { font-size: 0.6rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.06em; padding: 3px 9px; border-radius: 99px; border: 1px solid rgba(255,255,255,0.18); color: rgba(255,255,255,0.85); }
.rcm-tier--sov { color: #fde68a; border-color: rgba(245,158,11,0.55); background: linear-gradient(180deg, rgba(245,158,11,0.22), rgba(245,158,11,0.08)); box-shadow: 0 0 14px rgba(245,158,11,0.25); }
.rcm-selfchip { font-size: 0.6rem; font-weight: 700; padding: 3px 9px; border-radius: 99px; color: rgba(var(--nc-primary-rgb,0,210,210),0.95); background: rgba(var(--nc-primary-rgb,0,210,210),0.1); border: 1px solid rgba(var(--nc-primary-rgb,0,210,210),0.3); }
.rcm-persona { font-size: 0.82rem; color: rgba(255,255,255,0.72); margin-top: 5px; font-style: italic; }
.rcm-hero-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 9px; }
.rcm-hpill { font-size: 0.66rem; font-family: 'IBM Plex Mono','Fira Code',monospace; padding: 2px 8px; border-radius: 6px; color: rgba(255,255,255,0.6); background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); }
.rcm-hpill--td { color: rgba(var(--nc-primary-rgb,0,210,210),0.95); border-color: rgba(var(--nc-primary-rgb,0,210,210),0.28); background: rgba(var(--nc-primary-rgb,0,210,210),0.08); }
.rcm-hero-right { flex-shrink: 0; align-self: flex-start; margin-top: 2px; }
.rcm-seal { display: flex; align-items: center; gap: 6px; padding: 6px 11px; border-radius: 10px; font-size: 0.62rem; font-weight: 800; letter-spacing: 0.05em; }
.rcm-seal--ok { color: #6ee7b7; background: rgba(16,185,129,0.12); border: 1px solid rgba(16,185,129,0.45); box-shadow: 0 0 16px rgba(16,185,129,0.18); }
.rcm-seal--warn { color: #fcd34d; background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.45); }
.rcm-seal-glyph { font-size: 0.95rem; }
.rcm-seal-alg { font-family: 'IBM Plex Mono',monospace; font-weight: 600; opacity: 0.7; padding-left: 4px; border-left: 1px solid currentColor; }
.rcm-x { position: absolute; top: 14px; right: 16px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: rgba(255,255,255,0.7); width: 28px; height: 28px; border-radius: 8px; cursor: pointer; transition: all 0.15s; z-index: 2; }
.rcm-x:hover { background: rgba(255,255,255,0.14); color: #fff; transform: rotate(90deg); }
/* Body */
.rcm-body { padding: 18px 22px 20px; max-height: 74vh; overflow-y: auto; }
.rcm-state { display: flex; align-items: center; gap: 10px; justify-content: center; padding: 48px; color: rgba(255,255,255,0.6); }
.rcm-state--err { color: #fca5a5; }
.rcm-spinner { width: 22px; height: 22px; border: 2px solid rgba(var(--nc-primary-rgb,0,210,210),0.25); border-top-color: rgba(var(--nc-primary-rgb,0,210,210),1); border-radius: 50%; animation: rcm-spin 0.8s linear infinite; }
@keyframes rcm-spin { to { transform: rotate(360deg); } }
.rcm-desc { color: rgba(255,255,255,0.8); font-size: 0.9rem; line-height: 1.55; margin: 0 0 12px; }
.rcm-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.rcm-chips--tight { margin: 8px 0 0; }
.rcm-chip { font-size: 0.66rem; font-weight: 600; padding: 2px 9px; border-radius: 99px; color: rgba(var(--nc-primary-rgb,0,210,210),0.9); background: rgba(var(--nc-primary-rgb,0,210,210),0.08); border: 1px solid rgba(var(--nc-primary-rgb,0,210,210),0.25); }
.rcm-chip--dim { color: rgba(255,255,255,0.6); background: rgba(255,255,255,0.04); border-color: rgba(255,255,255,0.1); }
.rcm-grid { display: grid; grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
@media (max-width: 700px) { .rcm-grid { grid-template-columns: 1fr; } }
.rcm-sec { background: linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.018)); border: 1px solid rgba(255,255,255,0.07); border-radius: 13px; padding: 13px 15px; transition: border-color 0.18s ease, transform 0.18s ease, box-shadow 0.18s ease; }
.rcm-sec:hover { border-color: rgba(var(--nc-primary-rgb,0,210,210),0.28); transform: translateY(-1px); box-shadow: 0 8px 24px -14px rgba(0,0,0,0.7); }
.rcm-sec--fx:hover { border-color: rgba(245,158,11,0.35); }
.rcm-quarantine { display: flex; align-items: baseline; gap: 10px; margin: 0 0 14px; padding: 10px 14px; background: rgba(220,38,38,0.10); border: 1px solid rgba(220,38,38,0.34); border-radius: 4px; font-size: 0.78rem; line-height: 1.5; color: #fca5a5; }
.rcm-quarantine strong { font-family: 'Fira Code', monospace; font-size: 0.66rem; letter-spacing: 0.1em; color: #f87171; }
.rcm-denied { color: #f59e0b; }
/* REGAUTH (card v0.6) — regulated-action mode + evidence-tier chips */
.rcm-regmode { display: inline-block; margin-left: 6px; padding: 0 7px; border-radius: 999px; font-size: 0.58rem; letter-spacing: 0.06em; text-transform: uppercase; border: 1px solid rgba(240,180,41,0.55); color: #f0c95c; }
.rcm-regmode--enforce { border-color: rgba(255,90,90,0.55); color: #ff8a8a; }
.rcm-regauths .rcm-row dd { line-height: 1.55; }
.rcm-regtier { display: inline-block; margin-left: 6px; padding: 0 7px; border-radius: 999px; font-size: 0.58rem; letter-spacing: 0.05em; border: 1px solid rgba(45,212,191,0.5); color: #2dd4bf; cursor: help; }
.rcm-regtier--verify { background: transparent; font: inherit; font-size: 0.58rem; cursor: pointer; text-decoration: underline dotted; }
.rcm-regtier--verify:hover { background: rgba(45,212,191,0.12); }
.rcm-note { margin: 8px 0 0; font-size: 0.68rem; line-height: 1.5; color: rgba(255,255,255,0.42); }
.rcm-sec-h { display: flex; align-items: center; gap: 8px; font-size: 0.7rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.07em; color: rgba(255,255,255,0.58); margin: 0 0 10px; }
.rcm-bar { width: 3px; height: 13px; border-radius: 99px; display: inline-block; }
.rcm-bar--id { background: #22d3ee; } .rcm-bar--op { background: #a78bfa; } .rcm-bar--cap { background: #34d399; }
.rcm-bar--fx { background: #f59e0b; } .rcm-bar--fed { background: #60a5fa; } .rcm-bar--stat { background: #f0abfc; } .rcm-bar--commit { background: #94a3b8; }
.rcm-sec dl { margin: 0; display: flex; flex-direction: column; gap: 5px; }
.rcm-row { display: flex; align-items: baseline; gap: 10px; font-size: 0.78rem; }
.rcm-row dt { color: rgba(255,255,255,0.45); flex-shrink: 0; width: 92px; }
.rcm-row dd { color: rgba(255,255,255,0.9); margin: 0; min-width: 0; word-break: break-word; }
.rcm-mono { font-family: 'IBM Plex Mono','Fira Code',monospace; font-size: 0.72rem; }
.rcm-trunc { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 220px; }
.rcm-link { color: rgba(var(--nc-primary-rgb,0,210,210),0.95); text-decoration: none; }
.rcm-link:hover { text-decoration: underline; }
.rcm-dim { color: rgba(255,255,255,0.4); }
.rcm-ok { color: #34d399; font-weight: 700; }
.rcm-bad { color: var(--nc-danger, #f87171); font-weight: 700; }
.rcm-unmeasured { color: rgba(255,255,255,0.4); font-style: italic; }
.rcm-bio { font-size: 0.76rem; color: rgba(255,255,255,0.62); margin: 8px 0 0; line-height: 1.45; }
.rcm-note { font-size: 0.7rem; color: rgba(255,255,255,0.45); margin: 8px 0 0; line-height: 1.4; font-style: italic; }
/* Economics flourishes */
.rcm-ccy-row { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; flex-wrap: wrap; }
.rcm-ccy-badge { font-size: 1.05rem; font-weight: 850; letter-spacing: 0.02em; color: #0b0d16; background: linear-gradient(180deg, #fde68a, #f59e0b); padding: 3px 12px; border-radius: 9px; box-shadow: 0 0 18px rgba(245,158,11,0.3); }
.rcm-ccy-cap { font-size: 0.64rem; text-transform: uppercase; letter-spacing: 0.06em; color: rgba(255,255,255,0.45); }
.rcm-fxon { margin-left: auto; font-size: 0.64rem; font-weight: 800; color: #fcd34d; background: rgba(245,158,11,0.12); border: 1px solid rgba(245,158,11,0.4); padding: 2px 8px; border-radius: 99px; }
.rcm-supply { display: inline-flex; align-items: center; gap: 5px; }
.rcm-supply-dot { width: 7px; height: 7px; border-radius: 50%; background: rgba(255,255,255,0.3); display: inline-block; }
.rcm-supply-dot--ok { background: #34d399; box-shadow: 0 0 8px #34d399; animation: rcm-pulse 2.4s ease-in-out infinite; }
@keyframes rcm-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.45; } }
/* Network stat tiles */
.rcm-stats { display: grid; grid-template-columns: repeat(4,1fr); gap: 8px; }
.rcm-stat { text-align: center; background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.02)); border: 1px solid rgba(255,255,255,0.06); border-radius: 9px; padding: 9px 4px; transition: transform 0.15s ease, border-color 0.15s ease; }
.rcm-stat:hover { transform: translateY(-2px); border-color: rgba(var(--nc-primary-rgb,0,210,210),0.3); }
.rcm-stat-n { display: block; font-size: 1.15rem; font-weight: 850; background: linear-gradient(180deg, #fff, rgba(var(--nc-primary-rgb,0,210,210),0.8)); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
.rcm-stat-l { font-size: 0.58rem; text-transform: uppercase; letter-spacing: 0.05em; color: rgba(255,255,255,0.45); }
.rcm-meta { display: flex; align-items: center; gap: 12px; margin-top: 16px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.06); font-size: 0.68rem; color: rgba(255,255,255,0.4); flex-wrap: wrap; }
.rcm-meta-item { font-family: 'IBM Plex Mono',monospace; cursor: default; }
.rcm-meta-copy { cursor: pointer; transition: color 0.15s; }
.rcm-meta-copy:hover { color: rgba(var(--nc-primary-rgb,0,210,210),0.9); }
.rcm-meta-spacer { flex: 1; }
.rcm-rawlink { color: rgba(var(--nc-primary-rgb,0,210,210),0.9); text-decoration: none; font-weight: 600; }
.rcm-rawlink:hover { text-decoration: underline; }
/* transition */
.rcm-fade-enter-active, .rcm-fade-leave-active { transition: opacity 0.2s ease; }
.rcm-fade-enter-from, .rcm-fade-leave-to { opacity: 0; }
.rcm-fade-enter-active .rcm-panel { animation: rcm-pop 0.26s cubic-bezier(.22,.61,.36,1); }
@keyframes rcm-pop { from { transform: translateY(14px) scale(0.975); opacity: 0; } to { transform: none; opacity: 1; } }
@media (prefers-reduced-motion: reduce) {
  .rcm-fade-enter-active .rcm-panel { animation: none; }
  .rcm-spinner, .rcm-halo, .rcm-hero-sheen, .rcm-supply-dot--ok { animation: none; }
}
</style>
