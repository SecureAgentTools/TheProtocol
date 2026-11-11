<template>
  <!-- V0657 (b), polish 9: bringing an agent in. Its creator proposes it (a member, not only an administrator), or the
       agent asks itself; an administrator (a person, or an agent with the organization's admin authority) decides. -->
  <section class="oar" data-testid="org-agent-requests" :data-state="state">
    <header class="oar__head">
      <h3 class="oar__title">{{ t('orgRequests.title', 'Join requests') }}</h3>
      <button type="button" class="tp-btn tp-btn--ghost oar__btn" @click="load">{{ t('orgRequests.refresh', 'Refresh') }}</button>
    </header>
    <p class="oar__sub">{{ canDecide
      ? t('orgRequests.subAdmin', 'Agents that asked to join, and agents their creators proposed. Accepting brings the agent in as its owner\'s assign would.')
      : t('orgRequests.subMember', 'Propose an agent you created, or follow the requests you made. An administrator decides.') }}</p>

    <p v-if="state === 'loading'" class="oar__muted">{{ t('orgRequests.loading', 'Reading the requests…') }}</p>
    <p v-else-if="state === 'failed'" class="oar__err">{{ error }}</p>
    <p v-else-if="!items.length" class="oar__muted" data-testid="org-agent-requests-empty">{{ t('orgRequests.empty', 'No open request.') }}</p>
    <ul v-else class="oar__list">
      <li v-for="r in items" :key="r.id" class="oar__row" data-testid="org-agent-request" :data-id="r.id">
        <div class="oar__main">
          <span class="oar__agent" :title="r.agent_did">{{ r.agent_name || short(r.agent_did) }}</span>
          <span class="oar__who">{{ r.requested_by_kind === 'agent'
            ? t('orgRequests.askedItself', 'the agent asked')
            : t('orgRequests.proposed', 'proposed by its creator') }}</span>
          <span v-if="r.note" class="oar__note">{{ r.note }}</span>
        </div>
        <div class="oar__side">
          <template v-if="canDecide">
            <button type="button" class="tp-btn tp-btn--primary oar__btn" data-testid="org-agent-request-accept"
                    :disabled="busy === r.id" @click="decide(r, 'accept')">{{ t('orgRequests.accept', 'Accept') }}</button>
            <button type="button" class="tp-btn tp-btn--ghost oar__btn" data-testid="org-agent-request-decline"
                    :disabled="busy === r.id" @click="decide(r, 'decline')">{{ t('orgRequests.decline', 'Decline') }}</button>
          </template>
          <button v-else type="button" class="tp-btn tp-btn--ghost oar__btn" data-testid="org-agent-request-withdraw"
                  :disabled="busy === r.id" @click="withdraw(r)">{{ t('orgRequests.withdraw', 'Withdraw') }}</button>
        </div>
      </li>
    </ul>

    <form v-if="proposable.length" class="oar__propose" data-testid="org-agent-propose" @submit.prevent="propose">
      <label class="oar__label" for="oar-agent">{{ t('orgRequests.proposeLabel', 'Propose one of your agents') }}</label>
      <select id="oar-agent" v-model="pick" class="oar__select" data-testid="org-agent-propose-pick">
        <option value="" disabled>{{ t('orgRequests.pick', 'Choose an agent') }}</option>
        <option v-for="a in proposable" :key="a.did" :value="a.did">{{ a.name || short(a.did) }}</option>
      </select>
      <input v-model="note" class="oar__input" maxlength="1000" data-testid="org-agent-propose-note"
             :placeholder="t('orgRequests.notePh', 'Why it should join (optional)')" />
      <button type="submit" class="tp-btn tp-btn--primary oar__btn" :disabled="!pick || proposing"
              data-testid="org-agent-propose-send">{{ t('orgRequests.send', 'Send the request') }}</button>
    </form>

    <!-- V0658 (s): an agent belongs to one organization; accepting one that is in another asks first, naming it -->
    <ConfirmActionModal
      :show="!!moveAsk"
      :title="t('orgRequests.moveTitle', 'Move the agent into this organization?')"
      :message="moveMessage"
      tone="warn"
      :confirm-text="t('orgRequests.moveConfirm', 'Accept and move it')"
      :busy-text="t('orgRequests.moveBusy', 'Moving…')"
      :busy="!!moveAsk && busy === moveAsk.request.id"
      @close="moveAsk = null"
      @confirm="confirmMove"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useUIStore } from '@/stores/ui'
import { organizationService, type OrgAgentRequest } from '@/services/api/organizationService'
import ConfirmActionModal from '@/components/common/ConfirmActionModal.vue'
import { escapeHtml } from '@/utils/escapeHtml'
import { leaveBody, organizationLeft, type LeftOrganization } from '@/services/orgMove'

const props = defineProps<{
  orgId: string
  /** the viewer's own agents that are not in this organization */
  myAgents: Array<{ did: string; name?: string | null }>
}>()
const emit = defineEmits<{ (e: 'joined', did: string): void }>()
const { t, tp } = useI18n()
const uiStore = useUIStore()

const items = ref<OrgAgentRequest[]>([])
const canDecide = ref(false)
const state = ref<'loading' | 'ready' | 'failed'>('loading')
const error = ref('')
const busy = ref('')
const pick = ref('')
const note = ref('')
const proposing = ref(false)

const pendingDids = computed(() => new Set(items.value.map((r) => r.agent_did)))
const proposable = computed(() => props.myAgents.filter((a) => a.did && !pendingDids.value.has(a.did)))

function short(did?: string | null): string {
  if (!did) return '?'
  const core = did.replace(/^did:[a-z0-9]+:/i, '')
  return core.length > 18 ? core.slice(0, 8) + '…' + core.slice(-6) : core
}
function detail(e: any, fallback: string): string {
  return e?.response?.data?.detail || e?.message || fallback
}

async function load() {
  if (!props.orgId) return
  state.value = 'loading'
  try {
    const out = await organizationService.listAgentRequests(props.orgId, 'pending')
    items.value = out.items || []
    canDecide.value = !!out.can_decide
    state.value = 'ready'
  } catch (e: any) {
    error.value = detail(e, t('orgRequests.failed', 'The requests could not be read.'))
    state.value = 'failed'
  }
}

// V0658 (s): the accept the registry refused because the agent is in another organization, and that organization
const moveAsk = ref<{ request: OrgAgentRequest; from: LeftOrganization } | null>(null)
const moveMessage = computed(() => {
  const ask = moveAsk.value
  if (!ask) return ''
  // the modal renders this as HTML: every name is escaped, only the markup around them is ours
  const params = { agent: escapeHtml(ask.request.agent_name || short(ask.request.agent_did)),
    from: `<strong data-testid="org-move-from">${escapeHtml(ask.from.name)}</strong>` }
  // the second review (seq 2361): an organization the registry does not name to this administrator (not listed, and
  // they are not a member of it) is said in the registry's own words, "another organization, not listed"
  if (!ask.from.named) {
    return tp('orgRequests.moveBodyUnnamed',
      '{agent} is in {from}. An agent belongs to one organization: accepting the request brings it into this one and takes it out of that one.',
      params)
  }
  return tp('orgRequests.moveBody',
    '{agent} is in the organization {from}. An agent belongs to one organization: accepting the request brings it into this one and takes it out of that one.',
    params)
})

async function decide(r: OrgAgentRequest, verdict: 'accept' | 'decline', leaving?: LeftOrganization) {
  busy.value = r.id
  try {
    if (leaving) await organizationService.decideAgentRequest(props.orgId, r.id, verdict, leaveBody(leaving))
    else await organizationService.decideAgentRequest(props.orgId, r.id, verdict)
    moveAsk.value = null
    if (verdict === 'accept') emit('joined', r.agent_did)
    await load()
  } catch (e: any) {
    // a move out of another organization is a question, asked again naming the organization the agent is in now
    const from = verdict === 'accept' ? organizationLeft(e) : null
    if (from) {
      moveAsk.value = { request: r, from }
      return
    }
    moveAsk.value = null
    uiStore.showError(t('orgRequests.decideFailed', 'The request was not decided'), detail(e, ''))
  } finally {
    busy.value = ''
  }
}

async function confirmMove() {
  const ask = moveAsk.value
  if (!ask || busy.value) return
  await decide(ask.request, 'accept', ask.from)
}

async function withdraw(r: OrgAgentRequest) {
  busy.value = r.id
  try {
    await organizationService.withdrawAgentRequest(props.orgId, r.id)
    await load()
  } catch (e: any) {
    uiStore.showError(t('orgRequests.withdrawFailed', 'The request was not withdrawn'), detail(e, ''))
  } finally {
    busy.value = ''
  }
}

async function propose() {
  if (!pick.value) return
  proposing.value = true
  try {
    await organizationService.createAgentRequest(props.orgId, { agent_did: pick.value, note: note.value.trim() || undefined })
    pick.value = ''
    note.value = ''
    await load()
  } catch (e: any) {
    uiStore.showError(t('orgRequests.proposeFailed', 'The request was not sent'), detail(e, ''))
  } finally {
    proposing.value = false
  }
}

watch(() => props.orgId, load)
onMounted(load)
defineExpose({ load })
</script>

<style scoped>
@import './tp-modal-shared.css';
.oar__btn { padding: 3px 10px; font-size: 11px; }
.oar { display: flex; flex-direction: column; gap: 8px; margin: 16px 0; }
.oar__head { display: flex; justify-content: space-between; align-items: center; }
.oar__title { font-size: 12px; font-weight: 600; margin: 0; }
.oar__sub, .oar__muted { font-size: 12px; opacity: .7; margin: 0; }
.oar__err { font-size: 12px; color: #f87171; margin: 0; }
.oar__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.oar__row { display: flex; justify-content: space-between; gap: 10px; padding: 8px 10px;
  border: 1px solid rgba(148, 163, 184, .2); border-radius: 6px; }
.oar__main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.oar__agent { font-weight: 600; overflow-wrap: anywhere; }
.oar__who, .oar__note { font-size: 12px; opacity: .8; }
.oar__side { display: flex; gap: 6px; align-items: center; flex: 0 0 auto; }
.oar__propose { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.oar__label { font-size: 12px; width: 100%; }
.oar__select, .oar__input { font-size: 12px; padding: 4px 6px; min-width: 0; }
.oar__input { flex: 1 1 180px; }
</style>
