<script setup lang="ts">
// Registry Card v0.3 — operator editor (2026-05-21).
// Spec §5 Phase 5 deliverable. Routed at /admin/registry-card, gated canPlatform.

import { ref, onMounted, reactive, computed } from 'vue'
import { safeExternalUrl } from '@/utils/safeUrl'
import {
  registryCardAdminApi,
  type RegistryCardV03,
  FLARE_ENCIRCLEMENT_VARIANTS,
  FLARE_ENCIRCLEMENT_OVERLAYS,
  FLARE_CORNER_VARIANTS,
} from '@/services/api/registryCardAdmin'
import { useLogger } from '@/composables/useLogger'
import { useI18n } from '@/composables/useI18n'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { searchPlaces, PLACE_QUERY_MIN, type PlaceSearch } from '@/services/api/geocode'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'

const log = useLogger('RegistryCardEditor')
const { t } = useI18n()

const loading = ref(true)
const saving = ref(false)
const rotating = ref(false)
const uploading = ref(false)
const error = ref('')
const successMsg = ref('')
const card = ref<RegistryCardV03 | null>(null)

// Editable subset (operator PUT body).
const draft = reactive({
  display_name: '',
  description: '',
  tags: [] as string[],
  operator: {
    bio: '',
    contact_email: '',
    company: '',
    url: '',
    github_url: '',
    twitter_handle: '',
    timezone: '',
    location_label: '',
    latitude: '' as string,
    longitude: '' as string,
    successor_contact: '',
  },
  visual: {
    orb_color: '#00d2d2',
    orb_glow_color: '#00ffff',
    orb_pulse_speed_hz: 1.4,
    orb_size_px: 16,
    halo_enabled: true,
    halo_thickness: 1.4,
    theme: 'neural' as 'neural' | 'sovereign' | 'custom',
    flare_corner_variant: null as string | null,
    flare_encirclement_variant: null as string | null,
    flare_encirclement_overlay: null as string | null,
  },
  links: {
    whitepaper: '',
    docs: '',
    rss: '',
    github_source: '',
    status_page: '',
    blog: '',
    terms_of_service: '',
    privacy_policy: '',
    code_of_conduct: '',
    support_url: '',
    discord: '',
    matrix: '',
    incident_log: '',
  },
  commitments: {
    data_residency: '',
    gdpr_compliant: false,
    incident_disclosure_sla_hours: 72,
    uptime_sla_pct: 99.0,
    support_response_hours: 72,
    deprecation_notice_days: 30,
    open_source_license: 'AGPL-3.0-or-later',
    key_rotation_max_days: 90,
    card_refresh_max_minutes: 5,
    breach_disclosure_policy: '',
    legally_binding_disclaimer: '',
  },
})

const tagsCsv = ref('')

const jurisdictionProfile = computed(() => card.value?.compliance?.jurisdiction_profile || null)
// REGAUTH (card v0.6) — regulated-action declarations + recorded authorizations.
const regulatedActions = computed<[string, any][]>(() =>
  Object.entries((jurisdictionProfile.value as any)?.regulated_actions || {}))
// §FRAMEPOLICY — the frame's declared rules, straight off the card it publishes.
// Labels are written here rather than derived from the key, because a peer reading
// "peer_trust.restrict_below" learns nothing it did not already know.
const POLICY_LABELS: Record<string, string> = {
  'governance.standard_quorum_percent': 'Quorum for an ordinary proposal',
  'governance.standard_pass_percent': 'Pass threshold',
  'transaction_fees.base_rate_percent': 'Intra-frame fee',
  'transaction_fees.max_rate_percent': 'Maximum fee (velocity-scaled)',
  'transaction_fees.velocity_scaling_factor': 'Velocity scaling factor',
  'staking_rewards.max_apy_percent': 'Maximum payout rate on locked units',
  'enforcement.reputation_bond_min_avt': 'Minimum reputation bond',
  'enforcement.bond_maturity_min_age_days': 'Bond maturity age',
}

const policySource = computed<string>(() => (card.value?.policy as any)?.policy_source || '')
const policyVersion = computed<number>(() => Number((card.value?.policy as any)?.policy_version ?? 0))

const declaredPolicyRows = computed<Array<{ key: string; label: string; value: string; source: string; allowed: string }>>(() => {
  const declared = (card.value?.policy as any)?.declared_params
  if (!declared || typeof declared !== 'object') return []
  return Object.entries(declared as Record<string, any>).map(([key, e]) => {
    const bounds = e?.allowed
    const lo = bounds?.min, hi = bounds?.max
    // "no bound on that side" is a real state and must not render as a number.
    const allowed = bounds ? `${lo ?? 'any'} to ${hi ?? 'any'}` : ''
    return {
      key,
      label: POLICY_LABELS[key] || key,
      value: String(e?.value),
      source: String(e?.source || 'default'),
      allowed,
    }
  })
})

const cardAuthorizations = computed<any[]>(() =>
  (card.value as any)?.compliance?.regulatory_authorizations || [])

const isSovereignPinned = computed(() => {
  const sid = card.value?.identity?.spiffe_id || ''
  // Server pins these SPIFFE IDs — visual edits no-op at next serve.
  return sid === 'spiffe://agentvault.com/registry/Registry-A'
      || sid === 'spiffe://frame-b.theprotocol.cloud/registry/Frame-B'
})

const signatureBadge = computed(() => {
  const sig = card.value?.signature
  if (!sig) return { text: t('registryCardEditorView.signature.unsigned'), color: '#ffaa00' }
  return { text: t('registryCardEditorView.signature.signed', { kid: sig.kid.split('#')[1] || '?' }), color: '#00e676' }
})

// §2026-06-14 — globe location picker (mirrors Settings.vue AgentWorld tab; Nominatim
// forward-geocode + manual lat/lng). The CARD is the authoritative source for this
// registry's position on AgentWorld — saved via the card PUT (operator.latitude/longitude),
// NOT /agents/locations/me. The dev-location store is no longer the source of truth.
const geoQuery = ref('')
const geoResults = ref<{ label: string; lat: number; lng: number }[]>([])
const geoLoading = ref(false)
// §FESUITE (V0578): what the last search answered. A failed or switched-off search used to show nothing, exactly like
// "no place found" (the error body reached .map, threw inside the catch and became []).
const geoState = ref<'idle' | PlaceSearch['kind']>('idle')
let geoSeq = 0
const locValid = computed(() => {
  const la = parseFloat(String(draft.operator.latitude))
  const lo = parseFloat(String(draft.operator.longitude))
  return !isNaN(la) && !isNaN(lo) && la >= -90 && la <= 90 && lo >= -180 && lo <= 180
})
async function searchGeo() {
  if (geoQuery.value.trim().length < PLACE_QUERY_MIN) { geoResults.value = []; geoState.value = 'idle'; return }
  const seq = ++geoSeq
  geoLoading.value = true
  try {
    const r = await searchPlaces(geoQuery.value)
    if (seq !== geoSeq) return   // an older search landing after a newer one never replaces it
    geoResults.value = r.kind === 'found' ? r.places : []
    geoState.value = r.kind
  } finally { if (seq === geoSeq) geoLoading.value = false }
}
function applyGeo(g: { label: string; lat: number; lng: number }) {
  draft.operator.latitude = g.lat.toFixed(4)
  draft.operator.longitude = g.lng.toFixed(4)
  if (!draft.operator.location_label) draft.operator.location_label = g.label.split(', ').slice(0, 2).join(', ')
  geoResults.value = []
  geoQuery.value = ''
  geoState.value = 'idle'
}
function clearLoc() {
  draft.operator.latitude = ''
  draft.operator.longitude = ''
}

async function loadCard() {
  loading.value = true
  error.value = ''
  try {
    const c = await registryCardAdminApi.get()
    card.value = c
    draft.display_name = c.identity.display_name
    draft.description = c.description
    draft.tags = [...(c.tags || [])]
    tagsCsv.value = (c.tags || []).join(', ')
    if (c.operator) {
      draft.operator.bio = c.operator.bio || ''
      draft.operator.contact_email = (c.operator as any).contact_email || ''
      draft.operator.company = c.operator.company || ''
      draft.operator.url = c.operator.url || ''
      draft.operator.github_url = c.operator.github_url || ''
      draft.operator.twitter_handle = c.operator.twitter_handle || ''
      draft.operator.timezone = c.operator.timezone || ''
      draft.operator.location_label = c.operator.location_label || ''
      draft.operator.latitude = (c.operator as any).latitude != null ? String((c.operator as any).latitude) : ''
      draft.operator.longitude = (c.operator as any).longitude != null ? String((c.operator as any).longitude) : ''
      draft.operator.successor_contact = c.operator.successor_contact || ''
    }
    if (c.visual) {
      draft.visual.orb_color = c.visual.orb_color
      draft.visual.orb_glow_color = c.visual.orb_glow_color
      draft.visual.orb_pulse_speed_hz = c.visual.orb_pulse_speed_hz
      draft.visual.orb_size_px = c.visual.orb_size_px
      draft.visual.halo_enabled = c.visual.halo_enabled
      draft.visual.halo_thickness = c.visual.halo_thickness
      draft.visual.theme = c.visual.theme as any
      draft.visual.flare_corner_variant = c.visual.flare_corner_variant || null
      draft.visual.flare_encirclement_variant = c.visual.flare_encirclement_variant || null
      draft.visual.flare_encirclement_overlay = c.visual.flare_encirclement_overlay || null
    }
    if (c.links) Object.assign(draft.links, c.links)
    if (c.commitments) Object.assign(draft.commitments, c.commitments)
  } catch (e: any) {
    error.value = t('registryCardEditorView.errors.loadFailed', { msg: e?.message || e })
    log.error('loadCard failed', e)
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  error.value = ''
  successMsg.value = ''
  try {
    // §2026-06-14 — coord sanity: both-or-neither + in-range (card is authoritative).
    const _la = String(draft.operator.latitude).trim(), _lo = String(draft.operator.longitude).trim()
    if ((_la !== '') !== (_lo !== '')) { error.value = 'Set BOTH latitude and longitude, or neither.'; return }
    if (_la !== '' && !locValid.value) { error.value = 'Invalid coordinates — latitude −90..90, longitude −180..180.'; return }
    draft.tags = tagsCsv.value
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
      .slice(0, 20)
    // Backend RegistryCardLinks fields all carry pattern=r"^https?://" — Pydantic v2
    // applies the regex to empty strings, so '' must become null on the wire.
    // Same shape as the operator block already does via `|| null` per field.
    const stripEmpty = (obj: Record<string, any>) =>
      Object.fromEntries(
        Object.entries(obj).map(([k, v]) =>
          [k, (typeof v === 'string' && v.trim() === '') ? null : v]
        )
      )
    const body: any = {
      display_name: draft.display_name || undefined,
      description: draft.description,
      tags: draft.tags,
      operator: {
        // operator subset — let server merge with existing operator block;
        // strip empty strings so PUT doesn't overwrite real values with ''
        developer_id: card.value?.operator?.developer_id,
        display_name: card.value?.operator?.display_name,
        contact_email: draft.operator.contact_email || null,
        bio: draft.operator.bio || null,
        company: draft.operator.company || null,
        url: draft.operator.url || null,
        github_url: draft.operator.github_url || null,
        twitter_handle: draft.operator.twitter_handle || null,
        timezone: draft.operator.timezone || null,
        location_label: draft.operator.location_label || null,
        latitude: draft.operator.latitude !== '' && !isNaN(parseFloat(String(draft.operator.latitude))) ? parseFloat(String(draft.operator.latitude)) : null,
        longitude: draft.operator.longitude !== '' && !isNaN(parseFloat(String(draft.operator.longitude))) ? parseFloat(String(draft.operator.longitude)) : null,
        successor_contact: draft.operator.successor_contact || null,
      },
      visual: {
        orb_color: draft.visual.orb_color,
        orb_glow_color: draft.visual.orb_glow_color,
        orb_pulse_speed_hz: draft.visual.orb_pulse_speed_hz,
        orb_size_px: draft.visual.orb_size_px,
        halo_enabled: draft.visual.halo_enabled,
        halo_thickness: draft.visual.halo_thickness,
        theme: draft.visual.theme,
        flare_corner_variant: draft.visual.flare_corner_variant,
        flare_encirclement_variant: draft.visual.flare_encirclement_variant,
        flare_encirclement_overlay: draft.visual.flare_encirclement_overlay,
      },
      links: stripEmpty(draft.links),
      commitments: stripEmpty(draft.commitments),
    }
    const updated = await registryCardAdminApi.put(body)
    card.value = updated
    successMsg.value = t('registryCardEditorView.messages.saved', { etag: updated.lifecycle.card_etag.slice(0, 16) })
  } catch (e: any) {
    error.value = t('registryCardEditorView.errors.saveFailed', { msg: e?.response?.data?.detail || e?.message || e })
  } finally {
    saving.value = false
  }
}

async function uploadIcon(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  error.value = ''
  successMsg.value = ''
  try {
    if (file.size > 500 * 1024) {
      throw new Error(t('registryCardEditorView.errors.iconTooLarge', { kb: (file.size / 1024).toFixed(0) }))
    }
    const resp = await registryCardAdminApi.uploadIcon(file)
    successMsg.value = t('registryCardEditorView.messages.iconUploaded', { url: resp.icon_url, kb: (resp.icon_size_bytes / 1024).toFixed(1) })
    await loadCard()
  } catch (e: any) {
    error.value = t('registryCardEditorView.errors.uploadFailed', { msg: e?.response?.data?.detail || e?.message || e })
  } finally {
    uploading.value = false
    if (input) input.value = ''
  }
}

async function uploadAvatar(ev: Event) {
  const input = ev.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  error.value = ''
  successMsg.value = ''
  try {
    if (file.size > 500 * 1024) {
      throw new Error(t('registryCardEditorView.errors.avatarTooLarge', { kb: (file.size / 1024).toFixed(0) }))
    }
    const resp = await registryCardAdminApi.uploadAvatar(file)
    successMsg.value = t('registryCardEditorView.messages.avatarUploaded', { url: resp.operator_avatar_url, kb: (resp.avatar_size_bytes / 1024).toFixed(1) })
    await loadCard()
  } catch (e: any) {
    error.value = t('registryCardEditorView.errors.avatarUploadFailed', { msg: e?.response?.data?.detail || e?.message || e })
  } finally {
    uploading.value = false
    if (input) input.value = ''
  }
}

async function rotateKey() {
  if (!confirm(t('registryCardEditorView.confirm.rotateKey'))) return
  rotating.value = true
  error.value = ''
  successMsg.value = ''
  try {
    const r = await registryCardAdminApi.rotateSigningKey()
    successMsg.value = t('registryCardEditorView.messages.keyRotated', { seq: r.rotation_seq, alg: r.algorithm, kid: r.registry_spiffe_id, rotSeq: r.rotation_seq })
    await loadCard()
  } catch (e: any) {
    error.value = t('registryCardEditorView.errors.rotationFailed', { msg: e?.response?.data?.detail || e?.message || e })
  } finally {
    rotating.value = false
  }
}

onMounted(() => {
  loadCard()
})
</script>

<template>
  <div class="rce">
    <!-- Ambient (mirrors AdminEvents.ae-ambient pattern) -->
    <div class="rce-ambient" aria-hidden="true">
      <div class="rce-grid"></div>
      <div class="rce-glow rce-glow-1"></div>
      <div class="rce-glow rce-glow-2"></div>
    </div>

    <!-- Hero -->
    <section class="rce-hero">
      <div class="rce-hero-inner">
        <div class="rce-chip"><span class="rce-chip-dot"></span>{{ t('registryCardEditorView.hero.chip') }}</div>
        <h1 class="rce-h1">
          <!-- the space sits outside the span: a whitespace-only first child is dropped by Vue's whitespace condensing, and the
               heading read "Self-describingfederation peer card" (the camera, 2026-10-13) -->
          {{ t('registryCardEditorView.hero.title') }} <span class="rce-accent">{{ t('registryCardEditorView.hero.titleAccent') }}</span> {{ t('registryCardEditorView.hero.titleSuffix') }}
        </h1>
        <p class="rce-lead" v-if="card">
          <code class="rce-spiffe">{{ card.identity.spiffe_id }}</code>
          <span class="rce-tier-badge" :class="`rce-tier-${card.identity.tier}`">{{ card.identity.tier }}</span>
          <span class="rce-sig-badge" :style="{ color: signatureBadge.color, borderColor: signatureBadge.color }">
            {{ signatureBadge.text }}
          </span>
        </p>
        <p class="rce-lead-blurb">
          {{ t('registryCardEditorView.hero.blurb') }}
        </p>
        <div v-if="isSovereignPinned" class="rce-sovereign-warn">
          {{ t('registryCardEditorView.hero.sovereignWarn') }}
        </div>
      </div>
    </section>

    <!-- Body -->
    <div class="rce-body">
      <div v-if="loading" class="rce-status rce-status-loading">{{ t('registryCardEditorView.status.loading') }}</div>
      <div v-if="error" class="rce-status rce-status-error">{{ error }}</div>
      <div v-if="successMsg" class="rce-status rce-status-success">{{ successMsg }}</div>

      <div v-if="card && !loading" class="rc-grid">
      <!-- Preview tile -->
      <section class="rc-section rc-preview">
        <h2>{{ t('registryCardEditorView.sections.preview') }}</h2>
        <!-- FX/encirclement fix (2026-06-02): the Live Preview now renders the
             SELECTED flare encirclement (was a bare orb that ignored the
             encirclement selection — strategy §R-bonus). Mirrors the picker's
             FlareEncirclement usage; falls back to the orb when no flare chosen. -->
        <div class="rc-preview-stage">
          <FlareEncirclement
            v-if="draft.visual.flare_encirclement_variant"
            tier="shadow_chancellor"
            :variant="draft.visual.flare_encirclement_variant"
            :overlay="draft.visual.flare_encirclement_overlay"
            :avatar-url="card.visual?.icon_url || undefined"
            :initials="(draft.display_name || card.identity.registry_name).slice(0,2).toUpperCase()"
            size="md"
          />
          <div v-else class="rc-orb-preview" :style="{
            background: `radial-gradient(circle at 30% 30%, ${draft.visual.orb_glow_color}, ${draft.visual.orb_color} 60%, ${draft.visual.orb_color}88 100%)`,
            width: `${draft.visual.orb_size_px * 4}px`,
            height: `${draft.visual.orb_size_px * 4}px`,
            animation: `rc-pulse ${1 / draft.visual.orb_pulse_speed_hz}s ease-in-out infinite`,
          }"></div>
        </div>
        <div class="rc-preview-meta">
          <div><strong>{{ draft.display_name || card.identity.registry_name }}</strong></div>
          <div class="rc-mute">{{ card.identity.tier }}</div>
          <div class="rc-mute">{{ t('registryCardEditorView.preview.orbLabel') }}: {{ draft.visual.orb_color }} · {{ t('registryCardEditorView.preview.glowLabel') }}: {{ draft.visual.orb_glow_color }}</div>
          <div class="rc-mute">{{ draft.visual.orb_pulse_speed_hz.toFixed(1) }} Hz · {{ draft.visual.orb_size_px }}px · {{ draft.visual.theme }}</div>
          <div class="rc-mute" v-if="draft.visual.flare_encirclement_variant">{{ t('registryCardEditorView.preview.encirclementLabel') }}: {{ draft.visual.flare_encirclement_variant }}<template v-if="draft.visual.flare_encirclement_overlay"> · {{ t('registryCardEditorView.preview.overlayLabel') }}: {{ draft.visual.flare_encirclement_overlay }}</template></div>
          <div class="rc-mute" v-if="card.visual?.icon_url">
            {{ t('registryCardEditorView.preview.iconLabel') }}: <a :href="safeExternalUrl(card.visual.icon_url)" target="_blank" rel="noopener noreferrer">{{ t('registryCardEditorView.preview.viewLink') }}</a>
          </div>
        </div>
      </section>

      <!-- Identity (locked) -->
      <section class="rc-section">
        <h2>{{ t('registryCardEditorView.sections.identity') }} <span class="rc-locked">{{ t('registryCardEditorView.badges.locked') }}</span></h2>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.identity.spiffeId') }}</label><code>{{ card.identity.spiffe_id }}</code></div>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.identity.registryName') }}</label><code>{{ card.identity.registry_name }}</code></div>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.identity.trustDomain') }}</label><code>{{ card.identity.trust_domain }}</code></div>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.identity.publicUrl') }}</label><code>{{ card.identity.public_url }}</code></div>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.identity.tier') }}</label><code>{{ card.identity.tier }}</code></div>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.identity.founded') }}</label><code>{{ card.identity.founded_at }}</code></div>
      </section>

      <!-- Operator persona -->
      <section class="rc-section">
        <h2>{{ t('registryCardEditorView.sections.operatorPersona') }}</h2>
        <div class="rc-field-row">
          <label for="rc-operator-display-name">{{ t('registryCardEditorView.operator.displayName') }}</label>
          <input id="rc-operator-display-name" v-model="draft.display_name" type="text" maxlength="128" />
        </div>
        <div class="rc-field-row">
          <label for="rc-operator-bio">{{ t('registryCardEditorView.operator.bio') }}</label>
          <textarea id="rc-operator-bio" v-model="draft.operator.bio" rows="3" maxlength="2000"></textarea>
        </div>
        <div class="rc-field-row">
          <label for="rc-operator-contact-email">{{ t('registryCardEditorView.operator.contactEmail') }}</label>
          <input id="rc-operator-contact-email" v-model="draft.operator.contact_email" type="email" :placeholder="t('registryCardEditorView.operator.contactEmailPlaceholder')" />
        </div>
        <div class="rc-field-row rc-field-row--icon">
          <label>{{ t('registryCardEditorView.operator.avatarLabel') }}</label>
          <label class="rc-file-input">
            <input type="file" accept="image/png,image/jpeg" @change="uploadAvatar" :disabled="uploading" />
            <span class="rc-file-input-text">
              {{ uploading ? t('registryCardEditorView.fileInput.uploading') : ((card.operator as any)?.operator_avatar_url ? t('registryCardEditorView.fileInput.replaceAvatar') : t('registryCardEditorView.fileInput.chooseFile')) }}
            </span>
          </label>
        </div>
        <div class="rc-field-row">
          <label for="rc-operator-company">{{ t('registryCardEditorView.operator.company') }}</label>
          <input id="rc-operator-company" v-model="draft.operator.company" type="text" maxlength="256" />
        </div>
        <div class="rc-field-row">
          <label for="rc-operator-url">{{ t('registryCardEditorView.operator.url') }}</label>
          <input id="rc-operator-url" v-model="draft.operator.url" type="url" placeholder="https://…" />
        </div>
        <div class="rc-field-row">
          <label for="rc-operator-github">{{ t('registryCardEditorView.operator.github') }}</label>
          <input id="rc-operator-github" v-model="draft.operator.github_url" type="url" placeholder="https://github.com/…" />
        </div>
        <div class="rc-field-row">
          <label for="rc-operator-twitter">{{ t('registryCardEditorView.operator.twitter') }}</label>
          <input id="rc-operator-twitter" v-model="draft.operator.twitter_handle" type="text" :placeholder="t('registryCardEditorView.operator.twitterPlaceholder')" />
        </div>
        <div class="rc-field-row">
          <label for="rc-operator-timezone">{{ t('registryCardEditorView.operator.timezone') }}</label>
          <input id="rc-operator-timezone" v-model="draft.operator.timezone" type="text" :placeholder="t('registryCardEditorView.operator.timezonePlaceholder')" />
        </div>
        <!-- §2026-06-14 — AUTHORITATIVE globe location (mirrors dev Settings → AgentWorld). -->
        <div class="rc-loc-row">
          <label class="rc-loc-heading">
            <Icon name="mdi:earth" /> {{ t('registryCardEditorView.operator.location') }}
            <span class="rc-loc-tag">GLOBE · AUTHORITATIVE</span>
          </label>
          <div class="rc-loc">
            <div class="rc-loc-search">
              <input v-model="geoQuery" type="text" placeholder="Search a city or address…" @keydown.enter.prevent="searchGeo" />
              <button type="button" class="rc-loc-search-btn" @click="searchGeo" :disabled="geoLoading || geoQuery.trim().length < PLACE_QUERY_MIN" data-testid="rc-geo-search">
                <Icon v-if="!geoLoading" name="mdi:magnify" /> {{ geoLoading ? '…' : 'Search' }}
              </button>
            </div>
            <div v-if="geoResults.length" class="rc-loc-results">
              <button type="button" v-for="(g, i) in geoResults" :key="i" class="rc-loc-result" @click="applyGeo(g)">
                <span class="rc-loc-coord">{{ g.lat.toFixed(4) }}, {{ g.lng.toFixed(4) }}</span>
                <span class="rc-loc-name">{{ g.label }}</span>
              </button>
            </div>
            <p v-else-if="geoState === 'none'" class="rc-mute" data-testid="rc-geo-none">No place found for that name. Try another, or enter the coordinates below.</p>
            <p v-else-if="geoState === 'off'" class="rc-mute" data-testid="rc-geo-off">This frame does not search places. Enter the coordinates below.</p>
            <ReadFailedNotice v-else-if="geoState === 'failed'" dense data-testid="rc-geo-failed"
              text="The place search could not be read just now." :retry="searchGeo" />
            <div class="rc-loc-grid">
              <div class="rc-loc-field">
                <label for="rc-location-latitude">{{ t('settingsView.location.latitude') }}</label>
                <input id="rc-location-latitude" v-model="draft.operator.latitude" type="number" step="0.0001" min="-90" max="90" placeholder="50.1109" />
              </div>
              <div class="rc-loc-field">
                <label for="rc-location-longitude">{{ t('settingsView.location.longitude') }}</label>
                <input id="rc-location-longitude" v-model="draft.operator.longitude" type="number" step="0.0001" min="-180" max="180" placeholder="8.6821" />
              </div>
            </div>
            <div class="rc-loc-field">
              <label for="rc-location-location-label">{{ t('settingsView.location.locationLabel') }}</label>
              <input id="rc-location-location-label" v-model="draft.operator.location_label" type="text" :placeholder="t('registryCardEditorView.operator.locationPlaceholder')" />
            </div>
            <div v-if="locValid" class="rc-loc-pill">
              <span class="rc-loc-dot"></span>
              <span class="rc-loc-pill-coord">{{ Number(draft.operator.latitude).toFixed(4) }}°, {{ Number(draft.operator.longitude).toFixed(4) }}°</span>
              <span v-if="draft.operator.location_label" class="rc-loc-pill-label">{{ draft.operator.location_label }}</span>
              <button type="button" class="rc-loc-clear" @click="clearLoc">clear</button>
            </div>
            <p class="rc-loc-hint">Authoritative position for this registry on the AgentWorld globe. {{ t('settingsView.location.nominatimCredit') }} <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">openstreetmap.org/copyright</a></p>
          </div>
        </div>
        <div class="rc-field-row">
          <label for="rc-operator-successor">{{ t('registryCardEditorView.operator.successor') }}</label>
          <input id="rc-operator-successor" v-model="draft.operator.successor_contact" type="text" :placeholder="t('registryCardEditorView.operator.successorPlaceholder')" />
        </div>
      </section>

      <!-- Description + tags -->
      <section class="rc-section">
        <h2>{{ t('registryCardEditorView.sections.descriptionTags') }}</h2>
        <div class="rc-field-row">
          <label for="rc-desc-tags-description">{{ t('registryCardEditorView.descTags.description') }}</label>
          <textarea id="rc-desc-tags-description" v-model="draft.description" rows="3" maxlength="2000"></textarea>
        </div>
        <div class="rc-field-row">
          <label for="rc-desc-tags-tags-label">{{ t('registryCardEditorView.descTags.tagsLabel') }}</label>
          <input id="rc-desc-tags-tags-label" v-model="tagsCsv" type="text" :placeholder="t('registryCardEditorView.descTags.tagsPlaceholder')" />
        </div>
      </section>

      <!-- Visual -->
      <section class="rc-section">
        <h2>{{ t('registryCardEditorView.sections.visual') }} <span v-if="isSovereignPinned" class="rc-locked">{{ t('registryCardEditorView.badges.pinned') }}</span></h2>
        <div class="rc-field-row">
          <label for="rc-visual-orb-color" id="rc-visual-orb-color-label">{{ t('registryCardEditorView.visual.orbColor') }}</label>
          <input id="rc-visual-orb-color" v-model="draft.visual.orb_color" type="color" :disabled="isSovereignPinned" />
          <input aria-labelledby="rc-visual-orb-color-label" v-model="draft.visual.orb_color" type="text" :disabled="isSovereignPinned" maxlength="7" />
        </div>
        <div class="rc-field-row">
          <label for="rc-visual-glow-color" id="rc-visual-glow-color-label">{{ t('registryCardEditorView.visual.glowColor') }}</label>
          <input id="rc-visual-glow-color" v-model="draft.visual.orb_glow_color" type="color" :disabled="isSovereignPinned" />
          <input aria-labelledby="rc-visual-glow-color-label" v-model="draft.visual.orb_glow_color" type="text" :disabled="isSovereignPinned" maxlength="7" />
        </div>
        <div class="rc-field-row">
          <label for="rc-visual-pulse-hz">{{ t('registryCardEditorView.visual.pulseHz', { val: draft.visual.orb_pulse_speed_hz.toFixed(2) }) }}</label>
          <input id="rc-visual-pulse-hz" v-model.number="draft.visual.orb_pulse_speed_hz" type="range" min="0.5" max="3" step="0.1" :disabled="isSovereignPinned" />
        </div>
        <div class="rc-field-row">
          <label for="rc-visual-size-px">{{ t('registryCardEditorView.visual.sizePx', { val: draft.visual.orb_size_px }) }}</label>
          <input id="rc-visual-size-px" v-model.number="draft.visual.orb_size_px" type="range" min="10" max="24" step="1" :disabled="isSovereignPinned" />
        </div>
        <div class="rc-field-row">
          <label for="rc-visual-halo-enabled">{{ t('registryCardEditorView.visual.haloEnabled') }}</label>
          <input id="rc-visual-halo-enabled" v-model="draft.visual.halo_enabled" type="checkbox" :disabled="isSovereignPinned" />
        </div>
        <div class="rc-field-row">
          <label for="rc-visual-halo-thickness">{{ t('registryCardEditorView.visual.haloThickness') }}</label>
          <input id="rc-visual-halo-thickness" v-model.number="draft.visual.halo_thickness" type="range" min="0.5" max="2.5" step="0.1" :disabled="isSovereignPinned" />
        </div>
        <div class="rc-field-row">
          <label for="registrycardeditor-sel-581">{{ t('registryCardEditorView.visual.theme') }}</label>
          <select id="registrycardeditor-sel-581" v-model="draft.visual.theme" :disabled="isSovereignPinned">
            <option value="neural">neural</option>
            <option value="sovereign">sovereign</option>
            <option value="custom">custom</option>
          </select>
        </div>
        <div class="rc-field-row rc-field-row--icon">
          <label>{{ t('registryCardEditorView.visual.iconLabel') }}</label>
          <label class="rc-file-input">
            <input type="file" accept="image/png,image/jpeg" @change="uploadIcon" :disabled="uploading" />
            <span class="rc-file-input-text">
              {{ uploading ? t('registryCardEditorView.fileInput.uploading') : (card.visual?.icon_url ? t('registryCardEditorView.fileInput.replaceIcon') : t('registryCardEditorView.fileInput.chooseFile')) }}
            </span>
          </label>
        </div>
      </section>

      <!-- Flare layer (v0.3.1 — mirror of agent encirclement + broken-machine overlay) -->
      <section class="rc-section rc-section-flare">
        <h2>{{ t('registryCardEditorView.sections.flareLayer') }} <span class="rc-locked">{{ t('registryCardEditorView.badges.cosmetic') }}</span></h2>
        <p class="rc-blurb-inline">
          {{ t('registryCardEditorView.flare.blurb') }}
        </p>

        <h3 class="rc-subhead">{{ t('registryCardEditorView.flare.encirclementSubhead') }}</h3>
        <div class="rc-flare-grid">
          <button class="rc-flare-tile" :class="{ active: !draft.visual.flare_encirclement_variant }"
                  @click="draft.visual.flare_encirclement_variant = null; draft.visual.flare_encirclement_overlay = null">
            <div class="rc-flare-preview">
              <FlareEncirclement tier="shadow_chancellor" :variant="null" :overlay="null" :avatar-url="card.visual?.icon_url || undefined" :initials="(draft.display_name || card.identity.registry_name).slice(0,2).toUpperCase()" size="md" />
            </div>
            <span class="rc-flare-label">{{ t('registryCardEditorView.flare.none') }}</span>
          </button>
          <button v-for="v in FLARE_ENCIRCLEMENT_VARIANTS" :key="`enc-${v}`"
                  class="rc-flare-tile" :class="{ active: draft.visual.flare_encirclement_variant === v }"
                  @click="draft.visual.flare_encirclement_variant = v">
            <div class="rc-flare-preview">
              <FlareEncirclement tier="shadow_chancellor" :variant="v" :overlay="null" :avatar-url="card.visual?.icon_url || undefined" :initials="(draft.display_name || card.identity.registry_name).slice(0,2).toUpperCase()" size="md" />
            </div>
            <span class="rc-flare-label">{{ v }}</span>
          </button>
        </div>

        <h3 class="rc-subhead">{{ t('registryCardEditorView.flare.overlaySubhead') }}
          <span class="rc-mute" v-if="!draft.visual.flare_encirclement_variant">{{ t('registryCardEditorView.flare.overlayRequiresEncirclement') }}</span>
        </h3>
        <div class="rc-flare-grid" :class="{ 'rc-flare-disabled': !draft.visual.flare_encirclement_variant }">
          <button class="rc-flare-tile" :class="{ active: !draft.visual.flare_encirclement_overlay }"
                  :disabled="!draft.visual.flare_encirclement_variant"
                  @click="draft.visual.flare_encirclement_overlay = null">
            <div class="rc-flare-preview">
              <FlareEncirclement
                tier="shadow_chancellor"
                :variant="draft.visual.flare_encirclement_variant"
                :overlay="null"
                :avatar-url="card.visual?.icon_url || undefined"
                :initials="(draft.display_name || card.identity.registry_name).slice(0,2).toUpperCase()"
                size="md" />
            </div>
            <span class="rc-flare-label">{{ t('registryCardEditorView.flare.none') }}</span>
          </button>
          <button v-for="o in FLARE_ENCIRCLEMENT_OVERLAYS" :key="`ov-${o}`"
                  class="rc-flare-tile" :class="{ active: draft.visual.flare_encirclement_overlay === o }"
                  :disabled="!draft.visual.flare_encirclement_variant"
                  @click="draft.visual.flare_encirclement_overlay = o">
            <div class="rc-flare-preview">
              <FlareEncirclement
                tier="shadow_chancellor"
                :variant="draft.visual.flare_encirclement_variant"
                :overlay="o"
                :avatar-url="card.visual?.icon_url || undefined"
                :initials="(draft.display_name || card.identity.registry_name).slice(0,2).toUpperCase()"
                size="md" />
            </div>
            <span class="rc-flare-label">{{ o }}</span>
          </button>
        </div>

        <h3 class="rc-subhead">{{ t('registryCardEditorView.flare.cornerSubhead') }} <span class="rc-mute">{{ t('registryCardEditorView.flare.cornerNote') }}</span></h3>
        <div class="rc-corner-grid">
          <button class="rc-corner-tile" :class="{ active: !draft.visual.flare_corner_variant }"
                  @click="draft.visual.flare_corner_variant = null">{{ t('registryCardEditorView.flare.none') }}</button>
          <button v-for="cv in FLARE_CORNER_VARIANTS" :key="`corner-${cv}`"
                  class="rc-corner-tile" :class="{ active: draft.visual.flare_corner_variant === cv }"
                  @click="draft.visual.flare_corner_variant = cv">{{ cv }}</button>
        </div>
      </section>

      <!-- Economic (derived display) -->
      <section class="rc-section">
        <h2>{{ t('registryCardEditorView.sections.economic') }} <span class="rc-locked">{{ t('registryCardEditorView.badges.derived') }}</span></h2>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.economic.intraFee') }}</label><code>{{ card.fees.intra_registry?.base_rate_percent }}%</code></div>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.economic.crossFee') }}</label><code>{{ card.fees.cross_registry?.base_rate_percent }}% → {{ card.fees.cross_registry?.fee_recipient }}</code></div>
        <div class="rc-field-row">
          <label>{{ t('registryCardEditorView.economic.hostingFee') }}</label>
          <code v-if="card.fees.hosting?.enabled">{{ card.fees.hosting.rate_percent_of_agent_service_fee }}% {{ t('registryCardEditorView.economic.hostingEnabled') }}</code>
          <code v-else>{{ t('registryCardEditorView.economic.hostingDisabled') }}</code>
        </div>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.economic.feeCollector') }}</label><code>{{ card.fees.fee_collector_address }}</code></div>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.economic.waterfall') }}</label><code>{{ card.fees.fee_waterfall_policy }}</code></div>
        <div class="rc-field-row"><label>{{ t('registryCardEditorView.economic.supplyStatus') }}</label>
          <code :style="{ color: card.economic.supply_invariant_status === 'OK' ? '#00e676' : '#ff5252' }">
            {{ card.economic.supply_invariant_status }} (Δ {{ card.economic.supply_invariant_delta }})
          </code>
        </div>
      </section>

      <!-- Jurisdiction profile — computed from this deployment's declaration, signed into
           the card. Read-only here on purpose: the card renders what the deployment
           declares; the declaration itself is set through the jurisdiction-profile API. -->
      <section class="rc-section">
        <h2>Jurisdiction profile <span class="rc-locked">derived</span></h2>
        <template v-if="jurisdictionProfile">
          <div class="rc-field-row"><label>Declared profile</label><code>{{ jurisdictionProfile.name }} (v{{ jurisdictionProfile.version }})</code></div>
          <div class="rc-field-row">
            <label>Features denied</label>
            <code v-if="(jurisdictionProfile.features_denied || []).length" style="color:#f59e0b">{{ (jurisdictionProfile.features_denied || []).join(', ') }}</code>
            <code v-else>none</code>
          </div>
          <div class="rc-field-row"><label>Declared at</label><code>{{ jurisdictionProfile.declared_at }}</code></div>
          <div class="rc-field-row"><label>Profile hash</label><code class="rc-hash">{{ jurisdictionProfile.profile_hash }}</code></div>
          <div class="rc-field-row"><label>Declared by</label><code>{{ jurisdictionProfile.declared_by || 'operator' }}</code></div>
          <div v-if="regulatedActions.length" class="rc-field-row"><label>Regulated actions</label>
            <code>{{ regulatedActions.map(([a, e]) => a + ' (' + (e?.authority || '?') + ', ' + (e?.mode || 'shadow') + ')').join(' · ') }}</code>
          </div>
          <p class="rc-mute">Published on the signed card, so peers and the public can verify what this
            registry claims to run. Changing it is done through the jurisdiction-profile admin API.</p>
        </template>
        <template v-else>
          <div class="rc-field-row"><label>Declared profile</label><code>none declared</code></div>
          <p class="rc-mute">No jurisdiction profile is declared on this registry, so no feature scope is
            restricted and no compliance block appears on the card. Declaring one is the operator's
            decision and is not legal advice from the Provider.</p>
        </template>
        <!-- REGAUTH (card v0.6) — recorded authorizations are their own attestation
             and publish on the card whether or not a profile is declared. -->
        <template v-if="cardAuthorizations.length">
          <div class="rc-field-row" v-for="a in cardAuthorizations" :key="a.reference_id + (a.subject_ref || '')">
            <label>Authorization</label>
            <code>{{ a.action }}<template v-if="a.subject_ref"> ({{ a.subject_ref }})</template>:
              {{ a.authority }}, ref {{ a.reference_id }}<template v-if="a.valid_until">, until {{ a.valid_until.slice(0, 10) }}</template></code>
          </div>
          <p class="rc-mute">Recorded regulatory authorizations, signature-covered via the card's
            compliance digest. Recorded and revoked on the Jurisdiction admin panel.</p>
        </template>
      </section>

      <!-- §FRAMEPOLICY (2026-09-11) — THE RULES THIS FRAME APPLIES, as the signed
           card publishes them. Read-only here for the same reason the jurisdiction
           block is: the card renders what the frame declares, and the declaration
           moves through the enforcement-policy API or a governance proposal.

           ⚠ This block used to publish the MINIMUM of each allowed range as "the
           operator's chosen value", so EU's card told every peer it required a 5%
           quorum while the code applied 10% and the one frame with a real policy
           document had declared 20%. Each row now says whether the FRAME set the
           value or whether it is the shipped default, because "unset" and "set to
           the default" are different facts to a peer deciding whether to federate. -->
      <section class="rc-section" data-testid="rce-policy">
        <h2>Declared policy <span class="rc-locked">derived</span></h2>
        <template v-if="declaredPolicyRows.length">
          <div class="rc-field-row">
            <label>Policy document</label>
            <code>
              <template v-if="policySource === 'amended'">v{{ policyVersion }} · amended by this frame</template>
              <template v-else>factory default · never amended</template>
            </code>
          </div>
          <div class="rc-field-row" v-for="row in declaredPolicyRows" :key="row.key">
            <label>{{ row.label }}</label>
            <code>
              {{ row.value }}
              <span class="rce-pol-src" :class="row.source === 'policy' ? 'rce-pol-src--set' : 'rce-pol-src--dflt'">
                {{ row.source === 'policy' ? 'this frame' : 'default' }}
              </span>
              <span v-if="row.allowed" class="rc-mute">&nbsp;· network allows {{ row.allowed }}</span>
            </code>
          </div>
          <div class="rc-field-row"><label>Locked params hash</label><code class="rc-hash">{{ card.policy?.locked_params_hash }}</code></div>
          <div class="rc-field-row"><label>Policy hash</label><code class="rc-hash">{{ card.federation?.policy_hash }}</code></div>
          <p class="rc-mute">Published on the signed card so a peer can read this frame's rules before
            federating rather than discovering them in a refusal. The same hash is served by
            <code>/api/v1/federation/policy-compliance</code>; if the two ever disagree, one of them is
            describing a document this frame is not running.</p>
        </template>
        <template v-else>
          <div class="rc-field-row"><label>Declared policy</label><code>not published on this card</code></div>
          <p class="rc-mute">This card carries no declared-policy block, which means it was built by a
            registry older than V0325. Peers reading it cannot tell which rules this frame applies.</p>
        </template>
      </section>

      <!-- Commitments -->
      <section class="rc-section">
        <h2>{{ t('registryCardEditorView.sections.commitments') }}</h2>
        <div class="rc-field-row">
          <label for="rc-commitments-data-residency">{{ t('registryCardEditorView.commitments.dataResidency') }}</label>
          <input id="rc-commitments-data-residency" v-model="draft.commitments.data_residency" type="text" :placeholder="t('registryCardEditorView.commitments.dataResidencyPlaceholder')" />
        </div>
        <div class="rc-field-row">
          <label for="rc-commitments-gdpr">{{ t('registryCardEditorView.commitments.gdpr') }}</label>
          <input id="rc-commitments-gdpr" v-model="draft.commitments.gdpr_compliant" type="checkbox" />
        </div>
        <div class="rc-field-row">
          <label for="rc-commitments-incident-sla">{{ t('registryCardEditorView.commitments.incidentSla') }}</label>
          <input id="rc-commitments-incident-sla" v-model.number="draft.commitments.incident_disclosure_sla_hours" type="number" min="1" max="720" />
        </div>
        <div class="rc-field-row">
          <label for="rc-commitments-uptime-sla">{{ t('registryCardEditorView.commitments.uptimeSla') }}</label>
          <input id="rc-commitments-uptime-sla" v-model.number="draft.commitments.uptime_sla_pct" type="number" min="0" max="100" step="0.1" />
        </div>
        <div class="rc-field-row">
          <label for="rc-commitments-support-response">{{ t('registryCardEditorView.commitments.supportResponse') }}</label>
          <input id="rc-commitments-support-response" v-model.number="draft.commitments.support_response_hours" type="number" min="1" max="720" />
        </div>
        <div class="rc-field-row">
          <label for="rc-commitments-deprecation-notice">{{ t('registryCardEditorView.commitments.deprecationNotice') }}</label>
          <input id="rc-commitments-deprecation-notice" v-model.number="draft.commitments.deprecation_notice_days" type="number" min="0" max="365" />
        </div>
        <div class="rc-field-row">
          <label for="rc-commitments-oss-license">{{ t('registryCardEditorView.commitments.ossLicense') }}</label>
          <input id="rc-commitments-oss-license" v-model="draft.commitments.open_source_license" type="text" maxlength="64" />
        </div>
        <div class="rc-field-row">
          <label for="rc-commitments-key-rotation-max">{{ t('registryCardEditorView.commitments.keyRotationMax') }}</label>
          <input id="rc-commitments-key-rotation-max" v-model.number="draft.commitments.key_rotation_max_days" type="number" min="1" max="365" />
        </div>
        <div class="rc-field-row">
          <label for="rc-commitments-breach-disclosure">{{ t('registryCardEditorView.commitments.breachDisclosure') }}</label>
          <textarea id="rc-commitments-breach-disclosure" v-model="draft.commitments.breach_disclosure_policy" rows="2" maxlength="500" :placeholder="t('registryCardEditorView.commitments.breachDisclosurePlaceholder')"></textarea>
        </div>
        <div class="rc-field-row">
          <label for="rc-commitments-legal-disclaimer">{{ t('registryCardEditorView.commitments.legalDisclaimer') }}</label>
          <textarea id="rc-commitments-legal-disclaimer" v-model="draft.commitments.legally_binding_disclaimer" rows="2" maxlength="1000"></textarea>
        </div>
      </section>

      <!-- Links -->
      <section class="rc-section">
        <h2>{{ t('registryCardEditorView.sections.links') }}</h2>
        <div v-for="(k, label) in {
          whitepaper: t('registryCardEditorView.links.whitepaper'),
          docs: t('registryCardEditorView.links.docs'),
          github_source: t('registryCardEditorView.links.githubSource'),
          status_page: t('registryCardEditorView.links.statusPage'),
          blog: t('registryCardEditorView.links.blog'),
          rss: t('registryCardEditorView.links.rss'),
          terms_of_service: t('registryCardEditorView.links.terms'),
          privacy_policy: t('registryCardEditorView.links.privacy'),
          code_of_conduct: t('registryCardEditorView.links.codeOfConduct'),
          support_url: t('registryCardEditorView.links.support'),
          discord: t('registryCardEditorView.links.discord'),
          matrix: t('registryCardEditorView.links.matrix'),
          incident_log: t('registryCardEditorView.links.incidentLog'),
        }" :key="k" class="rc-field-row">
          <label :for="'rc-link-' + label">{{ k }}</label>
          <input :id="'rc-link-' + label" v-model="(draft.links as any)[label]" type="url" placeholder="https://…" />
        </div>
      </section>

      <!-- Signing key -->
      <section class="rc-section">
        <h2>{{ t('registryCardEditorView.sections.signingKey') }}</h2>
        <div class="rc-field-row" v-if="card.signature">
          <label>{{ t('registryCardEditorView.signingKey.currentKid') }}</label>
          <code>{{ card.signature.kid }}</code>
        </div>
        <div class="rc-field-row" v-if="card.signature">
          <label>{{ t('registryCardEditorView.signingKey.algorithm') }}</label>
          <code>{{ card.signature.alg }}</code>
        </div>
        <div class="rc-field-row" v-if="card.signature">
          <label>{{ t('registryCardEditorView.signingKey.signedFields') }}</label>
          <code>{{ card.signature.signed_canonical.length }} {{ t('registryCardEditorView.signingKey.canonicalPaths') }}</code>
        </div>
        <div class="rc-field-row" v-else>
          <label>{{ t('registryCardEditorView.signingKey.statusLabel') }}</label>
          <code style="color:#ffaa00">{{ t('registryCardEditorView.signingKey.noSignatureYet') }}</code>
        </div>
        <button class="rc-btn-rotate" @click="rotateKey" :disabled="rotating">
          {{ rotating ? t('registryCardEditorView.buttons.rotating') : t('registryCardEditorView.buttons.rotateKey') }}
        </button>
      </section>

      <div class="rc-actions">
        <button class="rc-btn-save" @click="save" :disabled="saving">
          {{ saving ? t('registryCardEditorView.buttons.saving') : t('registryCardEditorView.buttons.save') }}
        </button>
        <button class="rc-btn-reload" @click="loadCard" :disabled="loading">{{ t('registryCardEditorView.buttons.reload') }}</button>
      </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ── Page shell + ambient (mirror AdminEvents.ae-*) ─────── */
.rce {
  position: relative;
  min-height: 100vh;
  color: rgba(255,255,255,0.9);
  /* Theme alias — wires this view to body.theme-{neural|sovereign|custom}
     via the canonical --nc-primary tokens. Without these, all our var(--cyan)
     references silently fall back to literal #00d2d2 and never update on
     theme change. Pattern mirrored from AdminEvents.vue:668. */
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --mono: 'IBM Plex Mono', 'Fira Code', monospace;
}
.rce-ambient { position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden; }
.rce-grid {
  position: absolute; inset: 0;
  background-image:
    linear-gradient(rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--cyan-rgb), 0.03) 1px, transparent 1px);
  background-size: 56px 56px;
  opacity: 0.6;
}
.rce-glow { position: absolute; border-radius: 50%; filter: blur(120px); opacity: 0.18; }
.rce-glow-1 { width: 420px; height: 420px; background: rgba(var(--cyan-rgb), 0.6); top: -100px; right: -80px; }
.rce-glow-2 { width: 320px; height: 320px; background: rgba(255, 107, 53, 0.4); bottom: -60px; left: -100px; }

/* ── Globe location picker (§2026-06-14 — AUTHORITATIVE card geo) ─────────── */
.rc-loc-row { margin-bottom: 14px; }
.rc-loc-heading {
  display: flex; align-items: center; gap: 8px; margin-bottom: 10px;
  font-size: 0.8rem; color: rgba(255,255,255,0.82); font-weight: 500;
}
.rc-loc-tag {
  font-family: var(--mono, ui-monospace, monospace); font-size: 0.6rem; letter-spacing: 0.12em;
  color: var(--cyan, #00d2d2); background: rgba(var(--cyan-rgb, 0,210,210), 0.1);
  border: 1px solid rgba(var(--cyan-rgb, 0,210,210), 0.25); border-radius: 3px; padding: 2px 6px;
}
.rc-loc { display: flex; flex-direction: column; gap: 10px; }
.rc-loc input {
  width: 100%; box-sizing: border-box; background: rgba(0,0,0,0.25);
  border: 1px solid rgba(var(--cyan-rgb, 0,210,210), 0.18); border-radius: 5px;
  color: rgba(255,255,255,0.92); padding: 8px 11px; font-size: 0.82rem;
  font-family: inherit; transition: border-color 120ms;
}
.rc-loc input:focus { outline: none; border-color: rgba(var(--cyan-rgb, 0,210,210), 0.55); }
.rc-loc-search { display: flex; gap: 8px; }
.rc-loc-search input { flex: 1; }
.rc-loc-search-btn {
  display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
  padding: 0 16px; font-family: var(--mono, ui-monospace, monospace); font-size: 0.72rem; font-weight: 700;
  letter-spacing: 0.05em; color: #001020; cursor: pointer;
  background: var(--cyan, #00d2d2); border: none; border-radius: 5px;
}
.rc-loc-search-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.rc-loc-results { display: flex; flex-direction: column; gap: 5px; max-height: 230px; overflow-y: auto; }
.rc-loc-result {
  display: flex; align-items: baseline; gap: 10px; padding: 8px 12px;
  background: rgba(var(--cyan-rgb, 0,210,210), 0.04); border: 1px solid rgba(var(--cyan-rgb, 0,210,210), 0.1);
  border-radius: 6px; cursor: pointer; text-align: left; transition: background 120ms;
}
.rc-loc-result:hover { background: rgba(var(--cyan-rgb, 0,210,210), 0.12); }
.rc-loc-coord { font-family: var(--mono, ui-monospace, monospace); font-size: 0.72rem; color: var(--cyan, #00d2d2); white-space: nowrap; flex-shrink: 0; }
.rc-loc-name { font-size: 0.72rem; color: rgba(255,255,255,0.55); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rc-loc-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.rc-loc-field { display: flex; flex-direction: column; gap: 5px; }
.rc-loc-field > label { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.05em; color: rgba(255,255,255,0.5); }
.rc-loc-pill {
  display: inline-flex; align-items: center; gap: 10px; align-self: flex-start;
  padding: 6px 14px; border-radius: 20px; font-size: 0.78rem;
  background: rgba(var(--cyan-rgb, 0,210,210), 0.07); border: 1px solid rgba(var(--cyan-rgb, 0,210,210), 0.2);
}
.rc-loc-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--cyan, #00d2d2); box-shadow: 0 0 6px var(--cyan, #00d2d2); flex-shrink: 0; }
.rc-loc-pill-coord { font-family: var(--mono, ui-monospace, monospace); color: var(--cyan, #00d2d2); }
.rc-loc-pill-label { color: rgba(255,255,255,0.6); }
.rc-loc-clear { background: none; border: none; color: #ff6b6b; font-size: 0.72rem; cursor: pointer; margin-left: 2px; }
.rc-loc-hint { font-size: 0.66rem; color: rgba(255,255,255,0.4); line-height: 1.45; margin: 2px 0 0; }

/* ── Hero ───────────────────────────────────────────────── */
.rce-hero {
  position: relative;
  z-index: 1;
  padding: 36px 32px 18px;
}
.rce-hero-inner { max-width: 1400px; margin: 0 auto; }
.rce-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono, ui-monospace, SFMono-Regular, monospace);
  font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; color: var(--cyan, #00d2d2);
  padding: 4px 12px;
  background: rgba(var(--cyan-rgb, 0,210,210), 0.08);
  border: 1px solid rgba(var(--cyan-rgb, 0,210,210), 0.25);
  border-radius: 4px;
  margin-bottom: 14px;
}
.rce-chip-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--cyan, #00d2d2);
  box-shadow: 0 0 8px var(--cyan, #00d2d2);
}
.rce-h1 {
  font-size: 2.1rem;
  margin: 0 0 0.6rem;
  font-weight: 700;
  color: rgba(255, 255, 255, 0.95);
  letter-spacing: -0.01em;
}
.rce-accent { color: var(--cyan, #00d2d2); }
.rce-lead {
  font-size: 0.85rem;
  color: rgba(255, 255, 255, 0.7);
  margin: 0 0 8px;
  line-height: 1.5;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.rce-spiffe {
  background: rgba(0,0,0,0.4);
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 0.78rem;
  color: rgba(255,255,255,0.85);
  border: 1px solid rgba(var(--cyan-rgb, 0,210,210), 0.15);
}
.rce-tier-badge {
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 3px 8px;
  border-radius: 3px;
  background: rgba(var(--cyan-rgb, 0,210,210), 0.15);
  color: var(--cyan, #00d2d2);
  font-weight: 600;
}
.rce-tier-sovereign-mainframe { background: rgba(255, 107, 53, 0.15); color: #ff6b35; }
.rce-tier-sandbox { background: rgba(168, 85, 247, 0.15); color: #a855f7; }
.rce-tier-cloud-operator { background: rgba(0, 230, 118, 0.15); color: #00e676; }
.rce-lead-blurb {
  font-size: 0.83rem;
  color: rgba(255, 255, 255, 0.55);
  margin: 12px 0 0;
  line-height: 1.6;
  max-width: 920px;
}
.rce-lead-blurb code {
  background: rgba(0,0,0,0.4);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 0.78rem;
  color: var(--cyan, #00d2d2);
}
.rce-sovereign-warn {
  margin-top: 16px;
  padding: 12px 14px;
  background: linear-gradient(90deg, rgba(255, 170, 0, 0.12), rgba(255, 170, 0, 0.03));
  border-left: 3px solid #ffaa00;
  border-radius: 4px;
  color: #ffaa00;
  font-size: 0.83rem;
  max-width: 920px;
}

/* ── Body wrapper ───────────────────────────────────────── */
.rce-body {
  position: relative;
  z-index: 1;
  padding: 0 32px 48px;
  max-width: 1400px;
  margin: 0 auto;
}
.rce-status {
  padding: 14px 16px;
  border-radius: 4px;
  margin-bottom: 16px;
  font-size: 0.88rem;
}
.rce-status-loading {
  background: rgba(var(--cyan-rgb, 0,210,210), 0.08);
  border: 1px solid rgba(var(--cyan-rgb, 0,210,210), 0.2);
  color: var(--cyan, #00d2d2);
}
.rce-status-error {
  background: rgba(255, 82, 82, 0.08);
  border: 1px solid rgba(255, 82, 82, 0.3);
  color: #ff5252;
}
.rce-status-success {
  background: rgba(0, 230, 118, 0.08);
  border: 1px solid rgba(0, 230, 118, 0.3);
  color: #00e676;
}

/* legacy badge/icon (preserved for sig badge in hero) */
.rc-sig-badge {
  padding: 4px 10px;
  border: 1px solid;
  border-radius: 4px;
  font-size: 0.75rem;
  font-weight: 600;
}
.rc-blurb { margin: 12px 0 0; color: #90a4ae; font-size: 0.9rem; }
.rc-sovereign-warn {
  margin-top: 12px;
  padding: 10px 12px;
  background: rgba(255, 170, 0, 0.1);
  border: 1px solid rgba(255, 170, 0, 0.4);
  border-radius: 4px;
  color: #ffaa00;
  font-size: 0.85rem;
}
.rc-loading, .rc-error, .rc-success {
  padding: 16px;
  border-radius: 4px;
  margin-bottom: 16px;
}
.rc-loading { background: rgba(var(--cyan-rgb), 0.1); color: var(--cyan, #00d2d2); }
.rc-error { background: rgba(255, 82, 82, 0.1); color: #ff5252; border: 1px solid rgba(255, 82, 82, 0.4); }
.rc-success { background: rgba(0, 230, 118, 0.1); color: #00e676; border: 1px solid rgba(0, 230, 118, 0.4); }
/* §2026-06-07 v2i — deliberate 2-col with EQUAL-HEIGHT pairs. The old
   auto-fit+align-items:start left short cards with empty grid rows below them
   ("too much space"). Now pairs stretch to match; tall sections (flare/actions,
   already grid-column:1/-1) span full width. Flow: preview|identity ·
   operator|visual · flare(full) · economic|commitments · actions(full). */
.rc-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 900px) { .rc-grid { grid-template-columns: 1fr; } }
/* §2026-06-07 v2i — DESIGN LANGUAGE card (matches the AdminCICD/Reactors/Federation
   house style the Commander picked as the reference): subtle primary-tinted fill +
   thin hairline border + faint top sheen + light blur + soft shadow. Quieter than
   the heavy forex/staking glass; this is the candidate canonical surface to roll
   across views. */
.rc-section {
  background:
    linear-gradient(168deg, rgba(255,255,255,0.025), rgba(255,255,255,0) 60%),
    rgba(var(--cyan-rgb, 0,210,210), 0.035);
  border: 1px solid rgba(var(--cyan-rgb, 0,210,210), 0.18);
  border-radius: 12px;
  padding: 1.2rem 1.35rem 1.3rem;
  backdrop-filter: blur(9px) saturate(1.05);
  -webkit-backdrop-filter: blur(9px) saturate(1.05);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.03), 0 12px 32px -22px rgba(0,0,0,0.8);
  position: relative;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.rc-section:hover { border-color: rgba(var(--cyan-rgb, 0,210,210), 0.3); box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 16px 40px -24px rgba(0,0,0,0.88); }
.rc-section::before {
  content: "";
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--cyan-rgb, 0,210,210), 0.25), transparent);
}
.rc-section h2 {
  font-size: 0.95rem;
  margin: 0 0 14px;
  color: var(--cyan, #00d2d2);
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
  font-family: var(--mono, ui-monospace, SFMono-Regular, monospace);
  font-size: 0.78rem;
  border-bottom: 1px solid rgba(var(--cyan-rgb, 0,210,210), 0.1);
  padding-bottom: 10px;
}
.rc-locked {
  font-size: 0.65rem;
  background: rgba(255, 170, 0, 0.15);
  color: #ffaa00;
  padding: 2px 6px;
  border-radius: 3px;
  border: 1px solid rgba(255, 170, 0, 0.3);
}
.rc-preview { align-items: center; text-align: center; }
.rc-preview-stage {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100px;
  margin: 12px auto;
}
.rc-orb-preview {
  margin: 12px auto;
  border-radius: 50%;
  box-shadow: 0 0 30px currentColor;
}
.rc-preview-meta { font-size: 0.85rem; }
.rce-pol-src { font-size: 10.5px; letter-spacing: .5px; padding: 1px 6px; margin-left: 8px; border-radius: 999px; border: 1px solid; white-space: nowrap; }
.rce-pol-src--set { border-color: rgba(0, 220, 130, .45); color: #7ce8b8; }
.rce-pol-src--dflt { border-color: rgba(120, 160, 200, .35); color: var(--text-secondary, #9ab); }
.rc-hash { word-break: break-all; font-size: 0.72rem; opacity: 0.8; }

.rc-mute { color: #90a4ae; font-size: 0.75rem; margin-top: 2px; }
.rc-field-row {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr) auto;
  gap: 12px;
  margin-bottom: 12px;
  align-items: center;
}
/* File input row: collapses the 3rd column so the native picker doesn't push
   the grid out. Uses a styled <label> wrapper instead of the raw <input>. */
.rc-field-row--icon {
  grid-template-columns: 140px 1fr;
}
.rc-file-input {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(var(--cyan-rgb), 0.08);
  border: 1px dashed rgba(var(--cyan-rgb), 0.35);
  color: var(--cyan, #00d2d2);
  padding: 8px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.8rem;
  transition: background 120ms, border-color 120ms;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.rc-file-input:hover { background: rgba(var(--cyan-rgb), 0.14); border-color: rgba(var(--cyan-rgb), 0.6); }
.rc-file-input input[type=file] { display: none; }
.rc-file-input-text { font-family: var(--mono, ui-monospace, monospace); letter-spacing: 0.03em; }
.rc-field-row label {
  font-size: 0.8rem;
  color: #90a4ae;
}
.rc-field-row input[type=text],
.rc-field-row input[type=url],
.rc-field-row input[type=number],
.rc-field-row select,
.rc-field-row textarea {
  background: rgba(4, 8, 14, 0.55);
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  color: #e0f0ff;
  padding: 8px 11px;
  font-size: 0.85rem;
  border-radius: 7px;
  min-width: 0;
  font-family: inherit;
  transition: border-color .15s ease, box-shadow .15s ease;
}
.rc-field-row input:focus,
.rc-field-row select:focus,
.rc-field-row textarea:focus {
  outline: none;
  border-color: rgba(var(--cyan-rgb), 0.6);
  box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), 0.12);
}
.rc-field-row input[type=color] { padding: 0; width: 38px; height: 30px; border: 1px solid rgba(var(--cyan-rgb), 0.3); border-radius: 7px; }
.rc-field-row code {
  background: rgba(4, 8, 14, 0.55);
  padding: 6px 9px;
  font-size: 0.8rem;
  border-radius: 7px;
  word-break: break-all;
  border: 1px solid rgba(var(--cyan-rgb), 0.1);
}
.rc-actions {
  grid-column: 1 / -1;
  display: flex;
  gap: 12px;
  margin-top: 16px;
}
.rc-btn-save,
.rc-btn-reload,
.rc-btn-rotate {
  background: var(--cyan, #00d2d2);
  color: #001020;
  border: none;
  padding: 10px 24px;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: filter 120ms, transform 120ms;
}
.rc-btn-save:not(:disabled):active,
.rc-btn-reload:not(:disabled):active,
.rc-btn-rotate:not(:disabled):active { transform: translateY(1px); }
.rc-btn-save:hover, .rc-btn-reload:hover, .rc-btn-rotate:hover { filter: brightness(1.1); }
.rc-btn-reload { background: rgba(var(--cyan-rgb), 0.2); color: var(--cyan, #00d2d2); }
.rc-btn-rotate { background: #ffaa00; color: #001020; margin-top: 8px; }
.rc-btn-save:disabled,
.rc-btn-reload:disabled,
.rc-btn-rotate:disabled { opacity: 0.5; cursor: not-allowed; }
@keyframes rc-pulse {
  0%, 100% { transform: scale(1); opacity: 0.85; }
  50% { transform: scale(1.08); opacity: 1; }
}

/* Flare layer picker grids */
.rc-section-flare { grid-column: 1 / -1; }
.rc-subhead {
  font-size: 0.85rem;
  margin: 16px 0 8px;
  color: #00d2d2;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.rc-blurb-inline { color: #90a4ae; font-size: 0.8rem; margin: 0 0 12px; }
.rc-flare-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
  gap: 8px;
}
.rc-flare-disabled { opacity: 0.4; pointer-events: none; }
.rc-flare-tile {
  background: rgba(4, 8, 14, 0.5);
  border: 1px solid rgba(var(--cyan-rgb), 0.2);
  color: #e0f0ff;
  padding: 10px;
  border-radius: 10px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  transition: border-color 120ms, transform 120ms;
}
.rc-flare-tile:hover { transform: translateY(-1px); }
.rc-flare-tile:hover { border-color: rgba(var(--cyan-rgb), 0.6); }
.rc-flare-tile.active { border-color: var(--cyan, #00d2d2); background: rgba(var(--cyan-rgb), 0.1); }
.rc-flare-tile:disabled { cursor: not-allowed; }
.rc-flare-preview { width: 64px; height: 64px; display: flex; align-items: center; justify-content: center; }
.rc-flare-label { font-size: 0.7rem; color: #90a4ae; text-transform: uppercase; }
.rc-flare-tile.active .rc-flare-label { color: var(--cyan, #00d2d2); }

/* Corner-badge picker (text tiles — corner variants render as small badges, not full SVG previews) */
.rc-corner-grid { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.rc-corner-tile { background: rgba(0,0,0,0.3); border: 1px solid rgba(var(--cyan-rgb), 0.2); color: #90a4ae; padding: 4px 10px; border-radius: 4px; cursor: pointer; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.03em; font-family: var(--mono, monospace); }
.rc-corner-tile:hover { border-color: rgba(var(--cyan-rgb), 0.5); }
.rc-corner-tile.active { border-color: var(--cyan, #00d2d2); color: var(--cyan, #00d2d2); background: rgba(var(--cyan-rgb), 0.1); }
</style>
