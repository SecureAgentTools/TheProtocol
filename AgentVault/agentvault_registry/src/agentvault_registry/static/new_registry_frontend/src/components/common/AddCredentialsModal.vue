<template>
  <Teleport to="body">
    <div v-if="show" class="tp-overlay" @click.self="emit('close')">
      <div class="tp-modal" role="dialog" aria-modal="true" aria-labelledby="add-creds-title">
        <!-- Header -->
        <div class="tp-modal-header">
          <span id="add-creds-title" class="tp-modal-title">+ Add Agent Credentials</span>
          <button class="tp-modal-close" @click="emit('close')" aria-label="Close">✕</button>
        </div>

        <!-- Body -->
        <div class="tp-modal-body">
          <!-- Agent target -->
          <div class="ac-agent-card">
            <div class="ac-agent-name">{{ agent.name || 'Unnamed Agent' }}</div>
            <div class="ac-agent-did">{{ agent.did }}</div>
          </div>

          <p class="tp-banner tp-banner--info">
            Paste the <strong>client_id</strong> + <strong>client_secret</strong> issued when this
            agent was created. They're stored only in your browser's local storage so re-auth
            after reload works without re-pasting.
          </p>

          <form @submit.prevent="save" class="ac-form">
            <div class="tp-field">
              <label for="ac-client-id" class="tp-label">Client ID</label>
              <input
                id="ac-client-id"
                ref="firstInputRef"
                v-model="clientId"
                type="text"
                class="tp-input"
                placeholder="agent-xxxxxxxxxxxxxxxx"
                autocomplete="off"
                spellcheck="false"
                required
              />
              <p class="tp-hint">Usually starts with <code>agent-</code> followed by 16 hex chars.</p>
            </div>

            <div class="tp-field">
              <label for="ac-client-secret" class="tp-label">Client Secret</label>
              <div class="ac-secret-wrap">
                <input
                  id="ac-client-secret"
                  v-model="clientSecret"
                  :type="revealSecret ? 'text' : 'password'"
                  class="tp-input ac-secret-input"
                  placeholder="tp_secret_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                  autocomplete="off"
                  spellcheck="false"
                  required
                />
                <button
                  type="button"
                  class="ac-secret-toggle"
                  :title="revealSecret ? 'Hide secret' : 'Show secret'"
                  :aria-label="revealSecret ? 'Hide secret' : 'Show secret'"
                  @click="revealSecret = !revealSecret"
                >
                  <svg v-if="!revealSecret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/>
                    <circle cx="12" cy="12" r="3"/>
                  </svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/>
                    <line x1="1" y1="1" x2="23" y2="23"/>
                  </svg>
                </button>
              </div>
              <p class="tp-hint">Usually starts with <code>tp_secret_</code>. Shown <strong>only once</strong> at agent creation.</p>
            </div>

            <label class="ac-checkbox">
              <input v-model="testFirst" type="checkbox" />
              <span>Verify with backend before saving (recommended)</span>
            </label>

            <p v-if="errorMsg" class="tp-banner tp-banner--danger" role="alert">{{ errorMsg }}</p>
            <p v-if="successMsg" class="tp-banner tp-banner--success" role="status">{{ successMsg }}</p>

            <p class="tp-banner tp-banner--warn" style="font-size: 0.78rem; margin-bottom: 0;">
              <strong>Security notice:</strong> credentials live in browser localStorage for this
              origin. Anyone with access to your browser profile can use this agent. Rotate the
              secret + re-onboard if the device is shared.
            </p>
          </form>
        </div>

        <!-- Footer -->
        <div class="tp-modal-footer">
          <button class="tp-btn tp-btn--ghost" @click="emit('close')" :disabled="saving">Cancel</button>
          <button
            class="tp-btn tp-btn--primary"
            :disabled="!clientId || !clientSecret || saving"
            @click="save"
          >
            <span v-if="saving" class="tp-spinner" />
            <span>{{ saving ? 'Saving…' : (testFirst ? 'Verify + Save' : 'Save') }}</span>
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import { ref, watch, nextTick } from 'vue'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { agentApi } from '@/services/api/agents'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'

const props = defineProps<{
  show: boolean
  // §FEFRAME W1: where the agent lives travels with it, so a re-entered secret keeps its registry
  agent: { did: string; name?: string; humanReadableId?: string; registry?: string; registry_url?: string }
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved'): void
}>()

const uiStore = useUIStore()
const authStore = useAuthStore()

const clientId = ref('')
const clientSecret = ref('')
const revealSecret = ref(false)
const testFirst = ref(true)
const saving = ref(false)
const errorMsg = ref('')
const successMsg = ref('')

const firstInputRef = ref<HTMLInputElement | null>(null)

// Reset + focus on open
watch(
  () => props.show,
  async (v) => {
    if (v) {
      clientId.value = ''
      clientSecret.value = ''
      errorMsg.value = ''
      successMsg.value = ''
      saving.value = false
      revealSecret.value = false
      testFirst.value = true
      await nextTick()
      firstInputRef.value?.focus()
    }
  },
)

async function save() {
  errorMsg.value = ''
  successMsg.value = ''
  saving.value = true

  try {
    let accessToken: string | null = null

    if (testFirst.value) {
      try {
        // §FEFRAME W1: verify where the agent lives (a foreign agent's registry), on the bare client
        const verified = await agentApi.authenticate(props.agent.did, {
          client_id: clientId.value.trim(),
          client_secret: clientSecret.value.trim(),
        }, props.agent.registry_url || undefined)
        accessToken = verified?.access_token ?? null
        successMsg.value = 'Credentials verified.'
      } catch (e: any) {
        const status = e?.response?.status
        if (!e?.response) {
          errorMsg.value = "This console cannot reach the agent's registry (it does not accept this console yet, or it is offline). Nothing was saved."
        } else if (status === 401 || status === 403) {
          errorMsg.value = 'Backend rejected the credentials (invalid client_id or client_secret).'
        } else if (status === 404) {
          errorMsg.value = 'Agent not found on this registry. Check the DID matches.'
        } else {
          errorMsg.value = e?.message || 'Verification call failed. Try again or uncheck "verify before saving".'
        }
        saving.value = false
        return
      }
    }

    // §FEFRAME W1: keep WHERE the agent lives; re-entering a foreign agent's secret used to drop its registry address
    agentCredentialsStore.storeCredentials({
      did: props.agent.did,
      client_id: clientId.value.trim(),
      client_secret: clientSecret.value.trim(),
      name: props.agent.name,
      humanReadableId: props.agent.humanReadableId,
      registry: props.agent.registry,
      registry_url: props.agent.registry_url,
    })

    if (accessToken) {
      authStore.setActiveAgentFromToken(
        {
          ...props.agent,
          client_id: clientId.value.trim(),
          client_secret: clientSecret.value.trim(),
          name: props.agent.name,
        },
        accessToken,
      )
    }

    uiStore.showSuccess(
      'Credentials Saved',
      `${props.agent.name || props.agent.did.slice(0, 24) + '…'} ${accessToken ? 'is now your active agent.' : 'now has stored credentials.'}`,
    )

    emit('saved')
    emit('close')
  } catch (e: any) {
    errorMsg.value = e?.message || 'Save failed. Try again.'
  } finally {
    saving.value = false
  }
}

// Escape closes this dialog wherever the focus is, the topmost one only (composables/useEscapeClose: an
// @keydown.esc on the overlay heard nothing while the focus stayed on the button that opened it)
useEscapeClose(() => props.show, () => emit('close'))
</script>

<style scoped>
@import '@/components/disputes/tp-disputes-modals.css';

.ac-agent-card {
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 8px;
  padding: 0.75rem 0.9rem;
  margin-bottom: 1rem;
}
.ac-agent-name {
  font-family: 'Orbitron', sans-serif;
  font-size: 0.95rem;
  font-weight: 600;
  color: #e2e8f0;
  margin-bottom: 0.2rem;
}
.ac-agent-did {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: #6b7e96;
  word-break: break-all;
}

.ac-form .tp-field:last-of-type { margin-bottom: 0.85rem; }

.ac-secret-wrap { position: relative; }
.ac-secret-input { padding-right: 2.4rem; font-family: 'IBM Plex Mono', monospace; font-size: 0.78rem; }
.ac-secret-toggle {
  position: absolute;
  right: 0.5rem;
  top: 50%;
  transform: translateY(-50%);
  background: transparent;
  border: 0;
  color: #6b7e96;
  cursor: pointer;
  padding: 4px;
  display: inline-flex;
  align-items: center;
  border-radius: 4px;
}
.ac-secret-toggle:hover { color: rgb(0, 210, 210); background: rgba(var(--nc-primary-rgb), 0.08); }

.ac-checkbox {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
  color: #c8d6e8;
  margin: 0.6rem 0 0.85rem;
  cursor: pointer;
  user-select: none;
}
.ac-checkbox input[type='checkbox'] {
  width: 16px; height: 16px;
  accent-color: rgb(0, 210, 210);
  cursor: pointer;
}

code {
  background: rgba(var(--nc-primary-rgb), 0.1);
  border-radius: 3px;
  padding: 1px 5px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem;
  color: rgb(0, 210, 210);
}
</style>
