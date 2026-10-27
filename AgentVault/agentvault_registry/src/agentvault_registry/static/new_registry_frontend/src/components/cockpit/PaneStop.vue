<script setup lang="ts">
/**
 * §COCKPIT P5 — STOP. The clamp, one gesture, no step-up.
 *
 * I7 — STOPPING IS NEVER GATED. A posture that makes withdrawing authority harder than
 * granting it has the incentive exactly backwards, so nothing here asks for a
 * confirmation code, a signature or a floor. Revoking is the safe direction by
 * construction: it can only ever remove authority.
 *
 * ⚠ HONEST V1 SCOPE. This is the DEVELOPER's clamp over their OWN mandates. The
 * coordinated-suspension rail — registry flip + IRONHAND revoke + TEG suspend +
 * cross-TEG blocklist — is ADMIN-tier and is a later mount, not this pane. Labelling
 * this "emergency stop" without saying which stop it is would be the worse failure:
 * the moment you need it is the moment you cannot afford to discover its limits.
 *
 * The population is deliberately the agents THIS COCKPIT GOVERNS — the ones named by a
 * live mandate — not the whole fleet. A stop pane that opens a 15,000-row picker is a
 * stop pane you cannot use in the ten seconds you have.
 */
import { ref, computed, onMounted } from 'vue'
import Icon from '@/components/Icon.vue'
import PaneShell from './PaneShell.vue'
import AgentLink from './AgentLink.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { liabilityApi, type LiabilityMandate, type CeilingState } from '@/services/api/liability'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'
import { useCockpitBus } from '@/composables/useCockpitBus'
// §COCKPITSTOP — read the acting agent from the SAME store the API client routes on, so
// the sentence about it can never disagree with what the desk is actually doing.
import { useActingContext } from '@/composables/useActingContext'
import { stopActingState } from '@/services/cockpit/stopActing'
import { PANES } from './paneRegistry'

const { t, tp } = useI18n()
const acting = useActingContext()
const def = PANES.stop

const mandates = ref<LiabilityMandate[]>([])
const loading = ref(true)
const err = ref('')
const readAt = ref<number | null>(null)   // §COCKPITDESK: when the source last answered (PaneShell law 4)
const msg = ref('')
const busy = ref<string | null>(null)

const live = computed(() => mandates.value.filter(m => m.status === 'signed'))

/* 🔴 HIS REPORT, TWICE. First: *"(stop) has an agent selected and i have not selected an
 * agent."* I answered it with a DISCLAIMER — "nothing here follows the agent you are
 * acting as" — and he reported the same confusion again the next day, now with a name:
 * *"forge-a-gen-2 is being displayed in the stop modul but sybil is picked in my agent
 * selector."*
 *
 * The disclaimer was true and useless. It asked him to generalise from a rule instead of
 * answering the question he was actually asking, which is "where is SYBIL?" — and a
 * general statement is exactly what a reader skims past on a pane whose buttons deactivate
 * agents. So the pane now NAMES his agent and says what it holds: measured on this account
 * there is exactly ONE live mandate and it belongs to forge-a-gen-2, so the honest sentence
 * is that SYBIL has none. Silence about the agent he chose is what made a name he did not
 * choose look like the desk had chosen one for him.
 *
 * ⚠ A mandate for the acting agent SORTS FIRST and is marked, so when the answer is "yes,
 * here it is" the reader does not have to hunt for it either. */
const actingDid = computed<string>(() => String(acting.actingAgent.value?.did || ''))
const actingName = computed<string>(() =>
  String(acting.actingAgent.value?.name || acting.actingAgent.value?.agent_name || ''))
const actingHasMandate = computed<boolean>(() =>
  !!actingDid.value && live.value.some(m => m.agent_did === actingDid.value))
/** The three-state decision, in one TESTED place rather than a template ternary — it has
 *  been wrong twice, and the live browser cannot reach two of its three branches. */
const actingState = computed(() => stopActingState(actingName.value, actingHasMandate.value))
/** Acting agent's mandates first — the rest keep their order. */
const liveSorted = computed(() => {
  const a = actingDid.value
  if (!a) return live.value
  return [...live.value].sort((x, y) =>
    (y.agent_did === a ? 1 : 0) - (x.agent_did === a ? 1 : 0))
})
const empty = computed(() => !loading.value && live.value.length === 0)

/* 🔴 §COCKPITPOLISH P1 — THE PANE NAMED ITS SUBJECT `di…`.
 *
 * This rendered `m.agent_did` and nothing else, and in a one-column slot the identity
 * column was squeezed to two characters by the two buttons beside it — so the control that
 * DEACTIVATES AN AGENT sat next to an identity no human could read. That is a safety
 * defect wearing a layout defect's clothes, and it is the reason this pane got looked at.
 *
 * Names come from the EXISTING `include_dids` rail, which hydrates specific DIDs
 * regardless of the recency window (§agentfinder) — exactly the problem it was built for.
 * `limit: 1` keeps the base page it is prepended to as small as the endpoint allows.
 *
 * ⚠ A name that failed to resolve renders as the DID, never as blank and never as a
 * guess: "we could not look it up" and "it has no name" are different facts, and on this
 * pane the difference decides whether you can tell what you are about to switch off. */
const names = ref<Record<string, string>>({})

/** False until the lookup has been ATTEMPTED (settled either way).
 *
 * 🔴 §COCKPITFIT — his original report was that STOP named its subject `di…`. P1 resolved
 * the name, and the pane reads correctly once loaded — but `live` and `loadNames()` are
 * two awaits, and BETWEEN them `agentLabel()` fell through to the raw DID. So the button
 * that deactivates an agent spent that window labelled
 * `Deactivate did:theprotocol:65f488a8-…`, which is the very thing he reported, briefly.
 * Caught by READING a screenshot: one of three shots captured the flash.
 *
 * The distinction the pane already documents is preserved exactly — a name that FAILED to
 * resolve still renders as the DID, because "we could not look it up" and "it has no name"
 * are different facts. This only says: do not claim either until we have asked. */
const namesReady = ref(false)

async function loadNames() {
  const dids = Array.from(new Set(live.value.map(m => m.agent_did).filter(Boolean)))
  if (!dids.length) { names.value = {}; namesReady.value = true; return }
  try {
    const { data } = await apiClient.get('/developers/me/agents', {
      params: { limit: 1, include_dids: dids.slice(0, 300).join(',') },
    })
    const rows: any[] = Array.isArray(data) ? data : (data?.items || [])
    const map: Record<string, string> = {}
    for (const r of rows) {
      const n = r?.name || r?.card_data?.name
      if (r?.did && n) map[r.did] = String(n)
    }
    names.value = map
  } catch { /* the DID is still shown; a failed lookup must not blank the row */ }
  finally { namesReady.value = true }
}

/** The name when we have one, the full DID when we do not. Never truncated here —
 *  truncation is the stylesheet's job and `title` always carries the whole value. */
function agentLabel(did: string): string { return names.value[did] || did }
/** What the BUTTON says. Before the lookup settles it names no one rather than naming
 *  something unreadable; after it settles it is `agentLabel`, DID fallback included. */
function actionLabel(did: string): string {
  return namesReady.value ? agentLabel(did) : ''
}
const hasName = (did: string) => !!names.value[did]

/* §CEILING (P7) — a standing consent IS delegated authority, so it belongs on the pane
 * where authority is withdrawn. Shown per mandate with its decay state RE-DERIVED by the
 * server (never a stored `live` flag), and removable in one gesture: I7 says tightening
 * is never gated, and that has to include un-granting the right to not be asked. */
const ceilings = ref<Record<string, CeilingState>>({})
/* §FESUITE (V0577): the mandates whose standing-consent read failed. The catch said "a mandate without one is the
 * normal case", but the registry answers 200 with `ceiling: null` for none, so a failed read hid a standing consent on
 * the one pane where it is withdrawn. */
const ceilingUnread = ref<Record<string, boolean>>({})

async function loadCeilings() {
  const out: Record<string, CeilingState> = {}
  const unread: Record<string, boolean> = {}
  await Promise.all(live.value.map(async (m) => {
    try { out[m.id] = await liabilityApi.getCeiling(m.id) } catch { unread[m.id] = true }
  }))
  ceilings.value = out
  ceilingUnread.value = unread
}

async function removeCeiling(m: LiabilityMandate) {
  busy.value = `c:${m.id}`; msg.value = ''
  try {
    await liabilityApi.tightenCeiling(m.id)
    msg.value = t('cockpit.stop.ceilingRemoved', 'Standing consent removed. You will be asked again from the next action on.')
    await load()
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || e?.message || t('cockpit.stop.failed', 'Could not remove it.')
  } finally { busy.value = null }
}

async function load() {
  try {
    mandates.value = (await liabilityApi.myMandates()).mandates || []
    err.value = ''; readAt.value = Date.now()
    void loadCeilings()
    void loadNames()
  } catch (e: any) {
    if (e?.response?.status === 404) { mandates.value = []; err.value = ''; readAt.value = Date.now() }
    else err.value = e?.response?.data?.detail || e?.message || 'unreachable'
  } finally { loading.value = false }
}

async function revoke(m: LiabilityMandate) {
  busy.value = m.id; msg.value = ''
  try {
    await liabilityApi.revokeMandate(m.id, 'stopped from the cockpit')
    // The clamp is INSTANT and re-derived per request: every gate that leans on this
    // mandate conveys nothing on its very next call. Nothing needs to propagate.
    msg.value = t('cockpit.stop.revoked', 'Revoked. Anything leaning on it conveys nothing from the next request on.')
    await load()
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || e?.message || t('cockpit.stop.failed', 'Could not revoke.')
  } finally { busy.value = null }
}

async function deactivate(m: LiabilityMandate) {
  busy.value = m.agent_did; msg.value = ''
  try {
    // Soft delete — the agent's row survives as `revoked` and so does its balance.
    // "Deactivate" is the honest word for what this rail does; "delete" would not be.
    await apiClient.delete(`/developers/me/agents/${encodeURIComponent(m.agent_did)}`)
    msg.value = t('cockpit.stop.deactivated', 'Agent deactivated. Its record and balance stay put.')
    await load()
  } catch (e: any) {
    msg.value = e?.response?.data?.detail || e?.message || t('cockpit.stop.failed', 'Could not deactivate.')
  } finally { busy.value = null }
}

useCockpitBus({ 'liability.resolved': () => { void load() } })
onMounted(() => { void load() })
</script>

<template>
  <PaneShell
    :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
    :refresh-mode="def.refreshMode" :poll-seconds="def.pollSeconds"
    :loading="loading" :error="err" :read-at="readAt" :reload="load" :empty="empty"
    :empty-text="t('cockpit.stop.empty', 'No live mandates — there is nothing delegated to stop.')"
  >
    <div class="ckd-stop" data-testid="ckd-stop">
      <!-- 🔴 §COCKPITSHOW A2 — HIS REPORT: *"(stop) has an agent selected and i have not
           selected an agent in the websites agent selector."*
           He is reading the pane correctly and the pane was not explaining itself. This
           list is MANDATES YOU SIGNED — it has nothing to do with the agent you are acting
           as, and the header switcher can be empty while this is full. But a pane that
           simply prints an agent's name gives a reader no way to know that, so a name they
           did not choose looks like the desk chose one for them. The scope now leads,
           where it is read BEFORE the name rather than in a footnote under the buttons. -->
      <p class="ckd-stop-lede" data-testid="ckd-stop-lede">
        <!-- ⚠ ONE string literal, not a concatenation. The first version split this
             fallback across two literals joined with `+`; my key extractor stored the raw
             source between the outer quotes and the words `' + '` were RENDERED ON SCREEN.
             A fallback is read by tooling as well as by Vue, so it stays a single literal. -->
        {{ tp('cockpit.stop.lede', 'Mandates you signed ({n} live) — the authorities you granted, and where you take them back.', { n: live.length }) }}
      </p>
      <!-- The sentence that answers "where is the agent I picked?" by NAME. A general
           disclaimer did not land; this one is about his agent, so there is nothing to
           generalise from. -->
      <!-- 🔴 HIS ASK, VERBATIM: *"agentselector its called where the current agent is
           selected and authed. if you would display this one with stop modul it would be
           great."* So the authenticated agent gets its OWN identity block at the top of the
           pane, above the mandates — not a sentence referring to it, which is what he had
           already told me twice was not landing.

           ⚠ WHERE I DISAGREED, AND WHY IT IS BUILT THIS WAY: the list below is MANDATES,
           and a mandate belongs to whichever agent it was signed for. It cannot become a
           list about the selected agent, because on this account SYBIL has none — one live
           mandate exists and it is forge-a-gen-2's. Filtering to the selection would empty
           the pane and hide the only authority he can actually revoke. So the selection is
           SHOWN with its own state ("no live mandate"), and the list stays complete.

           ⚠ THREE STATES, NOT TWO. His FIRST report was the header being EMPTY while the
           pane showed a name, so the no-selection branch is the one he actually hit. -->
      <div class="ckd-stop-acting" data-testid="ckd-stop-acting">
        <span class="ckd-stop-actinglbl">{{ t('cockpit.stop.actingLbl', 'ACTING AS') }}</span>
        <template v-if="actingState !== 'unselected'">
          <span class="ckd-stop-actingname" data-testid="ckd-stop-actingname">{{ actingName }}</span>
          <span class="ckd-stop-actingstate" :class="{ 'is-has': actingState === 'selected-with-mandate' }">
            {{ actingState === 'selected-with-mandate'
                ? t('cockpit.stop.actingHas2', '1 live mandate — first below')
                : t('cockpit.stop.actingNone2', 'no live mandate — nothing below is about it') }}
          </span>
        </template>
        <span v-else class="ckd-stop-actingstate">
          {{ t('cockpit.stop.actingUnset2', 'no agent selected in the header — each mandate below names its own') }}
        </span>
      </div>
      <ul class="ckd-stop-list">
        <li v-for="m in liveSorted" :key="m.id" class="ckd-stop-row"
            :class="{ 'is-acting': m.agent_did === actingDid }">
          <div class="ckd-stop-who">
            <!-- §COCKPITFRAME F5 — the mandate names its agent, and now opens it.
                 ⚠ Only once the name lookup has SETTLED: while it is in flight the label is
                 the word "resolving", and a door whose text is a status word is a door
                 pointing at nothing (the §COCKPITFIT `namesReady` rule, one level out). -->
            <AgentLink class="ckd-stop-agent" data-testid="ckd-stop-agent"
                       :class="{ 'is-pending': !namesReady }"
                       :did="namesReady ? m.agent_did : ''"
                       :label="namesReady ? agentLabel(m.agent_did) : t('cockpit.stop.resolving', 'resolving name…')"
                       :hint="m.agent_did" />
            <span v-if="m.agent_did === actingDid" class="ckd-stop-actingtag"
                  data-testid="ckd-stop-actingtag">{{ t('cockpit.stop.actingTag', 'acting as') }}</span>
            <span v-if="hasName(m.agent_did)" class="ckd-stop-did" :title="m.agent_did">{{ m.agent_did }}</span>
            <span class="ckd-stop-scope" data-testid="ckd-stop-scope"
                  :title="(m.scope || []).join(' · ')">{{ (m.scope || []).join(' · ') || '—' }}</span>
          </div>
          <div v-if="ceilings[m.id]?.ceiling" class="ckd-stop-ceil" data-testid="ckd-stop-ceiling">
            <Icon name="mdi:infinity" />
            <span :class="{ 'is-decayed': !ceilings[m.id]?.ceiling?.live }">
              {{ tp('cockpit.stop.ceiling', 'not asking below {amount} {currency} for {scope}',
                    { amount: ceilings[m.id]!.ceiling!.max_per_tx,
                      currency: ceilings[m.id]!.ceiling!.currency,
                      scope: ceilings[m.id]!.ceiling!.scope }) }}
              <em v-if="!ceilings[m.id]?.ceiling?.live" data-testid="ckd-stop-ceiling-dead">
                · {{ ceilings[m.id]?.ceiling?.state }}
              </em>
            </span>
            <button class="ckd-stop-btn" :disabled="busy === `c:${m.id}`"
                    :data-testid="`ckd-stop-ceiling-remove-${m.id}`" @click="removeCeiling(m)">
              {{ t('cockpit.stop.removeCeiling', 'Ask me again') }}
            </button>
          </div>
          <div v-else-if="ceilingUnread[m.id]" class="ckd-stop-ceil" :data-testid="`ckd-stop-ceiling-unread-${m.id}`">
            <ReadFailedNotice dense :retry="loadCeilings"
              :text="t('cockpit.stop.ceilingUnread', 'Whether this mandate carries a standing consent could not be read just now.')" />
          </div>
          <div class="ckd-stop-acts">
            <button class="ckd-stop-btn" :disabled="busy === m.id"
                    :data-testid="`ckd-stop-revoke-${m.id}`" @click="revoke(m)">
              <Icon name="mdi:hand-back-left-off-outline" /> {{ t('cockpit.stop.revoke', 'Revoke mandate') }}
            </button>
            <!-- ⚠ NOT gated, deliberately: I7 says stopping is never harder than granting,
                 and a confirmation dialog on the withdraw side has the incentive exactly
                 backwards. What it gains instead is that the GESTURE NAMES ITS TARGET —
                 the button reads the agent's name, so the thing you are switching off is
                 legible at the moment you press it rather than two characters above it. -->
            <button class="ckd-stop-btn ckd-stop-btn--hard" :disabled="busy === m.agent_did"
                    :title="namesReady
                      ? tp('cockpit.stop.deactivateHint', 'Deactivate {name} — its record and balance stay put', { name: actionLabel(m.agent_did) })
                      : t('cockpit.stop.deactivateHintPending', 'Deactivate this agent — its record and balance stay put')"
                    :data-testid="`ckd-stop-deactivate`" @click="deactivate(m)">
              <Icon name="mdi:power-plug-off-outline" />
              {{ namesReady
                 ? tp('cockpit.stop.deactivateNamed', 'Deactivate {name}', { name: actionLabel(m.agent_did) })
                 : t('cockpit.stop.deactivatePending', 'Deactivate this agent') }}
            </button>
          </div>
        </li>
      </ul>
      <p v-if="msg" class="ckd-stop-msg" data-testid="ckd-stop-msg">{{ msg }}</p>
      <p class="ckd-stop-scope-note" data-testid="ckd-stop-scope-note">
        {{ tp('cockpit.stop.scopeNote',
              'Your own mandates ({n} live). Suspending an agent across the registry, its TEG and the '
              + 'federation is an operator action and is not this button.', { n: live.length }) }}
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ckd-stop { display: flex; flex-direction: column; gap: .4rem; }
.ckd-stop-acting { margin: .3rem 0 .45rem; padding: .28rem .4rem; border-radius: 3px;
  background: var(--nc-bg-elevated, #161b22); border: 1px solid var(--nc-border, #30363d);
  display: flex; flex-wrap: wrap; align-items: baseline; gap: .3rem; line-height: 1.35; }
.ckd-stop-actinglbl { font-size: .55rem; letter-spacing: .06em; color: var(--nc-text-muted, #6e7681); }
.ckd-stop-actingname { font-size: .74rem; font-weight: 600; color: var(--nc-primary, #58a6ff);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
.ckd-stop-actingstate { font-size: .62rem; color: var(--nc-text-muted, #6e7681); flex-basis: 100%; }
.ckd-stop-actingstate.is-has { color: var(--nc-success, #3fb950); }
.ckd-stop-row.is-acting { border-left: 2px solid var(--nc-primary, #58a6ff); padding-left: .35rem; }
.ckd-stop-actingtag { font-size: .58rem; text-transform: uppercase; letter-spacing: .04em;
  color: var(--nc-primary, #58a6ff); border: 1px solid var(--nc-primary, #58a6ff);
  border-radius: 3px; padding: 0 .22rem; align-self: flex-start; }
.ckd-stop-lede { margin: 0 0 .1rem; font-size: .63rem; line-height: 1.35; color: var(--nc-text-muted, #6e7681); }
.ckd-stop-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .35rem; }
/* §COCKPITPOLISH P1 — the row STACKS. It used to be a single flex line with the identity
   on `flex:1; min-width:0` and ~250px of buttons beside it, so in a one-column slot the
   identity was squeezed until the DID ellipsised to `di…`. A layout where the label loses
   every fight with the controls is a layout that hides what the controls act on. Identity
   gets a full line of its own; actions get the next one. */
.ckd-stop-row {
  display: flex; flex-direction: column; gap: .35rem; align-items: stretch;
  border: 1px solid var(--nc-border-subtle, rgba(255,255,255,.08)); border-radius: 7px; padding: .4rem .45rem;
}
.ckd-stop-who { display: flex; flex-direction: column; min-width: 0; gap: .05rem; }
.ckd-stop-agent.is-pending { color: var(--nc-text-muted, #6e7681); font-style: italic; }
.ckd-stop-agent { font-size: .74rem; font-weight: 600;
  color: var(--nc-text-primary, #e6edf3); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ckd-stop-did { font-family: var(--nc-font-mono, ui-monospace, monospace); font-size: .6rem;
  color: var(--nc-text-muted, #6e7681); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* ⚠ this had NO overflow rule at all, so a long scope list rendered at natural width and
   ran underneath the buttons — the stray `· teg.transfer` visible in his screenshot. */
.ckd-stop-scope { font-size: .63rem; color: var(--nc-text-muted, #6e7681);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ckd-stop-acts { display: flex; gap: .3rem; flex-wrap: wrap; }
.ckd-stop-ceil { flex: 1 1 100%; display: flex; align-items: center; gap: .3rem; font-size: .64rem;
  color: var(--nc-warning, #d29922); }
.ckd-stop-ceil .is-decayed { color: var(--nc-text-muted, #6e7681); text-decoration: line-through; }
.ckd-stop-ceil em { font-style: normal; opacity: .8; }
.ckd-stop-btn {
  display: inline-flex; align-items: center; gap: .2rem; cursor: pointer; font-size: .68rem;
  padding: .22rem .45rem; border-radius: 5px; background: transparent;
  border: 1px solid rgba(210,153,34,.45); color: var(--nc-warning, #d29922);
  max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ckd-stop-btn--hard { border-color: rgba(248,81,73,.45); color: var(--nc-danger, #f85149); }
.ckd-stop-btn:disabled { opacity: .45; cursor: not-allowed; }
.ckd-stop-msg { margin: .2rem 0 0; font-size: .68rem; color: var(--nc-text-secondary, #c9d1d9); }
.ckd-stop-scope-note { margin: .2rem 0 0; font-size: .62rem; color: var(--nc-text-muted, #6e7681); }
</style>
