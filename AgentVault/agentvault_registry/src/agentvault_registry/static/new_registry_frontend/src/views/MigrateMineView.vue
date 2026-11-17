<!--
  V0664 C4 (order gwo_85a6015257385f6bb010682e) — #/migrate/mine, My templates: the acting agent's own templates (drafts, unlisted and public),
  their versions, the listing's price and fork share, the buyers and how many developers certified a run of them. Reads GET /workflow-templates/mine;
  a registry that does not have the route yet says so. Writes (publish a version, change the listing) are the acting agent's, as in the library.
-->
<template>
  <div class="mm" data-testid="mm-root">
    <MigrateTabs current="migrate-mine" />
    <header class="mm-hero">
      <span class="mm-eyebrow">{{ t('migrate.mine.eyebrow', 'Migrate a system · yours') }}</span>
      <h1>{{ t('migrate.mine.title', 'My templates') }}</h1>
      <p class="mm-lead">{{ t('migrate.mine.lead', 'Your drafts, your unlisted and your public templates, with their versions, what they cost, who bought them and how many developers certified a run of them.') }}</p>
    </header>

    <p v-if="!signedIn" class="mm-note" data-testid="mm-signin">{{ t('migrate.mine.signIn', 'Sign in and pick an agent (top right) to see your templates.') }}</p>
    <p v-else-if="state === 'loading'" class="mm-note" aria-busy="true" data-testid="mm-loading">{{ t('migrate.mine.loading', 'Reading your templates…') }}</p>
    <p v-else-if="state === 'unavailable'" class="mm-note" data-testid="mm-unavailable">{{ t('migrate.mine.unavailable', 'This registry cannot list your templates yet. The library itself works: open one by its address, or build a new one.') }}</p>
    <p v-else-if="state === 'error'" class="mm-err" role="alert" data-testid="mm-error">{{ error }}</p>
    <div v-else-if="!items.length" class="mm-empty" data-testid="mm-empty">
      <p>{{ t('migrate.mine.empty', 'You have no templates yet.') }}</p>
      <RouterLink :to="{ name: 'migrate-new' }" class="mm-btn primary">{{ t('migrate.mine.buildOne', 'Build a migration') }}</RouterLink>
    </div>

    <article v-for="it in items" :key="it.t.id" class="mm-card" :data-testid="`mm-card-${it.t.id}`">
      <header class="mm-card-h">
        <div>
          <h2><RouterLink :to="{ name: 'migrate-template', params: { id: it.t.id } }" data-testid="mm-title">{{ it.t.title || it.t.slug }}</RouterLink></h2>
          <code class="mm-slug">{{ it.t.slug }}</code>
        </div>
        <span class="mm-chip" :class="stateOf(it.t)" data-testid="mm-state">{{ stateWords(it.t) }}</span>
      </header>

      <dl class="mm-stats" data-testid="mm-stats">
        <div><dt>{{ t('migrate.mine.kits', 'Kit downloads') }}</dt><dd>{{ it.t.uses }}</dd></div>
        <div><dt>{{ t('migrate.mine.users', 'Used by') }}</dt><dd>{{ it.t.used_by }}</dd></div>
        <div><dt>{{ t('migrate.mine.forks', 'Forks') }}</dt><dd>{{ it.t.forks }}</dd></div>
        <div><dt>{{ t('migrate.mine.buyers', 'Buyers') }}</dt><dd data-testid="mm-buyers">{{ it.t.buyers }}</dd></div>
      </dl>
      <p class="mm-cert" data-testid="mm-certified">{{ certifiedBy(certCount(it.t)) }}</p>

      <section class="mm-sec">
        <h3>{{ t('migrate.mine.versions', 'Versions') }}</h3>
        <ul class="mm-versions">
          <li v-for="v in it.t.versions" :key="v.version" :data-testid="`mm-version-${v.version}`">
            <b>v{{ v.version }}</b>
            <span class="mm-chip small" :class="v.published ? 'published' : 'draft'">{{ v.published ? t('migrate.mine.published', 'published') : t('migrate.mine.draft', 'draft') }}</span>
            <code class="mm-hash" :title="v.content_hash">{{ v.content_hash.slice(0, 12) }}</code>
            <span class="mm-cl">{{ v.changelog }}</span>
            <button v-if="!v.published" type="button" class="mm-btn small" :disabled="it.busy" :data-testid="`mm-publish-${v.version}`" @click="publish(it, v.version)">{{ t('migrate.mine.publish', 'Publish') }}</button>
          </li>
        </ul>
        <p v-if="!it.t.versions.length" class="mm-note">{{ t('migrate.mine.noVersions', 'No versions were read for this template.') }}</p>
        <p class="mm-note small">{{ t('migrate.mine.immutable', 'A published version never changes: a change is a new version.') }}</p>
      </section>

      <section class="mm-sec">
        <h3>{{ t('migrate.mine.listing', 'The listing') }}</h3>
        <div class="mm-form">
          <label class="mm-f"><span>{{ t('migrate.mine.visibility', 'Who sees it') }}</span>
            <select v-model="it.visibility" class="mm-in" data-testid="mm-visibility"><option value="private">{{ t('migrate.mine.vPrivate', 'only me') }}</option><option value="org">{{ t('migrate.mine.vOrg', 'my organization') }}</option><option value="unlisted">{{ t('migrate.mine.vUnlisted', 'anyone with the address') }}</option><option value="public">{{ t('migrate.mine.vPublic', 'everyone, in the library') }}</option></select></label>
          <label class="mm-f"><span>{{ t('migrate.mine.pricing', 'Price') }}</span>
            <select v-model="it.pricing" class="mm-in" data-testid="mm-pricing"><option value="free">{{ t('migrate.mine.free', 'free') }}</option><option value="purchase">{{ t('migrate.mine.paid', 'a price to buy') }}</option></select></label>
          <label v-if="it.pricing === 'purchase'" class="mm-f"><span>{{ it.t.price_currency ? tp('migrate.mine.amountIn', 'Amount, in {c}', { c: it.t.price_currency }) : t('migrate.mine.amount', 'Amount') }}</span>
            <input v-model="it.price" class="mm-in mono" inputmode="decimal" data-testid="mm-price" /></label>
          <label class="mm-f"><span>{{ t('migrate.mine.shareShort', 'Original author share, %') }}</span>
            <input v-model="it.share" class="mm-in mono" inputmode="decimal" data-testid="mm-share" /><small>{{ t('migrate.mine.shareHint', 'Paid by a fork of this template, 0 to 50.') }}</small></label>
        </div>
        <button type="button" class="mm-btn" :disabled="it.busy || !dirty(it)" data-testid="mm-save" @click="saveListing(it)">{{ t('migrate.mine.save', 'Save the listing') }}</button>
        <p v-if="it.saved" class="mm-ok" data-testid="mm-saved">{{ t('migrate.mine.saved', 'Saved.') }}</p>
        <p v-if="it.error" class="mm-err" role="alert" data-testid="mm-row-error">{{ it.error }}</p>
      </section>

      <section class="mm-sec">
        <h3>{{ t('migrate.mine.buyersH', 'Buyers') }}</h3>
        <ul v-if="it.t.buyer_rows.length" class="mm-buyers" data-testid="mm-buyer-rows"><li v-for="b in it.t.buyer_rows" :key="b.agent_did + b.at" :title="b.agent_did">
          <b v-if="b.name" class="mm-bname">{{ b.name }}</b><code class="mm-bdid">{{ shortDid(b.agent_did) }}</code> <time>{{ when(b.at) }}</time></li></ul>
        <p v-else class="mm-note">{{ it.t.buyers ? tp('migrate.mine.buyersCount', '{n} bought it; the registry names none of them to you.', { n: it.t.buyers }) : t('migrate.mine.noBuyers', 'Nobody has bought it yet.') }}</p>
      </section>
    </article>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import MigrateTabs from '@/components/migrate/MigrateTabs.vue'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'
import { listMyTemplates, listMyCertificates, patchTemplate, publishVersion } from '@/services/api/workflowTemplates'
import { certificatesFor, certifiedBy, stateOf, hasNewerDraft, type Certificate, type MyTemplate } from '@/services/migrate/mine'
import { decimalWords } from '@/services/migrate/templates'
import { shortDid } from '@/services/guild/orderView'

const { t, tp } = useI18n()
const auth = useAuthStore() as any
const signedIn = computed(() => !!auth.token && !!auth.agentToken && !!auth.activeAgent)

interface Row { t: MyTemplate; visibility: string; pricing: string; price: string; share: string; busy: boolean; error: string; saved: boolean }
const items = ref<Row[]>([])
const certs = ref<Certificate[]>([])
const state = ref<'loading' | 'ok' | 'unavailable' | 'error'>('loading')
const error = ref('')

const row = (x: MyTemplate): Row => reactive({ t: x, visibility: x.visibility, pricing: x.pricing_model, price: decimalWords(x.price), share: String(x.fork_share_bps / 100), busy: false, error: '', saved: false }) as Row
function why(e: any): string {
  const d = e?.response?.data
  return (typeof d?.detail === 'string' && d.detail) || e?.message || t('migrate.mine.failed', 'The request failed.')
}
async function load() {
  if (!signedIn.value) return
  state.value = 'loading'
  try {
    items.value = (await listMyTemplates()).map(row)
    state.value = 'ok'
  } catch (e: any) {
    const s = e?.response?.status
    if (s === 404 || s === 405) state.value = 'unavailable'
    else { state.value = 'error'; error.value = why(e) }
    return
  }
  try { certs.value = await listMyCertificates() } catch { certs.value = [] }   // the certificates are a second read: a failure leaves the counts to the library's own
}
onMounted(load)

const certCount = (x: MyTemplate): number => Math.max(x.certified, new Set(certificatesFor(certs.value, x).map((c) => c.target)).size)
const stateWords = (x: MyTemplate): string => {
  const s = stateOf(x)
  const base = s === 'draft' ? t('migrate.mine.sDraft', 'draft') : s === 'unlisted' ? t('migrate.mine.sUnlisted', 'unlisted') : t('migrate.mine.sPublished', 'published')
  return hasNewerDraft(x) ? `${base} · ${t('migrate.mine.newerDraft', 'a newer draft')}` : base
}
const when = (iso: string): string => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 16).replace('T', ' ') + ' UTC' }

const pct = (r: Row): number => Number(String(r.share).replace(',', '.'))
const dirty = (r: Row): boolean => r.visibility !== r.t.visibility || r.pricing !== r.t.pricing_model || (r.pricing === 'purchase' && r.price !== decimalWords(r.t.price)) || Math.round(pct(r) * 100) !== r.t.fork_share_bps

async function saveListing(r: Row) {
  r.error = ''; r.saved = false
  const p = pct(r)
  if (!Number.isFinite(p) || p < 0 || p > 50) { r.error = t('migrate.mine.shareRange', 'The share is a number from 0 to 50.'); return }
  const body: any = { visibility: r.visibility, pricing_model: r.pricing, fork_share_bps: Math.round(p * 100) }
  if (r.pricing === 'purchase') body.price = r.price
  r.busy = true
  try {
    await patchTemplate(r.t.id, body)
    Object.assign(r.t, { visibility: r.visibility, pricing_model: r.pricing, price: r.pricing === 'purchase' ? r.price : '0', fork_share_bps: body.fork_share_bps })
    r.saved = true
  } catch (e) { r.error = why(e) } finally { r.busy = false }
}
async function publish(r: Row, version: number) {
  r.error = ''; r.saved = false; r.busy = true
  try {
    await publishVersion(r.t.id, version)
    const v = r.t.versions.find((x) => x.version === version)
    if (v) v.published = true
  } catch (e) { r.error = why(e) } finally { r.busy = false }
}
</script>

<style scoped>
.mm { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.1rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.mm-hero { display: grid; gap: .55rem; }
.mm-eyebrow { justify-self: start; font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.mm-hero h1 { margin: 0; font-size: 1.8rem; font-weight: 300; }
.mm-lead { margin: 0; color: var(--muted); font-size: .9rem; max-width: 46rem; line-height: 1.55; }
.mm-note { margin: 0; color: var(--muted); font-size: .85rem; line-height: 1.5; }
.mm-note.small { font-size: .74rem; }
.mm-err { margin: 0; color: #fca5a5; font-size: .84rem; }
.mm-ok { margin: 0; color: #34d399; font-size: .82rem; }
.mm-empty { border: 1px dashed rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 1.6rem; display: grid; gap: .8rem; justify-items: start; color: var(--muted); }
.mm-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 12px; padding: 1.1rem 1.25rem; display: grid; gap: 1rem; }
.mm-card-h { display: flex; justify-content: space-between; gap: 1rem; align-items: flex-start; flex-wrap: wrap; }
.mm-card h2 { margin: 0; font-size: 1.1rem; font-weight: 500; }
.mm-card h2 a { color: var(--bright); text-decoration: none; }
.mm-card h2 a:hover, .mm-card h2 a:focus-visible { color: var(--cyan); }
.mm-slug { font: .74rem var(--mono); color: var(--muted); }
.mm-chip { font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 5px 10px; border: 1px solid rgba(var(--cyan-rgb), .3); color: var(--cyan); }
.mm-chip.published { color: var(--cyan); }
.mm-chip.draft { color: #fcd34d; border-color: rgba(245,158,11,.4); }
.mm-chip.unlisted { color: var(--muted); border-color: rgba(255,255,255,.2); }
.mm-chip.small { padding: 3px 8px; font-size: 9px; }
.mm-stats { margin: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .6rem; }
.mm-stats div { background: rgba(0,0,0,.25); border: 1px solid rgba(var(--cyan-rgb), .12); border-radius: 9px; padding: .55rem .7rem; }
.mm-stats dt { font: 700 9.5px/1.2 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
.mm-stats dd { margin: .25rem 0 0; font: 500 1.25rem var(--mono); font-variant-numeric: tabular-nums; }
.mm-cert { margin: 0; font-size: .84rem; color: #86efac; }
.mm-sec { display: grid; gap: .6rem; border-top: 1px solid rgba(255,255,255,.06); padding-top: .8rem; }
.mm-sec h3 { margin: 0; font: 700 11px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }
.mm-versions, .mm-buyers { list-style: none; margin: 0; padding: 0; display: grid; gap: .4rem; }
.mm-versions li { display: flex; flex-wrap: wrap; align-items: center; gap: .6rem; font-size: .82rem; }
.mm-hash { font: .74rem var(--mono); color: var(--muted); }
.mm-cl { color: var(--muted); flex: 1 1 10rem; min-width: 0; overflow-wrap: anywhere; }
.mm-buyers li { display: flex; flex-wrap: wrap; align-items: baseline; gap: .1rem .6rem; font-size: .82rem; }
.mm-bname { font-weight: 500; }
.mm-bdid { font: .72rem var(--mono); color: var(--muted); }
.mm-buyers time { color: var(--muted); margin-left: .5rem; font-family: var(--mono); font-size: .72rem; }
.mm-form { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); gap: .8rem; align-items: end; }
.mm-f { display: grid; gap: .3rem; font-size: .8rem; }
.mm-f > span { font: 600 .74rem var(--mono); color: #cbd5e1; }
.mm-f small { color: var(--muted); font-size: .7rem; }
.mm-in { min-height: 40px; background: rgba(0,0,0,.35); border: 1px solid rgba(var(--cyan-rgb), .18); border-radius: 7px; padding: 8px 11px; color: var(--bright); font: inherit; font-size: .85rem; width: 100%; min-width: 0; }
.mm-in.mono { font-family: var(--mono); font-size: .8rem; }
.mm-in:focus { outline: none; border-color: rgba(var(--cyan-rgb), .5); box-shadow: 0 0 0 3px rgba(var(--cyan-rgb), .12); }
.mm-btn { justify-self: start; display: inline-flex; align-items: center; justify-content: center; min-height: 38px; padding: 0 16px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: inherit; font-size: .84rem; cursor: pointer; text-decoration: none; }
.mm-btn.small { min-height: 30px; padding: 0 12px; font-size: .76rem; }
.mm-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.mm-btn:disabled { opacity: .45; cursor: default; }
@media (max-width: 640px) { .mm { padding: 1rem .8rem 2.5rem; } .mm-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } .mm-card { padding: .9rem; } }
</style>
