<template>
  <div class="enf-page">
    <header class="enf-hero">
      <div>
        <div class="enf-eyebrow"><Icon name="mdi:gavel" :size="14" /> WATCHTOWER · ENFORCEMENT</div>
        <h1 class="enf-h1">Economic Enforcement</h1>
        <p class="enf-sub">
          Per-agent levers: slashing locked units, the offense ladder{{ stakingRewardsOn ? ', payout pauses' : '' }} and suspension —
          plus the registry policy and the two-man pending queue. Every action requires a reason
          and lands in the audit trail.
        </p>
      </div>
    </header>

    <div v-if="banner" class="enf-banner" :class="banner.ok ? 'enf-banner--ok' : 'enf-banner--err'">
      <Icon :name="banner.ok ? 'mdi:check-circle' : 'mdi:alert'" :size="14" /> {{ banner.text }}
    </div>

    <!-- ═══ Agent console ═══ -->
    <section class="enf-card" data-tour="enf-agent">
      <div class="enf-card-head"><Icon name="mdi:robot" :size="15" /> AGENT CONSOLE</div>
      <div class="enf-did-row">
        <input v-model.trim="did" class="enf-input" placeholder="did:theprotocol:… (agent DID)" @keydown.enter="loadStatus" />
        <button class="enf-btn" :disabled="!did || loading" @click="loadStatus">{{ loading ? 'Loading…' : 'Load status' }}</button>
      </div>

      <div v-if="agentStatus" class="enf-status">
        <span class="enf-pill" :class="statusTone">{{ agentStatus.enforcement_status || agentStatus.status || 'unknown' }}</span>
        <span class="enf-meta" v-for="(v, k) in scalarStatus" :key="k">{{ k }}: <strong>{{ v }}</strong></span>
      </div>
      <p v-else-if="statusError" class="enf-err">{{ statusError }}</p>

      <div v-if="agentStatus" class="enf-actions">
        <!-- Slash (with mandatory preview) -->
        <div class="enf-action">
          <div class="enf-action-title"><Icon name="mdi:alert-octagon" :size="13" /> Slash locked units</div>
          <div class="enf-action-row">
            <input v-model.number="slashAmount" type="number" min="1" class="enf-input enf-input--sm" placeholder="amount" />
            <button class="enf-btn enf-btn--ghost" :disabled="!validSlashAmount || busy" @click="previewSlash">Preview</button>
            <button class="enf-btn enf-btn--danger" :disabled="!slashPreview || busy" @click="ask('slash')">Slash…</button>
          </div>
          <div v-if="slashPreview" class="enf-preview">
            locked {{ slashPreview.staked_balance ?? '—' }} → slash {{ slashPreview.slash_amount ?? slashAmount }} → remaining {{ slashPreview.resulting_stake ?? '—' }}
          </div>
        </div>

        <!-- Record offense -->
        <div class="enf-action">
          <div class="enf-action-title"><Icon name="mdi:file-document-edit" :size="13" /> Record offense</div>
          <div class="enf-action-row">
            <select v-model="offenseType" class="enf-input enf-input--sm" aria-label="Offense type">
              <option value="dispute_lost">dispute_lost</option>
              <option value="malpractice">malpractice</option>
              <option value="policy_violation">policy_violation</option>
              <option value="other">other</option>
            </select>
            <select v-model.number="offenseSeverity" class="enf-input enf-input--xs" title="Severity 1–4">
              <option :value="1">sev 1</option><option :value="2">sev 2</option><option :value="3">sev 3</option><option :value="4">sev 4</option>
            </select>
            <input v-model.trim="offenseRef" class="enf-input enf-input--sm" placeholder="reference (dispute id…)" />
            <button class="enf-btn enf-btn--warn" :disabled="busy" @click="ask('offense')">Record…</button>
          </div>
        </div>

        <!-- Payout pause / resume: only where the registry pays on locked units (registry-config's staking_rewards_enabled) -->
        <div v-if="stakingRewardsOn" class="enf-action">
          <div class="enf-action-title"><Icon name="mdi:pause" :size="13" /> Payouts</div>
          <div class="enf-action-row">
            <input v-model.number="pauseDays" type="number" min="1" max="365" class="enf-input enf-input--xs" title="days" />
            <span class="enf-hint">days</span>
            <button class="enf-btn enf-btn--warn" :disabled="busy" @click="ask('pause')">Pause…</button>
            <button class="enf-btn enf-btn--ghost" :disabled="busy" @click="ask('resume')">Resume…</button>
          </div>
        </div>

        <!-- Suspend / reinstate -->
        <div class="enf-action">
          <div class="enf-action-title"><Icon name="mdi:cancel" :size="13" /> Account</div>
          <div class="enf-action-row">
            <button class="enf-btn enf-btn--danger" :disabled="busy" @click="ask('suspend')">Suspend…</button>
            <button class="enf-btn enf-btn--ghost" :disabled="busy" @click="ask('reinstate')">Reinstate…</button>
          </div>
        </div>
      </div>
    </section>

    <!-- ═══ Pending two-man queue ═══ -->
    <section class="enf-card" data-tour="enf-pending">
      <div class="enf-card-head">
        <Icon name="mdi:account-multiple-outline" :size="15" /> PENDING APPROVALS (two-man rule)
        <button class="enf-btn enf-btn--ghost enf-head-btn" :disabled="busy" @click="loadPending">Refresh</button>
      </div>
      <!-- §FESUITE (2026-10-05): a failed queue read put a toast up and said "the queue is clear" under it: an all-clear
           on the two-man queue that the page never read. It says the read failed now, with Try again. -->
      <ReadFailedNotice v-if="pendingRead === 'failed' && !pending.length" dense :retry="loadPending" data-testid="enf-pending-failed" />
      <p v-else-if="pendingRead === 'ok' && !pending.length" class="enf-empty">No pending enforcement actions — the queue is clear.</p>
      <div v-for="p in pending" :key="p.id" class="enf-pending-row">
        <span class="enf-pill enf-pill--warn">{{ p.action_type || p.action || 'action' }}</span>
        <span class="enf-pending-did">{{ p.agent_did || '—' }}</span>
        <span class="enf-meta" v-if="p.requested_by">by <strong>{{ p.requested_by }}</strong></span>
        <span class="enf-pending-reason" v-if="p.reason">“{{ p.reason }}”</span>
        <span class="enf-pending-spacer"></span>
        <button class="enf-btn enf-btn--ghost" :disabled="busy" @click="ask('approve', p)">Approve…</button>
        <button class="enf-btn enf-btn--danger" :disabled="busy" @click="ask('rejectPending', p)">Reject…</button>
      </div>
    </section>

    <!-- ═══ Registry policy ═══ -->
    <section class="enf-card" data-tour="enf-policy">
      <div class="enf-card-head">
        <Icon name="mdi:scale-balance" :size="15" /> ENFORCEMENT POLICY
        <button class="enf-btn enf-btn--ghost enf-head-btn" :disabled="busy" @click="loadPolicy">Reload</button>
        <button class="enf-btn enf-btn--ghost enf-head-btn" :disabled="busy" @click="showDefaults = !showDefaults">{{ showDefaults ? 'Hide defaults' : 'Show defaults' }}</button>
      </div>
      <p class="enf-hint enf-hint--block">
        The live policy JSON (offense ladder thresholds, slash percentages, pause durations).
        Edits are validated server-side and require a reason.
      </p>

      <!-- §FRAMEPOLICY — what this frame ACTUALLY applies, and where each rule
           came from. The JSON below is the stored row; this is the resolved
           document, which is what the code reads and what the signed registry
           card publishes. -->
      <div v-if="resolved" class="enf-posture" data-testid="enf-posture">
        <div class="enf-posture-head">
          <span class="enf-posture-title">DECLARED POSTURE</span>
          <span class="enf-pill" :class="resolved.policy_source === 'amended' ? 'enf-pill--ok' : 'enf-pill--warn'">
            {{ resolved.policy_source === 'amended' ? `amended · v${resolved.policy_version}` : 'factory default · never amended' }}
          </span>
          <span class="enf-hint enf-posture-hash" :title="resolved.policy_hash">
            published hash sha256:{{ resolved.policy_hash.slice(0, 16) }}…
          </span>
        </div>
        <p class="enf-hint enf-hint--block">
          These are the rules this frame applies and publishes on its registry card, so a peer can
          read them before federating. A value marked <strong>default</strong> is the shipped
          default, not a choice this frame made.
        </p>
        <table class="enf-posture-table">
          <thead>
            <tr><th>Rule</th><th>Value</th><th>Set by</th><th>Allowed</th></tr>
          </thead>
          <tbody>
            <tr v-for="path in resolved.governed_paths" :key="path">
              <td class="enf-posture-path">{{ path.replace(/^governance\./, '') }}</td>
              <td class="enf-posture-val">{{ resolved.governed[path]?.value }}</td>
              <td>
                <span class="enf-src" :class="resolved.governed[path]?.source === 'policy' ? 'enf-src--set' : 'enf-src--dflt'">
                  {{ resolved.governed[path]?.source === 'policy' ? 'this frame' : 'default' }}
                </span>
                <span v-if="resolved.governed[path]?.via_deprecated_key" class="enf-hint"
                      :title="resolved.governed[path]?.via_deprecated_key">via deprecated key</span>
              </td>
              <td class="enf-hint">
                <template v-if="resolved.governed[path]?.bounds">
                  {{ resolved.governed[path]?.bounds?.min ?? '—' }} … {{ resolved.governed[path]?.bounds?.max ?? '—' }}
                </template>
                <template v-else>—</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="enf-policy-grid">
        <div class="enf-policy-col">
          <div id="enf-policy-live-label" class="enf-policy-label">Live policy (editable)</div>
          <textarea v-model="policyText" class="enf-json" rows="16" spellcheck="false" aria-labelledby="enf-policy-live-label"></textarea>
          <div class="enf-action-row">
            <button class="enf-btn enf-btn--warn" :disabled="busy || !policyDirty" @click="ask('savePolicy')">Save policy…</button>
            <span v-if="policyParseError" class="enf-err">{{ policyParseError }}</span>
            <span v-else-if="!policyDirty" class="enf-hint">unchanged</span>
          </div>
        </div>
        <div v-if="showDefaults" class="enf-policy-col">
          <div class="enf-policy-label">Source defaults (read-only)</div>
          <pre class="enf-json enf-json--ro">{{ defaultsText }}</pre>
        </div>
      </div>
    </section>

    <ConfirmActionModal
      :show="!!confirmKind"
      :title="confirmCfg.title"
      :message="confirmCfg.message"
      :tone="confirmCfg.tone"
      :confirm-text="confirmCfg.confirmText"
      :reason-required="confirmCfg.reasonRequired"
      :reason-min-length="5"
      :busy="busy"
      @close="confirmKind = null"
      @confirm="onConfirm"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { enforcementAdmin, type SlashPreview, type EnforcementStatus, type PendingAction, type ResolvedPolicy } from '@/services/api/enforcementAdmin'

const route = useRoute()

const did = ref('')
const loading = ref(false)
const busy = ref(false)
const agentStatus = ref<EnforcementStatus | null>(null)
const statusError = ref('')
const banner = ref<{ ok: boolean; text: string } | null>(null)

const slashAmount = ref<number | ''>('')
const slashPreview = ref<SlashPreview | null>(null)
const offenseType = ref('dispute_lost')
const offenseSeverity = ref(1)
const offenseRef = ref('')
const pauseDays = ref(7)

const pending = ref<PendingAction[]>([])
const pendingTarget = ref<PendingAction | null>(null)

const policyText = ref('')
const policyLoaded = ref('')
const defaultsText = ref('')
const showDefaults = ref(false)
const resolved = ref<ResolvedPolicy | null>(null)

type Kind = 'slash' | 'offense' | 'pause' | 'resume' | 'suspend' | 'reinstate' | 'savePolicy' | 'approve' | 'rejectPending'
const confirmKind = ref<Kind | null>(null)

const { config: enfRegistryCfg } = useRegistryConfig()
// his word 2026-10-25: "staking doesnt exist anymore in the way it did": the payout lever shows where payouts on locks run
const stakingRewardsOn = computed(() => enfRegistryCfg.value.staking_rewards_enabled === true)
const validSlashAmount = computed(() => typeof slashAmount.value === 'number' && Number.isFinite(slashAmount.value) && slashAmount.value >= 1)
const policyDirty = computed(() => policyText.value.trim() !== policyLoaded.value.trim())
const policyParseError = computed(() => {
  if (!policyDirty.value) return ''
  try { JSON.parse(policyText.value); return '' } catch { return 'invalid JSON' }
})

const statusTone = computed(() => {
  const s = String(agentStatus.value?.enforcement_status || agentStatus.value?.status || '').toLowerCase()
  if (s.includes('suspend') || s.includes('block')) return 'enf-pill--danger'
  if (s.includes('pause') || s.includes('probation') || s.includes('warn')) return 'enf-pill--warn'
  return 'enf-pill--ok'
})
// Render every scalar field the backend returns — the status shape varies by
// enforcement state and hardcoding keys would silently drop the useful ones.
const scalarStatus = computed(() => {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(agentStatus.value || {})) {
    if (k === 'agent_did' || k === 'status' || k === 'enforcement_status') continue
    if (v === null || v === undefined || typeof v === 'object') continue
    out[k] = String(v)
  }
  return out
})

function note(ok: boolean, text: string) {
  banner.value = { ok, text }
  setTimeout(() => { if (banner.value?.text === text) banner.value = null }, 7000)
}
function errText(e: unknown): string {
  const r = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail
  if (typeof r === 'string') return r
  if (r) return JSON.stringify(r).slice(0, 300)
  return (e as Error)?.message || 'request failed'
}

async function loadStatus() {
  if (!did.value) return
  loading.value = true
  statusError.value = ''
  agentStatus.value = null
  slashPreview.value = null
  try {
    agentStatus.value = await enforcementAdmin.agentStatus(did.value)
  } catch (e) {
    statusError.value = errText(e)
  } finally {
    loading.value = false
  }
}

async function previewSlash() {
  if (!validSlashAmount.value) return
  busy.value = true
  try {
    slashPreview.value = await enforcementAdmin.slashPreview(did.value, slashAmount.value as number)
  } catch (e) {
    note(false, `preview failed: ${errText(e)}`)
  } finally {
    busy.value = false
  }
}

// the queue's own read state: "clear" only after a read that answered; a failed refresh keeps the rows it showed
const pendingRead = ref<'loading' | 'ok' | 'failed'>('loading')
async function loadPending() {
  try {
    const r = await enforcementAdmin.listPending()
    pending.value = (r.pending || r.actions || (Array.isArray(r) ? (r as unknown as PendingAction[]) : [])) as PendingAction[]
    pendingRead.value = 'ok'
  } catch (e) {
    if (pendingRead.value !== 'ok') pendingRead.value = 'failed'
    note(false, `pending queue: ${errText(e)}`)
  }
}

async function loadPolicy() {
  try {
    const p = await enforcementAdmin.getPolicy()
    policyLoaded.value = JSON.stringify((p as { policy?: unknown }).policy ?? p, null, 2)
    policyText.value = policyLoaded.value
  } catch (e) {
    note(false, `policy: ${errText(e)}`)
  }
  try {
    const d = await enforcementAdmin.getPolicyDefaults()
    defaultsText.value = JSON.stringify((d as { policy?: unknown }).policy ?? (d as { defaults?: unknown }).defaults ?? d, null, 2)
  } catch { defaultsText.value = '—' }
  // §FRAMEPOLICY — the posture readout is its own read: a failure here must not
  // blank the editable JSON above it, and an absent block is honest (the panel
  // simply does not claim a posture it could not load).
  try {
    resolved.value = await enforcementAdmin.getResolvedPolicy()
  } catch (e) {
    resolved.value = null
    note(false, `posture: ${errText(e)}`)
  }
}

function ask(kind: Kind, target?: PendingAction) {
  if (kind === 'savePolicy' && policyParseError.value) { note(false, 'fix the policy JSON first'); return }
  pendingTarget.value = target || null
  confirmKind.value = kind
}

const confirmCfg = computed(() => {
  const d = `<code>${did.value}</code>`
  switch (confirmKind.value) {
    case 'slash': return {
      title: 'Slash locked units', tone: 'danger' as const, confirmText: 'Slash', reasonRequired: true,
      message: `Slash <strong>${slashAmount.value}</strong> from the locked units of ${d}. This burns them and is recorded as a supply-destroying event. It cannot be undone.`,
    }
    case 'offense': return {
      title: 'Record offense', tone: 'warn' as const, confirmText: 'Record', reasonRequired: false,
      message: `Record a <strong>${offenseType.value}</strong> offense (severity ${offenseSeverity.value}) against ${d}. The offense ladder may trigger automatic penalties at thresholds.`,
    }
    case 'pause': return {
      title: 'Pause payouts', tone: 'warn' as const, confirmText: 'Pause', reasonRequired: true,
      message: `Pause payouts on locked units for ${d} for <strong>${pauseDays.value} days</strong>.`,
    }
    case 'resume': return {
      title: 'Resume payouts', tone: 'primary' as const, confirmText: 'Resume', reasonRequired: true,
      message: `Resume payouts on locked units for ${d}.`,
    }
    case 'suspend': return {
      title: 'Suspend agent', tone: 'danger' as const, confirmText: 'Suspend', reasonRequired: true,
      message: `Suspend ${d} from all economic activity on this registry.`,
    }
    case 'reinstate': return {
      title: 'Reinstate agent', tone: 'primary' as const, confirmText: 'Reinstate', reasonRequired: true,
      message: `Reinstate ${d} — lifts the enforcement suspension.`,
    }
    case 'savePolicy': return {
      title: 'Update enforcement policy', tone: 'warn' as const, confirmText: 'Save policy', reasonRequired: true,
      message: 'Replace the live enforcement policy with the edited JSON. Server-side validation applies; the change affects every agent on this registry.',
    }
    case 'approve': return {
      title: 'Approve pending action', tone: 'danger' as const, confirmText: 'Approve & execute', reasonRequired: false,
      message: `Second-approve pending <strong>${pendingTarget.value?.action_type || pendingTarget.value?.action || 'action'}</strong> #${pendingTarget.value?.id} against <code>${pendingTarget.value?.agent_did || '—'}</code>. It executes immediately.`,
    }
    case 'rejectPending': return {
      title: 'Reject pending action', tone: 'warn' as const, confirmText: 'Reject', reasonRequired: true,
      message: `Reject pending <strong>${pendingTarget.value?.action_type || pendingTarget.value?.action || 'action'}</strong> #${pendingTarget.value?.id}.`,
    }
    default: return { title: '', tone: 'primary' as const, confirmText: 'Confirm', reasonRequired: false, message: '' }
  }
})

async function onConfirm(reason: string) {
  const kind = confirmKind.value
  if (!kind) return
  busy.value = true
  try {
    switch (kind) {
      case 'slash':
        await enforcementAdmin.slashStake(did.value, slashAmount.value as number, reason)
        note(true, `slashed ${slashAmount.value} from ${did.value}`)
        slashPreview.value = null; slashAmount.value = ''
        break
      case 'offense':
        await enforcementAdmin.recordOffense(did.value, {
          offense_type: offenseType.value, severity: offenseSeverity.value,
          ...(offenseRef.value ? { reference: offenseRef.value } : {}),
        })
        note(true, `offense recorded against ${did.value}`)
        offenseRef.value = ''
        break
      case 'pause':
        await enforcementAdmin.pauseRewards(did.value, pauseDays.value, reason)
        note(true, `payouts paused ${pauseDays.value}d for ${did.value}`)
        break
      case 'resume':
        await enforcementAdmin.resumeRewards(did.value, reason)
        note(true, `payouts resumed for ${did.value}`)
        break
      case 'suspend':
        await enforcementAdmin.suspend(did.value, reason)
        note(true, `${did.value} suspended`)
        break
      case 'reinstate':
        await enforcementAdmin.reinstate(did.value, reason)
        note(true, `${did.value} reinstated`)
        break
      case 'savePolicy':
        await enforcementAdmin.updatePolicy(JSON.parse(policyText.value), reason)
        note(true, 'enforcement policy updated')
        await loadPolicy()
        break
      case 'approve':
        if (pendingTarget.value) await enforcementAdmin.approvePending(pendingTarget.value.id)
        note(true, `pending action #${pendingTarget.value?.id} approved & executed`)
        await loadPending()
        break
      case 'rejectPending':
        if (pendingTarget.value) await enforcementAdmin.rejectPending(pendingTarget.value.id, reason)
        note(true, `pending action #${pendingTarget.value?.id} rejected`)
        await loadPending()
        break
    }
    confirmKind.value = null
    if (['slash', 'offense', 'pause', 'resume', 'suspend', 'reinstate'].includes(kind) && did.value) await loadStatus()
  } catch (e) {
    note(false, errText(e))
    confirmKind.value = null
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  const q = route.query.did
  if (typeof q === 'string' && q.startsWith('did:')) {
    did.value = q
    loadStatus()
  }
  loadPending()
  loadPolicy()
})
</script>

<style scoped>
.enf-page { max-width: 1120px; margin: 0 auto; padding: 24px 20px 80px; }
.enf-hero { margin-bottom: 18px; }
.enf-eyebrow { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; letter-spacing: 2px; color: var(--brand-primary, #00e5ff); opacity: .85; }
.enf-h1 { margin: 6px 0 4px; font-size: 26px; }
.enf-sub { margin: 0; max-width: 760px; color: var(--text-secondary, #9ab); font-size: 13.5px; line-height: 1.55; }

.enf-banner { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: 8px; font-size: 13px; margin-bottom: 14px; border: 1px solid; }
.enf-banner--ok { border-color: rgba(0, 220, 130, .4); background: rgba(0, 220, 130, .08); color: #7ce8b8; }
.enf-banner--err { border-color: rgba(255, 90, 90, .45); background: rgba(255, 90, 90, .08); color: #ff9c9c; }

.enf-card { border: 1px solid var(--border-color, rgba(120, 160, 200, .18)); border-radius: 12px; background: var(--bg-elevated, rgba(10, 18, 30, .55)); padding: 16px 18px; margin-bottom: 18px; }
/* the head wraps on a phone: the title, then its buttons, where "Show defaults" ran 40 px past the card (the camera,
   2026-10-13) */
.enf-card-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; font-size: 12px; letter-spacing: 1.6px; color: var(--text-secondary, #9ab); margin-bottom: 12px; }
.enf-head-btn { margin-left: auto; }
.enf-head-btn + .enf-head-btn { margin-left: 8px; }

.enf-did-row { display: flex; gap: 10px; }
.enf-input { background: rgba(0, 0, 0, .25); border: 1px solid var(--border-color, rgba(120, 160, 200, .25)); border-radius: 8px; color: var(--text-primary, #e8f1fa); padding: 8px 10px; font-size: 13px; flex: 1; min-width: 0; }
.enf-input--sm { flex: 0 1 180px; }
.enf-input--xs { flex: 0 0 84px; }
.enf-btn { border: 1px solid var(--brand-primary, #00e5ff); background: transparent; color: var(--brand-primary, #00e5ff); border-radius: 8px; padding: 7px 14px; font-size: 12.5px; cursor: pointer; white-space: nowrap; }
.enf-btn:disabled { opacity: .4; cursor: default; }
.enf-btn--ghost { border-color: var(--border-color, rgba(120, 160, 200, .35)); color: var(--text-secondary, #9ab); }
.enf-btn--warn { border-color: #f0b429; color: #f0b429; }
.enf-btn--danger { border-color: #ff5a5a; color: #ff7a7a; }

.enf-status { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; margin-top: 14px; }
.enf-pill { padding: 3px 10px; border-radius: 999px; font-size: 11.5px; letter-spacing: .8px; text-transform: uppercase; border: 1px solid; }
.enf-pill--ok { border-color: rgba(0, 220, 130, .5); color: #7ce8b8; }
.enf-pill--warn { border-color: rgba(240, 180, 41, .55); color: #f0c95c; }
.enf-pill--danger { border-color: rgba(255, 90, 90, .55); color: #ff8a8a; }
.enf-meta { font-size: 12.5px; color: var(--text-secondary, #9ab); }
.enf-meta strong { color: var(--text-primary, #e8f1fa); font-weight: 600; }
.enf-err { color: #ff9c9c; font-size: 12.5px; margin: 10px 0 0; }
.enf-hint { font-size: 12px; color: var(--text-secondary, #9ab); opacity: .8; align-self: center; }
.enf-hint--block { display: block; margin: -4px 0 10px; }
.enf-empty { font-size: 13px; color: var(--text-secondary, #9ab); margin: 4px 0; }

.enf-actions { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 14px; margin-top: 16px; }
.enf-action { border: 1px solid var(--border-color, rgba(120, 160, 200, .14)); border-radius: 10px; padding: 12px; }
.enf-action-title { display: flex; align-items: center; gap: 6px; font-size: 12px; letter-spacing: 1px; color: var(--text-secondary, #9ab); margin-bottom: 10px; text-transform: uppercase; }
.enf-action-row { display: flex; flex-wrap: wrap; gap: 8px; }
.enf-preview { margin-top: 10px; font-size: 12.5px; color: #f0c95c; font-family: var(--font-mono, monospace); }

.enf-pending-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 10px 0; border-top: 1px solid var(--border-color, rgba(120, 160, 200, .12)); }
.enf-pending-did { font-family: var(--font-mono, monospace); font-size: 12px; color: var(--text-primary, #e8f1fa); word-break: break-all; }
.enf-pending-reason { font-size: 12.5px; color: var(--text-secondary, #9ab); font-style: italic; }
.enf-pending-spacer { flex: 1; }

.enf-policy-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 14px; }
/* §FRAMEPOLICY — the declared posture: what this frame applies, and who chose it. */
.enf-posture { border: 1px solid var(--border-color, rgba(120, 160, 200, .2)); border-radius: 8px; padding: 12px 14px; margin: 0 0 14px; background: rgba(0, 0, 0, .18); }
.enf-posture-head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-bottom: 8px; }
.enf-posture-title { font-size: 11.5px; letter-spacing: 1.2px; text-transform: uppercase; color: var(--text-secondary, #9ab); }
.enf-posture-hash { font-family: var(--font-mono, monospace); font-size: 11.5px; }
.enf-posture-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.enf-posture-table th { text-align: left; font-weight: 500; font-size: 11px; letter-spacing: .9px; text-transform: uppercase; color: var(--text-secondary, #9ab); padding: 4px 10px 6px 0; border-bottom: 1px solid var(--border-color, rgba(120, 160, 200, .2)); }
.enf-posture-table td { padding: 5px 10px 5px 0; border-bottom: 1px solid rgba(120, 160, 200, .08); vertical-align: top; }
.enf-posture-path { font-family: var(--font-mono, monospace); color: var(--text-primary, #dfe9f5); }
.enf-posture-val { font-family: var(--font-mono, monospace); font-variant-numeric: tabular-nums; color: var(--text-primary, #dfe9f5); }
.enf-src { font-size: 11px; letter-spacing: .5px; padding: 1px 7px; border-radius: 999px; border: 1px solid; margin-right: 6px; white-space: nowrap; }
.enf-src--set { border-color: rgba(0, 220, 130, .45); color: #7ce8b8; }
.enf-src--dflt { border-color: rgba(120, 160, 200, .35); color: var(--text-secondary, #9ab); }
@media (max-width: 640px) {
  .enf-posture-table { display: block; overflow-x: auto; }
}
.enf-policy-label { font-size: 11.5px; letter-spacing: 1.2px; color: var(--text-secondary, #9ab); margin-bottom: 6px; text-transform: uppercase; }
.enf-json { width: 100%; box-sizing: border-box; background: rgba(0, 0, 0, .3); border: 1px solid var(--border-color, rgba(120, 160, 200, .2)); border-radius: 8px; color: var(--text-primary, #dfe9f5); font-family: var(--font-mono, monospace); font-size: 12px; line-height: 1.5; padding: 10px; resize: vertical; }
.enf-json--ro { max-height: 420px; overflow: auto; margin: 0; white-space: pre; }
.enf-policy-col .enf-action-row { margin-top: 8px; }
</style>
