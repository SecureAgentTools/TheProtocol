<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { safeExternalUrl } from '@/utils/safeUrl'
import { ref, computed, onMounted, watch } from 'vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useRouter, RouterLink } from 'vue-router'
import { useOrganizationStore } from '@/stores/organizations'
import { useAuthStore } from '@/stores/auth'
import { useAgentStore } from '@/stores/agents'
import { useUIStore } from '@/stores/ui'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import type { Organization, Team, OrganizationMember } from '@/services/api/organizationService'
import { organizationService } from '@/services/api/organizationService'
import { exchangeService } from '@/services/api/exchangeService'

import CreateOrganizationModal from '@/components/organizations/CreateOrganizationModal.vue'
import EditOrganizationModal from '@/components/organizations/EditOrganizationModal.vue'
import CreateTeamModal from '@/components/organizations/CreateTeamModal.vue'
import EditTeamModal from '@/components/organizations/EditTeamModal.vue'
import InviteMemberModal from '@/components/organizations/InviteMemberModal.vue'
import OrgPendingInvitations from '@/components/organizations/OrgPendingInvitations.vue'
import TeamMembersModal from '@/components/organizations/TeamMembersModal.vue'
import ChangeMemberRoleModal from '@/components/organizations/ChangeMemberRoleModal.vue'
import AgentAuthorityPanel from '@/components/organizations/AgentAuthorityPanel.vue'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import OrgPolicySettings from '@/components/organizations/OrgPolicySettings.vue'
import OrgOwnershipCard from '@/components/organizations/OrgOwnershipCard.vue'
import OrgRoomCard from '@/components/organizations/OrgRoomCard.vue'
import OrgRoomModeration from '@/components/organizations/OrgRoomModeration.vue'
import OrgSetupChecklist from '@/components/organizations/OrgSetupChecklist.vue'
import OrgWorkOrders from '@/components/organizations/OrgWorkOrders.vue'
import OrgBooks from '@/components/organizations/OrgBooks.vue'
import OrgActivityRollup from '@/components/organizations/OrgActivityRollup.vue'
import { useI18n } from '@/composables/useI18n'

const { t, tp } = useI18n()

// ── Stores ────────────────────────────────────────────────────────────────────
const router = useRouter()
const orgStore = useOrganizationStore()
const authStore = useAuthStore()
const agentStore = useAgentStore()
const uiStore = useUIStore()

// ── UI State ──────────────────────────────────────────────────────────────────
const selectedOrgId = ref('')
const activeTab = ref<'teams' | 'activity' | 'members' | 'agents' | 'room' | 'authority' | 'cicd' | 'treasury' | 'governance' | 'settings' | 'audit'>('teams')
const showCreateOrgModal = ref(false)
const showEditOrgModal = ref(false)
const showCreateTeamModal = ref(false)
const showInviteMemberModal = ref(false)
const editingTeam = ref<Team | null>(null)
const viewingTeam = ref<Team | null>(null)
const changingRoleMember = ref<OrganizationMember | null>(null)
const expandedTeamPerms = ref<Set<string>>(new Set())
// §pass50.1 — member detail drawer (right-side panel with developer profile + permissions)
const detailMember = ref<OrganizationMember | null>(null)

function openMemberDetail(member: OrganizationMember) {
  detailMember.value = member
}
function closeMemberDetail() {
  detailMember.value = null
}
function openAgentCicd(did: string | undefined | null) {
  if (!did) return
  router.push({ name: 'agent-cicd', params: { did } })
}

// Settings inline form
const settingsForm = ref({ name: '', description: '', website: '' })
const isSavingSettings = ref(false)

// ── Computed ──────────────────────────────────────────────────────────────────
const org = computed(() => orgStore.currentOrganization)
// §FESUITE (V0577): Try again on a failed teams / members read
function retryTeams() { if (org.value) return orgStore.fetchTeams(org.value.id) }
function retryMembers() { if (org.value) return orgStore.fetchMembers(org.value.id) }
/** read the organizations again (the store says whether it failed). The store reads only for a known developer, and a
 *  profile whose read failed is never read again by itself: read it first, as the page's mount does (lifecycle 59). */
async function retryOrgs() {
  try {
    if (!authStore.user && authStore.token) await authStore.initializeAuth()
    await orgStore.fetchOrganizations()
  } catch { /* listFailed speaks */ }
}

const orgAgentLimit = computed(() => {
  if (!org.value) return 1000
  // Backend returns limits as a dict, frontend type uses flat fields
  return (org.value as any).limits?.agent_limit ?? org.value.agent_limit ?? 1000
})
const orgMemberLimit = computed(() => {
  if (!org.value) return 100
  return (org.value as any).limits?.member_limit ?? org.value.member_limit ?? 100
})
const orgTeamLimit = computed(() => {
  if (!org.value) return 10
  return (org.value as any).limits?.team_limit ?? org.value.team_limit ?? 10
})

const memberCount  = computed(() => orgStore.members.length || org.value?.member_count || 0)
const teamCount    = computed(() => orgStore.teams.length  || org.value?.team_count  || 0)
const memberPct    = computed(() => Math.min(100, Math.round((memberCount.value / orgMemberLimit.value) * 100)))
const teamPct      = computed(() => Math.min(100, Math.round((teamCount.value  / orgTeamLimit.value)  * 100)))

// My agents (loaded during auth — zero extra calls)
const myAgents = computed(() => {
  const agList = agentStore.agents || []
  // Merge balance data from auth store's available agents
  const available = authStore.availableAgents || []
  return agList.map(a => {
    const rich = available.find((x: any) => (x.did || x.agent_did) === (a.did || a.agent_did))
    return { ...a, ...(rich || {}) }
  })
})
const agentPct = computed(() => Math.min(100, Math.round((myAgents.value.length / orgAgentLimit.value) * 100)))

// Org-assigned agents (fetched from API)
const orgAgents = ref<any[]>([])
const orgAgentsLoading = ref(false)
// §FESUITE (V0575): a failed read is not "No agents in this org", and the tab's count shows only for a list that was read
const orgAgentsFailed = ref(false)
const orgAgentsRead = ref(false)

// §FESUITE 135 (agentvault2-5b, 2026-10-15; agentvault2-61's finding): the organization picked last owns the screen. On a
// switch every pane reloads, and an answer that lands after it is no longer wanted (a quick A, then B) is dropped: it had
// put A's treasury, approvals or audit under B's header, where every action keys on B's id. One counter per pane: an answer
// is applied only when its load is the pane's latest and its organization is still the current one; only the pane's
// latest load ends its loading state.
function paneLoads() {
  let seq = 0
  return () => {
    const mine = ++seq
    const oid = orgStore.currentOrganization?.id || ''
    return {
      oid,
      fresh: () => mine === seq && !!oid && oid === (orgStore.currentOrganization?.id || ''),
      last: () => mine === seq,
    }
  }
}
const orgAgentsLoad = paneLoads()
async function fetchOrgAgents() {
  const load = orgAgentsLoad()
  if (!load.oid) return
  orgAgentsLoading.value = true
  orgAgentsFailed.value = false
  orgAgentsRead.value = false
  try {
    const { apiClient } = await import('@/services/api/client')
    const res = await apiClient.get(`/organizations/${load.oid}/agents`)
    if (!load.fresh()) return
    orgAgents.value = res.data?.agents || []
    orgAgentsRead.value = true
  } catch { if (load.fresh()) { orgAgents.value = []; orgAgentsFailed.value = true } }
  finally { if (load.last()) orgAgentsLoading.value = false }
}

async function assignAgent(agentDid: string) {
  if (!selectedOrgId.value) return
  try {
    const { apiClient } = await import('@/services/api/client')
    await apiClient.post(`/organizations/${selectedOrgId.value}/agents/${agentDid}/assign`)
    uiStore.showSuccess('Agent Assigned', `${agentDid.slice(0, 24)}... assigned to organization`)
    await fetchOrgAgents()
  } catch (e: any) {
    uiStore.showError('Assignment Failed', e?.response?.data?.detail || 'Could not assign agent')
  }
}

async function unassignAgent(agentDid: string) {
  if (!selectedOrgId.value) return
  try {
    const { apiClient } = await import('@/services/api/client')
    await apiClient.post(`/organizations/${selectedOrgId.value}/agents/${agentDid}/unassign`)
    uiStore.showSuccess('Agent Removed', `Agent removed from organization`)
    await fetchOrgAgents()
  } catch (e: any) {
    uiStore.showError('Removal Failed', e?.response?.data?.detail || 'Could not remove agent')
  }
}

// Agents that can be assigned (owned by me, not already in this org)
const assignableAgents = computed(() => {
  const orgDids = new Set(orgAgents.value.map((a: any) => a.did))
  return myAgents.value.filter(a => !orgDids.has(a.did || a.agent_did))
})

const tabs = computed(() => [
  // §FESUITE (V0577): an unread list has no count (a failed teams/members read is not "0")
  { id: 'teams',   label: 'TEAMS',   count: orgStore.teamsFailed ? undefined : orgStore.teams.length },
  // E3 — org-wide money/denial roll-up (owner/admin): spend per agent, denials,
  // parked approvals, treasury flow. The screen an org admin lives in.
  ...(myRole.value === 'owner' || myRole.value === 'admin'
    ? [{ id: 'activity', label: 'ACTIVITY' }] : []),
  { id: 'members', label: 'MEMBERS', count: orgStore.membersFailed ? undefined : orgStore.members.length },
  { id: 'agents',  label: 'AGENTS',  count: orgAgentsRead.value ? orgAgents.value.length : undefined },
  // §CHATDESK C3 — the org's ROOM: the card (switch/policy/door) + the moderation
  // sheet, administered where the org lives. (Label hardcoded like its siblings.)
  { id: 'room',    label: 'ROOM'                                    },
  // Track A2 — org→agent authority (IRONKEY org grants); owner/admin surface
  ...(myRole.value === 'owner' || myRole.value === 'admin'
    ? [{ id: 'authority', label: 'AUTHORITY' }] : []),
  // §FESUITE (V0575): a count is shown once its read answered; an unread or failed summary is not "0"
  { id: 'cicd',    label: 'CI/CD',   count: cicdSummary.value?.deployments?.total },
  { id: 'treasury',label: 'TREASURY',count: treasury.value?.listing_count },
  { id: 'governance',label: 'GOVERNANCE'                             },
  { id: 'settings',label: 'SETTINGS'                                 },
  // Track A6 — the org's own EventStore audit trail (owner/admin)
  ...(myRole.value === 'owner' || myRole.value === 'admin'
    ? [{ id: 'audit', label: 'AUDIT' }] : []),
])

// §CHATDESK H1.1 — the FIRM's track record: read-side aggregation over settled
// guild receipts' payee_org_id (the write side has existed since firm bids).
// Honest zeros: the endpoint answers zeros; the header chip hides at 0.
const orgTr = ref<any>(null)
const orgTrLoad = paneLoads()
async function loadOrgTr() {
  const load = orgTrLoad()
  orgTr.value = null   // the previous organization's chip never stands under this one's header
  if (!load.oid) return
  try { const r = await organizationService.getOrgTrackRecord(load.oid); if (load.fresh()) orgTr.value = r }
  catch { if (load.fresh()) orgTr.value = null }
}
watch(() => orgStore.currentOrganization?.id, () => loadOrgTr(), { immediate: true })

// §pass49 F3 — Org-scoped CI/CD summary (uses O4 endpoint).
const cicdSummary = ref<any>(null)
const cicdLoading = ref(false)
const cicdLoad = paneLoads()
async function loadCicdSummary() {
  const load = cicdLoad()
  if (!load.oid) return
  cicdLoading.value = true
  try {
    const r = await organizationService.getCicdSummary(load.oid)
    if (load.fresh()) cicdSummary.value = r
  } catch (e) {
    if (!load.fresh()) return
    console.warn('[OrgDashboard F3] cicd-summary load failed', e)
    cicdSummary.value = null
  } finally {
    if (load.last()) cicdLoading.value = false
  }
}
// §V0113 — Org consolidated treasury (holding-company roll-up).
const treasury = ref<Awaited<ReturnType<typeof exchangeService.orgTreasury>> | null>(null)
const treasuryLoading = ref(false)
// §FESUITE (V0577): the listings roll-up got no answer. It became null, so the Treasury tab said "No listings yet, the
// treasury appears once this org lists one…" and the Governance tab "No listings yet, governance opens once…".
const treasuryFailed = ref(false)

// ── Track C3 — the org's OWN treasury account (distinct from the AGORA listing purses) ──
const orgAccount = ref<{ treasury_agent_did: string | null; source: string | null; balance: string | null; exists: boolean } | null>(null)
const orgAccountLoading = ref(false)
// §FESUITE (V0577): the account read got no answer. It became null: badge "none", "This organization has no money account
// yet." and, to the owner, "Create treasury account" over an account that may exist.
const orgAccountFailed = ref(false)
const orgAccountBusy = ref(false)
const orgAccountMsg = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)
const fundAgentDid = ref('')
const fundAmount = ref('')
const orgMoneyEvents = ref<{ event_type: string; timestamp: string | null; data: Record<string, any> }[]>([])

const orgAccountLoad = paneLoads()
async function loadOrgAccount() {
  const load = orgAccountLoad()
  if (!load.oid) return
  orgAccountLoading.value = true
  orgAccountFailed.value = false
  try {
    const r = await organizationService.getOrgTreasuryAccount(load.oid)
    if (load.fresh()) orgAccount.value = r
  } catch (e) {
    if (load.fresh()) {
      console.warn('[OrgDashboard C3] treasury account load failed', e)
      orgAccount.value = null
      orgAccountFailed.value = true
    }
  } finally {
    if (load.last()) orgAccountLoading.value = false
  }
  // Movements come from the org's own audit trail (A6) — the fund/remit rails emit
  // OrganizationTreasury* on the org aggregate, so this needs no second source of truth.
  if (canManageTreasury.value && load.fresh()) {
    try {
      const r = await organizationService.getOrgAuditEvents(load.oid, {
        eventTypes: 'OrganizationTreasuryFunded,OrganizationTreasuryRemitted', limit: 25,
      })
      if (load.fresh()) orgMoneyEvents.value = r.events || []
    } catch { if (load.fresh()) orgMoneyEvents.value = [] }
  }
}

async function createOrgAccount() {
  if (!orgStore.currentOrganization?.id || orgAccountBusy.value) return
  orgAccountBusy.value = true; orgAccountMsg.value = null
  try {
    const r = await organizationService.createOrgTreasuryAccount(orgStore.currentOrganization.id)
    orgAccountMsg.value = { kind: 'ok', text: r.created ? 'Treasury account created.' : 'Treasury already existed.' }
    await loadOrgAccount()
  } catch (e: any) {
    orgAccountMsg.value = { kind: 'err', text: e?.response?.data?.detail || e?.message || 'Create failed' }
  } finally { orgAccountBusy.value = false }
}

async function submitFund() {
  if (!orgStore.currentOrganization?.id || orgAccountBusy.value) return
  if (!fundAgentDid.value || !fundAmount.value) return
  orgAccountBusy.value = true; orgAccountMsg.value = null
  // ONE key per user-initiated transfer. The server requires it and derives BOTH escrow legs
  // from it, so a retry of THIS transfer must reuse THIS key — never generate a fresh one on
  // retry, or the debit leg runs twice.
  const idem = `orgfund-ui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  try {
    await organizationService.fundOrgAgent(orgStore.currentOrganization.id, fundAgentDid.value, String(fundAmount.value), idem)
    orgAccountMsg.value = { kind: 'ok', text: `Sent ${fundAmount.value} to ${fundAgentDid.value.slice(0, 28)}…` }
    fundAmount.value = ''
    await loadOrgAccount()
  } catch (e: any) {
    orgAccountMsg.value = { kind: 'err', text: e?.response?.data?.detail || e?.message || 'Transfer failed' }
  } finally { orgAccountBusy.value = false }
}
const treasuryLoad = paneLoads()
async function loadTreasury() {
  const load = treasuryLoad()
  if (!load.oid) return
  treasuryLoading.value = true
  treasuryFailed.value = false
  try {
    const r = await exchangeService.orgTreasury(load.oid)
    if (!load.fresh()) return
    treasury.value = r
    // §T75 — pull each listing's committed market-makers + rebate config (public reads).
    for (const l of (treasury.value?.listings || [])) void loadMarketMakers(l.symbol)
  } catch (e) {
    if (!load.fresh()) return
    console.warn('[OrgDashboard V0113] treasury load failed', e)
    treasury.value = null
    treasuryFailed.value = true
  } finally {
    if (load.last()) treasuryLoading.value = false
  }
}
function fmtAmt(s: string | null): string {
  if (s === null || s === undefined) return '—'
  const n = Number(s)
  return isFinite(n) ? n.toLocaleString(appLocale(), { maximumFractionDigits: 2 }) : s
}

// §V0113 Phase 2 — org treasury spend actions (org-admin only). The treasury_agent_did
// is keyless; every spend rides the Δ-safe server spine (treasury_move / place_order /
// declare_dividend). Inline per-row forms collect inputs; ConfirmActionModal is the
// final confirm step before the call.
// §T75/§T77 — + 'rebate' (P2.2 maker rebate), 'mmseat' (P2.2 grant/revoke MM seat), 'fees' (P5 fee-edit)
type TreasuryAction = 'dividend' | 'buyback' | 'transfer' | 'sweep' | 'refloat' | 'sell' | 'mm' | 'rebate' | 'mmseat' | 'fees'
const canManageTreasury = computed(() => myRole.value === 'owner' || myRole.value === 'admin')
// §BAFIN (2026-10-01): no distribution door where this registry declares none (core/agora_gate.py)
const { config: orgRegistryCfg } = useRegistryConfig()
// §BAFIN B.5.5 (agentvault2-5b, 2026-10-03): fail-closed. No distribution door shows until the registry has
// said distributions are on; `!== false` showed one while the config was in flight and kept it if the read failed.
const agoraDistOn = computed(() => orgRegistryCfg.value.agora_distributions_enabled === true)
const treasuryActionRow = ref<string | null>(null)   // symbol whose action panel is open
const treasuryActionKind = ref<TreasuryAction | null>(null)
// form fields (one set, scoped by the open row)
const taPerShare = ref('')
const taQty = ref<number | null>(null)
const taLimitPrice = ref('')
const taDestDid = ref('')
const taAmount = ref('')
const taReserveFloor = ref('')
const taOfferPrice = ref('')                              // §P1.1 refloat offer (optional → market)
const taOrderType = ref<'limit' | 'market'>('limit')      // §P1.2 sell order type
const taMmEnabled = ref(false)                            // §P2.1 MM toggle
const taMmSpread = ref<number>(200)                       // §P2.1 MM spread bps
const taMmQty = ref<number>(100)                          // §P2.1 MM quote qty/side
// §T75 P2.2 maker rebate
const taRebateBps = ref<number>(0)
const taRebateRequiresReg = ref(true)
// §T75 P2.2 MM seat grant/revoke
const taMmSeatDid = ref('')
const taMmSeatStatus = ref<'active' | 'suspended' | 'revoked'>('active')
const taMmSeatMaxSpread = ref<number | null>(null)
// §T77 P5 fee-edit (blank → leave that field unchanged)
const taFeeBps = ref<number | null>(null)
const taFeeOrgSplitBps = ref<number | null>(null)
const taFeeRebateBps = ref<number | null>(null)
const showTreasuryConfirm = ref(false)
const treasuryActionBusy = ref(false)
// §T75 — committed market-makers per symbol (public read; powers the inline panel + grant prefill)
const mmBySymbol = ref<Record<string, Awaited<ReturnType<typeof exchangeService.marketMakers>>>>({})
async function loadMarketMakers(symbol: string) {
  try { mmBySymbol.value = { ...mmBySymbol.value, [symbol]: await exchangeService.marketMakers(symbol) } }
  catch { /* dark venue / no listing — panel stays hidden */ }
}

// §AGORAWORDS: display-only label for the internal action kind (the TreasuryAction
// type/values are unchanged; this only controls what a person reads).
function treasuryActionLabel(kind: TreasuryAction | string | null): string {
  if (kind === 'dividend') return 'distribution'
  if (kind === 'buyback') return 'treasury buy'
  if (kind === 'refloat') return 're-release'
  return kind || ''
}

function openTreasuryAction(symbol: string, kind: TreasuryAction) {
  if (treasuryActionRow.value === symbol && treasuryActionKind.value === kind) {
    treasuryActionRow.value = null
    treasuryActionKind.value = null
    return
  }
  treasuryActionRow.value = symbol
  treasuryActionKind.value = kind
  taPerShare.value = ''
  taQty.value = null
  taLimitPrice.value = ''
  taDestDid.value = ''
  taAmount.value = ''
  taReserveFloor.value = ''
  taOfferPrice.value = ''
  taOrderType.value = 'limit'
  taMmEnabled.value = false
  taMmSpread.value = 200
  taMmQty.value = 100
  // §T75/§T77 resets
  taRebateBps.value = 0
  taRebateRequiresReg.value = true
  taMmSeatDid.value = ''
  taMmSeatStatus.value = 'active'
  taMmSeatMaxSpread.value = null
  taFeeBps.value = null
  taFeeOrgSplitBps.value = null
  taFeeRebateBps.value = null
  if (kind === 'mm') {
    exchangeService.treasuryMMGet(orgStore.currentOrganization?.id || '', symbol).then((c: any) => {
      if (c?.configured) { taMmEnabled.value = !!c.enabled; taMmSpread.value = c.spread_bps ?? 200; taMmQty.value = c.quote_qty ?? 100 }
    }).catch(() => {})
  }
  // §T75 — prefill current rebate from the public MM list (also surfaces it in the panel).
  if (kind === 'rebate' || kind === 'mmseat') {
    void loadMarketMakers(symbol).then(() => {
      const mm = mmBySymbol.value[symbol]
      if (mm && kind === 'rebate') { taRebateBps.value = mm.maker_rebate_bps ?? 0; taRebateRequiresReg.value = mm.rebate_requires_registration ?? true }
    })
  }
}

const treasuryActionValid = computed(() => {
  const k = treasuryActionKind.value
  if (k === 'dividend') return Number(taPerShare.value) > 0
  if (k === 'buyback') return (taQty.value ?? 0) > 0 && Number(taLimitPrice.value) > 0
  if (k === 'transfer') return taDestDid.value.trim().length > 0 && Number(taAmount.value) > 0
  if (k === 'sweep') return taDestDid.value.trim().length > 0 && Number(taAmount.value) > 0
  if (k === 'refloat') return (taQty.value ?? 0) > 0
  if (k === 'sell') return (taQty.value ?? 0) > 0 && (taOrderType.value === 'market' || Number(taLimitPrice.value) > 0)
  if (k === 'mm') return (taMmSpread.value ?? 0) > 0 && (taMmQty.value ?? 0) > 0
  if (k === 'rebate') return (taRebateBps.value ?? -1) >= 0           // 0 is valid (disable rebate)
  if (k === 'mmseat') return taMmSeatDid.value.trim().length > 2
  if (k === 'fees') return taFeeBps.value != null || taFeeOrgSplitBps.value != null || taFeeRebateBps.value != null
  return false
})

const treasuryConfirmMessage = computed(() => {
  const sym = treasuryActionRow.value || ''
  const cur = treasury.value?.currency || ''
  const k = treasuryActionKind.value
  if (k === 'dividend') return `Declare a distribution of <strong>${taPerShare.value} ${cur}</strong> per point on <code>$${sym}</code>? The settlement worker funds the pot from the treasury and pays external holders.`
  if (k === 'buyback') return `Place a treasury BUY for <strong>${taQty.value}</strong> points of <code>$${sym}</code> at limit <strong>${taLimitPrice.value} ${cur}</strong>? Funds escrow from the treasury and matches on the book.`
  if (k === 'transfer') return `Transfer <strong>${taAmount.value} ${cur}</strong> from the <code>$${sym}</code> treasury to <code>${taDestDid.value}</code>?${taReserveFloor.value ? ` Reserve floor: ${taReserveFloor.value}.` : ''}`
  if (k === 'sweep') return `Sweep <strong>${taAmount.value} ${cur}</strong> from the <code>$${sym}</code> treasury to the <code>$${taDestDid.value.toUpperCase()}</code> treasury (same org)?`
  if (k === 'refloat') return `Release <strong>${taQty.value}</strong> points of <code>$${sym}</code> from the treasury into the buyable supply${taOfferPrice.value ? ` at <strong>${taOfferPrice.value} ${cur}</strong>` : ' at the current market price'}? Pure points-ledger move, no funds, Δ-safe.`
  if (k === 'sell') return `Place a treasury <strong>${taOrderType.value.toUpperCase()} SELL</strong> of <strong>${taQty.value}</strong> points of <code>$${sym}</code>${taOrderType.value === 'limit' ? ` at limit <strong>${taLimitPrice.value} ${cur}</strong>` : ' at market'}? Distributes points via the order book; proceeds settle to the treasury.`
  if (k === 'mm') return `${taMmEnabled.value ? 'Enable' : 'Disable'} the treasury market-maker on <code>$${sym}</code>${taMmEnabled.value ? ` (spread <strong>${taMmSpread.value}bps</strong>, <strong>${taMmQty.value}</strong> points/side)` : ''}? Maintains two-sided treasury quotes; Δ-safe. (Requires <code>TREASURY_MM_ENABLED</code> on this frame.)`
  if (k === 'rebate') return `Set the maker rebate on <code>$${sym}</code> to <strong>${taRebateBps.value} bps</strong>, ${taRebateRequiresReg.value ? 'restricted to <strong>registered MM seats</strong>' : 'open to <strong>any maker</strong>'}? Carved from the protocol fee slice at settlement — Δ-neutral.`
  if (k === 'mmseat') return `${taMmSeatStatus.value === 'revoked' ? 'Revoke' : taMmSeatStatus.value === 'suspended' ? 'Suspend' : 'Grant an'} MM seat on <code>$${sym}</code> for <code>${taMmSeatDid.value.trim()}</code> (status <strong>${taMmSeatStatus.value}</strong>)?`
  if (k === 'fees') {
    const parts: string[] = []
    if (taFeeBps.value != null) parts.push(`fee <strong>${taFeeBps.value} bps</strong>`)
    if (taFeeOrgSplitBps.value != null) parts.push(`org split <strong>${taFeeOrgSplitBps.value} bps</strong>`)
    if (taFeeRebateBps.value != null) parts.push(`maker rebate <strong>${taFeeRebateBps.value} bps</strong>`)
    return `Update the fee schedule on <code>$${sym}</code> → ${parts.join(', ')}? Only new trades stamp the new schedule — no existing trade, escrow, or balance is touched.`
  }
  return ''
})

async function confirmTreasuryAction() {
  const orgId = orgStore.currentOrganization?.id
  const sym = treasuryActionRow.value
  const k = treasuryActionKind.value
  if (!orgId || !sym || !k) return
  treasuryActionBusy.value = true
  try {
    if (k === 'dividend') {
      await exchangeService.treasuryDividend(orgId, sym, taPerShare.value)
    } else if (k === 'buyback') {
      await exchangeService.treasuryBuyback(orgId, sym, taQty.value as number, taLimitPrice.value)
    } else if (k === 'transfer') {
      await exchangeService.treasuryTransfer(orgId, sym, taDestDid.value.trim(), taAmount.value, taReserveFloor.value || undefined)
    } else if (k === 'sweep') {
      await exchangeService.treasurySweep(orgId, sym, taDestDid.value.trim().toUpperCase(), taAmount.value)
    } else if (k === 'refloat') {
      await exchangeService.treasuryRefloat(orgId, sym, taQty.value as number, taOfferPrice.value || undefined)
    } else if (k === 'sell') {
      await exchangeService.treasurySell(orgId, sym, taQty.value as number, taOrderType.value, taOrderType.value === 'limit' ? taLimitPrice.value : undefined)
    } else if (k === 'mm') {
      await exchangeService.treasuryMMSet(orgId, sym, { enabled: taMmEnabled.value, spread_bps: taMmSpread.value, quote_qty: taMmQty.value })
    } else if (k === 'rebate') {
      await exchangeService.setMakerRebate(orgId, sym, taRebateBps.value, taRebateRequiresReg.value)
    } else if (k === 'mmseat') {
      await exchangeService.grantMarketMaker(orgId, sym, { agent_did: taMmSeatDid.value.trim(), status: taMmSeatStatus.value, max_spread_bps: taMmSeatMaxSpread.value ?? undefined })
    } else if (k === 'fees') {
      await exchangeService.setListingFees(orgId, sym, {
        fee_bps: taFeeBps.value ?? undefined,
        fee_org_split_bps: taFeeOrgSplitBps.value ?? undefined,
        maker_rebate_bps: taFeeRebateBps.value ?? undefined,
      })
    }
    uiStore.showSuccess('Treasury action complete', `$${sym} ${k} submitted.`)
    showTreasuryConfirm.value = false
    treasuryActionRow.value = null
    treasuryActionKind.value = null
    if (k === 'rebate' || k === 'mmseat' || k === 'fees') await loadMarketMakers(sym)
    await loadTreasury()
  } catch (e: any) {
    uiStore.showError('Treasury action failed', e?.response?.data?.detail || e?.message || 'Could not complete the treasury action')
  } finally {
    treasuryActionBusy.value = false
  }
}

// ════ §P3.1 share-weighted governance (proposals: list / create / vote / tally) ════
// Reads (list/get) are public; create + tally = org-admin dev JWT; VOTE = agent JWT
// (the client.ts interceptor routes /exchange/proposals/*/vote to the active agent token).
const canManageGov = computed(() => myRole.value === 'owner' || myRole.value === 'admin')
const govSymbols = computed<string[]>(() => (treasury.value?.listings || []).map((l: any) => l.symbol))
const govSelectedSymbol = ref('')
const govProposals = ref<any[]>([])
const govLoading = ref(false)
const govDetail = ref<any | null>(null)
const govDetailLoading = ref(false)
const showCreateProposal = ref(false)
const cpTitle = ref(''); const cpDescription = ref('')
const cpDurationDays = ref<number>(7); const cpQuorum = ref<number>(20); const cpPass = ref<number>(50)
const cpBusy = ref(false)
const voteReason = ref(''); const voteBusy = ref(false); const tallyBusy = ref(false)
const activeAgentDid = computed<string | null>(() => (authStore.activeAgent as any)?.did || null)

async function loadGovernance() {
  if (!treasury.value) await loadTreasury()          // treasury roll-up carries the org's tickers
  if (!govSelectedSymbol.value && govSymbols.value.length) govSelectedSymbol.value = govSymbols.value[0]
  await loadProposals()
}
// §FESUITE (V0575): a failed read is not "No proposals for $X yet · Open the first proposal"
const govFailed = ref(false)
const proposalsLoad = paneLoads()
async function loadProposals() {
  const load = proposalsLoad()
  const symbol = govSelectedSymbol.value
  // the answer must also still be for the listing picked (a quick $A, then $B)
  const fresh = () => load.fresh() && symbol === govSelectedSymbol.value
  govDetail.value = null
  govFailed.value = false
  if (!symbol) { govProposals.value = []; if (load.last()) govLoading.value = false; return }
  govLoading.value = true
  try { const r = await exchangeService.listProposals(symbol); if (fresh()) govProposals.value = r?.proposals || [] }
  catch { if (fresh()) { govProposals.value = []; govFailed.value = true } }
  finally { if (load.last()) govLoading.value = false }
}
const proposalLoad = paneLoads()
async function openProposal(id: string) {
  const load = proposalLoad()
  govDetailLoading.value = true
  try { const r = await exchangeService.getProposal(id); if (load.fresh()) govDetail.value = r }
  catch (e: any) {
    if (!load.fresh()) return
    uiStore.showError('Could not load proposal', e?.response?.data?.detail || e?.message || ''); govDetail.value = null
  }
  finally { if (load.last()) govDetailLoading.value = false }
}
function closeProposal() { govDetail.value = null; voteReason.value = '' }
function govPct(part: number, whole: number): number { return whole > 0 ? Math.min(100, (Number(part) / Number(whole)) * 100) : 0 }

async function submitProposal() {
  const orgId = orgStore.currentOrganization?.id
  if (!orgId || !govSelectedSymbol.value || !cpTitle.value.trim() || !cpDescription.value.trim()) return
  cpBusy.value = true
  try {
    await exchangeService.createProposal(orgId, {
      symbol: govSelectedSymbol.value, title: cpTitle.value.trim(), description: cpDescription.value.trim(),
      duration_seconds: Math.max(60, Math.round((cpDurationDays.value || 7) * 86400)),
      quorum_pct: cpQuorum.value, pass_pct: cpPass.value,
    })
    uiStore.showSuccess('Proposal opened', `$${govSelectedSymbol.value} proposal created — holders enfranchised at snapshot.`)
    showCreateProposal.value = false; cpTitle.value = ''; cpDescription.value = ''
    await loadProposals()
  } catch (e: any) {
    uiStore.showError('Could not open proposal', e?.response?.data?.detail || e?.message || 'create failed')
  } finally { cpBusy.value = false }
}
function pickShareholderAgent() { (authStore as any).showAgentSelector = true }
async function castGovVote(inFavor: boolean) {
  if (!govDetail.value) return
  if (!activeAgentDid.value) {
    pickShareholderAgent()   // open the agent selector inline instead of a dead-end error toast
    return
  }
  voteBusy.value = true
  try {
    const r = await exchangeService.castVote(govDetail.value.id, inFavor, voteReason.value || undefined)
    uiStore.showSuccess('Vote cast', `Voted ${inFavor ? 'FOR' : 'AGAINST'} with weight ${r?.weight ?? '—'}.`)
    voteReason.value = ''
    await openProposal(govDetail.value.id)
  } catch (e: any) {
    uiStore.showError('Vote failed', e?.response?.data?.detail || e?.message || 'could not cast vote')
  } finally { voteBusy.value = false }
}
async function runGovTally() {
  if (!govDetail.value) return
  tallyBusy.value = true
  try {
    await exchangeService.tallyProposal(govDetail.value.id)
    uiStore.showSuccess('Tally refreshed', 'Quorum + pass recomputed (finalizes once voting ends).')
    await openProposal(govDetail.value.id); await loadProposals()
  } catch (e: any) {
    uiStore.showError('Tally failed', e?.response?.data?.detail || e?.message || 'could not tally')
  } finally { tallyBusy.value = false }
}

// Reload when org switches or tab opens.
watch(() => orgStore.currentOrganization?.id, () => {
  cicdSummary.value = null
  treasury.value = null; treasuryFailed.value = false
  // §FESUITE 135 (2026-10-15): the money account was kept, so after a switch made on another tab the Treasury tab showed
  // the previous organization's account (its load runs only when none is held); an open action or fund form is the
  // previous organization's too, and its confirm would key on this one's id
  orgAccount.value = null; orgAccountFailed.value = false; orgMoneyEvents.value = []; orgAccountMsg.value = null
  fundAgentDid.value = ''; fundAmount.value = ''
  treasuryActionRow.value = null; treasuryActionKind.value = null; showTreasuryConfirm.value = false
  govProposals.value = []; govDetail.value = null; govSelectedSymbol.value = ''; govFailed.value = false
  auditEvents.value = []; auditError.value = ''
  orgApprovals.value = []; orgApprovalsError.value = ''
  if (activeTab.value === 'cicd') loadCicdSummary()
  if (activeTab.value === 'treasury') { loadTreasury(); loadOrgAccount() }
  if (activeTab.value === 'governance') loadGovernance()
  if (activeTab.value === 'audit') loadOrgAudit()
  if (activeTab.value === 'authority') loadOrgApprovals()
})
watch(activeTab, (v) => {
  if (v === 'cicd' && !cicdSummary.value) loadCicdSummary()
  if (v === 'treasury') { if (!treasury.value) loadTreasury(); if (!orgAccount.value) loadOrgAccount() }
  if (v === 'governance') loadGovernance()
  if (v === 'audit') loadOrgAudit()
  if (v === 'authority') loadOrgApprovals()
})

// Track A6 — org audit trail (owner/admin; honest error state, never silent-empty)
const auditEvents = ref<{ event_type: string; timestamp: string | null; data: Record<string, any> }[]>([])
const auditLoading = ref(false)
const auditError = ref('')
const auditLoad = paneLoads()
let auditFor = ''   // the organization whose trail is being read: a second load for it waits on the first
async function loadOrgAudit() {
  const oid = orgStore.currentOrganization?.id || ''
  if (!oid || (auditLoading.value && auditFor === oid)) return
  const load = auditLoad()
  auditFor = oid
  auditLoading.value = true
  auditError.value = ''
  try {
    const r = await organizationService.getOrgAuditEvents(load.oid, { limit: 200 })
    if (load.fresh()) auditEvents.value = r.events
  } catch (e: any) {
    if (!load.fresh()) return
    auditError.value = e?.message || 'Failed to load audit trail'
    auditEvents.value = []
  } finally {
    if (load.last()) { auditLoading.value = false; auditFor = '' }
  }
}
// B3 oversight — org agents' spend-approval queue (owner/admin; READ-ONLY here:
// deciding stays with each agent's owning developer, who is the liable party).
const orgApprovals = ref<Awaited<ReturnType<typeof organizationService.listOrgSpendApprovals>>['approvals']>([])
const orgApprovalsLoading = ref(false)
const orgApprovalsError = ref('')
const approvalsLoad = paneLoads()
let approvalsFor = ''
async function loadOrgApprovals() {
  const oid = orgStore.currentOrganization?.id || ''
  if (!oid || (orgApprovalsLoading.value && approvalsFor === oid)) return
  const load = approvalsLoad()
  approvalsFor = oid
  orgApprovalsLoading.value = true
  orgApprovalsError.value = ''
  try {
    const r = await organizationService.listOrgSpendApprovals(load.oid, undefined, 50)
    if (load.fresh()) orgApprovals.value = r.approvals
  } catch (e: any) {
    if (!load.fresh()) return
    orgApprovalsError.value = e?.message || 'Failed to load spend approvals'
    orgApprovals.value = []
  } finally {
    if (load.last()) { orgApprovalsLoading.value = false; approvalsFor = '' }
  }
}
function approvalWhen(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString(appLocale()) : '—'
}
function approvalAmt(v: string): string {
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(appLocale(), { maximumFractionDigits: 6 }) : v
}

function auditSummary(ev: { event_type: string; data: Record<string, any> }): string {
  const d = ev.data || {}
  const bits: string[] = []
  if (d.email) bits.push(String(d.email))
  if (d.developer_id != null) bits.push(`dev ${d.developer_id}`)
  if (d.old_role && d.new_role) bits.push(`${d.old_role} → ${d.new_role}`)
  else if (d.role) bits.push(String(d.role))
  if (d.role_slice) bits.push(`slice ${d.role_slice} → ${d.agents} agents`)
  if (d.revoked != null) bits.push(`${d.revoked} revoked`)
  if (d.former_role) bits.push(`was ${d.former_role}`)
  return bits.join(' · ')
}

// Current user's role in this org
const myRole = computed(() => orgStore.currentUserRole)

const roleLabel = computed(() => {
  const r = myRole.value
  if (!r) return null
  return r.toUpperCase()
})

// ── Helpers ───────────────────────────────────────────────────────────────────
function permChipClass(perm: string): string {
  if (perm.startsWith('read_')   || perm === 'agents.view') return 'perm--read'
  if (perm.startsWith('create_') || perm === 'agents.create' || perm === 'contracts.create') return 'perm--create'
  if (perm.startsWith('update_') || perm === 'agents.edit') return 'perm--update'
  if (perm.startsWith('delete_') || perm === 'agents.delete') return 'perm--delete'
  if (perm.startsWith('admin')   || perm === 'members.invite' || perm === 'teams.manage') return 'perm--admin'
  return 'perm--default'
}

function roleBadgeClass(role: string): string {
  switch (role) {
    case 'owner':  return 'role--owner'
    case 'admin':  return 'role--admin'
    case 'member': return 'role--member'
    case 'guest':  return 'role--guest'
    default:       return 'role--guest'
  }
}

function avatarStyle(role: string): string {
  switch (role) {
    case 'owner':  return 'background:rgba(255,215,0,0.15);color:#ffd700;border:1px solid rgba(255,215,0,0.25)'
    case 'admin':  return 'background:rgba(var(--nc-primary-rgb),0.12);color:rgba(var(--nc-primary-rgb),0.9);border:1px solid rgba(var(--nc-primary-rgb),0.2)'
    case 'member': return 'background:rgba(41,182,246,0.12);color:rgba(41,182,246,0.9);border:1px solid rgba(41,182,246,0.2)'
    default:       return 'background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.4);border:1px solid rgba(255,255,255,0.08)'
  }
}

function isCurrentUser(member: OrganizationMember): boolean {
  const uid = orgStore.currentUserId
  if (!uid) return false
  return member.developer_id === parseInt(String(uid))
}

function canManageMember(member: OrganizationMember): boolean {
  if (member.role === 'owner') return false
  if (isCurrentUser(member)) return false
  return orgStore.canManageOrganization
}

// ── §ORGSPEND — the Procurement column: HOW MUCH each member may draw per transaction ──
// Caps live in org settings (procurement_limit_default + procurement_limits overrides)
// and bind every dev-driven treasury draw at the ONE resolver choke point. 0/unset =
// unlimited at both levels; an override of 0 explicitly exempts a member from the default.
const orgSettings = computed<Record<string, any>>(() => (org.value as any)?.settings || {})
const canEditProcurement = computed(() => myRole.value === 'owner' || myRole.value === 'admin')

function memberProcurementCap(member: OrganizationMember): { text: string; overridden: boolean; unlimited: boolean } {
  const s = orgSettings.value
  const overrides = (s.procurement_limits && typeof s.procurement_limits === 'object') ? s.procurement_limits : {}
  const key = String(member.developer_id)
  if (key in overrides) {
    const v = Number(overrides[key])
    const unlimited = !v || Number.isNaN(v) || v <= 0
    return { text: unlimited ? 'Unlimited' : String(overrides[key]), overridden: true, unlimited }
  }
  const d = Number(s.procurement_limit_default)
  const unlimited = !d || Number.isNaN(d) || d <= 0
  return { text: unlimited ? 'Unlimited' : String(s.procurement_limit_default), overridden: false, unlimited }
}

/** The viewer's OWN cap ('' = unlimited) — the work-order form shows what will bind. */
const myProcurementCapText = computed<string>(() => {
  const s = orgSettings.value
  const myId = String(orgStore.currentUserId ?? '')
  const overrides = (s.procurement_limits && typeof s.procurement_limits === 'object') ? s.procurement_limits : {}
  const raw = myId && myId in overrides ? overrides[myId] : s.procurement_limit_default
  const v = Number(raw)
  return v > 0 && !Number.isNaN(v) ? String(raw) : ''
})

const editingCapMember = ref<OrganizationMember | null>(null)
const capDraft = ref<string | number>('')
const capSaving = ref(false)
const capError = ref('')

function openCapEditor(member: OrganizationMember) {
  const overrides = orgSettings.value.procurement_limits || {}
  const cur = overrides[String(member.developer_id)]
  capDraft.value = cur !== undefined && cur !== null ? String(cur) : ''
  capError.value = ''
  editingCapMember.value = member
}

async function saveCap() {
  const member = editingCapMember.value
  if (!member || !org.value || capSaving.value) return
  capSaving.value = true
  capError.value = ''
  try {
    // The PUT replaces the whole map (top-level merge), so send the full merged map.
    // An empty draft REMOVES the override — the member falls back to the default.
    const overrides: Record<string, any> = { ...(orgSettings.value.procurement_limits || {}) }
    const key = String(member.developer_id)
    // the cap's field is type=number, so v-model hands back a number once typed in (§FESUITE 135, 2026-10-15: every
    // save failed with "capDraft.value.trim is not a function" and nothing reached the registry)
    const v = String(capDraft.value ?? '').trim()
    if (v === '') delete overrides[key]
    else overrides[key] = v
    const res = await organizationService.updateOrgSettings(org.value.id, { procurement_limits: overrides } as any)
    if (res?.settings) (org.value as any).settings = res.settings
    editingCapMember.value = null
  } catch (e: any) {
    capError.value = e?.detail || e?.message || 'Failed to save procurement limit'
  } finally {
    capSaving.value = false
  }
}

function toggleTeamPerms(teamId: string) {
  if (expandedTeamPerms.value.has(teamId)) {
    expandedTeamPerms.value.delete(teamId)
  } else {
    expandedTeamPerms.value.add(teamId)
  }
  expandedTeamPerms.value = new Set(expandedTeamPerms.value)
}

function isDefaultTeam(team: Team): boolean {
  return team.name.toLowerCase() === 'default team'
}

function formatDate(d: string): string {
  return new Date(d).toLocaleDateString(appLocale(), { year: 'numeric', month: 'short', day: 'numeric' })
}

function formatBalance(n: number | string | null | undefined): string {
  // Backend returns balances as Decimal strings (e.g. "10000.000000"); coerce safely.
  const num = typeof n === 'number' ? n : parseFloat(String(n ?? 0))
  if (!isFinite(num) || isNaN(num)) return '0'
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(2) + 'M'
  if (num >= 1_000)     return (num / 1_000).toFixed(1) + 'k'
  return num.toFixed(0)
}

function agentRepTier(score: number): string {
  if (score >= 51)  return 'SOVEREIGN'
  if (score >= 10)  return 'PLATINUM'
  if (score >= 7)   return 'GOLD'
  if (score >= 4)   return 'SILVER'
  if (score >= 1)   return 'BRONZE'
  return 'UNRANKED'
}

function agentRepClass(score: number): string {
  if (score >= 51)  return 'rep--sovereign'
  if (score >= 10)  return 'rep--platinum'
  if (score >= 7)   return 'rep--gold'
  if (score >= 4)   return 'rep--silver'
  if (score >= 1)   return 'rep--bronze'
  return 'rep--unranked'
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────
// GÖDEL FORGE: show the Evolution-Tree jump only where the arena is live (403/dark → hidden).
const forgeEnabled = ref(false)
import('@/services/api/forge').then(async (m) => {
  try { forgeEnabled.value = !!(await m.getForgeStatus())?.enabled } catch { forgeEnabled.value = false }
})

onMounted(async () => {
  if (!authStore.user && authStore.token) {
    await authStore.initializeAuth()
  }
  try {
    await orgStore.fetchOrganizations()
    if (orgStore.currentOrganization) {
      selectedOrgId.value = orgStore.currentOrganization.id
    } else if (orgStore.organizations.length > 0) {
      selectedOrgId.value = orgStore.organizations[0].id
      await orgStore.selectOrganization(selectedOrgId.value)
    }
  } catch (e) {
    console.error('Failed to load organizations:', e)
  }
  // Ensure agents are loaded (they usually are from auth, but be safe).
  // Server-default 200 is more than enough for the org-dashboard scope
  // (typical orgs have a handful of assignable agents).
  if (!agentStore.agents.length) {
    agentStore.fetchMyAgents().catch(() => {})
  }
  // Fetch org-assigned agents
  if (selectedOrgId.value) fetchOrgAgents()
})

// Sync settings form when org changes
watch(org, (val) => {
  if (val) {
    settingsForm.value = {
      name: val.name || '',
      description: val.description || '',
      website: val.website || ''
    }
  }
}, { immediate: true })

// ── Actions ───────────────────────────────────────────────────────────────────
async function handleOrgSwitch() {
  if (!selectedOrgId.value) return
  try {
    await orgStore.selectOrganization(selectedOrgId.value)
    fetchOrgAgents()
    activeTab.value = 'teams'
  } catch (e: any) {
    uiStore.showError('Switch Failed', e?.message || 'Could not load organization')
  }
}

function onOrgCreated(newOrg: Organization) {
  showCreateOrgModal.value = false
  selectedOrgId.value = newOrg.id
}

async function saveSettings() {
  isSavingSettings.value = true
  try {
    await orgStore.updateOrganization({
      // §FESUITE 135 (2026-10-15): an emptied description or website went as undefined, so it could never be cleared
      name:        settingsForm.value.name        || undefined,
      description: settingsForm.value.description.trim(),
      website:     settingsForm.value.website.trim()
    })
  } catch (e: any) {
    uiStore.showError('Save Failed', e?.message || 'Could not save organization settings')
  } finally {
    isSavingSettings.value = false
  }
}

// OD1+OD2+OD3 (audit 2026-05-07): replaced 2 confirm() + 1 prompt() with
// themed ConfirmActionModal. Delete-org uses the new requiredMatch prop —
// preserves the typed-name protection but inline + visually consistent.
const showDeleteTeamModal = ref(false)
const teamToDelete = ref<Team | null>(null)
const deleteTeamBusy = ref(false)

const showRemoveMemberModal = ref(false)
const memberToRemove = ref<OrganizationMember | null>(null)
const removeMemberBusy = ref(false)

const showDeleteOrgModal = ref(false)
const deleteOrgBusy = ref(false)

function deleteTeam(team: Team) {
  if (isDefaultTeam(team)) {
    uiStore.showError('Cannot Delete Default Team', 'The default team contains all organization members and cannot be deleted.')
    return
  }
  teamToDelete.value = team
  showDeleteTeamModal.value = true
}
async function confirmDeleteTeam() {
  if (!teamToDelete.value) return
  deleteTeamBusy.value = true
  try {
    await orgStore.deleteTeam(teamToDelete.value.id)
    showDeleteTeamModal.value = false
    teamToDelete.value = null
  } catch (e: any) {
    uiStore.showError('Failed to Delete Team', e.message)
  } finally {
    deleteTeamBusy.value = false
  }
}

function removeMember(member: OrganizationMember) {
  memberToRemove.value = member
  showRemoveMemberModal.value = true
}
async function confirmRemoveMember() {
  if (!memberToRemove.value) return
  removeMemberBusy.value = true
  try {
    // Backend DELETE /{org}/members/{developer_id} takes the DEVELOPER id (int),
    // not the membership-row UUID — passing .id 422s at pydantic.
    await orgStore.removeMember(memberToRemove.value.developer_id)
    showRemoveMemberModal.value = false
    memberToRemove.value = null
  } catch (e: any) {
    uiStore.showError('Remove Failed', e?.message || 'Could not remove member')
  } finally {
    removeMemberBusy.value = false
  }
}

function confirmDeleteOrg() {
  if (!org.value) return
  showDeleteOrgModal.value = true
}

// ── E1b — the corporate-death sequence. A delete refused with 409 carries a
// blockers checklist ({kind, action, ...}); render it in the danger zone and,
// for a funded treasury, offer the sweep rail inline (owner picks one of THEIR
// OWN agents as destination; the server refuses anything else).
const deleteBlockers = ref<any[]>([])
const sweepDest = ref('')
const sweepBusy = ref(false)
const myAgentOptions = ref<{ did: string; name: string }[]>([])
const hasTreasuryBlocker = computed(() =>
  deleteBlockers.value.some(b => b?.kind === 'funded_treasury'))

async function loadMyAgentOptions() {
  if (myAgentOptions.value.length) return
  try {
    const { agentApi } = await import('@/services/api/agents')
    const res: any = await agentApi.getMyAgents({ limit: 100, topLevelOnly: true })
    const list = Array.isArray(res) ? res : (res?.items || res?.agents || [])
    myAgentOptions.value = list
      .filter((a: any) => String(a?.status || 'active').toLowerCase() === 'active')
      .map((a: any) => ({ did: a.did, name: a.name || a.card_data?.name || a.did }))
  } catch { /* datalist is a convenience; the input still works bare */ }
}

async function doSweepTreasury() {
  if (!org.value || !sweepDest.value.trim() || sweepBusy.value) return
  sweepBusy.value = true
  try {
    const res = await organizationService.sweepOrgTreasury(
      org.value.id, sweepDest.value.trim(), crypto.randomUUID())
    uiStore.showSuccess(
      t('organizationDashboardView.danger.sweptTitle', 'Treasury swept'),
      t('organizationDashboardView.danger.sweptBody', 'Moved {amount} to your agent. You can delete the organization now.')
        .replace('{amount}', String(res?.amount ?? '')))
    deleteBlockers.value = deleteBlockers.value.filter(b => b?.kind !== 'funded_treasury')
    sweepDest.value = ''
  } catch (e: any) {
    uiStore.showError(
      t('organizationDashboardView.danger.sweepFailed', 'Sweep failed'),
      e?.response?.data?.detail || e?.message)
  } finally {
    sweepBusy.value = false
  }
}

async function executeDeleteOrg() {
  if (!org.value) return
  deleteOrgBusy.value = true
  try {
    await orgStore.deleteOrganization(org.value.id)
    deleteBlockers.value = []
    selectedOrgId.value = ''
    showDeleteOrgModal.value = false
  } catch (e: any) {
    const blockers = e?.detail?.blockers
    if (Array.isArray(blockers) && blockers.length) {
      // Deletion is money-guarded: show the checklist instead of a second toast
      // (the store already toasted the summary line).
      deleteBlockers.value = blockers
      showDeleteOrgModal.value = false
      if (blockers.some((b: any) => b?.kind === 'funded_treasury')) void loadMyAgentOptions()
    } else {
      uiStore.showError('Delete Failed', e?.message || 'Could not delete organization')
    }
  } finally {
    deleteOrgBusy.value = false
  }
}
</script>

<template>
  <div class="org-root">

    <!-- ── Command Bar — painted IMMEDIATELY, not gated on the org fetch (§TOURFIX
         2026-08-14). It carries the `org-hero` / `org-create-btn` anchors every
         guided-tour step falls back to, and on a loaded frame the org fetch takes
         seconds — a readable header over the spinner beats a blank page, and the
         tour can land its spotlight on first paint. Everything in it is safe while
         loading: the selector is disabled and the org list is simply empty. ── -->
    <div class="cmd-bar">
      <!-- §pass50.1 — removed "SOVEREIGN //" breadcrumb (was duplicate of
           DashboardHeader's frame indicator). Page title comes from the
           org name in the hero below. -->
      <div class="cmd-breadcrumb">
        <span class="cmd-glyph">⬡</span>
        <span class="cmd-title" data-tour="org-hero">Organizations <span class="cmd-title-amp">&amp;</span> Teams</span>
      </div>
      <div class="cmd-controls">
        <div class="org-selector-wrap">
          <select
            v-model="selectedOrgId"
            @change="handleOrgSwitch"
            :disabled="orgStore.isLoading"
            class="org-selector"
            :aria-label="t('organizationDashboardView.selectOrgAria', 'Choose an organization')"
          >
            <option value="" disabled>{{ t('organizationDashboardView.selectPlaceholder') }}</option>
            <option v-for="o in orgStore.organizations" :key="o.id" :value="o.id">
              {{ o.name }}
            </option>
          </select>
          <svg class="selector-arrow" viewBox="0 0 10 6" fill="none">
            <path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </div>
        <button class="cmd-btn cmd-btn--primary" @click="showCreateOrgModal = true" data-tour="org-create-btn">
          <svg viewBox="0 0 14 14" fill="none" class="btn-icon"><path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
          {{ t('organizationDashboardView.newOrgBtn') }}
        </button>
      </div>
    </div>

    <!-- ══ LOADING (content area only — the command bar above stays live) ═════ -->
    <div v-if="orgStore.isLoading && !org" class="org-loading">
      <div class="loading-spinner"></div>
      <p class="loading-label">{{ t('organizationDashboardView.loading') }}</p>
    </div>

    <!-- ══ MAIN LAYOUT ════════════════════════════════════════════════════════ -->
    <template v-else>

      <!-- ══ NO ORG STATE ═══════════════════════════════════════════════════ -->
      <ReadFailedNotice v-if="!org && orgStore.listFailed" :retry="retryOrgs" />
      <div v-else-if="!org && orgStore.listRead" class="no-org-state">
        <div class="no-org-hex">⬡</div>
        <div class="no-org-title">{{ t('organizationDashboardView.noOrg.title') }}</div>
        <p class="no-org-body">{{ t('organizationDashboardView.noOrg.body') }}</p>
        <button class="cmd-btn cmd-btn--primary" data-tour="org-create-btn" @click="showCreateOrgModal = true">
          <svg viewBox="0 0 14 14" fill="none" class="btn-icon"><path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
          {{ t('organizationDashboardView.createOrgBtn') }}
        </button>
      </div>

      <!-- neither answered nor failed yet (the store waits for the profile): still reading, no claim -->
      <div v-else-if="!org" class="org-loading">
        <div class="loading-spinner"></div>
        <p class="loading-label">{{ t('organizationDashboardView.loading') }}</p>
      </div>

      <!-- ══ ORG CONTENT ════════════════════════════════════════════════════ -->
      <div v-else class="org-content">

        <!-- ── Identity Panel ───────────────────────────────────────────── -->
        <div class="identity-panel">
          <div class="identity-main">
            <div class="identity-left">
              <div class="identity-name-row">
                <h1 class="identity-name">{{ org.name }}</h1>
                <span v-if="roleLabel" :class="['role-badge', roleBadgeClass(myRole || '')]">{{ roleLabel }}</span>
                <!-- §FESUITE (V0577): the role is read off the members; when they could not be read it is unknown, and
                     the owner/admin controls it gates are hidden for that reason, not because you hold none -->
                <span v-else-if="orgStore.membersFailed" class="role-badge" data-testid="org-role-unread"
                      :title="t('organizationDashboardView.roleUnreadHint', 'Your role here could not be read (the members read failed), so the owner and admin controls are hidden. Try again on the Members tab.')">
                  {{ t('organizationDashboardView.roleUnread', 'ROLE UNREAD') }}
                </span>
              </div>
              <div class="identity-slug">
                <span class="slug-prefix">@</span>{{ org.slug }}
              </div>
              <div v-if="orgTr && orgTr.verified_jobs > 0" class="identity-tr" data-testid="cd-org-tr">
                ✓ {{ tp('chatdesk.tr.line', '{n} verified jobs as this firm', { n: orgTr.verified_jobs }) }}<span v-if="orgTr.stars_avg != null" class="tr-star"> · {{ Number(orgTr.stars_avg).toFixed(1) }}★</span>
              </div>
              <p v-if="org.description" class="identity-desc">{{ org.description }}</p>
              <a v-if="safeExternalUrl(org.website)" :href="safeExternalUrl(org.website)" target="_blank" rel="noopener noreferrer" class="identity-website">
                <svg viewBox="0 0 14 14" fill="none" class="web-icon"><circle cx="7" cy="7" r="5.5" stroke="currentColor" stroke-width="1.2"/><path d="M7 1.5c-2 1.5-2 9 0 11M7 1.5c2 1.5 2 9 0 11M1.5 7h11" stroke="currentColor" stroke-width="1.1"/></svg>
                {{ org.website }}
              </a>
            </div>
            <div class="identity-actions" v-if="orgStore.canManageOrganization || forgeEnabled">
              <template v-if="orgStore.canManageOrganization">
                <button class="id-btn" @click="showEditOrgModal = true">{{ t('organizationDashboardView.identity.editBtn') }}</button>
                <button class="id-btn" @click="activeTab = 'settings'">{{ t('organizationDashboardView.identity.settingsBtn') }}</button>
              </template>
              <!-- GÖDEL FORGE (2026-07-19): a lineage IS an org — jump to its Evolution Tree
                   whenever the arena is live on this registry (hidden when dark, member or not). -->
              <button v-if="forgeEnabled" class="id-btn id-btn--forge"
                      @click="router.push({ path: '/forge', query: { org: org.id } })">
                <Icon name="mdi:source-branch" />
                {{ t('organizationDashboardView.identity.evolutionTreeBtn') }}
              </button>
            </div>
          </div>

          <!-- Capacity Meters -->
          <div class="capacity-row">
            <div class="capacity-item">
              <div class="cap-label">
                <span class="cap-name">{{ t('organizationDashboardView.capacity.members') }}</span>
                <span class="cap-count">{{ memberCount }} <span class="cap-limit">/ {{ orgMemberLimit }}</span></span>
              </div>
              <div class="cap-track">
                <div class="cap-fill cap-fill--members" :style="{ width: memberPct + '%' }"></div>
              </div>
            </div>
            <div class="capacity-item">
              <div class="cap-label">
                <span class="cap-name">{{ t('organizationDashboardView.capacity.teams') }}</span>
                <span class="cap-count">{{ teamCount }} <span class="cap-limit">/ {{ orgTeamLimit }}</span></span>
              </div>
              <div class="cap-track">
                <div class="cap-fill cap-fill--teams" :style="{ width: teamPct + '%' }"></div>
              </div>
            </div>
            <div class="capacity-item">
              <div class="cap-label">
                <span class="cap-name">{{ t('organizationDashboardView.capacity.myAgents') }}</span>
                <span class="cap-count">{{ myAgents.length }} <span class="cap-limit">/ {{ orgAgentLimit }}</span></span>
              </div>
              <div class="cap-track">
                <div class="cap-fill cap-fill--agents" :style="{ width: agentPct + '%' }"></div>
              </div>
            </div>
          </div>
        </div>

        <!-- E2 — Setup Guide: live checklist for a fresh org; each step deep-links
             to the tab holding the ONE implementation of that action. -->
        <!-- §FESUITE 135 (2026-10-15): keyed by the organization, like the tab panel below: a panel that read on mount
             kept the previous organization's answer after a switch (its tab stays mounted, v-show) -->
        <OrgSetupChecklist
          :key="org.id"
          :org-id="org.id"
          :can-manage="orgStore.canManageOrganization"
          @go="(tab: string) => { activeTab = tab as any }"
        />

        <!-- ── Tab Bar ──────────────────────────────────────────────────── -->
        <!-- §FESUITE 135 (2026-10-15): every panel below starts over for the organization picked. The tabs stay mounted
             (v-show), so a panel that read once on mount kept the previous organization's answer while its actions keyed
             on this one's id (OrgOwnershipCard offered A's admins as B's owners-to-be; OrgRoomCard's toggle set B's room
             from A's state), and a panel that reloads on its org-id had no check on an answer landing late. -->
        <div class="tab-panel" :key="org.id">
          <div class="tab-bar">
            <button
              v-for="tab in tabs"
              :key="tab.id"
              :data-tour="'org-tab-' + tab.id"
              :class="['tab-btn', { 'tab-btn--active': activeTab === tab.id }]"
              @click="activeTab = tab.id as any"
            >
              {{ tab.label }}
              <span v-if="tab.count !== undefined" :class="['tab-count', { 'tab-count--active': activeTab === tab.id }]">{{ tab.count }}</span>
            </button>
          </div>

          <!-- ══ ACTIVITY TAB (E3 — org money/denial roll-up) ════════════ -->
          <div v-show="activeTab === 'activity'" class="tab-body">
            <OrgActivityRollup :org-id="org.id" :active="activeTab === 'activity'" />
          </div>

          <!-- ══ TEAMS TAB ═══════════════════════════════════════════════ -->
          <div v-show="activeTab === 'teams'" class="tab-body">
            <div class="tab-header">
              <h2 class="tab-title">{{ t('organizationDashboardView.tabs.teams') }}</h2>
              <button
                v-if="orgStore.canManageTeams"
                class="cmd-btn cmd-btn--primary cmd-btn--sm"
                @click="showCreateTeamModal = true"
              >
                <svg viewBox="0 0 14 14" fill="none" class="btn-icon"><path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
                {{ t('organizationDashboardView.teams.createBtn') }}
              </button>
            </div>

            <!-- §ORGLIFE T2 — one honest line for the tab, rather than a caveat on
                 every card. The chips below are labels; nothing reads them. -->
            <p class="teams-note" data-testid="ot-teams-note">
              {{ t('organizationDashboardView.teams.labelsNote', 'Teams group people. The tags below are labels — access is governed by each member\'s organization role.') }}
            </p>

            <!-- Loading skeleton -->
            <div v-if="orgStore.isLoadingTeams" class="skel-rows">
              <div v-for="i in 3" :key="i" class="skel-card"></div>
            </div>

            <ReadFailedNotice v-else-if="orgStore.teamsFailed" :retry="retryTeams" data-testid="org-teams-failed" />
            <!-- Empty -->
            <div v-else-if="orgStore.teams.length === 0" class="empty-state">
              <div class="empty-icon">⬡</div>
              <p class="empty-title">{{ t('organizationDashboardView.teams.emptyTitle') }}</p>
              <p class="empty-body">{{ t('organizationDashboardView.teams.emptyBody') }}</p>
            </div>

            <!-- Teams Grid -->
            <div v-else class="teams-grid">
              <div
                v-for="team in orgStore.teams"
                :key="team.id"
                class="team-card"
              >
                <!-- Card Header -->
                <div class="team-card-head">
                  <div class="team-name-row">
                    <span :class="['team-dot', isDefaultTeam(team) ? 'team-dot--default' : 'team-dot--static']"></span>
                    <span class="team-name">{{ team.name }}</span>
                  </div>
                  <span class="team-members-count">{{ team.member_count ?? 0 }} {{ t('organizationDashboardView.teams.membersCount') }}</span>
                </div>

                <!-- Description -->
                <p class="team-desc">{{ team.description || t('organizationDashboardView.teams.noDescription') }}</p>

                <!-- Created -->
                <div class="team-meta">{{ t('organizationDashboardView.teams.created') }} {{ formatDate(team.created_at) }}</div>

                <!-- §ORGLIFE T4 — who is in this team, on the card. The count was
                     already served; the names were behind a modal. -->
                <div v-if="team.member_names && team.member_names.length" class="team-roster" data-testid="ot-roster">
                  <span v-for="n in team.member_names.slice(0, 3)" :key="n" class="roster-name">{{ n }}</span>
                  <span v-if="(team.member_count || 0) > 3" class="roster-more"
                    >{{ tp('organizationDashboardView.teams.rosterMore', '+{n} more', { n: (team.member_count || 0) - 3 }) }}</span>
                </div>

                <!-- §ORGLIFE T2 — LABELS, not permissions. Nothing in the backend reads
                     Team.permissions; measured at runtime, not inferred. -->
                <div v-if="team.permissions && team.permissions.length > 0" class="team-perms">
                  <template v-if="expandedTeamPerms.has(team.id)">
                    <span
                      v-for="perm in team.permissions"
                      :key="perm"
                      :class="['perm-chip', permChipClass(perm)]"
                    >{{ perm }}</span>
                    <button class="perm-expand-btn" @click="toggleTeamPerms(team.id)">{{ t('organizationDashboardView.teams.collapse') }}</button>
                  </template>
                  <template v-else>
                    <span
                      v-for="perm in team.permissions.slice(0, 4)"
                      :key="perm"
                      :class="['perm-chip', permChipClass(perm)]"
                    >{{ perm }}</span>
                    <button
                      v-if="team.permissions.length > 4"
                      class="perm-expand-btn"
                      @click="toggleTeamPerms(team.id)"
                    >{{ t('organizationDashboardView.teams.more', { count: team.permissions.length - 4 }) }}</button>
                  </template>
                </div>
                <div v-else class="team-perms">
                  <span class="perm-chip perm--default">{{ t('organizationDashboardView.teams.noLabels', 'no labels') }}</span>
                </div>

                <!-- Actions -->
                <div v-if="orgStore.canManageTeams" class="team-actions">
                  <button class="team-action-btn team-action-btn--edit" @click="editingTeam = team">{{ t('organizationDashboardView.teams.editBtn') }}</button>
                  <button class="team-action-btn team-action-btn--members" @click="viewingTeam = team">{{ t('organizationDashboardView.teams.membersBtn') }}</button>
                  <button
                    class="team-action-btn team-action-btn--delete"
                    @click="deleteTeam(team)"
                    :disabled="isDefaultTeam(team)"
                    :title="isDefaultTeam(team) ? 'Cannot delete default team' : ''"
                    :style="isDefaultTeam(team) ? 'opacity:0.3;cursor:not-allowed' : ''"
                  >{{ t('organizationDashboardView.teams.deleteBtn') }}</button>
                </div>
              </div>
            </div>
          </div>

          <!-- ══ MEMBERS TAB ═════════════════════════════════════════════ -->
          <div v-show="activeTab === 'members'" class="tab-body">
            <div class="tab-header">
              <h2 class="tab-title">{{ t('organizationDashboardView.tabs.members') }}</h2>
              <button
                v-if="orgStore.canInviteMembers"
                class="cmd-btn cmd-btn--primary cmd-btn--sm"
                @click="showInviteMemberModal = true"
              >
                <svg viewBox="0 0 14 14" fill="none" class="btn-icon"><path d="M7 1v12M1 7h12" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
                {{ t('organizationDashboardView.members.inviteBtn') }}
              </button>
            </div>

            <!-- §ORGINVITE — who has been invited and has not answered. This
                 tab showed two live invitations as nothing at all, because an
                 invitation is not a membership and the table below reads
                 `organization_members`. Same component as the Pocket org
                 surface; `@changed` refreshes the members list because an
                 invitation resolving is exactly what changes it. -->
            <OrgPendingInvitations
              :org-id="org.id"
              :my-role="orgStore.currentUserRole"
              :show-history="true"
              @changed="orgStore.fetchMembers(org.id)"
            />

            <!-- Loading skeleton -->
            <div v-if="orgStore.isLoadingMembers" class="skel-rows">
              <div v-for="i in 4" :key="i" class="skel-row"></div>
            </div>

            <ReadFailedNotice v-else-if="orgStore.membersFailed" :retry="retryMembers" data-testid="org-members-failed" />
            <!-- Empty -->
            <div v-else-if="orgStore.members.length === 0" class="empty-state">
              <div class="empty-icon">◎</div>
              <p class="empty-title">{{ t('organizationDashboardView.members.emptyTitle') }}</p>
              <p class="empty-body">{{ t('organizationDashboardView.members.emptyBody') }}</p>
            </div>

            <!-- Members Table -->
            <div v-else class="members-table-wrap">
              <table class="members-table">
                <thead>
                  <tr>
                    <th class="th-member">{{ t('organizationDashboardView.members.thMember') }}</th>
                    <th class="th-role">{{ t('organizationDashboardView.members.thRole') }}</th>
                    <th class="th-procurement">{{ t('organizationDashboardView.members.thProcurement', 'Procurement') }}</th>
                    <th class="th-joined">{{ t('organizationDashboardView.members.thJoined') }}</th>
                    <th class="th-actions"></th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="member in orgStore.members"
                    :key="member.id"
                    :class="['member-row', 'member-row--clickable', { 'member-row--self': isCurrentUser(member), 'member-row--owner': member.role === 'owner' }]"
                    :title="`Open member detail for ${member.developer_name}`"
                    @click="openMemberDetail(member)"
                  >
                    <td class="td-member">
                      <div class="member-identity">
                        <div class="member-avatar" :style="avatarStyle(member.role)">
                          {{ member.developer_name.charAt(0).toUpperCase() }}
                        </div>
                        <div class="member-info">
                          <div class="member-name">
                            {{ member.developer_name }}
                            <span v-if="isCurrentUser(member)" class="you-badge">{{ t('organizationDashboardView.members.you') }}</span>
                          </div>
                          <div class="member-email">{{ member.developer_email }}</div>
                        </div>
                      </div>
                    </td>
                    <td class="td-role">
                      <span :class="['role-badge', roleBadgeClass(member.role)]">{{ member.role.toUpperCase() }}</span>
                    </td>
                    <!-- §ORGSPEND — per-transaction treasury-draw limit binding this member -->
                    <td class="td-procurement" data-testid="member-procurement" @click.stop>
                      <template v-if="editingCapMember?.id === member.id">
                        <span class="proc-editor">
                          <input
                            v-model="capDraft"
                            type="number"
                            min="0"
                            class="proc-input"
                            :placeholder="t('organizationDashboardView.members.procPlaceholder', 'default')"
                            :disabled="capSaving"
                            data-testid="proc-input"
                            @keyup.enter="saveCap"
                            @keyup.escape="editingCapMember = null"
                          />
                          <button class="member-action-btn" :disabled="capSaving" data-testid="proc-save" @click="saveCap">
                            {{ capSaving ? '…' : t('common.save', 'Save') }}
                          </button>
                          <button class="member-action-btn" :disabled="capSaving" @click="editingCapMember = null">
                            {{ t('common.cancel', 'Cancel') }}
                          </button>
                        </span>
                        <span v-if="capError" class="proc-error" role="alert">{{ capError }}</span>
                      </template>
                      <template v-else>
                        <span
                          :class="['proc-value', { 'proc-value--unlimited': memberProcurementCap(member).unlimited }]"
                          :title="memberProcurementCap(member).overridden
                            ? t('organizationDashboardView.members.procOverrideTip', 'Per-member override (0 = unlimited)')
                            : t('organizationDashboardView.members.procDefaultTip', 'Org default — set an override to change it for this member')"
                        >
                          {{ memberProcurementCap(member).text }}
                          <em v-if="memberProcurementCap(member).overridden" class="proc-flag">{{ t('organizationDashboardView.members.procOverride', 'override') }}</em>
                        </span>
                        <button
                          v-if="canEditProcurement"
                          class="member-action-btn proc-edit-btn"
                          data-testid="proc-edit"
                          @click="openCapEditor(member)"
                        >{{ t('common.edit', 'Edit') }}</button>
                      </template>
                    </td>
                    <td class="td-joined">{{ formatDate(member.joined_at) }}</td>
                    <td class="td-member-actions" @click.stop>
                      <template v-if="canManageMember(member)">
                        <button class="member-action-btn" @click="changingRoleMember = member">{{ t('organizationDashboardView.members.changeRoleBtn') }}</button>
                        <button class="member-action-btn member-action-btn--danger" @click="removeMember(member)">{{ t('organizationDashboardView.members.removeBtn') }}</button>
                      </template>
                      <span v-else-if="member.role === 'owner'" class="owner-lock" title="Owner cannot be managed">
                        <svg viewBox="0 0 12 12" fill="none" width="12" height="12"><rect x="2" y="5" width="8" height="6" rx="1.5" stroke="currentColor" stroke-width="1.2"/><path d="M4 5V3.5a2 2 0 114 0V5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
                      </span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- ══ AGENTS TAB ══════════════════════════════════════════════ -->
          <div v-show="activeTab === 'agents'" class="tab-body">
            <div class="tab-header">
              <h2 class="tab-title">{{ t('organizationDashboardView.tabs.agents') }}</h2>
              <button class="cmd-btn cmd-btn--secondary cmd-btn--sm" @click="router.push({ name: 'my-agents' })">
                {{ t('organizationDashboardView.agents.fleetBtn') }}
              </button>
            </div>

            <!-- Assigned Agents -->
            <div v-if="orgAgentsLoading" class="skel-rows">
              <div v-for="i in 3" :key="i" class="skel-card"></div>
            </div>

            <ReadFailedNotice v-else-if="orgAgentsFailed" :retry="fetchOrgAgents" style="margin-bottom:20px;" />

            <div v-else-if="orgAgents.length === 0" class="empty-state" style="margin-bottom:20px;">
              <div class="empty-icon">◈</div>
              <p class="empty-title">{{ t('organizationDashboardView.agents.emptyTitle') }}</p>
              <p class="empty-body">{{ t('organizationDashboardView.agents.emptyBody') }}</p>
            </div>

            <div v-else class="agents-grid" style="margin-bottom:20px;">
              <div
                v-for="agent in orgAgents"
                :key="agent.did"
                data-testid="org-agent"
                :data-did="agent.did"
                class="agent-card agent-card--clickable"
                :title="`Open CI/CD view for ${agent.name || agent.did}`"
                @click="openAgentCicd(agent.did)"
              >
                <div class="agent-card-head">
                  <div class="agent-status-row">
                    <span :class="['agent-dot', agent.status === 'active' ? 'agent-dot--active' : 'agent-dot--inactive']"></span>
                    <span class="agent-name">{{ agent.name || agent.did?.slice(0, 20) }}</span>
                  </div>
                  <button v-if="myRole === 'owner' || myRole === 'admin'"
                    class="cmd-btn cmd-btn--danger cmd-btn--xs"
                    :aria-label="tp('organizationDashboardView.agents.removeAria', 'Remove {name} from the organization', { name: agent.name || agent.did })"
                    @click.stop="unassignAgent(agent.did)"
                    :title="tp('organizationDashboardView.agents.removeAria', 'Remove {name} from the organization', { name: agent.name || agent.did })"><span aria-hidden="true">✕</span></button>
                </div>
                <div class="agent-did">{{ (agent.did || '').slice(0, 36) }}…</div>
                <div v-if="agent.team_id" style="font-size:9px;color:rgba(var(--nc-primary-rgb),0.4);margin-top:4px;">Team: {{ agent.team_id.slice(0, 12) }}…</div>
                <!-- §ORGLIFE L2 — an assignment outlives its creator leaving, on purpose.
                     That is only honest if the screen says so, with the authority state
                     beside it: revoked is a closed door, none is a door never opened. -->
                <div v-if="agent.creator_is_member === false" class="ag-orphan" data-testid="ol-orphan">
                  <span class="ag-orphan-mark">⚠</span>
                  <span>{{ t('organizationDashboardView.agents.creatorLeft', 'Creator is no longer a member') }}</span>
                </div>
                <div v-if="agent.org_authority && agent.org_authority !== 'none'"
                     :class="['ag-auth', `ag-auth--${agent.org_authority}`]" data-testid="ol-authority">
                  {{ agent.org_authority === 'live'
                      ? t('organizationDashboardView.agents.authorityLive', 'Holds this org\'s authority')
                      : t('organizationDashboardView.agents.authorityRevoked', 'Org authority revoked') }}
                </div>
                <div class="agent-card-cta">Open CI/CD &rsaquo;</div>
              </div>
            </div>

            <!-- Assign agents section -->
            <div v-if="assignableAgents.length > 0 && (myRole === 'owner' || myRole === 'admin')" style="margin-top:10px;">
              <div class="tab-header" style="margin-bottom:8px;">
                <h2 class="tab-title" style="font-size:10px;">{{ t('organizationDashboardView.tabs.assignAgents') }}</h2>
              </div>
              <div class="agents-grid">
                <div v-for="agent in assignableAgents" :key="agent.did || agent.agent_did" class="agent-card" style="opacity:0.7;" data-testid="org-assignable" :data-did="agent.did || agent.agent_did">
                  <div class="agent-card-head">
                    <div class="agent-status-row">
                      <span class="agent-dot agent-dot--inactive"></span>
                      <span class="agent-name">{{ agent.name || 'Agent' }}</span>
                    </div>
                    <button class="cmd-btn cmd-btn--primary cmd-btn--xs" @click="assignAgent(agent.did || agent.agent_did)">{{ t('organizationDashboardView.agents.assignBtn') }}</button>
                  </div>
                  <div class="agent-did">{{ (agent.did || agent.agent_did || '').slice(0, 36) }}…</div>
                  <div class="agent-financials">
                    <div class="agent-fin-item">
                      <span class="fin-label">{{ t('organizationDashboardView.agents.liquid') }}</span>
                      <span class="fin-value fin-value--liquid">◎ {{ formatBalance(agent.liquid_balance || 0) }}</span>
                    </div>
                    <div class="agent-fin-item">
                      <span class="fin-label">{{ t('organizationDashboardView.agents.staked') }}</span>
                      <span class="fin-value fin-value--staked">◉ {{ formatBalance(agent.staked_balance || 0) }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- ══ Track A2: AGENT AUTHORITY TAB (IRONKEY org grants) ══════════ -->
          <div v-show="activeTab === 'authority'" class="tab-body">
            <div class="tab-header">
              <h2 class="tab-title">{{ t('organizationDashboardView.tabs.authority', 'Agent Authority') }}</h2>
            </div>
            <AgentAuthorityPanel
              v-if="selectedOrgId && org"
              :key="selectedOrgId"
              :org-id="selectedOrgId"
              :org-slug="org.slug || ''"
              :agents="orgAgents"
              :can-edit="myRole === 'owner' || myRole === 'admin'"
            />

            <!-- ══ B3 oversight: org agents' spend approvals (read-only) ═════ -->
            <div class="oap-block" data-tour="org-approvals">
              <div class="oap-head">
                <div>
                  <h3 class="oap-title">{{ t('organizationDashboardView.approvals.title', 'Spend approvals') }}</h3>
                  <p class="oap-sub">
                    {{ t('organizationDashboardView.approvals.sub',
                         'Over-threshold spends by this org\'s agents park here for a human decision. This view is oversight only: each ask is decided by the agent\'s owning developer in Settings → Approvals, because the owner is the liable party.') }}
                  </p>
                </div>
                <button class="cmd-btn cmd-btn--secondary cmd-btn--sm" :disabled="orgApprovalsLoading" @click="loadOrgApprovals">
                  {{ orgApprovalsLoading ? t('organizationDashboardView.approvals.loading', 'Loading…') : t('organizationDashboardView.approvals.refreshBtn', 'Refresh') }}
                </button>
              </div>
              <div v-if="orgApprovalsError" class="oap-empty oap-empty--err">{{ orgApprovalsError }}</div>
              <div v-else-if="orgApprovalsLoading && !orgApprovals.length" class="oap-empty">
                {{ t('organizationDashboardView.approvals.loading', 'Loading…') }}
              </div>
              <div v-else-if="!orgApprovals.length" class="oap-empty">
                {{ t('organizationDashboardView.approvals.empty', 'No spend approvals yet: none of this org\'s agents has asked to spend over its threshold.') }}
              </div>
              <div v-else class="oap-rows">
                <div v-for="r in orgApprovals" :key="r.id" class="oap-row">
                  <span :class="['oap-status', `oap-status--${r.status}`]">{{ r.status }}</span>
                  <span class="oap-amount">{{ approvalAmt(r.amount) }}<span v-if="r.currency" class="oap-cur">&nbsp;{{ r.currency }}</span></span>
                  <span class="oap-agent" :title="r.agent_did">{{ r.agent_name || r.agent_did }}</span>
                  <span v-if="r.counterparty_did" class="oap-cpty" :title="r.counterparty_did">
                    → {{ r.counterparty_did.slice(0, 28) }}…</span>
                  <span class="oap-when">{{ t('organizationDashboardView.approvals.asked', 'asked') }} {{ approvalWhen(r.created_at) }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- ══ Track A6: ORG AUDIT TAB (own EventStore trail) ══════════════ -->
          <div v-show="activeTab === 'audit'" class="tab-body">
            <div class="tab-header">
              <h2 class="tab-title">{{ t('organizationDashboardView.tabs.audit', 'Audit Trail') }}</h2>
              <button class="cmd-btn cmd-btn--secondary cmd-btn--sm" :disabled="auditLoading" @click="loadOrgAudit">
                {{ auditLoading ? t('organizationDashboardView.audit.loading', 'Loading…') : t('organizationDashboardView.audit.refreshBtn', 'Refresh') }}
              </button>
            </div>
            <div v-if="auditError" class="empty-state">
              <div class="empty-icon">⚠</div>
              <p class="empty-title">{{ t('organizationDashboardView.audit.errTitle', 'Audit backend unreachable') }}</p>
              <p class="empty-body">{{ auditError }}</p>
            </div>
            <div v-else-if="auditLoading && !auditEvents.length" class="skel-rows">
              <div v-for="i in 4" :key="i" class="skel-card"></div>
            </div>
            <div v-else-if="!auditEvents.length" class="empty-state">
              <div class="empty-icon">◈</div>
              <p class="empty-title">{{ t('organizationDashboardView.audit.emptyTitle', 'No lifecycle events yet') }}</p>
              <p class="empty-body">{{ t('organizationDashboardView.audit.emptyBody', 'Invites, joins, removals, role changes and authority grants land here as they happen.') }}</p>
            </div>
            <div v-else class="audit-rows" data-tour="org-audit-rows">
              <div v-for="(ev, i) in auditEvents" :key="i" class="audit-row">
                <span class="audit-type">{{ ev.event_type }}</span>
                <span class="audit-when">{{ ev.timestamp ? new Date(ev.timestamp).toLocaleString(appLocale()) : '—' }}</span>
                <span class="audit-data">{{ auditSummary(ev) }}</span>
              </div>
            </div>
          </div>

          <!-- ══ §pass49 F3: CI/CD TAB ═══════════════════════════════════════ -->
          <div v-show="activeTab === 'cicd'" class="tab-body">
            <div v-if="cicdLoading" class="empty-state">
              <p class="empty-title">Loading…</p>
            </div>
            <div v-else-if="!cicdSummary || cicdSummary.agent_count === 0" class="empty-state">
              <div class="empty-icon">
                <svg viewBox="0 0 24 24" fill="none" width="32" height="32"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.5"/></svg>
              </div>
              <p class="empty-title">No agents in this org yet</p>
              <p class="empty-body">Assign agents in the AGENTS tab to see their CI/CD activity here.</p>
            </div>
            <template v-else>
              <!-- Stat tiles -->
              <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;margin-bottom:14px;">
                <div class="cmd-card" style="padding:14px;">
                  <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--cmd-text-muted,#758296);">Agents</div>
                  <div style="font-size:24px;font-weight:700;margin-top:4px;">{{ cicdSummary.agent_count }}</div>
                </div>
                <div class="cmd-card" style="padding:14px;">
                  <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--cmd-text-muted,#758296);">Pipelines</div>
                  <div style="font-size:24px;font-weight:700;margin-top:4px;">{{ cicdSummary.pipelines?.total ?? 0 }}</div>
                  <div style="font-size:10px;color:var(--cmd-text-muted,#758296);margin-top:4px;" v-if="cicdSummary.pipelines?.last_created_at">last: {{ new Date(cicdSummary.pipelines.last_created_at).toLocaleString(appLocale()) }}</div>
                </div>
                <div class="cmd-card" style="padding:14px;">
                  <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--cmd-text-muted,#758296);">Deployments (24h)</div>
                  <div style="font-size:24px;font-weight:700;margin-top:4px;">{{ cicdSummary.deployments?.total ?? 0 }}</div>
                  <div style="font-size:10px;margin-top:4px;">
                    <span style="color:#5dffae;">{{ cicdSummary.deployments?.success ?? 0 }} ok</span> ·
                    <span style="color:#ff7676;">{{ cicdSummary.deployments?.failed ?? 0 }} fail</span> ·
                    <span style="color:#f0c64f;">{{ cicdSummary.deployments?.pending ?? 0 }} pending</span>
                  </div>
                </div>
                <div class="cmd-card" style="padding:14px;">
                  <div style="font-size:10px;text-transform:uppercase;letter-spacing:0.08em;color:var(--cmd-text-muted,#758296);">Active Versions</div>
                  <div style="font-size:24px;font-weight:700;margin-top:4px;">{{ cicdSummary.active_versions?.length ?? 0 }}</div>
                </div>
              </div>

              <!-- Top failing agents -->
              <div class="cmd-card" style="padding:14px;margin-bottom:14px;" v-if="cicdSummary.deployments?.top_failing_agents?.length">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--cmd-text-muted,#758296);font-weight:700;margin-bottom:8px;">Top failing agents (24h)</div>
                <div v-for="r in cicdSummary.deployments.top_failing_agents" :key="r.did" style="padding:6px 0;border-bottom:1px solid rgba(96,128,192,0.08);font-size:12px;display:flex;justify-content:space-between;">
                  <RouterLink :to="`/agent/${r.did}/ci-cd`" :title="r.did" style="color:#4fb6ff;font-family:monospace;">{{ r.did.length > 36 ? `${r.did.slice(0, 22)}…${r.did.slice(-10)}` : r.did }}</RouterLink>
                  <span style="color:#ff7676;">{{ r.fail_count }} fails</span>
                </div>
              </div>

              <!-- Active versions -->
              <div class="cmd-card" style="padding:14px;" v-if="cicdSummary.active_versions?.length">
                <div style="font-size:11px;text-transform:uppercase;letter-spacing:0.08em;color:var(--cmd-text-muted,#758296);font-weight:700;margin-bottom:8px;">Active versions</div>
                <div v-for="av in cicdSummary.active_versions" :key="av.did" style="padding:6px 0;border-bottom:1px solid rgba(96,128,192,0.08);font-size:12px;display:flex;justify-content:space-between;">
                  <RouterLink :to="`/agent/${av.did}/ci-cd`" :title="av.did" style="color:#4fb6ff;font-family:monospace;">{{ av.did.length > 36 ? `${av.did.slice(0, 22)}…${av.did.slice(-10)}` : av.did }}</RouterLink>
                  <span style="font-family:monospace;">{{ av.version }}</span>
                </div>
              </div>
            </template>
          </div>

          <!-- ══ SETTINGS TAB ════════════════════════════════════════════ -->
          <div v-show="activeTab === 'treasury'" class="tab-body">
            <div class="tab-header"><h2 class="tab-title">TREASURY</h2></div>

            <!-- ══ Track C3: THE ORGANIZATION'S OWN ACCOUNT ══════════════════════
                 Distinct from the AGORA listing purses below: this one exists whether or not
                 the org is listed, and it is keyless — no credential exists for it, so it can
                 only be moved by these rails. -->
            <section class="oa-sec" data-tour="org-treasury-account">
              <div class="oa-head">
                <h3 class="oa-title">Organization account</h3>
                <span v-if="orgAccount?.source === 'org'" class="oa-badge oa-badge--own">own account</span>
                <span v-else-if="orgAccount?.source === 'agora_listing'" class="oa-badge oa-badge--agora">AGORA listing purse</span>
                <!-- §FESUITE (V0577): "none" only once the account read answered -->
                <span v-else-if="orgAccount" class="oa-badge oa-badge--none" data-testid="org-account-none">none</span>
              </div>

              <p v-if="orgAccountLoading" style="opacity:.6">Loading account…</p>
              <ReadFailedNotice v-else-if="orgAccountFailed" :retry="loadOrgAccount" data-testid="org-account-failed" />

              <template v-else>
                <!-- no account at all -->
                <div v-if="!orgAccount?.exists" class="oa-empty">
                  <p>This organization has no money account yet.</p>
                  <p class="oa-hint">
                    An org account is a <strong>keyless</strong> wallet: no credential is ever issued for it,
                    so nobody can spend from it outside the org rails below.
                  </p>
                  <button v-if="myRole === 'owner'" class="ta-btn ta-btn--go" :disabled="orgAccountBusy"
                          data-tour="org-treasury-create" @click="createOrgAccount()">
                    {{ orgAccountBusy ? 'Creating…' : 'Create treasury account' }}
                  </button>
                  <p v-else class="oa-hint">Only the organization owner can create it.</p>
                </div>

                <!-- account exists -->
                <div v-else class="oa-grid">
                  <div class="oa-card">
                    <div class="oa-k">Balance</div>
                    <div class="oa-v">{{ fmtAmt(orgAccount.balance) }}</div>
                    <div class="oa-sub" v-if="orgAccount.balance === null">balance unavailable (ledger unreachable)</div>
                  </div>
                  <div class="oa-card oa-card--did">
                    <div class="oa-k">Account</div>
                    <div class="oa-did">{{ orgAccount.treasury_agent_did }}</div>
                    <div class="oa-sub" v-if="orgAccount.source === 'agora_listing'">
                      This is your AGORA listing's purse. Create an org account to keep the two separate.
                    </div>
                  </div>
                </div>

                <!-- fund one of the org's agents -->
                <div v-if="orgAccount?.exists && orgAccount.source === 'org' && canManageTreasury"
                     class="oa-fund" data-tour="org-treasury-fund">
                  <div class="oa-k" style="margin-bottom:.4rem">Fund an organization agent</div>
                  <div class="oa-fund-row">
                    <select :aria-label="t('organizationDashboardView.fundAgentAria', 'Organization agent to fund')" v-model="fundAgentDid" class="ta-input" style="flex:2 1 320px">
                      <option value="">Select an organization agent…</option>
                      <option v-for="a in orgAgents" :key="a.did || a.agent_did" :value="a.did || a.agent_did">
                        {{ a.name || a.did || a.agent_did }}
                      </option>
                    </select>
                    <input v-model="fundAmount" class="ta-input" type="number" min="0" step="0.000001"
                           placeholder="Amount" style="flex:1 1 140px" />
                    <button class="ta-btn ta-btn--go" :disabled="orgAccountBusy || !fundAgentDid || !fundAmount"
                            @click="submitFund()">
                      {{ orgAccountBusy ? 'Sending…' : 'Send' }}
                    </button>
                  </div>
                  <p class="oa-hint">
                    Agents send funds back themselves — there is no pull from this screen, by design:
                    an agent's balance stays its own.
                  </p>
                </div>

                <p v-if="orgAccountMsg" class="oa-msg" :class="'oa-msg--' + orgAccountMsg.kind">{{ orgAccountMsg.text }}</p>

                <!-- movements, from the org's own audit trail -->
                <div v-if="canManageTreasury && orgMoneyEvents.length" class="oa-moves">
                  <div class="oa-k" style="margin-bottom:.35rem">Recent movements</div>
                  <div v-for="(e, i) in orgMoneyEvents" :key="i" class="oa-move">
                    <span class="oa-move-kind" :class="e.event_type === 'OrganizationTreasuryFunded' ? 'oa-out' : 'oa-in'">
                      {{ e.event_type === 'OrganizationTreasuryFunded' ? 'sent' : 'received' }}
                    </span>
                    <span class="oa-move-amt">{{ fmtAmt(e.data?.amount) }}</span>
                    <span class="oa-move-did">{{ (e.data?.agent_did || '').slice(0, 34) }}…</span>
                    <span class="oa-move-ts">{{ e.timestamp ? new Date(e.timestamp).toLocaleString(appLocale()) : '' }}</span>
                  </div>
                </div>
              </template>
            </section>

            <!-- §ORGCLIENT (H3.1) — the firm posts work; the bounty draws from the account above -->
            <OrgWorkOrders
              v-if="org && orgAccount?.source === 'org'"
              :org-id="org.id"
              :can-manage="canManageTreasury"
              :my-cap="myProcurementCapText"
            />

            <!-- §CHATPOLISH — §ORGCLIENT's whole surface used to disappear when
                 the org had no treasury account of its own, with nothing said.
                 The §HIRECOHERE law: name the reason, and name the act that
                 clears it. -->
            <p v-else-if="org && canManageTreasury" class="oa-k" data-testid="owo-no-account"
               style="margin:1rem 0 0; opacity:.7">
              {{ t('orgWork.needsAccount', 'Commissioning work needs the organization\'s own treasury account. Open it above and the firm can post work orders here.') }}
            </p>

            <!-- §FIRMBOOKS (O-F) — the merged statement, admin-only -->
            <OrgBooks v-if="org && canManageTreasury" :org-id="org.id" />

            <h3 class="oa-title" style="margin:1.4rem 0 .5rem">AGORA listings</h3>
            <p v-if="treasuryLoading" style="opacity:.6">Loading treasury…</p>
            <ReadFailedNotice v-else-if="treasuryFailed" :retry="loadTreasury" data-testid="org-treasury-failed" />
            <template v-else-if="treasury && treasury.listing_count > 0">
              <div class="tr-cards">
                <div v-for="s in [
                      {k:'Available',v:treasury.totals.balance,a:'liquid'},
                      {k:'Raised (launch)',v:treasury.totals.raised,a:'raised'},
                      {k:'Fees collected',v:treasury.totals.fees_earned,a:'fees'},
                      {k:'Distributions paid',v:treasury.totals.dividends_paid,a:'div'}]" :key="s.k"
                  class="tr-card" :class="'tr-card--'+s.a">
                  <div class="tr-card-k">{{ s.k }}</div>
                  <div class="tr-card-v">{{ fmtAmt(s.v) }} <span class="tr-card-ccy">{{ treasury.currency }}</span></div>
                </div>
              </div>
              <table class="org-tbl" style="width:100%;border-collapse:collapse;font-size:.9rem">
                <thead><tr style="text-align:left;opacity:.55;font-size:.7rem;text-transform:uppercase">
                  <th style="padding:.5rem">Listing</th><th style="padding:.5rem">Available</th><th style="padding:.5rem">Raised</th><th style="padding:.5rem">Fees</th><th style="padding:.5rem">Distributions</th><th style="padding:.5rem">Status</th>
                  <th v-if="canManageTreasury" style="padding:.5rem">Actions</th>
                </tr></thead>
                <tbody>
                  <template v-for="l in treasury.listings" :key="l.symbol">
                  <tr style="border-top:1px solid var(--border,#243044)">
                    <td style="padding:.55rem;font-weight:600">${{ l.symbol }}</td>
                    <td style="padding:.55rem">{{ l.balance === null ? '—' : fmtAmt(l.balance) }} {{ l.currency }}</td>
                    <td style="padding:.55rem">{{ fmtAmt(l.raised) }}</td>
                    <td style="padding:.55rem">{{ fmtAmt(l.fees_earned) }}</td>
                    <td style="padding:.55rem">{{ fmtAmt(l.dividends_paid) }}</td>
                    <td style="padding:.55rem;text-transform:uppercase;font-size:.7rem;opacity:.75">{{ l.status }}</td>
                    <td v-if="canManageTreasury" style="padding:.55rem;white-space:nowrap">
                      <button v-if="agoraDistOn" class="ta-btn" @click="openTreasuryAction(l.symbol, 'dividend')">Distribution</button>
                      <button class="ta-btn" @click="openTreasuryAction(l.symbol, 'buyback')">Treasury buy</button>
                      <button class="ta-btn" @click="openTreasuryAction(l.symbol, 'transfer')">Transfer</button>
                      <button class="ta-btn" @click="openTreasuryAction(l.symbol, 'sweep')">Sweep</button>
                      <button class="ta-btn" @click="openTreasuryAction(l.symbol, 'refloat')">Re-release</button>
                      <button class="ta-btn" @click="openTreasuryAction(l.symbol, 'sell')">Sell</button>
                      <button class="ta-btn" @click="openTreasuryAction(l.symbol, 'mm')">MM</button>
                      <button class="ta-btn" @click="openTreasuryAction(l.symbol, 'rebate')">Rebate</button>
                      <button class="ta-btn" @click="openTreasuryAction(l.symbol, 'mmseat')">MM Seat</button>
                      <button class="ta-btn" @click="openTreasuryAction(l.symbol, 'fees')">Fees</button>
                    </td>
                  </tr>
                  <!-- §V0113 Phase 2 — inline action form (org-admin only) -->
                  <tr v-if="canManageTreasury && treasuryActionRow === l.symbol && treasuryActionKind" :key="l.symbol + '-form'">
                    <td :colspan="7" style="padding:.65rem 1rem;background:var(--surface-2,#0d1622);border-top:1px solid var(--border,#243044)">
                      <div style="display:flex;flex-wrap:wrap;align-items:flex-end;gap:.75rem">
                        <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;opacity:.7;align-self:center;min-width:90px">
                          {{ treasuryActionLabel(treasuryActionKind) }} · ${{ l.symbol }}
                        </div>
                        <template v-if="treasuryActionKind === 'dividend'">
                          <label class="ta-fld"><span>Per point ({{ l.currency }})</span><input v-model="taPerShare" class="ta-input" type="text" inputmode="decimal" placeholder="0.10" /></label>
                        </template>
                        <template v-else-if="treasuryActionKind === 'buyback'">
                          <label class="ta-fld"><span>Qty</span><input v-model.number="taQty" class="ta-input" type="number" min="1" placeholder="100" /></label>
                          <label class="ta-fld"><span>Limit price ({{ l.currency }})</span><input v-model="taLimitPrice" class="ta-input" type="text" inputmode="decimal" placeholder="10.00" /></label>
                        </template>
                        <template v-else-if="treasuryActionKind === 'transfer'">
                          <label class="ta-fld" style="flex:2 1 260px"><span>Destination DID</span><input v-model="taDestDid" class="ta-input" type="text" placeholder="did:theprotocol:…" /></label>
                          <label class="ta-fld"><span>Amount ({{ l.currency }})</span><input v-model="taAmount" class="ta-input" type="text" inputmode="decimal" placeholder="100" /></label>
                          <label class="ta-fld"><span>Reserve floor (opt.)</span><input v-model="taReserveFloor" class="ta-input" type="text" inputmode="decimal" placeholder="0" /></label>
                        </template>
                        <template v-else-if="treasuryActionKind === 'sweep'">
                          <label class="ta-fld"><span>To symbol (same org)</span><input v-model="taDestDid" class="ta-input" type="text" placeholder="OTHER" /></label>
                          <label class="ta-fld"><span>Amount ({{ l.currency }})</span><input v-model="taAmount" class="ta-input" type="text" inputmode="decimal" placeholder="100" /></label>
                        </template>
                        <template v-else-if="treasuryActionKind === 'refloat'">
                          <label class="ta-fld"><span>Points to release</span><input v-model.number="taQty" class="ta-input" type="number" min="1" placeholder="50000" /></label>
                          <label class="ta-fld"><span>Offer price ({{ l.currency }}, opt.)</span><input v-model="taOfferPrice" class="ta-input" type="text" inputmode="decimal" placeholder="market" /></label>
                        </template>
                        <template v-else-if="treasuryActionKind === 'sell'">
                          <label class="ta-fld"><span>Qty</span><input v-model.number="taQty" class="ta-input" type="number" min="1" placeholder="1000" /></label>
                          <label class="ta-fld"><span>Type</span><select v-model="taOrderType" class="ta-input"><option value="limit">limit</option><option value="market">market</option></select></label>
                          <label v-if="taOrderType === 'limit'" class="ta-fld"><span>Limit price ({{ l.currency }})</span><input v-model="taLimitPrice" class="ta-input" type="text" inputmode="decimal" placeholder="10.00" /></label>
                        </template>
                        <template v-else-if="treasuryActionKind === 'mm'">
                          <label class="ta-fld" style="flex-direction:row;align-items:center;gap:.4rem"><input v-model="taMmEnabled" type="checkbox" /><span style="margin:0">Market-maker enabled</span></label>
                          <label class="ta-fld"><span>Spread (bps)</span><input v-model.number="taMmSpread" class="ta-input" type="number" min="1" placeholder="200" /></label>
                          <label class="ta-fld"><span>Quote qty/side</span><input v-model.number="taMmQty" class="ta-input" type="number" min="1" placeholder="100" /></label>
                        </template>
                        <!-- §T75 P2.2 — maker rebate -->
                        <template v-else-if="treasuryActionKind === 'rebate'">
                          <label class="ta-fld"><span>Maker rebate (bps)</span><input v-model.number="taRebateBps" class="ta-input" type="number" min="0" max="10000" placeholder="0" /></label>
                          <label class="ta-fld" style="flex-direction:row;align-items:center;gap:.4rem"><input v-model="taRebateRequiresReg" type="checkbox" /><span style="margin:0">Registered MM seats only</span></label>
                        </template>
                        <!-- §T75 P2.2 — grant/revoke a designated MM seat -->
                        <template v-else-if="treasuryActionKind === 'mmseat'">
                          <label class="ta-fld" style="flex:2 1 260px"><span>MM agent DID</span><input v-model="taMmSeatDid" class="ta-input" type="text" placeholder="did:theprotocol:…" /></label>
                          <label class="ta-fld"><span>Status</span><select v-model="taMmSeatStatus" class="ta-input"><option value="active">active</option><option value="suspended">suspended</option><option value="revoked">revoked</option></select></label>
                          <label class="ta-fld"><span>Max spread (bps, opt.)</span><input v-model.number="taMmSeatMaxSpread" class="ta-input" type="number" min="1" placeholder="—" /></label>
                        </template>
                        <!-- §T77 P5 — fee-edit (blank field = leave unchanged) -->
                        <template v-else-if="treasuryActionKind === 'fees'">
                          <label class="ta-fld"><span>Fee (bps, ≤1000)</span><input v-model.number="taFeeBps" class="ta-input" type="number" min="0" max="1000" placeholder="unchanged" /></label>
                          <label class="ta-fld"><span>Org split (bps)</span><input v-model.number="taFeeOrgSplitBps" class="ta-input" type="number" min="0" max="10000" placeholder="unchanged" /></label>
                          <label class="ta-fld"><span>Maker rebate (bps)</span><input v-model.number="taFeeRebateBps" class="ta-input" type="number" min="0" max="10000" placeholder="unchanged" /></label>
                        </template>
                        <button class="ta-btn ta-btn--go" :disabled="!treasuryActionValid" @click="showTreasuryConfirm = true">Review…</button>
                        <button class="ta-btn" @click="treasuryActionRow = null; treasuryActionKind = null">Cancel</button>
                      </div>
                    </td>
                  </tr>
                  <!-- §T75 — committed market-makers panel (public read; shown for MM-seat/rebate rows) -->
                  <tr v-if="mmBySymbol[l.symbol] && treasuryActionRow === l.symbol && (treasuryActionKind === 'mmseat' || treasuryActionKind === 'rebate')" :key="l.symbol + '-mmpanel'">
                    <td :colspan="canManageTreasury ? 7 : 6" style="padding:.4rem 1rem .75rem;background:var(--surface-2,#0d1622)">
                      <div style="display:flex;flex-wrap:wrap;align-items:center;gap:.5rem .9rem;font-size:.74rem;opacity:.8;margin-bottom:.4rem">
                        <span style="text-transform:uppercase;letter-spacing:.06em;opacity:.65">Committed market-makers</span>
                        <span class="ta-chip">rebate {{ mmBySymbol[l.symbol].maker_rebate_bps }} bps</span>
                        <span class="ta-chip">{{ mmBySymbol[l.symbol].rebate_requires_registration ? 'registered only' : 'open to any maker' }}</span>
                        <span class="ta-chip">{{ mmBySymbol[l.symbol].active_count }} active</span>
                      </div>
                      <div v-if="mmBySymbol[l.symbol].market_makers.length" style="display:flex;flex-direction:column;gap:.25rem">
                        <div v-for="mm in mmBySymbol[l.symbol].market_makers" :key="mm.agent_did"
                             style="display:flex;flex-wrap:wrap;align-items:center;gap:.6rem;font-size:.78rem;padding:.3rem .5rem;border:1px solid var(--border,#243044);border-radius:6px">
                          <code style="font-size:.72rem;opacity:.85">{{ mm.agent_did.length > 40 ? mm.agent_did.slice(0,22) + '…' + mm.agent_did.slice(-10) : mm.agent_did }}</code>
                          <span class="ta-chip" :style="{color: mm.status==='active' ? 'var(--pos,#3fb950)' : mm.status==='revoked' ? 'var(--neg,#f85149)' : 'inherit'}">{{ mm.status }}</span>
                          <span v-if="mm.max_spread_bps != null" style="opacity:.6;font-size:.7rem">≤{{ mm.max_spread_bps }} bps</span>
                          <span v-if="mm.since" style="opacity:.5;font-size:.7rem;margin-left:auto">since {{ new Date(mm.since).toLocaleDateString(appLocale()) }}</span>
                        </div>
                      </div>
                      <p v-else style="opacity:.55;font-size:.76rem;margin:.2rem 0 0">No designated market-makers yet — grant a seat to commit one.</p>
                    </td>
                  </tr>
                  </template>
                </tbody>
              </table>
            </template>
            <p v-else style="opacity:.6">No listings yet, the treasury appears once this org lists one and raises capital.</p>
          </div>

          <!-- ══ GOVERNANCE TAB (§P3.1 share-weighted proposals) ════════════ -->
          <div v-show="activeTab === 'governance'" class="tab-body">
            <div class="tab-header"><h2 class="tab-title">GOVERNANCE</h2></div>
            <template v-if="govSymbols.length">
              <div style="display:flex;flex-wrap:wrap;align-items:flex-end;gap:.75rem;margin-bottom:1rem">
                <label class="ta-fld"><span>Listing</span>
                  <select v-model="govSelectedSymbol" class="ta-input" @change="loadProposals">
                    <option v-for="s in govSymbols" :key="s" :value="s">${{ s }}</option>
                  </select>
                </label>
                <button v-if="canManageGov" class="ta-btn ta-btn--go" @click="showCreateProposal = !showCreateProposal">{{ showCreateProposal ? 'Close' : 'New proposal' }}</button>
                <div style="flex:1"></div>
                <div style="font-size:.7rem;opacity:.55;align-self:center">Point-weighted · holder snapshot frozen at creation · one vote per agent</div>
              </div>

              <!-- create-proposal form (org admin) -->
              <div v-if="showCreateProposal && canManageGov" class="gov-create-form">
                <div style="display:flex;flex-wrap:wrap;align-items:flex-end;gap:.75rem">
                  <label class="ta-fld" style="flex:2 1 240px"><span>Title</span><input v-model="cpTitle" class="ta-input" type="text" maxlength="255" placeholder="e.g. Approve Q3 treasury buy" /></label>
                  <label class="ta-fld"><span>Duration (days)</span><input v-model.number="cpDurationDays" class="ta-input" type="number" min="1" max="30" /></label>
                  <label class="ta-fld"><span>Quorum %</span><input v-model.number="cpQuorum" class="ta-input" type="number" min="1" max="100" /></label>
                  <label class="ta-fld"><span>Pass %</span><input v-model.number="cpPass" class="ta-input" type="number" min="1" max="100" /></label>
                </div>
                <label class="ta-fld" style="margin-top:.6rem"><span>Description</span><textarea v-model="cpDescription" class="ta-input" rows="2" style="width:100%;resize:vertical" placeholder="What are holders voting on?"></textarea></label>
                <div style="margin-top:.6rem;display:flex;gap:.5rem">
                  <button class="ta-btn ta-btn--go" :disabled="cpBusy || !cpTitle.trim() || !cpDescription.trim()" @click="submitProposal">{{ cpBusy ? 'Opening…' : 'Open proposal' }}</button>
                  <button class="ta-btn" @click="showCreateProposal = false">Cancel</button>
                </div>
              </div>

              <p v-if="govLoading" style="opacity:.6">Loading proposals…</p>
              <ReadFailedNotice v-else-if="govFailed" dense :retry="loadProposals" />
              <div v-else-if="!govProposals.length" class="gov-empty">
                <Icon name="gavel" />
                <div class="gov-empty-title">No proposals for ${{ govSelectedSymbol }} yet</div>
                <div class="gov-empty-sub">{{ canManageGov ? 'Open the first proposal — holders are enfranchised at the creation snapshot.' : 'An org admin opens proposals; holders are enfranchised at the snapshot.' }}</div>
                <button v-if="canManageGov" class="ta-btn ta-btn--go" @click="showCreateProposal = true">Open first proposal</button>
              </div>
              <table v-else class="org-tbl" style="width:100%;border-collapse:collapse;font-size:.9rem">
                <thead><tr style="text-align:left;opacity:.55;font-size:.7rem;text-transform:uppercase">
                  <th style="padding:.5rem">Title</th><th style="padding:.5rem">Status</th><th style="padding:.5rem">Enfranchised</th><th style="padding:.5rem">Ends</th><th style="padding:.5rem"></th>
                </tr></thead>
                <tbody>
                  <tr v-for="p in govProposals" :key="p.id" style="border-top:1px solid var(--border,#243044)">
                    <td style="padding:.55rem;font-weight:600">{{ p.title }}</td>
                    <td style="padding:.55rem;text-transform:uppercase;font-size:.7rem;opacity:.85" :style="{color: p.status==='passed' ? 'var(--pos,#3fb950)' : p.status==='failed' ? 'var(--neg,#f85149)' : 'inherit'}">{{ p.status }}</td>
                    <td style="padding:.55rem">{{ fmtAmt(String(p.enfranchised_total)) }}</td>
                    <td style="padding:.55rem;font-size:.8rem;opacity:.7">{{ p.end_at ? new Date(p.end_at).toLocaleString(appLocale()) : '—' }}</td>
                    <td style="padding:.55rem"><button class="ta-btn" @click="openProposal(p.id)">View</button></td>
                  </tr>
                </tbody>
              </table>
            </template>
            <ReadFailedNotice v-else-if="treasuryFailed" :retry="loadGovernance" data-testid="org-gov-listings-failed" />
            <p v-else style="opacity:.6">No listings yet, governance opens once this org lists one with external holders.</p>

            <!-- proposal detail + vote drawer -->
            <div v-if="govDetail" class="gov-drawer" @click.self="closeProposal">
              <div class="gov-drawer-panel">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem">
                  <div>
                    <div style="font-size:.68rem;opacity:.55;text-transform:uppercase">${{ govDetail.symbol }} · proposal</div>
                    <h3 style="margin:.2rem 0 .1rem;font-size:1.15rem">{{ govDetail.title }}</h3>
                    <div style="font-size:.7rem;text-transform:uppercase;opacity:.85" :style="{color: govDetail.status==='passed' ? 'var(--pos,#3fb950)' : govDetail.status==='failed' ? 'var(--neg,#f85149)' : 'inherit'}">{{ govDetail.status }}</div>
                  </div>
                  <button class="ta-btn" @click="closeProposal">Close</button>
                </div>
                <p style="margin:1rem 0;white-space:pre-wrap;font-size:.92rem;opacity:.9">{{ govDetail.description }}</p>
                <template v-if="govDetail.tally">
                  <div style="display:flex;justify-content:space-between;font-size:.72rem;opacity:.7;margin-bottom:.25rem"><span>FOR {{ fmtAmt(String(govDetail.tally.for)) }}</span><span>AGAINST {{ fmtAmt(String(govDetail.tally.against)) }}</span></div>
                  <div style="height:10px;border-radius:5px;overflow:hidden;background:var(--neg,#f85149)">
                    <div :style="{width: govPct(govDetail.tally.for, Number(govDetail.tally.for) + Number(govDetail.tally.against)) + '%', height:'100%', background:'var(--pos,#3fb950)'}"></div>
                  </div>
                  <div style="display:flex;flex-wrap:wrap;gap:1rem;margin-top:.75rem;font-size:.78rem;opacity:.8">
                    <span>Cast: <strong>{{ fmtAmt(String(govDetail.tally.cast)) }}</strong> / {{ fmtAmt(String(govDetail.tally.enfranchised)) }}</span>
                    <span>Quorum {{ govDetail.quorum_pct }}%: <strong :style="{color: govDetail.tally.quorum_met ? 'var(--pos,#3fb950)' : 'var(--neg,#f85149)'}">{{ govDetail.tally.quorum_met ? 'met' : 'not met' }}</strong></span>
                    <span>Pass {{ govDetail.pass_pct }}%: <strong :style="{color: govDetail.tally.passed ? 'var(--pos,#3fb950)' : 'inherit'}">{{ govDetail.tally.passed ? 'passing' : 'failing' }}</strong></span>
                    <span style="opacity:.7">{{ govDetail.tally.voting_ended ? 'voting ended' : 'voting open' }}</span>
                  </div>
                </template>
                <div style="margin-top:1.5rem;padding-top:1rem;border-top:1px solid var(--border,#243044)">
                  <div class="gov-vote-label">Cast vote · holder agent</div>
                  <button v-if="!activeAgentDid" class="gov-agent-pick" @click="pickShareholderAgent">
                    <Icon name="gavel" /><span>Select holder agent</span>
                  </button>
                  <div v-else class="gov-agent-chip">
                    <Icon name="check-circle" />
                    <code class="gov-agent-did">{{ activeAgentDid.slice(0, 34) }}…</code>
                    <button class="gov-agent-swap" @click="pickShareholderAgent">switch</button>
                  </div>
                  <input v-model="voteReason" class="ta-input" type="text" maxlength="255" placeholder="Reason (optional)" style="width:100%;margin:.6rem 0 .5rem" />
                  <div style="display:flex;gap:.5rem;align-items:center">
                    <button class="ta-btn ta-btn--go" :disabled="voteBusy || !activeAgentDid || govDetail.status !== 'voting'" @click="castGovVote(true)">Vote FOR</button>
                    <button class="ta-btn" :disabled="voteBusy || !activeAgentDid || govDetail.status !== 'voting'" @click="castGovVote(false)">Vote AGAINST</button>
                    <div style="flex:1"></div>
                    <button v-if="canManageGov" class="ta-btn" :disabled="tallyBusy" @click="runGovTally">{{ tallyBusy ? 'Tallying…' : 'Tally' }}</button>
                  </div>
                  <div v-if="!activeAgentDid" class="gov-vote-hint">Pick one of your agents that held ${{ govDetail.symbol }} at the snapshot to enable voting.</div>
                </div>
              </div>
            </div>
          </div>

          <!-- §CHATDESK C3 — the ROOM tab. The card moved here from SETTINGS
               (ONE mount); the moderation sheet surfaces the §OURSTATE-2 rails. -->
          <div v-show="activeTab === 'room'" class="tab-body" data-testid="cd-room-tab">
            <OrgRoomCard :org-id="org.id" />
            <OrgRoomModeration :org-id="org.id" :active="activeTab === 'room'" />
          </div>

          <div v-show="activeTab === 'settings'" class="tab-body">
            <div v-if="!orgStore.canManageOrganization" class="empty-state">
              <div class="empty-icon">
                <svg viewBox="0 0 24 24" fill="none" width="32" height="32"><rect x="3" y="11" width="18" height="11" rx="2" stroke="currentColor" stroke-width="1.5"/><path d="M7 11V7a5 5 0 0110 0v4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
              </div>
              <p class="empty-title">{{ t('organizationDashboardView.settings.accessTitle') }}</p>
              <p class="empty-body">{{ t('organizationDashboardView.settings.accessBody') }}</p>
            </div>

            <template v-else>
              <!-- Inline Edit Form -->
              <div class="settings-section">
                <h3 class="settings-section-title">{{ t('organizationDashboardView.settings.detailsTitle') }}</h3>
                <div class="settings-form">
                  <div class="form-field">
                    <label class="form-label">{{ t('organizationDashboardView.settings.nameLabel') }}</label>
                    <input v-model="settingsForm.name" type="text" class="form-input" :placeholder="t('organizationDashboardView.settings.namePlaceholder')" />
                  </div>
                  <div class="form-field">
                    <label class="form-label">{{ t('organizationDashboardView.settings.descLabel') }}</label>
                    <textarea v-model="settingsForm.description" class="form-input form-textarea" rows="3" :placeholder="t('organizationDashboardView.settings.descPlaceholder')"></textarea>
                  </div>
                  <div class="form-field">
                    <label class="form-label">{{ t('organizationDashboardView.settings.websiteLabel') }}</label>
                    <input v-model="settingsForm.website" type="url" class="form-input" :placeholder="t('organizationDashboardView.settings.websitePlaceholder')" />
                  </div>
                  <div class="form-field">
                    <label class="form-label">{{ t('organizationDashboardView.settings.slugLabel') }} <span class="form-label-note">{{ t('organizationDashboardView.settings.readOnly') }}</span></label>
                    <div class="form-readonly">{{ org.slug }}</div>
                  </div>
                  <div class="form-field">
                    <label class="form-label">{{ t('organizationDashboardView.settings.createdLabel') }} <span class="form-label-note">{{ t('organizationDashboardView.settings.readOnly') }}</span></label>
                    <div class="form-readonly">{{ formatDate(org.created_at) }}</div>
                  </div>
                  <div class="settings-save-row">
                    <button
                      class="cmd-btn cmd-btn--primary"
                      :disabled="isSavingSettings"
                      @click="saveSettings"
                    >
                      <span v-if="isSavingSettings">{{ t('organizationDashboardView.settings.saving') }}</span>
                      <span v-else>{{ t('organizationDashboardView.settings.saveBtn') }}</span>
                    </button>
                  </div>
                </div>
              </div>

              <!-- §ORGPOLICY — tighten-only organization policy over the registry -->
              <OrgPolicySettings :org-id="org.id" :can-edit="orgStore.canManageOrganization" />

              <!-- E1a — ownership handshake (offer / accept / withdraw) -->
              <OrgOwnershipCard :org-id="org.id" @ownership-changed="orgStore.selectOrganization(org.id)" />

              <!-- Danger Zone -->
              <div class="danger-zone">
                <h3 class="danger-title">{{ t('organizationDashboardView.danger.title') }}</h3>
                <p class="danger-body">{{ t('organizationDashboardView.danger.body') }}</p>
                <button class="danger-btn" @click="confirmDeleteOrg">
                  {{ t('organizationDashboardView.danger.deleteBtn') }}
                </button>

                <!-- E1b — deletion refused: the money-safety checklist. Rendered after a
                     blocked attempt; the funded-treasury row carries the sweep rail inline. -->
                <div v-if="deleteBlockers.length" class="delete-blockers" data-testid="delete-blockers">
                  <p class="delete-blockers-title">
                    {{ t('organizationDashboardView.danger.blockedTitle', 'Deletion is blocked until these are resolved:') }}
                  </p>
                  <ul class="delete-blockers-list">
                    <li v-for="(b, i) in deleteBlockers" :key="i" class="delete-blocker">
                      <template v-if="b.kind === 'funded_treasury'">
                        <span class="delete-blocker-line">
                          {{ t('organizationDashboardView.danger.blockerTreasury', 'The org treasury still holds') }}
                          <strong class="mono">{{ Number(b.balance).toLocaleString(appLocale(), { maximumFractionDigits: 6 }) }}</strong>
                        </span>
                      </template>
                      <template v-else-if="b.kind === 'exchange_listing'">
                        <span class="delete-blocker-line">
                          {{ t('organizationDashboardView.danger.blockerListing', 'AGORA listing is still live:') }}
                          <strong class="mono">${{ b.symbol }}</strong> ({{ b.status }})
                        </span>
                      </template>
                      <template v-else>
                        <span class="delete-blocker-line mono">{{ b.kind }}</span>
                      </template>
                      <span class="delete-blocker-action">{{ b.action }}</span>
                    </li>
                  </ul>
                  <div v-if="hasTreasuryBlocker" class="sweep-form">
                    <label class="form-label" for="sweep-dest">
                      {{ t('organizationDashboardView.danger.sweepLabel', 'Sweep the full balance to one of YOUR agents') }}
                    </label>
                    <div class="sweep-row">
                      <input
                        id="sweep-dest" v-model="sweepDest" list="sweep-dest-options" class="form-input"
                        :placeholder="t('organizationDashboardView.danger.sweepPlaceholder', 'did:theprotocol:... (an agent you created)')"
                        data-testid="sweep-dest"
                      />
                      <datalist id="sweep-dest-options">
                        <option v-for="a in myAgentOptions" :key="a.did" :value="a.did">{{ a.name }}</option>
                      </datalist>
                      <button class="danger-btn" :disabled="sweepBusy || !sweepDest.trim()" data-testid="sweep-btn" @click="doSweepTreasury">
                        {{ sweepBusy
                          ? t('organizationDashboardView.danger.sweeping', 'Sweeping...')
                          : t('organizationDashboardView.danger.sweepBtn', 'Sweep treasury') }}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </template>
          </div>

        </div><!-- /tab-panel -->
      </div><!-- /org-content -->
    </template>

    <!-- ══ MODALS ═════════════════════════════════════════════════════════════ -->
    <CreateOrganizationModal
      v-if="showCreateOrgModal"
      @close="showCreateOrgModal = false"
      @created="onOrgCreated"
    />
    <EditOrganizationModal
      v-if="showEditOrgModal"
      :organization="org"
      @close="showEditOrgModal = false"
      @updated="showEditOrgModal = false"
    />
    <CreateTeamModal
      v-if="showCreateTeamModal"
      @close="showCreateTeamModal = false"
      @created="showCreateTeamModal = false"
    />
    <EditTeamModal
      v-if="editingTeam"
      :team="editingTeam"
      @close="editingTeam = null"
      @updated="editingTeam = null"
    />
    <InviteMemberModal
      v-if="showInviteMemberModal"
      @close="showInviteMemberModal = false"
      @invited="showInviteMemberModal = false"
    />
    <TeamMembersModal
      v-if="viewingTeam"
      :team="viewingTeam"
      @close="viewingTeam = null"
    />
    <ChangeMemberRoleModal
      v-if="changingRoleMember"
      :member="changingRoleMember"
      @close="changingRoleMember = null"
      @updated="changingRoleMember = null"
    />

    <!-- OD1+OD2+OD3 (audit 2026-05-07): themed destructive confirms -->
    <ConfirmActionModal
      :show="showDeleteTeamModal"
      title="// DELETE TEAM"
      :message="teamToDelete
        ? `Delete team <strong>${teamToDelete.name}</strong>? Team members are NOT removed from the organization, but team-scoped permissions for them are revoked. This cannot be undone.`
        : ''"
      tone="danger"
      confirm-text="Delete Team"
      busy-text="Deleting…"
      :busy="deleteTeamBusy"
      @close="showDeleteTeamModal = false; teamToDelete = null"
      @confirm="confirmDeleteTeam"
    />

    <ConfirmActionModal
      :show="showRemoveMemberModal"
      title="// REMOVE MEMBER"
      :message="memberToRemove
        ? `Remove <strong>${memberToRemove.developer_name}</strong> from this organization? They lose access immediately and must be re-invited to rejoin.`
        : ''"
      tone="warn"
      confirm-text="Remove Member"
      busy-text="Removing…"
      :busy="removeMemberBusy"
      @close="showRemoveMemberModal = false; memberToRemove = null"
      @confirm="confirmRemoveMember"
    />

    <ConfirmActionModal
      :show="showDeleteOrgModal"
      title="// PERMANENTLY DELETE ORGANIZATION"
      :message="org
        ? `<strong>This action is irreversible.</strong> All teams, member records, and assignments will be deleted. To confirm, type the organization name <code>${org.name}</code> below.`
        : ''"
      tone="danger"
      confirm-text="Delete Organization"
      busy-text="Deleting…"
      :busy="deleteOrgBusy"
      :required-match="org?.name || ''"
      :reason-placeholder="org?.name || ''"
      warning="All members lose access. Agent assignments are nulled. EventStore audit trail of org events is preserved."
      @close="showDeleteOrgModal = false"
      @confirm="executeDeleteOrg"
    />

    <!-- §V0113 Phase 2 — treasury spend confirm (org admin). Inline form holds the
         inputs; this modal is the final confirm. Δ-safe server spine moves funds. -->
    <ConfirmActionModal
      :show="showTreasuryConfirm"
      :title="`// TREASURY ${treasuryActionLabel(treasuryActionKind).toUpperCase()}`"
      :message="treasuryConfirmMessage"
      tone="warn"
      confirm-text="Confirm"
      busy-text="Submitting…"
      :busy="treasuryActionBusy"
      @close="showTreasuryConfirm = false"
      @confirm="confirmTreasuryAction"
    />

    <!-- §pass50.1 — Member detail side drawer. Read-only profile with quick
         actions (change role / remove) for owners + admins. -->
    <Transition name="md-drawer">
      <aside v-if="detailMember" class="md-drawer" role="dialog" :aria-label="`Member detail: ${detailMember.developer_name}`">
        <div class="md-drawer__scrim" @click="closeMemberDetail" aria-hidden="true" />
        <div class="md-drawer__panel" @click.stop>
          <header class="md-drawer__head">
            <div class="md-drawer__avatar" :style="avatarStyle(detailMember.role)">
              {{ detailMember.developer_name.charAt(0).toUpperCase() }}
            </div>
            <div class="md-drawer__id">
              <div class="md-drawer__name">{{ detailMember.developer_name }}<span v-if="isCurrentUser(detailMember)" class="md-you"> (you)</span></div>
              <div class="md-drawer__email">{{ detailMember.developer_email }}</div>
            </div>
            <button class="md-drawer__close" @click="closeMemberDetail" aria-label="Close">&times;</button>
          </header>
          <div class="md-drawer__body">
            <div class="md-drawer__row">
              <div class="md-drawer__row-label">Role</div>
              <div class="md-drawer__row-value">
                <span :class="['role-badge', roleBadgeClass(detailMember.role)]">{{ detailMember.role.toUpperCase() }}</span>
              </div>
            </div>
            <div class="md-drawer__row">
              <div class="md-drawer__row-label">Joined</div>
              <div class="md-drawer__row-value">{{ formatDate(detailMember.joined_at) }}</div>
            </div>
            <div class="md-drawer__row">
              <div class="md-drawer__row-label">Developer ID</div>
              <div class="md-drawer__row-value"><code>{{ detailMember.developer_id }}</code></div>
            </div>
          </div>
          <footer class="md-drawer__foot">
            <template v-if="canManageMember(detailMember)">
              <button class="cmd-btn cmd-btn--secondary cmd-btn--sm" @click="changingRoleMember = detailMember; closeMemberDetail()">Change role</button>
              <button class="cmd-btn cmd-btn--danger cmd-btn--sm" @click="removeMember(detailMember); closeMemberDetail()">Remove from org</button>
            </template>
            <button class="cmd-btn cmd-btn--ghost cmd-btn--sm" @click="closeMemberDetail">Close</button>
          </footer>
        </div>
      </aside>
    </Transition>
  </div>
</template>

<style scoped>
/* §V0113 Phase 2 — treasury action buttons + inline form fields. */
.ta-btn {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .64rem; font-weight: 600; letter-spacing: .06em; text-transform: uppercase;
  padding: .3rem .55rem; margin-right: .35rem;
  border-radius: 5px; cursor: pointer;
  background: transparent; color: #8fa3be;
  border: 1px solid rgba(var(--nc-primary-rgb), .2);
  transition: all .15s;
}
.ta-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), .08); color: rgb(0, 210, 210); }
.ta-btn:disabled { opacity: .4; cursor: not-allowed; }
.ta-btn--go { background: rgba(251, 191, 36, .15); color: rgb(251, 191, 36); border-color: rgba(251, 191, 36, .4); }
.ta-btn--go:hover:not(:disabled) { background: rgba(251, 191, 36, .25); }
.ta-fld { display: flex; flex-direction: column; gap: .25rem; flex: 1 1 130px; }
.ta-fld > span { font-size: .62rem; letter-spacing: .05em; text-transform: uppercase; opacity: .6; }
.ta-input {
  width: 100%; box-sizing: border-box;
  background: rgba(255, 255, 255, .04);
  border: 1px solid rgba(var(--nc-primary-rgb), .2);
  border-radius: 6px; color: #e2e8f0; padding: .4rem .6rem;
  font-size: .82rem; outline: none; font-family: inherit;
  transition: border-color .15s;
}
.ta-input:focus { border-color: rgba(var(--nc-primary-rgb), .55); background: rgba(255, 255, 255, .06); }
/* §T75 — small status/config chip for the committed-market-makers panel */
.ta-chip {
  display: inline-flex; align-items: center; font-family: ui-monospace, monospace;
  font-size: .66rem; letter-spacing: .04em; text-transform: uppercase;
  padding: .15rem .5rem; border-radius: 99px;
  border: 1px solid rgba(var(--nc-primary-rgb), .25); background: rgba(var(--nc-primary-rgb), .06);
}

/* ══ Root ══════════════════════════════════════════════════════════════════ */
.org-root {
  min-height: 100vh;
  /* §pass50.1 — opaque background removed so DashboardLayout's <ViewAmbient>
     paints the unified default tone through (was solid #060b14 blocking it). */
  color: rgba(226,232,240,0.88);
  font-family: system-ui, -apple-system, sans-serif;
  padding: 0;
  position: relative;
  z-index: 1;
}

/* ══ Loading ═══════════════════════════════════════════════════════════════ */
.org-loading {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  min-height: 60vh; gap: 16px;
}
.loading-spinner {
  width: 36px; height: 36px;
  border: 2px solid rgba(var(--nc-primary-rgb),0.12);
  border-top-color: rgba(var(--nc-primary-rgb),0.7);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.loading-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb),0.45);
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ══ Command Bar ═══════════════════════════════════════════════════════════ */
.cmd-bar {
  display: flex; align-items: center; justify-content: space-between;
  padding: 18px 32px 16px;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
  background: rgba(13,22,38,0.6);
  backdrop-filter: blur(8px);
}
.cmd-breadcrumb {
  display: flex; align-items: center; gap: 8px;
  font-family: 'IBM Plex Mono', monospace;
}
.breadcrumb-section {
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.16em;
  color: rgba(var(--nc-primary-rgb),0.75);
}
.breadcrumb-sep {
  font-size: 0.65rem; color: rgba(var(--nc-primary-rgb),0.2);
}
.cmd-glyph {
  font-size: 1.05rem; line-height: 1;
  color: rgba(var(--nc-primary-rgb),0.85);
  filter: drop-shadow(0 0 6px rgba(var(--nc-primary-rgb),0.4));
}
.cmd-title {
  margin: 0; font-family: 'IBM Plex Mono', monospace;
  font-size: 1.0rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb),1), rgba(var(--nc-primary-rgb),0.55));
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: rgba(var(--nc-primary-rgb),0.9);
}
.cmd-title-amp { -webkit-text-fill-color: rgba(148,163,184,0.55); color: rgba(148,163,184,0.55); font-weight: 400; }
.cmd-controls { display: flex; align-items: center; gap: 12px; }

/* Org selector */
.org-selector-wrap { position: relative; display: flex; align-items: center; }
.org-selector {
  appearance: none;
  background: rgba(13,22,38,0.8);
  border: 1px solid rgba(var(--nc-primary-rgb),0.18);
  border-radius: 6px;
  padding: 7px 36px 7px 12px;
  color: rgba(226,232,240,0.85);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  cursor: pointer; outline: none;
  transition: border-color 0.15s;
}
.org-selector:focus, .org-selector:hover { border-color: rgba(var(--nc-primary-rgb),0.38); }
.org-selector:disabled { opacity: 0.5; cursor: not-allowed; }
.selector-arrow {
  position: absolute; right: 10px; width: 10px; height: 6px;
  pointer-events: none; color: rgba(var(--nc-primary-rgb),0.45);
}

/* Buttons */
.cmd-btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 600; letter-spacing: 0.1em;
  padding: 8px 16px; border-radius: 6px; cursor: pointer;
  transition: all 0.15s; border: 1px solid transparent;
}
.cmd-btn--primary {
  background: rgba(var(--nc-primary-rgb),0.12);
  border-color: rgba(var(--nc-primary-rgb),0.3);
  color: rgba(var(--nc-primary-rgb),0.9);
}
.cmd-btn--primary:hover {
  background: rgba(var(--nc-primary-rgb),0.2);
  border-color: rgba(var(--nc-primary-rgb),0.55);
}
.cmd-btn--secondary {
  background: rgba(255,255,255,0.03);
  border-color: rgba(255,255,255,0.1);
  color: rgba(148,163,184,0.7);
}
.cmd-btn--secondary:hover { background: rgba(255,255,255,0.06); color: rgba(226,232,240,0.85); }
.cmd-btn--sm { padding: 6px 12px; font-size: 0.63rem; }
/* §ORGPOCKET O3 — both of these had markup and NO rule anywhere in the tree, so
   the REMOVE-MEMBER button was painted exactly like a neutral one. A destructive
   action that looks ordinary is a defect, not a style preference. */
.cmd-btn--xs { padding: 4px 10px; font-size: 0.58rem; letter-spacing: 0.08em; }
.cmd-btn--danger {
  background: rgba(239,68,68,0.08);
  border-color: rgba(239,68,68,0.32);
  color: rgba(248,113,113,0.92);
}
.cmd-btn--danger:hover { background: rgba(239,68,68,0.16); border-color: rgba(239,68,68,0.6); }
.cmd-card {
  background: rgba(6,11,20,0.4);
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 8px;
}
.delete-blocker-line { display: block; font-size: 0.8rem; line-height: 1.6; color: rgba(248,113,113,0.85); }
.md-drawer__id {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
  color: rgba(var(--nc-primary-rgb),0.55); word-break: break-all;
}
.cmd-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.btn-icon { width: 12px; height: 12px; flex-shrink: 0; }

/* ══ No-Org State ══════════════════════════════════════════════════════════ */
.no-org-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  min-height: 55vh; gap: 14px; text-align: center; padding: 40px;
}
.no-org-hex {
  font-size: 2.5rem; color: rgba(var(--nc-primary-rgb),0.18);
  line-height: 1; margin-bottom: 4px;
}
.no-org-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.2em;
  color: rgba(var(--nc-primary-rgb),0.55);
}
.no-org-body {
  font-size: 0.85rem; color: rgba(148,163,184,0.55);
  max-width: 380px; line-height: 1.6;
}

/* ══ Org Content ═══════════════════════════════════════════════════════════ */
.org-content { padding: 28px 32px; max-width: 1280px; }

/* ══ Identity Panel ════════════════════════════════════════════════════════ */
.identity-panel {
  background: #0d1626;
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 10px; padding: 24px 28px; margin-bottom: 20px;
}
.identity-main { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 24px; }
.identity-left { flex: 1; min-width: 0; }
.identity-name-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 6px; }
.identity-name {
  font-size: 1.65rem; font-weight: 700;
  color: rgba(226,232,240,0.95); margin: 0;
}
.identity-slug {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem; color: rgba(var(--nc-primary-rgb),0.85);
  margin-bottom: 8px;
}
.slug-prefix { color: rgba(var(--nc-primary-rgb),0.25); margin-right: 1px; }
.identity-desc { font-size: 0.875rem; color: rgba(148,163,184,0.85); margin: 0 0 8px; line-height: 1.5; }
.identity-website {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 0.8rem; color: rgba(var(--nc-primary-rgb),0.6);
  text-decoration: none;
  transition: color 0.15s;
}
.identity-website:hover { color: rgba(var(--nc-primary-rgb),0.9); }
.web-icon { width: 12px; height: 12px; flex-shrink: 0; }
.identity-actions { display: flex; gap: 8px; flex-shrink: 0; margin-left: 20px; }
.id-btn--forge { display: inline-flex; align-items: center; gap: 6px; border-color: rgba(139,92,246,0.5); }
.id-btn--forge:hover { border-color: rgba(139,92,246,0.85); background: rgba(139,92,246,0.12); }
.id-btn {
  padding: 5px 14px;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 5px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; font-weight: 600; letter-spacing: 0.1em;
  color: rgba(148,163,184,0.85);
  transition: all 0.15s;
}
.id-btn:hover { background: rgba(255,255,255,0.06); color: rgba(226,232,240,0.8); border-color: rgba(255,255,255,0.18); }

/* ── Role Badges ──────────────────────────────────────────────────────────── */
.role-badge {
  display: inline-flex; align-items: center;
  padding: 3px 10px; border-radius: 20px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; font-weight: 700; letter-spacing: 0.1em;
  border: 1px solid transparent;
}
.role--owner  { background: rgba(255,215,0,0.1); color: #ffd700; border-color: rgba(255,215,0,0.25); }
.role--admin  { background: rgba(var(--nc-primary-rgb),0.1); color: rgba(var(--nc-primary-rgb),0.9); border-color: rgba(var(--nc-primary-rgb),0.22); }
.role--member { background: rgba(41,182,246,0.1); color: rgba(41,182,246,0.9); border-color: rgba(41,182,246,0.22); }
.role--guest  { background: rgba(255,255,255,0.05); color: rgba(148,163,184,0.6); border-color: rgba(255,255,255,0.1); }

/* ── Capacity Meters ──────────────────────────────────────────────────────── */
.capacity-row { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
.capacity-item {
  padding: 10px 12px 11px; border-radius: 8px;
  background: rgba(6,11,20,0.4); border: 1px solid rgba(var(--nc-primary-rgb),0.08);
  transition: border-color 0.15s;
}
.capacity-item:hover { border-color: rgba(var(--nc-primary-rgb),0.18); }
.cap-label {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 7px;
}
.cap-name {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; letter-spacing: 0.14em;
  color: rgba(148,163,184,0.8);
}
.cap-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem; font-weight: 700;
  color: rgba(226,232,240,0.92);
}
.cap-limit { font-weight: 400; color: rgba(148,163,184,0.8); font-size: 0.62rem; }
.cap-track {
  height: 5px; background: rgba(255,255,255,0.05); border-radius: 3px; overflow: hidden;
}
.cap-fill {
  height: 100%; border-radius: 3px;
  transition: width 0.7s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 0 8px rgba(var(--nc-primary-rgb),0.3);
}
.cap-fill--members { background: linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.5), rgba(var(--nc-primary-rgb),0.9)); }
.cap-fill--teams   { background: linear-gradient(90deg, rgba(41,182,246,0.5), rgba(41,182,246,0.9)); box-shadow: 0 0 8px rgba(41,182,246,0.3); }
.cap-fill--agents  { background: linear-gradient(90deg, rgba(105,240,174,0.5), rgba(105,240,174,0.9)); box-shadow: 0 0 8px rgba(105,240,174,0.3); }

/* ══ Tab Panel ═════════════════════════════════════════════════════════════ */
.tab-panel {
  background: #0d1626;
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 10px; overflow: hidden;
}
.tab-bar {
  display: flex;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
  background: rgba(6,11,20,0.4);
  /* §ORGPOCKET O3 — measured 2026-08-28 at 390px: scrollWidth 1082 inside
     clientWidth 324, and the parent .tab-panel is overflow:hidden (it has to
     be, for the 10px radius). Hidden overflow has no user-scrollable box, so
     SEVEN of the ten tabs were unreachable to a finger — TREASURY, AUTHORITY,
     CI/CD, GOVERNANCE, SETTINGS, AUDIT and half of ACTIVITY. The scroll belongs
     on this row, not on the panel. No-op at 1440 where nothing overflows. */
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: none;
  -webkit-overflow-scrolling: touch;
  scroll-snap-type: x proximity;
}
.tab-bar::-webkit-scrollbar { display: none; }
/* §CHATPOLISH (2026-08-30) — the note above ends "No-op at 1440 where nothing
   overflows", and that premise expired: the row now carries ELEVEN tabs and at
   1440px it clipped mid-word on AUDIT. The scrollbar is hidden by design, so a
   desktop mouse had no affordance and no way to know a tab was there at all —
   the phone bug of §ORGPOCKET O3, wearing a desktop suit. Wrapping (rather than
   a fade, or hand-tuned padding) is the fix that stays correct the next time a
   tab is added, which on this screen is a matter of when. Phone keeps the
   single scrolling row: two rows of tabs on a 390px screen is worse. */
@media (min-width: 900px) {
  .tab-bar { flex-wrap: wrap; overflow-x: visible; }
}
.tab-btn {
  display: flex; align-items: center; gap: 7px;
  flex: 0 0 auto; white-space: nowrap; scroll-snap-align: start;
  padding: 14px 22px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.63rem; font-weight: 600; letter-spacing: 0.12em;
  color: rgba(148,163,184,0.8); /* §FESUITE 135: was 0.45, 2.4:1 */
  border: none; background: transparent; cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.15s;
  margin-bottom: -1px;
}
.tab-btn:hover { color: rgba(226,232,240,0.7); }
.tab-btn--active {
  color: rgba(var(--nc-primary-rgb),0.95);
  border-bottom-color: rgba(var(--nc-primary-rgb),0.85);
  background: linear-gradient(180deg, transparent, rgba(var(--nc-primary-rgb),0.06));
  box-shadow: inset 0 -8px 14px -10px rgba(var(--nc-primary-rgb),0.5);
}
.tab-count {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 18px; height: 18px; border-radius: 9px; padding: 0 5px;
  font-size: 0.58rem;
  background: rgba(255,255,255,0.05);
  color: rgba(148,163,184,0.45);
}
.tab-count--active {
  background: rgba(var(--nc-primary-rgb),0.12);
  color: rgba(var(--nc-primary-rgb),0.8);
}
.audit-rows { display: flex; flex-direction: column; gap: 6px; }
.audit-row {
  display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
  padding: 8px 12px; border: 1px solid rgba(255,255,255,0.05); border-radius: 6px;
  background: rgba(255,255,255,0.015);
}
.audit-type { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: rgba(var(--nc-primary-rgb),0.8); min-width: 240px; }
.audit-when { font-size: 0.66rem; color: rgba(148,163,184,0.4); }
.audit-data { font-size: 0.7rem; color: rgba(148,163,184,0.6); flex: 1; }

/* B3 oversight — org spend approvals (read-only) */
.oap-block { margin-top: 22px; padding-top: 18px; border-top: 1px solid rgba(148,163,184,0.12); }
.oap-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 14px; flex-wrap: wrap; }
.oap-title { margin: 0; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: rgba(226,232,240,0.85); }
.oap-sub { margin: 6px 0 0; font-size: 0.7rem; line-height: 1.55; max-width: 640px; color: rgba(148,163,184,0.65); }
.oap-empty { margin-top: 12px; padding: 14px; font-size: 0.72rem; color: rgba(148,163,184,0.6);
  border: 1px dashed rgba(148,163,184,0.18); border-radius: 8px; }
.oap-empty--err { color: rgba(248,113,113,0.8); border-color: rgba(248,113,113,0.3); }
.oap-rows { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.oap-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 10px;
  background: rgba(15,23,42,0.45); border: 1px solid rgba(148,163,184,0.1); border-radius: 8px; font-size: 0.72rem; }
.oap-status { padding: 1px 8px; border-radius: 999px; font-size: 0.62rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.06em; border: 1px solid rgba(148,163,184,0.3); color: rgba(148,163,184,0.8); }
.oap-status--pending { border-color: rgba(250,204,21,0.5); color: rgba(250,204,21,0.9); }
.oap-status--approved { border-color: rgba(74,222,128,0.5); color: rgba(74,222,128,0.9); }
.oap-status--consumed { border-color: rgba(56,189,248,0.5); color: rgba(56,189,248,0.9); }
.oap-status--denied, .oap-status--expired { border-color: rgba(248,113,113,0.45); color: rgba(248,113,113,0.85); }
.oap-amount { font-weight: 700; color: rgba(226,232,240,0.9); }
.oap-cur { font-weight: 400; color: rgba(148,163,184,0.7); }
.oap-agent { color: rgba(226,232,240,0.75); }
.oap-cpty { color: rgba(148,163,184,0.6); }
.oap-when { margin-left: auto; color: rgba(148,163,184,0.55); }

.tab-body { padding: 24px 28px; }

/* Tab headers */
.tab-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 20px;
}
.tab-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.15em;
  color: rgba(var(--nc-primary-rgb),0.7); margin: 0;
}

/* ══ Skeleton loaders ══════════════════════════════════════════════════════ */
.skel-rows { display: flex; flex-direction: column; gap: 10px; }
.skel-card {
  height: 140px; border-radius: 8px;
  background: linear-gradient(90deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.06) 50%, rgba(255,255,255,0.03) 100%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}
.skel-row {
  height: 56px; border-radius: 6px;
  background: linear-gradient(90deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.06) 50%, rgba(255,255,255,0.03) 100%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}
@keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }

/* ══ Empty State ═══════════════════════════════════════════════════════════ */
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  padding: 56px 20px; gap: 10px; text-align: center;
}
.empty-icon { font-size: 2rem; color: rgba(148,163,184,0.15); }
.empty-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem; font-weight: 600; letter-spacing: 0.1em;
  color: rgba(148,163,184,0.5);
}
.empty-body { font-size: 0.83rem; color: rgba(148,163,184,0.35); max-width: 320px; line-height: 1.6; }

/* ══ Governance · agent-selector + empty (§2026-06-25 polish) ══════════════ */
.gov-vote-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; font-weight: 600; letter-spacing: 0.16em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb),0.7); margin-bottom: 0.55rem;
}
.gov-agent-pick {
  display: inline-flex; align-items: center; gap: 0.5rem;
  padding: 0.6rem 0.95rem; width: 100%; justify-content: center;
  border: 1px dashed rgba(var(--nc-primary-rgb),0.45); border-radius: 8px;
  background: rgba(var(--nc-primary-rgb),0.06); color: rgba(var(--nc-primary-rgb),0.95);
  font-size: 0.82rem; font-weight: 600; cursor: pointer;
  transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
}
.gov-agent-pick:hover {
  border-color: rgba(var(--nc-primary-rgb),0.8); background: rgba(var(--nc-primary-rgb),0.12);
  box-shadow: 0 0 18px rgba(var(--nc-primary-rgb),0.15);
}
.gov-agent-pick :deep(svg), .gov-agent-chip :deep(svg) { width: 16px; height: 16px; }
.gov-agent-chip {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.5rem 0.7rem; border-radius: 8px;
  border: 1px solid rgba(63,185,80,0.35); background: rgba(63,185,80,0.08); color: rgba(63,185,80,0.95);
}
.gov-agent-did { font-size: 0.74rem; color: rgba(226,232,240,0.85); flex: 1; overflow: hidden; text-overflow: ellipsis; }
.gov-agent-swap {
  font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.08em;
  padding: 0.2rem 0.5rem; border-radius: 5px; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb),0.3); background: transparent; color: rgba(var(--nc-primary-rgb),0.85);
}
.gov-agent-swap:hover { background: rgba(var(--nc-primary-rgb),0.12); }
.gov-vote-hint { font-size: 0.72rem; color: rgba(148,163,184,0.55); margin-top: 0.45rem; }
.gov-agent-pick:focus-visible, .gov-agent-swap:focus-visible, .gov-empty .ta-btn:focus-visible {
  outline: 2px solid rgba(var(--nc-primary-rgb),0.65); outline-offset: 2px;
}
.gov-empty {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  text-align: center; gap: 0.55rem; padding: 48px 20px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.1); border-radius: 10px; background: rgba(6,11,20,0.5);
}
.gov-empty :deep(svg) { width: 30px; height: 30px; color: rgba(var(--nc-primary-rgb),0.4); }
.gov-empty-title {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.82rem; font-weight: 600;
  letter-spacing: 0.04em; color: rgba(226,232,240,0.85);
}
.gov-empty-sub { font-size: 0.8rem; color: rgba(148,163,184,0.55); max-width: 380px; line-height: 1.6; }
.gov-empty .ta-btn { margin-top: 0.4rem; }
.gov-create-form { padding: 0.9rem 1.05rem; border: 1px solid rgba(var(--nc-primary-rgb),0.16); border-radius: 10px; background: rgba(6,11,20,0.5); margin-bottom: 1.25rem; }
.gov-drawer { position: fixed; inset: 0; background: rgba(2,6,14,0.62); backdrop-filter: blur(3px); display: flex; justify-content: flex-end; z-index: 60; }
.gov-drawer-panel {
  width: min(560px, 100%); height: 100%; overflow: auto; padding: 1.5rem;
  background: linear-gradient(180deg, #0c1422, #0a1018);
  border-left: 1px solid rgba(var(--nc-primary-rgb),0.22);
  box-shadow: -20px 0 50px rgba(0,0,0,0.5);
}

/* ══ Treasury summary cards (§2026-06-25 polish) ═══════════════════════════ */
.tr-cards { display: flex; flex-wrap: wrap; gap: 1rem; margin-bottom: 1.25rem; }
/* ── Track C3 — the org's own treasury account ─────────────────────────────── */
.oa-sec {
  border: 1px solid rgba(var(--nc-primary-rgb),0.14); border-radius: 10px;
  padding: 1rem 1.15rem 1.1rem; margin-bottom: 1.2rem;
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.04), rgba(6,11,20,0.45));
}
.oa-head { display: flex; align-items: center; gap: .6rem; margin-bottom: .75rem; }
.oa-title { margin: 0; font-size: .95rem; letter-spacing: .04em; text-transform: uppercase; opacity: .9; }
.oa-badge { font-size: .62rem; letter-spacing: .07em; text-transform: uppercase; padding: .18rem .45rem;
            border-radius: 4px; border: 1px solid currentColor; opacity: .85; }
.oa-badge--own   { color: var(--nc-primary, #4fd1c5); }
.oa-badge--agora { color: #d6a44c; }
.oa-badge--none  { color: #7b8a9e; }
.oa-grid { display: flex; flex-wrap: wrap; gap: .75rem; }
.oa-card { flex: 1 1 180px; padding: .8rem .95rem; border-radius: 8px;
           border: 1px solid rgba(var(--nc-primary-rgb),0.12); background: rgba(6,11,20,0.35); }
.oa-card--did { flex: 3 1 340px; min-width: 0; }
.oa-k { font-size: .66rem; text-transform: uppercase; letter-spacing: .07em; opacity: .55; }
.oa-v { font-size: 1.5rem; font-weight: 600; margin-top: .2rem; }
.oa-did { font-family: var(--font-mono, ui-monospace, monospace); font-size: .78rem; margin-top: .3rem;
          word-break: break-all; opacity: .9; }
.oa-sub, .oa-hint { font-size: .72rem; opacity: .6; margin: .35rem 0 0; line-height: 1.45; }
.oa-empty { padding: .3rem 0 .1rem; }
.oa-empty p { margin: 0 0 .5rem; }
.oa-fund { margin-top: 1rem; padding-top: .9rem; border-top: 1px solid rgba(var(--nc-primary-rgb),0.10); }
.oa-fund-row { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
.oa-msg { margin: .7rem 0 0; font-size: .78rem; }
.oa-msg--ok  { color: var(--nc-primary, #4fd1c5); }
.oa-msg--err { color: #e06c75; }
.oa-moves { margin-top: 1rem; padding-top: .9rem; border-top: 1px solid rgba(var(--nc-primary-rgb),0.10); }
.oa-move { display: flex; flex-wrap: wrap; align-items: baseline; gap: .55rem; padding: .3rem 0;
           font-size: .76rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06); }
.oa-move-kind { font-size: .6rem; text-transform: uppercase; letter-spacing: .06em; padding: .1rem .35rem;
                border-radius: 3px; border: 1px solid currentColor; }
.oa-move-kind.oa-out { color: #d6a44c; }
.oa-move-kind.oa-in  { color: var(--nc-primary, #4fd1c5); }
.oa-move-amt { font-weight: 600; }
.oa-move-did { font-family: var(--font-mono, ui-monospace, monospace); opacity: .6; word-break: break-all; }
.oa-move-ts  { margin-left: auto; opacity: .45; font-size: .7rem; }

.tr-card {
  flex: 1 1 150px; padding: 0.95rem 1.05rem 0.9rem 1.15rem; border-radius: 10px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.14);
  background: linear-gradient(180deg, rgba(var(--nc-primary-rgb),0.05), rgba(6,11,20,0.5));
  position: relative; overflow: hidden; transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s;
}
.tr-card::before { content:''; position:absolute; left:0; top:0; bottom:0; width:3px; background: var(--tr-accent, rgba(var(--nc-primary-rgb),0.6)); }
.tr-card:hover { border-color: rgba(var(--nc-primary-rgb),0.32); transform: translateY(-1px); box-shadow: 0 6px 20px rgba(0,0,0,0.25); }
.tr-card--liquid { --tr-accent: rgba(var(--nc-primary-rgb),0.75); }
.tr-card--raised { --tr-accent: #58a6ff; }
.tr-card--fees   { --tr-accent: #d4a72c; }
.tr-card--div    { --tr-accent: #3fb950; }
.tr-card-k { font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.12em; text-transform: uppercase; color: rgba(148,163,184,0.6); }
.tr-card-v { font-size: 1.35rem; font-weight: 700; margin-top: 0.3rem; color: rgba(226,232,240,0.95); letter-spacing: -0.01em; }
.tr-card-ccy { font-size: 0.78rem; font-weight: 500; opacity: 0.5; }

/* ══ Shared org tables — hover + header rule (§2026-06-25 polish) ══════════ */
.org-tbl thead th { border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.12); }
.org-tbl tbody tr { transition: background 0.12s; }
.org-tbl tbody tr:hover { background: rgba(var(--nc-primary-rgb),0.04); }

/* ══ Teams Grid ════════════════════════════════════════════════════════════ */
/* min() so the card yields on a phone instead of being clipped by .tab-panel */
.teams-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(300px, 100%), 1fr)); gap: 14px; }
.team-card {
  position: relative; overflow: hidden;
  background: rgba(6,11,20,0.6);
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 8px; padding: 18px 18px 18px 20px;
  transition: border-color 0.15s, background 0.15s, transform 0.15s, box-shadow 0.15s;
}
.team-card::before {
  content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 2px;
  background: rgba(var(--nc-primary-rgb),0.4); opacity: 0; transition: opacity 0.15s;
}
.team-card:hover {
  border-color: rgba(var(--nc-primary-rgb),0.28);
  background: rgba(15,29,48,0.7);
  transform: translateY(-2px);
  box-shadow: 0 8px 22px rgba(0,0,0,0.28);
}
.team-card:hover::before { opacity: 1; }
.team-card-head {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;
}
.team-name-row { display: flex; align-items: center; gap: 8px; }
.team-dot {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
}
.team-dot--default {
  background: rgba(var(--nc-primary-rgb),0.7);
  box-shadow: 0 0 6px rgba(var(--nc-primary-rgb),0.5);
  animation: pulse-dot 2s ease-in-out infinite alternate;
}
.team-dot--static { background: rgba(148,163,184,0.25); }
@keyframes pulse-dot { from { opacity: 0.6; box-shadow: 0 0 4px rgba(var(--nc-primary-rgb),0.3); } to { opacity: 1; box-shadow: 0 0 10px rgba(var(--nc-primary-rgb),0.6); } }
.team-name { font-size: 0.9rem; font-weight: 600; color: rgba(226,232,240,0.88); }
.team-members-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; color: rgba(148,163,184,0.8);
}
.team-desc { font-size: 0.8rem; color: rgba(148,163,184,0.8); margin: 0 0 6px; line-height: 1.5; }
.team-meta {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; color: rgba(148,163,184,0.8); margin-bottom: 12px;
}
.team-perms { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 14px; }
.perm-chip {
  display: inline-flex; align-items: center;
  padding: 2px 8px; border-radius: 3px; font-size: 0.6rem;
  font-family: 'IBM Plex Mono', monospace;
  border: 1px solid transparent;
}
.perm--read    { background: rgba(105,240,174,0.08); color: #69f0ae; border-color: rgba(105,240,174,0.15); }
.perm--create  { background: rgba(var(--nc-primary-rgb),0.08);  color: rgba(var(--nc-primary-rgb),0.85); border-color: rgba(var(--nc-primary-rgb),0.15); }
.perm--update  { background: rgba(255,171,64,0.08); color: #ffab40; border-color: rgba(255,171,64,0.15); }
.perm--delete  { background: rgba(255,82,82,0.08);  color: #ff5252; border-color: rgba(255,82,82,0.15); }
.perm--admin   { background: rgba(171,71,188,0.08); color: #ce93d8; border-color: rgba(171,71,188,0.15); }
.perm--default { background: rgba(255,255,255,0.04); color: rgba(148,163,184,0.5); border-color: rgba(255,255,255,0.07); }
.perm-expand-btn {
  background: none; border: 1px dashed rgba(var(--nc-primary-rgb),0.2); border-radius: 3px;
  padding: 2px 7px; font-size: 0.58rem; font-family: 'IBM Plex Mono', monospace;
  color: rgba(var(--nc-primary-rgb),0.45); cursor: pointer;
  transition: all 0.12s;
}
.perm-expand-btn:hover { border-color: rgba(var(--nc-primary-rgb),0.45); color: rgba(var(--nc-primary-rgb),0.8); }
.team-actions { display: flex; gap: 8px; padding-top: 14px; border-top: 1px solid rgba(255,255,255,0.04); }
.team-action-btn {
  padding: 5px 12px; border-radius: 4px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem;
  transition: all 0.12s; border: 1px solid transparent;
}
.team-action-btn--edit    { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.08); color: rgba(148,163,184,0.85); }
.team-action-btn--edit:hover { background: rgba(255,255,255,0.06); color: rgba(226,232,240,0.8); }
.team-action-btn--members { background: rgba(var(--nc-primary-rgb),0.06); border-color: rgba(var(--nc-primary-rgb),0.15); color: rgba(var(--nc-primary-rgb),0.7); }
.team-action-btn--members:hover { background: rgba(var(--nc-primary-rgb),0.12); color: rgba(var(--nc-primary-rgb),0.9); }
.team-action-btn--delete  { background: rgba(239,68,68,0.05); border-color: rgba(239,68,68,0.15); color: rgba(248,113,113,0.95); }
.team-action-btn--delete:hover { background: rgba(239,68,68,0.1); color: rgba(239,68,68,0.85); }

/* ══ Members Table ═════════════════════════════════════════════════════════ */
.members-table-wrap { overflow-x: auto; }
.members-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }

/* §ORGSPEND — Procurement column */
.td-procurement { white-space: nowrap; }
.proc-value {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;
  color: rgba(226, 232, 240, 0.8);
}
.proc-value--unlimited { color: rgba(148, 163, 184, 0.45); }
.proc-flag {
  font-style: normal; font-size: 0.58rem; letter-spacing: 0.06em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.6); margin-left: 5px;
  padding: 1px 5px; border-radius: 999px;
  background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
}
.proc-edit-btn { margin-left: 8px; }
.proc-editor { display: inline-flex; align-items: center; gap: 6px; }
.proc-input {
  width: 92px;
  background: rgba(6, 11, 20, 0.7);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  border-radius: 5px; padding: 4px 8px;
  color: rgba(226, 232, 240, 0.85); font-size: 0.78rem; outline: none;
}
.proc-input:focus { border-color: rgba(var(--nc-primary-rgb), 0.45); }
.proc-error { display: block; font-size: 0.68rem; color: rgba(239, 68, 68, 0.85); margin-top: 4px; white-space: normal; }
/* header + cell classes that carried no rule at all */
.th-member { min-width: 220px; }
.th-role, .th-joined { white-space: nowrap; }
/* §CHATPOLISH — §ORGSPEND added the column and not its header rule; the cell
   wrapped where its neighbours do not. */
.th-procurement { white-space: nowrap; }
.td-member { min-width: 220px; }
.member-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.members-table th {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; letter-spacing: 0.12em;
  color: rgba(148,163,184,0.3);
  padding: 8px 14px; text-align: left;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.07);
}
.th-actions { width: 160px; }
.member-row { transition: background 0.1s; }
.member-row td { padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,0.03); }
/* §pass50.1 — click affordance on member rows */
.member-row--clickable { cursor: pointer; }
.member-row--clickable:hover { background: rgba(var(--nc-primary-rgb), 0.06); }
/* §pass50.1 — click affordance on agent cards */
.agent-card--clickable { cursor: pointer; transition: border-color 0.15s, transform 0.05s; }
.agent-card--clickable:hover { border-color: rgba(var(--nc-primary-rgb), 0.55); transform: translateY(-1px); }
.agent-card-cta {
  margin-top: 8px;
  font-size: 10px;
  letter-spacing: 0.08em;
  color: rgba(var(--nc-primary-rgb), 0.6);
  text-transform: uppercase;
  font-weight: 600;
}
.agent-card--clickable:hover .agent-card-cta { color: var(--nc-primary); }

/* §ORGLIFE T2/T4 — the teams tab's honest line, and the roster on each card. */
.teams-note {
  margin: 0 0 12px; font-size: 9px; line-height: 1.45;
  color: rgba(var(--nc-primary-rgb), 0.85); max-width: 68ch;
}
.team-roster {
  display: flex; flex-wrap: wrap; gap: 4px; margin: 6px 0 4px;
}
.roster-name {
  font-size: 9px; padding: 1px 6px; border-radius: 8px;
  background: rgba(var(--nc-primary-rgb), 0.08);
  color: rgba(var(--nc-primary-rgb), 0.75);
  max-width: 18ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.roster-more { font-size: 9px; color: rgba(var(--nc-primary-rgb), 0.45); align-self: center; }

/* §ORGLIFE L2 — the two states an assigned agent can be in that nothing used to show.
   Quiet by construction: these sit under the DID on a card whose job is CI/CD, so they
   read as annotations, not as an alarm. (.ost-hosting shipped with markup and NO rule
   anywhere and rendered full-bleed body-size — every new class here is scanned.) */
.ag-orphan {
  display: flex; align-items: center; gap: 5px;
  margin-top: 6px; font-size: 9px; line-height: 1.35;
  color: var(--nc-warning);
  opacity: 0.92;
}
.ag-orphan-mark { font-size: 10px; opacity: 0.9; flex: none; }
.ag-auth {
  margin-top: 4px; font-size: 9px; letter-spacing: 0.04em;
  text-transform: uppercase; font-weight: 600;
}
.ag-auth--live { color: rgba(var(--nc-primary-rgb), 0.72); }
.ag-auth--revoked { color: rgba(var(--nc-primary-rgb), 0.38); text-decoration: line-through; }

/* §pass50.1 — Member detail right-side drawer */
.md-drawer {
  position: fixed; inset: 0; z-index: 10050; display: flex; justify-content: flex-end;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}
.md-drawer__scrim { position: absolute; inset: 0; background: rgba(0,0,0,0.55); backdrop-filter: blur(3px); }
.md-drawer__panel {
  position: relative; width: min(380px, 92vw); height: 100vh;
  background: #0c1320; border-left: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  display: flex; flex-direction: column;
  box-shadow: -10px 0 40px rgba(0,0,0,0.6);
}
.md-drawer__head {
  display: grid; grid-template-columns: 48px 1fr auto; gap: 12px; align-items: center;
  padding: 18px 18px 14px; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12);
}
.md-drawer__avatar {
  width: 48px; height: 48px; border-radius: 8px; display: grid; place-items: center;
  font-weight: 700; font-size: 18px; color: #e8eaed;
}
.md-drawer__name { font-size: 14px; font-weight: 700; color: #e8eaed; }
.md-you { color: rgba(var(--nc-primary-rgb), 0.7); font-size: 11px; font-weight: 500; }
.md-drawer__email { font-size: 11px; color: #6b7785; margin-top: 2px; }
.md-drawer__close {
  background: transparent; border: none; color: #6b7785; font-size: 22px; cursor: pointer;
  width: 32px; height: 32px; display: grid; place-items: center; border-radius: 4px;
}
.md-drawer__close:hover { background: rgba(255,68,68,0.1); color: #ff4444; }
.md-drawer__body { padding: 18px; display: flex; flex-direction: column; gap: 14px; flex: 1; overflow-y: auto; }
.md-drawer__row { display: flex; flex-direction: column; gap: 4px; }
.md-drawer__row-label {
  font-size: 9.5px; letter-spacing: 0.16em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.55); font-weight: 700;
}
.md-drawer__row-value { font-size: 13px; color: #c8d8e8; }
.md-drawer__row-value code {
  background: rgba(255,255,255,0.04); padding: 2px 6px; border-radius: 3px;
  font-size: 12px; color: #b0c0d0;
}
.md-drawer__foot {
  display: flex; gap: 8px; justify-content: flex-end; flex-wrap: wrap;
  padding: 14px 18px; border-top: 1px solid rgba(var(--nc-primary-rgb), 0.12);
}
.cmd-btn--ghost {
  background: transparent; border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  color: rgba(var(--nc-primary-rgb), 0.7);
}
.cmd-btn--ghost:hover { color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb), 0.55); }

.md-drawer-enter-active, .md-drawer-leave-active { transition: opacity 0.18s; }
.md-drawer-enter-from, .md-drawer-leave-to { opacity: 0; }
.md-drawer-enter-active .md-drawer__panel, .md-drawer-leave-active .md-drawer__panel {
  transition: transform 0.22s ease;
}
.md-drawer-enter-from .md-drawer__panel, .md-drawer-leave-to .md-drawer__panel {
  transform: translateX(100%);
}
/* ══ §ORGPOCKET O3 — PHONE (measured, not guessed) ═════════════════════════
   There was no width media query in this view. At 390px: the org name painted
   19x28px UNDER the EDIT button, the name column collapsed to 97px so the
   description rendered one word per line, and .cmd-controls (the org selector,
   the only way to switch orgs) ran 210px past the viewport. Desktop measured
   clean at 1440 and is deliberately untouched. */
@media (max-width: 720px) {
  .cmd-bar { flex-wrap: wrap; gap: 10px; padding: 14px 16px 12px; }
  .cmd-controls { flex-wrap: wrap; width: 100%; gap: 8px; }
  .org-selector-wrap { flex: 1 1 auto; min-width: 0; }
  .org-selector { max-width: 100%; }
  .org-content { padding: 18px 16px; }
  .identity-panel { padding: 18px 16px; }
  /* stack: the actions go BELOW the name instead of riding over it */
  .identity-main { flex-direction: column; align-items: stretch; margin-bottom: 18px; }
  .identity-actions { margin-left: 0; margin-top: 14px; flex-wrap: wrap; }
  .identity-name { font-size: 1.25rem; overflow-wrap: anywhere; }
  .identity-slug, .identity-website { overflow-wrap: anywhere; max-width: 100%; }
  .capacity-row { grid-template-columns: 1fr; gap: 10px; }
  .tab-body { padding: 18px 16px; }
  .tab-btn { padding: 12px 14px; }
}

@media (prefers-reduced-motion: reduce) {
  .md-drawer-enter-active, .md-drawer-leave-active,
  .md-drawer-enter-active .md-drawer__panel, .md-drawer-leave-active .md-drawer__panel { transition: none; }
}
.member-row:hover td { background: rgba(var(--nc-primary-rgb),0.025); }
.member-row--self td { background: rgba(var(--nc-primary-rgb),0.03); }
.member-row--owner td:first-child { position: relative; }
.member-identity { display: flex; align-items: center; gap: 12px; }
.member-avatar {
  width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem; font-weight: 700;
}
.member-name {
  font-size: 0.875rem; font-weight: 500; color: rgba(226,232,240,0.85);
  display: flex; align-items: center; gap: 8px;
}
.member-email { font-size: 0.72rem; color: rgba(148,163,184,0.4); margin-top: 2px; }
.you-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.55rem; font-weight: 700; letter-spacing: 0.08em;
  padding: 1px 6px; border-radius: 3px;
  background: rgba(var(--nc-primary-rgb),0.1); color: rgba(var(--nc-primary-rgb),0.7);
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
}
.td-role, .td-joined, .td-member-actions { vertical-align: middle; }
.td-joined {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem; color: rgba(148,163,184,0.35);
}
.td-member-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.member-action-btn {
  padding: 4px 10px; border-radius: 4px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem;
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
  color: rgba(148,163,184,0.6); transition: all 0.12s;
}
.member-action-btn:hover { background: rgba(255,255,255,0.06); color: rgba(226,232,240,0.8); }
.member-action-btn--danger { border-color: rgba(239,68,68,0.15); color: rgba(239,68,68,0.55); }
.member-action-btn--danger:hover { background: rgba(239,68,68,0.08); color: rgba(239,68,68,0.85); }
.owner-lock { display: flex; align-items: center; color: rgba(255,215,0,0.2); }

/* ══ Agents Tab ════════════════════════════════════════════════════════════ */
.agents-context-note {
  display: flex; align-items: flex-start; gap: 8px;
  background: rgba(var(--nc-primary-rgb),0.04);
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 6px; padding: 10px 14px;
  font-size: 0.75rem; color: rgba(148,163,184,0.5);
  line-height: 1.5; margin-bottom: 20px;
}
.note-icon { flex-shrink: 0; margin-top: 2px; color: rgba(var(--nc-primary-rgb),0.4); }
.agents-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.agent-card {
  background: rgba(6,11,20,0.6);
  border: 1px solid rgba(var(--nc-primary-rgb),0.09);
  border-radius: 8px; padding: 16px;
  cursor: pointer; transition: all 0.15s;
}
.agent-card:hover {
  border-color: rgba(var(--nc-primary-rgb),0.25);
  background: rgba(15,29,48,0.7);
  transform: translateY(-1px);
}
.agent-card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.agent-status-row { display: flex; align-items: center; gap: 7px; }
.agent-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.agent-dot--active { background: rgba(105,240,174,0.8); box-shadow: 0 0 5px rgba(105,240,174,0.4); }
.agent-dot--inactive { background: rgba(148,163,184,0.2); }
.agent-name { font-size: 0.85rem; font-weight: 600; color: rgba(226,232,240,0.88); }
.agent-did {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; color: rgba(148,163,184,0.25);
  margin-bottom: 12px; word-break: break-all;
}
.agent-financials { display: flex; gap: 16px; }
.agent-fin-item { display: flex; flex-direction: column; gap: 2px; }
.fin-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.55rem; letter-spacing: 0.1em; color: rgba(148,163,184,0.3); }
.fin-value { font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem; font-weight: 600; }
.fin-value--liquid { color: rgba(var(--nc-primary-rgb),0.8); }
.fin-value--staked { color: rgba(99,179,237,0.7); }
/* Rep badges */
.rep-badge {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.55rem; font-weight: 700;
  padding: 2px 7px; border-radius: 3px; letter-spacing: 0.08em;
}
.rep--sovereign { background: rgba(224,64,251,0.1); color: #e040fb; border: 1px solid rgba(224,64,251,0.2); }
.rep--platinum  { background: rgba(176,190,197,0.1); color: #b0bec5; border: 1px solid rgba(176,190,197,0.2); }
.rep--gold      { background: rgba(255,215,0,0.1);   color: #ffd700; border: 1px solid rgba(255,215,0,0.2); }
.rep--silver    { background: rgba(148,163,184,0.1); color: #94a3b8; border: 1px solid rgba(148,163,184,0.2); }
.rep--bronze    { background: rgba(205,127,50,0.1);  color: #cd7f32; border: 1px solid rgba(205,127,50,0.2); }
.rep--unranked  { background: rgba(255,255,255,0.04); color: rgba(148,163,184,0.4); border: 1px solid rgba(255,255,255,0.07); }

/* ══ Settings Tab ══════════════════════════════════════════════════════════ */
.settings-section { margin-bottom: 32px; }
.settings-section-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; font-weight: 700; letter-spacing: 0.15em;
  color: rgba(var(--nc-primary-rgb),0.9); margin: 0 0 18px;
}
.settings-form { display: flex; flex-direction: column; gap: 16px; max-width: 560px; }
.form-field { display: flex; flex-direction: column; gap: 6px; }
.form-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; font-weight: 700; letter-spacing: 0.1em;
  color: rgba(148,163,184,0.8);
}
.form-label-note { font-weight: 400; color: rgba(148,163,184,0.8); }
.form-input {
  background: rgba(6,11,20,0.7);
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 6px; padding: 9px 12px;
  color: rgba(226,232,240,0.85); font-size: 0.85rem; outline: none;
  transition: border-color 0.15s;
}
.form-input:focus { border-color: rgba(var(--nc-primary-rgb),0.38); }
.form-textarea { resize: vertical; min-height: 80px; font-family: inherit; }
.form-readonly {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem; color: rgba(148,163,184,0.8);
  padding: 9px 12px;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 6px;
}
.settings-save-row { display: flex; justify-content: flex-end; }

/* Danger Zone */
.danger-zone {
  background: rgba(239,68,68,0.04);
  border: 1px solid rgba(239,68,68,0.18);
  border-radius: 8px; padding: 22px 24px;
}
.danger-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; font-weight: 700; letter-spacing: 0.14em;
  color: rgba(248,113,113,0.95); margin: 0 0 10px;
}
.danger-body { font-size: 0.82rem; color: rgba(148,163,184,0.85); line-height: 1.6; margin: 0 0 16px; }
.danger-btn {
  padding: 8px 20px; border-radius: 6px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; font-weight: 700; letter-spacing: 0.1em;
  background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.28); color: rgba(248,113,113,0.95);
  transition: all 0.15s;
}
.danger-btn:hover { background: rgba(239,68,68,0.15); border-color: rgba(239,68,68,0.5); color: rgba(239,68,68,0.95); }
.danger-btn:disabled { opacity: 0.45; cursor: not-allowed; }

/* E1b — deletion-blocked checklist + inline sweep rail */
.delete-blockers {
  margin-top: 16px; padding: 14px 16px; border-radius: 8px;
  background: rgba(251,191,36,0.05); border: 1px solid rgba(251,191,36,0.25);
}
.delete-blockers-title {
  margin: 0 0 8px; font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  color: rgba(251,191,36,0.85);
}
.delete-blockers-list { margin: 0 0 4px; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.delete-blocker { display: flex; flex-wrap: wrap; gap: 4px 10px; align-items: baseline; font-size: 0.8rem; color: rgba(226,232,240,0.85); }
.delete-blocker .mono { font-family: 'IBM Plex Mono', monospace; }
.delete-blocker-action { font-size: 0.72rem; color: rgba(148,163,184,0.6); }
.sweep-form { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.sweep-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.sweep-row .form-input { flex: 1 1 280px; min-width: 0; }

/* §CHATDESK H1.1 — the firm chip under the org name */
.identity-tr { display: inline-flex; align-items: center; gap: 6px; margin-top: 6px;
  font-size: .8rem; color: var(--text-secondary, #9ab); }
.identity-tr .tr-star { color: #e8b33d; }
</style>
