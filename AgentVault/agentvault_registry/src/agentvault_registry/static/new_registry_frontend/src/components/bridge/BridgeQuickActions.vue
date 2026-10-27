<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * §BRIDGE R8 — QUICK ACTIONS.
 *
 * His brief: *"the buttons on network pulse. instead of routing to the pages,
 * make the most important actions quick actionable from this view. so it displays
 * a modal or something. modals already exist. could be reused from the views."*
 *
 * THREE RULES THIS OBEYS, AND WHY EACH ONE IS LOAD-BEARING
 *
 * 1. NOTHING NEW IS BUILT. Every action calls an EXISTING rail through an
 *    EXISTING wrapper — `fundAgentLocal` (Galactic Command's own), `tegApi.smartSend`,
 *    the lock store — and every dialog is an EXISTING component:
 *    `AmountActionModal` from the command centre (it already carries the
 *    mis-target guard, the amount validator and the typed confirmation above a
 *    threshold).
 *    Doctrine rule 14: no parallel money flow, ever.
 *
 * 2. THE TARGET IS WHAT YOU ARE ALREADY WATCHING. A bridge is not a form. You
 *    follow an agent on the fleet log, and the actions act on THAT agent — so the
 *    thing you are looking at and the thing you are about to move money to are the
 *    same thing, and the modal names both sides before you commit. With nothing
 *    selected, a targeted action is DISABLED and says why, rather than opening a
 *    dialog that asks you to retype what the screen already knows.
 *
 * 3. IT SAYS WHAT IT DID. Every action reports the outcome in place — the amount,
 *    the counterparty and the reference — and a failure says what failed. An action
 *    surface that returns silently is indistinguishable from one that did nothing.
 */
import { ref, computed, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { useStakingStore } from '@/stores/staking'
import { tegApi } from '@/services/api/teg'
import { answeredAgain, failedSendOutcome, SendKey, sendReference } from '@/services/money/sendOutcome'
import { routeCameBackSentence, wholeLedgerRefusalSentence } from '@/services/api/ledgerRefusal'
import { newIdempotencyKey } from '@/services/api/idempotencyKey'
import { fundAgentLocal } from '@/services/api/command'
import { apiClient } from '@/services/api/client'
import AmountActionModal from '@/components/command/AmountActionModal.vue'
import ActingContextNotice from '@/components/common/ActingContextNotice.vue'

/**
 * §BRIDGE R11 #5 — CLAIM HAD NOTHING TO SAY FOR ITSELF.
 *
 * His words: *"fund send stake claim i dont know what claim means but i cant
 * test it like this."* He was right twice over: the button never said what it
 * would claim, and with nothing locked there is nothing to claim, so pressing
 * it could only ever return an empty success.
 *
 * The pending amount already exists on the agent's own locked balance
 * (`pending_rewards`, the rail CLAIM itself settles). One read on the acting
 * agent, refreshed when that agent changes — no new endpoint, no polling.
 * Unknown is shown as unknown; zero is shown as zero and the button says so.
 */
const props = defineProps<{
  /** The agent the viewer is following on the fleet log, if any. */
  targetDid: string | null
  /** Human name for that agent, when the fleet knows one. */
  targetName?: string | null
  currency: string
  /** The viewer's own agent DIDs. `/agents/{did}/lineage` is OWNER-gated, so
   *  asking it about someone else's agent is a guaranteed 404 in the console —
   *  measured, 2026-08-19. And "pay the principal" only means anything for an
   *  agent you actually own. §BRIDGE R9. */
  ownedDids?: string[]
  /**
   * §POCKETBRIDGE #PK7 — how a target is acquired is a fact about the HOST
   * surface, not this component. The default copy says "right-click an agent,
   * on the map or in the fleet log", which is the truth on the bridge and a
   * nonsense instruction on glass. A touch host passes its own sentence.
   */
  targetHint?: string
  /** §POCKETBRIDGE2 P0.3 — provenance of the acting authority, e.g. "via
   *  imported credentials" or "credential vault locked". Rendered muted after
   *  the executor's name; omitted = nothing shown (desktop bridge default). */
  actingHint?: string
  /**
   * §POCKETBRIDGE #PK8 (D3 ratified) — one door per money path. On the bridge
   * SEND owns an AmountActionModal; in Pocket the PocketSend sheet (dry-run →
   * biometric → send) is the ONE send door, so 'emit' hands the target over
   * instead of opening a second money dialog. Default 'modal' = bridge
   * behavior, byte-identical.
   */
  sendMode?: 'modal' | 'emit'
}>()

const emit = defineEmits<{
  /** R15.5 — VOTE / BID / POST WORK are doors to a lane, never actions here. */
  (e: 'open-lane', lane: 'senate' | 'guild'): void
  /** #PK8 — sendMode 'emit': the host's own send door opens, prefilled. */
  (e: 'open-send', p: { to: string | null }): void
}>()

const { t } = useI18n()
const authStore = useAuthStore()
const stakingStore = useStakingStore()

type ActionKey = 'fund' | 'request' | 'send' | 'vote' | 'bid' | 'postwork'

const openAction = ref<ActionKey | null>(null)
const busy = ref(false)
const outcome = ref<{ ok: boolean; text: string } | null>(null)
let outcomeTimer: ReturnType<typeof setTimeout> | null = null

const isAdmin = computed(() => !!authStore.isAdmin)
/** null = not asked yet / unreadable. A number = measured, including 0. */
const claimable = ref<number | null>(null)
const claimableLoading = ref(false)
async function refreshClaimable(): Promise<void> {
  claimable.value = null
  if (!authStore.activeAgent?.did) return
  claimableLoading.value = true
  try {
    await stakingStore.fetchMyStakingStats()
    const n = Number(stakingStore.availableRewards)
    claimable.value = Number.isFinite(n) ? n : null
  } catch {
    // Unreadable is not zero. Leaving it null makes the button say "check"
    // rather than assert an amount the network never confirmed.
    claimable.value = null
  } finally {
    claimableLoading.value = false
  }
}
const claimableText = computed<string | null>(() => {
  if (claimable.value === null) return null
  return claimable.value === 0
    ? t('bridge.qa.claimNone', 'nothing pending')
    : `${claimable.value.toLocaleString(appLocale(), { maximumFractionDigits: 4 })} ${props.currency || ''}`.trim()
})
const activeAgent = computed<any | null>(() => authStore.activeAgent || null)
const hasAgent = computed(() => !!activeAgent.value?.did)
const executorLabel = computed(() =>
  activeAgent.value?.name || activeAgent.value?.did || t('bridge.qa.noAgent', 'no agent selected'))
const targetLabel = computed(() =>
  props.targetName || (props.targetDid ? `${props.targetDid.slice(0, 22)}…` : ''))

/**
 * Above this, `AmountActionModal` demands the amount be TYPED again. Deliberately
 * low for a glance-surface: this view exists to be used quickly, which is exactly
 * why the large move should be the slow one.
 */
const WARN_AT = 1000

interface QuickAction {
  key: ActionKey
  label: string
  help: string
  /** null = available; a string = the honest reason it is not. */
  blocked: string | null
  needsTarget: boolean
}

const actions = computed<QuickAction[]>(() => {
  const noAgent = t('bridge.qa.blockAgent', 'Select an agent first: this acts as an agent, not as you.')
  // R13 #2/#5: "send button doesnt work" was this message. SEND was BLOCKED for
  // want of a target and the block reason only named the fleet log, while he had
  // been right-clicking the map — where selection did not exist yet. It does now,
  // and the message names both ways in.
  const noTarget = props.targetHint
    || t('bridge.qa.blockTarget', 'Nothing is targeted yet. Right-click an agent on the map, or in the fleet log, and it becomes the target.')
  const noAdmin = t('bridge.qa.blockAdmin', 'Treasury funding is an admin action.')
  const handBlock = t('bridge.qa.blockHand', 'This is a hand — its principal holds the wallet. Use "pay the principal" below.')
  return [
    /*
     * §BRIDGE R13 #4 — "FUND should be only available for admin accounts. others
     * cant do this. but request fund is a good thing to add adittionally for
     * devs without admin account. they can request funding."
     *
     * FUND moves treasury money and is admin-only in the backend, so offering it
     * to a developer was offering a door that cannot open. It is no longer
     * RENDERED for non-admins; in its place they get the petition rail that
     * already exists for exactly this (FLOW 10, `POST /funding/request`, agent
     * JWT) — no new endpoint, and the admin approves it on the existing
     * /admin/funding rail.
     */
    ...(isAdmin.value ? [{
      key: 'fund' as ActionKey,
      label: t('bridge.qa.fund', 'FUND'),
      help: t('bridge.qa.fundHelp', 'Fund the agent you are following, from the registry treasury.'),
      blocked: !props.targetDid ? noTarget : (isHand.value && !payVia.value ? handBlock : null),
      needsTarget: true,
    }] : [{
      key: 'request' as ActionKey,
      label: t('bridge.qa.request', 'REQUEST'),
      help: t('bridge.qa.requestHelp', 'Ask an admin to fund your active agent from the treasury. Goes on the funding queue for approval.'),
      blocked: !hasAgent.value ? noAgent : null,
      needsTarget: false,
    }]),
    {
      key: 'send',
      label: t('bridge.qa.send', 'SEND'),
      help: t('bridge.qa.sendHelp', 'Pay the agent you are following, as your active agent.'),
      // #PK8 — in 'emit' mode the host's send door takes any recipient, so a
      // missing target is not a block: the door opens blank. A HAND target
      // still demands the explicit principal choice before it prefills.
      blocked: !hasAgent.value ? noAgent
        : props.sendMode === 'emit' ? (props.targetDid && isHand.value && !payVia.value ? handBlock : null)
        : !props.targetDid ? noTarget : (isHand.value && !payVia.value ? handBlock : null),
      needsTarget: props.sendMode !== 'emit',
    },
    /*
     * §BRIDGE R15.5 — VOTE / BID / POST WORK.
     *
     * These are DOORS, not money paths. Each opens the lane where the real
     * action happens with typed input and its own confirmation — the same
     * discipline as QUICK BUY, which prefills the exchange ticket and never
     * places an order. A quick action that could commit a bounty or cast a vote
     * on one click is exactly how a mis-click becomes a decision.
     *
     * VOTE needs no target: a proposal is not an agent. It DOES need an agent,
     * because governance on this network is agent-only (PART 5 flow 7).
     */
    {
      key: 'vote',
      label: t('bridge.qa.vote', 'VOTE'),
      help: t('bridge.qa.voteHelp', 'Open the senate lane: proposals still open, and how you have voted.'),
      blocked: !hasAgent.value ? noAgent : null,
      needsTarget: false,
    },
    {
      key: 'bid',
      label: t('bridge.qa.bid', 'BID'),
      help: t('bridge.qa.bidHelp', 'Open the guild board: work you can bid on.'),
      blocked: !hasAgent.value ? noAgent : null,
      needsTarget: false,
    },
    {
      key: 'postwork',
      label: t('bridge.qa.postwork', 'POST WORK'),
      help: t('bridge.qa.postworkHelp', 'Open the guild board and post work of your own, with a bounty.'),
      blocked: !hasAgent.value ? noAgent : null,
      needsTarget: false,
    },
    /*
     * §BRIDGE R13 #3 — LOCK and CLAIM are GONE from here, on his word:
     * "top staking is irrelevant. can be removed ... the bottom modal you have
     * created is better more complete" and "claim button greyed out. can be
     * removed is already in staking modal".
     *
     * He is right on the merits, not just the duplication: this LOCK button could only
     * ever lock for a fixed 7 days with no tier choice, while the LOCKS
     * lane offers pending + CLAIM, an amount with a lock-period selector, the
     * existing positions and UNLOCK. A shortcut that can do less than the full
     * thing one click away is not a shortcut, it is a worse second copy.
     * The lane is reached from the LOCKS door in the same panel.
     */
  ]
})

/*
 * §BRIDGE R9 — SUBAGENTS ARE HANDS, NOT PAYEES.
 *
 * His words: *"we need treatment for subagents and delegation so we dont get
 * errors."* A spawned sub-agent (§SPAWN-ANCHOR) is a walletless HAND: its
 * PRINCIPAL holds the purse, and the registry resolves a hand's spend to that
 * principal's wallet. So aiming FUND or SEND at a hand offers a payment that
 * cannot land where the screen implies.
 *
 * The registry already knows this and says so: `GET /agents/{did}/lineage`
 * returns `born_from.anchored` (walletless) with `born_from.parent_did` (the
 * principal). One small owner-gated call per selection, cached for the session,
 * no new endpoint. When the target is a hand we say so and offer the principal
 * as the payable target — treated, not errored.
 */
interface HandInfo { anchored: boolean; principal: string | null; checked: boolean }
const handCache = new Map<string, HandInfo>()
const handInfo = ref<HandInfo | null>(null)
/** When the viewer redirects to the principal, this is the DID we act on. */
const payVia = ref<string | null>(null)

const ownedSet = computed(() => new Set((props.ownedDids || []).map(d => String(d).toLowerCase())))

async function inspectTarget(did: string | null): Promise<void> {
  payVia.value = null
  handInfo.value = null
  if (!did) return
  // Not ours -> not askable, and not answerable. Say nothing.
  if (ownedSet.value.size && !ownedSet.value.has(did.toLowerCase())) return
  const k = did.toLowerCase()
  const hit = handCache.get(k)
  if (hit) { handInfo.value = hit; return }
  try {
    const r = await apiClient.get(`/agents/${encodeURIComponent(did)}/lineage`, { params: { max_gen: 1 } })
    const bf = r.data?.born_from || null
    const info: HandInfo = { anchored: !!bf?.anchored, principal: bf?.parent_did || null, checked: true }
    handCache.set(k, info)
    handInfo.value = info
  } catch {
    // Not owned by us, or no lineage: not a hand as far as we can tell. Say
    // nothing rather than guess — an unproven claim about someone's wallet is
    // worse than silence.
    const info: HandInfo = { anchored: false, principal: null, checked: false }
    handCache.set(k, info)
    handInfo.value = info
  }
}
watch(() => props.targetDid, (d) => { void inspectTarget(d) }, { immediate: true })
watch(() => authStore.activeAgent?.did, () => { void refreshClaimable() }, { immediate: true })

const isHand = computed(() => !!handInfo.value?.anchored && !!handInfo.value?.principal)
/** Who the money actually moves to. */
const payDid = computed(() => payVia.value || props.targetDid)
const payLabel = computed(() =>
  payVia.value ? `${payVia.value.slice(0, 22)}…` : targetLabel.value)

const current = computed(() => actions.value.find(a => a.key === openAction.value) || null)

const modalTitle = computed(() => {
  switch (openAction.value) {
    case 'fund': return t('bridge.qa.fundTitle', 'Fund agent from treasury')
    case 'send': return t('bridge.qa.sendTitle', 'Send to agent')
    case 'request': return t('bridge.qa.requestTitle', 'Request funding')
    default: return ''
  }
})

function say(ok: boolean, text: string): void {
  outcome.value = { ok, text }
  if (outcomeTimer) clearTimeout(outcomeTimer)
  // Long enough to read a reference number, short enough not to become furniture.
  outcomeTimer = setTimeout(() => { outcome.value = null }, 12000)
}

function start(a: QuickAction): void {
  if (a.blocked) { say(false, a.blocked); return }
  outcome.value = null
  // R15.5 — these three open the lane that owns the action. They do not open a
  // modal here, because there is no amount to confirm at this point: the lane
  // takes the typed input and owns the confirmation.
  if (a.key === 'vote') { emit('open-lane', 'senate'); return }
  if (a.key === 'bid' || a.key === 'postwork') { emit('open-lane', 'guild'); return }
  // #PK8 — the host owns the send door; hand it the resolved payee (the
  // principal when the viewer chose "pay the principal instead").
  if (a.key === 'send' && props.sendMode === 'emit') { emit('open-send', { to: payDid.value || null }); return }
  openAction.value = a.key
}

function close(): void {
  if (busy.value) return
  openAction.value = null
}

// §FESUITE (2026-10-05): the quick send keeps one Idempotency-Key per request (recipient, amount, reason): a send that got
// no answer, or a 5xx, may have gone through and is said so; pressing again asks once more with the same key, never twice
const sendKey = new SendKey(newIdempotencyKey)

async function onConfirm(p: { amount: string; reason: string }): Promise<void> {
  const key = openAction.value
  if (!key || busy.value) return
  busy.value = true
  try {
    if (key === 'fund') {
      const r: any = await fundAgentLocal({
        target_agent_did: String(payDid.value),
        amount: p.amount,
        reason: p.reason || 'bridge quick action',
      })
      const ref0 = r?.transaction_id || r?.data?.transaction_id || r?.id || ''
      say(true, t('bridge.qa.funded', 'Funded') + ` ${p.amount} ${props.currency} → ${targetLabel.value}${ref0 ? ` · ${String(ref0).slice(0, 12)}` : ''}`)
    } else if (key === 'send') {
      const r: any = await tegApi.smartSend({
        receiver_did: String(payDid.value),
        amount: p.amount,
        message: p.reason || undefined,
      }, { idempotencyKey: sendKey.for(`${payDid.value}|${p.amount}|${p.reason || ''}`) })
      sendKey.answered()
      // §REPATLANE-7: the reference is the answer's transfer_id, and a payment answered again under this key says so
      const ref0 = sendReference(r)
      say(true, t('bridge.qa.sent', 'Sent') + ` ${p.amount} ${props.currency} → ${targetLabel.value}${ref0 ? ` · ${String(ref0).slice(0, 12)}` : ''}`
        + (answeredAgain(r) ? ` · ${t('bridge.qa.sentFromFirst', 'your first press had already gone through')}` : ''))
    } else if (key === 'request') {
      // FLOW 10, the petition rail that already exists: an agent asks, an admin
      // approves on /admin/funding. No new endpoint, no money moved here.
      const r: any = await apiClient.post('/funding/request', {
        amount: p.amount,
        reason: p.reason || 'requested from the bridge',
      })
      const id = r?.data?.id ?? r?.data?.request_id ?? ''
      say(true, t('bridge.qa.requested', 'Funding requested') +
        ` ${p.amount} ${props.currency}` + (id ? ` · #${id}` : '') +
        ' · ' + t('bridge.qa.requestedNote', 'an admin has to approve it'))
    }
    openAction.value = null
  } catch (e: any) {
    if (key === 'send' && failedSendOutcome(e) === 'unknown') {
      // the value may have moved: the key stays, so pressing send again cannot pay twice
      say(false, t('bridge.qa.unknownOutcome', 'The send may have gone through: no answer said whether it did. Pressing send again asks once more with the same request, which never pays twice.'))
      return
    }
    if (key === 'send') sendKey.answered()
    // §LEDGERGATE: the ledger's own sentence (nothing moved), never the raw detail with its code word
    const ledger = wholeLedgerRefusalSentence(e) || routeCameBackSentence(e)
    if (ledger) { say(false, ledger); return }
    // The body, not the status: two different denials share a 403.
    const msg = e?.response?.data?.detail || e?.response?.data?.title || e?.message || 'failed'
    say(false, t('bridge.qa.failed', 'Failed') + `: ${String(msg).slice(0, 140)}`)
  } finally {
    busy.value = false
  }
}

/* §PHONESTART (2026-09-02) — a host may open ONE action by key (Pocket home answers
   `?fund=1` with REQUEST). It goes through start(), so a blocked action says why instead of opening. */
defineExpose({ open(key: ActionKey) { const a = actions.value.find(x => x.key === key); if (a) start(a) } })
</script>

<template>
  <div class="brg-qa" data-testid="quick-actions">
    <div class="brg-qa-row">
      <button
        v-for="a in actions"
        :key="a.key"
        type="button"
        class="brg-qa-btn"
        :class="{ 'is-blocked': !!a.blocked }"
        :data-testid="`qa-${a.key}`"
        :title="a.blocked || a.help"
        :aria-disabled="!!a.blocked"
        @click="start(a)"
      >{{ a.label }}</button>
    </div>

    <!-- §BRIDGE R11 #6 — WHO IS ACTING, ALWAYS.
         *"the selected agent should then be the acting one but you should always
         see the current selected agent in the 'your fleet' gui."* Two different
         parties are involved in every quick action and only one of them was on
         screen: the TARGET. The EXECUTOR (your active agent) lived inside the
         dialogs. Both are named here now, permanently. -->
    <!-- §BRIDGE R13 #2 — TWO ROLES, ONE LINE, NEITHER OPTIONAL.
         "i picked an agent by right clicking. another agent is selected in the
          top right. i think the selection is biting eachother!"
         They were not fighting — they are different jobs (who ACTS vs who is
         ACTED ON) and nothing on screen said so, so two different names in two
         different places read as a conflict. Now it is one sentence with an
         arrow, and the target half says how to set it. -->
    <p class="brg-qa-roles" data-testid="qa-actor">
      <!-- ⚠ `gap` separates these visually but NOT in the accessible text run.
           R13 used `&#32;` entities for the spaces — and Vue's whitespace
           CONDENSE eats an entity-space at an element boundary, so the run
           read "ACTING ASTrader Theo" again. §POCKETBRIDGE's battery caught
           the regression; an INTERPOLATED space is dynamic text and survives. -->
      <span class="brg-qa-actor-k">{{ t('bridge.qa.acting', 'ACTING AS') + ' ' }}</span>
      <strong :class="{ 'is-none': !hasAgent }">{{ executorLabel }}</strong>
      <span v-if="actingHint" class="brg-qa-actor-x" data-testid="qa-acting-hint">{{ ' ' }}({{ actingHint }})</span>
      <span v-if="claimableText" class="brg-qa-actor-x"
            :title="t('bridge.qa.claimableHelp', 'Payouts on locked units pending for this agent: claim them in the LOCKS lane')">
        · {{ claimableText }}
      </span>
      <span class="brg-qa-arrow" aria-hidden="true">{{ ' \u2192 ' }}</span>
      <span class="brg-qa-actor-k">{{ t('bridge.qa.onto', 'ON') + ' ' }}</span>
      <strong v-if="targetDid" data-testid="qa-target">{{ targetLabel }}</strong>
      <span v-else class="brg-qa-notarget" data-testid="qa-target">
        {{ targetHint || t('bridge.qa.noTarget2', 'nobody yet — right-click an agent, on the map or in the fleet log') }}
      </span>
    </p>

    <!-- §BRIDGE R9 — a hand says what it is, and offers the wallet that exists. -->
    <p v-if="isHand" class="brg-qa-hand" data-testid="qa-hand">
      <span class="brg-qa-hand-k">{{ t('bridge.qa.handIs', 'HAND') }}</span>
      {{ t('bridge.qa.handWhy', 'walletless sub-agent — its principal holds the purse') }}
      <button type="button" class="brg-qa-hand-btn" data-testid="qa-pay-principal"
              @click="payVia = payVia ? null : (handInfo?.principal || null)">
        {{ payVia ? t('bridge.qa.handBack', 'aim back at the hand')
                  : t('bridge.qa.handPay', 'pay the principal instead') }}
      </button>
    </p>

    <p v-if="outcome" class="brg-qa-out" :class="outcome.ok ? 'is-ok' : 'is-bad'" data-testid="qa-outcome">
      {{ outcome.text }}
    </p>

    <!-- §FOREIGNACT — the desktop bridge is where the Commander's misread was
         inherited from: these actions execute AS the selected agent, which the
         api client sends to THAT agent's home registry, while the panel showed
         the viewer's currency. Renders nothing for a local agent. -->
    <ActingContextNotice strong />

    <AmountActionModal
      :show="openAction === 'fund' || openAction === 'send' || openAction === 'request'"
      :title="modalTitle"
      :target-label="openAction === 'request' ? (executorLabel as string) : (payLabel || '—')"
      :executor-label="openAction === 'fund' ? t('bridge.qa.treasury', 'registry treasury (admin)')
        : openAction === 'request' ? t('bridge.qa.queue', 'the funding queue (admin approves)')
        : (executorLabel as string)"
      :currency="currency"
      :busy="busy"
      :warn-threshold="WARN_AT"
      :amount-label="t('bridge.qa.amount', 'Amount')"
      @confirm="onConfirm"
      @cancel="close"
    />

  </div>
</template>

<style scoped>
.brg-qa { display: flex; flex-direction: column; gap: 4px; margin-top: 8px; }
/* §FESUITE (2026-10-10, axe on the everything-on sandbox): the acting-as strip drew at 3.0:1 and 3.23:1 on its panel
   (#131825; --nc-text-dim is defined nowhere, so the fallback always renders, then dimmed again by opacity). #7a8cab
   is 5.2:1, no opacity below. */
.brg-qa-roles { margin: 2px 0 0; font-size: 9px; letter-spacing: 0.04em; line-height: 1.5;
  color: var(--nc-text-dim, #7a8cab); display: flex; flex-wrap: wrap; gap: 0 4px; align-items: baseline; }
.brg-qa-actor-k { letter-spacing: 0.14em; }
/* full strength (it was 0.8, below 4.5:1); the rule keeps the class the template names defined */
.brg-qa-actor-x { opacity: 1; }
.brg-qa-arrow { opacity: 0.5; margin: 0 1px; }
.brg-qa-notarget { color: var(--nc-warn, #f6c453); opacity: 0.9; }
.brg-qa-roles strong { color: var(--brand-primary, #4dd8e6); font-weight: 700; }
.brg-qa-roles strong.is-none { color: var(--nc-warn, #f6c453); font-weight: 600; }
.brg-qa-row { display: flex; flex-wrap: wrap; gap: 4px; }
.brg-qa-btn {
  /* With two actions instead of four, `flex: 1 1 auto` stretched each to half
     the panel and they read as a banner rather than buttons. Grow, but stop. */
  flex: 0 1 auto;
  min-width: 72px; max-width: 10rem;
  padding: 5px 8px;
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  color: var(--brg-ink, #cfe3f5);
  background: color-mix(in srgb, var(--brg-accent, #56b6ff) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--brg-accent, #56b6ff) 26%, transparent);
  border-radius: 3px;
  cursor: pointer;
  transition: background 140ms ease, border-color 140ms ease, transform 140ms ease;
}
.brg-qa-btn:hover { background: color-mix(in srgb, var(--brg-accent, #56b6ff) 18%, transparent); }
.brg-qa-btn:active { transform: translateY(1px); }
.brg-qa-btn.is-blocked { opacity: 0.42; cursor: not-allowed; }
.brg-qa-target {
  margin: 0; font-size: 9px; letter-spacing: 0.06em;
  color: color-mix(in srgb, var(--brg-ink, #cfe3f5) 62%, transparent);
}
.brg-qa-target--none { opacity: 0.5; font-style: italic; }
.brg-qa-hand {
  margin: .25rem 0 0; font-size: 9px; letter-spacing: .04em; line-height: 1.5;
  color: var(--text-tertiary, #7a8a9a);
}
.brg-qa-hand-k {
  display: inline-block; padding: 0 .25rem; margin-right: .3rem; border-radius: 2px;
  background: color-mix(in srgb, var(--warn, #ffb648) 22%, transparent);
  color: var(--warn, #ffb648); font-weight: 600;
}
.brg-qa-hand-btn {
  background: none; border: 0; padding: 0 0 0 .35rem; cursor: pointer;
  color: var(--brand-primary, #4dd8e6); font-size: 9px; letter-spacing: .04em;
  text-decoration: underline; text-underline-offset: 2px;
}
.brg-qa-out { margin: 2px 0 0; font-size: 9.5px; line-height: 1.35; }
.brg-qa-out.is-ok { color: var(--brg-ok, #36d399); }
.brg-qa-out.is-bad { color: var(--brg-warn, #ffb86b); }
</style>
