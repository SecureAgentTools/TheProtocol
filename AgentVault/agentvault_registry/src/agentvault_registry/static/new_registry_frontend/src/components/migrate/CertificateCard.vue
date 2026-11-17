<!--
  V0664 C4 — a migration certificate, read against the reports dropped with it. Each check says in words whether it holds, does not hold, or
  could not be checked (a report that was not given is never a failure). Nothing here is sent anywhere.
-->
<template>
  <article class="cc" data-testid="rp-cert">
    <header class="cc-head">
      <div class="cc-title">
        <span class="cc-eyebrow">{{ t('migrate.cert.eyebrow', 'Migration certificate') }}</span>
        <h2>{{ t('migrate.cert.title', 'What this certificate claims') }}</h2>
      </div>
      <span class="cc-chip" :class="overall.tone" data-testid="rp-cert-overall">
        <Icon :name="overall.icon" /> {{ overall.label }}
      </span>
      <button type="button" class="cc-x" data-testid="rp-remove-cert" :aria-label="tp('migrate.rep.remove', 'Remove {name}', { name })" @click="$emit('remove')"><Icon name="mdi:close" /></button>
    </header>
    <p class="cc-meta">
      <span>{{ name }}</span>
      <span v-if="claim.template">{{ claim.template.name }} {{ t('migrate.rep.version', 'version') }} {{ claim.template.version }}</span>
      <span v-if="doc.registry">{{ doc.registry }}</span>
    </p>
    <div class="cc-tiles">
      <div class="cc-tile"><span class="lbl">{{ t('migrate.cert.verdict', 'Verdict claimed') }}</span><span class="val">{{ claim.verdict }}</span></div>
      <div class="cc-tile"><span class="lbl">{{ t('migrate.cert.moved', 'Rows moved') }}</span><span class="val">{{ nf(claim.moved) }}</span></div>
      <div class="cc-tile"><span class="lbl">{{ t('migrate.cert.rejected', 'Rows rejected') }}</span><span class="val">{{ nf(claim.rejected) }}</span></div>
    </div>
    <ul class="cc-checks" data-testid="rp-checks">
      <li v-for="c in check?.checks || []" :key="c.key" :data-testid="`rp-check-${c.key}`" :data-state="c.state">
        <Icon :name="c.state === 'ok' ? 'mdi:check-circle' : c.state === 'bad' ? 'mdi:close-circle' : 'mdi:help-circle-outline'" />
        <span class="cc-what"><b>{{ label(c.key) }}</b> <span class="cc-state">{{ stateWord(c.state) }}</span><span class="cc-why">{{ c.detail }}</span></span>
      </li>
    </ul>
    <dl class="cc-hashes">
      <div><dt>{{ t('migrate.cert.claimHash', 'Claim hash') }}</dt><dd data-testid="rp-claim-hash"><code>{{ check?.claimSha256 }}</code></dd></div>
      <div><dt>{{ t('migrate.cert.record', 'Record key') }}</dt><dd><code>{{ doc.attestation_data?.record }}</code></dd></div>
      <div v-for="(h, step) in claimedReports" :key="step"><dt>{{ t('migrate.cert.reportHash', 'Report hash') }} · {{ STEP_WORDS[step as string] || step }}</dt><dd><code>{{ h }}</code></dd></div>
    </dl>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useI18n } from '@/composables/useI18n'
import { formatNumber } from '@/i18n'
/** a count in the reader's own grouping (never the OS's: services/cockpit/num.ts has the why) */
const nf = (v: unknown): string => (typeof v === 'number' && Number.isFinite(v) ? formatNumber(v) : String(v ?? ''))
import type { CertificateCheck } from '@/services/migrate/reportCheck'
import { STEP_WORDS } from '@/services/migrate/reportView'

const props = defineProps<{ doc: any; check: CertificateCheck | null; name: string }>()
defineEmits<{ (e: 'remove'): void }>()
const { t, tp } = useI18n()

const claim = computed(() => props.doc?.attestation_data?.claim ?? {})
const claimedReports = computed(() => Object.fromEntries(Object.entries(claim.value.reports || {}).filter(([, h]) => !!h)))
const LABELS: Record<string, string> = {
  record: 'The record key', template: 'The template version', moved: 'Rows moved', rejected: 'Rows rejected', fresh: 'Reconcile after load', verdict: 'Reconcile verdict',
}
function label(key: string): string {
  if (key.startsWith('report:')) return `${STEP_WORDS[key.slice(7)] || key.slice(7)} ${t('migrate.cert.reportWord', 'report')}`
  return t(`migrate.cert.check.${key}`, LABELS[key] || key)
}
const stateWord = (s: string) => (s === 'ok' ? t('migrate.cert.holds', 'holds') : s === 'bad' ? t('migrate.cert.fails', 'does not hold') : t('migrate.cert.unchecked', 'not checked'))
const overall = computed(() => {
  const cs = props.check?.checks || []
  if (!cs.length) return { tone: 'tone-warn', icon: 'mdi:help-circle-outline', label: t('migrate.cert.reading', 'Reading…') }
  if (cs.some((c) => c.state === 'bad')) return { tone: 'tone-bad', icon: 'mdi:close-circle', label: t('migrate.cert.someFail', 'Something does not hold') }
  if (cs.some((c) => c.state === 'unknown')) return { tone: 'tone-warn', icon: 'mdi:help-circle-outline', label: t('migrate.cert.partial', 'Holds as far as checked') }
  return { tone: 'tone-ok', icon: 'mdi:shield-check', label: t('migrate.cert.allHold', 'Everything holds') }
})
</script>

<style scoped>
.cc { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  background: linear-gradient(168deg, rgba(255,255,255,.03), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .05); border: 1px solid rgba(var(--cyan-rgb), .3);
  border-radius: 12px; padding: 1.1rem 1.25rem 1.2rem; display: grid; gap: .9rem; box-shadow: inset 0 1px 0 rgba(255,255,255,.04), 0 12px 32px -22px rgba(0,0,0,.8); }
.cc-head { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem .8rem; }
.cc-title { display: grid; gap: .2rem; margin-right: auto; }
.cc-eyebrow { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); }
.cc-head h2 { margin: 0; font-size: 1.25rem; font-weight: 300; color: var(--bright); }
.cc-chip { display: inline-flex; align-items: center; gap: .4rem; border: 1px solid; border-radius: 999px; padding: 4px 11px; font-size: .78rem; font-weight: 500; }
.cc-chip :deep(svg) { width: .95rem; height: .95rem; }
.tone-ok { color: #10b981; border-color: rgba(16,185,129,.4); background: rgba(16,185,129,.07); }
.tone-bad { color: #ef4444; border-color: rgba(239,68,68,.45); background: rgba(239,68,68,.07); }
.tone-warn { color: #f59e0b; border-color: rgba(245,158,11,.4); background: rgba(245,158,11,.06); }
.cc-x { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .18); background: none; color: var(--muted); cursor: pointer; }
.cc-x:hover, .cc-x:focus-visible { color: var(--bright); border-color: rgba(var(--cyan-rgb), .5); }
.cc-x :deep(svg) { width: 1rem; height: 1rem; }
.cc-meta { margin: 0; display: flex; flex-wrap: wrap; gap: .3rem 1.1rem; font-size: .74rem; color: var(--muted); }
.cc-tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.cc-tile { background: rgba(var(--cyan-rgb), .03); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 8px; padding: 12px 14px; display: grid; gap: 6px; }
.cc-tile .lbl { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.cc-tile .val { font-size: 1.5rem; font-weight: 300; color: var(--bright); font-variant-numeric: tabular-nums; }
.cc-checks { list-style: none; margin: 0; padding: 0; display: grid; gap: 0; border-top: 1px solid rgba(var(--cyan-rgb), .12); }
.cc-checks li { display: grid; grid-template-columns: 1.3rem minmax(0, 1fr); gap: .6rem; padding: .65rem 0; border-bottom: 1px solid rgba(255,255,255,.05); font-size: .82rem; align-items: start; }
.cc-checks li :deep(svg) { width: 1.1rem; height: 1.1rem; margin-top: 1px; }
.cc-checks li[data-state="ok"] :deep(svg) { color: #10b981; }
.cc-checks li[data-state="bad"] :deep(svg) { color: #ef4444; }
.cc-checks li[data-state="unknown"] :deep(svg) { color: #f59e0b; }
.cc-what b { font-weight: 500; color: var(--bright); }
.cc-state { margin-left: .5rem; font: 700 10px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.cc-why { display: block; color: var(--muted); font-size: .76rem; margin-top: 2px; }
.cc-hashes { margin: 0; display: grid; gap: .5rem; }
.cc-hashes div { display: grid; grid-template-columns: 11rem minmax(0, 1fr); gap: .8rem; font-size: .74rem; }
.cc-hashes dt { color: var(--muted); }
.cc-hashes dd { margin: 0; overflow-wrap: anywhere; }
.cc-hashes code { font-family: var(--mono); color: var(--bright); }
@media (max-width: 640px) { .cc { padding: .9rem; } .cc-tiles { grid-template-columns: 1fr; } .cc-hashes div { grid-template-columns: 1fr; gap: .15rem; } }
</style>
