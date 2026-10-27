<script setup lang="ts">
/**
 * §COCKPITUP U3 (2026-09-01) — QUICK ACTIONS ON THE DESK.
 *
 * HIS ASK: *"maybe also quick action modul/pane like the bridge has with quick buy
 * exchange/sendmoney."*
 *
 * 🔴 THIS IS A MOUNT, NOT A SECOND QUICK-ACTIONS COMPONENT. `BridgeQuickActions` (530
 * lines) already carries SEND / FUND / STAKE / CLAIM on the EXISTING rails — `tegApi
 * .smartSend`, `fundAgentLocal`, the staking store — and the EXISTING dialog
 * (`AmountActionModal`, which owns the mis-target guard, the amount validator and the
 * typed confirmation above a threshold). Re-implementing any of that here would be a
 * parallel money flow, which doctrine rule 14 forbids outright, and a second copy of the
 * predicate that decides whether an action is allowed — the shape §ORGLEAK had.
 *
 * It is already mounted twice (MissionControl, PocketHome) and its `targetHint` prop
 * exists precisely BECAUSE "how a target is acquired is a fact about the HOST surface".
 * The desk is simply a third host. Precedent: §COCKPITA's §MINELEDGER, where the bridge's
 * ledger became a cockpit pane as a mount rather than new machinery.
 *
 * 🔴 THIS PANE FOLLOWS THE HEADER AGENT SWITCHER, AND IT SAYS SO. `PaneHoldings` is the
 * only other pane that does, and it states it on screen for a measured reason: his report
 * after §COCKPITSHOW was *"(stop) has an agent selected and i have not selected an agent"*.
 * On a desk where some panes follow the switcher and most do not, a pane that moves MONEY
 * must name whose money it is about to move.
 *
 * ⚠ WITH NO AGENT SELECTED, EVERY TARGETED ACTION IS DISABLED AND SAYS WHY — that is
 * `BridgeQuickActions`' own law 2, and it is why nothing here needs to guess. Passing a
 * null `targetDid` is the supported way to express "no subject".
 *
 * ⚠ CURRENCY COMES FROM THE ACTING AGENT'S HOME, NEVER THE PAGE (§FOREIGNACT). The api
 * client routes agent-tier calls to `activeAgentRegistryUrl` and `useActingContext` reads
 * that same field, so the label and the routing cannot disagree. An empty unit while the
 * foreign card loads is honest; the wrong unit is what locked 1337 AVT under a BVT label.
 *
 * 🔴 BUY / POST WORK / BID / VOTE ARE DOORS, NEVER ACTIONS HERE. R15.5's rule, kept: the
 * component emits `open-lane` and this host answers with navigation. An order placed from
 * a dashboard tile is a trade nobody reviewed.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import PaneShell from './PaneShell.vue'
import BridgeQuickActions from '@/components/bridge/BridgeQuickActions.vue'
import RecordLink from './RecordLink.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { useAgentStore } from '@/stores/agents'
import { useActingContext } from '@/composables/useActingContext'
import { PANES } from './paneRegistry'

const { t } = useI18n()
const auth = useAuthStore() as any
const router = useRouter()
const { actingCurrencyLabel } = useActingContext()
const def = PANES.quickactions

const uiStore = useUIStore()
const agentStore = useAgentStore()
/* §PANEDOORS (2026-09-02) — MEASURED on a fresh account: this pane said "Pick an agent in the
 * header switcher" to a person who owned none to pick. "0 agents on this account" is claimed
 * only after OUR OWN read of the store finished — the store has no loaded flag, and an
 * unloaded list looks exactly like an empty one. The quick modal bumps `agentCreatedTick`;
 * the door goes away on the re-read, never on the modal's word. */
const checked = ref(false)
async function checkAgents() {
  if (agentStore.agents.length) { checked.value = true; return }
  try { await agentStore.fetchMyAgents() } catch { /* the store keeps its own error */ } finally { checked.value = true }
}
onMounted(() => { void checkAgents() })
watch(() => uiStore.agentCreatedTick, () => { checked.value = false; void checkAgents() })
// §FESUITE (V0577): a failed read leaves the store at [] and 0 with myAgentsFailed set; that said "You have no agents on
// this account yet" with "Create your wallet agent". "0 agents" is claimed only after a read that ANSWERED.
const noAgents = computed(() => checked.value && !agentStore.loading && !agentStore.myAgentsFailed
  && agentStore.totalCount === 0 && agentStore.agents.length === 0)
const agentsUnread = computed(() => checked.value && !agentStore.loading && agentStore.myAgentsFailed
  && agentStore.agents.length === 0)
function retryAgents() { checked.value = false; return checkAgents() }
const actingDid = computed<string | null>(() => auth.activeAgent?.did || null)
const actingName = computed<string | null>(() => auth.activeAgent?.name || null)

/** The viewer's own agents — `/agents/{did}/lineage` is OWNER-gated, so asking it about
 *  somebody else's agent is a guaranteed 404 in the console (measured §BRIDGE R9). */
const ownedDids = computed<string[]>(() => {
  const list = auth.availableAgents || []
  return list.map((a: any) => a?.did).filter((d: any) => typeof d === 'string' && d.startsWith('did:'))
})

function openLane(lane: 'senate' | 'guild') {
  // Named routes only — a hand-rolled path is a link nothing checks (§COCKPITUP U2).
  router.push({ name: lane }).catch(() => {})
}
</script>

<template>
  <PaneShell :title="t(def.titleKey, def.titleFallback)" :icon="def.icon"
             :refresh-mode="def.refreshMode" :loading="false" :error="''" :empty="false">
    <div class="ckd-qa" data-testid="ckd-quickactions">
      <!-- Which agent this acts as, always — see the header doctrine. -->
      <p class="ckd-qa-who" data-testid="ckd-qa-who">
        <template v-if="actingDid">
          {{ t('cockpit.qa.acting', 'Acts as the agent in the header switcher:') }}
          <b>{{ actingName || actingDid }}</b>
        </template>
        <template v-else-if="noAgents">
          {{ t('cockpit.qa.noneYet', 'You have no agents on this account yet — the actions below need one.') }}
          <button type="button" class="ckd-qa-create" data-testid="ckd-qa-create" @click="uiStore.openQuickAgentModal()">
            {{ t('cockpit.door.createFirst', 'Create your wallet agent') }}
          </button>
        </template>
        <template v-else>
          {{ t('cockpit.qa.none', 'No agent is selected in the header switcher, so the actions below that need one are disabled.') }}
        </template>
      </p>
      <ReadFailedNotice v-if="!actingDid && agentsUnread" dense :retry="retryAgents" data-testid="ckd-qa-agents-unread"
        :text="t('cockpit.qa.agentsUnread', 'Your agents could not be read just now, so whether this account has one is not known here.')" />

      <BridgeQuickActions
        :target-did="actingDid"
        :target-name="actingName"
        :owned-dids="ownedDids"
        :currency="actingCurrencyLabel"
        :target-hint="noAgents ? t('cockpit.qa.hintNone', 'Create an agent first.') : t('cockpit.qa.hint', 'Pick an agent in the header switcher at the top right.')"
        @open-lane="openLane"
      />

      <!-- BUY is a door, deliberately: the venue is where an order is reviewed. -->
      <p class="ckd-qa-doors">
        <RecordLink kind="exchange" :label="t('cockpit.door.buy', 'Buy on the market')" />
        <RecordLink kind="guild" :label="t('cockpit.door.guild', 'Guild board')" />
        <RecordLink kind="senate" :label="t('cockpit.door.senate', 'Senate')" />
      </p>
    </div>
  </PaneShell>
</template>

<style scoped>
.ckd-qa { display: flex; flex-direction: column; gap: .4rem; }
.ckd-qa-who { margin: 0; font-size: .66rem; color: var(--nc-text-muted, #6e7681); }
.ckd-qa-who b { color: var(--nc-text-secondary, #c9d1d9); font-weight: 600; }
.ckd-qa-doors { margin: .1rem 0 0; display: flex; gap: .7rem; font-size: .66rem; }
.ckd-qa-create { margin-left: .5rem; font-size: .64rem; letter-spacing: .04em; padding: .2rem .55rem; border-radius: 6px; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb, 0,229,255), .5); background: transparent; color: var(--nc-primary, #00e5ff); }
.ckd-qa-create:hover { background: rgba(var(--nc-primary-rgb, 0,229,255), .08); }
</style>
