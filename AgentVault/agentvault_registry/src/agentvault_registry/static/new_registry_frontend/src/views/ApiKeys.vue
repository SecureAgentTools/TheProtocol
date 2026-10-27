<script setup lang="ts">
import { ref, onMounted, reactive, computed } from 'vue'
import { developerApi } from '@/services/api/developer'
import { useUIStore } from '@/stores/ui'
import { formatDate } from '@/utils/date'
import NeuralCard from '@/components/ui/NeuralCard.vue'
import NeuralIcon from '@/components/ui/NeuralIcon.vue'
import { useI18n } from '@/composables/useI18n'
import type { ApiKey } from '@/services/api/developer'
import { messageOf } from '@/utils/httpError'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('ApiKeys')

const { t } = useI18n()
const uiStore = useUIStore()

// State
const isLoading = ref(true)
const apiKeys = ref<ApiKey[]>([])
// §FESUITE (2026-10-05): a failed list read said "You haven't created any API keys yet." (under a toast); it says the read
// failed in place now, with Try again. A failed refresh keeps the list that was shown.
const keysRead = ref<'loading' | 'ok' | 'failed'>('loading')
const showCreateModal = ref(false)
const showDeleteConfirm = ref(false)
const keyToDelete = ref<ApiKey | null>(null)
const isCreating = ref(false)
const isDeleting = ref(false)

// Form state
const newKeyForm = reactive({
  description: '',
  // §FEPARITY-1 — AL-4 narrowing (previously FE-unreachable)
  scopeMode: 'full' as 'full' | 'scoped',
  scopesText: '',
  expiresDays: null as number | null,
})

// Newly created key (only shown once)
const createdKey = ref<string | null>(null)

// §pass66.8 — MCP bridge download snippets. The current page's
// window.location.origin IS the registry URL the developer should target
// (the SPA loads from the same origin as the API). Snippets are paste-ready
// for THIS registry; developers pointing elsewhere just swap the URL.
const detectedRegistryUrl = computed(() => {
  if (typeof window === 'undefined') return 'https://api.theprotocol.cloud'
  return window.location.origin
})

const claudeCodeSnippet = computed(() => `{
  "mcpServers": {
    "theprotocol-prod": {
      "command": "/usr/local/bin/node",
      "args": ["/path/to/mcp-stdio-bridge.js"],
      "env": {
        "THEPROTOCOL_API_URL": "${detectedRegistryUrl.value}",
        "THEPROTOCOL_API_KEY": "YOUR_API_KEY_HERE"
      }
    }
  }
}`)

const claudeDesktopSnippet = computed(() => `{
  "mcpServers": {
    "theprotocol-prod": {
      "command": "node",
      "args": ["/path/to/mcp-stdio-bridge.js"],
      "env": {
        "THEPROTOCOL_API_URL": "${detectedRegistryUrl.value}",
        "THEPROTOCOL_API_KEY": "YOUR_API_KEY_HERE"
      }
    }
  }
}`)

async function copySnippet(text: string, label: string) {
  try {
    await navigator.clipboard.writeText(text)
    uiStore.showNotification({
      type: 'success',
      title: 'Copied',
      message: `${label} copied to clipboard. Paste into your config file and replace YOUR_API_KEY_HERE.`
    })
  } catch (e: any) {
    uiStore.showNotification({
      type: 'error',
      title: 'Copy failed',
      message: 'Select the snippet manually and copy.'
    })
  }
}

// Load API keys
const loadApiKeys = async () => {
  isLoading.value = true
  if (keysRead.value !== 'ok') keysRead.value = 'loading'
  try {
    apiKeys.value = await developerApi.listApiKeys()
    keysRead.value = 'ok'
  } catch (error: any) {
    log.warn('Failed to load API keys:', error)
    if (keysRead.value !== 'ok') keysRead.value = 'failed'
  } finally {
    isLoading.value = false
  }
}

// Create new API key
const createApiKey = async () => {
  // §FESUITE — Enter on the name field calls this too, and the field is not disabled while a key is minted: without
  // this a second Enter minted a second key (the disabled button guards only the button).
  if (isCreating.value) return
  if (!newKeyForm.description.trim()) {
    uiStore.showNotification({
      type: 'error',
      title: 'Description required',
      message: 'Please provide a description for the API key'
    })
    return
  }

  isCreating.value = true
  try {
    const scopes = newKeyForm.scopeMode === 'scoped'
      ? newKeyForm.scopesText.split(',').map(s => s.trim()).filter(Boolean)
      : undefined
    const response = await developerApi.createApiKey(newKeyForm.description.trim(), {
      scopes,
      expires_in_days: newKeyForm.expiresDays ?? undefined,   // 0 passes through = non-expiring
    })
    
    // The plain API key is only returned on creation
    const responseAny = response as any
    if (responseAny.plain_api_key) {
      createdKey.value = responseAny.plain_api_key
    } else if (response.key) {
      createdKey.value = response.key
    }
    
    // Add the new key info to the list (a list that was never read is read now: never the new key shown alone)
    apiKeys.value.unshift(responseAny.api_key_info || response)
    if (keysRead.value !== 'ok') void loadApiKeys()
    
    // Reset form
    newKeyForm.description = ''
    newKeyForm.scopeMode = 'full'
    newKeyForm.scopesText = ''
    newKeyForm.expiresDays = null
    showCreateModal.value = false
    
    uiStore.showNotification({
      type: 'success',
      title: 'API Key Created',
      message: 'Your new API key has been created. Make sure to copy it now!'
    })
  } catch (error: any) {
    console.error('Failed to create API key:', error)
    uiStore.showNotification({
      type: 'error',
      title: 'Failed to create API key',
      message: messageOf(error?.response?.data, error?.message || 'An error occurred')
    })
  } finally {
    isCreating.value = false
  }
}

// Copy to clipboard
const copyToClipboard = async (text: string) => {
  try {
    await navigator.clipboard.writeText(text)
    uiStore.showNotification({
      type: 'success',
      title: 'Copied!',
      message: 'API key copied to clipboard'
    })
  } catch (error) {
    console.error('Failed to copy to clipboard:', error)
    uiStore.showNotification({
      type: 'error',
      title: 'Copy failed',
      message: 'Failed to copy to clipboard'
    })
  }
}

// Confirm delete
const confirmDelete = (key: ApiKey) => {
  keyToDelete.value = key
  showDeleteConfirm.value = true
}

// Delete API key
const deleteApiKey = async () => {
  if (!keyToDelete.value) return

  isDeleting.value = true
  try {
    await developerApi.deleteApiKey(String(keyToDelete.value.id))
    
    // Remove from list
    apiKeys.value = apiKeys.value.filter(k => k.id !== keyToDelete.value?.id)
    
    uiStore.showNotification({
      type: 'success',
      title: 'API Key Deleted',
      message: 'The API key has been deleted'
    })
    
    showDeleteConfirm.value = false
    keyToDelete.value = null
  } catch (error: any) {
    console.error('Failed to delete API key:', error)
    uiStore.showNotification({
      type: 'error',
      title: 'Failed to delete API key',
      message: error.message || 'An error occurred'
    })
  } finally {
    isDeleting.value = false
  }
}

// Mount hook
onMounted(() => {
  loadApiKeys()
})
</script>

<template>
  <div class="nc-page">
    <div class="nc-header">
      <div class="flex justify-between items-center">
        <div>
          <h1 class="nc-h1" data-tour="key-hero">
            <NeuralIcon name="key" :size="24" />
            <span>{{ t('apiKeysView.hero.h1') }}</span>
          </h1>
          <p class="nc-subtitle">
            Manage your API keys for programmatic access
          </p>
        </div>
        <button
          @click="showCreateModal = true"
          class="nc-btn nc-btn-primary"
          data-tour="key-new"
        >
          <NeuralIcon name="plus" :size="18" />
          <span>Create New Key</span>
        </button>
      </div>

      <!-- Loading State -->
      <div v-if="isLoading" class="mt-8 flex justify-center">
        <div class="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500"></div>
      </div>

      <!-- Content -->
      <div v-else class="mt-8">
        <!-- Created Key Alert -->
        <NeuralCard
          v-if="createdKey"
          variant="elevated"
          accent="success"
          class="mb-6"
          data-tour="key-reveal"
        >
          <div class="flex items-start">
            <NeuralIcon name="check-circle" :size="20" class="text-green-400 mt-0.5" />
            <div class="ml-3 flex-1">
              <h3 class="text-sm font-medium nc-text-primary">
                New API Key Created
              </h3>
              <p class="mt-1 text-sm nc-text-secondary">
                This is your API key. Copy it now as it won't be shown again!
              </p>
              <div class="mt-3 flex items-center gap-2">
                <code class="flex-1 nc-bg-void px-3 py-2 rounded-sm border border-green-700 text-sm font-mono text-green-400">
                  {{ createdKey }}
                </code>
                <button
                  @click="copyToClipboard(createdKey)"
                  class="nc-btn nc-btn-success"
                >
                  Copy
                </button>
                <button
                  @click="createdKey = null"
                  class="nc-btn nc-btn-secondary"
                >
                  Done
                </button>
              </div>
            </div>
          </div>
        </NeuralCard>

        <NeuralCard v-if="keysRead === 'failed'" variant="elevated" class="p-8" data-tour="key-list">
          <ReadFailedNotice :retry="loadApiKeys" />
        </NeuralCard>

        <!-- Empty State -->
        <NeuralCard v-else-if="apiKeys.length === 0" variant="elevated" class="p-8 text-center" data-tour="key-list">
          <NeuralIcon name="key" :size="64" class="mx-auto nc-text-muted mb-4" />
          <p class="nc-text-secondary mb-4">
            You haven't created any API keys yet.
          </p>
          <button
            @click="showCreateModal = true"
            class="nc-text-accent hover:underline font-medium"
          >
            Create your first API key →
          </button>
        </NeuralCard>
        
        <!-- API Keys List -->
        <div v-else class="space-y-4" data-tour="key-list">
          <NeuralCard
            v-for="key in apiKeys"
            :key="key.id"
            variant="elevated"
            class="p-6"
          >
            <div class="flex items-start justify-between">
              <div class="flex-1">
                <div class="flex items-center gap-3">
                  <h3 class="text-lg font-medium nc-text-primary">
                    {{ key.description || 'Unnamed API Key' }}
                  </h3>
                  <span
                    :class="[
                      'inline-flex items-center px-2 py-1 rounded-full text-xs font-medium',
                      key.is_active
                        ? 'bg-green-900 text-green-300'
                        : 'bg-red-900 text-red-300'
                    ]"
                  >
                    {{ key.is_active ? 'Active' : 'Inactive' }}
                  </span>
                </div>
                <div class="mt-2 space-y-1">
                  <p class="text-sm nc-text-secondary">
                    <span class="font-medium">Key ID:</span> {{ key.id }}
                  </p>
                  <p class="text-sm nc-text-secondary">
                    <span class="font-medium">Prefix:</span> 
                    <code class="nc-bg-void px-2 py-0.5 rounded-sm">{{ key.key_prefix }}...</code>
                  </p>
                  <p class="text-sm nc-text-secondary">
                    <span class="font-medium">Created:</span> {{ formatDate(key.created_at) }}
                  </p>
                  <p v-if="key.last_used_at" class="text-sm nc-text-secondary">
                    <span class="font-medium">Last used:</span> {{ formatDate(key.last_used_at) }}
                  </p>
                  <!-- §FEPARITY-1: AL-4 fields, previously dropped end-to-end -->
                  <p class="text-sm nc-text-secondary">
                    <span class="font-medium">Scopes:</span>
                    <span v-if="!key.scopes || key.scopes.includes('*')">full authority</span>
                    <code v-else class="nc-bg-void px-2 py-0.5 rounded-sm">{{ key.scopes.join(', ') }}</code>
                  </p>
                  <p class="text-sm nc-text-secondary">
                    <span class="font-medium">Expires:</span>
                    {{ key.expires_at ? formatDate(key.expires_at) : 'never' }}
                  </p>
                </div>
              </div>
              <button
                @click="confirmDelete(key)"
                class="ml-4 p-2 text-red-400 hover:bg-red-900/20 rounded-lg transition-colors"
                title="Delete API key"
              >
                <NeuralIcon name="trash-2" :size="20" />
              </button>
            </div>
          </NeuralCard>
        </div>
      </div>

      <!-- API Documentation Link -->
      <NeuralCard variant="elevated" accent="primary" class="mt-8 p-6">
        <h3 class="text-lg font-medium nc-text-primary mb-2">
          <NeuralIcon name="book-open" :size="20" class="inline mr-2" />
          API Documentation
        </h3>
        <p class="nc-text-secondary mb-4">
          Learn how to use the Registry API in your applications.
        </p>
        <a
          href="https://docs.theprotocol.cloud/api"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center nc-text-accent hover:underline font-medium"
        >
          View Documentation →
        </a>
      </NeuralCard>

      <!-- §pass66.8 (2026-05-23) — MCP Bridge for Claude Code / Claude Desktop.
           The JS bridge file is served at /api/v1/downloads/mcp-stdio-bridge.js.
           Code contains no secrets; developer sets THEPROTOCOL_API_KEY env to
           their own API key (created above). Registry URL auto-detected from
           the page's window.location.origin so the config snippet is
           paste-ready for the registry this UI was opened from. -->
      <NeuralCard variant="elevated" accent="cyan" class="mt-6 p-6" data-tour="key-usage">
        <h3 class="text-lg font-medium nc-text-primary mb-2">
          <NeuralIcon name="terminal" :size="20" class="inline mr-2" />
          MCP Bridge — Claude Code / Claude Desktop
        </h3>
        <p class="nc-text-secondary mb-4">
          Plug TheProtocol into Claude Code or Claude Desktop. The bridge is a
          single Node.js file (no npm deps) that proxies MCP tool calls to this
          registry over HTTPS. Create an API key above, then download the bridge
          and configure your Claude client.
        </p>

        <!-- Download buttons -->
        <div class="flex flex-wrap gap-3 mb-5">
          <a
            :href="`${detectedRegistryUrl}/api/v1/downloads/mcp-stdio-bridge.js`"
            download="mcp-stdio-bridge.js"
            class="nc-btn nc-btn-primary inline-flex items-center gap-2"
          >
            <NeuralIcon name="download" :size="16" />
            Download mcp-stdio-bridge.js
          </a>
          <a
            :href="`${detectedRegistryUrl}/api/v1/downloads/mcp-stdio-bridge-admin.js`"
            download="mcp-stdio-bridge-admin.js"
            class="nc-btn inline-flex items-center gap-2"
            title="Admin bridge — adminRequest, adminQueryEventStore, etc. Tool calls require an admin developer JWT at runtime."
          >
            <NeuralIcon name="download" :size="16" />
            Admin bridge (optional)
          </a>
        </div>

        <!-- Detected registry URL banner -->
        <div class="mb-4 p-3 rounded-lg" style="background: rgba(0,210,210,0.08); border: 1px solid rgba(0,210,210,0.2);">
          <p class="text-sm nc-text-secondary mb-1">
            Snippets below are pre-filled for this registry:
          </p>
          <code class="text-cyan-400 font-mono text-sm">{{ detectedRegistryUrl }}</code>
          <p class="text-xs nc-text-muted mt-2">
            Pointing at a different registry? Replace <code>THEPROTOCOL_API_URL</code>
            in your config with that registry's URL (e.g. <code>https://frame-b.theprotocol.cloud</code>
            or <code>https://op-london.op.theprotocol.cloud</code>).
          </p>
        </div>

        <!-- Step 1: install -->
        <div class="mb-4">
          <p class="text-sm font-medium nc-text-primary mb-2">
            1. Save the file somewhere stable (~/.local/share/ or your project dir).
          </p>
        </div>

        <!-- Step 2: claude code config -->
        <div class="mb-4">
          <p class="text-sm font-medium nc-text-primary mb-2">
            2a. Claude Code — add to <code>~/.claude.json</code> under <code>mcpServers</code>:
          </p>
          <div class="relative">
            <pre class="nc-code-block p-3 rounded-sm text-xs overflow-x-auto" style="background: rgba(0,0,0,0.45); border: 1px solid rgba(255,255,255,0.08);">{{ claudeCodeSnippet }}</pre>
            <button
              @click="copySnippet(claudeCodeSnippet, 'Claude Code config')"
              class="absolute top-2 right-2 nc-btn-sm"
              title="Copy to clipboard"
            >
              <NeuralIcon name="copy" :size="14" />
            </button>
          </div>
        </div>

        <!-- Step 3: claude desktop config -->
        <div class="mb-4">
          <p class="text-sm font-medium nc-text-primary mb-2">
            2b. Claude Desktop — add to <code>~/Library/Application Support/Claude/claude_desktop_config.json</code>
            (macOS) or <code>%APPDATA%\Claude\claude_desktop_config.json</code> (Windows):
          </p>
          <div class="relative">
            <pre class="nc-code-block p-3 rounded-sm text-xs overflow-x-auto" style="background: rgba(0,0,0,0.45); border: 1px solid rgba(255,255,255,0.08);">{{ claudeDesktopSnippet }}</pre>
            <button
              @click="copySnippet(claudeDesktopSnippet, 'Claude Desktop config')"
              class="absolute top-2 right-2 nc-btn-sm"
              title="Copy to clipboard"
            >
              <NeuralIcon name="copy" :size="14" />
            </button>
          </div>
        </div>

        <p class="text-xs nc-text-muted">
          Replace <code>YOUR_API_KEY_HERE</code> with your <code>avreg_...</code> key from above
          and <code>/path/to/mcp-stdio-bridge.js</code> with the absolute path to where you saved the file.
          Restart Claude Code / Desktop. The <code>theprotocol-prod</code> server should connect and
          expose 17 tools (Tier 1 public discovery + Tier 2 agent ops + Tier 3 developer ops).
        </p>
      </NeuralCard>
    </div>

    <!-- Create Modal -->
    <Teleport to="body">
      <div
        v-if="showCreateModal"
        class="fixed inset-0 bg-black/75 flex items-center justify-center p-4 z-50"
      >
        <NeuralCard variant="elevated" class="max-w-md w-full p-6">
          <h3 class="nc-h2 mb-4">
            Create New API Key
          </h3>
          
          <div class="mb-4">
            <label class="block text-sm font-medium nc-text-primary mb-2">
              Description <span class="text-red-500">*</span>
            </label>
            <input
              v-model="newKeyForm.description"
              type="text"
              placeholder="e.g., Production server key"
              class="nc-input"
              data-tour="key-name"
              maxlength="200"
              aria-label="Description"
              @keyup.enter="createApiKey"
            />
            <p class="mt-1 text-sm nc-text-muted">
              A description helps you identify this key later
            </p>
          </div>

          <!-- §FEPARITY-1: AL-4 narrowing — scopes + forced-rotation expiry -->
          <div class="mb-4">
            <label class="block text-sm font-medium nc-text-primary mb-2">Authority</label>
            <div class="flex gap-4 text-sm nc-text-secondary">
              <label class="flex items-center gap-2 cursor-pointer">
                <input v-model="newKeyForm.scopeMode" type="radio" value="full" :disabled="isCreating" />
                Full authority <code class="nc-bg-void px-1 rounded-sm">*</code>
              </label>
              <label class="flex items-center gap-2 cursor-pointer">
                <input v-model="newKeyForm.scopeMode" type="radio" value="scoped" :disabled="isCreating" />
                Scoped
              </label>
            </div>
            <div v-if="newKeyForm.scopeMode === 'scoped'" class="mt-2">
              <input
                v-model="newKeyForm.scopesText"
                type="text"
                placeholder="comma-separated, e.g. read:public, keys:manage"
                class="nc-input"
                data-tour="key-scopes"
              />
              <p class="mt-1 text-sm nc-text-muted">
                A scoped key cannot create further keys unless it carries
                <code class="nc-bg-void px-1 rounded-sm">keys:manage</code>. Scope enforcement
                widens progressively — narrow keys are the safe default for external systems.
              </p>
            </div>
          </div>

          <div class="mb-4">
            <label class="block text-sm font-medium nc-text-primary mb-2">Expires in (days)</label>
            <input
              v-model.number="newKeyForm.expiresDays"
              type="number"
              min="0"
              placeholder="server default (365) — 0 = never expires"
              class="nc-input"
              data-tour="key-expiry"
            />
          </div>

          <div class="flex justify-end gap-3">
            <button
              @click="showCreateModal = false"
              :disabled="isCreating"
              class="nc-btn nc-btn-secondary"
            >
              Cancel
            </button>
            <button
              @click="createApiKey"
              :disabled="isCreating || !newKeyForm.description.trim()"
              class="nc-btn nc-btn-primary"
            >
              {{ isCreating ? 'Creating...' : 'Create API Key' }}
            </button>
          </div>
        </NeuralCard>
      </div>
    </Teleport>

    <!-- Delete Confirmation -->
    <Teleport to="body">
      <div
        v-if="showDeleteConfirm"
        class="fixed inset-0 bg-black/75 flex items-center justify-center p-4 z-50"
      >
        <NeuralCard variant="elevated" class="max-w-md w-full p-6">
          <h3 class="nc-h2 mb-4">
            Delete API Key
          </h3>
          <p class="nc-text-secondary mb-6">
            Are you sure you want to delete this API key? This action cannot be undone.
          </p>
          
          <NeuralCard v-if="keyToDelete" variant="elevated" class="mb-6 p-3">
            <p class="text-sm font-medium nc-text-primary">
              {{ keyToDelete.description || 'Unnamed API Key' }}
            </p>
            <p class="text-sm nc-text-muted">
              {{ keyToDelete.key_prefix }}...
            </p>
          </NeuralCard>
          
          <div class="flex justify-end gap-3">
            <button
              @click="showDeleteConfirm = false"
              :disabled="isDeleting"
              class="nc-btn nc-btn-secondary"
            >
              Cancel
            </button>
            <button
              @click="deleteApiKey"
              :disabled="isDeleting"
              class="nc-btn nc-btn-danger"
            >
              {{ isDeleting ? 'Deleting...' : 'Delete API Key' }}
            </button>
          </div>
        </NeuralCard>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
/* Neural Command styles are applied through classes */

/* §pass41 (2026-05-18) — Defensive bg. Page renders correctly today because
   DashboardLayout's ViewAmbient paints behind it; this rule keeps the view
   solid even if the layout shell is bypassed or refactored. Theme-cycle
   compatible via var(--st-bg). */
.nc-page {
  min-height: 100vh;
  background: var(--st-bg, #0f1117);
  /* the page's own frame, as the webhooks page has (the camera, 2026-10-13: the title sat on the sidebar's edge under the
     top bar, the create button and the cards ran to the window's edge; .nc-page is defined nowhere else) */
  padding: 2rem;
}
.nc-page > * { max-width: 1440px; margin-left: auto; margin-right: auto; }
.nc-h1 { display: inline-flex; align-items: center; gap: 0.6rem; }
/* a config path (%APPDATA%\\Claude\\claude_desktop_config.json) breaks where it must on a phone instead of running past the
   card (the camera, 2026-10-13); code blocks keep their own scrolling */
code { overflow-wrap: anywhere; }
@media (max-width: 640px) {
  .nc-page { padding: 1rem; }
}
</style>
