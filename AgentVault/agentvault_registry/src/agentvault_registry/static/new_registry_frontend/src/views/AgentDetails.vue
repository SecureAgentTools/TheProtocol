<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import { ref, computed, onMounted, onErrorCaptured, watch } from 'vue'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)
import { useRoute, useRouter } from 'vue-router'
import { useAgentStore } from '@/stores/agents'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { apiClient } from '@/services/api/client'
import { agentAuthzApi, type AgentAuthz } from '@/services/api/agentAuthz'
import ZKPVerifiedBadge from '@/components/ZKPVerifiedBadge.vue'
import AgentLineageTree from '@/components/agent/AgentLineageTree.vue'
// §AGENTCOCKPIT T2.1 — the SAME panel the fleet page opens behind its "Access"
// button. One implementation, two mounts: roles, spend, delegation, grants and
// capability tokens were all editable there and read-only here, for the same
// agent, on the same account.
import AgentAccessPanel from '@/components/agent/AgentAccessPanel.vue'
import { refusalText } from '@/components/agent/accessRefusal'
import { isWalletAgent, walletHowItWorks } from '@/services/walletAgent'
import { reputationBondApi, type ReputationBlock, hiddenUntilBonded } from '@/services/api/reputationBond'
import BondMaturityBar from '@/components/discovery/BondMaturityBar.vue'
// §FLARESHOP (2026-08-16): the owner surface reuses the SAME panels the public
// discovery modal renders. Before this, a stranger could see an agent's proven
// work and its cosmetic flare while the agent's own developer could not.
import TrackRecordPanel from '@/components/common/TrackRecordPanel.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'

const { t, tp } = useI18n()
const { localCurrency } = useCurrency()
const route = useRoute()
const router = useRouter()
const agentStore = useAgentStore()
const authStore = useAuthStore()
const uiStore = useUIStore()

// ── State ─────────────────────────────────────────────────────────────────
/**
 * §AGENTCOCKPIT T3 (2026-08-30) — SEVEN TABS BECAME FOUR, because the seven were
 * not seven questions. GOVERNANCE and DISPUTES carried the same weight as the
 * agent's authority while being rare events, the A2A card had no home of its own
 * (its skills and protocol hid under CAPABILITIES beside IRONKEY roles, two
 * unrelated subjects on one screen), and the OVERVIEW was 1,231 characters.
 *
 * The four an owner actually asks:
 *   card    — what is it, what can it do, what does it charge, how do I reach it
 *   access  — what may it do, and with whose credentials
 *   work    — what has it done and what did that move
 *   runtime — is it alive, and where did it come from
 *
 * The per-tab CONTENT blocks are unchanged; only which tab they answer to moved.
 * A regroup that rewrites the markup is a regroup whose diff nobody can read.
 */
type Tab = 'card' | 'access' | 'work' | 'runtime'
const activeTab = ref<Tab>('card')
const copiedText = ref<string | null>(null)


// Agent data
const agent = ref<any>(null)
// §FLARESHOP (2026-08-16) — owner-side reflections of the public surface.
// `ownerTrackHas` mirrors the panel's own state emit so the section disappears
// entirely for an agent with no history (honest zero, not an empty box).
const ownerTrackHas = ref(false)

// §DISCREFINE — strictly the OWNER (no admin bypass; the backend agrees).
// §WALLETAGENT — a wallet card says what it is and how the identity is reused.
const isWalletCard = computed(() => isWalletAgent(agent.value))

// §REPBOND — skin in the game
const bondState = ref<ReputationBlock | null>(null)
const bondBusy = ref(false)
const bondError = ref('')
const walletAgentForBond = computed(() => {
  const mine = useAgentStore().agents || []
  return mine.find((a: any) => isWalletAgent(a) && a.did !== agentDid.value) || null
})
function bondStatusLabel(status: string | null | undefined): string {
  const k = status || 'none'
  const map: Record<string, [string, string]> = {
    none: ['agentDetails.bond.status.none', 'No bond'],
    pending: ['agentDetails.bond.status.pending', 'Bond pending'],
    locked: ['agentDetails.bond.status.locked', 'Bonded'],
    matured: ['agentDetails.bond.status.matured', 'Bond matured'],
    released: ['agentDetails.bond.status.released', 'Bond released'],
    forfeited: ['agentDetails.bond.status.forfeited', 'Bond forfeited'],
    voided: ['agentDetails.bond.status.voided', 'Legacy bond voided'],
  }
  const [key, fb] = map[k] || map.none
  return t(key, fb)
}
function bondFundedLabel(by: string): string {
  const map: Record<string, [string, string]> = {
    self: ['agentDetails.bond.funded.self', 'funded from its own balance'],
    wallet: ['agentDetails.bond.funded.wallet', 'funded from a wallet agent'],
    treasury: ['agentDetails.bond.funded.treasury', 'demonstration: underwritten by the treasury'],
  }
  const [key, fb] = map[by] || ['agentDetails.bond.funded.unknown', by]
  return t(key, fb)
}
// §BONDFILL-3 — the maturity bar is ONE component (components/discovery/BondMaturityBar.vue), in its
// detailed mode here. This view used to draw its own rows from the ABSOLUTE trust keys the relative
// gate retired, so it would have rendered a broken row: a second renderer is a second place to forget a change.
/** The owner's door to the maturity unlock. Shown only to the owner, and only with the backend's
 *  own verdict on whether it can be pressed now, so the button never offers what the rail refuses. */
const bondUnlock = computed(() => bondState.value?.bond?.unlock || null)
const unlockReasonText = computed(() => {
  const u = bondUnlock.value
  if (!u || u.available) return ''
  const map: Record<string, [string, string]> = {
    not_matured: ['agentDetails.bond.unlock.notMatured', 'Unlocks at maturity, when all three conditions are met.'],
    already_unlocked: ['agentDetails.bond.unlock.already', 'The maturity share was already unlocked. What remains keeps this agent trading.'],
    frame_releases_nothing: ['agentDetails.bond.unlock.none', 'This registry releases no capital at maturity.'],
    treasury_backstop: ['agentDetails.bond.unlock.treasury', 'A treasury-backstopped bond holds none of your capital, so there is nothing to unlock.'],
    cooldown: ['agentDetails.bond.unlock.cooldown', 'The unlock opens after the cooldown.'],
  }
  const [k, fb] = map[u.reason || ''] || ['agentDetails.bond.unlock.unavailable', 'Not available yet.']
  return t(k, fb)
})
async function unlockBond() {
  const did = agentDid.value
  if (!did) return
  bondBusy.value = true; bondError.value = ''
  try { await reputationBondApi.unlock(did); await loadBond() }
  catch (e: any) { bondError.value = e?.response?.data?.detail?.message || e?.response?.data?.detail || e?.message || 'Unlock failed' }
  finally { bondBusy.value = false }
}
// §FESUITE (V0575): a bond read that failed said "Reading the bond…" for good; it now says the read failed
const bondFailed = ref(false)
async function loadBond() {
  bondState.value = null
  bondFailed.value = false
  const did = agentDid.value
  if (!did) return
  try { bondState.value = await reputationBondApi.getAgentReputation(did) } catch { bondState.value = null; bondFailed.value = true }
}
async function bondFromWallet() {
  const did = agentDid.value, w = walletAgentForBond.value
  if (!did || !w) return
  bondBusy.value = true; bondError.value = ''
  try { await reputationBondApi.bondFromWallet(did, w.did); await loadBond() }
  catch (e: any) { bondError.value = e?.response?.data?.detail?.message || e?.response?.data?.detail || e?.message || 'Bond failed' }
  finally { bondBusy.value = false }
}
async function bondBackstop() {
  const did = agentDid.value
  if (!did) return
  bondBusy.value = true; bondError.value = ''
  try { await reputationBondApi.bondBackstop(did); await loadBond() }
  catch (e: any) { bondError.value = e?.response?.data?.detail?.message || e?.response?.data?.detail || e?.message || 'Bond failed' }
  finally { bondBusy.value = false }
}
const walletLines = computed(() => walletHowItWorks(t))
const isListingOwner = computed<boolean>(() => {
  const ownerId = (agent.value as any)?.creator_developer_id
  if (ownerId == null) return false
  const u = authStore.user as any
  if (!u) return false
  return [u.developer_id, u.id].filter((v: any) => v != null).map(String).includes(String(ownerId))
})
const listingUnlisted = ref(false)
// the registry enforces the bond and this agent holds none: discovery does not show it yet, whatever the toggle says
const bondHidesListing = computed(() => hiddenUntilBonded(bondState.value))
const listingBusy = ref(false)
const listingErr = ref('')
async function toggleListing(ev: Event) {
  const showIt = (ev.target as HTMLInputElement).checked
  listingBusy.value = true; listingErr.value = ''
  try {
    const { data } = await apiClient.patch(`/agent-cards/${encodeURIComponent(agentDid.value)}/listing`, { unlisted: !showIt })
    listingUnlisted.value = !!data?.unlisted
  } catch (e: any) {
    // Never let the checkbox drift from the server's answer on a failure. §FESUITE (2026-10-10): the box is the
    // element the person pressed; the state it binds did not change, so Vue had nothing to re-render and the box kept
    // the refused state (this line set the ref to itself). Put the element back to what the server holds.
    listingErr.value = refusalText(e, 'could not change the listing')
    ;(ev.target as HTMLInputElement).checked = !listingUnlisted.value
  } finally { listingBusy.value = false }
}
const agentDid = computed<string>(() => (agent.value as any)?.did || (agent.value as any)?.agent_did || '')
// §REPBOND — declared BELOW the ref it watches (§HIRECOHERE's TDZ class): the bond loads once the DID is known.
watch(agentDid, (d) => { if (d) void loadBond() }, { immediate: true })
const agentEndpoint = computed<string>(() => {
  const cd: any = (agent.value as any)?.card_data || {}
  return cd.url || cd.endpoint || (agent.value as any)?.agent_host || ''
})
// The per-agent flare rides in `card_data.flare` (the sidecar that
// routers/agent_cards.py::_inject_flare_into_card_data writes, identical in
// shape to the federation export). There is no top-level flare_tier on this
// endpoint's payload; reading one always yielded undefined and rendered a
// confident "no cosmetic flare" for agents that had one. Found by the #207
// battery buying a flare and then not seeing it.
const agentFlareTier = computed<string | null>(() => {
  const a: any = agent.value
  return flareFromCard.value || a?.card_data?.flare?.tier || a?.flare_tier || null
})

// `loadAgent()` prefers a cached entry from the agents STORE (see its own step
// 2), and those list rows carry no flare sidecar — so a flare bought a moment
// ago was invisible here, and the view said "no cosmetic flare" with confidence
// it had not earned. One targeted GET for the card settles it: the sidecar the
// serve-time injector writes is authoritative, and asking is cheaper than
// being wrong.
const flareFromCard = ref<string | null>(null)
async function loadFlareFromCard() {
  flareFromCard.value = null
  const did = agentDid.value
  if (!did) return
  try {
    const { data } = await apiClient.get(`/agent-cards/${encodeURIComponent(did)}`)
    flareFromCard.value = (data as any)?.card_data?.flare?.tier || null
    // §DISCREFINE — hydrate the listing toggle from the server, never from a guess.
    listingUnlisted.value = !!(data as any)?.unlisted
  } catch { /* absent flare and unreachable card look the same to the caller:
               we simply make no claim, which is the honest default */ }
}

function prettyFlare(tier: string): string {
  return String(tier).split(/[-_]/).map(p => p.charAt(0).toUpperCase() + p.slice(1)).join(' ')
}
const loading = ref(true)
const notFound = ref(false)

// Last render/mount error caught inside this component — surfaced visibly.
const boundaryError = ref<string | null>(null)

// If anything inside the template throws at render time, catch it here
// and display a visible red panel instead of letting Vue blank the slot.
onErrorCaptured((err: unknown) => {
  const msg = err instanceof Error ? (err.stack || err.message) : String(err)
  boundaryError.value = msg
  // eslint-disable-next-line no-console
  console.error('[AgentDetails] captured render error:', err)
  return false  // stop propagation — we're handling it
})

// Transactions
const transactions = ref<any[]>([])
const txLoading = ref(false)
const txLimit = ref(50)
// AGD3 (audit 2026-05-07): per-tab error refs surface backend failures
// instead of silently showing "no data" forever.
const txError = ref<string>('')

// Governance
const proposals = ref<any[]>([])
const govLoading = ref(false)
const govError = ref<string>('')

// Disputes
const disputes = ref<any[]>([])
const dispLoading = ref(false)
const dispError = ref<string>('')

// Metrics
const metrics = ref<any>(null)
const metricsLoading = ref(false)
const metricsError = ref<string>('')

// IRONKEY authorization (roles + effective permissions + delegation) — shown on
// the CAPABILITIES tab. Owner/admin only: the backend 403s /agents/{did}/authz
// for anyone else, so we never fetch it (nor render it) unless canSeeAuthz.
const authz = ref<AgentAuthz | null>(null)
const authzLoading = ref(false)
const authzError = ref<string>('')

// §AGENTCOCKPIT T3 — the glance strip's derived facts. Both read what is already
// loaded; neither triggers a fetch of its own.
const spendCeiling = computed<string>(() => {
  if (!authz.value) return '—'
  const v = (authz.value.spend_policy as any)?.max_per_tx
  return (v === null || v === undefined || v === '') ? t('agentDetails.gUncapped', 'uncapped') : String(v)
})
const handCount = ref<number | null>(null)
/** TOTAL earns its tile only when it reads differently from LIQUID at the
 *  precision the tile actually shows — comparing the numbers, not the strings,
 *  would keep a tile that displays the same glyphs. */
const totalDiffers = computed(() => {
  try { return formatAVT(totalBalance.value) !== formatAVT(Number(agent.value?.liquid_balance || 0)) }
  catch { return true }
})

// Edit mode
const isEditing = ref(false)
// §AGENTCOCKPIT T1.2 — `status` left this form with the select; the card is what
// this screen edits, and status is not on it.
const editForm = ref<{ name: string; description: string }>({ name: '', description: '' })
const isSaving = ref(false)

// ── Load Agent ────────────────────────────────────────────────────────────
// Resolution order is intentionally fast-path first:
//   1. Store cache (instant — covers the common nav-from-MyAgents case).
//   2. Direct /agents/by-did API (~50ms — covers deep-link-to-DID cold loads).
//   3. agentStore.fetchAgentById (handles numeric/UUID identifiers).
//   4. Whole-fleet fetchMyAgents (slow — only used if all else fails AND we
//      have no DID-shaped identifier to query the API directly).
//
// The previous order called fetchMyAgents *before* the by-DID API, which
// blocked rendering for several seconds on accounts with many agents because
// fetchMyAgents enriches balances via batched POSTs. Reordering moves the
// expensive call to last-resort.
async function loadAgent() {
  loading.value = true
  notFound.value = false
  const agentId = route.params.agentId as string

  // 1. Check store first (instant)
  if (agentStore.currentAgent?.did === agentId) {
    agent.value = agentStore.currentAgent
  }
  if (!agent.value && agentStore.agents.length) {
    const found = agentStore.agents.find(a =>
      a.did === agentId ||
      a.card_data?.humanReadableId === agentId ||
      String(a.id) === agentId
    )
    if (found) agent.value = found
  }

  // 2. Direct /agents/by-did API — fastest cold path for DID-shaped IDs
  if (!agent.value && agentId?.startsWith('did:')) {
    try {
      const res = await apiClient.get(`/agents/by-did/${encodeURIComponent(agentId)}`)
      if (res.data) {
        agent.value = {
          ...res.data,
          name: res.data.name || res.data.card_data?.name || 'Unnamed Agent',
          description: res.data.description || res.data.card_data?.description || '',
        }
      }
    } catch { /* fall through */ }
  }

  // 3. fetchAgentById in the store (numeric IDs, UUIDs, etc.)
  if (!agent.value) {
    try {
      await agentStore.fetchAgentById(agentId)
      if (agentStore.currentAgent) agent.value = agentStore.currentAgent
    } catch { /* fall through */ }
  }

  // 4. Last resort: load the full fleet and search there.
  // 2026-05-09: explicit limit=500 bumps the search surface to the server's
  // hard cap; for owners of >500 agents the by-DID API in step 2 is the
  // realistic resolver anyway — this fallback is just a safety net.
  if (!agent.value && !agentStore.agents.length) {
    try {
      await agentStore.fetchMyAgents(undefined, { limit: 500 })
      const found = agentStore.agents.find(a =>
        a.did === agentId ||
        a.card_data?.humanReadableId === agentId ||
        String(a.id) === agentId
      )
      if (found) agent.value = found
    } catch { /* exhausted */ }
  }

  if (!agent.value) notFound.value = true
  loading.value = false
}

// ── Tab Data Loaders ──────────────────────────────────────────────────────
function _errMsg(e: any): string {
  return e?.response?.data?.detail || e?.response?.data?.error?.detail || e?.message || 'Failed to load.'
}

async function loadTransactions() {
  if (!agent.value?.did || txLoading.value) return
  txLoading.value = true
  txError.value = ''
  try {
    const res = await apiClient.get(`/teg/transactions/history/${encodeURIComponent(agent.value.did)}`, {
      params: { limit: txLimit.value }
    })
    transactions.value = res.data?.transactions || res.data || []
  } catch (e: any) {
    transactions.value = []
    txError.value = _errMsg(e)
  } finally {
    txLoading.value = false
  }
}

async function loadGovernance() {
  if (govLoading.value) return
  govLoading.value = true
  govError.value = ''
  try {
    // AGD1 (audit 2026-05-07): backend doesn't support a proposer_did query
    // param, so we still filter client-side. But pass include_closed=true +
    // bump limit so closed/passed/applied proposals proposed by this agent
    // are visible (was: only VOTING proposals returned, hiding history).
    const res = await apiClient.get('/governance/proposals', {
      params: { include_closed: true, limit: 200 }
    })
    const all = res.data || []
    proposals.value = all.filter((p: any) => p.proposer_did === agent.value?.did)
  } catch (e: any) {
    proposals.value = []
    govError.value = _errMsg(e)
  } finally {
    govLoading.value = false
  }
}

async function loadDisputes() {
  if (dispLoading.value) return
  dispLoading.value = true
  dispError.value = ''
  try {
    // AGD2 (audit 2026-05-07): use server-side filtering. Backend supports
    // ?defendant_did=X and ?complainant_did=X (separate filters). We make 2
    // parallel calls and merge by id — eliminates the previous over-fetch
    // (was: fetched ALL disputes then client-side filter).
    const did = agent.value?.did
    if (!did) { disputes.value = []; return }
    const [asComp, asDef] = await Promise.all([
      apiClient.get('/disputes/', { params: { complainant_did: did, limit: 100 } }).catch(() => ({ data: [] as any[] })),
      apiClient.get('/disputes/', { params: { defendant_did:   did, limit: 100 } }).catch(() => ({ data: [] as any[] })),
    ])
    const merged: Record<string | number, any> = {}
    for (const d of (asComp.data || [])) merged[d.id] = d
    for (const d of (asDef.data || []))  merged[d.id] = d
    disputes.value = Object.values(merged)
  } catch (e: any) {
    disputes.value = []
    dispError.value = _errMsg(e)
  } finally {
    dispLoading.value = false
  }
}

async function loadMetrics() {
  if (!agent.value?.id && !agent.value?.did || metricsLoading.value) return
  metricsLoading.value = true
  metricsError.value = ''
  try {
    // 🔴 THIS ASKED WITH THE ONE IDENTIFIER THE ENDPOINT CANNOT RESOLVE.
    // `/agent-metrics/{agent_id}` matches a `did:`-prefixed value against
    // agents.did and ANY OTHER value against agents.CLIENT_ID — never the
    // primary key. So `agent.value.id` (226) missed, and the endpoint answered
    // `create_empty_metrics_response()`: all zeros, HTTP 200. Every agent's
    // metrics read 0 no matter how much traffic it had served. Measured on
    // Ironhand Alpha the same minute: did -> 118,270 · client_id -> 118,270 ·
    // id 226 -> 0. A miss that returns 200 with a zeroed body is indistinguishable
    // from an idle agent, which is why this survived.
    const key = agent.value.did || agent.value.client_id || agent.value.id
    const res = await apiClient.get(`/agent-metrics/${encodeURIComponent(key)}`)
    metrics.value = res.data
  } catch (e: any) {
    metrics.value = null
    metricsError.value = _errMsg(e)
  } finally {
    metricsLoading.value = false
  }
}

// IRONKEY roles / effective permissions / delegation for this agent.
// Caller must gate on canSeeAuthz — this endpoint is owner/admin-only server-side.
async function loadAuthz() {
  if (!agent.value?.did || authzLoading.value) return
  authzLoading.value = true
  authzError.value = ''
  try {
    authz.value = await agentAuthzApi.get(agent.value.did)
  } catch (e: any) {
    authz.value = null
    authzError.value = _errMsg(e)
  } finally {
    authzLoading.value = false
  }
}

// Tab switch handler
watch(activeTab, (tab) => {
  // §AGENTCOCKPIT T1.4 — edit mode used to survive a tab change, so SAVE/CANCEL
  // stayed pinned to the header while you were on CAPABILITIES, where nothing on
  // screen is editable by that form. Editing is an OVERVIEW act; leaving it ends.
  if (tab !== 'card' && isEditing.value) isEditing.value = false
  if (tab === 'work') {
    if (!transactions.value.length) loadTransactions()
    if (!proposals.value.length) loadGovernance()
    if (!disputes.value.length) loadDisputes()
  }
  if (tab === 'runtime' && !metrics.value) loadMetrics()
  if (tab === 'access' && canSeeAuthz.value && !authz.value) loadAuthz()
})

// ── Computed ──────────────────────────────────────────────────────────────
const agentName = computed(() => {
  if (!agent.value) return ''
  return agent.value.name || agent.value.card_data?.name ||
    agent.value.card_data?.humanReadableId || 'Unnamed Agent'
})

const totalBalance = computed(() =>
  parseFloat(agent.value?.liquid_balance || 0) + parseFloat(agent.value?.staked_balance || 0)
)

const repTier = computed(() => {
  const s = agent.value?.reputation_score || 0
  if (s >= 51) return { label: 'Sovereign', color: '#a78bfa' }
  if (s >= 10) return { label: 'Platinum', color: '#67e8f9' }
  if (s >= 7)  return { label: 'Gold',     color: '#fbbf24' }
  if (s >= 4)  return { label: 'Silver',   color: '#94a3b8' }
  if (s >= 1)  return { label: 'Bronze',   color: '#d97706' }
  return { label: 'Unranked', color: '#475569' }
})

// ── Access gating ───────────────────────────────────────────────────────────
// RBAC roles/permissions and the sub-agent lineage tree reveal authorization
// info, so they are shown ONLY to the agent's OWNER or an ADMIN. The backend
// 403s /agents/{did}/authz and /agents/{did}/lineage for anyone else, so an
// ungated FE would 403-flash / show a forbidden panel to non-owners.
const canSeeAuthz = computed<boolean>(() => {
  if (authStore.isAdmin) return true
  const ownerId = agent.value?.creator_developer_id
  if (ownerId == null) return false
  const u = authStore.user as any
  if (!u) return false
  // user.developer_id is the numeric dev id; user.id is its string form on some
  // hydration paths. Match either against the agent's numeric creator id.
  return [u.developer_id, u.id].filter((v: any) => v != null).map(String).includes(String(ownerId))
})

// The LINEAGE tab exposes the hand tree + their permissions → owner/admin only.
// Drop it from the tab bar entirely for everyone else.
const visibleTabs = computed<Tab[]>(() => {
  // ACCESS is owner/admin only — it is the authority surface and the backend 403s
  // its reads for anyone else, so showing the tab would promise a forbidden panel.
  const tabs: Tab[] = ['card']
  if (canSeeAuthz.value) tabs.push('access')
  tabs.push('work', 'runtime')
  return tabs
})
const TAB_LABELS: Record<Tab, [string, string]> = {
  card: ['agentDetails.tabCard', 'CARD'],
  access: ['agentDetails.tabAccess', 'ACCESS'],
  work: ['agentDetails.tabWork', 'WORK'],
  runtime: ['agentDetails.tabRuntime', 'RUNTIME'],
}
function tabLabel(tab: Tab): string { const [k, f] = TAB_LABELS[tab]; return t(k, f) }

// Belt-and-suspenders: if a non-owner is ever parked on 'lineage' (stale state,
// deep link), fall back to overview so they never trip the 403 path.
watch(canSeeAuthz, (ok) => {
  if (!ok && activeTab.value === 'access') activeTab.value = 'card'
}, { immediate: true })

// ── Helpers ───────────────────────────────────────────────────────────────
function formatAVT(n: number): string {
  if (!n) return '0'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(3) + 'M'
  return Math.round(n).toLocaleString(appLocale())
}

function formatDate(iso: string): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(appLocale(), {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit'
  })
}

function formatTimeAgo(iso: string | null): string {
  if (!iso) return '—'
  return dayjs(iso).fromNow()
}

function statusColor(s: string): string {
  if (s === 'active') return '#10b981'
  if (s === 'maintenance') return '#f59e0b'
  return '#ef4444'
}

function disputeRulingColor(ruling: string | null): string {
  if (!ruling) return 'rgba(148,163,184,0.5)'
  if (ruling.includes('COMPLAINANT')) return '#10b981'
  if (ruling.includes('DEFENDANT')) return '#ef4444'
  return '#f59e0b'
}

function txDirection(tx: any): 'in' | 'out' {
  const did = agent.value?.did
  return (tx.receiver === did || tx.details?.to === did) ? 'in' : 'out'
}

function peerDid(tx: any): string {
  const did = agent.value?.did
  const from = tx.sender || tx.details?.from || ''
  const to = tx.receiver || tx.details?.to || ''
  const peer = from === did ? to : from
  return peer ? (peer.slice(0, 22) + '…') : '—'
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedText.value = text
    setTimeout(() => { if (copiedText.value === text) copiedText.value = null }, 1500)
  } catch { /* expected */ }
}

function startEdit() {
  if (!isListingOwner.value) return
  editForm.value = {
    name: agentName.value,
    description: agent.value?.description || '',
  }
  isEditing.value = true
}

/**
 * §AGENTCOCKPIT T1.1 (2026-08-30) — THIS FORM USED TO WRITE NOTHING AND SAY IT HAD.
 *
 * It posted `{name, description, status}` at the TOP LEVEL of PUT
 * /agent-cards/{did}, whose body schema is:
 *     class AgentCardUpdate(BaseModel):
 *         card_data: Optional[Dict[str, Any]] = None
 *         is_active: Optional[bool] = None
 * with no `extra="forbid"`, so pydantic DROPPED all three before the handler ran.
 * Proven in the running container, not reasoned:
 *     AgentCardUpdate(name="NEW NAME", description="NEW DESC", status="inactive")
 *       -> {'card_data': None, 'is_active': None}   has name attr: False
 * `crud.update_agent_card` then set update_data_provided = False, skipped the
 * commit and returned the row untouched — HTTP 200. The old code merged that
 * unchanged response into local state and popped "Saved", so the screen looked
 * right until you reloaded. `db_card.name`/`.description` are written ONLY from
 * validated `card_data`, so there was never a path from this form to the DB.
 *
 * The card is the record: name and description go through `card_data`, which the
 * CRUD merges over the existing document, validates against the A2A model and
 * canonicalizes. `status` is gone from this form entirely — see the template.
 */
async function saveEdit() {
  if (!agent.value) return
  const name = (editForm.value.name || '').trim()
  if (!name) { uiStore.showError(t('agentDetails.saveFailed', 'Could not save'),
                                 t('agentDetails.nameRequired', 'An agent card must carry a name.')); return }
  isSaving.value = true
  try {
    const body = { card_data: { ...(agent.value.card_data || {}), name,
                                description: editForm.value.description || '' } }
    const { data } = await apiClient.put(`/agent-cards/${encodeURIComponent(agent.value.did)}`, body)
    // Read the RESULT back rather than assuming it: the whole defect above was a
    // write that reported success while changing nothing.
    agent.value.card_data = data?.card_data || agent.value.card_data
    agent.value.name = data?.name ?? name
    agent.value.description = data?.description ?? editForm.value.description
    const i = agentStore.agents.findIndex((a: any) => a.did === agent.value!.did)
    if (i !== -1) agentStore.agents[i] = { ...agentStore.agents[i], name: agent.value.name,
                                           description: agent.value.description }
    isEditing.value = false
    uiStore.showSuccess(t('agentDetails.saved', 'Saved'), agent.value.name)
  } catch (e: any) {
    uiStore.showError(t('agentDetails.saveFailed', 'Could not save'), _errMsg(e))
  } finally {
    isSaving.value = false
  }
}

// Navigating between agents (a parent ↔ hand link in the lineage tree) is the SAME
// 'agent-details' route with a different :agentId, so vue-router REUSES this component
// instance and onMounted does NOT re-run — the address bar changes but the view stays
// on the previous agent until a full reload (F5). Re-load everything on param change.
watch(() => route.params.agentId, async (newId, oldId) => {
  if (!newId || newId === oldId) return
  // drop the previous agent's data so nothing stale flashes through
  agent.value = null
  boundaryError.value = null
  notFound.value = false
  isEditing.value = false
  transactions.value = []; txError.value = ''; txLoading.value = false
  proposals.value = []; govError.value = ''; govLoading.value = false
  disputes.value = []; dispError.value = ''; dispLoading.value = false
  metrics.value = null; metricsError.value = ''; metricsLoading.value = false
  authz.value = null; authzError.value = ''; authzLoading.value = false
  await loadAgent()
  loadFlareFromCard()
  // re-dispatch whichever tab is active for the NEW agent (mirrors onMounted)
  if (activeTab.value === 'work') { loadTransactions(); loadGovernance(); loadDisputes() }
  else if (activeTab.value === 'runtime') loadMetrics()
  else if (activeTab.value === 'access' && canSeeAuthz.value) loadAuthz()
})

// ── Init ──────────────────────────────────────────────────────────────────
onMounted(async () => {
  if (route.query.edit === 'true') {
    await loadAgent()
    startEdit()
  } else {
    await loadAgent()
  }
  loadFlareFromCard()
  // §AGENTCOCKPIT T3 — the glance strip's two owner-only facts. Best-effort and
  // never blocking: a strip that cannot answer shows an em dash, which is why
  // both refs start at null rather than 0.
  if (canSeeAuthz.value) {
    void loadAuthz()
    void apiClient.get(`/agents/${encodeURIComponent(agentDid.value)}/lineage`)
      .then(r => { handCount.value = Array.isArray(r?.data?.hands) ? r.data.hands.length : 0 })
      .catch(() => { handCount.value = null })
  }
  // Eagerly load whichever tab is active on mount
  if (activeTab.value === 'work') { loadTransactions(); loadGovernance(); loadDisputes() }
  else if (activeTab.value === 'runtime') loadMetrics()
  else if (activeTab.value === 'access' && canSeeAuthz.value) loadAuthz()
})
</script>

<template>
  <div class="ad-root">

    <!-- ── Caught render error (surfaced by onErrorCaptured) ───────────── -->
    <div v-if="boundaryError" class="ad-boundary-error">
      <div class="ad-boundary-title">
        <span class="ad-boundary-dot" />
        AGENT DETAILS RENDER ERROR
      </div>
      <pre class="ad-boundary-msg">{{ boundaryError }}</pre>
      <div class="ad-boundary-actions">
        <button class="ad-boundary-btn" @click="boundaryError = null">Dismiss</button>
        <button class="ad-boundary-btn" @click="() => { boundaryError = null; loadAgent() }">Retry Load</button>
        <button class="ad-boundary-btn" @click="router.push({ name: 'my-agents' })">← Back to Fleet</button>
      </div>
    </div>

    <!-- ── Always-visible safety header ──────────────────────────────────
         Renders unconditionally so the page is NEVER fully blank, even if
         a downstream computed/template throws inside the agent branch.
         When the full content loads, the agent branch's own topbar takes
         visual primacy. -->
    <div v-if="!agent || loading" class="ad-safety-header">
      <button class="ad-back-btn" @click="router.push({ name: 'my-agents' })">← My Fleet</button>
      <div class="ad-safety-id">
        <span class="ad-safety-label">AGENT</span>
        <code class="ad-safety-did">{{ route.params.agentId }}</code>
      </div>
    </div>

    <!-- ── Loading ─────────────────────────────────────────────────────── -->
    <div v-if="loading" class="ad-loading">
      <div class="loading-ring" />
      <span>Resolving agent identity…</span>
    </div>

    <!-- ── Not Found ───────────────────────────────────────────────────── -->
    <div v-else-if="notFound" class="ad-notfound">
      <div class="nf-glyph">◌</div>
      <h3>Agent not found</h3>
      <p>No agent matched identifier: <code>{{ route.params.agentId }}</code></p>
      <button class="ad-back-btn" @click="router.push({ name: 'my-agents' })">← Back to Fleet</button>
    </div>

    <!-- ── Agent Content ───────────────────────────────────────────────── -->
    <template v-else-if="agent">

      <!-- Top bar -->
      <div class="ad-topbar">
        <button class="ad-back-btn" @click="router.push({ name: 'my-agents' })">← My Fleet</button>
        <div class="ad-breadcrumb">
          <span class="bc-sep">/</span>
          <span class="bc-agent">Agent</span>
          <span class="bc-sep">/</span>
          <span class="bc-name">{{ agentName }}</span>
        </div>
        <div class="ad-topbar-right">
          <!-- §FESUITE — the card is its owner's to edit (PUT /agent-cards/{did} refuses anyone else, admins included):
               a non-owner used to get EDIT and SAVE, and a "Could not save" after typing. -->
          <template v-if="isListingOwner">
            <button v-if="!isEditing" class="ad-edit-btn" @click="startEdit">EDIT</button>
            <template v-else>
              <button class="ad-save-btn" :disabled="isSaving" @click="saveEdit">
                {{ isSaving ? 'SAVING…' : 'SAVE' }}
              </button>
              <button class="ad-cancel-btn" @click="isEditing = false">CANCEL</button>
            </template>
          </template>
        </div>
      </div>

      <!-- §FESUITE — someone else's agent: say whose view this is (its public card), so "My Fleet" above does not
           read as this person's own. -->
      <p v-if="authStore.user && !isListingOwner" class="ad-notmine" role="note" data-testid="agd-not-yours">
        {{ t('agentDetails.notYours', "This agent belongs to another developer: you see its public card. Editing it and its owner's pages stay with them.") }}
      </p>

      <!-- Identity Header -->
      <div class="ad-header">
        <div class="ad-identity">
          <div class="ad-status-row">
            <span class="ad-status-dot" :style="{ background: statusColor(agent.status) }" />
            <span class="ad-status-text">{{ agent.status?.toUpperCase() }}</span>
            <span class="ad-last-active">{{ t('agentDetailsView.lastActive', { ago: formatTimeAgo(agent.last_active_at) }) }}</span>
          </div>

          <div v-if="!isEditing">
            <h1 class="ad-name">{{ agentName }}</h1>
          </div>
          <div v-else class="edit-field-group">
            <input v-model="editForm.name" class="edit-input edit-input--name" placeholder="Agent name" />
          </div>

          <div class="ad-did-row">
            <code class="ad-did">{{ agent.did }}</code>
            <button class="copy-btn" @click="copyText(agent.did)">
              {{ copiedText === agent.did ? '✓' : '⧉' }}
            </button>
            <ZKPVerifiedBadge :agent-did="agent.did" />
          </div>
          <div class="ad-client-row">
            <code class="ad-client-id">{{ agent.client_id }}</code>
            <button class="copy-btn" @click="copyText(agent.client_id)">
              {{ copiedText === agent.client_id ? '✓' : '⧉' }}
            </button>
          </div>
        </div>

        <!-- Financial + Reputation summary -->
        <div class="ad-summary-cards">
          <div class="ad-sum-card ad-sum-card--liquid">
            <span class="sum-label">{{ t('agentDetailsView.summary.liquid') }}</span>
            <span class="sum-value">◎ {{ formatAVT(agent.liquid_balance || 0) }}</span>
            <span class="sum-sub">{{ localCurrency }}</span>
          </div>
          <div class="ad-sum-card ad-sum-card--staked">
            <span class="sum-label">{{ t('agentDetailsView.summary.staked') }}</span>
            <span class="sum-value">◉ {{ formatAVT(agent.staked_balance || 0) }}</span>
            <span class="sum-sub">{{ localCurrency }}</span>
          </div>
          <!-- §AGENTCOCKPIT T3 — TOTAL only when it says something LIQUID does not.
               Measured on a real agent: liquid 2,254,639.35 and locked 77 both
               rendered as "2.255M", so a quarter of the header repeated its
               neighbour to four significant figures. A tile that always agrees
               with the tile beside it is not a fourth fact. -->
          <div v-if="totalDiffers" class="ad-sum-card ad-sum-card--total">
            <span class="sum-label">TOTAL</span>
            <span class="sum-value">{{ formatAVT(totalBalance) }}</span>
            <span class="sum-sub">{{ localCurrency }}</span>
          </div>
          <div class="ad-sum-card ad-sum-card--rep">
            <span class="sum-label">REPUTATION</span>
            <span class="sum-value" :style="{ color: repTier.color }">
              {{ repTier.label }}
            </span>
            <span class="sum-sub">Score {{ agent.reputation_score ?? 0 }}</span>
          </div>
        </div>
      </div>

      <!-- ── Tabs ────────────────────────────────────────────────────── -->
      <!-- ═══ AT A GLANCE ═══════════════════════════════════════════════
           §AGENTCOCKPIT T3 — "is this thing alright?" answered without a click.
           Every fact here is one the page already holds or fetches at mount; a
           number that is not known yet renders as an em dash rather than a zero,
           because a confident 0 is a lie about an unfinished fetch. -->
      <div class="ad-glance" data-testid="ad-glance">
        <span class="glance-item"><i>{{ t('agentDetails.gSeen', 'last seen') }}</i>{{ agent.last_active_at ? formatTimeAgo(agent.last_active_at) : '—' }}</span>
        <span v-if="canSeeAuthz" class="glance-item"><i>{{ t('agentDetails.gRoles', 'roles') }}</i>{{ authz ? (authz.roles.length ? authz.roles.join(', ') : t('agentDetails.gNoRoles', 'none')) : '—' }}</span>
        <span v-if="canSeeAuthz" class="glance-item"><i>{{ t('agentDetails.gCeiling', 'per-tx ceiling') }}</i>{{ spendCeiling }}</span>
        <span class="glance-item"><i>{{ t('agentDetails.gDiscovery', 'discovery') }}</i>{{ listingUnlisted ? t('agentDetails.gUnlisted', 'unlisted') : bondHidesListing ? t('agentDetails.gUnbonded', 'hidden until bonded') : t('agentDetails.gListed', 'listed') }}</span>
        <span class="glance-item"><i>{{ t('agentDetails.gHands', 'spawned') }}</i>{{ handCount === null ? '—' : handCount }}</span>
      </div>

      <div class="ad-tabs">
        <button
          v-for="tab in visibleTabs"
          :key="tab"
          class="ad-tab"
          :class="{ 'ad-tab--active': activeTab === tab }"
          @click="activeTab = tab"
        >{{ tabLabel(tab) }}</button>
      </div>

      <!-- ── Tab Content ─────────────────────────────────────────────── -->
      <div class="ad-tab-content">

        <!-- OVERVIEW ──────────────────────────────────────────────────── -->
        <div v-if="activeTab === 'card'" class="tab-body">
          <!-- Description -->
          <div class="ov-section">
            <div class="ov-section-label">DESCRIPTION</div>
            <div v-if="!isEditing" class="ov-desc">
              {{ agent.description || agent.card_data?.description || 'No description.' }}
            </div>
            <textarea v-else v-model="editForm.description" class="edit-textarea" rows="3" placeholder="Agent description" />
          </div>

          <!-- Details grid -->
          <div class="ov-details-grid">
            <div class="ov-detail">
              <span class="od-label">CREATED</span>
              <span class="od-value">{{ formatDate(agent.created_at) }}</span>
            </div>
            <div class="ov-detail">
              <span class="od-label">LAST ACTIVE</span>
              <span class="od-value">{{ formatDate(agent.last_active_at) }}</span>
            </div>
            <div class="ov-detail">
              <span class="od-label">STATUS</span>
              <!-- §AGENTCOCKPIT T1.2 — the editable select is GONE. `agents.status`
                   is 'active' | 'suspended' | 'revoked' (models.py), an ENFORCEMENT
                   state written by the enforcement rail and by soft-delete; live on
                   this frame: active 5253, revoked 254, suspended 3. The two options
                   the old select offered, INACTIVE and MAINTENANCE, are values the
                   column never holds, and nothing in this app could write them
                   anyway. Owner-controllable visibility already has its own control:
                   the DISCOVERY LISTING toggle below. -->
              <span class="od-value" :style="{ color: statusColor(agent.status) }">
                {{ agent.status?.toUpperCase() }}
              </span>
              <span v-if="isEditing" class="od-note">{{ t('agentDetails.statusOwned', 'Set by enforcement, not by the owner.') }}</span>
            </div>
            <div class="ov-detail">
              <span class="od-label">AGENT ID</span>
              <span class="od-value od-mono">{{ agent.id }}</span>
            </div>
            <div class="ov-detail">
              <span class="od-label">PROVIDER</span>
              <span class="od-value">{{ agent.card_data?.provider?.name || '—' }}</span>
            </div>
            <div class="ov-detail">
              <span class="od-label">PROTOCOL</span>
              <span class="od-value od-mono">{{ agent.card_data?.protocolVersion || agent.card_data?.agentVersion || '—' }}</span>
            </div>
          </div>

          <!-- §FLARESHOP (2026-08-16) — THE OWNER'S OWN VIEW OF PUBLIC TRUTH.
               This tab used to end here: a description and six metadata cells,
               then dead space. Everything a stranger can see about this agent in
               Discovery — its proven work, its receipts, its endpoint, its
               cosmetic flare — was missing from the one page its owner opens.
               Same components, same data, no second implementation. -->

          <!-- Proven work: the owner's own receipts, auto-hidden at zero -->
          <div v-if="agentDid" v-show="ownerTrackHas" class="ov-section ov-section--spaced" data-testid="agd-track-record">
            <div class="ov-section-label">{{ t('agentDetails.provenWork', 'PROVEN WORK') }}</div>
            <TrackRecordPanel :did="agentDid" auto-hide :max-rows="5" :agent-name="agent.name || ''"
                              @state="ownerTrackHas = $event.hasHistory" />
          </div>

          <!-- §REPBOND (2026-09-05) — SKIN IN THE GAME: the bond this registry holds in escrow,
               its maturity, the paid volume and the locked units. Owner doors: bond from a wallet
               agent, or (while the registry allows it) the treasury's demonstration backstop. -->
          <div v-if="agentDid" class="ov-section ov-section--spaced" data-testid="agd-bond" :data-bond-status="bondState?.bond?.status || 'unknown'">
            <div class="ov-section-label">{{ t('agentDetails.bond.label', 'SKIN IN THE GAME') }}</div>
            <div v-if="bondState" class="ov-bond">
              <div class="ov-bond-head">
                <span class="ov-bond-chip" :class="'ov-bond-chip--' + (bondState.bond.status || 'none')">
                  <Icon name="mdi:shield-account" />
                  {{ bondStatusLabel(bondState.bond.status) }}
                </span>
                <span v-if="bondState.bond.amount" class="ov-bond-amt">{{ bondState.bond.amount }} {{ bondState.bond.currency }}</span>
                <span v-if="bondState.bond.funded_by" class="ov-bond-meta">{{ bondFundedLabel(bondState.bond.funded_by) }}</span>
                <span v-if="bondState.bond.source === 'card' && bondState.bond.registry" class="ov-bond-meta">{{ t('agentDetails.bond.fromCard', 'as signed by') }} {{ bondState.bond.registry }}</span>
              </div>
              <div v-if="bondState.bond.progress || bondState.bond.fire" class="ov-bond-progress" data-testid="agd-bond-progress">
                <BondMaturityBar :bond="bondState.bond" :origin="bondState.bond.registry" detailed />
                <!-- §BONDFILL-3 — the owner's unlock: the declared share back, the rest stays bonded.
                     The button renders only when the backend says it can be pressed; otherwise the
                     one reason why. The full release (the exit) is deliberately not offered here. -->
                <div v-if="isListingOwner && bondUnlock && bondState.bond.status === 'matured'" class="ov-bond-actions" data-testid="agd-bond-unlock-block">
                  <button v-if="bondUnlock.available" type="button" class="ov-btn" :disabled="bondBusy" data-testid="agd-bond-unlock" @click="unlockBond">
                    {{ tp('agentDetails.bond.unlock.button', 'Unlock {amt} {ccy} (keep {keeps} bonded)', { amt: bondUnlock.amount || '', ccy: bondState.bond.currency || '', keeps: bondUnlock.keeps || '' }) }}
                  </button>
                  <p v-if="bondUnlock.available" class="ov-listing-note">{{ t('agentDetails.bond.unlock.note', 'Unlocking puts the fire out: the bond glows as embers instead, and buyers can see you took capital back. Keep it all in the bond and it keeps burning.') }}</p>
                  <p v-else class="ov-listing-note" data-testid="agd-bond-unlock-reason">{{ unlockReasonText }}</p>
                </div>
              </div>
              <p v-if="bondState.bond.status === 'none'" class="ov-listing-note" data-testid="agd-bond-none">{{ tp('agentDetails.bond.none', 'No reputation bond. Providing services here asks for {amt} {ccy} held in escrow by the registry.', { amt: bondState.bond.required_amount || '', ccy: bondState.bond.currency || '' }) }}</p>
              <div v-if="bondState.volume != null || bondState.staked" class="ov-bond-stats">
                <span v-if="bondState.volume != null">{{ t('agentDetails.bond.volume', 'Paid volume') }}: <strong>{{ bondState.volume }}</strong></span>
                <span v-if="bondState.transactions != null">{{ t('agentDetails.bond.transactions', 'Interactions') }}: <strong>{{ bondState.transactions }}</strong></span>
                <span v-if="bondState.staked">{{ t('agentDetails.bond.staked', 'Locked') }}: <strong>{{ bondState.staked }}</strong></span>
              </div>
              <div v-if="bondState.bond.status === 'none' && bondState.mode && bondState.mode !== 'off'" class="ov-bond-actions">
                <button v-if="walletAgentForBond" type="button" class="ov-btn" :disabled="bondBusy" data-testid="agd-bond-wallet" @click="bondFromWallet">
                  {{ tp('agentDetails.bond.fromWallet', 'Bond from {name}', { name: walletAgentForBond.name || 'wallet' }) }}
                </button>
                <button v-if="bondState.treasury_backstop" type="button" class="ov-btn ov-btn--ghost" :disabled="bondBusy" data-testid="agd-bond-backstop" @click="bondBackstop">
                  {{ t('agentDetails.bond.backstop', 'Demonstration: bond from the treasury') }}
                </button>
                <p v-if="bondState.treasury_backstop" class="ov-listing-note">{{ t('agentDetails.bond.backstopNote', 'A demonstration mechanism: the treasury underwrites the bond for now. It is planned that the bond comes out of your genesis grant or your income; a backstopped bond pays nothing back on release.') }}</p>
                <p v-if="!walletAgentForBond && !bondState.treasury_backstop" class="ov-listing-note">{{ t('agentDetails.bond.needWallet', 'Create a wallet agent that holds the amount, then bond from it here.') }}</p>
                <p v-if="bondError" class="ov-listing-note ov-bond-error" data-testid="agd-bond-error">{{ bondError }}</p>
              </div>
            </div>
            <ReadFailedNotice v-else-if="bondFailed" dense :retry="loadBond" data-testid="agd-bond-failed" />
            <p v-else class="ov-listing-note">{{ t('agentDetails.bond.loading', 'Reading the bond…') }}</p>
          </div>

          <div v-if="isWalletCard" class="ov-section ov-section--spaced" data-testid="agd-wallet">
            <div class="ov-section-label">{{ t('agentDetails.wallet', 'WALLET AGENT') }}</div>
            <ul class="ov-wallet-lines"><li v-for="(l, i) in walletLines" :key="i">{{ l }}</li></ul>
            <p class="ov-listing-note">{{ t('agentDetails.walletReuse', 'To reuse this identity, run your own agent with the Client ID above and its secret (rotate the secret from the credentials section if you lost it); the card it publishes replaces this one, and the balance and history stay.') }}</p>
          </div>

          <!-- §DISCREFINE (2026-08-23) — the owner decides whether this agent is
               listed. OWNER ONLY, deliberately: an admin can SEE hidden agents in
               order to moderate, but whether someone else's agent appears in
               discovery is not an operator's call, and the backend 403s it. -->
          <div v-if="isListingOwner" class="ov-section ov-section--spaced" data-testid="agd-listing">
            <div class="ov-section-label">{{ t('agentDetails.listing', 'DISCOVERY LISTING') }}</div>
            <div class="ov-listing">
              <label class="ov-listing-row">
                <input type="checkbox" :checked="!listingUnlisted" :disabled="listingBusy"
                       data-testid="agd-listing-toggle" @change="toggleListing" />
                <span>{{ t('agentDetails.listingShow', 'Show this agent in discovery') }}</span>
              </label>
              <p v-if="listingUnlisted || !bondHidesListing" class="ov-listing-note">
                {{ listingUnlisted
                  ? t('agentDetails.listingHiddenNote', 'Hidden here, and other registries are told to hide their copy too — usually within a few minutes. A registry on an older version keeps its copy until it drops it, and a direct DID link always still resolves: this hides the listing, it does not seal the agent.')
                  : t('agentDetails.listingShownNote', 'Listed in search, browse and facet counts, and exported to federated registries.') }}
              </p>
              <p v-if="!listingUnlisted && bondHidesListing" class="ov-listing-note ov-listing-bond" data-testid="agd-listing-bond">
                {{ tp('agentDetails.listingBondNote', 'Not shown yet: this registry shows an agent in discovery once it holds its reputation bond ({amt} {ccy}), so whoever finds it can see it answers for its work. Post the bond in the section above; a direct link to its DID resolves meanwhile.', { amt: bondState?.bond?.required_amount || '', ccy: bondState?.bond?.currency || '' }) }}
              </p>
              <p v-if="listingErr" class="ov-listing-err" data-testid="agd-listing-err">{{ listingErr }}</p>
            </div>
          </div>

          <!-- How the world calls this agent -->
          <div class="ov-section ov-section--spaced" data-testid="agd-public-face">
            <div class="ov-section-label">{{ t('agentDetails.publicFace', 'PUBLIC FACE') }}</div>
            <div class="ov-face">
              <div class="ov-face-avatar">
                <UserAvatar :user="agent" :display-name="agent.name || agentDid" size="md" />
                <span class="ov-face-flare" data-testid="agd-flare">
                  {{ agentFlareTier ? prettyFlare(agentFlareTier) : t('agentDetails.noFlare', 'no cosmetic flare') }}
                </span>
              </div>
              <div class="ov-face-rows">
                <div v-if="agentEndpoint" class="ov-face-row">
                  <span class="od-label">{{ t('agentDetails.endpoint', 'ENDPOINT') }}</span>
                  <code class="od-value od-mono ov-face-url" :title="agentEndpoint">{{ agentEndpoint }}</code>
                </div>
                <div class="ov-face-row">
                  <span class="od-label">{{ t('agentDetails.a2aCard', 'A2A CARD') }}</span>
                  <a v-if="agentDid" :href="`/api/v1/agents/${encodeURIComponent(agentDid)}/card-export`"
                     target="_blank" rel="noopener" class="ov-face-link" data-testid="agd-card-export">
                    {{ t('agentDetails.a2aCardLink', 'signed A2A v1.0 card') }} &#8599;
                  </a>
                </div>
              </div>
            </div>
            <div class="ov-face-actions">
              <router-link v-if="agentDid" :to="{ path: '/discover', query: { did: agentDid } }"
                           class="ov-action" data-testid="agd-view-public">
                {{ t('agentDetails.viewPublic', 'See it as the network sees it') }}
              </router-link>
              <router-link to="/flare-shop" class="ov-action" data-testid="agd-flare-shop">
                {{ agentFlareTier ? t('agentDetails.upgradeFlare', 'Upgrade its flare') : t('agentDetails.giveFlare', 'Give it a flare') }}
              </router-link>
              <router-link v-if="agentFlareTier" to="/flare-manager" class="ov-action" data-testid="agd-flare-manager">
                {{ t('agentDetails.manageFlare', 'Move or restyle it') }}
              </router-link>
            </div>
          </div>
        </div>

        <!-- TRANSACTIONS ──────────────────────────────────────────────── -->
        <div v-if="activeTab === 'work'" class="tab-body tab-tx">
          <div class="tab-section-header">
            <span class="tsh-title">TRANSACTION HISTORY</span>
            <button v-if="!txLoading" class="tsh-refresh" @click="loadTransactions">↻ Refresh</button>
            <div v-else class="loading-ring loading-ring--sm" />
          </div>

          <div v-if="txLoading && !transactions.length" class="tab-loading">
            <div class="loading-ring" /> Loading transactions…
          </div>

          <div v-else-if="txError" class="tab-error" role="alert">
            <span class="tab-error-icon"><Icon name="mdi:alert" /></span>
            Failed to load transactions: {{ txError }}
            <button class="tab-error-retry" @click="loadTransactions">Retry</button>
          </div>

          <div v-else-if="!transactions.length" class="tab-empty">
            <span class="tab-empty-glyph">◌</span>
            No transactions recorded yet.
          </div>

          <div v-else class="tx-list">
            <div
              v-for="tx in transactions"
              :key="tx.transaction_id || tx.id"
              class="tx-row"
              :class="txDirection(tx) === 'in' ? 'tx-row--in' : 'tx-row--out'"
            >
              <div class="tx-direction-badge">
                {{ txDirection(tx) === 'in' ? '↓ IN' : '↑ OUT' }}
              </div>
              <div class="tx-body">
                <div class="tx-amount">
                  {{ txDirection(tx) === 'in' ? '+' : '-' }}{{ tx.amount }} {{ localCurrency }}
                </div>
                <div class="tx-peer">{{ peerDid(tx) }}</div>
                <div v-if="tx.message || tx.details?.memo" class="tx-memo">
                  {{ tx.message || tx.details?.memo }}
                </div>
              </div>
              <div class="tx-time">{{ formatTimeAgo(tx.timestamp) }}</div>
            </div>
          </div>
        </div>

        <!-- GOVERNANCE ────────────────────────────────────────────────── -->
        <div v-if="activeTab === 'work'" class="tab-body tab-gov">
          <div class="tab-section-header">
            <span class="tsh-title">GOVERNANCE ACTIVITY</span>
            <span class="tsh-sub">Proposals by this agent</span>
          </div>

          <div v-if="govLoading" class="tab-loading">
            <div class="loading-ring" /> Loading proposals…
          </div>

          <div v-else-if="govError" class="tab-error" role="alert">
            <span class="tab-error-icon"><Icon name="mdi:alert" /></span>
            Failed to load proposals: {{ govError }}
            <button class="tab-error-retry" @click="loadGovernance">Retry</button>
          </div>

          <div v-else-if="!proposals.length" class="tab-empty">
            <span class="tab-empty-glyph">◌</span>
            No governance proposals by this agent.
          </div>

          <div v-else class="gov-list">
            <div v-for="p in proposals" :key="p.id" class="gov-row">
              <div class="gov-row-head">
                <span
                  class="gov-status"
                  :class="`gov-status--${(p.status||'').toLowerCase()}`"
                >{{ p.status }}</span>
                <span class="gov-type">{{ p.proposal_type }}</span>
                <span class="gov-id">#{{ p.id }}</span>
              </div>
              <div class="gov-title">{{ p.title }}</div>
              <div class="gov-stats">
                <span class="gov-stat gov-stat--for">▲ {{ p.votes_for || 0 }} for</span>
                <span class="gov-stat gov-stat--against">▼ {{ p.votes_against || 0 }} against</span>
                <span class="gov-stat gov-stat--voters">{{ p.total_voters || 0 }} voters</span>
                <span class="gov-stat gov-stat--end">ends {{ formatTimeAgo(p.end_timestamp) }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- DISPUTES ──────────────────────────────────────────────────── -->
        <div v-if="activeTab === 'work'" class="tab-body tab-disp">
          <div class="tab-section-header">
            <span class="tsh-title">DISPUTE HISTORY</span>
            <span class="tsh-sub">{{ disputes.length }} total</span>
          </div>

          <div v-if="dispLoading" class="tab-loading">
            <div class="loading-ring" /> Loading disputes…
          </div>

          <div v-else-if="dispError" class="tab-error" role="alert">
            <span class="tab-error-icon"><Icon name="mdi:alert" /></span>
            Failed to load disputes: {{ dispError }}
            <button class="tab-error-retry" @click="loadDisputes">Retry</button>
          </div>

          <div v-else-if="!disputes.length" class="tab-empty">
            <span class="tab-empty-glyph">◌</span>
            No disputes involving this agent.
          </div>

          <div v-else class="disp-list">
            <div v-for="d in disputes" :key="d.id" class="disp-row">
              <div class="disp-meta">
                <span class="disp-id">#{{ d.id }}</span>
                <span class="disp-status" :class="`disp-status--${(d.status||'').toLowerCase()}`">{{ d.status }}</span>
              </div>
              <div class="disp-parties">
                <span class="disp-role" :class="{ 'disp-role--complainant': d.complainant_did === agent.did }">
                  {{ d.complainant_did === agent.did ? 'COMPLAINANT' : 'DEFENDANT' }}
                </span>
                <span class="disp-peer">
                  vs {{ (d.complainant_did === agent.did ? d.defendant_did : d.complainant_did).slice(0, 28) }}…
                </span>
              </div>
              <div v-if="d.ruling" class="disp-ruling" :style="{ color: disputeRulingColor(d.ruling) }">
                <Icon name="mdi:scale-balance" /> {{ d.ruling.replace(/_/g,' ') }}
              </div>
              <div class="disp-date">{{ formatDate(d.created_at) }}</div>
            </div>
          </div>
        </div>

        <!-- CAPABILITIES ──────────────────────────────────────────────── -->
        <div v-if="activeTab === 'access'" class="tab-body tab-caps">
          <!-- §AGENTCOCKPIT T2.2 — CREDENTIALS. The agent payload has carried
               `client_id` all along and this page never showed it, so the one
               identifier an owner needs to wire the agent up lived only on the
               fleet page. The SECRET is not here and never will be: rotation is
               password-gated and shows the secret once, and that flow already
               exists — this is a door to it, not a second copy of it. -->
          <div v-if="canSeeAuthz && agent.client_id" class="ov-creds" data-testid="agd-credentials">
            <div class="ov-section-label">{{ t('agentDetails.credentials', 'CREDENTIALS') }}</div>
            <div class="ov-cred-row">
              <span class="od-label">{{ t('agentDetails.clientId', 'CLIENT ID') }}</span>
              <code class="ov-cred-val" data-testid="agd-client-id">{{ agent.client_id }}</code>
              <button class="ov-cred-copy" :title="t('common.copy', 'Copy')"
                    @click="copyText(agent.client_id)"><Icon name="mdi:content-copy" /></button>
            </div>
            <router-link class="ov-action" data-testid="agd-rotate"
                       :to="{ name: 'my-agents', query: { reset: agent.did } }">
              {{ t('agentDetails.rotate', 'Rotate credentials') }}
            </router-link>
            <p class="ov-cred-note">{{ t('agentDetails.rotateNote', 'Rotation asks for your password and shows the new secret once. The old one stops working immediately.') }}</p>
          </div>

          <!-- §AGENTCOCKPIT T2.1 — ACCESS, EDITABLE. This view imported the authz
               API and called exactly one method (.get), so an owner could read
               ENFORCE / roles / 27 permissions here and had to go back to the
               fleet page to change any of them. The panel below is the one that
               page already mounts; nothing new was written to enable this. -->
          <div v-if="canSeeAuthz" class="caps-section" data-testid="ad-access-panel">
            <AgentAccessPanel :agent-did="agent.did" mode="owner" />
          </div>
          <!-- IRONKEY ACCESS — live roles / effective permissions / delegation.
               Owner/admin only (canSeeAuthz); the agent-card section stays below. -->
          <div v-if="canSeeAuthz" class="caps-section authz-section">
            <div class="caps-section-label">IRONKEY ACCESS</div>

            <div v-if="authzLoading" class="tab-loading">
              <div class="loading-ring loading-ring--sm" /> {{ t('agentDetails.authzLoading', 'Loading access…') }}
            </div>
            <div v-else-if="authzError" class="tab-error" role="alert">
              <span class="tab-error-icon"><Icon name="mdi:alert" /></span>
              {{ t('agentDetails.authzError', 'Failed to load access') }}: {{ authzError }}
              <button class="tab-error-retry" @click="loadAuthz">{{ t('agentDetails.retry', 'Retry') }}</button>
            </div>
            <template v-else-if="authz">
              <div class="authz-summary">
                <span class="authz-mode" :class="'authz-mode--' + authz.mode"
                      :title="t('agentDetails.authzMode', 'Enforcement mode')">{{ authz.mode }}</span>
                <span class="authz-deleg" :class="authz.delegate_enabled ? 'authz-deleg--on' : 'authz-deleg--off'">
                  <Icon :name="authz.delegate_enabled ? 'mdi:check-circle-outline' : 'mdi:cancel'" />
                  {{ t('agentDetails.delegation', 'Delegation') }}:
                  {{ authz.delegate_enabled ? t('agentDetails.enabled', 'enabled') : t('agentDetails.disabled', 'disabled') }}
                </span>
              </div>

              <div class="authz-block">
                <div class="authz-block-label">{{ t('agentDetails.roles', 'ROLES') }}</div>
                <div v-if="authz.roles && authz.roles.length" class="authz-chips">
                  <span v-for="r in authz.roles" :key="r" class="authz-chip authz-chip--role">{{ r }}</span>
                </div>
                <div v-else class="authz-none">{{ t('agentDetails.noRoles', 'No IRONKEY roles resolved') }}</div>
              </div>

              <div class="authz-block">
                <div class="authz-block-label">{{ t('agentDetails.effectivePermissions', 'OWN PERMISSIONS (roles)') }}</div>
                <div v-if="authz.effective_permissions && authz.effective_permissions.length" class="authz-chips">
                  <span v-for="p in authz.effective_permissions" :key="p" class="authz-chip">{{ p }}</span>
                </div>
                <div v-else class="authz-none">{{ t('agentDetails.noPermissions', 'No permissions granted') }}</div>
              </div>

              <!-- Track A2 provenance: authority delegated TO this agent, per principal.
                   Never merged with own permissions — it bites only via a matching act-token. -->
              <div v-if="authz.delegations && authz.delegations.length" class="authz-block" data-tour="agent-authz-delegated">
                <div class="authz-block-label">{{ t('agentDetails.delegatedPermissions', 'DELEGATED (on-behalf-of)') }}</div>
                <div v-for="d in authz.delegations" :key="d.grant_id" class="authz-deleg-row">
                  <span class="authz-chip authz-chip--principal">{{ d.principal_ref }}</span>
                  <span v-for="p in d.permissions" :key="p" class="authz-chip authz-chip--delegated">{{ p }}</span>
                  <span v-if="d.expires_at" class="authz-none" style="margin:0;">exp {{ new Date(d.expires_at).toLocaleDateString(appLocale()) }}</span>
                </div>
                <div class="authz-none" style="margin-top:6px;">
                  {{ t('agentDetails.delegatedNote', 'Honored only when the agent presents a token acting for that principal (act.sub) — never inherited silently.') }}
                </div>
              </div>
            </template>
          </div>
        </div>

        <!-- ═══ CARD, part two: the A2A document itself ═══════════════════
             §AGENTCOCKPIT T3 — protocol, auth schemes and SKILLS used to sit
             under CAPABILITIES next to IRONKEY roles: two unrelated subjects
             sharing a screen because both were once called "capabilities".
             What an agent can DO belongs with the card that declares it. -->
        <div v-if="activeTab === 'card'" class="tab-body tab-card--doc">
          <div v-if="!agent.card_data" class="tab-empty">
            <span class="tab-empty-glyph">◌</span>
            {{ t('agentDetails.noCard', 'No agent card yet. The card is what the network reads: without it this agent cannot be found, priced or hired.') }}
          </div>
          <template v-else>
            <div class="caps-section">
              <div class="caps-section-label">PROTOCOL</div>
              <div class="caps-grid">
                <div class="cap-item">
                  <span class="cap-key">A2A Version</span>
                  <!-- §AGENTCOCKPIT T1.3 — `capabilities.a2aVersion` is null on every
                       canonicalized card (measured on this agent), so this rendered
                       "—" while the card states its version one level up. The
                       OVERVIEW tab was already reading the right field. -->
                  <span class="cap-val">{{ agent.card_data.capabilities?.a2aVersion
                    || agent.card_data.protocolVersion || agent.card_data.agentVersion || '—' }}</span>
                </div>
                <div class="cap-item">
                  <span class="cap-key">Streaming</span>
                  <span class="cap-val" :class="agent.card_data.capabilities?.streaming ? 'cap-yes' : 'cap-no'">
                    {{ agent.card_data.capabilities?.streaming ? 'YES' : 'NO' }}
                  </span>
                </div>
                <div class="cap-item">
                  <span class="cap-key">Push Notifications</span>
                  <span class="cap-val" :class="agent.card_data.capabilities?.supportsPushNotifications ? 'cap-yes' : 'cap-no'">
                    {{ agent.card_data.capabilities?.supportsPushNotifications ? 'YES' : 'NO' }}
                  </span>
                </div>
                <div class="cap-item">
                  <span class="cap-key">State History</span>
                  <span class="cap-val" :class="agent.card_data.capabilities?.stateTransitionHistory ? 'cap-yes' : 'cap-no'">
                    {{ agent.card_data.capabilities?.stateTransitionHistory ? 'YES' : 'NO' }}
                  </span>
                </div>
              </div>
            </div>

            <div v-if="agent.card_data.authSchemes?.length" class="caps-section">
              <div class="caps-section-label">AUTH SCHEMES</div>
              <div v-for="(scheme, i) in agent.card_data.authSchemes" :key="i" class="auth-scheme">
                <span class="auth-scheme-name">{{ scheme.scheme?.toUpperCase() }}</span>
                <span v-if="scheme.tokenUrl" class="auth-scheme-url">{{ scheme.tokenUrl }}</span>
              </div>
            </div>

            <div v-if="agent.card_data.skills?.length" class="caps-section">
              <div class="caps-section-label">SKILLS</div>
              <div class="skills-list">
                <div v-for="skill in agent.card_data.skills" :key="skill.id" class="skill-item">
                  <span class="skill-id">{{ skill.id }}</span>
                  <span class="skill-name">{{ skill.name }}</span>
                  <span class="skill-desc">{{ skill.description }}</span>
                </div>
              </div>
            </div>
            <div v-else class="tab-empty tab-empty--inline">No skills defined.</div>
          </template>
        </div>

        <!-- METRICS ───────────────────────────────────────────────────── -->
        <div v-if="activeTab === 'runtime'" class="tab-body tab-metrics">
          <div v-if="metricsLoading" class="tab-loading">
            <div class="loading-ring" /> Loading metrics…
          </div>
          <div v-else-if="metricsError" class="tab-error" role="alert">
            <span class="tab-error-icon"><Icon name="mdi:alert" /></span>
            Failed to load metrics: {{ metricsError }}
            <button class="tab-error-retry" @click="loadMetrics">Retry</button>
          </div>
          <div v-else-if="!metrics" class="tab-empty">
            <span class="tab-empty-glyph">◌</span>
            No metrics available.
          </div>
          <template v-else>
            <div class="metrics-grid">
              <div class="metric-card">
                <span class="metric-label">TOTAL REQUESTS</span>
                <span class="metric-value">{{ metrics.total_requests?.toLocaleString(appLocale()) || '0' }}</span>
              </div>
              <div class="metric-card">
                <span class="metric-label">SUCCESS RATE</span>
                <span class="metric-value">{{ (metrics.success_rate || 0).toFixed(1) }}%</span>
              </div>
              <div class="metric-card">
                <span class="metric-label">AVG RESPONSE</span>
                <span class="metric-value">{{ metrics.avg_response_time || '0' }}ms</span>
              </div>
              <div class="metric-card">
                <span class="metric-label">UPTIME</span>
                <span class="metric-value">{{ (metrics.uptime_percentage || 0).toFixed(1) }}%</span>
              </div>
            </div>
            <!-- §MISUSEDETAIL/T3 — these four are LIFETIME counters. Ironhand Alpha
                 reads 118,208 requests at 96.97% while its last request was months
                 ago; without a date that renders as a busy agent. The endpoint has
                 always returned `last_active` and nothing showed it. -->
            <p v-if="metrics.last_active" class="metrics-since">
              {{ t('agentDetails.mSince', 'since first request · last request') }}
              {{ formatTimeAgo(metrics.last_active) }}
            </p>
            <p v-else class="metrics-since">
              {{ t('agentDetails.mNever', 'this agent has never served a request') }}
            </p>
            <div class="metrics-daily">
              <div class="metrics-daily-label">TODAY</div>
              <div class="metrics-grid metrics-grid--sm">
                <div class="metric-card metric-card--sm">
                  <span class="metric-label">REQUESTS</span>
                  <span class="metric-value">{{ metrics.daily_stats?.requests_today || '0' }}</span>
                </div>
                <div class="metric-card metric-card--sm">
                  <span class="metric-label">ERRORS</span>
                  <span class="metric-value">{{ metrics.daily_stats?.errors_today || '0' }}</span>
                </div>
                <div class="metric-card metric-card--sm">
                  <span class="metric-label">UNIQUE CALLERS</span>
                  <span class="metric-value">{{ metrics.daily_stats?.unique_callers || '0' }}</span>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- LINEAGE — sub-agent hands this agent has spawned (IRONKEY L4 birth-token tree) -->
        <div v-if="activeTab === 'runtime' && canSeeAuthz" class="tab-body tab-lineage">
          <AgentLineageTree :key="agent.did" :agent-did="agent.did" mode="owner" />
        </div>

      </div><!-- /tab-content -->
    </template>
  </div>
</template>

<style scoped>
.ad-root {
  min-height: 100vh;
  padding: 2rem 2.5rem;
  /* Transparent so DashboardLayout's animated dot grid + scan beam +
     radial glows show through, matching Command Center / HealthMonitor. */
  background: transparent;
  color: #e2e8f0;
  font-family: system-ui, -apple-system, sans-serif;
}
.ad-safety-header {
  display: flex; gap: 16px; align-items: center;
  padding: 10px 14px; margin-bottom: 18px;
  background: rgba(13, 22, 38, 0.7);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 10px;
  font-family: 'IBM Plex Mono', monospace;
}

.ad-boundary-error {
  margin-bottom: 18px; padding: 14px 16px; border-radius: 10px;
  background: rgba(255, 77, 106, 0.10);
  border: 1px solid rgba(255, 77, 106, 0.6);
  color: #ffb3c1;
  font-family: 'IBM Plex Mono', monospace;
}
.ad-boundary-title {
  display: flex; align-items: center; gap: 10px;
  font-size: 11px; letter-spacing: 0.16em; text-transform: uppercase;
  color: #ff4d6a; font-weight: 700;
  margin-bottom: 10px;
}
.ad-boundary-dot { width: 10px; height: 10px; border-radius: 50%; background: #ff4d6a; box-shadow: 0 0 10px rgba(255,77,106,0.8); }
.ad-boundary-msg {
  margin: 0 0 12px; padding: 10px 12px;
  background: rgba(0,0,0,0.4); border: 1px solid rgba(255, 77, 106, 0.2);
  border-radius: 6px; color: #ffd1d9;
  font-size: 11px; max-height: 200px; overflow: auto;
  white-space: pre-wrap; word-break: break-word;
}
.ad-boundary-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.ad-boundary-btn {
  background: rgba(255,77,106,0.15); border: 1px solid rgba(255,77,106,0.5);
  color: #ff8da3; padding: 6px 14px; border-radius: 5px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 11px;
}
.ad-boundary-btn:hover { background: rgba(255,77,106,0.3); color: #fff; }
.ad-safety-label {
  font-size: 10px; letter-spacing: 0.18em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.85);
  margin-right: 8px;
}
.ad-safety-did {
  font-size: 12px; color: #c8d8e8;
  background: rgba(255,255,255,0.04); padding: 3px 8px; border-radius: 4px;
  word-break: break-all;
}
.ad-safety-id { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; flex: 1; }
.ad-loading, .ad-notfound {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; padding: 80px 20px; gap: 16px;
  color: rgba(200, 216, 232, 0.85); text-align: center;
}
.nf-glyph { font-size: 3rem; color: rgba(var(--nc-primary-rgb), 0.55); }
.ad-loading > span, .ad-notfound > p, .ad-notfound > h3 {
  font-family: 'IBM Plex Mono', monospace;
}
.loading-ring {
  width: 24px; height: 24px; border-radius: 50%;
  border: 2px solid rgba(var(--nc-primary-rgb),0.15);
  border-top-color: rgba(var(--nc-primary-rgb),0.7);
  animation: spin 0.8s linear infinite; flex-shrink: 0;
}
.loading-ring--sm { width: 14px; height: 14px; }
@keyframes spin { to { transform: rotate(360deg); } }
.ad-notfound code {
  font-family: 'IBM Plex Mono', monospace;
  background: rgba(255,255,255,0.04); padding: 2px 8px; border-radius: 4px;
}
.ad-topbar {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 1.5rem; flex-wrap: wrap;
}
.ad-back-btn {
  background: none; border: 1px solid rgba(var(--nc-primary-rgb),0.15); border-radius: 5px;
  padding: 6px 14px; cursor: pointer; font-size: 0.75rem;
  font-family: 'IBM Plex Mono', monospace;
  color: rgba(var(--nc-primary-rgb),0.6); transition: all 0.15s;
}
.ad-back-btn:hover { border-color: rgba(var(--nc-primary-rgb),0.4); color: rgba(var(--nc-primary-rgb),0.9); }
.ad-breadcrumb {
  display: flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
  color: rgba(148,163,184,0.4);
}
.bc-sep { color: rgba(var(--nc-primary-rgb),0.2); }
.bc-name { color: rgba(226,232,240,0.6); }
.ad-topbar-right { margin-left: auto; display: flex; gap: 8px; }
/* §AGENTCOCKPIT — credentials block + the status note under the edit form */
.ov-creds { margin-top: 1.1rem; }
.ov-cred-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 4px 0 8px; }
.ov-cred-val { font-family: 'IBM Plex Mono', ui-monospace, monospace; font-size: 0.8rem;
  padding: 3px 8px; border-radius: 6px; border: 1px solid rgba(148,163,184,0.2);
  background: rgba(148,163,184,0.06); overflow-wrap: anywhere; }
.ov-cred-copy { background: none; border: none; color: inherit; opacity: .6; cursor: pointer;
  min-width: 32px; min-height: 32px; }
.ov-cred-copy:hover { opacity: 1; }
.ov-cred-note { font-size: 0.72rem; opacity: 0.55; margin: 6px 0 0; max-width: 70ch; }
.od-note { font-size: 0.68rem; opacity: 0.55; margin-top: 2px; }

/* §AGENTCOCKPIT T3 — the per-tab wrappers had markup and NO rule (all seven of
   them, plus .ad-tab-content), which is why every tab body sat flush against the
   tab row with no rhythm of its own. One rule, not seven. */
.ad-tab-content { padding-top: .25rem; }
/* ⚠ `.tab-tx`, `.tab-gov`, `.tab-disp`, `.tab-caps`, `.tab-metrics`,
   `.tab-lineage` deliberately carry NO rule: they are SELECTOR HOOKS that six
   existing batteries target (checked before touching them). Layout comes from
   `.tab-body`, which every one of them now also carries. A reachability scan
   will keep naming them, and that is the scan being right about the CSS and
   wrong about the intent. */
.authz-section { padding-top: .2rem; }
.metrics-daily { display: flex; flex-wrap: wrap; gap: .5rem; }
.metrics-since { margin: .5rem 0 0; font-size: .74rem; color: var(--nc-text-muted, #94a3b8); }
.tab-body { display: flex; flex-direction: column; gap: 1.4rem; padding: 1.1rem 0 2rem; }
.tab-card--doc { padding-top: 0; }

/* the at-a-glance strip: five facts, one line */
.ad-glance {
  display: flex; flex-wrap: wrap; gap: .35rem 1.4rem;
  padding: .55rem 0 .7rem; margin-bottom: .2rem;
  border-bottom: 1px solid rgba(148,163,184,0.12);
  font-size: .74rem; color: rgba(226,232,240,0.85);
}
.glance-item { display: inline-flex; align-items: baseline; gap: .4rem; }
.glance-item i { font-style: normal; text-transform: uppercase; letter-spacing: .08em;
  font-size: .6rem; color: rgba(148,163,184,0.65); }

.ad-edit-btn, .ad-save-btn, .ad-cancel-btn {
  padding: 6px 16px; border-radius: 5px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
  letter-spacing: 0.08em; transition: all 0.15s;
}
.ad-edit-btn {
  background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  color: rgba(var(--nc-primary-rgb),0.8);
}
.ad-edit-btn:hover { background: rgba(var(--nc-primary-rgb),0.15); }
.ad-save-btn {
  background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3);
  color: rgba(16,185,129,0.9);
}
.ad-save-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.ad-cancel-btn {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
  color: rgba(148,163,184,0.6);
}
.ad-header {
  display: flex; gap: 2rem; align-items: flex-start;
  margin-bottom: 2rem; flex-wrap: wrap;
}
.ad-identity { flex: 1; min-width: 0; }
.ad-status-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.ad-status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.ad-status-text {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.12em;
  color: rgba(148,163,184,0.5);
}
.ad-last-active {
  margin-left: auto; font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; color: rgba(148,163,184,0.3);
}
.ad-name {
  font-family: 'IBM Plex Mono', monospace; font-size: 1.75rem; font-weight: 700;
  letter-spacing: 0.06em; color: #e2e8f0; margin: 0 0 8px;
}
.ad-did-row, .ad-client-row {
  display: flex; align-items: center; gap: 8px;
  font-family: 'IBM Plex Mono', monospace; margin-bottom: 4px;
}
.ad-did { font-size: 0.72rem; color: rgba(var(--nc-primary-rgb),0.5); word-break: break-all; }
.ad-client-id { font-size: 0.68rem; color: rgba(148,163,184,0.35); }
.copy-btn {
  background: none; border: none; cursor: pointer;
  color: rgba(var(--nc-primary-rgb),0.3); font-size: 0.8rem;
  padding: 0 2px; transition: color 0.15s; flex-shrink: 0;
}
.copy-btn:hover { color: rgba(var(--nc-primary-rgb),0.8); }
.edit-field-group { margin-bottom: 8px; }
.edit-input {
  width: 100%; background: rgba(255,255,255,0.04);
  border: 1px solid rgba(var(--nc-primary-rgb),0.25); border-radius: 5px;
  color: #e2e8f0; outline: none; padding: 6px 10px;
  font-family: 'IBM Plex Mono', monospace; transition: border-color 0.15s;
}
.edit-input:focus { border-color: rgba(var(--nc-primary-rgb),0.5); }
.edit-input--name { font-size: 1.2rem; font-weight: 600; }
.edit-textarea {
  width: 100%; background: rgba(255,255,255,0.04);
  border: 1px solid rgba(var(--nc-primary-rgb),0.2); border-radius: 5px;
  color: #e2e8f0; outline: none; padding: 8px 10px;
  font-size: 0.85rem; resize: vertical; line-height: 1.5; transition: border-color 0.15s;
}
.edit-textarea:focus { border-color: rgba(var(--nc-primary-rgb),0.5); }
.edit-select {
  background: rgba(255,255,255,0.04); border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  border-radius: 5px; color: #e2e8f0; outline: none;
  padding: 5px 10px; font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;
}
.ad-summary-cards { display: flex; gap: 1rem; flex-wrap: wrap; align-self: flex-start; }
.ad-sum-card {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 8px; padding: 14px 18px; text-align: center; min-width: 100px;
  transition: border-color 0.2s;
}
.ad-sum-card:hover { border-color: rgba(var(--nc-primary-rgb),0.2); }
.sum-label {
  display: block; font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem; letter-spacing: 0.12em;
  color: rgba(148,163,184,0.35); margin-bottom: 4px;
}
.sum-value { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 1.05rem; font-weight: 700; margin-bottom: 2px; }
.sum-sub { display: block; font-size: 0.6rem; color: rgba(148,163,184,0.3); }
.ad-sum-card--liquid .sum-value { color: rgba(var(--nc-primary-rgb),0.9); }
.ad-sum-card--staked .sum-value { color: rgba(99,179,237,0.85); }
.ad-sum-card--total .sum-value { color: rgba(226,232,240,0.7); }
.ad-tabs {
  display: flex; gap: 0; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.1);
  margin-bottom: 1.5rem; overflow-x: auto;
}
.ad-tab {
  padding: 10px 20px; background: none; border: none; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; letter-spacing: 0.1em;
  color: rgba(148,163,184,0.4); transition: all 0.15s; white-space: nowrap;
  border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.ad-tab:hover { color: rgba(148,163,184,0.7); }
.ad-tab--active { color: rgba(var(--nc-primary-rgb),0.9); border-bottom-color: rgba(var(--nc-primary-rgb),0.7); }
.tab-section-header { display: flex; align-items: center; gap: 12px; margin-bottom: 1rem; }
.tsh-title {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; letter-spacing: 0.14em;
  color: rgba(var(--nc-primary-rgb),0.4);
}
.tsh-sub { font-size: 0.7rem; color: rgba(148,163,184,0.3); }
.tsh-refresh {
  margin-left: auto; background: none; border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 4px; cursor: pointer; font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; color: rgba(var(--nc-primary-rgb),0.4); padding: 4px 8px; transition: all 0.15s;
}
.tsh-refresh:hover { color: rgba(var(--nc-primary-rgb),0.8); border-color: rgba(var(--nc-primary-rgb),0.35); }
.tab-loading {
  display: flex; align-items: center; gap: 12px; padding: 40px;
  justify-content: center; color: rgba(148,163,184,0.4); font-size: 0.8rem;
}
.tab-empty {
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  padding: 60px 20px; color: rgba(148,163,184,0.35); font-size: 0.82rem; text-align: center;
}
.tab-empty--inline { padding: 20px; }
.tab-empty-glyph { font-size: 2rem; color: rgba(var(--nc-primary-rgb),0.1); }
/* AGD3 (audit 2026-05-07): per-tab error banner */
.tab-error {
  display: flex; align-items: center; gap: 12px;
  padding: 16px 20px;
  margin: 16px 0;
  border-radius: 8px;
  background: rgba(239, 68, 68, 0.06);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: rgba(239, 68, 68, 0.95);
  font-size: 0.85rem;
}
.tab-error-icon { font-size: 1.1rem; }
.tab-error-retry {
  margin-left: auto;
  padding: 6px 14px;
  border-radius: 6px;
  background: transparent;
  border: 1px solid rgba(239, 68, 68, 0.4);
  color: rgba(239, 68, 68, 0.95);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.15s;
}
.tab-error-retry:hover {
  background: rgba(239, 68, 68, 0.15);
}
.ov-section { margin-bottom: 1.5rem; }
/* §FLARESHOP (2026-08-16) — owner-side public-face block. */
.ov-section--spaced { margin-top: 1.75rem; }
.ov-face { display: flex; gap: 1.25rem; align-items: flex-start; flex-wrap: wrap; }
.ov-face-avatar { display: flex; flex-direction: column; align-items: center; gap: 0.4rem; min-width: 96px; }
.ov-face-flare { font-size: 0.68rem; color: var(--nc-text-muted, #94a3b8); text-align: center; }
.ov-face-rows { flex: 1; min-width: 240px; display: flex; flex-direction: column; gap: 0.55rem; }
.ov-face-row { display: flex; flex-direction: column; gap: 0.15rem; }
.ov-face-url { word-break: break-all; font-size: 0.78rem; }
.ov-face-link { font-size: 0.8rem; color: rgba(var(--nc-primary-rgb), 0.9); }
.ov-face-link:hover { text-decoration: underline; }
.ov-face-actions { display: flex; gap: 0.6rem; flex-wrap: wrap; margin-top: 0.9rem; }
.ov-action {
  font-size: 0.76rem; padding: 0.32rem 0.7rem; border-radius: 0.3rem;
  border: 1px solid rgba(148, 163, 184, 0.22); color: var(--nc-text-secondary, #cbd5e1);
  transition: border-color 0.15s, color 0.15s;
}
.ov-action:hover { border-color: rgba(var(--nc-primary-rgb), 0.5); color: rgba(var(--nc-primary-rgb), 0.95); }
/* the bond's own buttons (unlock, bond from the wallet, the treasury demonstration) carried a class no rule named
   since §REPBOND: they drew as bare text. The two that move the owner's money are the primary ones. */
.ov-btn {
  font-size: 0.76rem; padding: 0.32rem 0.7rem; border-radius: 0.3rem;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.45); color: rgba(var(--nc-primary-rgb), 0.95);
  background: rgba(var(--nc-primary-rgb), 0.08);
  transition: border-color 0.15s, background 0.15s, color 0.15s;
}
.ov-btn:hover:not(:disabled) { border-color: rgba(var(--nc-primary-rgb), 0.75); background: rgba(var(--nc-primary-rgb), 0.14); }
.ov-btn--ghost { border-color: rgba(148, 163, 184, 0.22); color: var(--nc-text-secondary, #cbd5e1); background: transparent; }
.ov-btn--ghost:hover:not(:disabled) { border-color: rgba(var(--nc-primary-rgb), 0.5); color: rgba(var(--nc-primary-rgb), 0.95); background: transparent; }
.ov-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.ov-listing { display: flex; flex-direction: column; gap: 0.4rem; }
.ov-listing-row { display: flex; align-items: center; gap: 0.5rem; cursor: pointer; }
.ov-listing-row input { width: 16px; height: 16px; }
.ov-listing-note { margin: 0; font-size: 0.78rem; opacity: 0.65; line-height: 1.45; }
.ov-listing-err { margin: 0; font-size: 0.78rem; color: #ff6b6b; }
.ov-section-label {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.14em;
  /* §FESUITE — 0.35 measured 2.2:1 on the page (axe); 0.8 is 6.9:1 on the neural surface */
  color: rgba(var(--nc-primary-rgb),0.8); margin-bottom: 8px;
}
.ov-desc { color: rgba(226,232,240,0.7); font-size: 0.88rem; line-height: 1.6; }
.ov-details-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 1rem; }
.ov-detail {
  background: rgba(255,255,255,0.02); border: 1px solid rgba(var(--nc-primary-rgb),0.07);
  border-radius: 6px; padding: 12px 14px;
}
.od-label {
  display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.56rem;
  letter-spacing: 0.12em; color: rgba(148,163,184,0.82); margin-bottom: 4px;
}
.od-value { display: block; font-size: 0.82rem; color: rgba(226,232,240,0.7); }
.od-mono { font-family: 'IBM Plex Mono', monospace; }
.tx-list { display: flex; flex-direction: column; gap: 4px; }
.tx-row {
  display: flex; align-items: flex-start; gap: 14px; padding: 12px 14px;
  border-radius: 6px; border: 1px solid rgba(255,255,255,0.04);
  background: rgba(255,255,255,0.02); transition: background 0.1s;
}
.tx-row:hover { background: rgba(255,255,255,0.04); }
.tx-row--in .tx-direction-badge { color: rgba(16,185,129,0.9); }
.tx-row--out .tx-direction-badge { color: rgba(239,68,68,0.8); }
.tx-direction-badge {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem;
  letter-spacing: 0.1em; flex-shrink: 0; padding-top: 2px;
}
.tx-body { flex: 1; min-width: 0; }
.tx-amount { font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; font-weight: 600; color: rgba(226,232,240,0.85); }
.tx-peer { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; color: rgba(148,163,184,0.4); margin-top: 2px; }
.tx-memo { font-size: 0.72rem; color: rgba(var(--nc-primary-rgb),0.4); margin-top: 3px; font-style: italic; }
.tx-time { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; color: rgba(148,163,184,0.3); flex-shrink: 0; padding-top: 2px; }
.gov-list { display: flex; flex-direction: column; gap: 8px; }
.gov-row { padding: 14px 16px; border-radius: 6px; border: 1px solid rgba(var(--nc-primary-rgb),0.08); background: rgba(255,255,255,0.02); }
.gov-row-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.gov-status { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.1em; padding: 2px 8px; border-radius: 4px; }
.gov-status--voting { background: rgba(99,179,237,0.1); color: rgba(99,179,237,0.9); }
.gov-status--passed { background: rgba(16,185,129,0.1); color: rgba(16,185,129,0.9); }
.gov-status--failed { background: rgba(239,68,68,0.1); color: rgba(239,68,68,0.8); }
.gov-type { font-size: 0.68rem; color: rgba(148,163,184,0.4); }
.gov-id { margin-left: auto; font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; color: rgba(148,163,184,0.3); }
.gov-title { font-size: 0.9rem; color: rgba(226,232,240,0.8); margin-bottom: 6px; }
.gov-stats { display: flex; flex-wrap: wrap; gap: 12px; }
.gov-stat { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; }
.gov-stat--for { color: rgba(16,185,129,0.7); }
.gov-stat--against { color: rgba(239,68,68,0.6); }
.gov-stat--voters { color: rgba(148,163,184,0.4); }
.gov-stat--end { color: rgba(148,163,184,0.35); }
.disp-list { display: flex; flex-direction: column; gap: 6px; }
.disp-row { padding: 12px 16px; border-radius: 6px; border: 1px solid rgba(var(--nc-primary-rgb),0.06); background: rgba(255,255,255,0.02); }
.disp-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.disp-id { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; color: rgba(148,163,184,0.4); }
.disp-status { font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; letter-spacing: 0.1em; padding: 2px 8px; border-radius: 4px; }
.disp-status--open { background: rgba(245,158,11,0.1); color: rgba(245,158,11,0.8); }
.disp-status--closed { background: rgba(148,163,184,0.08); color: rgba(148,163,184,0.5); }
.disp-parties { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.disp-role { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.08em; color: rgba(148,163,184,0.45); }
.disp-role--complainant { color: rgba(99,179,237,0.7); }
.disp-peer { font-family: 'IBM Plex Mono', monospace; font-size: 0.63rem; color: rgba(148,163,184,0.35); }
.disp-ruling { font-size: 0.75rem; font-weight: 600; margin-bottom: 4px; }
.disp-date { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; color: rgba(148,163,184,0.3); }
.caps-section { margin-bottom: 1.5rem; }
.caps-section-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.14em; color: rgba(var(--nc-primary-rgb),0.8); margin-bottom: 10px; }
.caps-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
.cap-item { background: rgba(255,255,255,0.02); border: 1px solid rgba(var(--nc-primary-rgb),0.07); border-radius: 6px; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
.cap-key { font-size: 0.65rem; color: rgba(148,163,184,0.82); }
.cap-val { font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; color: rgba(226,232,240,0.7); }
.cap-yes { color: rgba(16,185,129,0.8) !important; }
.cap-no { color: rgba(148,163,184,0.75) !important; }
.auth-scheme { display: flex; align-items: center; gap: 12px; padding: 8px 12px; border-radius: 6px; background: rgba(255,255,255,0.02); border: 1px solid rgba(var(--nc-primary-rgb),0.07); margin-bottom: 6px; }
.auth-scheme-name { font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; color: rgba(var(--nc-primary-rgb),0.7); }
.auth-scheme-url { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; color: rgba(148,163,184,0.82); }
.skills-list { display: flex; flex-direction: column; gap: 6px; }
.skill-item { display: grid; grid-template-columns: 140px 160px 1fr; gap: 12px; padding: 8px 12px; background: rgba(255,255,255,0.02); border: 1px solid rgba(var(--nc-primary-rgb),0.06); border-radius: 6px; align-items: center; }
.skill-id { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: rgba(var(--nc-primary-rgb),0.9); }
.skill-name { font-size: 0.8rem; font-weight: 500; color: rgba(226,232,240,0.7); }
.skill-desc { font-size: 0.72rem; color: rgba(148,163,184,0.82); }
/* a phone: the skill's id and name on one line, its description under them, where 140 px + 160 px + the description
   ran past the card (the camera, 2026-10-13, Pixel 7) */
@media (max-width: 640px) {
  .skill-item { grid-template-columns: auto minmax(0, 1fr); gap: 4px 12px; }
  .skill-desc { grid-column: 1 / -1; }
}
.metrics-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; margin-bottom: 1.5rem; }
.metrics-grid--sm { gap: 8px; }
.metric-card { background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.1); border-radius: 8px; padding: 16px; text-align: center; }
.metric-card--sm { padding: 12px; }
.metric-label { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.55rem; letter-spacing: 0.12em; color: rgba(148,163,184,0.35); margin-bottom: 6px; }
.metric-value { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 1.4rem; font-weight: 700; color: rgba(var(--nc-primary-rgb),0.8); }
.metric-card--sm .metric-value { font-size: 1.1rem; }
.metrics-daily-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.14em; color: rgba(var(--nc-primary-rgb),0.3); margin-bottom: 8px; }
/* IRONKEY Access (owner/admin only) — matches the caps design language. */
.authz-summary { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 14px; }
.authz-mode { font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; letter-spacing: 0.1em; text-transform: uppercase; padding: 3px 8px; border-radius: 5px; border: 1px solid; }
.authz-mode--off { color: rgba(148,163,184,0.7); border-color: rgba(148,163,184,0.3); background: rgba(148,163,184,0.08); }
.authz-mode--shadow { color: rgba(251,191,36,0.9); border-color: rgba(180,83,9,0.4); background: rgba(180,83,9,0.12); }
.authz-mode--enforce { color: rgba(134,239,172,0.95); border-color: rgba(21,128,61,0.4); background: rgba(21,128,61,0.14); }
.authz-deleg { display: inline-flex; align-items: center; gap: 5px; font-family: 'IBM Plex Mono', monospace; font-size: 0.66rem; letter-spacing: 0.04em; }
.authz-deleg--on { color: rgba(16,185,129,0.85); }
.authz-deleg--off { color: rgba(148,163,184,0.45); }
.authz-block { margin-bottom: 12px; }
.authz-block-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.56rem; letter-spacing: 0.12em; color: rgba(148,163,184,0.35); margin-bottom: 6px; }
.authz-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.authz-chip { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; padding: 3px 8px; border-radius: 5px; background: rgba(255,255,255,0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.12); color: rgba(226,232,240,0.75); }
.authz-chip--role { border-color: rgba(var(--nc-primary-rgb),0.3); color: rgba(var(--nc-primary-rgb),0.85); background: rgba(var(--nc-primary-rgb),0.06); }
.authz-deleg-row { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; margin-bottom: 5px; }
.authz-chip--principal { border-color: rgba(255,215,0,0.3); color: rgba(255,215,0,0.8); background: rgba(255,215,0,0.05); }
.authz-chip--delegated { border-style: dashed; color: rgba(226,232,240,0.6); }
.authz-none { font-size: 0.72rem; color: rgba(148,163,184,0.4); font-style: italic; }
.ov-wallet-lines { margin: 0.3rem 0 0.5rem; padding-left: 1.1rem; display: grid; gap: 0.25rem; font-size: 0.82rem; }

/* §REPBOND — skin in the game */
.ov-bond { display: flex; flex-direction: column; gap: 0.6rem; }
.ov-bond-head { display: flex; align-items: center; gap: 0.6rem; flex-wrap: wrap; }
.ov-bond-chip { display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.15rem 0.6rem; border-radius: 999px; font-size: 0.75rem; font-weight: 600;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35); color: rgb(var(--nc-primary-rgb)); background: rgba(var(--nc-primary-rgb), 0.08); }
.ov-bond-chip--matured { border-color: rgba(52,211,153,0.5); color: #34d399; background: rgba(52,211,153,0.1); }
.ov-bond-chip--none, .ov-bond-chip--released, .ov-bond-chip--voided { opacity: 0.7; border-color: rgba(148,163,184,0.4); color: var(--nc-text-muted, #94a3b8); background: transparent; }
.ov-bond-chip--forfeited { border-color: rgba(248,113,113,0.5); color: #f87171; background: rgba(248,113,113,0.08); }
.ov-bond-amt { font-variant-numeric: tabular-nums; font-weight: 600; }
.ov-bond-meta { font-size: 0.75rem; opacity: 0.75; }
.ov-bond-progress { display: flex; flex-direction: column; gap: 0.35rem; }
.ov-bond-row { display: grid; grid-template-columns: 7rem 1fr auto; align-items: center; gap: 0.6rem; font-size: 0.75rem; }
.ov-bond-bar { display: block; height: 6px; border-radius: 3px; background: rgba(148,163,184,0.2); overflow: hidden; }
.ov-bond-bar-fill { display: block; height: 100%; background: rgb(var(--nc-primary-rgb)); transition: width 0.3s; }
.ov-bond-bar-fill.met { background: #34d399; }
.ov-bond-row-r { font-variant-numeric: tabular-nums; opacity: 0.8; }
.ov-bond-stats { display: flex; gap: 1.2rem; flex-wrap: wrap; font-size: 0.75rem; opacity: 0.85; }
.ov-bond-actions { display: flex; flex-direction: column; gap: 0.4rem; align-items: flex-start; }
.ov-bond-error { color: #f87171; }
.ad-notmine {
  margin: 0 0 0.75rem; padding: 0.55rem 0.8rem; border: 1px solid rgba(148, 163, 184, 0.35); border-radius: 6px;
  color: #c3ccd8; font-size: 0.8rem; background: rgba(148, 163, 184, 0.06);
}
</style>
