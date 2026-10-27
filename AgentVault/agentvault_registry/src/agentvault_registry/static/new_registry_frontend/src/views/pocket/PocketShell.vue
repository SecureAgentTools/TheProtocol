<!--
  POCKET mode — the consumer shell (2026-07-07 · AAA+ polish 2026-07-08). Phone-app layout:
  ambient glow field, minimal header (frame + IRONKEY badge), routed tab content, thumb-zone
  bottom bar with an active pill (safe-area aware). Full Mission Control ("Advanced mode") is
  one tap away in More — untouched.
-->
<template>
  <div class="pk-shell">
    <div class="pk-ambient" aria-hidden="true"></div>

    <header class="pk-top">
      <!-- §POCKETCREDS — the identity corner IS the identity control: tapping
           the brand opens the global agent sheet (switch / import / adopt).
           The acting line makes "who am I right now" permanent chrome instead
           of something each tab answers differently. -->
      <button class="pk-brand" data-testid="pk-acting-chip" @click="agentSheetTab = 'switch'; agentSheetOpen = true"
              :aria-label="actingName ? `${t('pocket.shell.actingAs', 'Acting as')} ${actingName}` : t('pocket.agentSheet.title', 'Acting agent')">
        <!-- §OURCHAT polish (2026-08-25, D3) — the mark had NINE desktop mounts
             and ZERO in Pocket. It sits BESIDE the dot rather than replacing it,
             because they are two different facts: the mark says whose app this
             is, the dot says what mode the registry is enforcing. Collapsing
             them would make the brand blink green.
             `alive` is deliberately OFF: that mode runs a breathing drop-shadow,
             a 5s sweep and a blinking core forever, which on a phone is battery
             spent on chrome — and it would compete with the dot's own pulse,
             which is the one animation here that MEANS something.
             aria-hidden: the button already names itself via aria-label, so the
             mark would only add a second voice for one control. -->
        <ProtocolMark :size="24" class="pk-mark" aria-hidden="true" />
        <!-- The ENFORCE text badge was header real estate spent on something More
             already states (his call). The dot that was always here now CARRIES
             the meaning: solid green = IRONKEY enforce, mode readable on
             touch/hover and to screen readers. -->
        <span class="pk-dot" :class="{ enforce: ironkeyMode === 'enforce' }" role="img"
              :title="ironkeyMode ? `IRONKEY ${ironkeyMode} (details in More)` : ''"
              :aria-label="ironkeyMode ? `IRONKEY ${ironkeyMode}` : 'registry status'"></span>
        <span class="pk-brand-col">
          <span class="pk-brand-name">{{ registryName }}</span>
          <span class="pk-acting" data-testid="pk-acting-line">
            <template v-if="actingName">{{ t('pocket.shell.actingAs', 'Acting as') }}{{ ' ' }}<strong>{{ actingName }}</strong></template>
            <template v-else>{{ t('pocket.shell.noActing', 'No acting agent — tap to choose') }}</template>
            <Icon name="mdi:chevron-down" class="pk-acting-chev" />
          </span>
        </span>
      </button>
      <div class="pk-top-right">
        <!-- §POCKETBRIDGE #PK11 — the command queue's door. A phone is an
             inbox device; NEEDS YOU is the inbox. Badge absent until a source
             has actually answered (a 0 we have not earned is a lie). -->
        <button class="pk-bell" :aria-label="t('pocket.shell.needsYou', 'Needs you')" data-tour="pk-attn" data-testid="pk-attn-btn" @click="attnOpen = true">
          <Icon name="mdi:clipboard-check-multiple-outline" />
          <span v-if="attnCount" class="pk-bell-badge pk-badge-attn">{{ attnCount > 9 ? '9+' : attnCount }}</span>
        </button>
        <button class="pk-bell" :aria-label="t('pocket.shell.alerts', 'Alerts')" data-tour="pk-bell" @click="alertsOpen = true">
          <Icon name="mdi:bell" />
          <span v-if="alertCount" class="pk-bell-badge">{{ alertCount > 9 ? '9+' : alertCount }}</span>
        </button>
        <!-- §POCKETBRIDGE3 WS-B2 — hold-to-talk. The shell only CAPTURES the
             utterance; the Assistant panel is the one brain that answers.
             Hidden when SpeechRecognition is absent — the panel explains why. -->
        <button v-if="voice.supported" class="pk-bell pk-mic" :class="{ live: voice.listening.value }"
          :aria-label="t('pocket.shell.holdToTalk', 'Hold to talk')" data-testid="pk-mic"
          @pointerdown.prevent="micDown" @pointerup.prevent="micUp" @pointerleave="micUp" @pointercancel="micUp"
          @click="micClick">
          <Icon name="mdi:microphone" />
        </button>
      </div>
    </header>

    <div v-if="!online" class="pk-offline" role="status" data-testid="pk-offline">
      {{ t('pocket.shell.offline', "Offline — showing what this device last saw. Nothing sends until you're back.") }}
    </div>

    <PocketAlerts :open="alertsOpen" @close="alertsOpen = false" @count="alertCount = $event" />

    <!-- #PK11 — the SAME NEEDS YOU the bridge and the light bridge run (13
         sources incl. the cross-registry fan-out over this device's own
         credentials). Its CSS-var positioning falls back to full viewport,
         which is exactly right here; the :deep overrides below only size it
         for thumbs. unread-door: Pocket HAS an alerts sheet, so the unread
         row is a door here (#PK12) — on the bridge it stays a number. -->
    <BridgeAttention :show="attnOpen" :unread-door="true"
                     @close="attnOpen = false" @count="attnCount = $event"
                     @open-work="openWork" @open-lane="onAttnLane"
                     @open-unread="alertsOpen = true" />
    <!-- #PK13 — contracts / guild work / disputes arrive in Pocket through the
         existing WORK view (Teleported; its phone sheet CSS is global). -->
    <component :is="BridgeWorkView" v-if="workEver" :show="workOpen" :initial-tab="workLane" :initial-id="workId" :land-seq="workSeq" @close="workOpen = false" />
    <!-- #PK17 — the senate sheet; also reachable from Home's VOTE door via ?sheet=senate. -->
    <PocketSenate :open="senateOpen" @close="senateOpen = false" />
    <!-- §POCKETCREDS — the global agent sheet (switch / import / adopt), owned
         by the shell so every tab shares one instance; ?sheet=agent&tab=… is
         the deep-link door (More's credential rows use it). -->
    <PocketAgentSheet :open="agentSheetOpen" :initial-tab="agentSheetTab"
                      @close="agentSheetOpen = false" @switched="onAgentSwitched"
                      @create="agentSheetOpen = false; uiStore.openQuickAgentModal()" />
    <QuickAgentModal />

    <main id="main-content" class="pk-main app-main" tabindex="-1" style="position: relative;">
      <!-- §POCKETBRIDGE2 W3.1 — a throwing tab used to escape to the APP-level
           boundary, unmounting the whole pocket chrome (tab bar, header, lock)
           into the desktop fallback. Caught here, the tab shows recovery in
           place and the shell stays alive. -->
      <ErrorBoundary :fallback="t('pocket.shell.tabError', 'This tab hit an error. The rest of Pocket is fine — try again or switch tabs.')">
        <!-- ⚠ NO `mode="out-in"` HERE, AND IT MUST STAY THAT WAY.
             Every pocket route is a LAZY `() => import(...)`. With out-in, Vue
             tears the old view down, runs its leave transition, and only then
             mounts the new one — but an async component that is still resolving
             when that gap closes never gets mounted at all: the outlet keeps
             rendering an empty comment and only a full page load recovers.
             MEASURED 2026-08-24 on his own report: tapping a thread in the
             OurState list changed the hash, fetched the chunk (HTTP 200), and
             left the screen blank; F5 fixed it. It bit here first because this
             is the app's first LIST → DETAIL step inside one tab, and every
             battery until now entered a thread by URL, so the click path was
             never measured (the "audit that always presses Next" class).
             A simultaneous cross-fade has no gap to fall into. -->
        <router-view v-slot="{ Component }">
          <transition name="pk-tab">
            <component :is="Component" />
          </transition>
        </router-view>
      </ErrorBoundary>
    </main>

    <nav class="pk-bar" :aria-label="t('pocket.shell.navLabel', 'Pocket navigation')" data-tour="pk-tabbar">
      <!-- loop var is `tab`, NOT `t`: `t` is the translate function in this scope
           and a v-for alias would shadow it (the DOM-global-shadowing class). -->
      <router-link v-for="tab in tabs" :key="tab.path" :to="tab.path" class="pk-tab-btn"
                   :class="{ active: isActive(tab.path) }"
                   :aria-current="isActive(tab.path) ? 'page' : undefined"
                   :aria-label="tab.label">
        <span class="pk-tab-pill" aria-hidden="true"></span>
        <Icon :name="tab.icon" />
        <span class="pk-tab-label">{{ tab.label }}</span>
      </router-link>
    </nav>

    <!-- biometric app-lock overlay -->
    <transition name="pk-lock">
      <!-- Not on the approve-sign-in screen: that device may have no session at all (the lock is
           protecting nothing), and the approval itself already demands a verified fingerprint —
           gating it behind the lock asked for TWO prompts for one intent. -->
      <div v-if="lock.locked.value && route.name !== 'pocket-approve-login'"
           class="pk-lockscreen" role="dialog" aria-modal="true" :aria-label="t('pocket.shell.lockedAria', 'Locked')">
        <div class="pk-lock-ring"><Icon name="mdi:fingerprint" /></div>
        <h2 class="pk-lock-title">{{ registryName }}</h2>
        <p class="pk-lock-sub">{{ t('pocket.shell.lockedSub', 'Pocket is locked') }}</p>
        <button class="pk-lock-btn" :disabled="lock.busy.value" @click="doUnlock">
          <Icon name="mdi:fingerprint" /> {{ lock.busy.value ? t('pocket.shell.verifying', 'Verifying…') : t('pocket.shell.unlock', 'Unlock with biometrics') }}
        </button>
        <p v-if="unlockErr" class="pk-lock-err">{{ unlockErr }}</p>
      </div>
    </transition>

    <!-- guided-tour overlay — Pocket has its own shell, so the DashboardLayout mount never covers /pocket/* -->
    <GuidedTour />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ProtocolMark from '@/components/ProtocolMark.vue'
import { apiClient } from '@/services/api/client'
import { usePocketLock, maybeUnsealDeviceKeyVault } from '@/composables/usePocketLock'
import { useAlive } from '@/composables/useAlive'
import { usePocketAgent } from '@/composables/usePocketAgent'
import { useNotificationStore } from '@/stores/notifications'
import BridgeAttention from '@/components/bridge/BridgeAttention.vue'
import ErrorBoundary from '@/components/common/ErrorBoundary.vue'
import { useLedgerStream } from '@/composables/useLedgerStream'
import { useVoice } from '@/composables/useVoice'
import PocketSenate from './PocketSenate.vue'
import PocketAgentSheet from './PocketAgentSheet.vue'
import PocketAlerts from './PocketAlerts.vue'
import { useUIStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import GuidedTour from '@/views/Tutorials/guided/GuidedTour.vue'
import { useGuidedTourStore } from '@/views/Tutorials/guided/tourStore'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const route = useRoute()
const registryName = ref('TheProtocol')
const ironkeyMode = ref('')
const lock = usePocketLock()
const unlockErr = ref('')
const alertsOpen = ref(false)
const alertCount = ref(0)
lock.arm()

/* ── §POCKETBRIDGE #PK11/#PK13/#PK17 — the command queue + its doors ── */
const router = useRouter()
const notif = useNotificationStore()
const auth = useAuthStore()
const { restoreActing, credAgents } = usePocketAgent()

/* §POCKETCREDS — the global agent sheet + the header's acting line. The name
   resolves store-first, vault-second: the auth store knows WHO is acting, the
   vault usually knows what they are CALLED. */
const agentSheetOpen = ref(false)
const agentSheetTab = ref<'switch' | 'import' | 'adopt'>('switch')
// §PHONESTART (2026-09-02) — THE quick-create modal (DashboardLayout mounts the same one),
// so Pocket's create doors (`uiStore.openQuickAgentModal()`) open something on a phone.
const uiStore = useUIStore()
const QuickAgentModal = defineAsyncComponent(() => import('@/components/common/QuickAgentModal.vue'))
const actingName = computed<string>(() => {
  const act = (auth as any).activeAgent
  if (!act?.did) return ''
  if (act.name) return String(act.name)
  const hit = credAgents.value.find(a => a.did === act.did)
  return hit?.name || `${String(act.did).slice(0, 18)}…`
})
function onAgentSwitched() { agentSheetOpen.value = false }
const attnOpen = ref(false)
// §FESUITE (V0578): null until NEEDS YOU has answered (its count is null while it loads and when every read failed); the
// shell read that null as 0 and cleared the installed app's icon badge on it: "nothing needs you" said by the phone
const attnCount = ref<number | null>(null)
const workOpen = ref(false)
const workEver = ref(false)          // mount-once latch: keeps WORK's tab state across opens
const senateOpen = ref(false)
const BridgeWorkView = defineAsyncComponent(() => import('@/components/bridge/BridgeWorkView.vue'))

/* §POCKETBRIDGE #PK19 — ONE live wire (S9): the SHELL owns setMineDids, the
   §LITEBRIDGE lesson verbatim (the stage owned it once; with no stage, MINE
   read empty forever on a healthy machine). The slim /agent-dids read is the
   §BRIDGE R1 endpoint: identity only, whole fleet, one request. */
const stream = useLedgerStream()
async function loadMineDids(): Promise<void> {
  try {
    const res = await apiClient.get('/developers/me/agent-dids')
    const dids = Array.isArray(res.data?.dids) ? res.data.dids.map((d: any) => String(d)) : []
    if (dids.length) stream.setMineDids(dids)
  } catch { /* MINE stays unset — live views still count everything, honestly unmarked */ }
}

/* #PK25 — offline honesty: the cached shell may boot with no network; a page
   that looks normal while silently failing every fetch is a lie of omission. */
const online = ref(typeof navigator === 'undefined' ? true : navigator.onLine)
const onNet = () => { online.value = true }
const offNet = () => { online.value = false }
// §POCKETBRIDGE5 A' — the modal opens ONTO the lane (and row) the attention
// row named; a bare open keeps the default tab.
const workLane = ref<'contracts' | 'guild' | 'disputes' | undefined>(undefined)
const workId = ref<string | undefined>(undefined)
// Every openWork bumps this: a deep link naming the SAME record while the
// modal is already open would otherwise be invisible to the modal (identical
// prop values fire no watcher) — and the record may have changed under it.
const workSeq = ref(0)
function openWork(tab?: 'contracts' | 'guild' | 'disputes', id?: string) {
  workLane.value = tab; workId.value = id; workSeq.value++
  workEver.value = true; workOpen.value = true
}
function onAttnLane(lane: string, ref?: string) {
  if (lane === 'senate') { senateOpen.value = true }
  // §POCKETBRIDGE2 W5.3 — a guild row lands on ITS order, not just the tab.
  else if (lane === 'guild') { router.push(ref ? { path: '/pocket/payments', query: { order: ref } } : '/pocket/payments').catch(() => {}) }
  else if (lane === 'staking') { router.push({ path: '/pocket/home', query: { sheet: 'stake' } }).catch(() => {}) }
  // Anything else has no pocket door yet — the queue's own rows are the truth.
}

/* Deep links: a push lands on ?attention=1 (#PK14), Home's VOTE door on
   ?sheet=senate. Query-only navigation never remounts — watch, don't mount
   (§NOTIFLOG). Cleaned after handling so reloads do not re-open. */
watch(() => route.query, (q) => {
  let dirty = false
  const clean: Record<string, any> = { ...q }
  if (q.attention === '1') { attnOpen.value = true; delete clean.attention; dirty = true }
  if (q.sheet === 'senate') { senateOpen.value = true; delete clean.sheet; dirty = true }
  // §POCKETCREDS — ?sheet=agent(&tab=import|adopt) opens the global agent
  // sheet on the named lane (More's credential rows arrive this way).
  else if (q.sheet === 'agent') {
    agentSheetTab.value = q.tab === 'import' || q.tab === 'adopt' ? q.tab : 'switch'
    agentSheetOpen.value = true
    delete clean.sheet; delete clean.tab; dirty = true
  }
  // §POCKETBRIDGE5 — ?dispute=<id> lands ON that dispute in the WORK modal;
  // ?work=<lane> opens the modal on a lane (the Earn disputed-order door).
  if (q.dispute) { openWork('disputes', String(q.dispute)); delete clean.dispute; dirty = true }
  else if (q.work === 'disputes' || q.work === 'contracts' || q.work === 'guild') { openWork(q.work as any); delete clean.work; dirty = true }
  if (dirty) router.replace({ query: clean }).catch(() => {})
}, { immediate: true, deep: true })
async function doUnlock() { unlockErr.value = ''; const ok = await lock.unlock(); if (!ok) unlockErr.value = t('pocket.shell.unlockFailed', 'Verification failed or cancelled. Try again.') }

// Computed, not a const: the tab bar must re-label when the locale changes.
const tabs = computed(() => [
  { path: '/pocket/home', icon: 'mdi:home', label: t('pocket.tabs.home', 'Home') },
  { path: '/pocket/trade', icon: 'mdi:chart-line', label: t('pocket.tabs.trade', 'Trade') },
  { path: '/pocket/payments', icon: 'mdi:briefcase', label: t('pocket.tabs.earn', 'Payments') },
  { path: '/pocket/agents', icon: 'mdi:robot', label: t('pocket.tabs.agents', 'Agents') },
  // D2 (§OURSTATE-1, Commander-approved): OurState takes this slot. Approvals
  // stays fully reachable — route unchanged, NEEDS YOU doors unchanged, and a
  // row in More. "OurState" is a proper noun, untranslated in all locales.
  { path: '/pocket/ourchat', icon: 'mdi:chat', label: 'OurChat' },
  { path: '/pocket/more', icon: 'mdi:cog', label: t('pocket.tabs.more', 'More') },
])
const isActive = (p: string) => route.path.startsWith(p)

// §FESUITE (the leave sweep): the shell's network listeners went on after its first reads and never came off; a shell
// left during those reads starts nothing when they land, and one that unmounts takes its listeners with it
const alive = useAlive()
onMounted(async () => {
  // Registry identity + IRONKEY posture — best-effort, never blocks the shell.
  try {
    const r = await fetch('/.well-known/registry-card.json')
    if (r.ok) {
      const data = await r.json()
      registryName.value = data?.identity?.display_name || data?.identity?.name || 'TheProtocol'
    }
  } catch { /* keep default */ }
  // §FESUITE: the shell also frames a PUBLIC page (approve-login, opened on a device with no session): there the
  // member's questions (the IRONKEY badge, the fleet's DIDs) have no one to answer them and came back 401.
  if (auth.isAuthenticated) {
    try {
      const { data } = await apiClient.get('/agents/authz/catalog')
      ironkeyMode.value = data?.mode || ''
    } catch { /* badge hidden */ }
  }
  if (!alive()) return
  window.addEventListener('online', onNet)
  window.addEventListener('offline', offNet)
  if (auth.isAuthenticated) void loadMineDids()
  // #PK32 — device-key vaults open without a prompt (the lock still gates the
  // UI); PRF vaults open inside the unlock ceremony itself.
  void maybeUnsealDeviceKeyVault()
  // #PK11 — make SOME agent the acting one so the command queue can read the
  // agent-scoped rails on arrival. Failure = the queue states its blind spot.
  void restoreActing()
  // unread-alerts badge — via the notifications STORE now, one fetch that also
  // feeds the command queue's unread row (the bridge reads the same store).
  try {
    await (notif as any).fetchUnread?.()
    alertCount.value = Number((notif as any).unreadCount || 0)
  } catch { /* badge hidden */ }
  if (!alive()) return

  // First Pocket visit → run the walkthrough once, ever. Replay lives in More → App tour.
  // Flag is set the moment we fire (skip counts as seen); never fires over the lock screen.
  //
  // §OPGUIDE-7 — MUST NOT fire while a tour is already running. The pocket tour's own
  // second step routes to /pocket/home, which mounts this shell; the auto-start then
  // restarted the very tour that was mid-flight (observed: 3/13 → 1/13), so it could
  // never reach the trade/earn/agents/approvals/more steps. It also hijacked any other
  // tour that happened to route through Pocket. Checked twice — once now and again
  // inside the timeout, because 700ms is plenty of time for a tour to start.
  try {
    const gt = useGuidedTourStore()
    if (!localStorage.getItem('pk_tour_done') && !lock.locked.value && !gt.isActive) {
      localStorage.setItem('pk_tour_done', '1')
      setTimeout(() => { if (!gt.isActive) gt.start('pocket') }, 700)
    }
  } catch { /* storage unavailable — skip auto-start */ }
})
onUnmounted(() => {
  window.removeEventListener('online', onNet)
  window.removeEventListener('offline', offNet)
})

// §POCKETBRIDGE4 WS-H — the NEEDS-YOU count on the installed app's icon.
// Badging is a silent nicety: feature-detected, never throws, and a 0 clears.
watch(attnCount, (n) => {
  if (n === null) return   // unanswered: the icon keeps what it last showed, never a cleared "nothing needs you"
  try {
    const nav: any = navigator
    if (typeof nav.setAppBadge !== 'function') return
    if (n > 0) nav.setAppBadge(n).catch(() => {})
    else nav.clearAppBadge?.().catch(() => {})
  } catch { /* unsupported browser */ }
}, { immediate: true })

// §POCKETBRIDGE3 WS-B2 — shell mic: capture, hand off, let the panel answer.
const voice = useVoice()
let shellMicHeld = false
function micDown() {
  if (shellMicHeld) return
  shellMicHeld = true
  voice.start((heard) => {
    try { sessionStorage.setItem('tp_assistant_heard', heard) } catch { /* ok */ }
    router.push('/pocket/assistant').catch(() => {})
  })
}
function micUp() { if (!shellMicHeld) return; shellMicHeld = false; voice.stop() }
// a plain tap (no speech captured) still opens the panel — discoverability
function micClick() { if (!voice.listening.value && !voice.interim.value) router.push('/pocket/assistant').catch(() => {}) }
</script>

<style scoped>
.pk-shell { min-height: 100dvh; display: flex; flex-direction: column; background: #06080c; color: #e6edf3;
  position: relative; isolation: isolate; }
/* ambient glow field — fixed, GPU-cheap, behind everything */
.pk-ambient { position: fixed; inset: 0; z-index: -1; pointer-events: none;
  background:
    radial-gradient(60rem 34rem at 85% -8%, rgba(0,212,255,0.075), transparent 62%),
    radial-gradient(46rem 30rem at -18% 32%, rgba(99,102,241,0.055), transparent 60%),
    radial-gradient(40rem 30rem at 55% 118%, rgba(16,185,129,0.045), transparent 62%); }

.pk-top { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; padding: 0.7rem 1rem;
  padding-top: calc(0.7rem + env(safe-area-inset-top, 0px));
  border-bottom: 1px solid rgba(255,255,255,0.06); background: rgba(9,12,17,0.86); backdrop-filter: blur(12px);
  position: sticky; top: 0; z-index: 20; }
.pk-brand { display: flex; align-items: center; gap: 0.5rem; font-weight: 600; font-size: 0.92rem;
  letter-spacing: 0.02em; min-width: 0; flex: 1 1 auto;
  /* §POCKETCREDS — the brand is a BUTTON now (the agent-sheet door); the
     resets keep it looking exactly like the label it always was. */
  background: none; border: none; color: inherit; padding: 0; text-align: left;
  cursor: pointer; -webkit-tap-highlight-color: transparent; min-height: 44px; }
.pk-brand-col { display: flex; flex-direction: column; gap: 0.08rem; min-width: 0; }
.pk-brand-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pk-acting { display: flex; align-items: center; gap: 0.2rem; font-size: 0.64rem; font-weight: 500;
  color: rgba(230,237,243,0.55); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; letter-spacing: 0.01em; }
.pk-acting strong { color: var(--nc-primary, #00d4ff); font-weight: 700; overflow: hidden; text-overflow: ellipsis; }
.pk-acting-chev { flex: 0 0 auto; opacity: 0.6; }
.pk-acting :deep(svg) { width: 0.8rem; height: 0.8rem; }
/* §OURCHAT polish — the mark leads the identity corner. `flex: 0 0 auto` so a
   long registry name ellipsises the NAME and never squeezes the brand; the
   negative right margin tightens it against the dot so the two read as one
   identity cluster rather than as two separate widgets. */
.pk-mark { flex: 0 0 auto; margin-right: -0.12rem; }
.pk-dot.enforce { background: #22c55e; box-shadow: 0 0 7px rgba(34,197,94,0.55); }
.pk-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--nc-primary, #00d4ff);
  box-shadow: 0 0 10px var(--nc-primary, #00d4ff); flex: 0 0 auto;
  animation: pk-pulse 3.2s ease-in-out infinite; }
.pk-top-right { flex: 0 0 auto; display: flex; align-items: center; gap: 0.45rem; }
.pk-bell { position: relative; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); border-radius: 10px; min-width: 44px; min-height: 44px; display: grid; place-items: center;
  color: rgba(230,237,243,0.75); cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pk-bell :deep(svg) { width: 1rem; height: 1rem; }
.pk-bell-badge { position: absolute; top: -5px; right: -5px; min-width: 15px; height: 15px; border-radius: 8px; padding: 0 3px;
  background: #ff6b6b; color: #fff; font-size: 0.56rem; font-weight: 800; display: grid; place-items: center; line-height: 1; }
.pk-secure { display: inline-flex; align-items: center; gap: 0.3rem; font-size: 0.64rem; font-weight: 700; letter-spacing: 0.08em;
  color: #34d399; background: rgba(16,185,129,0.12); border: 1px solid rgba(16,185,129,0.3); border-radius: 7px; padding: 0.24rem 0.5rem;
  white-space: nowrap; }
.pk-secure :deep(svg) { width: 0.85rem; height: 0.85rem; }

.pk-main { flex: 1 1 auto; overflow-y: auto; -webkit-overflow-scrolling: touch;
  padding-bottom: calc(5.2rem + env(safe-area-inset-bottom, 0px)); }

.pk-bar { position: fixed; left: 0; right: 0; bottom: 0; z-index: 30; display: flex;
  background: rgba(9,12,17,0.92); backdrop-filter: blur(16px) saturate(1.3);
  border-top: 1px solid rgba(255,255,255,0.08);
  box-shadow: 0 -12px 32px rgba(0,0,0,0.35);
  padding: 0.3rem 0.4rem; padding-bottom: calc(0.3rem + env(safe-area-inset-bottom, 0px)); }
/* §FESUITE: an inactive tab's label was 42% white, 3.64:1 on the bar (AA asks 4.5:1); 55% is about 5.3:1 */
.pk-tab-btn { position: relative; flex: 1 1 0; min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.16rem;
  padding: 0.55rem 0.1rem 0.25rem; min-height: 56px; text-decoration: none; color: rgba(230,237,243,0.55);
  font-size: 0.58rem; letter-spacing: 0.01em; border-radius: 14px;
  transition: color 0.18s ease, transform 0.12s ease; -webkit-tap-highlight-color: transparent; }
.pk-tab-btn:active { transform: scale(0.94); }
.pk-tab-btn :deep(svg) { width: 1.3rem; height: 1.3rem; flex: 0 0 auto; transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1); }
.pk-tab-label { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pk-tab-pill { position: absolute; inset: 4px 3px; border-radius: 12px; opacity: 0;
  background: linear-gradient(180deg, rgba(0,212,255,0.13), rgba(0,212,255,0.05));
  border: 1px solid rgba(0,212,255,0.22); transition: opacity 0.2s ease; }
.pk-tab-btn.active { color: var(--nc-primary, #00d4ff); }
.pk-tab-btn.active .pk-tab-pill { opacity: 1; }
.pk-tab-btn.active :deep(svg) { filter: drop-shadow(0 0 7px rgba(0,212,255,0.55)); }
.pk-tab-label { position: relative; }
.pk-tab-btn.active .pk-tab-label { font-weight: 700; }

.pk-tab-enter-active { transition: opacity 0.18s ease, transform 0.18s ease; }
.pk-tab-leave-active { transition: opacity 0.12s ease; position: absolute; inset: 0; }
.pk-tab-enter-from { opacity: 0; transform: translateY(6px); }
.pk-tab-leave-to { opacity: 0; }

/* lock screen */
.pk-lockscreen { position: fixed; inset: 0; z-index: 100; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 0.5rem; padding: 2rem; text-align: center;
  background: radial-gradient(40rem 30rem at 50% 30%, rgba(0,212,255,0.08), transparent 60%), rgba(6,8,12,0.98); backdrop-filter: blur(6px); }
.pk-lock-ring { width: 5rem; height: 5rem; border-radius: 50%; display: grid; place-items: center; margin-bottom: 0.5rem;
  background: rgba(0,212,255,0.07); border: 1px solid rgba(0,212,255,0.25); color: var(--nc-primary, #00d4ff);
  box-shadow: 0 0 30px -6px rgba(0,212,255,0.35); animation: pk-lock-breathe 3s ease-in-out infinite; }
.pk-lock-ring :deep(svg) { width: 2.6rem; height: 2.6rem; }
.pk-lock-title { font-size: 1.05rem; margin: 0; }
.pk-lock-sub { font-size: 0.82rem; opacity: 0.55; margin: 0 0 1rem; }
.pk-lock-btn { display: inline-flex; align-items: center; gap: 0.5rem; background: linear-gradient(160deg, rgba(0,212,255,0.18), rgba(0,212,255,0.06));
  border: 1px solid rgba(0,212,255,0.35); border-radius: 14px; padding: 0.85rem 1.4rem; color: #e6edf3; font-size: 0.92rem; font-weight: 600;
  cursor: pointer; min-height: 48px; -webkit-tap-highlight-color: transparent; transition: transform 0.12s; }
.pk-lock-btn:active { transform: scale(0.96); }
.pk-lock-btn :deep(svg) { width: 1.2rem; height: 1.2rem; color: var(--nc-primary, #00d4ff); }
.pk-lock-err { font-size: 0.78rem; color: #ff8a8a; margin: 0.6rem 0 0; }
.pk-lock-enter-active, .pk-lock-leave-active { transition: opacity 0.2s ease; }
.pk-lock-enter-from, .pk-lock-leave-to { opacity: 0; }
@keyframes pk-lock-breathe { 0%, 100% { box-shadow: 0 0 30px -6px rgba(0,212,255,0.35); } 50% { box-shadow: 0 0 44px -4px rgba(0,212,255,0.55); } }
@keyframes pk-pulse { 0%, 100% { box-shadow: 0 0 10px var(--nc-primary, #00d4ff); }
  50% { box-shadow: 0 0 3px var(--nc-primary, #00d4ff); } }
/* §POCKETBRIDGE #PK9/#PK11 — NEEDS YOU, thumb-sized. BridgeAttention renders
   in-tree (no Teleport), so scoped :deep reaches it: bottom-sheet posture,
   44px rows, safe-area. The desktop keeps its own compact sizing. */
.pk-badge-attn { background: #f6c453; color: #1a1205; }
.pk-offline { position: sticky; top: 0; z-index: 25; text-align: center; font-size: 0.72rem; font-weight: 600;
  color: #ffd9a0; background: rgba(224,166,63,0.14); border-bottom: 1px solid rgba(224,166,63,0.35);
  padding: 0.35rem 0.8rem; }
.pk-shell :deep(.bat-wrap) { padding: 0; align-items: flex-end; z-index: 95; }
.pk-shell :deep(.bat) { width: 100%; max-width: 560px; max-height: 86dvh;
  border-radius: 22px 22px 0 0; border-bottom: none;
  padding-bottom: env(safe-area-inset-bottom, 0px); background: #0c0f15; }
.pk-shell :deep(.bat-hdr) { padding: 0.85rem 1rem; }
.pk-shell :deep(.bat-title) { font-size: 0.8rem; }
.pk-shell :deep(.bat-x) { min-width: 44px; min-height: 44px; font-size: 1.3rem; }
.pk-shell :deep(.bat-body) { padding: 0.7rem 0.9rem 1rem; gap: 0.45rem; }
.pk-shell :deep(.bat-row) { min-height: 44px; font-size: 0.82rem; border-radius: 12px; padding: 0.6rem 0.7rem; }
.pk-shell :deep(.bat-note), .pk-shell :deep(.bat-clear), .pk-shell :deep(.bat-blind) { font-size: 0.78rem; }

@media (prefers-reduced-motion: reduce) {
  .pk-tab-enter-active, .pk-tab-leave-active, .pk-tab-btn, .pk-tab-btn :deep(svg), .pk-tab-pill { transition: none; }
  .pk-dot, .pk-lock-ring { animation: none; }
}

/* §POCKETBRIDGE3 — the mic bell */
.pk-mic.live { color: #ff8a8a; border-color: rgba(255,138,138,0.5); }
.pk-mic { touch-action: none; }
</style>
