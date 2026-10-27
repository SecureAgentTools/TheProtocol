<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
/**
 * BridgeAttention.vue — §BRIDGE R14.3, "WHAT NEEDS YOU".
 *
 * The gap this closes: the bridge tells you what the NETWORK is doing, in great
 * detail, and never once tells you what is waiting on YOUR answer. A command
 * deck that cannot say "this one needs a decision from you" is a telemetry
 * screen with good lighting.
 *
 * ── THE DISTINCTION THIS PANEL IS BUILT ON ──────────────────────────────────
 * ATTENTION is not WORK (R12). WORK answers *what is this agent doing*.
 * ATTENTION answers *what is blocked on a human decision right now*. That
 * difference decides the contents, and it excludes things people expect to see:
 *
 *   · YOUR pending funding request is NOT here. It is waiting on an ADMIN, not
 *     on you. Listing it would turn this panel into a to-do list of other
 *     people's work, which is the failure mode that makes such panels ignored.
 *   · The ADMIN approval queue IS here, for admins only, because for them those
 *     same requests genuinely are blocked on their decision.
 *
 * ── EVERY SOURCE ALREADY EXISTS ─────────────────────────────────────────────
 *   notifications   the Pinia store DashboardLayout already fills on mount —
 *                   zero new requests for the commonest source.
 *   contracts       `contractsV2Api.mine()`, agent-JWT, so it is scoped to the
 *                   acting agent BY CONSTRUCTION rather than by a filter.
 *   disputes        `disputesApi.getAgentDisputes(did)`, same rail R12 uses.
 *   funding         `fundingAdminApi.getPending()`, admin only.
 * No new endpoint, no new money path, nothing this app could not already read.
 *
 * ── THE HONESTY RULE THAT SHAPES THE EMPTY STATE ────────────────────────────
 * An empty panel MUST distinguish "nothing needs you" from "I could not look".
 * Most rows here need an acting agent; without one those rails cannot be read
 * at all, and rendering a calm "all clear" would be a claim we have not earned.
 * So the panel states its own blind spots, always, and the badge stays absent
 * rather than showing 0 while it still knows nothing.
 */
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useAlive } from '@/composables/useAlive'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { usePrivacy } from '@/composables/usePrivacy'
import { useAuthStore } from '@/stores/auth'
import { useNotificationStore } from '@/stores/notifications'
import { contractsV2Api } from '@/services/api/contractsV2'
import { offersAwaiting, milestonesAwaiting, openDisputeCount,
         votesAwaiting, guildAwaiting, offersExpiring, claimableRewards,
         attestationsExpiring, humanLeft,
         foreignRegistryGroups, foreignNeedsCount } from '@/services/bridge/attention'
import { agentCredentialsStore } from '@/services/agentCredentialsStore'
import { useSessionHub } from '@/stores/sessions'
import { currentFrameManifest } from '@/composables/useFrameManifest'
import { entryByOrigin } from '@/services/frameManifest'
import { governanceApi } from '@/services/api/governance'
import { guildApi } from '@/services/api/guild'
import { stakingApi } from '@/services/api/staking'
import { attestationsApi } from '@/services/api/attestations'
import { disputesApi } from '@/services/api/disputes'
import { fundingAdminService } from '@/services/api/fundingAdmin'
import { hasAdminFlag } from '@/composables/usePermissions'

const { t } = useI18n()
const sessionHub = useSessionHub()
const { money } = usePrivacy()
const router = useRouter()
const authStore = useAuthStore()
const notifications = useNotificationStore()

const props = defineProps<{
  show: boolean
  /**
   * §POCKETBRIDGE #PK12 — on the bridge the unread row is deliberately static
   * (the bell is a Teleport panel with no open-by-event seam, and a clickable
   * row that goes nowhere is worse than a number). Pocket HAS a door — its
   * alerts sheet — so a host that can open one says so and gets the click.
   */
  unreadDoor?: boolean
}>()

// §POCKETBRIDGE5 W-D — dialog semantics were declared; the trap makes them true.
const trapEl = ref<HTMLElement | null>(null)
useFocusTrap(trapEl, { activeWhen: computed(() => props.show) })

/* Read the acting agent from the store, exactly as BridgeWorkView does. One
 * source of truth for "who am I acting as", not a prop chain that can disagree
 * with the selector. */
const actingDid = computed<string | null>(() => authStore.activeAgent?.did || null)
const actingName = computed<string>(() =>
  authStore.activeAgent?.name || (actingDid.value ? `${actingDid.value.slice(0, 22)}\u2026` : ''))
// the funding queue is the TREASURY admin's (require_admin_flag("admin_treasury")): asked for any admin flag, a support,
// enforcement, federation or platform admin was refused it on every panel, and the panel then said the funding queue
// could not be read (§FESUITE lifecycle 90)
const canTreasury = computed<boolean>(() => hasAdminFlag(authStore.user, 'treasury'))

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'count', n: number | null): void
  (e: 'open-work', tab?: 'contracts' | 'guild' | 'disputes'): void
  /** Open a docked terminal lane. R3: act on the rail that exists. */
  (e: 'open-lane', lane: string, ref?: string): void
  /** #PK12 — only ever fired when the host declared `unreadDoor`. */
  (e: 'open-unread'): void
}>()

const loading = ref(false)
/** null until a real answer arrives: a 0 we have not earned is a lie. */
/* The RAW rail response, whatever shape it is. All shape handling lives in
 * `services/bridge/attention.ts` — see the note there on why a throwing
 * computed in this panel destroys the entire bridge. */
const contracts = ref<any>(null)
const disputesOpen = ref<number | null>(null)
/* R15.1 — the rest of the command queue. Each is the RAW response; every shape
 * decision lives in the pure module, which is where it can be tested. */
const proposals = ref<any>(null)
const myVotes = ref<any>(null)
const guildMine = ref<any>(null)
const stakeStats = ref<any>(null)
const attests = ref<any>(null)
const nowMs = ref(Date.now())
/* R15.4 — one row per OTHER registry you hold an agent on. Loaded separately
 * and after the local queue: this fans out real requests and must never delay
 * the badge for the registry you are actually looking at. */
const foreign = ref<Array<{ host: string; count: number }>>([])
const foreignFailed = ref<string[]>([])
const foreignDone = ref(false)
/* The panel loads on mount, on an agent change AND on open, which is right for
 * the local queue (cheap, same-origin) and wrong for this one: measured on the
 * canary, opening the panel fired THREE token mints and two full fetch rounds
 * at op-berlin. A fan-out repeats its cost on every trigger, so it runs once
 * per (agent x registry set) and only again when that actually changes. */
let foreignRanFor: string | null = null
let foreignBusy = false
const fundingPending = ref<number | null>(null)
const failed = ref<string[]>([])

/* Both derivations are pure and cannot throw on an unexpected shape. The first
 * version did `(contracts.value || []).filter(...)`, which guards null but NOT
 * type, and the rail returns `{items:[...]}` — it threw in a computed and the
 * error boundary blanked the entire bridge. */
const offersToMe = computed(() => offersAwaiting(contracts.value, actingDid.value))
const milestonesToRelease = computed(() => milestonesAwaiting(contracts.value, actingDid.value))
const openVotes = computed(() => votesAwaiting(proposals.value, myVotes.value, nowMs.value))
const guild = computed(() => guildAwaiting(guildMine.value, actingDid.value))
const lapsingOffers = computed(() => offersExpiring(contracts.value, actingDid.value, nowMs.value))
const claimable = computed(() => claimableRewards(stakeStats.value))
const lapsingAttests = computed(() => attestationsExpiring(attests.value, nowMs.value))

const unread = computed(() => notifications.unreadCount || 0)

/** Absent (null) until at least one source has answered. */
const total = computed<number | null>(() => {
  const items = Array.isArray(notifications.items) ? notifications.items : []
  if (contracts.value === null && disputesOpen.value === null && !items.length && unread.value === 0) {
    // §FESUITE (V0578): with the reads that would count something FAILED, nothing answered: not 0 (Pocket's shell cleared
    // the installed app's icon badge on that 0, "nothing needs you" said by the phone over reads that never answered)
    return loading.value || failed.value.length ? null : 0
  }
  const g = guild.value
  const foreignTotal = foreign.value.reduce((a, f) => a + f.count, 0)
  return foreignTotal + unread.value + offersToMe.value.length + milestonesToRelease.value.length
    + (disputesOpen.value || 0) + (fundingPending.value || 0)
    + openVotes.value.length + g.bidsToAward.length + g.awardedToYou.length + g.toVerify.length
    + lapsingOffers.value.length + (claimable.value > 0 ? 1 : 0) + lapsingAttests.value.length
})

watch(total, (n) => emit('count', n), { immediate: true })

/* §POCKETBRIDGE2 W1.10 — refreshed on every load, NOT a computed: the vault
 * state is a plain object and a computed over it evaluates once and caches
 * forever (the §BRIDGE R11 non-reactive-computed trap). */
const vaultLocked = ref(false)

async function load(): Promise<void> {
  try { vaultLocked.value = agentCredentialsStore.isSealedLocked() } catch { vaultLocked.value = false }
  loading.value = true
  failed.value = []
  const jobs: Promise<void>[] = []

  if (actingDid.value) {
    jobs.push((async () => {
      try { contracts.value = await contractsV2Api.mine({}) }
      catch { contracts.value = null; failed.value.push('contracts') }
    })())
    jobs.push((async () => {
      try {
        disputesOpen.value = openDisputeCount(await disputesApi.getAgentDisputes(actingDid.value as string))
      } catch { disputesOpen.value = null; failed.value.push('disputes') }
    })())
    // R15.1 — each source fails ALONE. One dead rail must not empty the queue,
    // and a source that could not be read is named rather than shown as zero.
    jobs.push((async () => {
      try { guildMine.value = await guildApi.mine() }
      catch { guildMine.value = null; failed.value.push('guild') }
    })())
    jobs.push((async () => {
      try { stakeStats.value = await stakingApi.getMyStakingStats() }
      catch { stakeStats.value = null; failed.value.push('locks') }
    })())
    jobs.push((async () => {
      try { attests.value = await attestationsApi.getAttestationsByDid(actingDid.value as string, { limit: 100 } as any) }
      catch { attests.value = null; failed.value.push('attestations') }
    })())
    jobs.push((async () => {
      try { myVotes.value = await governanceApi.getMyVotes({ limit: 100 }) }
      catch { myVotes.value = null; failed.value.push('your votes') }
    })())
  } else {
    contracts.value = null; disputesOpen.value = null; guildMine.value = null
    stakeStats.value = null; attests.value = null; myVotes.value = null
  }

  // Proposals are PUBLIC (T1), so the vote queue is readable even before you
  // pick an agent — we just cannot say whether YOU voted until you have one.
  jobs.push((async () => {
    try {
      const r: any = await governanceApi.getProposals({ limit: 50 } as any)
      proposals.value = Array.isArray(r) ? r : (r?.proposals ?? r?.items ?? r)
    } catch { proposals.value = null; failed.value.push('proposals') }
  })())

  if (canTreasury.value) {
    jobs.push((async () => {
      try {
        const p = await fundingAdminService.listPending()
        fundingPending.value = Array.isArray(p) ? p.length : 0
      } catch { fundingPending.value = null; failed.value.push('funding') }
    })())
  } else {
    fundingPending.value = null
  }

  await Promise.all(jobs)
  // §FESUITE (2026-10-04): the panel may be gone by now (the person left the page while these reads ran); nothing more
  // is asked for a panel nobody sees
  if (!alive()) return
  nowMs.value = Date.now()
  loading.value = false
  // After the local answer is on screen, never before it.
  void loadForeign()
}

// §FESUITE (2026-10-04, the leave sweep on V0572, fes-20261004T171222Z-9caf): the deferred first load was a timer nothing
// cleared, so leaving Pocket (or the bridge) within 1.2 s ran six reads from a panel that was already gone, and a failed one
// logged "Failed to fetch staking stats" on the next page. The timer is cleared on unmount and checks it is still wanted.
const alive = useAlive()
let firstLoad: ReturnType<typeof setTimeout> | null = null
onMounted(() => {
  // Deferred: the badge is not worth a millisecond of first paint, and R2b was
  // a lesson about a panel that shifted the layout while it waited on a slow
  // endpoint. It arrives when it arrives.
  firstLoad = setTimeout(() => { firstLoad = null; if (alive()) void load() }, 1200)
})
onUnmounted(() => { if (firstLoad) clearTimeout(firstLoad); firstLoad = null })
watch(() => [actingDid.value, canTreasury.value], () => { load() })
watch(() => props.show, (open) => { if (open) load() })

function goContract(): void {
  emit('close')
  emit('open-work', 'contracts')   // R3: dock on the rail that already exists, never a new copy.
}
// §POCKETBRIDGE5 A' — a dispute row lands ON the disputes lane, not merely at
// the modal's front door.
function goDisputes(): void { emit('close'); emit('open-work', 'disputes') }
function goLane(lane: string, ref?: string): void { emit('close'); emit('open-lane', lane, ref) }
/* VERIFIED, not guessed: the funding approval queue is `FundingRequestsPanel`
 * inside AdminDevelopers.vue, route name `admin-developers`. There is no
 * `/admin/funding` route in this build, and pushing to one would be a door
 * onto a wall — the §R5 defect where DISCOVERY rows linked to `/agent/{did}`,
 * a route that does not exist. */
function goFunding(): void { emit('close'); router.push({ name: 'admin-developers' }).catch(() => { /* guarded by the admin flag */ }) }

/*
 * The fan-out. Plain `fetch`, deliberately: the axios client rewrites baseURL
 * from the ACTIVE agent's registry (the R11 #12 seam), which is the wrong
 * address for every registry except the one that agent belongs to.
 *
 * The agent token endpoint is OAuth2 FORM with `username` = client_id — not
 * JSON, and not `did`. Verified live when the 608 sim credentials were minted.
 */
async function loadForeign(force = false): Promise<void> {
  if (foreignBusy) return
  let groups: any[] = []
  try {
    groups = foreignRegistryGroups(agentCredentialsStore.getAllCredentials(), window.location.origin)
  } catch { groups = [] }
  // Every foreign source is agent-scoped, so without an acting agent the answer
  // is zero by construction — and asking N registries for a zero we already
  // know is how the first cut fired three token mints on one panel open.
  if (!actingDid.value) { foreign.value = []; foreignDone.value = true; foreignBusy = false; return }
  const key = `${actingDid.value}|${groups.map((g: any) => g.origin).join(',')}`
  if (!force && key === foreignRanFor) return          // same question, same answer
  foreignRanFor = key
  foreignBusy = true
  foreignDone.value = false
  foreignFailed.value = []
  if (!groups.length) { foreign.value = []; foreignDone.value = true; foreignBusy = false; return }

  const results: Array<{ host: string; count: number }> = []
  await Promise.all(groups.map(async (g: any) => {
    const agent = g.agents[0]
    try {
      // §FEFRAME W3: through the session hub, keyed by the registry's manifest key (or its origin): a token still
      // fresh is reused instead of re-minted on every open, your developer session there signs the agent in with no
      // secret, and a refused secret is marked rejected instead of retried on the next open
      const m = currentFrameManifest()
      const hubKey = (m && entryByOrigin(m, g.origin)?.key) || g.origin
      const tok = await sessionHub.ensureAgentToken(hubKey, String(agent.did || ''))
      if (!tok) throw new Error(sessionHub.lastAgentError[String(agent.did || '')] || 'no token')
      const h = { Authorization: `Bearer ${tok}` }
      // §FESUITE (V0577): a read that got no answer (none at all, a 5xx, or a page where JSON was asked) is a failure,
      // named below like a failed sign-in. It was null, so that registry counted 0 needs and was never named. Only a
      // refusal (a 4xx: the rail is not served there, or not for this agent) is an answer of none.
      const read = (url: string) => fetch(url, { headers: h }).then(r => {
        if (r.ok) return r.json()
        if (r.status >= 500) throw new Error(`HTTP ${r.status}`)
        return null
      })
      const [cr, gr] = await Promise.all([
        read(`${g.origin}/api/v1/contracts/v2/mine`),
        read(`${g.origin}/api/v1/guild/mine`),
      ])
      const n = foreignNeedsCount(cr, gr, String(agent.did || ''))
      if (n > 0) results.push({ host: g.host, count: n })
    } catch {
      // Named, never silently zero: "nothing waiting there" and "I could not
      // ask" are different answers and the panel must not conflate them.
      foreignFailed.value.push(g.host)
    }
  }))
  foreign.value = results.sort((a, b) => b.count - a.count)
  foreignDone.value = true
  foreignBusy = false
}

defineExpose({
  reload: load,
  /** R15.4 — provable state: ran? for whom? what did it reach or fail to reach? */
  foreignState: () => ({ done: foreignDone.value, ranFor: foreignRanFor,
                         rows: foreign.value.slice(), failed: foreignFailed.value.slice() }),
})
</script>

<template>
  <div v-if="show" class="bat-wrap" data-testid="bridge-attention">
    <div class="bat-scrim" @click="emit('close')"></div>
    <section ref="trapEl" class="bat" role="dialog" aria-modal="true" :aria-label="t('bridge.attention.title', 'Needs you')">
      <header class="bat-hdr">
        <span class="bat-title">{{ t('bridge.attention.title', 'NEEDS YOU') }}</span>
        <span v-if="actingName" class="bat-actor">{{ t('bridge.attention.as', 'as') }}&#32;{{ actingName }}</span>
        <button type="button" class="bat-x" :title="t('common.close', 'Close')" @click="emit('close')">&times;</button>
      </header>

      <div class="bat-body">
        <p v-if="loading" class="bat-note">{{ t('bridge.attention.loading', 'Checking what is waiting on you...') }}</p>

        <!-- UNREAD -->
        <!-- On the bridge: deliberately NOT a button. Notifications have no
             route in this build — the bell is a Teleport panel the header
             owns, with no open-by-event seam, and a row that looks clickable
             and goes nowhere is worse than a row that tells you the number.
             #PK12: a host that DOES have a door (Pocket's alerts sheet)
             declares `unreadDoor` and the row becomes one. -->
        <button v-if="unread > 0 && props.unreadDoor" type="button" class="bat-row bat-act" data-testid="bat-unread"
                @click="emit('close'); emit('open-unread')">
          <Icon name="mdi:bell-ring" :size="14" />
          <span class="bat-n">{{ unread }}</span>
          <span class="bat-txt">{{ t('bridge.attention.unreadDoor', 'unread notifications') }}</span>
        </button>
        <div v-else-if="unread > 0" class="bat-row bat-static" data-testid="bat-unread">
          <Icon name="mdi:bell-ring" :size="14" />
          <span class="bat-n">{{ unread }}</span>
          <span class="bat-txt">{{ t('bridge.attention.unread', 'unread notifications — open the bell in the header') }}</span>
        </div>

        <!-- OFFERS TO ME -->
        <button v-for="c in offersToMe" :key="`o-${c.id}`" type="button" class="bat-row bat-act" data-testid="bat-offer" @click="goContract()">
          <Icon name="mdi:hand-coin-outline" :size="14" />
          <span class="bat-txt">{{ t('bridge.attention.offer', 'Contract offered to you') }}: {{ c.title }}</span>
          <span class="bat-amt">{{ money(c.amount) }}&#32;{{ c.currency }}</span>
        </button>

        <!-- WORK SUBMITTED TO ME -->
        <button v-for="m in milestonesToRelease" :key="`m-${m.contractId}-${m.seq}`" type="button" class="bat-row bat-act" data-testid="bat-milestone" @click="goContract()">
          <Icon name="mdi:clipboard-check-multiple-outline" :size="14" />
          <span class="bat-txt">{{ t('bridge.attention.milestone', 'Work submitted, awaiting your release') }}: {{ m.title }}</span>
          <span class="bat-amt">{{ money(m.amount) }}&#32;{{ m.currency }}</span>
        </button>

        <!-- OPEN VOTES — a real deadline, and the decision is yours. -->
        <button v-for="v in openVotes" :key="`v-${v.id}`" type="button" class="bat-row bat-act" data-testid="bat-vote" @click="goLane('senate')">
          <Icon name="mdi:gavel" :size="14" />
          <span class="bat-txt">{{ t('bridge.attention.vote', 'Open vote you have not cast') }}: {{ v.title }}</span>
          <span class="bat-amt">{{ humanLeft(v.closesInMs) || t('bridge.attention.noDeadline', 'no deadline') }}</span>
        </button>

        <!-- GUILD: bids you must award -->
        <button v-for="g in guild.bidsToAward" :key="`gb-${g.id}`" type="button" class="bat-row bat-act" data-testid="bat-guild-award" @click="goLane('guild', g.id)">
          <Icon name="mdi:hammer-wrench" :size="14" />
          <span class="bat-n">{{ g.bids }}</span>
          <span class="bat-txt">{{ t('bridge.attention.bids', 'bids on your posted work, awaiting your award') }}: {{ g.title }}</span>
        </button>

        <!-- GUILD: work awarded to you -->
        <button v-for="g in guild.awardedToYou" :key="`ga-${g.id}`" type="button" class="bat-row bat-act" data-testid="bat-guild-deliver" @click="goLane('guild', g.id)">
          <Icon name="mdi:briefcase" :size="14" />
          <span class="bat-txt">{{ t('bridge.attention.awarded', 'Work awarded to you, not yet delivered') }}: {{ g.title }}</span>
          <span class="bat-amt">{{ money(g.bounty) }}&#32;{{ g.currency }}</span>
        </button>

        <!-- GUILD: work submitted to you -->
        <button v-for="g in guild.toVerify" :key="`gv-${g.id}`" type="button" class="bat-row bat-act" data-testid="bat-guild-verify" @click="goLane('guild', g.id)">
          <Icon name="mdi:check-decagram" :size="14" />
          <span class="bat-txt">{{ t('bridge.attention.verify', 'Work delivered to you, awaiting your verification') }}: {{ g.title }}</span>
          <span class="bat-amt">{{ money(g.bounty) }}&#32;{{ g.currency }}</span>
        </button>

        <!-- OFFERS YOU SENT that lapse if ignored -->
        <button v-for="o in lapsingOffers" :key="`x-${o.id}`" type="button" class="bat-row bat-act" data-testid="bat-offer-lapsing" @click="goContract()">
          <Icon name="mdi:timer-sand" :size="14" />
          <span class="bat-txt">{{ t('bridge.attention.lapsing', 'Your offer lapses soon') }}: {{ o.title }}</span>
          <span class="bat-amt">{{ humanLeft(o.expiresInMs) }}</span>
        </button>

        <!-- CLAIMABLE — a statement with a door, not a second CLAIM button:
             he removed CLAIM as a quick action because the lock lane owns it. -->
        <button v-if="claimable > 0" type="button" class="bat-row" data-testid="bat-claimable" @click="goLane('staking')">
          <Icon name="mdi:gift-outline" :size="14" />
          <span class="bat-txt">{{ t('bridge.attention.claimable', 'payouts on locked units are claimable') }}</span>
          <span class="bat-amt">{{ money(claimable.toLocaleString(appLocale())) }}</span>
        </button>

        <!-- ATTESTATIONS lapsing -->
        <div v-if="lapsingAttests.length" class="bat-row bat-static" data-testid="bat-attest">
          <Icon name="mdi:certificate" :size="14" />
          <span class="bat-n">{{ lapsingAttests.length }}</span>
          <span class="bat-txt">{{ t('bridge.attention.attest', 'attestations lapse within two weeks') }}</span>
        </div>

        <!-- DISPUTES -->
        <button v-if="(disputesOpen || 0) > 0" type="button" class="bat-row bat-act" data-testid="bat-dispute" @click="goDisputes">
          <Icon name="mdi:gavel" :size="14" />
          <span class="bat-n">{{ disputesOpen }}</span>
          <span class="bat-txt">{{ t('bridge.attention.disputes', 'open disputes involving this agent') }}</span>
        </button>

        <!-- ADMIN APPROVAL QUEUE -->
        <button v-if="(fundingPending || 0) > 0" type="button" class="bat-row bat-act" data-testid="bat-funding" @click="goFunding">
          <Icon name="mdi:cash-multiple" :size="14" />
          <span class="bat-n">{{ fundingPending }}</span>
          <span class="bat-txt">{{ t('bridge.attention.funding', 'funding requests awaiting your approval') }}</span>
        </button>

        <!-- OTHER REGISTRIES you hold an agent on -->
        <div v-for="f in foreign" :key="`f-${f.host}`" class="bat-row bat-static bat-act" data-testid="bat-foreign">
          <Icon name="mdi:earth" :size="14" />
          <span class="bat-n">{{ f.count }}</span>
          <span class="bat-txt">{{ t('bridge.attention.elsewhere', 'waiting on you at') }}&#32;{{ f.host }}</span>
        </div>

        <!-- NOTHING, and WHY we can say so -->
        <p v-if="!loading && total === 0" class="bat-clear" data-testid="bat-clear">
          <Icon name="mdi:check-circle-outline" :size="14" />
          <!-- §FESUITE (V0577): not absolute while the lines below name reads that failed -->
          {{ failed.length || foreignFailed.length
            ? t('bridge.attention.clearPartial', 'Nothing is waiting on you in what could be read.')
            : t('bridge.attention.clear', 'Nothing is waiting on you.') }}
        </p>

        <!-- THE BLIND SPOTS. Stated ALWAYS, because an empty panel that cannot
             see is indistinguishable from an empty panel that looked. -->
        <p v-if="vaultLocked" class="bat-blind" data-testid="bat-blind-vault">
          {{ t('bridge.attention.vaultLocked', 'Your credential vault is LOCKED — agent-side checks (contracts, disputes) and every cross-registry check are not running. Unlock Pocket to include them.') }}
        </p>
        <p v-else-if="!actingDid" class="bat-blind" data-testid="bat-blind-agent">
          {{ t('bridge.attention.noAgent', 'Contracts and disputes are not checked: they are read with an agent credential and you are not acting as an agent. Pick one in the selector to include them.') }}
        </p>
        <p v-if="foreignFailed.length" class="bat-blind" data-testid="bat-blind-foreign">
          {{ t('bridge.attention.foreignFailed', 'Could not reach:') }}&#32;{{ foreignFailed.join(', ') }}
        </p>
        <p v-if="failed.length" class="bat-blind" data-testid="bat-blind-failed">
          {{ t('bridge.attention.failed', 'Could not read:') }}&#32;{{ failed.join(', ') }}
        </p>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* Docks in the STAGE COLUMN, never over the rails: his standing instruction is
   that a modal must not block the live ledger. Same vars WorkView uses. */
.bat-wrap { position: fixed; top: 0; bottom: 0; z-index: 12000;
  left: var(--brg-stage-l, 0px); right: var(--brg-stage-r, 0px);
  display: flex; align-items: flex-start; justify-content: center; padding: 3.2rem 1rem 1rem; }
.bat-scrim { position: absolute; inset: 0; background: rgba(3, 6, 10, 0.55); }
.bat { position: relative; width: min(46rem, 100%); max-height: 70vh; display: flex; flex-direction: column;
  border: 1px solid var(--nc-border); border-radius: 8px; background: var(--nc-elevated);
  box-shadow: var(--nc-shadow-lg); overflow: hidden; }
.bat-hdr { display: flex; align-items: center; gap: 0.6rem; padding: 0.6rem 0.8rem;
  border-bottom: 1px solid var(--nc-border); }
.bat-title { letter-spacing: 0.14em; font-size: 0.72rem; color: var(--nc-text-primary); }
.bat-actor { font-size: 0.68rem; color: var(--nc-text-muted); }
.bat-x { margin-left: auto; background: none; border: none; color: var(--nc-text-secondary);
  font-size: 1.1rem; cursor: pointer; min-width: 24px; min-height: 24px; }
.bat-body { padding: 0.6rem 0.8rem; overflow-y: auto; display: flex; flex-direction: column; gap: 0.35rem; }
.bat-row { display: flex; align-items: center; gap: 0.5rem; width: 100%; text-align: left;
  padding: 0.45rem 0.55rem; min-height: 32px; border: 1px solid var(--nc-border-subtle);
  border-radius: 5px; background: transparent; color: var(--nc-text-secondary);
  font-size: 0.74rem; cursor: pointer; }
.bat-row:hover { border-color: var(--nc-primary); color: var(--nc-text-primary); }
.bat-act { border-left: 2px solid var(--nc-warning); }
.bat-static { cursor: default; }
.bat-static:hover { border-color: var(--nc-border-subtle); color: var(--nc-text-secondary); }
.bat-n { font-variant-numeric: tabular-nums; color: var(--nc-text-primary); font-weight: 600; }
.bat-txt { flex: 1 1 auto; }
.bat-amt { font-variant-numeric: tabular-nums; color: var(--nc-text-primary); }
.bat-note, .bat-clear, .bat-blind { margin: 0.2rem 0; font-size: 0.72rem; }
.bat-note { color: var(--nc-text-muted); }
.bat-clear { color: var(--nc-success); display: flex; align-items: center; gap: 0.4rem; }
.bat-blind { color: var(--nc-text-muted); font-style: italic; }
</style>
