<template>
  <div class="cockpit-view p-4 md:p-6 space-y-6 max-w-6xl mx-auto">
    <!-- Header -->
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-2xl font-bold flex items-center gap-2">
          <Icon name="mdi:card-account-details" class="w-7 h-7 text-rose-400" />
          Cockpit Card
        </h1>
        <p class="text-sm opacity-70 mt-1">
          The liable hybrid identity — you underwrite an agent for a declared scope. Authority is
          re-derived on every request; revoke a flag and the card narrows instantly.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span class="px-2 py-1 rounded-sm text-xs font-mono border"
              :class="mode === 'enforce' ? 'border-red-500 text-red-400' : mode === 'shadow' ? 'border-amber-500 text-amber-400' : 'border-gray-600 text-gray-400'">
          MODE: {{ mode.toUpperCase() }}
        </span>
        <button class="btn-secondary text-sm" @click="reload" :disabled="loading">
          <Icon name="mdi:refresh" class="w-4 h-4" /> Refresh
        </button>
      </div>
    </div>

    <!-- Feature dark -->
    <div v-if="featureDark" class="rounded-lg border border-gray-700 p-8 text-center opacity-80">
      <Icon name="mdi:card-account-details" class="w-10 h-10 mx-auto mb-3 opacity-50" />
      <p class="font-semibold">Liability mandates are not enabled on this registry yet.</p>
      <p class="text-sm mt-1 opacity-70">The Cockpit Card ships dark and is lit per-registry (frame-c first).</p>
    </div>

    <template v-else>
      <!-- §COCKPITDESK (2026-10-15): a refused confirmation says why, above the list it was pressed in (the list is re-read) -->
      <p v-if="confirmError" class="text-sm text-red-400" role="alert" data-testid="ck-confirm-error">{{ confirmError }}</p>
      <!-- Pending confirms (phone rail) -->
      <div v-if="challenges.length" class="rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 space-y-3">
        <h2 class="font-semibold flex items-center gap-2 text-amber-400">
          <Icon name="mdi:shield-key" class="w-5 h-5" /> Pending confirmations ({{ challenges.length }})
        </h2>
        <div v-for="ch in challenges" :key="ch.id" class="rounded-sm border border-gray-700 p-3 flex flex-wrap items-center gap-3">
          <div class="flex-1 min-w-[220px]">
            <div class="font-mono text-sm">{{ ch.action_type }} <span v-if="ch.action_ref" class="opacity-60">· {{ ch.action_ref }}</span></div>
            <div class="text-xs opacity-60 mt-0.5">hash {{ ch.challenge_hash.slice(0, 16) }}… · expires {{ fmtTime(ch.expires_at) }}</div>
            <pre class="text-xs opacity-70 mt-1 whitespace-pre-wrap max-h-24 overflow-auto">{{ factsPreview(ch.facts) }}</pre>
          </div>
          <div class="flex items-center gap-2">
            <input v-model="challengeCodes[ch.id]" placeholder="TOTP" maxlength="8"
                   class="input-field w-24 text-center font-mono" />
            <button class="btn-primary text-sm" :disabled="!challengeCodes[ch.id] || busy" @click="approve(ch)">Approve</button>
            <button class="btn-secondary text-sm" :disabled="busy" @click="deny(ch)">Deny</button>
          </div>
        </div>
      </div>

      <!-- Issue wizard -->
      <div class="rounded-lg border border-gray-700 p-4 space-y-4">
        <h2 class="font-semibold flex items-center gap-2">
          <Icon name="mdi:plus-circle" class="w-5 h-5 text-rose-400" /> Underwrite an agent
        </h2>
        <div v-if="!info?.presence.totp_enrolled" class="text-sm rounded-sm border border-amber-500/40 bg-amber-500/5 p-3">
          <Icon name="mdi:alert" class="w-4 h-4 inline text-amber-400" />
          Two-factor (TOTP) enrolment is required before you can issue a mandate — the card is only
          as strong as the presence proof behind it. Enable 2FA in Settings first.
        </div>
        <div class="grid md:grid-cols-2 gap-4">
          <div>
            <label class="text-xs uppercase opacity-60">Agent</label>
            <select v-model="form.agent_did" class="input-field w-full mt-1" aria-label="Agent">
              <option value="" disabled>Select one of your agents…</option>
              <option v-for="a in myAgents" :key="a.did" :value="a.did">{{ a.name || a.did }}</option>
            </select>
          </div>
          <div>
            <label class="text-xs uppercase opacity-60">Expires (days, blank = none)</label>
            <input v-model.number="form.expires_in_days" type="number" min="1" max="365" class="input-field w-full mt-1" aria-label="Expires in days" />
          </div>
        </div>
        <div>
          <label class="text-xs uppercase opacity-60">Scope — what you underwrite
            <span class="opacity-50">(your live authority allows {{ info?.delegatable.length ?? 0 }} permissions)</span>
          </label>
          <div class="flex flex-wrap gap-2 mt-2">
            <button v-for="p in info?.delegatable ?? []" :key="p" @click="toggleScope(p)"
                    class="px-2 py-1 rounded-sm text-xs font-mono border transition"
                    :class="form.scope.includes(p) ? 'border-rose-400 bg-rose-400/10 text-rose-300' : 'border-gray-600 opacity-70 hover:opacity-100'">
              {{ p }}
            </button>
          </div>
          <p class="text-xs opacity-50 mt-2">
            Never delegatable: <span class="font-mono">{{ (info?.non_delegatable ?? []).join(', ') }}</span>
            — a mandate is for doing work, not for handing out authority.
          </p>
        </div>
        <div class="flex flex-wrap items-end gap-3">
          <div>
            <label class="block text-xs uppercase opacity-60">Presence — TOTP code</label>
            <input v-model="form.totp_code" placeholder="000000" maxlength="8"
                   class="input-field w-32 text-center font-mono mt-1" />
          </div>
          <button class="btn-primary" :disabled="!canIssue || busy" @click="issue">
            <Icon name="mdi:draw-pen" class="w-4 h-4" /> Sign mandate
          </button>
          <span v-if="issueError" class="text-sm text-red-400">{{ issueError }}</span>
        </div>
      </div>

      <!-- Mandates -->
      <div class="rounded-lg border border-gray-700 p-4 space-y-3">
        <h2 class="font-semibold flex items-center gap-2">
          <Icon name="mdi:certificate" class="w-5 h-5 text-rose-400" /> My mandates ({{ mandates.length }})
        </h2>
        <p v-if="mandateError" class="text-sm text-red-400" role="alert" data-testid="ck-mandate-error">{{ mandateError }}</p>
        <ReadFailedNotice v-if="mandatesFailed && !mandates.length" dense text="Your mandates could not be read just now." :retry="reload" />
      <div v-else-if="!mandates.length" class="text-sm opacity-60 py-4 text-center">No mandates yet — underwrite an agent above.</div>
        <div v-for="m in mandates" :key="m.id" class="rounded-sm border border-gray-700">
          <button class="w-full flex flex-wrap items-center gap-3 p-3 text-left" @click="toggleDetail(m.id)">
            <span class="px-2 py-0.5 rounded-sm text-xs font-mono"
                  :class="m.status === 'signed' ? (m.resolved?.valid ? 'bg-emerald-500/15 text-emerald-400' : 'bg-amber-500/15 text-amber-400') : 'bg-red-500/15 text-red-400'">
              {{ m.status === 'signed' ? (m.resolved?.valid ? 'LIVE' : 'CLAMPED') : m.status.toUpperCase() }}
            </span>
            <span class="font-mono text-sm flex-1 min-w-[200px] truncate">{{ m.agent_did }}</span>
            <span class="text-xs opacity-60">{{ m.tier }} · {{ (m.resolved?.effective_scope ?? m.scope).length }} perms · {{ fmtTime(m.issued_at) }}</span>
            <Icon :name="detailOpen === m.id ? 'mdi:chevron-up' : 'mdi:chevron-down'" class="w-4 h-4 opacity-60" />
          </button>
          <div v-if="detailOpen === m.id" class="border-t border-gray-700 p-3 space-y-3 text-sm">
            <div class="grid md:grid-cols-2 gap-3">
              <div>
                <div class="text-xs uppercase opacity-60 mb-1">Effective scope (now)</div>
                <div class="flex flex-wrap gap-1">
                  <span v-for="p in (m.resolved?.effective_scope ?? [])" :key="p" class="px-1.5 py-0.5 rounded-sm bg-emerald-500/10 text-emerald-300 text-xs font-mono">{{ p }}</span>
                  <span v-if="!(m.resolved?.effective_scope ?? []).length" class="text-xs opacity-60">∅ — {{ (m.resolved?.reasons ?? []).join(', ') || 'nothing conveyed' }}</span>
                </div>
                <div class="text-xs opacity-50 mt-1">Declared: <span class="font-mono">{{ m.scope.join(', ') }}</span></div>
              </div>
              <div>
                <div class="text-xs uppercase opacity-60 mb-1">Card</div>
                <div class="text-xs font-mono opacity-70 break-all">{{ m.id }}</div>
                <div class="text-xs opacity-60 mt-0.5">content sha256 {{ m.content_hash.slice(0, 20) }}…</div>
                <div class="text-xs mt-0.5" :class="detail?.chain_ok === false ? 'text-red-400' : 'opacity-60'">
                  evidence chain: {{ detail?.chain_ok === false ? `BROKEN @seq ${detail?.chain_break_at}` : `${detail?.evidence?.length ?? '…'} links, intact` }}
                </div>
              </div>
            </div>
            <div v-if="detail?.evidence?.length" class="max-h-56 overflow-auto rounded-sm border border-gray-700/60">
              <table class="w-full text-xs">
                <thead class="opacity-60 text-left"><tr><th class="p-1.5">#</th><th class="p-1.5">event</th><th class="p-1.5">ref</th><th class="p-1.5">presence</th><th class="p-1.5">when</th></tr></thead>
                <tbody>
                  <tr v-for="e in detail.evidence" :key="e.seq" class="border-t border-gray-700/40">
                    <td class="p-1.5 font-mono">{{ e.seq }}</td>
                    <td class="p-1.5 font-mono" :class="e.event_type.includes('denied') || e.event_type.includes('block') ? 'text-red-400' : ''">{{ e.event_type }}</td>
                    <td class="p-1.5 font-mono opacity-70">{{ e.action_ref || '—' }}</td>
                    <td class="p-1.5 opacity-70">{{ e.presence?.method || '—' }}</td>
                    <td class="p-1.5 opacity-60">{{ fmtTime(e.created_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div class="flex flex-wrap gap-2">
              <button class="btn-secondary text-xs" :disabled="busy" @click="runVerify(m)">
                <Icon name="mdi:check-decagram" class="w-4 h-4" /> Verify now
              </button>
              <button v-if="m.status === 'signed'" class="btn-secondary text-xs" :disabled="busy" @click="testChallenge(m)">
                <Icon name="mdi:cellphone-key" class="w-4 h-4" /> Test confirm
              </button>
              <button v-if="m.status === 'signed'" class="btn-danger text-xs" :disabled="busy" @click="revoke(m)">
                <Icon name="mdi:close-octagon" class="w-4 h-4" /> Revoke
              </button>
              <span v-if="verifyResult && verifyResult.id === m.id" class="text-xs font-mono"
                    :class="verifyResult.valid ? 'text-emerald-400' : 'text-red-400'">
                {{ verifyResult.valid ? '✔ valid' : `✖ ${verifyResult.reasons.join(', ')}` }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
// COCKPIT CARD view (L1, 2026-07-25) — dev-JWT surface for the liable human.
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { liabilityApi, type DelegatableInfo, type LiabilityChallenge, type LiabilityMandate } from '@/services/api/liability'
import { agentApi } from '@/services/api/agents'

const loading = ref(false)
const busy = ref(false)
const featureDark = ref(false)
const info = ref<DelegatableInfo | null>(null)
const mandates = ref<LiabilityMandate[]>([])
const challenges = ref<LiabilityChallenge[]>([])
const myAgents = ref<Array<{ did: string; name?: string }>>([])
const detailOpen = ref<string | null>(null)
const detail = ref<LiabilityMandate | null>(null)
const challengeCodes = ref<Record<string, string>>({})
const issueError = ref('')
const verifyResult = ref<{ id: string; valid: boolean; reasons: string[] } | null>(null)
// §COCKPITDESK (2026-10-15): a refused action says why. Revoke, Verify now, Test confirm and Deny threw out of the click
// (nothing said, the list as it was), and a refused approval (a wrong code, an ended challenge) was swallowed: the
// confirmation stayed as if the press had not happened.
const confirmError = ref('')
const mandateError = ref('')
function why(e: any, fallback: string): string {
  const d = e?.response?.data?.detail ?? e?.response?.data?.error?.detail
  if (typeof d === 'string' && d) return d
  if (d && typeof d === 'object') return String(d.error || d.message || JSON.stringify(d)).slice(0, 200)
  return fallback
}

const form = ref<{ agent_did: string; scope: string[]; expires_in_days: number | null; totp_code: string }>({
  agent_did: '', scope: [], expires_in_days: null, totp_code: '',
})

const mode = computed(() => info.value?.mode ?? 'off')
const canIssue = computed(() =>
  !!form.value.agent_did && form.value.scope.length > 0 && form.value.totp_code.length >= 6
  && !!info.value?.presence.totp_enrolled)

function fmtTime(t: string) { return new Date(t).toLocaleString(appLocale()) }
function factsPreview(f: Record<string, any>) { return JSON.stringify(f, null, 1).slice(0, 400) }
function toggleScope(p: string) {
  const i = form.value.scope.indexOf(p)
  if (i >= 0) form.value.scope.splice(i, 1); else form.value.scope.push(p)
}

// §FESUITE (the failing-reads census, 2026-10-04): with every read failed the card said "No mandates yet — underwrite an
// agent above." A 404 is the server's answer (the cockpit is dark here); any other failure read nothing.
const mandatesFailed = ref(false)
async function reload() {
  loading.value = true
  try {
    info.value = await liabilityApi.delegatable()
    featureDark.value = false
    const [mm, cc] = await Promise.all([liabilityApi.myMandates(), liabilityApi.pendingChallenges()])
    mandates.value = mm.mandates
    challenges.value = cc.challenges
    mandatesFailed.value = false
  } catch (e: any) {
    if (e?.response?.status === 404) featureDark.value = true
    else mandatesFailed.value = !mandates.value.length
  } finally { loading.value = false }
  try {
    const res = await agentApi.getMyAgents({ limit: 100 })
    myAgents.value = (Array.isArray(res) ? res : (res as any).items ?? []) as any
  } catch { /* agent list is a convenience only */ }
}

async function issue() {
  issueError.value = ''
  busy.value = true
  try {
    await liabilityApi.createMandate({
      agent_did: form.value.agent_did, scope: form.value.scope,
      expires_in_days: form.value.expires_in_days || undefined, totp_code: form.value.totp_code,
    })
    form.value.scope = []; form.value.totp_code = ''
    await reload()
  } catch (e: any) {
    const d = e?.response?.data?.detail
    issueError.value = typeof d === 'string' ? d : d?.error === 'scope_exceeds_authority'
      ? `Scope exceeds your authority: ${(d.offending ?? []).join(', ')}` : 'Issue failed'
  } finally { busy.value = false }
}

async function toggleDetail(id: string) {
  if (detailOpen.value === id) { detailOpen.value = null; detail.value = null; return }
  detailOpen.value = id
  detail.value = null
  try {
    const d = await liabilityApi.getMandate(id)
    // another card opened while this one was read: its evidence chain is not this one's
    if (detailOpen.value === id) detail.value = d
  } catch { /* keep summary row */ }
}

async function revoke(m: LiabilityMandate) {
  busy.value = true; mandateError.value = ''
  try { await liabilityApi.revokeMandate(m.id, 'revoked from Cockpit'); await reload() }
  catch (e: any) { mandateError.value = `Not revoked: ${why(e, 'the registry refused the revocation')}` }
  finally { busy.value = false }
}

async function runVerify(m: LiabilityMandate) {
  busy.value = true; mandateError.value = ''
  try {
    const r = await liabilityApi.verifyMandate(m.id)
    verifyResult.value = { id: m.id, valid: r.valid, reasons: r.reasons ?? [] }
  } catch (e: any) { mandateError.value = `Could not verify: ${why(e, 'the registry gave no answer')}` }
  finally { busy.value = false }
}

async function testChallenge(m: LiabilityMandate) {
  busy.value = true; mandateError.value = ''
  try {
    await liabilityApi.createChallenge({ mandate_id: m.id, action_type: 'cockpit.test', facts: { note: 'self-test confirm' } })
    challenges.value = (await liabilityApi.pendingChallenges()).challenges
  } catch (e: any) { mandateError.value = `No test confirmation: ${why(e, 'the registry refused it')}` }
  finally { busy.value = false }
}

async function approve(ch: LiabilityChallenge) {
  busy.value = true; confirmError.value = ''
  try {
    await liabilityApi.approveChallenge(ch.id, { totp_code: challengeCodes.value[ch.id] })
    delete challengeCodes.value[ch.id]
    await reload()
  } catch (e: any) {
    // the refusal is evidence server-side as well; the person is told here, and the list re-read (a refused
    // attempt can end the challenge)
    confirmError.value = `Not approved: ${why(e, 'the registry refused the confirmation')}`
    await reload()
  } finally { busy.value = false }
}

async function deny(ch: LiabilityChallenge) {
  busy.value = true; confirmError.value = ''
  try { await liabilityApi.denyChallenge(ch.id); await reload() }
  catch (e: any) { confirmError.value = `Not denied: ${why(e, 'the registry refused')}` }
  finally { busy.value = false }
}

onMounted(reload)
</script>

<style scoped>
/* Tailwind 4: a style block compiles on its own, so @apply needs the theme it applies from (no CSS is emitted) */
@reference "../assets/styles/main.css";
.input-field {
  @apply bg-transparent border border-gray-600 rounded-sm px-2 py-1.5 text-sm focus:border-rose-400 focus:outline-hidden;
}
.btn-primary {
  @apply inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm bg-rose-500/90 hover:bg-rose-500 text-white text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed transition;
}
/* §COCKPITDESK (2026-10-15): no background of their own, so the browser drew its grey button face (the camera's white
   Refresh); transparent with the theme's text, like the rest of the card */
.btn-secondary {
  @apply inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm border border-gray-600 hover:border-gray-400 text-sm disabled:opacity-40 transition;
  background: transparent; color: var(--nc-text-secondary, #c9d1d9);
}
.btn-danger {
  @apply inline-flex items-center gap-1.5 px-3 py-1.5 rounded-sm border border-red-500/60 text-red-400 hover:bg-red-500/10 text-sm disabled:opacity-40 transition;
  background: transparent;
}
</style>
