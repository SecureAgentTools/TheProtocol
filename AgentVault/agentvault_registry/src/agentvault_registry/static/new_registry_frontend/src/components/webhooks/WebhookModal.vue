<template>
  <Teleport to="body">
    <div class="wh-modal-backdrop">
      <div class="flex min-h-screen items-center justify-center p-4">
        <!-- Overlay -->
        <div class="fixed inset-0 bg-black/70 backdrop-blur-xs" @click="handleBackdropClick"></div>

        <!-- Modal -->
        <!-- §COCKPITDESK (2026-10-15): a dialog for assistive tech, and Escape closes it like every other door -->
        <div ref="panelRef" class="wh-modal relative w-full max-w-3xl" role="dialog" aria-modal="true" aria-labelledby="wh-modal-title" data-testid="wh-modal">

          <!-- ══ HEADER ══ -->
          <div class="wh-modal-header flex items-start justify-between">
            <div>
              <div class="wh-modal-eyebrow">
                {{ secretStep ? '// SECURITY // SAVE SECRET' : (isEditing ? '// EDIT // WEBHOOK' : '// NEW // WEBHOOK') }}
              </div>
              <div id="wh-modal-title" class="wh-modal-title">
                {{ secretStep ? 'Webhook Secret' : (isEditing ? 'Edit Webhook' : 'Create Webhook') }}
              </div>
              <p class="text-xs mt-1" style="color:var(--nc-text-muted);font-family:'IBM Plex Mono',monospace">
                {{ secretStep ? 'Save this secret now — it will never be shown again' : 'Configure HTTP callback endpoint and event subscriptions' }}
              </p>
            </div>
            <button
              v-if="secretStep"
              @click="$emit('close')"
              style="color:var(--nc-text-muted);background:none;border:none;cursor:pointer;padding:0.25rem"
            >✕</button>
          </div>

          <!-- ══ SECRET STEP ══ -->
          <div v-if="secretStep" class="p-6">
            <div class="wh-secret-panel">
              <div class="wh-secret-title"><Icon name="mdi:alert" /> ONE-TIME SECRET</div>
              <p style="font-size:0.8rem;color:#f59e0b;line-height:1.5">
                This secret is used to verify webhook signatures via <code style="font-size:0.75rem">X-TheProtocol-Signature</code>.
                Copy it now — it cannot be retrieved after closing this dialog.
              </p>
              <div class="wh-secret-code">
                <code>{{ webhookSecret }}</code>
                <button @click="copySecret" class="webhook-btn webhook-btn--test" style="padding:0.25rem 0.6rem;font-size:0.65rem">
                  {{ copied ? 'COPIED ✓' : 'COPY' }}
                </button>
              </div>
            </div>
            <div class="mt-4 p-3 rounded-sm" style="background:rgba(var(--nc-primary-rgb),0.04);border:1px solid rgba(var(--nc-primary-rgb),0.12);font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:var(--nc-text-secondary)">
              Webhook created for <span style="color:var(--nc-primary)">{{ createdUrl }}</span>
            </div>
          </div>

          <!-- ══ FORM BODY ══ -->
          <div v-else class="p-6 space-y-6">

            <!-- URL -->
            <div>
              <label class="wh-field-label">
                Endpoint URL <span style="color:var(--nc-danger)">*</span>
              </label>
              <input
                v-model="formData.url"
                type="url"
                maxlength="500"
                aria-label="Endpoint URL"
                placeholder="https://your-server.com/webhook"
                class="wh-input"
                :class="{ 'wh-input--error': errors.url }"
                autocomplete="off"
              />
              <p v-if="errors.url" class="wh-field-error">{{ errors.url }}</p>
              <p v-else class="wh-field-hint">This URL will receive signed POST requests with event data</p>
            </div>

            <!-- Events -->
            <div>
              <label class="wh-field-label">
                Event Subscriptions <span style="color:var(--nc-danger)">*</span>
              </label>

              <!-- Quick Select -->
              <div class="flex gap-2 mb-3">
                <button type="button" @click="selectAllEvents" class="webhook-btn webhook-btn--test" style="font-size:0.65rem;padding:0.25rem 0.6rem">SELECT ALL</button>
                <button type="button" @click="deselectAllEvents" class="webhook-btn webhook-btn--cancel" style="font-size:0.65rem;padding:0.25rem 0.6rem">CLEAR ALL</button>
                <span class="ml-auto" style="font-family:'IBM Plex Mono',monospace;font-size:0.7rem;color:var(--nc-text-muted);align-self:center">
                  {{ formData.events.length }} of {{ availableEvents.length }} selected
                </span>
              </div>

              <p v-if="catalogLoading" class="wh-field-hint" style="margin-top:0">Loading event catalog…</p>
              <p v-else-if="!catalogLive" class="wh-field-hint" data-tour="wh-catalog-fallback" style="margin-top:0">
                Live catalog unavailable — showing the bundled list ({{ availableEvents.length }} events).
                This deployment may support more.
              </p>

              <div class="wh-events-grid" data-tour="wh-events-grid">
                <div v-for="(events, category) in eventCategories" :key="category" class="wh-event-category">
                  <div class="wh-category-header">{{ category }}</div>
                  <label
                    v-for="event in events"
                    :key="event"
                    class="wh-event-row"
                  >
                    <input
                      type="checkbox"
                      :value="event"
                      v-model="formData.events"
                      class="wh-checkbox"
                    />
                    <span class="wh-event-label">{{ formatEventLabel(event) }}</span>
                    <span class="wh-event-code">{{ event }}</span>
                  </label>
                </div>
              </div>

              <p v-if="errors.events" class="wh-field-error mt-2">{{ errors.events }}</p>
            </div>

            <!-- Status Toggle (edit only) -->
            <div v-if="isEditing" class="flex items-center justify-between">
              <div>
                <div class="wh-field-label" style="margin-bottom:0.1rem">Webhook Status</div>
                <p class="wh-field-hint" style="margin-top:0">Inactive webhooks will not receive event deliveries</p>
              </div>
              <button
                type="button"
                @click="formData.is_active = !formData.is_active"
                class="wh-toggle"
                :class="formData.is_active ? 'wh-toggle--on' : 'wh-toggle--off'"
              >
                <span
                  class="wh-toggle-knob"
                  :class="formData.is_active ? 'wh-toggle-knob--on' : 'wh-toggle-knob--off'"
                ></span>
              </button>
            </div>

          </div>

          <!-- ══ FOOTER ══ -->
          <div class="wh-modal-footer flex items-center justify-between">
            <div style="font-family:'IBM Plex Mono',monospace;font-size:0.65rem;color:var(--nc-text-muted)">
              <template v-if="!secretStep">
                X-TheProtocol-Signature · X-TheProtocol-Event · X-TheProtocol-Delivery-ID
              </template>
            </div>

            <div class="flex gap-2">
              <template v-if="secretStep">
                <button @click="$emit('close')" class="nc-btn nc-btn-primary">
                  DONE — I'VE SAVED MY SECRET
                </button>
              </template>
              <template v-else>
                <button @click="$emit('close')" type="button" class="nc-btn nc-btn-ghost">
                  CANCEL
                </button>
                <button
                  @click="handleSubmit"
                  type="button"
                  :disabled="isSubmitting"
                  class="nc-btn nc-btn-primary"
                  style="min-width:140px"
                >
                  <span v-if="isSubmitting" class="wh-spin inline-block" style="width:12px;height:12px;border:2px solid currentColor;border-top-color:transparent;border-radius:50%;margin-right:6px"></span>
                  {{ isEditing ? 'UPDATE WEBHOOK' : 'CREATE WEBHOOK' }}
                </button>
              </template>
            </div>
          </div>

        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useEscapeClose } from '@/composables/useEscapeClose'
import Icon from '@/components/Icon.vue'
import { ref, computed, reactive, watch, onMounted } from 'vue'
import type { Webhook } from '@/services/api/webhookService'
import { EVENT_CATEGORIES, groupEvents, webhookService } from '@/services/api/webhookService'
import { useWebhookStore } from '@/stores/webhooks'
import { useUIStore } from '@/stores/ui'
import { messageOf } from '@/utils/httpError'

const props = defineProps<{
  webhook?: Webhook | null
}>()

const emit = defineEmits<{
  close: []
}>()

const webhookStore = useWebhookStore()
const uiStore      = useUIStore()

// ── State ──────────────────────────────
const isEditing    = computed(() => !!props.webhook)
const isSubmitting = ref(false)
const secretStep   = ref(false)
const webhookSecret = ref('')
const createdUrl   = ref('')
const copied       = ref(false)

const formData = reactive({
  url: props.webhook?.url || '',
  events: props.webhook ? [...props.webhook.events] : [],
  is_active: props.webhook?.is_active ?? true
})

const errors = reactive({ url: '', events: '' })

// §FEPARITY-R4 — the picker renders the SERVER's catalog, not a bundled map that
// drifts. Starts from the bundled list so the grid is never empty on first paint,
// then swaps to the live list. `catalogLive=false` is surfaced in the UI rather than
// silently pretending the short list is complete.
const availableEvents = ref<string[]>((Object.values(EVENT_CATEGORIES) as string[][]).flat())
const catalogLive     = ref(false)
const catalogLoading  = ref(true)

const eventCategories = computed(() => groupEvents(availableEvents.value))

onMounted(async () => {
  try {
    const { events, live } = await webhookService.getSupportedEvents()
    availableEvents.value = events
    catalogLive.value = live
  } finally {
    catalogLoading.value = false
  }
})

// Sync form when editing webhook changes
watch(() => props.webhook, (wh) => {
  if (wh) {
    formData.url      = wh.url
    formData.events   = [...wh.events]
    formData.is_active = wh.is_active
  }
}, { immediate: true })

// ── Helpers ────────────────────────────
function formatEventLabel(event: string): string {
  const part = event.split('.').pop() || event
  return part.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function selectAllEvents() {
  // Must select what is actually OFFERED (the live catalog), not the bundled subset —
  // otherwise "SELECT ALL" quietly subscribes to 22 of 49.
  formData.events = [...availableEvents.value]
}

function deselectAllEvents() {
  formData.events = []
}

async function copySecret() {
  try {
    await navigator.clipboard.writeText(webhookSecret.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2500)
  } catch {
    uiStore.showError('Copy failed', 'Please copy the secret manually')
  }
}

function handleBackdropClick() {
  // Prevent accidental close when secret is showing
  if (!secretStep.value) emit('close')
}

/* §COCKPITDESK (2026-10-15) — Escape closes the form through the shared stack (composables/useEscapeClose): the topmost
 * open dialog answers, a dialog the stack does not know that holds the focus keeps its press, and never while the
 * one-time secret is on screen (it is closed by its own button, as the backdrop is). */
const panelRef = ref<HTMLElement | null>(null)
useEscapeClose(() => true, () => emit('close'), () => !secretStep.value, () => panelRef.value)

function validate(): boolean {
  errors.url    = ''
  errors.events = ''
  let ok = true

  if (!formData.url) {
    errors.url = 'URL is required'
    ok = false
  } else if (!formData.url.startsWith('http://') && !formData.url.startsWith('https://')) {
    errors.url = 'URL must start with http:// or https://'
    ok = false
  }

  if (formData.events.length === 0) {
    errors.events = 'Select at least one event'
    ok = false
  }

  return ok
}

// ── Submit ─────────────────────────────
async function handleSubmit() {
  if (isSubmitting.value || !validate()) return
  isSubmitting.value = true

  try {
    if (isEditing.value && props.webhook) {
      await webhookStore.updateWebhook(props.webhook.id, {
        url: formData.url,
        events: formData.events,
        is_active: formData.is_active
      })
      uiStore.showSuccess('Webhook Updated', 'Webhook configuration saved')
      emit('close')
    } else {
      const webhook = await webhookStore.createWebhook({
        url: formData.url,
        events: formData.events
      })
      // Show secret reveal step inside the modal
      if (webhook?.secret) {
        webhookSecret.value = webhook.secret
        createdUrl.value    = webhook.url
        secretStep.value    = true
      } else {
        uiStore.showSuccess('Webhook Created', `Endpoint registered: ${formData.url}`)
        emit('close')
      }
    }
  } catch (err: any) {
    uiStore.showError(
      isEditing.value ? 'Update Failed' : 'Create Failed',
      messageOf(err?.response?.data, err?.message || 'Unknown error')
    )
  } finally {
    isSubmitting.value = false
  }
}
</script>

<style scoped>
@import '@/assets/styles/neural-reset.css';
@import '@/assets/styles/neural-command.css';
@import '@/assets/styles/tp-webhooks.css';

.wh-modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 50;
  overflow-y: auto;
}

.wh-field-label {
  display: block;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--nc-text-secondary);
  margin-bottom: 0.4rem;
  text-transform: uppercase;
}
.wh-field-hint {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.65rem;
  color: var(--nc-text-muted);
  margin-top: 0.3rem;
}
.wh-field-error {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.7rem;
  color: var(--nc-danger);
  margin-top: 0.3rem;
}

/* Events grid */
.wh-events-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 1rem;
  max-height: 20rem;
  overflow-y: auto;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 0.375rem;
  padding: 1rem;
  background: var(--nc-deep, #0a0d16);
  scrollbar-width: thin;
  scrollbar-color: rgba(var(--nc-primary-rgb),0.2) transparent;
}
.wh-event-category { display: flex; flex-direction: column; gap: 0.35rem; }
.wh-event-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
  padding: 0.15rem 0;
}
.wh-event-row:hover .wh-event-label { color: var(--nc-text-primary); }
.wh-event-label {
  font-size: 0.8rem;
  color: var(--nc-text-secondary);
  transition: color 0.1s ease;
  flex: 1;
}
.wh-event-code {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem;
  color: var(--nc-text-muted);
  display: none;
}
@media (min-width: 640px) { .wh-event-code { display: block; } }
</style>
