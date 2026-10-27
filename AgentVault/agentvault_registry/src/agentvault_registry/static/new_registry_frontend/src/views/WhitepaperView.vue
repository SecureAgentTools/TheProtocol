<template>
  <div class="wp-page">
    <!-- Ambient background (dimmer for article readability) -->
    <div class="wp-ambient">
      <div class="wp-grid-bg"></div>
      <div class="wp-scan"></div>
      <div class="wp-glow wp-glow-1"></div>
      <div class="wp-glow wp-glow-2"></div>
      <div class="wp-glow wp-glow-3"></div>
    </div>

    <!-- Reading progress bar -->
    <div class="wp-progress" :style="{ width: readingProgress + '%' }"></div>

    <!-- Top chrome -->
    <header class="wp-chrome">
      <div class="wp-chrome-inner">
        <RouterLink to="/" class="wp-back">{{ t('whitepaperView.back') }}</RouterLink>
        <div class="wp-chrome-meta">
          <span class="wp-chip"><span class="wp-chip-dot"></span>{{ paper.chip }}</span>
        </div>
        <button class="wp-print" @click="printPage" title="Print or save as PDF">PRINT / PDF</button>
      </div>
    </header>

    <!-- Header -->
    <section class="wp-header">
      <div class="wp-header-eyebrow">{{ paper.eyebrow }}</div>
      <h1 class="wp-title">{{ paper.titleTop }}<br /><span class="wp-accent">{{ paper.titleAccent }}</span></h1>
      <p class="wp-subtitle">{{ paper.subtitle }}</p>
      <div class="wp-meta-grid">
        <div v-for="item in paper.meta" :key="item.label" class="wp-meta-item"><div class="wp-meta-label">{{ item.label }}</div><div class="wp-meta-value">{{ item.value }}</div><div class="wp-meta-sub">{{ item.sub }}</div></div>
      </div>
      <div class="wp-meta-sub-line">{{ wordCount.toLocaleString(appLocale()) }} words &middot; ~{{ readingTime }} min read</div>
    </section>

    <!-- Table of contents -->
    <nav class="wp-toc" aria-label="Table of contents">
      <div class="wp-toc-label">CONTENTS</div>
      <ol class="wp-toc-list">
        <li v-for="item in toc" :key="item.id">
          <a :href="`#${item.id}`" class="wp-toc-link" @click.prevent="scrollToSection(item.id)">
            <span class="wp-toc-num">{{ item.num }}</span>
            <span class="wp-toc-text">{{ item.label }}</span>
          </a>
        </li>
      </ol>
    </nav>

    <!-- Rendered markdown content -->
    <!-- §LANDINGTRUTH (16): the whitepaper describes lock-weight (veToken) voting -->
    <MemberModeNotice v-if="paper.memberModeNotice" />
    <article class="wp-content" v-html="renderedContent" ref="articleRef" @click="onArticleClick"></article>

    <!-- Footer -->
    <footer class="wp-footer">
      <div class="wp-footer-row">
        <RouterLink to="/roadmap" class="wp-footer-link">&larr; Roadmap</RouterLink>
        <RouterLink v-if="journalEnabled" to="/blog" class="wp-footer-link">Journal</RouterLink>
        <div class="wp-footer-cite">
          <span>{{ paper.citeLabel }} Cite as:</span>
          <code class="wp-cite">{{ paper.cite }}</code>
        </div>
      </div>
    </footer>
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useI18n } from '@/composables/useI18n'
import MemberModeNotice from '@/components/docs/MemberModeNotice.vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { useRoute } from 'vue-router'

const { t } = useI18n()
const { journalEnabled } = useRegistryConfig()
import {
  renderDocsMarkdown,
  stripFrontmatter,
} from '@/composables/docs/useDocsMarkdown'
import { paperArticle, paperContents } from './whitepaperOutline'
import { renderMermaidDiagrams } from '@/composables/docs/useMermaidRenderer'

import quantumSrc from '@/assets/docs/whitepaper/accountable-quantum-compute.md?raw'

// The whitepapers this view renders: /whitepaper is the platform paper,
// /whitepaper/quantum the accountable-compute paper the roadmap links.
interface Paper {
  src: string
  chip: string
  eyebrow: string
  titleTop: string
  titleAccent: string
  subtitle: string
  meta: Array<{ label: string; value: string; sub: string }>
  memberModeNotice: boolean
  citeLabel: string
  cite: string
}

// A function, so the translated platform strings follow the locale.
const papers = (): Record<string, Paper> => ({
  quantum: {
    src: quantumSrc,
    chip: 'WHITEPAPER · OCTOBER 2026',
    eyebrow: 'THEPROTOCOL · WHITEPAPER · DRAFT · OCTOBER 2026',
    titleTop: 'Accountable',
    titleAccent: 'quantum compute',
    subtitle: 'A federated agent network as the trust layer for quantum workloads, and the path to a network that survives quantum computers.',
    meta: [
      { label: 'STEWARD', value: 'Raphael Zbigniew Jeziorny', sub: 'review before publication' },
      { label: 'DRAFTED BY', value: 'Claude Opus 5.5 · Anthropic', sub: 'drafted from the code and its tests' },
      { label: 'REPLACES', value: 'August 2025 analysis', sub: 'Quantum-Classical Interface Protocol Analysis' },
      { label: 'SOURCE LICENSE', value: 'AGPL v3', sub: 'the code base it describes' },
    ],
    memberModeNotice: false,
    citeLabel: 'Draft · October 2026.',
    cite: 'Jeziorny, R. Z. (2026). Accountable quantum compute. TheProtocol whitepaper, draft.',
  },
})

const route = useRoute()
const paper = computed<Paper>(() => {
  const all = papers()
  return all[String(route.params.paper || 'quantum')] ?? all.quantum
})

const articleRef = ref<HTMLElement | null>(null)
const readingProgress = ref(0)

const bodyMarkdown = computed(() => stripFrontmatter(paper.value.src))

const renderedContent = computed(() =>
  renderDocsMarkdown(paperArticle(bodyMarkdown.value), { classPrefix: 'wp', headingAnchors: true })
)

const wordCount = computed(() => bodyMarkdown.value.trim().split(/\s+/).filter(Boolean).length)
const readingTime = computed(() => Math.max(1, Math.ceil(wordCount.value / 250)))

const toc = computed(() => paperContents(bodyMarkdown.value))

function scrollToSection(id: string) {
  const el = document.getElementById(id)
  if (!el) return
  const y = el.getBoundingClientRect().top + window.scrollY - 80
  window.scrollTo({ top: y, behavior: 'smooth' })
  history.replaceState(null, '', `#${id}`)
}

function printPage() {
  window.print()
}

function onArticleClick(event: MouseEvent) {
  const target = event.target as HTMLElement
  if (target.getAttribute('data-action') === 'copy-code') {
    event.preventDefault()
    const wrap = target.closest('.wp-code-wrap')
    const codeEl = wrap?.querySelector('pre.wp-code code') as HTMLElement | null
    if (!codeEl) return
    navigator.clipboard.writeText(codeEl.textContent || '').catch(() => {})
    target.textContent = 'Copied'
    window.setTimeout(() => { target.textContent = 'Copy' }, 1200)
  }
}

function onScroll() {
  const doc = document.documentElement
  const total = doc.scrollHeight - window.innerHeight
  if (total <= 0) { readingProgress.value = 0; return }
  const scrolled = window.scrollY
  readingProgress.value = Math.min(100, Math.max(0, (scrolled / total) * 100))
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
  const hash = window.location.hash.slice(1)
  if (hash) {
    setTimeout(() => scrollToSection(hash), 80)
  }
  nextTick(() =>
    renderMermaidDiagrams({
      selector: '.wp-content .wp-mermaid',
      theme: 'whitepaper',
    })
  )
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>

<style scoped>
.wp-page {
  --bg: #060810;
  --cyan: var(--nc-primary);
  --green: #00e676;
  --text: #b0bec5;
  --text-bright: #f0f4f8;
  --muted: #78909c;
  --card-bg: #0a0e18;
  --card-border: #141a2a;
  --mono: 'JetBrains Mono', 'Fira Code', 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
  position: relative;
  padding-bottom: 120px;
}

.wp-ambient { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
.wp-grid-bg {
  position: fixed; inset: 0; z-index: 0;
  background-image:
    linear-gradient(rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px),
    linear-gradient(90deg, rgba(var(--nc-primary-rgb),0.02) 1px, transparent 1px);
  background-size: 80px 80px;
}
.wp-scan {
  position: fixed; top: 0; left: 0; right: 0; height: 2px; z-index: 0;
  background: linear-gradient(90deg, transparent, var(--nc-primary), transparent);
  opacity: 0.3;
  animation: wpScan 12s linear infinite;
}
@keyframes wpScan { from { top: 0; } to { top: 100vh; } }
.wp-glow { position: fixed; border-radius: 50%; pointer-events: none; z-index: 0; filter: blur(140px); }
.wp-glow-1 { width: 620px; height: 620px; top: -10%; left: -5%; background: #00b8b8; opacity: 0.05; }
.wp-glow-2 { width: 440px; height: 440px; bottom: 8%; right: -5%; background: #10b981; opacity: 0.035; }
.wp-glow-3 { width: 320px; height: 320px; top: 42%; left: 48%; background: var(--nc-primary); opacity: 0.025; }

.wp-progress {
  position: fixed; top: 0; left: 0; height: 3px;
  background: linear-gradient(90deg, var(--nc-primary), #10b981);
  box-shadow: 0 0 10px rgba(var(--nc-primary-rgb),0.4);
  z-index: 100;
  transition: width 0.12s ease-out;
}

.wp-chrome {
  position: sticky; top: 0; z-index: 50;
  background: linear-gradient(180deg, rgba(6,8,16,0.95) 0%, rgba(6,8,16,0.75) 100%);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.1);
}
.wp-chrome-inner {
  max-width: 860px; margin: 0 auto;
  padding: 14px 2rem;
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
}
.wp-back, .wp-print {
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--cyan); text-decoration: none; background: none; border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  padding: 7px 14px; border-radius: 3px; cursor: pointer; transition: all 0.2s;
}
.wp-back:hover, .wp-print:hover { background: rgba(var(--nc-primary-rgb),0.08); border-color: var(--cyan); }
.wp-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 10px; font-weight: 600;
  letter-spacing: 0.18em; text-transform: uppercase;
  color: var(--cyan);
  border: 1px solid rgba(var(--nc-primary-rgb),0.22);
  background: rgba(var(--nc-primary-rgb),0.05);
  padding: 5px 12px; border-radius: 3px;
}
.wp-chip-dot {
  width: 5px; height: 5px; border-radius: 50%;
  background: var(--green); box-shadow: 0 0 6px var(--green);
  animation: wp-pulse 2s ease-in-out infinite;
}
@keyframes wp-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

.wp-header {
  position: relative; z-index: 1;
  max-width: 860px; margin: 0 auto;
  padding: 80px 2rem 50px;
}
.wp-header-eyebrow {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.2em; color: var(--muted);
  margin-bottom: 28px;
}
.wp-title {
  font-size: clamp(2rem, 5.2vw, 3.6rem);
  font-weight: 300;
  color: var(--text-bright);
  line-height: 1.12;
  letter-spacing: -0.02em;
  margin: 0 0 24px;
  text-shadow: 0 0 80px rgba(var(--nc-primary-rgb),0.1);
}
.wp-accent { color: var(--cyan); font-weight: 400; }
.wp-subtitle {
  font-size: 17px; line-height: 1.7;
  color: #8a9aac;
  max-width: 640px;
  margin: 0 0 40px;
  font-weight: 300;
}
.wp-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1px;
  background: rgba(var(--nc-primary-rgb),0.08);
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 4px;
  overflow: hidden;
}
.wp-meta-sub-line {
  margin-top: 14px;
  font-family: var(--mono);
  font-size: 11.5px;
  letter-spacing: 0.08em;
  color: var(--muted);
  text-transform: uppercase;
  text-align: right;
}
@media (max-width: 520px) {
  .wp-meta-grid { grid-template-columns: 1fr; }
  .wp-meta-sub-line { text-align: left; font-size: 10.5px; }
}
.wp-meta-item {
  padding: 18px 20px;
  background: #080c16;
}
.wp-meta-label {
  font-family: var(--mono); font-size: 9.5px;
  letter-spacing: 0.18em; color: var(--muted);
  margin-bottom: 6px;
  text-transform: uppercase;
}
.wp-meta-value {
  font-size: 14.5px; color: var(--text-bright);
  font-weight: 500;
  margin-bottom: 3px;
}
.wp-meta-sub {
  font-size: 11.5px; color: #6e7d8d;
  font-family: var(--mono);
}

.wp-toc {
  position: relative; z-index: 1;
  max-width: 860px; margin: 0 auto;
  padding: 20px 2rem 40px;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.08);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.08);
}
.wp-toc-label {
  font-family: var(--mono); font-size: 10px;
  letter-spacing: 0.2em; color: var(--muted);
  margin: 18px 0 14px;
  text-transform: uppercase;
}
.wp-toc-list {
  list-style: none; margin: 0; padding: 0;
  display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 4px 24px;
}
.wp-toc-link {
  display: flex; align-items: baseline; gap: 14px;
  padding: 7px 2px;
  color: #8a9aac; text-decoration: none;
  font-size: 14px; line-height: 1.45;
  border-bottom: 1px dashed transparent;
  transition: color 0.15s, border-color 0.15s;
}
.wp-toc-link:hover {
  color: var(--text-bright);
  border-bottom-color: rgba(var(--nc-primary-rgb),0.2);
}
.wp-toc-num {
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.05em;
  color: var(--cyan); min-width: 28px;
}

.wp-content {
  position: relative; z-index: 1;
  max-width: 720px;
  margin: 0 auto;
  padding: 40px 2rem 0;
}

.wp-content :deep(h1) {
  font-size: 2rem; font-weight: 300;
  color: var(--text-bright);
  margin: 0 0 2rem;
  letter-spacing: -0.01em;
  display: none;
}
.wp-content :deep(h2) {
  font-size: 1.55rem; font-weight: 400;
  color: var(--text-bright);
  margin: 3.8rem 0 1.4rem;
  letter-spacing: -0.01em;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.18);
  scroll-margin-top: 90px;
}
.wp-content :deep(h2:first-child) { margin-top: 0.5rem; }
.wp-content :deep(h3) {
  font-size: 1.2rem; font-weight: 500;
  color: var(--text-bright);
  margin: 2.4rem 0 0.9rem;
  scroll-margin-top: 90px;
}
.wp-content :deep(h4) {
  font-size: 1.02rem; font-weight: 600;
  color: #c8d2dc;
  margin: 1.8rem 0 0.7rem;
  letter-spacing: 0.01em;
  scroll-margin-top: 90px;
}
.wp-content :deep(p) {
  font-size: 15.5px; line-height: 1.82;
  color: #94a3b3;
  margin: 0 0 1.4rem;
}
.wp-content :deep(strong) { color: #e4ecf4; font-weight: 600; }
.wp-content :deep(em) { color: #b8c4d0; font-style: italic; }

.wp-content :deep(code.wp-ic),
.wp-content :deep(code) {
  font-family: var(--mono);
  font-size: 13px;
  background: rgba(var(--nc-primary-rgb),0.06);
  border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  padding: 2px 6px;
  border-radius: 3px;
  color: var(--cyan);
  /* a long identifier breaks where it must on a phone (the camera, 2026-10-13) */
  overflow-wrap: anywhere;
}

.wp-content :deep(.wp-code-wrap) {
  position: relative;
  margin: 1.6rem 0;
}
.wp-content :deep(pre.wp-code) {
  background: #0a0e18;
  border: 1px solid #141a2a;
  border-left: 3px solid rgba(var(--nc-primary-rgb),0.4);
  border-radius: 4px;
  padding: 1.4rem 1.35rem 1.15rem;
  overflow-x: auto;
  margin: 0;
  font-size: 13px; line-height: 1.7;
}
.wp-content :deep(.wp-code-lang) {
  position: absolute;
  top: 0.5rem;
  left: 1rem;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.16em;
  color: rgba(176, 190, 197, 0.4);
  pointer-events: none;
  z-index: 2;
}
.wp-content :deep(.wp-code-copy) {
  position: absolute;
  top: 0.45rem;
  right: 0.6rem;
  z-index: 3;
  font-family: var(--mono);
  font-size: 10px;
  letter-spacing: 0.08em;
  padding: 0.28rem 0.55rem;
  background: rgba(10, 14, 24, 0.8);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.18);
  border-radius: 3px;
  color: var(--cyan);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.18s, background 0.18s;
}
.wp-content :deep(.wp-code-wrap:hover .wp-code-copy),
.wp-content :deep(.wp-code-copy:focus-visible) { opacity: 1; }
/* a device with no hover (a phone) cannot reveal the copy button: show it there */
@media (hover: none) {
  .wp-content :deep(.wp-code-copy) { opacity: 1; }
}
.wp-content :deep(.wp-code-copy:hover) {
  background: rgba(var(--nc-primary-rgb), 0.1);
  border-color: var(--cyan);
}

/* Callouts */
.wp-content :deep(.wp-callout) {
  margin: 1.6rem 0;
  padding: 0.85rem 1.2rem 0.7rem;
  border-radius: 4px;
  border: 1px solid #141a2a;
  border-left-width: 3px;
  background: rgba(10, 14, 24, 0.5);
}
.wp-content :deep(.wp-callout-head) {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  margin-bottom: 0.4rem;
}
.wp-content :deep(.wp-callout-icon) {
  width: 10px; height: 10px;
  border-radius: 50%;
}
.wp-content :deep(.wp-callout-label) {
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.wp-content :deep(.wp-callout-body > p) { margin-bottom: 0.5rem; }
.wp-content :deep(.wp-callout-body > p:last-child) { margin-bottom: 0; }

.wp-content :deep(.wp-callout-tip) { border-left-color: #10b981; }
.wp-content :deep(.wp-callout-tip .wp-callout-icon) { background: #10b981; }
.wp-content :deep(.wp-callout-tip .wp-callout-label) { color: #10b981; }

.wp-content :deep(.wp-callout-warn) { border-left-color: #f59e0b; }
.wp-content :deep(.wp-callout-warn .wp-callout-icon) { background: #f59e0b; }
.wp-content :deep(.wp-callout-warn .wp-callout-label) { color: #f59e0b; }

.wp-content :deep(.wp-callout-info) { border-left-color: var(--cyan); }
.wp-content :deep(.wp-callout-info .wp-callout-icon) { background: var(--cyan); }
.wp-content :deep(.wp-callout-info .wp-callout-label) { color: var(--cyan); }

.wp-content :deep(.wp-callout-note) { border-left-color: #8b5cf6; }
.wp-content :deep(.wp-callout-note .wp-callout-icon) { background: #8b5cf6; }
.wp-content :deep(.wp-callout-note .wp-callout-label) { color: #8b5cf6; }

.wp-content :deep(.wp-mermaid) {
  background: #0a0e18;
  border: 1px solid #141a2a;
  border-left: 3px solid rgba(var(--nc-primary-rgb),0.4);
  border-radius: 4px;
  padding: 1.6rem 1rem;
  margin: 1.8rem 0;
  overflow-x: auto;
  text-align: center;
  min-height: 80px;
  font-size: 13px;
  line-height: 1.6;
  color: #6e7d8d;
}
.wp-content :deep(.wp-mermaid svg) {
  max-width: 100%;
  height: auto;
  margin: 0 auto;
  display: block;
}
.wp-content :deep(.wp-mermaid[data-processed="true"]) {
  color: transparent;
  background: #0a0e18;
}
.wp-content :deep(pre.wp-code code) {
  background: none; border: none; padding: 0;
  color: #b5c3d0; font-size: 13px;
}

.wp-content :deep(blockquote) {
  border-left: 3px solid var(--cyan);
  margin: 1.8rem 0;
  padding: 0.9rem 1.5rem;
  color: #8a9aac;
  font-style: italic;
  background: rgba(var(--nc-primary-rgb),0.03);
  border-radius: 0 4px 4px 0;
}

.wp-content :deep(ul), .wp-content :deep(ol.wp-ol), .wp-content :deep(ol) {
  margin: 0 0 1.4rem; padding-left: 1.6rem;
}
.wp-content :deep(li) {
  font-size: 15.5px; line-height: 1.78;
  color: #94a3b3;
  margin-bottom: 0.45rem;
}

.wp-content :deep(.wp-tbl-wrap) {
  margin: 1.6rem 0;
  border: 1px solid rgba(var(--nc-primary-rgb),0.12);
  border-radius: 4px;
  overflow-x: auto;
  background: #080c16;
}
.wp-content :deep(table) {
  width: 100%; border-collapse: collapse;
  font-size: 13.5px;
}
.wp-content :deep(th) {
  font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--cyan); font-weight: 600;
  text-align: left;
  padding: 12px 14px;
  background: rgba(var(--nc-primary-rgb),0.04);
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.15);
}
.wp-content :deep(td) {
  padding: 11px 14px;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06);
  color: #a8b4c0;
  line-height: 1.55;
  vertical-align: top;
}
.wp-content :deep(tr:last-child td) { border-bottom: none; }

.wp-content :deep(a) {
  color: var(--cyan);
  text-decoration: none;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.3);
  transition: border-color 0.2s;
}
.wp-content :deep(a:hover) { border-bottom-color: var(--cyan); }

.wp-content :deep(hr) {
  border: none;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.1);
  margin: 2.8rem 0;
}

.wp-footer {
  position: relative; z-index: 1;
  max-width: 720px;
  margin: 80px auto 0;
  padding: 2rem 2rem 0;
  border-top: 1px solid rgba(var(--nc-primary-rgb),0.1);
}
.wp-footer-row {
  display: flex; flex-wrap: wrap; gap: 20px;
  justify-content: space-between; align-items: center;
}
.wp-footer-link {
  font-family: var(--mono); font-size: 12px;
  color: var(--cyan); text-decoration: none;
  letter-spacing: 0.04em;
  transition: opacity 0.2s;
}
.wp-footer-link:hover { opacity: 0.7; }
.wp-footer-cite {
  font-size: 12px; color: var(--muted); text-align: right;
}
.wp-cite {
  display: block; margin-top: 4px;
  font-family: var(--mono); font-size: 11.5px;
  color: #7a8898;
  background: rgba(var(--nc-primary-rgb),0.04);
  padding: 6px 10px; border-radius: 3px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.08);
}

@media (max-width: 720px) {
  .wp-chrome-inner { padding: 12px 1.2rem; gap: 8px; }
  .wp-header { padding: 48px 1.2rem 32px; }
  .wp-toc { padding: 16px 1.2rem 28px; }
  .wp-toc-list { grid-template-columns: 1fr; gap: 0; }
  .wp-content { padding: 28px 1.2rem 0; }
  .wp-footer { padding: 28px 1.2rem 0; }
  .wp-content :deep(h2) { font-size: 1.3rem; margin: 2.4rem 0 1rem; }
  .wp-content :deep(h3) { font-size: 1.08rem; }
  .wp-content :deep(p), .wp-content :deep(li) { font-size: 14.5px; }
  .wp-footer-row { flex-direction: column; align-items: flex-start; }
  .wp-footer-cite { text-align: left; }
}

/* PRINT / PDF prints the page the screen shows, its dark ground and colours included, whatever
   the print dialog's background setting: like the journal and the compliance pages. Only what
   works on a screen alone stays off paper: the reading bar, the scan line, the navigation. */
@media print {
  .wp-page { -webkit-print-color-adjust: exact; print-color-adjust: exact; min-height: 0; padding-bottom: 40px; }
  .wp-scan, .wp-progress, .wp-chrome, .wp-footer-link { display: none !important; }
  .wp-content :deep(h1), .wp-content :deep(h2), .wp-content :deep(h3), .wp-content :deep(h4) { break-after: avoid; }
  .wp-content :deep(pre), .wp-content :deep(table), .wp-content :deep(blockquote), .wp-content :deep(figure),
  .wp-meta-grid, .wp-toc { break-inside: avoid; }
}
</style>
