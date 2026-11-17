<!--
  V0664 C4 (order gwo_85a6015257385f6bb010682e) — #/migrate/runs, My migrations: the acting agent's workflows that were made from a template (the
  workflow's `template` block: id, version, content hash, title), and the certificates it holds. A workflow made by hand is the Workflows page's.
-->
<template>
  <div class="mr" data-testid="mr-root">
    <MigrateTabs current="migrate-runs" />
    <header class="mr-hero">
      <span class="mr-eyebrow">{{ t('migrate.runs.eyebrow', 'Migrate a system · yours') }}</span>
      <h1>{{ t('migrate.runs.title', 'My migrations') }}</h1>
      <p class="mr-lead">{{ t('migrate.runs.lead', 'The workflows you made from a template, which template and version each came from, and the certificates you hold for a load that was read back and passed.') }}</p>
    </header>

    <p v-if="!signedIn" class="mr-note" data-testid="mr-signin">{{ t('migrate.runs.signIn', 'Sign in and pick an agent (top right) to see your migrations.') }}</p>
    <p v-else-if="state === 'loading'" class="mr-note" aria-busy="true" data-testid="mr-loading">{{ t('migrate.runs.loading', 'Reading your migrations…') }}</p>
    <p v-else-if="state === 'error'" class="mr-err" role="alert" data-testid="mr-error">{{ error }}</p>
    <template v-else>
      <section class="mr-sec">
        <h2>{{ t('migrate.runs.workflows', 'Workflows from a template') }}</h2>
        <div v-if="!runs.length" class="mr-empty" data-testid="mr-empty">
          <p>{{ t('migrate.runs.empty', 'None yet. Open a template and choose “Make a workflow from it”.') }}</p>
          <RouterLink :to="{ name: 'migrate' }" class="mr-btn">{{ t('migrate.runs.browse', 'Browse the library') }}</RouterLink>
        </div>
        <ul v-else class="mr-list">
          <li v-for="r in runs" :key="r.id" class="mr-card" :data-testid="`mr-run-${r.id}`">
            <div class="mr-card-h">
              <b class="mr-name">{{ r.title }}</b>
              <span class="mr-chip" :class="r.status" data-testid="mr-status">{{ r.status }}</span>
            </div>
            <p class="mr-prov" data-testid="mr-provenance">
              {{ t('migrate.runs.from', 'From template') }}
              <RouterLink :to="{ name: 'migrate-template', params: { id: r.template!.id } }">{{ r.template!.title || r.template!.id }}</RouterLink>
              <template v-if="r.template!.version !== null"> v{{ r.template!.version }}</template>
              <code v-if="r.template!.content_hash" class="mr-hash" :title="r.template!.content_hash">{{ r.template!.content_hash.slice(0, 12) }}</code>
            </p>
            <p class="mr-meta">{{ budget(r) }}<span v-if="r.created_at"> · {{ day(r.created_at) }}</span></p>
            <p v-if="certsOf(r).length" class="mr-cert" data-testid="mr-run-cert"><Icon name="mdi:certificate" /> {{ certsOf(r).length === 1 ? t('migrate.runs.certOne', '1 certificate for this version') : tp('migrate.runs.certsFor', '{n} certificates for this version', { n: certsOf(r).length }) }}</p>
            <RouterLink :to="{ name: 'workflows' }" class="mr-link">{{ t('migrate.runs.open', 'Open in Workflows') }}</RouterLink>
          </li>
        </ul>
      </section>

      <section class="mr-sec">
        <h2>{{ t('migrate.runs.certs', 'Certificates') }}</h2>
        <p v-if="certState === 'unavailable'" class="mr-note" data-testid="mr-certs-unavailable">{{ t('migrate.runs.certsUnavailable', 'The certificates could not be read just now.') }}</p>
        <p v-else-if="!certs.length" class="mr-note" data-testid="mr-no-certs">{{ t('migrate.runs.noCerts', 'You hold no migration certificate yet. One is made by `tp-proxy migrate certify` after a reconcile that passed.') }}</p>
        <ul v-else class="mr-list">
          <li v-for="c in certs" :key="c.id" class="mr-card" :data-testid="`mr-cert-${c.id}`">
            <div class="mr-card-h"><b class="mr-name">{{ c.claim?.template?.name || t('migrate.runs.unnamed', 'a template') }} <span v-if="c.claim?.template?.version !== undefined">v{{ c.claim.template.version }}</span></b>
              <span class="mr-chip" :class="c.claim?.verdict === 'pass' ? 'ok' : 'bad'">{{ c.claim?.verdict || '?' }}</span></div>
            <p class="mr-meta" data-testid="mr-claim">{{ claimWords(c) }}</p>
            <p class="mr-meta"><code>{{ c.record }}</code></p>
          </li>
        </ul>
        <p class="mr-note small">{{ t('migrate.runs.checkNote', 'To check a certificate against its reports, open “Read a report”: nothing leaves your browser.') }} <RouterLink :to="{ name: 'migrate-report' }">{{ t('migrate.runs.checkLink', 'Read a report') }}</RouterLink></p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import MigrateTabs from '@/components/migrate/MigrateTabs.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { listMyCertificates, listMyRuns } from '@/services/api/workflowTemplates'
import { certificatesFor, claimWords, migrationsOnly, type Certificate, type MyRun } from '@/services/migrate/mine'
import { decimalWords } from '@/services/migrate/templates'

const { t, tp } = useI18n()
const auth = useAuthStore() as any
const signedIn = computed(() => !!auth.token && !!auth.agentToken && !!auth.activeAgent)
const runs = ref<MyRun[]>([])
const certs = ref<Certificate[]>([])
const state = ref<'loading' | 'ok' | 'error'>('loading')
const certState = ref<'ok' | 'unavailable'>('ok')
const error = ref('')

async function load() {
  if (!signedIn.value) return
  state.value = 'loading'
  try { runs.value = migrationsOnly(await listMyRuns()); state.value = 'ok' } catch (e: any) {
    state.value = 'error'; error.value = (typeof e?.response?.data?.detail === 'string' && e.response.data.detail) || e?.message || t('migrate.runs.failed', 'The request failed.')
    return
  }
  try { certs.value = await listMyCertificates() } catch { certs.value = []; certState.value = 'unavailable' }
}
onMounted(load)

const certsOf = (r: MyRun): Certificate[] => (r.template?.content_hash ? certificatesFor(certs.value, { content_hash: r.template.content_hash }) : [])
const budget = (r: MyRun): string => `${decimalWords(r.total_budget)} ${r.currency}`.trim()
const day = (iso: string): string => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 10) }
</script>

<style scoped>
.mr { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.mr-hero { display: grid; gap: .55rem; }
.mr-eyebrow { justify-self: start; font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.mr-hero h1 { margin: 0; font-size: 1.8rem; font-weight: 300; }
.mr-lead { margin: 0; color: var(--muted); font-size: .9rem; max-width: 46rem; line-height: 1.55; }
.mr-note { margin: 0; color: var(--muted); font-size: .85rem; line-height: 1.5; }
.mr-note.small { font-size: .76rem; }
.mr-note a, .mr-prov a, .mr-link { color: var(--cyan); }
.mr-err { margin: 0; color: #fca5a5; font-size: .84rem; }
.mr-sec { display: grid; gap: .7rem; }
.mr-sec h2 { margin: 0; font: 700 11px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.mr-empty { border: 1px dashed rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 1.4rem; display: grid; gap: .7rem; justify-items: start; color: var(--muted); }
.mr-list { list-style: none; margin: 0; padding: 0; display: grid; gap: .7rem; }
.mr-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 12px; padding: .95rem 1.1rem; display: grid; gap: .45rem; }
.mr-card-h { display: flex; justify-content: space-between; gap: .8rem; align-items: center; flex-wrap: wrap; }
.mr-name { font-weight: 500; overflow-wrap: anywhere; }
.mr-chip { font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 4px 9px; border: 1px solid rgba(var(--cyan-rgb), .3); color: var(--cyan); }
.mr-chip.done, .mr-chip.ok { color: #34d399; border-color: rgba(16,185,129,.4); }
.mr-chip.bad, .mr-chip.cancelled { color: #fca5a5; border-color: rgba(248,113,113,.4); }
.mr-chip.draft { color: #fcd34d; border-color: rgba(245,158,11,.4); }
.mr-prov { margin: 0; font-size: .84rem; }
.mr-hash { font: .72rem var(--mono); color: var(--muted); margin-left: .4rem; }
.mr-meta { margin: 0; font-size: .78rem; color: var(--muted); overflow-wrap: anywhere; }
.mr-cert { margin: 0; display: flex; align-items: center; gap: .4rem; font-size: .8rem; color: #86efac; }
.mr-cert :deep(svg) { width: 1rem; height: 1rem; }
.mr-link { font-size: .78rem; justify-self: start; }
.mr-btn { display: inline-flex; align-items: center; min-height: 38px; padding: 0 16px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font-size: .84rem; text-decoration: none; }
@media (max-width: 640px) { .mr { padding: 1rem .8rem 2.5rem; } }
</style>
