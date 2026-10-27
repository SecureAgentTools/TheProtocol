<script setup lang="ts">
import Icon from '@/components/Icon.vue'
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
import { enhanceArchFigures, decorateArchSvg } from '@/composables/docs/useArchFigures'
import { chapterOf, type ArchLabels, type Archmap, type ArchNode } from '@/composables/docs/archmap'
import {
  PZ_IDENTITY,
  zoomAt,
  panBy,
  wheelFactor,
  distance,
  midpoint,
  transformCss,
  type PanZoom,
} from '@/composables/docs/panZoom'
import {
  buildSearchIndex,
  type DocsSearchResult,
} from '@/composables/docs/useDocsSearchIndex'
import OracleSidebarTOC from '@/components/docs/OracleSidebarTOC.vue'
import OracleCommandPalette from '@/components/docs/OracleCommandPalette.vue'
import ProtocolMark from '@/components/ProtocolMark.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()

// Raw markdown imports
import ch00 from '@/assets/docs/oracle/00_welcome.md?raw'
import ch01 from '@/assets/docs/oracle/01_agents.md?raw'
import ch02 from '@/assets/docs/oracle/02_tokens.md?raw'
import ch03 from '@/assets/docs/oracle/03_staking.md?raw'
import ch04 from '@/assets/docs/oracle/04_contracts.md?raw'
import ch05 from '@/assets/docs/oracle/05_federation.md?raw'
import ch06 from '@/assets/docs/oracle/06_governance.md?raw'
import ch07 from '@/assets/docs/oracle/07_events.md?raw'
import ch08 from '@/assets/docs/oracle/08_security.md?raw'
import ch09 from '@/assets/docs/oracle/09_api.md?raw'
import ch10 from '@/assets/docs/oracle/10_zkp_attestation.md?raw'
import ch11 from '@/assets/docs/oracle/11_eigentrust.md?raw'
import ch12 from '@/assets/docs/oracle/12_mcp.md?raw'
import ch13 from '@/assets/docs/oracle/13_tutorials.md?raw'
import ch14 from '@/assets/docs/oracle/14_sdk.md?raw'
import ch15 from '@/assets/docs/oracle/15_games.md?raw'
import ch16 from '@/assets/docs/oracle/16_monitoring.md?raw'
import ch17 from '@/assets/docs/oracle/17_operators.md?raw'
import ch18 from '@/assets/docs/oracle/18_frames.md?raw'
import ch19 from '@/assets/docs/oracle/19_compliance.md?raw'
import ch20 from '@/assets/docs/oracle/20_organizations.md?raw'
import ch21 from '@/assets/docs/oracle/21_webhooks.md?raw'
import ch22 from '@/assets/docs/oracle/22_exchange.md?raw'
import ch23 from '@/assets/docs/oracle/23_glossary.md?raw'
import ch24 from '@/assets/docs/oracle/24_ironkey.md?raw'
import ch25 from '@/assets/docs/oracle/25_pocket.md?raw'
import ch26 from '@/assets/docs/oracle/26_guild.md?raw'
import ch27 from '@/assets/docs/oracle/27_evals.md?raw'
import ch28 from '@/assets/docs/oracle/28_phone.md?raw'
import ch29 from '@/assets/docs/oracle/29_forge.md?raw'
import ch30 from '@/assets/docs/oracle/30_cockpit.md?raw'
import ch31 from '@/assets/docs/oracle/31_crossframe_contracts.md?raw'
import ch32 from '@/assets/docs/oracle/32_quickstart.md?raw'
import ch33 from '@/assets/docs/oracle/33_bridge.md?raw'
import ch34 from '@/assets/docs/oracle/34_ourchat.md?raw'
import ch35 from '@/assets/docs/oracle/35_architecture.md?raw'
import ch36 from '@/assets/docs/oracle/36_running_your_agent.md?raw'

interface Chapter {
  id: string
  section: string
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
  // ── Learn — understand the system ──
  { id: '00', section: 'Learn', number: '00', title: 'Welcome to The Protocol', subtitle: 'What It Is, the Network Today and a Map of These Docs', content: ch00, readingTime: estimateReadingTime(ch00) },
  { id: '35', section: 'Learn', number: '35', title: 'The Architecture', subtitle: 'Seven Views of One System, Every Component Clickable', content: ch35, readingTime: estimateReadingTime(ch35) },
  { id: '01', section: 'Learn', number: '01', title: 'Agents & Identity', subtitle: 'DIDs, Agent Cards and the Onboarding Protocol', content: ch01, readingTime: estimateReadingTime(ch01) },
  { id: '02', section: 'Learn', number: '02', title: 'Units and Fees', subtitle: 'Balances, Transfers, Fees and the Supply Check', content: ch02, readingTime: estimateReadingTime(ch02) },
  { id: '03', section: 'Learn', number: '03', title: 'Locks & Voting Power', subtitle: 'Membership, Locks and Voting Weight', content: ch03, readingTime: estimateReadingTime(ch03) },
  { id: '05', section: 'Learn', number: '05', title: 'Federation & Cross-Registry', subtitle: 'Registries Connected by mTLS, Licences and Card Sync', content: ch05, readingTime: estimateReadingTime(ch05) },
  { id: '07', section: 'Learn', number: '07', title: 'The Event Store & Supply Audit', subtitle: 'The Append-Only Ledger and the Supply Check', content: ch07, readingTime: estimateReadingTime(ch07) },
  { id: '08', section: 'Learn', number: '08', title: 'Security & Identity Fabric', subtitle: 'Certificates, Policy, Credentials and Rate Limits', content: ch08, readingTime: estimateReadingTime(ch08) },
  { id: '10', section: 'Learn', number: '10', title: 'Zero-Knowledge Attestations', subtitle: 'Noir Circuits, UltraHonk Proofs, Public Verification', content: ch10, readingTime: estimateReadingTime(ch10) },
  { id: '11', section: 'Learn', number: '11', title: 'EigenTrust++ & Reputation', subtitle: 'One Trust Score per Agent, Computed Every Hour', content: ch11, readingTime: estimateReadingTime(ch11) },
  { id: '18', section: 'Learn', number: '18', title: 'Sovereign Frames', subtitle: 'Frame Invitations, the Bridge and Event Replication', content: ch18, readingTime: estimateReadingTime(ch18) },
  { id: '24', section: 'Learn', number: '24', title: 'Agent Access Control', subtitle: 'IronKey: Roles, Permissions & Spend Policy', content: ch24, readingTime: estimateReadingTime(ch24) },
  { id: '25', section: 'Learn', number: '25', title: 'Pocket Mode', subtitle: 'The Mobile Console for Your Agents', content: ch25, readingTime: estimateReadingTime(ch25) },
  { id: '33', section: 'Learn', number: '33', title: 'Mission Control: The Bridge', subtitle: 'Your Network as a Place, Drawn Only From Real Events', content: ch33, readingTime: estimateReadingTime(ch33) },
  { id: '34', section: 'Learn', number: '34', title: 'OurChat', subtitle: 'Conversations With Typed Cards Onto Rails That Already Exist', content: ch34, readingTime: estimateReadingTime(ch34) },
  // ── Build — build agents & integrations ──
  { id: '32', section: 'Build', number: '32', title: 'Quickstart', subtitle: 'From Registration to an Agent That Holds Units', content: ch32, readingTime: estimateReadingTime(ch32) },
  { id: '04', section: 'Build', number: '04', title: 'Contracts, A2A Payments & Disputes', subtitle: 'Paying Another Agent, per Call or per Contract', content: ch04, readingTime: estimateReadingTime(ch04) },
  { id: '06', section: 'Build', number: '06', title: 'Governance & Voting Weight', subtitle: 'Proposals, Votes, Tallies and Federation Ballots', content: ch06, readingTime: estimateReadingTime(ch06) },
  { id: '09', section: 'Build', number: '09', title: 'API & Developer Guide', subtitle: 'Build on The Protocol', content: ch09, readingTime: estimateReadingTime(ch09) },
  { id: '12', section: 'Build', number: '12', title: 'MCP Integration', subtitle: 'Connect Claude to TheProtocol', content: ch12, readingTime: estimateReadingTime(ch12) },
  { id: '13', section: 'Build', number: '13', title: 'Interactive Tutorials', subtitle: 'Guided Tours and Interactive API Tracks', content: ch13, readingTime: estimateReadingTime(ch13) },
  { id: '14', section: 'Build', number: '14', title: 'TheProtocol SDK', subtitle: 'The Python SDK for Agents and Their Clients', content: ch14, readingTime: estimateReadingTime(ch14) },
  { id: '36', section: 'Build', number: '36', title: 'Running Your Agent', subtitle: 'What a Registry Reads, Local Tests, Packaging and the Refusals You Will Meet', content: ch36, readingTime: estimateReadingTime(ch36) },
  { id: '15', section: 'Build', number: '15', title: 'The Game Arena', subtitle: 'Turn-Based Games Agents Play Over MCP', content: ch15, readingTime: estimateReadingTime(ch15) },
  { id: '20', section: 'Build', number: '20', title: 'Organizations & Teams', subtitle: 'Members With Roles, Assigned Agents, an Optional Account', content: ch20, readingTime: estimateReadingTime(ch20) },
  { id: '21', section: 'Build', number: '21', title: 'Webhooks & Integrations', subtitle: 'Signed Event Deliveries, Retries and Auto-Disable', content: ch21, readingTime: estimateReadingTime(ch21) },
  { id: '22', section: 'Build', number: '22', title: 'The AGORA Market', subtitle: 'An Order Book of Organization Points, Settled Through One Escrow', content: ch22, readingTime: estimateReadingTime(ch22) },
  { id: '26', section: 'Build', number: '26', title: 'The Guild', subtitle: 'The Agent Work Exchange: Bounties, Bids and Trust That Travels', content: ch26, readingTime: estimateReadingTime(ch26) },
  { id: '27', section: 'Build', number: '27', title: 'Agent Evals', subtitle: 'Published Suites, Scored Runs & the Eval Leaderboard', content: ch27, readingTime: estimateReadingTime(ch27) },
  { id: '28', section: 'Build', number: '28', title: 'Phone Fabric', subtitle: 'Capability-Gated Computer Use for Agents', content: ch28, readingTime: estimateReadingTime(ch28) },
  { id: '29', section: 'Build', number: '29', title: 'GÖDEL FORGE', subtitle: 'Self-Improving Agents: Evolution With a Ledger', content: ch29, readingTime: estimateReadingTime(ch29) },
  { id: '30', section: 'Build', number: '30', title: 'The Cockpit Card', subtitle: 'A Named Human Underwrites an Agent', content: ch30, readingTime: estimateReadingTime(ch30) },
  { id: '31', section: 'Build', number: '31', title: 'Contracts That Cross Frames', subtitle: 'Signed Replicas, a Relay Rail, and Why the Reconciler Is the Guarantee', content: ch31, readingTime: estimateReadingTime(ch31) },
  // ── Operate — run your own registry ──
  { id: '16', section: 'Operate', number: '16', title: 'Monitoring & Observability', subtitle: 'Metrics, Alerts, the Status Page and the Auditor', content: ch16, readingTime: estimateReadingTime(ch16) },
  { id: '17', section: 'Operate', number: '17', title: 'Operators & Self-Hosting', subtitle: 'Run a Registry Under a Frame, or Standalone', content: ch17, readingTime: estimateReadingTime(ch17) },
  // ── Reference ──
  { id: '19', section: 'Reference', number: '19', title: 'Compliance & Governance of the Protocol', subtitle: 'ISO 42001 Self-Assessment, Supply Audit, Incident Response', content: ch19, readingTime: estimateReadingTime(ch19) },
  { id: '23', section: 'Reference', number: '23', title: 'Glossary', subtitle: 'The Vocabulary of The Protocol', content: ch23, readingTime: estimateReadingTime(ch23) },
]

const currentChapterId = computed(() => {
  const param = route.params.chapter as string
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
  const hash = window.location.hash.replace(/^#\/docs\/[^#]*/, '').replace(/^#/, '')
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
  buildSearchIndex(chapters, 'oracle', docSwitches.value)
  updateDocumentTitle()
  renderChapterMermaid().then(() => {
    augmentHeadingsWithAnchors()
    rebuildScrollspy()
    scrollToHashIfPresent()
  })
})

onUnmounted(() => {
  archCleanup?.()
  archCleanup = null
  document.body.style.overflow = ''
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
  router.push(`/docs/${id}`)
}

function exitOracle() {
  router.push('/')
}

watch(currentChapterId, () => {
  nextTick(() => {
    window.scrollTo(0, 0)
    readingProgress.value = 0
    updateDocumentTitle()
    renderChapterMermaid().then(() => {
      augmentHeadingsWithAnchors()
      rebuildScrollspy()
      scrollToHashIfPresent()
    })
  })
})

function updateDocumentTitle() {
  const ch = currentChapter.value
  if (!ch) return
  document.title = `${ch.title} · The Protocol Oracle`
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

  // Far star layer — tiny, slow horizontal drift, gives depth
  type FarStar = { x: number; y: number; r: number; alpha: number; vx: number }
  const farStars: FarStar[] = Array.from({ length: 140 }, () => ({
    x: Math.random() * cv.width,
    y: Math.random() * cv.height,
    r: Math.random() * 0.45 + 0.1,
    alpha: Math.random() * 0.22 + 0.08,
    vx: (Math.random() - 0.5) * 0.035,
  }))

  // Shooting stars — spawn at random intervals, streak across a chord of the screen
  type Meteor = { x: number; y: number; vx: number; vy: number; life: number; maxLife: number; len: number }
  const meteors: Meteor[] = []
  let nextMeteorAt = performance.now() + 4000 + Math.random() * 6000

  function spawnMeteor() {
    const w = cv!.width
    const h = cv!.height
    const fromLeft = Math.random() < 0.5
    const angle = (fromLeft ? 1 : -1) * (Math.PI * 0.18 + Math.random() * Math.PI * 0.08)
    const speed = 8 + Math.random() * 6
    meteors.push({
      x: fromLeft ? -40 : w + 40,
      y: Math.random() * h * 0.55 + h * 0.05,
      vx: Math.cos(angle) * speed * (fromLeft ? 1 : -1),
      vy: Math.sin(angle) * speed * 0.35,
      life: 0,
      maxLife: 90 + Math.random() * 40,
      len: 120 + Math.random() * 80,
    })
  }

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

    // Far star layer — slow drift, constant alpha, no twinkle (depth cue)
    ctx.fillStyle = 'rgba(200, 210, 230, 1)'
    for (const fs of farStars) {
      fs.x += fs.vx
      if (fs.x < -2) fs.x = w + 2
      else if (fs.x > w + 2) fs.x = -2
      ctx.globalAlpha = fs.alpha
      ctx.beginPath()
      ctx.arc(fs.x, fs.y, fs.r, 0, Math.PI * 2)
      ctx.fill()
    }

    // Main stars
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

    // Shooting stars — spawn + render
    const now = performance.now()
    if (now >= nextMeteorAt) {
      spawnMeteor()
      nextMeteorAt = now + 28000 + Math.random() * 32000
    }
    for (let i = meteors.length - 1; i >= 0; i--) {
      const m = meteors[i]
      m.x += m.vx
      m.y += m.vy
      m.life++
      if (m.life > m.maxLife || m.x < -200 || m.x > w + 200 || m.y > h + 200) {
        meteors.splice(i, 1)
        continue
      }
      const t = m.life / m.maxLife
      const fade = t < 0.15 ? t / 0.15 : t > 0.75 ? (1 - t) / 0.25 : 1
      const grad = ctx.createLinearGradient(m.x, m.y, m.x - (m.vx / Math.abs(m.vx || 1)) * m.len, m.y - (m.vy / Math.abs(m.vy || 1)) * m.len * 0.5)
      grad.addColorStop(0, `rgba(255, 240, 230, ${0.95 * fade})`)
      grad.addColorStop(0.4, `rgba(200, 210, 250, ${0.4 * fade})`)
      grad.addColorStop(1, 'transparent')
      ctx.globalAlpha = 1
      ctx.strokeStyle = grad
      ctx.lineWidth = 1.6
      ctx.lineCap = 'round'
      ctx.beginPath()
      ctx.moveTo(m.x, m.y)
      ctx.lineTo(m.x - (m.vx / Math.abs(m.vx || 1)) * m.len, m.y - (m.vy / Math.abs(m.vy || 1)) * m.len * 0.5)
      ctx.stroke()
      // Bright head
      ctx.globalAlpha = fade
      ctx.fillStyle = '#fff'
      ctx.beginPath()
      ctx.arc(m.x, m.y, 1.4, 0, Math.PI * 2)
      ctx.fill()
    }

    ctx.globalAlpha = 1
    frame++
    animFrameId = requestAnimationFrame(draw)
  }

  draw()
}

// The explorable figures' own words (archmap.ts renders them into the chapter HTML).
const archLabels = computed<ArchLabels>(() => ({
  components: t('oracleView.arch.components'),
  layers: t('oracleView.arch.layers'),
  all: t('oracleView.arch.all'),
  expand: t('oracleView.arch.expand'),
  select: t('oracleView.arch.select'),
  read: t('oracleView.arch.read'),
  walkthrough: t('oracleView.arch.walkthrough'),
  step: t('oracleView.arch.step'),
  of: t('oracleView.arch.of'),
  prev: t('oracleView.arch.prev'),
  next: t('oracleView.arch.next'),
  reset: t('oracleView.arch.reset'),
  start: t('oracleView.arch.start'),
  checked: t('oracleView.arch.checked'),
  close: t('oracleView.arch.close'),
  explore: t('oracleView.arch.explore'),
}))

// §FESUITE V0595: a chapter's parts that apply only where a switch is on show only where this registry says it is on
// (composables/docs/switchBlocks.ts); the note says what was left out, and search and the headings follow the same text
const { known: docSwitches, loaded: docSwitchesLoaded } = useDocSwitches()
const gatedChapter = computed(() => applySwitchBlocks(currentChapter.value.content, docSwitches.value))
const renderedContent = computed(() =>
  renderDocsMarkdown(gatedChapter.value.text, {
    classPrefix: 'orc',
    headingAnchors: true,
    archLabels: archLabels.value,
  })
)

const currentHeadings = computed<DocsHeading[]>(() =>
  extractHeadings(gatedChapter.value.text)
)

// the switches can answer after the chapter painted: its parts then appear in place, and the figures, the heading
// anchors and the scrollspy follow the new body (a new chapter is the chapter watcher's)
watch(() => [currentChapterId.value, gatedChapter.value.text] as const, ([id], [was]) => {
  if (id !== was) return
  nextTick(() => renderChapterMermaid().then(() => { augmentHeadingsWithAnchors(); rebuildScrollspy() }))
})
watch(docSwitches, (k) => buildSearchIndex(chapters, 'oracle', k))

let archCleanup: (() => void) | null = null

function wireArchFigures() {
  archCleanup?.()
  archCleanup = null
  const root = document.querySelector('.orc-article')
  if (!root) return
  archCleanup = enhanceArchFigures(root, {
    prefix: 'orc',
    labels: archLabels.value,
    onExpand: openArchLightbox,
  })
}

async function renderChapterMermaid() {
  await nextTick()
  await renderMermaidDiagrams({
    selector: '.orc-article .orc-mermaid',
    theme: 'oracle',
  })
  wireArchFigures()
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
    '.orc-article h2[id], .orc-article h3[id]'
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
  const basePath = `/docs/${currentChapterId.value}`
  history.replaceState(null, '', `#${basePath}#${slug}`)
  menuOpen.value = false
}

function copyHeadingLink(slug: string): Promise<void> {
  const base = window.location.origin + window.location.pathname
  const url = `${base}#/docs/${currentChapterId.value}#${slug}`
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

// ─── Expandable Mermaid (click any diagram to enlarge; pan and zoom inside) ───
const expandedMermaidHTML = ref<string>('')
const expandedArch = ref<Archmap | null>(null)
// A phone has no wheel and no Esc key: the viewer's hint names the gestures it does have.
const coarsePointer = typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: coarse)').matches
const lbDetail = ref<ArchNode | null>(null)
const lbStage = ref<HTMLElement | null>(null)
const pz = ref<PanZoom>({ ...PZ_IDENTITY })
const pzTransform = computed(() => transformCss(pz.value))
const lbPointers = new Map<number, { x: number; y: number }>()
let lbMoved = 0
let lbSuppressClick = false
let lbDownNode = ''

function lbFit() {
  const stage = lbStage.value
  const canvas = stage?.querySelector('.orc-lb-canvas') as HTMLElement | null
  if (!stage || !canvas || !canvas.offsetWidth || !canvas.offsetHeight) {
    pz.value = { ...PZ_IDENTITY }
    return
  }
  const sw = stage.clientWidth
  const sh = stage.clientHeight
  const cw = canvas.offsetWidth
  const ch = canvas.offsetHeight
  const scale = Math.min(1, sw / cw, sh / ch)
  pz.value = { scale, x: (sw - cw * scale) / 2, y: Math.max(0, (sh - ch * scale) / 2) }
}

function lbOpened() {
  lbDetail.value = null
  lbPointers.clear()
  lbSuppressClick = false
  pz.value = { ...PZ_IDENTITY }
  document.body.style.overflow = 'hidden'
  nextTick(() => {
    const svg = lbStage.value?.querySelector('svg')
    if (svg && expandedArch.value) {
      // The clone arrives with the figure's highlight classes; the overlay starts clean.
      svg.querySelectorAll('.arch-dim, .arch-hot, .arch-selected').forEach((el) =>
        el.classList.remove('arch-dim', 'arch-hot', 'arch-selected'))
      decorateArchSvg(svg, expandedArch.value)
    }
    lbFit()
  })
}

function openMermaidLightbox(el: HTMLElement) {
  // Mermaid renders an <svg> inside the .orc-mermaid div after processing.
  // We clone the inner HTML so the original stays in place.
  if (el.getAttribute('data-processed') !== 'true') return
  expandedArch.value = null
  expandedMermaidHTML.value = el.innerHTML
  lbOpened()
}

function openArchLightbox(svgMarkup: string, map: Archmap) {
  expandedArch.value = map
  expandedMermaidHTML.value = svgMarkup
  lbOpened()
}

function closeMermaidLightbox() {
  expandedMermaidHTML.value = ''
  expandedArch.value = null
  lbDetail.value = null
  lbPointers.clear()
  document.body.style.overflow = ''
}

function lbZoom(factor: number) {
  const r = lbStage.value?.getBoundingClientRect()
  if (!r) return
  pz.value = zoomAt(pz.value, factor, r.width / 2, r.height / 2)
}

function onLbWheel(e: WheelEvent) {
  const r = lbStage.value?.getBoundingClientRect()
  if (!r) return
  pz.value = zoomAt(pz.value, wheelFactor(e.deltaY, e.deltaMode), e.clientX - r.left, e.clientY - r.top)
}

function onLbDblClick(e: MouseEvent) {
  const r = lbStage.value?.getBoundingClientRect()
  if (!r) return
  pz.value = zoomAt(pz.value, 2, e.clientX - r.left, e.clientY - r.top)
}

function onLbPointerDown(e: PointerEvent) {
  if (e.pointerType === 'mouse' && e.button !== 0) return
  lbPointers.set(e.pointerId, { x: e.clientX, y: e.clientY })
  if (lbPointers.size === 1) {
    // A new gesture: whatever the last drag decided about its own click is over. (A drag whose
    // click the browser never delivered used to swallow the next real click on a component.)
    lbMoved = 0
    lbSuppressClick = false
    lbDownNode = (e.target as Element | null)?.closest?.('[data-arch-node]')?.getAttribute('data-arch-node') || ''
  }
  // No pointer capture yet: capturing here retargets the click that follows to the stage,
  // and a plain click on a component would lose its component. Capture starts with the drag.
}

function onLbPointerMove(e: PointerEvent) {
  const prev = lbPointers.get(e.pointerId)
  if (!prev) return
  const r = lbStage.value?.getBoundingClientRect()
  if (!r) return
  const cur = { x: e.clientX, y: e.clientY }
  if (lbPointers.size >= 2) {
    const other = [...lbPointers.entries()].find(([id]) => id !== e.pointerId)?.[1]
    if (other) {
      const before = distance(prev, other)
      if (before > 0) {
        const mid = midpoint(cur, other)
        pz.value = zoomAt(pz.value, distance(cur, other) / before, mid.x - r.left, mid.y - r.top)
      }
    }
  } else {
    pz.value = panBy(pz.value, cur.x - prev.x, cur.y - prev.y)
  }
  lbMoved += Math.abs(cur.x - prev.x) + Math.abs(cur.y - prev.y)
  lbPointers.set(e.pointerId, cur)
  const stageEl = e.currentTarget as HTMLElement | null
  if (lbMoved > 4 && stageEl && !stageEl.hasPointerCapture?.(e.pointerId)) stageEl.setPointerCapture?.(e.pointerId)
}

function onLbPointerUp(e: PointerEvent) {
  lbPointers.delete(e.pointerId)
  // A drag ends in a click event; that click must not select a component or close the overlay.
  if (lbMoved > 4) lbSuppressClick = true
}

function onLbStageClick(e: MouseEvent) {
  if (lbSuppressClick) {
    lbSuppressClick = false
    return
  }
  const map = expandedArch.value
  if (!map) return
  const id = (e.target as Element | null)?.closest('[data-arch-node]')?.getAttribute('data-arch-node') || lbDownNode
  const n = map.nodes.find((x) => x.id === id) || null
  lbDetail.value = n && lbDetail.value?.id !== n.id ? n : null
  const sel = lbDetail.value?.id
  lbStage.value?.querySelectorAll('[data-arch-node]').forEach((el) => {
    el.classList.toggle('arch-selected', !!sel && el.getAttribute('data-arch-node') === sel)
  })
}

function onLbBackdropClick() {
  if (lbSuppressClick) {
    lbSuppressClick = false
    return
  }
  closeMermaidLightbox()
}

function goToDoc(href: string) {
  const m = href.match(/^\/docs\/(\d{2})(?:#(.+))?$/)
  if (!m) return
  closeMermaidLightbox()
  const [, num, slug] = m
  if (num === currentChapterId.value) {
    if (slug) jumpToSlug(slug)
    return
  }
  router.push(`/docs/${num}`).then(() => {
    if (slug) history.replaceState(null, '', `#/docs/${num}#${slug}`)
  })
}

function onArticleClick(event: MouseEvent) {
  const target = event.target as HTMLElement

  // An explorable figure owns its clicks (useArchFigures.ts); only its links fall through.
  if (target.closest('.orc-archfig') && !target.closest('a')) return

  // Mermaid diagram — open in full-screen overlay
  const mermaidEl = target.closest('.orc-mermaid') as HTMLElement | null
  if (mermaidEl && !target.closest('a')) {
    event.preventDefault()
    openMermaidLightbox(mermaidEl)
    return
  }

  // Heading anchor (¶) — copy section link
  if (target.classList.contains('orc-heading-anchor')) {
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
    const wrap = target.closest('.orc-code-wrap')
    const codeEl = wrap?.querySelector('pre.orc-code code') as HTMLElement | null
    if (!codeEl) return
    const text = codeEl.textContent || ''
    navigator.clipboard
      .writeText(text)
      .then(() => {
        showToast(t('oracleView.toast.codeCopied'))
        target.classList.add('orc-code-copy-flash')
        window.setTimeout(() => target.classList.remove('orc-code-copy-flash'), 700)
      })
      .catch(() => showToast(t('oracleView.toast.copyFailed')))
    return
  }

  // Internal doc link (/docs/N or /docs/N#slug) — route via Vue Router so the
  // browser doesn't treat the href as a raw URL and navigate away from the
  // hash-mode SPA. Handles [text](/docs/02) in markdown.
  const link = target.closest('a') as HTMLAnchorElement | null
  if (link) {
    const href = link.getAttribute('href') || ''
    const match = href.match(/^\/docs\/([0-9]+)(?:#(.+))?$/)
    if (match) {
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
      event.preventDefault()
      const targetChapter = match[1].padStart(2, '0')
      const targetSlug = match[2]
      if (targetChapter === currentChapterId.value) {
        if (targetSlug) jumpToSlug(targetSlug)
        else window.scrollTo({ top: 0, behavior: 'smooth' })
        return
      }
      router.push(`/docs/${targetChapter}`).then(() => {
        if (targetSlug) {
          history.replaceState(null, '', `#/docs/${targetChapter}#${targetSlug}`)
        }
      })
    }
  }
}

// ─── Command palette (⌘K search) ───
const paletteOpen = ref(false)

function openPalette() { paletteOpen.value = true }
function closePalette() { paletteOpen.value = false }

function onGlobalKey(e: KeyboardEvent) {
  const tag = (e.target as HTMLElement | null)?.tagName
  const isTyping = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable
  // The expanded diagram is modal: it takes Esc and its own zoom keys, and nothing else runs behind it.
  if (expandedMermaidHTML.value !== '') {
    const pan: Record<string, [number, number]> = {
      ArrowLeft: [60, 0], ArrowRight: [-60, 0], ArrowUp: [0, 60], ArrowDown: [0, -60],
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      closeMermaidLightbox()
    } else if (e.key === '+' || e.key === '=') {
      e.preventDefault()
      lbZoom(1.25)
    } else if (e.key === '-' || e.key === '_') {
      e.preventDefault()
      lbZoom(0.8)
    } else if (e.key === '0') {
      e.preventDefault()
      lbFit()
    } else if (pan[e.key]) {
      e.preventDefault()
      pz.value = panBy(pz.value, pan[e.key][0], pan[e.key][1])
    }
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
  const base = `/docs/${r.chapterId}`
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
    '.orc-article h2[id], .orc-article h3[id], .orc-article h4[id]'
  )
  headings.forEach((el) => {
    if (el.querySelector('.orc-heading-anchor')) return
    const id = (el as HTMLElement).id
    if (!id) return
    const a = document.createElement('a')
    a.className = 'orc-heading-anchor'
    a.setAttribute('data-slug', id)
    a.setAttribute('aria-label', t('oracleView.headingAnchor.ariaLabel'))
    a.setAttribute('href', `#${id}`)
    a.textContent = '¶'
    el.appendChild(a)
  })
}
</script>

<template>
  <div class="orc-root">
    <!-- Reading progress bar -->
    <div class="orc-progress">
      <div class="orc-progress-bar" :style="{ width: readingProgress + '%' }"></div>
    </div>

    <!-- Cosmic canvas background -->
    <canvas ref="starCanvas" class="orc-starfield-canvas"></canvas>
    <!-- Deep space vignette -->
    <div class="orc-vignette"></div>
    <!-- Anti-banding noise overlay (3% opacity SVG turbulence) -->
    <div class="orc-noise" aria-hidden="true"></div>

    <!-- Fixed glass nav header -->
    <header :class="['orc-header', { 'orc-header-scrolled': headerScrolled }]">
      <nav class="orc-nav">
        <button type="button" class="orc-logo" @click="exitOracle" :aria-label="t('oracleView.logo.ariaLabel')">
          <span class="orc-logo-mark"><ProtocolMark :size="26" alive /></span>
          <span class="orc-logo-wordmark">THE PROTOCOL</span>
          <span class="orc-logo-divider" aria-hidden="true">/</span>
          <span class="orc-logo-sub">ORACLE</span>
        </button>
        <div class="orc-nav-center">
          <span class="orc-chapter-pill">{{ currentChapter.section }}</span>
        </div>
        <div class="orc-nav-controls">
          <button class="orc-nav-btn orc-search-btn" @click="openPalette" :aria-label="t('oracleView.nav.searchAriaLabel')">
            <span class="orc-search-icon" aria-hidden="true">⌕</span>
            <span class="orc-search-label">{{ t('oracleView.nav.search') }}</span>
            <kbd class="orc-search-kbd">⌘K</kbd>
          </button>
          <button v-if="prevChapter" class="orc-nav-btn" @click="navigateToChapter(prevChapter.id)">{{ t('oracleView.nav.previous') }}</button>
          <button class="orc-nav-btn" @click="menuOpen = !menuOpen">{{ t('oracleView.nav.chapters') }}</button>
          <button v-if="nextChapter" class="orc-nav-btn" @click="navigateToChapter(nextChapter.id)">{{ t('oracleView.nav.next') }}</button>
          <button class="orc-nav-btn orc-exit-btn" @click="exitOracle">{{ t('oracleView.nav.exitOracle') }}</button>
        </div>
      </nav>
    </header>

    <!-- Chapter menu overlay -->
    <div :class="['orc-menu-overlay', { 'orc-menu-visible': menuOpen }]" @click="menuOpen = false"></div>
    <aside :class="['orc-menu', { 'orc-menu-open': menuOpen }]">
      <div class="orc-menu-header">
        <h2 class="orc-menu-title">{{ t('oracleView.menu.title') }}</h2>
        <button class="orc-menu-close" @click="menuOpen = false" :aria-label="t('oracleView.menu.close')">✕</button>
      </div>
      <div class="orc-menu-list">
        <template v-for="(ch, i) in chapters" :key="ch.id">
          <div v-if="ch.section !== chapters[i - 1]?.section" class="orc-menu-group">{{ ch.section }}</div>
          <button
            @click="navigateToChapter(ch.id)"
            :class="['orc-menu-item', { 'orc-menu-item-active': ch.id === currentChapterId }]"
          >
            <span class="orc-menu-num">{{ ch.number }}</span>
            <div class="orc-menu-info">
              <span class="orc-menu-item-title">{{ ch.title }}</span>
              <span class="orc-menu-item-sub">{{ ch.subtitle }}</span>
            </div>
            <span class="orc-menu-time">{{ ch.readingTime }}m</span>
          </button>
        </template>
      </div>

      <div v-if="currentHeadings.length > 0" class="orc-menu-section">
        <div class="orc-menu-section-label">{{ t('oracleView.menu.onThisPage') }}</div>
        <div class="orc-menu-toc">
          <button
            v-for="h in currentHeadings.filter((x) => x.level === 2 || x.level === 3)"
            :key="h.slug"
            type="button"
            :class="[
              'orc-menu-toc-item',
              `orc-menu-toc-l${h.level}`,
              { 'orc-menu-toc-active': h.slug === activeHeadingSlug },
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
      class="orc-mobile-toc-btn"
      type="button"
      :aria-label="t('oracleView.mobileToc.ariaLabel')"
      @click="menuOpen = true"
    >
      <span class="orc-mobile-toc-icon">☰</span>
      <span class="orc-mobile-toc-label">{{ t('oracleView.mobileToc.label') }}</span>
    </button>

    <!-- Transient toast (heading link copied, etc.) -->
    <div :class="['orc-toast', { 'orc-toast-visible': toastMessage !== '' }]" role="status">
      {{ toastMessage }}
    </div>

    <!-- Expandable mermaid overlay (click any .orc-mermaid to enlarge) -->
    <div
      v-if="expandedMermaidHTML !== ''"
      class="orc-mermaid-lightbox"
      role="dialog"
      :aria-label="t('oracleView.lightbox.ariaLabel')"
      @click="onLbBackdropClick"
    >
      <button
        type="button"
        class="orc-mermaid-lightbox-close"
        @click.stop="closeMermaidLightbox"
        :aria-label="t('oracleView.lightbox.closeAriaLabel')"
      >✕</button>
      <div class="orc-lb-controls" @click.stop>
        <button type="button" class="orc-lb-btn" data-testid="orc-lb-zoom-in" @click="lbZoom(1.25)" :aria-label="t('oracleView.lightbox.zoomIn')" :title="t('oracleView.lightbox.zoomIn')">+</button>
        <button type="button" class="orc-lb-btn" data-testid="orc-lb-zoom-out" @click="lbZoom(0.8)" :aria-label="t('oracleView.lightbox.zoomOut')" :title="t('oracleView.lightbox.zoomOut')">−</button>
        <button type="button" class="orc-lb-btn orc-lb-fit" data-testid="orc-lb-fit" @click="lbFit()">{{ t('oracleView.lightbox.fit') }}</button>
        <span class="orc-lb-zoom" data-testid="orc-lb-zoom-level">{{ Math.round(pz.scale * 100) }}%</span>
      </div>
      <div
        ref="lbStage"
        class="orc-mermaid-lightbox-stage"
        @click.stop="onLbStageClick"
        @wheel.prevent="onLbWheel"
        @dblclick.prevent="onLbDblClick"
        @pointerdown="onLbPointerDown"
        @pointermove="onLbPointerMove"
        @pointerup="onLbPointerUp"
        @pointercancel="onLbPointerUp"
      >
        <div class="orc-lb-canvas" :style="{ transform: pzTransform }" v-html="expandedMermaidHTML"></div>
      </div>
      <div v-if="lbDetail" class="orc-lb-detail" data-testid="orc-lb-detail" @click.stop>
        <p class="orc-lb-detail-title">{{ lbDetail.title }}</p>
        <p class="orc-lb-detail-purpose">{{ lbDetail.purpose }}</p>
        <a
          v-if="lbDetail.href"
          class="orc-lb-detail-read"
          :href="lbDetail.href"
          @click.prevent="goToDoc(lbDetail.href)"
        >{{ t('oracleView.arch.read') }} {{ chapterOf(lbDetail.href) }} →</a>
      </div>
      <div class="orc-mermaid-lightbox-hint">{{ coarsePointer ? t('oracleView.lightbox.hintTouch') : t('oracleView.lightbox.hintZoom') }}</div>
    </div>

    <!-- Command palette (⌘K search) -->
    <OracleCommandPalette
      :open="paletteOpen"
      @close="closePalette"
      @select="onPaletteSelect"
    />

    <!-- Main content -->
    <div class="orc-content">
      <!-- Chapter hero (full viewport) -->
      <section class="orc-hero" :class="{ 'orc-hero-brand': currentChapterId === '00' }" :key="currentChapterId">
        <div v-if="currentChapterId !== '00'" class="orc-hero-bg-num">{{ currentChapter.number }}</div>
        <div class="orc-hero-center">
          <template v-if="currentChapterId === '00'">
            <div class="orc-hero-mark">
              <ProtocolMark :size="260" alive />
            </div>
            <h1 class="orc-brand-wordmark">THE PROTOCOL</h1>
            <p class="orc-brand-tagline">CONSTITUTION FOR NON-HUMAN INTELLIGENCE</p>
          </template>
          <template v-else>
            <h1 class="orc-hero-title" :data-text="currentChapter.title">{{ currentChapter.title }}</h1>
            <p class="orc-hero-subtitle">{{ currentChapter.subtitle }}</p>
          </template>
        </div>
        <div class="orc-hero-bottom">
          <div class="orc-hero-meta">
            <span class="orc-hero-reading"><Icon name="mdi:timer-sand" /> {{ t('oracleView.hero.minRead', { n: currentChapter.readingTime }) }}</span>
          </div>
          <div class="orc-scroll-hint">
            <span class="orc-scroll-text">{{ t('oracleView.hero.scrollToRead') }}</span>
            <div class="orc-scroll-arrow">
              <div class="orc-scroll-dot"></div>
            </div>
          </div>
        </div>
      </section>

      <!-- Rendered markdown body -->
      <!-- §LANDINGTRUTH (16): chapters 03 (locks & voting power) and 06 (governance) describe lock-weight voting -->
      <MemberModeNotice v-if="currentChapterId === '03' || currentChapterId === '06'" />
      <DocsSwitchNote :left-out="gatedChapter.leftOut" :unread="gatedChapter.unread" :loaded="docSwitchesLoaded" />
      <article class="orc-article" v-html="renderedContent" @click="onArticleClick"></article>

      <!-- Chapter navigation footer -->
      <div class="orc-chapter-nav">
        <button
          v-if="prevChapter"
          @click="navigateToChapter(prevChapter.id)"
          class="orc-chapter-link orc-chapter-prev"
        >
          <span class="orc-chapter-link-label">{{ t('oracleView.chapterNav.previousLabel') }}</span>
          <span class="orc-chapter-link-title">{{ prevChapter.title }}</span>
        </button>
        <div v-else></div>
        <button
          v-if="nextChapter"
          @click="navigateToChapter(nextChapter.id)"
          class="orc-chapter-link orc-chapter-next"
        >
          <span class="orc-chapter-link-label">{{ t('oracleView.chapterNav.nextLabel') }}</span>
          <span class="orc-chapter-link-title">{{ nextChapter.title }}</span>
        </button>
        <div v-else></div>
      </div>

      <!-- Footer -->
      <footer class="orc-footer">
        <p>{{ t('oracleView.footer.copyright') }}</p>
        <p class="orc-footer-sm">{{ t('oracleView.footer.derived') }}</p>
      </footer>
    </div>
  </div>
</template>

<style scoped>
@import url('/fonts/fonts-extra.css'); /* §LEGALKIT: Vite inlines this public file at build time; the font URLs inside it are /static/fonts/, where the registry serves the dist (V0413) */

/* ═══ ROOT & VARIABLES ═══ */
.orc-root {
  --orc-blue: #3B82F6;
  --orc-purple: #8B5CF6;
  --orc-green: #10B981;
  --orc-gold: #F59E0B;
  --orc-gradient: linear-gradient(135deg, #3B82F6 0%, #8B5CF6 50%, #10B981 100%);
  --orc-glass: rgba(15, 15, 20, 0.4);
  --orc-glass-border: rgba(255, 255, 255, 0.1);
  --orc-text: #F8FAFC;
  --orc-text-secondary: #94A3B8;
  --orc-text-muted: #7d8ba0; /* §FESUITE: was #64748B, 4.13-4.32:1 on the docs' surfaces; now 5.1-6.0:1 */

  min-height: 100vh;
  background: #020309;
  color: var(--orc-text);
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  overflow-x: hidden;
}

/* ═══ CANVAS STARFIELD ═══ */
.orc-starfield-canvas {
  position: fixed;
  top: 0; left: 0;
  width: 100%; height: 100%;
  z-index: 1;
  pointer-events: none;
  display: block;
}
.orc-vignette {
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

/* Anti-banding noise: SVG fractal turbulence baked into a data URI, tiled at
   3% opacity with soft-light blend. Eliminates the gradient stepping visible
   on wide flat areas. Static (no animation) — cheap. */
.orc-noise {
  position: fixed;
  inset: 0;
  z-index: 3;
  pointer-events: none;
  opacity: 0.035;
  mix-blend-mode: soft-light;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='240' height='240'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch' seed='7'/><feColorMatrix values='0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.8 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>");
  background-size: 240px 240px;
}

/* ═══ READING PROGRESS ═══ */
.orc-progress {
  position: fixed;
  top: 0; left: 0;
  width: 100%; height: 4px;
  background: rgba(59,130,246,0.1);
  z-index: 1002;
  pointer-events: none;
}
.orc-progress-bar {
  height: 100%;
  background: var(--orc-gradient);
  transition: width 0.2s ease;
  box-shadow: 0 0 20px rgba(59,130,246,0.6);
}

/* ═══ GLASS HEADER ═══ */
.orc-header {
  position: fixed;
  top: 0; left: 0; right: 0;
  /* Above the App.vue beta-banner (z:9999) so the Oracle nav controls — search,
     Chapters, prev/next — stay tappable on mobile where the banner is sticky. */
  z-index: 10000;
  background: var(--orc-glass);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid var(--orc-glass-border);
  padding: 1.25rem 2rem;
  transition: all 0.3s ease;
  box-shadow: 0 8px 32px rgba(0,0,0,0.4);
}
.orc-header-scrolled {
  padding: 0.75rem 2rem;
  background: rgba(10,10,10,0.92);
}
.orc-nav {
  max-width: 1600px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.orc-logo {
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
.orc-logo:hover { opacity: 0.85; }
.orc-logo-mark {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 0;
}
.orc-logo-wordmark {
  font-family: 'Orbitron', 'Inter', sans-serif;
  font-weight: 800;
  font-size: 0.92rem;
  letter-spacing: 0.08em;
  color: #F8FAFC;
  white-space: nowrap;
}
.orc-logo-divider {
  color: rgba(255, 255, 255, 0.2);
  font-weight: 300;
  font-size: 0.9rem;
}
.orc-logo-sub {
  font-family: 'Orbitron', 'Inter', sans-serif;
  font-weight: 500;
  font-size: 0.72rem;
  letter-spacing: 0.22em;
  color: #DC2626;
  text-shadow: 0 0 8px rgba(220, 38, 38, 0.45);
  white-space: nowrap;
}
.orc-nav-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}
.orc-chapter-pill {
  font-size: 0.8rem;
  font-weight: 500;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--orc-text-secondary);
  padding: 0.4rem 1rem;
  background: rgba(59,130,246,0.1);
  border-radius: 50px;
  border: 1px solid rgba(59,130,246,0.2);
}
.orc-nav-controls { display: flex; gap: 0.75rem; }
.orc-nav-btn {
  background: var(--orc-glass);
  backdrop-filter: blur(10px);
  border: 1px solid var(--orc-glass-border);
  color: var(--orc-text);
  padding: 0.6rem 1.25rem;
  border-radius: 10px;
  cursor: pointer;
  font-weight: 500;
  font-size: 0.85rem;
  font-family: inherit;
  letter-spacing: 0.02em;
  transition: all 0.3s ease;
}
.orc-nav-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(59,130,246,0.25);
  border-color: var(--orc-blue);
  background: rgba(59,130,246,0.15);
}
.orc-exit-btn {
  border-color: rgba(255,255,255,0.08);
  color: var(--orc-text-secondary);
}
.orc-exit-btn:hover {
  border-color: rgba(220,38,38,0.3);
  box-shadow: 0 8px 24px rgba(220,38,38,0.15);
}

.orc-search-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.6rem;
  padding-right: 0.5rem;
}
.orc-search-icon {
  color: rgba(139, 92, 246, 0.9);
  font-size: 1rem;
  line-height: 1;
}
.orc-search-label {
  font-weight: 500;
  letter-spacing: 0.01em;
}
.orc-search-kbd {
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

/* ═══ CHAPTER MENU (slide from right) ═══ */
/* Backdrop sits between Oracle header (10000) and the drawer (10001), dims everything */
.orc-menu-overlay {
  position: fixed;
  top: 0; left: 0; right: 0; bottom: 0;
  background: rgba(0,0,0,0.62);
  z-index: 10000;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.3s ease;
}
.orc-menu-visible { opacity: 1; pointer-events: all; }
.orc-menu {
  position: fixed;
  top: 0;
  right: -420px;
  width: 420px;
  height: 100vh;
  background: rgba(8,8,12,0.95);
  backdrop-filter: blur(20px);
  border-left: 1px solid var(--orc-glass-border);
  /* Above the Oracle header (z:10000) AND the App.vue beta-banner (z:9999) so
     the drawer's close ✕, title, and chapter list are fully tappable on mobile
     where the banner is sticky-fixed at the top. */
  z-index: 10001;
  transition: right 0.35s cubic-bezier(0.25,0.46,0.45,0.94);
  overflow-y: auto;
  box-shadow: -10px 0 40px rgba(0,0,0,0.6);
}
.orc-menu-open { right: 0; }
.orc-menu-header {
  padding: 2rem;
  border-bottom: 1px solid var(--orc-glass-border);
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.orc-menu-title {
  font-size: 1.5rem;
  font-weight: 800;
  background: var(--orc-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
.orc-menu-close {
  background: none;
  border: 1px solid var(--orc-glass-border);
  color: var(--orc-text-secondary);
  width: 36px; height: 36px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 1rem;
  transition: all 0.2s;
  font-family: inherit;
}
.orc-menu-close:hover { border-color: var(--orc-blue); color: var(--orc-text); }
.orc-menu-list { padding: 1rem; }
.orc-menu-group {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--orc-blue);
  opacity: 0.7;
  padding: 1rem 1rem 0.4rem;
  margin-top: 0.25rem;
}
.orc-menu-group:first-child { margin-top: 0; }
.orc-menu-item {
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
  color: var(--orc-text-secondary);
  margin-bottom: 4px;
}
.orc-menu-item:hover {
  background: rgba(59,130,246,0.06);
  border-color: rgba(59,130,246,0.15);
  color: var(--orc-text);
}
.orc-menu-item-active {
  background: rgba(59,130,246,0.1) !important;
  border-color: rgba(59,130,246,0.3) !important;
  color: var(--orc-text) !important;
}
.orc-menu-num {
  font-size: 0.7rem;
  font-weight: 700;
  color: var(--orc-blue);
  opacity: 0.5;
  font-variant-numeric: tabular-nums;
  min-width: 1.5rem;
}
.orc-menu-item-active .orc-menu-num { opacity: 1; }
.orc-menu-info { flex: 1; }
.orc-menu-item-title {
  display: block;
  font-size: 0.9rem;
  font-weight: 600;
  margin-bottom: 2px;
}
.orc-menu-item-sub {
  display: block;
  font-size: 0.75rem;
  color: var(--orc-text-muted);
}
.orc-menu-time {
  font-size: 0.7rem;
  color: var(--orc-text-muted);
  white-space: nowrap;
}

/* ═══ CONTENT LAYER ═══ */
.orc-content {
  position: relative;
  z-index: 10;
  isolation: isolate;
}

/* ═══ CHAPTER HERO (full viewport, cinematic) ═══ */
.orc-hero {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  position: relative;
  overflow: hidden;
  background: radial-gradient(ellipse at center, rgba(59,130,246,0.09) 0%, rgba(30,20,80,0.04) 50%, transparent 75%);
  padding-top: 80px;
}
.orc-hero::before {
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
.orc-hero-bg-num {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  font-size: 30vw;
  font-weight: 900;
  opacity: 0.025;
  color: var(--orc-blue);
  pointer-events: none;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.05em;
  line-height: 1;
}
.orc-hero-center {
  text-align: center;
  z-index: 2;
  max-width: 1100px;
  padding: 0 2rem;
  animation: orc-hero-up 1s ease 0.3s both;
}
@keyframes orc-hero-up {
  from { opacity: 0; transform: translateY(40px); }
  to { opacity: 1; transform: translateY(0); }
}
.orc-hero-mark {
  display: flex;
  justify-content: center;
  margin-bottom: 2.5rem;
  animation: orc-hero-mark-in 1.2s ease 0.15s both;
}
@keyframes orc-hero-mark-in {
  from { opacity: 0; transform: translateY(18px) scale(0.94); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* ═══ BRAND HERO (chapter 00 only — matches /logo page) ═══ */
.orc-hero-brand {
  /* Slightly richer vignette so the mark + wordmark pop */
  background:
    radial-gradient(ellipse at center, rgba(220, 38, 38, 0.08) 0%, rgba(60, 10, 20, 0.04) 45%, transparent 75%);
}
.orc-brand-wordmark {
  font-family: 'Orbitron', 'Inter', sans-serif;
  font-weight: 900;
  font-size: clamp(2.2rem, 7vw, 5rem);
  letter-spacing: 0.06em;
  line-height: 1;
  margin: 0 0 1.2rem;
  /* Chrome gradient — bone-white top into steel at bottom */
  background: linear-gradient(180deg, #FAFAFA 0%, #D4D4D4 45%, #8A8A8A 80%, #5A5A5A 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
  text-shadow: 0 0 40px rgba(255, 255, 255, 0.06);
  animation: orc-hero-up 1s ease 0.4s both;
}
.orc-brand-tagline {
  font-family: 'Orbitron', 'Inter', sans-serif;
  font-weight: 500;
  font-size: clamp(0.75rem, 1.4vw, 1rem);
  letter-spacing: 0.32em;
  color: #DC2626;
  text-shadow: 0 0 14px rgba(220, 38, 38, 0.5);
  margin: 0;
  animation: orc-hero-up 1s ease 0.6s both;
}
.orc-hero-title {
  font-size: clamp(3rem, 9vw, 6.5rem);
  font-weight: 900;
  line-height: 1.08;
  letter-spacing: -0.025em;
  margin-bottom: 1.5rem;
  background: var(--orc-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  position: relative;
  display: inline-block;
}
.orc-hero-title::before {
  content: attr(data-text);
  position: absolute;
  left: 0; top: 0;
  z-index: -1;
  background: var(--orc-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  filter: blur(40px);
  opacity: 0.4;
}
.orc-hero-subtitle {
  font-size: clamp(1.1rem, 2.5vw, 1.75rem);
  color: var(--orc-text-secondary);
  font-weight: 300;
  letter-spacing: 0.02em;
  animation: orc-hero-up 1s ease 0.5s both;
}
.orc-hero-bottom {
  position: absolute;
  bottom: 2.5rem;
  left: 0; right: 0;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  padding: 0 2.5rem;
  animation: orc-hero-up 1s ease 0.8s both;
}
.orc-hero-reading {
  font-size: 0.8rem;
  color: var(--orc-text-muted);
  letter-spacing: 0.03em;
}
.orc-scroll-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.6rem;
}
.orc-scroll-text {
  font-size: 0.65rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--orc-text-muted);
}
.orc-scroll-arrow {
  width: 22px; height: 36px;
  border: 2px solid var(--orc-blue);
  border-radius: 20px;
  position: relative;
  opacity: 0.5;
}
.orc-scroll-dot {
  position: absolute;
  top: 6px; left: 50%;
  width: 4px; height: 6px;
  background: var(--orc-blue);
  border-radius: 2px;
  transform: translateX(-50%);
  animation: orc-scroll-bounce 2s ease-in-out infinite;
}
@keyframes orc-scroll-bounce {
  0%, 100% { transform: translateX(-50%) translateY(0); }
  50% { transform: translateX(-50%) translateY(10px); }
}

/* ═══ ARTICLE (markdown body) ═══ */
.orc-article {
  max-width: 900px;
  margin: 0 auto;
  padding: 5rem 2rem 6rem;
  position: relative;
  z-index: 2;
}

/* Headings */
.orc-article :deep(h1) {
  font-size: clamp(2.25rem, 5vw, 3.25rem);
  font-weight: 800;
  margin: 4rem 0 1.5rem;
  background: var(--orc-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  line-height: 1.2;
  letter-spacing: -0.02em;
  padding-bottom: 0.75rem;
  position: relative;
}
.orc-article :deep(h1)::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0;
  width: 80px; height: 4px;
  background: var(--orc-gradient);
  border-radius: 2px;
}
.orc-article :deep(h2) {
  font-size: clamp(1.75rem, 4vw, 2.25rem);
  font-weight: 700;
  margin: 3.5rem 0 1.25rem;
  color: var(--orc-blue);
  position: relative;
  padding-left: 1.5rem;
}
.orc-article :deep(h2)::before {
  content: '◈';
  position: absolute;
  left: 0; top: 50%;
  transform: translateY(-50%);
  color: var(--orc-green);
  font-size: 1rem;
}
.orc-article :deep(h3) {
  font-size: clamp(1.25rem, 3vw, 1.75rem);
  font-weight: 600;
  margin: 2.5rem 0 0.75rem;
  color: var(--orc-purple);
}
.orc-article :deep(h4) {
  font-size: 1.1rem;
  font-weight: 600;
  margin: 2rem 0 0.5rem;
  color: #a78bfa;
}

/* Body text */
.orc-article :deep(p) {
  font-size: 1.1rem;
  line-height: 1.85;
  color: var(--orc-text);
  margin-bottom: 1.5rem;
  font-weight: 400;
  letter-spacing: 0.01em;
}
.orc-article :deep(strong) { color: #fff; font-weight: 600; }
.orc-article :deep(em) { color: var(--orc-text-secondary); }
.orc-article :deep(a) {
  color: var(--orc-blue);
  text-decoration: none;
  border-bottom: 1px solid rgba(59,130,246,0.3);
  transition: border-color 0.2s;
}
.orc-article :deep(a:hover) { border-bottom-color: var(--orc-blue); }

/* Code blocks (wrapped: copy button + lang label + pre) */
.orc-article :deep(.orc-code-wrap) {
  position: relative;
  margin: 2rem 0;
  border-radius: 14px;
  overflow: hidden;
}
.orc-article :deep(.orc-code) {
  background: rgba(10, 13, 22, 0.62);
  border: 1px solid var(--orc-glass-border);
  border-radius: 14px;
  padding: 1.8rem 1.5rem 1.1rem;
  margin: 0;
  overflow-x: auto;
  box-shadow: 0 8px 32px rgba(0,0,0,0.42), inset 0 1px 0 rgba(255,255,255,0.035);
  position: relative;
}
.orc-article :deep(.orc-code-lang) {
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
.orc-article :deep(.orc-code-copy) {
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
.orc-article :deep(.orc-code-wrap:hover .orc-code-copy),
.orc-article :deep(.orc-code-copy:focus-visible) { opacity: 1; }
/* a device with no hover (a phone) cannot reveal the copy button: show it there */
@media (hover: none) {
  .orc-article :deep(.orc-code-copy) { opacity: 1; }
}
.orc-article :deep(.orc-code-copy:hover) {
  background: rgba(59, 130, 246, 0.18);
  color: #e4ecf4;
  border-color: rgba(59, 130, 246, 0.4);
}
.orc-article :deep(.orc-code-copy-flash) {
  background: rgba(16, 185, 129, 0.28) !important;
  color: #d1fae5 !important;
  border-color: rgba(16, 185, 129, 0.55) !important;
}
.orc-article :deep(.orc-code code) {
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 0.85rem;
  line-height: 1.55;
  color: var(--orc-text);
  white-space: pre;
  display: block;
}

/* Callouts — :::tip / :::warn / :::info / :::note */
.orc-article :deep(.orc-callout) {
  margin: 2rem 0;
  padding: 1rem 1.25rem 0.85rem;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-left-width: 3px;
  background: rgba(15, 18, 28, 0.5);
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.3);
}
.orc-article :deep(.orc-callout-head) {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
}
.orc-article :deep(.orc-callout-icon) {
  width: 14px; height: 14px;
  border-radius: 50%;
  flex-shrink: 0;
}
.orc-article :deep(.orc-callout-label) {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.orc-article :deep(.orc-callout-body) {
  color: rgba(226, 232, 240, 0.92);
  font-size: 1rem;
  line-height: 1.75;
}
.orc-article :deep(.orc-callout-body > p:last-child) { margin-bottom: 0; }
.orc-article :deep(.orc-callout-body > p) { margin-bottom: 0.55rem; font-size: 1rem; line-height: 1.7; }

.orc-article :deep(.orc-callout-tip) {
  border-left-color: #10B981;
  background: linear-gradient(90deg, rgba(16, 185, 129, 0.08), rgba(15, 18, 28, 0.5) 45%);
}
.orc-article :deep(.orc-callout-tip .orc-callout-icon) {
  background: radial-gradient(circle at 35% 30%, #34d399, #059669);
  box-shadow: 0 0 10px rgba(16, 185, 129, 0.55);
}
.orc-article :deep(.orc-callout-tip .orc-callout-label) { color: #34d399; }

.orc-article :deep(.orc-callout-warn) {
  border-left-color: #F59E0B;
  background: linear-gradient(90deg, rgba(245, 158, 11, 0.1), rgba(15, 18, 28, 0.5) 45%);
}
.orc-article :deep(.orc-callout-warn .orc-callout-icon) {
  background: radial-gradient(circle at 35% 30%, #fbbf24, #d97706);
  box-shadow: 0 0 10px rgba(245, 158, 11, 0.55);
}
.orc-article :deep(.orc-callout-warn .orc-callout-label) { color: #fbbf24; }

.orc-article :deep(.orc-callout-info) {
  border-left-color: #3B82F6;
  background: linear-gradient(90deg, rgba(59, 130, 246, 0.08), rgba(15, 18, 28, 0.5) 45%);
}
.orc-article :deep(.orc-callout-info .orc-callout-icon) {
  background: radial-gradient(circle at 35% 30%, #60a5fa, #2563eb);
  box-shadow: 0 0 10px rgba(59, 130, 246, 0.55);
}
.orc-article :deep(.orc-callout-info .orc-callout-label) { color: #60a5fa; }

.orc-article :deep(.orc-callout-note) {
  border-left-color: #8B5CF6;
  background: linear-gradient(90deg, rgba(139, 92, 246, 0.08), rgba(15, 18, 28, 0.5) 45%);
}
.orc-article :deep(.orc-callout-note .orc-callout-icon) {
  background: radial-gradient(circle at 35% 30%, #a78bfa, #7c3aed);
  box-shadow: 0 0 10px rgba(139, 92, 246, 0.55);
}
.orc-article :deep(.orc-callout-note .orc-callout-label) { color: #a78bfa; }
.orc-article :deep(.orc-ic) {
  background: rgba(59,130,246,0.1);
  border: 1px solid rgba(59,130,246,0.2);
  padding: 0.15rem 0.45rem;
  border-radius: 6px;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  color: var(--orc-green);
  font-size: 0.88em;
  font-weight: 500;
  /* a long path or permission name breaks where it must instead of running past a phone's edge (the camera, 2026-10-13) */
  overflow-wrap: anywhere;
}

/* Tables */
.orc-article :deep(.orc-tbl-wrap) {
  overflow-x: auto;
  margin: 2rem 0;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
}
.orc-article :deep(table) {
  width: 100%;
  border-collapse: collapse;
  background: var(--orc-glass);
  backdrop-filter: blur(10px);
  font-size: 0.9rem;
}
.orc-article :deep(th) {
  background: rgba(59,130,246,0.1);
  padding: 0.85rem 1.25rem;
  text-align: left;
  font-weight: 600;
  color: var(--orc-blue);
  font-size: 0.8rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 2px solid rgba(59,130,246,0.2);
  white-space: nowrap;
}
.orc-article :deep(td) {
  padding: 0.75rem 1.25rem;
  border-bottom: 1px solid var(--orc-glass-border);
  color: var(--orc-text-secondary);
  vertical-align: top;
}
.orc-article :deep(tr:last-child td) { border-bottom: none; }
.orc-article :deep(tr:hover td) { background: rgba(59,130,246,0.04); }

/* Lists */
.orc-article :deep(ul) {
  list-style: none;
  padding: 0;
  margin: 1.5rem 0;
}
.orc-article :deep(li) {
  position: relative;
  padding: 0.4rem 0 0.4rem 1.75rem;
  font-size: 1.05rem;
  line-height: 1.75;
  color: var(--orc-text);
}
.orc-article :deep(li)::before {
  content: '▸';
  position: absolute;
  left: 0;
  color: var(--orc-blue);
  font-weight: 700;
  font-size: 1.15rem;
}
/* Ordered lists */
.orc-article :deep(.orc-ol) {
  list-style: none;
  padding: 0;
  margin: 1.5rem 0;
  counter-reset: orc-counter;
}
.orc-article :deep(.orc-ol > li) {
  position: relative;
  padding: 0.45rem 0 0.45rem 2.5rem;
  font-size: 1.05rem;
  line-height: 1.75;
  color: var(--orc-text);
  counter-increment: orc-counter;
}
.orc-article :deep(.orc-ol > li)::before {
  content: counter(orc-counter);
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
  color: var(--orc-blue);
  line-height: 1.75rem;
  text-align: center;
}

/* Mermaid diagrams — translucent glass card over the starfield */
.orc-article :deep(.orc-mermaid) {
  background: rgba(15, 18, 28, 0.45);
  backdrop-filter: blur(14px) saturate(140%);
  -webkit-backdrop-filter: blur(14px) saturate(140%);
  border: 1px solid rgba(139, 92, 246, 0.25);
  border-left: 3px solid rgba(59, 130, 246, 0.55);
  border-radius: 14px;
  padding: 1.75rem 1.25rem;
  margin: 2rem 0;
  overflow-x: auto;
  text-align: center;
  min-height: 80px;
  font-size: 0.82rem;
  line-height: 1.55;
  color: var(--orc-text-muted);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.35);
}
.orc-article :deep(.orc-mermaid svg) {
  max-width: 100%;
  height: auto;
  margin: 0 auto;
  display: block;
}
.orc-article :deep(.orc-mermaid[data-processed="true"]) {
  color: transparent;
  cursor: zoom-in;
  position: relative;
  transition: border-color 0.25s ease, box-shadow 0.25s ease, transform 0.25s ease;
}
.orc-article :deep(.orc-mermaid[data-processed="true"]:hover) {
  border-color: rgba(139, 92, 246, 0.55);
  box-shadow: 0 12px 40px rgba(139, 92, 246, 0.18);
  transform: translateY(-1px);
}
.orc-article :deep(.orc-mermaid[data-processed="true"])::after {
  content: '⤢ Click to enlarge';
  position: absolute;
  top: 0.5rem;
  right: 0.75rem;
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 0.65rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(139, 92, 246, 0.8);
  background: rgba(15, 18, 28, 0.85);
  border: 1px solid rgba(139, 92, 246, 0.25);
  padding: 0.25rem 0.55rem;
  border-radius: 6px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s ease;
}
.orc-article :deep(.orc-mermaid[data-processed="true"]:hover)::after {
  opacity: 1;
}

/* ═══ EXPLORABLE ARCHITECTURE FIGURES (```mermaid + ```archmap; archmap.ts, useArchFigures.ts) ═══ */
.orc-article :deep(.orc-archfig) {
  margin: 2.25rem 0 2.5rem;
  padding: 0;
}
/* A figure may be wider than the text column. Below 1500px nothing sits beside the column,
   so it grows on both sides; from 1500px the fixed TOC sits 40px right of the column, so it
   grows to the left only. */
@media (min-width: 1100px) and (max-width: 1499px) {
  .orc-article :deep(.orc-archfig) {
    width: min(1240px, calc(100vw - 4rem));
    margin-left: calc((100% - min(1240px, calc(100vw - 4rem))) / 2);
  }
}
@media (min-width: 1500px) {
  .orc-article :deep(.orc-archfig) {
    width: calc(100% + min(340px, (100vw - 900px) / 2 - 3rem));
    margin-left: calc(-1 * min(340px, (100vw - 900px) / 2 - 3rem));
  }
}
.orc-article :deep(.orc-archfig .orc-mermaid) {
  margin: 0.75rem 0 0;
}
.orc-article :deep(.orc-archfig .orc-mermaid[data-processed="true"]) {
  cursor: default;
}
.orc-article :deep(.orc-archfig .orc-mermaid[data-processed="true"]:hover) {
  transform: none;
}
.orc-article :deep(.orc-archfig .orc-mermaid[data-processed="true"])::after {
  content: none;
}
.orc-article :deep(.orc-arch-title) {
  font: 700 0.72rem 'Inter', system-ui, sans-serif;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(167, 139, 250, 0.95);
  margin: 0 0 0.6rem;
}
.orc-article :deep(.orc-arch-toolbar) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem 1rem;
}
.orc-article :deep(.orc-arch-layers) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
}
.orc-article :deep(.orc-arch-layers-label),
.orc-article :deep(.orc-arch-stepper-label) {
  font: 600 0.68rem 'Inter', system-ui, sans-serif;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--orc-text-muted);
  margin-right: 0.25rem;
}
.orc-article :deep(.orc-arch-chip),
.orc-article :deep(.orc-arch-expand),
.orc-article :deep(.orc-arch-step-btn),
.orc-article :deep(.orc-arch-step-reset) {
  font: 600 0.75rem 'Inter', system-ui, sans-serif;
  color: var(--orc-text);
  background: rgba(15, 18, 28, 0.6);
  border: 1px solid rgba(139, 92, 246, 0.3);
  border-radius: 999px;
  padding: 0.3rem 0.75rem;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease, color 0.2s ease;
}
.orc-article :deep(.orc-arch-chip:hover),
.orc-article :deep(.orc-arch-expand:hover),
.orc-article :deep(.orc-arch-step-btn:hover:not(:disabled)),
.orc-article :deep(.orc-arch-step-reset:hover),
.orc-article :deep(.orc-arch-chip:focus-visible),
.orc-article :deep(.orc-arch-expand:focus-visible),
.orc-article :deep(.orc-arch-step-btn:focus-visible),
.orc-article :deep(.orc-arch-step-reset:focus-visible) {
  border-color: rgba(59, 130, 246, 0.8);
  outline: none;
}
.orc-article :deep(.orc-arch-explore) {
  display: none;
}
.orc-article :deep(.orc-archfig.is-tiny .orc-arch-explore) {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  margin: 0.6rem 0 0;
  padding: 0.55rem 0.9rem;
  font: 600 0.8rem 'Inter', system-ui, sans-serif;
  color: #ffffff;
  background: rgba(59, 130, 246, 0.2);
  border: 1px solid rgba(96, 165, 250, 0.6);
  border-radius: 0.6rem;
  cursor: pointer;
}
.orc-article :deep(.orc-archfig.is-tiny .orc-arch-explore:focus-visible) {
  outline: 2px solid rgba(96, 165, 250, 0.9);
  outline-offset: 2px;
}
.orc-article :deep(.orc-archfig.is-tiny .orc-mermaid[data-processed="true"]) {
  cursor: zoom-in;
}
.orc-article :deep(.orc-arch-chip.is-on) {
  background: rgba(59, 130, 246, 0.22);
  border-color: rgba(96, 165, 250, 0.85);
  color: #ffffff;
}
.orc-article :deep(.orc-arch-step-btn) {
  width: 2rem;
  padding: 0.3rem 0;
  font-size: 1rem;
  line-height: 1;
}
.orc-article :deep(.orc-arch-step-btn:disabled) {
  opacity: 0.35;
  cursor: default;
}
.orc-article :deep(.orc-arch-stepper) {
  margin: 0.75rem 0 0;
  padding: 0.75rem 1rem;
  border: 1px solid rgba(16, 185, 129, 0.3);
  border-left: 3px solid rgba(16, 185, 129, 0.7);
  border-radius: 12px;
  background: rgba(13, 30, 26, 0.35);
}
.orc-article :deep(.orc-arch-stepper-bar) {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
}
.orc-article :deep(.orc-arch-step-count) {
  font: 600 0.75rem 'JetBrains Mono', 'Fira Code', monospace;
  color: #a7f3d0;
  min-width: 6.5rem;
  text-align: center;
}
.orc-article :deep(.orc-arch-narration) {
  margin-top: 0.55rem;
  font-size: 0.92rem;
  line-height: 1.6;
  color: var(--orc-text);
  min-height: 1.6em;
}
.orc-article :deep(.orc-arch-narration-title) {
  display: block;
  color: #6ee7b7;
  margin-bottom: 0.15rem;
}
.orc-article :deep(.orc-arch-narration-idle),
.orc-article :deep(.orc-arch-detail-idle) {
  color: var(--orc-text-muted);
  font-style: italic;
}
.orc-article :deep(.orc-arch-detail) {
  margin: 0.75rem 0 0;
  padding: 0.75rem 1rem;
  border: 1px solid rgba(139, 92, 246, 0.22);
  border-radius: 12px;
  background: rgba(15, 18, 28, 0.4);
  transition: border-color 0.25s ease, background 0.25s ease;
}
.orc-article :deep(.orc-arch-detail p) {
  margin: 0;
}
.orc-article :deep(.orc-arch-detail.is-active) {
  border-color: rgba(250, 204, 21, 0.5);
  background: rgba(42, 31, 14, 0.35);
}
/* With the card showing beside the component, the panel stays only for screen readers. */
.orc-article :deep(.orc-arch-detail.is-active.has-pop) {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  border: 0;
}
/* The card beside the component that was clicked (useArchFigures.ts places it) */
.orc-article :deep(.orc-arch-pop) {
  position: absolute;
  z-index: 5;
  width: min(340px, calc(100% - 16px));
  padding: 0.75rem 2.1rem 0.8rem 0.95rem;
  text-align: left;
  background: rgba(20, 15, 6, 0.96);
  border: 1px solid rgba(250, 204, 21, 0.6);
  border-radius: 12px;
  box-shadow: 0 14px 44px rgba(0, 0, 0, 0.6);
  color: var(--orc-text);
  cursor: default;
  animation: orc-arch-pop-in 0.16s ease-out;
}
@keyframes orc-arch-pop-in {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: none; }
}
.orc-article :deep(.orc-arch-pop[hidden]) {
  display: none;
}
.orc-article :deep(.orc-arch-pop p) {
  margin: 0 !important;
}
.orc-article :deep(.orc-arch-pop-title) {
  font: 700 0.9rem 'Inter', system-ui, sans-serif !important;
  color: #fde68a !important;
  margin-bottom: 0.3rem !important;
}
.orc-article :deep(.orc-arch-pop-purpose) {
  font-size: 0.84rem !important;
  line-height: 1.5 !important;
  margin-bottom: 0.4rem !important;
}
.orc-article :deep(.orc-arch-pop-close) {
  position: absolute;
  top: 0.35rem;
  right: 0.45rem;
  width: 1.6rem;
  height: 1.6rem;
  border-radius: 50%;
  border: 1px solid rgba(250, 204, 21, 0.35);
  background: transparent;
  color: #fde68a;
  cursor: pointer;
  line-height: 1;
}
.orc-article :deep(.orc-arch-detail-title) {
  font-weight: 700;
  color: #fde68a;
  margin-bottom: 0.25rem !important;
}
.orc-article :deep(.orc-arch-detail-purpose) {
  font-size: 0.92rem;
  line-height: 1.6;
  margin-bottom: 0.35rem !important;
}
.orc-article :deep(.orc-arch-read) {
  font-size: 0.8rem;
  font-weight: 600;
  white-space: nowrap;
}
.orc-article :deep(.orc-arch-legend) {
  margin: 0.75rem 0 0;
  border: 1px solid rgba(139, 92, 246, 0.18);
  border-radius: 12px;
  background: rgba(15, 18, 28, 0.3);
}
.orc-article :deep(.orc-arch-legend-head) {
  cursor: pointer;
  padding: 0.6rem 1rem;
  font: 600 0.78rem 'Inter', system-ui, sans-serif;
  letter-spacing: 0.06em;
  color: var(--orc-text-muted);
  list-style-position: inside;
}
.orc-article :deep(.orc-arch-count) {
  display: inline-block;
  margin-left: 0.35rem;
  padding: 0 0.45rem;
  border-radius: 999px;
  background: rgba(139, 92, 246, 0.2);
  color: #ddd6fe;
  font-size: 0.7rem;
}
.orc-article :deep(.orc-arch-list) {
  list-style: none;
  margin: 0;
  padding: 0.25rem 0.75rem 0.75rem;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 0.5rem;
}
.orc-article :deep(.orc-arch-item-row) {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  margin: 0;
  padding: 0;
}
.orc-article :deep(.orc-arch-item-row)::before {
  content: none;
}
.orc-article :deep(.orc-arch-item) {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  width: 100%;
  text-align: left;
  padding: 0.55rem 0.7rem;
  border-radius: 10px;
  border: 1px solid rgba(59, 130, 246, 0.18);
  background: rgba(20, 24, 36, 0.45);
  color: var(--orc-text);
  cursor: pointer;
  transition: border-color 0.2s ease, opacity 0.25s ease, background 0.2s ease;
}
.orc-article :deep(.orc-arch-item:hover),
.orc-article :deep(.orc-arch-item:focus-visible) {
  border-color: rgba(96, 165, 250, 0.7);
  outline: none;
}
.orc-article :deep(.orc-arch-item.is-selected) {
  border-color: rgba(250, 204, 21, 0.75);
  background: rgba(42, 31, 14, 0.45);
}
.orc-article :deep(.orc-arch-item.is-dim) {
  opacity: 0.4;
}
.orc-article :deep(.orc-arch-item-title) {
  font-weight: 700;
  font-size: 0.85rem;
}
.orc-article :deep(.orc-arch-item-purpose) {
  font-size: 0.78rem;
  line-height: 1.45;
  color: var(--orc-text-muted);
}
.orc-article :deep(.orc-arch-item-row .orc-arch-read) {
  padding-left: 0.7rem;
}
.orc-article :deep(.orc-arch-checked) {
  margin: 0.5rem 0 0 !important;
  font: 500 0.68rem 'JetBrains Mono', 'Fira Code', monospace !important;
  letter-spacing: 0.04em;
  color: rgba(148, 163, 184, 0.75) !important;
  text-align: right;
}
.orc-article :deep(.orc-arch-error) {
  color: #fecaca;
  font: 600 0.8rem 'JetBrains Mono', 'Fira Code', monospace;
}
/* The SVG itself: what is lit, what steps back */
.orc-article :deep(.orc-archfig svg [data-arch-node]) {
  cursor: pointer;
  transition: opacity 0.25s ease, filter 0.25s ease;
}
.orc-article :deep(.orc-archfig svg [data-arch-node]:focus) {
  outline: none;
}
.orc-article :deep(.orc-archfig svg [data-arch-node]:focus-visible) {
  filter: drop-shadow(0 0 6px rgba(96, 165, 250, 0.95));
}
.orc-article :deep(.orc-archfig svg [data-arch-node]:hover) {
  filter: drop-shadow(0 0 5px rgba(167, 139, 250, 0.8));
}
.orc-article :deep(.orc-archfig svg .arch-dim) {
  opacity: 0.14;
}
.orc-article :deep(.orc-archfig svg [data-arch-from]),
.orc-article :deep(.orc-archfig svg text[data-arch-msg]) {
  transition: opacity 0.25s ease, stroke 0.25s ease, stroke-width 0.25s ease;
}
.orc-article :deep(.orc-archfig svg path.arch-hot),
.orc-article :deep(.orc-archfig svg line.arch-hot) {
  stroke: #facc15 !important;
  stroke-width: 2.5px !important;
}
.orc-article :deep(.orc-archfig svg text.arch-hot) {
  fill: #fde68a !important;
  font-weight: 700;
}
.orc-article :deep(.orc-archfig svg .arch-selected) {
  filter: drop-shadow(0 0 7px rgba(250, 204, 21, 0.95)) drop-shadow(0 0 18px rgba(250, 204, 21, 0.4));
}

/* ═══ MERMAID LIGHTBOX (expandable diagrams) ═══ */
.orc-mermaid-lightbox {
  position: fixed;
  inset: 0;
  /* Above Oracle drawer (z:10001) + beta banner (z:9999) — full-screen modal */
  z-index: 10002;
  background: rgba(6, 8, 16, 0.88);
  backdrop-filter: blur(8px) saturate(120%);
  -webkit-backdrop-filter: blur(8px) saturate(120%);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 4rem 2rem 2rem;
  animation: orc-lightbox-fade 0.22s ease-out;
}
@keyframes orc-lightbox-fade {
  from { opacity: 0; backdrop-filter: blur(0px); }
  to   { opacity: 1; backdrop-filter: blur(8px) saturate(120%); }
}
.orc-mermaid-lightbox-stage {
  position: relative;
  width: min(96vw, 1800px);
  height: calc(100vh - 9rem);
  overflow: hidden;
  padding: 0;
  background: rgba(15, 18, 28, 0.7);
  border: 1px solid rgba(139, 92, 246, 0.4);
  border-radius: 18px;
  box-shadow: 0 24px 80px rgba(0, 0, 0, 0.6),
              0 0 0 1px rgba(59, 130, 246, 0.18) inset;
  cursor: grab;
  /* pinch and drag arrive as pointer events, not as page scroll or browser zoom */
  touch-action: none;
  user-select: none;
}
.orc-mermaid-lightbox-stage:active {
  cursor: grabbing;
}
.orc-lb-canvas {
  width: 100%;
  box-sizing: border-box;
  padding: 1.5rem;
  transform-origin: 0 0;
  /* no will-change: a promoted layer is rasterised once and then scaled, which blurs text at 300% */
}
/* v-html content carries no scope attribute: every rule that reaches into it is :deep */
.orc-lb-canvas :deep(svg) {
  width: 100% !important;
  height: auto !important;
  max-width: none !important;
  max-height: none !important;
  display: block;
  margin: 0 auto;
}
.orc-lb-canvas :deep([data-arch-node]) {
  cursor: pointer;
}
.orc-lb-canvas :deep(g.arch-selected),
.orc-lb-canvas :deep(.arch-selected) {
  filter: drop-shadow(0 0 7px rgba(250, 204, 21, 0.95)) drop-shadow(0 0 18px rgba(250, 204, 21, 0.45));
}
.orc-lb-controls {
  position: absolute;
  top: 1.25rem;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 0.4rem;
  z-index: 1;
}
.orc-lb-btn {
  min-width: 2.25rem;
  height: 2.25rem;
  padding: 0 0.7rem;
  border-radius: 999px;
  background: rgba(15, 18, 28, 0.85);
  border: 1px solid rgba(139, 92, 246, 0.4);
  color: var(--orc-text);
  font: 600 0.95rem 'Inter', system-ui, sans-serif;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease;
}
.orc-lb-btn:hover,
.orc-lb-btn:focus-visible {
  border-color: rgba(59, 130, 246, 0.8);
  background: rgba(20, 30, 46, 0.95);
  outline: none;
}
.orc-lb-fit {
  font-size: 0.78rem;
  letter-spacing: 0.04em;
}
.orc-lb-zoom {
  min-width: 3.4rem;
  text-align: center;
  font: 600 0.75rem 'JetBrains Mono', 'Fira Code', monospace;
  color: rgba(180, 188, 200, 0.85);
}
.orc-lb-detail {
  position: absolute;
  right: 1.5rem;
  bottom: 3rem;
  width: min(360px, calc(100vw - 3rem));
  padding: 0.9rem 1.1rem;
  background: rgba(10, 13, 22, 0.94);
  border: 1px solid rgba(250, 204, 21, 0.45);
  border-radius: 12px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.55);
  z-index: 1;
}
.orc-lb-detail-title {
  margin: 0 0 0.35rem;
  font: 700 0.95rem 'Inter', system-ui, sans-serif;
  color: #fde68a;
}
.orc-lb-detail-purpose {
  margin: 0 0 0.5rem;
  font-size: 0.85rem;
  line-height: 1.5;
  color: var(--orc-text);
}
.orc-lb-detail-read {
  font-size: 0.8rem;
  font-weight: 600;
  color: #93c5fd;
  text-decoration: none;
}
.orc-lb-detail-read:hover {
  text-decoration: underline;
}
.orc-mermaid-lightbox-close {
  position: absolute;
  top: 1.25rem;
  right: 1.5rem;
  background: rgba(15, 18, 28, 0.85);
  border: 1px solid rgba(139, 92, 246, 0.4);
  color: var(--orc-text);
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
.orc-mermaid-lightbox-close:hover {
  border-color: rgba(220, 38, 38, 0.55);
  background: rgba(42, 14, 14, 0.85);
  color: #fecaca;
  transform: scale(1.05);
}
.orc-mermaid-lightbox-hint {
  position: absolute;
  bottom: 1rem;
  left: 50%;
  transform: translateX(-50%);
  font-family: 'Inter', system-ui, sans-serif;
  font-size: 0.78rem;
  letter-spacing: 0.05em;
  color: rgba(180, 188, 200, 0.7);
}
.orc-mermaid-lightbox-hint kbd {
  background: rgba(139, 92, 246, 0.18);
  border: 1px solid rgba(139, 92, 246, 0.4);
  border-radius: 5px;
  padding: 0.15rem 0.4rem;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.72rem;
  color: #e4ecf4;
  margin: 0 0.2rem;
}
@media (max-width: 768px) {
  .orc-mermaid-lightbox {
    padding: 3rem 0.5rem 1rem;
  }
  .orc-mermaid-lightbox-stage {
    width: 100%;
    height: calc(100vh - 7rem);
  }
  .orc-lb-canvas {
    padding: 0.75rem;
  }
  .orc-lb-controls {
    top: 0.75rem;
    left: 0.75rem;
    transform: none;
  }
  .orc-lb-detail {
    left: 0.75rem;
    right: 0.75rem;
    bottom: 2.5rem;
    width: auto;
  }
  .orc-mermaid-lightbox-close {
    top: 0.75rem;
    right: 0.75rem;
  }
}

/* Scroll margin so anchor-jump lands below the sticky header */
.orc-article :deep(h1),
.orc-article :deep(h2),
.orc-article :deep(h3),
.orc-article :deep(h4) {
  scroll-margin-top: 110px;
}

/* HR */
.orc-article :deep(hr) {
  border: none;
  height: 1px;
  background: var(--orc-glass-border);
  margin: 3rem 0;
}

/* ═══ CHAPTER NAV FOOTER ═══ */
.orc-chapter-nav {
  max-width: 900px;
  margin: 0 auto;
  padding: 0 2rem 2rem;
  display: flex;
  gap: 1rem;
}
.orc-chapter-link {
  flex: 1;
  padding: 1.5rem;
  background: var(--orc-glass);
  backdrop-filter: blur(10px);
  border: 1px solid var(--orc-glass-border);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.3s ease;
  font-family: inherit;
  text-align: left;
}
.orc-chapter-next { text-align: right; }
.orc-chapter-link:hover {
  border-color: rgba(59,130,246,0.3);
  box-shadow: 0 8px 24px rgba(59,130,246,0.15);
  transform: translateY(-2px);
}
.orc-chapter-link-label {
  display: block;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--orc-blue);
  margin-bottom: 0.4rem;
}
.orc-chapter-link-title {
  display: block;
  font-size: 1rem;
  color: var(--orc-text);
  font-weight: 500;
}

/* ═══ FOOTER ═══ */
.orc-footer {
  text-align: center;
  padding: 3rem 2rem;
  font-size: 0.8rem;
  color: var(--orc-text-muted);
  border-top: 1px solid var(--orc-glass-border);
  max-width: 900px;
  margin: 0 auto;
}
.orc-footer-sm {
  margin-top: 0.4rem;
  font-size: 0.7rem;
  color: var(--orc-text-muted); /* was #334155, 1.98:1 */
  font-style: italic;
}

/* ═══ HEADING ANCHOR (¶ on hover → copy link) ═══ */
.orc-article :deep(h2), .orc-article :deep(h3), .orc-article :deep(h4) {
  position: relative;
}
.orc-article :deep(.orc-heading-anchor) {
  position: absolute;
  left: -1.5rem;
  top: 50%;
  transform: translateY(-50%);
  color: rgba(139, 92, 246, 0.5);
  text-decoration: none;
  border-bottom: none;
  font-weight: 400;
  font-size: 0.9em;
  opacity: 0;
  transition: opacity 0.18s ease, color 0.18s ease, transform 0.18s ease;
  padding: 0 0.4rem;
  cursor: pointer;
}
.orc-article :deep(h2:hover) .orc-heading-anchor,
.orc-article :deep(h3:hover) .orc-heading-anchor,
.orc-article :deep(h4:hover) .orc-heading-anchor {
  opacity: 0.7;
}
.orc-article :deep(.orc-heading-anchor:hover) {
  opacity: 1 !important;
  color: var(--orc-blue);
  transform: translateY(-50%) scale(1.15);
  border-bottom: none;
}

/* ═══ "ON THIS PAGE" SECTION IN DRAWER ═══ */
.orc-menu-section {
  margin-top: 0.5rem;
  padding: 1rem 0;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.orc-menu-section-label {
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: rgba(148, 163, 184, 0.75);
  padding: 0 1.5rem 0.75rem;
}
.orc-menu-toc {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 0 0.75rem;
}
.orc-menu-toc-item {
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
.orc-menu-toc-item:hover {
  background: rgba(59, 130, 246, 0.08);
  color: #e4ecf4;
}
.orc-menu-toc-l3 { padding-left: 1.5rem; font-size: 0.78rem; color: rgba(148, 163, 184, 0.7); }
.orc-menu-toc-active {
  background: rgba(59, 130, 246, 0.15) !important;
  color: #ffffff !important;
  box-shadow: inset 2px 0 0 var(--orc-blue);
}

/* ═══ MOBILE "ON THIS PAGE" FLOATING BUTTON ═══ */
.orc-mobile-toc-btn {
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
  border: 1px solid rgba(139, 92, 246, 0.35);
  border-radius: 999px;
  color: #e4ecf4;
  font-family: inherit;
  font-size: 0.82rem;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.orc-mobile-toc-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 12px 32px rgba(59, 130, 246, 0.25);
}
.orc-mobile-toc-icon {
  font-size: 0.95rem;
  color: var(--orc-blue);
}

/* ═══ TOAST ═══ */
.orc-toast {
  position: fixed;
  bottom: 2rem;
  left: 50%;
  transform: translateX(-50%) translateY(40px);
  z-index: 2000;
  padding: 0.7rem 1.25rem;
  background: rgba(15, 18, 28, 0.92);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(139, 92, 246, 0.35);
  border-radius: 10px;
  color: #e4ecf4;
  font-size: 0.85rem;
  letter-spacing: 0.01em;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.25s ease, transform 0.25s ease;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.5);
}
.orc-toast-visible {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

/* ═══ RESPONSIVE ═══ */
/* Tablet + medium phones (≤ 768px) */
@media (max-width: 768px) {
  .orc-header { padding: 0.75rem 1rem; }
  .orc-header-scrolled { padding: 0.5rem 1rem; }
  .orc-nav-center { display: none; }
  .orc-nav-controls { gap: 0.4rem; }
  .orc-nav-btn { padding: 0.5rem 0.8rem; font-size: 0.75rem; min-height: 40px; }
  .orc-exit-btn { display: none; }
  .orc-search-label { display: none; }
  .orc-search-kbd { display: none; }
  .orc-logo { gap: 0.45rem; }
  .orc-logo-wordmark { font-size: 0.78rem; letter-spacing: 0.06em; }
  .orc-logo-divider, .orc-logo-sub { display: none; }
  .orc-hero-title { font-size: clamp(2.5rem, 8vw, 4rem); }
  .orc-hero-bottom { padding: 0 1.5rem; }
  .orc-article {
    padding: 3rem 1.5rem 4rem;
    /* Contain any wide children (long code lines, big mermaid SVGs, wide tables)
       so they scroll internally instead of forcing the viewport to scroll. */
    overflow-x: hidden;
  }
  .orc-article :deep(.orc-code-wrap),
  .orc-article :deep(.orc-tbl-wrap),
  .orc-article :deep(.orc-mermaid),
  .orc-article :deep(pre) { max-width: 100%; }
  .orc-menu { width: 100%; right: -100%; }
  /* CRITICAL: re-assert the open state INSIDE the @media block so it beats the
     `right: -100%` rule above (CSS specificity is equal, source order decides;
     without this the drawer stayed off-screen on mobile despite the menuOpen
     state — only the overlay dimmed). */
  .orc-menu.orc-menu-open { right: 0; }
  .orc-chapter-nav { flex-direction: column; padding: 0 1rem 2rem; }
  .orc-mobile-toc-btn { display: inline-flex; }
  .orc-article :deep(.orc-heading-anchor) { display: none; }
  /* Mermaid blocks: smaller padding, smaller "Click to enlarge" hint on phones */
  .orc-article :deep(.orc-mermaid) {
    padding: 1rem 0.5rem;
    margin: 1.25rem 0;
  }
  .orc-article :deep(.orc-mermaid[data-processed="true"])::after {
    font-size: 0.55rem;
    padding: 0.18rem 0.4rem;
    top: 0.3rem;
    right: 0.4rem;
    opacity: 1;  /* always visible on touch (no hover state) */
  }
}

/* Narrow phones (≤ 600px) — hide ← Previous / Next → nav buttons because the
   horizontal row otherwise overflows on 375-414px viewports. The drawer +
   article-bottom "Next Chapter" panel cover the same navigation. */
@media (max-width: 600px) {
  .orc-nav { gap: 0.4rem; }
  .orc-nav-controls { gap: 0.3rem; flex-wrap: nowrap; }
  /* Hide the inline prev/next buttons — chapter switching happens via the
     drawer (Chapters) or via the bottom-of-article navigation cards. */
  .orc-nav-controls .orc-nav-btn:nth-child(2),
  .orc-nav-controls .orc-nav-btn:nth-child(4) { display: none; }
  /* Larger tap targets — minimum 44x44 per touch UX guidance */
  .orc-search-btn, .orc-nav-btn { min-width: 44px; min-height: 44px; padding: 0.6rem 0.85rem; }
  .orc-mobile-toc-btn {
    right: 0.75rem;
    bottom: 0.75rem;
    padding: 0.75rem 1.1rem;
    font-size: 0.8rem;
    min-height: 44px;
  }
  /* Reduce hero to fit short viewports; the bottom strip (reading time, scroll hint) sits 2.5rem from the bottom
     and is ~6rem tall: keep the centred block above it (the camera, 2026-10-13: on a Pixel 7 "SCROLL TO READ"
     lay over the tagline) */
  .orc-hero { min-height: 70vh; padding-bottom: 6.5rem; }
  .orc-hero-title { font-size: clamp(2rem, 8vw, 3rem); }
  .orc-hero-subtitle { font-size: 0.95rem; }
}

/* Very small phones (≤ 380px — older iPhone SE, etc.) */
@media (max-width: 380px) {
  .orc-logo-wordmark { font-size: 0.7rem; }
  .orc-nav-btn { font-size: 0.7rem; padding: 0.5rem 0.65rem; }
  .orc-article { padding: 2.5rem 1rem 3rem; }
  .orc-article :deep(.orc-mermaid) {
    margin: 1rem -0.5rem;
    border-radius: 8px;
  }
}

/* Hide mobile TOC button on desktop (redundant with sidebar) */
@media (min-width: 769px) {
  .orc-mobile-toc-btn { display: none; }
}
</style>
