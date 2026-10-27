<template>
<div class="op">
  <!-- Ambient lives globally in DashboardLayout (<ViewAmbient />). Per-view
       ambient blocks would double the grid+beam. Don't add one here. -->

  <!-- ════════════════════════════════════════════════════════════
       HERO — pitch the flare, not the registry
       ════════════════════════════════════════════════════════════ -->
  <section class="op-hero">
    <!-- Decorative starfield + topology hint (z-index below content) -->
    <div class="op-hero-decor" aria-hidden="true">
      <span v-for="i in 24" :key="'st-'+i" class="op-star" :style="starStyle(i)"></span>
      <svg class="op-hero-topo" viewBox="0 0 800 360" preserveAspectRatio="none">
        <defs>
          <radialGradient id="op-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stop-color="rgba(var(--nc-primary-rgb), 0.18)" />
            <stop offset="100%" stop-color="rgba(var(--nc-primary-rgb), 0)" />
          </radialGradient>
        </defs>
        <ellipse cx="640" cy="80" rx="180" ry="80" fill="url(#op-glow)" />
        <ellipse cx="160" cy="280" rx="200" ry="90" fill="url(#op-glow)" />
        <!-- Faint topology lines hinting at federation -->
        <line x1="120" y1="120" x2="280" y2="180" stroke="rgba(var(--nc-primary-rgb), 0.08)" stroke-width="1"/>
        <line x1="280" y1="180" x2="500" y2="120" stroke="rgba(var(--nc-primary-rgb), 0.08)" stroke-width="1"/>
        <line x1="500" y1="120" x2="640" y2="220" stroke="rgba(var(--nc-primary-rgb), 0.08)" stroke-width="1"/>
        <line x1="280" y1="180" x2="380" y2="280" stroke="rgba(var(--nc-primary-rgb), 0.06)" stroke-width="1"/>
        <line x1="640" y1="220" x2="720" y2="300" stroke="rgba(var(--nc-primary-rgb), 0.06)" stroke-width="1"/>
        <!-- Federation node dots -->
        <circle cx="120" cy="120" r="2.5" fill="rgba(var(--nc-primary-rgb), 0.4)"/>
        <circle cx="280" cy="180" r="3" fill="rgba(var(--nc-primary-rgb), 0.55)"/>
        <circle cx="500" cy="120" r="2.5" fill="rgba(var(--nc-primary-rgb), 0.4)"/>
        <circle cx="640" cy="220" r="3" fill="rgba(var(--nc-primary-rgb), 0.55)"/>
        <circle cx="380" cy="280" r="2" fill="rgba(var(--nc-primary-rgb), 0.3)"/>
        <circle cx="720" cy="300" r="2" fill="rgba(var(--nc-primary-rgb), 0.3)"/>
      </svg>
    </div>

    <div class="op-hero-inner">
      <div class="op-chip">
        <span class="op-chip-dot"></span>
        {{ t('operatorPageView.hero.chip') }}
      </div>
      <h1 class="op-h1">{{ t('operatorPageView.hero.h1a') }}<br/><span class="op-h1-accent">{{ t('operatorPageView.hero.h1Accent') }}</span></h1>
      <p class="op-lead">{{ t('operatorPageView.hero.lead') }}</p>
      <div class="op-hero-acts">
        <!-- §OPPAGE (2026-10-02, his words "cloud operators are free for testing there is no fiat lane anymore"):
             the euro backing button is gone; the first door is the free test operator. -->
        <button type="button" class="op-btn op-btn-primary" @click="setTab('cloud')">
          <span>{{ t('operatorPageView.ctas.tryCloud') }}</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
        </button>
        <button type="button" class="op-btn op-btn-ghost" @click="setTab('self-hosted')">
          <span>{{ t('operatorPageView.ctas.selfHost') }}</span>
        </button>
        <router-link to="/operator-portal" class="op-btn op-btn--cloud">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1"/>
            <rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/>
            <rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
          <span>{{ t('operatorPageView.ctas.ownerPortal') }}</span>
        </router-link>
      </div>
      <div class="op-hero-proof" ref="proofRef">
        <div
          class="op-proof-item"
          v-for="(p, i) in proofPoints"
          :key="p.label"
          :class="{ 'op-proof-item--visible': proofVisible }"
          :style="{ transitionDelay: (i * 90) + 'ms' }"
        >
          <span class="op-proof-val">{{ animatedProof[i] }}</span>
          <span class="op-proof-lbl">{{ p.label }}</span>
        </div>
      </div>
    </div>
    <!-- Hero scroll cue -->
    <div class="op-hero-cue" aria-hidden="true">
      <span class="op-hero-cue-lbl">{{ t('operatorPageView.scroll') }}</span>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 4v14M5 12l7 7 7-7"/>
      </svg>
    </div>
  </section>

  <!-- ════════════════════════════════════════════════════════════
       TAB BAR — sticky, deep-linkable via ?tab=
       ════════════════════════════════════════════════════════════ -->
  <nav class="op-tabs" role="tablist" aria-label="Operator routes" ref="tabsRef">
    <button
      v-for="(tab, i) in tabs"
      :key="tab.id"
      role="tab"
      :aria-selected="activeTab === tab.id"
      :class="['op-tab', { 'op-tab--active': activeTab === tab.id }]"
      @click="setTab(tab.id)"
      :ref="el => { if (el) tabRefs[i] = el as HTMLButtonElement }"
    >
      <span class="op-tab-eyebrow">{{ tab.eyebrow }}</span>
      <span class="op-tab-label">{{ tab.label }}</span>
    </button>
    <!-- Animated underline slider — translates between tabs -->
    <span
      class="op-tab-slider"
      :style="{
        width: sliderWidth + 'px',
        transform: `translateX(${sliderX}px)`,
      }"
      aria-hidden="true"
    ></span>
  </nav>

  <!-- ════════════════════════════════════════════════════════════
       TAB: OVERVIEW — the math + scope grid
       ════════════════════════════════════════════════════════════ -->
  <Transition name="op-fade" mode="out-in">
  <section v-show="activeTab === 'overview'" class="op-sec" key="overview">
    <div class="op-sec-head">
      <span class="op-eyebrow">{{ t('operatorPageView.scope.eyebrow') }}</span>
      <h2 class="op-h2">{{ t('operatorPageView.scope.h2') }}</h2>
      <p class="op-sub">{{ t('operatorPageView.scope.sub') }}</p>
    </div>

    <div class="op-scope-grid">
      <button class="op-scope-card op-scope-card--cloud op-scope-card--clickable" :style="{ '--idx': 0 }" @click="setTab('cloud')">
        <span class="op-scope-corner op-scope-corner--cloud" aria-hidden="true">{{ t('operatorPageView.scope.cloudCorner') }}</span>
        <div class="op-scope-tag">{{ t('operatorPageView.scope.cloudTag') }}</div>
        <h3 class="op-scope-title">{{ t('operatorPageView.scope.cloudTitle') }}</h3>
        <p class="op-scope-desc" v-html="t('operatorPageView.scope.cloudDesc')"></p>
        <span class="op-scope-jump">{{ t('operatorPageView.scope.cloudJump') }} <span class="op-arr">→</span></span>
      </button>

      <button class="op-scope-card op-scope-card--free op-scope-card--clickable" :style="{ '--idx': 1 }" @click="setTab('self-hosted')">
        <span class="op-scope-corner op-scope-corner--free" aria-hidden="true">{{ t('operatorPageView.scope.freeCorner') }}</span>
        <div class="op-scope-tag op-scope-tag--free">{{ t('operatorPageView.scope.freeTag') }}</div>
        <h3 class="op-scope-title">{{ t('operatorPageView.scope.freeTitle') }}</h3>
        <p class="op-scope-desc" v-html="t('operatorPageView.scope.freeDesc')"></p>
        <span class="op-scope-jump">{{ t('operatorPageView.scope.freeJump') }} <span class="op-arr">→</span></span>
      </button>

      <button class="op-scope-card op-scope-card--frame op-scope-card--clickable" :style="{ '--idx': 2 }" @click="setTab('frames')">
        <span class="op-scope-corner op-scope-corner--frame" aria-hidden="true">{{ t('operatorPageView.scope.frameCorner') }}</span>
        <div class="op-scope-tag op-scope-tag--frame">{{ t('operatorPageView.scope.frameTag') }}</div>
        <h3 class="op-scope-title">{{ t('operatorPageView.scope.frameTitle') }}</h3>
        <p class="op-scope-desc" v-html="t('operatorPageView.scope.frameDesc')"></p>
        <span class="op-scope-jump">{{ t('operatorPageView.scope.frameJump') }} <span class="op-arr">→</span></span>
      </button>
    </div>
  </section>
  </Transition>

  <!-- ════════════════════════════════════════════════════════════
       TAB: CLOUD: hosted by us, free for testing (§OPPAGE)
       ════════════════════════════════════════════════════════════ -->
  <Transition name="op-fade" mode="out-in">
  <section v-show="activeTab === 'cloud'" class="op-sec" key="cloud">
    <div class="op-sec-head">
      <span class="op-eyebrow">{{ t('operatorPageView.cloud.eyebrow') }}</span>
      <h2 class="op-h2">{{ t('operatorPageView.cloud.h2') }}</h2>
      <p class="op-sub">
        {{ t('operatorPageView.cloud.sub') }}
      </p>
    </div>

    <div class="op-cards-2col">
      <div class="op-card">
        <div class="op-card-tag">{{ t('operatorPageView.cloud.whatYouGet') }}</div>
        <ul class="op-card-list">
          <li v-html="t('operatorPageView.cloud.feature1')"></li>
          <li v-html="t('operatorPageView.cloud.feature2')"></li>
          <li v-html="t('operatorPageView.cloud.feature3')"></li>
          <li v-html="t('operatorPageView.cloud.feature4')"></li>
          <li v-html="t('operatorPageView.cloud.feature5')"></li>
          <li v-html="t('operatorPageView.cloud.feature6')"></li>
        </ul>
      </div>

      <div class="op-card">
        <div class="op-card-tag">{{ t('operatorPageView.cloud.howItWorks') }}</div>
        <ol class="op-card-ol">
          <li>{{ t('operatorPageView.cloud.step1') }}</li>
          <li>{{ t('operatorPageView.cloud.step2') }}</li>
          <li v-html="t('operatorPageView.cloud.step3')"></li>
          <li>{{ t('operatorPageView.cloud.step4') }}</li>
          <li>{{ t('operatorPageView.cloud.step5') }}</li>
        </ol>
      </div>
    </div>

    <div class="op-cta-strip">
      <button type="button" class="op-btn op-btn-primary" @click="goApply('cloud')">{{ t('operatorPageView.cloud.ctaApply') }}</button>
      <router-link to="/operator-portal" class="op-btn op-btn-ghost">{{ t('operatorPageView.cloud.ctaPortal') }}</router-link>
    </div>

    <div class="op-callout op-callout--cyan">
      <p class="op-fineprint">
        {{ t('operatorPageView.cloud.fineprint') }}
      </p>
    </div>
  </section>
  </Transition>

  <!-- ════════════════════════════════════════════════════════════
       TAB: SELF-HOSTED: always free (the application form below serves both routes)
       ════════════════════════════════════════════════════════════ -->
  <Transition name="op-fade" mode="out-in">
  <section v-show="activeTab === 'self-hosted'" class="op-sec" key="self-hosted">
    <div class="op-sec-head">
      <span class="op-eyebrow">{{ t('operatorPageView.selfHosted.eyebrow') }}</span>
      <h2 class="op-h2">{{ t('operatorPageView.selfHosted.h2') }}</h2>
      <p class="op-sub">
        {{ t('operatorPageView.selfHosted.sub') }}
      </p>
    </div>

    <div class="op-callout op-callout--cyan">
      <p class="op-fineprint" v-html="t('operatorPageView.selfHosted.fineprint')"></p>
    </div>
  </section>
  </Transition>

  <!-- ════════════════════════════════════════════════════════════
       APPLY: one form for the cloud and the self-hosted route (§OPPAGE 2026-10-02).
       It posts `deployment` ("cloud" | "self_hosted"): the backend keeps it on the
       application, the admin list shows it, and the cloud provisioner writes "cloud".
       ════════════════════════════════════════════════════════════ -->
  <Transition name="op-fade" mode="out-in">
  <section v-show="activeTab === 'cloud' || activeTab === 'self-hosted'" id="op-apply" ref="applyRef" class="op-sec op-apply" key="apply">
    <div class="op-sec-head">
      <span class="op-eyebrow">{{ t('operatorPageView.apply.eyebrow') }}</span>
      <h2 class="op-h2">{{ t('operatorPageView.apply.h2') }}</h2>
      <p class="op-sub">{{ t('operatorPageView.apply.sub') }}</p>
    </div>

    <form class="op-form" @submit.prevent="submitApplication">
      <fieldset class="op-deploy">
        <legend class="op-form-label">{{ t('operatorPageView.apply.deployLabel') }}</legend>
        <div class="op-deploy-opts">
          <label :class="['op-deploy-opt', { 'op-deploy-opt--on': appForm.deployment === 'cloud' }]">
            <input v-model="appForm.deployment" type="radio" name="op-deployment" value="cloud" />
            <span class="op-deploy-title">{{ t('operatorPageView.apply.deployCloud') }}</span>
            <span class="op-deploy-sub">{{ t('operatorPageView.apply.deployCloudSub') }}</span>
          </label>
          <label :class="['op-deploy-opt', { 'op-deploy-opt--on': appForm.deployment === 'self_hosted' }]">
            <input v-model="appForm.deployment" type="radio" name="op-deployment" value="self_hosted" />
            <span class="op-deploy-title">{{ t('operatorPageView.apply.deploySelf') }}</span>
            <span class="op-deploy-sub">{{ t('operatorPageView.apply.deploySelfSub') }}</span>
          </label>
        </div>
      </fieldset>

      <div class="op-form-row">
        <div class="op-form-field">
          <label for="op-app-name" class="op-form-label">{{ t('operatorPageView.selfHosted.formName') }} *</label>
          <input id="op-app-name" ref="appNameRef" v-model="appForm.name" class="op-form-input" required autocomplete="name" :placeholder="t('operatorPageView.selfHosted.formNamePh')" />
        </div>
        <div class="op-form-field">
          <label for="op-app-email" class="op-form-label">{{ t('operatorPageView.selfHosted.formEmail') }} *</label>
          <input id="op-app-email" v-model="appForm.email" type="email" class="op-form-input" required autocomplete="email" placeholder="you@example.com" />
        </div>
      </div>
      <p class="op-form-hint op-form-hint--account" v-html="t('operatorPageView.apply.accountHint')"></p>

      <div class="op-form-row">
        <div class="op-form-field">
          <label for="op-app-org" class="op-form-label">{{ t('operatorPageView.selfHosted.formOrg') }}</label>
          <input id="op-app-org" v-model="appForm.organization" class="op-form-input" autocomplete="organization" :placeholder="t('operatorPageView.selfHosted.formOrgPh')" />
        </div>
        <div class="op-form-field">
          <label for="operatorpage-sel-305" class="op-form-label">{{ t('operatorPageView.selfHosted.formExp') }}</label>
          <select id="operatorpage-sel-305" v-model="appForm.experience" class="op-form-input">
            <option value="beginner">{{ t('operatorPageView.selfHosted.expBeginner') }}</option>
            <option value="intermediate">{{ t('operatorPageView.selfHosted.expIntermediate') }}</option>
            <option value="experienced">{{ t('operatorPageView.selfHosted.expExperienced') }}</option>
          </select>
        </div>
      </div>

      <div class="op-form-field">
        <label for="op-app-usecase" class="op-form-label">{{ t('operatorPageView.selfHosted.formUseCase') }}</label>
        <textarea id="op-app-usecase" v-model="appForm.use_case" class="op-form-input" rows="3" :placeholder="t('operatorPageView.selfHosted.formUseCasePh')"></textarea>
      </div>

      <!-- §FESUITE V0595 (his word 2026-10-11): what the operator runs. It starts as this frame runs it; the frame-exclusive
           settings are shown greyed with the frame's value and cannot be chosen; only what differs is sent -->
      <details v-if="envCatalog?.role === 'frame' || envFailed" class="op-env" data-testid="op-env" :open="envChangedCount > 0">
        <summary class="op-env-summary">
          <span class="op-form-label">{{ t('operatorPageView.apply.envTitle', 'What your operator runs') }}</span>
          <span class="op-env-sub" data-testid="op-env-count">
            {{ envChangedCount
              ? tp('operatorPageView.apply.envChanged', '{n} changed from this frame\'s settings', { n: envChangedCount })
              : t('operatorPageView.apply.envInherit', 'Everything as this frame runs it') }}
          </span>
        </summary>
        <ReadFailedNotice v-if="envFailed" dense :retry="loadEnv"
          :text="t('operatorPageView.apply.envUnread', 'This frame\'s settings could not be read. Your operator would inherit all of them, and you can still apply.')" />
        <FcSwitchBoard v-else-if="envCatalog" :features="opFeatures" :locked="envLocked" :baseline="envBaseline"
          @change="onEnvChange" @reset="resetEnv" />
      </details>

      <label class="op-form-accept">
        <input v-model="appAcceptTerms" type="checkbox" required />
        <span>{{ t('operatorPageView.selfHosted.acceptTerms') }} (<a href="#/legal/operators" target="_blank" rel="noopener noreferrer">{{ t('operatorPageView.apply.readTerms') }}</a>)</span>
      </label>
      <div class="op-form-actions">
        <button type="submit" class="op-btn op-btn-primary" :disabled="appSubmitting">
          {{ appSubmitting ? t('operatorPageView.selfHosted.submitting') : t('operatorPageView.selfHosted.submitBtn') }}
        </button>
        <span v-if="appSuccess" class="op-form-msg op-form-msg--ok" role="status">{{ t('operatorPageView.selfHosted.successMsg') }}</span>
        <span v-if="appError" class="op-form-msg op-form-msg--err" role="alert">{{ appError }}</span>
      </div>
    </form>
  </section>
  </Transition>

  <!-- ════════════════════════════════════════════════════════════
       TAB: FRAMES — sovereign nation pitch (form lives at /frame-commander)
       ════════════════════════════════════════════════════════════ -->
  <Transition name="op-fade" mode="out-in">
  <section v-show="activeTab === 'frames'" class="op-sec" key="frames">
    <div class="op-sec-head">
      <span class="op-eyebrow">{{ t('operatorPageView.frames.eyebrow') }}</span>
      <h2 class="op-h2">{{ t('operatorPageView.frames.h2') }}</h2>
      <p class="op-sub">
        {{ t('operatorPageView.frames.sub1') }}
      </p>
      <p class="op-sub" style="margin-top: 1rem;">
        {{ frameNames ? t('operatorPageView.frames.sub2', { names: frameNames }) : t('operatorPageView.frames.sub2NoNames') }}
      </p>
      <p class="op-money-quote">
        <span class="op-money-rule"></span>
        {{ t('operatorPageView.frames.moneyQuote') }}
        <span class="op-money-rule"></span>
      </p>
    </div>

    <div class="op-cards-2col">
      <div class="op-card">
        <div class="op-card-tag">{{ t('operatorPageView.frames.syncTag') }}</div>
        <h3 class="op-card-title">{{ t('operatorPageView.frames.syncTitle') }}</h3>
        <p class="op-card-desc">
          {{ t('operatorPageView.frames.syncDesc') }}
        </p>
        <ul class="op-card-spec">
          <li>{{ t('operatorPageView.frames.syncSpec1') }}</li>
          <li>{{ t('operatorPageView.frames.syncSpec2') }}</li>
          <li>{{ t('operatorPageView.frames.syncSpec3') }}</li>
        </ul>
      </div>

      <div class="op-card">
        <div class="op-card-tag">{{ t('operatorPageView.frames.asyncTag') }}</div>
        <h3 class="op-card-title">{{ t('operatorPageView.frames.asyncTitle') }}</h3>
        <p class="op-card-desc">
          {{ t('operatorPageView.frames.asyncDesc') }}
        </p>
        <ul class="op-card-spec">
          <li>{{ t('operatorPageView.frames.asyncSpec1') }}</li>
          <li>{{ t('operatorPageView.frames.asyncSpec2') }}</li>
          <li>{{ t('operatorPageView.frames.asyncSpec3') }}</li>
        </ul>
      </div>
    </div>

    <!-- CTA into /frame-commander -->
    <div class="op-frame-cta">
      <div class="op-frame-cta-content">
        <span class="op-frame-cta-eyebrow">{{ t('operatorPageView.frames.ctaEyebrow') }}</span>
        <h3 class="op-frame-cta-title">{{ t('operatorPageView.frames.ctaTitle') }}</h3>
        <p class="op-frame-cta-desc">
          {{ t('operatorPageView.frames.ctaDesc') }}
        </p>
      </div>
      <router-link to="/frame-commander" class="op-btn op-btn-primary">
        <span>{{ t('operatorPageView.frames.ctaTitle') }}</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
      </router-link>
    </div>

    <div class="op-callout op-callout--gold">
      <p class="op-fineprint" v-html="t('operatorPageView.frames.fineprint')"></p>
    </div>
  </section>
  </Transition>

  <!-- ════════════════════════════════════════════════════════════
       FOOTER — fair-trade closing
       ════════════════════════════════════════════════════════════ -->
  <section class="op-sec op-footer-sec">
    <p class="op-footer">
      {{ t('operatorPageView.footer.main') }}
    </p>
    <p class="op-footer-sub">
      {{ t('operatorPageView.footer.sub') }}
    </p>
  </section>
</div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { useAlive } from '@/composables/useAlive'
import { useRouter, useRoute } from 'vue-router'
import axios from 'axios'
import { useI18n } from '@/composables/useI18n'
import { useFrameManifest } from '@/composables/useFrameManifest'
import FcSwitchBoard from '@/components/frameCommander/FcSwitchBoard.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { useOperatorEnvStep } from '@/composables/useOperatorEnvStep'

const { t, tp } = useI18n()
const router = useRouter()
const route = useRoute()

// ─── Tabs ─────────────────────────────────────────────────────────────
const TAB_IDS = ['overview', 'cloud', 'self-hosted', 'frames'] as const
type TabId = typeof TAB_IDS[number]
const tabs = computed<{ id: TabId; label: string; eyebrow: string }[]>(() => [
  { id: 'overview',    label: t('operatorPageView.tabs.overview'),    eyebrow: '01' },
  { id: 'cloud',       label: t('operatorPageView.tabs.cloud'),       eyebrow: '02' },
  { id: 'self-hosted', label: t('operatorPageView.tabs.selfHosted'),  eyebrow: '03' },
  { id: 'frames',      label: t('operatorPageView.tabs.frames'),      eyebrow: '04' },
])

const VALID = new Set<TabId>(TAB_IDS)
const initialTab: TabId =
  (typeof route.query.tab === 'string' && VALID.has(route.query.tab as TabId))
    ? route.query.tab as TabId
    : 'overview'

const activeTab = ref<TabId>(initialTab)

// Refs for the animated underline slider
const tabsRef = ref<HTMLElement | null>(null)
const tabRefs = ref<HTMLButtonElement[]>([])
const sliderX = ref(0)
const sliderWidth = ref(0)

function updateSlider() {
  const idx = tabs.value.findIndex(tab => tab.id === activeTab.value)
  const el = tabRefs.value[idx]
  if (!el || !tabsRef.value) return
  const tabsRect = tabsRef.value.getBoundingClientRect()
  const elRect = el.getBoundingClientRect()
  sliderX.value = elRect.left - tabsRect.left
  sliderWidth.value = elRect.width
}

function setTab(id: TabId) {
  activeTab.value = id
  // Push the query param so deep-linking works (browser back/forward + share).
  router.replace({ path: route.path, query: { ...route.query, tab: id } })
  // Scroll to the top of the tab area so the user sees the new content from the top.
  // Defer one tick so v-show toggles before we measure.
  requestAnimationFrame(() => {
    const tabEl = document.querySelector('.op-tabs') as HTMLElement | null
    if (tabEl) tabEl.scrollIntoView({ behavior: 'smooth', block: 'start' })
    updateSlider()
  })
}

// React to ?tab= changes from elsewhere (deep-links, browser back/forward).
watch(() => route.query.tab, (newTab) => {
  if (typeof newTab === 'string' && VALID.has(newTab as TabId) && activeTab.value !== newTab) {
    activeTab.value = newTab as TabId
    nextTick(updateSlider)
  }
})

// ─── Hero proof points (with tick-up animation on scroll-into-view) ───
// §OPPAGE (2026-10-02): the counts come from the frame manifest the console already reads (registry-config `self` +
// `peers[]`), never a literal: the page said 8 operators while the network ran 4. '…' until the manifest answers.
const fm = useFrameManifest()
const liveCounts = computed(() => {
  const m = fm.manifest.value
  if (!m) return null
  const entries = [m.self, ...(m.peers || [])]
  return {
    operators: entries.filter(e => e && e.role === 'operator').length,
    frames: fm.frames.value.length,
  }
})
// §FESUITE V0578: '…' stayed for good once the manifest read had failed (or the registry stated none): it is '…' only
// while the first read is in flight, and a count nobody read is '—'.
const countUnread = computed(() => (fm.settled.value ? '—' : '…'))
const proofPoints = computed(() => {
  const c = liveCounts.value
  return [
    { label: t('operatorPageView.proof.operatorsLive'), value: c ? String(c.operators) : countUnread.value, numeric: c ? c.operators : null },
    { label: t('operatorPageView.proof.framesPaired'),  value: c ? String(c.frames) : countUnread.value,    numeric: c ? c.frames : null },
    { label: t('operatorPageView.proof.costToTest'),    value: t('operatorPageView.proof.costToTestVal'), numeric: null },
    { label: t('operatorPageView.proof.commanderNaps'), value: '1/day', numeric: null },
  ]
})
const proofRef = ref<HTMLElement | null>(null)
const proofVisible = ref(false)
const animatedProof = ref<string[]>(proofPoints.value.map(p => p.numeric != null ? '0' : p.value))
let proofAnimating = false

let proofObserver: IntersectionObserver | null = null

function animateTickup() {
  const startTs = performance.now()
  const dur = 1400
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (reduced) {
    animatedProof.value = proofPoints.value.map(p => p.value)
    return
  }
  proofAnimating = true
  const step = (ts: number) => {
    const k = Math.min(1, (ts - startTs) / dur)
    const eased = 1 - Math.pow(1 - k, 3) // ease-out cubic
    proofPoints.value.forEach((p, i) => {
      if (p.numeric != null) animatedProof.value[i] = String(Math.round(p.numeric * eased))
    })
    if (k < 1) requestAnimationFrame(step)
    else {
      proofAnimating = false
      animatedProof.value = proofPoints.value.map(p => p.value)
    }
  }
  requestAnimationFrame(step)
}

// The manifest can answer after the strip was shown: show the arrived numbers (no second tick-up).
watch(proofPoints, (pts) => {
  if (!proofVisible.value) {
    animatedProof.value = pts.map(p => p.numeric != null ? '0' : p.value)
  } else if (!proofAnimating) {
    animatedProof.value = pts.map(p => p.value)
  }
})

// ─── Frames tab: the frames that run today, by name, from the manifest ───
const frameNames = computed(() => {
  const names = fm.frames.value.map(f => f.display_name || f.name).filter(Boolean)
  if (names.length < 2) return names[0] || ''
  return names.slice(0, -1).join(', ') + ' ' + t('operatorPageView.frames.listAnd') + ' ' + names[names.length - 1]
})

// ─── The application form (shown below the Cloud and the Self-Hosted tab) ───
// §OPPAGE (2026-10-02, his words "cloud operators are free for testing there is no fiat lane anymore"): the euro
// backing ladder, its tiers, the founder-slot stats and the fiat lane's probe are gone (the lane answers 503 on every
// frame, and the page asked it on every visit). One form serves both routes; `deployment`
// says which, and follows the tab the visitor came from.
type Deployment = 'cloud' | 'self_hosted'
const appForm = ref({
  name: '',
  email: '',
  organization: '',
  experience: 'intermediate',
  use_case: '',
  deployment: (initialTab === 'self-hosted' ? 'self_hosted' : 'cloud') as Deployment,
})
const appSubmitting = ref(false)
const appAcceptTerms = ref(false)   // §LEGALKIT: Operator Terms § 1.2
const appSuccess = ref(false)
const appError = ref('')
const applyRef = ref<HTMLElement | null>(null)
const appNameRef = ref<HTMLInputElement | null>(null)

watch(activeTab, (tab) => {
  if (tab === 'cloud') appForm.value.deployment = 'cloud'
  else if (tab === 'self-hosted') appForm.value.deployment = 'self_hosted'
})

/** Bring the form into view with the route chosen (the Cloud tab's button, and any later caller). */
function goApply(kind: Deployment) {
  const tab: TabId = kind === 'cloud' ? 'cloud' : 'self-hosted'
  if (activeTab.value !== 'cloud' && activeTab.value !== 'self-hosted') setTab(tab)
  appForm.value.deployment = kind
  nextTick(() => {
    requestAnimationFrame(() => {
      applyRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
      appNameRef.value?.focus({ preventScroll: true })
    })
  })
}

// ─── What the operator runs (§FESUITE V0595): the frame's catalog, locked where it is the frame's ───
const { envCatalog, envFailed, opFeatures, envBaseline, envLocked, envChangedCount, choices: envChoices, loadEnv, onEnvChange, resetEnv } =
  useOperatorEnvStep()

async function submitApplication() {
  appError.value = ''
  appSuccess.value = false
  if (!appAcceptTerms.value) {
    appError.value = t('operatorPageView.selfHosted.acceptRequired')
    return
  }
  appSubmitting.value = true
  try {
    await axios.post('/api/v1/operator-applications', {
      ...appForm.value,
      accept_operator_terms: true,   // §LEGALKIT: Operator Terms § 1.2, asked and recorded
      // §FESUITE V0595: only the operator settings chosen differently from this frame's; an unread catalog sends none
      env_choices: envChoices(),
    })
    appAcceptTerms.value = false
    appSuccess.value = true
    resetEnv()
    appForm.value = { name: '', email: '', organization: '', experience: 'intermediate', use_case: '', deployment: appForm.value.deployment }
  } catch (err: any) {
    // a refusal's own sentence when it is one (409 duplicate, 422 terms, 429 rate limit); a 422 list is not
    const detail = err?.response?.data?.detail
    appError.value = (typeof detail === 'string' && detail) || t('operatorPageView.selfHosted.failMsg')
  } finally {
    appSubmitting.value = false
  }
}

// ─── Decorative starfield ─────────────────────────────────────────────
const starSeeds = Array.from({ length: 24 }, (_, i) => ({
  x: (i * 41) % 100,
  y: (i * 67 + 13) % 100,
  size: 1 + (i % 3),
  delay: (i * 220) % 4000,
  duration: 3200 + ((i * 137) % 2200),
}))
function starStyle(i: number) {
  const s = starSeeds[(i - 1) % starSeeds.length]
  return {
    left: s.x + '%',
    top: s.y + '%',
    width: s.size + 'px',
    height: s.size + 'px',
    animationDelay: s.delay + 'ms',
    animationDuration: s.duration + 'ms',
  }
}

// ─── On-mount: honour deep-link, scroll to top, fetch stats ──────────
// §FESUITE (the leave sweep's gate, useAlive.sites.test.ts): the resize listener goes on only while the page is still there
const alive = useAlive()
onMounted(async () => {
  // If user landed on /operator?tab=frames, scroll the tab bar into view
  // so the active tab content is visible (not the hero alone).
  if (initialTab !== 'overview') {
    requestAnimationFrame(() => {
      const tabEl = document.querySelector('.op-tabs') as HTMLElement | null
      if (tabEl) tabEl.scrollIntoView({ behavior: 'instant' as ScrollBehavior, block: 'start' })
    })
  }

  // §FESUITE V0595: what an operator of this frame would run (the configuration step)
  void loadEnv()

  // Wire the underline slider after first render
  await nextTick()
  if (!alive()) return
  updateSlider()
  window.addEventListener('resize', updateSlider)

  // Wire the proof-strip tick-up animation when it scrolls into view
  if (proofRef.value && typeof IntersectionObserver !== 'undefined') {
    proofObserver = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting && !proofVisible.value) {
          proofVisible.value = true
          animateTickup()
          proofObserver?.disconnect()
          break
        }
      }
    }, { threshold: 0.3 })
    proofObserver.observe(proofRef.value)
  } else {
    proofVisible.value = true
    proofPoints.value.forEach((p, i) => { animatedProof.value[i] = p.value })
  }

})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateSlider)
  proofObserver?.disconnect()
})
</script>

<style scoped>
/* ── ROOT ────────────────────────────────────────────────────── */
/* Ambient (cyber-grid + scan beam + radial glows) lives in DashboardLayout's
   global <ViewAmbient />. Per-view ambient blocks would double-render the
   layer; do not re-add. The .op container is transparent so the global
   ambient shows through. */
.op {
  position: relative; min-height: 100vh; color: var(--text);
  background: transparent;
}

/* ── HERO ────────────────────────────────────────────────────── */
.op-hero {
  position: relative; z-index: 1;
  padding: 6rem 2rem 3rem;
  overflow: hidden;
}
.op-hero-decor {
  position: absolute; inset: 0; pointer-events: none;
  z-index: 0;
  -webkit-mask-image: linear-gradient(to bottom, rgba(0,0,0,1) 0%, rgba(0,0,0,0.6) 70%, rgba(0,0,0,0) 100%);
          mask-image: linear-gradient(to bottom, rgba(0,0,0,1) 0%, rgba(0,0,0,0.6) 70%, rgba(0,0,0,0) 100%);
}
.op-hero-topo {
  position: absolute; inset: 0; width: 100%; height: 100%;
  opacity: 0.7;
}
.op-star {
  position: absolute; display: block;
  border-radius: 50%;
  background: rgba(var(--nc-primary-rgb), 0.55);
  box-shadow: 0 0 6px rgba(var(--nc-primary-rgb), 0.6);
  animation: op-star-twinkle 4000ms ease-in-out infinite alternate;
  will-change: opacity, transform;
}
@keyframes op-star-twinkle {
  0%   { opacity: 0.15; transform: scale(0.7); }
  50%  { opacity: 0.85; transform: scale(1.05); }
  100% { opacity: 0.35; transform: scale(0.9); }
}
.op-hero-inner { position: relative; z-index: 1; max-width: 1100px; margin: 0 auto; }
.op-chip {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 14px; border-radius: 4px;
  background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.1em;
  color: var(--nc-primary); text-transform: uppercase; margin-bottom: 1.6rem;
}
.op-chip-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--nc-primary);
  box-shadow: 0 0 8px var(--nc-primary);
  animation: op-chip-pulse 2.4s ease-in-out infinite;
}
@keyframes op-chip-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.55; transform: scale(0.9); }
}
.op-h1 {
  font-size: clamp(40px, 6vw, 72px); font-weight: 600; line-height: 1.05;
  letter-spacing: -0.02em; margin: 0 0 1.2rem; color: #fff;
  text-shadow: 0 0 36px rgba(var(--nc-primary-rgb), 0.2);
}

/* Hero scroll cue (bottom of hero) */
.op-hero-cue {
  position: absolute; bottom: 18px; left: 50%;
  transform: translateX(-50%);
  display: inline-flex; flex-direction: column; align-items: center; gap: 4px;
  color: rgba(var(--nc-primary-rgb), 0.55);
  pointer-events: none;
  z-index: 1;
  animation: op-cue-bounce 2.4s cubic-bezier(0.22, 1, 0.36, 1) infinite;
}
.op-hero-cue svg { width: 16px; height: 16px; }
.op-hero-cue-lbl {
  font-family: var(--mono); font-size: 9px; letter-spacing: 0.2em;
  text-transform: uppercase; opacity: 0.7;
}
@keyframes op-cue-bounce {
  0%, 100% { transform: translateX(-50%) translateY(0);   opacity: 0.55; }
  50%      { transform: translateX(-50%) translateY(5px); opacity: 1; }
}
.op-h1-accent {
  color: var(--nc-primary);
  background: linear-gradient(90deg, var(--nc-primary) 0%, rgba(var(--nc-primary-rgb), 0.7) 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.op-lead {
  font-size: clamp(15px, 1.6vw, 18px); line-height: 1.6; color: var(--text-secondary);
  max-width: 640px; margin: 0 0 2rem;
}
.op-hero-acts {
  display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 2.4rem;
}

/* ── BUTTONS ─────────────────────────────────────────────────── */
.op-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 12px 22px; border-radius: 4px; border: 1px solid;
  font-family: var(--mono); font-size: 13px; font-weight: 600;
  letter-spacing: 0.04em; text-transform: uppercase;
  text-decoration: none; cursor: pointer;
  transition: background 0.2s, border-color 0.2s, color 0.2s, box-shadow 0.2s, transform 0.18s;
}
.op-btn:hover { transform: translateY(-1px); }
.op-btn-primary {
  color: #060a12; background: var(--nc-primary); border-color: var(--nc-primary);
  box-shadow: 0 0 0 rgba(var(--nc-primary-rgb), 0);
}
.op-btn-primary:hover {
  background: rgba(var(--nc-primary-rgb), 0.92);
  box-shadow: 0 8px 28px rgba(var(--nc-primary-rgb), 0.3);
}
.op-btn-primary:disabled { opacity: 0.5; cursor: not-allowed; box-shadow: none; transform: none; }
.op-btn-ghost {
  color: var(--text-bright); border-color: rgba(255,255,255,0.12);
  background: transparent;
}
.op-btn-ghost:hover {
  border-color: rgba(255,255,255,0.25); color: #fff;
  background: rgba(255,255,255,0.03);
}
.op-btn--cloud {
  color: var(--nc-primary); border-color: rgba(var(--nc-primary-rgb), 0.35);
  background: transparent;
}
.op-btn--cloud:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.6);
  background: rgba(var(--nc-primary-rgb), 0.06);
}

/* ── HERO PROOF ──────────────────────────────────────────────── */
.op-hero-proof { display: flex; gap: 36px; flex-wrap: wrap; }
.op-proof-item {
  display: flex; flex-direction: column; gap: 3px;
  opacity: 0; transform: translateY(8px);
  transition: opacity 520ms cubic-bezier(0.22, 1, 0.36, 1),
              transform 520ms cubic-bezier(0.22, 1, 0.36, 1);
}
.op-proof-item--visible { opacity: 1; transform: translateY(0); }
.op-proof-val {
  font-family: var(--mono); font-size: 24px; font-weight: 600;
  color: var(--nc-primary);
  font-variant-numeric: tabular-nums;
  text-shadow: 0 0 12px rgba(var(--nc-primary-rgb), 0.25);
}
.op-proof-lbl { font-size: 10px; letter-spacing: 0.08em; color: var(--muted); text-transform: uppercase; }

/* ── TAB BAR ─────────────────────────────────────────────────── */
.op-tabs {
  position: sticky; top: 0; z-index: 10;
  display: flex; gap: 0;
  max-width: 1100px; margin: 0 auto;
  padding: 14px 2rem 0;
  background: linear-gradient(to bottom, var(--nc-deep) 0%, var(--nc-deep) 70%, transparent 100%);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12);
}
.op-tab {
  background: transparent; border: 0;
  padding: 14px 22px;
  display: flex; flex-direction: column; align-items: flex-start; gap: 2px;
  cursor: pointer; color: var(--muted);
  font-family: var(--mono); text-align: left;
  transition: color 0.22s;
  position: relative;
}
.op-tab:hover { color: var(--text-bright); }
.op-tab--active { color: var(--nc-primary); }
.op-tab-eyebrow {
  font-size: 9px; letter-spacing: 0.18em; opacity: 0.55; text-transform: uppercase;
}
.op-tab-label {
  font-size: 14px; font-weight: 600; letter-spacing: 0.06em;
}
/* Animated underline slider — translates between active tabs */
.op-tab-slider {
  position: absolute;
  left: 0; bottom: -1px;
  height: 2px;
  background: var(--nc-primary);
  box-shadow: 0 0 12px rgba(var(--nc-primary-rgb), 0.6);
  transition: transform 320ms cubic-bezier(0.22, 1, 0.36, 1),
              width    320ms cubic-bezier(0.22, 1, 0.36, 1);
  pointer-events: none;
}

/* ── TAB TRANSITIONS ─────────────────────────────────────────── */
.op-fade-enter-active, .op-fade-leave-active {
  transition: opacity 240ms ease, transform 240ms ease;
}
.op-fade-enter-from { opacity: 0; transform: translateY(8px); }
.op-fade-leave-to   { opacity: 0; transform: translateY(-4px); }

/* ── SECTIONS (tab panels) ───────────────────────────────────── */
.op-sec {
  max-width: 1100px; margin: 0 auto; padding: 4rem 2rem;
  position: relative; z-index: 1;
}
.op-sec-head { margin-bottom: 2.5rem; }
.op-eyebrow {
  display: inline-block;
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.18em;
  color: var(--nc-primary); text-transform: uppercase;
  margin-bottom: 12px; opacity: 0.85;
}
.op-h2 {
  font-size: clamp(24px, 3vw, 32px); font-weight: 600; color: #fff; margin: 0 0 8px;
  letter-spacing: -0.01em;
}
.op-sub { font-size: 14px; color: var(--text-secondary); line-height: 1.7; max-width: 720px; }
.op-fineprint {
  font-size: 12px; color: var(--muted); line-height: 1.65; margin: 0;
  max-width: 760px; font-style: italic;
}

/* ── CALLOUTS (replaces plain fineprint blocks) ──────────────── */
.op-callout {
  margin: 2rem 0 0;
  padding: 16px 18px;
  border-left: 3px solid;
  border-radius: 4px;
  background: rgba(255,255,255, 0.015);
}
.op-callout--cyan {
  border-left-color: rgba(var(--nc-primary-rgb), 0.65);
  background: rgba(var(--nc-primary-rgb), 0.025);
}
.op-callout--gold {
  border-left-color: rgba(255, 196, 76, 0.55);
  background: rgba(255, 196, 76, 0.025);
}
.op-callout .op-fineprint { color: var(--text-secondary); }

/* ── SCOPE GRID (Overview tab) ───────────────────────────────── */
.op-scope-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px;
}
.op-scope-card {
  position: relative; overflow: hidden;
  padding: 28px; border-radius: 8px;
  border: 1px solid var(--border);
  background: rgba(var(--nc-primary-rgb), 0.02);
  display: flex; flex-direction: column; gap: 14px;
  transition: border-color 0.22s, background 0.22s, transform 0.22s, box-shadow 0.22s;
  text-align: left;
  font-family: inherit;
  color: inherit;
  animation: op-card-rise 600ms cubic-bezier(0.22, 1, 0.36, 1) both;
  animation-delay: calc(380ms + var(--idx, 0) * 110ms);
}
.op-scope-card--clickable { cursor: pointer; }
.op-scope-card--clickable:hover {
  transform: translateY(-2px) scale(1.005);
  box-shadow: 0 14px 36px rgba(0,0,0,0.4);
}
.op-scope-card--cloud {
  border-color: rgba(var(--nc-primary-rgb), 0.25);
  background: rgba(var(--nc-primary-rgb), 0.04);
}
.op-scope-card--cloud:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  background: rgba(var(--nc-primary-rgb), 0.07);
  box-shadow: 0 14px 36px rgba(0,0,0,0.4), 0 0 24px rgba(var(--nc-primary-rgb), 0.16);
}
.op-scope-card--free { border-color: rgba(74, 222, 128, 0.18); }
.op-scope-card--free:hover {
  border-color: rgba(74, 222, 128, 0.45);
  background: rgba(74, 222, 128, 0.03);
  box-shadow: 0 14px 36px rgba(0,0,0,0.4), 0 0 24px rgba(74, 222, 128, 0.14);
}
.op-scope-card--frame { border-color: rgba(255, 196, 76, 0.18); }
.op-scope-card--frame:hover {
  border-color: rgba(255, 196, 76, 0.42);
  background: rgba(255, 196, 76, 0.03);
  box-shadow: 0 14px 36px rgba(0,0,0,0.4), 0 0 24px rgba(255, 196, 76, 0.14);
}

/* Diagonal corner accent badge */
.op-scope-corner {
  position: absolute;
  top: 16px; right: -36px;
  transform: rotate(38deg);
  padding: 4px 40px;
  font-family: var(--mono); font-size: 9px; font-weight: 700;
  letter-spacing: 0.18em; text-transform: uppercase;
  color: #060a12;
  pointer-events: none;
}
.op-scope-corner--cloud {
  background: linear-gradient(90deg, var(--nc-primary), rgba(var(--nc-primary-rgb), 0.7));
}
.op-scope-corner--free  { background: linear-gradient(90deg, #4ade80, rgba(74, 222, 128, 0.7)); }
.op-scope-corner--frame { background: linear-gradient(90deg, rgba(255, 196, 76, 0.95), rgba(255, 196, 76, 0.65)); }

.op-scope-tag {
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.1em;
  color: var(--nc-primary); text-transform: uppercase;
}
.op-scope-tag--free  { color: #4ade80; }
.op-scope-tag--frame { color: rgba(255, 196, 76, 0.95); }
.op-scope-title { font-size: 19px; font-weight: 600; color: #fff; margin: 0; }
.op-scope-desc { font-size: 13px; color: var(--text-secondary); line-height: 1.6; margin: 0; }
.op-scope-jump {
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.06em;
  color: var(--nc-primary); margin-top: auto; padding-top: 6px;
  text-transform: uppercase;
  display: inline-flex; align-items: center; gap: 6px;
}
.op-scope-card--free .op-scope-jump  { color: #4ade80; }
.op-scope-card--frame .op-scope-jump { color: rgba(255, 196, 76, 0.95); }
.op-arr { transition: transform 0.22s; display: inline-block; }
.op-scope-card:hover .op-arr { transform: translateX(3px); }

/* ── TWO-COLUMN CARDS (Cloud + Frames tabs) ──────────────────── */
.op-cards-2col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.op-card {
  padding: 28px; border-radius: 8px;
  border: 1px solid var(--border);
  background: rgba(var(--nc-primary-rgb), 0.02);
  transition: border-color 0.22s, background 0.22s;
}
.op-card:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.25);
}
.op-card-tag {
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.1em;
  color: var(--nc-primary); text-transform: uppercase; margin-bottom: 10px;
}
.op-card-title { font-size: 17px; font-weight: 600; color: #fff; margin: 0 0 12px; }
.op-card-desc { font-size: 13px; color: var(--text-secondary); line-height: 1.6; margin: 0 0 14px; }
.op-card-list, .op-card-ol { padding: 0 0 0 1.1rem; margin: 0; color: var(--text); font-size: 13px; line-height: 1.7; }
.op-card-list { list-style: none; padding-left: 0; }
.op-card-list li { padding: 7px 0; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.05); }
.op-card-list li::before { content: '— '; color: var(--muted); }
.op-card-ol li { padding: 4px 0; }
.op-card-ol li::marker { color: var(--nc-primary); font-family: var(--mono); }
.op-card-spec { list-style: none; padding: 0; margin: 0; }
.op-card-spec li {
  font-size: 12px; font-family: var(--mono); color: var(--text);
  padding: 6px 0; border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.05);
}
.op-card-spec li::before { content: '∙ '; color: var(--nc-primary); }
.op-card a, .op-card-list a, .op-card-ol a { color: var(--nc-primary); text-decoration: none; }
.op-card a:hover, .op-card-list a:hover, .op-card-ol a:hover { text-decoration: underline; }
.op-card code {
  font-family: var(--mono); font-size: 12px;
  padding: 1px 6px; border-radius: 3px;
  background: rgba(var(--nc-primary-rgb), 0.08);
  color: var(--nc-primary);
}

/* ── MONEY QUOTE — "Anything less than this is a folder." ──── */
.op-money-quote {
  display: flex; align-items: center; gap: 18px;
  margin: 2.4rem auto 0;
  max-width: 760px;
  font-size: clamp(15px, 2vw, 18px);
  color: var(--text-bright);
  font-style: italic;
  font-weight: 500;
  text-align: center;
  letter-spacing: 0.005em;
  justify-content: center;
}
.op-money-rule {
  flex: 1; height: 1px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.35), transparent);
}

/* ── CTA STRIP ───────────────────────────────────────────────── */
.op-cta-strip {
  display: flex; gap: 12px; flex-wrap: wrap;
  margin-top: 2rem;
}

/* ── FRAME COMMANDER CTA (Frames tab → standalone form) ─────── */
.op-frame-cta {
  display: flex; align-items: center; justify-content: space-between;
  gap: 24px; flex-wrap: wrap;
  margin-top: 2.5rem;
  padding: 28px 32px; border-radius: 8px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  background:
    radial-gradient(circle at 100% 0%, rgba(var(--nc-primary-rgb), 0.08), transparent 50%),
    rgba(var(--nc-primary-rgb), 0.04);
  transition: border-color 0.22s, box-shadow 0.22s;
}
.op-frame-cta:hover {
  border-color: rgba(var(--nc-primary-rgb), 0.45);
  box-shadow: 0 0 28px rgba(var(--nc-primary-rgb), 0.12);
}
.op-frame-cta-content { flex: 1; min-width: 320px; }
.op-frame-cta-eyebrow {
  display: inline-block;
  font-family: var(--mono); font-size: 10px; letter-spacing: 0.18em;
  color: var(--nc-primary); text-transform: uppercase;
  margin-bottom: 6px;
}
.op-frame-cta-title {
  font-size: 19px; font-weight: 600; color: #fff; margin: 0 0 8px;
}
.op-frame-cta-desc {
  font-size: 13px; color: var(--text-secondary); line-height: 1.6; margin: 0;
  max-width: 600px;
}

/* ── FORM ────────────────────────────────────────────────────── */
.op-form {
  display: flex; flex-direction: column; gap: 18px; max-width: 760px;
}
.op-form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.op-form-field { display: flex; flex-direction: column; gap: 6px; }
.op-form-label {
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.08em;
  color: var(--muted); text-transform: uppercase;
}
.op-form-input {
  font-family: var(--mono); font-size: 14px;
  padding: 11px 14px; border-radius: 4px;
  border: 1px solid var(--border);
  background: rgba(var(--nc-primary-rgb), 0.02);
  color: var(--text-bright);
  outline: none; transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
}
.op-form-input:focus {
  border-color: rgba(var(--nc-primary-rgb), 0.55);
  background: rgba(var(--nc-primary-rgb), 0.05);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,0.02),
    0 0 0 3px rgba(var(--nc-primary-rgb), 0.12);
}
textarea.op-form-input { resize: vertical; min-height: 88px; }
.op-form-hint {
  font-size: 11px; color: var(--muted); margin-top: 4px;
  line-height: 1.5; font-style: italic;
}
.op-form-actions {
  display: flex; align-items: center; gap: 12px; margin-top: 8px; flex-wrap: wrap;
}
.op-form-msg { font-size: 12px; font-family: var(--mono); }
.op-form-msg--ok { color: #4ade80; }
.op-form-msg--err { color: #f87171; }

/* ── APPLY (one form, two routes; §OPPAGE) ─────────────────────── */
.op-apply { padding-top: 1rem; }
.op-apply .op-sec-head { border-top: 1px solid rgba(var(--nc-primary-rgb), 0.12); padding-top: 2.5rem; }
.op-deploy { border: 0; margin: 0; padding: 0; min-width: 0; }
.op-deploy legend { margin-bottom: 8px; padding: 0; }
.op-deploy-opts { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.op-deploy-opt {
  position: relative; display: flex; flex-direction: column; gap: 4px;
  padding: 14px 16px; border-radius: 6px; cursor: pointer;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  background: rgba(var(--nc-primary-rgb), 0.025);
  transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
}
.op-deploy-opt:hover { border-color: rgba(var(--nc-primary-rgb), 0.4); }
.op-deploy-opt input { position: absolute; opacity: 0; width: 1px; height: 1px; pointer-events: none; }
.op-deploy-opt:focus-within { outline: 2px solid var(--nc-primary); outline-offset: 2px; }
.op-deploy-opt--on {
  border-color: rgba(var(--nc-primary-rgb), 0.65);
  background: rgba(var(--nc-primary-rgb), 0.08);
  box-shadow: inset 0 0 0 1px rgba(var(--nc-primary-rgb), 0.25);
}
.op-deploy-title { font-size: 14px; font-weight: 600; color: var(--text-bright); }
.op-deploy-sub { font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.op-form-hint--account { margin-top: -8px; font-style: normal; }
.op-form-hint--account :deep(a), .op-form-hint--account a { color: var(--nc-primary); text-decoration: underline; }
@media (max-width: 640px) {
  .op-deploy-opts { grid-template-columns: 1fr; }
}

/* ── CHECKBOX (Frames request — auto-create-account) ────────── */
.op-form-checkbox-row {
  padding: 16px;
  border-radius: 6px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  background: rgba(var(--nc-primary-rgb), 0.04);
}
.op-form-checkbox {
  display: flex; gap: 14px; cursor: pointer;
  align-items: flex-start;
}
.op-form-checkbox input[type="checkbox"] {
  position: absolute; opacity: 0; pointer-events: none;
}
.op-form-checkbox-mark {
  flex-shrink: 0;
  width: 18px; height: 18px;
  border: 1px solid rgba(var(--nc-primary-rgb), 0.4);
  border-radius: 3px;
  background: rgba(var(--nc-primary-rgb), 0.05);
  margin-top: 2px;
  position: relative;
  transition: background 0.15s, border-color 0.15s;
}
.op-form-checkbox input[type="checkbox"]:checked + .op-form-checkbox-mark {
  background: var(--nc-primary);
  border-color: var(--nc-primary);
}
.op-form-checkbox input[type="checkbox"]:checked + .op-form-checkbox-mark::after {
  content: '';
  position: absolute;
  left: 4px; top: 0px;
  width: 6px; height: 11px;
  border-right: 2px solid #060a12;
  border-bottom: 2px solid #060a12;
  transform: rotate(45deg);
}
.op-form-checkbox-text { display: flex; flex-direction: column; gap: 4px; }
.op-form-checkbox-text strong {
  font-size: 13px; color: var(--text-bright); font-weight: 600;
}
.op-form-checkbox-sub {
  font-size: 12px; color: var(--text-secondary); line-height: 1.55;
}

/* ── FOOTER ──────────────────────────────────────────────────── */
.op-footer-sec { padding-top: 0; padding-bottom: 5rem; }
.op-footer {
  font-size: 13px; color: var(--text-bright); line-height: 1.7;
  font-style: italic; max-width: 720px; margin: 0;
}
.op-footer-sub {
  font-size: 12px; color: var(--muted); line-height: 1.7;
  max-width: 720px; margin: 12px 0 0;
}

/* ── RESPONSIVE ──────────────────────────────────────────────── */
@media (max-width: 960px) {
  .op-scope-grid { grid-template-columns: 1fr; }
  .op-cards-2col { grid-template-columns: 1fr; }
}
@media (max-width: 700px) {
  .op-tabs { padding: 14px 1rem 0; gap: 0; flex-wrap: wrap; }
  .op-tab { padding: 10px 14px; }
  .op-tab-label { font-size: 12px; }
  .op-tab-slider { display: none; }
  .op-money-quote { font-size: 15px; gap: 12px; }
  .op-money-rule { display: none; }
  .op-hero-cue { display: none; }
}
@media (max-width: 640px) {
  .op-form-row { grid-template-columns: 1fr; }
  .op-hero { padding: 4rem 1.5rem 2.5rem; }
  .op-sec { padding: 3rem 1.5rem; }
  .op-scope-corner { font-size: 8px; padding: 3px 38px; }
}

/* ── REDUCED MOTION ──────────────────────────────────────────── */
@media (prefers-reduced-motion: reduce) {
  .op-star,
  .op-chip-dot,
  .op-hero-cue,
  .op-scope-card {
    animation: none !important;
  }
  .op-scope-card { opacity: 1; transform: none !important; }
  .op-proof-item,
  .op-tab-slider,
  .op-card,
  .op-frame-cta,
  .op-deploy-opt,
  .op-fade-enter-active, .op-fade-leave-active {
    transition: none !important;
  }
  .op-scope-card--clickable:hover, .op-btn:hover {
    transform: none !important;
  }
}
.op-form-accept { display: flex; gap: 10px; align-items: flex-start; margin: 6px 0 12px; font-size: 0.92rem; line-height: 1.45; }
.op-form-accept input { margin-top: 4px; }
.op-form-accept a { text-decoration: underline; }
/* §FESUITE V0595: the configuration step */
.op-env { margin: 0.5rem 0 1rem; border: 1px solid rgba(var(--nc-primary-rgb), 0.16); border-radius: 10px; padding: 0.75rem 1rem; }
.op-env-summary { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0.75rem; cursor: pointer; list-style: none; }
.op-env-summary::-webkit-details-marker { display: none; }
.op-env-sub { font-size: 12px; color: var(--text-secondary, #b8c0cc); }
.op-env[open] .op-env-summary { margin-bottom: 0.75rem; }
</style>
