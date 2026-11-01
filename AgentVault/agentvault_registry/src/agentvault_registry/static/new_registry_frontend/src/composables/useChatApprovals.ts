/**
 * V0650 (l) — approvals in the chat: the pinned panel's state and its two actions.
 *
 * Reads the room's pending requests (GET /chat/conversations/{id}/approvals) and decides them
 * (POST .../approvals/decide) with the DEVELOPER token the caller passes: agents never decide. Every answer is for the
 * room on screen when it arrives (a thread switch mid-read drops the earlier answer). A failed read is a failed read,
 * never an empty list. A 428 answer (the room asks for a phone confirmation) becomes `stepUp`, which the panel hands
 * to the existing step-up dialog; the same decision is sent again with the approved challenge.
 *
 * V0652 (y), his seq 477: he approved on the desktop and his phone still offered Approve on the same request (the server
 * was right: an idempotent 200, "already decided this way"). The panel re-reads when its window regains focus or its
 * tab becomes visible (the thread re-reads it live on a decided card), only the newest read applies (a read started
 * before a decision never brings the decided request back), and a press on a request decided before it reads the
 * record and says when and by whom (`late`), never a fresh "approved".
 */
import { computed, onUnmounted, ref, watch, type Ref } from 'vue'
import { chatApi } from '@/services/api/chat'
import { parseStepUp, type StepUpChallenge } from '@/services/membership/membership'
import {
  alreadyDecidedIds, approveAllIds, decidedElsewhere, pendingShown, type ApprovalItem, type DecidedElsewhere,
} from '@/services/chat/approvals'

export interface PendingStepUp {
  decision: 'approve' | 'deny' | 'choose'
  ids: string[]
  challenge: StepUpChallenge
  option?: number   // V0652 (ab): the option a choose is resent with
}

export interface ChatApprovalsOptions {
  /** The signed-in developer's id, read when a late press is explained ("another device" when it is theirs). */
  myDeveloperId?: () => number | string | null | undefined
}

export function useChatApprovals(conversationId: Ref<string>, token: Ref<string>, enabled: Ref<boolean>,
                                 options: ChatApprovalsOptions = {}) {
  const items = ref<ApprovalItem[]>([])
  const canDecide = ref(false)
  const presence = ref('off')
  const loaded = ref(false)
  const readFailed = ref(false)
  const busyIds = ref<Set<string>>(new Set())
  const lastError = ref('')
  const stepUp = ref<PendingStepUp | null>(null)
  const late = ref<DecidedElsewhere | null>(null)
  const now = ref(Date.now())
  let timer: ReturnType<typeof setInterval> | null = null
  let readSeq = 0

  function tick() { now.value = Date.now() }
  function startClock() { if (!timer) timer = setInterval(tick, 1000) }
  function stopClock() { if (timer) { clearInterval(timer); timer = null } }

  async function refresh(): Promise<void> {
    const cid = conversationId.value
    const mine = ++readSeq
    if (!enabled.value || !cid || !token.value) { items.value = []; loaded.value = false; return }
    try {
      const r = await chatApi.listApprovals(token.value, cid, 'pending')
      if (cid !== conversationId.value || mine !== readSeq) return
      items.value = Array.isArray(r?.items) ? r.items : []
      canDecide.value = !!r?.can_decide
      presence.value = String(r?.presence || 'off')
      readFailed.value = false
      loaded.value = true
    } catch (e: any) {
      if (cid !== conversationId.value || mine !== readSeq) return
      // 501 = switched off on this registry, 409 = not a room approvals live in: there is nothing to show, by name
      if (e?.status === 501 || e?.status === 409 || e?.status === 404) {
        items.value = []; readFailed.value = false; loaded.value = true
        return
      }
      readFailed.value = true
    }
    if (items.value.length) startClock(); else stopClock()
  }

  /** A press on requests decided before it: read the first one's record and keep what it says for the panel. */
  async function explainLate(cid: string, ids: string[]): Promise<boolean> {
    let myId: number | string | null | undefined = null
    try { myId = options.myDeveloperId?.() } catch { myId = null }
    for (const id of ids.slice(0, 3)) {
      try {
        const rec = await chatApi.getApproval(token.value, id)
        if (cid !== conversationId.value) return false
        const said = decidedElsewhere(rec, myId)
        if (said) { late.value = said; return true }
      } catch { /* the next id, or nothing to say */ }
    }
    return false
  }

  async function decide(decision: 'approve' | 'deny' | 'choose', ids: string[], challengeId?: string,
                        option?: number): Promise<boolean> {
    const cid = conversationId.value
    if (!ids.length || !cid) return false
    const marking = new Set(busyIds.value)
    ids.forEach((i) => marking.add(i))
    busyIds.value = marking
    lastError.value = ''
    late.value = null
    try {
      const r: any = await chatApi.decideApprovals(token.value, cid, {
        decision, approval_ids: ids, surface: 'console',
        ...(challengeId ? { challenge_id: challengeId } : {}),
        ...(decision === 'choose' && typeof option === 'number' ? { option } : {}),
      })
      stepUp.value = null
      // decided ones leave the panel now; the next read confirms it
      items.value = items.value.filter((i) => !ids.includes(i.id))
      const before = alreadyDecidedIds(r, ids)
      if (before.length) await explainLate(cid, before)
      void refresh()
      return true
    } catch (e: any) {
      const ch = e?.status === 428 ? parseStepUp(e?.body) : null
      if (ch) { stepUp.value = { decision, ids, challenge: ch, ...(typeof option === 'number' ? { option } : {}) }; return false }
      // 409: decided the other way before this press; the record says when and by whom (the server's sentence stays
      // the fallback when the record cannot be read)
      if (e?.status === 409 && await explainLate(cid, ids)) {
        items.value = items.value.filter((i) => !ids.includes(i.id))
      } else {
        lastError.value = String(e?.detail || e?.message || 'The decision was not recorded.')
      }
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
  /** V0652 (ab): a choice is decided by one of its options, one request at a time (deny declines them all). */
  function choose(id: string, option: number) { return decide('choose', [id], undefined, option) }
  /** Exactly the requests on screen that are pending and unexpired at the moment of the press. */
  function approveAll() { return decide('approve', approveAllIds(items.value, Date.now())) }
  function resendWithChallenge(challengeId: string) {
    const s = stepUp.value
    return s ? decide(s.decision, s.ids, challengeId, s.option) : Promise.resolve(false)
  }

  watch([conversationId, enabled], () => {
    items.value = []; stepUp.value = null; lastError.value = ''; late.value = null; void refresh()
  }, { immediate: true })

  // V0652 (y): back on screen, read again (a request decided on another device leaves without a reload)
  function onBack() {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    void refresh()
  }
  if (typeof window !== 'undefined') window.addEventListener('focus', onBack)
  if (typeof document !== 'undefined') document.addEventListener('visibilitychange', onBack)
  onUnmounted(() => {
    stopClock()
    if (typeof window !== 'undefined') window.removeEventListener('focus', onBack)
    if (typeof document !== 'undefined') document.removeEventListener('visibilitychange', onBack)
  })

  return {
    items, shown, allIds, canDecide, presence, loaded, readFailed, busyIds, lastError, stepUp, late, now,
    refresh, approve, deny, choose, approveAll, resendWithChallenge,
  }
}
