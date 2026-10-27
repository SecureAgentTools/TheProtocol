<template>
  <BaseModal
    :show="authStore.showAgentSelector"
    @update:show="authStore.showAgentSelector = $event"
    title="Select an Agent"
    size="lg"
  >
    <div class="space-y-4">
      <!-- Explanation -->
      <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
        <h3 class="text-sm font-medium text-blue-900 dark:text-blue-100 mb-1">
          Agent Required
        </h3>
        <p class="text-sm text-blue-700 dark:text-blue-300">
          This feature requires you to act as one of your agents. Agents are the economic actors that hold units, vote on proposals, and participate in the network.
        </p>
      </div>

      <!-- Loading state - show while loading OR credentials not yet checked -->
      <div v-if="authStore.agentLoading || !authStore.credentialsChecked" class="py-8 text-center">
        <div class="inline-flex items-center gap-3">
          <svg class="animate-spin h-8 w-8 text-primary-600" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
          </svg>
          <span class="text-lg text-gray-600 dark:text-gray-400">
            {{ !authStore.credentialsChecked ? 'Checking agent credentials...' : 'Loading your agents...' }}
          </span>
        </div>
      </div>

      <!-- Agent list - only show when credentials are checked -->
      <div v-else-if="authStore.credentialsChecked && authStore.availableAgents.length > 0" class="space-y-3" :key="modalKey">
        <h4 class="text-sm font-medium text-gray-700 dark:text-gray-300 uppercase tracking-wide">
          Your Agents
        </h4>
        
        <div class="grid gap-3 max-h-96 overflow-y-auto pr-2">
          <div
            v-for="agent in sortedAgents"
            :key="agent.did"
            class="w-full p-4 bg-white dark:bg-gray-800 border rounded-lg transition-all"
            :class="getAgentCardClass(agent)"
          >
            <div class="flex items-start justify-between">
              <button
                @click="selectAgent(agent)"
                class="flex-1 text-left"
                :disabled="false"
              >
                <h3 class="font-medium text-gray-900 dark:text-white flex items-center gap-2">
                  {{ agent.name || 'Unnamed Agent' }}
                  <span v-if="agent.hasInvalidCredentials" class="text-red-600">
                    <Icon name="mdi:close-circle" />
                  </span>
                  <span v-else-if="actable(agent)" class="text-green-600">
                    <Icon name="mdi:check-circle" />
                  </span>
                  <span v-else class="text-yellow-500">
                    <Icon name="mdi:alert" />
                  </span>
                </h3>
                <p class="text-sm text-gray-500 dark:text-gray-400 mt-1 font-mono">
                  {{ agent.did }}
                </p>
                
                <div class="mt-2 space-y-1">
                  <!-- Total Balance (prominent display) -->
                  <div v-if="agent.totalBalance !== undefined" class="text-sm">
                    <span class="text-gray-600 dark:text-gray-400">Balance:</span>
                    <span class="font-semibold text-lg ml-2" :class="{
                      'text-green-600 dark:text-green-400': agent.totalBalance > 0,
                      'text-gray-900 dark:text-white': agent.totalBalance === 0
                    }">
                      {{ formatBalance(agent.totalBalance) }} {{ agentCcy(agent) }}
                    </span>
                    <span v-if="isForeignAgent(agent.registry_url)" class="ml-2 text-xs px-1.5 py-0.5 rounded-sm"
                          style="border:1px solid rgba(246,196,83,0.4); background:rgba(246,196,83,0.10); color:#f6c453"
                          :title="`This agent lives on ${agentRegistry(agent)} — acting as it sends every action there.`"
                          data-testid="agent-foreign-chip">
                      {{ agentRegistry(agent) }}
                    </span>
                  </div>
                  
                  <!-- Balance breakdown -->
                  <div class="flex flex-wrap gap-4 text-xs text-gray-500 dark:text-gray-400">
                    <div v-if="agent.liquidBalance !== undefined">
                      <span>Liquid:</span>
                      <span class="font-medium ml-1">{{ formatBalance(agent.liquidBalance) }}</span>
                    </div>
                    <div v-if="agent.stakedBalance !== undefined && agent.stakedBalance > 0">
                      <span>Locked:</span>
                      <span class="font-medium text-purple-600 dark:text-purple-400 ml-1">{{ formatBalance(agent.stakedBalance) }}</span>
                    </div>
                  </div>
                </div>
                
                <!-- §MCPTEST30 (V0640): a revoked or suspended agent says the server's word, before any credentials line -->
                <p v-if="cannotActReason(agent)" class="text-sm text-gray-500 dark:text-gray-400 mt-2"
                   data-testid="agent-selector-cannot-act">
                  <Icon name="mdi:close-circle" /> {{ cannotActReason(agent) === 'revoked'
                    ? t('agentSelector.cannotDeleted', 'Deleted on its registry: it cannot act')
                    : t('agentSelector.cannotSuspended', 'Suspended on its registry: it cannot act') }}
                </p>
                <p v-else-if="agent.hasInvalidCredentials" class="text-sm text-red-600 dark:text-red-400 mt-2">
                  <Icon name="mdi:close-circle" /> {{ t('agentSelector.rejected', 'The registry refused the saved secret: re-enter it or forget it') }}
                </p>
                <p v-else-if="!actable(agent)" class="text-sm text-yellow-600 dark:text-yellow-400 mt-2">
                  <Icon name="mdi:alert" /> {{ t('agentSelector.noSecret', 'No secret saved in this browser') }}
                </p>
                <p v-else-if="agent.hasCredentials !== true" class="text-sm text-gray-500 dark:text-gray-400 mt-2" data-testid="agent-selector-owned">
                  {{ t('agentSelector.ownedNoSecret', 'Yours here: it signs in through your session, no secret needed') }}
                </p>
              </button>
              
              <div class="ml-4 flex flex-col items-end gap-2">
                <span
                  v-if="authStore.activeAgent?.did === agent.did"
                  class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-primary-100 text-primary-800 dark:bg-primary-900 dark:text-primary-200"
                >
                  Active
                </span>
                <button
                  v-if="!cannotActReason(agent) && (!actable(agent) || agent.hasInvalidCredentials)"
                  type="button"
                  data-testid="agent-selector-add-secret"
                  @click="openAddCredentialsModal(agent)"
                  class="inline-flex items-center px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-md focus:outline-hidden focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                >
                  <svg class="w-3 h-3 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                  </svg>
                  {{ agent.hasInvalidCredentials ? t('agentSelector.reenter', 'Re-enter secret') : t('agentSelector.addSecret', 'Add Credentials') }}
                </button>
                <!-- §FEFRAME W1: a saved secret can leave this browser (the functions existed; nothing called them) -->
                <button
                  v-if="agent.hasCredentials === true || agent.hasInvalidCredentials"
                  type="button"
                  data-testid="agent-selector-forget-secret"
                  @click.stop="forgetOne(agent)"
                  class="inline-flex items-center px-2 py-1 text-xs text-gray-500 hover:text-red-600"
                >
                  {{ t('agentSelector.forget', 'Forget secret') }}
                </button>
              </div>
            </div>
          </div>
        </div>
        
        <div class="pt-4 border-t border-gray-200 dark:border-gray-700 flex gap-3 items-center">
          <!-- §pass50.7 — Quick onboard takes precedence over routing to /my-agents -->
          <button
            type="button"
            @click="authStore.showAgentSelector = false; uiStore.openQuickAgentModal()"
            class="inline-flex items-center text-sm font-medium text-primary-600 hover:text-primary-700"
          >
            <svg class="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
            </svg>
            Quick deploy (30s)
          </button>
          <span class="text-gray-400 text-xs">·</span>
          <router-link
            to="/my-agents"
            @click="authStore.showAgentSelector = false"
            class="inline-flex items-center text-xs text-gray-500 hover:text-gray-700"
          >
            Manage agents
          </router-link>
          <template v-if="savedCount > 0">
            <span class="text-gray-400 text-xs">·</span>
            <button
              type="button"
              data-testid="agent-selector-download"
              @click="downloadSaved()"
              class="inline-flex items-center text-xs text-gray-500 hover:text-gray-700"
            >
              {{ t('agentSelector.download', 'Download saved secrets (.json)') }}
            </button>
            <span class="text-gray-400 text-xs">·</span>
            <button
              type="button"
              data-testid="agent-selector-forget-all"
              @click="forgetAll()"
              class="inline-flex items-center text-xs text-gray-500 hover:text-red-600"
            >
              {{ t('agentSelector.forgetAll', 'Forget all saved secrets in this browser') }}
            </button>
          </template>
        </div>
      </div>

      <!-- §FESUITE (V0577): a failed agents read is not "no agent": this was the bare v-else below, so the selector a
           page opens when it needs an agent said "No wallet agent yet… Create your wallet agent first" to a person whose
           agents could not be read (the switcher has said so since §DIDCHUNK). The store reads it again on its own. -->
      <div v-else-if="authStore.agentFetchFailed" data-testid="asel-read-failed">
        <ReadFailedNotice
          :text="t('agentSelector.readFailed', 'Your agents could not be read just now. They are still there.')"
          :retry="() => authStore.fetchAvailableAgents({ force: true })"
        />
      </div>

      <!-- No agents state -->
      <div v-else class="py-8 text-center">
        <div class="w-16 h-16 mx-auto mb-4 bg-gray-100 dark:bg-gray-800 rounded-full flex items-center justify-center">
          <svg class="w-8 h-8 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
          </svg>
        </div>
        <h3 class="text-lg font-medium text-gray-900 dark:text-white mb-2">
          {{ t('agentSelector.noneTitle', 'No wallet agent yet') }}
        </h3>
        <p class="text-sm text-gray-500 dark:text-gray-400 mb-6">
          {{ t('agentSelector.noneBody', 'This acts as one of your agents. Create your wallet agent first: an identity that holds your funds.') }}
        </p>
        <!-- §pass50.7 — Open QuickAgentModal directly instead of routing -->
        <button
          type="button"
          @click="authStore.showAgentSelector = false; uiStore.openQuickAgentModal()"
          class="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md text-white bg-primary-600 hover:bg-primary-700 focus:outline-hidden focus:ring-2 focus:ring-offset-2 focus:ring-primary-500"
        >
          {{ t('agentSelector.noneCta', 'Create your wallet agent') }}
        </button>
        <p class="text-xs text-gray-500 dark:text-gray-400 mt-3">
          Or
          <router-link
            to="/my-agents"
            @click="authStore.showAgentSelector = false"
            class="text-primary-600 hover:text-primary-700"
          >open AgentForge for advanced setup</router-link>.
        </p>
      </div>
    </div>

    <template #footer>
      <button
        @click="authStore.showAgentSelector = false"
        class="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-md focus:outline-hidden focus:ring-2 focus:ring-offset-2 focus:ring-gray-500"
      >
        Cancel
      </button>
    </template>
  </BaseModal>
  
  <!-- Add Credentials Modal -->
  <AddCredentialsModal
    v-if="selectedAgentForCredentials"
    :show="showAddCredentials"
    :agent="selectedAgentForCredentials"
    @close="showAddCredentials = false"
    @saved="handleCredentialsSaved"
  />
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { useI18n } from '@/composables/useI18n'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { cannotActReason, cannotActSentence } from '@/services/agentActable'
import Icon from '@/components/Icon.vue'
import { computed, ref, watch, nextTick, defineAsyncComponent } from 'vue'
import { useCurrency } from '@/composables/useCurrency'
import { useRegistryFacts } from '@/composables/useActingContext'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import BaseModal from '@/components/BaseModal.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

// DYNAMIC IMPORT - Breaks circular dependency!
const AddCredentialsModal = defineAsyncComponent(() => 
  import('./AddCredentialsModal.vue')
)

const authStore = useAuthStore()
const uiStore = useUIStore()
const { t } = useI18n()
const { localCurrency } = useCurrency()
/**
 * §FOREIGNACT (2026-08-24) — this list can hold agents from SEVERAL registries
 * (imported credentials carry `registry_url`), and every row was labelled with
 * the VIEWER's currency. That is the earliest place the wrong unit appears: you
 * pick the agent here, and everything downstream inherits the misread.
 */
const { ensureFor, currencyFor, nameFor, isForeign: isForeignAgent } = useRegistryFacts()
function agentCcy(a: any): string { return currencyFor(a?.registry_url) }
function agentRegistry(a: any): string { return nameFor(a?.registry_url) }

// State for add credentials modal
const showAddCredentials = ref(false)
const selectedAgentForCredentials = ref<any>(null)

// Force re-render key
const modalKey = ref(0)

// Watch for modal opening to ensure fresh data
watch(() => authStore.showAgentSelector, async (newValue) => {
  if (newValue) {
    import.meta.env.DEV && console.log('[AgentSelector] 🔄 MODAL OPENED - FORCING REFRESH!')
    // FORCE A REFRESH EVERY TIME THE MODAL OPENS
    // Increment key to force complete re-render
    modalKey.value++
    
    // Also force the computed to recalculate
    const agents = [...authStore.availableAgents]
    authStore.availableAgents = []
    await nextTick()
    authStore.availableAgents = agents
    import.meta.env.DEV && console.log('[AgentSelector] ✅ Forced refresh complete! Key:', modalKey.value)
  }
})

// Resolve each foreign registry's card ONCE per origin, off the render path.
watch(() => authStore.availableAgents, (list) => {
  try { ensureFor((list || []).map((a: any) => a?.registry_url)) } catch { /* fail-soft */ }
}, { immediate: true, deep: false })

// Computed property to sort agents: credentials first, then by balance
const sortedAgents = computed(() => {
  import.meta.env.DEV && console.log('[AgentSelector] 🔄 COMPUTED RECALCULATION at', new Date().toISOString())
  import.meta.env.DEV && console.log('[AgentSelector] credentialsChecked:', authStore.credentialsChecked)
  import.meta.env.DEV && console.log('[AgentSelector] Raw agents from store:', authStore.availableAgents.length, 'agents')
  import.meta.env.DEV && console.log('[AgentSelector] Modal Key:', modalKey.value)
  
  if (!authStore.credentialsChecked) {
    import.meta.env.DEV && console.log('[AgentSelector] ⚠️ Credentials not checked yet, returning empty array')
    return [] // Don't show agents until credentials are checked
  }
  
  import.meta.env.DEV && console.log('[AgentSelector] 🕐 CREDENTIAL STATES AT RENDER TIME:')
  authStore.availableAgents.forEach(a => {
    import.meta.env.DEV && console.log(`  ${a.name || 'Unnamed'}: hasCredentials=${a.hasCredentials}, client_id=${!!a.client_id}, secret=${!!a.client_secret}`)
  })
  
  // Simply use the agents as-is since auth store now properly sets hasCredentials
  return [...authStore.availableAgents].sort((a, b) => {
    // First sort by credentials availability
    const aHasCreds = actable(a)
    const bHasCreds = actable(b)
    
    if (aHasCreds && !bHasCreds) return -1
    if (!aHasCreds && bHasCreds) return 1
    
    // Then sort by balance within each group
    const aBalance = a.totalBalance || a.balance || 0
    const bBalance = b.totalBalance || b.balance || 0
    return bBalance - aBalance  // Descending order (highest first)
  })
})

// Helper function to get the appropriate CSS class for an agent card
function getAgentCardClass(agent: any) {
  if (agent.hasInvalidCredentials) {
    return 'border-red-500 ring-2 ring-red-500/20'
  }
  if (actable(agent)) {
    return 'border-green-500 ring-2 ring-green-500/20 hover:shadow-md'
  }
  return 'border-yellow-500 ring-2 ring-yellow-500/20 opacity-60'
}

/** §FESUITE (2026-10-10): can the console act as this agent from here? A secret saved in this browser, or an agent you
 *  own on this registry (the store's canActAs, §FEFRAME W3: it signs in through your session); never one whose saved
 *  secret the registry refused. The picker asked only "is a secret saved here": pressing an owned agent opened "Add
 *  Credentials" for a secret it does not need, and every owned agent read "No secret saved in this browser". */
function actable(agent: any): boolean {
  // §MCPTEST30 (V0640): a revoked or suspended agent cannot act, whatever secret this browser saved for it
  if (!agent || agent.hasInvalidCredentials || cannotActReason(agent)) return false
  return agent.hasCredentials === true || !!authStore.canActAs?.(agent)
}

async function selectAgent(agent: any) {
  // §MCPTEST30 (V0640): a revoked or suspended agent is said as such, before any credentials door (agentvault2-5b's
  // code read: its row read "No secret saved in this browser" and a press opened Add Credentials for an agent that
  // cannot act by any road)
  const cannot = cannotActReason(agent)
  if (cannot) {
    uiStore.showError(cannot === 'revoked' ? 'Agent deleted' : 'Agent suspended', cannotActSentence(agent, cannot))
    return
  }
  if (agent.hasInvalidCredentials) {
    // §FEFRAME W1: a refused secret opens the re-entry instead of a dead end
    openAddCredentialsModal(agent)
    return
  }

  // An agent the console cannot act as from here: the modal to add its secret
  if (!actable(agent)) {
    import.meta.env.DEV && console.log('[AgentSelector] Agent missing credentials, opening modal:', agent.did)
    openAddCredentialsModal(agent)
    return
  }
  
  // Loading feedback
  uiStore.showInfo(
    'Authenticating...',
    `Switching to ${agent.name || agent.did}`
  )
  
  const success = await authStore.switchAgent(agent.did)
  
  if (success) {
    authStore.showAgentSelector = false
  }
}

function formatBalance(balance: string | number): string {
  const num = typeof balance === 'string' ? parseFloat(balance) : balance
  return num.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** §FEFRAME W1 — how many agents in the list hold a saved secret in this browser (drives "Forget all"). */
const savedCount = computed(() => authStore.availableAgents.filter((a: any) => a.hasCredentials === true || a.hasInvalidCredentials).length)

function forgetOne(agent: any) {
  authStore.forgetCredential(agent.did)
  uiStore.showInfo(t('agentSelector.forgotTitle', 'Secret forgotten'), `${agent.name || agent.did}`)
}

/** §FEFRAME W1 — the saved secrets as the bulk importer's own file (each row names its registry). */
function downloadSaved() {
  const rows = agentCredentialsStore.exportVisible(window.location.origin)
  if (!rows.length) return
  const blob = new Blob([JSON.stringify(rows, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `agent-credentials-${window.location.hostname}.json`
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function forgetAll() {
  if (!window.confirm(t('agentSelector.forgetAllConfirm', 'Forget every agent secret saved in this browser for this account? You will need to re-enter or re-import them.'))) return
  authStore.forgetAllCredentials()
  uiStore.showInfo(t('agentSelector.forgotAllTitle', 'Saved secrets forgotten'), '')
}

function openAddCredentialsModal(agent: any) {
  selectedAgentForCredentials.value = agent
  showAddCredentials.value = true
}

function handleCredentialsSaved() {
  showAddCredentials.value = false
  selectedAgentForCredentials.value = null
  // Refresh the agents list to show updated credentials
  authStore.fetchAvailableAgents()
}
</script>
