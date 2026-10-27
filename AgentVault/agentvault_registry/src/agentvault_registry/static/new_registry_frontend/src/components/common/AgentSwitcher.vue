<template>
  <div v-if="authStore.isDeveloper || authStore.isAdmin" class="relative" ref="triggerRef">
    <!-- Agent Switcher Button -->
    <button
      @click="toggleDropdown"
      class="as-trigger"
      data-tour="agent-switcher"
      :class="{
        'as-trigger--warn': !authStore.activeAgent && authStore.isAgentRequired($route.path),
        'as-trigger--pulse': isPulsing,
        'as-trigger--attention': uiStore.agentSwitcherAttention,
      }"
    >
      <!-- 2026-05-12 §14: UserAvatar replaces the unicode glyph + trailing
           FlareBadge. UserAvatar resolves both flare slots (encirclement +
           corner) for the active agent so shadow_chancellor agents render
           correctly. Initials fall back from agent.name. Credential health
           is conveyed via the row-level styling + warning icon below. -->
      <UserAvatar
        v-if="authStore.activeAgent"
        :user="authStore.activeAgent"
        :display-name="authStore.activeAgent.name || authStore.activeAgent.did.slice(0, 8)"
        :granted-at="authStore.activeAgent.flare_granted_at || null"
        size="xs"
        class="as-avatar"
      />
      <span v-else class="as-agent-icon">◉</span>
      <span v-if="authStore.activeAgent?.hasInvalidCredentials" class="as-cred-warn" title="Agent credentials are invalid"><Icon name="mdi:alert" /></span>
      <span class="as-agent-name">
        <template v-if="authStore.activeAgent">
          {{ (authStore.activeAgent.name || authStore.activeAgent.did.slice(0, 18) + '…').replace(' (Hardcoded)', '') }}
        </template>
        <template v-else>
          <span class="as-no-agent">{{ t('agentSwitcher.select') }}</span>
        </template>
      </span>
      <svg class="as-chevron" :class="{ 'as-chevron--open': isOpen }" viewBox="0 0 12 12">
        <path d="M2 4l4 4 4-4" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round"/>
      </svg>
    </button>

    <!-- Dropdown + Overlay via Teleport — always top layer -->
    <Teleport to="body">
      <!-- Click-outside overlay (behind dropdown) -->
      <div
        v-if="isOpen"
        class="as-overlay"
        @click="isOpen = false"
      />

      <!-- Dropdown panel -->
      <Transition
        enter-active-class="as-enter-active"
        enter-from-class="as-enter-from"
        enter-to-class="as-enter-to"
        leave-active-class="as-leave-active"
        leave-from-class="as-leave-from"
        leave-to-class="as-leave-to"
      >
        <div
          v-if="isOpen"
          class="as-dropdown"
          :style="dropdownStyle"
        >
          <!-- Header -->
          <div class="as-dropdown-header">
            <span class="as-header-label">AGENT CONTEXT</span>
            <div class="as-header-right">
              <button
                class="as-refresh-btn"
                @click.stop="refreshList"
                :title="'Refresh agent list'"
                :disabled="authStore.agentLoading"
              >⟳</button>
              <span class="as-header-count">
                <span v-if="searching" class="as-searching-pip" title="Searching your whole fleet">⟳</span>
                {{ filteredAgents.length }}<span v-if="filteredAgents.length !== authStore.availableAgents.length">/{{ authStore.availableAgents.length }}</span> agents
              </span>
            </div>
          </div>

          <!-- Search / filter -->
          <div v-if="authStore.availableAgents.length > 5" class="as-search">
            <input
              ref="searchInputRef"
              v-model="filter"
              type="search"
              class="as-search-input"
              placeholder="filter by name or DID…"
              @keydown.escape="onSearchEscape"
            />
            <button v-if="filter" class="as-search-clear" @click="filter = ''" title="clear">×</button>
          </div>

          <!-- §FESUITE (V0577): the fleet search got no answer, so the rows below are only the agents loaded here -->
          <ReadFailedNotice
            v-if="searchFailed && filter && filteredAgents.length && !authStore.agentLoading"
            dense
            :text="t('agentSwitcher.searchFailedSlice', 'Your whole fleet could not be searched just now: these are only the agents loaded here.')"
            :retry="retrySearch"
            data-testid="as-search-failed"
          />

          <!-- Loading -->
          <div v-if="authStore.agentLoading" class="as-loading">
            <div class="as-spinner" />
            <span>Loading agents...</span>
          </div>

          <!-- Agent List -->
          <div v-else-if="filteredAgents.length > 0" class="as-agent-list">
            <button
              v-for="agent in filteredAgents"
              :key="agent.did"
              @click="selectAgent(agent)"
              class="as-agent-row"
              :class="{
                'as-agent-row--active': authStore.activeAgent?.did === agent.did,
                'as-agent-row--nocreds': (!agent.client_id || !agent.client_secret) && !viaSession(agent)
              }"
            >
              <!-- Per-agent UserAvatar in dropdown — shows agent's flare slot
                   composition. The status dot moves to a small overlay so
                   credential health stays visible without dropping the
                   identity surface. -->
              <div class="as-row-avatar">
                <UserAvatar
                  :user="agent"
                  :display-name="agent.name || agent.did.slice(0, 8)"
                  :granted-at="agent.flare_granted_at || null"
                  size="sm"
                />
                <span
                  class="as-row-status-pip"
                  :class="{
                    'as-row-status-pip--active': authStore.activeAgent?.did === agent.did,
                    'as-row-status-pip--error': agent.hasInvalidCredentials,
                    'as-row-status-pip--ok': !agent.hasInvalidCredentials && ((agent.client_id && agent.client_secret) || viaSession(agent)) && authStore.activeAgent?.did !== agent.did,
                    'as-row-status-pip--warn': !agent.hasInvalidCredentials && (!agent.client_id || !agent.client_secret) && !viaSession(agent),
                  }"
                />
              </div>
              <div class="as-row-body">
                <div class="as-row-name">{{ (agent.name || 'Unnamed Agent').replace(' (Hardcoded)', '') }}</div>
                <div class="as-row-did">{{ agent.did.slice(0, 32) }}…</div>
                <!-- §BRIDGE R11 #12 — an agent that lives somewhere else SAYS SO.
                     Acting as an agent on another registry is a different act
                     from acting here, and a selector that hides the difference
                     invites you to aim a payment at the wrong network. -->
                <div v-if="foreignHost(agent)" class="as-row-foreign"
                     :title="'This agent lives on another registry. It authenticates there, and its calls go there.'">
                  &#8599; {{ foreignHost(agent) }}
                </div>
                <div v-if="agent.liquidBalance || agent.stakedBalance" class="as-row-balance">
                  ◎ {{ formatBalance(agent.liquidBalance || 0) }}
                  <span class="as-bal-sep">·</span>
                  ◉ {{ formatBalance(agent.stakedBalance || 0) }} locked
                </div>
                <!-- §MCPTEST30 (V0640): a revoked or suspended agent says the server's word, never "No credentials" -->
                <div v-if="cannotActReason(agent)" class="as-row-warn" data-testid="as-row-cannot-act">
                  {{ cannotActReason(agent) === 'revoked' ? 'Deleted on its registry · it cannot act' : 'Suspended on its registry · it cannot act' }}
                </div>
                <!-- V0641: an agent you own here with no secret saved signs in through your session (viaSession) -->
                <div v-else-if="viaSession(agent)" class="as-row-owned" data-testid="as-row-owned">
                  Yours here · signs in through your session
                </div>
                <div v-else-if="!agent.client_id || !agent.client_secret" class="as-row-warn">
                  No credentials · click to add
                </div>
              </div>
              <div v-if="authStore.activeAgent?.did === agent.did" class="as-row-check">✓</div>
            </button>
          </div>

          <!-- Quick deploy rail — §pass50.8c: when agents ARE listed, surface
               a single "+ deploy" entry between the list and the footer.
               Visually distinct from agent rows (dashed-top accent + light bg)
               so it reads as a separate action, not a malformed agent. -->
          <button
            v-if="filteredAgents.length > 0"
            type="button"
            class="as-deploy-rail"
            @click="openQuickDeploy"
            :title="'Spin up a new agent in 30 seconds'"
          >
            <span class="as-deploy-rail-icon"></span>
            <span class="as-deploy-rail-text">
              <span class="as-deploy-rail-primary">Quick deploy a new agent</span>
              <span class="as-deploy-rail-secondary">Identity, card &amp; credentials in ~30s</span>
            </span>
            <span class="as-deploy-rail-badge">30s</span>
          </button>

          <!-- Empty — §pass50.8b: Quick deploy CTA lives HERE (only state where
               creating an agent is the meaningful action). When agents already
               exist, the footer stays clean and the user goes through Manage
               Fleet to create more. -->
          <div v-else class="as-empty">
            <template v-if="searching">
              <div class="as-spinner" />
              <p class="as-empty-msg">Searching all agents…</p>
              <p class="as-empty-sub">Looking across your whole fleet for "{{ filter }}".</p>
            </template>
            <!-- §FESUITE (V0577): a fleet search that got no answer said 'No agents match… Searched your whole fleet' -->
            <template v-else-if="filter && searchFailed">
              <ReadFailedNotice
                dense
                :text="t('agentSwitcher.searchFailed', 'Your whole fleet could not be searched just now.')"
                :retry="retrySearch"
                data-testid="as-search-failed"
              />
              <p class="as-empty-sub">{{ tp('agentSwitcher.searchFailedLocal', 'No agent loaded here matches "{q}".', { q: filter }) }}</p>
              <button
                type="button"
                class="as-empty-clear"
                @click="filter = ''"
              >Clear filter</button>
            </template>
            <template v-else-if="filter && authStore.availableAgents.length">
              <p class="as-empty-msg">No agents match "{{ filter }}".</p>
              <p class="as-empty-sub">Searched your whole fleet by name and DID.</p>
              <button
                type="button"
                class="as-empty-clear"
                @click="filter = ''"
              >Clear filter</button>
            </template>
            <!-- §DIDCHUNK — a FAILED load is not an empty fleet.
                 This branch used to be a bare v-else, so a request that died
                 (measured: a 13.8 KB include_dids URL rejected outright once
                 600+ credentials were stored) rendered "No agents yet, spin up
                 your first agent" to an operator who owns 4,432. Say what
                 actually happened and offer the retry. -->
            <template v-else-if="authStore.agentFetchFailed">
              <div class="as-empty-icon" aria-hidden="true">
                <Icon name="mdi:alert-circle-outline" :size="22" />
              </div>
              <p class="as-empty-msg" data-testid="as-fetch-failed">Couldn’t load your agents</p>
              <p class="as-empty-sub">
                The request to this registry failed. This is not a statement about
                what you own — your agents are still there.
              </p>
              <button
                type="button"
                class="as-empty-cta"
                data-testid="as-retry"
                @click="authStore.fetchAvailableAgents({ force: true })"
              >Retry</button>
            </template>
            <template v-else>
              <div class="as-empty-icon" aria-hidden="true">
                
              </div>
              <p class="as-empty-msg">{{ t('agentSwitcher.emptyTitle', 'No wallet agent yet') }}</p>
              <p class="as-empty-sub">{{ t('agentSwitcher.emptyBody', 'Everything here is done as one of your agents. Your wallet agent is the first: an identity that holds your funds, no code required.') }}</p>
              <button
                type="button"
                class="as-empty-cta"
                @click="openQuickDeploy"
              >
                <Icon name="mdi:rocket-launch" class="as-empty-cta-icon" />
                <span>{{ t('agentSwitcher.emptyCta', 'Create your wallet agent') }}</span>
                <span class="as-empty-cta-sub">30s</span>
              </button>
              <router-link
                to="/agent-builder"
                @click="isOpen = false"
                class="as-empty-secondary"
              >
                Open AgentForge for advanced setup &rsaquo;
              </router-link>
            </template>
          </div>

          <!-- Footer — §pass50.8b: clean to just management entry points.
               Quick deploy moved into the empty state (above). Existing devs
               with agents go through Manage Fleet to create more. -->
          <div class="as-dropdown-footer">
            <button
              type="button"
              class="as-footer-link as-footer-link--btn"
              @click="openBulkImport"
              title="Bulk import credentials JSON for agents created elsewhere"
            >
              <Icon name="mdi:upload" class="as-footer-icon" />
              <span>Bulk Import</span>
            </button>
            <router-link to="/my-agents" @click="isOpen = false" class="as-footer-link as-footer-link--dim">
              Manage Fleet &rsaquo;
            </router-link>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>

  <!-- Credentials Modal -->
  <AddCredentialsModal
    v-if="selectedAgentForCredentials"
    :show="showAddCredentials"
    :agent="selectedAgentForCredentials"
    @close="showAddCredentials = false"
    @saved="handleCredentialsSaved"
  />

  <!-- Bulk Import Modal -->
  <BulkCredentialsImportModal
    :show="showBulkImport"
    @close="showBulkImport = false"
    @imported="handleBulkImported"
  />
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, nextTick, onMounted, onUnmounted, watch, defineAsyncComponent } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useRoute } from 'vue-router'
import UserAvatar from '@/components/common/UserAvatar.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import Icon from '@/components/Icon.vue'
import { cannotActReason, cannotActSentence } from '@/services/agentActable'
import { useI18n } from '@/composables/useI18n'
import { rankAgents } from '@/services/agentLiveness'

const { t, tp } = useI18n()

const AddCredentialsModal = defineAsyncComponent(() =>
  import('./AddCredentialsModal.vue')
)
const BulkCredentialsImportModal = defineAsyncComponent(() =>
  import('./BulkCredentialsImportModal.vue')
)

const authStore = useAuthStore()
const uiStore = useUIStore()
const route = useRoute()

// 2026-05-12 §14: activeAgentFlare computed retired — UserAvatar now resolves
// the agent's flare slots directly via `:user="authStore.activeAgent"`. Agents
// expose `flare_tier` + customization fields, which UserAvatar maps through
// the same dual-slot logic used for developer avatars.

const isOpen = ref(false)
const triggerRef = ref<HTMLElement | null>(null)
const showAddCredentials = ref(false)
const selectedAgentForCredentials = ref<any>(null)
const showBulkImport = ref(false)

// Filter + search
const filter = ref('')
const searchInputRef = ref<HTMLInputElement | null>(null)

// §agentfinder (2026-07-26) — server-side finder results. The local list is
// capped at the recency window; when the user searches, we ALSO query the
// backend (by name/DID across the whole fleet) so any agent is findable even
// if it isn't in the loaded window. Results are debounced + merged (deduped)
// under the local matches, with credentialed agents kept on top.
// §FESUITE (V0577): the rows are kept with the term they answered, so a reply for an earlier term is never merged
// under a new one; searchFailed = the search for the current term got no answer ("could not read" is not "no match").
const serverResults = ref<{ term: string; rows: any[] }>({ term: '', rows: [] })
const searching = ref(false)
const searchFailed = ref(false)
let searchTimer: ReturnType<typeof setTimeout> | null = null
let searchSeq = 0

/* §COCKPITPOLISH P2 — the local `credRank` comparator is retired in favour of the
 * SHARED rail (`services/agentLiveness.ts`), which the cockpit's instruct picker also
 * asks. Two pickers with two orderings agree on the day they ship and drift by Friday.
 *
 * The switcher's question is "which agent may I ACT AS", so credentials stay the primary
 * key — `credentialsFirst` — and liveness breaks ties inside each credential tier. That
 * preserves §agentfinder's deliberate behaviour (the credentialed working set on top)
 * while putting the agents that are actually RUNNING above the ones that are not. */

const filteredAgents = computed(() => {
  const q = filter.value.trim().toLowerCase()
  const base = !q
    ? authStore.availableAgents
    : authStore.availableAgents.filter((a: any) => {
        const name = (a.name || '').toLowerCase()
        const did = (a.did || '').toLowerCase()
        const cid = (a.client_id || '').toLowerCase()
        return name.includes(q) || did.includes(q) || cid.includes(q)
      })
  // Merge server-side finder results not already present locally.
  const seen = new Set(base.map((a: any) => a.did))
  const extra = q && serverResults.value.term.toLowerCase() === q
    ? serverResults.value.rows.filter((a: any) => !seen.has(a.did))
    : []
  const merged = [...base, ...extra]
  // Keep credentialed/active agents on top so the working set is always first; among
  // equals, the agent that called this registry most recently leads.
  return rankAgents(merged, { activeDid: authStore.activeAgent?.did, credentialsFirst: true })
})

/*
 * §OWNEDHOMES — pull a foreign agent's cosmetics from its OWN registry.
 *
 * "its cosmetics from registry-a is not loading which is sad. it should be
 * available and loading each agents cosmetics in the agent selector from its
 * original registry." Measured: Hagrid reads `sovereign` at registry-a and 404
 * on frame-c, so this registry cannot serve them — only the home one can.
 *
 * BOUNDED to what is on screen, because §LAZYBAL was exactly this shape done
 * without a cap and it left the switcher empty for minutes. The store caches
 * hits AND misses for the session, so reopening the dropdown is free.
 */
watch([isOpen, filteredAgents], async ([open, rows]) => {
  if (!open) return
  const dids = (rows as any[]).slice(0, 24).map(a => a?.did).filter(Boolean)
  if (dids.length) await authStore.hydrateForeignFlares(dids)
}, { immediate: false })

// The agent he is ACTING AS is the one he looks at most; never leave it bare.
watch(() => authStore.activeAgent?.did, (did) => {
  if (did) void authStore.hydrateForeignFlares([String(did)], 1)
}, { immediate: true })

// Debounced server search whenever the filter changes (>=2 chars).
watch(filter, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  const term = q.trim()
  const seq = ++searchSeq
  searchFailed.value = false
  if (term.length < 2) { serverResults.value = { term: '', rows: [] }; searching.value = false; return }
  searching.value = true
  searchTimer = setTimeout(() => { void runSearch(term, seq) }, 250)
})

async function runSearch(term: string, seq: number) {
  const res = await authStore.searchAgents(term)
  // §FESUITE (V0577): the person kept typing, so a newer search owns the rows and the flags. A late reply used to
  // clear "Searching…" for the newer term, and "No agents match… Searched your whole fleet" showed before it answered.
  if (seq !== searchSeq) return
  serverResults.value = { term, rows: res ?? [] }
  searchFailed.value = res === null
  searching.value = false
}

function retrySearch() {
  const term = filter.value.trim()
  if (term.length < 2) return
  const seq = ++searchSeq
  searchFailed.value = false
  searching.value = true
  return runSearch(term, seq)
}

// Force-refresh the agent list from the API (bypass the 30s cache).
async function refreshList() {
  if (authStore.agentLoading) return
  await authStore.fetchAvailableAgents({ force: true })
}

// Close the dropdown on any route change — prevents the overlay from
// intercepting clicks after navigation (was BUG C).
watch(
  () => route.fullPath,
  () => {
    if (isOpen.value) isOpen.value = false
  }
)

// Reset filter + focus search input when the dropdown opens.
watch(isOpen, async (open) => {
  if (open) {
    filter.value = ''
    await nextTick()
    searchInputRef.value?.focus()
  }
})

// Escape behavior inside the search input: 1st press clears the filter,
// 2nd press (or on an already-empty filter) closes the whole picker.
function onSearchEscape(e: KeyboardEvent) {
  if (filter.value) {
    filter.value = ''
    e.stopPropagation()
  } else {
    isOpen.value = false
  }
}

// Compute dropdown position from trigger element
const dropdownStyle = computed(() => {
  if (!triggerRef.value) return {}
  const rect = triggerRef.value.getBoundingClientRect()
  return {
    position: 'fixed' as const,
    top: `${rect.bottom + 6}px`,
    right: `${window.innerWidth - rect.right}px`,
    zIndex: 99999,
  }
})

function toggleDropdown() {
  isOpen.value = !isOpen.value
}

/**
 * V0641 (agentvault2-5b, 2026-10-25, with agentvault2-66): an agent you own on this registry with no secret saved in this
 * browser signs in through your session (the store's canActAs, §FEFRAME W3), as the picker modal has since 2026-10-10.
 * The switcher asked only "is a secret saved here": its row said "No credentials · click to add" and a press opened
 * Add Credentials for a secret the agent does not need (any member on a second device, or whose agents were made over
 * the API). A row with a saved secret, or one the console cannot act as (not yours, not here, revoked or suspended), is
 * not this case.
 */
function viaSession(agent: any): boolean {
  if (!agent || (agent.client_id && agent.client_secret)) return false
  return !cannotActReason(agent) && !!authStore.canActAs?.(agent)
}

async function selectAgent(agent: any) {
  // §MCPTEST30 (V0640): a revoked or suspended agent is said as such, before the credentials door (agentvault2-5b's
  // code read: a deleted agent's press opened Add Credentials, and with a saved secret the store's refusal said nothing
  // because the picker modal was closed)
  const cannot = cannotActReason(agent)
  if (cannot) {
    uiStore.showError(cannot === 'revoked' ? 'Agent deleted' : 'Agent suspended', cannotActSentence(agent, cannot))
    isOpen.value = false
    return
  }
  // V0641: the credentials door only for an agent the console cannot sign in through your session (viaSession)
  if ((!agent.client_id || !agent.client_secret) && !viaSession(agent)) {
    selectedAgentForCredentials.value = agent
    showAddCredentials.value = true
    isOpen.value = false
    return
  }
  if (agent.hasInvalidCredentials) {
    uiStore.showWarning('Invalid Credentials', 'This agent has invalid credentials.')
    isOpen.value = false
    return
  }
  const success = await authStore.switchAgent(agent.did)
  if (success) isOpen.value = false
}

/**
 * §BRIDGE R11 #12 — the host an agent really answers on, or null for local.
 *
 * Returns the HOST, not the full URL: the row is 20rem wide and the hostname is
 * the part that identifies the registry. Null for anything on this origin, so
 * a fleet that has never imported a foreign credential shows nothing new.
 */
function foreignHost(agent: any): string | null {
  const u = agent?.registry_url
  if (!u || typeof u !== 'string') return null
  try {
    const parsed = new URL(u)
    return parsed.origin === window.location.origin ? null : parsed.host
  } catch { return null }
}

function formatBalance(balance: string | number): string {
  const num = typeof balance === 'string' ? parseFloat(balance) : balance
  if (isNaN(num)) return '0'
  if (num >= 1_000_000) return (num / 1_000_000).toFixed(1) + 'M'
  if (num >= 1_000) return Math.round(num).toLocaleString(appLocale())
  return num.toFixed(0)
}

function handleCredentialsSaved() {
  showAddCredentials.value = false
  selectedAgentForCredentials.value = null
  authStore.fetchAvailableAgents({ force: true })
}

function openBulkImport() {
  isOpen.value = false
  showBulkImport.value = true
}

// §pass50.8 — Quick deploy footer button opens QuickAgentModal in lieu of
// routing to /agent-builder (full wizard). uiStore is already imported above.
function openQuickDeploy() {
  isOpen.value = false
  uiStore.openQuickAgentModal()
}

function handleBulkImported(_count: number) {
  showBulkImport.value = false
  authStore.fetchAvailableAgents({ force: true })
}

function handleEscape(e: KeyboardEvent) {
  if (e.key === 'Escape' && isOpen.value) isOpen.value = false
}

// RBAC §66 (2026-05-08): attention pulse from ui store. Router guard +
// DashboardSidebar.handleLockedClick fire `uiStore.pulseAgentSwitcher()`
// when an agent-required area is gated; we glow the trigger for ~2.4s
// and (when autoOpen=true) pop the dropdown so the user can pick
// immediately. The token is a counter — we watch the value, not the
// state, so consecutive pulses re-fire correctly.
const isPulsing = ref(false)
let pulseTimer: ReturnType<typeof setTimeout> | null = null
watch(() => uiStore.agentSwitcherPulseToken, (token) => {
  if (token <= 0) return
  isPulsing.value = true
  // §FESUITE (2026-10-10): one door at a time. The agent guard and a locked sidebar item open the agent picker AND pulse
  // this switcher; its dropdown's click-outside overlay (fixed, z 99998, transparent) then lay over the picker, so the
  // first press on an agent in the picker only closed the dropdown (the console suite's lifecycle 82). While the picker
  // is open the switcher glows and stays shut.
  if (uiStore.agentSwitcherPulseAutoOpen && !authStore.showAgentSelector) {
    isOpen.value = true
  }
  if (pulseTimer) clearTimeout(pulseTimer)
  pulseTimer = setTimeout(() => {
    isPulsing.value = false
  }, 2400)
})

onMounted(() => document.addEventListener('keydown', handleEscape))
onUnmounted(() => {
  document.removeEventListener('keydown', handleEscape)
  if (pulseTimer) clearTimeout(pulseTimer)
  if (searchTimer) clearTimeout(searchTimer)
  searchSeq++
})
</script>

<style scoped>
/* Trigger button */
.as-trigger {
  display: flex; align-items: center; gap: 8px;
  padding: 6px 12px;
  background: rgba(var(--nc-primary-rgb),0.06);
  border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.8rem;
  color: rgba(var(--nc-primary-rgb),0.9);
  white-space: nowrap;
  max-width: 220px;
}
.as-trigger:hover {
  background: rgba(var(--nc-primary-rgb),0.1);
  border-color: rgba(var(--nc-primary-rgb),0.4);
  box-shadow: 0 0 12px rgba(var(--nc-primary-rgb),0.08);
}
.as-trigger--warn { border-color: rgba(245,158,11,0.5); color: rgba(245,158,11,0.9); }

/* 2026-05-12 §14: UserAvatar at the trigger — replaces unicode glyph
   + post-name FlareBadge. Encirclement halo extends OUTSIDE its bbox
   so the trigger gets a touch more vertical breathing room. */
.as-avatar {
  flex-shrink: 0;
  /* Small left-align — keeps the avatar tucked against the trigger edge
     while leaving room for the halo to bloom. */
}
/* Credential warning glyph (only when agent.hasInvalidCredentials).
   Lives between the avatar and the name, in amber tint. */
.as-cred-warn {
  flex-shrink: 0;
  font-size: 0.85em;
  color: rgba(245, 158, 11, 0.95);
  filter: drop-shadow(0 0 4px rgba(245, 158, 11, 0.55));
  animation: as-cred-warn-pulse 2.4s ease-in-out infinite;
}
@keyframes as-cred-warn-pulse {
  0%, 100% { opacity: 0.7; }
  50%      { opacity: 1; }
}

/* Per-row UserAvatar in the dropdown — slightly larger (sm) for legibility.
   Status pip overlay (bottom-left) carries credential health independent
   of the flare composition. */
.as-row-avatar {
  position: relative;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  margin-right: 2px;
}
.as-row-status-pip {
  position: absolute;
  bottom: -2px;
  left: -2px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  border: 1.5px solid rgba(8, 12, 22, 0.95);
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.35);
  z-index: 5;
}
.as-row-status-pip--active { background: rgba(74, 222, 128, 1); box-shadow: 0 0 0 1px rgba(0,0,0,0.35), 0 0 6px rgba(74, 222, 128, 0.65); }
.as-row-status-pip--ok     { background: rgba(74, 222, 128, 0.85); }
.as-row-status-pip--warn   { background: rgba(251, 191, 36, 0.95); }
.as-row-status-pip--error  { background: rgba(248, 113, 113, 1); box-shadow: 0 0 0 1px rgba(0,0,0,0.35), 0 0 6px rgba(248, 113, 113, 0.6); }

/* RBAC §66.1 refactor (2026-05-08): pulse + attention.
 *
 * --pulse  → one-shot 2.4s ring (4 × 0.6s cycles). Used when the user
 *            had no chance to hover (router-guard navigation block).
 *
 * --attention → continuous gentle glow while the user is hovering a
 *               locked agent-required item in the sidebar. Mirrors the
 *               locked-tooltip's "while hovering" UX. Stops the moment
 *               they move off the item.
 *
 * Both can stack; --pulse takes precedence visually because it's louder.
 */
.as-trigger--pulse {
  animation: as-attention-pulse 0.6s ease-in-out 4;
  border-color: rgba(245, 158, 11, 0.85);
  color: rgba(252, 211, 77, 1);
  background: rgba(245, 158, 11, 0.10);
}
.as-trigger--attention {
  animation: as-trigger-glow 1.4s ease-in-out infinite;
  border-color: rgba(245, 158, 11, 0.7);
  color: rgba(252, 211, 77, 1);
  background: rgba(245, 158, 11, 0.08);
}
@keyframes as-attention-pulse {
  0%   { box-shadow: 0 0 0 0   rgba(245, 158, 11, 0.55), 0 0 8px rgba(245, 158, 11, 0.25); transform: scale(1); }
  50%  { box-shadow: 0 0 0 10px rgba(245, 158, 11, 0),    0 0 18px rgba(245, 158, 11, 0.55); transform: scale(1.06); }
  100% { box-shadow: 0 0 0 0   rgba(245, 158, 11, 0),    0 0 0 rgba(245, 158, 11, 0); transform: scale(1); }
}
@keyframes as-trigger-glow {
  0%, 100% {
    box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.0),
                0 0 6px rgba(245, 158, 11, 0.20);
  }
  50% {
    box-shadow: 0 0 0 6px rgba(245, 158, 11, 0.0),
                0 0 14px rgba(245, 158, 11, 0.55);
  }
}

/* §66.1: when the dropdown opens with 0 visible agents, the
 * "Deploy New Agent" footer link blinks too — that's the action the
 * user actually needs (router-link → /agent-builder). Continuous gentle
 * pulse, identical visual language to the trigger glow but on amber-text.
 * Stops once any agent is registered (filteredAgents.length > 0). */
.as-deploy-pulse {
  animation: as-deploy-glow 1.4s ease-in-out infinite;
  color: rgba(252, 211, 77, 1) !important;
  text-shadow: 0 0 10px rgba(245, 158, 11, 0.45);
  position: relative;
}
.as-deploy-pulse::before {
  content: '';
  position: absolute;
  inset: -3px -8px;
  border-radius: 6px;
  border: 1px solid rgba(245, 158, 11, 0);
  pointer-events: none;
  animation: as-deploy-ring 1.4s ease-in-out infinite;
}
@keyframes as-deploy-glow {
  0%, 100% { background: rgba(245, 158, 11, 0.06); }
  50%      { background: rgba(245, 158, 11, 0.14); }
}
@keyframes as-deploy-ring {
  0%, 100% { border-color: rgba(245, 158, 11, 0.10); box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.0); }
  50%      { border-color: rgba(245, 158, 11, 0.55); box-shadow: 0 0 0 4px rgba(245, 158, 11, 0); }
}
.as-agent-icon { font-size: 1rem; line-height: 1; color: rgba(var(--nc-primary-rgb),0.7); }
.as-agent-name { flex: 1; overflow: hidden; text-overflow: ellipsis; }
.as-no-agent { color: rgba(148,163,184,0.82); }
.as-chevron {
  width: 12px; height: 12px; flex-shrink: 0;
  color: rgba(var(--nc-primary-rgb),0.5);
  transition: transform 0.15s ease;
}
.as-chevron--open { transform: rotate(180deg); }

/* Overlay */
.as-overlay {
  position: fixed; inset: 0;
  z-index: 99998;
  background: transparent;
}

/* Dropdown panel */
.as-dropdown {
  width: 320px;
  background: #0a1628;
  border: 1px solid rgba(var(--nc-primary-rgb),0.25);
  border-radius: 8px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.6), 0 0 0 1px rgba(var(--nc-primary-rgb),0.1);
  overflow: hidden;
  z-index: 99999;
}

/* §14 mobile pass — at <640px the dropdown overflows narrow viewports
   when anchored to the trigger's right edge. Force full-width with safe
   horizontal margin. !important is required because dropdownStyle (in
   script) sets `top` / `right` as inline styles. We let `top` stay
   anchored to the trigger but override left/right/width. */
@media (max-width: 639.98px) {
  .as-dropdown {
    left: 12px !important;
    right: 12px !important;
    width: auto !important;
    max-width: calc(100vw - 24px) !important;
  }
}
/* Mobile-friendly trigger — reserve enough room for avatar+name without
   overflowing the header at iPhone-13-mini width (375px). */
@media (max-width: 639.98px) {
  /* 180 px was sized before the header carried the frame's currency chip and the bell: on a 412 px phone the header ran
     ~30 px past the screen and the account avatar was cut off (the camera, 2026-10-13); the name ellipsizes */
  .as-trigger { max-width: 116px; gap: 6px; padding: 6px 8px; }
  .as-agent-name { min-width: 0; }
}
@media (max-width: 380px) {
  /* a small phone: the agent's avatar and the chevron say which agent acts; its name is in the open list */
  .as-agent-name { display: none; }
}

/* Transitions */
.as-enter-active, .as-leave-active { transition: opacity 0.12s ease, transform 0.12s ease; }
.as-enter-from, .as-leave-to { opacity: 0; transform: translateY(-4px) scale(0.98); }
.as-enter-to, .as-leave-from { opacity: 1; transform: translateY(0) scale(1); }

/* Header */
.as-dropdown-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 10px 14px 8px;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.1);
}
.as-header-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; letter-spacing: 0.12em;
  color: rgba(var(--nc-primary-rgb),0.5);
}
.as-header-count {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: rgba(148,163,184,0.4);
}
.as-searching-pip {
  display: inline-block;
  color: rgba(var(--nc-primary-rgb), 0.8);
  animation: spin 0.7s linear infinite;
  margin-right: 3px;
}
.as-header-right {
  display: flex; align-items: center; gap: 8px;
}
.as-refresh-btn {
  background: transparent; border: none; cursor: pointer;
  color: rgba(var(--nc-primary-rgb),0.6);
  font-size: 0.95rem; line-height: 1;
  padding: 2px 6px;
  border-radius: 3px;
  transition: all 0.15s ease;
}
.as-refresh-btn:hover:not(:disabled) {
  color: rgba(var(--nc-primary-rgb),1);
  background: rgba(var(--nc-primary-rgb),0.08);
  transform: rotate(180deg);
}
.as-refresh-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* Search / filter */
.as-search {
  position: relative;
  padding: 8px 10px 4px;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
}
.as-search-input {
  width: 100%;
  background: rgba(0,0,0,0.3);
  border: 1px solid rgba(var(--nc-primary-rgb),0.15);
  border-radius: 3px;
  padding: 5px 22px 5px 10px;
  color: rgba(226,232,240,0.9);
  font: 0.75rem 'IBM Plex Mono', monospace;
  outline: none;
  transition: border-color 0.15s;
}
.as-search-input:focus {
  border-color: rgba(var(--nc-primary-rgb),0.45);
}
.as-search-input::placeholder {
  color: rgba(148,163,184,0.4);
  font-size: 0.72rem;
}
.as-search-clear {
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-30%);
  background: transparent;
  border: none;
  color: rgba(148,163,184,0.6);
  font-size: 1rem;
  line-height: 1;
  cursor: pointer;
  padding: 2px 4px;
}
.as-search-clear:hover { color: rgba(var(--nc-primary-rgb),0.8); }

/* Loading */
.as-loading {
  display: flex; align-items: center; gap: 8px;
  padding: 16px 14px;
  color: rgba(148,163,184,0.6);
  font-size: 0.8rem;
}
.as-spinner {
  width: 14px; height: 14px;
  border: 2px solid rgba(var(--nc-primary-rgb),0.2);
  border-top-color: rgba(var(--nc-primary-rgb),0.7);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Agent list */
.as-agent-list { max-height: 340px; overflow-y: auto; }
.as-agent-list::-webkit-scrollbar { width: 4px; }
.as-agent-list::-webkit-scrollbar-thumb { background: rgba(var(--nc-primary-rgb),0.15); border-radius: 2px; }

.as-agent-row {
  display: flex; align-items: flex-start; gap: 10px;
  width: 100%; padding: 10px 14px;
  background: transparent; border: none; cursor: pointer;
  text-align: left; transition: background 0.1s ease;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.as-agent-row:hover { background: rgba(var(--nc-primary-rgb),0.05); }
.as-agent-row--active { background: rgba(var(--nc-primary-rgb),0.08) !important; }
.as-agent-row--nocreds { opacity: 0.65; }
.as-row-foreign {
  font-size: 9px; letter-spacing: 0.03em; margin-top: 1px;
  color: var(--nc-warn, #f6c453); opacity: 0.9;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

.as-row-indicator { padding-top: 4px; flex-shrink: 0; }
.as-dot { display: block; width: 7px; height: 7px; border-radius: 50%; }
.as-dot--active { background: #00d4d4; box-shadow: 0 0 6px rgba(var(--nc-primary-rgb),0.6); }
.as-dot--ok { background: rgba(16,185,129,0.8); }
.as-dot--warn { background: rgba(245,158,11,0.7); }
.as-dot--error { background: rgba(239,68,68,0.7); }

.as-row-body { flex: 1; min-width: 0; }
.as-row-name {
  font-size: 0.8rem; font-weight: 500;
  color: rgba(226,232,240,0.9);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.as-row-did {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem; color: rgba(148,163,184,0.45);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  margin-top: 2px;
}
.as-row-balance {
  font-size: 0.68rem; color: rgba(var(--nc-primary-rgb),0.6);
  margin-top: 3px;
}
.as-bal-sep { margin: 0 4px; color: rgba(148,163,184,0.3); }
.as-row-warn {
  font-size: 0.65rem; color: rgba(245,158,11,0.7);
  margin-top: 2px;
}
.as-row-owned {
  font-size: 0.65rem; color: rgba(148,163,184,0.75);
  margin-top: 2px;
}

.as-row-check {
  font-size: 0.75rem; color: rgba(var(--nc-primary-rgb),0.8);
  padding-top: 2px; flex-shrink: 0;
}

/* Quick deploy rail — §pass50.8c. Appears between the agent list and the
   footer when filteredAgents.length > 0. Sits AS A SEPARATE STRIPE — not a
   row in the list, not a button in the footer. Hover lifts the icon, the
   rail brightens, and the badge pulses. */
.as-deploy-rail {
  display: flex; align-items: center; gap: 0.75rem;
  width: 100%; padding: 11px 14px 12px;
  background:
    linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.04) 0%, rgba(var(--nc-primary-rgb), 0.075) 100%);
  border: none;
  border-top: 1px dashed rgba(var(--nc-primary-rgb), 0.22);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.10);
  cursor: pointer;
  text-align: left;
  transition: background 0.18s, border-color 0.18s;
  position: relative;
}
.as-deploy-rail:hover {
  background:
    linear-gradient(180deg, rgba(var(--nc-primary-rgb), 0.10) 0%, rgba(var(--nc-primary-rgb), 0.16) 100%);
  border-top-color: rgba(var(--nc-primary-rgb), 0.45);
}
.as-deploy-rail:active { background: rgba(var(--nc-primary-rgb), 0.18); }
.as-deploy-rail-icon {
  display: grid; place-items: center;
  width: 26px; height: 26px;
  border-radius: 6px;
  background: rgba(var(--nc-primary-rgb), 0.18);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.4);
  color: var(--nc-primary, #00d2d2);
  flex-shrink: 0;
  transition: background 0.18s, transform 0.18s, box-shadow 0.18s;
}
.as-deploy-rail-icon svg { width: 16px; height: 16px; }
.as-deploy-rail:hover .as-deploy-rail-icon {
  background: rgba(var(--nc-primary-rgb), 0.32);
  transform: scale(1.08) rotate(90deg);
  box-shadow: 0 0 14px rgba(var(--nc-primary-rgb), 0.45);
}
.as-deploy-rail-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 1px; }
.as-deploy-rail-primary {
  font-size: 0.78rem; font-weight: 600;
  color: rgba(226, 232, 240, 0.95);
  font-family: 'IBM Plex Mono', monospace;
  letter-spacing: 0.005em;
  line-height: 1.25;
}
.as-deploy-rail:hover .as-deploy-rail-primary { color: var(--nc-primary, #00d2d2); }
.as-deploy-rail-secondary {
  font-size: 0.65rem;
  color: rgba(148, 163, 184, 0.65);
  line-height: 1.3;
  font-weight: 500;
}
.as-deploy-rail-badge {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  padding: 3px 8px;
  border-radius: 3px;
  background: rgba(var(--nc-primary-rgb), 0.16);
  color: var(--nc-primary, #00d2d2);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.3);
  flex-shrink: 0;
  transition: background 0.18s, border-color 0.18s;
}
.as-deploy-rail:hover .as-deploy-rail-badge {
  background: rgba(var(--nc-primary-rgb), 0.28);
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  box-shadow: 0 0 10px rgba(var(--nc-primary-rgb), 0.25);
}
@media (prefers-reduced-motion: reduce) {
  .as-deploy-rail-icon, .as-deploy-rail:hover .as-deploy-rail-icon {
    transition: none; transform: none;
  }
}

/* Empty — §pass50.8b: when there are zero agents, the dropdown's main job
   is "convince the user to make one" rather than "switch". The CTA gets
   real estate, an icon, and a secondary AgentForge link below. */
.as-empty {
  padding: 22px 18px 20px;
  text-align: center;
  color: rgba(148, 163, 184, 0.6);
  font-size: 0.78rem;
  display: flex; flex-direction: column; align-items: center; gap: 0.55rem;
}
.as-empty-icon {
  width: 42px; height: 42px;
  display: grid; place-items: center;
  border-radius: 50%;
  background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.22);
  color: rgba(var(--nc-primary-rgb), 0.85);
  margin-bottom: 0.15rem;
  box-shadow: inset 0 0 18px rgba(var(--nc-primary-rgb), 0.06);
}
.as-empty-icon svg { width: 22px; height: 22px; }
.as-empty-msg {
  margin: 0;
  color: rgba(226, 232, 240, 0.92);
  font-size: 0.88rem;
  font-weight: 600;
  letter-spacing: 0.01em;
}
.as-empty-sub {
  margin: 0;
  color: rgba(148, 163, 184, 0.65);
  font-size: 0.72rem;
  line-height: 1.5;
  max-width: 24ch;
}
.as-empty-cta {
  display: inline-flex; align-items: center; gap: 0.42rem;
  margin-top: 0.4rem;
  background: linear-gradient(180deg, var(--nc-primary-bright, #00e8e8) 0%, var(--nc-primary, #00d2d2) 100%);
  border: 1px solid var(--nc-primary, #00d2d2);
  color: #04141f;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.18s, box-shadow 0.18s, transform 0.08s;
  box-shadow: 0 4px 14px rgba(var(--nc-primary-rgb), 0.32), inset 0 1px 0 rgba(255,255,255,0.25);
}
.as-empty-cta:hover {
  background: linear-gradient(180deg, #ffffff 0%, var(--nc-primary-bright, #00e8e8) 100%);
  box-shadow: 0 6px 18px rgba(var(--nc-primary-rgb), 0.45), inset 0 1px 0 rgba(255,255,255,0.4);
}
.as-empty-cta:active { transform: translateY(1px); }
.as-empty-cta-icon { width: 14px; height: 14px; flex-shrink: 0; }
.as-empty-cta-sub {
  font-size: 0.66rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.18);
  color: rgba(4, 20, 31, 0.85);
}
.as-empty-secondary {
  margin-top: 0.2rem;
  color: rgba(var(--nc-primary-rgb), 0.7);
  font-size: 0.7rem;
  text-decoration: none;
  border-bottom: 1px dashed rgba(var(--nc-primary-rgb), 0.4);
  padding-bottom: 1px;
  transition: color 0.15s, border-color 0.15s;
}
.as-empty-secondary:hover {
  color: var(--nc-primary, #00d2d2);
  border-bottom-color: var(--nc-primary, #00d2d2);
}
.as-empty-clear {
  margin-top: 0.2rem;
  background: transparent;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  color: rgba(var(--nc-primary-rgb), 0.85);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  padding: 5px 12px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.as-empty-clear:hover {
  background: rgba(var(--nc-primary-rgb), 0.08);
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  color: var(--nc-primary);
}

/* Footer */
.as-dropdown-footer {
  display: flex; justify-content: space-between; align-items: center;
  padding: 8px 14px;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.1);
}
.as-footer-link {
  display: inline-flex; align-items: center; gap: 5px;
  font-size: 0.72rem; font-family: 'IBM Plex Mono', monospace;
  color: rgba(var(--nc-primary-rgb),0.7); text-decoration: none;
  transition: color 0.15s, background 0.15s, transform 0.08s;
}
.as-footer-link:hover { color: rgba(var(--nc-primary-rgb),1); }
.as-footer-link--dim { color: rgba(148,163,184,0.4); }
.as-footer-link--dim:hover { color: rgba(148,163,184,0.7); }
.as-footer-link--btn {
  background: transparent;
  border: 0;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  font-family: inherit;
  text-align: center;
}
.as-footer-link--btn:hover {
  background: rgba(var(--nc-primary-rgb), 0.08);
}
.as-footer-link--cta {
  color: rgba(var(--nc-primary-rgb), 0.95);
  font-weight: 600;
}
.as-footer-link--cta:hover {
  color: var(--nc-primary, #00d2d2);
  background: rgba(var(--nc-primary-rgb), 0.12);
  transform: translateY(-1px);
}
.as-footer-icon {
  width: 12px; height: 12px;
  flex-shrink: 0;
  color: currentColor;
}
.as-footer-sub {
  color: rgba(148, 163, 184, 0.55);
  font-weight: 500;
  font-size: 0.66rem;
  margin-left: 2px;
}
.as-footer-link--cta:hover .as-footer-sub {
  color: rgba(var(--nc-primary-rgb), 0.7);
}
</style>
