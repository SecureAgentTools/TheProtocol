<script setup lang="ts">
import { escapeHtml } from '@/utils/escapeHtml'
import { appLocale } from '@/services/appLocale'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ref, computed, onMounted, watch, defineAsyncComponent } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
dayjs.extend(relativeTime)
import { useAgentStore } from '@/stores/agents'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { apiClient } from '@/services/api/client'
import { exchangeService, type EquityChip } from '@/services/api/exchangeService'
import { useI18n } from '@/composables/useI18n'
import { isWalletAgent } from '@/services/walletAgent'
import { useCurrency } from '@/composables/useCurrency'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import PaymentTokensPanel from '@/components/myagents/PaymentTokensPanel.vue'
import StatementPanel from '@/components/myagents/StatementPanel.vue'
import FlareBadge from '@/components/common/FlareBadge.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'

const AddCredentialsModal = defineAsyncComponent(() =>
  import('@/components/common/AddCredentialsModal.vue'),
)
const BulkCredentialsImportModal = defineAsyncComponent(() =>
  import('@/components/common/BulkCredentialsImportModal.vue'),
)

const router = useRouter()
const route = useRoute()
const agentStore = useAgentStore()
const authStore = useAuthStore()
const uiStore = useUIStore()
const { t, tp } = useI18n()
// FX multi-currency: own-agent balances/funding are in THIS registry's currency
// (AVT on Frame A/B, BVT on Frame C). The ◎/◉ glyphs are currency-neutral
// liquid/staked marks; only explicit currency labels need localCurrency. §17.5.
const { localCurrency } = useCurrency()

// ── View State ──────────────────────────────────────────────────────────────
const viewMode = ref<'grid' | 'list'>('grid')
// §28 polish (2026-05-15) — Card-mode: customize (flare pickers visible)
// vs details (no flare pickers, leaner agent-meta view). Persisted across
// reloads via localStorage so Commander's preference sticks.
const cardMode = ref<'customize' | 'details'>(
  (typeof localStorage !== 'undefined' && (localStorage.getItem('myAgents:cardMode') as any)) || 'customize'
)
watch(cardMode, v => { try { localStorage.setItem('myAgents:cardMode', v) } catch {} })

// §28 polish 2 (2026-05-15) — Per-card collapse override. Even when the
// global mode is 'customize', individual cards can hide their flare-rows
// via the chevron in the card header. State is a Set of DIDs persisted to
// localStorage so toggles survive reloads.
const _initialCollapsed = (() => {
  try { return new Set<string>(JSON.parse(localStorage.getItem('myAgents:collapsedCards') || '[]')) } catch { return new Set<string>() }
})()
const collapsedCards = ref<Set<string>>(_initialCollapsed)
function isCardFlareVisible(did: string): boolean {
  return cardMode.value === 'customize' && !collapsedCards.value.has(did)
}
function toggleCardFlare(did: string) {
  const s = new Set(collapsedCards.value)
  if (s.has(did)) s.delete(did); else s.add(did)
  collapsedCards.value = s
  try { localStorage.setItem('myAgents:collapsedCards', JSON.stringify(Array.from(s))) } catch {}
}
const searchQuery = ref('')
const statusFilter = ref('')
// §agentdeclutter — hide spawned HANDS (server-side top_level_only) so real agents
// surface. Default ON because for sim/forge fixture owners the newest 500 (the page
// window) are almost all hands, burying real agents outside the window entirely.
const hideSubAgents = ref(true)
const sortBy = ref<'name' | 'balance' | 'reputation' | 'activity'>('balance')
const showDeleteDialog = ref(false)
const agentToDelete = ref<any>(null)
const copiedDid = ref<string | null>(null)

// §15 — per-agent encirclement variant picker (shadow_chancellor agents only).
// Holds the DID of the agent currently being saved so we can disable its
// pill row during the round-trip + show subtle loading state.
const agentVariantSaving = ref<string | null>(null)

// §26 (2026-05-13) — single source of truth for the per-agent variant pill
// list. Keep in sync with backend ENCIRCLEMENT_VARIANTS + frontend
// FlareEncirclement VARIANTS map + FlareManager ENCIRCLEMENT_VARIANTS array.
// §28 (2026-05-13) — glitch / cascade / panic moved to AGENT_OVERLAY_PILLS
// (independent axis).
const AGENT_VARIANT_PILLS = [
  'sauron', 'goth', 'obsidian', 'void',
  'aurora', 'phoenix', 'crystal',
  'blackhole', 'halloween',
  'inferno', 'glacier', 'matrix',
  'galaxy', 'ink', 'circuit',
  'yule', 'sakura', 'solstice', 'harvest',
] as const

// §28 (2026-05-13) — per-agent overlay pills. Independent axis: sits on top
// of any base variant. §29 ships panic-a/b/c tournament-round designs.
const AGENT_OVERLAY_PILLS = [
  'glitch', 'cascade',
  'panic-a', 'panic-b', 'panic-c',
] as const
const agentOverlaySaving = ref<string | null>(null)

// §21 (2026-05-13) — flare-move state. Mirrors FlareManager's moveTo flow:
// allows Commander to move their dev flare directly from MyAgents instead
// of context-switching to /my-flare. The dev's flare ends up on the picked
// agent; the previous bearer (if any) gets cleared.
const flareMoving = ref<string | null>(null)
const flareMoveError = ref<string>('')

async function moveFlareToAgent(agent: any) {
  if (flareMoving.value) return
  if (!authStore.user?.flare_tier) {
    flareMoveError.value = t('myAgentsView.errors.noFlare', 'You don\'t have a backer flare yet.')
    return
  }
  flareMoving.value = agent.did
  flareMoveError.value = ''
  try {
    const r = await apiClient.post(
      `/fiat/flare/move/${encodeURIComponent(agent.did)}`,
    )
    const data = r.data || {}
    // Patch local agents in-place so the bearer pill jumps without a full reload
    if (agentStore.agents) {
      for (const a of agentStore.agents as any[]) {
        if (a.did === data.moved_to_did) {
          a.flare_tier = data.flare_tier
          a.flare_granted_at = data.flare_granted_at
          a.flare_encirclement_variant = a.flare_encirclement_variant || 'sauron'
          a.bears_corner_flare = true
          a.bears_encirclement_flare = true
          a.selected_corner_flare       = (authStore.user as any)?.selected_corner_flare ?? null
          a.selected_encirclement_flare = (authStore.user as any)?.selected_encirclement_flare ?? null
        } else if (data.moved_from_did && a.did === data.moved_from_did) {
          a.flare_tier = null
          a.flare_granted_at = null
          a.flare_encirclement_variant = null
          a.bears_corner_flare = false
          a.bears_encirclement_flare = false
          a.selected_corner_flare = null
          a.selected_encirclement_flare = null
        }
      }
    }
  } catch (e: any) {
    flareMoveError.value = e?.response?.data?.detail || e?.message || t('myAgentsView.errors.moveFlareFailed', 'Failed to move flare.')
  } finally {
    flareMoving.value = null
  }
}

// §23 (2026-05-14) — Per-slot quick-equip on agent cards.
// Each slot is independently equip-able to any of the dev's agents. Same
// agent can bear both. Server enforces single-bearer-per-slot.
const slotEquipping = ref<{ slot: 'corner' | 'encirclement'; did: string } | null>(null)
const slotEquipError = ref<string>('')

function canEquipSlot(slot: 'corner' | 'encirclement'): boolean {
  if (slot === 'corner') return !!(authStore.user as any)?.selected_corner_flare
  if (slot === 'encirclement') return !!(authStore.user as any)?.selected_encirclement_flare
  return false
}

async function equipSlotOnAgent(slot: 'corner' | 'encirclement', agent: any) {
  if (slotEquipping.value) return
  if (!canEquipSlot(slot)) {
    slotEquipError.value = slot === 'corner'
      ? t('myAgentsView.errors.noCornerSelected', 'No corner badge selected. Visit Flare Manager to pick one first.')
      : t('myAgentsView.errors.noEncirclementSelected', 'No encirclement selected. Visit Flare Manager to pick one first.')
    return
  }
  slotEquipping.value = { slot, did: agent.did }
  slotEquipError.value = ''
  try {
    const r = await apiClient.post(
      `/fiat/flare/equip/${slot}/${encodeURIComponent(agent.did)}`,
    )
    const data = r.data || {}
    // Mutate local state — clear slot from siblings, set on target.
    if (agentStore.agents) {
      const devCorner = (authStore.user as any)?.selected_corner_flare ?? null
      const devEnc    = (authStore.user as any)?.selected_encirclement_flare ?? null
      for (const a of agentStore.agents as any[]) {
        if (a.did === agent.did) {
          if (slot === 'corner') {
            a.bears_corner_flare = true
            a.selected_corner_flare = devCorner
          } else {
            a.bears_encirclement_flare = true
            a.selected_encirclement_flare = devEnc
          }
          // Keep legacy flare_tier consistent for renderers that still read it.
          a.flare_tier = a.flare_tier || (authStore.user as any)?.flare_tier || null
        } else {
          // Clear the moved-from slot on siblings (single-bearer invariant)
          if (slot === 'corner' && a.bears_corner_flare) {
            a.bears_corner_flare = false
            a.selected_corner_flare = null
            if (!a.bears_encirclement_flare) {
              a.flare_tier = null
              a.flare_granted_at = null
            }
          }
          if (slot === 'encirclement' && a.bears_encirclement_flare) {
            a.bears_encirclement_flare = false
            a.selected_encirclement_flare = null
            if (!a.bears_corner_flare) {
              a.flare_tier = null
              a.flare_granted_at = null
            }
          }
        }
      }
    }
    void data
  } catch (e: any) {
    slotEquipError.value = e?.response?.data?.detail || e?.message || `Failed to equip ${slot}.`
  } finally {
    slotEquipping.value = null
  }
}

async function unequipSlotFromAgent(slot: 'corner' | 'encirclement', agent: any) {
  if (slotEquipping.value) return
  slotEquipping.value = { slot, did: agent.did }
  slotEquipError.value = ''
  try {
    await apiClient.post(
      `/fiat/flare/unequip/${slot}/${encodeURIComponent(agent.did)}`,
    )
    if (agentStore.agents) {
      for (const a of agentStore.agents as any[]) {
        if (a.did !== agent.did) continue
        if (slot === 'corner') {
          a.bears_corner_flare = false
          a.selected_corner_flare = null
        } else {
          a.bears_encirclement_flare = false
          a.selected_encirclement_flare = null
        }
        if (!a.bears_corner_flare && !a.bears_encirclement_flare) {
          a.flare_tier = null
          a.flare_granted_at = null
        }
      }
    }
  } catch (e: any) {
    slotEquipError.value = e?.response?.data?.detail || e?.message || `Failed to unequip ${slot}.`
  } finally {
    slotEquipping.value = null
  }
}

// §23 — Per-agent admin corner-badge variant (admin-only).
const cornerVariantSaving = ref<string | null>(null)
const ADMIN_CORNER_VARIANTS = ['rocket', 'crown', 'vault', 'gavel', 'atom', 'network'] as const
type AdminCornerVariant = typeof ADMIN_CORNER_VARIANTS[number]

function isAdminUser(): boolean {
  const u = authStore.user as any
  if (!u) return false
  return !!(u.is_admin || u.admin_treasury || u.admin_support ||
            u.admin_enforcement || u.admin_federation || u.admin_platform)
}

async function setAgentCornerVariant(agent: any, variant: AdminCornerVariant | null) {
  if (cornerVariantSaving.value) return
  if (agent.flare_corner_variant === variant) return
  cornerVariantSaving.value = agent.did
  try {
    const r = await apiClient.patch(
      `/fiat/flare/agent/${encodeURIComponent(agent.did)}/corner-variant`,
      { variant: variant === null ? '__clear__' : variant },
    )
    // §24 — mirror server's single-occupancy enforcement locally
    if (variant !== null && agentStore.agents) {
      for (const other of agentStore.agents as any[]) {
        if (other.did === agent.did) continue
        if (other.flare_corner_variant === variant) {
          other.flare_corner_variant = null
        }
      }
    }
    agent.flare_corner_variant = r.data?.flare_corner_variant ?? null
  } catch (e: any) {
    console.error('[MyAgents] setAgentCornerVariant failed:', e?.response?.data?.detail || e?.message)
  } finally {
    cornerVariantSaving.value = null
  }
}

async function clearAgentVariant(agent: any) {
  // Quick "back to default Sauron" action — used when an agent's variant
  // is stuck on something the dev wants to reset. Mirrors setAgentVariant
  // but goes back to the default explicitly.
  return setAgentVariant(agent, 'sauron')
}

async function setAgentVariant(
  agent: any,
  variant:
    | 'sauron' | 'goth' | 'obsidian' | 'void'
    | 'aurora' | 'phoenix' | 'crystal'
    | 'blackhole' | 'halloween'
    | 'inferno' | 'glacier' | 'matrix'
    | 'galaxy' | 'ink' | 'circuit'
    | 'yule' | 'sakura' | 'solstice' | 'harvest'
    | null,
) {
  if (agentVariantSaving.value) return
  if ((agent.flare_encirclement_variant || null) === variant) return  // no-op
  agentVariantSaving.value = agent.did
  try {
    const r = await apiClient.patch(
      `/fiat/flare/agent/${encodeURIComponent(agent.did)}/variant`,
      { variant: variant === null ? '__clear__' : variant },
    )
    // §24 (2026-05-14) — Server enforces single-occupancy per variant: when
    // we set X on THIS agent, the server clears X from any other agent of
    // the dev. Mirror that locally so the picker rows on other cards update
    // without a refetch.
    if (agentStore.agents) {
      for (const other of agentStore.agents as any[]) {
        if (other.did === agent.did) continue
        if (other.flare_encirclement_variant === variant) {
          other.flare_encirclement_variant = null
        }
      }
    }
    agent.flare_encirclement_variant = r.data?.flare_encirclement_variant ?? variant
  } catch (e: any) {
    console.error('[MyAgents] setAgentVariant failed:', e?.response?.data?.detail || e?.message)
  } finally {
    agentVariantSaving.value = null
  }
}

// §28 (2026-05-13) — Per-agent OVERLAY setter. Independent axis (composes on
// top of any base variant). Server enforces ownership + bearer gate.
async function switchAgentOverlay(
  agent: any,
  overlay:
    | 'glitch' | 'cascade'
    | 'panic-a' | 'panic-b' | 'panic-c'
    | null,
) {
  if (agentOverlaySaving.value) return
  if ((agent.flare_encirclement_overlay || null) === overlay) return  // no-op
  agentOverlaySaving.value = agent.did
  try {
    const r = await apiClient.patch(
      `/fiat/flare/agent/${encodeURIComponent(agent.did)}/overlay`,
      { overlay: overlay === null ? '__clear__' : overlay },
    )
    agent.flare_encirclement_overlay = r.data?.flare_encirclement_overlay ?? overlay
  } catch (e: any) {
    console.error('[MyAgents] switchAgentOverlay failed:', e?.response?.data?.detail || e?.message)
  } finally {
    agentOverlaySaving.value = null
  }
}

// §24 (2026-05-14) — Fleet-wide variant occupancy map. Lets each agent
// card's STYLE picker show "→ AGENT_X" hint on a pill that's currently
// equipped on a different agent of the same dev. Clicking will MOVE the
// variant (server enforces single-occupancy per variant).
const variantOwnerByEnc = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const a of (agentStore.agents || []) as any[]) {
    if (a.flare_encirclement_variant) {
      out[a.flare_encirclement_variant] = a.name || a.did || 'agent'
    }
  }
  return out
})

const variantOwnerByCorner = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const a of (agentStore.agents || []) as any[]) {
    if (a.flare_corner_variant) {
      out[a.flare_corner_variant] = a.name || a.did || 'agent'
    }
  }
  return out
})

// Helpers for the template — return "→ AGENT_NAME" string when the variant
// is currently equipped on a DIFFERENT agent than the one being rendered.
function variantHint(variant: string, currentAgent: any): string {
  const owner = variantOwnerByEnc.value[variant]
  if (!owner) return ''
  const currentName = currentAgent?.name || currentAgent?.did
  if (owner === currentName) return ''
  return owner
}

function cornerVariantHint(variant: string, currentAgent: any): string {
  const owner = variantOwnerByCorner.value[variant]
  if (!owner) return ''
  const currentName = currentAgent?.name || currentAgent?.did
  if (owner === currentName) return ''
  return owner
}

// ── Per-agent Avatar Edit (§15.4, 2026-05-13) ──────────────────────────────
// Each row can edit its iconUrl (lives inside the agent_card.card_data) via
// PUT /agent-cards/{did}. The avatar URL is then passed to UserAvatar as
// :avatar-url so the agent's flare composition pops with imagery instead
// of falling back to initials.
const avatarEditingDid = ref<string | null>(null)
const avatarEditingValue = ref('')
const avatarSavingDid = ref<string | null>(null)
const avatarErrorByDid = ref<Record<string, string>>({})

function openAvatarEditor(agent: any) {
  avatarEditingDid.value = agent.did
  avatarEditingValue.value = agent.card_data?.iconUrl || agent.card_data?.icon_url || ''
  avatarErrorByDid.value = { ...avatarErrorByDid.value, [agent.did]: '' }
}

function cancelAvatarEditor() {
  avatarEditingDid.value = null
  avatarEditingValue.value = ''
}

function truncMid(s: string, head = 14, tail = 8): string {
  if (!s || s.length <= head + tail + 1) return s
  return `${s.slice(0, head)}…${s.slice(-tail)}`
}

async function saveAgentAvatar(agent: any) {
  if (avatarSavingDid.value) return
  const trimmed = avatarEditingValue.value.trim()
  // Allow empty string → clears icon. Validate http(s) URL otherwise.
  if (trimmed && !/^https?:\/\//i.test(trimmed)) {
    avatarErrorByDid.value = { ...avatarErrorByDid.value, [agent.did]: 'URL must start with http:// or https://' }
    return
  }
  avatarSavingDid.value = agent.did
  avatarErrorByDid.value = { ...avatarErrorByDid.value, [agent.did]: '' }
  try {
    // Build the updated card_data preserving everything else
    const nextCardData = { ...(agent.card_data || {}), iconUrl: trimmed || null }
    // PUT /agent-cards/{did} — endpoint resolves by DID per _resolve_agent_card
    const r = await apiClient.put(
      `/agent-cards/${encodeURIComponent(agent.did)}`,
      { card_data: nextCardData },
    )
    // Patch the agent in-place so the UserAvatar above re-renders the icon
    if (r.data?.card_data) {
      agent.card_data = r.data.card_data
    } else {
      agent.card_data = nextCardData
    }
    cancelAvatarEditor()
  } catch (e: any) {
    const msg = e?.response?.data?.detail || e?.response?.data?.error?.detail || e?.message || t('myAgentsView.errors.saveAvatarFailed', 'Failed to save avatar.')
    avatarErrorByDid.value = { ...avatarErrorByDid.value, [agent.did]: msg }
  } finally {
    avatarSavingDid.value = null
  }
}

// ── Funding Request State ───────────────────────────────────────────────────
const showFundingModal = ref(false)
/** §ONBOARDQOL P2 — the funding DOOR (`?fund=1`). Consumed then scrubbed like ?reset=.
 *  ⚠ Answered from onMounted AND from a watcher: vue-router REUSES this component when
 *  only the query changes (the §ORGJOIN lesson), so a door opened while already on this
 *  view would otherwise do nothing — measured: the URL kept ?fund=1 and no modal came. */
function openFundingDoor() {
  router.replace({ name: 'my-agents', query: {} }).catch(() => {})
  selectedFundingAgentDid.value = authStore.activeAgent?.did || ''
  fundingError.value = null
  showFundingModal.value = true
}
watch(() => route.query.fund, (v) => { if (String(v || '')) openFundingDoor() })
const fundingAmount = ref<number>(1000)
const fundingReason = ref('')
const fundingSubmitting = ref(false)
const fundingError = ref<string | null>(null)
const showFundingHistory = ref(false)
const fundingRequests = ref<any[]>([])
const fundingHistoryLoading = ref(false)
// §FESUITE (2026-10-05): a failed history read said "No funding requests yet" (and counted 0) under a warning toast; it
// says the read failed in place now, with Try again. A failed refresh (after a request) keeps the list that was shown.
const fundingHistoryFailed = ref(false)
let fundingHistoryOk = false
const selectedFundingAgentDid = ref<string>('')
const fundingAgentSwitching = ref(false)

// ── Reset Credentials State ─────────────────────────────────────────────────
const showResetDialog = ref(false)
const showCredentialsDialog = ref(false)
const agentToReset = ref<any>(null)
const resetPassword = ref('')
const resetLoading = ref(false)
const resetError = ref('')
const newCredentials = ref<{client_id: string, client_secret: string} | null>(null)
const copiedField = ref('')

// ── Local-credentials Add/Import State ──────────────────────────────────────
const showAddCredentials = ref(false)
const agentForAddCreds = ref<any>(null)
const showBulkImport = ref(false)
const credsRefreshTick = ref(0) // bump to re-evaluate hasLocalCreds in template

function hasLocalCreds(did: string): boolean {
  // credsRefreshTick is read here so the computed re-runs when modals close.
  void credsRefreshTick.value
  return agentCredentialsStore.hasCredentials(did)
}

function openAddCredentials(agent: any) {
  agentForAddCreds.value = { did: agent.did, name: agentName(agent) }
  showAddCredentials.value = true
}

function handleAddCredsSaved() {
  showAddCredentials.value = false
  agentForAddCreds.value = null
  credsRefreshTick.value += 1
  authStore.fetchAvailableAgents({ force: true })
}

function handleBulkImported(_n: number) {
  showBulkImport.value = false
  credsRefreshTick.value += 1
  authStore.fetchAvailableAgents({ force: true })
}

// ── Data ─────────────────────────────────────────────────────────────────────
const agents = computed(() => agentStore.agents || [])
const fleetUnread = computed(() => agentStore.myAgentsFailed && agents.value.length === 0)

const filteredAgents = computed(() => {
  let list = [...agents.value]
  if (searchQuery.value.trim()) {
    const q = searchQuery.value.toLowerCase()
    list = list.filter(a =>
      (a.name || '').toLowerCase().includes(q) ||
      (a.did || '').toLowerCase().includes(q) ||
      (a.card_data?.humanReadableId || '').toLowerCase().includes(q) ||
      (a.description || '').toLowerCase().includes(q) ||
      // §CAPSEARCH (2026-09-01) — this box's placeholder promises "name, DID, or
      // capability" and the predicate above never looked at a capability. The same
      // blank promise he reported for DIDs on Agent Discovery, one page over.
      // ⚠ `skills` is NOT reliably an array (measured server-side: JSON-null on
      // 12,122 of 15,252 cards), so Array.isArray guards it — .some() on a null
      // throws and would blank the whole list, not just skip this row.
      (Array.isArray(a.card_data?.skills) && a.card_data.skills.some((sk: any) =>
        ((sk?.name || '') + ' ' + (sk?.description || '')).toLowerCase().includes(q)
      ))
    )
  }
  if (statusFilter.value) {
    list = list.filter(a => a.status === statusFilter.value)
  }
  list.sort((a, b) => {
    switch (sortBy.value) {
      case 'balance':
        return (Number(b.liquid_balance || 0) + Number(b.staked_balance || 0)) -
               (Number(a.liquid_balance || 0) + Number(a.staked_balance || 0))
      case 'reputation':
        return (b.reputation_score || 0) - (a.reputation_score || 0)
      case 'activity':
        if (!a.last_active_at && !b.last_active_at) return 0
        if (!a.last_active_at) return 1
        if (!b.last_active_at) return -1
        return new Date(b.last_active_at).getTime() - new Date(a.last_active_at).getTime()
      case 'name':
      default:
        return agentName(a).localeCompare(agentName(b))
    }
  })
  return list
})

const namedAgents = computed(() => filteredAgents.value.filter(a => a.name && a.card_data))
const orphanedAgents = computed(() => filteredAgents.value.filter(a => !a.name || !a.card_data))

// ── Fleet Stats ───────────────────────────────────────────────────────────────
const totalLiquid = computed(() =>
  agents.value.reduce((sum, a) => sum + Number(a.liquid_balance || 0), 0)
)
const totalStaked = computed(() =>
  agents.value.reduce((sum, a) => sum + Number(a.staked_balance || 0), 0)
)
const activeCount = computed(() =>
  agents.value.filter(a => a.status === 'active').length
)
const lastActive = computed(() => {
  const times = agents.value
    .filter(a => a.last_active_at)
    .map(a => new Date(a.last_active_at!).getTime())
  if (!times.length) return null
  return new Date(Math.max(...times))
})

// ── Helpers ───────────────────────────────────────────────────────────────────
function agentName(agent: any): string {
  if (agent.name) return agent.name
  if (agent.card_data?.name) return agent.card_data.name
  if (agent.card_data?.humanReadableId) return agent.card_data.humanReadableId
  return agent.did ? agent.did.slice(-8) : 'Unnamed'
}

function formatAVT(n: number): string {
  if (!n) return '0'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (n >= 1_000) return Math.round(n).toLocaleString(appLocale())
  return String(n)
}

function formatTimeAgo(iso: string | null): string {
  if (!iso) return t('common.never', 'never')
  return dayjs(iso).fromNow()
}

function reputationTier(score: number): { label: string; color: string } {
  if (score >= 51) return { label: 'Sovereign', color: '#a78bfa' }
  if (score >= 10) return { label: 'Platinum', color: '#67e8f9' }
  if (score >= 7)  return { label: 'Gold',     color: '#fbbf24' }
  if (score >= 4)  return { label: 'Silver',   color: '#94a3b8' }
  if (score >= 1)  return { label: 'Bronze',   color: '#d97706' }
  return { label: 'Unranked', color: '#8191a5' }  // §FESUITE: #475569 was 2.4:1 on the card
}

function statusColor(status: string): string {
  if (status === 'active') return '#10b981'
  if (status === 'maintenance') return '#f59e0b'
  return '#ef4444'
}

async function copyDid(did: string) {
  try {
    await navigator.clipboard.writeText(did)
    copiedDid.value = did
    setTimeout(() => { if (copiedDid.value === did) copiedDid.value = null }, 1500)
  } catch { /* expected */ }
}

// FIX: Always use agent.did as the canonical route param.
// HumanReadableId is NOT unique — revoked and active agents can share the same HRI
// (e.g. two deploys of "Vivacious Valentino"). Using HRI caused the agents list
// find() to return the wrong (active) agent when viewing a revoked one with same name.
function navigateToAgent(agent: any) {
  agentStore.currentAgent = { ...agent, name: agentName(agent) }
  router.push({ name: 'agent-details', params: { agentId: agent.did } })
}

// §V0064 P2 — AGORA equity chip: did→{symbol,last,ccy,status} for agents whose
// org is listed on THIS venue (equity-map). Empty on dark venues → no chips.
const equityByDid = ref<Record<string, EquityChip>>({})
function equityFor(agent: any): EquityChip | null {
  return (agent?.did && equityByDid.value[agent.did]) || null
}
function goToDesk(chip: EquityChip) {
  router.push({ path: '/agora', query: { sym: chip.symbol } })
}
function fmtEquityPx(v: any): string {
  // last prices arrive as NUMERIC(30,18) strings — show the price, not the padding
  const n = Number(v)
  return Number.isFinite(n) ? n.toLocaleString(appLocale(), { maximumFractionDigits: 4 }) : String(v)
}

import AgentAccessPanel from '@/components/agent/AgentAccessPanel.vue'  // IRONKEY
import { useEscapeClose } from '@/composables/useEscapeClose'
const accessDid = ref<string | null>(null)  // IRONKEY access modal
useEscapeClose(() => !!accessDid.value, () => { accessDid.value = null })
const accessAgentName = computed(() =>
  accessDid.value ? (agents.value.find((a: any) => a.did === accessDid.value)?.name || '') : '')

function editAgent(agent: any) {
  agentStore.currentAgent = { ...agent, name: agentName(agent) }
  router.push({ name: 'agent-details', params: { agentId: agent.did }, query: { edit: 'true' } })
}

function confirmDelete(agent: any) {
  agentToDelete.value = agent
  showDeleteDialog.value = true
}

async function deleteAgent() {
  if (!agentToDelete.value) return
  try {
    await agentStore.deleteAgent(agentToDelete.value.did)
    uiStore.showSuccess(t('myAgentsView.toasts.deleted', 'Deleted'), tp('myAgentsView.toasts.deleteBody', '{name} removed from fleet', { name: agentName(agentToDelete.value) }))
  } catch {
    uiStore.showError(t('myAgentsView.toasts.failed', 'Failed'), t('myAgentsView.errors.deleteFailed', 'Could not delete agent'))
  }
  showDeleteDialog.value = false
  agentToDelete.value = null
}

// ── Reset Credentials Helpers ────────────────────────────────────────────────
function confirmResetCredentials(agent: any) {
  agentToReset.value = agent
  resetPassword.value = ''
  resetError.value = ''
  showResetDialog.value = true
}

async function executeResetCredentials() {
  if (!agentToReset.value || !resetPassword.value) return
  resetLoading.value = true
  resetError.value = ''
  try {
    const response = await apiClient.post(
      `/onboard/agents/${agentToReset.value.did}/reset-credentials`,
      { password: resetPassword.value }
    )
    newCredentials.value = {
      client_id: response.data.client_id,
      client_secret: response.data.client_secret,
    }
    // §FEFRAME W1: the reset killed the old secret, so the one saved in this browser was dead from this moment and
    // every page load retried it (a 401 and a toast). Save the new pair in its place, with its home registry.
    try {
      const prev = agentCredentialsStore.getCredentials(agentToReset.value.did)
      agentCredentialsStore.storeCredentials({
        did: agentToReset.value.did,
        client_id: response.data.client_id,
        client_secret: response.data.client_secret,
        name: agentToReset.value.name || prev?.name,
        humanReadableId: prev?.humanReadableId,
        registry: prev?.registry,
        // minted by THIS console's registry, so local to it: no address (with one, EU's alias hosts would read it as
        // foreign). The response's registry_url is for a credential that travels (a download, another console).
        registry_url: undefined,
      })
    } catch { /* the dialog still shows the pair; saving is a convenience */ }
    showResetDialog.value = false
    showCredentialsDialog.value = true
  } catch (e: any) {
    resetError.value = e?.response?.data?.error?.detail || e?.response?.data?.detail || t('myAgentsView.errors.resetFailed', 'Reset failed. Check your password.')
  } finally {
    resetLoading.value = false
  }
}

async function copyToClipboard(text: string, field: string) {
  try {
    await navigator.clipboard.writeText(text)
    copiedField.value = field
    setTimeout(() => { copiedField.value = '' }, 2000)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    copiedField.value = field
    setTimeout(() => { copiedField.value = '' }, 2000)
  }
}

function closeCredentialsDialog() {
  newCredentials.value = null
  showCredentialsDialog.value = false
  copiedField.value = ''
}

// ── Funding Request Helpers ──────────────────────────────────────────────────
const hasActiveAgent = computed(() => !!authStore.agentToken && !!authStore.activeAgent)

// Agents eligible for funding selection: named, non-stress, active
const fundingEligibleAgents = computed(() => {
  return (agentStore.agents || []).filter((a: any) => {
    const name = a.name || a.agent_name || ''
    if (!name || name.startsWith('Stress')) return false
    if (a.status && a.status !== 'active') return false
    return true
  })
})

// Whether an agent is selected for funding (either via dropdown or already active)
const fundingAgentReady = computed(() => {
  if (selectedFundingAgentDid.value) {
    // Check if the selected agent matches the currently active agent
    return hasActiveAgent.value && authStore.activeAgent?.did === selectedFundingAgentDid.value
  }
  return hasActiveAgent.value
})

async function selectFundingAgent(did: string) {
  if (!did) return
  selectedFundingAgentDid.value = did
  // If already active as this agent, no switch needed
  if (authStore.activeAgent?.did === did) return
  // Switch to the selected agent
  fundingAgentSwitching.value = true
  fundingError.value = null
  try {
    const success = await authStore.switchAgent(did)
    if (!success) {
      fundingError.value = t('myAgentsView.errors.authFailed', 'Failed to authenticate as selected agent. Check agent credentials.')
    }
  } catch (e: any) {
    fundingError.value = e.message || t('myAgentsView.errors.switchFailed', 'Failed to switch agent')
  } finally {
    fundingAgentSwitching.value = false
  }
}

async function fetchFundingRequests() {
  if (!hasActiveAgent.value) return
  fundingHistoryLoading.value = true
  try {
    const { data } = await apiClient.get('/funding/my-requests', {
      headers: { Authorization: `Bearer ${authStore.agentToken}` }
    })
    fundingRequests.value = Array.isArray(data) ? data : (data.requests || [])
    fundingHistoryOk = true
    fundingHistoryFailed.value = false
  } catch (e: any) {
    console.error('Failed to fetch funding requests:', e)
    if (!fundingHistoryOk) fundingHistoryFailed.value = true
  } finally {
    fundingHistoryLoading.value = false
  }
}

async function submitFundingRequest() {
  if (!hasActiveAgent.value) return
  if (fundingAmount.value < 100 || fundingAmount.value > 100000) {
    fundingError.value = tp('myAgentsView.errors.fundingAmountRange', 'Amount must be between 100 and 100,000 {ccy}', { ccy: localCurrency || '' })
    return
  }
  if (!fundingReason.value || fundingReason.value.trim().length < 10) {
    fundingError.value = t('myAgentsView.errors.fundingReasonMin', 'Please provide a reason (at least 10 characters)')
    return
  }
  fundingSubmitting.value = true
  fundingError.value = null
  try {
    await apiClient.post('/funding/request', {
      amount: String(fundingAmount.value),
      reason: fundingReason.value.trim()
    }, {
      headers: { Authorization: `Bearer ${authStore.agentToken}` }
    })
    uiStore.showSuccess(t('myAgentsView.toasts.requestSubmitted', 'Request Submitted'), tp('myAgentsView.toasts.requestSubmittedBody', 'Your {ccy} funding request has been submitted for review.', { ccy: localCurrency || '' }))
    showFundingModal.value = false
    fundingAmount.value = 1000
    fundingReason.value = ''
    await fetchFundingRequests()
  } catch (e: any) {
    fundingError.value = e.response?.data?.detail || e.message || t('myAgentsView.errors.fundingSubmitFailed', 'Failed to submit request')
  } finally {
    fundingSubmitting.value = false
  }
}

function fundingStatusColor(status: string): string {
  switch (status?.toLowerCase()) {
    case 'pending': return '#f59e0b'
    case 'approved': return '#3b82f6'
    case 'funded': return '#10b981'
    case 'rejected': return '#ef4444'
    default: return '#94a3b8'
  }
}

function formatDate(iso: string): string {
  if (!iso) return '--'
  return new Date(iso).toLocaleDateString(appLocale(), { month: 'short', day: 'numeric', year: 'numeric' })
}

// ── Init ──────────────────────────────────────────────────────────────────────
// 2026-05-09: explicit limit=500 — show as many of the developer's own agents
// as the server allows in one shot. Server caps at 500 hard. For fleets larger
// than that, pagination via `offset` is a follow-up — MyAgents.vue already
// has its own client-side pagination + filtering UI which still works fine
// over the first 500 rows.
// §agentdeclutter — reload the fleet from the server with the current levers:
//  • the search box drives the backend `q` (whole-fleet name/DID search) instead of
//    only filtering the loaded page — a real agent behind thousands of hands is now
//    findable; a present query searches EVERYTHING (hands included).
//  • hideSubAgents drives top_level_only (exclude birth-token holders).
const fleetReloading = ref(false)
let fleetSearchTimer: ReturnType<typeof setTimeout> | null = null
async function reloadFleet() {
  fleetReloading.value = true
  try {
    const q = searchQuery.value.trim()
    await agentStore.fetchMyAgents(undefined, {
      limit: 500,
      q: q || undefined,
      topLevelOnly: q ? false : hideSubAgents.value,
    })
  } finally {
    fleetReloading.value = false
  }
}
watch(hideSubAgents, () => { reloadFleet() })
watch(searchQuery, () => {
  if (fleetSearchTimer) clearTimeout(fleetSearchTimer)
  fleetSearchTimer = setTimeout(() => { reloadFleet() }, 350)
})

onMounted(async () => {
  // §AGENTCOCKPIT T2.2 — the agent detail page shows an agent's client_id and needs
  // a door to rotation. Rotation is password-gated and reveals the secret ONCE, and
  // that flow lives HERE; ?reset=<did> opens THIS dialog rather than growing a
  // second copy of a credential path in another view.
  //
  // FIRST, before the fleet fetch is awaited: this ran after it and the dialog took
  // ~10 SECONDS to appear (measured) while 500 agents loaded, which reads as a door
  // that did nothing. The dialog needs a did and a label, both of which arrived in
  // the query.
  // ⚠ do NOT look the agent up in the fleet list to get them: that list is PAGED at
  // 500 and this account holds more — measured, the very agent this door was opened
  // for was absent from it. The list is consulted only to upgrade the label later.
  const wantReset = String(route.query.reset || '')
  if (wantReset) {
    router.replace({ name: 'my-agents', query: {} }).catch(() => {})
    confirmResetCredentials({ did: wantReset, name: wantReset })
  }
  // §ONBOARDQOL P2 (2026-09-02) — the funding DOOR. Every surface that tells a person
  // "you hold 0 <ccy>" (the quick-onboard success sheet, OurChat's confirm sheet) links
  // here with ?fund=1, and this opens the SAME request modal the REQUEST button opens.
  // Consumed then scrubbed, like ?reset= above.
  if (String(route.query.fund || '')) openFundingDoor()
  try {
    await agentStore.fetchMyAgents(undefined, { limit: 500, topLevelOnly: hideSubAgents.value })
    if (hasActiveAgent.value) {
      await fetchFundingRequests()
    }
  } catch (e: any) {
    uiStore.showError(t('myAgentsView.toasts.loadFailed', 'Load Failed'), t('myAgentsView.errors.loadFailed', 'Could not load your fleet. Please refresh.'))
  }
  // equity chips — non-blocking, after the fleet renders (dark venue → {})
  exchangeService.equityByDid().then(m => { equityByDid.value = m }).catch(() => {})

  // the dialog opened before the fleet was known; give it the real name now that it is
  if (wantReset && agentToReset.value?.did === wantReset) {
    const known = agents.value.find((a: any) => a.did === wantReset)
    if (known) agentToReset.value = known
  }

})
</script>

<template>
  <div class="fleet-root hm-module">
    <!-- 2026-05-07: ambient bg layer (matches Federation, AdminCanaries) — fixes "lost background" complaint. -->

    <div class="fleet-content">
    <!-- ── Header ──────────────────────────────────────────────────────────── -->
    <div class="fleet-header">
      <div class="fleet-title-block">
        <div class="fleet-eyebrow">{{ t('myAgentsView.eyebrow', 'SOVEREIGN REGISTRY') }}</div>
        <h1 class="fleet-title" data-tour="mya-hero">{{ t('myAgentsView.title', 'MY FLEET') }}</h1>
        <!-- §LEDGERGATE (V0601): the count and the stats bar are what the fleet read answered; over a read that failed they
             said "0 agents deployed" and zero balances above the notice that says the read failed (journal 51's figures) -->
        <div v-if="!fleetUnread" class="fleet-subtitle">{{ agents.length }} agents deployed</div>
      </div>

      <!-- Stats bar -->
      <div v-if="!fleetUnread" class="fleet-stats" data-testid="mya-fleet-stats">
        <div class="fleet-stat">
          <span class="stat-label">{{ t('myAgentsView.stats.liquid', 'LIQUID') }}</span>
          <span class="stat-value stat-avt">◎ {{ formatAVT(totalLiquid) }}</span>
        </div>
        <div class="fleet-stat-divider" />
        <div class="fleet-stat">
          <span class="stat-label">{{ t('myAgentsView.stats.staked', 'LOCKED') }}</span>
          <span class="stat-value stat-staked">◉ {{ formatAVT(totalStaked) }}</span>
        </div>
        <div class="fleet-stat-divider" />
        <div class="fleet-stat">
          <span class="stat-label">{{ t('myAgentsView.stats.active', 'ACTIVE') }}</span>
          <span class="stat-value stat-active">{{ activeCount }}/{{ agents.length }}</span>
        </div>
        <div v-if="lastActive" class="fleet-stat-divider" />
        <div v-if="lastActive" class="fleet-stat">
          <span class="stat-label">{{ t('myAgentsView.stats.lastPing', 'LAST PING') }}</span>
          <span class="stat-value stat-ping">{{ formatTimeAgo(lastActive.toISOString()) }}</span>
        </div>
      </div>

      <!-- §pass50.7 — Quick-onboard takes precedence; "Advanced" still opens AgentForge -->
      <button class="fleet-deploy-btn" @click="uiStore.openQuickAgentModal()" title="30-second quick deploy">
        <span class="deploy-icon">+</span> {{ t('myAgentsView.actions.deployAgent', 'DEPLOY AGENT') }}
      </button>
      <button class="fleet-deploy-btn fleet-deploy-btn--funding" data-tour="mya-fund" @click="showFundingModal = true; selectedFundingAgentDid = authStore.activeAgent?.did || ''; fundingError = null">
        <span class="deploy-icon">◎</span> {{ tp('myAgentsView.actions.requestCcy', 'REQUEST {ccy}', { ccy: localCurrency || '' }) }}
      </button>
      <button class="fleet-deploy-btn fleet-deploy-btn--import" @click="showBulkImport = true" title="Paste credentials JSON for agents created in another browser">
        <span class="deploy-icon">⏶</span> {{ t('myAgentsView.actions.importKeys', 'IMPORT KEYS') }}
      </button>
    </div>

    <!-- ── Controls ───────────────────────────────────────────────────────── -->
    <div class="fleet-controls">
      <div class="fleet-search-wrap">
        <span class="search-icon">⌕</span>
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="t('myAgentsView.searchPlaceholder', 'Search by name, DID, or capability…')"
          class="fleet-search"
        />
      </div>

      <div class="fleet-filters">
        <select v-model="statusFilter" class="fleet-select" :aria-label="t('myAgentsView.filters.statusAria', 'Filter agents by status')">
          <option value="">{{ t('myAgentsView.filters.allStatus', 'All Status') }}</option>
          <option value="active">{{ t('myAgentsView.filters.active', 'Active') }}</option>
          <option value="inactive">{{ t('myAgentsView.filters.inactive', 'Inactive') }}</option>
          <option value="maintenance">{{ t('myAgentsView.filters.maintenance', 'Maintenance') }}</option>
        </select>

        <select v-model="sortBy" class="fleet-select" :aria-label="t('myAgentsView.sort.aria', 'Sort agents')">
          <option value="balance">{{ t('myAgentsView.sort.balance', 'Sort: Balance') }}</option>
          <option value="reputation">{{ t('myAgentsView.sort.reputation', 'Sort: Reputation') }}</option>
          <option value="activity">{{ t('myAgentsView.sort.activity', 'Sort: Activity') }}</option>
          <option value="name">{{ t('myAgentsView.sort.name', 'Sort: Name') }}</option>
        </select>

        <!-- §agentdeclutter — hide spawned sub-agents (hands) so real agents surface.
             Server-side (top_level_only); searching looks through everything. -->
        <label class="fleet-toggle"
               :title="t('myAgentsView.filters.hideSubAgentsHint', 'Hide spawned sub-agents (hands) so your real agents show. The search box looks through everything.')">
          <input type="checkbox" v-model="hideSubAgents" />
          <span>{{ t('myAgentsView.filters.hideSubAgents', 'Hide sub-agents') }}</span>
          <span v-if="fleetReloading" class="fleet-toggle-spin" aria-hidden="true">⟳</span>
        </label>

        <!-- §28 polish (2026-05-15) — Card-mode toggle: customize vs details.
             Customize: show flare pickers (corner/encirclement/overlay/variant rows).
             Details:   hide all flare pickers, leaner card focused on agent meta. -->
        <div class="view-toggle view-toggle--mode" :title="t('myAgentsView.toggleModeTitle', 'Switch between flare-customization mode and details mode')">
          <button
            class="view-btn" :class="{ 'view-btn--active': cardMode === 'customize' }"
            @click="cardMode = 'customize'" :title="t('myAgentsView.modeCustomize', 'Customize')"
          >
            <Icon name="mdi:palette-outline" />
            <span class="view-btn-label">{{ t('myAgentsView.modeCustomize', 'Customize') }}</span>
          </button>
          <button
            class="view-btn" :class="{ 'view-btn--active': cardMode === 'details' }"
            @click="cardMode = 'details'" :title="t('myAgentsView.modeDetails', 'Details')"
          >
            <Icon name="mdi:card-account-details" />
            <span class="view-btn-label">{{ t('myAgentsView.modeDetails', 'Details') }}</span>
          </button>
        </div>

        <div class="view-toggle">
          <button
            class="view-btn" :class="{ 'view-btn--active': viewMode === 'grid' }"
            @click="viewMode = 'grid'" title="Grid"
          >⊞</button>
          <button
            class="view-btn" :class="{ 'view-btn--active': viewMode === 'list' }"
            @click="viewMode = 'list'" title="List"
          >≡</button>
        </div>
      </div>
    </div>

    <!-- ── Loading (only the INITIAL empty load; a refresh/search must never blank
         an already-populated fleet to a full-page spinner — §agentdeclutter) ──── -->
    <div v-if="agentStore.loading && agents.length === 0" class="fleet-loading">
      <div class="loading-ring" />
      <span>{{ t('myAgentsView.loading', 'Querying sovereign registry…') }}</span>
    </div>

    <!-- §FESUITE (2026-10-05): a failed fleet read said "Fleet is empty: No agents deployed" and offered a first wallet
         agent; it says the read failed now, with Try again -->
    <div v-else-if="agentStore.myAgentsFailed && agents.length === 0" class="fleet-empty" data-testid="mya-fleet-read-failed">
      <ReadFailedNotice :retry="reloadFleet" />
    </div>

    <!-- ── Empty State ────────────────────────────────────────────────────── -->
    <div v-else-if="!agentStore.loading && agents.length === 0" class="fleet-empty">
      <div class="empty-glyph">◈</div>
      <h3 class="empty-title">{{ t('myAgentsView.emptyTitle', 'Fleet is empty') }}</h3>
      <p class="empty-sub">{{ t('myAgentsView.emptyBody', 'No agents deployed. Ready to join the sovereign network?') }}</p>
      <!-- §pass50.7 — Quick-onboard the first agent (30s flow); "Advanced" still on the card buttons -->
      <button class="fleet-deploy-btn fleet-deploy-btn--large" @click="uiStore.openQuickAgentModal()">
        {{ t('myAgentsView.card.deployFirst', 'CREATE YOUR WALLET AGENT') }}
      </button>
      <button class="fleet-deploy-btn fleet-deploy-btn--ghost" style="margin-top:10px;" @click="router.push({ name: 'agent-builder' })">
        Or open AgentForge for advanced setup &rsaquo;
      </button>
    </div>

    <!-- ── No Results ─────────────────────────────────────────────────────── -->
    <div v-else-if="filteredAgents.length === 0" class="fleet-empty fleet-empty--small">
      <p class="empty-sub">{{ t('myAgentsView.noMatchBody', 'No agents match your filter.') }}</p>
    </div>

    <template v-else>
      <!-- ── GRID VIEW ─────────────────────────────────────────────────────── -->
      <template v-if="viewMode === 'grid'">

        <!-- Named agents -->
        <div v-if="namedAgents.length" class="fleet-grid">
          <div
            v-for="agent in namedAgents"
            :key="agent.did"
            class="agent-card"
            data-testid="agent-card"
            :data-did="agent.did"
          >
            <!-- Status bar -->
            <div class="card-status-bar">
              <span class="status-dot" :style="{ background: statusColor(agent.status) }" />
              <span class="status-label">{{ agent.status?.toUpperCase() }}</span>
              <span
                :class="['creds-pill', hasLocalCreds(agent.did) ? 'creds-pill--ok' : 'creds-pill--miss']"
                :title="hasLocalCreds(agent.did) ? t('myAgentsView.card.credsStored', 'Credentials stored locally') : t('myAgentsView.card.noCredsHint', 'No credentials in this browser — click ADD KEYS to paste')"
              >
                <span class="creds-pill-dot" />
                {{ hasLocalCreds(agent.did) ? t('myAgentsView.card.keys', 'KEYS') : t('myAgentsView.card.noKeys', 'NO KEYS') }}
              </span>
              <span class="card-age">{{ formatTimeAgo(agent.last_active_at ?? null) }}</span>
            </div>

            <!-- Name + DID + Flare -->
            <div class="card-identity">
              <div class="card-name-row">
                <!-- §15: shadow_chancellor agents render via UserAvatar so the
                     encirclement variant is visible. §15.4: pass the agent's
                     iconUrl (from agent_card.card_data) as :avatar-url so the
                     image shows inside the encirclement composition.
                     §19 (2026-05-13): UserAvatar now renders for ALL agents
                     (not just shadow). Non-shadow agents get a plain avatar
                     ring without encirclement — UserAvatar handles the
                     no-flare case via its v-else branch. This gives every
                     agent a visible avatar so the AVATAR URL editor below has
                     a concrete preview. -->
                <UserAvatar
                  :user="agent"
                  :avatar-url="agent.card_data?.iconUrl || agent.card_data?.icon_url || null"
                  :display-name="agentName(agent)"
                  size="sm"
                  class="card-flare-avatar"
                />
                <h3 class="card-name" @click="navigateToAgent(agent)">{{ agentName(agent) }}</h3>
                <span v-if="isWalletAgent(agent)" class="card-wallet-chip" data-testid="agent-wallet-chip" :title="t('wallet.first', 'Your wallet agent is your first identity. It holds your funds and pays and votes with its own address, under your name.')">{{ t('wallet.chip', 'WALLET') }}</span>
                <FlareBadge
                  v-if="agent.flare_tier"
                  :tier="agent.flare_tier"
                  :granted-at="agent.flare_granted_at"
                  :display-name="agent.flare_display_name"
                  :tagline="agent.flare_tagline"
                  :logo-url="agent.flare_logo_url"
                  :cause="agent.flare_cause"
                  :accent-color="agent.flare_accent_color"
                  :flare-id="agent.flare_id"
                  size="sm"
                  :show-label="false"
                />
              </div>
              <div class="card-did">
                <span class="did-text">{{ agent.did }}</span>
                <button class="did-copy" @click.stop="copyDid(agent.did)" :title="'Copy DID'">
                  {{ copiedDid === agent.did ? '✓' : '⧉' }}
                </button>
              </div>
              <!-- §V0064 P2 — AGORA equity chip: this agent's org is publicly
                   listed → show $TICKER + last price, click → the Exchange Desk
                   for that book. equity-map join (org→listing), local venue. -->
              <button
                v-if="equityFor(agent)"
                class="card-equity-chip"
                :title="`${equityFor(agent)!.symbol} listed on AGORA, open the AGORA Desk`"
                @click.stop="goToDesk(equityFor(agent)!)"
              >
                <Icon name="mdi:chart-candlestick" />
                <span class="card-equity-sym">${{ equityFor(agent)!.symbol }}</span>
                <span v-if="equityFor(agent)!.last" class="card-equity-px">{{ fmtEquityPx(equityFor(agent)!.last) }} {{ equityFor(agent)!.currency }}</span>
                <span v-if="equityFor(agent)!.status === 'halted'" class="card-equity-halt">HALTED</span>
              </button>
              <!-- §28 polish (2026-05-15) — cardMode='details' hides ALL
                   flare-customization rows below. Per-card chevron also
                   toggles JUST this card. -->
              <div v-if="cardMode === 'customize'" class="card-flare-collapse-row">
                <button
                  class="card-flare-collapse-btn"
                  :class="{ 'card-flare-collapse-btn--collapsed': collapsedCards.has(agent.did) }"
                  @click.stop="toggleCardFlare(agent.did)"
                  :title="collapsedCards.has(agent.did) ? t('myAgentsView.expandFlares', 'Show flare options') : t('myAgentsView.collapseFlares', 'Hide flare options')"
                >
                  <Icon name="mdi:palette-outline" />
                  <span class="card-flare-collapse-label">{{ collapsedCards.has(agent.did) ? t('myAgentsView.expandFlares', 'Show flare options') : t('myAgentsView.collapseFlares', 'Hide flare options') }}</span>
                  <Icon :name="collapsedCards.has(agent.did) ? 'mdi:chevron-down' : 'mdi:chevron-up'" class="card-flare-chevron" />
                </button>
              </div>
              <template v-if="isCardFlareVisible(agent.did)">
              <!-- §23 (2026-05-14) — DUAL-SLOT FLARE quick-equip rows.
                   Each slot is independently equip-able from the agent card.
                   Same agent can bear both; or each slot on a different
                   agent. Shows: BEARER pill (with inline remove ✕) when this
                   agent bears the slot; "↪ Equip here" CTA when the dev has
                   that slot earned + selected but this agent doesn't bear
                   it; muted "no slot" placeholder when the dev hasn't
                   selected anything for that slot. -->
              <div
                v-if="canEquipSlot('corner') || canEquipSlot('encirclement') || agent.bears_corner_flare || agent.bears_encirclement_flare"
                class="card-flare-row card-flare-row--slot card-flare-row--corner"
              >
                <span class="card-variant-label">{{ t('myAgentsView.card.corner', 'CORNER') }}</span>
                <span v-if="agent.bears_corner_flare" class="card-flare-bearer-pill card-flare-bearer-pill--corner">
                  <span class="card-flare-bearer-dot"></span>
                  {{ t('myAgentsView.card.bearer', 'BEARER') }} · {{ agent.selected_corner_flare ? (agent.selected_corner_flare[0].toUpperCase() + agent.selected_corner_flare.slice(1)) : t('myAgentsView.card.cornerFallback', 'Corner') }}
                  <button
                    class="card-flare-slot-clear"
                    :disabled="slotEquipping !== null"
                    @click.stop="unequipSlotFromAgent('corner', agent)"
                  >✕</button>
                </span>
                <button
                  v-else-if="canEquipSlot('corner')"
                  class="card-flare-move-btn card-flare-move-btn--corner"
                  :disabled="slotEquipping !== null"
                  @click.stop="equipSlotOnAgent('corner', agent)"
                >
                  <span v-if="slotEquipping?.slot === 'corner' && slotEquipping?.did === agent.did">{{ t('myAgentsView.card.equipping', 'Equipping…') }}</span>
                  <span v-else>{{ t('myAgentsView.card.equipCorner', '↪ Equip corner here') }}</span>
                </button>
                <span v-else class="card-flare-no-slot">{{ t('myAgentsView.card.noCorner', '— no corner') }}</span>
              </div>

              <div
                v-if="canEquipSlot('corner') || canEquipSlot('encirclement') || agent.bears_corner_flare || agent.bears_encirclement_flare"
                class="card-flare-row card-flare-row--slot card-flare-row--enc"
              >
                <span class="card-variant-label">{{ t('myAgentsView.card.encircle', 'ENCIRCLE') }}</span>
                <span v-if="agent.bears_encirclement_flare" class="card-flare-bearer-pill card-flare-bearer-pill--enc">
                  <span class="card-flare-bearer-dot"></span>
                  {{ t('myAgentsView.card.bearer', 'BEARER') }} · {{ agent.selected_encirclement_flare === 'shadow_chancellor' ? t('myAgentsView.card.shadow', 'Shadow') : (agent.selected_encirclement_flare || t('myAgentsView.card.encircleFallback', 'Encirclement')) }}
                  <button
                    class="card-flare-slot-clear"
                    :disabled="slotEquipping !== null"
                    @click.stop="unequipSlotFromAgent('encirclement', agent)"
                  >✕</button>
                </span>
                <button
                  v-else-if="canEquipSlot('encirclement')"
                  class="card-flare-move-btn card-flare-move-btn--enc"
                  :disabled="slotEquipping !== null"
                  @click.stop="equipSlotOnAgent('encirclement', agent)"
                >
                  <span v-if="slotEquipping?.slot === 'encirclement' && slotEquipping?.did === agent.did">{{ t('myAgentsView.card.equipping', 'Equipping…') }}</span>
                  <span v-else>{{ t('myAgentsView.card.equipEncirclement', '↪ Equip encirclement here') }}</span>
                </button>
                <span v-else class="card-flare-no-slot">{{ t('myAgentsView.card.noEncirclement', '— no encirclement') }}</span>
              </div>

              <!-- §15+§24: per-agent variant picker. Visible when agent
                   bears the encirclement slot. All 19 variants are pickable
                   (§24 removed cosmetic locks). Each variant is single-
                   occupancy across the dev's fleet: clicking a variant
                   currently equipped elsewhere MOVES it from the previous
                   agent to this one. The pill shows a "→ AGENT_X" hint
                   when the variant is currently in use by another agent. -->
              <div v-if="agent.bears_encirclement_flare && agent.selected_encirclement_flare === 'shadow_chancellor'" class="card-variant-row">
                <span class="card-variant-label">{{ t('myAgentsView.card.style', 'STYLE') }}</span>
                <button
                  class="card-variant-pill card-variant-pill--reset"
                  :disabled="agentVariantSaving === agent.did || !agent.flare_encirclement_variant"
                  @click.stop="setAgentVariant(agent, null as any)"
                >
                  {{ t('myAgentsView.card.resetVariant', '↺ default') }}
                </button>
                <button
                  v-for="vId in AGENT_VARIANT_PILLS"
                  :key="vId"
                  class="card-variant-pill"
                  :class="{
                    'card-variant-pill--active': agent.flare_encirclement_variant === vId,
                    'card-variant-pill--elsewhere': variantHint(vId, agent) !== '',
                  }"
                  :disabled="agentVariantSaving === agent.did"
                  :title="variantHint(vId, agent)
                    ? `On ${variantHint(vId, agent)} — click to move ${vId} here`
                    : `Switch ${agentName(agent)}'s encirclement to ${vId}`"
                  @click.stop="setAgentVariant(agent, vId)"
                >
                  {{ vId }}
                  <span v-if="variantHint(vId, agent)" class="card-variant-pill-hint">
                    → {{ variantHint(vId, agent) }}
                  </span>
                </button>
              </div>

              <!-- §28 (2026-05-13) — Per-agent OVERLAY picker (broken-machine
                   axis). Independent of base variant; composes on top. -->
              <div v-if="agent.bears_encirclement_flare && agent.selected_encirclement_flare === 'shadow_chancellor'" class="card-variant-row">
                <span class="card-variant-label">{{ t('myAgentsView.card.overlay', 'OVERLAY') }}</span>
                <button
                  class="card-variant-pill card-variant-pill--reset"
                  :disabled="agentOverlaySaving === agent.did || !agent.flare_encirclement_overlay"
                  @click.stop="switchAgentOverlay(agent, null)"
                >
                  {{ t('myAgentsView.card.resetOverlay', '↺ no overlay') }}
                </button>
                <button
                  v-for="oId in AGENT_OVERLAY_PILLS"
                  :key="`ov-${oId}`"
                  class="card-variant-pill"
                  :class="{
                    'card-variant-pill--active': agent.flare_encirclement_overlay === oId,
                  }"
                  :disabled="agentOverlaySaving === agent.did"
                  :title="`Switch ${agentName(agent)}'s overlay to ${oId}`"
                  @click.stop="switchAgentOverlay(agent, oId)"
                >
                  {{ oId }}
                </button>
              </div>

              <!-- §23 (2026-05-14) — Per-agent ADMIN CORNER BADGE variant
                   picker. Only shown when (a) caller is admin AND (b) agent
                   currently bears the corner slot. Mirrors the §20 admin
                   corner picker from FlareManager but per-agent. -->
              <div
                v-if="isAdminUser() && agent.bears_corner_flare"
                class="card-variant-row card-variant-row--admin"
              >
                <span class="card-variant-label">{{ t('myAgentsView.card.icon', 'ICON') }}</span>
                <button
                  class="card-variant-pill card-variant-pill--reset"
                  :disabled="cornerVariantSaving === agent.did || !agent.flare_corner_variant"
                  @click.stop="setAgentCornerVariant(agent, null)"
                >{{ t('myAgentsView.card.resetVariant', '↺ default') }}</button>
                <button
                  v-for="cv in ADMIN_CORNER_VARIANTS"
                  :key="cv"
                  class="card-variant-pill card-variant-pill--admin"
                  :class="{
                    'card-variant-pill--active': agent.flare_corner_variant === cv,
                    'card-variant-pill--elsewhere': cornerVariantHint(cv, agent) !== '',
                  }"
                  :disabled="cornerVariantSaving === agent.did"
                  :title="cornerVariantHint(cv, agent)
                    ? `On ${cornerVariantHint(cv, agent)} — click to move ${cv} here`
                    : `Switch ${agentName(agent)}'s corner icon to ${cv}`"
                  @click.stop="setAgentCornerVariant(agent, cv)"
                >
                  {{ cv }}
                  <span v-if="cornerVariantHint(cv, agent)" class="card-variant-pill-hint">
                    → {{ cornerVariantHint(cv, agent) }}
                  </span>
                </button>
              </div>
              </template>
              <!-- /§28 polish — end of cardMode='customize' block -->

              <p v-if="slotEquipError && (slotEquipping?.did === agent.did || agent.bears_corner_flare || agent.bears_encirclement_flare)" class="card-flare-error">
                {{ slotEquipError }}
              </p>
              <p v-if="flareMoveError && flareMoving === agent.did" class="card-flare-error">
                {{ flareMoveError }}
              </p>

              <!-- §15.4: per-agent avatar URL editor — mirrors Settings → Avatar.
                   PUT /agent-cards/{did} with merged card_data. UserAvatar above
                   shows the iconUrl when set, falling back to initials otherwise.
                   §28 polish 7 (2026-05-15): hidden when card is in collapsed/
                   details mode — the chevron at the top of the card toggles. -->
              <div v-if="isCardFlareVisible(agent.did)" class="card-avatar-row">
                <template v-if="avatarEditingDid === agent.did">
                  <input
                    v-model="avatarEditingValue"
                    type="url"
                    class="card-avatar-input"
                    :placeholder="t('myAgentsView.card.avatarPlaceholder', 'https://example.com/avatar.png  (blank to clear)')"
                    maxlength="500"
                    :disabled="avatarSavingDid === agent.did"
                    @keyup.enter="saveAgentAvatar(agent)"
                    @keyup.escape="cancelAvatarEditor"
                  />
                  <button
                    class="card-avatar-btn card-avatar-btn--save"
                    :disabled="avatarSavingDid === agent.did"
                    @click.stop="saveAgentAvatar(agent)"
                  >
                    {{ avatarSavingDid === agent.did ? '…' : t('myAgentsView.card.save', 'SAVE') }}
                  </button>
                  <button
                    class="card-avatar-btn card-avatar-btn--cancel"
                    :disabled="avatarSavingDid === agent.did"
                    @click.stop="cancelAvatarEditor"
                  >
                    ✕
                  </button>
                </template>
                <template v-else>
                  <span class="card-variant-label">{{ t('myAgentsView.card.avatar', 'AVATAR') }}</span>
                  <span class="card-avatar-display" :title="agent.card_data?.iconUrl || ''">
                    {{ agent.card_data?.iconUrl ? truncMid(agent.card_data.iconUrl, 28, 14) : t('myAgentsView.card.avatarNone', '(none — using initials)') }}
                  </span>
                  <button
                    class="card-avatar-btn"
                    @click.stop="openAvatarEditor(agent)"
                  >
                    {{ t('myAgentsView.card.edit', 'EDIT') }}
                  </button>
                </template>
                <p v-if="avatarErrorByDid[agent.did]" class="card-avatar-error">
                  {{ avatarErrorByDid[agent.did] }}
                </p>
              </div>
            </div>

            <!-- Description -->
            <p v-if="agent.description" class="card-desc">{{ agent.description }}</p>

            <!-- Financials -->
            <div class="card-financials">
              <div class="fin-block">
                <span class="fin-label">{{ t('myAgentsView.card.liquid', 'LIQUID') }}</span>
                <span class="fin-value fin-liquid">◎ {{ formatAVT(Number(agent.liquid_balance) || 0) }}</span>
              </div>
              <div class="fin-block">
                <span class="fin-label">{{ t('myAgentsView.card.staked', 'LOCKED') }}</span>
                <span class="fin-value fin-staked">◉ {{ formatAVT(Number(agent.staked_balance) || 0) }}</span>
              </div>
              <div class="fin-block">
                <span class="fin-label">{{ t('myAgentsView.card.total', 'TOTAL') }}</span>
                <span class="fin-value">{{ formatAVT((Number(agent.liquid_balance) || 0) + (Number(agent.staked_balance) || 0)) }}</span>
              </div>
            </div>

            <!-- Reputation -->
            <div class="card-rep">
              <span class="rep-icon">★</span>
              <span
                class="rep-tier"
                :style="{ color: reputationTier(agent.reputation_score || 0).color }"
              >{{ reputationTier(agent.reputation_score || 0).label }}</span>
              <span class="rep-score">{{ agent.reputation_score ?? 0 }}</span>
            </div>

            <!-- Actions — §28 polish 7: EDIT button is part of the customize
                 cluster (it routes to the agent-builder where users tweak
                 the agent card / flare). Hidden in details mode along with
                 the avatar URL row. -->
            <!-- the decommission button keeps a column of its own; the labelled buttons wrap beside it (it wrapped onto a
                 row alone below VIEW when four labels filled the card) -->
            <div class="card-actions card-actions--split">
              <div class="card-actions-main">
              <button class="card-btn card-btn--primary" data-tour="mya-card" @click="navigateToAgent(agent)">{{ t('myAgentsView.card.view', 'VIEW') }}</button>
              <button v-if="isCardFlareVisible(agent.did)" class="card-btn card-btn--secondary" @click="editAgent(agent)">{{ t('myAgentsView.card.edit', 'EDIT') }}</button>
              <button class="card-btn card-btn--secondary" data-tour="ma-access-btn" @click="accessDid = agent.did" :title="t('myAgentsView.card.accessHint', 'Manage roles & spend limits')">{{ t('myAgentsView.card.access', 'ACCESS') }}</button>
              <button
                v-if="!hasLocalCreds(agent.did)"
                class="card-btn card-btn--accent"
                @click="openAddCredentials(agent)"
                title="Paste existing client_id + client_secret"
              >{{ t('myAgentsView.card.addKeys', 'ADD KEYS') }}</button>
              <button class="card-btn card-btn--warning" @click="confirmResetCredentials(agent)" title="Reset OAuth credentials">{{ t('myAgentsView.card.resetKeys', 'RESET KEYS') }}</button>
              </div>
              <button class="card-btn card-btn--danger" :aria-label="tp('myAgentsView.card.decommissionAria', 'Decommission {name}', { name: agentName(agent) })" :title="tp('myAgentsView.card.decommissionAria', 'Decommission {name}', { name: agentName(agent) })" @click="confirmDelete(agent)"><span aria-hidden="true">✕</span></button>
            </div>
          </div>
        </div>

        <!-- Orphaned agents section -->
        <div v-if="orphanedAgents.length" class="orphan-section">
          <div class="orphan-header">
            <span class="orphan-glyph">◌</span>
            {{ t('myAgentsView.orphan.header', 'UNCONFIGURED AGENTS') }}
            <span class="orphan-count">{{ orphanedAgents.length }}</span>
          </div>
          <div class="fleet-grid fleet-grid--orphan">
            <div
              v-for="agent in orphanedAgents"
              :key="agent.did"
              class="agent-card agent-card--orphan"
            >
              <div class="card-status-bar">
                <span class="status-dot" style="background: rgba(148,163,184,0.3)" />
                <span class="status-label" style="color: rgba(148,163,184,0.4)">{{ t('myAgentsView.card.unconfigured', 'UNCONFIGURED') }}</span>
              </div>
              <div class="card-identity">
                <!-- §15.1 (2026-05-13): even orphaned agents show their flare —
                     dev's automatic single-agent grant lands here for seed-data /
                     test setups that don't have agent cards yet. Same UserAvatar
                     dual-slot composition as named agents.
                     §19 (2026-05-13): renders for ALL orphaned agents too. -->
                <div class="card-name-row">
                  <UserAvatar
                    :user="agent"
                    :avatar-url="agent.card_data?.iconUrl || agent.card_data?.icon_url || null"
                    :display-name="agent.did.slice(-12)"
                    size="sm"
                    class="card-flare-avatar"
                  />
                  <h3 class="card-name card-name--dim">{{ agent.did.slice(-12) }}</h3>
                  <FlareBadge
                    v-if="agent.flare_tier"
                    :tier="agent.flare_tier"
                    :granted-at="agent.flare_granted_at"
                    size="sm"
                    :show-label="false"
                  />
                </div>
                <div class="card-did">
                  <span class="did-text">{{ agent.did }}</span>
                  <button class="did-copy" @click.stop="copyDid(agent.did)">
                    {{ copiedDid === agent.did ? '✓' : '⧉' }}
                  </button>
                </div>
                <!-- §28 polish (2026-05-15) — same customize/details gate
                     for the orphan-list variant of agent cards. Includes
                     per-card chevron collapse. -->
                <div v-if="cardMode === 'customize'" class="card-flare-collapse-row">
                  <button
                    class="card-flare-collapse-btn"
                    :class="{ 'card-flare-collapse-btn--collapsed': collapsedCards.has(agent.did) }"
                    @click.stop="toggleCardFlare(agent.did)"
                    :title="collapsedCards.has(agent.did) ? t('myAgentsView.expandFlares', 'Show flare options') : t('myAgentsView.collapseFlares', 'Hide flare options')"
                  >
                    <Icon name="mdi:palette-outline" />
                    <span class="card-flare-collapse-label">{{ collapsedCards.has(agent.did) ? t('myAgentsView.expandFlares', 'Show flare options') : t('myAgentsView.collapseFlares', 'Hide flare options') }}</span>
                    <Icon :name="collapsedCards.has(agent.did) ? 'mdi:chevron-down' : 'mdi:chevron-up'" class="card-flare-chevron" />
                  </button>
                </div>
                <template v-if="isCardFlareVisible(agent.did)">
                <!-- §23 (2026-05-14) — dual-slot quick-equip for orphans too. -->
                <div
                  v-if="canEquipSlot('corner') || canEquipSlot('encirclement') || agent.bears_corner_flare || agent.bears_encirclement_flare"
                  class="card-flare-row card-flare-row--slot card-flare-row--corner"
                >
                  <span class="card-variant-label">{{ t('myAgentsView.card.corner', 'CORNER') }}</span>
                  <span v-if="agent.bears_corner_flare" class="card-flare-bearer-pill card-flare-bearer-pill--corner">
                    <span class="card-flare-bearer-dot"></span>
                    {{ t('myAgentsView.card.bearer', 'BEARER') }} · {{ agent.selected_corner_flare ? (agent.selected_corner_flare[0].toUpperCase() + agent.selected_corner_flare.slice(1)) : t('myAgentsView.card.cornerFallback', 'Corner') }}
                    <button
                      class="card-flare-slot-clear"
                      :disabled="slotEquipping !== null"
                      @click.stop="unequipSlotFromAgent('corner', agent)"
                    >✕</button>
                  </span>
                  <button
                    v-else-if="canEquipSlot('corner')"
                    class="card-flare-move-btn card-flare-move-btn--corner"
                    :disabled="slotEquipping !== null"
                    @click.stop="equipSlotOnAgent('corner', agent)"
                  >
                    <span v-if="slotEquipping?.slot === 'corner' && slotEquipping?.did === agent.did">{{ t('myAgentsView.card.equipping', 'Equipping…') }}</span>
                    <span v-else>{{ t('myAgentsView.card.equipCorner', '↪ Equip corner here') }}</span>
                  </button>
                  <span v-else class="card-flare-no-slot">{{ t('myAgentsView.card.noCorner', '— no corner') }}</span>
                </div>

                <div
                  v-if="canEquipSlot('corner') || canEquipSlot('encirclement') || agent.bears_corner_flare || agent.bears_encirclement_flare"
                  class="card-flare-row card-flare-row--slot card-flare-row--enc"
                >
                  <span class="card-variant-label">{{ t('myAgentsView.card.encircle', 'ENCIRCLE') }}</span>
                  <span v-if="agent.bears_encirclement_flare" class="card-flare-bearer-pill card-flare-bearer-pill--enc">
                    <span class="card-flare-bearer-dot"></span>
                    {{ t('myAgentsView.card.bearer', 'BEARER') }} · {{ agent.selected_encirclement_flare === 'shadow_chancellor' ? t('myAgentsView.card.shadow', 'Shadow') : (agent.selected_encirclement_flare || t('myAgentsView.card.encircleFallback', 'Encirclement')) }}
                    <button
                      class="card-flare-slot-clear"
                      :disabled="slotEquipping !== null"
                      @click.stop="unequipSlotFromAgent('encirclement', agent)"
                    >✕</button>
                  </span>
                  <button
                    v-else-if="canEquipSlot('encirclement')"
                    class="card-flare-move-btn card-flare-move-btn--enc"
                    :disabled="slotEquipping !== null"
                    @click.stop="equipSlotOnAgent('encirclement', agent)"
                  >
                    <span v-if="slotEquipping?.slot === 'encirclement' && slotEquipping?.did === agent.did">{{ t('myAgentsView.card.equipping', 'Equipping…') }}</span>
                    <span v-else>{{ t('myAgentsView.card.equipEncirclement', '↪ Equip encirclement here') }}</span>
                  </button>
                  <span v-else class="card-flare-no-slot">{{ t('myAgentsView.card.noEncirclement', '— no encirclement') }}</span>
                </div>

                <!-- Per-agent variant picker for shadow agents (mirrors named-agent flow). §24 polish. -->
                <div v-if="agent.bears_encirclement_flare && agent.selected_encirclement_flare === 'shadow_chancellor'" class="card-variant-row">
                  <span class="card-variant-label">{{ t('myAgentsView.card.style', 'STYLE') }}</span>
                  <button
                    class="card-variant-pill card-variant-pill--reset"
                    :disabled="agentVariantSaving === agent.did || !agent.flare_encirclement_variant"
                    @click.stop="setAgentVariant(agent, null as any)"
                  >
                    {{ t('myAgentsView.card.resetVariant', '↺ default') }}
                  </button>
                  <button
                    v-for="vId in AGENT_VARIANT_PILLS"
                    :key="vId"
                    class="card-variant-pill"
                    :class="{
                      'card-variant-pill--active': agent.flare_encirclement_variant === vId,
                      'card-variant-pill--elsewhere': variantHint(vId, agent) !== '',
                    }"
                    :disabled="agentVariantSaving === agent.did"
                    :title="variantHint(vId, agent)
                      ? `On ${variantHint(vId, agent)} — click to move ${vId} here`
                      : `Switch encirclement to ${vId}`"
                    @click.stop="setAgentVariant(agent, vId)"
                  >
                    {{ vId }}
                    <span v-if="variantHint(vId, agent)" class="card-variant-pill-hint">
                      → {{ variantHint(vId, agent) }}
                    </span>
                  </button>
                </div>

                <!-- Admin per-agent corner-icon variant picker -->
                <div
                  v-if="isAdminUser() && agent.bears_corner_flare"
                  class="card-variant-row card-variant-row--admin"
                >
                  <span class="card-variant-label">{{ t('myAgentsView.card.icon', 'ICON') }}</span>
                  <button
                    class="card-variant-pill card-variant-pill--reset"
                    :disabled="cornerVariantSaving === agent.did || !agent.flare_corner_variant"
                    @click.stop="setAgentCornerVariant(agent, null)"
                  >{{ t('myAgentsView.card.resetVariant', '↺ default') }}</button>
                  <button
                    v-for="cv in ADMIN_CORNER_VARIANTS"
                    :key="cv"
                    class="card-variant-pill card-variant-pill--admin"
                    :class="{
                      'card-variant-pill--active': agent.flare_corner_variant === cv,
                      'card-variant-pill--elsewhere': cornerVariantHint(cv, agent) !== '',
                    }"
                    :disabled="cornerVariantSaving === agent.did"
                    :title="cornerVariantHint(cv, agent)
                      ? `On ${cornerVariantHint(cv, agent)} — click to move ${cv} here`
                      : `Switch corner icon to ${cv}`"
                    @click.stop="setAgentCornerVariant(agent, cv)"
                  >
                    {{ cv }}
                    <span v-if="cornerVariantHint(cv, agent)" class="card-variant-pill-hint">
                      → {{ cornerVariantHint(cv, agent) }}
                    </span>
                  </button>
                </div>
                </template>
                <!-- /§28 polish — end of orphan customize block -->
              </div>
              <p class="card-desc card-desc--dim">{{ t('myAgentsView.card.noCardConfigured', 'No agent card configured.') }}</p>
              <div class="card-actions">
                <button class="card-btn card-btn--configure" @click="router.push({ name: 'agent-builder' })">
                  {{ t('myAgentsView.card.configure', 'CONFIGURE') }}
                </button>
                <button class="card-btn card-btn--danger" :aria-label="tp('myAgentsView.card.decommissionAria', 'Decommission {name}', { name: agentName(agent) })" :title="tp('myAgentsView.card.decommissionAria', 'Decommission {name}', { name: agentName(agent) })" @click="confirmDelete(agent)"><span aria-hidden="true">✕</span></button>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ── LIST VIEW ──────────────────────────────────────────────────────── -->
      <div v-else class="fleet-table-wrap">
        <table class="fleet-table" data-tour="mya-table">
          <thead>
            <tr>
              <th>{{ t('myAgentsView.cols.status', 'STATUS') }}</th>
              <th>{{ t('myAgentsView.cols.agent', 'AGENT') }}</th>
              <th>{{ t('myAgentsView.cols.did', 'DID') }}</th>
              <th>{{ t('myAgentsView.cols.liquid', 'LIQUID') }}</th>
              <th>{{ t('myAgentsView.cols.staked', 'LOCKED') }}</th>
              <th>{{ t('myAgentsView.cols.rep', 'REP') }}</th>
              <th>{{ t('myAgentsView.cols.lastActive', 'LAST ACTIVE') }}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="agent in filteredAgents"
              :key="agent.did"
              class="table-row"
              :class="{ 'table-row--orphan': !agent.name }"
              @click="agent.name && navigateToAgent(agent)"
            >
              <td>
                <span class="status-dot" :style="{ background: statusColor(agent.status) }" />
              </td>
              <td class="td-name">
                <span class="td-name-text">{{ agentName(agent) }}</span>
                <FlareBadge
                  v-if="agent.flare_tier"
                  :tier="agent.flare_tier"
                  :granted-at="agent.flare_granted_at"
                  size="xs"
                  :show-label="false"
                />
              </td>
              <td class="td-did">
                <span>{{ agent.did.slice(0, 26) }}…</span>
                <button class="did-copy" @click.stop="copyDid(agent.did)">
                  {{ copiedDid === agent.did ? '✓' : '⧉' }}
                </button>
              </td>
              <td class="td-avt">◎ {{ formatAVT(Number(agent.liquid_balance) || 0) }}</td>
              <td class="td-staked">◉ {{ formatAVT(Number(agent.staked_balance) || 0) }}</td>
              <td>
                <span
                  class="rep-tier rep-tier--sm"
                  :style="{ color: reputationTier(agent.reputation_score || 0).color }"
                >{{ reputationTier(agent.reputation_score || 0).label }}</span>
              </td>
              <td class="td-time">{{ formatTimeAgo(agent.last_active_at ?? null) }}</td>
              <td @click.stop class="td-actions">
                <button v-if="agent.name" class="tbl-btn" @click="editAgent(agent)">{{ t('myAgentsView.card.edit', 'EDIT') }}</button>
                <button class="tbl-btn tbl-btn--danger" :aria-label="tp('myAgentsView.card.decommissionAria', 'Decommission {name}', { name: agentName(agent) })" :title="tp('myAgentsView.card.decommissionAria', 'Decommission {name}', { name: agentName(agent) })" @click="confirmDelete(agent)"><span aria-hidden="true">✕</span></button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>

    <!-- ── Funding Requests History ──────────────────────────────────────── -->
    <div class="funding-section" data-tour="mya-funding">
      <!-- A toggle is a button (keyboard, screen reader, its state said); it was a clickable div. -->
      <button type="button" class="funding-header" data-testid="mya-funding-toggle"
              :aria-expanded="showFundingHistory ? 'true' : 'false'" @click="showFundingHistory = !showFundingHistory">
        <span class="funding-glyph" aria-hidden="true">◎</span>
        {{ t('myAgentsView.actions.fundingRequests', 'FUNDING REQUESTS') }}
        <span v-if="!fundingHistoryFailed" class="funding-count">{{ fundingRequests.length }}</span>
        <span class="funding-toggle" aria-hidden="true">{{ showFundingHistory ? '▾' : '▸' }}</span>
      </button>
      <div v-if="showFundingHistory" class="funding-body">
        <div v-if="!hasActiveAgent" class="funding-note">
          {{ t('myAgentsView.funding.selectAgent', 'Select an agent first to view funding requests.') }}
        </div>
        <div v-else-if="fundingHistoryLoading" class="funding-note">{{ t('myAgentsView.funding.loading', 'Loading requests...') }}</div>
        <ReadFailedNotice v-else-if="fundingHistoryFailed" dense :retry="fetchFundingRequests" />
        <div v-else-if="fundingRequests.length === 0" class="funding-note">{{ t('myAgentsView.funding.empty', 'No funding requests yet.') }}</div>
        <div v-else class="funding-list">
          <div v-for="req in fundingRequests" :key="req.id" class="funding-item">
            <div class="funding-item-top">
              <span class="funding-item-amount">◎ {{ Number(req.amount).toLocaleString(appLocale()) }} {{ localCurrency }}</span>
              <span
                class="funding-item-status"
                :style="{ background: fundingStatusColor(req.status) + '20', color: fundingStatusColor(req.status), borderColor: fundingStatusColor(req.status) + '40' }"
              >{{ (req.status || 'unknown').toUpperCase() }}</span>
              <span class="funding-item-date">{{ formatDate(req.created_at) }}</span>
            </div>
            <div class="funding-item-reason">{{ (req.reason || '').slice(0, 80) }}{{ (req.reason || '').length > 80 ? '...' : '' }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── A2A Payment Tokens (Build #2, 2026-05-07) ──────────────────────── -->
    <PaymentTokensPanel
      :agent-did="authStore.activeAgent?.did || null"
      :has-agent-token="hasActiveAgent"
    />

    <!-- ── Cross-Frame Bridge panel UNMOUNTED (Commander, 2026-08-04): the
         bridge rail is not part of the current setup (FX triangle is the live
         cross-frame mechanism). Component + service kept — restore = re-add
         <BridgePanel :agent-did :has-agent-token /> here. ─────────────────── -->

    <!-- ── TEG Statement (Build #3, 2026-05-07) ────────────────────────────── -->
    <StatementPanel
      :agent-did="authStore.activeAgent?.did || null"
      :has-agent-token="hasActiveAgent"
    />

    <!-- ── Funding Request Modal ─────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showFundingModal" class="modal-overlay" @click.self="showFundingModal = false">
        <div class="modal-box modal-box--funding">
          <h3 class="modal-title modal-title--funding">{{ tp('myAgentsView.funding.modalTitle', 'Request {ccy} Funding', { ccy: localCurrency || '' }) }}</h3>

          <div v-if="!hasActiveAgent" class="funding-modal-note">
            <span class="funding-modal-note-icon">!</span>
            {{ t('myAgentsView.funding.noSession', 'No active agent session. Click an agent in your fleet and authenticate first, then request funding.') }}
          </div>

          <template v-else>
            <!-- Active Agent Display -->
            <div class="funding-field">
              <label class="funding-label">{{ t('myAgentsView.funding.requestingAgent', 'Requesting Agent') }}</label>
              <div style="padding: 8px 12px; background: rgba(var(--nc-primary-rgb),0.06); border: 1px solid rgba(var(--nc-primary-rgb),0.15); border-radius: 6px; font-size: 0.85rem;">
                <span style="color: #f9fafb; font-weight: 600;">{{ authStore.activeAgent?.name || t('myAgentsView.funding.activeAgentFallback', 'Active Agent') }}</span>
                <span style="color: #6b7280; font-size: 0.75rem; margin-left: 8px; font-family: monospace;">{{ authStore.activeAgent?.did?.slice(0, 25) }}...</span>
              </div>
              <span class="funding-hint">{{ t('myAgentsView.funding.agentHint', 'Funding will be sent to this agent. Switch agents in your fleet list to request for a different one.') }}</span>
              <span class="funding-hint" data-testid="funding-review-note">{{ t('myAgentsView.funding.reviewNote', 'A registry operator reviews every request; its state shows under FUNDING REQUESTS below.') }}</span>
            </div>

            <div class="funding-field">
              <label class="funding-label">{{ tp('myAgentsView.funding.amountLabel', 'Amount ({ccy})', { ccy: localCurrency || '' }) }}</label>
              <input
                v-model.number="fundingAmount"
                type="number"
                min="100"
                max="100000"
                step="100"
                class="funding-input"
                placeholder="1000"
              />
              <span class="funding-hint">{{ t('myAgentsView.funding.amountHint', 'Min: 100 · Max: 100,000') }}</span>
            </div>

            <div class="funding-field">
              <label class="funding-label">{{ t('myAgentsView.funding.reasonLabel', 'Reason') }}</label>
              <textarea
                v-model="fundingReason"
                class="funding-textarea"
                rows="3"
                :placeholder="t('myAgentsView.funding.reasonPlaceholder', 'Describe what the units are for...')"
                maxlength="500"
                :disabled="!hasActiveAgent"
              ></textarea>
              <span class="funding-hint">{{ tp('myAgentsView.funding.charCount', '{current}/500 characters (min 10)', { current: fundingReason.length }) }}</span>
            </div>

            <div v-if="fundingError" class="funding-error">{{ fundingError }}</div>
            <div v-if="!hasActiveAgent" class="funding-error" style="color: #fbbf24;">{{ t('myAgentsView.funding.noSessionError', 'Agent session not active. Go to your agent\'s profile and click "Authenticate" first.') }}</div>
            <div v-else-if="fundingAmount < 100 || fundingAmount > 100000" class="funding-error" style="color: #fbbf24;">{{ tp('myAgentsView.funding.amountRange', 'Amount must be between 100 and 100,000 {ccy}', { ccy: localCurrency || '' }) }}</div>
            <div v-else-if="fundingReason.trim().length < 10" class="funding-error" style="color: #fbbf24;">{{ tp('myAgentsView.funding.reasonMin', 'Reason must be at least 10 characters ({current}/10)', { current: fundingReason.trim().length }) }}</div>

            <div class="modal-actions">
              <button class="modal-btn modal-btn--cancel" @click="showFundingModal = false; fundingError = null; selectedFundingAgentDid = ''">{{ t('common.cancel', 'Cancel') }}</button>
              <button
                class="modal-btn modal-btn--funding-submit"
                :disabled="fundingSubmitting || !hasActiveAgent || fundingAmount < 100 || fundingAmount > 100000 || fundingReason.trim().length < 10"
                @click="submitFundingRequest"
              >
                {{ fundingSubmitting ? t('myAgentsView.funding.submitting', 'Submitting...') : t('myAgentsView.funding.submit', 'Submit Request') }}
              </button>
            </div>
          </template>
        </div>
      </div>
    </Teleport>

    <!-- ── Delete Confirm ─────────────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showDeleteDialog" class="modal-overlay" @click.self="showDeleteDialog = false">
        <div class="modal-box">
          <h3 class="modal-title">{{ t('myAgentsView.deleteModal.title', 'Confirm Decommission') }}</h3>
          <p class="modal-body">
            {{ tp('myAgentsView.deleteModal.body', 'Remove {name} from the fleet? This cannot be undone.', { name: agentName(agentToDelete) }) }}
          </p>
          <div class="modal-actions">
            <button class="modal-btn modal-btn--cancel" @click="showDeleteDialog = false">{{ t('common.cancel', 'Cancel') }}</button>
            <button class="modal-btn modal-btn--danger" @click="deleteAgent">{{ t('myAgentsView.deleteModal.confirm', 'Decommission') }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── Reset Credentials Confirmation ─────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showResetDialog" class="modal-overlay" @click.self="showResetDialog = false">
        <div class="modal-card" style="max-width: 480px;">
          <div class="modal-card-header">
            <h3 style="color: #ffa000; margin: 0; font-family: 'IBM Plex Mono', monospace; font-size: 1rem;">{{ t('myAgentsView.resetModal.title', 'Reset Credentials') }}</h3>
          </div>
          <div class="modal-card-body">
            <p
              style="color: #b0bec5; margin-bottom: 12px; font-size: 0.85rem;"
              v-html="t('myAgentsView.resetModal.body', { target: escapeHtml(agentToReset?.name || agentToReset?.did) })"
            />
            <div style="background: rgba(255,160,0,0.06); border: 1px solid rgba(255,160,0,0.2); border-radius: 6px; padding: 12px; margin-bottom: 16px;">
              <p
                style="color: #ffa000; font-size: 0.8rem; margin: 0;"
                v-html="t('myAgentsView.resetModal.warning', 'The current credentials will be <strong>permanently invalidated</strong>. Any systems using the old credentials will immediately lose access.')"
              />
            </div>
            <label style="display: block; color: #7a8a9a; font-size: 0.65rem; margin-bottom: 6px; letter-spacing: 0.1em; font-family: 'IBM Plex Mono', monospace;">
              {{ t('myAgentsView.resetModal.enterPasswordLabel', 'ENTER YOUR PASSWORD TO CONFIRM') }}
            </label>
            <input
              v-model="resetPassword"
              type="password"
              :placeholder="t('myAgentsView.resetModal.passwordPlaceholder', 'Your account password')"
              style="width: 100%; padding: 10px 12px; background: rgba(0,0,0,0.3); border: 1px solid rgba(var(--nc-primary-rgb),0.15); border-radius: 4px; color: #e0e8f0; font-size: 0.9rem; outline: none; box-sizing: border-box;"
              @keyup.enter="executeResetCredentials"
              autofocus
            />
            <p v-if="resetError" style="color: #f44336; font-size: 0.8rem; margin-top: 8px;">{{ resetError }}</p>
          </div>
          <div class="modal-card-footer" style="display: flex; gap: 10px; justify-content: flex-end;">
            <button class="modal-btn modal-btn--cancel" @click="showResetDialog = false" :disabled="resetLoading">{{ t('myAgentsView.resetModal.cancel', 'Cancel') }}</button>
            <button
              class="card-btn card-btn--warning"
              style="flex: 0; padding: 8px 20px;"
              @click="executeResetCredentials"
              :disabled="!resetPassword || resetLoading"
            >
              {{ resetLoading ? t('myAgentsView.resetModal.resetting', 'RESETTING...') : t('myAgentsView.resetModal.resetButton', 'RESET CREDENTIALS') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── New Credentials Display ────────────────────────────────────────── -->
    <Teleport to="body">
      <div v-if="showCredentialsDialog" class="modal-overlay">
        <div class="modal-card" style="max-width: 560px;">
          <div class="modal-card-header">
            <h3 style="color: var(--nc-primary); margin: 0; font-family: 'IBM Plex Mono', monospace; font-size: 1rem;">{{ t('myAgentsView.credsModal.title', 'New Credentials Generated') }}</h3>
          </div>
          <div class="modal-card-body">
            <div style="background: rgba(var(--nc-primary-rgb),0.04); border: 1px solid rgba(var(--nc-primary-rgb),0.12); border-radius: 6px; padding: 16px; margin-bottom: 12px;">
              <div style="margin-bottom: 12px;">
                <label style="color: #7a8a9a; font-size: 0.6rem; letter-spacing: 0.12em; display: block; margin-bottom: 4px; font-family: 'IBM Plex Mono', monospace;">{{ t('myAgentsView.credsModal.clientId', 'CLIENT ID') }}</label>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <code style="flex: 1; font-size: 0.8rem; color: var(--nc-primary); word-break: break-all; font-family: 'IBM Plex Mono', monospace;">{{ newCredentials?.client_id }}</code>
                  <button class="card-btn card-btn--primary" style="flex: 0; font-size: 0.6rem; padding: 4px 10px;" @click="copyToClipboard(newCredentials?.client_id || '', 'id')">
                    {{ copiedField === 'id' ? t('myAgentsView.credsModal.copied', 'COPIED') : t('myAgentsView.credsModal.copy', 'COPY') }}
                  </button>
                </div>
              </div>
              <div>
                <label style="color: #7a8a9a; font-size: 0.6rem; letter-spacing: 0.12em; display: block; margin-bottom: 4px; font-family: 'IBM Plex Mono', monospace;">{{ t('myAgentsView.credsModal.clientSecret', 'CLIENT SECRET') }}</label>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <code style="flex: 1; font-size: 0.75rem; color: #ffa000; word-break: break-all; font-family: 'IBM Plex Mono', monospace;">{{ newCredentials?.client_secret }}</code>
                  <button class="card-btn card-btn--warning" style="flex: 0; font-size: 0.6rem; padding: 4px 10px;" @click="copyToClipboard(newCredentials?.client_secret || '', 'secret')">
                    {{ copiedField === 'secret' ? t('myAgentsView.credsModal.copied', 'COPIED') : t('myAgentsView.credsModal.copy', 'COPY') }}
                  </button>
                </div>
              </div>
            </div>
            <div style="background: rgba(255,160,0,0.06); border: 1px solid rgba(255,160,0,0.15); border-radius: 6px; padding: 10px 14px;">
              <p style="color: #ffa000; font-size: 0.75rem; margin: 0;"
                 v-html="t('myAgentsView.credsModal.storeWarning', 'Store these credentials securely. They will <strong>NOT</strong> be shown again.')"
              ></p>
            </div>
          </div>
          <div class="modal-card-footer" style="display: flex; justify-content: flex-end;">
            <button class="card-btn card-btn--primary" style="flex: 0; padding: 8px 24px;" @click="closeCredentialsDialog">{{ t('myAgentsView.credsModal.done', 'DONE') }}</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- ── Add Credentials (paste existing) ─────────────────────────────────── -->
    <AddCredentialsModal
      v-if="agentForAddCreds"
      :show="showAddCredentials"
      :agent="agentForAddCreds"
      @close="showAddCredentials = false; agentForAddCreds = null"
      @saved="handleAddCredsSaved"
    />

    <!-- ── Bulk Credentials Import ──────────────────────────────────────────── -->
    <BulkCredentialsImportModal
      :show="showBulkImport"
      @close="showBulkImport = false"
      @imported="handleBulkImported"
    />

    </div><!-- /fleet-content -->
  </div>
    <!-- IRONKEY access modal: on the body, above the page's own layers (inside the page the STATEMENT bar drew over its
         backdrop) -->
    <Teleport to="body">
    <div v-if="accessDid" style="position:fixed;inset:0;background:rgba(2,6,23,.78);z-index:10050;display:flex;align-items:flex-start;justify-content:center;padding:5vh 1rem;overflow:auto" @click.self="accessDid = null">
      <!-- a dialog for assistive tech too (it was an anonymous div), named by its title; Escape closes it (useEscapeClose) -->
      <div role="dialog" aria-modal="true" aria-labelledby="mya-access-title" data-testid="mya-access-dialog"
           style="background:#0b1220;border:1px solid #1e293b;border-radius:14px;max-width:660px;width:100%;padding:1.2rem">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem;color:#e2e8f0;font-weight:600">
          <!-- name the agent whose leash this is — a nameless access panel invites editing the wrong one -->
          <span style="display:flex;flex-direction:column;gap:2px;min-width:0">
            <span id="mya-access-title">Agent Access<template v-if="accessAgentName"> · {{ accessAgentName }}</template></span>
            <span style="font-size:10px;font-weight:400;color:#8b97ab;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ accessDid }}</span>
          </span>
          <button type="button" :aria-label="t('common.close', 'Close')" style="background:none;border:none;color:#94a3b8;font-size:1.5rem;line-height:1;cursor:pointer;min-width:32px;min-height:32px" @click="accessDid = null"><span aria-hidden="true">×</span></button>
        </div>
        <AgentAccessPanel :agent-did="accessDid" mode="owner" />
      </div>
    </div>
    </Teleport>
</template>

<style scoped>
.fleet-root {
  min-height: 100vh;
  padding: 2rem 2.5rem;
  /* §pass50.4 — opaque background removed; DashboardLayout's <ViewAmbient> paints. */
  color: #e2e8f0;
  font-family: system-ui, -apple-system, sans-serif;
  position: relative;
  z-index: 1;
}
/* 2026-05-07: Wrap content so the ambient layer sits behind it. */
.fleet-content {
  position: relative;
  z-index: 1;
}
.fleet-header {
  display: flex; align-items: flex-end; gap: 2rem;
  margin-bottom: 2rem; flex-wrap: wrap;
}
.fleet-title-block { flex-shrink: 0; }
.fleet-eyebrow {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem; letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb),0.4); margin-bottom: 4px;
}
.fleet-title {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 2rem; font-weight: 700; letter-spacing: 0.1em;
  color: #e2e8f0; margin: 0; line-height: 1;
}
.fleet-subtitle {
  font-size: 0.78rem; color: rgba(148,163,184,0.5);
  margin-top: 4px; font-family: 'IBM Plex Mono', monospace;
}
.fleet-stats {
  display: flex; align-items: center; gap: 1.5rem;
  flex: 1; flex-wrap: wrap;
  background: rgba(var(--nc-primary-rgb),0.04);
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 8px; padding: 12px 20px;
}
.fleet-stat { text-align: center; }
/* §COCKPITDESK (2026-10-15), the camera: between the title and the buttons the stats bar wrapped to two lines and,
   bottom-aligned, stood above the title. On a wide screen it is a row of its own under them. */
@media (min-width: 900px) {
  .fleet-stats { order: 3; flex: 1 1 100%; justify-content: flex-start; }
  .fleet-header > .fleet-deploy-btn:first-of-type { margin-left: auto; }
}
.stat-label {
  display: block; font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; letter-spacing: 0.14em;
  color: rgba(148,163,184,0.4); margin-bottom: 2px;
}
.stat-value { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.9rem; font-weight: 600; }
.stat-avt { color: rgba(var(--nc-primary-rgb),0.9); }
.stat-staked { color: rgba(99,179,237,0.9); }
.stat-active { color: rgba(16,185,129,0.9); }
.stat-ping { color: rgba(148,163,184,0.6); }
.fleet-stat-divider { width: 1px; height: 28px; background: rgba(var(--nc-primary-rgb),0.1); }
.fleet-deploy-btn {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 20px; flex-shrink: 0;
  background: rgba(var(--nc-primary-rgb),0.12); border: 1px solid rgba(var(--nc-primary-rgb),0.35);
  border-radius: 6px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem; letter-spacing: 0.1em;
  color: rgba(var(--nc-primary-rgb),0.9); transition: all 0.2s ease;
}
.fleet-deploy-btn:hover { background: rgba(var(--nc-primary-rgb),0.2); border-color: rgba(var(--nc-primary-rgb),0.6); box-shadow: 0 0 20px rgba(var(--nc-primary-rgb),0.12); }
.fleet-deploy-btn--large { padding: 14px 32px; font-size: 0.9rem; margin-top: 20px; }
.deploy-icon { font-size: 1.1rem; line-height: 1; }
.fleet-controls { display: flex; gap: 1rem; align-items: center; margin-bottom: 1.5rem; flex-wrap: wrap; }
.fleet-search-wrap { position: relative; flex: 1; min-width: 220px; }
.search-icon { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: rgba(var(--nc-primary-rgb),0.4); font-size: 1.1rem; pointer-events: none; }
.fleet-search { width: 100%; padding: 9px 12px 9px 36px; background: rgba(255,255,255,0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.15); border-radius: 6px; color: #e2e8f0; font-size: 0.85rem; outline: none; transition: border-color 0.2s; }
.fleet-search:focus { border-color: rgba(var(--nc-primary-rgb),0.4); }
.fleet-search::placeholder { color: rgba(148,163,184,0.3); }
.fleet-filters { display: flex; align-items: center; gap: 0.75rem; flex-shrink: 0; }
.fleet-select { padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.15); border-radius: 6px; color: rgba(226,232,240,0.7); font-size: 0.8rem; outline: none; cursor: pointer; font-family: 'IBM Plex Mono', monospace; }
.fleet-toggle { display: inline-flex; align-items: center; gap: 0.4rem; padding: 8px 12px; background: rgba(255,255,255,0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.15); border-radius: 6px; color: rgba(226,232,240,0.75); font-size: 0.78rem; cursor: pointer; user-select: none; white-space: nowrap; }
.fleet-toggle:hover { border-color: rgba(var(--nc-primary-rgb),0.35); }
.fleet-toggle input { accent-color: rgb(var(--nc-primary-rgb)); cursor: pointer; margin: 0; }
.fleet-toggle-spin { display: inline-block; animation: fleet-spin 0.8s linear infinite; color: rgba(var(--nc-primary-rgb),0.8); }
@keyframes fleet-spin { to { transform: rotate(360deg); } }
.fleet-select option { background: #0a1628; }
.view-toggle { display: flex; border: 1px solid rgba(var(--nc-primary-rgb),0.15); border-radius: 6px; overflow: hidden; }
.view-btn { padding: 8px 12px; background: transparent; border: none; cursor: pointer; color: rgba(148,163,184,0.4); font-size: 1rem; transition: all 0.15s; }
.view-btn:hover { background: rgba(var(--nc-primary-rgb),0.05); color: rgba(var(--nc-primary-rgb),0.7); }
.view-btn--active { background: rgba(var(--nc-primary-rgb),0.1); color: rgba(var(--nc-primary-rgb),0.9); }
/* §28 polish (2026-05-15) — Customize/Details mode toggle. Wider buttons
   because of the label + icon (vs the symbol-only grid/list toggle). */
.view-toggle--mode {
  border-color: rgba(var(--nc-primary-rgb), 0.32);
  box-shadow: 0 0 0 1px rgba(var(--nc-primary-rgb), 0.08), inset 0 0 12px -8px rgba(var(--nc-primary-rgb), 0.25);
}
/* §28 polish 7 (2026-05-15) — Per-card flare collapse chevron. Compact pill:
   icon + chevron only by default (28x20). Label reveals on hover via inline
   width transition. Title attr also surfaces the action for screen readers. */
.card-flare-collapse-row { margin: 0.4rem 0 0.05rem; display: flex; justify-content: flex-end; }
.card-flare-collapse-btn {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 7px;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  font-size: 0.60rem; font-weight: 600;
  letter-spacing: 0.05em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.75);
  background: rgba(var(--nc-primary-rgb), 0.05);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.14s ease, border-color 0.14s ease, color 0.14s ease, box-shadow 0.14s ease;
  height: 20px;
}
.card-flare-collapse-btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.12);
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  color: rgba(var(--nc-primary-rgb), 1);
  box-shadow: 0 0 10px -2px rgba(var(--nc-primary-rgb), 0.3);
}
.card-flare-collapse-btn--collapsed {
  color: rgba(148, 163, 184, 0.55);
  background: rgba(148, 163, 184, 0.04);
  border-color: rgba(148, 163, 184, 0.15);
}
.card-flare-collapse-btn--collapsed:hover {
  color: rgba(var(--nc-primary-rgb), 0.9);
  border-color: rgba(var(--nc-primary-rgb), 0.35);
}
.card-flare-chevron { font-size: 0.8rem; line-height: 1; }
/* Label is hidden by default; pops in on hover. Title attribute is the
   accessible fallback for keyboard / screen-reader users. */
.card-flare-collapse-label {
  white-space: nowrap;
  max-width: 0;
  overflow: hidden;
  opacity: 0;
  transition: max-width 0.18s ease, opacity 0.16s ease, margin 0.16s ease;
  margin: 0;
}
.card-flare-collapse-btn:hover .card-flare-collapse-label,
.card-flare-collapse-btn:focus-visible .card-flare-collapse-label {
  max-width: 160px;
  opacity: 1;
  margin: 0 2px;
}
.view-toggle--mode .view-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 14px; font-size: 0.78rem; font-weight: 600;
  letter-spacing: 0.04em;
}
.view-toggle--mode .view-btn-label {
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
  text-transform: uppercase; font-size: 0.7rem;
}
.view-toggle--mode .view-btn--active {
  background: rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(var(--nc-primary-rgb), 1);
  box-shadow: inset 0 0 12px -4px rgba(var(--nc-primary-rgb), 0.35);
}
/* A phone (the camera, 2026-10-13, Pixel 7): the header stacks (the title, the stats across the width, the buttons), where
   side by side the stats were squeezed into a narrow column beside a bottom-aligned title; the filters wrap, where
   "Hide sub-agents" ran past the screen. */
@media (max-width: 640px) {
  .fleet-header { flex-direction: column; align-items: stretch; gap: 1rem; margin-bottom: 1.5rem; }
  .fleet-stats { justify-content: space-around; gap: 0.75rem 1rem; padding: 10px 12px; }
  .fleet-stat-divider { display: none; }
  .fleet-search-wrap { flex-basis: 100%; min-width: 0; }
  .fleet-filters { flex-wrap: wrap; flex-shrink: 1; gap: 0.5rem; }
}
/* Keep label visible down to very small viewports — it's the only cue
   that the icons mean "customize / details" for new users. (Was 540 px, where on a phone the Details half, which had
   no icon, showed an empty box; the filters wrap since the camera's pass of 2026-10-13, so the labels fit a phone.) */
@media (max-width: 380px) {
  .view-toggle--mode .view-btn-label { display: none; }
  .view-toggle--mode .view-btn { padding: 8px 10px; }
}
.fleet-loading { display: flex; align-items: center; gap: 12px; padding: 60px; justify-content: center; color: rgba(148,163,184,0.5); font-size: 0.85rem; font-family: 'IBM Plex Mono', monospace; }
.loading-ring { width: 20px; height: 20px; border-radius: 50%; border: 2px solid rgba(var(--nc-primary-rgb),0.15); border-top-color: rgba(var(--nc-primary-rgb),0.7); animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.fleet-empty { text-align: center; padding: 80px 20px; }
.fleet-empty--small { padding: 40px 20px; }
.empty-glyph { font-size: 3rem; color: rgba(var(--nc-primary-rgb),0.15); margin-bottom: 16px; }
.empty-title { font-family: 'IBM Plex Mono', monospace; font-size: 1.1rem; color: rgba(226,232,240,0.4); margin-bottom: 8px; }
.empty-sub { color: rgba(148,163,184,0.4); font-size: 0.85rem; }
.fleet-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 1.25rem; margin-bottom: 2rem; }
.fleet-grid--orphan { margin-top: 0; }
/* §15 — per-agent variant picker styling. */
.card-flare-avatar {
  flex-shrink: 0;
  margin-right: 2px;
}
.card-variant-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}

/* §21 (2026-05-13) — FLARE action row. Lives between the DID and the
   variant pills. Shows the bearer pill (for agents that wear the dev's
   flare) OR a "Move flare here" CTA (for agents that COULD wear it). */
.card-flare-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
  min-height: 22px;
}
.card-flare-bearer-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 3px 9px;
  border-radius: 3px;
  /* Gold-ish bearer accent — universally readable across all flare tiers */
  color: rgba(254, 243, 199, 0.98);
  background: rgba(120, 53, 15, 0.42);
  border: 1px solid rgba(252, 211, 77, 0.6);
  box-shadow: 0 0 14px -4px rgba(252, 211, 77, 0.55);
}
.card-flare-bearer-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(254, 215, 170, 1);
  box-shadow: 0 0 6px rgba(254, 215, 170, 0.85);
  animation: card-flare-bearer-pulse 2.4s ease-in-out infinite;
}
@keyframes card-flare-bearer-pulse {
  0%, 100% { opacity: 0.9; transform: scale(1); }
  50%      { opacity: 1;   transform: scale(1.18); }
}
.card-flare-move-btn {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 3px;
  color: rgba(196, 181, 253, 0.95);
  background: rgba(91, 33, 158, 0.18);
  border: 1px solid rgba(167, 139, 250, 0.42);
  cursor: pointer;
  transition: background 0.18s, border-color 0.18s, color 0.18s, transform 0.12s;
}
.card-flare-move-btn:hover:not(:disabled) {
  color: rgba(232, 213, 255, 1);
  background: rgba(91, 33, 158, 0.32);
  border-color: rgba(196, 181, 253, 0.85);
  transform: translateY(-1px);
}
.card-flare-move-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
.card-flare-error {
  margin: 4px 0 0 0;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: rgba(248, 113, 113, 0.92);
}

/* §23 (2026-05-14) — DUAL-SLOT FLARE rows on agent cards.
   Two rows: CORNER (slot 1) + ENCIRCLE (slot 2). Same vertical rhythm
   as the legacy single row, but each is tinted to its slot color
   (cyan for corner, violet for encirclement). */
.card-flare-row--slot {
  margin-top: 6px;
}
.card-flare-row--slot:first-of-type {
  margin-top: 8px;
}
.card-flare-row--corner .card-variant-label {
  color: rgba(var(--nc-primary-rgb), 0.85);
}
.card-flare-row--enc .card-variant-label {
  color: rgba(167, 139, 250, 0.92);
}

/* Slot-specific BEARER pill — replaces the generic gold one for per-slot
   rows. Cyan for corner, violet for encirclement. */
.card-flare-bearer-pill--corner {
  color: rgba(var(--nc-primary-rgb), 1);
  background: rgba(var(--nc-primary-rgb), 0.14);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.55);
  box-shadow: 0 0 12px -4px rgba(var(--nc-primary-rgb), 0.55);
}
.card-flare-bearer-pill--corner .card-flare-bearer-dot {
  background: rgba(var(--nc-primary-rgb), 1);
  box-shadow: 0 0 6px rgba(var(--nc-primary-rgb), 0.85);
}
.card-flare-bearer-pill--enc {
  color: rgba(196, 181, 253, 1);
  background: rgba(91, 33, 158, 0.28);
  border: 1px solid rgba(167, 139, 250, 0.6);
  box-shadow: 0 0 12px -4px rgba(167, 139, 250, 0.55);
}
.card-flare-bearer-pill--enc .card-flare-bearer-dot {
  background: rgba(196, 181, 253, 1);
  box-shadow: 0 0 6px rgba(196, 181, 253, 0.85);
}

/* Inline ✕ "remove this slot" button inside the bearer pill */
.card-flare-slot-clear {
  display: inline-flex; align-items: center; justify-content: center;
  width: 14px; height: 14px;
  margin-left: 2px;
  border: 1px solid currentColor;
  border-radius: 50%;
  background: transparent;
  color: inherit;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  line-height: 1;
  cursor: pointer;
  opacity: 0.55;
  transition: opacity 0.18s, background 0.18s, transform 0.18s;
}
.card-flare-slot-clear:hover:not(:disabled) {
  opacity: 1;
  background: rgba(255, 255, 255, 0.06);
  transform: scale(1.08);
}
.card-flare-slot-clear:disabled {
  opacity: 0.3; cursor: not-allowed;
}

/* Slot-specific Equip CTA — tinted per slot */
.card-flare-move-btn--corner {
  color: rgba(var(--nc-primary-rgb), 1);
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.42);
}
.card-flare-move-btn--corner:hover:not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border-color: rgba(var(--nc-primary-rgb), 0.85);
  color: rgba(var(--nc-primary-rgb), 1);
}
.card-flare-move-btn--enc {
  color: rgba(196, 181, 253, 0.95);
  background: rgba(91, 33, 158, 0.18);
  border-color: rgba(167, 139, 250, 0.42);
}
.card-flare-move-btn--enc:hover:not(:disabled) {
  color: rgba(232, 213, 255, 1);
  background: rgba(91, 33, 158, 0.32);
  border-color: rgba(196, 181, 253, 0.85);
}

/* Muted "no slot earned yet" placeholder text */
.card-flare-no-slot {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  letter-spacing: 0.08em;
  color: rgba(148, 163, 184, 0.42);
  font-style: italic;
}

/* Admin per-agent corner-icon picker row — subtle gold accent so admins
   can spot it instantly among the regular shadow-style picker. */
.card-variant-row--admin .card-variant-label {
  color: rgba(252, 211, 77, 0.95);
}
.card-variant-pill--admin {
  color: rgba(254, 243, 199, 0.92);
  border-color: rgba(252, 211, 77, 0.32);
  background: rgba(120, 53, 15, 0.12);
}
.card-variant-pill--admin:hover:not(:disabled) {
  border-color: rgba(252, 211, 77, 0.7);
  background: rgba(120, 53, 15, 0.22);
}
.card-variant-pill--admin.card-variant-pill--active {
  color: rgb(254, 243, 199);
  border-color: rgba(252, 211, 77, 0.95);
  background: rgba(120, 53, 15, 0.42);
  box-shadow: 0 0 12px -2px rgba(252, 211, 77, 0.55);
}

/* §21 — DEFAULT reset pill for the variant picker. Visually distinct from
   the variant ID pills (uses a subtle outline rather than a filled chip)
   so it reads as a control, not another variant. */
.card-variant-pill--reset {
  background: transparent !important;
  color: rgba(167, 139, 250, 0.85);
  border: 1px dashed rgba(167, 139, 250, 0.55);
  font-style: italic;
}
.card-variant-pill--reset:hover:not(:disabled) {
  color: rgba(232, 213, 255, 1);
  border-color: rgba(196, 181, 253, 0.95);
  background: rgba(91, 33, 158, 0.12) !important;
}

/* §15.4 — per-agent avatar URL editor row. Same visual language as the
   variant pill row but uses cyan/primary accents. Single-line layout that
   wraps gracefully on mobile. */
.card-avatar-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
  min-height: 22px;
}
.card-avatar-display {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 10px;
  color: rgba(148, 163, 184, 0.82);
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.card-avatar-input {
  flex: 1;
  min-width: 140px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 3px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.35);
  background: rgba(0, 0, 0, 0.4);
  color: rgba(255, 255, 255, 0.92);
  outline: none;
  transition: border-color 0.18s;
}
.card-avatar-input:focus {
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.85);
}
.card-avatar-btn {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 3px;
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.25);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.05);
  color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.85);
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s, color 0.18s;
}
.card-avatar-btn:hover:not(:disabled) {
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.7);
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.12);
  color: rgba(255, 255, 255, 1);
}
.card-avatar-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.card-avatar-btn--save {
  border-color: rgba(74, 222, 128, 0.5);
  background: rgba(74, 222, 128, 0.08);
  color: rgba(167, 243, 208, 1);
}
.card-avatar-btn--save:hover:not(:disabled) {
  border-color: rgba(74, 222, 128, 1);
  background: rgba(74, 222, 128, 0.18);
}
.card-avatar-btn--cancel {
  border-color: rgba(248, 113, 113, 0.4);
  background: rgba(248, 113, 113, 0.06);
  color: rgba(252, 165, 165, 0.95);
}
.card-avatar-error {
  width: 100%;
  font-size: 11px;
  color: rgba(248, 113, 113, 0.95);
  margin: 4px 0 0;
}
.card-variant-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.14em;
  color: rgba(167, 139, 250, 0.85);
  text-transform: uppercase;
  margin-right: 4px;
}
.card-variant-pill {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 9px;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  padding: 3px 8px;
  border-radius: 3px;
  border: 1px solid rgba(167, 139, 250, 0.2);
  background: rgba(15, 5, 25, 0.65);
  color: rgba(180, 160, 220, 0.7);
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s, color 0.18s;
}
.card-variant-pill:hover:not(:disabled) {
  border-color: rgba(196, 181, 253, 0.6);
  color: rgba(196, 181, 253, 1);
  background: rgba(91, 33, 158, 0.18);
}
.card-variant-pill:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.card-variant-pill--active {
  border-color: rgba(196, 181, 253, 0.85);
  color: rgb(196, 181, 253);
  background: rgba(91, 33, 158, 0.28);
  box-shadow: 0 0 8px -2px rgba(91, 33, 158, 0.65);
}

/* §24 (2026-05-14) — Per-variant single-occupancy hint state.
   Pill shows "→ AGENT_X" suffix when this variant is currently equipped
   on a DIFFERENT agent of the same dev. Clicking moves it. Visually:
   amber/gold accent so it reads as "in use, click to claim." */
.card-variant-pill--elsewhere {
  border-color: rgba(251, 191, 36, 0.42);
  background: rgba(60, 40, 0, 0.22);
  color: rgba(252, 211, 77, 0.85);
}
.card-variant-pill--elsewhere:hover:not(:disabled) {
  border-color: rgba(251, 191, 36, 0.75);
  background: rgba(80, 55, 0, 0.32);
  color: rgba(254, 215, 0, 1);
}
.card-variant-pill--elsewhere.card-variant-pill--active {
  /* Edge case: active here AND on another agent shouldn't really happen
     after server-side single-occupancy, but be defensive. */
  border-color: rgba(196, 181, 253, 0.85);
  background: rgba(91, 33, 158, 0.28);
  color: rgb(196, 181, 253);
}

/* Tiny "→ AGENT_X" suffix inside the pill — caps at 12 chars + ellipsis */
.card-variant-pill-hint {
  display: inline-block;
  margin-left: 4px;
  padding-left: 4px;
  border-left: 1px solid currentColor;
  opacity: 0.8;
  font-size: 8.5px;
  letter-spacing: 0.06em;
  text-transform: none;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: bottom;
  white-space: nowrap;
}

/* Admin (corner-icon) elsewhere state — gold-on-gold (already gold themed) */
.card-variant-pill--admin.card-variant-pill--elsewhere {
  border-color: rgba(251, 191, 36, 0.5);
  background: rgba(60, 40, 0, 0.32);
  color: rgba(254, 215, 100, 0.85);
}
.card-variant-pill--admin.card-variant-pill--elsewhere:hover:not(:disabled) {
  border-color: rgba(251, 191, 36, 0.85);
  background: rgba(80, 55, 0, 0.45);
  color: rgba(254, 230, 130, 1);
}

.agent-card { background: #0d1626; border: 1px solid rgba(var(--nc-primary-rgb),0.12); border-radius: 8px; padding: 16px; display: flex; flex-direction: column; gap: 10px; transition: all 0.2s ease; }
.agent-card:hover { border-color: rgba(var(--nc-primary-rgb),0.28); box-shadow: 0 4px 24px rgba(0,0,0,0.3), 0 0 0 1px rgba(var(--nc-primary-rgb),0.08); transform: translateY(-1px); }
.agent-card--orphan { opacity: 0.45; border-color: rgba(148,163,184,0.08); background: rgba(13,22,38,0.5); }
.agent-card--orphan:hover { opacity: 0.65; }
/* §V0064 P2 — AGORA equity chip on the agent card */
.card-equity-chip {
  display: inline-flex; align-items: center; gap: 6px; align-self: flex-start;
  margin-top: 2px; cursor: pointer;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.62rem; letter-spacing: 0.06em; font-weight: 700;
  color: #10b981; background: rgba(16,185,129,0.08);
  border: 1px solid rgba(16,185,129,0.4); border-radius: 99px; padding: 3px 10px;
  transition: background 0.15s, box-shadow 0.15s;
}
.card-equity-chip:hover { background: rgba(16,185,129,0.18); box-shadow: 0 0 12px rgba(16,185,129,0.3); }
.card-equity-chip :deep(svg) { width: 12px; height: 12px; }
.card-equity-sym { font-weight: 800; }
.card-equity-px { color: rgba(226,232,240,0.7); font-weight: 600; }
.card-equity-halt { color: #f59e0b; font-size: 0.55rem; letter-spacing: 0.1em; }
.card-status-bar { display: flex; align-items: center; gap: 6px; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.status-label { font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; letter-spacing: 0.12em; color: rgba(148,163,184,0.82); }
.card-age { margin-left: auto; font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; color: rgba(148,163,184,0.82); }
.card-name { font-size: 1rem; font-weight: 600; color: rgba(226,232,240,0.9); margin: 0 0 4px; cursor: pointer; transition: color 0.15s; }
.card-wallet-chip { font-size: 0.58rem; letter-spacing: 0.12em; font-weight: 700; padding: 0.1rem 0.4rem; border-radius: 999px; margin-left: 0.4rem; vertical-align: middle;
  color: var(--nc-primary, #00e5ff); border: 1px solid rgba(var(--nc-primary-rgb, 0,229,255), 0.5); background: rgba(var(--nc-primary-rgb, 0,229,255), 0.1); }
.card-name:hover { color: rgba(var(--nc-primary-rgb),0.9); }
.card-name-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.card-name-row .card-name { margin: 0; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-name--dim { color: rgba(148,163,184,0.4); cursor: default; }
.card-name--dim:hover { color: rgba(148,163,184,0.4); }
.card-did { display: flex; align-items: center; gap: 6px; font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; color: rgba(148,163,184,0.82); word-break: break-all; }
.did-copy { background: none; border: none; cursor: pointer; color: rgba(var(--nc-primary-rgb),0.4); font-size: 0.75rem; padding: 0 2px; transition: color 0.15s; flex-shrink: 0; }
.did-copy:hover { color: rgba(var(--nc-primary-rgb),0.8); }
.card-desc { font-size: 0.75rem; color: rgba(148,163,184,0.82); margin: 0; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.card-desc--dim { opacity: 0.5; }
.card-financials { display: flex; gap: 12px; }
.fin-block { flex: 1; }
.fin-label { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.55rem; letter-spacing: 0.1em; color: rgba(148,163,184,0.82); margin-bottom: 2px; }
.fin-value { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.8rem; font-weight: 600; color: rgba(226,232,240,0.7); }
.fin-liquid { color: rgba(var(--nc-primary-rgb),0.85); }
.fin-staked { color: rgba(99,179,237,0.8); }
.card-rep { display: flex; align-items: center; gap: 6px; }
.rep-icon { color: rgba(251,191,36,0.6); font-size: 0.85rem; }
.rep-tier { font-size: 0.75rem; font-weight: 600; font-family: 'IBM Plex Mono', monospace; }
.rep-tier--sm { font-size: 0.7rem; }
.rep-score { font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; color: rgba(148,163,184,0.35); margin-left: 2px; }
/* the row wraps whole buttons, where a narrow card broke "ADD KEYS" and "RESET KEYS" over two lines (the camera,
   2026-10-13) */
.card-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: auto; padding-top: 4px; }
.card-actions--split { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: start; }
.card-actions-main { display: flex; flex-wrap: wrap; gap: 8px; min-width: 0; }
.card-btn { flex: 1 1 auto; white-space: nowrap; padding: 7px 8px; border-radius: 5px; cursor: pointer; font-size: 0.7rem; font-family: 'IBM Plex Mono', monospace; letter-spacing: 0.08em; font-weight: 600; transition: all 0.15s ease; border: 1px solid transparent; }
.card-btn--primary { background: rgba(var(--nc-primary-rgb),0.1); border-color: rgba(var(--nc-primary-rgb),0.3); color: rgba(var(--nc-primary-rgb),0.9); }
.card-btn--primary:hover { background: rgba(var(--nc-primary-rgb),0.2); border-color: rgba(var(--nc-primary-rgb),0.5); }
.card-btn--secondary { background: rgba(255,255,255,0.03); border-color: rgba(255,255,255,0.08); color: rgba(148,163,184,0.88); }
.card-btn--secondary:hover { background: rgba(255,255,255,0.06); color: rgba(226,232,240,0.8); }
.card-btn--danger { flex: 0; padding: 7px 12px; background: rgba(239,68,68,0.06); border-color: rgba(239,68,68,0.2); color: rgba(239,68,68,0.6); }
.card-btn--danger:hover { background: rgba(239,68,68,0.12); color: rgba(239,68,68,0.9); }
.card-btn--configure { background: rgba(99,179,237,0.1); border-color: rgba(99,179,237,0.25); color: rgba(99,179,237,0.8); }
.card-btn--configure:hover { background: rgba(99,179,237,0.2); }
/* "ADD KEYS" — paste-existing-credentials CTA, distinct from "RESET KEYS" (regenerate). */
.card-btn--accent {
  background: rgba(167,139,250,0.1);
  border-color: rgba(167,139,250,0.3);
  color: rgba(167,139,250,0.9);
}
.card-btn--accent:hover { background: rgba(167,139,250,0.2); border-color: rgba(167,139,250,0.5); }
/* Per-card credentials-status pill (sits next to the status indicator). */
.creds-pill {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 1px 7px;
  margin-left: 8px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; font-weight: 600;
  letter-spacing: 0.1em;
  border-radius: 9999px;
  border: 1px solid transparent;
}
.creds-pill-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: currentColor;
}
.creds-pill--ok   { color: rgba(34,197,94,0.85);  border-color: rgba(34,197,94,0.3);  background: rgba(34,197,94,0.06); }
.creds-pill--miss { color: rgba(167,139,250,0.85); border-color: rgba(167,139,250,0.3); background: rgba(167,139,250,0.06); }
/* Top-bar IMPORT KEYS button (alongside DEPLOY + REQUEST AVT) */
.fleet-deploy-btn--import {
  background: rgba(167,139,250,0.08);
  border: 1px solid rgba(167,139,250,0.3);
  color: rgba(167,139,250,0.9);
}
.fleet-deploy-btn--import:hover {
  background: rgba(167,139,250,0.18);
  border-color: rgba(167,139,250,0.5);
}
.orphan-section { margin-top: 0.5rem; }
.orphan-header { display: flex; align-items: center; gap: 8px; font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; letter-spacing: 0.14em; color: rgba(148,163,184,0.3); margin-bottom: 1rem; }
.orphan-glyph { font-size: 0.9rem; }
.orphan-count { background: rgba(148,163,184,0.1); border-radius: 4px; padding: 1px 6px; font-size: 0.6rem; }
.fleet-table-wrap { overflow-x: auto; }
.fleet-table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
.fleet-table th { font-family: 'IBM Plex Mono', monospace; font-size: 0.6rem; letter-spacing: 0.12em; color: rgba(148,163,184,0.35); padding: 8px 12px; text-align: left; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08); }
.fleet-table td { padding: 12px 12px; border-bottom: 1px solid rgba(255,255,255,0.03); }
.table-row { cursor: pointer; transition: background 0.1s; }
.table-row:hover { background: rgba(var(--nc-primary-rgb),0.03); }
.table-row--orphan { opacity: 0.45; cursor: default; }
.td-name { font-weight: 500; color: rgba(226,232,240,0.85); display: inline-flex; align-items: center; gap: 6px; }
.td-name-text { display: inline-block; }
.td-did { font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; color: rgba(148,163,184,0.4); display: flex; align-items: center; gap: 6px; }
.td-avt { font-family: 'IBM Plex Mono', monospace; color: rgba(var(--nc-primary-rgb),0.8); }
.td-staked { font-family: 'IBM Plex Mono', monospace; color: rgba(99,179,237,0.7); }
.td-time { font-family: 'IBM Plex Mono', monospace; color: rgba(148,163,184,0.4); font-size: 0.75rem; }
.td-actions { display: flex; gap: 6px; align-items: center; }
.tbl-btn { padding: 4px 10px; background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; color: rgba(148,163,184,0.6); font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; cursor: pointer; transition: all 0.15s; }
.tbl-btn:hover { background: rgba(255,255,255,0.06); color: rgba(226,232,240,0.8); }
.tbl-btn--danger { border-color: rgba(239,68,68,0.2); color: rgba(239,68,68,0.6); }
.tbl-btn--danger:hover { background: rgba(239,68,68,0.1); color: rgba(239,68,68,0.9); }
.modal-overlay { position: fixed; inset: 0; z-index: 99999; background: rgba(0,0,0,0.7); display: flex; align-items: center; justify-content: center; }
.modal-box { background: #0d1626; border: 1px solid rgba(239,68,68,0.25); border-radius: 10px; padding: 28px; max-width: 440px; width: 90%; box-shadow: 0 20px 60px rgba(0,0,0,0.6); }
.modal-title { font-family: 'IBM Plex Mono', monospace; font-size: 1rem; font-weight: 600; color: #f26464; margin: 0 0 12px; }
.modal-body { color: rgba(148,163,184,0.7); font-size: 0.85rem; line-height: 1.5; margin: 0 0 20px; }
.modal-agent-name { color: rgba(226,232,240,0.85); }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; }
.modal-btn { padding: 8px 20px; border-radius: 6px; cursor: pointer; font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; transition: all 0.15s; }
.modal-btn--cancel { background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.1); color: rgba(148,163,184,0.9); }
.modal-btn--cancel:hover { background: rgba(255,255,255,0.07); color: rgba(226,232,240,0.8); }
.modal-btn--danger { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); color: #f26464; }
.modal-btn--danger:hover { background: rgba(239,68,68,0.2); border-color: rgba(239,68,68,0.5); }

/* ── Funding Button ──────────────────────────────────────────────────────── */
.fleet-deploy-btn--funding {
  background: rgba(99,179,237,0.12); border-color: rgba(99,179,237,0.35);
  color: rgba(99,179,237,0.9);
}
.fleet-deploy-btn--funding:hover { background: rgba(99,179,237,0.2); border-color: rgba(99,179,237,0.6); box-shadow: 0 0 20px rgba(99,179,237,0.12); }

/* ── Funding History Section ─────────────────────────────────────────────── */
.funding-section { margin-top: 2rem; }
/* 0.5 read 2.9:1 on the page (axe color-contrast); 0.8 reads about 5.8:1. */
.funding-header { display: flex; align-items: center; gap: 8px; width: 100%; background: none; border: 0; text-align: left; font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; letter-spacing: 0.14em; color: rgba(99,179,237,0.8); cursor: pointer; padding: 10px 0; user-select: none; transition: color 0.15s; }
.funding-header:hover, .funding-header:focus-visible { color: rgba(99,179,237,1); }
.funding-header:focus-visible { outline: 1px solid rgba(99,179,237,0.6); outline-offset: 2px; }
.funding-glyph { font-size: 0.9rem; }
.funding-count { background: rgba(99,179,237,0.1); border-radius: 4px; padding: 1px 6px; font-size: 0.6rem; color: rgba(99,179,237,0.9); }
.funding-toggle { margin-left: auto; font-size: 0.7rem; color: rgba(148,163,184,0.4); }
.funding-body { margin-top: 0.5rem; }
.funding-note { font-size: 0.8rem; color: rgba(148,163,184,0.5); font-family: 'IBM Plex Mono', monospace; padding: 12px 16px; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 6px; }
.funding-list { display: flex; flex-direction: column; gap: 8px; }
.funding-item { background: rgba(255,255,255,0.02); border: 1px solid rgba(99,179,237,0.1); border-radius: 6px; padding: 12px 16px; }
.funding-item-top { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.funding-item-amount { font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; font-weight: 600; color: rgba(99,179,237,0.9); }
.funding-item-status { font-family: 'IBM Plex Mono', monospace; font-size: 0.58rem; letter-spacing: 0.1em; padding: 2px 8px; border-radius: 4px; border: 1px solid; font-weight: 600; }
.funding-item-date { margin-left: auto; font-family: 'IBM Plex Mono', monospace; font-size: 0.65rem; color: rgba(148,163,184,0.4); }
.funding-item-reason { margin-top: 6px; font-size: 0.75rem; color: rgba(148,163,184,0.5); line-height: 1.4; }

/* ── Funding Modal ───────────────────────────────────────────────────────── */
.modal-box--funding { border-color: rgba(99,179,237,0.25); max-width: 480px; }
.modal-title--funding { color: rgba(99,179,237,0.9); }
.funding-field { margin-bottom: 16px; }
.funding-label { display: block; font-family: 'IBM Plex Mono', monospace; font-size: 0.68rem; letter-spacing: 0.1em; color: rgba(148,163,184,0.6); margin-bottom: 6px; }
.funding-input { width: 100%; padding: 10px 14px; background: rgba(255,255,255,0.03); border: 1px solid rgba(99,179,237,0.2); border-radius: 6px; color: #e2e8f0; font-size: 0.9rem; font-family: 'IBM Plex Mono', monospace; outline: none; transition: border-color 0.2s; box-sizing: border-box; }
.funding-input:focus { border-color: rgba(99,179,237,0.5); }
.funding-textarea { width: 100%; padding: 10px 14px; background: rgba(255,255,255,0.03); border: 1px solid rgba(99,179,237,0.2); border-radius: 6px; color: #e2e8f0; font-size: 0.82rem; font-family: system-ui, sans-serif; outline: none; resize: vertical; transition: border-color 0.2s; box-sizing: border-box; }
.funding-textarea:focus { border-color: rgba(99,179,237,0.5); }
.funding-textarea::placeholder { color: rgba(148,163,184,0.3); }
.funding-hint { display: block; margin-top: 4px; font-size: 0.65rem; color: rgba(148,163,184,0.35); font-family: 'IBM Plex Mono', monospace; }
.funding-error { background: rgba(239,68,68,0.08); border: 1px solid rgba(239,68,68,0.2); border-radius: 6px; padding: 8px 12px; color: rgba(239,68,68,0.9); font-size: 0.78rem; margin-bottom: 16px; }
.modal-btn--funding-submit { background: rgba(99,179,237,0.12); border: 1px solid rgba(99,179,237,0.35); color: rgba(99,179,237,0.9); }
.modal-btn--funding-submit:hover:not(:disabled) { background: rgba(99,179,237,0.22); border-color: rgba(99,179,237,0.6); }
.modal-btn--funding-submit:disabled { opacity: 0.4; cursor: not-allowed; }
.funding-modal-note { background: rgba(251,191,36,0.08); border: 1px solid rgba(251,191,36,0.2); border-radius: 6px; padding: 14px 16px; color: rgba(251,191,36,0.9); font-size: 0.82rem; line-height: 1.5; display: flex; gap: 10px; align-items: flex-start; }
.funding-modal-note-icon { flex-shrink: 0; width: 20px; height: 20px; border-radius: 50%; background: rgba(251,191,36,0.15); display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.7rem; color: rgba(251,191,36,0.9); }
.funding-select { cursor: pointer; appearance: auto; }
.funding-select option { background: #0a1628; color: #e2e8f0; }

/* ── Reset Credentials Button & Modals ───────────────────────────────────── */
.card-btn--warning {
  background: rgba(255, 160, 0, 0.1); border: 1px solid rgba(255, 160, 0, 0.3);
  color: #ffa000; flex: 0; padding: 7px 10px;
}
.card-btn--warning:hover { background: rgba(255, 160, 0, 0.2); border-color: #ffa000; }
.card-btn--warning:disabled { opacity: 0.5; cursor: not-allowed; }
.modal-card {
  background: #0f1118; border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 8px; padding: 0; width: 90%; box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}
.modal-card-header { padding: 16px 20px; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08); }
.modal-card-body { padding: 20px; }
.modal-card-footer { padding: 12px 20px; border-top: 1px solid rgba(var(--nc-primary-rgb),0.08); }
/* §COCKPITDESK (2026-10-15), the phone camera's small-target readings (WCAG 2.5.8, 24 x 24 CSS px): a finger's target grows, the glyph keeps its size */
@media (pointer: coarse), (max-width: 640px) {
  .view-btn { min-width: 32px; min-height: 32px; }
  .did-copy { min-width: 24px; min-height: 24px; display: inline-flex; align-items: center; justify-content: center; }
  .card-flare-collapse-btn { min-height: 24px; }
}
</style>
