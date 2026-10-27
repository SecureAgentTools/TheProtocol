<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
// ─────────────────────────────────────────────────────────────────────────────
// E1a — Organization ownership card (Settings tab).
//
// Ownership is liability, so it moves by explicit two-party handshake: the
// owner offers the org to an existing ADMIN member, the target accepts or
// declines, and the previous owner steps down to admin (never dropped). One
// pending offer per org, 7-day TTL, self-retiring server-side. Mandates do NOT
// transfer: they are developer∘agent instruments, so the new owner underwrites
// with their own.
//
// Three viewer states, derived from GET /{org}/settings (owner_id +
// pending_ownership_transfer) plus the members list:
//   * owner, no offer   → target picker (admin members only) + offer button
//   * owner, offer live → pending banner + cancel
//   * the offered admin → accept / decline banner
//   * anyone else       → read-only owner line (+ pending note when one exists)
// ─────────────────────────────────────────────────────────────────────────────
import { ref, computed, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import {
  organizationService,
  type OrganizationMember,
  type PendingOwnershipTransfer,
} from '@/services/api/organizationService'

const { t } = useI18n()
const authStore = useAuthStore()
const uiStore = useUIStore()

const props = defineProps<{ orgId: string }>()
const emit = defineEmits<{ (e: 'ownership-changed'): void }>()

const loading = ref(true)
const loadError = ref<string | null>(null)
const busy = ref(false)

const ownerId = ref<number | null>(null)
const pending = ref<PendingOwnershipTransfer | null>(null)
const members = ref<OrganizationMember[]>([])
const targetDevId = ref<number | ''>('')

const myId = computed(() => Number((authStore.user as any)?.id ?? -1))
const iAmOwner = computed(() => ownerId.value !== null && myId.value === ownerId.value)
const iAmTarget = computed(() => !!pending.value && myId.value === pending.value.to_developer_id)

const ownerMember = computed(() =>
  members.value.find(m => m.developer_id === ownerId.value) || null)
const pendingMember = computed(() =>
  members.value.find(m => m.developer_id === pending.value?.to_developer_id) || null)
/** Only ACTIVE admins qualify as transfer targets (accepting ownership is
 *  accepting liability; the promote-then-transfer two-step keeps each act explicit). */
const adminTargets = computed(() =>
  members.value.filter(m => m.is_active && m.role === 'admin' && m.developer_id !== ownerId.value))

function memberLabel(m: OrganizationMember | null, fallbackId?: number | null): string {
  if (m) return (m as any).developer_name || (m as any).developer_email || `#${m.developer_id}`
  return fallbackId != null ? `#${fallbackId}` : '?'
}
function fmtExpiry(iso: string | null): string {
  if (!iso) return t('orgOwnership.noExpiry', 'no expiry')
  try { return new Date(iso).toLocaleString(appLocale()) } catch { return iso }
}

async function load() {
  loading.value = true
  loadError.value = null
  try {
    const [settings, mem] = await Promise.all([
      organizationService.getOrgSettings(props.orgId),
      organizationService.listMembers(props.orgId),
    ])
    ownerId.value = settings.owner_id ?? null
    pending.value = settings.pending_ownership_transfer ?? null
    members.value = mem || []
  } catch (e: any) {
    loadError.value = e?.message || t('orgOwnership.loadFailed', 'Could not load ownership state')
  } finally {
    loading.value = false
  }
}

async function offer() {
  if (targetDevId.value === '' || busy.value) return
  busy.value = true
  try {
    await organizationService.initiateOwnershipTransfer(props.orgId, Number(targetDevId.value))
    uiStore.showSuccess(
      t('orgOwnership.offerSentTitle', 'Offer sent'),
      t('orgOwnership.offerSentBody', 'The admin has 7 days to accept ownership.'))
    targetDevId.value = ''
    await load()
  } catch (e: any) {
    uiStore.showError(t('orgOwnership.offerFailed', 'Offer failed'), e?.response?.data?.detail || e?.message)
  } finally { busy.value = false }
}

async function cancelOffer() {
  if (busy.value) return
  busy.value = true
  try {
    await organizationService.cancelOwnershipTransfer(props.orgId)
    uiStore.showSuccess(
      t('orgOwnership.cancelledTitle', 'Offer withdrawn'),
      t('orgOwnership.cancelledBody', 'The pending ownership offer was cancelled.'))
    await load()
  } catch (e: any) {
    uiStore.showError(t('orgOwnership.cancelFailed', 'Cancel failed'), e?.response?.data?.detail || e?.message)
  } finally { busy.value = false }
}

async function respond(accept: boolean) {
  if (busy.value) return
  busy.value = true
  try {
    await organizationService.respondOwnershipTransfer(props.orgId, accept)
    if (accept) {
      uiStore.showSuccess(
        t('orgOwnership.acceptedTitle', 'You now own this organization'),
        t('orgOwnership.acceptedBody', 'The previous owner stays on as admin. Your mandates now underwrite org activity.'))
    } else {
      uiStore.showSuccess(
        t('orgOwnership.declinedTitle', 'Offer declined'),
        t('orgOwnership.declinedBody', 'Ownership stays where it was.'))
    }
    await load()
    emit('ownership-changed')
  } catch (e: any) {
    uiStore.showError(t('orgOwnership.respondFailed', 'Response failed'), e?.response?.data?.detail || e?.message)
  } finally { busy.value = false }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <section class="own-root" data-tour="org-ownership">
    <div class="own-head">
      <h3 class="own-title">
        <Icon name="crown" class="own-title-ic" />
        <span>{{ t('orgOwnership.title', 'Ownership') }}</span>
      </h3>
      <p class="own-subtitle">
        {{ t('orgOwnership.subtitle', 'The owner is the liable person behind this organization. Ownership moves only by explicit handshake: offer, then accept.') }}
      </p>
    </div>

    <div v-if="loading" class="own-state">
      <Icon name="loader" class="own-spin" />
      <span>{{ t('orgOwnership.loading', 'Loading ownership state') }}</span>
    </div>

    <div v-else-if="loadError" class="own-alert own-alert--error" role="alert">
      <Icon name="mdi:alert-octagon" class="own-alert-ic" />
      <span>{{ loadError }}</span>
      <button class="own-retry" @click="load">{{ t('orgOwnership.retry', 'Retry') }}</button>
    </div>

    <template v-else>
      <div class="own-row">
        <span class="own-label">{{ t('orgOwnership.currentOwner', 'Current owner') }}</span>
        <span class="own-value">
          {{ memberLabel(ownerMember, ownerId) }}
          <span v-if="iAmOwner" class="own-you">{{ t('orgOwnership.you', '(you)') }}</span>
        </span>
      </div>

      <!-- Pending offer banner ─ target sees accept/decline, owner sees cancel -->
      <div v-if="pending" class="own-pending" data-testid="ownership-pending">
        <Icon name="mdi:bank-transfer" class="own-pending-ic" />
        <div class="own-pending-body">
          <p class="own-pending-line">
            {{ t('orgOwnership.pendingTo', 'Ownership offered to') }}
            <strong>{{ memberLabel(pendingMember, pending.to_developer_id) }}</strong>
            <span v-if="iAmTarget" class="own-you">{{ t('orgOwnership.you', '(you)') }}</span>
          </p>
          <p class="own-pending-sub">
            {{ t('orgOwnership.pendingExpires', 'Offer expires:') }} {{ fmtExpiry(pending.expires_at) }}
          </p>
        </div>
        <div class="own-pending-actions">
          <template v-if="iAmTarget">
            <button class="own-btn own-btn--accept" :disabled="busy" data-testid="ownership-accept" @click="respond(true)">
              <Icon name="mdi:account-check" />
              {{ t('orgOwnership.acceptBtn', 'Accept ownership') }}
            </button>
            <button class="own-btn own-btn--ghost" :disabled="busy" @click="respond(false)">
              {{ t('orgOwnership.declineBtn', 'Decline') }}
            </button>
          </template>
          <button v-else-if="iAmOwner" class="own-btn own-btn--ghost" :disabled="busy" data-testid="ownership-cancel" @click="cancelOffer">
            <Icon name="mdi:cancel" />
            {{ t('orgOwnership.cancelBtn', 'Withdraw offer') }}
          </button>
        </div>
      </div>

      <!-- Owner with no pending offer: the transfer form -->
      <div v-else-if="iAmOwner" class="own-form">
        <label class="own-label" for="own-target">{{ t('orgOwnership.transferTo', 'Transfer ownership to') }}</label>
        <div class="own-form-row">
          <div class="own-select-wrap">
            <select id="own-target" v-model="targetDevId" class="own-select" data-testid="ownership-target">
              <option value="" disabled>{{ t('orgOwnership.pickAdmin', 'Pick an admin member') }}</option>
              <option v-for="m in adminTargets" :key="m.developer_id" :value="m.developer_id">
                {{ memberLabel(m) }}
              </option>
            </select>
            <svg class="own-select-arrow" viewBox="0 0 10 6" fill="none"><path d="M1 1l4 4 4-4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg>
          </div>
          <button class="own-btn" :disabled="busy || targetDevId === ''" data-testid="ownership-offer" @click="offer">
            {{ t('orgOwnership.offerBtn', 'Offer ownership') }}
          </button>
        </div>
        <p v-if="!adminTargets.length" class="own-hint own-hint--muted">
          <Icon name="mdi:information-outline" class="own-hint-ic" />
          {{ t('orgOwnership.noAdmins', 'No eligible targets yet. Promote a member to admin first, then transfer.') }}
        </p>
        <p class="own-hint own-hint--muted">
          <Icon name="mdi:information-outline" class="own-hint-ic" />
          {{ t('orgOwnership.mandateNote', 'Mandates do not transfer. The new owner underwrites with their own, and you stay on as admin.') }}
        </p>
      </div>
    </template>
  </section>
</template>

<style scoped>
.own-root {
  margin-top: 26px; padding: 20px 22px;
  background: rgba(255, 255, 255, 0.015);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 10px;
}
.own-head { margin-bottom: 16px; }
.own-title {
  display: flex; align-items: center; gap: 8px; margin: 0 0 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.78rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase;
  color: rgba(226, 232, 240, 0.85);
}
.own-title-ic { font-size: 1rem; color: rgba(var(--nc-primary-rgb), 0.7); }
.own-subtitle { margin: 0; font-size: 0.78rem; line-height: 1.55; color: rgba(148, 163, 184, 0.85); max-width: 620px; }

.own-state { display: flex; align-items: center; gap: 8px; font-size: 0.78rem; color: rgba(148, 163, 184, 0.5); padding: 8px 0; }
.own-spin { animation: own-rot 1s linear infinite; }
@keyframes own-rot { to { transform: rotate(360deg); } }

.own-alert {
  display: flex; align-items: center; gap: 8px;
  font-size: 0.78rem; padding: 10px 12px; border-radius: 8px;
}
.own-alert--error { color: rgba(239, 68, 68, 0.85); background: rgba(239, 68, 68, 0.06); border: 1px solid rgba(239, 68, 68, 0.2); }
.own-alert-ic { flex-shrink: 0; }
.own-retry {
  margin-left: auto; background: none; border: 1px solid rgba(239, 68, 68, 0.35);
  color: rgba(239, 68, 68, 0.85); border-radius: 6px; padding: 3px 10px;
  font-size: 0.7rem; cursor: pointer;
}

.own-row { display: flex; align-items: baseline; gap: 12px; margin-bottom: 14px; }
.own-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.6rem; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
  color: rgba(148, 163, 184, 0.8);
}
.own-value { font-size: 0.85rem; color: rgba(226, 232, 240, 0.85); }
.own-you { margin-left: 6px; font-size: 0.72rem; color: rgba(var(--nc-primary-rgb), 0.75); }

.own-pending {
  display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap;
  padding: 14px 16px; border-radius: 8px;
  background: rgba(251, 191, 36, 0.05);
  border: 1px solid rgba(251, 191, 36, 0.25);
}
.own-pending-ic { font-size: 1.2rem; color: rgba(251, 191, 36, 0.8); flex-shrink: 0; margin-top: 2px; }
.own-pending-body { flex: 1 1 240px; min-width: 0; }
.own-pending-line { margin: 0 0 4px; font-size: 0.82rem; color: rgba(226, 232, 240, 0.85); }
.own-pending-sub { margin: 0; font-size: 0.72rem; color: rgba(148, 163, 184, 0.55); font-family: 'IBM Plex Mono', monospace; }
.own-pending-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

.own-form { display: flex; flex-direction: column; gap: 8px; max-width: 560px; }
.own-form-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.own-select-wrap { position: relative; flex: 1 1 220px; }
.own-select {
  width: 100%; appearance: none; cursor: pointer;
  background: rgba(6, 11, 20, 0.7);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.15);
  border-radius: 6px; padding: 9px 30px 9px 12px;
  color: rgba(226, 232, 240, 0.85); font-size: 0.85rem; outline: none;
}
.own-select:focus { border-color: rgba(var(--nc-primary-rgb), 0.38); box-shadow: 0 0 0 3px rgba(var(--nc-primary-rgb), 0.12); }
.own-select option { background: #0a1120; color: rgba(226, 232, 240, 0.85); }
.own-select-arrow {
  position: absolute; right: 12px; top: 50%; transform: translateY(-50%);
  width: 10px; height: 6px; pointer-events: none; color: rgba(148, 163, 184, 0.5);
}

.own-btn {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; font-weight: 600; letter-spacing: 0.1em;
  padding: 8px 16px; border-radius: 6px; cursor: pointer;
  transition: all 0.15s;
  background: rgba(var(--nc-primary-rgb), 0.12);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.3);
  color: rgba(var(--nc-primary-rgb), 0.9);
}
.own-btn:hover:not(:disabled) { background: rgba(var(--nc-primary-rgb), 0.2); border-color: rgba(var(--nc-primary-rgb), 0.55); }
.own-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.own-btn--accept { background: rgba(52, 211, 153, 0.12); border-color: rgba(52, 211, 153, 0.35); color: rgba(52, 211, 153, 0.9); }
.own-btn--accept:hover:not(:disabled) { background: rgba(52, 211, 153, 0.2); border-color: rgba(52, 211, 153, 0.55); }
.own-btn--ghost { background: rgba(255, 255, 255, 0.03); border-color: rgba(255, 255, 255, 0.12); color: rgba(148, 163, 184, 0.75); }
.own-btn--ghost:hover:not(:disabled) { border-color: rgba(255, 255, 255, 0.25); color: rgba(226, 232, 240, 0.85); }

.own-hint { display: flex; align-items: flex-start; gap: 6px; font-size: 0.74rem; line-height: 1.5; margin: 2px 0 0; }
.own-hint--muted { color: rgba(148, 163, 184, 0.8); }
.own-hint-ic { font-size: 0.85rem; flex-shrink: 0; margin-top: 0.15em; color: rgba(var(--nc-primary-rgb), 0.55); }
</style>
