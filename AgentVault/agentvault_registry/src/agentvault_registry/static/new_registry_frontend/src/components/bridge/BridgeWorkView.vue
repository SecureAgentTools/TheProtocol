<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * BridgeWorkView.vue — §BRIDGE R12
 *
 * "can you also build contracts quick view modals maybe settlements and guild
 *  work of your agents or what. this would be awesome." — Commander, 2026-08-20
 *
 * ONE modal, three tabs, all of it about the agent you are ACTING AS. Nothing
 * here is a second copy of a view: every list comes off the same rail the full
 * page uses, every row opens the real detail on the same rail, and every tab
 * keeps a FULL VIEW link for everything a quick view should not carry.
 * (§BRIDGE R3, his rule: dock things in view on EXISTING rails; a door onto a
 * wall is worse than no door.)
 *
 * WHAT EACH TAB CAN HONESTLY SHOW
 *
 *  CONTRACTS  `GET /contracts/v2/mine` — agent-JWT, so it is scoped to the
 *             ACTING agent by construction, not by a filter I wrote.
 *  GUILD      `GET /guild/mine` + `GET /guild/my-credentials` — same.
 *  DISPUTES   `GET /disputes/agent/{did}` is agent-scoped and open to the
 *             owner. **SETTLEMENTS ARE NOT**: `GET /federation/disputes/
 *             settlements` requires the `admin_enforcement` flag (verified in
 *             `routers/federation_disputes.py:773`). So the settlement half
 *             appears only for someone who can actually read it, and the panel
 *             SAYS which half you are looking at rather than implying that an
 *             empty list means nothing happened. Same discipline as the
 *             ledger's admin-gated FORENSICS door.
 *
 * WITHOUT AN ACTING AGENT there is nothing honest to show: these rails answer
 * "what is THIS agent doing", and an empty list would read as "you have none".
 * So the modal asks for an agent instead of rendering a lie.
 */
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { contractsV2Api, type ContractV2 } from '@/services/api/contractsV2'
import ReplicaContractDoor from '@/components/contracts/ReplicaContractDoor.vue'
import { guildApi, type GuildOrder } from '@/services/api/guild'
import { actionsFor, type GuildActionOffer } from '@/services/guildActions'
// §POCKETI18N — ONE label brain with PocketEarn (guildActions stays pure).
import { useGuildLabels } from '@/composables/useGuildLabels'
import { disputesApi } from '@/services/api/disputes'
import { settlementsApi, type Settlement } from '@/services/api/settlements'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

/* §POCKETBRIDGE5 A' — the modal can be OPENED ONTO a lane and a specific row
 * (NEEDS YOU dispute rows, ?dispute= deep links). No new surface, no new
 * button: the existing door learns to land where the attention came from. */
const props = defineProps<{ show: boolean; initialTab?: 'contracts' | 'guild' | 'disputes'; initialId?: string; landSeq?: number }>()
const emit = defineEmits<{ (e: 'close'): void }>()
// §POCKETBRIDGE5 W-D — the dialog role was already declared; the trap makes it TRUE:
// focus enters on open, Tab cycles inside, and RETURNS to the opener on close.
const trapEl = ref<HTMLElement | null>(null)
useFocusTrap(trapEl, { activeWhen: computed(() => props.show) })

type Tab = 'contracts' | 'guild' | 'disputes'
const tab = ref<Tab>('contracts')

const actingDid = computed<string | null>(() => authStore.activeAgent?.did || null)
const actingName = computed<string>(() =>
  authStore.activeAgent?.name || (actingDid.value ? `${actingDid.value.slice(0, 22)}…` : ''))

/** Per-tab load state. `error` is shown, never swallowed — a blank tab that had
 *  a 500 behind it is the same lie as a blank tab with no agent. */
interface Lane<T> { rows: T[]; loading: boolean; error: string | null; loaded: boolean }
function lane<T>(): Lane<T> { return { rows: [], loading: false, error: null, loaded: false } }

const contracts = ref<Lane<ContractV2>>(lane<ContractV2>())
const guild = ref<Lane<GuildOrder>>(lane<GuildOrder>())
const disputes = ref<Lane<any>>(lane<any>())
const settlements = ref<Lane<Settlement>>(lane<Settlement>())
const credentials = ref<{ count: number; verified: number } | null>(null)

const isAdmin = computed(() => !!authStore.isAdmin)

function msg(e: any): string {
  return e?.response?.data?.detail || e?.response?.data?.error?.detail || e?.message || 'Request failed'
}

async function loadContracts(force = false): Promise<void> {
  if (!actingDid.value) return
  if (contracts.value.loaded && !force) return
  contracts.value.loading = true; contracts.value.error = null
  try {
    const r = await contractsV2Api.mine({})
    contracts.value.rows = r.items || []
    contracts.value.loaded = true
  } catch (e: any) { contracts.value.error = msg(e) } finally { contracts.value.loading = false }
}

async function loadGuild(force = false): Promise<void> {
  if (!actingDid.value) return
  if (guild.value.loaded && !force) return
  guild.value.loading = true; guild.value.error = null
  try {
    const r = await guildApi.mine()
    guild.value.rows = r.orders || []
    guild.value.loaded = true
  } catch (e: any) { guild.value.error = msg(e) } finally { guild.value.loading = false }
  // The travelled-trust count is a bonus, never a reason to fail the tab.
  try {
    const c = await guildApi.myCredentials()
    credentials.value = { count: c.count ?? (c.credentials?.length || 0),
                          verified: (c.credentials || []).filter((x: any) => x.verified).length }
  } catch { credentials.value = null }
}

async function loadDisputes(force = false): Promise<void> {
  if (!actingDid.value) return
  if (disputes.value.loaded && !force) return
  disputes.value.loading = true; disputes.value.error = null
  try {
    disputes.value.rows = await disputesApi.getAgentDisputes(actingDid.value)
    disputes.value.loaded = true
  } catch (e: any) { disputes.value.error = msg(e) } finally { disputes.value.loading = false }

  // The settlement half only for someone who can read it. Asking anyway would
  // 403 and put a scary error in front of a user who did nothing wrong.
  if (!isAdmin.value) { settlements.value.loaded = true; return }
  settlements.value.loading = true; settlements.value.error = null
  try {
    const r = await settlementsApi.list()
    const mine = (r.settlements || []).filter((s) =>
      [s.complainant_did, s.defendant_did].some((d) => d && d.toLowerCase() === actingDid.value!.toLowerCase()))
    settlements.value.rows = mine
    settlements.value.loaded = true
  } catch (e: any) { settlements.value.error = msg(e) } finally { settlements.value.loading = false }
}

function loadTab(force = false): void {
  if (tab.value === 'contracts') void loadContracts(force)
  else if (tab.value === 'guild') void loadGuild(force)
  else void loadDisputes(force)
}
// ⚠ immediate — in Pocket the component MOUNTS with show already true
// (v-if="workEver" defers the mount to the first open), so a plain watcher
// never fires and initialTab silently did nothing. Measured: ?work=disputes
// opened the CONTRACTS tab for 8s straight.
watch(() => props.show, (v) => {
  if (!v) return
  if (props.initialTab) tab.value = props.initialTab
  loadTab()
  // Land ON the row the attention row named — after its lane has rows.
  if (props.initialTab === 'disputes' && props.initialId) {
    const want = String(props.initialId)
    const tryOpen = () => {
      if (!disputes.value.loaded) return
      // Already on this record? RE-FETCH it — a deep link promises the record's
      // CURRENT state (a ruling may have landed since it was first expanded).
      if (openId.value === want) void refreshRow('disputes', want)
      else void toggleRow('disputes', want)
    }
    const stop = watch(() => disputes.value.loaded, (l) => { if (l) { tryOpen(); stop() } }, { immediate: true })
  }
}, { immediate: true })
watch(tab, () => { if (props.show) loadTab() })
// A deep link can arrive while the modal is ALREADY open (a NEEDS YOU row for
// another dispute, a push tapped mid-session, a re-tap of the same link after
// a ruling). The show-watcher never refires then — the shell bumps landSeq on
// every openWork instead, and this re-lands on the named record.
watch(() => props.landSeq, () => {
  if (!props.show || !props.initialId || props.initialTab !== 'disputes') return
  const want = String(props.initialId)
  if (tab.value !== 'disputes') tab.value = 'disputes'
  const land = () => {
    if (openId.value === want) void refreshRow('disputes', want)
    else void toggleRow('disputes', want)
  }
  if (disputes.value.loaded) land()
  else { const stop = watch(() => disputes.value.loaded, (l) => { if (l) { land(); stop() } }) }
})
// Switching the acting agent invalidates every lane: these lists ARE that agent.
watch(actingDid, () => {
  contracts.value = lane<ContractV2>(); guild.value = lane<GuildOrder>()
  disputes.value = lane<any>(); settlements.value = lane<Settlement>(); credentials.value = null
  if (props.show) loadTab()
})

/** Expanded row -> the real detail, on the same rail the full page uses. */
const openId = ref<string | null>(null)
const detail = ref<any>(null)
const detailLoading = ref(false)
const detailError = ref<string | null>(null)
async function toggleRow(kind: Tab, id: string, replica = false): Promise<void> {
  if (openId.value === id) { openId.value = null; detail.value = null; return }
  openId.value = id; detail.value = null; detailError.value = null
  // §XHIREFE — a replica row has NO local detail (the contract lives at its
  // home registry; fetching it here 404'd). Its expansion is the relay door.
  if (replica) { detailLoading.value = false; return }
  detailLoading.value = true
  try {
    if (kind === 'contracts') detail.value = await contractsV2Api.get(id)
    else if (kind === 'guild') detail.value = await guildApi.detail(id)
    else detail.value = await disputesApi.getDispute(id)
  } catch (e: any) { detailError.value = msg(e) } finally { detailLoading.value = false }
}
/** Reload an already-expanded row's detail IN PLACE (deep link re-entry): the
 *  stale record stays visible until the fresh one lands — same discipline as
 *  the guild actions' post-action refresh. */
async function refreshRow(kind: Tab, id: string): Promise<void> {
  openId.value = id; detailError.value = null; detailLoading.value = true
  try {
    if (kind === 'contracts') detail.value = await contractsV2Api.get(id)
    else if (kind === 'guild') detail.value = await guildApi.detail(id)
    else detail.value = await disputesApi.getDispute(id)
  } catch (e: any) { detailError.value = msg(e) } finally { detailLoading.value = false }
}

/* §POCKETBRIDGE4 WS-P — guild actions in the expanded detail, gated by the SAME
 * brain Pocket and GuildBoard use (services/guildActions). Additive: every read
 * above stays untouched; an action refreshes the detail in place. */
const { actionLabel, noteText } = useGuildLabels()
const gOffer = computed(() => actionsFor(detail.value?.order || null, actingDid.value))
const actBusy = ref(false)
const actErr = ref<string | null>(null)
const actForm = ref({ price: '', text: '' })
async function guildAct(key: GuildActionOffer['key'], accept = true): Promise<void> {
  const id = detail.value?.order?.id
  if (!id || actBusy.value) return
  actBusy.value = true; actErr.value = null
  try {
    if (key === 'bid') {
      const p = Number(actForm.value.price)
      if (!Number.isFinite(p) || p <= 0) { actErr.value = t('bridge.work.needPrice', 'Enter a bid price first.'); return }
      await guildApi.bid(id, { price: p })
    } else if (key === 'submit') {
      const text = actForm.value.text.trim()
      if (!text) { actErr.value = t('bridge.work.needDeliverable', 'Describe the deliverable first.'); return }
      await guildApi.submitWork(id, { text })
    } else if (key === 'verify') {
      await guildApi.verify(id, accept, 5)
    } else if (key === 'cancel') {
      await guildApi.cancel(id)
    }
    actForm.value = { price: '', text: '' }
    detail.value = await guildApi.detail(id)
    void loadGuild(true)
  } catch (e: any) { actErr.value = msg(e) } finally { actBusy.value = false }
}
async function guildAward(bidId: number): Promise<void> {
  const id = detail.value?.order?.id
  if (!id || actBusy.value) return
  actBusy.value = true; actErr.value = null
  try {
    await guildApi.award(id, bidId)
    detail.value = await guildApi.detail(id)
    void loadGuild(true)
  } catch (e: any) { actErr.value = msg(e) } finally { actBusy.value = false }
}

/* §POCKETBRIDGE5 A' — DISPUTES grow up inside the EXISTING modal (his word:
 * no new surface, no new bottom button; the quick-access door is enough).
 * Detail + evidence timeline + submit evidence + file-a-dispute, all on the
 * rails DisputesView already uses. Filing moves NO money — compensation
 * happens only at an admin ruling, and the form says so. */
const evForm = ref({ type: 'text' as 'text' | 'link', content: '', description: '' })
const evBusy = ref(false)
const evNote = ref<string | null>(null)
const disputeActive = (d: any) => ['open', 'investigating'].includes(String(d?.status || ''))
async function submitEv(): Promise<void> {
  const id = detail.value?.id
  const content = evForm.value.content.trim()
  if (!id || evBusy.value) return
  if (!content) { evNote.value = t('bridge.work.evNeedContent', 'Evidence needs content (text or a URL).'); return }
  evBusy.value = true; evNote.value = null
  try {
    await disputesApi.submitEvidence(String(id), {
      type: evForm.value.type, content,
      ...(evForm.value.description.trim() ? { description: evForm.value.description.trim() } : {}),
    }, actingDid.value || undefined)
    evForm.value = { type: 'text', content: '', description: '' }
    detail.value = await disputesApi.getDispute(String(id))
    evNote.value = t('bridge.work.evOk', 'Evidence submitted. It is on the record below.')
  } catch (e: any) { evNote.value = msg(e) } finally { evBusy.value = false }
}

const fdOpen = ref(false)
const fdForm = ref({ defendant: '', category: 'service_failure', description: '', amount: '' })
const fdBusy = ref(false)
const fdNote = ref<{ ok: boolean; text: string } | null>(null)
const FD_CATS = [
  { k: 'service_failure', label: 'Service failure' },
  { k: 'payment_dispute', label: 'Payment dispute' },
  { k: 'contract_breach', label: 'Contract breach' },
  { k: 'other', label: 'Other' },
]
async function fileDispute(): Promise<void> {
  if (fdBusy.value) return
  const defendant = fdForm.value.defendant.trim()
  const description = fdForm.value.description.trim()
  const me = actingDid.value
  if (!me) { fdNote.value = { ok: false, text: t('bridge.work.fdNoAgent', 'Pick an acting agent first: disputes are filed AS an agent.') }; return }
  if (!defendant.startsWith('did:')) { fdNote.value = { ok: false, text: t('bridge.work.fdBadDid', 'The respondent must be an agent address (did:…).') }; return }
  if (defendant === me) { fdNote.value = { ok: false, text: t('bridge.work.fdSelf', 'An agent cannot dispute itself.') }; return }
  if (!description) { fdNote.value = { ok: false, text: t('bridge.work.fdNeedDesc', 'Describe what went wrong: that text becomes the first evidence.') }; return }
  const amount = fdForm.value.amount === '' ? undefined : Number(fdForm.value.amount)
  if (amount !== undefined && (!Number.isFinite(amount) || amount <= 0)) {
    fdNote.value = { ok: false, text: t('bridge.work.fdBadAmount', 'The disputed amount must be a positive number (or leave it empty).') }; return
  }
  fdBusy.value = true; fdNote.value = null
  try {
    const d = await disputesApi.createDispute({
      complainant_did: me, defendant_did: defendant,
      category: fdForm.value.category, description,
      ...(amount !== undefined ? { amount_disputed: amount } : {}),
    })
    fdForm.value = { defendant: '', category: 'service_failure', description: '', amount: '' }
    fdOpen.value = false
    fdNote.value = { ok: true, text: t('bridge.work.fdOk', 'Dispute filed. Nothing moved; compensation happens only if an admin rules in your favor.') }
    await loadDisputes(true)
    void toggleRow('disputes', String(d.id))
  } catch (e: any) { fdNote.value = { ok: false, text: msg(e) } } finally { fdBusy.value = false }
}
const linkish = (v: string) => /^https?:\/\//i.test(v)

/**
 * FULL VIEW by ROUTE NAME, not by path.
 *
 * These four views are CHILD routes with relative paths (`contracts`, `guild`,
 * `disputes`), so their absolute form depends on a parent I would be guessing
 * at. A name cannot drift when the parent moves. And `router.push` RESOLVES on
 * an aborted or redirected navigation rather than throwing (PART 1), so the
 * catch here is for a rejected guard only — it is not evidence of arrival.
 */
function go(name: string): void {
  emit('close')
  router.push({ name }).catch(() => { /* the route guard owns the outcome */ })
}

/**
 * Escape closes it — the same defect polish pass 2 found on the payload modal.
 * `@keydown.esc` on a non-focusable overlay never fires. Capture phase + a stop,
 * so the bridge's own global Escape (which clears stage focus) does not also
 * fire behind this modal.
 */
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape') { e.stopPropagation(); emit('close') }
}
watch(() => props.show, (open) => {
  if (typeof window === 'undefined') return
  if (open) window.addEventListener('keydown', onKey, true)
  else window.removeEventListener('keydown', onKey, true)
}, { immediate: true })
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKey, true)
})

function short(d?: string | null): string {
  if (!d) return '—'
  return d.length > 26 ? `${d.slice(0, 16)}…${d.slice(-4)}` : d
}
function money(v: unknown, cur?: string): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return `${n.toLocaleString(appLocale(), { maximumFractionDigits: 4 })}${cur ? ' ' + cur : ''}`
}
function when(s?: string | null): string {
  if (!s) return '—'
  const d = new Date(s)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('en-GB', { dateStyle: 'short', timeStyle: 'short' })
}
/** Which side of a contract the acting agent is on — the first thing you want. */
function myRole(c: ContractV2): string {
  const me = actingDid.value?.toLowerCase()
  if (!me) return ''
  if (c.client_did?.toLowerCase() === me) return t('bridge.work.asClient', 'you hired')
  if (c.provider_did?.toLowerCase() === me) return t('bridge.work.asProvider', 'you were hired')
  return ''
}
function guildRole(o: GuildOrder): string {
  const me = actingDid.value?.toLowerCase()
  if (!me) return ''
  if (o.poster_did?.toLowerCase() === me) return t('bridge.work.posted', 'you posted')
  if (o.worker_did?.toLowerCase() === me) return t('bridge.work.working', 'you are working')
  return t('bridge.work.bid', 'you bid')
}
function milestoneLine(c: ContractV2): string | null {
  const ms = c.milestones || []
  if (!ms.length) return null
  const done = ms.filter((m: any) => ['released', 'approved', 'completed'].includes(String(m.status || '').toLowerCase())).length
  return `${done}/${ms.length} ${t('bridge.work.milestones', 'milestones')}`
}

const counts = computed(() => ({
  contracts: contracts.value.loaded ? contracts.value.rows.length : null,
  guild: guild.value.loaded ? guild.value.rows.length : null,
  disputes: disputes.value.loaded ? disputes.value.rows.length + settlements.value.rows.length : null,
}))
</script>

<template>
  <Teleport to="body">
    <div v-if="show" class="bwv-overlay" data-testid="work-view" @click.self="emit('close')">
      <div ref="trapEl" class="bwv" role="dialog" aria-modal="true" aria-labelledby="bwv-title">
        <header class="bwv-hdr">
          <div class="bwv-hdr-l">
            <span id="bwv-title" class="bwv-title">{{ t('bridge.work.title', 'YOUR WORK') }}</span>
            <span v-if="actingDid" class="bwv-actor" data-testid="work-actor">
              {{ t('bridge.work.acting', 'acting as') }} <strong>{{ actingName }}</strong>
            </span>
          </div>
          <div class="bwv-hdr-r">
            <button type="button" class="bwv-btn" data-testid="work-refresh"
                    :title="t('bridge.work.refresh', 'Reload this tab')" @click="loadTab(true)">
              <Icon name="mdi:refresh" :size="11" />
            </button>
            <button type="button" class="bwv-x" :aria-label="t('common.close', 'Close')" @click="emit('close')">&#10005;</button>
          </div>
        </header>

        <!-- Without an acting agent these rails have nothing to answer. Saying
             so beats three empty lists that read as "you have none". -->
        <p v-if="!actingDid" class="bwv-empty bwv-empty--lead" data-testid="work-noagent">
          {{ t('bridge.work.noAgent', 'Select an agent first. Contracts, guild work and disputes are all scoped to the agent you act as, so there is nothing to show until one is chosen.') }}
        </p>

        <template v-else>
          <div class="bwv-tabs" role="tablist">
            <button type="button" class="bwv-tab" :class="{ 'is-on': tab === 'contracts' }"
                    role="tab" :aria-selected="tab === 'contracts'"
                    data-testid="work-tab-contracts" @click="tab = 'contracts'">
              {{ t('bridge.work.contracts', 'CONTRACTS') }}
              <span v-if="counts.contracts !== null" class="bwv-tab-n">{{ counts.contracts }}</span>
            </button>
            <button type="button" class="bwv-tab" :class="{ 'is-on': tab === 'guild' }"
                    role="tab" :aria-selected="tab === 'guild'"
                    data-testid="work-tab-guild" @click="tab = 'guild'">
              {{ t('bridge.work.guild', 'GUILD WORK') }}
              <span v-if="counts.guild !== null" class="bwv-tab-n">{{ counts.guild }}</span>
            </button>
            <button type="button" class="bwv-tab" :class="{ 'is-on': tab === 'disputes' }"
                    role="tab" :aria-selected="tab === 'disputes'"
                    data-testid="work-tab-disputes" @click="tab = 'disputes'">
              {{ t('bridge.work.disputes', 'DISPUTES') }}
              <span v-if="counts.disputes !== null" class="bwv-tab-n">{{ counts.disputes }}</span>
            </button>
          </div>

          <div class="bwv-body">
            <!-- ── CONTRACTS ─────────────────────────────────────────────── -->
            <template v-if="tab === 'contracts'">
              <p v-if="contracts.loading" class="bwv-empty">{{ t('bridge.work.loading', 'Loading…') }}</p>
              <p v-else-if="contracts.error" class="bwv-err" data-testid="work-error">{{ contracts.error }}</p>
              <p v-else-if="!contracts.rows.length" class="bwv-empty">
                {{ t('bridge.work.noContracts', 'This agent is not party to any contract yet. Hiring an agent from Discovery, or being hired, creates one.') }}
              </p>
              <div v-for="c in contracts.rows" :key="c.id" class="bwv-row"
                   :class="{ 'bwv-row-replica': c.replica }"
                   :data-testid="c.replica ? 'work-contract-replica' : 'work-contract'">
                <button type="button" class="bwv-row-btn" @click="toggleRow('contracts', c.id, !!c.replica)">
                  <span class="bwv-row-main">
                    <span class="bwv-row-title">{{ c.title || c.contract_type }}</span>
                    <span class="bwv-row-sub">
                      <!-- §XHIREFE — a replica names its HOME first: this row is a
                           courier for a contract living on another registry. -->
                      <span v-if="c.replica" class="bwv-replica-chip" data-testid="work-replica-chip">
                        <Icon name="mdi:earth" /> {{ c.home_registry }}</span>
                      {{ myRole(c) }} · {{ short(c.provider_did === actingDid ? c.client_did : c.provider_did) }}
                      <template v-if="milestoneLine(c)"> · {{ milestoneLine(c) }}</template>
                    </span>
                  </span>
                  <span class="bwv-row-amt">{{ money(c.total_amount, c.currency) }}</span>
                  <span class="bwv-chip" :class="`is-${c.status}`">{{ c.status }}</span>
                </button>
                <div v-if="openId === c.id" class="bwv-detail">
                  <ReplicaContractDoor v-if="c.replica" :contract="c" @acted="loadContracts(true)" />
                  <template v-else>
                    <p v-if="detailLoading" class="bwv-empty">{{ t('bridge.work.loading', 'Loading…') }}</p>
                    <p v-else-if="detailError" class="bwv-err">{{ detailError }}</p>
                    <template v-else-if="detail">
                      <!-- §XHIREFE client side — the provider lives on another registry -->
                      <p v-if="detail.counterparty_home_registry" class="bwv-home-line" data-testid="work-provider-home">
                        <Icon name="mdi:earth" />
                        {{ t('bridge.work.providerHome', 'Provider is on') }} <b>{{ detail.counterparty_home_registry }}</b> —
                        {{ t('bridge.work.providerHome2', 'their accept and submissions arrive over federation; settlement stages through this contract\'s escrow.') }}
                      </p>
                      <div class="bwv-kv"><span>{{ t('bridge.work.created', 'CREATED') }}</span><b>{{ when(detail.created_at) }}</b></div>
                      <div class="bwv-kv"><span>{{ t('bridge.work.deadline', 'DEADLINE') }}</span><b>{{ when(detail.deadline) }}</b></div>
                      <div class="bwv-kv"><span>{{ t('bridge.work.escrow', 'ESCROW') }}</span><b>{{ detail.escrow_ref || '—' }}</b></div>
                      <div v-for="m in (detail.milestones || [])" :key="m.seq" class="bwv-ms">
                        <span class="bwv-ms-n">{{ m.seq }}</span>
                        <span class="bwv-ms-t">{{ m.title || m.description || '—' }}</span>
                        <span class="bwv-ms-a">{{ money(m.amount, detail.currency) }}</span>
                        <span class="bwv-chip" :class="`is-${m.status}`">{{ m.status }}</span>
                      </div>
                    </template>
                  </template>
                </div>
              </div>
            </template>

            <!-- ── GUILD ─────────────────────────────────────────────────── -->
            <template v-else-if="tab === 'guild'">
              <p v-if="credentials" class="bwv-note" data-testid="work-credentials">
                {{ credentials.count }} {{ t('bridge.work.credentials', 'work credentials held') }}
                <template v-if="credentials.verified !== credentials.count">
                  · {{ credentials.verified }} {{ t('bridge.work.verified', 'verified at origin') }}
                </template>
              </p>
              <p v-if="guild.loading" class="bwv-empty">{{ t('bridge.work.loading', 'Loading…') }}</p>
              <p v-else-if="guild.error" class="bwv-err" data-testid="work-error">{{ guild.error }}</p>
              <p v-else-if="!guild.rows.length" class="bwv-empty">
                {{ t('bridge.work.noGuild', 'No guild orders for this agent yet: nothing posted, bid on or awarded.') }}
              </p>
              <div v-for="o in guild.rows" :key="o.id" class="bwv-row" data-testid="work-guild">
                <button type="button" class="bwv-row-btn" @click="toggleRow('guild', o.id)">
                  <span class="bwv-row-main">
                    <span class="bwv-row-title">{{ o.title }}</span>
                    <span class="bwv-row-sub">
                      {{ guildRole(o) }}
                      <template v-if="o.bid_count"> · {{ o.bid_count }} {{ t('bridge.work.bids', 'bids') }}</template>
                    </span>
                  </span>
                  <span class="bwv-row-amt">{{ money(o.bounty, o.currency) }}</span>
                  <span class="bwv-chip" :class="`is-${o.status}`">{{ o.status }}</span>
                </button>
                <div v-if="openId === o.id" class="bwv-detail">
                  <p v-if="detailLoading" class="bwv-empty">{{ t('bridge.work.loading', 'Loading…') }}</p>
                  <p v-else-if="detailError" class="bwv-err">{{ detailError }}</p>
                  <template v-else-if="detail?.order">
                    <div class="bwv-kv"><span>{{ t('bridge.work.posted2', 'POSTED') }}</span><b>{{ when(detail.order.created_at) }}</b></div>
                    <div class="bwv-kv"><span>{{ t('bridge.work.settled', 'SETTLED') }}</span><b>{{ when(detail.order.settled_at) }}</b></div>
                    <p v-if="detail.order.spec" class="bwv-spec">{{ detail.order.spec }}</p>
                    <!-- §POCKETBRIDGE4: offered actions — same brain as Pocket/GuildBoard -->
                    <div v-if="gOffer.actions.length || gOffer.note" class="bwv-acts" data-testid="bwv-guild-acts">
                      <p v-if="gOffer.note" class="bwv-note">{{ noteText(gOffer) }}</p>
                      <p v-if="actErr" class="bwv-err">{{ actErr }}</p>
                      <template v-for="a in gOffer.actions" :key="a.key">
                        <div v-if="a.key === 'bid'" class="bwv-act-row">
                          <input v-model="actForm.price" class="bwv-in" type="number" inputmode="decimal"
                                 :placeholder="t('bridge.work.price', 'price')" :aria-label="t('bridge.work.price', 'price')" />
                          <button class="bwv-act" data-testid="bwv-act-bid" :disabled="actBusy" @click="guildAct('bid')">{{ actionLabel(a) }}</button>
                        </div>
                        <div v-else-if="a.key === 'submit'" class="bwv-act-row">
                          <input v-model="actForm.text" class="bwv-in bwv-in-wide" type="text"
                                 :placeholder="t('bridge.work.deliverable', 'Deliverable (text / URL / hash)')"
                                 :aria-label="t('bridge.work.deliverable', 'Deliverable (text / URL / hash)')" />
                          <button class="bwv-act" data-testid="bwv-act-submit" :disabled="actBusy" @click="guildAct('submit')">{{ actionLabel(a) }}</button>
                        </div>
                        <div v-else-if="a.key === 'verify'" class="bwv-act-row">
                          <button class="bwv-act is-money" data-testid="bwv-act-verify" :disabled="actBusy" @click="guildAct('verify', true)">{{ t('bridge.work.acceptPay', 'Accept & pay') }}</button>
                          <button class="bwv-act is-danger" data-testid="bwv-act-reject" :disabled="actBusy" @click="guildAct('verify', false)">{{ t('bridge.work.reject', 'Reject') }}</button>
                        </div>
                        <div v-else-if="a.key === 'cancel'" class="bwv-act-row">
                          <button class="bwv-act is-danger" data-testid="bwv-act-cancel" :disabled="actBusy" @click="guildAct('cancel')">{{ actionLabel(a) }}</button>
                        </div>
                        <div v-else-if="a.key === 'award'" class="bwv-award">
                          <div v-for="b in (detail.bids || []).filter((x: any) => x.status === 'open')" :key="b.id" class="bwv-act-row">
                            <span class="bwv-bidline"><code>{{ String(b.bidder_did || '').slice(0, 18) }}…</code> · {{ money(b.price, detail.order.currency) }}</span>
                            <button class="bwv-act" :data-testid="'bwv-act-award-' + b.id" :disabled="actBusy" @click="guildAward(b.id)">{{ t('bridge.work.award', 'Award') }}</button>
                          </div>
                        </div>
                      </template>
                    </div>
                    <div v-for="e in (detail.events || []).slice(-6)" :key="e.seq" class="bwv-ev">
                      <span class="bwv-ev-t">{{ e.event_type }}</span>
                      <span class="bwv-ev-w">{{ when(e.created_at) }}</span>
                    </div>
                  </template>
                </div>
              </div>
            </template>

            <!-- ── DISPUTES (+ SETTLEMENTS when readable) ────────────────── -->
            <template v-else>
              <!-- §POCKETBRIDGE5 A' — file a dispute from here (the low-cost
                   service-failure case). Filing moves NO money. -->
              <div class="bwv-fd" data-testid="work-file-dispute">
                <button v-if="!fdOpen" type="button" class="bwv-act" data-testid="work-fd-open" @click="fdOpen = true; fdNote = null">
                  <Icon name="mdi:gavel" :size="11" /> {{ t('bridge.work.fdBtn', 'FILE A DISPUTE') }}
                </button>
                <div v-else class="bwv-fd-form">
                  <input v-model="fdForm.defendant" class="bwv-in bwv-in-wide" type="text" data-testid="work-fd-did"
                         :placeholder="t('bridge.work.fdDid', 'respondent did:…')" :aria-label="t('bridge.work.fdDid', 'respondent did:…')" />
                  <select v-model="fdForm.category" class="bwv-in" :aria-label="t('bridge.work.fdCat', 'category')">
                    <option v-for="c in FD_CATS" :key="c.k" :value="c.k">{{ c.label }}</option>
                  </select>
                  <input v-model="fdForm.amount" class="bwv-in" type="number" inputmode="decimal"
                         :placeholder="t('bridge.work.fdAmt', 'amount (opt.)')" :aria-label="t('bridge.work.fdAmt', 'disputed amount, optional')" />
                  <input v-model="fdForm.description" class="bwv-in bwv-in-wide" type="text" data-testid="work-fd-desc"
                         :placeholder="t('bridge.work.fdDesc', 'What went wrong? This becomes the first evidence.')"
                         :aria-label="t('bridge.work.fdDesc', 'What went wrong?')" />
                  <div class="bwv-act-row">
                    <button type="button" class="bwv-act" data-testid="work-fd-go" :disabled="fdBusy" @click="fileDispute">
                      {{ fdBusy ? t('bridge.work.filing', 'Filing…') : t('bridge.work.fdFile', 'File') }}
                    </button>
                    <button type="button" class="bwv-act is-danger" :disabled="fdBusy" @click="fdOpen = false">{{ t('bridge.work.cancel', 'Cancel') }}</button>
                    <span class="bwv-note">{{ t('bridge.work.fdMoney', 'Filing moves nothing. Compensation only at an admin ruling.') }}</span>
                  </div>
                </div>
                <p v-if="fdNote" class="bwv-fd-note" :class="fdNote.ok ? 'ok' : 'bad'" data-testid="work-fd-note">{{ fdNote.text }}</p>
              </div>

              <p v-if="disputes.loading" class="bwv-empty">{{ t('bridge.work.loading', 'Loading…') }}</p>
              <p v-else-if="disputes.error" class="bwv-err" data-testid="work-error">{{ disputes.error }}</p>
              <p v-else-if="!disputes.rows.length" class="bwv-empty">
                {{ t('bridge.work.noDisputes', 'No disputes involving this agent.') }}
              </p>
              <div v-for="d in disputes.rows" :key="d.id" class="bwv-row" data-testid="work-dispute">
                <button type="button" class="bwv-row-btn" @click="toggleRow('disputes', String(d.id))">
                  <span class="bwv-row-main">
                    <span class="bwv-row-title">{{ d.reason || d.dispute_type || t('bridge.work.dispute', 'dispute') }}</span>
                    <span class="bwv-row-sub">{{ short(d.complainant_did) }} → {{ short(d.defendant_did) }}</span>
                  </span>
                  <span class="bwv-row-amt">{{ money(d.amount ?? d.requested_amount, d.currency) }}</span>
                  <span class="bwv-chip" :class="`is-${d.status}`">{{ d.status }}</span>
                </button>
                <!-- §POCKETBRIDGE5 A' — the expanded dispute: the row used to
                     load a detail and render NOTHING. Now: facts, ruling,
                     compensation, the evidence record, and a submit form. -->
                <div v-if="openId === String(d.id)" class="bwv-detail" data-testid="work-dispute-detail">
                  <p v-if="detailLoading" class="bwv-empty">{{ t('bridge.work.loading', 'Loading…') }}</p>
                  <p v-else-if="detailError" class="bwv-err">{{ detailError }}</p>
                  <template v-else-if="detail && detail.id">
                    <div class="bwv-kv"><span>{{ t('bridge.work.dParties', 'PARTIES') }}</span><b>{{ detail.claimant_name || short(detail.claimant_did) }} → {{ detail.respondent_name || short(detail.respondent_did) }}</b></div>
                    <div class="bwv-kv"><span>{{ t('bridge.work.dFiled', 'FILED') }}</span><b>{{ when(detail.created_at) }}</b></div>
                    <div v-if="detail.resolution_date" class="bwv-kv"><span>{{ t('bridge.work.dResolved', 'RESOLVED') }}</span><b>{{ when(detail.resolution_date) }}</b></div>
                    <p v-if="detail.description" class="bwv-spec">{{ detail.description }}</p>
                    <div v-if="detail.ruling" class="bwv-kv"><span>{{ t('bridge.work.dRuling', 'RULING') }}</span><b>{{ detail.ruling }}</b></div>
                    <p v-if="detail.compensation" class="bwv-comp" data-testid="work-dispute-comp">
                      <Icon name="mdi:cash-check" :size="11" />
                      <template v-if="detail.compensation.applied">
                        {{ t('bridge.work.dCompPaid', 'Compensation paid:') }} <b>{{ money(detail.compensation.amount) }}</b>
                        <template v-if="detail.compensation.partial"> · {{ t('bridge.work.dPartial', 'partial') }} ({{ money(detail.compensation.deferred_amount) }} {{ t('bridge.work.dDeferred', 'deferred') }})</template>
                      </template>
                      <template v-else>{{ t('bridge.work.dCompNone', 'No compensation moved.') }}<template v-if="detail.compensation.reason"> {{ detail.compensation.reason }}</template></template>
                    </p>
                    <div class="bwv-sec"><span class="bwv-sec-t">{{ t('bridge.work.dEvidence', 'EVIDENCE') }} <template v-if="(detail.evidence || []).length">({{ detail.evidence.length }})</template></span></div>
                    <p v-if="!(detail.evidence || []).length" class="bwv-empty">{{ t('bridge.work.dNoEv', 'No evidence on record yet.') }}</p>
                    <div v-for="ev in (detail.evidence || [])" :key="ev.id" class="bwv-ev-item" data-testid="work-evidence">
                      <span class="bwv-ev-head">{{ ev.type }} · {{ ev.submitted_by_name || short(ev.submitted_by) }} · {{ when(ev.submitted_at) }}</span>
                      <a v-if="linkish(ev.content)" class="bwv-ev-link" :href="ev.content" target="_blank" rel="noopener noreferrer">{{ ev.content }}</a>
                      <span v-else class="bwv-ev-body">{{ ev.content }}</span>
                      <span v-if="ev.description" class="bwv-ev-desc">{{ ev.description }}</span>
                    </div>
                    <div v-if="disputeActive(detail)" class="bwv-acts" data-testid="work-ev-form">
                      <div class="bwv-act-row">
                        <select v-model="evForm.type" class="bwv-in" :aria-label="t('bridge.work.evType', 'evidence type')">
                          <option value="text">{{ t('bridge.work.evText', 'text') }}</option>
                          <option value="link">{{ t('bridge.work.evLink', 'link') }}</option>
                        </select>
                        <input v-model="evForm.content" class="bwv-in bwv-in-wide" type="text" data-testid="work-ev-content"
                               :placeholder="evForm.type === 'link' ? 'https://…' : t('bridge.work.evPh', 'What happened, verbatim')"
                               :aria-label="t('bridge.work.evPh', 'Evidence content')" />
                        <button type="button" class="bwv-act" data-testid="work-ev-go" :disabled="evBusy" @click="submitEv">
                          {{ evBusy ? t('bridge.work.evBusy', 'Submitting…') : t('bridge.work.evGo', 'Submit evidence') }}
                        </button>
                      </div>
                      <p v-if="evNote" class="bwv-note" data-testid="work-ev-note">{{ evNote }}</p>
                    </div>
                    <p v-else class="bwv-note">{{ t('bridge.work.dClosed', 'This dispute is closed. The record above is final.') }}</p>
                  </template>
                </div>
              </div>

              <!-- The settlement half. Present only when the viewer can read it,
                   and it says which half it is either way. -->
              <div class="bwv-sec">
                <span class="bwv-sec-t">{{ t('bridge.work.settlements', 'CROSS-REGISTRY SETTLEMENTS') }}</span>
              </div>
              <p v-if="!isAdmin" class="bwv-note" data-testid="work-settle-gate">
                {{ t('bridge.work.settleAdmin', 'The settlement ledger is an enforcement surface and needs the admin_enforcement flag, so it is not shown here. The disputes above are the agent-side half of the same story.') }}
              </p>
              <template v-else>
                <p v-if="settlements.loading" class="bwv-empty">{{ t('bridge.work.loading', 'Loading…') }}</p>
                <p v-else-if="settlements.error" class="bwv-err">{{ settlements.error }}</p>
                <p v-else-if="!settlements.rows.length" class="bwv-empty" data-testid="work-settle-empty">
                  {{ t('bridge.work.noSettlements', 'No cross-registry settlement names this agent. (The list is capped at the 100 most recent on this registry.)') }}
                </p>
                <div v-for="s in settlements.rows" :key="s.id" class="bwv-row" data-testid="work-settlement">
                  <span class="bwv-row-btn bwv-row-btn--flat">
                    <span class="bwv-row-main">
                      <span class="bwv-row-title">{{ s.ruling || t('bridge.work.settlement', 'settlement') }}</span>
                      <span class="bwv-row-sub">{{ short(s.complainant_did) }} → {{ short(s.defendant_did) }}<template v-if="s.is_partial"> · {{ t('bridge.work.partial', 'partial') }}</template></span>
                    </span>
                    <span class="bwv-row-amt">{{ money(s.slashed_amount) }}</span>
                    <span class="bwv-chip" :class="`is-${s.status}`">{{ s.status }}</span>
                  </span>
                </div>
              </template>
            </template>
          </div>

          <footer class="bwv-foot">
            <button v-if="tab === 'contracts'" type="button" class="bwv-door" data-testid="work-full" @click="go('contracts')">
              {{ t('bridge.work.fullContracts', 'FULL CONTRACTS VIEW') }} <Icon name="mdi:arrow-right" :size="10" />
            </button>
            <button v-else-if="tab === 'guild'" type="button" class="bwv-door" data-testid="work-full" @click="go('guild')">
              {{ t('bridge.work.fullGuild', 'FULL GUILD BOARD') }} <Icon name="mdi:arrow-right" :size="10" />
            </button>
            <button v-else type="button" class="bwv-door" data-testid="work-full" @click="go('disputes')">
              {{ t('bridge.work.fullDisputes', 'FULL DISPUTES VIEW') }} <Icon name="mdi:arrow-right" :size="10" />
            </button>
            <span class="bwv-foot-note">
              {{ t('bridge.work.scope', 'scoped to the agent you are acting as') }}
            </span>
          </footer>
        </template>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.bwv-overlay {
  position: fixed; top: 0; bottom: 0; z-index: 12000;
  /**
   * §BRIDGE R13 #10 — live INSIDE the stage column, so the rails stay readable.
   *
   * "the modals should not blcok the live ledger view." The bounds come from
   * `--brg-stage-l/r`, which Mission Control publishes on the ROOT element from
   * the measured `.brg-center` box (teleported content cannot inherit from
   * `.brg`). Both fall back to 0 — on a narrow window, or anywhere the bridge is
   * not mounted, this is an ordinary full-viewport modal again.
   */
  left: var(--brg-stage-l, 0px); right: var(--brg-stage-r, 0px);
  background: rgba(2, 5, 12, 0.72);
  display: flex; align-items: center; justify-content: center; padding: 1.2rem;
}
.bwv {
  width: min(860px, 96vw); max-height: 86vh; display: flex; flex-direction: column;
  background: var(--nc-bg-elev, #0a1018);
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.22)); border-radius: 6px;
  font-family: var(--nc-font-mono, ui-monospace, monospace);
  box-shadow: 0 18px 60px rgba(0, 0, 0, 0.55);
}
.bwv-hdr { display: flex; align-items: center; justify-content: space-between; padding: 0.6rem 0.8rem;
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.16)); }
.bwv-hdr-l { display: flex; align-items: baseline; gap: 0.7rem; min-width: 0; flex-wrap: wrap; }
.bwv-hdr-r { display: inline-flex; align-items: center; gap: 0.4rem; }
.bwv-title { font-size: 0.68rem; letter-spacing: 0.18em; color: var(--nc-text, #d6e2f2); }
.bwv-actor { font-size: 0.58rem; color: var(--nc-text-dim, #6b7f9e); }
.bwv-actor strong { color: var(--brand-primary, #4dd8e6); font-weight: 700; }
.bwv-btn { background: transparent; border: 0; cursor: pointer; color: var(--nc-text-dim, #6b7f9e);
  padding: 0 2px; min-width: 20px; min-height: 20px; display: inline-flex; align-items: center; justify-content: center; }
.bwv-btn:hover { color: var(--nc-primary, #22d3ee); }
.bwv-x { background: none; border: 0; color: var(--nc-text-dim, #6b7f9e); cursor: pointer; font-size: 0.8rem;
  min-width: 20px; min-height: 20px; }
.bwv-x:hover { color: var(--nc-text, #d6e2f2); }
.bwv-tabs { display: flex; gap: 0.35rem; padding: 0.5rem 0.8rem;
  border-bottom: 1px solid var(--nc-border, rgba(120, 160, 210, 0.1)); }
.bwv-tab { background: transparent; border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18));
  border-radius: 3px; padding: 0.2rem 0.6rem; cursor: pointer; font-family: inherit;
  font-size: 0.56rem; letter-spacing: 0.12em; color: var(--nc-text-dim, #8fa3c0); }
.bwv-tab.is-on { color: var(--nc-primary, #22d3ee); border-color: color-mix(in srgb, var(--nc-primary, #22d3ee) 45%, transparent); }
.bwv-tab-n { opacity: 0.65; margin-left: 0.3rem; }
.bwv-body { flex: 1 1 auto; min-height: 8rem; overflow-y: auto; padding: 0.4rem 0.8rem 0.6rem; }
.bwv-empty, .bwv-note, .bwv-err { font-size: 0.6rem; line-height: 1.6; padding: 0.5rem 0.1rem; }
.bwv-empty { color: var(--nc-text-dim, #6b7f9e); }
.bwv-empty--lead { padding: 1.4rem 0.9rem; }
.bwv-note { color: var(--nc-text-dim, #8fa3c0); border-left: 2px solid color-mix(in srgb, var(--nc-primary, #22d3ee) 40%, transparent); padding-left: 0.5rem; }
.bwv-err { color: var(--nc-danger, #ff5252); }
.bwv-row { border-bottom: 1px dotted rgba(120, 160, 210, 0.1); }
/* §XHIREFE — replica rows carry a left accent + home chip so a courier row
   never reads as a local contract. */
.bwv-row-replica { border-left: 2px solid var(--nc-accent, #37c9ff); }
.bwv-replica-chip { display: inline-flex; align-items: center; gap: 3px; margin-right: 5px;
                    padding: 0.05rem 0.35rem; border-radius: 999px; font-size: 0.52rem;
                    font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase;
                    background: rgba(55, 201, 255, 0.12); border: 1px solid rgba(55, 201, 255, 0.35); }
.bwv-home-line { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; margin: 0 0 0.4rem;
                 font-size: 0.62rem; opacity: 0.9; }
.bwv-row-btn { display: grid; grid-template-columns: 1fr auto auto; gap: 0.6rem; align-items: center;
  width: 100%; text-align: left; background: transparent; border: 0; cursor: pointer;
  padding: 0.35rem 0.2rem; font-family: inherit; color: var(--nc-text, #d6e2f2); }
.bwv-row-btn:hover { background: rgba(34, 211, 238, 0.07); }
.bwv-row-btn:focus-visible { outline: 1px solid var(--nc-primary, #22d3ee); outline-offset: -1px; }
.bwv-row-btn--flat { cursor: default; }
.bwv-row-main { display: flex; flex-direction: column; gap: 1px; min-width: 0; }
.bwv-row-title { font-size: 0.63rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bwv-row-sub { font-size: 0.53rem; color: var(--nc-text-dim, #6b7f9e); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bwv-row-amt { font-size: 0.6rem; color: var(--nc-text, #d6e2f2); white-space: nowrap; }
.bwv-chip { font-size: 0.5rem; letter-spacing: 0.08em; padding: 0.08rem 0.35rem; border-radius: 2px;
  border: 1px solid rgba(120, 160, 210, 0.25); color: var(--nc-text-dim, #8fa3c0); white-space: nowrap; }
.bwv-chip.is-completed, .bwv-chip.is-settled, .bwv-chip.is-released, .bwv-chip.is-verified { color: var(--nc-success, #22c55e); border-color: rgba(34, 197, 94, 0.4); }
.bwv-chip.is-disputed, .bwv-chip.is-failed, .bwv-chip.is-cancelled, .bwv-chip.is-expired { color: var(--nc-danger, #ff5252); border-color: rgba(255, 82, 82, 0.4); }
.bwv-chip.is-in_progress, .bwv-chip.is-agreed, .bwv-chip.is-awarded, .bwv-chip.is-open, .bwv-chip.is-pending { color: var(--nc-primary, #22d3ee); border-color: rgba(34, 211, 238, 0.35); }
.bwv-detail { padding: 0.35rem 0.4rem 0.6rem 0.6rem; border-left: 2px solid rgba(34, 211, 238, 0.25); margin: 0 0 0.35rem 0.2rem; }
.bwv-kv { display: flex; gap: 0.5rem; font-size: 0.55rem; line-height: 1.7; }
.bwv-kv span { color: var(--nc-text-dim, #6b7f9e); letter-spacing: 0.1em; min-width: 5rem; }
.bwv-kv b { color: var(--nc-text, #d6e2f2); font-weight: 600; }
.bwv-ms { display: grid; grid-template-columns: 1.2rem 1fr auto auto; gap: 0.45rem; align-items: center;
  font-size: 0.55rem; padding: 0.12rem 0; }
.bwv-ms-n { color: var(--nc-text-dim, #6b7f9e); }
.bwv-ms-t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bwv-spec { font-size: 0.55rem; line-height: 1.6; color: var(--nc-text-dim, #8fa3c0); margin: 0.3rem 0; }
.bwv-ev { display: flex; justify-content: space-between; font-size: 0.53rem; color: var(--nc-text-dim, #6b7f9e); }
.bwv-sec { margin: 0.9rem 0 0.2rem; padding-top: 0.5rem; border-top: 1px solid rgba(120, 160, 210, 0.14); }
.bwv-sec-t { font-size: 0.55rem; letter-spacing: 0.14em; color: var(--nc-text-dim, #8fa3c0); }
.bwv-foot { display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap;
  padding: 0.45rem 0.8rem; border-top: 1px solid var(--nc-border, rgba(120, 160, 210, 0.14)); }
.bwv-door { display: inline-flex; align-items: center; gap: 0.25rem; background: transparent;
  border: 1px solid var(--nc-border, rgba(120, 160, 210, 0.18)); border-radius: 3px;
  padding: 0.15rem 0.5rem; cursor: pointer; font-family: inherit;
  font-size: 0.55rem; letter-spacing: 0.12em; color: var(--nc-text-dim, #8fa3c0); }
.bwv-door:hover { color: var(--nc-primary, #22d3ee); }
.bwv-foot-note { font-size: 0.5rem; letter-spacing: 0.06em; color: var(--nc-text-dim, #5f708a); }

/* §POCKETBRIDGE4 — offered guild actions */
.bwv-acts { display: flex; flex-direction: column; gap: 0.3rem; margin: 0.35rem 0; padding: 0.35rem 0.4rem; border: 1px solid rgba(34, 211, 238, 0.18); border-radius: 6px; }
.bwv-note { margin: 0; font-size: 0.58rem; color: var(--nc-text-dim, #8fa3c0); }
.bwv-act-row { display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap; }
.bwv-in { width: 6.5rem; background: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 5px; padding: 0.22rem 0.4rem; color: inherit; font-family: inherit; font-size: 0.62rem; outline: none; }
.bwv-in-wide { flex: 1 1 10rem; width: auto; min-width: 0; }
.bwv-in:focus { border-color: rgba(34, 211, 238, 0.45); }
.bwv-act { background: rgba(34, 211, 238, 0.1); border: 1px solid rgba(34, 211, 238, 0.35); border-radius: 5px; padding: 0.22rem 0.55rem; cursor: pointer; font-family: inherit; font-size: 0.58rem; letter-spacing: 0.08em; color: var(--nc-primary, #22d3ee); }
.bwv-act:disabled { opacity: 0.45; cursor: default; }
.bwv-act.is-money { background: rgba(52, 211, 153, 0.1); border-color: rgba(52, 211, 153, 0.4); color: #34d399; }
.bwv-act.is-danger { background: rgba(248, 113, 113, 0.08); border-color: rgba(248, 113, 113, 0.35); color: #f87171; }
.bwv-bidline { font-size: 0.6rem; color: var(--nc-text-dim, #8fa3c0); }
.bwv-award { display: flex; flex-direction: column; gap: 0.25rem; }

/* §POCKETBRIDGE5 A' — disputes grown up in place */
.bwv-fd { display: flex; flex-direction: column; gap: 0.3rem; margin: 0.1rem 0 0.5rem; }
.bwv-fd-form { display: flex; flex-wrap: wrap; gap: 0.3rem; padding: 0.35rem 0.4rem; border: 1px solid rgba(248, 113, 113, 0.22); border-radius: 6px; }
.bwv-fd-note { margin: 0; font-size: 0.6rem; }
.bwv-fd-note.ok { color: #34d399; }
.bwv-fd-note.bad { color: #f87171; }
.bwv-comp { display: flex; align-items: center; gap: 0.3rem; flex-wrap: wrap; margin: 0.25rem 0; font-size: 0.62rem; color: #34d399; }
.bwv-ev-item { display: flex; flex-direction: column; gap: 0.1rem; padding: 0.25rem 0 0.25rem 0.5rem; border-left: 2px solid rgba(255, 255, 255, 0.1); margin: 0.15rem 0; }
.bwv-ev-head { font-size: 0.52rem; letter-spacing: 0.08em; text-transform: uppercase; color: var(--nc-text-dim, #8fa3c0); }
.bwv-ev-body { font-size: 0.64rem; white-space: pre-wrap; word-break: break-word; }
.bwv-ev-link { font-size: 0.62rem; color: var(--nc-primary, #22d3ee); word-break: break-all; }
.bwv-ev-desc { font-size: 0.56rem; color: var(--nc-text-dim, #8fa3c0); }

/* Phone comfort (his rule: the modal itself is the pocket surface — no new
 * chrome). Coarse pointers get the touch floors; 16px inputs stop iOS zoom. */
@media (pointer: coarse) {
  .bwv-in { font-size: 16px; min-height: 44px; }
  .bwv-act { min-height: 44px; padding: 0.3rem 0.7rem; font-size: 0.68rem; }
  .bwv-row-btn { min-height: 44px; }
  .bwv-fd-form { gap: 0.4rem; }
}
</style>
