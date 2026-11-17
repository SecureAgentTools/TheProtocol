<!--
  V0664 C4 (order gwo_85a6015257385f6bb010682e) — #/migrate/report. Drop, choose or paste a migration report, or a certificate with its reports, and read it
  as a page: the counts, the rejected rows by reason, the fill per field, the reconcile verdict. The hashes are recomputed HERE (WebCrypto sha256 over
  canonical JSON, pinned against Python's by vectors) and matched to the certificate. Public, and nothing leaves the browser: this page makes no request.
-->
<template>
  <div class="rp" data-testid="rp-root" :aria-busy="reading ? 'true' : 'false'">
    <MigrateTabs current="migrate-report" />
    <header class="rp-hero">
      <span class="rp-eyebrow">{{ t('migrate.rep.eyebrow', 'Migrate a system · report') }}</span>
      <h1>{{ t('migrate.rep.title', 'Read a migration report') }}</h1>
      <p class="rp-lead">{{ t('migrate.rep.lead', 'Drop the JSON a migration wrote (a report, or a certificate with its reports) and read it as a page. Each report\'s hash is recomputed here and matched to the certificate\'s claim.') }}</p>
      <p class="rp-privacy" data-testid="rp-privacy"><Icon name="mdi:lock" /> {{ t('migrate.rep.privacy', 'Nothing leaves your browser: the files are read here and no request is made. A report holds counts, names and hashes, never a record\'s value.') }}</p>
    </header>

    <section class="rp-drop" data-testid="rp-drop" :class="{ over }" @dragover.prevent="over = true" @dragleave="over = false" @drop.prevent="onDrop">
      <Icon name="mdi:upload" class="rp-drop-ico" />
      <p>{{ t('migrate.rep.dropHere', 'Drop report or certificate files here') }}</p>
      <label class="rp-btn primary">
        {{ t('migrate.rep.choose', 'Choose files') }}
        <input type="file" multiple accept=".json,application/json" class="rp-file" data-testid="rp-file" @change="onChoose" />
      </label>
      <details class="rp-paste-box">
        <summary>{{ t('migrate.rep.orPaste', 'or paste the JSON') }}</summary>
        <textarea v-model="pasted" rows="6" spellcheck="false" class="rp-paste" data-testid="rp-paste" :aria-label="t('migrate.rep.pasteLabel', 'The JSON of a report or a certificate')" />
        <button type="button" class="rp-btn" data-testid="rp-read" :disabled="!pasted.trim()" @click="readPasted">{{ t('migrate.rep.read', 'Read it') }}</button>
      </details>
    </section>

    <p class="rp-status" role="status" data-testid="rp-status">{{ status }}</p>

    <div v-if="!shown.length" class="rp-empty" data-testid="rp-empty">
      <Icon name="mdi:file-document" />
      <p>{{ t('migrate.rep.empty', 'Nothing read yet. A migration writes its reports to the kit\'s .migrate/reports folder and its certificate to .migrate/certificate.json.') }}</p>
      <RouterLink :to="{ name: 'migrate' }">{{ t('migrate.rep.back', 'Back to migration templates') }}</RouterLink>
    </div>

    <div v-else class="rp-list">
      <div class="rp-bar">
        <span></span>
        <button type="button" class="rp-btn ghost" data-testid="rp-clear" @click="clearAll">{{ t('migrate.rep.clear', 'Clear all') }}</button>
      </div>
      <template v-for="it in shown" :key="it.key">
        <CertificateCard v-if="it.kind === 'certificate'" :doc="it.doc" :name="it.name" :check="checks[it.key] || null" @remove="remove(it.key)" />
        <ReportCard v-else-if="it.kind === 'report'" :doc="it.doc" :holds="it.holds" :name="it.name" @remove="remove(it.key)" />
        <article v-else class="rp-error" data-testid="rp-error" role="alert">
          <Icon name="mdi:alert-circle-outline" />
          <div><b>{{ it.name }}</b><span>{{ it.error }}</span></div>
          <button type="button" class="rp-x" :aria-label="tp('migrate.rep.remove', 'Remove {name}', { name: it.name })" @click="remove(it.key)"><Icon name="mdi:close" /></button>
        </article>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import MigrateTabs from '@/components/migrate/MigrateTabs.vue'
import ReportCard from '@/components/migrate/ReportCard.vue'
import CertificateCard from '@/components/migrate/CertificateCard.vue'
import { useI18n } from '@/composables/useI18n'
import { checkCertificate, type CertificateCheck } from '@/services/migrate/reportCheck'
import { readTexts, sortItems, type Item } from '@/services/migrate/reportView'

const { t, tp } = useI18n()
type Keyed = Item & { key: string }
const items = ref<Keyed[]>([])
const checks = ref<Record<string, CertificateCheck>>({})
const pasted = ref('')
const over = ref(false)
const status = ref('')
const busy = ref(0)               // files being read
const checking = ref(0)           // certificates being checked
const reading = computed(() => busy.value > 0 || checking.value > 0)

// a report is its hash, a certificate its record key: the same one dropped twice is shown once
const keyOf = (i: Item, n: number): string => (i.kind === 'report' ? `r:${i.doc.report_sha256 || n}` : i.kind === 'certificate' ? `c:${i.doc.attestation_data?.record || n}` : `e:${i.name}:${n}`)
const shown = computed(() => sortItems(items.value) as Keyed[])

async function fileText(f: File): Promise<string> {
  if (typeof (f as any).text === 'function') return (f as any).text()
  return new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(String(r.result)); r.onerror = () => reject(r.error); r.readAsText(f) })
}

async function take(files: Array<{ name: string; text: string }>) {
  busy.value++
  try { await takeNow(files) } finally { busy.value-- }
}
async function takeNow(files: Array<{ name: string; text: string }>) {
  const read = await readTexts(files)
  const have = new Set(items.value.map((i) => i.key))
  const add: Keyed[] = []
  read.forEach((i, n) => {
    const key = keyOf(i, items.value.length + n)
    if (have.has(key)) return
    have.add(key)
    add.push({ ...i, key } as Keyed)
  })
  items.value = [...items.value, ...add]
  const ok = read.filter((i) => i.kind !== 'error').length
  status.value = tp('migrate.rep.statusRead', 'Read {ok} of {n} files.', { ok, n: read.length })
}

async function onChoose(e: Event) {
  const input = e.target as HTMLInputElement
  const list = Array.from(input.files || [])
  await take(await Promise.all(list.map(async (f) => ({ name: f.name, text: await fileText(f) }))))
  try { input.value = '' } catch { /* a test input */ }
}
async function onDrop(e: DragEvent) {
  over.value = false
  const list = Array.from(e.dataTransfer?.files || [])
  await take(await Promise.all(list.map(async (f) => ({ name: f.name, text: await fileText(f) }))))
}
async function readPasted() {
  const text = pasted.value
  await take([{ name: t('migrate.rep.pastedName', 'pasted text'), text }])
  pasted.value = ''
}
function remove(key: string) { items.value = items.value.filter((i) => i.key !== key); status.value = '' }
function clearAll() { items.value = []; checks.value = {}; status.value = '' }

// a certificate is checked against whatever reports are on the page, again whenever they change
watch(items, async (list) => {
  checking.value++
  try {
    const reports = list.filter((i) => i.kind === 'report').map((i: any) => i.doc)
    const next: Record<string, CertificateCheck> = {}
    for (const i of list) if (i.kind === 'certificate') next[i.key] = await checkCertificate((i as any).doc, reports)
    checks.value = next
  } finally { checking.value-- }
}, { deep: false })
</script>

<style scoped>
.rp { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', 'Fira Code', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.6rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.2rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.rp-hero { display: grid; gap: .6rem; }
.rp-eyebrow { justify-self: start; font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.rp-hero h1 { margin: 0; font-size: 1.9rem; font-weight: 300; letter-spacing: -.01em; }
.rp-lead { margin: 0; color: var(--muted); font-size: .92rem; max-width: 46rem; line-height: 1.55; }
.rp-privacy { margin: 0; display: flex; gap: .55rem; align-items: flex-start; font-size: .82rem; color: #86efac; border: 1px solid rgba(16,185,129,.3); background: rgba(16,185,129,.05); border-radius: 8px; padding: .55rem .8rem; max-width: 46rem; }
.rp-privacy :deep(svg) { width: 1rem; height: 1rem; flex: none; margin-top: 2px; }
.rp-drop { border: 1px dashed rgba(var(--cyan-rgb), .35); border-radius: 12px; padding: 1.6rem 1.2rem; display: grid; justify-items: center; gap: .7rem; text-align: center; background: rgba(var(--cyan-rgb), .02); transition: border-color .15s, background .15s; }
.rp-drop.over { border-color: var(--cyan); background: rgba(var(--cyan-rgb), .07); }
.rp-drop p { margin: 0; color: var(--muted); font-size: .9rem; }
.rp-drop-ico :deep(svg), .rp-drop-ico { width: 1.8rem; height: 1.8rem; color: var(--cyan); }
.rp-file { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); opacity: 0; }
.rp-btn { position: relative; display: inline-flex; align-items: center; gap: .4rem; min-height: 38px; padding: 0 16px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: inherit; font-size: .84rem; cursor: pointer; }
.rp-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.rp-btn.primary:focus-within { outline: 2px solid var(--bright); outline-offset: 2px; }
.rp-btn.ghost { background: none; color: var(--muted); border-color: rgba(var(--cyan-rgb), .18); }
.rp-btn:disabled { opacity: .45; cursor: default; }
.rp-btn:active:not(:disabled) { transform: translateY(1px); }
.rp-paste-box { width: 100%; max-width: 40rem; text-align: left; display: grid; gap: .6rem; }
.rp-paste-box summary { cursor: pointer; color: var(--muted); font-size: .84rem; justify-self: center; padding: 6px 4px; }
.rp-paste { width: 100%; background: rgba(0,0,0,.35); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 7px; padding: 9px 11px; color: var(--bright); font: .78rem/1.5 var(--mono); resize: vertical; }
.rp-paste:focus { outline: none; border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }
.rp-status { margin: 0; min-height: 1.1rem; font-size: .78rem; color: var(--muted); }
.rp-empty { display: grid; justify-items: center; gap: .6rem; text-align: center; padding: 2.2rem 1rem; color: var(--muted); border: 1px solid rgba(var(--cyan-rgb), .12); border-radius: 12px; }
.rp-empty :deep(svg) { width: 1.8rem; height: 1.8rem; opacity: .6; }
.rp-empty p { margin: 0; max-width: 34rem; font-size: .88rem; line-height: 1.55; }
.rp-empty a { color: var(--cyan); font-size: .84rem; }
.rp-list { display: grid; gap: 1rem; }
.rp-bar { display: flex; align-items: center; justify-content: space-between; font-size: .8rem; color: var(--muted); }
.rp-error { display: grid; grid-template-columns: auto 1fr auto; gap: .7rem; align-items: start; border: 1px solid rgba(245,158,11,.4); background: rgba(245,158,11,.05); border-radius: 10px; padding: .8rem 1rem; font-size: .84rem; }
.rp-error > :deep(svg) { width: 1.2rem; height: 1.2rem; color: #f59e0b; margin-top: 1px; }
.rp-error div { display: grid; gap: .2rem; }
.rp-error span { color: var(--muted); }
.rp-x { width: 32px; height: 32px; display: grid; place-items: center; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .18); background: none; color: var(--muted); cursor: pointer; }
.rp-x :deep(svg) { width: 1rem; height: 1rem; }
@media (max-width: 640px) { .rp { padding: 1rem .8rem 2.5rem; } .rp-hero h1 { font-size: 1.5rem; } }
</style>
