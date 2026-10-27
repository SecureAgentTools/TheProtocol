<template>
  <div class="opp-shell">
    <!-- ═══ HERO ═════════════════════════════════════════════════════════ -->
    <section class="opp-hero">
      <div class="opp-hero-inner">
        <div class="opp-hero-chip">
          <span class="opp-hero-chip-dot"></span>
          {{ t('operatorPortalView.hero.chip') }}
        </div>
        <h1 class="opp-h1">
          {{ t('operatorPortalView.hero.titleLead') }} <span class="opp-h1-accent">{{ t('operatorPortalView.hero.titleAccent') }}</span>
        </h1>
        <p class="opp-lead">
          {{ t('operatorPortalView.hero.leadBefore') }}<code class="opp-inline-code">tp</code>{{ t('operatorPortalView.hero.leadAfter') }}
        </p>
      </div>
    </section>

    <!-- ═══ TAB BAR ═══════════════════════════════════════════════════════ -->
    <nav class="opp-tabs" role="tablist" :aria-label="t('operatorPortalView.tabsAria')">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        :ref="el => { if (el) tabRefs[tab.id] = el as HTMLButtonElement }"
        type="button"
        role="tab"
        :class="['opp-tab', { 'opp-tab--active': activeTab === tab.id }]"
        :aria-selected="activeTab === tab.id"
        :data-tab="tab.id"
        @click="setTab(tab.id)"
        @keydown="onTabKeydown($event, tab.id)"
      >
        <span class="opp-tab-label">{{ tab.label }}</span>
        <span v-if="tab.indicator" class="opp-tab-indicator" :title="tab.indicatorTitle">{{ tab.indicator }}</span>
      </button>
      <div class="opp-tabs-rule" :style="rulerStyle" aria-hidden="true"></div>
    </nav>

    <!-- ═══ TAB CONTENT ════════════════════════════════════════════════════ -->
    <main class="opp-body">
      <Suspense>
        <template #default>
          <KeepAlive>
            <component
              :is="currentTabComponent"
              v-bind="componentProps"
              @refresh-shell="refreshShell"
            />
          </KeepAlive>
        </template>
        <template #fallback>
          <div class="opp-tab-fallback">{{ t('operatorPortalView.loadingTab') }}</div>
        </template>
      </Suspense>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, defineAsyncComponent, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getMyLifecycle, type OperatorLifecycle } from '@/services/api/operator'
import { useI18n } from '@/composables/useI18n'
import { useAlive } from '@/composables/useAlive'

// Lazy tabs — defer load until first activation, then KeepAlive holds state.
const OPAccountTab     = defineAsyncComponent(() => import('@/components/operator/OPAccountTab.vue'))
const OPHealthTab      = defineAsyncComponent(() => import('@/components/operator/OPHealthTab.vue'))
const OPFederationTab  = defineAsyncComponent(() => import('@/components/operator/OPFederationTab.vue'))
const OPLicenseTab     = defineAsyncComponent(() => import('@/components/operator/OPLicenseTab.vue'))
const OPRegistryCardTab = defineAsyncComponent(() => import('@/components/operator/OPRegistryCardTab.vue'))
const OPLiveTab        = defineAsyncComponent(() => import('@/components/operator/OPLiveTab.vue'))

type TabId = 'account' | 'health' | 'federation' | 'license' | 'registry-card' | 'live'
interface TabDef {
  id: TabId; label: string;
  indicator?: string; indicatorTitle?: string;
}

const lifecycle = ref<OperatorLifecycle | null>(null)
const { t } = useI18n()

const tabs = computed<TabDef[]>(() => {
  const driftCount = lifecycle.value?.drift_flags?.length || 0
  return [
    { id: 'account', label: t('operatorPortalView.tabs.account') },
    {
      id: 'health',
      label: t('operatorPortalView.tabs.health'),
      indicator: driftCount > 0 ? String(driftCount) : undefined,
      indicatorTitle: driftCount > 0 ? t(driftCount === 1 ? 'operatorPortalView.driftFlagOne' : 'operatorPortalView.driftFlagMany', { n: driftCount }) : undefined,
    },
    { id: 'federation', label: t('operatorPortalView.tabs.federation') },
    { id: 'license', label: t('operatorPortalView.tabs.license') },
    { id: 'registry-card', label: t('operatorPortalView.tabs.registryCard') },
    { id: 'live', label: t('operatorPortalView.tabs.live') },
  ]
})

const TAB_IDS: TabId[] = ['account', 'health', 'federation', 'license', 'registry-card', 'live']

const route = useRoute()
const router = useRouter()

const activeTab = ref<TabId>('account')
const tabRefs: Record<string, HTMLButtonElement> = {}

const rulerStyle = ref<{ left: string; width: string }>({ left: '0px', width: '0px' })

const currentTabComponent = computed(() => {
  switch (activeTab.value) {
    case 'health':        return OPHealthTab
    case 'federation':    return OPFederationTab
    case 'license':       return OPLicenseTab
    case 'registry-card': return OPRegistryCardTab
    case 'live':          return OPLiveTab
    default:              return OPAccountTab
  }
})

// Only OPLicenseTab needs the lifecycle prop. Vue would warn about
// extraneous-attrs fallthrough on tabs that don't declare it.
const componentProps = computed<Record<string, any>>(() => {
  if (activeTab.value === 'license') return { lifecycle: lifecycle.value, lifecycleRead: lifecycleRead.value }
  return {}
})

function setTab(id: TabId) {
  if (!TAB_IDS.includes(id)) id = 'account'
  activeTab.value = id
  router.replace({ query: { ...route.query, tab: id } })
  nextTick(updateRuler)
}

function updateRuler() {
  const el = tabRefs[activeTab.value]
  if (!el) return
  rulerStyle.value = {
    left: `${el.offsetLeft}px`,
    width: `${el.offsetWidth}px`,
  }
}

function onTabKeydown(e: KeyboardEvent, current: TabId) {
  const idx = TAB_IDS.indexOf(current)
  if (e.key === 'ArrowRight') { e.preventDefault(); setTab(TAB_IDS[(idx + 1) % TAB_IDS.length]) }
  else if (e.key === 'ArrowLeft') { e.preventDefault(); setTab(TAB_IDS[(idx - 1 + TAB_IDS.length) % TAB_IDS.length]) }
  else if (e.key === 'Home') { e.preventDefault(); setTab(TAB_IDS[0]) }
  else if (e.key === 'End') { e.preventDefault(); setTab(TAB_IDS[TAB_IDS.length - 1]) }
}

// §FESUITE (V0575): the shell stays open when the lifecycle read fails (fail-open), but a lifecycle that was never read
// is not "no licence": the License tab says "Loading…" until it is read and that the read failed when it got no answer
// (a later failed refresh keeps the lifecycle that was read)
const lifecycleRead = ref<'reading' | 'read' | 'unread'>('reading')
async function refreshShell() {
  try {
    lifecycle.value = await getMyLifecycle()
    lifecycleRead.value = 'read'
  } catch { if (lifecycleRead.value !== 'read') lifecycleRead.value = 'unread' }
}

watch(() => route.query.tab, (q) => {
  if (typeof q === 'string' && TAB_IDS.includes(q as TabId)) {
    activeTab.value = q as TabId
    nextTick(updateRuler)
  }
}, { immediate: false })

// §FESUITE (the leave sweep): the resize listener went on after the first read and never came off, one more on every visit
const alive = useAlive()
onMounted(async () => {
  const q = route.query.tab
  if (typeof q === 'string' && TAB_IDS.includes(q as TabId)) {
    activeTab.value = q as TabId
  }
  await refreshShell()
  if (!alive()) return
  nextTick(updateRuler)
  window.addEventListener('resize', updateRuler)
})
onUnmounted(() => window.removeEventListener('resize', updateRuler))
</script>

<style scoped>
.opp-shell { display: flex; flex-direction: column; min-height: 100%; }

.opp-hero {
  padding: 2rem 2rem 1.6rem;
  background:
    radial-gradient(ellipse 800px 200px at 50% 0%, rgba(var(--nc-primary-rgb), 0.06), transparent 60%),
    rgba(0, 8, 14, 0.4);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.12);
}
.opp-hero-inner { max-width: 1100px; margin: 0 auto; }
.opp-hero-chip {
  display: inline-flex; align-items: center; gap: 0.5rem;
  padding: 0.2rem 0.6rem;
  background: rgba(var(--nc-primary-rgb), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28);
  border-radius: 2px;
  font-size: 0.62rem; letter-spacing: 0.18em;
  color: rgba(var(--nc-primary-rgb), 0.95);
  font-family: 'IBM Plex Mono', monospace;
  font-weight: 700;
  margin-bottom: 1rem;
}
.opp-hero-chip-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: rgba(var(--nc-primary-rgb), 0.95);
  box-shadow: 0 0 6px rgba(var(--nc-primary-rgb), 0.7);
  animation: oppHeroChipPulse 1.8s ease-in-out infinite;
}
@keyframes oppHeroChipPulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.85); }
}
.opp-h1 {
  margin: 0 0 0.6rem; font-size: 2.1rem; font-weight: 600;
  color: #f4f9ff; letter-spacing: -0.02em; line-height: 1.15;
}
.opp-h1-accent {
  background: linear-gradient(90deg, rgba(var(--nc-primary-rgb), 1), rgba(120, 200, 255, 1));
  -webkit-background-clip: text; background-clip: text;
  color: transparent;
}
.opp-lead {
  margin: 0; max-width: 720px;
  font-size: 0.92rem; line-height: 1.6;
  color: rgba(255, 255, 255, 0.65);
}
.opp-inline-code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.85rem;
  background: rgba(var(--nc-primary-rgb), 0.1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  padding: 0.05rem 0.35rem;
  border-radius: 2px;
  color: rgba(var(--nc-primary-rgb), 0.95);
}

.opp-tabs {
  position: sticky; top: 0; z-index: 10;
  display: flex; align-items: stretch; gap: 0;
  padding: 0 2rem;
  background: rgba(0, 8, 14, 0.92);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  overflow-x: auto; overflow-y: hidden;
}
.opp-tab {
  background: transparent;
  border: none; outline: none;
  padding: 0.95rem 1.2rem;
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.74rem; letter-spacing: 0.1em;
  text-transform: uppercase; font-weight: 600;
  color: rgba(255, 255, 255, 0.45);
  cursor: pointer;
  transition: color 0.18s;
  position: relative;
  white-space: nowrap;
  display: inline-flex; align-items: center; gap: 0.5rem;
}
.opp-tab:hover { color: rgba(255, 255, 255, 0.75); }
.opp-tab:focus-visible {
  color: rgba(255, 255, 255, 0.95);
  outline: 1px dashed rgba(var(--nc-primary-rgb), 0.55);
  outline-offset: -4px;
}
.opp-tab--active { color: rgba(var(--nc-primary-rgb), 1); }
.opp-tab-indicator {
  display: inline-flex; align-items: center; justify-content: center;
  min-width: 18px; height: 18px;
  padding: 0 0.4rem;
  font-size: 0.62rem; font-weight: 700;
  background: rgba(255, 176, 0, 0.18);
  border: 1px solid rgba(255, 176, 0, 0.45);
  color: rgba(255, 200, 80, 1);
  border-radius: 10px;
  letter-spacing: 0;
}

.opp-tabs-rule {
  position: absolute; bottom: 0; height: 2px;
  background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 1), transparent);
  transition: left 0.35s cubic-bezier(0.65, 0, 0.35, 1), width 0.35s cubic-bezier(0.65, 0, 0.35, 1);
  pointer-events: none;
}
.opp-tabs { position: relative; }

.opp-body {
  flex: 1 1 auto;
  background: rgba(0, 4, 8, 0.3);
}

.opp-tab-fallback {
  padding: 3rem;
  text-align: center;
  color: rgba(255, 255, 255, 0.4);
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.82rem;
}

@media (max-width: 768px) {
  .opp-hero { padding: 1.4rem 1rem; }
  .opp-h1 { font-size: 1.55rem; }
  .opp-lead { font-size: 0.85rem; }
  .opp-tabs { padding: 0 0.5rem; }
  .opp-tab { padding: 0.8rem 0.7rem; font-size: 0.68rem; letter-spacing: 0.05em; }
}
</style>
