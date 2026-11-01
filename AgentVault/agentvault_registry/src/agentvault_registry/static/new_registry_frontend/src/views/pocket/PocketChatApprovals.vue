<!-- V0651 (y) — the chat's approval requests in Pocket's Approvals.

     The maintainer's bug report from his phone (2026-10-31, the sessions' room, seq 234/235): "under approvals in
     pocket it's also not there". Pocket's Approvals held the delegations, the permits and the phone confirmations, and
     no chat approval: a request an agent asked in an organization's room was only in that room. This lists every
     request the signed-in person may decide (GET /chat/approvals: the org's owner or a named approver, the rooms' own
     rule), oldest first, each opening its room on that request (?approval=), where the pinned panel decides it with
     the room's own refusals and step-up. A failed read says so (never an empty list); a registry without approvals
     in the chat shows nothing. -->
<template>
  <section v-if="!off" class="pca" data-testid="pca">
    <h2 class="pca-head">
      <Icon name="mdi:shield-check" />
      {{ t('ourstate.approvals.inRooms', 'Approval requests in your rooms') }}
      <span class="pca-count" data-testid="pca-count">{{ items.length }}</span>
    </h2>
    <ReadFailedNotice v-if="readFailed" dense :retry="refresh" data-testid="pca-read-failed"
                      :text="t('ourstate.approvals.readFailed', 'Approval requests could not be read just now.')" />
    <p v-else-if="loaded && !items.length" class="pca-none" data-testid="pca-none">
      {{ t('ourstate.approvals.noneWaiting', 'No approval request in your rooms waits for you.') }}</p>
    <ul v-else class="pca-list">
      <li v-for="a in items" :key="a.id">
        <button type="button" class="pca-item" :data-testid="`pca-item-${a.id}`" @click="open(a)">
          <span class="pca-title">{{ a.title }}</span>
          <!-- V0652 (ab): a choice says so, with its options (chosen in its room's pinned panel) -->
          <span v-if="Array.isArray(a.options) && a.options.length >= 2" class="pca-unlocks" data-testid="pca-choice">
            {{ tp('ourstate.approvals.chooseFrom', 'Choose: {options}', { options: a.options.join(' / ') }) }}</span>
          <span v-if="a.unlocks" class="pca-unlocks">
            {{ tp('ourstate.approvals.unlocks', 'Unlocks: {what}', { what: a.unlocks }) }}</span>
          <span class="pca-meta">
            <span class="pca-room">{{ tp('ourstate.approvals.inRoom', 'in {room}', { room: a.room?.title || '' }) }}</span>
            <span class="pca-from">{{ a.requester?.name || '' }} <code>{{ didTail(a.requester?.agent_did) }}</code></span>
            <span v-if="a.production_impact" class="pca-prod" data-testid="pca-prod">
              {{ t('ourstate.approvals.production', 'Affects production') }}</span>
            <span class="pca-left">{{ leftText(a) }}</span>
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { chatApi } from '@/services/api/chat'
import { readAccessToken } from '@/services/accessToken'
import { didTail, isExpired, leftParts, secondsLeft, type ApprovalItem } from '@/services/chat/approvals'
import { useAuthStore } from '@/stores/auth'

type WaitingItem = ApprovalItem & { room?: { conversation_id: string; title?: string; org_name?: string } | null }

const { t, tp } = useI18n()
const router = useRouter()
const auth = useAuthStore()

const items = ref<WaitingItem[]>([])
const loaded = ref(false)
const readFailed = ref(false)
const off = ref(false)
const now = ref(Date.now())
let clock: ReturnType<typeof setInterval> | null = null

async function refresh(): Promise<void> {
  const token = (auth as any).token || readAccessToken() || ''
  if (!token) return
  try {
    const r = await chatApi.listWaitingApprovals(token)
    items.value = Array.isArray(r?.items) ? r.items : []
    readFailed.value = false
    off.value = false
    loaded.value = true
  } catch (e: any) {
    // 501: approvals in the chat are switched off here; 404: a registry before V0651 has no such list
    if (e?.status === 501 || e?.status === 404) { off.value = true; return }
    readFailed.value = true
  }
}

function leftText(a: WaitingItem): string {
  if (isExpired(a, now.value)) return t('ourstate.approvals.expired', 'expired')
  const s = secondsLeft(a, now.value)
  if (!Number.isFinite(s)) return ''
  const { h, m } = leftParts(s)
  if (h > 0) return tp('ourstate.approvals.leftHours', '{h} h {m} min left', { h, m: String(m).padStart(2, '0') })
  return tp('ourstate.approvals.leftMinutesOnly', '{m} min left', { m: Math.max(1, m) })
}

function open(a: WaitingItem) {
  const conv = a.room?.conversation_id || a.conversation_id
  if (conv) void router.push({ path: `/pocket/ourchat/${conv}`, query: { approval: a.id } })
}

function onVisible() { if (document.visibilityState === 'visible') void refresh() }
// V0652 (y): the window's focus too (a desktop window comes back without a visibility change)
function onFocus() { void refresh() }

onMounted(() => {
  void refresh()
  clock = setInterval(() => { now.value = Date.now() }, 30000)
  document.addEventListener('visibilitychange', onVisible)
  window.addEventListener('focus', onFocus)
})
onBeforeUnmount(() => {
  if (clock) clearInterval(clock)
  document.removeEventListener('visibilitychange', onVisible)
  window.removeEventListener('focus', onFocus)
})

defineExpose({ refresh, items })
</script>

<style scoped>
.pca { margin: 0 0 1rem; padding: 0.75rem 0.85rem; border-radius: 14px;
  border: 1px solid rgba(0, 212, 255, 0.22); background: rgba(0, 212, 255, 0.05); }
.pca-head { display: flex; align-items: center; gap: 0.45rem; margin: 0; font-size: 0.9rem; font-weight: 700; }
.pca-count { margin-left: auto; min-width: 1.6rem; text-align: center; border-radius: 9px; padding: 0.05rem 0.45rem;
  background: rgba(0, 212, 255, 0.16); font-size: 0.78rem; }
.pca-none { margin: 0.45rem 0 0; font-size: 0.82rem; opacity: 0.75; }
.pca-list { list-style: none; margin: 0.55rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.5rem; }
.pca-item { width: 100%; text-align: left; display: flex; flex-direction: column; gap: 0.25rem; min-height: 44px;
  padding: 0.6rem 0.7rem; border-radius: 12px; border: 1px solid rgba(255, 255, 255, 0.12);
  background: rgba(255, 255, 255, 0.04); color: inherit; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pca-title { font-weight: 600; font-size: 0.88rem; }
.pca-unlocks { font-size: 0.8rem; opacity: 0.85; }
.pca-meta { display: flex; flex-wrap: wrap; gap: 0.35rem 0.6rem; font-size: 0.74rem; opacity: 0.8; }
.pca-room { font-weight: 600; }
.pca-from { white-space: nowrap; }
.pca-prod { color: #fbbf24; font-weight: 700; }
.pca-left { margin-left: auto; font-variant-numeric: tabular-nums; }
</style>
