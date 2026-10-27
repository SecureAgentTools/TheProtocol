<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { computed, onMounted, onBeforeUnmount, watch, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import ProtocolMark from '@/components/ProtocolMark.vue'
import Icon from '@/components/Icon.vue'
import { LEGAL_SUITE_V2, type LegalPageV2 } from '@/content/legal/suiteV2'
import { LEGAL_SUITE_V2_DE } from '@/content/legal/suiteV2.de'
import { useFrames } from '@/composables/useFrames'
import { providerTokens, resolveLegalTokens, useLegalConfig } from '@/services/legal/config'

const route = useRoute()
const router = useRouter()
const { t, tp, locale: i18nLocale, availableLocales } = useI18n()
// Frame-currency awareness: the same image serves every frame. {LOCAL_UNIT} in the legal content resolves to
// this deployment's settlement currency from its own public registry card; while that is unknown the text says
// so instead of naming a unit that may be wrong (§LEGALKIT: a contract never falls back to another frame's money).
const { localCurrency } = useFrames()
// §LEGALKIT: who runs this frame, from the registry. Every provider placeholder in the texts resolves from here;
// on a frame in operator mode the provider-owned pages render the operator's facts and links instead.
const { config: legal, state: legalState } = useLegalConfig()

const unitLabel = computed(() => localCurrency.value || t('legalView.unit.unknown', 'the Unit of this frame'))
const tokens = computed(() => providerTokens(legal.value?.provider ?? null))
function withUnit(text: string): string {
  return resolveLegalTokens(text, tokens.value, unitLabel.value)
}

const pageSlug = computed(() => (route.params.page as string) || 'terms')

const langOpen = ref(false)
const langRef = ref<HTMLElement | null>(null)
function selectLocale(code: string) {
  i18nLocale.value = code as typeof i18nLocale.value
  langOpen.value = false
}
function onDocClickForLang(e: MouseEvent) {
  if (!langOpen.value) return
  if (langRef.value && !langRef.value.contains(e.target as Node)) {
    langOpen.value = false
  }
}

// Legal Suite v2.1: content lives in src/content/legal/suiteV2.ts (the contract language, English; the source
// PRODUCTION_DOCS/12_LEGAL/*.md is rendered from). §LEGALKIT B8: a German UI gets the German set for the pages that
// have one (Terms, Privacy, Risk Notice, and since §COOKIES the Cookie and Browser Storage Policy); those are
// convenience translations, and the banner below says so. Every other locale, and every page without a translation,
// reads the English source.
// The German set is a Partial (four pages); its spec guarantees every present page is whole, so the spread is a
// full page map (the cast says only that; a missing page falls through to the English one above it).
const legalPages = computed<Record<string, LegalPageV2>>(() =>
  i18nLocale.value === 'de' ? { ...LEGAL_SUITE_V2, ...(LEGAL_SUITE_V2_DE as Record<string, LegalPageV2>) } : LEGAL_SUITE_V2
)
const translatedView = computed(() => i18nLocale.value === 'de' && Boolean(LEGAL_SUITE_V2_DE[pageSlug.value]))

const currentPage = computed(() => legalPages.value[pageSlug.value] || null)

// Operator mode: a provider-owned page is the OPERATOR's statement, not ours. With no facts published it is an
// honest "not yet"; with facts and links it names them. Software- and network-owned pages render as written.
const operatorMode = computed(() => legal.value?.mode === 'operator')
const operatorView = computed(() => operatorMode.value && currentPage.value?.owner === 'provider')
const networkNote = computed(() => operatorMode.value && currentPage.value?.owner === 'network')
const operatorFacts = computed(() => legal.value?.provider ?? null)
const operatorLinks = computed(() => legal.value?.operator_links ?? null)
const operatorIdentified = computed(() => Boolean(legal.value?.provider_identified))
const providerLine = computed(() => legal.value?.provider?.full_line || '')

const pageKeys = computed(() => [
  { slug: 'terms', label: t('legalView.pages.terms') },
  { slug: 'privacy', label: t('legalView.pages.privacy') },
  { slug: 'cookies', label: t('legalView.pages.cookies') },
  { slug: 'disclaimer', label: t('legalView.pages.disclaimer') },
  { slug: 'dpa', label: t('legalView.pages.dpa') },
  { slug: 'license', label: t('legalView.pages.license') },
  { slug: 'sla', label: t('legalView.pages.sla') },
  { slug: 'evaluation', label: t('legalView.pages.evaluation', 'Evaluation Access') },
  { slug: 'operators', label: t('legalView.pages.operators') },
  { slug: 'imprint', label: t('legalView.pages.imprint') },
  { slug: 'security', label: t('legalView.pages.security', 'Vulnerability Disclosure') },
  { slug: 'dsa', label: t('legalView.pages.dsa', 'Digital Services Act') },
  { slug: 'changes', label: t('legalView.pages.changes', 'Legal Changes') },
])

function navigateTo(slug: string) {
  router.push(`/legal/${slug}`)
}

const toc = computed(() =>
  (currentPage.value?.sections || []).map((s, i) => {
    const short = s.title.length > 20 ? s.title.slice(0, 19).trimEnd() + '…' : s.title
    return {
      id: s.anchor || `sec-${i}`,
      label: s.number ? `${s.number} · ${short}` : short,
      full: s.number ? `${s.number} ${s.title}` : s.title,
    }
  })
)

function scrollToSection(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(() => {
  document.addEventListener('click', onDocClickForLang)
  scrollToHashOrTop()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClickForLang)
})

watch(pageSlug, () => {
  scrollToHashOrTop()
})

function scrollToHashOrTop() {
  const hash = route.hash?.replace('#', '')
  if (hash) {
    requestAnimationFrame(() => {
      document.getElementById(hash)?.scrollIntoView({ block: 'start' })
    })
  } else {
    window.scrollTo(0, 0)
  }
}

function formatContent(text: string): string {
  return withUnit(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}
</script>

<template>
  <div class="lp-root">
    <!-- Navigation -->
    <nav class="lp-nav">
      <div class="lp-nav-inner">
        <!-- Brand (mirrors DashboardHeader logo) -->
        <router-link to="/" class="lp-brand">
          <ProtocolMark :size="28" />
          <span class="lp-brand-name">THE PROTOCOL</span>
        </router-link>
        <div class="lp-nav-links">
          <!-- Language picker -->
          <div class="lp-lang" ref="langRef">
            <button
              class="lp-lang-btn"
              @click="langOpen = !langOpen"
              :aria-expanded="langOpen"
              :aria-label="`Language: ${availableLocales[i18nLocale]}`"
            >
              <Icon icon="mdi:translate" class="lp-lang-icon" />
              <span class="lp-lang-code">{{ i18nLocale.toUpperCase() }}</span>
            </button>
            <ul v-if="langOpen" class="lp-lang-menu" role="menu">
              <li v-for="(name, code) in availableLocales" :key="code" role="none">
                <button
                  role="menuitem"
                  class="lp-lang-item"
                  :class="{ 'lp-lang-item--active': i18nLocale === code }"
                  @click="selectLocale(code as string)"
                >
                  <span class="lp-lang-item-code">{{ (code as string).toUpperCase() }}</span>
                  <span class="lp-lang-item-name">{{ name }}</span>
                  <span v-if="i18nLocale === code" class="lp-lang-item-check" aria-hidden="true">✓</span>
                </button>
              </li>
            </ul>
          </div>
          <router-link to="/login" class="lp-nav-link">{{ t('legalView.nav.login') }}</router-link>
          <router-link to="/register" class="lp-nav-btn">{{ t('legalView.nav.signUp') }}</router-link>
        </div>
      </div>
    </nav>

    <div class="lp-layout" v-if="currentPage">
      <!-- Sidebar -->
      <aside class="lp-sidebar">
        <div class="lp-sidebar-sticky">
          <div class="lp-sidebar-label">{{ t('legalView.sidebar.label') }}</div>
          <button
            v-for="pk in pageKeys"
            :key="pk.slug"
            @click="navigateTo(pk.slug)"
            :class="['lp-sidebar-item', { 'lp-sidebar-active': pk.slug === pageSlug }]"
          >
            {{ pk.label }}
          </button>
          <div class="lp-sidebar-divider"></div>
          <router-link to="/" class="lp-sidebar-back">{{ t('legalView.sidebar.back') }}</router-link>
        </div>
      </aside>

      <!-- Main Content -->
      <main id="main-content" class="lp-main app-main" tabindex="-1">
        <!-- Header -->
        <div class="lp-header">
          <div class="lp-header-icon"><Icon :name="currentPage.icon" /></div>
          <h1 class="lp-title">{{ currentPage.title }}</h1>
          <p class="lp-subtitle">{{ currentPage.subtitle }}</p>
          <div class="lp-meta" v-if="currentPage.effectiveDate">
            <span v-if="currentPage.effectiveDate" class="lp-meta-item">
              <span class="lp-meta-icon"><Icon name="mdi:calendar" /></span> {{ t('legalView.meta.effective') }} {{ currentPage.effectiveDate }}
            </span>
            <span v-if="currentPage.version" class="lp-meta-item">
              <span class="lp-meta-icon"><Icon name="mdi:clipboard" /></span> {{ t('legalView.meta.version') }} {{ currentPage.version }}
            </span>
            <span class="lp-meta-item">
              <span class="lp-meta-icon"><Icon name="mdi:web" /></span> {{ withUnit(currentPage.jurisdiction) }}
            </span>
          </div>
          <nav v-if="toc.length > 3" class="lp-toc" :aria-label="t('legalView.onThisPage', 'On this page')">
            <span class="lp-toc-label">{{ t('legalView.onThisPage', 'On this page') }}</span>
            <button
              v-for="t in toc"
              :key="t.id"
              class="lp-toc-chip"
              :title="t.full"
              @click="scrollToSection(t.id)"
            >{{ t.label }}</button>
          </nav>
        </div>

        <!-- §LEGALKIT: operator mode, provider-owned page -->
        <div v-if="operatorView" class="lp-sections lp-operator" data-testid="lp-operator-view">
          <section class="lp-section">
            <div class="lp-section-head"><h2 class="lp-section-title">{{ operatorIdentified ? t('legalView.operator.title', 'This registry is run by its operator') : t('legalView.operator.notPublishedTitle', 'The operator of this registry has not published a legal notice yet') }}</h2></div>
            <template v-if="operatorIdentified && operatorFacts">
              <p class="lp-text">{{ tp('legalView.operator.runBy', 'Run by {name}', { name: operatorFacts.full_line || operatorFacts.legal_name }) }}</p>
              <p v-if="operatorFacts.legal_email || operatorFacts.support_email" class="lp-text">{{ tp('legalView.operator.contact', 'Contact: {email}', { email: operatorFacts.legal_email || operatorFacts.support_email }) }}</p>
              <p v-if="operatorFacts.address_block" class="lp-text" style="white-space: pre-line">{{ operatorFacts.address_block }}</p>
            </template>
            <p v-else class="lp-text">{{ t('legalView.operator.notPublishedBody', 'This registry runs the open-source TheProtocol software. Its operator publishes the legal notice, privacy policy and terms that apply to it; none has been published here yet.') }}</p>
          </section>
          <section class="lp-section">
            <div class="lp-section-head"><h2 class="lp-section-title">{{ t('legalView.operator.documents', "The operator's documents") }}</h2></div>
            <ul class="lp-list">
              <li>{{ t('legalView.operator.terms', 'Terms of service') }}: <a v-if="operatorLinks?.terms_url" :href="safeExternalUrl(operatorLinks.terms_url)" rel="noopener noreferrer">{{ operatorLinks.terms_url }}</a><span v-else>{{ t('legalView.operator.noLink', 'not published yet') }}</span></li>
              <li>{{ t('legalView.operator.privacy', 'Privacy policy') }}: <a v-if="operatorLinks?.privacy_url" :href="safeExternalUrl(operatorLinks.privacy_url)" rel="noopener noreferrer">{{ operatorLinks.privacy_url }}</a><span v-else>{{ t('legalView.operator.noLink', 'not published yet') }}</span></li>
              <li>{{ t('legalView.operator.securityPolicy', 'Vulnerability disclosure') }}: <a v-if="operatorLinks?.security_policy_url" :href="safeExternalUrl(operatorLinks.security_policy_url)" rel="noopener noreferrer">{{ operatorLinks.security_policy_url }}</a><span v-else>{{ t('legalView.operator.noLink', 'not published yet') }}</span></li>
            </ul>
          </section>
          <section class="lp-section">
            <div class="lp-plain"><span class="lp-plain-tag">Software</span><p class="lp-plain-text">{{ t('legalView.operator.softwareNotice', 'Software: TheProtocol, AGPL-3.0-or-later for server components and Apache-2.0 for the SDK. See the Software License Notice. The author of the software is not a party to this operator\'s terms.') }} <a href="#/legal/license">Software License Notice</a></p></div>
          </section>
        </div>

        <!-- Sections -->
        <div v-else class="lp-sections">
          <!-- §LEGALKIT B8: a translated page says what it is and offers the text that controls -->
          <div v-if="translatedView" class="lp-callout lp-callout-info lp-translation" data-testid="lp-translation-note">
            <span class="lp-callout-icon"><Icon name="mdi:translate" /></span>
            <span>
              {{ t('legalView.translation.notice', 'German convenience translation. The contract language is English (Terms § 1.7); where the two differ, the English text prevails to the extent mandatory law permits.') }}
              <button type="button" class="lp-translation-switch" @click="selectLocale('en')">{{ t('legalView.translation.showEnglish', 'Show the English version') }}</button>
            </span>
          </div>
          <div v-if="networkNote" class="lp-callout lp-callout-info" data-testid="lp-network-note">
            <span class="lp-callout-icon"><Icon name="mdi:information-outline" /></span>
            <span>{{ t('legalView.operator.networkNote', 'This page describes the network the software implements; it is the same on every frame and is not a statement by the operator of this registry.') }}</span>
          </div>
          <div v-if="legalState === 'failed' && currentPage.owner === 'provider'" class="lp-callout lp-callout-critical" data-testid="lp-config-failed">
            <span class="lp-callout-icon"><Icon name="mdi:alert" /></span>
            <span>The provider details could not be loaded from this registry; placeholders are shown as gaps. Reload the page.</span>
          </div>
          <section
            v-for="(section, idx) in currentPage.sections"
            :key="idx"
            class="lp-section"
            :id="section.anchor || `sec-${idx}`"
          >
            <div class="lp-section-head">
              <span v-if="section.number" class="lp-section-number">{{ section.number }}</span>
              <h2 class="lp-section-title">{{ section.title }}</h2>
            </div>

            <!-- Plain-words summary -->
            <div v-if="section.plain" class="lp-plain">
              <span class="lp-plain-tag">{{ t('legalView.plainWords', 'In plain words') }}</span>
              <p class="lp-plain-text">{{ withUnit(section.plain) }}</p>
            </div>

            <!-- Critical callout -->
            <div v-if="section.critical" class="lp-callout lp-callout-critical">
              <span class="lp-callout-icon"><Icon name="mdi:alert" /></span>
              <span>{{ withUnit(section.critical) }}</span>
            </div>

            <!-- Important callout -->
            <div v-if="section.important" class="lp-callout lp-callout-info">
              <span class="lp-callout-icon"><Icon name="mdi:information-outline" /></span>
              <span>{{ withUnit(section.important) }}</span>
            </div>

            <!-- Main content -->
            <p v-if="section.content" class="lp-text" v-html="formatContent(section.content)"></p>

            <!-- Subsections -->
            <div v-if="section.subsections" class="lp-subsections">
              <div v-for="(sub, si) in section.subsections" :key="si" class="lp-subsection">
                <h3 class="lp-subsection-title">{{ sub.title }}</h3>
                <p class="lp-text" v-html="formatContent(sub.content)"></p>
                <ul v-if="sub.items" class="lp-list">
                  <li v-for="(item, ii) in sub.items" :key="ii">{{ withUnit(item) }}</li>
                </ul>
              </div>
            </div>

            <!-- List items -->
            <ul v-if="section.items" class="lp-list">
              <li v-for="(item, ii) in section.items" :key="ii">{{ withUnit(item) }}</li>
            </ul>
          </section>
        </div>

        <!-- Footer -->
        <div class="lp-content-footer">
          <p>{{ t('legalView.footer.copy') }}</p>
          <p v-if="providerLine" class="lp-footer-small" data-testid="lp-footer-provider">{{ tp('legalView.footer.provider', 'Provider: {provider}', { provider: providerLine }) }}</p>
          <!-- AGPL-3.0 § 13 by configuration: shown only where the frame names its source (SOURCE_CODE_URL) -->
          <p v-if="legal?.source_code_url" class="lp-footer-small" data-testid="lp-footer-source">{{ t('legalView.footer.source', 'Source code of this deployment (AGPL-3.0 § 13):') }} <a :href="safeExternalUrl(legal.source_code_url)" rel="noopener noreferrer" target="_blank">{{ legal.source_code_url }}</a></p>
        </div>
      </main>
    </div>

    <!-- 404 -->
    <div v-else class="lp-not-found">
      <h1>{{ t('legalView.notFound.title') }}</h1>
      <p>{{ t('legalView.notFound.body') }}</p>
      <button @click="navigateTo('terms')" class="lp-nav-btn">{{ t('legalView.notFound.viewTerms') }}</button>
    </div>
  </div>
</template>

<style scoped>
.lp-root {
  min-height: 100vh;
  background: #060a10;
  color: #c8d6e5;
  font-family: 'IBM Plex Sans', 'Segoe UI', system-ui, sans-serif;
}

/* Nav */
.lp-nav {
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(6, 10, 16, 0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(0, 230, 230, 0.1);
}
.lp-nav-inner {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0.875rem 2rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

/* Brand: ProtocolMark + wordmark, mirrors DashboardSidebar */
.lp-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  cursor: pointer;
  flex-shrink: 0;
  transition: opacity 0.2s;
}
.lp-brand:hover { opacity: 0.85; }
.lp-brand-name {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.2em;
  color: rgba(255, 255, 255, 0.9);
  font-family: 'Fira Code', monospace;
  text-transform: uppercase;
}

.lp-nav-links { display: flex; gap: 1rem; align-items: center; }
.lp-nav-link {
  color: #8899aa;
  text-decoration: none;
  font-size: 0.85rem;
  letter-spacing: 0.08em;
  font-weight: 500;
  transition: color 0.2s;
}
.lp-nav-link:hover { color: #00e6e6; }
.lp-nav-btn {
  padding: 0.5rem 1.25rem;
  background: #00e6e6;
  color: #060a10;
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-decoration: none;
  border: none;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}
.lp-nav-btn:hover {
  background: #00cccc;
  box-shadow: 0 0 20px rgba(0, 230, 230, 0.3);
}

/* Language picker */
.lp-lang {
  position: relative;
  flex-shrink: 0;
}
.lp-lang-btn {
  height: 30px;
  padding: 0 10px;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(0, 230, 230, 0.06);
  border: 1px solid rgba(0, 230, 230, 0.18);
  border-radius: 4px;
  color: rgba(0, 230, 230, 0.9);
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.06em;
  cursor: pointer;
  font-family: 'Fira Code', monospace;
  transition: background 0.15s, border-color 0.15s;
}
.lp-lang-btn:hover {
  background: rgba(0, 230, 230, 0.14);
  border-color: rgba(0, 230, 230, 0.32);
}
.lp-lang-icon { width: 14px; height: 14px; flex-shrink: 0; }
.lp-lang-code { font-feature-settings: 'tnum' 1; }
.lp-lang-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 210px;
  background: rgba(10, 14, 22, 0.98);
  border: 1px solid rgba(0, 230, 230, 0.22);
  border-radius: 6px;
  padding: 4px;
  list-style: none;
  margin: 0;
  z-index: 100;
  box-shadow: 0 12px 36px rgba(0, 0, 0, 0.6);
  backdrop-filter: blur(10px);
}
.lp-lang-item {
  width: 100%;
  display: grid;
  grid-template-columns: 36px 1fr 16px;
  align-items: center;
  gap: 6px;
  padding: 7px 10px;
  border: none;
  background: transparent;
  color: rgba(230, 249, 255, 0.85);
  cursor: pointer;
  font-size: 0.8rem;
  text-align: left;
  border-radius: 4px;
  font-family: inherit;
  transition: background 0.1s, color 0.1s;
}
.lp-lang-item:hover {
  background: rgba(0, 230, 230, 0.14);
  color: #ffffff;
}
.lp-lang-item--active {
  color: rgba(0, 230, 230, 1);
  background: rgba(0, 230, 230, 0.10);
}
.lp-lang-item-code {
  font-family: 'Fira Code', monospace;
  font-weight: 700;
  font-size: 0.62rem;
  letter-spacing: 0.06em;
  opacity: 0.75;
}
.lp-lang-item-name { font-weight: 500; }
.lp-lang-item-check {
  text-align: right;
  font-weight: 700;
  color: rgba(0, 230, 230, 1);
}

/* Layout */
.lp-layout {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  gap: 0;
  min-height: calc(100vh - 60px);
}

/* Sidebar */
.lp-sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid rgba(0, 230, 230, 0.08);
  background: rgba(8, 12, 20, 0.5);
}
.lp-sidebar-sticky {
  position: sticky;
  top: 60px;
  padding: 2rem 1rem;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.lp-sidebar-label {
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.15em;
  color: #8593a2;
  padding: 0 0.75rem;
  margin-bottom: 0.75rem;
}
.lp-sidebar-item {
  display: block;
  width: 100%;
  text-align: left;
  padding: 0.6rem 0.75rem;
  font-size: 0.825rem;
  color: #8899aa;
  background: none;
  border: none;
  border-left: 2px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.lp-sidebar-item:hover {
  color: #c8d6e5;
  background: rgba(0, 230, 230, 0.03);
}
.lp-sidebar-active {
  color: #00e6e6 !important;
  border-left-color: #00e6e6;
  background: rgba(0, 230, 230, 0.05) !important;
}
.lp-sidebar-divider {
  height: 1px;
  background: rgba(0, 230, 230, 0.08);
  margin: 1rem 0.75rem;
}
.lp-sidebar-back {
  font-size: 0.8rem;
  color: #8e9bab;
  text-decoration: none;
  padding: 0.5rem 0.75rem;
  transition: color 0.2s;
}
.lp-sidebar-back:hover { color: #00e6e6; }

/* Main Content */
.lp-main {
  flex: 1;
  min-width: 0;
  padding: 3rem 4rem;
}

/* Header */
.lp-header {
  margin-bottom: 3rem;
  padding-bottom: 2rem;
  border-bottom: 1px solid rgba(0, 230, 230, 0.08);
}
.lp-header-icon {
  font-size: 38px; /* Icon.vue sizes 1em x 1em; this is the documented override */
  line-height: 1;
  color: #00e6e6;
  opacity: 0.9;
  margin-bottom: 0.85rem;
}

/* On-this-page index */
.lp-toc {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 1.35rem;
}
.lp-toc-label {
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #8593a2;
  font-family: 'Fira Code', monospace;
  margin-right: 0.35rem;
}
.lp-toc-chip {
  font-family: 'Fira Code', monospace;
  font-size: 0.66rem;
  padding: 4px 9px;
  background: rgba(0, 230, 230, 0.05);
  border: 1px solid rgba(0, 230, 230, 0.14);
  border-radius: 3px;
  color: #7fb3c3;
  cursor: pointer;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
}
.lp-toc-chip:hover {
  color: #00e6e6;
  border-color: rgba(0, 230, 230, 0.35);
  background: rgba(0, 230, 230, 0.1);
}
.lp-title {
  font-size: 2.25rem;
  font-weight: 300;
  letter-spacing: 0.02em;
  color: #f0f4f8;
  margin-bottom: 0.5rem;
}
.lp-subtitle {
  font-size: 1rem;
  color: #8e9bab;
  font-weight: 400;
  max-width: 72ch;
}
.lp-meta {
  display: flex;
  gap: 2rem;
  margin-top: 1.25rem;
  flex-wrap: wrap;
}
.lp-meta-item {
  font-size: 0.8rem;
  color: #8593a2;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.lp-meta-icon { font-size: 0.9rem; }

/* Sections */
.lp-sections { display: flex; flex-direction: column; gap: 2.5rem; }
.lp-section {
  padding: 2rem;
  background: rgba(10, 16, 24, 0.5);
  border: 1px solid rgba(0, 230, 230, 0.06);
  border-radius: 2px;
  scroll-margin-top: 72px;
}
.lp-section-head {
  display: flex;
  align-items: baseline;
  gap: 1rem;
  margin-bottom: 1.25rem;
}
.lp-section-number {
  font-size: 0.75rem;
  font-weight: 600;
  color: #00e6e6;
  letter-spacing: 0.05em;
  white-space: nowrap;
  opacity: 0.7;
}
.lp-section-title {
  font-size: 1.25rem;
  font-weight: 500;
  color: #e0e6ed;
  letter-spacing: 0.01em;
}

/* Plain-words summary */
.lp-plain {
  margin-bottom: 1.25rem;
  padding: 0.9rem 1.15rem;
  background: rgba(0, 230, 230, 0.035);
  border-left: 3px solid rgba(0, 230, 230, 0.55);
  border-radius: 2px;
}
.lp-plain-tag {
  display: inline-block;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: #00e6e6;
  opacity: 0.85;
  margin-bottom: 0.35rem;
  font-family: 'Fira Code', monospace;
}
.lp-plain-text {
  font-size: 0.9rem;
  line-height: 1.7;
  color: #b9c9d9;
  margin: 0;
}

/* Text */
.lp-text {
  font-size: 0.925rem;
  line-height: 1.75;
  color: #99aabb;
  margin-bottom: 1rem;
}
.lp-text:last-child { margin-bottom: 0; }
.lp-text :deep(strong) { color: #c2d2e2; font-weight: 600; }

/* Callouts */
.lp-callout {
  display: flex;
  gap: 0.75rem;
  padding: 1rem 1.25rem;
  margin-bottom: 1.25rem;
  font-size: 0.875rem;
  line-height: 1.6;
  border-radius: 2px;
}
.lp-callout-critical {
  background: rgba(220, 38, 38, 0.08);
  border: 1px solid rgba(220, 38, 38, 0.2);
  color: #f87171;
}
.lp-callout-info {
  background: rgba(0, 230, 230, 0.04);
  border: 1px solid rgba(0, 230, 230, 0.12);
  color: #7dd3d3;
}
.lp-callout-icon { flex-shrink: 0; }

/* Subsections */
.lp-subsections {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.lp-subsection {
  padding-left: 1.25rem;
  border-left: 2px solid rgba(0, 230, 230, 0.1);
}
.lp-subsection-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: #b0bec5;
  margin-bottom: 0.5rem;
}

/* Lists */
.lp-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.lp-list li {
  position: relative;
  padding: 0.5rem 0 0.5rem 1.5rem;
  font-size: 0.9rem;
  color: #99aabb;
  border-bottom: 1px solid rgba(0, 230, 230, 0.04);
  line-height: 1.6;
}
.lp-list li:last-child { border-bottom: none; }
.lp-list li::before {
  content: '▸';
  position: absolute;
  left: 0;
  color: #00e6e6;
  opacity: 0.5;
  font-weight: bold;
}

/* Content Footer */
.lp-content-footer {
  margin-top: 4rem;
  padding-top: 2rem;
  border-top: 1px solid rgba(0, 230, 230, 0.08);
  text-align: center;
  font-size: 0.8rem;
  color: #7d8a98;
}
.lp-footer-small {
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #7d8a98;
}

/* 404 */
.lp-not-found {
  text-align: center;
  padding: 6rem 2rem;
}
.lp-not-found h1 {
  font-size: 2rem;
  font-weight: 300;
  color: #e0e6ed;
  margin-bottom: 1rem;
}
.lp-not-found p {
  color: #8e9bab;
  margin-bottom: 2rem;
}

/* Responsive */
@media (max-width: 900px) {
  .lp-sidebar { display: none; }
  .lp-main { padding: 2rem 1.5rem; }
  .lp-title { font-size: 1.75rem; }
  .lp-meta { flex-direction: column; gap: 0.5rem; }
  .lp-lang-btn { padding: 0 8px; }
  .lp-lang-code { display: none; }
  .lp-lang-menu { right: -4px; min-width: 190px; }
  .lp-brand-dim { display: none; }
  .lp-brand-sep { display: none; }
}
.lp-translation-switch {
  margin-left: 0.6rem;
  background: none;
  border: 1px solid currentColor;
  border-radius: 4px;
  color: inherit;
  cursor: pointer;
  font: inherit;
  font-size: 0.85em;
  padding: 0.15rem 0.5rem;
}
.lp-translation-switch:hover,
.lp-translation-switch:focus-visible {
  background: rgba(255, 255, 255, 0.08);
  outline: none;
}
</style>
