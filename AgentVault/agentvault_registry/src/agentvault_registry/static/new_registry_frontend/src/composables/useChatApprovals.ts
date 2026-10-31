/**
 * V0650 (l) — approvals in the chat: the pinned panel's state and its two actions.
 *
 * Reads the room's pending requests (GET /chat/conversations/{id}/approvals) and decides them
 * (POST .../approvals/decide) with the DEVELOPER token the caller passes: agents never decide. Every answer is for the
 * room on screen when it arrives (a thread switch mid-read drops the earlier answer). A failed read is a failed read,
 * never an empty list. A 428 answer (the room asks for a phone confirmation) becomes `stepUp`, which the panel hands
 * to the existing step-up dialog; the same decision is sent again with the approved challenge.
 */
import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import { chatApi } from '@/services/api/chat'
import { parseStepUp, type StepUpChallenge } from '@/services/membership/membership'
import { approveAllIds, pendingShown, type ApprovalItem } from '@/services/chat/approvals'

export interface PendingStepUp {
  decision: 'approve' | 'deny'
  ids: string[]
  challenge: StepUpChallenge
}

export function useChatApprovals(conversationId: Ref<string>, token: Ref<string>, enabled: Ref<boolean>) {
  const items = ref<ApprovalItem[]>([])
  const canDecide = ref(false)
  const presence = ref('off')
  const loaded = ref(false)
  const readFailed = ref(false)
  const busyIds = ref<Set<string>>(new Set())
  const lastError = ref('')
  const stepUp = ref<PendingStepUp | null>(null)
  const now = ref(Date.now())
  let timer: ReturnType<typeof setInterval> | null = null

  function tick() { now.value = Date.now() }
  function startClock() { if (!timer) timer = setInterval(tick, 1000) }
  function stopClock() { if (timer) { clearInterval(timer); timer = null } }

  async function refresh(): Promise<void> {
    const cid = conversationId.value
    if (!enabled.value || !cid || !token.value) { items.value = []; loaded.value = false; return }
    try {
      const r = await chatApi.listApprovals(token.value, cid, 'pending')
      if (cid !== conversationId.value) return
      items.value = Array.isArray(r?.items) ? r.items : []
      canDecide.value = !!r?.can_decide
      presence.value = String(r?.presence || 'off')
      readFailed.value = false
      loaded.value = true
    } catch (e: any) {
      if (cid !== conversationId.value) return
      // 501 = switched off on this registry, 409 = not a room approvals live in: there is nothing to show, by name
      if (e?.status === 501 || e?.status === 409 || e?.status === 404) {
        items.value = []; readFailed.value = false; loaded.value = true
        return
      }
      readFailed.value = true
    }
    if (items.value.length) startClock(); else stopClock()
  }

  async function decide(decision: 'approve' | 'deny', ids: string[], challengeId?: string): Promise<boolean> {
    const cid = conversationId.value
    if (!ids.length || !cid) return false
    const marking = new Set(busyIds.value)
    ids.forEach((i) => marking.add(i))
    busyIds.value = marking
    lastError.value = ''
    try {
      await chatApi.decideApprovals(token.value, cid, {
        decision, approval_ids: ids, surface: 'console',
        ...(challengeId ? { challenge_id: challengeId } : {}),
      })
      stepUp.value = null
      // decided ones leave the panel now; the next read confirms it
      items.value = items.value.filter((i) => !ids.includes(i.id))
      void refresh()
      return true
    } catch (e: any) {
      const ch = e?.status === 428 ? parseStepUp(e?.body) : null
      if (ch) { stepUp.value = { decision, ids, challenge: ch }; return false }
      lastError.value = String(e?.detail || e?.message || 'The decision was not recorded.')
      void refresh()
      return false
    } finally {
      const left = new Set(busyIds.value)
      ids.forEach((i) => left.delete(i))
      busyIds.value = left
    }
  }

  const shown = computed(() => pendingShown(items.value, now.value))
  const allIds = computed(() => approveAllIds(items.value, now.value))

  function approve(id: string) { return decide('approve', [id]) }
  function deny(id: string) { return decide('deny', [id]) }
  /** Exactly the requests on screen that are pending and unexpired at the moment of the press. */
  function approveAll() { return decide('approve', approveAllIds(items.value, Date.now())) }
  function resendWithChallenge(challengeId: string) {
    const s = stepUp.value
    return s ? decide(s.decision, s.ids, challengeId) : Promise.resolve(false)
  }

  watch([conversationId, enabled], () => { items.value = []; stepUp.value = null; lastError.value = ''; void refresh() },
        { immediate: true })
  onUnmounted(stopClock)

  return {
    items, shown, allIds, canDecide, presence, loaded, readFailed, busyIds, lastError, stepUp, now,
    refresh, approve, deny, approveAll, resendWithChallenge,
  }
}
