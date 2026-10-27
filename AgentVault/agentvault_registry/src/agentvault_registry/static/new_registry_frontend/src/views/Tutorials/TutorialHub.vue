<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { allTracks } from './data/trackDefinitions'
import { useTutorialRunnerStore, achievementTypeFor } from './stores/tutorialRunnerStore'
import type { SavedTrackProgress, TutorialTrack } from './types/tutorial.types'
import TrackCard from './components/shared/TrackCard.vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { trackIcon } from './trackIcons'
import { TOURS } from './guided/tourRegistry'
import type { GuidedTour } from './guided/tour.types'
import { useGuidedTourStore } from './guided/tourStore'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'
import { withUnit } from './guided/tourUnit'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useAuthStore } from '@/stores/auth'
import { usePermissions, type AdminAction } from '@/composables/usePermissions'

const { t } = useI18n()
// §FESUITE V0597: localCurrency also fills a tour's {unit} (guided/tourUnit.ts)
const { localCurrency, config: hubRegistryCfg } = useRegistryConfig()
const router = useRouter()
const guidedTour = useGuidedTourStore()
const store = useTutorialRunnerStore()
const auth = useAuthStore()
const { can } = usePermissions()

// Access-control LOCK — a tour/track is locked when the current user lacks the
// required admin flag (or the is_admin super-flag). `requireFlag` is an RBAC flag
// like 'admin_enforcement'; usePermissions().can() takes the bare action, so we
// strip the 'admin_' prefix. Server enforces independently — this is UX only.
function isLocked(item: { requireAdmin?: boolean; requireFlag?: string }): boolean {
  if (item.requireAdmin && !auth.isAdmin) return true
  if (item.requireFlag && !can(item.requireFlag.replace(/^admin_/, '') as AdminAction)) return true
  return false
}
function lockLabel(item: { requireAdmin?: boolean; requireFlag?: string }): string {
  return item.requireFlag ? `Requires ${item.requireFlag}` : 'Requires admin access'
}

// §SANDBOXGATE (2026-09-02, his word: "4 is gated by sandbox running … display a
// visible banner for tutorials when sandbox is off. we cant run this on prod.
// its the correct behaviour just miscommunications.")
//
// The API tracks make REAL calls against the sandbox tier, which is off by
// default on prod — correct behaviour, not a bug. Until now nothing said so:
// `sandboxHealthy` existed in the store and drove ONE COLOUR DOT in the runner,
// the hub never mentioned it, and nothing gated anything. A person clicked a
// track and collected step failures.
//
// ⚠ Deliberately NOT folded into isLocked(), which also serves the GUIDED TOURS —
// those run against the LIVE app and must stay available when the sandbox is off.
// ⚠ `sandboxHealthy` is `boolean | null` and the null is load-bearing: null means
// "not answered yet", NOT "off". Bannering on null would tell a first-time
// visitor the tutorials are unavailable for as long as the probe is in flight —
// the §RAT law, an unreadable read is not an empty one. Both predicates require
// an EXPLICIT false.
const sandboxOff = computed(() => store.sandboxHealthy === false)

function trackLocked(track: { requireAdmin?: boolean; requireFlag?: string }): boolean {
  return isLocked(track) || sandboxOff.value
}
function trackLockLabel(track: { requireAdmin?: boolean; requireFlag?: string }): string {
  if (isLocked(track)) return lockLabel(track)
  return t('tutorialHubView.sandboxLock', 'Needs the sandbox — currently offline')
}

// f038: Load achievement catalog and earned achievements
const achievementCatalog = ref<Record<string, { payout_avt: number; name: string }>>({})
const earnedAchievements = ref<Record<string, { payout_avt: number; awarded_at: string }>>({})

onMounted(async () => {
  // §SANDBOXGATE — ask once; the banner and the locks read the answer.
  store.checkSandbox().catch(() => { /* null stays null: unknown, not off */ })
  try {
    const [catalogRes, earnedRes] = await Promise.all([
      apiClient.get('/achievements/catalog').catch(() => ({ data: { achievements: [] } })),
      apiClient.get('/achievements/me').catch(() => ({ data: { achievements: [] } })),
    ])
    for (const a of (catalogRes.data?.achievements || [])) {
      achievementCatalog.value[a.type] = { payout_avt: a.payout_avt, name: a.name }
    }
    for (const a of (earnedRes.data?.achievements || [])) {
      earnedAchievements.value[a.type] = { payout_avt: a.payout_avt, awarded_at: a.awarded_at }
    }
  } catch { /* non-blocking */ }
})

// D6-737: the type a finished track records, from the same rule the runner records it by (every track has one)
function getTrackPayout(trackId: string): number {
  return achievementCatalog.value[achievementTypeFor(trackId)]?.payout_avt || 0
}

function isTrackPaidOut(trackId: string): boolean {
  return !!earnedAchievements.value[achievementTypeFor(trackId)]
}

const savedProgress = computed(() => {
  const all = store.loadAllProgress()
  return all as Record<string, SavedTrackProgress>
})

function handleSelectTrack(trackId: string) {
  router.push({ name: 'tutorial-runner', params: { trackId } })
}

// §TOURBLOG-4 — split the rails: user tours launch for everyone; the operator
// series renders in its own section so the locked cards read intentional.
// §BAFIN (2026-10-01) — a tour whose surface this registry switched off is not offered: the fiat tour where the euro
// lane is closed, the locks tour where locking is. Each switch keeps its own default while the config is unknown
// (the euro lane is off unless said on; locking is on unless said off), the same reading the nav and router use.
const FLAG_DEFAULT_ON: Record<NonNullable<GuidedTour['requiresRegistryFlag']>, boolean> = {
  fiat_onramp_enabled: false,
  staking_enabled: true,
  cockpit_desk_enabled: false,  // the router's reading: an unreadable config leaves the desk closed
}
const tourOffered = (tr: GuidedTour) => {
  const flag = tr.requiresRegistryFlag
  if (!flag) return true
  const v = hubRegistryCfg.value[flag]
  return v === undefined ? FLAG_DEFAULT_ON[flag] : v === true
}
const userTours = computed(() => TOURS.filter(tr => !tr.requireAdmin && tourOffered(tr)))
// an API track follows the same rule (the locks track where locking is on), and the counts count what is offered
const trackOffered = (tr: TutorialTrack) => {
  const flag = tr.requiresRegistryFlag
  if (!flag) return true
  const v = hubRegistryCfg.value[flag]
  return v === undefined ? FLAG_DEFAULT_ON[flag] : v === true
}
const offeredTracks = computed(() => allTracks.filter(trackOffered))
const totalTracks = computed(() => offeredTracks.value.length)
const opTours = computed(() => TOURS.filter(tr => tr.requireAdmin && tourOffered(tr)))
const completedTracks = computed(() =>
  offeredTracks.value.filter(t => {
    const prog = savedProgress.value[t.id]
    return prog && prog.completedStepIds.length === t.steps.length
  }).length
)

const totalStepsCompleted = computed(() =>
  offeredTracks.value.reduce((sum, t) => {
    const prog = savedProgress.value[t.id]
    return sum + (prog?.completedStepIds.length ?? 0)
  }, 0)
)

const totalSteps = computed(() => offeredTracks.value.reduce((sum, t) => sum + t.steps.length, 0))

const overallPercent = computed(() =>
  totalSteps.value > 0 ? Math.round((totalStepsCompleted.value / totalSteps.value) * 100) : 0
)

// Collapsible progress
const showProgressDetail = ref(false)

</script>

<template>
  <div class="th-page max-w-6xl mx-auto px-4 py-8">
    <div class="th-ambient" aria-hidden="true"><div class="th-glow th-glow-a"></div><div class="th-glow th-glow-b"></div><div class="th-grid"></div></div>

    <!-- Hero Header (§TOURBLOG-4 facelift: chip + gradient title + live stat pills) -->
    <div class="th-hero text-center mb-8">
      <div class="th-chip"><span class="th-chip-dot"></span>ACADEMY &middot; LEARN BY DOING</div>
      <h1 class="th-title">
        <span class="bg-linear-to-r/srgb from-cyan-300 via-violet-400 to-purple-400 bg-clip-text text-transparent">
          {{ t('tutorialHubView.title', 'API Tutorials') }}
        </span>
      </h1>
      <p class="text-gray-500 text-xs font-mono tracking-wide mb-3">
        {{ t('tutorialHubView.subtitle', 'Interactive Sandbox-Proxied Step Sequencer with Live ZKP Proof Generation') }}
      </p>
      <!-- §ONBOARDQOL P3 (2026-09-02) — the hero told the truth about the sandbox only
           BELOW the fold (§SANDBOXGATE's banner), while this paragraph promised "AVT
           rewards" above it on every frame, BVT ones included. The sentence now follows
           the sandbox state. D6-738 (2026-10-16): it promises no payouts at all (a registry's
           achievement catalog decides whether a finished track grants anything; the production
           frames' catalog is empty), so it names no currency and need not wait for one. -->
      <p class="text-gray-400 text-sm max-w-2xl mx-auto leading-relaxed" data-testid="th-hero-body" :data-sandbox="sandboxOff ? 'off' : 'on'">
        {{ sandboxOff
          ? t('tutorialHubView.bodyOff', 'The guided tours below walk the live app and work right now. The API tracks run against a sandbox tier that is switched off on this registry, so they stay locked until an operator starts it.')
          : t('tutorialHubView.body', 'Hands-on tutorials executing real API calls against the sandbox stack. Walk through each step and see the full request and response.') }}
      </p>
      <div class="th-stats" role="list">
        <span class="th-stat" role="listitem"><b>{{ userTours.length + opTours.length }}</b> guided tours</span>
        <span class="th-stat" role="listitem"><b>{{ totalTracks }}</b> API tracks<span v-if="sandboxOff" class="th-stat-off" data-testid="th-tracks-off">{{ t('tutorialHubView.tracksOff', 'sandbox offline') }}</span></span>
        <span class="th-stat" role="listitem"><b>{{ totalSteps }}</b> executable steps</span>
        <span class="th-stat" role="listitem" v-if="totalStepsCompleted > 0"><b class="th-stat-live">{{ totalStepsCompleted }}</b> completed by you</span>
      </div>
    </div>

    <!-- Compact Progress Bar (always visible if any progress) -->
    <div v-if="totalStepsCompleted > 0" class="mb-6">
      <button
        @click="showProgressDetail = !showProgressDetail"
        class="w-full rounded-xl border border-gray-700/40 bg-gray-900/40 px-5 py-3 transition-colors hover:border-gray-600/50"
      >
        <div class="flex items-center justify-between mb-2">
          <div class="flex items-center gap-3">
            <h2 class="text-xs font-semibold text-gray-400 uppercase tracking-wider">{{ t('tutorialHubView.progress.title', 'Your Progress') }}</h2>
            <span class="text-[10px] text-gray-500 font-mono">{{ t('tutorialHubView.progress.steps', { completed: totalStepsCompleted, total: totalSteps }) }}</span>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-xs text-gray-400">{{ t('tutorialHubView.progress.tracks', { completed: completedTracks, total: totalTracks }) }}</span>
            <span class="text-gray-600 text-xs transition-transform" :class="showProgressDetail ? 'rotate-180' : ''">▾</span>
          </div>
        </div>
        <div class="w-full h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div
            class="h-full bg-linear-to-r/srgb from-violet-500 to-purple-500 rounded-full transition-all duration-500"
            :style="{ width: `${overallPercent}%` }"
          />
        </div>
      </button>

      <!-- Expandable track detail -->
      <div
        v-if="showProgressDetail"
        class="mt-1 rounded-xl border border-gray-700/30 bg-gray-900/30 px-5 py-3"
      >
        <div class="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-x-4 gap-y-1.5">
          <div
            v-for="track in offeredTracks"
            :key="track.id"
            class="flex items-center gap-2 py-1"
          >
            <Icon :name="trackIcon(track.icon)" class="w-5 text-center" aria-hidden="true" />
            <span class="text-xs text-gray-400 truncate flex-1">{{ track.title }}</span>
            <template v-if="savedProgress[track.id]?.completedStepIds.length === track.steps.length">
              <span class="text-[10px] text-emerald-400 font-semibold">✓</span>
            </template>
            <template v-else-if="(savedProgress[track.id]?.completedStepIds.length ?? 0) > 0">
              <span class="text-[10px] text-gray-500 font-mono">{{ savedProgress[track.id]?.completedStepIds.length }}/{{ track.steps.length }}</span>
            </template>
            <span v-else class="text-[10px] text-gray-700">—</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Guided Tours — game-style spotlight walkthroughs of the real UI -->
    <div class="mb-10">
      <div class="th-section-head">
        <span class="th-section-icon th-section-icon--cyan"><Icon name="mdi:school" /></span>
        <div>
          <h2 class="th-section-title">Guided Tours</h2>
          <p class="th-section-sub">Walk the real interface, spotlight by spotlight — the fastest way to learn your way around.</p>
        </div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <button v-for="tr in userTours" :key="tr.id"
          @click="guidedTour.start(tr.id)"
          class="th-tour-card text-left rounded-xl border p-4"
          :style="{ borderColor: tr.accent + '55', '--th-accent': tr.accent }">
          <div class="flex items-center gap-2.5 mb-2">
            <span class="th-tour-ico" :style="{ color: tr.accent, background: tr.accent + '1c', borderColor: tr.accent + '44' }"><Icon :name="tr.icon" /></span>
            <span class="font-semibold text-white">{{ withUnit(tr.title, localCurrency) }}</span>
          </div>
          <p class="text-sm text-gray-400 mb-3">{{ withUnit(tr.subtitle, localCurrency) }}</p>
          <div class="text-xs text-gray-500 flex items-center justify-between">
            <span>{{ tr.estMinutes }} min · {{ tr.steps.length }} stops</span>
            <span class="th-start font-semibold" :style="{ color: tr.accent }">Start &rarr;</span>
          </div>
        </button>
      </div>
    </div>

    <!-- Operator series — admin-locked cards, deliberately visible to everyone -->
    <div class="mb-10" v-if="opTours.length">
      <div class="th-section-head">
        <span class="th-section-icon th-section-icon--emerald"><Icon name="mdi:server-network" /></span>
        <div>
          <h2 class="th-section-title">Operator Series</h2>
          <p class="th-section-sub">Running the node itself: each tour unlocks with the matching admin area, and its lock label names that area.</p>
        </div>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <button v-for="tr in opTours" :key="tr.id"
          @click="!isLocked(tr) && guidedTour.start(tr.id)"
          :disabled="isLocked(tr)"
          :aria-disabled="isLocked(tr) || undefined"
          :title="isLocked(tr) ? lockLabel(tr) : undefined"
          class="th-tour-card text-left rounded-xl border p-4"
          :class="{ 'tour-card--locked cursor-not-allowed': isLocked(tr) }"
          :style="{ borderColor: tr.accent + '55', '--th-accent': tr.accent }">
          <div class="flex items-center gap-2.5 mb-2">
            <span class="th-tour-ico" :style="{ color: tr.accent, background: tr.accent + '1c', borderColor: tr.accent + '44' }"><Icon :name="tr.icon" /></span>
            <span class="font-semibold text-white">{{ withUnit(tr.title, localCurrency) }}</span>
          </div>
          <p class="text-sm text-gray-400 mb-3">{{ withUnit(tr.subtitle, localCurrency) }}</p>
          <div class="text-xs text-gray-500 flex items-center justify-between">
            <span>{{ tr.estMinutes }} min · {{ tr.steps.length }} stops</span>
            <span v-if="isLocked(tr)" class="font-semibold inline-flex items-center gap-1 text-gray-400">
              <Icon name="mdi:lock" /> {{ lockLabel(tr) }}
            </span>
            <span v-else class="th-start font-semibold" :style="{ color: tr.accent }">Start &rarr;</span>
          </div>
        </button>
      </div>
    </div>

    <!-- §SANDBOXGATE — visible, and only on an EXPLICIT false (never on null). A check that could not be read is
         neither: it says so and offers the check again (§FESUITE, 2026-10-04). -->
    <ReadFailedNotice v-if="store.sandboxCheckFailed" :retry="store.checkSandbox" dense />
    <div v-else-if="sandboxOff" class="th-sandbox-banner" data-testid="th-sandbox-off">
      <Icon name="mdi:alert-circle-outline" class="th-sb-icon" />
      <div>
        <p class="th-sb-title">{{ t('tutorialHubView.sandboxOffTitle', 'API tracks are unavailable right now') }}</p>
        <p class="th-sb-body">{{ t('tutorialHubView.sandboxOffBody', 'These tracks make real calls against the sandbox tier, which is switched off on this registry. The guided tours above still work — they run against the live app.') }}</p>
      </div>
    </div>

    <!-- API Tracks -->
    <div class="th-section-head">
      <span class="th-section-icon th-section-icon--violet"><Icon name="mdi:api" /></span>
      <div>
        <h2 class="th-section-title">API Tracks</h2>
        <p class="th-section-sub">{{ sandboxOff
          ? t('tutorialHubView.tracksSubOff', 'These tracks need the sandbox tier, which is switched off on this registry right now, so every track below is locked. The guided tours above run against the live app.')
          : t('tutorialHubView.tracksSub', 'Real calls against a live sandbox: execute every step, keep the returned IDs, collect the badge.') }}</p>
      </div>
    </div>
    <!-- Track Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
      <TrackCard
        v-for="track in offeredTracks"
        :key="track.id"
        :track="track"
        :saved-progress="savedProgress[track.id] || null"
        :payout-avt="getTrackPayout(track.id)"
        :is-paid-out="isTrackPaidOut(track.id)"
        :locked="trackLocked(track)"
        :locked-label="trackLockLabel(track)"
        @select="handleSelectTrack"
      />
    </div>

    <!-- Info Footer -->
    <div class="mt-8 text-center text-gray-600 text-xs">
      <p>{{ t('tutorialHubView.footer', 'All tutorials execute against the isolated sandbox stack. Progress saves locally.') }}</p>
    </div>
  </div>
</template>

<style scoped>
/* Access-control LOCK — dimmed, non-interactive admin/flag-gated tour card. */
.tour-card--locked {
  opacity: 0.55;
}

/* ── §TOURBLOG-4 facelift ─────────────────────────────────────────── */
.th-page { position: relative; }
.th-ambient { position: absolute; inset: -40px 0 0; pointer-events: none; overflow: hidden; z-index: 0; }
.th-glow { position: absolute; border-radius: 50%; filter: blur(90px); opacity: 0.16; }
.th-glow-a { width: 480px; height: 480px; top: -160px; left: -80px; background: #7c3aed; }
.th-glow-b { width: 420px; height: 420px; top: -120px; right: -60px; background: #06b6d4; }
.th-grid {
  position: absolute; inset: 0;
  background-image: linear-gradient(rgba(148,163,184,0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148,163,184,0.05) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: linear-gradient(to bottom, rgba(0,0,0,0.9), transparent 65%);
}
.th-hero, .th-section-head, .grid { position: relative; z-index: 1; }
.th-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 10.5px; font-weight: 700; letter-spacing: 0.22em;
  color: #a5b4fc; border: 1px solid rgba(139,92,246,0.35);
  background: rgba(139,92,246,0.10); border-radius: 999px;
  padding: 5px 14px; margin-bottom: 14px; text-transform: uppercase;
}
.th-chip-dot { width: 6px; height: 6px; border-radius: 50%; background: #22d3ee; box-shadow: 0 0 8px #22d3ee; }
.th-title { font-size: 2.35rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 6px; }
.th-stats { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px; margin-top: 16px; }
.th-stat {
  font-size: 12px; color: #94a3b8; border: 1px solid rgba(100,116,139,0.35);
  background: rgba(15,23,42,0.55); border-radius: 999px; padding: 5px 13px;
}
.th-stat b { color: #e2e8f0; font-weight: 700; margin-right: 4px; }
.th-stat-live { color: #34d399 !important; }
.th-stat-off { margin-left: .45rem; padding: .1rem .4rem; border-radius: 3px; font-size: .58rem; letter-spacing: .1em; text-transform: uppercase; color: #fbbf24; background: rgba(251,191,36,.12); border: 1px solid rgba(251,191,36,.3); }
.th-section-head { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 14px; }
.th-section-icon {
  display: inline-flex; align-items: center; justify-content: center;
  width: 34px; height: 34px; border-radius: 10px; flex-shrink: 0; font-size: 18px;
  border: 1px solid transparent;
}
.th-section-icon--cyan { color: #22d3ee; background: rgba(34,211,238,0.10); border-color: rgba(34,211,238,0.30); }
.th-section-icon--emerald { color: #34d399; background: rgba(52,211,153,0.10); border-color: rgba(52,211,153,0.30); }
.th-section-icon--violet { color: #a78bfa; background: rgba(167,139,250,0.10); border-color: rgba(167,139,250,0.30); }
.th-section-title { font-size: 1.18rem; font-weight: 700; color: #fff; line-height: 1.2; }
.th-section-sub { font-size: 0.83rem; color: #94a3b8; margin-top: 2px; }
.th-tour-card {
  background: rgba(255,255,255,0.04);
  transition: transform 0.16s ease, box-shadow 0.16s ease, background 0.16s ease;
  position: relative; z-index: 1;
}
.th-tour-card:not(.tour-card--locked):hover {
  background: rgba(255,255,255,0.07);
  transform: translateY(-2px);
  box-shadow: 0 8px 28px -12px var(--th-accent, rgba(139,92,246,0.5));
}
.th-tour-ico {
  display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 8px; border: 1px solid transparent;
  font-size: 16px; flex-shrink: 0;
}
.th-start { transition: transform 0.16s ease; display: inline-block; }
.th-tour-card:not(.tour-card--locked):hover .th-start { transform: translateX(3px); }

/* §SANDBOXGATE — states a real constraint, so amber (attention) not red (fault):
   the sandbox being off on prod is correct behaviour, not a failure. */
.th-sandbox-banner { display: flex; gap: 0.85rem; align-items: flex-start; margin: 0 0 1.25rem;
  padding: 0.9rem 1.1rem; border: 1px solid rgba(245, 158, 11, 0.35);
  border-radius: 0.6rem; background: rgba(245, 158, 11, 0.07); }
.th-sb-icon { width: 1.35rem; height: 1.35rem; color: #f59e0b; flex: 0 0 auto; margin-top: 0.1rem; }
.th-sb-title { font-size: 0.92rem; font-weight: 600; color: #fbbf24; margin: 0 0 0.2rem; }
.th-sb-body { font-size: 0.82rem; line-height: 1.5; color: rgba(255,255,255,0.66); margin: 0; }
</style>
