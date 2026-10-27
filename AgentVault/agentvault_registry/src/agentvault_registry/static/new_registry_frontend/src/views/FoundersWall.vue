<template>
  <!--
    FoundersWall — public-anonymized list of every backer (PB-1, 2026-05-09).

    No PII. Each row is just a flare + tier label + "X minutes ago" timestamp.
    The page is a tribute, not a leaderboard — the goal is to make every
    backer feel they're part of a real, growing community.

    Three sections:
      1. Hero with totals (total backers / AVT distributed)
      2. Founders gallery — first 100 Founders are forever
      3. Recent backers feed (live)
  -->
  <div class="fw-root nc-page">
    <header class="fw-hero">
      <div class="fw-chip">
        <span class="fw-chip-dot"></span>
        {{ t('founderWall.chip') }}
      </div>
      <h1 class="fw-h1">
        <template v-if="t('founderWall.h1Prefix')">{{ t('founderWall.h1Prefix') }} </template><span class="fw-h1-accent">{{ t('founderWall.h1Accent') }}</span>
      </h1>
      <p class="fw-tagline">
        {{ t('founderWall.tagline') }}
      </p>

      <div class="fw-totals">
        <div class="fw-total-item">
          <div class="fw-total-num">{{ stats ? formatNumber(stats.total_backers ?? 0) : '—' }}</div>
          <div class="fw-total-label">{{ (stats?.total_backers ?? 0) === 1 ? t('founderWall.totals.backer') : t('founderWall.totals.backers') }}</div>
        </div>
        <div class="fw-total-item">
          <div class="fw-total-num">{{ stats ? formatNumber(Number(stats.total_avt_distributed ?? 0)) : '—' }}</div>
          <div class="fw-total-label">{{ t('founderWall.totals.avtDistributed', { unit: localCurrency }) }}</div>
        </div>
        <div class="fw-total-item">
          <div class="fw-total-num">
            <span style="color: rgb(252, 211, 77)">{{ stats ? (stats.founder_count ?? 0) : '—' }}</span>
            <span style="opacity: 0.5">/100</span>
          </div>
          <div class="fw-total-label">{{ t('founderWall.totals.founders') }}</div>
        </div>
      </div>

      <div class="fw-actions">
        <router-link to="/become-a-backer" class="nc-btn nc-btn-primary fw-back-cta">
          <Icon name="mdi:hand-coin-outline" /> {{ t('founderWall.joinCta') }}
        </router-link>
      </div>
    </header>

    <div v-if="loading" class="fw-loading">
      <Icon name="mdi:loading" class="fw-spin" /> {{ t('founderWall.loading') }}
    </div>

    <ReadFailedNotice v-else-if="statsFailed && !stats" :retry="load" />

    <template v-else>
      <!-- 2026-05-10 — Glory pass: backers grouped by tier (rare → common).
           The original separate Founder-gallery section was removed in favor
           of the per-tier section below + the totals strip in the hero.
           Founder scarcity messaging now lives in the Founder tier section's
           empty-state copy ("No Founders yet. 100 slots remain.") — the
           tagline already conveys the limit. -->
      <!-- 2026-05-11 §12 — Shadow Cabinet section is COUNT-ONLY by Commander
           direction. No per-backer rows: just the count + a single polished
           encirclement sample + the tight tagline. The other tiers (founder/
           architect/sentinel) keep their full per-backer feeds below. -->
      <section
        v-if="(stats?.shadow_chancellor_count ?? 0) > 0 || tierBackers('shadow_chancellor').length > 0"
        class="fw-tier-section fw-tier-shadow_chancellor fw-tier-shadow-cabinet"
      >
        <div class="fw-tier-header fw-shadow-header">
          <FlareEncirclement
            tier="shadow_chancellor"
            :variant="currentSampleVariant"
            :initials="'??'"
            size="lg"
            class="fw-shadow-sample"
          />
          <div class="fw-shadow-text">
            <div class="fw-shadow-title-row">
              <h2 class="fw-tier-title">{{ t('founderWall.shadowCabinet.title') }}</h2>
              <span class="fw-tier-count fw-shadow-count">{{ shadowCabinetCount }}</span>
            </div>
            <p class="fw-tier-sub fw-shadow-sub">
              {{ t('founderWall.shadowCabinet.sub') }}
            </p>
          </div>
        </div>
      </section>

      <section
        v-for="tier in tierOrder"
        v-show="!(tier.hideWhenEmpty && tierBackers(tier.flare).length === 0)"
        :key="tier.flare"
        class="fw-tier-section"
        :class="`fw-tier-${tier.flare}`"
      >
        <div class="fw-tier-header">
          <div class="fw-tier-title-row">
            <FlareBadge :tier="tier.flare" size="sm" :show-label="false" />
            <h2 class="fw-tier-title">{{ tier.label }}</h2>
            <span class="fw-tier-count">{{ tierBackers(tier.flare).length }}</span>
          </div>
          <p class="fw-tier-sub">{{ tier.tagline }}</p>
        </div>
        <ul v-if="tierBackers(tier.flare).length" class="fw-feed">
          <li
            v-for="(b, i) in tierBackers(tier.flare)"
            :key="`${tier.flare}-${i}`"
            class="fw-feed-row"
          >
            <FlareBadge :tier="b.flare_tier" size="sm" :show-label="false" />
            <span v-if="b.display_country" class="flag-frame"><span class="flag-glyph">{{ flagEmoji(b.display_country) }}</span></span>
            <span v-if="b.display_name" class="fw-feed-name">{{ b.display_name }}</span>
            <span v-else class="fw-feed-name fw-feed-name-anon">{{ t('founderWall.anonymous') }}</span>
            <span class="fw-feed-amount">{{ formatNumber(Number(b.amount_avt)) }} {{ localCurrency }}</span>
            <span class="fw-feed-time">{{ formatTimeAgo(b.minutes_ago, b.seconds_ago) }}</span>
            <span v-if="b.seconds_ago < 600" class="fw-feed-fresh">{{ t('founderWall.justJoined') }}</span>
          </li>
        </ul>
        <p v-else class="fw-empty">{{ tier.empty }}</p>
      </section>
    </template>

    <footer class="fw-footer">
      <p>
        {{ t('founderWall.footer.main', { unit: localCurrency }) }}
        <router-link to="/become-a-backer" style="text-decoration: underline; text-underline-offset: 2px">{{ t('founderWall.footer.cta') }} →</router-link>
      </p>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'
import { fiatOnrampService, type PublicStatsResponse } from '@/services/api/fiatOnramp'
import FlareBadge from '@/components/common/FlareBadge.vue'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'
import { flagEmoji } from '@/utils/countries'

const { t } = useI18n()
// the frame's own unit (empty until the frame answers, never another frame's name)
const { localCurrency } = useCurrency()

const stats = ref<PublicStatsResponse | null>(null)
const loading = ref(true)
// §FESUITE (2026-10-05): a failed read drew "0 backers", "0 distributed" and each tier's empty line ("No Founders yet.
// 100 slots remain."); the figures say "—" until read and the tiers say the read failed, with Try again. A failed
// refresh (the poll) keeps what was shown.
const statsFailed = ref(false)
let pollTimer: number | null = null

// 2026-05-10 — tier-grouped wall. Rare → common (Founders first).
// 2026-05-11 §12 — Shadow Chancellor REMOVED from tierOrder; rendered
// separately above the loop as a count-only section. Per Commander: don't
// list shadow backers individually + tighten the copy.
type FlareT = 'sentinel' | 'architect' | 'founder'
const tierOrder = computed<Array<{
  flare: FlareT, label: string, tagline: string, empty: string, hideWhenEmpty?: boolean
}>>(() => [
  { flare: 'founder',   label: t('founderWall.tiers.founders.label'),   tagline: t('founderWall.tiers.founders.tagline', { unit: localCurrency.value }), empty: t('founderWall.tiers.founders.empty') },
  { flare: 'architect', label: t('founderWall.tiers.architects.label'), tagline: t('founderWall.tiers.architects.tagline', { unit: localCurrency.value }), empty: t('founderWall.tiers.architects.empty') },
  { flare: 'sentinel',  label: t('founderWall.tiers.sentinels.label'),  tagline: t('founderWall.tiers.sentinels.tagline'), empty: t('founderWall.tiers.sentinels.empty') },
])

// §19 (2026-05-13) — Shadow Cabinet sample cycles through the unlocked
// encirclement variants every 4 seconds on the public page. Gives the
// public a taste of the variety + makes the Shadow Cabinet preview feel
// alive (vs. static Sauron repeated forever). Locked cosmetic variants
// (phoenix/crystal/blackhole/halloween/inferno/glacier/matrix/galaxy/ink/
// circuit) NOT in the cycle — public page sees only what's actually earned.
const SHADOW_SAMPLE_VARIANTS = [
  'sauron', 'goth', 'obsidian', 'void', 'aurora',
] as const
type ShadowSampleVariant = typeof SHADOW_SAMPLE_VARIANTS[number]
const currentSampleVariant = ref<ShadowSampleVariant>('sauron')
let sampleTimer: number | null = null

// Shadow Cabinet count: prefer backend `shadow_chancellor_count` if shipped,
// else count from recent_backers (fallback for older builds).
const shadowCabinetCount = computed(() => {
  const b = stats.value as any
  if (b && typeof b.shadow_chancellor_count === 'number') {
    return b.shadow_chancellor_count
  }
  return tierBackers('shadow_chancellor' as any).length
})

function tierBackers(t: FlareT) {
  return (stats.value?.recent_backers || []).filter(b => b.flare_tier === t)
}

async function load() {
  try {
    stats.value = await fiatOnrampService.getPublicStats()
    statsFailed.value = false
  } catch {
    if (!stats.value) statsFailed.value = true
  } finally {
    loading.value = false
  }
}

function formatNumber(n: number): string {
  return n.toLocaleString(appLocale(), { maximumFractionDigits: 0 })
}

function formatTimeAgo(minutes: number, seconds: number): string {
  if (seconds < 60) return `${seconds}s ago`
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

onMounted(() => {
  load()
  pollTimer = window.setInterval(load, 30000)
  // §19: cycle Shadow Cabinet sample variant every 4 seconds
  let idx = 0
  sampleTimer = window.setInterval(() => {
    idx = (idx + 1) % SHADOW_SAMPLE_VARIANTS.length
    currentSampleVariant.value = SHADOW_SAMPLE_VARIANTS[idx]
  }, 4000)
})

import { onUnmounted } from 'vue'
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (sampleTimer) clearInterval(sampleTimer)
})
</script>

<style scoped>
.fw-root {
  max-width: 920px;
  margin: 0 auto;
  padding: 24px 20px 80px;
  position: relative;
  z-index: 1;
}

.fw-hero { text-align: center; margin-bottom: 36px; padding-top: 8px; }
.fw-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px 5px 10px;
  background: rgba(245, 158, 11, 0.08);
  border: 1px solid rgba(245, 158, 11, 0.32);
  border-radius: 99px;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgb(252, 211, 77);
  margin-bottom: 18px;
}
.fw-chip-dot {
  width: 6px; height: 6px;
  background: rgb(252, 211, 77);
  border-radius: 50%;
  animation: fw-pulse-dot 2.4s ease-in-out infinite;
}
@keyframes fw-pulse-dot {
  0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.55); }
  50%      { box-shadow: 0 0 0 6px rgba(245, 158, 11, 0); }
}
.fw-h1 {
  font-size: 42px;
  font-weight: 600;
  margin: 0 0 14px;
  letter-spacing: -0.025em;
  line-height: 1.1;
}
.fw-h1-accent {
  background: linear-gradient(135deg, rgb(252, 211, 77), rgba(245, 158, 11, 0.85));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  font-style: italic;
  font-weight: 500;
}
.fw-tagline {
  font-size: 15px;
  line-height: 1.55;
  opacity: 0.78;
  max-width: 580px;
  margin: 0 auto 24px;
}
.fw-totals {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 32px;
  margin: 18px 0 22px;
}
.fw-total-item { text-align: center; }
.fw-total-num {
  font-size: 32px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1.1;
}
.fw-total-label {
  font-size: 10px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  opacity: 0.55;
  margin-top: 4px;
}
.fw-back-cta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.fw-loading {
  text-align: center;
  padding: 30px;
  font-size: 13px;
  opacity: 0.7;
}
.fw-spin { animation: fw-spin 1s linear infinite; }
@keyframes fw-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

.fw-section {
  background: var(--nc-surface, rgba(0, 0, 0, 0.40));
  border: 1px solid var(--nc-border, rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18));
  border-radius: 14px;
  padding: 22px 22px 20px;
  margin-bottom: 18px;
  backdrop-filter: blur(6px);
}
.fw-section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}
.fw-section-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}
.fw-section-sub {
  margin: 4px 0 0;
  font-size: 12.5px;
  opacity: 0.65;
}
.fw-counter {
  font-family: ui-monospace, monospace;
  font-size: 12px;
  letter-spacing: 0.05em;
  opacity: 0.68;
  white-space: nowrap;
  flex-shrink: 0;
}

.fw-progress {
  height: 8px;
  background: rgba(255, 255, 255, 0.05);
  border-radius: 99px;
  overflow: hidden;
  position: relative;
  margin: 6px 0 8px;
}
.fw-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, rgba(245, 158, 11, 0.65), rgb(253, 224, 71));
  border-radius: 99px;
  box-shadow: 0 0 8px rgba(253, 224, 71, 0.5);
  transition: width 600ms ease;
}
.fw-progress-label {
  font-size: 12px;
  opacity: 0.7;
  margin: 4px 0 0;
}
.fw-progress-label strong { color: rgb(252, 211, 77); font-weight: 600; }

.fw-feed {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.fw-feed-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.20);
  border: 1px solid rgba(255, 255, 255, 0.03);
  border-radius: 8px;
  font-size: 13px;
  transition: border-color 200ms ease;
}
.fw-feed-row:hover {
  border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.20);
}
/* Flag-frame "ID stamp" container. Matches the same component on the
   landing chip + BuyAVT preview so the wall feels continuous across views. */
.flag-frame {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 17px;
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 3px;
  background: rgba(0, 0, 0, 0.32);
  overflow: hidden;
  flex-shrink: 0;
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.02),
    0 1px 2px rgba(0, 0, 0, 0.3);
}
.flag-frame > .flag-glyph {
  font-family: 'Apple Color Emoji', 'Segoe UI Emoji', 'Noto Color Emoji', sans-serif;
  font-size: 14px;
  line-height: 1;
  display: block;
  filter: saturate(0.92);
  transform: translateY(-0.5px);
}
.fw-feed-name {
  font-family: 'IBM Plex Sans', sans-serif;
  font-weight: 600;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.92);
  letter-spacing: 0.005em;
  max-width: 22ch;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fw-feed-name-anon {
  color: rgba(255, 255, 255, 0.4);
  font-style: italic;
  font-weight: 500;
}
.fw-feed-amount {
  flex: 1;
  font-variant-numeric: tabular-nums;
  font-weight: 500;
  opacity: 0.92;
  text-align: right;
}
.fw-feed-time {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  opacity: 0.55;
  white-space: nowrap;
}
.fw-feed-fresh {
  display: inline-block;
  padding: 2px 8px;
  font-family: ui-monospace, monospace;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: rgb(110, 231, 183);
  background: rgba(16, 185, 129, 0.10);
  border: 1px solid rgba(16, 185, 129, 0.30);
  border-radius: 4px;
}
.fw-empty {
  text-align: center;
  padding: 18px 16px;
  opacity: 0.5;
  font-size: 12px;
  font-style: italic;
}

/* Tier sections — rare to common, each with its own accent. */
.fw-tier-section {
  margin-bottom: 28px;
  padding: 16px 18px 18px;
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.012);
  position: relative;
  overflow: hidden;
}
.fw-tier-section::before {
  content: '';
  position: absolute; top: 0; left: 0; right: 0;
  height: 2px;
  opacity: 0.5;
}
.fw-tier-founder::before    { background: linear-gradient(90deg, transparent, #fbbf24, transparent); opacity: 0.85; }
.fw-tier-architect::before  { background: linear-gradient(90deg, transparent, #10b981, transparent); }
.fw-tier-sentinel::before   { background: linear-gradient(90deg, transparent, var(--nc-primary, #00d2d2), transparent); }

.fw-tier-founder {
  background: linear-gradient(180deg, rgba(245, 158, 11, 0.025) 0%, rgba(245, 158, 11, 0.005) 100%);
  border-color: rgba(245, 158, 11, 0.18);
}
.fw-tier-header { margin-bottom: 14px; }
.fw-tier-title-row { display: flex; align-items: center; gap: 10px; margin-bottom: 4px; }
.fw-tier-title {
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: rgba(255, 255, 255, 0.94);
}
.fw-tier-founder .fw-tier-title    { color: rgb(252, 211, 77); }
.fw-tier-architect .fw-tier-title  { color: rgb(52, 211, 153); }
.fw-tier-sentinel .fw-tier-title   { color: var(--nc-primary, #00d2d2); }
.fw-tier-count {
  margin-left: auto;
  font-family: ui-monospace, monospace;
  font-size: 12px;
  letter-spacing: 0.04em;
  padding: 3px 10px;
  border-radius: 100px;
  background: rgba(255, 255, 255, 0.04);
  color: rgba(255, 255, 255, 0.6);
  font-variant-numeric: tabular-nums;
}
.fw-tier-sub {
  margin: 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.45);
  line-height: 1.55;
}

.fw-footer {
  text-align: center;
  margin-top: 28px;
  padding: 18px 16px;
  font-size: 12px;
  opacity: 0.66;  /* §FESUITE: the backer link at 4.9:1 (0.62 put it at 4.47:1) */
}
.fw-footer a {
  color: var(--nc-primary, #00d2d2);
  text-decoration: none;
}
.fw-footer a:hover { text-decoration: underline; text-underline-offset: 3px; }

@media (max-width: 640px) {
  .fw-h1 { font-size: 30px; }
  .fw-totals { gap: 22px; }
  .fw-total-num { font-size: 24px; }
  .fw-section-head { flex-direction: column; }
  .fw-feed-row { flex-wrap: wrap; }
}

/* ── SHADOW CABINET (count-only section, 2026-05-11 §12) ────── */
.fw-tier-shadow-cabinet {
  border-color: rgba(88, 28, 135, 0.3);
  background:
    radial-gradient(ellipse at 50% 20%, rgba(67, 20, 110, 0.08), transparent 70%),
    rgba(8, 2, 14, 0.35);
}
.fw-shadow-header {
  display: flex; align-items: center; gap: 18px;
  flex-wrap: wrap;
}
.fw-shadow-sample { flex-shrink: 0; }
.fw-shadow-text { flex: 1; min-width: 240px; }
.fw-shadow-title-row {
  display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap;
  margin-bottom: 6px;
}
.fw-tier-shadow-cabinet .fw-tier-title {
  color: rgb(196, 181, 253);
}
.fw-shadow-count {
  font-family: var(--mono);
  font-size: 22px;
  font-weight: 600;
  color: rgb(196, 181, 253);
  letter-spacing: 0.04em;
  background: transparent;
  border: 0;
  padding: 0;
}
.fw-shadow-sub {
  color: var(--text-secondary);
  font-style: italic;
  max-width: 640px;
}
@media (max-width: 640px) {
  .fw-shadow-header { gap: 14px; }
}
</style>
