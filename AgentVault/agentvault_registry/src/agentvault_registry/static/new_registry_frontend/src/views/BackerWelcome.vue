<template>
  <div class="bavs-root nc-page">
    <!-- §FLARESHOP (2026-08-16): deep links land here after a Stripe redirect.
         With the euro lane closed there is no session to report, and rendering
         an eternal "pending purchase" would be a lie. A visitor holding a real
         historical session_id still gets their receipt. -->
    <div v-if="laneClosedStray" class="bavs-card" data-testid="bavs-lane-gate">
      <div class="bavs-status">
        <Icon name="mdi:currency-eur-off" class="bavs-status-icon" />
      </div>
      <h1 class="bavs-headline">{{ t('backerWelcomeView.gateTitle', 'The euro lane is closed on this registry') }}</h1>
      <p class="bavs-sub">
        {{ t('backerWelcomeView.gateSub', 'Nothing was purchased and nothing is pending. Flares on this frame are bought with its own currency.') }}
      </p>
      <router-link to="/flare-shop" class="bavs-cta" data-testid="bavs-gate-shop">
        {{ t('backerWelcomeView.gateShop', 'Open the Flare Shop') }}
      </router-link>
    </div>
    <div v-else class="bavs-card">
      <!-- Celebration burst — only on completed -->
      <div v-if="state.status === 'completed'" class="bavs-burst" aria-hidden="true">
        <span v-for="i in 24" :key="i" class="bavs-spark" :style="sparkStyle(i)"></span>
      </div>

      <div
        class="bavs-status"
        :class="[`bavs-status-${state.status}`, state.flareTier ? `bavs-status-flare-${state.flareTier}` : '']"
      >
        <FlareBadge
          v-if="state.status === 'completed' && state.flareTier"
          :tier="state.flareTier"
          size="lg"
          :show-label="false"
        />
        <Icon v-else :name="statusIcon" class="bavs-status-icon" />
      </div>
      <h1 class="bavs-headline">{{ headline }}</h1>
      <p class="bavs-sub">{{ subline }}</p>

      <p
        v-if="state.status === 'completed' && state.flareTier"
        class="bavs-flare-reveal"
        v-html="t('backerWelcomeView.flareReveal', { tier: escapeHtml(flareDisplayName(state.flareTier)) })"
      />


      <div v-if="state.status === 'completed'" class="bavs-receipt">
        <div class="bavs-row">
          <span class="bavs-row-l">{{ t('backerWelcomeView.paid') }}</span>
          <span class="bavs-row-r">€{{ state.eur }}</span>
        </div>
        <div class="bavs-row">
          <span class="bavs-row-l">{{ t('backerWelcomeView.avtCredited', { unit: localCurrency }) }}</span>
          <span class="bavs-row-r bavs-row-emph">{{ state.avt }} {{ localCurrency }}</span>
        </div>
        <div class="bavs-row">
          <span class="bavs-row-l">{{ t('backerWelcomeView.tier') }}</span>
          <span class="bavs-row-r">{{ state.tier }}</span>
        </div>
        <div v-if="state.agent_did" class="bavs-row">
          <span class="bavs-row-l">{{ t('backerWelcomeView.agent') }}</span>
          <span class="bavs-row-r bavs-mono">{{ truncMid(state.agent_did, 14) }}</span>
        </div>
        <div v-if="state.tx_id" class="bavs-row">
          <span class="bavs-row-l">{{ t('backerWelcomeView.transaction') }}</span>
          <span class="bavs-row-r bavs-mono">{{ truncMid(state.tx_id, 14) }}</span>
        </div>
      </div>

      <div v-else-if="state.status === 'failed'" class="bavs-error">
        <p>{{ t('backerWelcomeView.errorContact') }}
        <a href="mailto:support@theprotocol.cloud">support@theprotocol.cloud</a>
        {{ t('backerWelcomeView.errorWithSession') }}</p>
        <code class="bavs-mono">{{ stripeSessionId }}</code>
      </div>

      <div v-else-if="state.status === 'pending'" class="bavs-pending">
        <p>{{ t('backerWelcomeView.pendingDetails', { unit: localCurrency }) }}</p>
      </div>

      <div v-if="state.anonymous && state.status === 'completed'" class="bavs-magic-link">
        <Icon name="mdi:email-fast" class="bavs-mail-icon" />
        <div>
          <p class="bavs-magic-l1">{{ t('backerWelcomeView.checkEmail') }}</p>
          <p class="bavs-magic-l2"
             v-html="t('backerWelcomeView.checkEmailDetails', { email: escapeHtml(state.email_hint || t('backerWelcomeView.yourAddress')) })"
          />
        </div>
      </div>

      <div class="bavs-actions">
        <button
          v-if="state.status === 'completed' && !state.anonymous"
          class="nc-btn nc-btn-primary"
          @click="goWallet"
        >
          <Icon name="mdi:wallet" /> {{ t('backerWelcomeView.openWallet') }}
        </button>
        <router-link
          v-if="state.status === 'completed' && state.flareTier && !state.anonymous"
          to="/flare-manager"
          class="nc-btn nc-btn-secondary"
        >
          <Icon name="mdi:shield-star-outline" /> {{ t('backerWelcomeView.viewMyFlare') }}
        </router-link>
        <button
          v-if="state.status === 'failed'"
          class="nc-btn"
          @click="goBuyAgain"
        >
          <Icon name="mdi:refresh" /> {{ t('backerWelcomeView.tryAgain') }}
        </button>
        <router-link to="/leaderboard" class="nc-btn nc-btn-ghost">
          <Icon name="mdi:home" /> {{ t('backerWelcomeView.home') }}
        </router-link>
      </div>

      <p v-if="state.status === 'pending'" class="bavs-poll-counter">
        {{ t('backerWelcomeView.pollCounter', { count: pollCount, sec: lastCheckSec }) }}
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { escapeHtml } from '@/utils/escapeHtml'
import { loadRegistryConfig } from '@/composables/useRegistryConfig'
import { ref, computed, onMounted, onUnmounted, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fiatOnrampService } from '@/services/api/fiatOnramp'
import Icon from '@/components/Icon.vue'
import FlareBadge from '@/components/common/FlareBadge.vue'
import { useI18n } from '@/composables/useI18n'
import { useCurrency } from '@/composables/useCurrency'

type FlareTier = 'sentinel' | 'architect' | 'founder'

const { t } = useI18n()
// §FESUITE (81's ask): the credited amount names the frame's own unit (empty until the frame answers), not AVT
const { localCurrency } = useCurrency()
const route = useRoute()
const router = useRouter()

const stripeSessionId = computed<string>(() => {
  const s = route.query.session_id
  return Array.isArray(s) ? (s[0] || '') : (s || '')
})

// §FLARESHOP — is the euro lane live here? Same public channel the sidebar and
// the shop use. Defaults false while in flight, so a closed lane never flashes
// a purchase state it cannot deliver.
const fiatEnabled = ref(true)
const laneClosedStray = computed(() => !fiatEnabled.value && !stripeSessionId.value)

const state = reactive({
  status: 'pending' as 'pending' | 'completed' | 'failed' | 'refunded',
  eur: '—',
  avt: '—',
  tier: '—',
  agent_did: null as string | null,
  tx_id: null as string | null,
  anonymous: false,
  email_hint: null as string | null,
  flareTier: null as FlareTier | null,
})

function flareDisplayName(tier: FlareTier): string {
  return ({
    sentinel: t('backerWelcomeView.tiers.sentinel'),
    architect: t('backerWelcomeView.tiers.architect'),
    founder: t('backerWelcomeView.tiers.founder'),
  } as Record<string, string>)[tier] || ''
}

// Spark positions — pre-randomized at module load so re-renders are stable.
const SPARK_SEEDS = Array.from({ length: 24 }, (_, i) => ({
  angle: (i / 24) * 360 + (Math.random() - 0.5) * 12,
  distance: 80 + Math.random() * 40,
  delay: Math.random() * 0.4,
  duration: 1.4 + Math.random() * 0.8,
  hue: Math.random() > 0.7 ? 'gold' : 'cyan',
}))

function sparkStyle(i: number): Record<string, string> {
  const s = SPARK_SEEDS[i - 1] || SPARK_SEEDS[0]
  const x = Math.cos(s.angle * Math.PI / 180) * s.distance
  const y = Math.sin(s.angle * Math.PI / 180) * s.distance
  return {
    '--bavs-spark-x': `${x.toFixed(1)}px`,
    '--bavs-spark-y': `${y.toFixed(1)}px`,
    '--bavs-spark-delay': `${s.delay}s`,
    '--bavs-spark-duration': `${s.duration}s`,
    '--bavs-spark-color': s.hue === 'gold' ? 'rgb(253, 224, 71)' : 'var(--nc-primary, #00d2d2)',
  }
}
const pollCount = ref(0)
const lastCheckSec = ref(0)
let pollTimer: number | null = null
let tickTimer: number | null = null

const statusIcon = computed(() => ({
  pending: 'mdi:loading',
  completed: 'mdi:check-circle',
  failed: 'mdi:alert-circle',
  refunded: 'mdi:cash-refund',
}[state.status]))

const headline = computed(() => ({
  pending: t('backerWelcomeView.headline.pending'),
  completed: state.anonymous ? t('backerWelcomeView.headline.completedAnon') : t('backerWelcomeView.headline.completed', { unit: localCurrency.value }),
  failed: t('backerWelcomeView.headline.failed'),
  refunded: t('backerWelcomeView.headline.refunded'),
}[state.status]))

const subline = computed(() => ({
  pending: t('backerWelcomeView.subline.pending'),
  completed: state.anonymous
    ? t('backerWelcomeView.subline.completedAnon', { unit: localCurrency.value })
    : t('backerWelcomeView.subline.completed', { unit: localCurrency.value }),
  failed: t('backerWelcomeView.subline.failed'),
  refunded: t('backerWelcomeView.subline.refunded'),
}[state.status]))

function truncMid(s: string, head = 12, tail = 8): string {
  if (!s || s.length <= head + tail + 1) return s
  return `${s.slice(0, head)}…${s.slice(-tail)}`
}

async function poll() {
  if (!stripeSessionId.value) return
  try {
    const p = await fiatOnrampService.getPurchase(stripeSessionId.value)
    state.status = p.status
    state.eur = p.eur_amount
    state.avt = p.avt_amount
    state.tier = p.tier_label
    state.agent_did = p.agent_did
    state.tx_id = p.avt_transfer_tx_id
    state.anonymous = p.anonymous_flow
    state.flareTier = (p.flare_tier as FlareTier | null) || null
  } catch (e: any) {
    if (e?.response?.status === 404) {
      state.status = 'failed'
    }
  }
  pollCount.value++
  lastCheckSec.value = 0
  if (state.status === 'pending' || state.status === 'failed' && pollCount.value < 3) {
    pollTimer = window.setTimeout(poll, 3000)
  }
}

function goWallet() {
  router.push('/my-agents')
}

function goBuyAgain() {
  router.push('/become-a-backer')
}

onMounted(async () => {
  try {
    // §FEFRAME W2: the ONE shared config read (useRegistryConfig), not a request of its own
    fiatEnabled.value = !!(await loadRegistryConfig()).fiat_onramp_enabled
  } catch { /* leave as-is; a stray visit then behaves exactly as before */ }
})
onMounted(() => {
  if (!stripeSessionId.value) {
    state.status = 'failed'
    return
  }
  poll()
  tickTimer = window.setInterval(() => { lastCheckSec.value++ }, 1000)
})

onUnmounted(() => {
  if (pollTimer) clearTimeout(pollTimer)
  if (tickTimer) clearInterval(tickTimer)
})
</script>

<style scoped>
.bavs-root {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32px 16px;
}
/* §FLARESHOP — the closed-lane CTA on a stray success visit. */
.bavs-cta {
  display: inline-flex; align-items: center; gap: 0.4rem; margin-top: 1.2rem;
  padding: 0.55rem 1.05rem; border-radius: 0.45rem; font-size: 0.86rem; font-weight: 600;
  border: 1px solid rgba(167, 139, 250, 0.45); background: rgba(167, 139, 250, 0.12); color: #c4b5fd;
}
.bavs-cta:hover { background: rgba(167, 139, 250, 0.2); }

.bavs-card {
  width: 100%;
  max-width: 520px;
  background: var(--nc-surface, rgba(0, 0, 0, 0.4));
  border: 1px solid var(--nc-border, rgba(var(--nc-primary-rgb, 0, 210, 210), 0.18));
  border-radius: 14px;
  padding: 36px 32px;
  text-align: center;
  backdrop-filter: blur(6px);
  position: relative;
  overflow: visible;
}

/* ── Celebration burst (only renders on completed) ─────────── */
.bavs-burst {
  position: absolute;
  top: 76px;
  left: 50%;
  width: 0; height: 0;
  pointer-events: none;
  z-index: 1;
}
.bavs-spark {
  position: absolute;
  top: 0; left: 0;
  width: 6px; height: 6px;
  background: var(--bavs-spark-color, var(--nc-primary, #00d2d2));
  border-radius: 50%;
  box-shadow: 0 0 6px 1px var(--bavs-spark-color, var(--nc-primary, #00d2d2));
  transform: translate(-50%, -50%);
  opacity: 0;
  animation: bavs-spark-fly var(--bavs-spark-duration, 1.6s)
    cubic-bezier(.15,.6,.3,.9) var(--bavs-spark-delay, 0s) forwards;
}
@keyframes bavs-spark-fly {
  0%   { opacity: 0;   transform: translate(-50%, -50%) scale(0.4); }
  20%  { opacity: 1;   transform: translate(-50%, -50%) scale(1); }
  85%  { opacity: 0.8; }
  100% {
    opacity: 0;
    transform: translate(
      calc(-50% + var(--bavs-spark-x, 0px)),
      calc(-50% + var(--bavs-spark-y, 0px))
    ) scale(0.6);
  }
}
@media (prefers-reduced-motion: reduce) {
  .bavs-spark { animation: none !important; opacity: 0 !important; }
}

.bavs-flare-reveal {
  margin: -8px 0 18px;
  font-size: 13px;
  letter-spacing: 0.04em;
  opacity: 0.92;
}
.bavs-flare-reveal strong {
  font-weight: 600;
  color: var(--nc-primary, #00d2d2);
}
.bavs-status-flare-founder + .bavs-headline + .bavs-sub + .bavs-flare-reveal strong {
  color: rgb(253, 224, 71);
}
.bavs-status {
  display: inline-flex;
  width: 80px; height: 80px;
  border-radius: 50%;
  align-items: center; justify-content: center;
  margin: 0 auto 18px;
}
.bavs-status-icon { font-size: 48px; }
.bavs-status-pending {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10);
  color: var(--nc-primary, #00d2d2);
}
.bavs-status-pending .bavs-status-icon { animation: bavs-spin 1.2s linear infinite; }
.bavs-status-completed {
  background: rgba(16, 185, 129, 0.12);
  color: rgb(16, 185, 129);
}
.bavs-status-failed, .bavs-status-refunded {
  background: rgba(239, 68, 68, 0.12);
  color: rgb(239, 68, 68);
}
@keyframes bavs-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }

.bavs-headline {
  font-size: 22px;
  font-weight: 600;
  margin: 0 0 6px;
  letter-spacing: -0.01em;
}
.bavs-sub {
  font-size: 14px;
  opacity: 0.75;
  margin: 0 0 24px;
  line-height: 1.5;
}
.bavs-receipt {
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid var(--nc-border, rgba(var(--nc-primary-rgb, 0, 210, 210), 0.10));
  border-radius: 10px;
  padding: 16px 20px;
  text-align: left;
  margin-bottom: 24px;
}
.bavs-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px dashed rgba(255,255,255,0.06);
  font-size: 13px;
}
.bavs-row:last-child { border-bottom: none; }
.bavs-row-l { opacity: 0.7; }
.bavs-row-r { font-variant-numeric: tabular-nums; }
.bavs-row-emph {
  color: var(--nc-primary, #00d2d2);
  font-weight: 600;
  font-size: 15px;
}
.bavs-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}
.bavs-error {
  background: rgba(239, 68, 68, 0.07);
  border: 1px solid rgba(239, 68, 68, 0.25);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 18px;
  text-align: left;
  font-size: 13px;
}
.bavs-error code { display: block; margin-top: 8px; word-break: break-all; }
.bavs-pending {
  font-size: 13px;
  opacity: 0.7;
  margin-bottom: 18px;
}
.bavs-magic-link {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.05);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.20);
  border-radius: 8px;
  padding: 14px 16px;
  margin: 0 0 24px;
  text-align: left;
}
.bavs-mail-icon {
  font-size: 24px;
  color: var(--nc-primary, #00d2d2);
  margin-top: 2px;
  flex-shrink: 0;
}
.bavs-magic-l1 { font-size: 14px; font-weight: 600; margin: 0 0 2px; }
.bavs-magic-l2 { font-size: 13px; opacity: 0.8; margin: 0; line-height: 1.45; }

.bavs-actions {
  display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;
}
.bavs-poll-counter {
  font-size: 11px;
  opacity: 0.5;
  margin: 18px 0 0;
}
</style>
