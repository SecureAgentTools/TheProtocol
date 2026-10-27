<!--
  §pass50.7 + §pass50.8 — QuickAgentModal.vue
  30-second agent onboarding. ONE screen, ONE input (name), ONE button.

  Reuses existing backend:
    POST /onboard/bootstrap/request-token  →  bootstrap_token
    POST /onboard/create_agent             →  {agent_did, client_id, client_secret}

  After successful create:
    1. Credentials stored (via agents.create()).
    2. auth.authenticateAsAgent() mints agent JWT.
    3. localStorage.activeAgentId set + auth.activeAgent populated.
    4. Agent-required routes (/contracts /disputes /staking /attestations)
       unlock without a page refresh.

  §pass50.8 — All emoji glyphs (tag icons, error icon, close glyph) replaced
  with mdi icons via the project's local Icon.vue map per
  `feedback_no_emojis_in_ui` memory + project_icon_vue_pattern.

  Open via uiStore.openQuickAgentModal(). Mount once globally in DashboardLayout.
-->
<script setup lang="ts">
import { fundingDoor, agentsDoor, isPocketMode } from '@/services/uiMode'
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { agentApi } from '@/services/api/agents'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { useViewport } from '@/composables/useViewport'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useAgentStore } from '@/stores/agents'
import { developerApi } from '@/services/api/developers'   // ⚠ PLURAL — developer.ts has no balances rail
import { displayAmount } from '@/services/chat/cards'
import { apiClient } from '@/services/api/client'
import { walletTags, walletSentence, walletHowItWorks, moveFundsDoor, isWalletAgent, firstAgentIsWallet } from '@/services/walletAgent'
import { reputationBondApi, type BondConfig } from '@/services/api/reputationBond'
import { copyText } from '@/utils/copyText'
import { agentSlug } from '@/services/agentSlug'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const uiStore = useUIStore()
const auth = useAuthStore()
const router = useRouter()
const viewport = useViewport()

// ── State ───────────────────────────────────────────────────────────────────
const name = ref('')
const description = ref('')
const selectedTags = ref<string[]>([])
const submitting = ref(false)
const error = ref('')
const phase = ref<'form' | 'creating' | 'success'>('form')
const { t, tp } = useI18n()
const { localCurrency, config: registryConfig } = useRegistryConfig()
// §BAFIN: the sheet names Locks only where this registry says a lock position can be opened here; an unread
// config names none (EU and ASIA run STAKING_ENABLED=false)
const stakingOn = computed(() => registryConfig?.value?.staking_enabled === true)
// §ONBOARDQOL P1 (2026-09-02) — what the new agent HOLDS, read from the ledger after
// creation. Three states, never folded: unread (say nothing about money), read and
// zero (name the wall and open the funding door), read and positive (name the amount).
// A failed read is silence, not "0" — the batch rail answers `{balance:'0', error}` on
// failure, so `error` is read first (§RAT).
const held = ref<string | null>(null)
const heldKnown = ref(false)
const heldIsZero = computed(() => heldKnown.value && Number(held.value) === 0)
const createdAgent = ref<{
  did: string
  name: string
  client_id?: string
  client_secret?: string
} | null>(null)
const nameInputRef = ref<HTMLInputElement | null>(null)
const credsCopied = ref(false)

// §WALLETAGENT (2026-09-02) — the FIRST agent is the wallet agent (his framing). Decided only
// after our OWN read of the account's agents: a 0-agent claim is never made from a missing list.
const walletMode = ref(false)
const createdWasWallet = ref(false)
const hasWalletAgent = computed(() => useAgentStore().agents.some(a => isWalletAgent(a)))

// §REPBOND — the birth-flow bond door
const bondCfg = ref<BondConfig | null>(null)
// §FESUITE (V0578): a failed config read hid the bond door, which is exactly what a registry that asks no bond shows:
// the owner of a new provider was not told a bond is needed. The read's failure is its own state.
const bondCfgFailed = ref(false)
const bondDone = ref(false)
const bondBusy = ref(false)
const bondError = ref('')
const walletForBond = computed(() => {
  const did = createdAgent.value?.did
  return useAgentStore().agents.find((a: any) => isWalletAgent(a) && a.did !== did) || null
})
async function loadBondCfg() {
  bondDone.value = false; bondError.value = ''; bondCfgFailed.value = false
  try { bondCfg.value = await reputationBondApi.getConfig() } catch { bondCfg.value = null; bondCfgFailed.value = true }
}
async function _bond(run: () => Promise<any>) {
  bondBusy.value = true; bondError.value = ''
  try { await run(); bondDone.value = true; void readHeld(createdAgent.value?.did || '') }
  catch (e: any) { bondError.value = e?.response?.data?.detail?.message || e?.response?.data?.detail || e?.message || 'Bond failed' }
  finally { bondBusy.value = false }
}
function bondFromWallet() {
  const did = createdAgent.value?.did, w = walletForBond.value
  if (!did || !w) return
  return _bond(() => reputationBondApi.bondFromWallet(did, w.did))
}
function bondFromSelf() {
  const did = createdAgent.value?.did
  if (!did) return
  return _bond(() => reputationBondApi.bondFromWallet(did, did))
}
function bondBackstop() {
  const did = createdAgent.value?.did
  if (!did) return
  return _bond(() => reputationBondApi.bondBackstop(did))
}
const walletLines = computed(() => walletSentence(t))
const walletHow = computed(() => walletHowItWorks(t))
async function decideWalletMode() {
  const st = useAgentStore()
  if (!st.agents.length) { try { await st.fetchMyAgents() } catch { /* the store owns its error state */ } }
  // §FESUITE (V0577): only a read that answered "none" makes this the first (wallet) agent; a failed read is not none
  walletMode.value = firstAgentIsWallet(st.agents, st.myAgentsFailed)
  if (walletMode.value) {
    if (!name.value.trim()) name.value = t('quickAgent.walletName', 'Wallet')
    if (!description.value.trim()) description.value = t('quickAgent.walletDesc', "Wallet agent: holds and moves this account's funds; reusable by any agent attached later.")
  }
}
/* Decision 2026-09-02: a wallet answers no calls, so it is not listed in Discover. Best effort;
 * the agent page's listing toggle flips it any time, and a failure is named on the sheet. */
const walletListing = ref<'unlisted' | 'unchanged' | null>(null)
async function markWalletUnlisted(did: string) {
  try { await apiClient.patch(`/agent-cards/${encodeURIComponent(did)}/listing`, { unlisted: true }); walletListing.value = 'unlisted' }
  catch { walletListing.value = 'unchanged' }
}

// §pass50.8 — emoji icons → mdi names (verified mapped in Icon.vue local map)
const TAG_OPTIONS = [
  { value: 'chatbot',  label: 'Chatbot',  icon: 'mdi:robot-happy-outline' },
  { value: 'oracle',   label: 'Oracle',   icon: 'mdi:telescope' },
  { value: 'scraper',  label: 'Scraper',  icon: 'mdi:web' },
  { value: 'utility',  label: 'Utility',  icon: 'mdi:tools' },
  { value: 'service',  label: 'Service',  icon: 'mdi:hand-coin-outline' },
  { value: 'research', label: 'Research', icon: 'mdi:test-tube' },
]

const isOpen = computed(() => uiStore.showQuickAgentModal)
const canSubmit = computed(() => name.value.trim().length >= 2 && !submitting.value)
const trimmedName = computed(() => name.value.trim())
// Quick onboarding (2026-10-09): the hint shows the handle agentApi.create sends (one rule, services/agentSlug.ts); the
// old preview was the old formula and promised "café-bot-#1" for a card that is stored as "cafe-bot-1".
const slugPreview = computed(() => (trimmedName.value ? agentSlug(trimmedName.value) : 'agent-name'))

// §pass51 — lazily-loaded top featured templates surfaced as a 4th onboarding shape
const featuredTemplates = ref<any[]>([])
const featuredLoading = ref(false)

async function loadFeaturedTemplates() {
  if (featuredTemplates.value.length > 0) return
  featuredLoading.value = true
  try {
    // Direct fetch (avoids axios interceptors that might add auth headers
    // and trip the public endpoint's no-auth contract)
    const resp = await fetch('/api/v1/bundles/marketplace/featured?limit=3')
    if (resp.ok) {
      const data = await resp.json()
      featuredTemplates.value = (data?.featured || []).slice(0, 3)
    }
  } catch (_) { /* non-fatal — just no templates shown */ }
  finally { featuredLoading.value = false }
}

function pickTemplate(tpl: any) {
  // Close the quick modal; route to /bundles/:id where the Fork CTA fires the
  // full fork flow + credentials surface.
  uiStore.closeQuickAgentModal()
  router.push({ name: 'bundle-detail', params: { bundleId: tpl.id } }).catch(() => {
    // fallback if route name differs
    router.push(`/bundles/${tpl.id}`).catch(() => {})
  })
}

// ── Lifecycle ───────────────────────────────────────────────────────────────
watch(isOpen, async (open) => {
  if (open) {
    name.value = ''
    description.value = ''
    selectedTags.value = []
    error.value = ''
    phase.value = 'form'
    createdAgent.value = null
    credsCopied.value = false
    // §pass51 — fetch featured templates in background; render when ready
    loadFeaturedTemplates()
    await nextTick()
    nameInputRef.value?.focus()
    // §WALLETAGENT — decide the framing AFTER the reset above (the reset ran after our prefill
    // when this lived in its own watcher and blanked the name — measured, pv4 W1).
    createdWasWallet.value = false; walletListing.value = null
    void decideWalletMode()
  }
})

function toggleTag(value: string) {
  const idx = selectedTags.value.indexOf(value)
  if (idx >= 0) {
    selectedTags.value.splice(idx, 1)
  } else if (selectedTags.value.length < 3) {
    selectedTags.value.push(value)
  }
}

function close() {
  if (submitting.value) return
  uiStore.closeQuickAgentModal()
}

function onScrimClick(e: MouseEvent) {
  if ((e.target as HTMLElement)?.classList?.contains('qa-scrim')) close()
}

function onKey(e: KeyboardEvent) {
  if (!isOpen.value) return
  if (e.key === 'Escape' && phase.value !== 'creating') {
    e.preventDefault()
    close()
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKey)
  // §pass50.7 — testability hook
  ;(window as any).openQuickAgent = () => uiStore.openQuickAgentModal()
})
// §FESUITE (the leave sweep): the layouts that mount this modal come and go, and each mount added a key listener that
// stayed on the window for the tab's life; it goes with the modal now
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))

// ── Core flow ───────────────────────────────────────────────────────────────
async function createAgent() {
  if (!canSubmit.value) return
  error.value = ''
  submitting.value = true
  phase.value = 'creating'
  try {
    const agent = await agentApi.create({
      name: trimmedName.value,
      description: description.value.trim() || (walletMode.value ? t('quickAgent.walletDesc', "Wallet agent: holds and moves this account's funds; reusable by any agent attached later.") : `Quick-onboarded agent: ${trimmedName.value}`),
      capabilities: walletMode.value ? walletTags() : selectedTags.value,
    })

    const cred = agentCredentialsStore.getCredentials(agent.did)
    if (!cred?.client_id || !cred?.client_secret) {
      throw new Error('Credentials not returned by backend — cannot auto-login. The agent was created; configure it manually from My Agents.')
    }

    const agentForAuth: any = {
      did: agent.did,
      name: agent.name,
      client_id: cred.client_id,
      client_secret: cred.client_secret,
    }
    const ok = await auth.authenticateAsAgent(agentForAuth)
    if (!ok) {
      throw new Error('Agent created but auto-login failed. Try selecting it from the agent picker.')
    }
    auth.setActiveAgentFromToken(agentForAuth, (auth as any).agentToken)
    // §WALLETAGENT — persisted exactly as switchAgent persists it, so the acting agent survives a reload.
    try { localStorage.setItem('activeAgentId', agent.did) } catch { /* storage unavailable */ }
    createdWasWallet.value = walletMode.value
    if (walletMode.value) void markWalletUnlisted(agent.did)

    createdAgent.value = {
      did: agent.did,
      name: agent.name,
      client_id: cred.client_id,
      client_secret: cred.client_secret,
    }
    phase.value = 'success'
    void loadBondCfg()  // §REPBOND — the door's amount + mode
    // §ONBOARDQOL P1 — tell the surfaces behind the modal (the dashboard's first-run CTA,
    // its fleet card) that the population changed, and refresh the ONE agent store that
    // every list reads. Before this, the modal said "is live" over a dashboard that still
    // said "No agents yet" until F5 (D14).
    uiStore.noteAgentCreated()
    useAgentStore().fetchMyAgents().catch(() => { /* the store owns its own error state */ })
    void readHeld(agent.did)

    try { await auth.loadAvailableAgents?.() } catch (_) { /* best-effort */ }
  } catch (e: any) {
    console.error('[QuickAgentModal] create failed', e)
    error.value = e?.response?.data?.detail || e?.message || 'Agent creation failed. Try again or use the full AgentForge view.'
    phase.value = 'form'
  } finally {
    submitting.value = false
  }
}

function goToMyAgents() {
  uiStore.closeQuickAgentModal()
  router.push(agentsDoor()).catch(() => { /* ignore */ })   // §PHONESTART — Pocket's agents tab on a phone
}

/** §ONBOARDQOL P2 — the funding door: My Agents opens its REQUEST modal on `?fund=1`,
 *  the same modal its own button opens. One rail, one modal, a second entrance. */
function goToFunding() {
  uiStore.closeQuickAgentModal()
  router.push(fundingDoor()).catch(() => { /* ignore */ })   // §PHONESTART — Pocket home's REQUEST on a phone
}
/** §WALLETAGENT — a newer agent gets its first funds from the wallet: the ONE send door, prefilled. */
function goToMoveFunds() {
  const did = createdAgent.value?.did
  uiStore.closeQuickAgentModal()
  if (did) router.push(moveFundsDoor(did)).catch(() => { /* ignore */ })
}

async function readHeld(did: string) {
  held.value = null; heldKnown.value = false
  try {
    const raw: any = await developerApi.getAgentBalancesBatch([did])
    const b = (raw?.balances || raw || {})[did] || {}
    if (b.error) return
    const liquid = b.liquid_balance ?? b.balance
    if (liquid === undefined || liquid === null) return
    held.value = displayAmount(String(liquid)) || String(liquid)
    heldKnown.value = true
  } catch { /* unread ⇒ the sheet says nothing about money */ }
}

function goToAgentForge() {
  uiStore.closeQuickAgentModal()
  router.push({ name: 'agent-forge' }).catch(() =>
    router.push({ name: 'agent-builder' }).catch(() => router.push('/onboarding')))
}

function shortDid(did: string): string {
  if (!did) return ''
  return did.length > 40 ? `${did.slice(0, 30)}…${did.slice(-6)}` : did
}

// Quick onboarding (2026-10-09): "Copied" only after the copy happened. The write was not awaited, so a browser with no
// clipboard API (or one that refused it) showed "Copied to clipboard" over credentials that are shown once.
async function copyCreds() {
  if (!createdAgent.value) return
  const block = `Agent DID: ${createdAgent.value.did}
Client ID: ${createdAgent.value.client_id}
Client Secret: ${createdAgent.value.client_secret}
Created: ${new Date().toISOString()}`
  if (await copyText(block)) {
    credsCopied.value = true
    setTimeout(() => { credsCopied.value = false }, 1800)
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="qa-fade">
      <div
        v-if="isOpen"
        class="qa-scrim"
        role="dialog"
        :aria-label="phase === 'success' ? 'Agent created' : 'Quick onboard agent'"
        @click="onScrimClick"
      >
        <Transition name="qa-pop">
          <div
            v-if="isOpen"
            class="qa-modal"
            :class="{ 'is-mobile': viewport.isSmallPhone.value, 'is-success': phase === 'success' }"
            @click.stop
          >
            <!-- Top accent rail — colored band tied to the active theme primary -->
            <div class="qa-rail" aria-hidden="true"></div>

            <!-- ── Header ────────────────────────────────────────────────── -->
            <header class="qa-head">
              <div class="qa-head-l">
                <div class="qa-eyebrow">
                  <span class="qa-dot"></span>
                  {{ phase === 'success' ? (createdWasWallet ? t('quickAgent.walletLiveEyebrow', 'WALLET AGENT LIVE') : 'AGENT LIVE') : (walletMode ? t('quickAgent.walletEyebrow', 'YOUR WALLET AGENT') : 'QUICK ONBOARD') }}
                </div>
                <h2 class="qa-title">
                  <template v-if="phase === 'success' && createdWasWallet">
                    {{ createdAgent?.name }} <span class="qa-title-accent">{{ t('quickAgent.walletLiveTitle', 'is your wallet agent') }}</span>
                  </template>
                  <template v-else-if="phase === 'success'">
                    {{ createdAgent?.name }} <span class="qa-title-accent">is live</span>
                  </template>
                  <template v-else-if="walletMode">
                    {{ t('quickAgent.walletTitle', 'Create your wallet agent') }}
                  </template>
                  <template v-else>
                    Deploy an agent in <span class="qa-title-accent">30 seconds</span>
                  </template>
                </h2>
                <p class="qa-subtitle" v-if="phase !== 'success' && walletMode" data-testid="qa-wallet-lead">{{ walletLines.join(' ') }}</p>
                <p class="qa-subtitle" v-else-if="phase !== 'success'">
                  We'll generate the cryptographic identity, A2A v1.0 card, and a runnable bundle. Defaults are sensible.
                  Need every dial? <a href="#" @click.prevent="goToAgentForge">Open AgentForge &rsaquo;</a>
                </p>
                <p class="qa-subtitle" v-else data-testid="qa-success-sub" :data-held="heldKnown ? (heldIsZero ? 'zero' : 'some') : 'unread'">
                  {{ t('quickAgent.successLead', "You're authenticated as this agent right now.") }}
                  <template v-if="heldIsZero">
                    {{ tp('quickAgent.holdsNothing', 'It holds 0 {ccy}: on this registry a new agent starts empty, so a paid call needs funding first.', { ccy: localCurrency || '' }) }}
                    <a href="#" class="qa-fund-door" data-testid="qa-fund-door" @click.prevent="goToFunding">{{ tp('quickAgent.fundDoor', 'Request {ccy} &rsaquo;', { ccy: localCurrency || '' }) }}</a>
                  </template>
                  <template v-else-if="heldKnown">
                    {{ tp('quickAgent.holdsSome', 'It holds {amt} {ccy}, and paid calls draw on that balance.', { amt: held, ccy: localCurrency || '' }) }}
                  </template>
                  {{ isPocketMode()
                    ? (stakingOn ? t('quickAgent.unlockedPocket', 'Send, Lock and OurChat are yours to use now.') : t('quickAgent.unlockedPocketPlain', 'Send and OurChat are yours to use now.'))
                    : (stakingOn ? t('quickAgent.unlocked', 'Agent-required pages (Contracts, Disputes, Locks, Attestations) just unlocked.') : t('quickAgent.unlockedPlain', 'Agent-required pages (Contracts, Disputes, Attestations) just unlocked.')) }}
                </p>
                <details v-if="phase === 'success' && createdWasWallet" class="qa-how" data-testid="qa-wallet-how" open>
                  <summary>{{ t('quickAgent.walletHowTitle', 'How your wallet agent works') }}</summary>
                  <ul><li v-for="(l, i) in walletHow" :key="i">{{ l }}</li></ul>
                  <p class="qa-how-note" :data-listing="walletListing || 'pending'">{{ walletListing === 'unchanged' ? t('quickAgent.walletListingUnchanged', 'Listing unchanged: it is still visible in Discover; hide it from its page if you like.') : t('quickAgent.walletUnlistedNote', 'Not listed in Discover: it answers no calls. List it from its page when an agent is attached.') }}</p>
                </details>
                <p v-else-if="phase === 'success' && hasWalletAgent" class="qa-subtitle">
                  <a href="#" class="qa-fund-door" data-testid="qa-move-door" @click.prevent="goToMoveFunds">{{ t('quickAgent.moveDoor', 'Move funds from your wallet agent ›') }}</a>
                </p>
                <!-- §REPBOND (2026-09-05) — the birth-flow door: the bond a provider needs, funded
                     from the wallet agent (his flow), from this agent's own balance, or by the
                     treasury's demonstration backstop while the registry allows it. -->
                <div v-if="phase === 'success' && !createdWasWallet && bondCfg && bondCfg.mode !== 'off'" class="qa-bond" data-testid="qa-bond-door" :data-bond="bondDone ? 'done' : 'open'">
                  <template v-if="bondDone">
                    <p class="qa-subtitle">{{ tp('quickAgent.bondDone', 'Reputation bond locked: {amt} {ccy} held in escrow. This agent can provide services here.', { amt: bondCfg.amount, ccy: bondCfg.currency }) }}</p>
                  </template>
                  <template v-else>
                    <!-- §FESUITE: the frame releases a PART at maturity (maturity.releases_percent); "released back once it
                         matures" promised all of it -->
                    <p v-if="bondCfg.maturity?.releases_percent != null" class="qa-subtitle">{{ tp('quickAgent.bondLeadPartial', 'Providing services here asks for a reputation bond of {amt} {ccy}, held in escrow by the registry; once this agent matures, {pct}% of it goes back to its funder.', { amt: bondCfg.amount, ccy: bondCfg.currency, pct: bondCfg.maturity.releases_percent }) }}</p>
                    <p v-else class="qa-subtitle">{{ tp('quickAgent.bondLeadHeld', 'Providing services here asks for a reputation bond of {amt} {ccy}, held in escrow by the registry.', { amt: bondCfg.amount, ccy: bondCfg.currency }) }}</p>
                    <div class="qa-bond-actions">
                      <button v-if="walletForBond" type="button" class="qa-bond-btn" :disabled="bondBusy" data-testid="qa-bond-wallet" @click="bondFromWallet">{{ tp('quickAgent.bondFromWallet', 'Bond from {name}', { name: walletForBond.name || 'wallet' }) }}</button>
                      <button v-else-if="heldKnown && Number(held) >= Number(bondCfg.amount)" type="button" class="qa-bond-btn" :disabled="bondBusy" data-testid="qa-bond-self" @click="bondFromSelf">{{ t('quickAgent.bondFromSelf', "Bond from this agent's balance") }}</button>
                      <button v-if="bondCfg.treasury_backstop" type="button" class="qa-bond-btn qa-bond-btn--ghost" :disabled="bondBusy" data-testid="qa-bond-backstop" @click="bondBackstop">{{ t('quickAgent.bondBackstop', 'Demonstration: bond from the treasury') }}</button>
                    </div>
                    <p v-if="!walletForBond && !(heldKnown && Number(held) >= Number(bondCfg.amount))" class="qa-how-note" data-testid="qa-bond-need">{{ tp('quickAgent.bondNeed', 'You need {amt} {ccy} in a wallet agent, or in this agent, to place the bond.', { amt: bondCfg.amount, ccy: bondCfg.currency }) }}</p>
                    <p v-if="bondCfg.treasury_backstop" class="qa-how-note">{{ t('quickAgent.bondBackstopNote', 'Demonstration: the treasury underwrites the bond for now. It is planned that the bond comes out of your genesis grant or your income; a backstopped bond pays nothing back.') }}</p>
                    <p v-if="bondError" class="qa-how-note qa-bond-error" data-testid="qa-bond-error">{{ bondError }}</p>
                  </template>
                </div>
                <ReadFailedNotice v-else-if="phase === 'success' && !createdWasWallet && bondCfgFailed" dense data-testid="qa-bond-unread"
                  :text="t('quickAgent.bondUnread', 'Whether this registry asks a provider for a reputation bond could not be read just now.')" :retry="loadBondCfg" />
              </div>
              <button
                v-if="phase !== 'creating'"
                type="button"
                class="qa-close"
                :aria-label="phase === 'success' ? 'Close — keep agent active' : 'Cancel'"
                :title="phase === 'success' ? 'Close (agent stays active)' : 'Cancel'"
                @click="close"
              >
                <Icon name="mdi:close" />
              </button>
            </header>

            <!-- ── Form phase ────────────────────────────────────────────── -->
            <section v-if="phase === 'form'" class="qa-body">
              <!-- §pass51 — top featured templates as a 4th onboarding shape -->
              <div v-if="featuredTemplates.length > 0" class="qa-templates">
                <div class="qa-templates-head">
                  <span class="qa-templates-eyebrow">FORK FROM TEMPLATE</span>
                  <span class="qa-templates-sub">Start from a proven sovereign pattern instead</span>
                </div>
                <div class="qa-templates-grid">
                  <button
                    v-for="tpl in featuredTemplates"
                    :key="tpl.id"
                    type="button"
                    class="qa-tpl-chip"
                    @click="pickTemplate(tpl)"
                  >
                    <span class="qa-tpl-name">{{ tpl.name.replace(/^Sovereign Pattern\s*[—-]\s*/i, '') }}</span>
                    <span v-if="tpl.category" class="qa-tpl-cat">{{ tpl.category }}</span>
                    <Icon name="mdi:chevron-right" class="qa-tpl-arrow" />
                  </button>
                </div>
                <div class="qa-templates-divider"><span>or build from scratch</span></div>
              </div>

              <label class="qa-field">
                <span class="qa-label">Agent name <span class="qa-req">*</span></span>
                <input
                  ref="nameInputRef"
                  v-model="name"
                  type="text"
                  class="qa-input"
                  placeholder="e.g., Pricing Oracle"
                  maxlength="60"
                  :disabled="submitting"
                  @keydown.enter="createAgent"
                />
                <span class="qa-hint">Becomes <code>did:theprotocol:&lt;uuid&gt;</code> with humanReadableId <code>{{ slugPreview }}</code></span>
              </label>

              <label class="qa-field">
                <span class="qa-label">Description <span class="qa-opt">optional</span></span>
                <input
                  v-model="description"
                  type="text"
                  class="qa-input"
                  placeholder="One sentence: what does it do?"
                  maxlength="120"
                  :disabled="submitting"
                  @keydown.enter="createAgent"
                />
              </label>

              <div v-if="!walletMode" class="qa-field">
                <span class="qa-label">Capability tags <span class="qa-opt">pick up to 3</span></span>
                <div class="qa-tags">
                  <button
                    v-for="t in TAG_OPTIONS"
                    :key="t.value"
                    type="button"
                    class="qa-tag"
                    :class="{ 'is-active': selectedTags.includes(t.value), 'is-disabled': !selectedTags.includes(t.value) && selectedTags.length >= 3 }"
                    :disabled="submitting || (!selectedTags.includes(t.value) && selectedTags.length >= 3)"
                    @click="toggleTag(t.value)"
                  >
                    <Icon :name="t.icon" class="qa-tag-icon" />
                    <span>{{ t.label }}</span>
                    <Icon v-if="selectedTags.includes(t.value)" name="mdi:check" class="qa-tag-check" />
                  </button>
                </div>
              </div>

              <p v-if="error" class="qa-error" role="alert">
                <Icon name="mdi:alert" class="qa-error-icon" />
                <span>{{ error }}</span>
              </p>
            </section>

            <!-- ── Creating phase ────────────────────────────────────────── -->
            <section v-else-if="phase === 'creating'" class="qa-body qa-body--center">
              <div class="qa-spinner" aria-hidden="true">
                <div class="qa-spinner-ring"></div>
                <div class="qa-spinner-pulse"></div>
              </div>
              <div class="qa-creating-text">
                <div class="qa-creating-step">Requesting bootstrap token…</div>
                <div class="qa-creating-step is-fade2">Generating cryptographic identity…</div>
                <div class="qa-creating-step is-fade3">Registering agent card…</div>
                <div class="qa-creating-step is-fade4">Authenticating as agent…</div>
              </div>
            </section>

            <!-- ── Success phase ─────────────────────────────────────────── -->
            <section v-else class="qa-body">
              <div class="qa-success-hero">
                <div class="qa-success-check" aria-hidden="true">
                  <Icon name="mdi:check-circle" />
                </div>
              </div>

              <div class="qa-success-summary">
                <div class="qa-success-tile">
                  <span class="qa-success-tile-label">Agent name</span>
                  <span class="qa-success-tile-value">{{ createdAgent?.name }}</span>
                </div>
                <div class="qa-success-tile">
                  <span class="qa-success-tile-label">Decentralized identifier</span>
                  <code class="qa-success-tile-value qa-mono">{{ shortDid(createdAgent?.did || '') }}</code>
                </div>
              </div>

              <details class="qa-creds-block">
                <summary>
                  <Icon name="mdi:key" class="qa-creds-icon" />
                  Show credentials <span class="qa-creds-sub">(saved automatically to this browser)</span>
                </summary>
                <div class="qa-creds-grid">
                  <span class="qa-cred-label">Client ID</span>
                  <code class="qa-cred-value">{{ createdAgent?.client_id }}</code>
                  <span class="qa-cred-label">Client Secret</span>
                  <code class="qa-cred-value qa-cred-secret">{{ createdAgent?.client_secret }}</code>
                </div>
                <button type="button" class="qa-copy" @click="copyCreds">
                  <Icon :name="credsCopied ? 'mdi:check' : 'mdi:content-copy'" />
                  <span>{{ credsCopied ? 'Copied to clipboard' : 'Copy as a block' }}</span>
                </button>
                <p class="qa-creds-note" data-testid="qa-creds-note">
                  {{ t('quickAgent.credsNote', 'These credentials let your agent prove its identity. This browser keeps them so the agent stays signed in after a reload. Lost the secret? Issue a new pair with Reset credentials, in Quick onboarding or My Agents.') }}
                </p>
              </details>
            </section>

            <!-- ── Footer ────────────────────────────────────────────────── -->
            <footer class="qa-foot">
              <template v-if="phase === 'form'">
                <button type="button" class="qa-btn qa-btn--ghost" :disabled="submitting" @click="close">Cancel</button>
                <button
                  type="button"
                  class="qa-btn qa-btn--primary"
                  :disabled="!canSubmit"
                  @click="createAgent"
                >
                  <Icon name="mdi:rocket-launch" class="qa-btn-icon" />
                  <span>Create agent</span>
                </button>
              </template>
              <template v-else-if="phase === 'creating'">
                <span class="qa-foot-hint">Generating identity… ~5s</span>
              </template>
              <template v-else>
                <button type="button" class="qa-btn qa-btn--ghost" @click="goToAgentForge">Open AgentForge &rsaquo;</button>
                <button type="button" class="qa-btn qa-btn--ghost" @click="goToMyAgents">My Agents &rsaquo;</button>
                <button type="button" class="qa-btn qa-btn--primary" @click="close">Done</button>
              </template>
            </footer>
          </div>
        </Transition>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.qa-scrim {
  position: fixed; inset: 0; z-index: 10090;
  background: radial-gradient(ellipse at center, rgba(2, 6, 12, 0.78) 0%, rgba(0, 0, 0, 0.88) 100%);
  backdrop-filter: blur(8px) saturate(1.2);
  -webkit-backdrop-filter: blur(8px) saturate(1.2);
  display: flex; align-items: center; justify-content: center;
  padding: 1.5rem;
  font-family: 'IBM Plex Mono', 'Fira Code', monospace;
}

.qa-modal {
  position: relative;
  width: 100%; max-width: 580px;
  background:
    linear-gradient(180deg, rgba(14,24,40,0.97) 0%, rgba(8,14,24,0.99) 100%);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28);
  border-radius: 12px;
  box-shadow:
    0 32px 96px rgba(0, 0, 0, 0.78),
    0 0 0 1px rgba(var(--nc-primary-rgb), 0.06),
    0 0 80px rgba(var(--nc-primary-rgb), 0.10),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
  color: #e8eaed;
  display: flex; flex-direction: column;
  overflow: hidden;
  max-height: 92vh;
}
.qa-modal.is-mobile { max-width: 100%; border-radius: 12px 12px 0 0; align-self: flex-end; max-height: 94vh; }
.qa-modal.is-success {
  border-color: rgba(0, 255, 136, 0.38);
  box-shadow:
    0 32px 96px rgba(0, 0, 0, 0.78),
    0 0 0 1px rgba(0, 255, 136, 0.08),
    0 0 100px rgba(0, 255, 136, 0.14),
    inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

/* Top accent rail — thin colored band that ties the modal to the active theme */
.qa-rail {
  height: 2px;
  background: linear-gradient(90deg,
    transparent 0%,
    var(--nc-primary, #00d2d2) 22%,
    var(--nc-primary-bright, #00e8e8) 50%,
    var(--nc-primary, #00d2d2) 78%,
    transparent 100%);
  opacity: 0.85;
  filter: drop-shadow(0 0 4px rgba(var(--nc-primary-rgb), 0.45));
}
.qa-modal.is-success .qa-rail {
  background: linear-gradient(90deg, transparent 0%, #00ff88 22%, #36ffa8 50%, #00ff88 78%, transparent 100%);
  filter: drop-shadow(0 0 4px rgba(0,255,136,0.55));
}

/* ── Header ─────────────────────────────────────────────────────────────── */
.qa-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem;
  padding: 1.5rem 1.6rem 1.1rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  position: relative;
}
.qa-head::after {
  content: '';
  position: absolute; left: 1.6rem; right: 1.6rem; bottom: -1px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.22), transparent);
}
.qa-head-l { min-width: 0; flex: 1; }
.qa-eyebrow {
  display: inline-flex; align-items: center; gap: 0.5rem;
  font-size: 0.6rem; letter-spacing: 0.22em; color: rgba(var(--nc-primary-rgb), 0.9);
  font-weight: 800; text-transform: uppercase; margin-bottom: 0.7rem;
}
.qa-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--nc-primary, #00d2d2);
  box-shadow: 0 0 10px rgba(var(--nc-primary-rgb), 0.7), 0 0 2px rgba(var(--nc-primary-rgb), 0.9);
  animation: qa-pulse 2.4s ease-in-out infinite;
}
.qa-modal.is-success .qa-dot { background: #00ff88; box-shadow: 0 0 10px rgba(0,255,136,0.7), 0 0 2px rgba(0,255,136,0.9); }
@keyframes qa-pulse { 0%,100% { opacity: 0.7; transform: scale(1); } 50% { opacity: 1; transform: scale(1.1); } }
@media (prefers-reduced-motion: reduce) { .qa-dot { animation: none; } }

.qa-title {
  font-size: 1.52rem; font-weight: 700; line-height: 1.18; margin: 0; color: #fff;
  letter-spacing: -0.01em;
}
.qa-title-accent {
  color: var(--nc-primary, #00d2d2);
  text-shadow: 0 0 18px rgba(var(--nc-primary-rgb), 0.35);
}
.qa-modal.is-success .qa-title-accent { color: #00ff88; text-shadow: 0 0 18px rgba(0,255,136,0.45); }
.qa-subtitle {
  font-size: 0.82rem; color: #99a5b3; line-height: 1.55; margin: 0.55rem 0 0 0;
}
.qa-subtitle a {
  color: var(--nc-primary); text-decoration: none;
  border-bottom: 1px dashed rgba(var(--nc-primary-rgb), 0.55);
  padding-bottom: 1px; transition: color 0.15s, border-color 0.15s;
}
.qa-subtitle a:hover { color: var(--nc-primary-bright); border-bottom-color: var(--nc-primary); }

.qa-close {
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.06);
  cursor: pointer;
  color: #8b95a3; font-size: 1.1rem; line-height: 1;
  width: 32px; height: 32px; border-radius: 6px;
  display: grid; place-items: center;
  transition: background 0.15s, color 0.15s, border-color 0.15s, transform 0.1s;
  flex-shrink: 0;
}
.qa-close:hover { background: rgba(255, 68, 68, 0.12); color: #ff5252; border-color: rgba(255, 82, 82, 0.4); }
.qa-close:active { transform: scale(0.94); }
.qa-close svg { width: 16px; height: 16px; }

/* ── Body ───────────────────────────────────────────────────────────────── */
.qa-body {
  padding: 1.3rem 1.6rem 0.6rem; overflow-y: auto;
  display: flex; flex-direction: column; gap: 1.05rem;
}
.qa-body--center { align-items: center; justify-content: center; padding: 2.2rem 1.6rem; min-height: 240px; }

/* §pass51 — featured-template fork rail */
.qa-templates {
  display: flex; flex-direction: column; gap: 0.5rem;
  margin: 0 0 0.3rem;
}
.qa-templates-head { display: flex; flex-direction: column; gap: 2px; }
.qa-templates-eyebrow {
  font-size: 0.6rem; letter-spacing: 0.22em;
  color: rgba(255, 215, 0, 0.85); font-weight: 800; text-transform: uppercase;
}
.qa-templates-sub { font-size: 0.7rem; color: #99a5b3; line-height: 1.45; }
.qa-templates-grid { display: flex; flex-direction: column; gap: 0.35rem; }
.qa-tpl-chip {
  display: flex; align-items: center; gap: 0.55rem;
  background: linear-gradient(180deg, rgba(255, 215, 0, 0.06) 0%, rgba(255, 215, 0, 0.12) 100%);
  border: 1px solid rgba(255, 215, 0, 0.28);
  border-radius: 6px;
  padding: 9px 12px;
  color: #e8eaed;
  font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; font-weight: 600;
  cursor: pointer;
  transition: background 0.18s, border-color 0.18s, transform 0.06s;
}
.qa-tpl-chip:hover {
  background: linear-gradient(180deg, rgba(255, 215, 0, 0.14) 0%, rgba(255, 215, 0, 0.22) 100%);
  border-color: rgba(255, 215, 0, 0.6);
  transform: translateX(2px);
}
.qa-tpl-chip:active { transform: translateX(2px) translateY(1px); }
.qa-tpl-name { flex: 1; text-align: left; }
.qa-tpl-cat { font-size: 0.62rem; color: rgba(255, 215, 0, 0.8); background: rgba(0, 0, 0, 0.35); padding: 2px 7px; border-radius: 3px; font-weight: 600; letter-spacing: 0.06em; }
.qa-tpl-arrow { width: 14px; height: 14px; color: rgba(255, 215, 0, 0.55); flex-shrink: 0; }
.qa-tpl-chip:hover .qa-tpl-arrow { color: rgba(255, 215, 0, 0.95); }
.qa-templates-divider {
  display: flex; align-items: center; gap: 0.6rem;
  font-size: 0.66rem; color: rgba(148, 163, 184, 0.55); letter-spacing: 0.12em; text-transform: uppercase;
  padding: 0.3rem 0 0.1rem;
}
.qa-templates-divider::before, .qa-templates-divider::after { content: ''; flex: 1; height: 1px; background: rgba(255, 255, 255, 0.06); }

.qa-field { display: flex; flex-direction: column; gap: 0.4rem; }
.qa-label {
  font-size: 0.65rem; letter-spacing: 0.18em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.75); font-weight: 700;
}
.qa-req { color: #ff6b6b; }
.qa-opt { color: #6b7785; font-weight: 500; letter-spacing: 0.08em; }
.qa-hint { font-size: 0.7rem; color: #6b7785; line-height: 1.5; margin-top: 0.2rem; }
.qa-hint code {
  background: rgba(255,255,255,0.04);
  padding: 1px 6px; border-radius: 3px;
  font-size: 0.68rem; color: #b0c0d0;
  border: 1px solid rgba(255,255,255,0.05);
}

.qa-input {
  width: 100%; box-sizing: border-box;
  background: rgba(0, 0, 0, 0.45);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  border-radius: 6px;
  padding: 0.75rem 0.9rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.88rem;
  color: #e8eaed;
  outline: none;
  transition: border-color 0.18s, background 0.18s, box-shadow 0.18s;
}
.qa-input::placeholder { color: #4a5568; }
.qa-input:focus {
  border-color: rgba(var(--nc-primary-rgb), 0.75);
  background: rgba(0,0,0,0.6);
  box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.08), 0 0 12px rgba(var(--nc-primary-rgb), 0.06);
}
.qa-input:disabled { opacity: 0.5; cursor: not-allowed; }

.qa-tags { display: flex; flex-wrap: wrap; gap: 0.45rem; }
.qa-tag {
  display: inline-flex; align-items: center; gap: 0.45rem;
  background: rgba(var(--nc-primary-rgb), 0.05);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  color: rgba(var(--nc-primary-rgb), 0.85);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem; font-weight: 600;
  padding: 7px 12px;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.18s, border-color 0.18s, color 0.18s, transform 0.08s, box-shadow 0.18s;
}
.qa-tag-icon { width: 14px; height: 14px; flex-shrink: 0; }
.qa-tag-check {
  width: 12px; height: 12px;
  color: var(--nc-primary, #00d2d2);
  margin-left: 0.1rem;
}
.qa-tag:hover:not(.is-disabled):not(:disabled) {
  background: rgba(var(--nc-primary-rgb), 0.14); color: var(--nc-primary);
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  transform: translateY(-1px);
}
.qa-tag.is-active {
  background: rgba(var(--nc-primary-rgb), 0.20); color: var(--nc-primary);
  border-color: rgba(var(--nc-primary-rgb), 0.7);
  box-shadow: 0 0 14px rgba(var(--nc-primary-rgb), 0.18), inset 0 1px 0 rgba(255,255,255,0.05);
}
.qa-tag.is-disabled { opacity: 0.35; cursor: not-allowed; }

.qa-error {
  display: flex; align-items: flex-start; gap: 0.55rem;
  margin: 0; padding: 0.75rem 0.9rem;
  background: rgba(255, 68, 68, 0.07); border: 1px solid rgba(255, 68, 68, 0.32);
  color: #ffb4b4; border-radius: 6px; font-size: 0.78rem; line-height: 1.5;
}
.qa-error-icon { width: 16px; height: 16px; flex-shrink: 0; color: #ff8c8c; margin-top: 1px; }

/* ── Creating spinner ───────────────────────────────────────────────────── */
.qa-spinner { width: 64px; height: 64px; position: relative; margin-bottom: 1.3rem; }
.qa-spinner-ring {
  position: absolute; inset: 0; border-radius: 50%;
  border: 3px solid rgba(var(--nc-primary-rgb), 0.15);
  border-top-color: var(--nc-primary, #00d2d2);
  animation: qa-spin 0.9s linear infinite;
}
.qa-spinner-pulse {
  position: absolute; inset: 14px; border-radius: 50%;
  background: radial-gradient(circle, rgba(var(--nc-primary-rgb), 0.35) 0%, transparent 70%);
  animation: qa-spinner-pulse 1.8s ease-in-out infinite;
}
@keyframes qa-spin { to { transform: rotate(360deg); } }
@keyframes qa-spinner-pulse { 0%,100% { opacity: 0.4; transform: scale(0.85); } 50% { opacity: 0.9; transform: scale(1); } }
@media (prefers-reduced-motion: reduce) {
  .qa-spinner-ring { animation: none; border-top-color: rgba(var(--nc-primary-rgb), 0.55); }
  .qa-spinner-pulse { animation: none; opacity: 0.6; }
}
.qa-creating-text { text-align: center; }
.qa-creating-step {
  font-size: 0.78rem; color: #99a5b3; padding: 0.2rem 0;
  font-family: 'IBM Plex Mono', monospace;
  animation: qa-fade-in 1s ease-out forwards;
  opacity: 0;
}
.qa-creating-step.is-fade2 { animation-delay: 0.8s; }
.qa-creating-step.is-fade3 { animation-delay: 1.6s; }
.qa-creating-step.is-fade4 { animation-delay: 2.4s; }
@keyframes qa-fade-in { from { opacity: 0; transform: translateY(2px); } to { opacity: 1; transform: translateY(0); } }

/* ── Success ────────────────────────────────────────────────────────────── */
.qa-success-hero {
  display: flex; justify-content: center; padding: 0.2rem 0 0.4rem;
}
.qa-success-check {
  width: 56px; height: 56px;
  display: grid; place-items: center;
  color: #00ff88;
  filter: drop-shadow(0 0 14px rgba(0,255,136,0.55));
  animation: qa-success-pop 0.5s cubic-bezier(.2,.7,.3,1.4) both;
}
.qa-success-check svg { width: 56px; height: 56px; }
@keyframes qa-success-pop {
  0% { opacity: 0; transform: scale(0.4); }
  60% { opacity: 1; transform: scale(1.12); }
  100% { opacity: 1; transform: scale(1); }
}
@media (prefers-reduced-motion: reduce) { .qa-success-check { animation: none; } }

.qa-success-summary {
  display: grid; grid-template-columns: 1fr; gap: 0.7rem;
  background:
    linear-gradient(180deg, rgba(0, 255, 136, 0.06) 0%, rgba(0, 255, 136, 0.02) 100%);
  border: 1px solid rgba(0, 255, 136, 0.22);
  border-radius: 8px; padding: 1rem 1.1rem;
}
.qa-success-tile { display: flex; flex-direction: column; gap: 0.2rem; }
.qa-success-tile-label {
  font-size: 0.6rem; letter-spacing: 0.18em; text-transform: uppercase;
  color: rgba(0, 255, 136, 0.85); font-weight: 700;
}
.qa-success-tile-value { font-size: 0.98rem; font-weight: 700; color: #e8eaed; word-break: break-all; }
.qa-mono {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; color: #b0c0d0;
  font-weight: 500; background: rgba(0,0,0,0.4); padding: 5px 9px; border-radius: 4px;
  border: 1px solid rgba(255,255,255,0.04);
}

.qa-creds-block {
  background: rgba(255,255,255,0.015);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  border-radius: 6px; padding: 0.65rem 0.9rem;
}
.qa-creds-block summary {
  display: flex; align-items: center; gap: 0.45rem;
  font-size: 0.74rem; letter-spacing: 0.04em; color: #99a5b3;
  cursor: pointer; padding: 0.35rem 0; font-weight: 600; user-select: none;
  list-style: none;
}
.qa-creds-block summary::-webkit-details-marker { display: none; }
.qa-creds-icon { width: 14px; height: 14px; flex-shrink: 0; color: rgba(var(--nc-primary-rgb), 0.7); }
.qa-creds-sub { color: #6b7785; font-weight: 500; font-size: 0.7rem; }
.qa-creds-block summary:hover { color: #e8eaed; }
.qa-creds-block[open] summary { color: var(--nc-primary); margin-bottom: 0.5rem; }
.qa-creds-block[open] .qa-creds-icon { color: var(--nc-primary); }
.qa-creds-grid {
  display: grid; grid-template-columns: max-content 1fr; gap: 0.45rem 0.9rem;
  align-items: center; margin-top: 0.5rem;
}
.qa-cred-label {
  font-size: 0.6rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.65); font-weight: 700;
}
.qa-cred-value {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.72rem;
  background: rgba(0,0,0,0.4); padding: 5px 9px; border-radius: 4px;
  color: #d0d8e0; word-break: break-all;
  border: 1px solid rgba(255,255,255,0.04);
}
.qa-cred-secret { color: #fbbf24; }

.qa-copy {
  display: inline-flex; align-items: center; gap: 0.4rem;
  margin-top: 0.65rem;
  background: rgba(var(--nc-primary-rgb), 0.10);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.32);
  color: var(--nc-primary);
  font-family: 'IBM Plex Mono', monospace; font-size: 0.7rem; font-weight: 600;
  padding: 6px 11px; border-radius: 5px; cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.qa-copy svg { width: 12px; height: 12px; }
.qa-copy:hover { background: rgba(var(--nc-primary-rgb), 0.22); color: #fff; border-color: rgba(var(--nc-primary-rgb), 0.55); }

.qa-creds-note {
  font-size: 0.7rem; color: #6b7785; line-height: 1.6;
  margin: 0.7rem 0 0 0; font-style: italic;
}

/* ── Footer ─────────────────────────────────────────────────────────────── */
.qa-foot {
  display: flex; gap: 0.6rem; justify-content: flex-end; flex-wrap: wrap;
  padding: 1.1rem 1.6rem 1.3rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1);
  background:
    linear-gradient(180deg, rgba(0,0,0,0.16) 0%, rgba(0,0,0,0.22) 100%);
  position: relative;
}
.qa-foot::before {
  content: '';
  position: absolute; left: 1.6rem; right: 1.6rem; top: -1px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.18), transparent);
}
.qa-foot-hint { font-size: 0.72rem; color: #99a5b3; font-style: italic; margin: auto; }

.qa-btn {
  display: inline-flex; align-items: center; gap: 0.4rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem; font-weight: 700; letter-spacing: 0.08em;
  padding: 0.6rem 1.1rem;
  border-radius: 5px; cursor: pointer;
  transition: background 0.18s, color 0.18s, border-color 0.18s, transform 0.08s, box-shadow 0.18s;
}
.qa-btn:active:not(:disabled) { transform: translateY(1px); }
.qa-btn-icon { width: 14px; height: 14px; flex-shrink: 0; }

.qa-btn--ghost {
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.8);
}
.qa-btn--ghost:hover {
  color: var(--nc-primary);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  background: rgba(var(--nc-primary-rgb), 0.05);
}

.qa-btn--primary {
  background: linear-gradient(180deg, var(--nc-primary-bright, #00e8e8) 0%, var(--nc-primary, #00d2d2) 100%);
  color: #04141f;
  border: 1px solid var(--nc-primary, #00d2d2);
  box-shadow:
    0 4px 16px rgba(var(--nc-primary-rgb), 0.32),
    inset 0 1px 0 rgba(255,255,255,0.25);
}
.qa-btn--primary:hover:not(:disabled) {
  background: linear-gradient(180deg, #ffffff 0%, var(--nc-primary-bright, #00e8e8) 100%);
  box-shadow:
    0 6px 20px rgba(var(--nc-primary-rgb), 0.45),
    inset 0 1px 0 rgba(255,255,255,0.4);
}
.qa-btn--primary:disabled { opacity: 0.4; cursor: not-allowed; box-shadow: none; }
.qa-modal.is-success .qa-btn--primary {
  background: linear-gradient(180deg, #36ffa8 0%, #00ff88 100%);
  border-color: #00ff88;
  box-shadow:
    0 4px 16px rgba(0,255,136,0.35),
    inset 0 1px 0 rgba(255,255,255,0.3);
}
.qa-modal.is-success .qa-btn--primary:hover {
  background: linear-gradient(180deg, #ffffff 0%, #36ffa8 100%);
  box-shadow:
    0 6px 20px rgba(0,255,136,0.5),
    inset 0 1px 0 rgba(255,255,255,0.45);
}

/* ── Transitions ────────────────────────────────────────────────────────── */
.qa-fade-enter-active, .qa-fade-leave-active { transition: opacity 0.2s; }
.qa-fade-enter-from, .qa-fade-leave-to { opacity: 0; }

.qa-pop-enter-active { transition: transform 0.26s cubic-bezier(.2,.7,.3,1.25), opacity 0.18s; }
.qa-pop-leave-active { transition: transform 0.16s ease, opacity 0.14s; }
.qa-pop-enter-from { transform: translateY(14px) scale(0.96); opacity: 0; }
.qa-pop-leave-to { transform: translateY(8px) scale(0.98); opacity: 0; }
@media (prefers-reduced-motion: reduce) {
  .qa-pop-enter-active, .qa-pop-leave-active, .qa-fade-enter-active, .qa-fade-leave-active { transition: none; }
}
.qa-how { margin: 0.6rem 0 0; padding: 0.55rem 0.8rem; border: 1px dashed rgba(var(--nc-primary-rgb, 0,229,255), 0.35); border-radius: 8px; font-size: 0.8rem; }
.qa-how summary { cursor: pointer; font-weight: 600; color: var(--nc-primary, #00e5ff); }
.qa-how ul { margin: 0.45rem 0 0; padding-left: 1.1rem; display: grid; gap: 0.25rem; }
.qa-how-note { margin: 0.45rem 0 0; font-size: 0.72rem; color: var(--nc-text-muted, #6e7681); }

/* §REPBOND — the birth-flow bond door */
.qa-bond { margin-top: 0.6rem; padding: 0.6rem 0.75rem; border-radius: 10px; border: 1px solid rgba(var(--nc-primary-rgb), 0.25); background: rgba(var(--nc-primary-rgb), 0.05); }
.qa-bond-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; margin: 0.4rem 0; }
.qa-bond-btn { padding: 0.35rem 0.75rem; border-radius: 8px; font-size: 0.8rem; font-weight: 600; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.5); background: rgba(var(--nc-primary-rgb), 0.15); color: inherit; }
.qa-bond-btn--ghost { background: transparent; opacity: 0.85; }
.qa-bond-btn:disabled { opacity: 0.5; cursor: default; }
.qa-bond-error { color: #f87171; }
</style>
