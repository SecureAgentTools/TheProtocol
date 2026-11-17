<!--
  V0664 (order gwo_fc4ec96d3679ca02d5e3afa8, his screenshot seq 4058): the Code changes page, #/code-changes. It explains the way a change goes (seven steps, who acts at each,
  what a sensitive path needs), lists the changes as cards (state, the step it is at, the paths, bounty or branch, the author, the ballot's tally) with filters by state,
  and invites the first one with an example. One change has its own page (#/code-changes/:id); proposing is a guided flow (#/code-changes/new). The registry decides every
  step again (services/code_changes): this page words the record.
-->
<template>
  <div class="ccl" data-testid="ccl-root">
    <CodeChangesTabs current="code-changes" />

    <header class="ccl-hero">
      <span class="ccl-eyebrow">{{ t('codeChanges.eyebrow', 'Governed code') }}</span>
      <h1>{{ t('codeChanges.title', 'Code changes') }}</h1>
      <p class="ccl-lede">{{ t('codeChanges.intro', 'Changes to the console and its documentation, proposed by members, checked by a signed checker, reviewed by members who did not write them and decided by the frame\'s members. Nothing is merged without a passed ballot, and nothing reaches production except through a release.') }}</p>
      <GovernedElsewhere v-if="authorityView_.readOnly" :view="authorityView_" />
      <!-- V0667 the passport: take part on the governing registry from here (session-lead seq 5361: beside the governing sentence) -->
      <CodePassportPress v-if="authorityView_.readOnly && auth.isAuthenticated" />
      <div class="ccl-cta">
        <RouterLink v-if="!authorityView_.readOnly" :to="{ name: 'code-changes-new' }" class="ccl-btn primary" data-testid="ccl-propose">{{ t('codeChanges.propose.open', 'Propose a change') }}</RouterLink>
        <a href="#ccl-way" class="ccl-btn" data-testid="ccl-way-link" @click.prevent="scrollTo('ccl-way')">{{ t('codeChanges.way.link', 'How a change goes') }}</a>
      </div>
      <RepoAccountLink :status="repo" @linked="loadRepo" />
    </header>

    <details id="ccl-way" class="ccl-card ccl-way" data-testid="ccl-way" :open="wide">
      <summary class="ccl-way-sum"><h2>{{ t('codeChanges.way.title', 'How a change goes') }}</h2><span class="ccl-way-hint">{{ t('codeChanges.way.hint', 'seven steps') }}</span></summary>
      <ChangeStepper :steps="explain" explain />
      <div class="ccl-rules">
        <p data-testid="ccl-open-rule"><Icon name="mdi:check-circle" /> {{ t('codeChanges.rule.open', 'Open in this phase: the console and its documentation. Never a secret, a key, a build or a dependency file.') }}</p>
        <p data-testid="ccl-sensitive-rule"><Icon name="mdi:shield-check" /> {{ sensitiveNeeds(tr) }}</p>
        <p data-testid="ccl-terms"><Icon name="mdi:file-document" /> {{ t('codeChanges.rule.terms', 'A contribution is offered under the project\'s licences.') }}
          <a :href="safeExternalUrl(LICENCE_URL)" target="_blank" rel="noopener noreferrer">{{ t('codeChanges.rule.termsLink', 'Read them') }}</a></p>
      </div>
    </details>

    <section class="ccl-listing" data-static="omit" :aria-busy="loading ? 'true' : 'false'">
      <div class="ccl-bar">
        <h2>{{ t('codeChanges.list.title', 'The changes') }}</h2>
        <div class="ccl-filters" role="group" :aria-label="t('codeChanges.filters.aria', 'Filter by state')">
          <button v-for="f in FILTERS" :key="f.key" type="button" class="ccl-filter" :class="{ on: filter === f.key }" :aria-pressed="filter === f.key ? 'true' : 'false'" :data-testid="`ccl-filter-${f.key}`" @click="filter = f.key">
            {{ filterLabel(f.key) }} <span class="ccl-count">{{ count(f.key) }}</span>
          </button>
        </div>
      </div>

      <div v-if="loading && !list.length" class="ccl-skel" data-testid="ccl-loading" role="status">
        <span class="ccl-sr">{{ t('codeChanges.list.loading', 'Reading the changes') }}</span>
        <div v-for="i in 3" :key="i" class="ccl-skel-card" aria-hidden="true"><i class="w60"></i><i class="w90"></i><i class="w40"></i></div>
      </div>
      <div v-else-if="listError" class="ccl-error" role="alert" data-testid="ccl-error">
        <p>{{ t('codeChanges.listError', 'The list could not be read; try again.') }}</p>
        <button type="button" class="ccl-btn" data-testid="ccl-retry" @click="load">{{ t('codeChanges.retry', 'Try again') }}</button>
      </div>
      <div v-else-if="!list.length" class="ccl-empty" data-testid="ccl-empty">
        <h3>{{ t('codeChanges.emptyState.title', 'No code change has been proposed yet') }}</h3>
        <p>{{ t('codeChanges.emptyState.lead', 'The first one sets the pattern. A good proposal is small, names its files and says what is wrong:') }}</p>
        <div class="ccl-example" data-testid="ccl-example">
          <b>{{ t('codeChanges.emptyState.exTitle', 'Show who is paid on the order page') }}</b>
          <code>views/GuildBoard.vue</code>
          <span>{{ t('codeChanges.emptyState.exProblem', 'The order page does not say which agent is paid when a firm bids. Show the payee beside the price.') }}</span>
        </div>
        <RouterLink v-if="!authorityView_.readOnly" :to="{ name: 'code-changes-new' }" class="ccl-btn primary">{{ t('codeChanges.emptyState.cta', 'Propose the first change') }}</RouterLink>
      </div>
      <p v-else-if="!shown.length" class="ccl-note" data-testid="ccl-none-here">{{ t('codeChanges.filters.none', 'No change in this group.') }}</p>
      <ul v-else class="ccl-grid" data-testid="ccl-list">
        <li v-for="c in shown" :key="c.id" class="ccl-card ccl-item" :data-testid="`ccl-card-${c.id}`">
          <header class="ccl-item-h">
            <RouterLink :to="{ name: 'code-change', params: { id: c.id } }" class="ccl-item-title" data-testid="ccl-title">{{ c.title }}</RouterLink>
            <span class="ccl-chips">
              <span class="ccl-chip" :data-state="c.state" data-testid="ccl-state">{{ stateWord(String(c.state), tr) }}</span>
              <span v-if="c.sensitive" class="ccl-chip warn" data-testid="ccl-sensitive">{{ t('codeChanges.sensitive', 'Sensitive path') }}</span>
            </span>
          </header>
          <p class="ccl-where" data-testid="ccl-where"><span class="ccl-where-k">{{ t('codeChanges.where', 'Now') }}</span> {{ stand(c) }}</p>
          <p class="ccl-paths" data-testid="ccl-paths">
            <code v-for="p in summary(c).shown" :key="p" :class="{ sens: isSensitive(p) }" :title="p">{{ shortPath(p) }}</code>
            <span v-if="summary(c).more" class="ccl-more">{{ tp('codeChanges.morePaths', '+{n} more', { n: summary(c).more }) }}</span>
          </p>
          <div v-if="ballots[c.proposal_id]" class="ccl-tally" :data-testid="`ccl-tally-${c.id}`" :title="tallyTitle(ballots[c.proposal_id])">
            <span class="ccl-tally-bar" aria-hidden="true"><i :style="{ width: (ballots[c.proposal_id].forShare ?? 0) + '%' }"></i></span>
            <span class="ccl-tally-t">{{ tallyWords(ballots[c.proposal_id]) }}</span>
          </div>
          <dl class="ccl-meta">
            <div v-if="c.mode === 'bounty'"><dt>{{ t('codeChanges.bounty', 'Bounty') }}</dt>
              <dd><RouterLink v-if="c.order_id" :to="{ path: '/guild', query: { order: String(c.order_id) } }" class="ccl-link" data-testid="ccl-order">{{ t('codeChanges.guildOrder', 'Guild order') }}</RouterLink><template v-if="c.order_status"> · {{ c.order_status }}</template></dd></div>
            <div v-else><dt>{{ t('codeChanges.branchFact', 'Branch') }}</dt><dd><code>{{ c.branch }}</code></dd></div>
            <div><dt>{{ t('codeChanges.author', 'Proposed by') }}</dt><dd><PersonName :label="author(c)" :gone="proposerOf(c).gone" testid="ccl-author" /></dd></div>
            <div><dt>{{ t('codeChanges.when', 'Proposed') }}</dt><dd><time :datetime="c.created_at">{{ day(c.created_at) }}</time></dd></div>
          </dl>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Icon from '@/components/Icon.vue'
import ChangeStepper from '@/components/codeChanges/ChangeStepper.vue'
import CodeChangesTabs from '@/components/codeChanges/CodeChangesTabs.vue'
import GovernedElsewhere from '@/components/codeChanges/GovernedElsewhere.vue'
import { authorityView, useCodeAuthority } from '@/services/codeChanges/authority'
import { useI18n } from '@/composables/useI18n'
import { getBallot, listChanges, type ChangeRecord } from '@/services/api/codeChanges'
import { stateWord } from '@/services/codeChanges/codeChangeView'
import { FILTERS, ballotTally, explainer, matchesFilter, pathSummary, sensitiveNeeds, shortPath, whereItStands, type Tally } from '@/services/codeChanges/flow'
import { isSensitive } from '@/services/codeChanges/pathRules'
import { labelOf, proposerOf, sameNames } from '@/services/codeChanges/people'
import PersonName from '@/components/codeChanges/PersonName.vue'
import RepoAccountLink from '@/components/codeChanges/RepoAccountLink.vue'
import CodePassportPress from '@/components/codeChanges/CodePassportPress.vue'
import { getRepoAccount, type RepoAccountStatus } from '@/services/api/repoAccount'
import { useAuthStore } from '@/stores/auth'
import { useTr } from '@/services/codeChanges/tr'

const LICENCE_URL = 'https://github.com/SecureAgentTools/TheProtocol/blob/main/LICENSING.md'
const { t, tp } = useI18n()
const { authority } = useCodeAuthority()      // V0666: one governing registry: the sentence and no Submit anywhere else
const authorityView_ = computed(() => authorityView(authority.value))
const tr = useTr()
const route = useRoute()
const router = useRouter()

const list = ref<ChangeRecord[]>([])
const loading = ref(true)
const listError = ref(false)
const filter = ref('all')
const ballots = reactive<Record<string, Tally>>({})
const explain = computed(() => explainer(tr))
// the explanation is open on a wide screen and folded on a phone (it is three screens tall there); a press on "How a change goes" opens it
const wide = typeof window === 'undefined' || typeof window.matchMedia !== 'function' ? true : window.matchMedia('(min-width: 900px)').matches

const shown = computed(() => list.value.filter((c) => matchesFilter(c, filter.value)))
// the people of the cards on screen: a tail only where two of them share a name
const shared = computed(() => sameNames(shown.value.map(proposerOf), tr))
const author = (c: ChangeRecord) => labelOf(proposerOf(c), shared.value, tr)
const count = (k: string) => list.value.filter((c) => matchesFilter(c, k)).length
const filterLabel = (k: string) => ({ all: t('codeChanges.filters.all', 'All'), open: t('codeChanges.filters.open', 'Being decided'), merged: t('codeChanges.filters.merged', 'Merged'), ended: t('codeChanges.filters.ended', 'Ended') } as Record<string, string>)[k] || k
const stand = (c: ChangeRecord): string => { const s = whereItStands(c, tr); return s ? [s.title, s.note].filter(Boolean).join(' · ') : '' }
const summary = (c: ChangeRecord) => pathSummary(c.paths || [], 2)
const day = (iso: string): string => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? String(iso || '') : d.toISOString().slice(0, 10) }
const tallyWords = (b: Tally): string => (b.forShare === null ? t('codeChanges.tally.none', 'No votes yet') : tp('codeChanges.tally.words', '{f} for, {a} against', { f: b.forVotes, a: b.against }))
const tallyTitle = (b: Tally): string => tp('codeChanges.tally.title', 'Quorum {q}%, {p}% in favour to pass', { q: b.quorumPct ?? '?', p: b.passPct ?? '?' })
const scrollTo = (id: string) => { const el = document.getElementById(id) as HTMLDetailsElement | null; if (el) { el.open = true; el.scrollIntoView({ behavior: 'smooth', block: 'start' }) } }

async function load() {
  loading.value = true
  listError.value = false
  try {
    list.value = await listChanges()
    // the ballot's numbers for the changes that have one (the first twenty: a card with no numbers is still a card)
    await Promise.all(list.value.filter((c) => c.proposal_id).slice(0, 20).map(async (c) => {
      const p = await getBallot(Number(c.proposal_id))
      if (p) ballots[c.proposal_id] = ballotTally(p)
    }))
  } catch {
    listError.value = true
  } finally {
    loading.value = false
  }
}

// V0667: the "Link repository account" button (room seq 5040: never automatic). The list is public; only a signed-in developer is asked, and a status that
// could not be read shows no button rather than a wrong one.
const auth = useAuthStore() as any
const repo = ref<RepoAccountStatus | null>(null)
async function loadRepo() {
  if (!auth.isAuthenticated) return
  try { repo.value = await getRepoAccount() } catch { repo.value = null }
}

onMounted(() => {
  // a link of V0663 (?id=) opens the change's own page
  const id = route.query.id
  if (typeof id === 'string' && id) { void router.replace({ name: 'code-change', params: { id } }); return }
  void load()
  void loadRepo()
})
</script>

<style scoped>
.ccl { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); --muted: #8b97a6; --bright: #e8eaed; --mono: 'IBM Plex Mono', monospace;
  max-width: 72rem; margin: 0 auto; padding: 1.2rem 1.2rem 3rem; color: var(--bright); display: grid; gap: 1.3rem; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.ccl > * { min-width: 0; }
.ccl-hero { display: grid; gap: .6rem; justify-items: start; }
.ccl-eyebrow { font: 700 10px/1 var(--mono); letter-spacing: .1em; text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), .08); border: 1px solid rgba(var(--cyan-rgb), .25); border-radius: 12px; padding: 6px 10px; }
.ccl-hero h1 { margin: 0; font-size: 1.9rem; font-weight: 300; letter-spacing: -.01em; }
.ccl-lede { margin: 0; color: var(--muted); font-size: .92rem; max-width: 50rem; line-height: 1.6; }
.ccl-cta { display: flex; flex-wrap: wrap; gap: .6rem; margin-top: .3rem; }
.ccl-btn { display: inline-flex; align-items: center; min-height: 40px; padding: 0 18px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .35); background: rgba(var(--cyan-rgb), .12); color: var(--cyan); font: inherit; font-size: .85rem; text-decoration: none; cursor: pointer; }
.ccl-btn.primary { background: var(--cyan); color: #04141a; font-weight: 600; border-color: transparent; }
.ccl-btn:hover, .ccl-btn:focus-visible { filter: brightness(1.12); }
.ccl-card { background: linear-gradient(168deg, rgba(255,255,255,.025), rgba(255,255,255,0) 60%), rgba(var(--cyan-rgb), .035); border: 1px solid rgba(var(--cyan-rgb), .16); border-radius: 12px; padding: 1.1rem 1.25rem; min-width: 0; }
.ccl-way { display: grid; gap: 1rem; }
.ccl-way:not([open]) { gap: 0; }
.ccl-way h2, .ccl-bar h2 { margin: 0; font-size: 1.05rem; font-weight: 500; }
.ccl-way-sum { display: flex; align-items: baseline; justify-content: space-between; gap: .8rem; cursor: pointer; list-style: none; min-height: 32px; }
.ccl-way-sum::-webkit-details-marker { display: none; }
.ccl-way-sum::after { content: '+'; font: 600 1rem var(--mono); color: var(--cyan); }
.ccl-way[open] > .ccl-way-sum::after { content: '−'; }
.ccl-way-hint { margin-right: auto; font: 600 .7rem var(--mono); color: var(--muted); letter-spacing: .06em; text-transform: uppercase; }
.ccl-way-sum:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), .6); outline-offset: 4px; border-radius: 6px; }
.ccl-rules { display: grid; gap: .5rem; border-top: 1px solid rgba(255,255,255,.07); padding-top: .9rem; }
.ccl-rules p { margin: 0; display: flex; gap: .5rem; align-items: flex-start; font-size: .82rem; line-height: 1.5; color: #aab4c0; }
.ccl-rules :deep(svg) { flex: none; width: 1rem; height: 1rem; margin-top: 2px; color: var(--cyan); }
.ccl-rules a, .ccl-link { color: var(--cyan); }
.ccl-listing { display: grid; gap: .9rem; }
.ccl-bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .8rem; }
.ccl-filters { display: flex; flex-wrap: wrap; gap: .4rem; }
.ccl-filter { min-height: 34px; padding: 0 12px; border-radius: 999px; border: 1px solid rgba(var(--cyan-rgb), .22); background: none; color: var(--muted); font: inherit; font-size: .78rem; cursor: pointer; display: inline-flex; align-items: center; gap: .45rem; }
.ccl-filter.on { color: #04141a; background: var(--cyan); border-color: transparent; font-weight: 600; }
.ccl-count { font: 600 .68rem var(--mono); opacity: .8; }
.ccl-grid { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(22rem, 1fr)); gap: .9rem; }
.ccl-item { display: grid; gap: .7rem; align-content: start; transition: border-color .15s; }
.ccl-item:hover, .ccl-item:focus-within { border-color: rgba(var(--cyan-rgb), .5); }
.ccl-item-h { display: grid; gap: .5rem; }
.ccl-item-title { font-size: 1rem; font-weight: 500; color: var(--bright); text-decoration: none; line-height: 1.35; overflow-wrap: anywhere; }
.ccl-item-title:hover, .ccl-item-title:focus-visible { color: var(--cyan); }
.ccl-chips { display: flex; flex-wrap: wrap; gap: .35rem; }
.ccl-chip { font: 700 10px/1 var(--mono); letter-spacing: .06em; text-transform: uppercase; border-radius: 999px; padding: 5px 9px; border: 1px solid rgba(var(--cyan-rgb), .3); color: var(--cyan); }
.ccl-chip[data-state='merged'], .ccl-chip[data-state='passed'] { color: #34d399; border-color: rgba(16, 185, 129, .4); }
.ccl-chip[data-state='failed'], .ccl-chip[data-state='vetoed'] { color: #fca5a5; border-color: rgba(248, 113, 113, .4); }
.ccl-chip[data-state='withdrawn'] { color: var(--muted); border-color: rgba(255,255,255,.2); }
.ccl-chip[data-state='balloting'] { color: #fcd34d; border-color: rgba(245, 158, 11, .4); }
.ccl-chip.warn { color: #fcd34d; border-color: rgba(245, 158, 11, .4); }
.ccl-where { margin: 0; font-size: .8rem; line-height: 1.5; color: #aab4c0; overflow-wrap: anywhere; }
.ccl-where-k { font: 700 10px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; color: var(--muted); margin-right: .4rem; }
.ccl-paths { margin: 0; display: flex; flex-wrap: wrap; gap: .35rem; align-items: center; }
.ccl-paths code, .ccl-meta code { font: .72rem var(--mono); background: rgba(0,0,0,.3); border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 5px; padding: 2px 7px; overflow-wrap: anywhere; }
.ccl-paths code.sens { border-color: rgba(245, 158, 11, .5); color: #fcd34d; }
.ccl-more { font-size: .72rem; color: var(--muted); }
.ccl-tally { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: .6rem; align-items: center; font-size: .76rem; color: var(--muted); }
.ccl-tally-t { white-space: nowrap; font-variant-numeric: tabular-nums; }
.ccl-tally-bar { height: 6px; border-radius: 3px; background: rgba(255,255,255,.08); overflow: hidden; }
.ccl-tally-bar i { display: block; height: 100%; background: var(--cyan); }
.ccl-meta { margin: 0; display: flex; flex-wrap: wrap; gap: .4rem 1.2rem; font-size: .76rem; color: var(--muted); border-top: 1px solid rgba(255,255,255,.06); padding-top: .6rem; }
.ccl-meta div { display: flex; gap: .4rem; align-items: baseline; }
.ccl-meta dt { font: 700 10px/1 var(--mono); letter-spacing: .08em; text-transform: uppercase; }
.ccl-meta dd { margin: 0; }
.ccl-note { margin: 0; font-size: .85rem; color: var(--muted); }
.ccl-error { border: 1px solid rgba(248, 113, 113, .35); border-radius: 12px; padding: 1rem 1.2rem; display: flex; flex-wrap: wrap; align-items: center; gap: .8rem; color: #fca5a5; }
.ccl-error p { margin: 0; }
.ccl-empty { border: 1px dashed rgba(var(--cyan-rgb), .3); border-radius: 12px; padding: 1.6rem 1.4rem; display: grid; gap: .8rem; justify-items: start; }
.ccl-empty h3 { margin: 0; font-size: 1.15rem; font-weight: 400; }
.ccl-empty p { margin: 0; color: var(--muted); font-size: .88rem; max-width: 40rem; line-height: 1.55; }
.ccl-example { display: grid; gap: .35rem; max-width: 40rem; padding: .9rem 1rem; border-left: 2px solid var(--cyan); background: rgba(var(--cyan-rgb), .05); border-radius: 0 8px 8px 0; font-size: .84rem; }
.ccl-example code { font: .74rem var(--mono); color: var(--cyan); }
.ccl-example span { color: #aab4c0; line-height: 1.5; }
.ccl-skel { display: grid; grid-template-columns: repeat(auto-fill, minmax(22rem, 1fr)); gap: .9rem; }
.ccl-skel-card { border: 1px solid rgba(var(--cyan-rgb), .12); border-radius: 12px; padding: 1.1rem 1.25rem; display: grid; gap: .7rem; min-height: 8rem; }
.ccl-skel-card i { display: block; height: .7rem; border-radius: 4px; background: linear-gradient(90deg, rgba(255,255,255,.04), rgba(255,255,255,.09), rgba(255,255,255,.04)); background-size: 200% 100%; animation: ccl-shimmer 1.4s linear infinite; }
.ccl-skel-card .w60 { width: 60%; height: 1rem; } .ccl-skel-card .w90 { width: 90%; } .ccl-skel-card .w40 { width: 40%; }
.ccl-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@keyframes ccl-shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .ccl-skel-card i { animation: none; } }
@media (max-width: 640px) { .ccl { padding: 1rem .8rem 2.5rem; } .ccl-hero h1 { font-size: 1.5rem; } .ccl-grid, .ccl-skel { grid-template-columns: 1fr; } .ccl-card { padding: .95rem; } }
</style>
