<!--
  POCKET FRAME — Approvals & panic control (S2, 2026-07-07 · AAA pass).
  Mobile-first oversight over IRONKEY L3/L4 for the agents you own:
    • per-agent delegation grants (L3) with modal-confirmed revoke
    • capability permits the agent issued/holds (L4) with subtree-revoke
    • a PANIC button that revokes an agent's entire token tree (typed-confirm)
  All read/write via the existing owner/admin delegation endpoints. Deny-only,
  Δ-irrelevant. This is the "co-signer" half of POCKET FRAME made visible.
-->
<template>
  <div class="pa-wrap">
    <header class="pa-head">
      <div class="pa-head-badge"><Icon name="mdi:shield-key" /></div>
      <div class="pa-head-txt">
        <h1>Approvals &amp; Control</h1>
        <p>Delegations and capability permits for your agents — revoke instantly.</p>
      </div>
    </header>

    <!-- §POCKETBRIDGE2 P0.1 (Commander feedback): the picker searches the whole
         fleet server-side, balance-ranked — a bare select was unusable at fleet
         scale. Same rail as the Agents tab (getMyAgents q + sort=balance). -->
    <div class="pa-picker" data-tour="pk-appr-picker">
      <div class="pa-pick-box">
        <Icon name="mdi:magnify" class="pa-pick-ico" />
        <input v-model="pickerQ" class="pa-pick-in" type="search" inputmode="search"
               data-testid="pa-picker-search"
               :placeholder="selectedName ? selectedName : 'Search your agents…'"
               @focus="openPicker" @input="onPickerInput" />
        <button class="pa-btn pa-btn-icon" aria-label="Refresh" :disabled="!selectedDid || loading" @click="loadForAgent">
          <Icon name="mdi:refresh" :class="{ 'pa-spin': loading }" />
        </button>
      </div>
      <div v-if="pickerOpen" class="pa-pick-list" data-testid="pa-picker-list">
        <div v-if="pickerBusy" class="pa-pick-note">Searching…</div>
        <div v-else-if="pickerErr" class="pa-pick-note pa-pick-err">{{ pickerErr }} <button class="pa-pick-retry" @click="runPickerSearch">Retry</button></div>
        <template v-else>
          <button v-for="a in agents" :key="a.did" class="pa-pick-row" @click="pickAgent(a)">
            <span class="pa-pick-name">{{ a.name || a.did }}</span>
            <span v-if="a.balance != null" class="pa-pick-bal">{{ a.balance }}</span>
          </button>
          <div v-if="!agents.length" class="pa-pick-note">No agents match "{{ pickerQ }}".</div>
          <div v-else class="pa-pick-note">{{ pickerQ ? 'whole-fleet search' : 'top funded · type to search all' }}</div>
        </template>
      </div>
    </div>

    <!-- COCKPIT CARD confirmations (2026-07-25). The phone rail: the phone renders the
         exact facts and signs THEM. Hidden entirely when the registry runs LIABILITY_MODE=off. -->
    <section v-if="liabilityLive" class="pa-card pa-confirm" data-tour="pk-confirm">
      <h2><Icon name="mdi:cellphone-key" /> Confirmations <span class="pa-count">{{ challengeCount }}</span></h2>

      <div class="pa-keyrow">
        <div class="pa-keystate">
          <Icon :name="deviceKeyEnrolled ? 'mdi:shield-check' : 'mdi:shield-off-outline'"
                :class="deviceKeyEnrolled ? 'pa-ok' : 'pa-dim'" />
          <span v-if="deviceKeyEnrolled">This device holds a signing key — approvals are signed, not just tapped.</span>
          <span v-else-if="!keySupported">This browser can't hold a signing key. Confirmations fall back to a code.</span>
          <span v-else>No signing key on this device yet. Without one, a confirmation is only a tap.</span>
        </div>
        <button v-if="keySupported && !deviceKeyEnrolled" class="pa-btn pa-btn-primary"
                :disabled="enrolling" @click="enrolKey">
          <Icon name="mdi:fingerprint" /> {{ enrolling ? 'Enrolling…' : 'Enable fingerprint signing' }}
        </button>
        <button v-else-if="deviceKeyEnrolled" class="pa-btn" :disabled="enrolling" @click="revokeKey">
          <Icon name="mdi:key-remove" /> Revoke key
        </button>
      </div>


      <!-- §COCKPIT P5 — THE SHARED QUEUE. This view used to render confirms its own way:
           every pending row live at once, no ack, no presentation hash, no posture, and
           a deny with no reason. The desk rendered the same decisions differently. One
           implementation now serves both; what is genuinely per-surface — WHICH
           credential signs — is injected, because the phone signs with the Pocket
           biometric lock's key and the desk with its own. -->
      <DecisionQueue variant="phone" :sign-with="pocketSign" @count="n => challengeCount = n" />

      <p v-if="confirmMsg" class="pa-confirm-msg">{{ confirmMsg }}</p>
    </section>

    <!-- EMERGENCY — global freeze. Always visible, never gated: the one control you need
         when a device is lost is exactly the one you can't be asked to navigate to. -->
    <section class="pa-panic pa-global" data-tour="pk-panic">
      <p class="pa-panic-note"><Icon name="mdi:alert-octagon" /><span>Lost your phone? Rogue agent? Freeze <strong>all</strong> delegated authority — every capability permit and every delegation grant, on every agent you own.</span></p>
      <button class="pa-btn pa-btn-panic" :disabled="sweeping" @click="askGlobalPanic">
        <Icon :name="sweeping ? 'mdi:loading' : 'mdi:alert-octagon'" :class="{ 'pa-spin': sweeping }" />
        {{ sweeping ? (sweepProgress || 'Freezing…') : 'EMERGENCY — freeze all agents' }}
      </button>
    </section>

    <!-- nothing selected → guided empty state -->
    <div v-if="!selectedDid" class="pa-hero">
      <Icon name="mdi:shield-key" class="pa-hero-ico" />
      <h3>Pick an agent to review its authority</h3>
      <p>See every delegation grant and capability permit it holds — and kill any of them in one tap. Need the nuclear option? The red <strong>EMERGENCY</strong> card above works without selecting anything.</p>
    </div>

    <template v-else>
      <div v-if="mode" class="pa-mode">IRONKEY mode <span :class="['pa-badge', 'pa-' + mode]">{{ mode }}</span></div>

      <!-- §FESUITE (V0575): a failed read is not "No delegation grants on this agent", and never the previous agent's rows -->
      <section v-if="listsFailed && !loading" class="pa-card" data-testid="pa-lists-failed">
        <ReadFailedNotice dense :text="listsFailed" :retry="loadForAgent" />
      </section>
      <template v-else>
      <!-- L3 grants -->
      <section class="pa-card">
        <h2><Icon name="mdi:key-variant" /> Delegation grants <span class="pa-count">{{ grants.length }}</span></h2>
        <div v-if="loading" class="pa-list"><div v-for="n in 2" :key="n" class="pa-skel"></div></div>
        <ul v-else class="pa-list">
          <li v-for="g in grants" :key="g.id" class="pa-item">
            <div class="pa-item-body">
              <div class="pa-item-title">{{ g.principal }} <span v-if="g.revoked" class="pa-tag pa-tag-rev">revoked</span></div>
              <div class="pa-muted pa-perms">{{ g.permissions.join(', ') }}<span v-if="g.expires_at"> · exp {{ short(g.expires_at) }}</span></div>
            </div>
            <button v-if="!g.revoked" class="pa-btn pa-btn-icon pa-btn-danger" title="Revoke grant" aria-label="Revoke grant" @click="askRevokeGrant(g)"><Icon name="mdi:trash-can-outline" /></button>
          </li>
          <li v-if="!grants.length" class="pa-empty">No delegation grants on this agent.</li>
        </ul>
      </section>

      <!-- L4 capability permits -->
      <section class="pa-card">
        <h2><Icon name="mdi:key" /> Capability permits <span class="pa-count">{{ tokens.length }}</span></h2>
        <div v-if="loading" class="pa-list"><div v-for="n in 2" :key="n" class="pa-skel"></div></div>
        <ul v-else class="pa-list">
          <li v-for="t in tokens" :key="t.id" class="pa-item">
            <div class="pa-item-body">
              <div class="pa-item-title">
                #{{ t.id }} <span class="pa-tag">{{ t.role }}</span>
                <span class="pa-tag" :class="'pa-st-' + t.status">{{ t.status }}</span>
                <span v-if="t.depth" class="pa-muted pa-depth">depth {{ t.depth }}</span>
              </div>
              <div class="pa-muted pa-perms">
                {{ (t.permissions || []).join(', ') || 'no perms' }}
                <span v-if="t.budget_remaining != null"> · {{ t.budget_remaining }} {{ t.currency }} left</span>
              </div>
            </div>
            <button v-if="t.status === 'issued' || t.status === 'active'" class="pa-btn pa-btn-sm pa-btn-danger" title="Revoke permit + subtree" @click="askRevokeToken(t)">
              <Icon name="mdi:trash-can-outline" /> subtree
            </button>
          </li>
          <li v-if="!tokens.length" class="pa-empty">No capability permits on this agent.</li>
        </ul>
      </section>
      </template>

      <!-- phone sessions (computer-use) — #PK4: owners see their own agent's
           sessions via the agent-side rail; the scope is NAMED, never implied. -->
      <section class="pa-card" v-if="phoneEnabled || phoneNote">
        <h2><Icon name="mdi:monitor-cellphone" /> Phone sessions <span v-if="phoneScope" class="pa-count">{{ phoneSessions.length }}</span>
          <span v-if="phoneScope === 'owner'" class="pa-scope" data-testid="pa-phone-scope">this agent’s own view</span>
          <span v-else-if="phoneScope === 'admin'" class="pa-scope">admin oversight</span>
        </h2>
        <p v-if="phoneNote" class="pa-hint" data-testid="pa-phone-note">{{ phoneNote }}</p>
        <ul class="pa-list">
          <li v-for="p in phoneSessions" :key="p.id" class="pa-item" :class="{ 'pa-item-live': p.status === 'active' }">
            <div class="pa-item-body">
              <div class="pa-item-title">
                {{ p.current_app || 'phone' }}
                <span class="pa-tag" :class="p.status === 'active' ? 'pa-tag-live' : 'pa-tag-rev'">{{ p.status }}</span>
              </div>
              <div class="pa-muted">{{ p.actions_used }} actions · {{ Number(p.budget_spent) }} spent</div>
            </div>
            <button v-if="p.status === 'active'" class="pa-btn pa-btn-icon pa-btn-danger" title="Kill session" aria-label="Kill session" @click="askKillPhone(p)"><Icon name="mdi:phone-hangup" /></button>
          </li>
          <li v-if="!phoneSessions.length" class="pa-empty">No phone sessions for this agent.</li>
        </ul>
      </section>

      <!-- panic (scoped to the selected agent) -->
      <section class="pa-panic">
        <p class="pa-panic-note"><Icon name="mdi:alert-octagon" /><span>Kill every permit and grant on <strong>{{ selectedName }}</strong> only, in one action.</span></p>
        <button class="pa-btn pa-btn-panic" :disabled="panicking || (!grants.length && !liveTokenCount)" @click="askPanic">
          <Icon :name="panicking ? 'mdi:loading' : 'mdi:alert-octagon'" :class="{ 'pa-spin': panicking }" /> {{ panicking ? 'Revoking…' : 'PANIC — revoke this agent' }}
        </button>
      </section>
    </template>

    <transition name="pa-fade"><p v-if="msg" class="pa-msg"><Icon name="mdi:check-circle" /> {{ msg }}</p></transition>
    <transition name="pa-fade"><p v-if="err" class="pa-err"><Icon name="mdi:alert-octagon" /> {{ err }}</p></transition>

    <!-- confirmations -->
    <ConfirmActionModal
      :show="!!grantTarget" title="Revoke delegation grant?"
      :message="grantTarget ? `Revoke <strong>${escapeHtml(grantTarget.principal)}</strong>'s grant of ${grantTarget.permissions.length} permission(s)? The agent loses this delegated authority immediately.` : ''"
      tone="danger" confirmText="Revoke grant" busyText="Revoking…" :busy="acting"
      @confirm="doRevokeGrant" @close="grantTarget = null" />

    <ConfirmActionModal
      :show="!!tokenTarget" title="Revoke capability permit + subtree?"
      :message="tokenTarget ? `Revoke token <strong>#${tokenTarget.id}</strong> and every token derived from it. This cascades — child tokens die too. Irreversible.` : ''"
      tone="danger" confirmText="Revoke subtree" busyText="Revoking…" :busy="acting"
      @confirm="doRevokeToken" @close="tokenTarget = null" />

    <!-- §COCKPITDESK (2026-10-15): no count here. It printed the picker's page (top 30, or 0 before the picker opened)
         as "all N agent(s) you own" while the sweep pages through the whole fleet (4,130 on one account); the sweep
         lists them first and its result says how many it checked. -->
    <ConfirmActionModal
      :show="globalConfirm" title="EMERGENCY — freeze ALL agents?"
      :message="`This revokes <strong>every live capability permit and delegation grant</strong> on <strong>every agent you own</strong>. Agents keep running but lose ALL delegated authority instantly. There is no undo.`"
      tone="danger" :requiredMatch="'REVOKE'" reasonPlaceholder="Type REVOKE to confirm"
      confirmText="Freeze everything" busyText="Freezing…" :busy="sweeping"
      warningTitle="⚠ Irreversible" :warning="'Every agent you own is swept. Re-issue grants and tokens afterwards as needed.'"
      @confirm="doGlobalPanic" @close="globalConfirm = false" />

    <ConfirmActionModal
      :show="panicConfirm" title="PANIC — revoke ALL authority?"
      :message="`This revokes <strong>every</strong> live capability permit AND delegation grant on <strong>${escapeHtml(selectedName)}</strong>. Use it if this agent or a device is compromised. There is no undo.`"
      tone="danger" :requiredMatch="'REVOKE'" reasonPlaceholder="Type REVOKE to confirm"
      confirmText="Revoke everything" busyText="Revoking…" :busy="panicking"
      warningTitle="⚠ Irreversible" :warning="`${liveTokenCount} permit(s) + ${grants.filter(g => !g.revoked).length} grant(s) will be revoked.`"
      @confirm="doPanic" @close="panicConfirm = false" />

    <ConfirmActionModal
      :show="!!phoneKillTarget" title="Kill phone session?"
      :message="phoneKillTarget ? `End this agent's phone session (<strong>${escapeHtml(phoneKillTarget.current_app || 'phone')}</strong>) immediately and release the device. The agent's next action is refused.` : ''"
      tone="danger" confirmText="Kill session" busyText="Killing…" :busy="acting"
      @confirm="doKillPhone" @close="phoneKillTarget = null" />
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { failedForWantOfAnAnswer } from '@/services/api/peerDirect'
import { useAuthStore } from '@/stores/auth'
import { agentApi } from '@/services/api/agents'
import { agentDelegationApi, type DelegationGrant, type CapabilityToken } from '@/services/api/agentDelegation'
import { phoneFabricApi, type PhoneSession } from '@/services/api/phoneFabric'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { loadRegistryConfig } from '@/composables/useRegistryConfig'
import { usePocketLock, pocketCredentialId } from '@/composables/usePocketLock'
import { liabilityApi } from '@/services/api/liability'
import { devicePushApi } from '@/services/api/devicePush'
import { useDeviceSigner } from '@/composables/useDeviceSigner'
import DecisionQueue from '@/components/cockpit/DecisionQueue.vue'

const lock = usePocketLock()

// ── COCKPIT CARD confirmations ────────────────────────────────────────────────────────────
const signer = useDeviceSigner()
const keySupported = signer.supported
const liabilityLive = ref(false)        // false when the registry runs LIABILITY_MODE=off (404)
const challengeCount = ref(0)   // reported by the shared queue, for the header count
const deviceKeyEnrolled = ref(false)
const pushDeviceId = ref<number | null>(null)
const enrolling = ref(false)
const confirmMsg = ref('')

async function loadConfirmations() {
  try {
    // The pending call is kept for its ANSWER, not its rows: a 404 here is how this view
    // learns the registry runs LIABILITY_MODE=off, and any other failure is an outage.
    // The rows themselves belong to DecisionQueue.
    const [, devices] = await Promise.all([
      liabilityApi.pendingChallenges(),
      devicePushApi.listMine().catch(() => ({ devices: [], total: 0 })),
    ])
    liabilityLive.value = true
    pushDeviceId.value = devices.devices?.[0]?.id ?? null
    // enrolment lives on the SERVER now (the credential is in the phone's keystore, not ours)
    // Enrolment is a property of THIS DEVICE, not of the account. Reading it from the server's
    // device list made a second phone believe it was already enrolled, hide the enrol button, and
    // then fail to sign with a credential it never had. The local credential is the one that signs.
    deviceKeyEnrolled.value = !!pocketCredentialId()
  } catch (e: any) {
    // 404 = the feature is dark on this registry; stay quiet rather than showing a broken panel.
    if (e?.response?.status === 404) { liabilityLive.value = false; return }
    // §POCKETBRIDGE2 W1: any OTHER failure is an outage, not darkness — say so
    // instead of silently freezing the panel on stale rows.
    confirmMsg.value = 'Could not load confirmations: ' + (e?.response?.data?.detail || e?.message || 'request failed')
  }
}

async function enrolKey() {
  // Deliberately NOT gated on a push-device row. The unified endpoint creates its own row when
  // there is none, and gating here meant a browser that had not (or could not) subscribe to push
  // was silently unable to enrol a signing key at all — the click just did nothing.
  enrolling.value = true
  confirmMsg.value = ''
  try {
    if (!(await signer.platformAvailable())) {
      confirmMsg.value = 'This device has no fingerprint or screen lock available for signing.'
      return
    }
    // Reuse the EXISTING Pocket biometric lock. It creates the credential, stores it locally and
    // now registers it server-side, so the phone ends up with ONE credential doing everything.
    // Minting a second one here is what produced two prompts and the stray passkey picker.
    const ok = await lock.enroll()
    if (!ok) { confirmMsg.value = 'Biometric enrolment was cancelled.'; return }
    await loadConfirmations()
    confirmMsg.value = deviceKeyEnrolled.value
      ? 'Biometric signing enrolled. Confirmations now require your fingerprint.'
      : 'Enrolled on this device, but the registry did not record it — try again.'
  } catch (e: any) {
    confirmMsg.value = e?.message || 'Could not enrol biometric signing.'
  } finally { enrolling.value = false }
}

async function revokeKey() {
  enrolling.value = true
  try {
    // Revoke the row holding THIS device's credential, not whichever row happens to be first —
    // that would disarm another phone and leave this one signing. A list that could not be read
    // is a failure to report (below), never "No signing key registered for this device" (§FESUITE, V0575).
    const devs = await devicePushApi.listMine()
    const mine = (devs.devices || []).find((d: any) => d.webauthn_credential_id === pocketCredentialId())
    const target = mine?.id ?? pushDeviceId.value
    if (!target) { confirmMsg.value = 'No signing key registered for this device.'; return }
    await liabilityApi.revokeDeviceKey(target)
    // #PK32 — disable() refuses while the credential vault is sealed under this
    // fingerprint key (dropping the lock then would strand the vault's only key).
    const off = lock.disable()
    deviceKeyEnrolled.value = false
    confirmMsg.value = off.ok
      ? 'Key revoked. Confirmations fall back to a code.'
      : `Key revoked server-side. ${off.reason}`
  } catch (e: any) {
    confirmMsg.value = e?.response?.data?.detail || 'Could not revoke the key.'
  } finally { enrolling.value = false }
}

/** §COCKPIT P5 — the phone's HALF of consent: find THIS device's credential and sign.
 *  Everything after the signature — the POST, the read floor, the refusal bodies, the
 *  deny taxonomy — belongs to DecisionQueue, which does it identically on both
 *  surfaces. Returning null means "this device cannot sign right now", a state the
 *  queue renders; it is not an error to throw at a human mid-decision. */
async function pocketSign(challengeHashHex: string) {
  // a device list that could not be read throws to the queue, which reports it: null would read as "this device
  // holds no key" and ask for a code instead of the signature it can give (§FESUITE, V0575)
  const devs = await devicePushApi.listMine()
  // Match on THIS device's credential. Picking the account's first enrolled device asks
  // the browser to sign with a key another phone holds — which fails, or opens the
  // passkey picker.
  const local = pocketCredentialId()
  const signerDev = (devs.devices || []).find(
    (d: any) => local && d.webauthn_credential_id === local && d.webauthn_enrolled)
  if (!signerDev) return null
  const a = await signer.sign(challengeHashHex, (signerDev as any).webauthn_credential_id)
  return { device_id: signerDev.id, ...a }
}

const agents = ref<{ did: string; name?: string; balance?: string | null }[]>([])
// #PK4 — the shared agent-context brain mints the selected agent's JWT for the
// owner phone-session rail (and knows the sealed-vault distinction).
const { ensureAgentFor } = usePocketAgent()
const selectedDid = ref('')
const grants = ref<DelegationGrant[]>([])
const tokens = ref<CapabilityToken[]>([])
const mode = ref('')
const loading = ref(false)
const acting = ref(false)
const panicking = ref(false)
const msg = ref('')
const err = ref('')
const listsFailed = ref('')   // the sentence shown instead of the grant and token lists when their read failed

const grantTarget = ref<DelegationGrant | null>(null)
const tokenTarget = ref<CapabilityToken | null>(null)
const panicConfirm = ref(false)

// EMERGENCY — global freeze across ALL owned agents (works with nothing selected)
const route = useRoute()
const router = useRouter()
const globalConfirm = ref(false)
const sweeping = ref(false)
const sweepProgress = ref('')

// PHONE FABRIC — this agent's phone sessions (admin oversight; graceful-empty if disabled/non-admin)
const phoneEnabled = ref(false)
const phoneSessions = ref<PhoneSession[]>([])
const phoneKillTarget = ref<PhoneSession | null>(null)

const selectedName = computed(() => agents.value.find((a) => a.did === selectedDid.value)?.name || selectedDid.value)
const liveTokenCount = computed(() => tokens.value.filter((t) => t.status === 'issued' || t.status === 'active').length)

const short = (s: string) => { try { return new Date(s).toLocaleDateString(appLocale()) } catch { return s } }
const escapeHtml = (s: string) => (s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] as string))
const flash = (m: string) => { msg.value = m; setTimeout(() => { if (msg.value === m) msg.value = '' }, 4000) }

/* §POCKETBRIDGE2 P0.1 — server-ranked, server-searched picker (whole fleet). */
const pickerQ = ref('')
const pickerOpen = ref(false)
const pickerBusy = ref(false)
const pickerErr = ref('')
let pickerTimer: ReturnType<typeof setTimeout> | null = null

async function loadAgents() {
  await runPickerSearch()
}

async function runPickerSearch() {
  pickerBusy.value = true; pickerErr.value = ''
  try {
    const q = pickerQ.value.trim()
    const res: any = await agentApi.getMyAgents({ limit: 30, sort: 'balance', ...(q ? { q } : {}) })
    const list = Array.isArray(res) ? res : res?.items || res?.data || []
    agents.value = list.map((a: any) => ({
      did: a.did || a.agent_did,
      name: a.name || a.agent_card_name,
      balance: a.liquid_balance != null ? Number(a.liquid_balance).toLocaleString(appLocale(), { maximumFractionDigits: 0 }) : null,
    }))
  } catch (e: any) {
    // S2: an error is an error, never an empty roster.
    pickerErr.value = e?.response?.data?.detail || e?.message || 'Could not load your agents'
  } finally { pickerBusy.value = false }
}

function openPicker() { pickerOpen.value = true; if (!agents.value.length && !pickerBusy.value) runPickerSearch() }
function onPickerInput() {
  pickerOpen.value = true
  if (pickerTimer) clearTimeout(pickerTimer)
  pickerTimer = setTimeout(runPickerSearch, 250)
}
function pickAgent(a: { did: string; name?: string }) {
  selectedDid.value = a.did
  if (!agents.value.some((x) => x.did === a.did)) agents.value.unshift(a as any)
  pickerOpen.value = false
  pickerQ.value = ''
  loadForAgent()
}

// §COCKPITDESK (2026-10-15): the latest pick owns the screen. An agent's lists still in flight when another agent is
// picked are dropped on arrival: they had landed under the later agent's name, where a revoke takes the earlier agent's
// grant or token by its id.
let loadSeq = 0
async function loadForAgent() {
  if (!selectedDid.value) return
  const did = selectedDid.value
  const seq = ++loadSeq
  loading.value = true; err.value = ''; listsFailed.value = ''
  try {
    const [g, c] = await Promise.all([
      agentDelegationApi.listGrants(did),
      agentDelegationApi.listCapabilities(did),
    ])
    if (seq !== loadSeq) return
    grants.value = g.grants || []
    tokens.value = c.tokens || []
    mode.value = c.mode || ''
  } catch (e: any) {
    if (seq !== loadSeq) return
    // §FESUITE (V0575): the lists are emptied (the previous agent's rows must not stand under this one's name) and the
    // page says the read failed, never "No delegation grants on this agent"; a refusal says the server's reason
    grants.value = []; tokens.value = []; mode.value = ''
    const detail = e?.response?.data?.detail
    listsFailed.value = (!failedForWantOfAnAnswer(e) && typeof detail === 'string' && detail)
      || 'This agent’s grants and permits could not be read just now.'
  } finally {
    if (seq === loadSeq) loading.value = false
  }
  if (seq === loadSeq) loadPhoneSessions()
}

// PHONE FABRIC — §POCKETBRIDGE #PK4 (D8 ratified, closes F5): admins read the
// oversight list; everyone else reads the agent-side `/phone/sessions/mine`
// rail AS the selected agent — scoped by construction, no filter. Before this,
// a non-admin owner silently saw an empty section while their agent drove a
// phone: the admin call failed, the catch hid everything, and "no sessions"
// and "not allowed to look" were the same pixels (the §STAKEDFIX class).
const phoneScope = ref<'admin' | 'owner' | ''>('')
const phoneNote = ref('')
const authStore = useAuthStore()
async function loadPhoneSessions() {
  // the same rule as the lists: an answer for an agent no longer picked is dropped
  const seq = loadSeq, did = selectedDid.value
  const stale = () => seq !== loadSeq || did !== selectedDid.value
  phoneNote.value = ''
  // §FESUITE V0578: the admin rail is an admin's question. A developer who is not an admin asked it on every visit (a
  // 403 each time) before the owner rail, and an admin whose read got no answer fell to the owner rail as if refused,
  // so "could not be read" never showed for an admin.
  if (authStore.isAdmin) {
    try {
      const r = await phoneFabricApi.sessions()
      if (stale()) return
      phoneEnabled.value = !!r.enabled
      phoneSessions.value = (r.sessions || []).filter((s) => s.agent_did === did).slice(0, 20)
      phoneScope.value = 'admin'
      return
    } catch (e: any) {
      if (stale()) return
      if (failedForWantOfAnAnswer(e)) {
        phoneEnabled.value = false; phoneSessions.value = []; phoneScope.value = ''
        phoneNote.value = 'Phone sessions could not be read just now. Refresh to try again.'
        return
      }
      /* refused (an admin without the flag, or the admin rail dark): the owner rail below */
    }
  }
  try {
    // D6-841 (agentvault2-5b, 2026-10-25): the owner rail answers 503 where the Phone Fabric is off. Asked only once an
    // owned agent could act here (V0641: through the session), it went out on every visit to a registry without the
    // fabric. Now asked only where the registry says the fabric is on; one that says nothing is asked, as before.
    const cfg = await loadRegistryConfig().catch(() => ({} as Record<string, unknown>))
    if (stale()) return
    if ((cfg as Record<string, unknown>).phone_fabric_enabled === false) {
      phoneEnabled.value = false; phoneSessions.value = []; phoneScope.value = ''
      return
    }
    const held = !!did && await ensureAgentFor(did)
    if (stale()) return
    if (!held) {
      // The owner rail needs this agent's stored credentials to mint its JWT.
      phoneEnabled.value = false; phoneSessions.value = []; phoneScope.value = ''
      phoneNote.value = did
        ? 'Phone sessions are read with this agent’s own credentials — add them via the agent switcher to see its sessions here.'
        : ''
      return
    }
    const r = await phoneFabricApi.mySessions()
    if (stale()) return
    phoneEnabled.value = true
    phoneScope.value = 'owner'
    phoneSessions.value = (r.sessions || []).slice(0, 20)
      .map((s: any) => ({ ...s, agent_did: did }))
  } catch (e: any) {
    if (stale()) return
    // Phone fabric disabled on this registry (or the rail refused) — hidden, as before.
    phoneEnabled.value = false; phoneSessions.value = []; phoneScope.value = ''
    // §FESUITE (V0575): a read that got no answer is not a dark fabric; hiding the section would read as "no phone is
    // driving this agent"
    if (failedForWantOfAnAnswer(e)) phoneNote.value = 'Phone sessions could not be read just now. Refresh to try again.'
  }
}
function askKillPhone(p: PhoneSession) { phoneKillTarget.value = p; err.value = '' }
async function doKillPhone() {
  if (!phoneKillTarget.value) return
  acting.value = true
  try {
    // #PK4 — same act, matching rail: admins use the oversight kill, owners end
    // their own agent's session on the agent-side rail.
    if (phoneScope.value === 'owner') await phoneFabricApi.endMine(phoneKillTarget.value.id)
    else await phoneFabricApi.kill(phoneKillTarget.value.id)
    flash('Phone session killed.'); phoneKillTarget.value = null; await loadPhoneSessions()
  }
  catch (e: any) { err.value = e?.response?.data?.detail || e?.message || 'Kill failed' }
  finally { acting.value = false }
}

function askRevokeGrant(g: DelegationGrant) { grantTarget.value = g; err.value = '' }
async function doRevokeGrant() {
  if (!grantTarget.value) return
  acting.value = true
  try { await agentDelegationApi.revokeGrant(grantTarget.value.id); flash(`Grant ${grantTarget.value.id} revoked.`); grantTarget.value = null; await loadForAgent() }
  catch (e: any) { err.value = e?.response?.data?.detail || e?.message || 'Revoke failed' }
  finally { acting.value = false }
}

function askRevokeToken(t: CapabilityToken) { tokenTarget.value = t; err.value = '' }
async function doRevokeToken() {
  if (!tokenTarget.value) return
  acting.value = true
  try {
    const r = await agentDelegationApi.revokeCapability(selectedDid.value, tokenTarget.value.id)
    flash(`Permit #${tokenTarget.value.id} + subtree revoked (${r?.revoked_count ?? '?'} permits).`)
    tokenTarget.value = null; await loadForAgent()
  } catch (e: any) { err.value = e?.response?.data?.detail || e?.message || 'Revoke failed' }
  finally { acting.value = false }
}

function askPanic() { panicConfirm.value = true; err.value = '' }
async function doPanic() {
  if (!selectedDid.value) return
  // biometric confirmation for the nuclear action (only the phone owner can PANIC)
  if (lock.enabled.value) {
    const okBio = await lock.verify()
    if (!okBio) { err.value = 'Biometric confirmation failed — nothing revoked.'; panicConfirm.value = false; return }
  }
  panicking.value = true; err.value = ''
  try {
    // §POCKETBRIDGE2 W1.9 — failures are COUNTED and REPORTED. "Panic complete"
    // while tokens stayed live was a false all-clear on the one control that
    // must never lie.
    const live = tokens.value.filter((t) => t.status === 'issued' || t.status === 'active')
    let total = 0, failed = 0
    for (const t of live) {
      try { const r = await agentDelegationApi.revokeCapability(selectedDid.value, t.id); total += r?.revoked_count ?? 1 } catch { failed++ }
    }
    const liveGrants = grants.value.filter((x) => !x.revoked)
    let grOk = 0
    for (const g of liveGrants) { try { await agentDelegationApi.revokeGrant(g.id); grOk++ } catch { failed++ } }
    panicConfirm.value = false
    if (failed) {
      err.value = `Panic INCOMPLETE — ${total} permit(s) + ${grOk} grant(s) revoked, but ${failed} revocation(s) FAILED and may still be live. Retry panic.`
    } else {
      flash(`Panic complete — ${total} capability permit(s) + ${grOk} grant(s) revoked.`)
    }
    await loadForAgent()
  } finally {
    panicking.value = false
  }
}

function askGlobalPanic() { globalConfirm.value = true; err.value = '' }
async function doGlobalPanic() {
  // biometric confirmation for the nuclear action (only the phone owner can freeze)
  if (lock.enabled.value) {
    const okBio = await lock.verify()
    if (!okBio) { err.value = 'Biometric confirmation failed — nothing revoked.'; globalConfirm.value = false; return }
  }
  sweeping.value = true; err.value = ''
  let tok = 0, gr = 0, touched = 0, revokeFails = 0, unreadable = 0
  try {
    // §POCKETBRIDGE2 W1.9 — "freeze ALL agents" must mean ALL: the sweep
    // enumerates the WHOLE fleet by pagination (the picker list is a top-30
    // page and the old code silently swept only what was loaded), and every
    // failure is counted and reported instead of swallowed.
    sweepProgress.value = 'Listing your agents…'
    let roster: { did: string }[] = []
    try {
      let offset = 0
      for (;;) {
        const res: any = await agentApi.getMyAgents({ limit: 500, offset })
        const list = Array.isArray(res) ? res : res?.items || res?.data || []
        roster.push(...list.map((a: any) => ({ did: a.did || a.agent_did })))
        if (list.length < 500 || roster.length >= 20000) break
        offset += 500
      }
    } catch (e: any) {
      err.value = 'Could not list your agents — NOTHING was frozen. ' + (e?.response?.data?.detail || e?.message || '')
      globalConfirm.value = false
      return
    }
    for (let i = 0; i < roster.length; i++) {
      const a = roster[i]
      sweepProgress.value = `Sweeping ${i + 1}/${roster.length}…`
      try {
        const [g, c] = await Promise.all([
          agentDelegationApi.listGrants(a.did),
          agentDelegationApi.listCapabilities(a.did),
        ])
        const liveT = (c.tokens || []).filter((t) => t.status === 'issued' || t.status === 'active')
        const liveG = (g.grants || []).filter((x) => !x.revoked)
        if (liveT.length || liveG.length) touched++
        for (const t of liveT) { try { const r = await agentDelegationApi.revokeCapability(a.did, t.id); tok += r?.revoked_count ?? 1 } catch { revokeFails++ } }
        for (const x of liveG) { try { await agentDelegationApi.revokeGrant(x.id); gr++ } catch { revokeFails++ } }
      } catch { unreadable++ /* keep sweeping — one broken agent must not stop the freeze, but it IS counted */ }
    }
    globalConfirm.value = false
    if (revokeFails || unreadable) {
      err.value = `Freeze INCOMPLETE — ${tok} permit(s) + ${gr} grant(s) revoked across ${roster.length} agent(s), but `
        + [revokeFails ? `${revokeFails} revocation(s) FAILED` : '', unreadable ? `${unreadable} agent(s) could not be checked` : '']
          .filter(Boolean).join(' and ')
        + '. Authority may still be live there — retry the freeze.'
    } else {
      flash(tok + gr
        ? `Emergency freeze complete — ${tok} permit(s) + ${gr} grant(s) revoked across ${touched} of ${roster.length} agent(s).`
        : `Emergency sweep complete — checked ${roster.length} agent(s); nothing was live.`)
    }
    if (selectedDid.value) await loadForAgent()
  } finally {
    sweeping.value = false; sweepProgress.value = ''
  }
}

// /pocket/approvals?panic=1 — the More-tab Emergency row lands here armed.
// Watched (not just mounted): a query-only navigation reuses the component.
function armFromQuery() {
  if (route.query.panic) {
    router.replace({ query: {} })
    globalConfirm.value = true; err.value = ''
  }
}
watch(() => route.query.panic, () => armFromQuery())

onMounted(async () => {
  loadConfirmations()   // COCKPIT CARD: quiet no-op when the registry runs the feature dark
  await loadAgents()
  armFromQuery()
})
</script>

<style scoped>
.pa-wrap { max-width: 720px; margin: 0 auto; padding: 1rem; display: flex; flex-direction: column; gap: 0.85rem; box-sizing: border-box; width: 100%; }
.pa-wrap * { box-sizing: border-box; }
.pa-head { display: flex; gap: 0.8rem; align-items: center; }
.pa-head-badge { width: 2.6rem; height: 2.6rem; border-radius: 12px; display: grid; place-items: center; flex: 0 0 auto;
  background: linear-gradient(135deg, rgba(16,185,129,0.2), rgba(16,185,129,0.05)); border: 1px solid rgba(16,185,129,0.3); }
.pa-head-badge :deep(svg) { width: 1.5rem; height: 1.5rem; color: #34d399; }
.pa-head-txt { min-width: 0; }
.pa-head h1 { font-size: 1.35rem; margin: 0; }
.pa-head p { margin: 0.15rem 0 0; opacity: 0.7; font-size: 0.85rem; }
.pa-picker { display: flex; gap: 0.5rem; align-items: stretch; }
.pa-pick-box { display: flex; align-items: center; gap: 0.5rem; flex: 1 1 auto; min-width: 0;
  background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.12); border-radius: 12px; padding: 0.2rem 0.3rem 0.2rem 0.7rem; }
.pa-pick-ico { width: 1.05rem; height: 1.05rem; opacity: 0.5; flex: 0 0 auto; }
.pa-pick-in { flex: 1 1 auto; min-width: 0; background: none; border: none; color: inherit;
  font-size: 16px; min-height: 44px; outline: none; }
.pa-pick-in::placeholder { color: rgba(230,237,243,0.55); }
.pa-pick-list { margin-top: 0.4rem; background: rgba(9,12,17,0.97); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 12px; max-height: 46vh; overflow-y: auto; }
.pa-pick-row { display: flex; align-items: center; justify-content: space-between; gap: 0.6rem; width: 100%;
  background: none; border: none; border-bottom: 1px solid rgba(255,255,255,0.05); color: inherit; text-align: left;
  padding: 0 0.85rem; min-height: 48px; font-size: 0.9rem; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pa-pick-row:active { background: rgba(255,255,255,0.06); }
.pa-pick-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pa-pick-bal { font-variant-numeric: tabular-nums; opacity: 0.55; font-size: 0.8rem; flex: 0 0 auto; }
.pa-pick-note { padding: 0.55rem 0.85rem; font-size: 0.74rem; opacity: 0.55; }
.pa-pick-err { color: #ff9a9a; opacity: 0.9; }
.pa-pick-retry { background: none; border: 1px solid rgba(255,255,255,0.2); border-radius: 8px; color: inherit;
  padding: 0.25rem 0.6rem; margin-left: 0.4rem; min-height: 32px; cursor: pointer; }
.pa-select:focus { outline: none; border-color: #34d399; }
.pa-hero { text-align: center; padding: 2.4rem 1.2rem; opacity: 0.8; display: flex; flex-direction: column; align-items: center; gap: 0.5rem; }
.pa-hero-ico { width: 2.6rem; height: 2.6rem; color: #34d399; opacity: 0.6; }
.pa-hero h3 { margin: 0.3rem 0 0; font-size: 1rem; }
.pa-hero p { margin: 0; font-size: 0.85rem; opacity: 0.7; max-width: 30rem; line-height: 1.5; }
.pa-mode { font-size: 0.78rem; opacity: 0.8; display: flex; align-items: center; gap: 0.4rem; }
.pa-badge { padding: 0.06rem 0.45rem; border-radius: 5px; text-transform: uppercase; font-size: 0.65rem; letter-spacing: 0.05em; }
.pa-enforce { background: rgba(16,185,129,0.2); color: #34d399; }
.pa-shadow { background: rgba(245,158,11,0.2); color: #fbbf24; }
.pa-off { background: rgba(255,255,255,0.1); }
.pa-card { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 1.1rem; }
.pa-card h2 { font-size: 1rem; margin: 0 0 0.6rem; display: flex; align-items: center; gap: 0.4rem; }
.pa-card h2 :deep(svg) { width: 1.1rem; height: 1.1rem; color: #34d399; }
.pa-count { margin-left: auto; font-size: 0.72rem; background: rgba(255,255,255,0.08); border-radius: 20px; padding: 0.1rem 0.5rem; opacity: 0.75; }
.pa-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.45rem; }
.pa-item { display: flex; align-items: center; gap: 0.6rem; background: rgba(0,0,0,0.2); border: 1px solid rgba(255,255,255,0.05); border-radius: 11px; padding: 0.6rem 0.7rem; }
.pa-item-body { flex: 1 1 auto; min-width: 0; }
.pa-item-title { font-size: 0.88rem; display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap; }
.pa-muted { opacity: 0.65; font-size: 0.8rem; }
.pa-perms { margin-top: 0.2rem; word-break: break-word; }
.pa-depth { font-size: 0.72rem; }
.pa-tag { font-size: 0.62rem; text-transform: uppercase; letter-spacing: 0.04em; background: rgba(255,255,255,0.1); padding: 0.06rem 0.4rem; border-radius: 5px; }
.pa-tag-rev { background: rgba(255,107,107,0.2); color: #ff9b9b; }
.pa-tag-live { background: rgba(16,185,129,0.2); color: #34d399; }
.pa-item-live { border-left: 3px solid #34d399; }
.pa-st-active, .pa-st-issued { background: rgba(16,185,129,0.2); color: #34d399; }
.pa-st-revoked, .pa-st-expired, .pa-st-exhausted { background: rgba(255,107,107,0.15); color: #ff9b9b; }
.pa-btn { display: inline-flex; align-items: center; justify-content: center; gap: 0.3rem; background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.14); border-radius: 10px; padding: 0.55rem 0.75rem; min-height: 44px; color: inherit; font-size: 0.82rem; cursor: pointer; transition: background 0.15s; white-space: nowrap; }
.pa-btn:hover:not(:disabled) { background: rgba(255,255,255,0.12); }
.pa-btn :deep(svg) { width: 0.95rem; height: 0.95rem; }
.pa-btn-icon { flex: 0 0 auto; padding: 0.55rem; min-width: 44px; }
.pa-btn-sm { flex: 0 0 auto; padding: 0.4rem 0.6rem; font-size: 0.76rem; min-height: 44px; }
.pa-btn-danger { color: #ff6b6b; border-color: rgba(255,107,107,0.3); }
.pa-btn:disabled { opacity: 0.5; cursor: default; }
.pa-panic { border: 1px solid rgba(255,107,107,0.3); background: rgba(255,107,107,0.06); border-radius: 16px; padding: 1.1rem; }
.pa-global { border-color: rgba(255,77,77,0.45); background: linear-gradient(180deg, rgba(255,77,77,0.1), rgba(255,77,77,0.04)); }
.pa-panic-note { display: flex; align-items: center; gap: 0.4rem; font-size: 0.82rem; opacity: 0.85; margin: 0 0 0.7rem; }
.pa-panic-note :deep(svg) { width: 1rem; height: 1rem; color: #ff6b6b; flex: 0 0 auto; }
.pa-btn-panic { width: 100%; background: #dc2626; color: #fff; border: none; font-weight: 700; padding: 0.75rem; font-size: 0.95rem; letter-spacing: 0.02em; }
.pa-btn-panic:hover:not(:disabled) { background: #b91c1c; }  /* §FESUITE: white on the fill 4.83:1, 6.47:1 on hover (#ff4d4d was 3.27:1, #ff3333 3.64:1) */
.pa-spin { animation: pa-rot 0.9s linear infinite; }
@keyframes pa-rot { to { transform: rotate(360deg); } }
.pa-skel { height: 3rem; border-radius: 11px; background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.12), rgba(255,255,255,0.05)); background-size: 200% 100%; animation: pa-shim 1.3s ease-in-out infinite; }
@keyframes pa-shim { to { background-position: -200% 0; } }
.pa-msg { color: #34d399; font-size: 0.85rem; display: flex; align-items: center; gap: 0.4rem; }
.pa-err { color: #ff6b6b; font-size: 0.85rem; display: flex; align-items: center; gap: 0.4rem; }
.pa-msg :deep(svg), .pa-err :deep(svg) { width: 1rem; height: 1rem; flex: 0 0 auto; }
.pa-fade-enter-active, .pa-fade-leave-active { transition: opacity 0.2s ease; }
.pa-fade-enter-from, .pa-fade-leave-to { opacity: 0; }

/* COCKPIT CARD confirmations */
.pa-confirm .pa-keyrow { display:flex; align-items:center; gap:.75rem; flex-wrap:wrap;
  padding:.6rem .75rem; border:1px solid var(--pa-border,#334); border-radius:8px; margin-bottom:.75rem; }
.pa-confirm .pa-keystate { display:flex; align-items:center; gap:.5rem; flex:1; min-width:220px; font-size:.85rem; }
.pa-confirm .pa-ok { color:#34d399; }
.pa-confirm .pa-dim { opacity:.5; }
.pa-confirm .pa-hint { font-size:.75rem; opacity:.6; margin:-.4rem 0 .75rem; }
.pa-scope { font-size:.62rem; font-weight:600; letter-spacing:.06em; opacity:.55; margin-left:.45rem; text-transform:uppercase; }
.pa-card .pa-hint { font-size:.75rem; opacity:.6; margin:.1rem 0 .6rem; }
.pa-confirm .pa-empty { font-size:.85rem; opacity:.6; padding:.5rem 0; }
/* §COCKPIT P5 — .pa-chal* / .pa-facts / .pa-code went with the markup they styled.
   Rules that outlive their template are the §ROOMVIEW class inverted: not a class
   with no rule, but a rule reachable by nothing, quietly claiming to be doing work. */
.pa-confirm-msg { font-size:.8rem; opacity:.8; margin-top:.5rem; }
</style>
