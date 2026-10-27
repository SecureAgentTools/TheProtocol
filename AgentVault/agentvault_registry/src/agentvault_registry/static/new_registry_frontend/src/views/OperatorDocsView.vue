<script setup lang="ts">
import ProtocolMark from '@/components/ProtocolMark.vue'
import OracleSidebarTOC from '@/components/docs/OracleSidebarTOC.vue'
import OracleCommandPalette from '@/components/docs/OracleCommandPalette.vue'
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import MemberModeNotice from '@/components/docs/MemberModeNotice.vue'
import DocsSwitchNote from '@/components/docs/DocsSwitchNote.vue'
import { useDocSwitches } from '@/composables/docs/useDocSwitches'
import { applySwitchBlocks } from '@/composables/docs/switchBlocks'
import {
  renderDocsMarkdown,
  extractHeadings,
  type DocsHeading,
} from '@/composables/docs/useDocsMarkdown'
import { renderMermaidDiagrams } from '@/composables/docs/useMermaidRenderer'
import {
  buildSearchIndex,
  type DocsSearchResult,
} from '@/composables/docs/useDocsSearchIndex'

const { t } = useI18n()

const route = useRoute()
const router = useRouter()

// Raw markdown imports
import ch00 from '@/assets/docs/operator/00_quickstart.md?raw'
import ch01 from '@/assets/docs/operator/01_architecture.md?raw'
import ch02 from '@/assets/docs/operator/02_configuration.md?raw'
import ch03 from '@/assets/docs/operator/03_federation.md?raw'
import ch04 from '@/assets/docs/operator/04_token_economy.md?raw'
import ch05 from '@/assets/docs/operator/05_api_reference.md?raw'
import ch06 from '@/assets/docs/operator/06_monitoring.md?raw'
import ch07 from '@/assets/docs/operator/07_troubleshooting.md?raw'
import ch08 from '@/assets/docs/operator/08_security.md?raw'
import ch09 from '@/assets/docs/operator/09_governance.md?raw'
import ch10 from '@/assets/docs/operator/10_compliance.md?raw'
import ch11 from '@/assets/docs/operator/11_sovereign_frames.md?raw'
import ch12 from '@/assets/docs/operator/12_host_cli.md?raw'
import ch13 from '@/assets/docs/operator/13_ai_assistants.md?raw'
import ch14 from '@/assets/docs/operator/14_setup_manual.md?raw'
import ch15 from '@/assets/docs/operator/15_frame_federation.md?raw'
import ch16 from '@/assets/docs/operator/16_updates.md?raw'
import ch17 from '@/assets/docs/operator/17_legal_for_operators.md?raw'
import ch18 from '@/assets/docs/operator/18_canaries.md?raw'
import ch19 from '@/assets/docs/operator/19_market_simulation.md?raw'
import ch20 from '@/assets/docs/operator/20_test_verified_development.md?raw'
import ch21 from '@/assets/docs/operator/21_ai_operations_brief.md?raw'
import ch22 from '@/assets/docs/operator/22_suspension.md?raw'

interface Chapter {
  id: string
  number: string
  title: string
  subtitle: string
  content: string
  readingTime: number
}

function estimateReadingTime(text: string): number {
  return Math.max(1, Math.ceil(text.split(/\s+/).filter(Boolean).length / 200))
}

const chapters: Chapter[] = [
  { id: '00', number: '00', title: 'Quickstart', subtitle: 'Your Own Registry, a Frame, or an Operator Under One', content: ch00, readingTime: estimateReadingTime(ch00) },
  { id: '01', number: '01', title: 'Architecture', subtitle: 'Container Topology', content: ch01, readingTime: estimateReadingTime(ch01) },
  { id: '02', number: '02', title: 'Configuration', subtitle: 'Environment Variables & Secrets', content: ch02, readingTime: estimateReadingTime(ch02) },
  { id: '03', number: '03', title: 'Federation', subtitle: 'Joining a Frame, Card Sync, Transfers', content: ch03, readingTime: estimateReadingTime(ch03) },
  { id: '04', number: '04', title: 'Units & Fees', subtitle: 'Units, Fees, Locks, Disputes', content: ch04, readingTime: estimateReadingTime(ch04) },
  { id: '05', number: '05', title: 'API Reference', subtitle: 'Endpoints, Auth, Examples', content: ch05, readingTime: estimateReadingTime(ch05) },
  { id: '06', number: '06', title: 'Monitoring', subtitle: 'Prometheus, Grafana, Alerts', content: ch06, readingTime: estimateReadingTime(ch06) },
  { id: '07', number: '07', title: 'Troubleshooting', subtitle: 'Common Issues & Docker Commands', content: ch07, readingTime: estimateReadingTime(ch07) },
  { id: '08', number: '08', title: 'Security', subtitle: 'mTLS, SPIRE, Licences, Incidents', content: ch08, readingTime: estimateReadingTime(ch08) },
  { id: '09', number: '09', title: 'Governance', subtitle: 'Local Votes, Federation Ballots, Veto', content: ch09, readingTime: estimateReadingTime(ch09) },
  { id: '10', number: '10', title: 'Compliance', subtitle: 'ISO 42001, Supply Audit, GDPR', content: ch10, readingTime: estimateReadingTime(ch10) },
  { id: '11', number: '11', title: 'Sovereign Frames', subtitle: 'Frames, Bridges & Cross-Frame FX (Preview)', content: ch11, readingTime: estimateReadingTime(ch11) },
  { id: '12', number: '12', title: 'Host CLI', subtitle: 'Day-2 Ops: Status, Backups, Updates, SPIRE', content: ch12, readingTime: estimateReadingTime(ch12) },
  { id: '13', number: '13', title: 'AI Assistants & MCP', subtitle: 'Bridges, the Served Manual, Tool Catalog', content: ch13, readingTime: estimateReadingTime(ch13) },
  { id: '14', number: '14', title: 'Setup Manual', subtitle: 'Standalone and Federated, Step by Step', content: ch14, readingTime: estimateReadingTime(ch14) },
  { id: '15', number: '15', title: 'Frame Federation', subtitle: 'Federating a Frame, Call by Call', content: ch15, readingTime: estimateReadingTime(ch15) },
  { id: '16', number: '16', title: 'Releases & Updates', subtitle: 'Images, the Release Channel, Updates', content: ch16, readingTime: estimateReadingTime(ch16) },
  { id: '17', number: '17', title: 'Legal Pages', subtitle: 'The Legal Pages on a Frame You Run', content: ch17, readingTime: estimateReadingTime(ch17) },
  { id: '18', number: '18', title: 'Canaries', subtitle: 'Synthetic Transfers on Your Frame', content: ch18, readingTime: estimateReadingTime(ch18) },
  { id: '19', number: '19', title: 'Market Simulation', subtitle: 'The Simulation on Your Frame', content: ch19, readingTime: estimateReadingTime(ch19) },
  { id: '20', number: '20', title: 'Test-Verified Development', subtitle: 'Changing the Code with Proof', content: ch20, readingTime: estimateReadingTime(ch20) },
  { id: '21', number: '21', title: 'AI Operations Brief', subtitle: 'The Briefing for an Operator\'s AI Assistant', content: ch21, readingTime: estimateReadingTime(ch21) },
  { id: '22', number: '22', title: 'Suspension', subtitle: 'Agents and Developers, Every Lever in One Action', content: ch22, readingTime: estimateReadingTime(ch22) },
]

const currentChapterId = computed(() => {
  const param = route.params.section as string
  if (!param) return '00'
  const padded = param.padStart(2, '0')
  return chapters.find(c => c.id === padded) ? padded : '00'
})

const currentChapter = computed(() => chapters.find(c => c.id === currentChapterId.value) || chapters[0])
const currentIndex = computed(() => chapters.findIndex(c => c.id === currentChapterId.value))
const prevChapter = computed(() => currentIndex.value > 0 ? chapters[currentIndex.value - 1] : null)
const nextChapter = computed(() => currentIndex.value < chapters.length - 1 ? chapters[currentIndex.value + 1] : null)

// Chapter menu
const menuOpen = ref(false)

// Reading progress
const readingProgress = ref(0)
const headerScrolled = ref(false)

function onScroll() {
  const scrollTop = window.scrollY
  const docHeight = document.documentElement.scrollHeight - window.innerHeight
  readingProgress.value = docHeight > 0 ? Math.min(100, (scrollTop / docHeight) * 100) : 0
  headerScrolled.value = scrollTop > 80
}

function scrollToHashIfPresent() {
  const hash = window.location.hash.replace(/^#\/operator-docs\/[^#]*/, '').replace(/^#/, '')
  if (!hash) return
  setTimeout(() => {
    const el = document.getElementById(hash)
    if (!el) return
    const y = el.getBoundingClientRect().top + window.scrollY - 90
    window.scrollTo({ top: y, behavior: 'smooth' })
    activeHeadingSlug.value = hash
  }, 120)
}

function onHashChange() {
  scrollToHashIfPresent()
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('keydown', onGlobalKey)
  window.addEventListener('hashchange', onHashChange)
  window.scrollTo(0, 0)
  nextTick(() => initStarfield())
  window.addEventListener('resize', () => {
    if (animFrameId !== null) { cancelAnimationFrame(animFrameId); animFrameId = null }
    initStarfield()
  })
  buildSearchIndex(chapters, 'operator', docSwitches.value)
  updateDocumentTitle()
  renderDiagrams().then(() => {
    augmentHeadingsWithAnchors()
    rebuildScrollspy()
    scrollToHashIfPresent()
  })
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('keydown', onGlobalKey)
  window.removeEventListener('hashchange', onHashChange)
  if (animFrameId !== null) { cancelAnimationFrame(animFrameId); animFrameId = null }
  scrollspyObserver?.disconnect()
  scrollspyObserver = null
  if (toastTimeoutId !== null) window.clearTimeout(toastTimeoutId)
})

function navigateToChapter(id: string) {
  menuOpen.value = false
  router.push(`/operator-docs/${id}`)
}

function exitDocs() {
  router.push('/operator')
}

watch(currentChapterId, () => {
  nextTick(() => {
    window.scrollTo(0, 0)
    readingProgress.value = 0
    updateDocumentTitle()
    renderDiagrams().then(() => {
      augmentHeadingsWithAnchors()
      rebuildScrollspy()
      scrollToHashIfPresent()
    })
  })
})

function updateDocumentTitle() {
  const ch = currentChapter.value
  if (!ch) return
  document.title = `${ch.title} · Operator Docs · TheProtocol`
}

// ─── Canvas Starfield ───
const starCanvas = ref<HTMLCanvasElement | null>(null)
let animFrameId: number | null = null

function initStarfield() {
  const cv = starCanvas.value
  if (!cv) return
  const ctx = cv.getContext('2d')
  if (!ctx) return

  cv.width = window.innerWidth
  cv.height = window.innerHeight

  const palette = ['#ffffff', '#ccd8ff', '#d0c8ff', '#c8eeff', '#ffe8d0']
  const stars = Array.from({ length: 420 }, () => ({
    x: Math.random() * cv.width,
    y: Math.random() * cv.height,
    r: Math.random() < 0.12 ? Math.random() * 1.5 + 0.9 : Math.random() * 0.65 + 0.15,
    alpha: Math.random() * 0.55 + 0.22,
    speed: Math.random() * 0.022 + 0.004,
    phase: Math.random() * Math.PI * 2,
    color: palette[Math.floor(Math.random() * palette.length)]
  }))

  type NebDef = { x: number; y: number; r: number; rgb: string; a: number }
  const nebulae: NebDef[] = [
    { x: 0.12, y: 0.22, r: 0.28, rgb: '59,90,240', a: 0.045 },
    { x: 0.80, y: 0.55, r: 0.25, rgb: '120,70,240', a: 0.040 },
    { x: 0.48, y: 0.90, r: 0.32, rgb: '16,140,100', a: 0.028 },
    { x: 0.65, y: 0.10, r: 0.20, rgb: '90,50,200', a: 0.025 },
    { x: 0.32, y: 0.68, r: 0.22, rgb: '40,100,210', a: 0.030 },
    { x: 0.90, y: 0.30, r: 0.18, rgb: '200,60,120', a: 0.018 },
  ]

  type GalDef = { x: number; y: number; rx: number; ry: number; angle: number; alpha: number }
  const galaxies: GalDef[] = [
    { x: 0.28, y: 0.35, rx: 0.022, ry: 0.006, angle: 0.4, alpha: 0.07 },
    { x: 0.72, y: 0.18, rx: 0.018, ry: 0.005, angle: -0.7, alpha: 0.06 },
    { x: 0.88, y: 0.72, rx: 0.024, ry: 0.007, angle: 0.3, alpha: 0.05 },
    { x: 0.14, y: 0.80, rx: 0.015, ry: 0.004, angle: 1.1, alpha: 0.05 },
    { x: 0.55, y: 0.48, rx: 0.019, ry: 0.005, angle: -0.3, alpha: 0.04 },
  ]

  let frame = 0

  function draw() {
    if (!cv) return
    if (!ctx) return
    const w = cv.width, h = cv.height
    const diag = Math.sqrt(w * w + h * h)
    ctx.clearRect(0, 0, w, h)

    // Nebulae
    for (const n of nebulae) {
      const px = n.x * w, py = n.y * h, pr = n.r * diag
      const grad = ctx.createRadialGradient(px, py, 0, px, py, pr)
      grad.addColorStop(0, `rgba(${n.rgb}, ${n.a})`)
      grad.addColorStop(0.55, `rgba(${n.rgb}, ${n.a * 0.3})`)
      grad.addColorStop(1, 'transparent')
      ctx.fillStyle = grad
      ctx.fillRect(0, 0, w, h)
    }

    // Distant galaxies
    for (const g of galaxies) {
      const px = g.x * w, py = g.y * h
      const prx = g.rx * w, pry = g.ry * h
      ctx.save()
      ctx.translate(px, py)
      ctx.rotate(g.angle)
      ctx.scale(1, pry / prx)
      const gg = ctx.createRadialGradient(0, 0, 0, 0, 0, prx)
      gg.addColorStop(0, `rgba(210, 190, 255, ${g.alpha})`)
      gg.addColorStop(0.45, `rgba(165, 130, 245, ${g.alpha * 0.5})`)
      gg.addColorStop(1, 'transparent')
      ctx.shadowBlur = 14
      ctx.shadowColor = 'rgba(140, 100, 255, 0.5)'
      ctx.fillStyle = gg
      ctx.beginPath()
      ctx.arc(0, 0, prx, 0, Math.PI * 2)
      ctx.fill()
      ctx.shadowBlur = 0
      ctx.restore()
    }

    // Stars
    for (const s of stars) {
      const twinkle = 0.58 + Math.sin(frame * s.speed + s.phase) * 0.42
      ctx.globalAlpha = s.alpha * twinkle
      if (s.r > 0.9) {
        ctx.shadowBlur = s.r * 7
        ctx.shadowColor = s.color
      }
      ctx.fillStyle = s.color
      ctx.beginPath()
      ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
      ctx.fill()
      if (s.r > 0.9) ctx.shadowBlur = 0
    }
    ctx.globalAlpha = 1
    frame++
    animFrameId = requestAnimationFrame(draw)
  }

  draw()
}

// Rendered markdown — the shared docs renderer (§OPDOCS): heading ids + anchor
// targets, code-copy buttons, callouts, mermaid fences. Same pipeline as the
// Oracle, emitted under the opd- class prefix this view already styles.
// §FESUITE V0595: a chapter's parts that apply only where a switch is on show only where this registry says it is on
// (composables/docs/switchBlocks.ts); the note says what was left out, and search and the headings follow the same text
const { known: docSwitches, loaded: docSwitchesLoaded } = useDocSwitches()
const gatedChapter = computed(() => applySwitchBlocks(currentChapter.value.content, docSwitches.value))
const renderedContent = computed(() =>
  renderDocsMarkdown(gatedChapter.value.text, {
    classPrefix: 'opd',
    headingAnchors: true,
  })
)

const currentHeadings = computed<DocsHeading[]>(() =>
  extractHeadings(gatedChapter.value.text)
)

// the switches can answer after the chapter painted: its parts then appear in place, and the diagrams, the heading
// anchors and the scrollspy follow the new body (a new chapter is the chapter watcher's)
watch(() => [currentChapterId.value, gatedChapter.value.text] as const, ([id], [was]) => {
  if (id !== was) return
  nextTick(() => renderDiagrams().then(() => { augmentHeadingsWithAnchors(); rebuildScrollspy() }))
})
watch(docSwitches, (k) => buildSearchIndex(chapters, 'operator', k))

// Render any mermaid fences in the freshly-injected article (oracle glass theme).
async function renderDiagrams() {
  await nextTick()
  await renderMermaidDiagrams({ selector: '.opd-article .opd-mermaid', theme: 'oracle' })
}

// ─── Scrollspy: active heading tracking via IntersectionObserver ───
const activeHeadingSlug = ref<string | null>(null)
let scrollspyObserver: IntersectionObserver | null = null
let scrollspyIgnoreUntil = 0
const visibleSlugs = new Set<string>()

function rebuildScrollspy() {
  scrollspyObserver?.disconnect()
  visibleSlugs.clear()
  activeHeadingSlug.value = null
  const headings = document.querySelectorAll(
    '.opd-article h2[id], .opd-article h3[id]'
  )
  if (headings.length === 0) return
  scrollspyObserver = new IntersectionObserver(
    (entries) => {
      if (performance.now() < scrollspyIgnoreUntil) return
      for (const entry of entries) {
        const id = (entry.target as HTMLElement).id
        if (!id) continue
        if (entry.isIntersecting) visibleSlugs.add(id)
        else visibleSlugs.delete(id)
      }
      if (visibleSlugs.size === 0) return
      const ordered = Array.from(headings)
        .map((el) => (el as HTMLElement).id)
        .filter((id) => visibleSlugs.has(id))
      if (ordered.length > 0) activeHeadingSlug.value = ordered[0]
    },
    {
      rootMargin: '-100px 0px -55% 0px',
      threshold: [0, 1],
    }
  )
  headings.forEach((el) => scrollspyObserver!.observe(el))
}

function jumpToSlug(slug: string) {
  const el = document.getElementById(slug)
  if (!el) return
  scrollspyIgnoreUntil = performance.now() + 600
  activeHeadingSlug.value = slug
  const y = el.getBoundingClientRect().top + window.scrollY - 100
  window.scrollTo({ top: y, behavior: 'smooth' })
  const basePath = `/operator-docs/${currentChapterId.value}`
  history.replaceState(null, '', `#${basePath}#${slug}`)
  menuOpen.value = false
}

function copyHeadingLink(slug: string): Promise<void> {
  const base = window.location.origin + window.location.pathname
  const url = `${base}#/operator-docs/${currentChapterId.value}#${slug}`
  return navigator.clipboard.writeText(url)
}

const toastMessage = ref<string>('')
let toastTimeoutId: number | null = null
function showToast(message: string) {
  toastMessage.value = message
  if (toastTimeoutId !== null) window.clearTimeout(toastTimeoutId)
  toastTimeoutId = window.setTimeout(() => {
    toastMessage.value = ''
    toastTimeoutId = null
  }, 2200)
}

// ─── Expandable Mermaid (click any diagram to enlarge) ───
const expandedMermaidHTML = ref<string>('')

function openMermaidLightbox(el: HTMLElement) {
  if (el.getAttribute('data-processed') !== 'true') return
  expandedMermaidHTML.value = el.innerHTML
  document.body.style.overflow = 'hidden'
}

function closeMermaidLightbox() {
  expandedMermaidHTML.value = ''
  document.body.style.overflow = ''
}

function onArticleClick(event: MouseEvent) {
  const target = event.target as HTMLElement

  // Mermaid diagram — open in full-screen overlay
  const mermaidEl = target.closest('.opd-mermaid') as HTMLElement | null
  if (mermaidEl && !target.closest('a')) {
    event.preventDefault()
    openMermaidLightbox(mermaidEl)
    return
  }

  // Heading anchor (¶) — copy section link
  if (target.classList.contains('opd-heading-anchor')) {
    event.preventDefault()
    const slug = target.getAttribute('data-slug')
    if (!slug) return
    copyHeadingLink(slug)
      .then(() => showToast(t('oracleView.toast.linkCopied')))
      .catch(() => showToast(t('oracleView.toast.copyFailed')))
    return
  }

  // Code block copy button
  if (target.getAttribute('data-action') === 'copy-code') {
    event.preventDefault()
    const wrap = target.closest('.opd-code-wrap')
    const codeEl = wrap?.querySelector('pre.opd-code code') as HTMLElement | null
    if (!codeEl) return
    const text = codeEl.textContent || ''
    navigator.clipboard
      .writeText(text)
      .then(() => {
        showToast(t('oracleView.toast.codeCopied'))
        target.classList.add('opd-code-copy-flash')
        window.setTimeout(() => target.classList.remove('opd-code-copy-flash'), 700)
      })
      .catch(() => showToast(t('oracleView.toast.copyFailed')))
    return
  }

  // Internal doc links — route via Vue Router so the hash-mode SPA does not
  // treat the href as a raw URL. Handles [text](/operator-docs/02) and
  // cross-links into the Oracle, [text](/docs/09).
  const link = target.closest('a') as HTMLAnchorElement | null
  if (link) {
    const href = link.getAttribute('href') || ''
    const own = href.match(/^\/operator-docs\/([0-9]+)(?:#(.+))?$/)
    if (own) {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
      event.preventDefault()
      const targetChapter = own[1].padStart(2, '0')
      const targetSlug = own[2]
      if (targetChapter === currentChapterId.value) {
        if (targetSlug) jumpToSlug(targetSlug)
        else window.scrollTo({ top: 0, behavior: 'smooth' })
        return
      }
      router.push(`/operator-docs/${targetChapter}`).then(() => {
        if (targetSlug) {
          history.replaceState(null, '', `#/operator-docs/${targetChapter}#${targetSlug}`)
        }
      })
      return
    }
    const oracle = href.match(/^\/docs\/([0-9]+)(?:#(.+))?$/)
    if (oracle) {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
      event.preventDefault()
      router.push(`/docs/${oracle[1].padStart(2, '0')}`)
    }
  }
}

// ─── Command palette (⌘K search, namespaced to the operator index) ───
const paletteOpen = ref(false)

const OPERATOR_SEARCH_SUGGESTIONS: string[] = [
  'ai assistant',
  'mail posture',
  'invite codes',
  'federation license',
  'backup',
  'treasury',
  'monitoring',
  'spire',
]

function openPalette() { paletteOpen.value = true }
function closePalette() { paletteOpen.value = false }

function onGlobalKey(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement | null)?.tagName
  const isTyping = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable
  if (e.key === 'Escape' && expandedMermaidHTML.value !== '') {
    e.preventDefault()
    closeMermaidLightbox()
    return
  }
  if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault()
    paletteOpen.value = !paletteOpen.value
    return
  }
  if (e.key === '/' && !isTyping && !paletteOpen.value) {
    e.preventDefault()
    paletteOpen.value = true
  }
}

function onPaletteSelect(r: DocsSearchResult) {
  paletteOpen.value = false
  if (r.chapterId === currentChapterId.value) {
    if (r.headingSlug) nextTick(() => jumpToSlug(r.headingSlug!))
    else window.scrollTo({ top: 0, behavior: 'smooth' })
    return
  }
  const base = `/operator-docs/${r.chapterId}`
  if (r.headingSlug) {
    router.push(base).then(() => {
      history.replaceState(null, '', `#${base}#${r.headingSlug}`)
    })
  } else {
    router.push(base)
  }
}

function augmentHeadingsWithAnchors() {
  const headings = document.querySelectorAll(
    '.opd-article h2[id], .opd-article h3[id], .opd-article h4[id]'
  )
  headings.forEach((el) => {
    if (el.querySelector('.opd-heading-anchor')) return
    const id = (el as HTMLElement).id
    if (!id) return
    const a = document.createElement('a')
    a.className = 'opd-heading-anchor'
    a.setAttribute('data-slug', id)
    a.setAttribute('aria-label', t('oracleView.headingAnchor.ariaLabel'))
    a.setAttribute('href', `#${id}`)
    a.textContent = '¶'
    el.appendChild(a)
  })
}
</script>

<template>
  <div class="opd-root">
    <!-- Reading progress bar -->
    <div class="opd-progress">
      <div class="opd-progress-bar" :style="{ width: readingProgress + '%' }"></div>
    </div>

    <!-- Cosmic canvas background -->
    <canvas ref="starCanvas" class="opd-starfield-canvas"></canvas>
    <!-- Deep space vignette -->
    <div class="opd-vignette"></div>

    <!-- Fixed glass nav header -->
    <header :class="['opd-header', { 'opd-header-scrolled': headerScrolled }]">
      <nav class="opd-nav">
        <button type="button" class="opd-logo" @click="exitDocs" :aria-label="t('oracleView.logo.ariaLabel')">
          <span class="opd-logo-mark"><ProtocolMark :size="26" alive /></span>
          <span class="opd-logo-wordmark">THE PROTOCOL</span>
          <span class="opd-logo-divider" aria-hidden="true">/</span>
          <span class="opd-logo-sub">OPERATOR DOCS</span>
        </button>
        <div class="opd-nav-center">
          <span class="opd-chapter-pill">{{ t('operatorDocsView.nav.sectionPill', { current: parseInt(currentChapter.number) + 1, total: chapters.length }) }}</span>
        </div>
        <div class="opd-nav-controls">
          <button class="opd-nav-btn opd-search-btn" @click="openPalette" :aria-label="t('oracleView.nav.searchAriaLabel')">
            <span class="opd-search-icon" aria-hidden="true">⌕</span>
            <span class="opd-search-label">{{ t('oracleView.nav.search') }}</span>
            <kbd class="opd-search-kbd">⌘K</kbd>
          </button>
          <button v-if="prevChapter" class="opd-nav-btn" @click="navigateToChapter(prevChapter.id)">{{ t('operatorDocsView.nav.previous') }}</button>
          <button class="opd-nav-btn" @click="menuOpen = !menuOpen">{{ t('operatorDocsView.nav.chapters') }}</button>
          <button v-if="nextChapter" class="opd-nav-btn" @click="navigateToChapter(nextChapter.id)">{{ t('operatorDocsView.nav.next') }}</button>
          <button class="opd-nav-btn opd-exit-btn" @click="exitDocs">{{ t('operatorDocsView.nav.exitDocs') }}</button>
        </div>
      </nav>
    </header>

    <!-- Chapter menu overlay -->
    <div :class="['opd-menu-overlay', { 'opd-menu-visible': menuOpen }]" @click="menuOpen = false"></div>
    <aside :class="['opd-menu', { 'opd-menu-open': menuOpen }]">
      <div class="opd-menu-header">
        <h2 class="opd-menu-title">{{ t('operatorDocsView.menu.title') }}</h2>
        <button class="opd-menu-close" @click="menuOpen = false">{{ t('operatorDocsView.menu.close') }}</button>
      </div>
      <div class="opd-menu-list">
        <button
          v-for="ch in chapters"
          :key="ch.id"
          @click="navigateToChapter(ch.id)"
          :class="['opd-menu-item', { 'opd-menu-item-active': ch.id === currentChapterId }]"
        >
          <span class="opd-menu-num">{{ ch.number }}</span>
          <div class="opd-menu-info">
            <span class="opd-menu-item-title">{{ ch.title }}</span>
            <span class="opd-menu-item-sub">{{ ch.subtitle }}</span>
          </div>
          <span class="opd-menu-time">{{ t('operatorDocsView.menu.readingTimeMinutes', { n: ch.readingTime }) }}</span>
        </button>
      </div>

      <div v-if="currentHeadings.length > 0" class="opd-menu-section">
        <div class="opd-menu-section-label">{{ t('oracleView.menu.onThisPage') }}</div>
        <div class="opd-menu-toc">
          <button
            v-for="h in currentHeadings.filter((x) => x.level === 2 || x.level === 3)"
            :key="h.slug"
            type="button"
            :class="[
              'opd-menu-toc-item',
              `opd-menu-toc-l${h.level}`,
              { 'opd-menu-toc-active': h.slug === activeHeadingSlug },
            ]"
            @click="jumpToSlug(h.slug)"
          >
            {{ h.text }}
          </button>
        </div>
      </div>
    </aside>

    <!-- Sidebar TOC (desktop only, fixed right) -->
    <OracleSidebarTOC
      :headings="currentHeadings"
      :active-slug="activeHeadingSlug"
      :chapter-number="currentChapter.number"
      :chapter-title="currentChapter.title"
      @jump="jumpToSlug"
    />

    <!-- Mobile floating TOC button -->
    <button
      v-if="currentHeadings.length > 0"
      class="opd-mobile-toc-btn"
      type="button"
      :aria-label="t('oracleView.mobileToc.ariaLabel')"
      @click="menuOpen = true"
    >
      <span class="opd-mobile-toc-icon">☰</span>
      <span class="opd-mobile-toc-label">{{ t('oracleView.mobileToc.label') }}</span>
    </button>

    <!-- Transient toast (heading link copied, etc.) -->
    <div :class="['opd-toast', { 'opd-toast-visible': toastMessage !== '' }]" role="status">
      {{ toastMessage }}
    </div>

    <!-- Expandable mermaid overlay -->
    <div
      v-if="expandedMermaidHTML !== ''"
      class="opd-mermaid-lightbox"
      role="dialog"
      :aria-label="t('oracleView.lightbox.ariaLabel')"
      @click="closeMermaidLightbox"
    >
      <button
        type="button"
        class="opd-mermaid-lightbox-close"
        @click.stop="closeMermaidLightbox"
        :aria-label="t('oracleView.lightbox.closeAriaLabel')"
      >✕</button>
      <div class="opd-mermaid-lightbox-stage" @click.stop v-html="expandedMermaidHTML"></div>
      <div class="opd-mermaid-lightbox-hint">{{ t('oracleView.lightbox.hint') }}</div>
    </div>

    <!-- Command palette (⌘K search, operator namespace) -->
    <OracleCommandPalette
      :open="paletteOpen"
      namespace="operator"
      :suggestions="OPERATOR_SEARCH_SUGGESTIONS"
      @close="closePalette"
      @select="onPaletteSelect"
    />

    <!-- Main content -->
    <div class="opd-content">
      <!-- Chapter hero (full viewport) -->
      <section class="opd-hero" :key="currentChapterId">
        <div class="opd-hero-bg-num">{{ currentChapter.number }}</div>
        <div class="opd-hero-center">
          <h1 class="opd-hero-title" :data-text="currentChapter.title">{{ currentChapter.title }}</h1>
          <p class="opd-hero-subtitle">{{ currentChapter.subtitle }}</p>
        </div>
        <div class="opd-hero-bottom">
          <div class="opd-hero-meta">
            <span class="opd-hero-reading">{{ t('operatorDocsView.hero.minRead', { n: currentChapter.readingTime }) }}</span>
          </div>
          <div class="opd-scroll-hint">
            <span class="opd-scroll-text">{{ t('operatorDocsView.hero.scrollToRead') }}</span>
            <div class="opd-scroll-arrow">
              <div class="opd-scroll-dot"></div>
            </div>
          </div>
        </div>
      </section>

      <!-- Rendered markdown body -->
      <!-- §LANDINGTRUTH (16): chapter 04 (units & fees) describes lock-weight voting -->
      <MemberModeNotice v-if="currentChapterId === '04'" />
      <DocsSwitchNote :left-out="gatedChapter.leftOut" :unread="gatedChapter.unread" :loaded="docSwitchesLoaded" />
      <article class="opd-article" v-html="renderedContent" @click="onArticleClick"></article>

      <!-- Chapter navigation footer -->
      <div class="opd-chapter-nav">
        <button
          v-if="prevChapter"
          @click="navigateToChapter(prevChapter.id)"
          class="opd-chapter-link opd-chapter-prev"
        >
          <span class="opd-chapter-link-label">{{ t('operatorDocsView.chapterNav.previousLabel') }}</span>
          <span class="opd-chapter-link-title">{{ prevChapter.title }}</span>
        </button>
        <div v-else></div>
        <button
          v-if="nextChapter"
          @click="navigateToChapter(nextChapter.id)"
          class="opd-chapter-link opd-chapter-next"
        >
          <span class="opd-chapter-link-label">{{ t('operatorDocsView.chapterNav.nextLabel') }}</span>
          <span class="opd-chapter-link-title">{{ nextChapter.title }}</span>
        </button>
        <div v-else></div>
      </div>

      <!-- Footer -->
      <footer class="opd-footer">
        <p>{{ t('operatorDocsView.footer.copyright') }}</p>
        <p class="opd-footer-sm">{{ t('operatorDocsView.footer.sourceNote') }}</p>
      </footer>
    </div>
  </div>
</template>

<style scoped>
@import url('/fonts/fonts-extra.css'); /* §LEGALKIT: Vite inlines this public file at build time; the font URLs inside it are /static/fonts/, where the registry serves the dist (V0413) */

/* ═══ ROOT & VARIABLES ═══ */
.opd-root {
  --opd-blue: #3B82F6;
  --opd-purple: #8B5CF6;
  --opd-green: #10B981;
  --opd-gold: #F59E0B;
  --opd-gradient: linear-gradient(135deg, #3B82F6 0%, #8B5CF6 50%, #10B981 100%);
  --opd-glass: rgba(15, 15, 20, 0.4);
  --opd-glass-border: rgba(255, 255, 255, 0.1);
  --opd-text: #F8FAFC;
  --opd-text-secondary: #94A3B8;
  --opd-text-muted: #7d8ba0; /* §FESUITE: was #64748B, 4.13-4.32:1 on the docs' surfaces; now 5.1-6.0:1 */

  min-height: 100vh;
  background: #020309;
  color: var(--opd-text);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  overflow-x: hidden;
}

/* ═══ CANVAS STARFIELD ═══ */
.opd-starfield-canvas {
  position: fixed;
  top: 0; left: 0;
  width: 100%; height: 100%;
  z-index: 1;
  pointer-events: none;
  display: block;
}
.opd-vignette {
  position: fixed;
  top: 0; left: 0;
  width: 100%; height: 100%;
  z-index: 2;
  pointer-events: none;
  background:
    radial-gradient(ellipse at 50% 0%, transparent 40%, rgba(2,3,9,0.55) 100%),
    radial-gradient(ellipse at 0% 50%, rgba(2,3,9,0.35) 0%, transparent 60%),
    radial-gradient(ellipse at 100% 50%, rgba(2,3,9,0.35) 0%, transparent 60%),
    radial-gradient(ellipse at 50% 100%, rgba(2,3,9,0.50) 0%, transparent 60%);
}

/* ═══ READING PROGRESS ═══ */
.opd-progress {
  position: fixed;
  top: 0; left: 0;
  width: 100%; height: 4px;
  background: rgba(59,130,246,0.1);
  z-index: 1002;
  pointer-events: none;
}
.opd-progress-bar {
  height: 100%;
  background: var(--opd-gradient);
  transition: width 0.2s ease;
  box-shadow: 0 0 20px rgba(59,130,246,0.6);
}

/* ═══ GLASS HEADER ═══ */
.opd-header {
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 1000;
  background: var(--opd-glass);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid var(--opd-glass-border);
  padding: 1.25rem 2rem;
  transition: all 0.3s ease;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}
.opd-header-scrolled {
  padding: 0.75rem 2rem;
  background: rgba(10,10,10,0.92);
}
.opd-nav {
  max-width: 1600px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.opd-logo {
  font-size: 1.5rem;
  font-weight: 800;
  background: var(--opd-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  cursor: pointer;
  transition: opacity 0.2s;
}
.opd-logo:hover { opacity: 0.8; }
.opd-nav-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}
.opd-chapter-pill {
  font-size: 0.8rem;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--opd-text-secondary);
  padding: 0.4rem 1rem;
  background: rgba(59,130,246,0.1);
  border-radius: 50px;
  border: 1px solid rgba(59,130,246,0.2);
}
.opd-nav-controls { display: flex; gap: 0.75rem; }
.opd-nav-btn {
  background: var(--opd-glass);
  backdrop-filter: blur(10px);
  border: 1px solid var(--opd-glass-border);
  color: var(--opd-text);
  padding: 0.6rem 1.25rem;
  border-radius: 10px;
  cursor: pointer;
  font-weight: 500;
  font-size: 0.85rem;
  font-family: inherit;
  letter-spacing: 0.02em;
  transition: all 0.3s ease;
}
.opd-nav-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(59,130,246,0.25);
  border-color: var(--opd-blue);
  background: rgba(59,130,246,0.15);
}
.opd-exit-btn {
  border-color: rgba(255,255,255,0.08);
  color: var(--opd-text-secondary);
}
.opd-exit-btn:hover {
  border-color: rgba(220,38,38,0.3);
  box-shadow: 0 8px 24px rgba(220,38,38,0.15);
}

/* ═══ CHAPTER MENU (slide from right) ═══ */
.opd-menu-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.5);
  z-index: 998;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.3s ease;
}
.opd-menu-visible { opacity: 1; pointer-events: all; }
.opd-menu {
  position: fixed;
  top: 0;
  right: -420px;
  width: 420px;
  height: 100vh;
  background: rgba(8,8,12,0.95);
  backdrop-filter: blur(20px);
  border-left: 1px solid var(--opd-glass-border);
  z-index: 999;
  transition: right 0.35s cubic-bezier(0.25,0.46,0.45,0.94);
  overflow-y: auto;
  box-shadow: -10px 0 40px rgba(0,0,0,0.6);
}
.opd-menu-open { right: 0; }
.opd-menu-header {
  padding: 2rem;
  border-bottom: 1px solid var(--opd-glass-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.opd-menu-title {
  font-size: 1.5rem;
  font-weight: 800;
  background: var(--opd-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.opd-menu-close {
  background: none;
  border: 1px solid var(--opd-glass-border);
  color: var(--opd-text-secondary);
  width: 36px; height: 36px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1rem;
  transition: all 0.2s;
  font-family: inherit;
}
.opd-menu-close:hover { border-color: var(--opd-blue); color: var(--opd-text); }
.opd-menu-list { padding: 1rem; }
.opd-menu-item {
  display: flex;
  align-items: center;
  gap: 1rem;
  width: 100%;
  padding: 1rem;
  background: none;
  border: 1px solid transparent;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  font-family: inherit;
  color: var(--opd-text-secondary);
  margin-bottom: 4px;
}
.opd-menu-item:hover {
  background: rgba(59,130,246,0.06);
  border-color: rgba(59,130,246,0.15);
  color: var(--opd-text);
}
.opd-menu-item-active {
  background: rgba(59,130,246,0.1) !important;
  border-color: rgba(59,130,246,0.3) !important;
  color: var(--opd-text) !important;
}
.opd-menu-num {
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--opd-blue);
  opacity: 0.5;
  font-variant-numeric: tabular-nums;
  min-width: 1.5rem;
}
.opd-menu-item-active .opd-menu-num { opacity: 1; }
.opd-menu-info { flex: 1; }
.opd-menu-item-title {
  display: block;
  font-size: 0.9rem;
  font-weight: 600;
  margin-bottom: 2px;
}
.opd-menu-item-sub {
  display: block;
  font-size: 0.75rem;
  color: var(--opd-text-muted);
}
.opd-menu-time {
  font-size: 0.7rem;
  color: var(--opd-text-muted);
  white-space: nowrap;
}

/* ═══ CONTENT LAYER ═══ */
.opd-content {
  position: relative;
  z-index: 10;
  isolation: isolate;
}

/* ═══ CHAPTER HERO (full viewport, cinematic) ═══ */
.opd-hero {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: radial-gradient(ellipse at center, rgba(59,130,246,0.09) 0%, rgba(30,20,80,0.04) 50%, transparent 75%);
  padding-top: 80px;
}
.opd-hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(59,130,246,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(59,130,246,0.025) 1px, transparent 1px);
  background-size: 72px 72px;
  mask-image: radial-gradient(ellipse at center, black 30%, transparent 75%);
  -webkit-mask-image: radial-gradient(ellipse at center, black 30%, transparent 75%);
  pointer-events: none;
  z-index: 1;
}
.opd-hero-bg-num {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-size: 30vw;
  font-weight: 900;
  opacity: 0.025;
  color: var(--opd-blue);
  pointer-events: none;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.05em;
  line-height: 1;
}
.opd-hero-center {
  text-align: center;
  z-index: 2;
  max-width: 1100px;
  padding: 0 2rem;
  animation: opd-hero-up 1s ease 0.3s both;
}
@keyframes opd-hero-up {
  from { opacity: 0; transform: translateY(40px); }
  to { opacity: 1; transform: translateY(0); }
}
.opd-hero-title {
  font-size: clamp(3rem, 9vw, 6.5rem);
  font-weight: 900;
  line-height: 1.08;
  letter-spacing: -0.025em;
  margin-bottom: 1.5rem;
  background: var(--opd-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  position: relative;
  display: inline-block;
}
.opd-hero-title::before {
  content: attr(data-text);
  position: absolute;
  left: 0; top: 0;
  z-index: -1;
  background: var(--opd-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  filter: blur(40px);
  opacity: 0.4;
}
.opd-hero-subtitle {
  font-size: clamp(1.1rem, 2.5vw, 1.75rem);
  color: var(--opd-text-secondary);
  font-weight: 300;
  letter-spacing: 0.02em;
  animation: opd-hero-up 1s ease 0.5s both;
}
.opd-hero-bottom {
  position: absolute;
  bottom: 2.5rem;
  left: 0; right: 0;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  padding: 0 2.5rem;
  animation: opd-hero-up 1s ease 0.8s both;
}
.opd-hero-reading {
  font-size: 0.8rem;
  color: var(--opd-text-muted);
  letter-spacing: 0.03em;
}
.opd-scroll-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
}
.opd-scroll-text {
  font-size: 0.65rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--opd-text-muted);
}
.opd-scroll-arrow {
  width: 22px; height: 36px;
  border: 2px solid var(--opd-blue);
  border-radius: 20px;
  position: relative;
  opacity: 0.5;
}
.opd-scroll-dot {
  position: absolute;
  top: 6px; left: 50%;
  width: 4px; height: 6px;
  background: var(--opd-blue);
  border-radius: 2px;
  transform: translateX(-50%);
  animation: opd-scroll-bounce 2s ease-in-out infinite;
}
@keyframes opd-scroll-bounce {
  0%, 100% { transform: translateX(-50%) translateY(0); }
  50% { transform: translateX(-50%) translateY(10px); }
}

/* ═══ ARTICLE (markdown body) ═══ */
.opd-article {
  max-width: 900px;
  margin: 0 auto;
  padding: 5rem 2rem 6rem;
  position: relative;
  z-index: 2;
}

/* Headings */
.opd-article :deep(h1) {
  font-size: clamp(2.25rem, 5vw, 3.25rem);
  font-weight: 800;
  margin: 4rem 0 1.5rem;
  background: var(--opd-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  line-height: 1.2;
  letter-spacing: -0.02em;
  padding-bottom: 0.75rem;
  position: relative;
}
.opd-article :deep(h1)::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0;
  width: 80px; height: 4px;
  background: var(--opd-gradient);
  border-radius: 2px;
}
.opd-article :deep(h2) {
  font-size: clamp(1.75rem, 4vw, 2.25rem);
  font-weight: 700;
  margin: 3.5rem 0 1.25rem;
  color: var(--opd-blue);
  position: relative;
  padding-left: 1.5rem;
}
.opd-article :deep(h2)::before {
  content: '\25C8';
  position: absolute;
  left: 0; top: 50%;
  transform: translateY(-50%);
  color: var(--opd-green);
  font-size: 1rem;
}
.opd-article :deep(h3) {
  font-size: clamp(1.25rem, 3vw, 1.75rem);
  font-weight: 600;
  margin: 2.5rem 0 0.75rem;
  color: var(--opd-purple);
}
.opd-article :deep(h4) {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 2rem 0 0.5rem;
  color: #a78bfa;
}

/* Body text */
.opd-article :deep(p) {
  font-size: 1.1rem;
  line-height: 1.85;
  color: var(--opd-text);
  margin-bottom: 1.5rem;
  font-weight: 400;
  letter-spacing: 0.01em;
}
.opd-article :deep(strong) { color: #fff; font-weight: 600; }
.opd-article :deep(em) { color: var(--opd-text-secondary); }
.opd-article :deep(a) {
  color: var(--opd-blue);
  text-decoration: none;
  border-bottom: 1px solid rgba(59,130,246,0.3);
  transition: border-color 0.2s;
}
.opd-article :deep(a:hover) { border-bottom-color: var(--opd-blue); }

/* Code blocks */
.opd-article :deep(.opd-code) {
  background: var(--opd-glass);
  backdrop-filter: blur(10px);
  border: 1px solid var(--opd-glass-border);
  border-radius: 14px;
  padding: 1.1rem 1.5rem;
  padding-top: 1.8rem;
  margin: 2rem 0;
  overflow-x: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
  position: relative;
}
.opd-article :deep(.opd-code)::before {
  content: 'CODE';
  position: absolute;
  top: 0.75rem; right: 1rem;
  font-size: 0.65rem;
  color: var(--opd-text-muted);
  font-weight: 600;
  letter-spacing: 0.12em;
}
.opd-article :deep(.opd-code code) {
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 0.85rem;
  line-height: 1.4;
  color: var(--opd-text);
  white-space: pre;
  display: block;
}
.opd-article :deep(.opd-ic) {
  background: rgba(59,130,246,0.1);
  border: 1px solid rgba(59,130,246,0.2);
  padding: 0.15rem 0.45rem;
  border-radius: 6px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  color: var(--opd-green);
  font-size: 0.88em;
  font-weight: 500;
  /* a long path breaks where it must instead of running past a phone's edge (the camera, 2026-10-13: up to 142 px) */
  overflow-wrap: anywhere;
}

/* Mermaid diagrams */
.opd-article :deep(.opd-mermaid) {
  margin: 2.5rem 0;
  padding: 1.5rem;
  background: var(--opd-glass);
  border: 1px solid var(--opd-glass-border);
  border-radius: 14px;
  text-align: center;
  overflow-x: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
.opd-article :deep(.opd-mermaid svg) { max-width: 100%; height: auto; }
.opd-article :deep(.opd-mermaid:not([data-processed="true"])) {
  color: transparent;
  min-height: 2rem;
}

/* Tables */
.opd-article :deep(.opd-tbl-wrap) {
  overflow-x: auto;
  margin: 2rem 0;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
.opd-article :deep(table) {
  width: 100%;
  border-collapse: collapse;
  background: var(--opd-glass);
  backdrop-filter: blur(10px);
  font-size: 0.9rem;
}
.opd-article :deep(th) {
  background: rgba(59,130,246,0.1);
  padding: 0.85rem 1.25rem;
  text-align: left;
  font-weight: 600;
  color: var(--opd-blue);
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid rgba(59,130,246,0.2);
  white-space: nowrap;
}
.opd-article :deep(td) {
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--opd-glass-border);
  color: var(--opd-text-secondary);
  vertical-align: top;
}
.opd-article :deep(tr:last-child td) { border-bottom: none; }
.opd-article :deep(tr:hover td) { background: rgba(59,130,246,0.04); }

/* Lists */
.opd-article :deep(ul) {
  list-style: none;
  padding: 0;
  margin: 1.5rem 0;
}
.opd-article :deep(li) {
  position: relative;
  padding: 0.4rem 0 0.4rem 1.75rem;
  font-size: 1.05rem;
  line-height: 1.75;
  color: var(--opd-text);
}
.opd-article :deep(li)::before {
  content: '\25B8';
  position: absolute;
  left: 0;
  color: var(--opd-blue);
  font-weight: 700;
  font-size: 1.15rem;
}
/* Ordered lists */
.opd-article :deep(.opd-ol) {
  list-style: none;
  padding: 0;
  margin: 1.5rem 0;
  counter-reset: opd-counter;
}
.opd-article :deep(.opd-ol-item) {
  position: relative;
  padding: 0.45rem 0 0.45rem 2.5rem;
  font-size: 1.05rem;
  line-height: 1.75;
  color: var(--opd-text);
  counter-increment: opd-counter;
}
.opd-article :deep(.opd-ol-item)::before {
  content: counter(opd-counter);
  position: absolute;
  left: 0;
  top: 0.45rem;
  width: 1.75rem; height: 1.75rem;
  background: rgba(59,130,246,0.1);
  border: 1px solid rgba(59,130,246,0.2);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--opd-blue);
  line-height: 1.75rem;
  text-align: center;
}

/* HR */
.opd-article :deep(hr) {
  border: none;
  height: 1px;
  background: var(--opd-glass-border);
  margin: 3rem 0;
}

/* ═══ CHAPTER NAV FOOTER ═══ */
.opd-chapter-nav {
  max-width: 900px;
  margin: 0 auto;
  padding: 0 2rem 2rem;
  display: flex;
  gap: 1rem;
}
.opd-chapter-link {
  flex: 1;
  padding: 1.5rem;
  background: var(--opd-glass);
  backdrop-filter: blur(10px);
  border: 1px solid var(--opd-glass-border);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.3s ease;
  font-family: inherit;
  text-align: left;
}
.opd-chapter-next { text-align: right; }
.opd-chapter-link:hover {
  border-color: rgba(59,130,246,0.3);
  box-shadow: 0 8px 24px rgba(59,130,246,0.15);
  transform: translateY(-2px);
}
.opd-chapter-link-label {
  display: block;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--opd-blue);
  margin-bottom: 0.4rem;
}
.opd-chapter-link-title {
  display: block;
  font-size: 1rem;
  color: var(--opd-text);
  font-weight: 500;
}

/* ═══ FOOTER ═══ */
.opd-footer {
  text-align: center;
  padding: 3rem 2rem;
  font-size: 0.8rem;
  color: var(--opd-text-muted);
  border-top: 1px solid var(--opd-glass-border);
  max-width: 900px;
  margin: 0 auto;
}
.opd-footer-sm {
  margin-top: 0.4rem;
  font-size: 0.7rem;
  color: var(--opd-text-muted); /* was #334155, 1.98:1 */
  font-style: italic;
}

/* ═══ RESPONSIVE ═══ */
@media (max-width: 768px) {
  .opd-nav-center { display: none; }
  .opd-nav-controls { gap: 0.4rem; }
  .opd-nav-btn { padding: 0.5rem 0.8rem; font-size: 0.75rem; }
  .opd-exit-btn { display: none; }
  .opd-hero-title { font-size: clamp(2.5rem, 8vw, 4rem); }
  .opd-hero-bottom { padding: 0 1.5rem; }
  .opd-article { padding: 3rem 1.5rem 4rem; }
  .opd-menu { width: 100%; right: -100%; }
  .opd-chapter-nav { flex-direction: column; }
}

/* ═══════════════════════════════════════════════════════════════════════════
   §OPDOCS (2026-08-02) — polish parity with the Oracle: branded header, ⌘K
   search, ON THIS PAGE TOC, heading ¶ anchors, code copy, mermaid lightbox.
   Transcribed from OracleView (orc- → opd-) with the operator green accent.
   ═══════════════════════════════════════════════════════════════════════════ */
.opd-logo {
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.25rem 0.4rem 0.25rem 0;
  background: transparent;
  border: none;
  cursor: pointer;
  font-family: inherit;
  transition: opacity 0.2s;
}
.opd-logo:hover { opacity: 0.85; }
.opd-logo-mark { display: inline-flex; align-items: center; justify-content: center; line-height: 0; }
.opd-logo-wordmark {
  font-family: 'Orbitron', 'Inter', sans-serif;
  font-weight: 800;
  font-size: 0.92rem;
  letter-spacing: 0.08em;
  color: #F8FAFC;
  white-space: nowrap;
}
.opd-logo-divider { color: rgba(255, 255, 255, 0.2); font-weight: 300; font-size: 0.9rem; }
.opd-logo-sub {
  font-family: 'Orbitron', 'Inter', sans-serif;
  font-weight: 500;
  font-size: 0.72rem;
  letter-spacing: 0.22em;
  color: #34d399;
  text-shadow: 0 0 8px rgba(16, 185, 129, 0.45);
  white-space: nowrap;
}
.opd-search-btn { display: inline-flex; align-items: center; gap: 0.6rem; padding-right: 0.5rem; }
.opd-search-icon { color: rgba(52, 211, 153, 0.9); font-size: 1rem; line-height: 1; }
.opd-search-label { font-weight: 500; letter-spacing: 0.01em; }
.opd-search-kbd {
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: rgba(148, 163, 184, 0.75);
  padding: 0.18rem 0.4rem;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  line-height: 1;
}

/* Headings host the absolutely-positioned ¶ anchor */
.opd-article :deep(h2),
.opd-article :deep(h3),
.opd-article :deep(h4) { position: relative; }
.opd-article :deep(.opd-heading-anchor) {
  position: absolute;
  left: -1.5rem;
  top: 50%;
  transform: translateY(-50%);
  color: rgba(52, 211, 153, 0.5);
  text-decoration: none;
  border-bottom: none;
  font-weight: 400;
  font-size: 0.9em;
  opacity: 0;
  transition: opacity 0.18s ease, color 0.18s ease, transform 0.18s ease;
  padding: 0 0.4rem;
  cursor: pointer;
}
.opd-article :deep(h2:hover) .opd-heading-anchor,
.opd-article :deep(h3:hover) .opd-heading-anchor,
.opd-article :deep(h4:hover) .opd-heading-anchor { opacity: 0.7; }
.opd-article :deep(.opd-heading-anchor:hover) {
  opacity: 1 !important;
  color: #34d399;
  transform: translateY(-50%) scale(1.15);
  border-bottom: none;
}

/* Code blocks: wrapper + copy button + language label (shared renderer markup) */
.opd-article :deep(.opd-code-wrap) { position: relative; margin: 2rem 0; border-radius: 14px; overflow: hidden; }
.opd-article :deep(.opd-code-wrap .opd-code) { margin: 0; }
.opd-article :deep(.opd-code-copy) {
  position: absolute;
  top: 0.6rem;
  right: 0.7rem;
  z-index: 3;
  font-family: inherit;
  font-size: 0.68rem;
  font-weight: 500;
  letter-spacing: 0.04em;
  padding: 0.3rem 0.65rem;
  background: rgba(20, 24, 36, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  color: rgba(226, 232, 240, 0.8);
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.18s ease, background 0.18s ease, color 0.18s ease;
}
.opd-article :deep(.opd-code-wrap:hover .opd-code-copy),
.opd-article :deep(.opd-code-copy:focus-visible) { opacity: 1; }
/* a device with no hover (a phone) cannot reveal the copy button: show it there */
@media (hover: none) {
  .opd-article :deep(.opd-code-copy) { opacity: 1; }
}
.opd-article :deep(.opd-code-copy:hover) {
  background: rgba(16, 185, 129, 0.18);
  color: #e4ecf4;
  border-color: rgba(16, 185, 129, 0.4);
}
.opd-article :deep(.opd-code-copy-flash) {
  background: rgba(16, 185, 129, 0.28) !important;
  color: #d1fae5 !important;
  border-color: rgba(16, 185, 129, 0.55) !important;
}
.opd-article :deep(.opd-code-lang) {
  position: absolute;
  top: 0.65rem;
  left: 1.1rem;
  font-family: 'JetBrains Mono', 'Fira Code', Consolas, monospace;
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: rgba(148, 163, 184, 0.8);
  pointer-events: none;
  z-index: 2;
}

/* Callouts — :::tip / :::warn / :::info / :::note */
.opd-article :deep(.opd-callout) {
  margin: 2rem 0;
  padding: 1rem 1.25rem 0.85rem;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-left-width: 3px;
  background: rgba(15, 18, 28, 0.5);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.3);
}
.opd-article :deep(.opd-callout-head) { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }
.opd-article :deep(.opd-callout-icon) { width: 14px; height: 14px; border-radius: 50%; flex-shrink: 0; }
.opd-article :deep(.opd-callout-label) { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; }
.opd-article :deep(.opd-callout-body) { color: rgba(226, 232, 240, 0.92); font-size: 1rem; line-height: 1.75; }
.opd-article :deep(.opd-callout-body > p:last-child) { margin-bottom: 0; }
.opd-article :deep(.opd-callout-body > p) { margin-bottom: 0.55rem; font-size: 1rem; line-height: 1.7; }
.opd-article :deep(.opd-callout-tip) { border-left-color: #10B981; background: linear-gradient(90deg, rgba(16, 185, 129, 0.08), rgba(15, 18, 28, 0.5) 45%); }
.opd-article :deep(.opd-callout-tip .opd-callout-icon) { background: radial-gradient(circle at 35% 30%, #34d399, #059669); box-shadow: 0 0 10px rgba(16, 185, 129, 0.55); }
.opd-article :deep(.opd-callout-tip .opd-callout-label) { color: #34d399; }
.opd-article :deep(.opd-callout-warn) { border-left-color: #F59E0B; background: linear-gradient(90deg, rgba(245, 158, 11, 0.1), rgba(15, 18, 28, 0.5) 45%); }
.opd-article :deep(.opd-callout-warn .opd-callout-icon) { background: radial-gradient(circle at 35% 30%, #fbbf24, #d97706); box-shadow: 0 0 10px rgba(245, 158, 11, 0.55); }
.opd-article :deep(.opd-callout-warn .opd-callout-label) { color: #fbbf24; }
.opd-article :deep(.opd-callout-info) { border-left-color: #3B82F6; background: linear-gradient(90deg, rgba(59, 130, 246, 0.08), rgba(15, 18, 28, 0.5) 45%); }
.opd-article :deep(.opd-callout-info .opd-callout-icon) { background: radial-gradient(circle at 35% 30%, #60a5fa, #2563eb); box-shadow: 0 0 10px rgba(59, 130, 246, 0.55); }
.opd-article :deep(.opd-callout-info .opd-callout-label) { color: #60a5fa; }
.opd-article :deep(.opd-callout-note) { border-left-color: #8B5CF6; background: linear-gradient(90deg, rgba(139, 92, 246, 0.08), rgba(15, 18, 28, 0.5) 45%); }
.opd-article :deep(.opd-callout-note .opd-callout-icon) { background: radial-gradient(circle at 35% 30%, #a78bfa, #7c3aed); box-shadow: 0 0 10px rgba(139, 92, 246, 0.55); }
.opd-article :deep(.opd-callout-note .opd-callout-label) { color: #a78bfa; }

/* ═══ "ON THIS PAGE" SECTION IN DRAWER ═══ */
.opd-menu-section { margin-top: 0.5rem; padding: 1rem 0; border-top: 1px solid rgba(255, 255, 255, 0.06); }
.opd-menu-section-label { font-size: 0.62rem; font-weight: 700; letter-spacing: 0.18em; color: rgba(148, 163, 184, 0.75); padding: 0 1.5rem 0.75rem; }
.opd-menu-toc { display: flex; flex-direction: column; gap: 1px; padding: 0 0.75rem; }
.opd-menu-toc-item {
  background: transparent;
  border: none;
  padding: 0.42rem 0.75rem;
  border-radius: 6px;
  color: rgba(148, 163, 184, 0.85);
  font-family: inherit;
  font-size: 0.82rem;
  text-align: left;
  cursor: pointer;
  transition: color 0.18s ease, background 0.18s ease;
  line-height: 1.35;
}
.opd-menu-toc-item:hover { background: rgba(16, 185, 129, 0.08); color: #e4ecf4; }
.opd-menu-toc-l3 { padding-left: 1.5rem; font-size: 0.78rem; color: rgba(148, 163, 184, 0.7); }
.opd-menu-toc-active {
  background: rgba(16, 185, 129, 0.15) !important;
  color: #ffffff !important;
  box-shadow: inset 2px 0 0 #34d399;
}

/* ═══ MOBILE "ON THIS PAGE" FLOATING BUTTON ═══ */
.opd-mobile-toc-btn {
  position: fixed;
  right: 1rem;
  bottom: 1rem;
  z-index: 100;
  display: none;
  align-items: center;
  gap: 0.5rem;
  padding: 0.65rem 1rem;
  background: rgba(15, 18, 28, 0.85);
  backdrop-filter: blur(18px) saturate(160%);
  -webkit-backdrop-filter: blur(18px) saturate(160%);
  border: 1px solid rgba(16, 185, 129, 0.35);
  border-radius: 999px;
  color: #e4ecf4;
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.opd-mobile-toc-btn:hover { transform: translateY(-1px); box-shadow: 0 12px 32px rgba(16, 185, 129, 0.25); }
.opd-mobile-toc-icon { font-size: 0.95rem; color: #34d399; }

/* ═══ TOAST ═══ */
.opd-toast {
  position: fixed;
  bottom: 2rem;
  left: 50%;
  transform: translateX(-50%) translateY(40px);
  z-index: 2000;
  padding: 0.7rem 1.25rem;
  background: rgba(15, 18, 28, 0.92);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(16, 185, 129, 0.35);
  border-radius: 10px;
  color: #e4ecf4;
  font-size: 0.85rem;
  letter-spacing: 0.01em;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s ease, transform 0.25s ease;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}
.opd-toast-visible { opacity: 1; transform: translateX(-50%) translateY(0); }

/* ═══ MERMAID LIGHTBOX ═══ */
.opd-mermaid-lightbox {
  position: fixed;
  inset: 0;
  z-index: 10002;
  background: rgba(6, 8, 16, 0.88);
  backdrop-filter: blur(8px) saturate(120%);
  -webkit-backdrop-filter: blur(8px) saturate(120%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem 2rem;
}
.opd-mermaid-lightbox-stage {
  width: min(96vw, 1800px);
  max-height: calc(100vh - 8rem);
  overflow: auto;
  padding: 2rem;
  background: rgba(15, 18, 28, 0.7);
  border: 1px solid rgba(16, 185, 129, 0.4);
  border-radius: 18px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(16, 185, 129, 0.18) inset;
  cursor: default;
}
.opd-mermaid-lightbox-stage svg {
  width: 100% !important;
  height: auto !important;
  max-height: none !important;
  display: block;
  margin: 0 auto;
}
.opd-mermaid-lightbox-close {
  position: absolute;
  top: 1.25rem;
  right: 1.5rem;
  background: rgba(15, 18, 28, 0.85);
  border: 1px solid rgba(16, 185, 129, 0.4);
  color: #e4ecf4;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: 50%;
  cursor: pointer;
  font-size: 1.1rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
  z-index: 1;
}
.opd-mermaid-lightbox-close:hover {
  border-color: rgba(220, 38, 38, 0.55);
  background: rgba(42, 14, 14, 0.85);
  color: #fecaca;
  transform: scale(1.05);
}
.opd-mermaid-lightbox-hint {
  position: absolute;
  bottom: 1rem;
  left: 50%;
  transform: translateX(-50%);
  font-size: 0.78rem;
  letter-spacing: 0.05em;
  color: rgba(180, 188, 200, 0.7);
}

/* ═══ RESPONSIVE (ported breakpoints) ═══ */
@media (max-width: 768px) {
  .opd-search-label { display: none; }
  .opd-search-kbd { display: none; }
  .opd-logo { gap: 0.45rem; }
  .opd-logo-wordmark { font-size: 0.78rem; letter-spacing: 0.06em; }
  .opd-logo-divider, .opd-logo-sub { display: none; }
  .opd-article :deep(.opd-code-wrap),
  .opd-article :deep(.opd-tbl-wrap),
  .opd-article :deep(.opd-mermaid),
  .opd-article :deep(pre) { max-width: 100%; }
  .opd-mobile-toc-btn { display: inline-flex; }
  .opd-article :deep(.opd-heading-anchor) { display: none; }
  .opd-mermaid-lightbox { padding: 3rem 0.5rem 1rem; }
  .opd-mermaid-lightbox-stage { padding: 1rem; width: 100%; }
  .opd-mermaid-lightbox-close { top: 0.75rem; right: 0.75rem; }
}
@media (max-width: 600px) {
  .opd-search-btn, .opd-nav-btn { min-width: 44px; min-height: 44px; padding: 0.6rem 0.85rem; }
  .opd-mobile-toc-btn { right: 0.75rem; bottom: 0.75rem; padding: 0.75rem 1.1rem; font-size: 0.8rem; min-height: 44px; }
}
@media (max-width: 380px) {
  .opd-logo-wordmark { font-size: 0.7rem; }
}
@media (min-width: 769px) {
  .opd-mobile-toc-btn { display: none; }
}

</style>
