<!--
  V0664 M5 (order gwo_5a4ea8476b97147f3056405e) — Migrate a system. Public, no sign-in: what it does in three steps, a gallery of
  migration templates (filters: from-system, to-system, free or paid) and "write your own". The engine (proxy, migrate, dry run,
  reconcile, certificate) is free and open source; a template's author may charge for the template, and a fork pays its parent's
  author a share of each sale (the platform takes nothing from a sale). The contract: sessionlogs2026/DESIGN_2026-11-14_MIGRATION_TEMPLATES.md.
-->
<template>
  <div class="mg" data-testid="mg-root">
    <MigrateTabs current="migrate" />
    <header class="mg-hero">
      <span class="mg-badge"><Icon name="mdi:database-export" /></span>
      <div>
        <h1>{{ t('migrate.title', 'Migrate a system') }}</h1>
        <p>{{ t('migrate.subtitle', 'Replace a legacy system instead of bridging it: pick a template, dry-run it free on your own machine, then load and reconcile with a certificate.') }}</p>
        <div class="mg-cta">
          <RouterLink :to="{ name: 'migrate-new' }" class="mg-btn primary" data-testid="mg-cta-build">{{ t('migrate.cta.build', 'Build a migration') }}</RouterLink>
          <RouterLink :to="{ name: 'migrate-report' }" class="mg-btn" data-testid="mg-cta-report">{{ t('migrate.cta.report', 'Read a report') }}</RouterLink>
        </div>
      </div>
    </header>

    <ol class="mg-steps" data-testid="mg-steps">
      <li><strong>{{ t('migrate.step1Title', '1. Pick a template') }}</strong><span>{{ t('migrate.step1Body', 'Free or paid, written by anyone, forkable. See what it needs and what it maps before you start.') }}</span></li>
      <li><strong>{{ t('migrate.step2Title', '2. Dry-run it free') }}</strong><span>{{ t('migrate.step2Body', 'On its sample data first, then against your own system read-only. It writes nothing to your target and calls nothing on TheProtocol; its report holds counts, field names and hashes, never a value.') }}</span></li>
      <li><strong>{{ t('migrate.step3Title', '3. Load and reconcile') }}</strong><span>{{ t('migrate.step3Body', 'The load runs exactly once and can resume; both sides are read back and compared; a migration certificate on the ledger carries every report\'s hash, checkable offline.') }}</span></li>
    </ol>

    <section class="mg-filters" :aria-label="t('migrate.filtersAria', 'Filter the templates')">
      <label>{{ t('migrate.fFrom', 'From') }}
        <select v-model="filters.from" data-testid="mg-filter-from">
          <option value="">{{ t('migrate.any', 'Any') }}</option>
          <option v-for="k in KINDS" :key="k" :value="k">{{ kindWords(k) }}</option>
        </select>
      </label>
      <label>{{ t('migrate.fTo', 'To') }}
        <select v-model="filters.to" data-testid="mg-filter-to">
          <option value="">{{ t('migrate.any', 'Any') }}</option>
          <option v-for="k in KINDS" :key="k" :value="k">{{ kindWords(k) }}</option>
        </select>
      </label>
      <label>{{ t('migrate.fPrice', 'Price') }}
        <select v-model="filters.price" data-testid="mg-filter-price">
          <option value="any">{{ t('migrate.any', 'Any') }}</option>
          <option value="free">{{ t('migrate.free', 'Free') }}</option>
          <option value="paid">{{ t('migrate.paid', 'Paid') }}</option>
        </select>
      </label>
      <label>{{ t('migrate.fSort', 'Sort') }}
        <select v-model="filters.sort" data-testid="mg-sort">
          <option value="new">{{ t('migrate.sortNew', 'Newest') }}</option>
          <option value="uses">{{ t('migrate.sortUses', 'Most used') }}</option>
          <option value="certified">{{ t('migrate.sortCertified', 'Most certified') }}</option>
        </select>
      </label>
      <label class="mg-q">{{ t('migrate.fSearch', 'Search') }}
        <input v-model="filters.q" type="search" maxlength="80" :placeholder="t('migrate.searchPh', 'a system, a table, a name')" data-testid="mg-q" />
      </label>
    </section>

    <p v-if="error" class="mg-error" role="alert" data-testid="mg-error">{{ error }}</p>
    <div v-else-if="loading && !shown.length" class="mg-skel" data-testid="mg-loading" aria-busy="true" role="status">
      <span class="mg-sr">{{ t('migrate.loading', 'Reading the library') }}</span>
      <div v-for="i in 3" :key="i" class="mg-skel-card" aria-hidden="true"><i class="w60"></i><i class="w40"></i><i class="w90"></i><i class="w50"></i></div>
    </div>

    <ul v-if="shown.length" class="mg-gallery" data-testid="mg-gallery">
      <li v-for="tpl in shown" :key="tpl.id" class="mg-card" :data-testid="'mg-card-' + tpl.id">
        <RouterLink :to="{ name: 'migrate-template', params: { id: tpl.id } }" class="mg-card-link">
          <span class="mg-card-title">{{ tpl.title }}</span>
          <span class="mg-card-route">{{ kindWords(tpl.from_kind) }} <Icon name="mdi:arrow-right" /> {{ kindWords(tpl.to_kind) }}</span>
          <span v-if="tpl.summary" class="mg-card-sum">{{ tpl.summary }}</span>
          <span class="mg-card-meta">
            <span class="mg-price" :class="{ free: tpl.pricing_model === 'free' }" :data-testid="'mg-price-' + tpl.id">{{ priceWords(tpl) === 'Free' ? t('migrate.free', 'Free') : priceWords(tpl) }}</span>
            <span>{{ tpl.uses === 1 ? t('migrate.p.download', '1 download') : tp('migrate.uses', '{n} downloads', { n: tpl.uses }) }}</span>
            <span>{{ tpl.certified === 1 ? t('migrate.p.certified', 'certified by 1 developer') : tp('migrate.certified', 'certified by {n} developers', { n: tpl.certified }) }}</span>
            <span v-if="tpl.forks">{{ tpl.forks === 1 ? t('migrate.p.fork', '1 fork') : tp('migrate.forks', '{n} forks', { n: tpl.forks }) }}</span>
          </span>
        </RouterLink>
      </li>
    </ul>
    <p v-else-if="loaded && !loading && !error" class="mg-note" data-testid="mg-empty">{{ t('migrate.empty', 'No template matches yet. Write the first one for this pair: it takes three commands.') }}</p>

    <section class="mg-own" data-testid="mg-own">
      <h2>{{ t('migrate.ownTitle', 'Write your own') }}</h2>
      <p>{{ t('migrate.ownBody', 'A template is a folder: a manifest, a proxy spec with its mappings, a README and sample data. Publish it free or for a price; a fork names its parent and pays the parent\'s author a share of each sale.') }}</p>
      <pre class="mg-code" data-testid="mg-own-commands" tabindex="0" role="region" :aria-label="t('migrate.ownCommandsAria', 'Write your own: the commands')">{{ own.join('\n') }}</pre>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import MigrateTabs from '@/components/migrate/MigrateTabs.vue'
import { useI18n } from '@/composables/useI18n'
import { listTemplates } from '@/services/api/workflowTemplates'
import { DEFAULT_FILTERS, kindWords, matchesFilters, priceWords, writeYourOwn, type Filters, type TemplateListing } from '@/services/migrate/templates'

const { t, tp } = useI18n()
const KINDS = ['sql', 'file', 'rest']
const filters = reactive<Filters>({ ...DEFAULT_FILTERS })
const items = ref<TemplateListing[]>([])
const loading = ref(false)
const loaded = ref(false)         // "none" is said only after a read answered: the first paint comes before the first read
const error = ref('')
const own = writeYourOwn()

// the registry narrows by the query; the same filters are applied to what comes back (a registry that answers with everything)
const shown = computed(() => items.value.filter((x) => matchesFilters(x, filters)))

function why(e: any): string {
  const d = e?.response?.data
  return (typeof d?.detail === 'string' && d.detail) || e?.message || t('migrate.readFailed', 'The library could not be read.')
}

let timer: ReturnType<typeof setTimeout> | null = null
async function load() {
  loading.value = true
  try { items.value = await listTemplates({ ...filters }); error.value = ''; loaded.value = true }
  catch (e) { error.value = why(e) }
  finally { loading.value = false }
}

onMounted(load)
watch(() => ({ ...filters }), () => {
  if (timer) clearTimeout(timer)
  timer = setTimeout(load, 250)       // a typed search asks once it pauses
})
</script>

<style scoped>
.mg { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --mono: 'IBM Plex Mono', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: #e8eaed; display: grid; gap: 1.1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.mg-hero { display: flex; align-items: flex-start; gap: 0.9rem; }
.mg-badge { flex: none; width: 2.8rem; height: 2.8rem; border-radius: 12px; display: grid; place-items: center; background: rgba(var(--cyan-rgb), .1); border: 1px solid rgba(var(--cyan-rgb), .3); }
.mg-badge :deep(svg) { width: 1.5rem; height: 1.5rem; color: var(--cyan); }
.mg-hero h1 { margin: 0; font-size: 1.8rem; font-weight: 300; letter-spacing: -.01em; }
.mg-hero p { margin: 0.3rem 0 0; font-size: 0.9rem; color: var(--muted); max-width: 46rem; line-height: 1.55; }
.mg-steps { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0.8rem; }
.mg-steps li { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 0.9rem 1rem; display: grid; gap: 0.4rem; align-content: start; font-size: 0.82rem; line-height: 1.5; }
.mg-steps strong { font: 700 11px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--cyan); }
.mg-steps span { color: var(--muted); }
.mg-filters { display: flex; flex-wrap: wrap; gap: 0.7rem; align-items: end; }
.mg-filters label { display: grid; gap: 0.3rem; font: 600 .72rem var(--mono); color: #cbd5e1; }
.mg-filters select, .mg-filters input { height: 40px; background: rgba(0,0,0,.35); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 7px; color: #e8eaed; padding: 0 .7rem; font: inherit; font-size: 0.84rem; }
.mg-filters select:focus, .mg-filters input:focus { outline: none; border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }
.mg-q { flex: 1; min-width: 12rem; }
.mg-error { margin: 0; color: #fca5a5; font-size: 0.85rem; }
.mg-note { margin: 0; font-size: 0.85rem; color: var(--muted); }
.mg-gallery { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr)); gap: 0.8rem; }
.mg-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; transition: border-color .15s, transform .15s; }
.mg-card:hover, .mg-card:focus-within { border-color: rgba(var(--cyan-rgb), .5); transform: translateY(-1px); }
.mg-card-link { display: grid; gap: 0.45rem; padding: 1rem 1.1rem; color: inherit; text-decoration: none; height: 100%; align-content: start; }
.mg-card-link:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: -2px; border-radius: 12px; }
.mg-card-title { font-weight: 500; font-size: 1rem; line-height: 1.35; overflow-wrap: anywhere; }
.mg-card-route { font: 600 .72rem var(--mono); color: var(--muted); display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; }
.mg-card-route :deep(svg) { width: 0.9rem; height: 0.9rem; color: var(--cyan); }
.mg-card-sum { font-size: 0.82rem; color: #aab4c0; line-height: 1.5; }
.mg-card-meta { display: flex; flex-wrap: wrap; align-items: center; gap: .3rem 1rem; margin-top: auto; padding-top: .55rem; border-top: 1px solid rgba(255,255,255,.06); font-size: 0.74rem; color: var(--muted); }
.mg-price { font: 700 .76rem var(--mono); color: #fbbf24; }
.mg-price.free { color: #34d399; }
.mg-own { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1.1rem 1.25rem; display: grid; gap: 0.6rem; min-width: 0; }
.mg-own h2 { margin: 0; font-size: 1.05rem; font-weight: 500; }
.mg-own p { margin: 0; font-size: 0.85rem; color: var(--muted); line-height: 1.5; }
.mg-code { margin: 0; background: rgba(0,0,0,.4); border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 8px; padding: 0.7rem 0.9rem; font: 0.78rem/1.6 var(--mono); overflow-x: auto; white-space: pre; }
.mg-code:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 2px; }
@media (max-width: 720px) { .mg { padding: 1rem .8rem 2.5rem; } .mg-steps { grid-template-columns: 1fr; } .mg-hero h1 { font-size: 1.5rem; } .mg-filters label { flex: 1 1 8rem; } .mg-filters select { width: 100%; } }
.mg-cta { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: .8rem; }
.mg-btn { display: inline-flex; align-items: center; min-height: 38px; padding: 0 16px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font-size: .84rem; text-decoration: none; }
.mg-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.mg-btn:hover, .mg-btn:focus-visible { filter: brightness(1.12); }
.mg-skel { display: grid; grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr)); gap: .8rem; }
.mg-skel-card { border: 1px solid rgba(var(--cyan-rgb), .12); border-radius: 12px; padding: 1rem 1.1rem; display: grid; gap: .6rem; min-height: 9rem; }
.mg-skel-card i { display: block; height: .7rem; border-radius: 4px; background: linear-gradient(90deg, rgba(255,255,255,.04), rgba(255,255,255,.09), rgba(255,255,255,.04)); background-size: 200% 100%; animation: mg-shimmer 1.4s linear infinite; }
.mg-skel-card .w60 { width: 60%; height: 1rem; } .mg-skel-card .w40 { width: 40%; } .mg-skel-card .w90 { width: 90%; } .mg-skel-card .w50 { width: 50%; }
.mg-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@keyframes mg-shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .mg-skel-card i { animation: none; } }
</style>
