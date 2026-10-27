<template>
<div class="gd" :data-mode="cfgRead ? mode : 'unread'" data-testid="governance-docs">
  <!-- §LANDINGTRUTH (21), his words 2026-10-03: "i think /governance-docs needs a complete makeover ... the layout is old
       and janky ... i think there is more wrong information". Every statement here was checked against the code (fact
       sheet, session scratchpad governance_facts.md); what differs per registry is read live from the registry's public
       settings and its membership statistics, never written as a fixed claim. -->
  <header class="gd-top">
    <div class="gd-top-in">
      <router-link to="/" class="gd-brand">
        <span class="gd-brand-dot" aria-hidden="true"></span>TheProtocol
      </router-link>
      <nav class="gd-docnav" :aria-label="t('governanceDocsView.nav.label')">
        <router-link v-for="l in docLinks" :key="l.to" :to="l.to" :class="{ on: l.to === '/governance-docs' }"
                     :aria-current="l.to === '/governance-docs' ? 'page' : undefined">{{ l.label }}</router-link>
      </nav>
      <details class="gd-docmenu">
        <summary>{{ t('governanceDocsView.nav.menu') }}</summary>
        <div class="gd-docmenu-list">
          <router-link v-for="l in docLinks" :key="l.to" :to="l.to"
                       :aria-current="l.to === '/governance-docs' ? 'page' : undefined">{{ l.label }}</router-link>
        </div>
      </details>
    </div>
  </header>

  <!-- one landmark for the page's content (the hero with its h1, and the body): the app's skip link targets #main-content -->
  <main id="main-content" class="gd-content" tabindex="-1">
  <!-- ═══ HERO + THIS REGISTRY ═══ -->
  <section class="gd-hero">
    <div class="gd-hero-text">
      <div class="gd-eyebrow"><span class="gd-eyebrow-dot" aria-hidden="true"></span>{{ t('governanceDocsView.eyebrow') }}</div>
      <h1 class="gd-h1">{{ t('governanceDocsView.h1') }}</h1>
      <p class="gd-lead">{{ t('governanceDocsView.lead') }}</p>
      <div class="gd-jumps">
        <button v-for="j in heroJumps" :key="j.id" type="button" class="gd-jump" @click="go(j.id)">{{ j.label }} <span aria-hidden="true">↓</span></button>
      </div>
    </div>

    <aside class="gd-live" aria-labelledby="gd-live-title" data-testid="gd-live">
      <div class="gd-live-head">
        <h2 id="gd-live-title" class="gd-live-title">{{ t('governanceDocsView.live.title') }}</h2>
        <span v-if="cfgRead" class="gd-live-name">{{ config.registry_name }}</span>
      </div>
      <div v-if="!loaded" class="gd-live-loading">{{ t('governanceDocsView.live.loading') }}</div>
      <dl v-else-if="cfgRead" class="gd-live-rows">
        <div v-for="row in liveRows" :key="row.key" class="gd-live-row" :data-row="row.key">
          <dt>{{ row.label }}</dt>
          <dd><span class="gd-live-val" :class="'is-' + row.tone">{{ row.value }}</span><span class="gd-live-sub">{{ row.sub }}</span></dd>
        </div>
      </dl>
      <p v-else class="gd-live-unread">{{ t('governanceDocsView.live.unread') }}
        <button v-if="readFailed" type="button" class="gd-live-retry" data-testid="gd-live-retry" @click="reload()">{{ t('common.readFailed.retry', 'Try again') }}</button>
      </p>
      <p v-if="cfgRead" class="gd-live-foot">{{ t('governanceDocsView.live.foot') }}</p>
    </aside>
  </section>

  <div class="gd-body">
    <!-- On this page: a sticky list on wide screens, a fold on phones. Buttons, not #anchors: the app routes on the hash. -->
    <nav class="gd-toc" :aria-label="t('governanceDocsView.toc.label')">
      <div class="gd-toc-title">{{ t('governanceDocsView.toc.label') }}</div>
      <button v-for="s in sections" :key="s.id" type="button" class="gd-toc-link" :class="{ on: active === s.id }"
              @click="go(s.id)">{{ s.label }}</button>
    </nav>
    <details class="gd-toc-m">
      <summary>{{ t('governanceDocsView.toc.label') }}</summary>
      <button v-for="s in sections" :key="s.id" type="button" class="gd-toc-link" @click="go(s.id)">{{ s.label }}</button>
    </details>

    <div class="gd-main">
      <!-- ═══ THE THREE LEVELS ═══ -->
      <section id="gd-levels" class="gd-sec" aria-labelledby="gd-levels-h">
        <h2 id="gd-levels-h" class="gd-h2">{{ t('governanceDocsView.levels.title') }}</h2>
        <p class="gd-intro">{{ t('governanceDocsView.levels.intro') }}</p>
        <ol class="gd-levels">
          <li class="gd-level">
            <span class="gd-level-n" aria-hidden="true">1</span>
            <h3 class="gd-h3">{{ t('governanceDocsView.levels.registry.title') }}</h3>
            <p>{{ t('governanceDocsView.levels.registry.text') }}</p>
          </li>
          <li class="gd-level">
            <span class="gd-level-n" aria-hidden="true">2</span>
            <h3 class="gd-h3">{{ t('governanceDocsView.levels.network.title') }}</h3>
            <p>{{ t('governanceDocsView.levels.network.text') }}</p>
          </li>
          <li class="gd-level">
            <span class="gd-level-n" aria-hidden="true">3</span>
            <h3 class="gd-h3">{{ t('governanceDocsView.levels.veto.title') }}</h3>
            <p>{{ t('governanceDocsView.levels.veto.text') }}</p>
          </li>
        </ol>
        <p class="gd-aside">{{ t('governanceDocsView.levels.commons') }}</p>
      </section>

      <!-- ═══ WHO VOTES ═══ -->
      <section id="gd-who" class="gd-sec" aria-labelledby="gd-who-h">
        <h2 id="gd-who-h" class="gd-h2">{{ t('governanceDocsView.who.title') }}</h2>
        <p class="gd-intro">{{ t('governanceDocsView.who.intro') }}</p>
        <div class="gd-modes">
          <article class="gd-card gd-mode" :class="{ 'is-here': cfgRead && mode === 'member' }" data-testid="gd-mode-member">
            <header class="gd-mode-head">
              <h3 class="gd-h3">{{ t('governanceDocsView.who.member.title') }}</h3>
              <span v-if="cfgRead && mode === 'member'" class="gd-here">{{ t('governanceDocsView.here') }}</span>
            </header>
            <dl class="gd-facts">
              <div><dt>{{ t('governanceDocsView.who.member.whoLabel') }}</dt>
                <dd>{{ t('governanceDocsView.who.member.whoText', { days: minBondDays }) }}</dd></div>
              <div><dt>{{ t('governanceDocsView.who.member.weightLabel') }}</dt>
                <dd>{{ t('governanceDocsView.who.member.weightText', { max: maxWeightText, days: fullDays }) }}</dd></div>
              <div><dt>{{ t('governanceDocsView.who.member.voteLabel') }}</dt>
                <dd>{{ t('governanceDocsView.who.member.voteText') }}</dd></div>
              <div><dt>{{ t('governanceDocsView.who.member.costLabel') }}</dt>
                <dd>{{ t('governanceDocsView.who.member.costText') }}</dd></div>
            </dl>
            <p class="gd-note">{{ rulesRead ? t('governanceDocsView.who.member.rulesHere') : t('governanceDocsView.who.member.rulesDefault') }}</p>
          </article>

          <article class="gd-card gd-mode" :class="{ 'is-here': cfgRead && mode === 'lock' }" data-testid="gd-mode-lock">
            <header class="gd-mode-head">
              <h3 class="gd-h3">{{ t('governanceDocsView.who.lock.title') }}</h3>
              <span v-if="cfgRead && mode === 'lock'" class="gd-here">{{ t('governanceDocsView.here') }}</span>
            </header>
            <div class="gd-formula" role="note">
              <code>{{ t('governanceDocsView.who.lock.formula') }}</code>
              <code>{{ t('governanceDocsView.who.lock.formulaFlex') }}</code>
            </div>
            <dl class="gd-facts">
              <div><dt>{{ t('governanceDocsView.who.lock.decayLabel') }}</dt>
                <dd>{{ t('governanceDocsView.who.lock.decayText') }}</dd></div>
              <div><dt>{{ t('governanceDocsView.who.lock.needLabel') }}</dt>
                <dd>{{ t('governanceDocsView.who.lock.needText') }}</dd></div>
              <div><dt>{{ t('governanceDocsView.who.lock.bonusLabel') }}</dt>
                <dd>{{ t('governanceDocsView.who.lock.bonusText') }}</dd></div>
            </dl>
            <p v-if="cfgRead && !stakingOn" class="gd-note">{{ t('governanceDocsView.who.lock.noNewLocks') }}</p>
          </article>
        </div>
        <p class="gd-aside">{{ t('governanceDocsView.who.governor') }}</p>
      </section>

      <!-- ═══ A PROPOSAL ON A REGISTRY ═══ -->
      <section id="gd-local" class="gd-sec" aria-labelledby="gd-local-h">
        <h2 id="gd-local-h" class="gd-h2">{{ t('governanceDocsView.local.title') }}</h2>
        <p class="gd-intro">{{ t('governanceDocsView.local.intro') }}</p>
        <ol class="gd-steps">
          <li v-for="(s, i) in localSteps" :key="s.title" class="gd-step">
            <span class="gd-step-n" aria-hidden="true">{{ i + 1 }}</span>
            <div class="gd-step-body">
              <h3 class="gd-h3">{{ s.title }}</h3>
              <p>{{ s.text }}</p>
            </div>
          </li>
        </ol>

        <div class="gd-card gd-table-card">
          <h3 id="gd-table-h" class="gd-h3">{{ t('governanceDocsView.local.tableTitle') }}</h3>
          <!-- scrolls sideways at phone width: focusable so a keyboard can scroll it (axe scrollable-region-focusable) -->
          <div class="gd-table-wrap" tabindex="0" role="region" aria-labelledby="gd-table-h">
            <table class="gd-table">
              <thead>
                <tr>
                  <th scope="col">{{ t('governanceDocsView.local.colKind') }}</th>
                  <th scope="col">{{ t('governanceDocsView.local.colQuorum') }}</th>
                  <th scope="col">{{ t('governanceDocsView.local.colPass') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <th scope="row">{{ t('governanceDocsView.local.kindStandard') }}</th>
                  <td>{{ t('governanceDocsView.local.standardQuorum') }}</td>
                  <td>{{ t('governanceDocsView.local.standardPass') }}</td>
                </tr>
                <tr>
                  <th scope="row">{{ t('governanceDocsView.local.kindPolicy') }}</th>
                  <td>{{ t('governanceDocsView.local.policyQuorum') }}</td>
                  <td>{{ t('governanceDocsView.local.policyPass') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="gd-note">{{ t('governanceDocsView.local.tableNote') }}</p>
        </div>

        <div class="gd-card gd-limits">
          <h3 class="gd-h3">{{ t('governanceDocsView.local.limitsTitle') }}</h3>
          <ul class="gd-list">
            <li>{{ t('governanceDocsView.local.limitSwitches') }}</li>
            <li>{{ t('governanceDocsView.local.limitLocked') }}</li>
            <li>{{ t('governanceDocsView.local.limitOverride') }}</li>
          </ul>
        </div>
      </section>

      <!-- ═══ ACROSS THE NETWORK ═══ -->
      <section id="gd-network" class="gd-sec" aria-labelledby="gd-network-h">
        <h2 id="gd-network-h" class="gd-h2">{{ t('governanceDocsView.network.title') }}</h2>
        <p class="gd-intro">{{ t('governanceDocsView.network.intro') }}</p>
        <div class="gd-modes">
          <article class="gd-card gd-mode" :class="{ 'is-here': cfgRead && ballots }" data-testid="gd-ballots">
            <header class="gd-mode-head">
              <h3 class="gd-h3">{{ t('governanceDocsView.network.ballots.title') }}</h3>
              <span v-if="cfgRead && ballots" class="gd-here">{{ t('governanceDocsView.here') }}</span>
            </header>
            <ul class="gd-list">
              <li>{{ t('governanceDocsView.network.ballots.one') }}</li>
              <li>{{ t('governanceDocsView.network.ballots.who') }}</li>
              <li>{{ t('governanceDocsView.network.ballots.eligible') }}</li>
              <li>{{ t('governanceDocsView.network.ballots.pass') }}</li>
            </ul>
          </article>
          <article class="gd-card gd-mode" :class="{ 'is-here': cfgRead && !ballots && mode === 'lock' }" data-testid="gd-weighted">
            <header class="gd-mode-head">
              <h3 class="gd-h3">{{ t('governanceDocsView.network.weighted.title') }}</h3>
              <span v-if="cfgRead && !ballots && mode === 'lock'" class="gd-here">{{ t('governanceDocsView.here') }}</span>
            </header>
            <ul class="gd-list">
              <li>{{ t('governanceDocsView.network.weighted.who') }}</li>
              <li>{{ t('governanceDocsView.network.weighted.pass') }}</li>
              <li>{{ t('governanceDocsView.network.weighted.trust') }}</li>
            </ul>
          </article>
        </div>
        <p class="gd-aside">{{ t('governanceDocsView.network.fixed') }}</p>
      </section>

      <!-- ═══ THE VETO WINDOW, AND ITS SUCCESSOR ═══ -->
      <section id="gd-veto" class="gd-sec" aria-labelledby="gd-veto-h">
        <h2 id="gd-veto-h" class="gd-h2">{{ t('governanceDocsView.veto.title') }}</h2>
        <p class="gd-intro">{{ t('governanceDocsView.veto.intro') }}</p>
        <div class="gd-card">
          <dl class="gd-facts">
            <div><dt>{{ t('governanceDocsView.veto.windowLabel') }}</dt><dd>{{ t('governanceDocsView.veto.windowText') }}</dd></div>
            <div><dt>{{ t('governanceDocsView.veto.whoLabel') }}</dt><dd>{{ t('governanceDocsView.veto.whoText') }}</dd></div>
            <div><dt>{{ t('governanceDocsView.veto.limitLabel') }}</dt><dd>{{ t('governanceDocsView.veto.limitText') }}</dd></div>
            <div><dt>{{ t('governanceDocsView.veto.applyLabel') }}</dt><dd>{{ t('governanceDocsView.veto.applyText') }}</dd></div>
          </dl>
        </div>
        <ol class="gd-path" :aria-label="t('governanceDocsView.veto.pathLabel')">
          <li class="gd-path-step is-now">
            <span class="gd-path-tag">{{ t('governanceDocsView.veto.nowTag') }}</span>
            <h3 class="gd-h3">{{ t('governanceDocsView.veto.nowTitle') }}</h3>
            <p>{{ t('governanceDocsView.veto.nowText') }}</p>
          </li>
          <li class="gd-path-step is-planned">
            <span class="gd-path-tag">{{ t('governanceDocsView.veto.plannedTag') }}</span>
            <h3 class="gd-h3">{{ t('governanceDocsView.veto.plannedTitle') }}</h3>
            <p>{{ t('governanceDocsView.veto.plannedText') }}</p>
          </li>
        </ol>
      </section>

      <!-- ═══ THE COMMONS ═══ -->
      <section id="gd-commons" class="gd-sec" aria-labelledby="gd-commons-h">
        <h2 id="gd-commons-h" class="gd-h2">
          {{ t('governanceDocsView.commons.title') }}
          <span v-if="cfgRead" class="gd-here" :class="{ 'is-off': !commons }">{{ commons ? t('governanceDocsView.commons.onHere') : t('governanceDocsView.commons.offHere') }}</span>
        </h2>
        <p class="gd-intro">{{ t('governanceDocsView.commons.intro') }}</p>
        <ol class="gd-steps">
          <li v-for="(s, i) in commonsSteps" :key="s.title" class="gd-step">
            <span class="gd-step-n" aria-hidden="true">{{ i + 1 }}</span>
            <div class="gd-step-body">
              <h3 class="gd-h3">{{ s.title }}</h3>
              <p>{{ s.text }}</p>
            </div>
          </li>
        </ol>
      </section>

      <!-- ═══ GUARD RAILS ═══ -->
      <section id="gd-rails" class="gd-sec" aria-labelledby="gd-rails-h">
        <h2 id="gd-rails-h" class="gd-h2">{{ t('governanceDocsView.rails.title') }}</h2>
        <ul class="gd-rails">
          <li v-for="r in rails" :key="r">{{ r }}</li>
        </ul>
      </section>

      <!-- ═══ REFERENCE ═══ -->
      <section id="gd-ref" class="gd-sec" aria-labelledby="gd-ref-h">
        <h2 id="gd-ref-h" class="gd-h2">{{ t('governanceDocsView.ref.title') }}</h2>
        <p class="gd-intro">{{ t('governanceDocsView.ref.intro') }}</p>
        <div v-for="g in refGroups" :key="g.title" class="gd-card gd-ref">
          <h3 class="gd-h3">{{ g.title }}</h3>
          <ul class="gd-ref-list">
            <li v-for="e in g.items" :key="e.path + e.method">
              <code class="gd-ref-call"><span class="gd-ref-method" :data-m="e.method">{{ e.method }}</span>{{ e.path }}</code>
              <span class="gd-ref-what">{{ e.what }}</span>
            </li>
          </ul>
        </div>
      </section>
    </div>
  </div>
  </main>

  <footer class="gd-foot">
    <div class="gd-foot-in">
      <span>TheProtocol · {{ t('governanceDocsView.foot.tagline') }}</span>
      <nav class="gd-foot-links" :aria-label="t('governanceDocsView.foot.label')">
        <router-link to="/">{{ t('governanceDocsView.nav.home') }}</router-link>
        <router-link v-for="l in docLinks" :key="'f' + l.to" :to="l.to">{{ l.label }}</router-link>
        <router-link to="/a2a-protocol">{{ t('governanceDocsView.nav.a2a') }}</router-link>
        <router-link to="/operator">{{ t('governanceDocsView.nav.operator') }}</router-link>
        <router-link to="/compliance">{{ t('governanceDocsView.nav.compliance') }}</router-link>
      </nav>
    </div>
  </footer>
</div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { appLocale } from '@/services/appLocale'
import { commonsEnabled, governanceMode, presenceMode, weightLabel } from '@/services/membership/membership'
import type { MembershipStats } from '@/services/membership/membership'

const { t } = useI18n()

// What differs per registry is READ, never written down: the public settings (one shared read) and the membership
// statistics. A settings read that failed resolves to {} in the composable; registry_name is what tells a real answer
// from that empty one, so a failed read says so instead of describing the lock mode as this registry's.
const { config, loaded, readOk, readFailed, reload } = useRegistryConfig()
const cfgRead = computed(() => loaded.value && !!config.value.registry_name)
const mode = computed(() => governanceMode(config.value))
const presence = computed(() => presenceMode(config.value))
const ballots = computed(() => config.value.federation_ballot_mode === true)
const commons = computed(() => commonsEnabled(config.value))
const stakingOn = computed(() => config.value.staking_enabled !== false)

const stats = ref<MembershipStats | null>(null)
async function loadStats() {
  try {
    const r = await fetch(`${window.location.origin}/api/v1/membership/stats`, { cache: 'no-store' })
    if (r.ok) stats.value = (await r.json()) as MembershipStats
  } catch { /* the membership card then shows the software defaults and says they are defaults */ }
}
const rulesRead = computed(() => !!stats.value)
const minBondDays = computed(() => stats.value?.min_bond_age_days ?? 30)
const fullDays = computed(() => stats.value?.tenure_full_days ?? 365)
const maxWeightText = computed(() => weightLabel(stats.value?.max_weight ?? 2, appLocale()).replace(/0$/, ''))

const liveRows = computed(() => {
  const rows: Array<{ key: string; label: string; value: string; sub: string; tone: string }> = []
  rows.push(mode.value === 'member'
    ? { key: 'mode', label: t('governanceDocsView.live.modeLabel'), value: t('governanceDocsView.live.modeMember'),
        sub: t('governanceDocsView.live.modeMemberSub'), tone: 'on' }
    : { key: 'mode', label: t('governanceDocsView.live.modeLabel'), value: t('governanceDocsView.live.modeLock'),
        sub: t('governanceDocsView.live.modeLockSub'), tone: 'on' })
  if (mode.value === 'member' && stats.value) {
    rows.push({ key: 'members', label: t('governanceDocsView.live.membersLabel'),
                value: new Intl.NumberFormat(appLocale()).format(stats.value.members ?? 0),
                sub: t('governanceDocsView.live.membersSub', { days: minBondDays.value }), tone: 'num' })
  }
  rows.push({ key: 'presence', label: t('governanceDocsView.live.presenceLabel'),
              value: presence.value === 'required' ? t('governanceDocsView.live.presenceRequired')
                : presence.value === 'conditional' ? t('governanceDocsView.live.presenceConditional')
                  : t('governanceDocsView.live.presenceOff'),
              sub: presence.value === 'required' ? t('governanceDocsView.live.presenceSubRequired')
                : presence.value === 'conditional' ? t('governanceDocsView.live.presenceSubConditional') : '',
              tone: presence.value === 'off' ? 'off' : 'on' })
  rows.push({ key: 'ballots', label: t('governanceDocsView.live.ballotsLabel'),
              value: ballots.value ? t('governanceDocsView.live.ballotsOn') : t('governanceDocsView.live.ballotsOff'),
              sub: ballots.value ? t('governanceDocsView.live.ballotsOnSub') : '', tone: ballots.value ? 'on' : 'off' })
  rows.push({ key: 'commons', label: t('governanceDocsView.live.commonsLabel'),
              value: commons.value ? t('governanceDocsView.live.commonsOn') : t('governanceDocsView.live.commonsOff'),
              sub: '', tone: commons.value ? 'on' : 'off' })
  rows.push({ key: 'locks', label: t('governanceDocsView.live.locksLabel'),
              value: stakingOn.value ? t('governanceDocsView.live.locksOn') : t('governanceDocsView.live.locksOff'),
              sub: stakingOn.value ? '' : t('governanceDocsView.live.locksOffSub'), tone: stakingOn.value ? 'on' : 'off' })
  return rows
})

const docLinks = computed(() => [
  { to: '/getting-started', label: t('governanceDocsView.nav.start') },
  { to: '/units-and-fees', label: t('governanceDocsView.nav.units') },
  { to: '/governance-docs', label: t('governanceDocsView.nav.governance') },
  { to: '/federation-docs', label: t('governanceDocsView.nav.federation') },
  { to: '/trust-reputation', label: t('governanceDocsView.nav.trust') },
  { to: '/architecture', label: t('governanceDocsView.nav.architecture') },
  { to: '/docs', label: t('governanceDocsView.nav.docs') },
])

const sections = computed(() => [
  { id: 'gd-levels', label: t('governanceDocsView.toc.levels') },
  { id: 'gd-who', label: t('governanceDocsView.toc.who') },
  { id: 'gd-local', label: t('governanceDocsView.toc.local') },
  { id: 'gd-network', label: t('governanceDocsView.toc.network') },
  { id: 'gd-veto', label: t('governanceDocsView.toc.veto') },
  { id: 'gd-commons', label: t('governanceDocsView.toc.commons') },
  { id: 'gd-rails', label: t('governanceDocsView.toc.rails') },
  { id: 'gd-ref', label: t('governanceDocsView.toc.ref') },
])

const heroJumps = computed(() => [
  { id: 'gd-who', label: t('governanceDocsView.toc.who') },
  { id: 'gd-network', label: t('governanceDocsView.toc.network') },
  { id: 'gd-veto', label: t('governanceDocsView.toc.veto') },
])

const localSteps = computed(() => [
  { title: t('governanceDocsView.local.s1Title'), text: t('governanceDocsView.local.s1Text') },
  { title: t('governanceDocsView.local.s2Title'), text: t('governanceDocsView.local.s2Text') },
  { title: t('governanceDocsView.local.s3Title'), text: t('governanceDocsView.local.s3Text') },
  { title: t('governanceDocsView.local.s4Title'), text: t('governanceDocsView.local.s4Text') },
])

const commonsSteps = computed(() => [
  { title: t('governanceDocsView.commons.s1Title'), text: t('governanceDocsView.commons.s1Text') },
  { title: t('governanceDocsView.commons.s2Title'), text: t('governanceDocsView.commons.s2Text') },
  { title: t('governanceDocsView.commons.s3Title'), text: t('governanceDocsView.commons.s3Text') },
  { title: t('governanceDocsView.commons.s4Title'), text: t('governanceDocsView.commons.s4Text') },
])

const rails = computed(() => [
  t('governanceDocsView.rails.r1'), t('governanceDocsView.rails.r2'), t('governanceDocsView.rails.r3'),
  t('governanceDocsView.rails.r4'), t('governanceDocsView.rails.r5'), t('governanceDocsView.rails.r6'),
  t('governanceDocsView.rails.r7'), t('governanceDocsView.rails.r8'),
])

// Paths are code and stay out of the bundles (a {id} in a message is an interpolation slot). All under /api/v1.
const refGroups = computed(() => [
  { title: t('governanceDocsView.ref.public'), items: [
    { method: 'GET', path: '/governance/proposals', what: t('governanceDocsView.ref.proposals') },
    { method: 'GET', path: '/governance/proposals/{id}/votes', what: t('governanceDocsView.ref.votes') },
    { method: 'GET', path: '/governance/stats', what: t('governanceDocsView.ref.stats') },
    { method: 'GET', path: '/membership/stats', what: t('governanceDocsView.ref.memberStats') },
    { method: 'GET', path: '/commons/seasons', what: t('governanceDocsView.ref.seasons') },
  ] },
  { title: t('governanceDocsView.ref.agent'), items: [
    { method: 'POST', path: '/governance/proposals', what: t('governanceDocsView.ref.propose') },
    { method: 'POST', path: '/governance/proposals/{id}/vote', what: t('governanceDocsView.ref.vote') },
    { method: 'POST', path: '/governance/proposals/{id}/tally', what: t('governanceDocsView.ref.tally') },
    { method: 'GET', path: '/governance/voting-power', what: t('governanceDocsView.ref.power') },
    { method: 'POST', path: '/commons/seasons/{id}/ballot', what: t('governanceDocsView.ref.commonsBallot') },
  ] },
  { title: t('governanceDocsView.ref.developer'), items: [
    { method: 'GET', path: '/membership/me', what: t('governanceDocsView.ref.me') },
    { method: 'POST', path: '/agents/{did}/authz/roles', what: t('governanceDocsView.ref.governor') },
    { method: 'GET', path: '/governance/federation-ballots', what: t('governanceDocsView.ref.openBallots') },
  ] },
  { title: t('governanceDocsView.ref.admin'), items: [
    { method: 'POST', path: '/governance/federation/propose', what: t('governanceDocsView.ref.elevate') },
    { method: 'POST', path: '/admin/federation/ballots/local-vote', what: t('governanceDocsView.ref.localVote') },
    { method: 'POST', path: '/admin/federation/ballots', what: t('governanceDocsView.ref.castBallot') },
    { method: 'POST', path: '/governance/federation/proposals/{id}/veto', what: t('governanceDocsView.ref.veto') },
    { method: 'POST', path: '/governance/federation/proposals/{id}/apply', what: t('governanceDocsView.ref.apply') },
    { method: 'PUT', path: '/admin/enforcement/policy', what: t('governanceDocsView.ref.override') },
  ] },
])

// Which section is in view, for the list on the side.
const active = ref('gd-levels')
let io: IntersectionObserver | null = null
const reduceMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
function go(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' })
  active.value = id
}
// A registry from before membership publishes no governance_weight_mode and serves no /membership/stats: ask only one
// that knows the setting (an older one gets the defaults, labelled as defaults, and no 404 in its console).
// §LANDINGTRUTH (31): keyed on the registry's ANSWER, not on `loaded`: `loaded` turns true once, on a failed first read
// too, so a read that answered after a failure never asked for the figures and the card kept the defaults
// (agentvault2-45's recovery sweep on V0572, fes-20261004T184044Z-fa6d)
watch(() => (readOk.value ? config.value.governance_weight_mode : undefined),
  (m) => { if (m && !stats.value) void loadStats() }, { immediate: true })
onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') return
  io = new IntersectionObserver((entries) => {
    for (const e of entries) if (e.isIntersecting) active.value = (e.target as HTMLElement).id
  }, { rootMargin: '-15% 0px -70% 0px' })
  for (const s of sections.value) {
    const el = document.getElementById(s.id)
    if (el) io.observe(el)
  }
})
onBeforeUnmount(() => { io?.disconnect(); io = null })
</script>

<style scoped>
.gd {
  --cyan: var(--nc-primary, #00d2d2);
  --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210);
  --bg: #070b13;
  --border: rgba(var(--cyan-rgb), 0.16);
  --border-strong: rgba(var(--cyan-rgb), 0.32);
  --text: #b4c1ca;
  --text-bright: #e8eaed;
  --muted: #7d8b97;
  --ok: #10b981;
  --off: #94a3b8;
  --mono: 'IBM Plex Mono', 'JetBrains Mono', 'Fira Code', monospace;
  position: relative;
  min-height: 100vh;
  background:
    radial-gradient(900px 420px at 85% -120px, rgba(var(--cyan-rgb), 0.10), transparent 70%),
    radial-gradient(700px 380px at -10% 30%, rgba(var(--cyan-rgb), 0.05), transparent 70%),
    var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
  line-height: 1.6;
}

/* ── top bar ── */
.gd-top { position: sticky; top: 0; z-index: 20; background: rgba(7, 11, 19, 0.86); backdrop-filter: blur(8px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.05); }
.gd-top-in { max-width: 1180px; margin: 0 auto; padding: 12px 24px; display: flex; align-items: center; gap: 24px; }
.gd-brand { display: inline-flex; align-items: center; gap: 9px; color: var(--text-bright); font-weight: 700;
  font-size: 15px; letter-spacing: -0.01em; text-decoration: none; white-space: nowrap; }
.gd-brand-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--cyan);
  box-shadow: 0 0 10px rgba(var(--cyan-rgb), 0.7); }
.gd-docnav { display: flex; gap: 4px; flex-wrap: wrap; margin-left: auto; }
.gd-docnav a { color: var(--muted); font-size: 13px; text-decoration: none; padding: 6px 10px; border-radius: 6px; }
.gd-docnav a:hover { color: var(--text-bright); background: rgba(255, 255, 255, 0.04); }
.gd-docnav a.on { color: var(--cyan); background: rgba(var(--cyan-rgb), 0.08); }
.gd-docmenu { display: none; margin-left: auto; position: relative; }
.gd-docmenu summary { list-style: none; cursor: pointer; color: var(--text-bright); font-size: 13px; padding: 6px 12px;
  border: 1px solid var(--border); border-radius: 6px; }
.gd-docmenu summary::-webkit-details-marker { display: none; }
.gd-docmenu-list { position: absolute; right: 0; top: calc(100% + 6px); min-width: 200px; display: flex; flex-direction: column;
  background: #0b111c; border: 1px solid var(--border); border-radius: 10px; padding: 6px; box-shadow: 0 16px 40px -18px #000; }
.gd-docmenu-list a { color: var(--text); text-decoration: none; padding: 8px 10px; border-radius: 6px; font-size: 14px; }
.gd-docmenu-list a[aria-current='page'] { color: var(--cyan); }

/* ── hero ── */
.gd-hero { max-width: 1180px; margin: 0 auto; padding: 72px 24px 40px; display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 430px); gap: 48px; align-items: start; }
.gd-hero-text { min-width: 0; }
.gd-eyebrow { display: inline-flex; align-items: center; gap: 8px; font: 700 10px/1 var(--mono); letter-spacing: 0.16em;
  text-transform: uppercase; color: var(--cyan); background: rgba(var(--cyan-rgb), 0.08);
  border: 1px solid rgba(var(--cyan-rgb), 0.25); border-radius: 12px; padding: 6px 12px; margin-bottom: 22px; }
.gd-eyebrow-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--cyan); }
.gd-h1 { font-size: clamp(34px, 5vw, 54px); font-weight: 800; line-height: 1.06; letter-spacing: -0.03em;
  color: #fff; margin: 0 0 20px; }
.gd-lead { font-size: 17px; color: var(--text); max-width: 600px; margin: 0; }
.gd-jumps { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 28px; }
.gd-jump { font: inherit; font-size: 13.5px; color: var(--text-bright); background: rgba(var(--cyan-rgb), 0.06);
  border: 1px solid var(--border); border-radius: 8px; padding: 8px 14px; cursor: pointer; }
.gd-jump span { color: var(--cyan); margin-left: 4px; }
.gd-jump:hover { border-color: var(--border-strong); background: rgba(var(--cyan-rgb), 0.1); }
.gd-jump:focus-visible { outline: 2px solid rgba(var(--cyan-rgb), 0.7); outline-offset: 2px; }

.gd-live { background: linear-gradient(168deg, rgba(255, 255, 255, 0.03), rgba(255, 255, 255, 0) 60%), rgba(var(--cyan-rgb), 0.04);
  border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px 14px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 18px 40px -26px rgba(0, 0, 0, 0.9); }
.gd-live-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.gd-live-title { font: 700 11px/1 var(--mono); letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted); margin: 0; }
.gd-live-name { font: 600 12px/1 var(--mono); color: var(--cyan); background: rgba(var(--cyan-rgb), 0.08);
  border: 1px solid rgba(var(--cyan-rgb), 0.22); border-radius: 10px; padding: 4px 9px; }
.gd-live-rows { margin: 0; }
.gd-live-row { display: grid; grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.45fr); gap: 12px; padding: 10px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.05); }
.gd-live-row dt { font-size: 12.5px; color: var(--muted); }
.gd-live-row dd { margin: 0; display: flex; flex-direction: column; gap: 2px; }
.gd-live-val { font-size: 14px; font-weight: 650; color: var(--text-bright); }
.gd-live-val.is-on::before { content: ''; display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: var(--ok); margin-right: 7px; vertical-align: 1px; }
.gd-live-val.is-off { color: var(--off); }
.gd-live-val.is-num { font-variant-numeric: tabular-nums; }
.gd-live-sub { font-size: 12px; color: var(--muted); line-height: 1.45; }
.gd-live-loading, .gd-live-unread { font-size: 13px; color: var(--muted); margin: 6px 0 4px; }
.gd-live-retry { margin-left: 8px; background: none; border: 1px solid var(--border-strong); border-radius: 6px; color: var(--cyan);
  font: inherit; font-size: 12px; padding: 2px 10px; cursor: pointer; }
.gd-live-retry:hover, .gd-live-retry:focus-visible { background: rgba(var(--cyan-rgb), 0.1); }
.gd-live-foot { font-size: 11.5px; color: var(--muted); margin: 8px 0 0; border-top: 1px solid rgba(255, 255, 255, 0.05);
  padding-top: 10px; }

/* ── body: side list + main column ── */
.gd-body { max-width: 1180px; margin: 0 auto; padding: 8px 24px 64px; display: grid;
  grid-template-columns: 210px minmax(0, 1fr); gap: 56px; }
.gd-toc { position: sticky; top: 76px; align-self: start; display: flex; flex-direction: column; gap: 2px; }
.gd-toc-title { font: 700 10px/1 var(--mono); letter-spacing: 0.14em; text-transform: uppercase; color: var(--muted);
  margin: 6px 0 10px 12px; }
.gd-toc-link { text-align: left; background: none; border: 0; border-left: 2px solid rgba(255, 255, 255, 0.06);
  color: var(--muted); font: inherit; font-size: 13.5px; padding: 6px 12px; cursor: pointer; border-radius: 0 6px 6px 0; }
.gd-toc-link:hover { color: var(--text-bright); background: rgba(255, 255, 255, 0.03); }
.gd-toc-link.on { color: var(--cyan); border-left-color: var(--cyan); background: rgba(var(--cyan-rgb), 0.05); }
.gd-toc-link:focus-visible, .gd-docnav a:focus-visible, .gd-docmenu summary:focus-visible, .gd-brand:focus-visible {
  outline: 2px solid rgba(var(--cyan-rgb), 0.7); outline-offset: 2px; }
.gd-toc-m { display: none; }

.gd-main { min-width: 0; max-width: 820px; }
.gd-sec { padding: 8px 0 44px; scroll-margin-top: 80px; }
.gd-sec + .gd-sec { border-top: 1px solid rgba(255, 255, 255, 0.05); padding-top: 40px; }
.gd-h2 { font-size: clamp(22px, 2.6vw, 28px); font-weight: 750; letter-spacing: -0.02em; color: #fff; margin: 0 0 10px;
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.gd-h3 { font-size: 15.5px; font-weight: 650; color: var(--text-bright); margin: 0 0 6px; }
.gd-intro { font-size: 15px; color: var(--text); margin: 0 0 22px; max-width: 700px; }
.gd-aside { font-size: 13.5px; color: var(--muted); margin: 18px 0 0; padding-left: 14px;
  border-left: 2px solid rgba(var(--cyan-rgb), 0.25); }
.gd-note { font-size: 12.5px; color: var(--muted); margin: 14px 0 0; }

.gd-card { background: linear-gradient(168deg, rgba(255, 255, 255, 0.025), rgba(255, 255, 255, 0) 60%), rgba(var(--cyan-rgb), 0.03);
  border: 1px solid var(--border); border-radius: 12px; padding: 18px 20px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03), 0 12px 32px -22px rgba(0, 0, 0, 0.8); }
.gd-card + .gd-card { margin-top: 14px; }
.gd-modes > .gd-card + .gd-card { margin-top: 0; }

/* the three levels */
.gd-levels { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px;
  counter-reset: none; }
.gd-level { position: relative; background: rgba(var(--cyan-rgb), 0.03); border: 1px solid var(--border); border-radius: 12px;
  padding: 18px 18px 16px; }
.gd-level p { margin: 0; font-size: 14px; }
.gd-level-n { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 50%;
  font: 700 12px/1 var(--mono); color: var(--cyan); background: rgba(var(--cyan-rgb), 0.1);
  border: 1px solid rgba(var(--cyan-rgb), 0.3); margin-bottom: 12px; }
.gd-level + .gd-level::before { content: ''; position: absolute; left: -15px; top: 30px; width: 14px; height: 1px;
  background: rgba(var(--cyan-rgb), 0.35); }

/* two side-by-side cards with a "this registry" mark */
.gd-modes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.gd-mode { display: flex; flex-direction: column; }
.gd-mode.is-here { border-color: var(--border-strong); box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03),
  0 0 0 1px rgba(var(--cyan-rgb), 0.12), 0 12px 32px -22px rgba(0, 0, 0, 0.8); }
.gd-mode-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.gd-mode-head .gd-h3 { margin: 0; }
.gd-here { font: 700 9.5px/1 var(--mono); letter-spacing: 0.12em; text-transform: uppercase; color: var(--ok);
  border: 1px solid rgba(16, 185, 129, 0.4); background: rgba(16, 185, 129, 0.08); border-radius: 10px; padding: 4px 8px;
  white-space: nowrap; }
.gd-here.is-off { color: var(--off); border-color: rgba(148, 163, 184, 0.35); background: rgba(148, 163, 184, 0.06); }
.gd-facts { margin: 0; display: flex; flex-direction: column; gap: 12px; }
.gd-facts dt { font: 700 10px/1.3 var(--mono); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
.gd-facts dd { margin: 3px 0 0; font-size: 14px; color: var(--text); }
.gd-formula { display: flex; flex-direction: column; gap: 6px; margin: 2px 0 14px; padding: 12px 14px; border-radius: 8px;
  background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(var(--cyan-rgb), 0.12); }
.gd-formula code { font-family: var(--mono); font-size: 12.5px; color: var(--text-bright); white-space: normal; }

/* steps */
.gd-steps { list-style: none; margin: 0 0 18px; padding: 0; display: flex; flex-direction: column; }
.gd-step { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 14px; position: relative; padding-bottom: 18px; }
.gd-step:not(:last-child)::after { content: ''; position: absolute; left: 16px; top: 34px; bottom: 2px; width: 1px;
  background: rgba(var(--cyan-rgb), 0.22); }
.gd-step-n { width: 34px; height: 34px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
  font: 700 13px/1 var(--mono); color: var(--cyan); background: rgba(var(--cyan-rgb), 0.08);
  border: 1px solid rgba(var(--cyan-rgb), 0.28); }
.gd-step-body p { margin: 0; font-size: 14px; }
.gd-step-body .gd-h3 { margin-top: 6px; }

/* thresholds table */
.gd-table-wrap { overflow-x: auto; margin: 4px -4px 0; border-radius: 6px; }
.gd-table-wrap:focus-visible { outline: 2px solid var(--cyan); outline-offset: 2px; }
.gd-content:focus { outline: none; }
.gd-table { width: 100%; border-collapse: collapse; font-size: 13.5px; }
.gd-table th, .gd-table td { text-align: left; padding: 10px 8px; border-bottom: 1px solid rgba(255, 255, 255, 0.05);
  vertical-align: top; }
.gd-table thead th { font: 700 10px/1.3 var(--mono); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
.gd-table tbody th { color: var(--text-bright); font-weight: 600; }
.gd-table tr:last-child th, .gd-table tr:last-child td { border-bottom: 0; }

.gd-list { margin: 0; padding-left: 18px; list-style: disc outside; display: flex; flex-direction: column; gap: 9px; font-size: 14px; }
.gd-list li::marker { color: rgba(var(--cyan-rgb), 0.6); }
.gd-limits { margin-top: 14px; }

/* the veto's path */
.gd-path { list-style: none; margin: 16px 0 0; padding: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.gd-path-step { position: relative; border-radius: 12px; padding: 18px 20px; border: 1px solid var(--border);
  background: rgba(var(--cyan-rgb), 0.03); }
.gd-path-step.is-planned { border-style: dashed; border-color: rgba(var(--cyan-rgb), 0.35); background: rgba(var(--cyan-rgb), 0.05); }
.gd-path-step + .gd-path-step::before { content: '→'; position: absolute; left: -14px; top: 50%; transform: translate(-50%, -50%);
  color: var(--cyan); font-size: 16px; }
.gd-path-step p { margin: 0; font-size: 14px; }
.gd-path-tag { display: inline-block; font: 700 9.5px/1 var(--mono); letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--muted); margin-bottom: 10px; }
.gd-path-step.is-planned .gd-path-tag { color: var(--cyan); }

/* guard rails */
.gd-rails { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 22px; }
.gd-rails li { position: relative; padding-left: 22px; font-size: 14px; }
.gd-rails li::before { content: ''; position: absolute; left: 2px; top: 8px; width: 9px; height: 5px;
  border-left: 2px solid var(--cyan); border-bottom: 2px solid var(--cyan); transform: rotate(-45deg); }

/* reference */
.gd-ref .gd-h3 { font: 700 10.5px/1.3 var(--mono); letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted);
  margin-bottom: 10px; }
.gd-ref-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.gd-ref-list li { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 14px; padding: 8px 0;
  border-top: 1px solid rgba(255, 255, 255, 0.04); align-items: baseline; }
.gd-ref-list li:first-child { border-top: 0; }
.gd-ref-call { font-family: var(--mono); font-size: 12.5px; color: var(--text-bright); overflow-wrap: anywhere; }
.gd-ref-method { display: inline-block; min-width: 42px; margin-right: 8px; font-weight: 700; font-size: 11px; color: var(--ok); }
.gd-ref-method[data-m='POST'] { color: var(--cyan); }
.gd-ref-method[data-m='PUT'] { color: #f59e0b; }
.gd-ref-what { font-size: 13.5px; color: var(--text); }

/* footer */
.gd-foot { border-top: 1px solid rgba(255, 255, 255, 0.05); }
.gd-foot-in { max-width: 1180px; margin: 0 auto; padding: 22px 24px 30px; display: flex; flex-wrap: wrap; gap: 14px 24px;
  align-items: center; justify-content: space-between; font-size: 12px; color: var(--muted); }
.gd-foot-links { display: flex; flex-wrap: wrap; gap: 8px 18px; }
.gd-foot-links a { color: var(--muted); text-decoration: none; }
.gd-foot-links a:hover { color: var(--text-bright); }

/* ── narrower screens ── */
@media (max-width: 1080px) {
  .gd-docnav { display: none; }
  .gd-docmenu { display: block; }
}
@media (max-width: 960px) {
  .gd-hero { grid-template-columns: minmax(0, 1fr); gap: 28px; padding-top: 48px; }
  .gd-body { grid-template-columns: minmax(0, 1fr); gap: 0; }
  .gd-toc { display: none; }
  .gd-toc-m { display: block; margin: 0 0 24px; border: 1px solid var(--border); border-radius: 10px; padding: 4px 6px; }
  .gd-toc-m summary { cursor: pointer; padding: 8px 8px; color: var(--text-bright); font-size: 14px; }
  .gd-toc-m .gd-toc-link { display: block; width: 100%; }
  .gd-levels { grid-template-columns: minmax(0, 1fr); }
  .gd-level + .gd-level::before { display: none; }
}
@media (max-width: 720px) {
  .gd-top-in, .gd-hero, .gd-body, .gd-foot-in { padding-left: 16px; padding-right: 16px; }
  .gd-modes, .gd-path, .gd-rails { grid-template-columns: minmax(0, 1fr); }
  .gd-path-step + .gd-path-step::before { content: '↓'; left: 50%; top: -14px; }
  .gd-ref-list li { grid-template-columns: minmax(0, 1fr); gap: 4px; }
  .gd-live-row { grid-template-columns: minmax(0, 1fr); gap: 4px; }
  .gd-lead { font-size: 16px; }
}
@media (prefers-reduced-motion: reduce) {
  .gd * { transition: none !important; }
}
</style>
