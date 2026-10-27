<!--
  §NOTIFV2 (2026-07-26) → §SETPOLISH (2026-07-27) — the ONE notification surface.

  Matrix: rendered ENTIRELY from GET /notifications/prefs/effective, so a new catalog
  entry appears here with zero frontend work. Toggles write sparse rows via
  PUT /notifications/prefs (per-row upsert — never a blob read-modify-write). A toggle
  that lands back on the catalog default sends reset:true so the table stays sparse.

  Basics strip (bottom): broadcast severities + delivery channels + quiet hours stay on
  the legacy store (PATCH /developers/me/notification-prefs) because broadcast DELIVERY
  still reads those keys — but they now present as plain settings and AUTO-SAVE, so the
  panel no longer looks like two duplicated systems (Commander, 2026-07-27).

  §SETPOLISH changes:
    * ALL requests ride apiClient — the old hand-rolled fetch() used a token source the
      axios interceptor chain didn't refresh, which is how the panel could sit at
      "Load failed: 401" on an otherwise healthy page (caught by the BEFORE audit).
    * knobs are proper switches on a fixed grid with a reserved reset slot — nothing
      shifts when a row gains/loses a custom value.
    * thresholds moved into the row's name cell (second line) — the grid stays 3 cols.

  Notes for future editors:
    * mandatory rows are locked ON — the resolver ignores prefs for them by design.
    * "soon" = catalog entry exists but nothing emits it yet; configuring ahead is allowed.
    * device (phone) prefs can only NARROW what is enabled here — never widen it.
    * Labels are English v1, matching every other Settings panel; the catalog already
      carries label_key/desc_key for the locale pass.
-->
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { useUIStore } from '@/stores/ui'
import { apiClient } from '@/services/api/client'
import { useLogger } from '@/composables/useLogger'
// LEGACY i18n mode: always the composable, never raw vue-i18n (raw throws a SyntaxError that the
// error boundary swallows into a blank view). t(key, fallback) returns the fallback when the key
// is missing, which is what keeps a half-translated locale from rendering raw i18n paths.
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const { t } = useI18n()
const log = useLogger('NotificationsPanel')
const uiStore = useUIStore()

/* ── v2 matrix state ─────────────────────────────────────────────────────── */
interface EffChannel { enabled: boolean; source: string; threshold: number | null }
interface NType {
  key: string; category: string; severity: string; mandatory: boolean
  audience: string; legacy_managed: boolean; emitter: boolean
  threshold_kind: string; threshold_default: number | null
  coalesce_window_s: number
  default_enabled: Record<string, boolean>
  effective: Record<string, EffChannel>
  // The catalog owns these (label_key defaults to notifCatalog.<key_underscored>.label);
  // the panel must never invent its own name for a type.
  label_key?: string; desc_key?: string | null
}
// All FOUR catalog channels. The resolver and the prefs table were channel-complete from day
// one (decide() takes any channel; _WRITABLE_CHANNELS = set(CHANNELS)); only DELIVERY was
// push-only, which is why this list used to stop at two.
const MATRIX_CHANNELS = computed(() => [
  { id: 'inapp', label: t('notifCatalog._channel.inapp', 'In-app') },
  { id: 'email', label: t('notifCatalog._channel.email', 'Email') },
  { id: 'push_desktop', label: t('notifCatalog._channel.desktop', 'Desktop') },
  { id: 'push_mobile', label: t('notifCatalog._channel.mobile', 'Mobile') },
])

/** Type display name. The catalog's label_key is authoritative; prettyName is the fallback for a
 *  locale that has not been filled in yet, so a missing key never renders "notifCatalog.x.label". */
function typeLabel(t_: NType): string {
  return t(t_.label_key || `notifCatalog.${t_.key.replace(/\./g, '_')}.label`, prettyName(t_.key))
}
function typeDesc(t_: NType): string {
  return t_.desc_key ? t(t_.desc_key, '') : ''
}

const vTypes = ref<NType[]>([])
const vMode = ref('off')
const vLoading = ref(true)
const vError = ref('')
// §FESUITE (2026-10-05): the matrix's read has a state of its own. "Quiet mobile" and "Reset to defaults" act on the matrix
// this panel read: over a failed read, "Quiet mobile" turned every mobile push off (its keep-list found no types, so
// disputes, funding decisions and revocations went quiet too) and "Reset to defaults" reset the wildcards only while saying
// everything was reset. The presets wait for a read matrix now; a re-read after a change that fails keeps the matrix on
// screen and says the re-read failed, instead of swapping the matrix for an error.
const vRead = ref<'loading' | 'ok' | 'failed'>('loading')
const vRefreshFailed = ref(false)
const busyCell = ref('')            // `${key}:${channel}` while a write is in flight
const thresholdDraft = ref<Record<string, string>>({})

const CATEGORY_LABEL: Record<string, string> = {
  security: 'Security & approvals', agents: 'Agents & delegation', money: 'Money',
  contracts: 'Contracts', marketplace: 'Marketplace', ops: 'Operator & federation',
}

// §FESUITE (2026-10-04): a registry whose staking rewards are switched off (the production set since V0520) has no
// reward to tell anyone about, so its "Staking rewards" row goes, and stays gone while the config is still being read
// (§LANDINGTRUTH 12e: no reward information where rewards are off, not even while the config loads)
const { config: registryCfg } = useRegistryConfig()
const REWARD_TYPES = new Set(['staking.rewards'])
const rewardsOn = computed(() => registryCfg.value.staking_rewards_enabled === true)

const matrixGroups = computed(() => {
  const groups: { cat: string; label: string; types: NType[] }[] = []
  for (const cat of ['security', 'agents', 'money', 'contracts', 'marketplace', 'ops']) {
    const types = vTypes.value.filter(t => t.category === cat && !t.legacy_managed && (rewardsOn.value || !REWARD_TYPES.has(t.key)))
    if (types.length) groups.push({ cat, label: t(`notifCatalog._category.${cat}`, CATEGORY_LABEL[cat] ?? cat), types })
  }
  return groups
})

function prettyName(key: string): string {
  const tail = key.split('.').slice(1).join(' ').replace(/_/g, ' ')
  const head = key.split('.')[0]
  const s = `${tail}`.trim()
  const base = s.charAt(0).toUpperCase() + s.slice(1)
  // a few reads-better-in-English overrides
  const overrides: Record<string, string> = {
    'security.login_approval': 'Sign-in approval',
    'security.liability_challenge': 'Liability confirmation (Cockpit Card)',
    'security.device_enrolled': 'New device registered',
    'account.suspended': 'Account suspended',
    'account.reinstated': 'Account reinstated',
    'delegation.granted': 'Delegation granted to your agent',
    'delegation.breaker_tripped': 'Capability circuit breaker tripped',
    'capability.issued': 'Capability permit issued',
    'capability.revoked': 'Capability permit revoked',
    'agent.spawned': 'Sub-agent spawned',
    'agent.mtls_revoked': 'Agent mTLS identity revoked',
    'money.received': 'Payment received (above threshold)',
    'funding.decided': 'Funding request decided',
    'dispute.filed_against_you': 'Dispute filed against your agent',
    'guild.awarded': 'Guild: job awarded to you',
    'guild.verified_paid': 'Guild: work verified & paid',
    'guild.bid_received': 'Guild: bid received on your order',
    'guild.work_submitted': 'Guild: work delivered for review',
    'contract.offered': 'Contract offer received',
    'contract.agreed': 'Contract agreed (escrow funded)',
    'contract.milestone_submitted': 'Milestone delivered for your review',
    'contract.milestone_released': 'Milestone released (you were paid)',
    'contract.disputed': 'Contract disputed',
    'contract.completed': 'Contract completed',
    'contract.cancelled': 'Contract cancelled',
  }
  return overrides[key] ?? `${base}` + (head === 'evals' ? ' (evals)' : '')
}

async function vLoad() {
  const first = vRead.value !== 'ok'
  if (first) { vRead.value = 'loading'; vLoading.value = true; vError.value = '' }
  try {
    const { data } = await apiClient.get('/notifications/prefs/effective')
    vTypes.value = data.types ?? []
    vMode.value = data.mode ?? 'off'
    for (const t of vTypes.value) {
      if (t.threshold_kind === 'amount') {
        const cur = t.effective?.push_mobile?.threshold ?? t.threshold_default
        thresholdDraft.value[t.key] = cur != null ? String(cur) : ''
      }
    }
    vRead.value = 'ok'
    vRefreshFailed.value = false
  } catch (e: any) {
    log.warn('load matrix', e)
    if (first) {
      vRead.value = 'failed'
      vError.value = e?.response?.data?.detail || e.message || String(e)
    } else {
      vRefreshFailed.value = true
    }
  } finally {
    vLoading.value = false
  }
}

async function putRows(rows: any[]) {
  await apiClient.put('/notifications/prefs', { rows })
}

async function toggleCell(t: NType, channel: string) {
  if (t.mandatory || t.legacy_managed) return
  const cellId = `${t.key}:${channel}`
  if (busyCell.value) return
  busyCell.value = cellId
  try {
    const cur = t.effective[channel]?.enabled ?? false
    const next = !cur
    const isDefault = next === (t.default_enabled[channel] ?? false)
    const thr = t.threshold_kind === 'amount' && next
      ? parseFloat(thresholdDraft.value[t.key] || '') || t.threshold_default
      : undefined
    // Landing back on the default (and no custom threshold) → reset keeps the table sparse.
    const row = (isDefault && thr == null)
      ? { type_key: t.key, channel, reset: true }
      : { type_key: t.key, channel, enabled: next, ...(thr != null ? { threshold_num: thr } : {}) }
    await putRows([row])
    await vLoad()
  } catch (e: any) {
    uiStore.showError('Notification preference', e?.response?.data?.detail || e.message || String(e))
  } finally {
    busyCell.value = ''
  }
}

async function resetCell(t: NType, channel: string) {
  if (busyCell.value) return
  busyCell.value = `${t.key}:${channel}`
  try {
    await putRows([{ type_key: t.key, channel, reset: true }])
    await vLoad()
  } catch (e: any) {
    uiStore.showError('Notification preference', e?.response?.data?.detail || e.message || String(e))
  } finally {
    busyCell.value = ''
  }
}

async function saveThreshold(t: NType) {
  const raw = thresholdDraft.value[t.key]
  const num = parseFloat(raw)
  if (!isFinite(num) || num < 0) {
    uiStore.showError('Threshold', 'Enter a non-negative number.')
    return
  }
  const rows = MATRIX_CHANNELS.value
    .filter(c => t.effective[c.id]?.enabled)
    .map(c => ({ type_key: t.key, channel: c.id, enabled: true, threshold_num: num }))
  if (!rows.length) {
    uiStore.showInfo?.('Threshold', 'Enable a channel first — the threshold applies to enabled channels.')
    return
  }
  try {
    await putRows(rows)
    await vLoad()
    uiStore.showSuccess('Saved', `Threshold for ${prettyName(t.key)} set to ${num}.`)
  } catch (e: any) {
    uiStore.showError('Threshold', e?.response?.data?.detail || e.message || String(e))
  }
}

/* Presets — bulk row writes; the server stores rows, never "which preset". */
async function presetQuietMobile() {
  if (vRead.value !== 'ok') return   // never act on a matrix this panel did not read
  // Mobile rings only for what genuinely needs a human; mandatory types are unaffected
  // by construction. Everything else on mobile: off via the channel master.
  const keep = ['contract.disputed', 'dispute.filed_against_you', 'funding.decided',
                'capability.revoked', 'agent.mtls_revoked', 'guild.awarded']
  const rows: any[] = [{ type_key: '*', channel: 'push_mobile', enabled: false }]
  for (const k of keep) {
    if (vTypes.value.some(t => t.key === k)) {
      rows.push({ type_key: k, channel: 'push_mobile', enabled: true })
    }
  }
  try {
    await putRows(rows)
    await vLoad()
    uiStore.showSuccess('Preset applied', 'Quiet mobile: only approvals, security and money events ring your phone.')
  } catch (e: any) {
    uiStore.showError('Preset', e?.response?.data?.detail || e.message || String(e))
  }
}

async function presetDefaults() {
  if (vRead.value !== 'ok') return   // never act on a matrix this panel did not read
  // Reset every explicit row (incl. wildcards) back to catalog defaults.
  const rows: any[] = []
  for (const t of vTypes.value) {
    for (const c of MATRIX_CHANNELS.value) {
      if (t.effective[c.id]?.source === 'row') rows.push({ type_key: t.key, channel: c.id, reset: true })
    }
  }
  for (const c of MATRIX_CHANNELS.value) rows.push({ type_key: '*', channel: c.id, reset: true })
  try {
    await putRows(rows)
    await vLoad()
    uiStore.showSuccess('Preset applied', 'All notification preferences reset to defaults.')
  } catch (e: any) {
    uiStore.showError('Preset', e?.response?.data?.detail || e.message || String(e))
  }
}

/* ── basics strip: broadcasts + delivery + quiet hours (legacy store) ────── */
interface Prefs {
  prefs_version: number
  mute_info: boolean
  mute_warning: boolean
  mute_maintenance: boolean
  delivery_in_app: boolean
  delivery_email: boolean
  quiet_hours_start: number | null
  quiet_hours_end: number | null
}

const DEFAULTS: Prefs = {
  prefs_version: 1,
  mute_info: false,
  mute_warning: false,
  mute_maintenance: false,
  delivery_in_app: true,
  delivery_email: true,
  quiet_hours_start: null,
  quiet_hours_end: null,
}

const prefs = ref<Prefs>({ ...DEFAULTS })
const bLoading = ref(true)
const bError = ref('')
const bStatus = ref<'' | 'saving' | 'saved' | 'error'>('')
let bTimer: number | null = null
let bStatusTimer: number | null = null

const quietHoursEnabled = computed({
  get: () => prefs.value.quiet_hours_start !== null && prefs.value.quiet_hours_end !== null,
  set: (on: boolean) => {
    if (on) {
      if (prefs.value.quiet_hours_start === null) prefs.value.quiet_hours_start = 22
      if (prefs.value.quiet_hours_end === null) prefs.value.quiet_hours_end = 7
    } else {
      prefs.value.quiet_hours_start = null
      prefs.value.quiet_hours_end = null
    }
    queueBasicsSave()
  },
})

async function bLoad() {
  bLoading.value = true
  bError.value = ''
  try {
    const { data } = await apiClient.get('/developers/me/notification-prefs')
    prefs.value = { ...DEFAULTS, ...data }
  } catch (e: any) {
    bError.value = e?.response?.data?.detail || e.message || String(e)
    log.warn('load basics', e)
  } finally {
    bLoading.value = false
  }
}

/* Auto-save: these are basic settings — no save button. Rapid clicks batch
   through a short debounce; the status chip narrates saving → saved. */
function queueBasicsSave() {
  bStatus.value = 'saving'
  if (bTimer !== null) window.clearTimeout(bTimer)
  bTimer = window.setTimeout(saveBasics, 600)
}

async function saveBasics() {
  bTimer = null
  try {
    const body = {
      mute_info: prefs.value.mute_info,
      mute_warning: prefs.value.mute_warning,
      mute_maintenance: prefs.value.mute_maintenance,
      delivery_in_app: prefs.value.delivery_in_app,
      delivery_email: prefs.value.delivery_email,
      quiet_hours_start: prefs.value.quiet_hours_start,
      quiet_hours_end: prefs.value.quiet_hours_end,
    }
    const { data } = await apiClient.patch('/developers/me/notification-prefs', body)
    prefs.value = { ...DEFAULTS, ...data }
    bStatus.value = 'saved'
    if (bStatusTimer !== null) window.clearTimeout(bStatusTimer)
    bStatusTimer = window.setTimeout(() => { if (bStatus.value === 'saved') bStatus.value = '' }, 2500)
  } catch (e: any) {
    bStatus.value = 'error'
    uiStore.showError('Broadcast preferences', e?.response?.data?.detail || e.message || String(e))
  }
}

onBeforeUnmount(() => {
  // Never lose a pending change to navigation — flush the debounce.
  if (bTimer !== null) { window.clearTimeout(bTimer); void saveBasics() }
})

onMounted(() => { vLoad(); bLoad() })
</script>

<template>
  <section class="np-root" data-testid="notif-matrix">
    <!-- header: intro left, presets right -->
    <div class="np-header">
      <div class="np-header-text">
        <h3 class="np-title">Notifications</h3>
        <p class="np-subtitle">
          What reaches you, where. Desktop push is your browser; mobile push is your paired
          phone. Locked rows are security approvals that cannot be muted. Your phone's own
          settings can further narrow these, never widen them.
        </p>
      </div>
      <div v-if="vRead === 'ok'" class="np-presets">
        <button class="np-preset-btn" @click="presetQuietMobile">Quiet mobile</button>
        <button class="np-preset-btn" @click="presetDefaults">Reset to defaults</button>
      </div>
    </div>
    <p v-if="!vLoading && !vError && vMode !== 'on'" class="np-mode-hint">
      Preferences are saved now and take effect when v2 delivery is switched on (mode: {{ vMode }}).
    </p>

    <div v-if="vLoading" class="np-loading">Loading notification matrix…</div>
    <div v-else-if="vError" class="np-error">
      {{ vError }}
      <button class="np-preset-btn" @click="vLoad">Retry</button>
    </div>
    <template v-else>
      <ReadFailedNotice v-if="vRefreshFailed" dense :retry="vLoad" />
      <div v-for="g in matrixGroups" :key="g.cat" class="np-cat">
        <div class="np-cat-head">
          <h4 class="np-cat-title">{{ g.label }}</h4>
          <span v-for="c in MATRIX_CHANNELS" :key="c.id" class="np-mh-ch">{{ c.label }}</span>
        </div>
        <div class="np-rows">
          <div v-for="t in g.types" :key="t.key" class="np-mrow" :class="{ 'is-soon': !t.emitter }" :data-type="t.key">
            <div class="np-mname">
              <span class="np-mname-line" :title="typeDesc(t) || undefined">
                {{ typeLabel(t) }}
                <span v-if="t.mandatory" class="np-badge np-badge--lock" title="Security approval — always delivered">locked on</span>
                <span v-else-if="!t.emitter" class="np-badge" title="Declared — will start firing in an upcoming release">soon</span>
                <span v-if="t.coalesce_window_s > 0" class="np-badge np-badge--soft"
                      :title="`Bursts are grouped: at most one push per ${t.coalesce_window_s}s, with a '+N more' count`">grouped</span>
              </span>
              <span v-if="t.threshold_kind === 'amount'" class="np-thr">
                <span class="np-thr-lbl">min amount</span>
                <input v-model="thresholdDraft[t.key]" class="np-thr-in" inputmode="decimal"
                       :placeholder="String(t.threshold_default ?? '')" @keydown.enter.prevent="saveThreshold(t)" />
                <button class="np-thr-btn" @click="saveThreshold(t)">set</button>
              </span>
            </div>
            <span v-for="c in MATRIX_CHANNELS" :key="c.id" class="np-mcell">
              <label class="np-sw" :class="{ 'np-sw--lock': t.mandatory, 'np-sw--busy': busyCell === `${t.key}:${c.id}` }">
                <input
                  type="checkbox"
                  :checked="t.effective[c.id]?.enabled"
                  :disabled="t.mandatory || busyCell === `${t.key}:${c.id}`"
                  :aria-label="`${typeLabel(t)}: ${c.label}`"
                  :data-channel="c.id"
                  @change="toggleCell(t, c.id)"
                />
                <span class="np-sw-track"></span>
              </label>
              <button
                v-if="t.effective[c.id]?.source === 'row' && !t.mandatory"
                class="np-reset" title="Back to default"
                :aria-label="`${typeLabel(t)}: ${c.label}, back to default`"
                :disabled="busyCell === `${t.key}:${c.id}`"
                @click="resetCell(t, c.id)"
              >&#8634;</button>
              <span v-else class="np-reset np-reset--slot" aria-hidden="true"></span>
            </span>
          </div>
        </div>
      </div>
    </template>

    <!-- ── basics: broadcasts + delivery + quiet hours (auto-save) ── -->
    <div class="np-basics">
      <div class="np-basics-head">
        <h4 class="np-basics-title">Broadcasts &amp; quiet hours</h4>
        <span class="np-basics-status" :class="`is-${bStatus}`">
          {{ bStatus === 'saving' ? 'saving…' : bStatus === 'saved' ? 'saved' : bStatus === 'error' ? 'save failed' : '' }}
        </span>
      </div>

      <div v-if="bLoading" class="np-loading">Loading…</div>
      <div v-else-if="bError" class="np-error">
        {{ bError }}
        <button class="np-preset-btn" @click="bLoad">Retry</button>
      </div>
      <div v-else class="np-basics-grid">
        <div class="np-bgroup">
          <span class="np-bgroup-title">Admin broadcasts</span>
          <label class="np-brow"><input v-model="prefs.mute_info" type="checkbox" @change="queueBasicsSave" /><span>Mute Info</span></label>
          <label class="np-brow"><input v-model="prefs.mute_warning" type="checkbox" @change="queueBasicsSave" /><span>Mute Warning</span></label>
          <label class="np-brow"><input v-model="prefs.mute_maintenance" type="checkbox" @change="queueBasicsSave" /><span>Mute Maintenance</span></label>
          <span class="np-bnote">Critical broadcasts always deliver.</span>
        </div>
        <div class="np-bgroup">
          <span class="np-bgroup-title">Broadcast delivery</span>
          <label class="np-brow"><input v-model="prefs.delivery_in_app" type="checkbox" @change="queueBasicsSave" /><span>In-app (bell, toast, banner)</span></label>
          <label class="np-brow"><input v-model="prefs.delivery_email" type="checkbox" @change="queueBasicsSave" /><span>Email</span></label>
        </div>
        <div class="np-bgroup">
          <span class="np-bgroup-title">Quiet hours (UTC)</span>
          <label class="np-brow">
            <input :checked="quietHoursEnabled" type="checkbox" @change="(e: any) => quietHoursEnabled = e.target.checked" />
            <span>Silence toasts and non-critical push</span>
          </label>
          <div v-if="quietHoursEnabled" class="np-quiet-grid">
            <label class="np-quiet-label">from
              <select v-model.number="prefs.quiet_hours_start" class="np-select" @change="queueBasicsSave">
                <option v-for="h in 24" :key="`s${h-1}`" :value="h-1">{{ String(h-1).padStart(2,'0') }}:00</option>
              </select>
            </label>
            <label class="np-quiet-label">to
              <select v-model.number="prefs.quiet_hours_end" class="np-select" @change="queueBasicsSave">
                <option v-for="h in 24" :key="`e${h-1}`" :value="h-1">{{ String(h-1).padStart(2,'0') }}:00</option>
              </select>
            </label>
          </div>
          <span class="np-bnote">Held broadcasts land in your unread feed; security approvals still deliver.</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.np-root {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  color: #c8d8e8;
}

/* header */
.np-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 1rem; margin-bottom: 0.85rem; flex-wrap: wrap;
}
.np-header-text { max-width: 640px; }
.np-title {
  font-size: 1rem; font-weight: 700; color: #e0ecf4;
  margin: 0 0 0.4rem 0; letter-spacing: 0.04em;
}
.np-subtitle { font-size: 0.74rem; color: #8899aa; margin: 0; line-height: 1.55; }
.np-loading, .np-error { padding: 1.25rem; text-align: center; font-size: 0.82rem; }
.np-error { color: #ff6677; display: flex; flex-direction: column; align-items: center; gap: 0.6rem; }
.np-mode-hint { font-size: 0.66rem; color: #8899aa; font-style: italic; margin: 0 0 0.9rem; }

/* presets */
.np-presets { display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0; }
.np-preset-btn {
  font-family: inherit; font-size: 0.66rem; font-weight: 700; letter-spacing: 0.1em;
  background: rgba(var(--nc-primary-rgb), 0.1); color: var(--nc-primary);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35); border-radius: 4px;
  padding: 0.42rem 0.8rem; cursor: pointer; text-transform: uppercase;
  transition: background 0.15s, color 0.15s;
}
.np-preset-btn:hover { background: rgba(var(--nc-primary-rgb), 0.26); color: #fff; }

/* category blocks */
.np-cat { margin-bottom: 1.15rem; }
.np-cat-head {
  display: grid; grid-template-columns: minmax(0, 1fr) 74px 74px 74px 74px;
  align-items: end; gap: 0.4rem; padding: 0 0.5rem 0.3rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  margin-bottom: 0.25rem;
}
.np-cat-title {
  font-size: 0.66rem; letter-spacing: 0.16em; color: rgba(var(--nc-primary-rgb), 0.85);
  font-weight: 700; margin: 0; text-transform: uppercase;
}
.np-mh-ch {
  font-size: 0.58rem; color: #8193ab; letter-spacing: 0.1em; /* §FESUITE: 4.5:1+ on the panel (the grey was #6c7f97, 4.1-4.4:1) */
  text-align: center; text-transform: uppercase;
}

/* rows — fixed 3-col grid, controls perfectly centered */
.np-rows { display: flex; flex-direction: column; }
.np-mrow {
  display: grid; grid-template-columns: minmax(0, 1fr) 74px 74px 74px 74px;
  align-items: center; gap: 0.4rem;
  padding: 0.34rem 0.5rem; border-radius: 4px; font-size: 0.75rem;
}
.np-rows .np-mrow:nth-child(odd) { background: rgba(var(--nc-primary-rgb), 0.03); }
.np-mrow:hover { background: rgba(var(--nc-primary-rgb), 0.06); }
.np-mrow.is-soon .np-mname-line { color: #66778a; }
.np-mname { display: flex; flex-direction: column; gap: 0.28rem; min-width: 0; }
.np-mname-line { color: #b6c6d6; display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; line-height: 1.35; }
.np-mcell { display: inline-flex; align-items: center; justify-content: center; gap: 0.28rem; }

/* switch knob — compact st-toggle sibling, identical geometry per cell */
.np-sw { position: relative; width: 34px; height: 18px; flex-shrink: 0; display: inline-block; }
.np-sw input { opacity: 0; width: 0; height: 0; position: absolute; }
/* §FESUITE — a keyboard reaches the hidden input; show where it is */
.np-sw input:focus-visible + .np-sw-track { outline: 2px solid var(--nc-primary); outline-offset: 2px; }
.np-sw-track {
  position: absolute; inset: 0; border-radius: 9px; cursor: pointer;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  transition: background 0.18s, border-color 0.18s;
}
.np-sw-track::after {
  content: ''; position: absolute; top: 2px; left: 2px; width: 12px; height: 12px;
  border-radius: 50%; background: #8193ab; transition: transform 0.18s, background 0.18s;
}
.np-sw input:checked + .np-sw-track {
  background: rgba(var(--nc-primary-rgb), 0.22); border-color: rgba(var(--nc-primary-rgb), 0.75);
}
.np-sw input:checked + .np-sw-track::after { transform: translateX(16px); background: var(--nc-primary); }
.np-sw input:disabled + .np-sw-track { cursor: not-allowed; opacity: 0.75; }
.np-sw--lock .np-sw-track { border-color: rgba(255, 176, 32, 0.5); background: rgba(255, 176, 32, 0.12); }
.np-sw--lock input:checked + .np-sw-track::after { background: #ffb020; }
.np-sw--busy .np-sw-track { opacity: 0.45; }

/* reset control occupies a fixed slot whether or not it is shown */
.np-reset {
  width: 16px; height: 16px; line-height: 1; flex-shrink: 0;
  background: transparent; border: none; color: rgba(var(--nc-primary-rgb), 0.8);
  cursor: pointer; font-size: 0.82rem; padding: 0; text-align: center;
}
.np-reset:hover { color: #fff; }
.np-reset--slot { visibility: hidden; pointer-events: none; }

/* badges */
.np-badge {
  font-size: 0.53rem; letter-spacing: 0.08em; padding: 0.08rem 0.35rem; border-radius: 999px;
  border: 1px solid rgba(136, 153, 170, 0.5); color: #8899aa; text-transform: uppercase;
  white-space: nowrap;
}
.np-badge--lock { border-color: rgba(255, 176, 32, 0.6); color: #ffb020; }
.np-badge--soft { border-color: rgba(var(--nc-primary-rgb), 0.35); color: rgba(var(--nc-primary-rgb), 0.8); }

/* per-row threshold, second line of the name cell */
.np-thr { display: inline-flex; align-items: center; gap: 0.35rem; }
.np-thr-lbl { font-size: 0.6rem; color: #8193ab; letter-spacing: 0.06em; text-transform: uppercase; }
.np-thr-in {
  font-family: inherit; width: 84px; background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18); color: #c8d8e8;
  padding: 3px 6px; border-radius: 3px; font-size: 0.68rem; outline: none;
}
.np-thr-in:focus { border-color: rgba(var(--nc-primary-rgb), 0.55); }
.np-thr-btn {
  font-family: inherit; font-size: 0.6rem; letter-spacing: 0.06em; text-transform: uppercase;
  background: rgba(var(--nc-primary-rgb), 0.1); color: var(--nc-primary);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35); border-radius: 3px;
  padding: 3px 8px; cursor: pointer;
}
.np-thr-btn:hover { background: rgba(var(--nc-primary-rgb), 0.24); color: #fff; }

/* basics strip — plain settings, auto-save */
.np-basics {
  margin-top: 1.4rem; padding-top: 1.1rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.12);
}
.np-basics-head { display: flex; align-items: baseline; gap: 0.75rem; margin-bottom: 0.7rem; }
.np-basics-title {
  font-size: 0.66rem; letter-spacing: 0.16em; color: rgba(var(--nc-primary-rgb), 0.85);
  font-weight: 700; margin: 0; text-transform: uppercase;
}
.np-basics-status { font-size: 0.62rem; color: #8193ab; font-style: italic; min-height: 1em; }
.np-basics-status.is-saved { color: #35d49a; }
.np-basics-status.is-error { color: #ff6677; }
.np-basics-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.9rem; }
.np-bgroup {
  background: rgba(var(--nc-primary-rgb), 0.03);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  border-radius: 4px; padding: 0.75rem 0.85rem;
  display: flex; flex-direction: column; gap: 0.1rem;
}
.np-bgroup-title {
  font-size: 0.6rem; letter-spacing: 0.12em; color: #8899aa;
  font-weight: 700; text-transform: uppercase; margin-bottom: 0.4rem;
}
.np-brow {
  display: flex; align-items: center; gap: 0.5rem; padding: 0.24rem 0;
  cursor: pointer; font-size: 0.74rem; color: #b6c6d6;
}
.np-brow input[type="checkbox"] { cursor: pointer; accent-color: var(--nc-primary); }
.np-bnote { font-size: 0.62rem; color: #8193ab; margin-top: 0.45rem; line-height: 1.4; }
.np-quiet-grid { display: flex; gap: 0.75rem; margin: 0.35rem 0 0.1rem; }
.np-quiet-label {
  font-size: 0.62rem; color: #8899aa; display: flex; align-items: center; gap: 0.4rem;
  text-transform: uppercase; letter-spacing: 0.06em;
}
.np-select {
  font-family: 'IBM Plex Mono', monospace; background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18); color: #c8d8e8;
  padding: 4px 8px; border-radius: 3px; font-size: 0.72rem; outline: none;
}

/* mobile */
@media (max-width: 900px) { .np-basics-grid { grid-template-columns: 1fr; } }
@media (max-width: 720px) {
  .np-cat-head, .np-mrow { grid-template-columns: minmax(0, 1fr) 46px 46px 46px 46px; gap: 0.2rem; }
  .np-cat-head { padding: 0 0.35rem 0.3rem; }
  .np-mrow { padding: 0.34rem 0.35rem; }
  .np-mh-ch { font-size: 0.52rem; letter-spacing: 0.04em; }
  .np-mcell { gap: 0.15rem; }
  .np-header { flex-direction: column; }
}
</style>
