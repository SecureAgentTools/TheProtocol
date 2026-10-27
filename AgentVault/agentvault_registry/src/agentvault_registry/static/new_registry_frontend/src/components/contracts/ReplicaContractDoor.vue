<!--
  §XHIREFE — the provider's door onto a cross-registry contract.

  A replica row (`replica: true` from /contracts/v2/mine) is a signed copy: the contract, its escrow and every state
  transition live at `home_registry`. §TWOAGENT (V0437): the door calls the contracts v2 routes on THIS registry, as the
  acting agent (accept, deliver a milestone, cancel); this registry gates the agent and carries the command to the home
  (the answer names it, `relayed_to`). It used to call the legacy /contracts/cross-registry/proxy, which is not mounted
  where the legacy surface is off (EU and ASIA), so the door could only 404 there.

  Laws it keeps:
   * §FOREIGNACT — the door NAMES the acting agent it binds, and the requests carry that same agent's token (both read
     authStore.activeAgent).
   * The home's refusals are HONEST — shown verbatim, never paraphrased.
   * The replica refreshes from home right after an action and on the reconciler's pass; the door shows the home's
     answer and says so, rather than pretending the copy is live state.
-->
<template>
  <div class="rcd" data-testid="replica-door">
    <div class="rcd-head">
      <span class="rcd-chip" data-testid="replica-chip">
        <Icon name="mdi:earth" />
        <!-- §TWOAGENT V0441: an offer only while there is one to accept; a completed replica read "Offer". -->
        <template v-if="door === 'accept'">{{ t('bridge.replica.chip', 'Offer from another registry') }}</template>
        <template v-else>{{ t('bridge.replica.chipContract', 'Contract at another registry') }}</template>
        · {{ contract.home_registry }}
      </span>
      <span v-if="contract.stale" class="rcd-stale" data-testid="replica-stale">
        {{ t('bridge.replica.stale', 'mirror may be stale') }}</span>
    </div>

    <p class="rcd-line">
      {{ t('bridge.replica.explain', 'This contract lives at') }} <b>{{ contract.home_registry }}</b> —
      {{ t('bridge.replica.explain2', 'its escrow and every state change happen there. Actions below are relayed over federation.') }}
    </p>

    <p class="rcd-acting" data-testid="replica-acting">
      <Icon name="mdi:account-check" />
      <template v-if="actingDid">
        {{ t('bridge.replica.actingAs', 'Acting as') }} <b>{{ actingName }}</b>
        <span class="rcd-did">{{ shortDid(actingDid) }}</span> —
        <template v-if="door === 'accept'">{{ t('bridge.replica.actingBinds', 'accepting binds this agent as the provider.') }}</template>
        <template v-else-if="door === 'work'">{{ t('bridge.replica.actingSigns', 'the provider; the relay signs as this agent.') }}</template>
        <template v-else>{{ t('bridge.replica.actingProvider', 'the provider on this contract.') }}</template>
      </template>
      <template v-else>
        {{ t('bridge.replica.noActing', 'Select an acting agent first — the relay signs as the acting agent.') }}
      </template>
    </p>

    <p v-if="paid.length" class="rcd-line" data-testid="replica-paid">
      <Icon name="mdi:check-circle" />
      {{ t('bridge.replica.paid', 'Paid milestones:') }} {{ paid.join(', ') }}
    </p>

    <!-- accept door (open offers only). ⚠ justAccepted must SUPPRESS this
         branch: the replica keeps saying 'offered' until it refreshes, and the
         first v-if would otherwise shadow the work lane (measured in the battery). -->
    <div v-if="door === 'accept'" class="rcd-actions">
      <button class="rcd-btn rcd-btn-primary" data-testid="replica-accept"
              :disabled="!!busy || !actingDid" @click="doAccept">
        {{ busy === 'accept' ? t('common.working', 'Working…')
           : tp('bridge.replica.acceptAt', 'Accept at {home}', { home: contract.home_registry }) }}
      </button>
    </div>

    <!-- work door (accepted work: 'agreed', and 'in_progress' once a delivery was made) -->
    <template v-else-if="door === 'work'">
      <div class="rcd-actions rcd-submit">
        <input v-model="prUrl" class="rcd-input" type="url" data-testid="replica-pr-url"
               :placeholder="t('bridge.replica.prPh', 'Deliverable URL (PR, artifact…)')" />
        <button class="rcd-btn rcd-btn-primary" data-testid="replica-submit"
                :disabled="!!busy || !actingDid || !prUrl.trim()" @click="doSubmit">
          {{ busy === 'submit' ? t('common.working', 'Working…')
             : tp('bridge.replica.deliverAt', 'Deliver milestone {n} at {home}', { n: nextSeq, home: contract.home_registry }) }}
        </button>
      </div>
      <div class="rcd-actions">
        <button v-if="!confirmCancel" class="rcd-btn" data-testid="replica-cancel"
                :disabled="!!busy || !actingDid" @click="confirmCancel = true">
          {{ tp('bridge.replica.cancelAt', 'Cancel at {home}', { home: contract.home_registry }) }}
        </button>
        <template v-else>
          <span class="rcd-line">{{ tp('bridge.replica.cancelConfirm',
            'Cancel this contract at {home}? The unreleased remainder returns to the client; paid milestones stay paid.',
            { home: contract.home_registry }) }}</span>
          <button class="rcd-btn rcd-btn-danger" data-testid="replica-cancel-yes" :disabled="!!busy" @click="doCancel">
            {{ busy === 'cancel' ? t('common.working', 'Working…') : t('bridge.replica.cancelYes', 'Yes, cancel it') }}
          </button>
          <button class="rcd-btn" data-testid="replica-cancel-no" :disabled="!!busy" @click="confirmCancel = false">
            {{ t('bridge.replica.cancelNo', 'Keep it') }}
          </button>
        </template>
      </div>
    </template>

    <p v-else class="rcd-line rcd-dim">
      {{ tp('bridge.replica.noDoor', 'No relayed action for status "{st}" — settlement and release run at {home}.',
            { st: contract.status, home: contract.home_registry }) }}
    </p>

    <!-- the home registry's own answer, verbatim -->
    <div v-if="result" class="rcd-result" data-testid="replica-result">
      <p class="rcd-ok"><Icon name="mdi:check-circle" />
        {{ tp('bridge.replica.homeAnswered', '{home} answered: status {st}',
              { home: contract.home_registry, st: String(result.status || 'ok') }) }}</p>
      <p class="rcd-dim">{{ t('bridge.replica.mirrorCatchup', 'This mirror refreshes from the home registry on the next replication cycle.') }}</p>
    </div>
    <pre v-if="error" class="rcd-err" data-testid="replica-error">{{ error }}</pre>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import { contractsV2Api } from '@/services/api/contractsV2'
import { doorFor, nextDeliverable, paidMilestones } from '@/services/contracts/replicaDoor'
import { useAuthStore } from '@/stores/auth'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{ contract: Record<string, any> }>()
const emit = defineEmits<{ (e: 'acted'): void }>()
const { t, tp } = useI18n()

const authStore = useAuthStore()
const actingDid = computed<string | null>(() => authStore.activeAgent?.did || null)
const actingName = computed(() => authStore.activeAgent?.name || shortDid(actingDid.value || ''))
const shortDid = (d: string) => (d.length > 26 ? `${d.slice(0, 22)}…` : d)

const busy = ref<'' | 'accept' | 'submit' | 'cancel'>('')
const prUrl = ref('')
const result = ref<Record<string, any> | null>(null)
const error = ref('')
const justAccepted = ref(false)
const confirmCancel = ref(false)

const door = computed(() => doorFor(props.contract.status, justAccepted.value))
const paid = computed(() => paidMilestones(props.contract.released_milestones))
const nextSeq = computed(() => nextDeliverable(props.contract.released_milestones))

function errText(e: any): string {
  const d = e?.response?.data
  if (typeof d?.detail === 'string') return d.detail
  if (d) { try { return JSON.stringify(d, null, 1) } catch { /* noop */ } }
  return e?.message || String(e)
}

async function act(kind: 'accept' | 'submit' | 'cancel', call: () => Promise<any>) {
  busy.value = kind; error.value = ''; result.value = null
  try {
    result.value = await call()
    if (kind === 'accept') justAccepted.value = true
    if (kind === 'cancel') confirmCancel.value = false
    emit('acted')
  } catch (e: any) { error.value = errText(e) } finally { busy.value = '' }
}

const doAccept = () => act('accept', () => contractsV2Api.accept(String(props.contract.id)))
const doSubmit = () => act('submit', () => contractsV2Api.submitMilestone(
  String(props.contract.id), nextSeq.value, { pr_url: prUrl.value.trim() }))
const doCancel = () => act('cancel', () => contractsV2Api.cancel(String(props.contract.id)))
</script>

<style scoped>
.rcd { display: flex; flex-direction: column; gap: 8px; padding: 10px 2px 4px; }
.rcd-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rcd-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px;
            font-size: .74rem; font-weight: 700; letter-spacing: .04em;
            background: var(--accent-soft, rgba(120,160,255,.14));
            border: 1px solid var(--border-color, rgba(128,128,128,.3)); }
.rcd-stale { font-size: .72rem; color: var(--warning, #e0b34d); }
.rcd-line { margin: 0; font-size: .82rem; opacity: .85; }
.rcd-dim { opacity: .6; }
.rcd-acting { margin: 0; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: .8rem; }
.rcd-did { font-family: monospace; font-size: .72rem; opacity: .6; }
.rcd-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.rcd-input { flex: 1 1 260px; min-height: 38px; padding: 0 10px; border-radius: 8px;
             border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: transparent; color: inherit; }
.rcd-btn { min-height: 38px; padding: 0 14px; border-radius: 8px; cursor: pointer;
           border: 1px solid var(--border-color, rgba(128,128,128,.3)); background: none; color: inherit; }
.rcd-btn-primary { background: var(--accent-soft, rgba(120,160,255,.16)); font-weight: 700; }
.rcd-btn-danger { color: var(--danger, #e0716b); border-color: rgba(224,113,107,.45); font-weight: 700; }
.rcd-btn:disabled { opacity: .45; cursor: not-allowed; }
.rcd-result { border-left: 3px solid var(--success, #4fbf82); padding-left: 10px; }
.rcd-ok { margin: 0; display: flex; align-items: center; gap: 6px; color: var(--success, #4fbf82); font-size: .82rem; }
.rcd-err { margin: 0; padding: 8px 10px; border-radius: 8px; font-size: .74rem; white-space: pre-wrap;
           color: var(--danger, #e0716b); background: rgba(224,113,107,.08);
           border: 1px solid rgba(224,113,107,.3); }
</style>
