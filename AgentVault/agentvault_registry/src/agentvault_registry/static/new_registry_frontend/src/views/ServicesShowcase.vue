<template>
<div class="svc-scope sx-page">
  <div class="sx-wrap">
    <!-- Breadcrumb -->
    <nav class="sx-crumb">
      <router-link to="/" class="sx-crumb-home">TheProtocol</router-link>
      <span class="sx-crumb-sep">/</span>
      <span>{{ t('servicesShowcaseView.crumb') }}</span>
    </nav>

    <!-- Context banner -->
    <div class="sx-banner">
      <strong>{{ t('servicesShowcaseView.contextStrong') }}</strong>{{ t('servicesShowcaseView.contextRest') }}
      <router-link to="/monetize" class="sx-banner-link">{{ t('servicesShowcaseView.contextLink') }}</router-link>
    </div>

    <!-- Hero -->
    <header class="sx-hero">
      <span class="svc-eyebrow">{{ t('servicesShowcaseView.heroBadge') }}</span>
      <h1 class="svc-h1 sx-hero-title">{{ t('servicesShowcaseView.heroTitle') }}</h1>
      <p class="svc-lead sx-hero-sub" v-html="t('servicesShowcaseView.heroSub', { n: services.length, unit: unitWord })"></p>
      <p v-if="unavailable" class="sx-off" role="status" data-testid="svc-showcase-off">
        {{ t('servicesShowcaseView.offHere', 'Live calls are switched off on this frame: the services below are described here, not callable.') }}
      </p>
      <div v-else class="sx-meter">
        <div class="svc-meter" style="width:200px"><div class="svc-meter-fill" :style="{ width: (requestsLeft / 50 * 100) + '%' }"></div></div>
        <span class="sx-meter-text">{{ t('servicesShowcaseView.meterText', { n: requestsLeft }) }}</span>
      </div>
    </header>

    <!-- How it works -->
    <div class="sx-steps">
      <div class="sx-step" v-for="step in howSteps" :key="step.num">
        <span class="sx-step-num">{{ step.num }}</span>
        <div>
          <div class="sx-step-label">{{ step.label }}</div>
          <div class="sx-step-desc">{{ step.desc }}</div>
        </div>
      </div>
    </div>

    <!-- Service grid -->
    <div class="sx-grid">
      <ServiceCard
        v-for="svc in services"
        :key="svc.id"
        :svc="svc"
        :open="active === svc.id"
        :loading="loading === svc.id"
        :response="results[svc.id]"
        :unavailable="unavailable"
        @toggle="toggle(svc.id)"
        @run="call(svc)"
      />
    </div>

    <!-- What just happened -->
    <section class="sx-section">
      <span class="svc-eyebrow">{{ t('servicesShowcaseView.hood.label') }}</span>
      <h2 class="svc-h2 sx-section-title">{{ t('servicesShowcaseView.hood.title') }}</h2>
      <div class="sx-hood">
        <div v-for="n in 3" :key="n" class="svc-card svc-card-pad sx-hood-step">
          <span class="sx-hood-num">{{ n }}</span>
          <div>
            <div class="sx-hood-head">{{ t(`servicesShowcaseView.hood.step${n}.head`) }}</div>
            <div class="sx-hood-text">{{ t(`servicesShowcaseView.hood.step${n}.text`) }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- Architecture -->
    <section class="sx-section">
      <span class="svc-eyebrow">{{ t('servicesShowcaseView.arch.label') }}</span>
      <h2 class="svc-h2 sx-section-title">{{ t('servicesShowcaseView.arch.title') }}</h2>
      <div class="sx-arch">
        <div v-for="a in archCards" :key="a.key" class="svc-card svc-card-pad sx-arch-card">
          <svg class="sx-arch-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" v-html="a.svg"></svg>
          <div class="sx-arch-name">{{ t(`servicesShowcaseView.arch.${a.key}.name`) }}</div>
          <div class="sx-arch-desc">{{ t(`servicesShowcaseView.arch.${a.key}.desc`) }}</div>
        </div>
      </div>
    </section>

    <!-- Revenue model -->
    <section class="sx-section">
      <span class="svc-eyebrow">{{ t('servicesShowcaseView.revenue.label') }}</span>
      <h2 class="svc-h2 sx-section-title">{{ t('servicesShowcaseView.revenue.title') }}</h2>
      <div class="svc-grid-2">
        <div class="svc-card svc-card-pad">
          <div class="sx-rev-head">{{ t('servicesShowcaseView.revenue.earn.head') }}</div>
          <ul class="sx-rev-list">
            <li v-for="i in 3" :key="i">{{ t(`servicesShowcaseView.revenue.earn.li${i}`) }}</li>
          </ul>
        </div>
        <div class="svc-card svc-card-pad">
          <div class="sx-rev-head">{{ t('servicesShowcaseView.revenue.external.head') }}</div>
          <ul class="sx-rev-list">
            <li v-for="i in 4" :key="i">{{ t(`servicesShowcaseView.revenue.external.li${i}`) }}</li>
          </ul>
          <router-link to="/monetize" class="sx-rev-link">{{ t('servicesShowcaseView.revenue.external.link') }}</router-link>
        </div>
      </div>
    </section>

    <!-- Getting started -->
    <section class="sx-section">
      <span class="svc-eyebrow">{{ t('servicesShowcaseView.getStarted.label') }}</span>
      <h2 class="svc-h2 sx-section-title">{{ t('servicesShowcaseView.getStarted.title') }}</h2>
      <p class="svc-lead" style="margin-bottom:1.1rem">{{ t('servicesShowcaseView.getStarted.sub') }}</p>
      <div class="svc-grid-3">
        <div v-for="p in paths" :key="p.key" class="svc-card svc-card-pad sx-path">
          <span class="sx-path-num">{{ p.letter }}</span>
          <div class="sx-path-name">{{ t(`servicesShowcaseView.getStarted.${p.key}.name`) }}</div>
          <div class="sx-path-desc">{{ t(`servicesShowcaseView.getStarted.${p.key}.desc`) }}</div>
          <code class="sx-path-code" v-html="p.code"></code>
        </div>
      </div>
    </section>

    <!-- Final CTA -->
    <section class="svc-card svc-card-pad sx-cta">
      <h2 class="svc-h2">{{ t('servicesShowcaseView.cta.title') }}</h2>
      <p class="svc-lead" style="margin:.5rem 0 1.1rem">{{ t('servicesShowcaseView.cta.text') }}</p>
      <div class="sx-cta-acts">
        <router-link to="/register" class="svc-btn">{{ t('servicesShowcaseView.cta.create') }}</router-link>
        <router-link to="/docs" class="svc-btn svc-btn-ghost">{{ t('servicesShowcaseView.cta.docs') }}</router-link>
        <router-link to="/monetize" class="svc-btn svc-btn-ghost">{{ t('servicesShowcaseView.cta.demo') }}</router-link>
      </div>
    </section>

    <footer class="sx-footer">
      A2A v1.0 · Federated Agent Network · <a href="https://theprotocol.cloud" class="sx-footer-link">theprotocol.cloud</a>
    </footer>
  </div>
</div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { escapeHtml } from '@/utils/escapeHtml'
import { useShowcaseServices } from '@/composables/useShowcaseServices'
import ServiceCard from '@/components/services/ServiceCard.vue'

const { t } = useI18n()
// §LANDINGTRUTH (12): the agent is paid in this registry's own unit, read from its config, never a literal (escaped:
// heroSub renders through v-html)
const { localCurrency } = useRegistryConfig()
const unitWord = computed(() => escapeHtml(localCurrency.value || t('servicesShowcaseView.unitsWord')))
const { services, results, loading, requestsLeft, call, unavailable } = useShowcaseServices()

const active = ref<string | null>(services[0]?.id ?? null)
function toggle(id: string) { active.value = active.value === id ? null : id }

const howSteps = computed(() => [
  { num: '1', label: t('servicesShowcaseView.steps.pick.label'), desc: t('servicesShowcaseView.steps.pick.desc') },
  { num: '2', label: t('servicesShowcaseView.steps.send.label'), desc: t('servicesShowcaseView.steps.send.desc') },
  { num: '3', label: t('servicesShowcaseView.steps.get.label'), desc: t('servicesShowcaseView.steps.get.desc') },
])

const archCards = [
  { key: 'fed', svg: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>' },
  { key: 'identity', svg: '<path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/>' },
  { key: 'token', svg: '<path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>' },
  { key: 'trust', svg: '<path d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>' },
  { key: 'a2a', svg: '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>' },
  { key: 'ledger', svg: '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>' },
]

const paths = [
  { key: 'pathA', letter: 'A', code: 'pip install theprotocol-orchestrator<br>ppao setup<br>ppao hire "weather in Berlin"' },
  { key: 'pathB', letter: 'B', code: 'pip install theprotocol-sdk<br>from theprotocol.agent import create_a2a_router<br># Payment enforcement is automatic' },
  { key: 'pathC', letter: 'C', code: '# Apply → receive license + Docker images<br># Your agents cross-registry transfer in<br># Your rules, your fees, your governance' },
]
</script>

<style scoped>
.sx-page { min-height: 100vh; background: radial-gradient(1200px 620px at 50% -8%, rgba(var(--nc-primary-rgb, 0, 210, 210), 0.06), transparent 62%), #070b12; }
.sx-wrap { max-width: 920px; margin: 0 auto; padding: 2.5rem 1.5rem 3.5rem; }

.sx-crumb { display: flex; align-items: center; gap: 0.4rem; font-size: 0.72rem; color: var(--svc-faint); margin-bottom: 1.6rem; }
.sx-crumb-home { color: var(--svc-dim); text-decoration: none; }
.sx-crumb-home:hover { color: var(--svc); }
.sx-crumb-sep { opacity: 0.4; }

.sx-banner { background: rgba(var(--svc-rgb), 0.05); border: 1px solid var(--svc-line); border-radius: 11px; padding: 0.75rem 1rem; margin-bottom: 1.8rem; font-size: 0.76rem; color: var(--svc-dim); line-height: 1.5; }
.sx-banner strong { color: var(--svc-ink); }
.sx-banner-link { color: var(--svc); text-decoration: none; font-weight: 600; margin-left: 0.3rem; }
.sx-banner-link:hover { text-decoration: underline; }

.sx-hero { text-align: center; margin-bottom: 2.2rem; }
.sx-hero-title { margin: 0.7rem 0 0.5rem; }
.sx-hero-sub { max-width: 560px; margin: 0 auto 1.2rem; }
.sx-off { max-width: 560px; margin: 0 auto; font-size: 0.78rem; color: var(--svc-dim); border: 1px solid var(--svc-line); border-radius: 9px; padding: 0.55rem 0.8rem; }
.sx-meter { display: flex; flex-direction: column; align-items: center; gap: 0.45rem; }
.sx-meter-text { font-family: var(--svc-mono); font-size: 0.6rem; color: var(--svc-faint); letter-spacing: 0.04em; }

.sx-steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.7rem; margin-bottom: 2.2rem; }
.sx-step { display: flex; align-items: center; gap: 0.65rem; padding: 0.6rem 0.2rem; }
.sx-step-num { width: 28px; height: 28px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 50%; font-size: 0.72rem; font-weight: 700; color: var(--svc); background: rgba(var(--svc-rgb), 0.08); border: 1px solid rgba(var(--svc-rgb), 0.22); }
.sx-step-label { font-size: 0.78rem; font-weight: 600; color: var(--svc-ink); }
.sx-step-desc { font-size: 0.66rem; color: var(--svc-dim); margin-top: 0.1rem; }

.sx-grid { display: flex; flex-direction: column; gap: 0.65rem; margin-bottom: 3rem; }

.sx-section { margin-bottom: 3rem; }
.sx-section-title { margin: 0.5rem 0 1rem; }

.sx-hood { display: flex; flex-direction: column; gap: 0.65rem; }
.sx-hood-step { display: flex; gap: 0.85rem; align-items: flex-start; }
.sx-hood-num { width: 26px; height: 26px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 50%; font-size: 0.68rem; font-weight: 700; color: var(--svc); background: rgba(var(--svc-rgb), 0.08); border: 1px solid rgba(var(--svc-rgb), 0.2); }
.sx-hood-head { font-size: 0.8rem; font-weight: 600; color: var(--svc-ink); margin-bottom: 0.2rem; }
.sx-hood-text { font-size: 0.7rem; color: var(--svc-dim); line-height: 1.55; }

.sx-arch { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.7rem; }
.sx-arch-icon { width: 22px; height: 22px; color: var(--svc); margin-bottom: 0.6rem; }
.sx-arch-name { font-size: 0.78rem; font-weight: 600; color: var(--svc-ink); margin-bottom: 0.3rem; }
.sx-arch-desc { font-size: 0.68rem; color: var(--svc-dim); line-height: 1.55; }

.sx-rev-head { font-size: 0.82rem; font-weight: 700; color: var(--svc-ink); margin-bottom: 0.7rem; }
.sx-rev-list { list-style: none; padding: 0; margin: 0; }
.sx-rev-list li { font-size: 0.72rem; color: var(--svc-dim); line-height: 1.5; padding: 0.4rem 0; border-bottom: 1px solid var(--svc-line-soft); }
.sx-rev-list li:last-child { border-bottom: 0; }
.sx-rev-link { display: inline-block; margin-top: 0.8rem; font-size: 0.72rem; color: var(--svc); text-decoration: none; font-weight: 600; }
.sx-rev-link:hover { text-decoration: underline; }

.sx-path { display: flex; flex-direction: column; }
.sx-path-num { width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; border-radius: 7px; font-size: 0.66rem; font-weight: 800; color: var(--svc); background: rgba(var(--svc-rgb), 0.1); border: 1px solid rgba(var(--svc-rgb), 0.25); margin-bottom: 0.6rem; }
.sx-path-name { font-size: 0.82rem; font-weight: 700; color: var(--svc-ink); margin-bottom: 0.35rem; }
.sx-path-desc { font-size: 0.68rem; color: var(--svc-dim); line-height: 1.55; margin-bottom: 0.7rem; flex: 1; }
.sx-path-code { display: block; padding: 0.6rem 0.7rem; background: rgba(0, 0, 0, 0.35); border: 1px solid var(--svc-line-soft); border-radius: 8px; font-family: var(--svc-mono); font-size: 0.62rem; color: var(--svc); line-height: 1.7; }

.sx-cta { text-align: center; }
.sx-cta-acts { display: flex; gap: 0.6rem; justify-content: center; flex-wrap: wrap; }

.sx-footer { text-align: center; font-size: 0.62rem; color: var(--svc-faint); padding-top: 1rem; }
.sx-footer-link { color: var(--svc-dim); text-decoration: none; }
.sx-footer-link:hover { color: var(--svc); }

@media (max-width: 640px) {
  .sx-wrap { padding: 1.6rem 1rem 2.5rem; }
  .sx-steps { grid-template-columns: 1fr; gap: 0.4rem; }
  .sx-arch { grid-template-columns: 1fr; }
  .sx-cta-acts { flex-direction: column; }
  .sx-cta-acts .svc-btn { width: 100%; }
}
</style>
