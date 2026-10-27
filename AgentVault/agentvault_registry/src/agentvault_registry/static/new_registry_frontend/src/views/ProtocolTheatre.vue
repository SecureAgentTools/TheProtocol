<template>
  <div class="theatre-root">
    <!-- Ambient background effects -->
    <div class="theatre-bg">
      <div class="grid-overlay"></div>
      <div class="scanline"></div>
      <div class="particle-field">
        <div v-for="n in 16" :key="n" class="particle" :style="particleStyle(n)"></div>
      </div>
    </div>

    <!-- TOP BAR -->
    <header class="theatre-header">
      <div class="header-left">
        <div class="theatre-logo">
          <div class="logo-icon">
            <svg viewBox="0 0 32 32" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M16 2L4 9v14l12 7 12-7V9L16 2z" stroke="url(#logo-grad)" stroke-width="1.5" fill="none"/>
              <path d="M16 2v28M4 9l12 7 12-7M4 23l12-7 12 7" stroke="url(#logo-grad)" stroke-width="0.8" opacity="0.5"/>
              <circle cx="16" cy="16" r="3" fill="url(#logo-grad)" opacity="0.8"/>
              <defs>
                <linearGradient id="logo-grad" x1="4" y1="2" x2="28" y2="30">
                  <stop offset="0%" stop-color="#10b981"/>
                  <stop offset="100%" stop-color="#8b5cf6"/>
                </linearGradient>
              </defs>
            </svg>
          </div>
          <div class="logo-text">
            <h1>{{ t('protocolTheatreView.title') }}</h1>
            <span class="subtitle">{{ t('protocolTheatreView.subtitle') }}</span>
          </div>
        </div>
      </div>

      <div class="header-center">
        <div class="progress-track">
          <div v-for="i in 10" :key="i"
               class="progress-dot"
               :class="{ active: i <= currentBeat, current: i === currentBeat }">
            <span class="dot-number">{{ i }}</span>
          </div>
          <div class="progress-line">
            <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
          </div>
        </div>
        <div class="beat-label" v-if="currentBeat > 0">
          Beat {{ currentBeat }} of {{ totalBeats }} &mdash; {{ currentBeatData?.title }}
        </div>
        <div class="beat-label idle-label" v-else>
          Press PLAY to begin the protocol exchange
        </div>
      </div>

      <div class="header-right">
        <div class="live-indicator" :class="{ active: isPlaying }">
          <div class="live-dot"></div>
          <span>{{ isPlaying ? 'LIVE' : 'READY' }}</span>
        </div>
        <button class="play-btn" @click="togglePlay" :class="{ playing: isPlaying }"
                :disabled="SANDBOX_OFFLINE"
                :title="SANDBOX_OFFLINE ? t('protocolTheatreView.sandboxDown.playDisabled', 'Unavailable while the sandbox tier is offline') : ''">
          <svg v-if="!isPlaying" viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
            <polygon points="6,3 20,12 6,21"/>
          </svg>
          <svg v-else viewBox="0 0 24 24" fill="currentColor" width="18" height="18">
            <rect x="5" y="3" width="4" height="18"/>
            <rect x="15" y="3" width="4" height="18"/>
          </svg>
          <span>{{ isPlaying ? 'PAUSE' : 'PLAY' }}</span>
        </button>
        <button class="reset-btn" @click="resetTheatre" :disabled="currentBeat === 0 && !isPlaying" :aria-label="t('theatre.reset', 'Reset the theatre')" :title="t('theatre.reset', 'Reset the theatre')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" aria-hidden="true">
            <path d="M1 4v6h6M23 20v-6h-6"/>
            <path d="M20.49 9A9 9 0 005.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15"/>
          </svg>
        </button>
      </div>
    </header>

    <!-- ═══ SHOWCASE UNAVAILABLE — SANDBOX TIER OFFLINE (2026-08-01) ═══════════ -->
    <!-- Stated up front rather than left to surface as "Gerald returned HTTP 404" -->
    <!-- after someone presses PLAY. See SANDBOX_OFFLINE in the script block.       -->
    <div v-if="SANDBOX_OFFLINE" class="sandbox-notice" role="status">
      <div class="sandbox-notice-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" width="20" height="20">
          <circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16.5v.01"/>
        </svg>
      </div>
      <div class="sandbox-notice-text">
        <strong>{{ t('protocolTheatreView.sandboxDown.title', 'The live run is unavailable right now.') }}</strong>
        <span>{{ t('protocolTheatreView.sandboxDown.body', 'The Theatre performs a real mission against the sandbox tier, a separate set of throwaway registries kept apart from production so a demo can move real units without touching anyone\'s money. That tier is currently offline, so there is nothing for the mission to run against. Restoring it needs more capacity than the host has spare today, so the showcase will return as part of a future infrastructure upgrade. Everything else on this page is real and unaffected.') }}</span>
      </div>
    </div>

    <!-- MAIN THREE-COLUMN LAYOUT -->
    <main id="main-content" class="theatre-main app-main" tabindex="-1">
      <!-- LEFT COLUMN — GLASS GERALD -->
      <aside class="agent-panel gerald-panel" aria-labelledby="theatre-gerald-name">
        <div class="agent-card">
          <div class="agent-glow gerald-glow"></div>
          <div class="agent-avatar gerald-avatar">
            <svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="40" cy="40" r="36" stroke="#10b981" stroke-width="2" opacity="0.3"/>
              <circle cx="40" cy="40" r="28" stroke="#10b981" stroke-width="1.5" opacity="0.5"/>
              <circle cx="40" cy="40" r="20" fill="rgba(16,185,129,0.1)" stroke="#10b981" stroke-width="1"/>
              <!-- Face -->
              <circle cx="33" cy="35" r="3" fill="#10b981"/>
              <circle cx="47" cy="35" r="3" fill="#10b981"/>
              <path d="M32 47 Q40 54 48 47" stroke="#10b981" stroke-width="2" fill="none" stroke-linecap="round"/>
              <!-- Monocle -->
              <circle cx="47" cy="35" r="6" stroke="#34d399" stroke-width="1" fill="none"/>
              <line x1="53" y1="35" x2="60" y2="42" stroke="#34d399" stroke-width="1"/>
            </svg>
            <div class="avatar-ring" :class="geraldStatusClass"></div>
          </div>
          <div id="theatre-gerald-name" class="agent-name">GLASS GERALD</div>
          <div class="agent-role">CLIENT</div>
          <div class="agent-did" :title="geraldDid">
            <span class="did-prefix">did:theprotocol:</span>{{ geraldDidShort }}
          </div>
          <div class="agent-balance">
            <div class="balance-label">BALANCE</div>
            <div class="balance-value gerald-accent">
              <div v-if="!balancesLoaded" class="balance-skel-wrap"><SkeletonLoader variant="block" width="100%" height="22px" /></div>
              <span v-else-if="geraldHere === false" class="balance-unit" data-testid="theatre-gerald-elsewhere">{{ t('theatre.notOnThisFrame', 'not on this frame') }}</span>
              <template v-else>
                <span class="balance-amount">{{ formatBalance(geraldBalance) }}</span>
                <span class="balance-unit">{{ localCode }}</span>
              </template>
            </div>
          </div>
          <div class="agent-status">
            <div class="status-indicator" :class="geraldStatusClass">
              <div class="status-dot"></div>
              <span>{{ geraldStatus }}</span>
            </div>
          </div>

          <!-- Gerald capabilities -->
          <div class="agent-capabilities">
            <div class="cap-label">CAPABILITIES</div>
            <div class="cap-tags">
              <span class="cap-tag gerald-tag">contract_management</span>
              <span class="cap-tag gerald-tag">security_audit</span>
              <span class="cap-tag gerald-tag">a2a_protocol</span>
            </div>
          </div>
        </div>
      </aside>

      <!-- CENTER COLUMN — MESSAGE FLOW -->
      <section class="message-flow">
        <div class="flow-container" ref="flowContainer">
          <!-- Connection line -->
          <div class="connection-spine">
            <div class="spine-line"></div>
            <div class="spine-pulse" :class="{ active: isPlaying }"></div>
          </div>

          <!-- Error state (shared kit) — the live A2A run could not start -->
          <div v-if="missionError && visibleBeats.length === 0" class="flow-error">
            <EmptyState
              icon="mdi:connection"
              accent="danger"
              title="Couldn't reach the live agents"
              :subtitle="missionError"
              cta-label="Try again"
              @cta="togglePlay"
            />
            <p class="flow-error-hint">The Theatre streams a real Glass&nbsp;Gerald&nbsp;↔&nbsp;SYBIL exchange — it needs the live Gerald service to be reachable from this registry.</p>
          </div>

          <!-- Welcome state -->
          <div v-else-if="visibleBeats.length === 0" class="flow-welcome">
            <div class="welcome-icon">
              <svg viewBox="0 0 64 64" fill="none">
                <path d="M8 32h48M32 8v48" stroke="rgba(139,92,246,0.2)" stroke-width="1"/>
                <circle cx="32" cy="32" r="20" stroke="url(#welcome-grad)" stroke-width="1.5" stroke-dasharray="4 4">
                  <animateTransform attributeName="transform" type="rotate" from="0 32 32" to="360 32 32" dur="20s" repeatCount="indefinite"/>
                </circle>
                <circle cx="32" cy="32" r="12" stroke="url(#welcome-grad)" stroke-width="1" opacity="0.6">
                  <animateTransform attributeName="transform" type="rotate" from="360 32 32" to="0 32 32" dur="15s" repeatCount="indefinite"/>
                </circle>
                <circle cx="32" cy="32" r="4" fill="url(#welcome-grad)" opacity="0.8"/>
                <defs>
                  <linearGradient id="welcome-grad" x1="12" y1="12" x2="52" y2="52">
                    <stop offset="0%" stop-color="#10b981"/>
                    <stop offset="100%" stop-color="#8b5cf6"/>
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <p class="welcome-text">Agent-to-Agent protocol exchange between Glass Gerald and SYBIL</p>
            <p class="welcome-sub">10 live steps — security audit, threat analysis, a paid call, and conversation threading via the A2A JSON-RPC protocol. Real agents. Real units.</p>
          </div>

          <!-- Mid-stream error banner (keeps completed beats visible) -->
          <div v-if="missionError && visibleBeats.length > 0" class="flow-error-bar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            <span>{{ missionError }}</span>
            <button class="flow-error-retry" @click="togglePlay">Retry</button>
          </div>

          <!-- Message beats -->
          <div class="beats-list">
            <div v-for="beat in visibleBeats" :key="beat.number"
                 class="beat-item"
                 :class="[beat.direction, { completed: beat.number < currentBeat, current: beat.number === currentBeat }]">

              <div class="beat-header" @click="toggleBeatExpand(beat.number)">
                <div class="beat-number" :class="beat.number <= currentBeat ? 'beat-passed' : (beat.direction === 'ltr' ? 'gerald-bg' : 'sybil-bg')">
                  <svg v-if="beat.number < currentBeat" viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><polyline points="20 6 9 17 4 12" fill="none" stroke="currentColor" stroke-width="3"/></svg>
                  <span v-else>{{ beat.number }}</span>
                </div>
                <div class="beat-title">{{ beat.title }}</div>
                <div class="beat-timestamp">{{ beat.timestamp }}</div>
                <div class="beat-expand-icon" :class="{ rotated: expandedBeats.has(beat.number) }">&#9662;</div>
              </div>

              <div class="beat-arrow-track">
                <div class="arrow-sender">{{ beat.direction === 'ltr' ? 'GERALD' : 'SYBIL' }}</div>
                <div class="arrow-line" :class="beat.direction">
                  <div class="arrow-body">
                    <div class="arrow-method" :class="beat.direction === 'ltr' ? 'gerald-method' : 'sybil-method'">
                      {{ beat.method }}
                    </div>
                    <div class="arrow-head"></div>
                  </div>
                  <div class="arrow-trail"></div>
                </div>
                <div class="arrow-receiver">{{ beat.direction === 'ltr' ? 'SYBIL' : 'GERALD' }}</div>
              </div>

              <div class="beat-preview">
                <code>{{ beat.preview }}</code>
              </div>

              <!-- INLINE PAYLOAD (auto-expands on complete) -->
              <div v-if="expandedBeats.has(beat.number)" class="beat-payload">
                <div class="payload-tabs">
                  <button class="ptab" :class="{ active: beatTab(beat.number) === 'request' }" @click.stop="setBeatTab(beat.number, 'request')">REQUEST</button>
                  <button class="ptab" :class="{ active: beatTab(beat.number) === 'response' }" @click.stop="setBeatTab(beat.number, 'response')">RESPONSE</button>
                  <button class="ptab-copy" @click.stop="copyBeatPayload(beat.number)">COPY</button>
                </div>
                <pre class="json-viewer" v-html="getHighlighted(beat.number, beatTab(beat.number))"></pre>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- RIGHT COLUMN — SYBIL -->
      <aside class="agent-panel sybil-panel" aria-labelledby="theatre-sybil-name">
        <div class="agent-card">
          <div class="agent-glow sybil-glow"></div>
          <div class="agent-avatar sybil-avatar">
            <svg viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
              <circle cx="40" cy="40" r="36" stroke="#8b5cf6" stroke-width="2" opacity="0.3"/>
              <circle cx="40" cy="40" r="28" stroke="#8b5cf6" stroke-width="1.5" opacity="0.5"/>
              <circle cx="40" cy="40" r="20" fill="rgba(139,92,246,0.1)" stroke="#8b5cf6" stroke-width="1"/>
              <!-- Face — angular/analytical -->
              <rect x="30" y="32" width="6" height="6" rx="1" fill="#8b5cf6"/>
              <rect x="44" y="32" width="6" height="6" rx="1" fill="#8b5cf6"/>
              <line x1="33" y1="28" x2="28" y2="30" stroke="#a78bfa" stroke-width="1.5" stroke-linecap="round"/>
              <line x1="47" y1="28" x2="52" y2="30" stroke="#a78bfa" stroke-width="1.5" stroke-linecap="round"/>
              <path d="M34 48 L40 45 L46 48" stroke="#8b5cf6" stroke-width="2" fill="none" stroke-linecap="round"/>
              <!-- Scan beam -->
              <line x1="40" y1="20" x2="40" y2="10" stroke="#a78bfa" stroke-width="1" opacity="0.5" stroke-dasharray="2 2"/>
            </svg>
            <div class="avatar-ring" :class="sybilStatusClass"></div>
          </div>
          <div id="theatre-sybil-name" class="agent-name">SYBIL</div>
          <div class="agent-role">CONTRACTOR</div>
          <div class="agent-did" :title="sybilDid">
            <span class="did-prefix">did:theprotocol:</span>{{ sybilDidShort }}
          </div>
          <div class="agent-balance">
            <div class="balance-label">BALANCE</div>
            <div class="balance-value sybil-accent">
              <div v-if="!balancesLoaded" class="balance-skel-wrap"><SkeletonLoader variant="block" width="100%" height="22px" /></div>
              <span v-else-if="sybilHere === false" class="balance-unit" data-testid="theatre-sybil-elsewhere">{{ t('theatre.notOnThisFrame', 'not on this frame') }}</span>
              <template v-else>
                <span class="balance-amount">{{ formatBalance(sybilBalance) }}</span>
                <span class="balance-unit">{{ localCode }}</span>
              </template>
            </div>
          </div>
          <div class="agent-status">
            <div class="status-indicator" :class="sybilStatusClass">
              <div class="status-dot"></div>
              <span>{{ sybilStatus }}</span>
            </div>
          </div>

          <div class="agent-capabilities">
            <div class="cap-label">CAPABILITIES</div>
            <div class="cap-tags">
              <span class="cap-tag sybil-tag">security_analysis</span>
              <span class="cap-tag sybil-tag">threat_detection</span>
              <span class="cap-tag sybil-tag">audit_reporting</span>
            </div>
          </div>
        </div>
      </aside>
    </main>

    <!-- Bottom inspector removed — payloads now inline below each beat -->
  </div>
</template>

<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, nextTick, onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from '@/composables/useI18n'
import EmptyState from '@/components/common/EmptyState.vue'
import SkeletonLoader from '@/components/common/SkeletonLoader.vue'
import { useFrames } from '@/composables/useFrames'

const { t } = useI18n()

// ─── Types ───
interface Beat {
  number: number
  title: string
  direction: 'ltr' | 'rtl'
  method: string
  preview: string
  timestamp: string
  gerald_status: string
  sybil_status: string
  request: object
  response: object
}

// ─── Agent Data ───
const geraldDid = 'did:theprotocol:4c783710-64d5-f8c3-3f6c'
const sybilDid = 'did:theprotocol:0f254f2c-9555-a764-aadc'
const geraldDidShort = '4c783710...3f6c'
const sybilDidShort = '0f254f2c...aadc'

// §FESUITE (V0576): null until the balance was read (shown "—"): a read that failed showed 0.00 as the agent's balance
const geraldBalance = ref<number | null>(null)
const sybilBalance = ref<number | null>(null)
const balancesLoaded = ref(false)
// §FESUITE: the theatre's two agents are Frame A's, and no current frame has them; a 404 used to leave the balance at
// 0 and the page claimed "0.00 AVT" for an agent that is not here. null = not asked yet, false = this frame says no.
const geraldHere = ref<boolean | null>(null)
const sybilHere = ref<boolean | null>(null)
const { localCurrency } = useFrames()
const localCode = computed(() => String(localCurrency.value || ''))
const geraldStatus = ref('IDLE')
const sybilStatus = ref('IDLE')
const missionError = ref('')

// ─── SHOWCASE AVAILABILITY ────────────────────────────────────────────────
// The Theatre does not replay a recording: it asks Glass Gerald to execute
// GG-MISSION-08 (a real A2A exchange — Gerald pays SYBIL 50 AVT — rate-limited
// server-side per IP).
//
// 🔴 COMMANDER STANDING ORDER (2026-08-11): the Theatre stays OFF and the
// sandbox tier stays STOPPED — compute on this host is budgeted, and a public
// PLAY button that anyone can press is a standing load + 50 AVT per press.
// This is a resource decision, not breakage: the mission itself was verified
// end-to-end on 2026-08-10 via https://gerald.theprotocol.cloud (10/10 steps,
// steps_failed=0; the earlier outage was the RETIRED gerald.raphaeljeziorny.com
// vhost, fixed below, plus the stopped sandbox tier). Everything needed to
// re-enable is: flip this to false, rebuild, redeploy. Do not flip it without
// the Commander's say-so.
const SANDBOX_OFFLINE = true

// Gerald API — use public URL (proxied via nginx) or direct
const GERALD_API = (window.location.hostname === 'localhost')
  ? 'http://localhost:8035'
  : 'https://gerald.theprotocol.cloud'

// ─── Playback State ───
const currentBeat = ref(0)
const isPlaying = ref(false)
const expandedBeats = ref<Set<number>>(new Set())
const beatTabs = ref<Record<number, 'request' | 'response'>>({})
const flowContainer = ref<HTMLElement | null>(null)
let eventSource: EventSource | null = null

// Syntax highlighting cache
const highlightCache = new Map<string, string>()

function beatTab(num: number): 'request' | 'response' {
  return beatTabs.value[num] || 'request'
}
function setBeatTab(num: number, tab: 'request' | 'response') {
  beatTabs.value = { ...beatTabs.value, [num]: tab }
}
function toggleBeatExpand(num: number) {
  const next = new Set(expandedBeats.value)
  if (next.has(num)) next.delete(num); else next.add(num)
  expandedBeats.value = next
}
function getHighlighted(num: number, tab: 'request' | 'response'): string {
  const key = `${num}-${tab}`
  if (highlightCache.has(key)) return highlightCache.get(key)!
  const beat = beats.value[num - 1]
  if (!beat) return ''
  const data = tab === 'request' ? beat.request : beat.response
  const result = syntaxHighlight(JSON.stringify(data, null, 2))
  highlightCache.set(key, result)
  return result
}
function copyBeatPayload(num: number) {
  const beat = beats.value[num - 1]
  if (!beat) return
  const data = beatTab(num) === 'request' ? beat.request : beat.response
  navigator.clipboard.writeText(JSON.stringify(data, null, 2))
}

// ─── Beat Data — populated LIVE from Gerald's SSE mission stream ───
const beats = ref<Beat[]>([])

// Map step titles to A2A direction and method labels
const STEP_META: Record<string, { direction: 'ltr' | 'rtl'; method: string; gerald: string; sybil: string }> = {
  'Discovery': { direction: 'ltr', method: 'GET /agents/by-did', gerald: 'SENDING', sybil: 'IDLE' },
  'Gerald Authentication': { direction: 'ltr', method: 'POST /auth/agent/token', gerald: 'SENDING', sybil: 'IDLE' },
  'Pre-Flight Balance': { direction: 'ltr', method: 'GET /teg/balance', gerald: 'SENDING', sybil: 'IDLE' },
  'Handshake': { direction: 'ltr', method: 'message/send', gerald: 'SENDING', sybil: 'RECEIVED' },
  'Analysis': { direction: 'rtl', method: 'tasks/get (poll)', gerald: 'WAITING', sybil: 'ANALYZING' },
  'Results': { direction: 'rtl', method: 'tasks/get', gerald: 'RECEIVED', sybil: 'RESPONDING' },
  'Verification': { direction: 'ltr', method: 'GET /events', gerald: 'SENDING', sybil: 'IDLE' },
  'Payment': { direction: 'ltr', method: 'POST /teg/transfer', gerald: 'SENDING', sybil: 'RECEIVED' },
  'Acknowledgment': { direction: 'ltr', method: 'message/send (follow-up)', gerald: 'SENDING', sybil: 'RECEIVED' },
  'Post-Flight': { direction: 'ltr', method: 'GET /teg/balance', gerald: 'SENDING', sybil: 'IDLE' },
}

function metaForStep(title: string): { direction: 'ltr' | 'rtl'; method: string; gerald: string; sybil: string } {
  for (const [key, meta] of Object.entries(STEP_META)) {
    if (title.includes(key)) return meta
  }
  return { direction: 'ltr', method: title, gerald: 'SENDING', sybil: 'IDLE' }
}

// ─── Computed ───
const totalBeats = computed(() => beats.value.length || 10) // 10 expected from GG-MISSION-08
const visibleBeats = computed(() => beats.value.filter(b => b.number <= currentBeat.value))

const currentBeatData = computed(() => {
  if (currentBeat.value === 0) return null
  return beats.value.find(b => b.number === currentBeat.value) || null
})

const progressPercent = computed(() => {
  if (currentBeat.value === 0) return 0
  return (currentBeat.value / totalBeats.value) * 100
})

const geraldStatusClass = computed(() => {
  const s = geraldStatus.value.toLowerCase()
  if (s === 'sending') return 'status-sending'
  if (s === 'waiting') return 'status-waiting'
  if (s === 'received') return 'status-received'
  return 'status-idle'
})

const sybilStatusClass = computed(() => {
  const s = sybilStatus.value.toLowerCase()
  if (s === 'analyzing') return 'status-analyzing'
  if (s === 'responding') return 'status-responding'
  if (s === 'waiting') return 'status-waiting'
  if (s === 'received') return 'status-received'
  return 'status-idle'
})

// selectedBeatData and highlightedPayload removed — replaced by inline getHighlighted()

// ─── Methods ───
function particleStyle(n: number) {
  const seed = n * 7919
  const left = ((seed * 13) % 100)
  const top = ((seed * 17) % 100)
  const size = 1 + (seed % 3)
  const delay = (seed % 8000)
  const duration = 12000 + (seed % 10000)
  const opacity = 0.1 + (seed % 40) / 100
  return {
    left: `${left}%`,
    top: `${top}%`,
    width: `${size}px`,
    height: `${size}px`,
    animationDelay: `-${delay}ms`,
    animationDuration: `${duration}ms`,
    opacity
  }
}

function formatBalance(val: number | null): string {
  if (val == null) return '—'
  return val.toLocaleString(appLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function syntaxHighlight(json: string): string {
  // Escape HTML entities first to prevent XSS in JSON values
  const escaped = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return escaped.replace(
    /("(\\u[a-fA-F0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?|\bnull\b|[{}\[\],])/g,
    (match) => {
      let cls = 'json-number' // number
      if (/^"/.test(match)) {
        if (/:$/.test(match)) {
          cls = 'json-key'
          // Remove the trailing colon, wrap key, add colon back
          return `<span class="${cls}">${match.slice(0, -1)}</span>:`
        } else {
          cls = 'json-string'
        }
      } else if (/true|false/.test(match)) {
        cls = 'json-boolean'
      } else if (/null/.test(match)) {
        cls = 'json-null'
      } else if (/[{}\[\]]/.test(match)) {
        cls = 'json-brace'
      } else if (/,/.test(match)) {
        cls = 'json-comma'
      }
      return `<span class="${cls}">${match}</span>`
    }
  )
}

// ─── Balance fetching (same-origin, no auth) ───
const API = '/api/v1'
let initialGeraldBalance: number | null = null
let initialSybilBalance: number | null = null

async function fetchBalances() {
  for (const [did, setter, isGerald] of [
    [geraldDid, (v: number) => { geraldBalance.value = v }, true],
    [sybilDid, (v: number) => { sybilBalance.value = v }, false],
  ] as const) {
    try {
      const resp = await fetch(`${API}/agents/by-did/${encodeURIComponent(did)}`)
      if (resp.status === 404) { if (isGerald) geraldHere.value = false; else sybilHere.value = false; continue }
      if (resp.ok) {
        if (isGerald) geraldHere.value = true; else sybilHere.value = true
        const data = await resp.json()
        const bal = data.liquid_balance ?? data.balance
        if (bal != null) {
          const val = parseFloat(String(bal));
          (setter as (v: number) => void)(val)
          if (isGerald) initialGeraldBalance = val
          else initialSybilBalance = val
        }
      }
    } catch { /* non-critical */ }
  }
}

async function fetchSybilBalance() {
  if (sybilHere.value === false) return
  try {
    const resp = await fetch(`${API}/agents/by-did/${encodeURIComponent(sybilDid)}`)
    if (resp.ok) {
      const data = await resp.json()
      const bal = data.liquid_balance ?? data.balance
      if (bal != null) sybilBalance.value = parseFloat(String(bal))
    }
  } catch { /* non-critical */ }
}

// ─── LIVE SSE mission execution via fetch + ReadableStream ───
let abortController: AbortController | null = null

function handleSSELine(line: string) {
  if (!line.startsWith('data: ')) return
  const jsonStr = line.slice(6).trim()
  if (!jsonStr) return
  let d: any
  try { d = JSON.parse(jsonStr) } catch { return }

  if (d.type === 'mission_start') {
    geraldStatus.value = 'SENDING'
    return
  }

  if (d.type === 'step_result') {
    const stepId = d.step_id || beats.value.length + 1
    const title = d.title || `Step ${stepId}`
    const meta = metaForStep(title)
    const status = d.status || 'unknown'

    // Deep redact secrets from any object for display
    const SECRET_KEYS = new Set(['agent_jwt', 'client_secret', 'password', 'access_token', 'refresh_token', 'token', 'secret', 'api_key'])
    function redactObj(obj: any): any {
      if (obj === null || obj === undefined) return obj
      if (typeof obj === 'string') return obj
      if (Array.isArray(obj)) return obj.map(redactObj)
      if (typeof obj === 'object') {
        const safe: Record<string, any> = {}
        for (const [k, v] of Object.entries(obj)) {
          if (SECRET_KEYS.has(k) && typeof v === 'string' && v.length > 20) {
            safe[k] = v.slice(0, 20) + '...[REDACTED]'
          } else if (typeof v === 'object') {
            safe[k] = redactObj(v)
          } else {
            safe[k] = v
          }
        }
        return safe
      }
      return obj
    }

    const safeArgs = redactObj(d.request_args || d.args || {})

    const beat: Beat = {
      number: stepId,
      title,
      direction: meta.direction,
      method: meta.method,
      preview: status === 'success'
        ? (d.response?.task_id ? `task: ${String(d.response.task_id).slice(0, 24)}...` : d.response?.transaction_id ? `tx: ${String(d.response.transaction_id).slice(0, 24)}...` : title)
        : `FAILED: ${String(d.error || '').slice(0, 80)}`,
      timestamp: `Step ${stepId}/10`,
      gerald_status: meta.gerald,
      sybil_status: meta.sybil,
      request: safeArgs,
      response: redactObj(d.response || (d.error ? { error: d.error } : {})),
    }

    beats.value = [...beats.value, beat]
    currentBeat.value = stepId
    geraldStatus.value = meta.gerald
    sybilStatus.value = meta.sybil

    // Extract balances from balance-check steps
    const resp = d.response || {}
    if (title.includes('Pre-Flight') || title.includes('Post-Flight')) {
      const bal = resp.balance || resp.liquid_balance
      if (bal) geraldBalance.value = parseFloat(bal)
    }
    // Update SYBIL balance after payment step
    if (title.includes('Payment') && status === 'success') {
      // SYBIL received 50 AVT — re-fetch her balance
      fetchSybilBalance()
    }

    // Auto-expand the beat
    const next = new Set(expandedBeats.value)
    next.add(stepId)
    expandedBeats.value = next

    nextTick(() => {
      if (flowContainer.value) {
        flowContainer.value.scrollTop = flowContainer.value.scrollHeight
      }
    })
  }

  if (d.type === 'mission_complete') {
    isPlaying.value = false
    geraldStatus.value = d.steps_failed === 0 ? 'RECEIVED' : 'IDLE'
    sybilStatus.value = d.steps_failed === 0 ? 'RECEIVED' : 'IDLE'
  }
}

async function togglePlay() {
  if (isPlaying.value) {
    if (abortController) { abortController.abort(); abortController = null }
    isPlaying.value = false
    geraldStatus.value = 'IDLE'
    sybilStatus.value = 'IDLE'
    return
  }

  resetTheatre()
  isPlaying.value = true
  missionError.value = ''
  highlightCache.clear()

  abortController = new AbortController()
  const url = `${GERALD_API}/api/gerald/missions/GG-MISSION-08/run`

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { Accept: 'text/event-stream' },
      signal: abortController.signal,
    })

    if (!response.ok || !response.body) {
      missionError.value = `Gerald returned HTTP ${response.status}`
      isPlaying.value = false
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      for (const line of lines) {
        handleSSELine(line)
      }
    }
    // Stream ended naturally
    if (isPlaying.value) {
      isPlaying.value = false
      geraldStatus.value = 'RECEIVED'
      sybilStatus.value = 'RECEIVED'
    }
  } catch (e: any) {
    if (e.name !== 'AbortError') {
      missionError.value = e.message || 'Connection to Gerald failed'
      isPlaying.value = false
      geraldStatus.value = 'IDLE'
      sybilStatus.value = 'IDLE'
    }
  }
}

function resetTheatre() {
  if (abortController) { abortController.abort(); abortController = null }
  isPlaying.value = false
  currentBeat.value = 0
  beats.value = []
  expandedBeats.value = new Set()
  beatTabs.value = {}
  highlightCache.clear()
  geraldStatus.value = 'IDLE'
  sybilStatus.value = 'IDLE'
  geraldBalance.value = initialGeraldBalance
  sybilBalance.value = initialSybilBalance
  missionError.value = ''
}

onMounted(() => {
  fetchBalances().finally(() => { balancesLoaded.value = true })
})

onBeforeUnmount(() => {
  if (abortController) { abortController.abort(); abortController = null }
})
</script>

<style scoped>
/* ═══════════════════════════════════════════
   PROTOCOL THEATRE — ROOT & BACKGROUNDS
   ═══════════════════════════════════════════ */

.theatre-root {
  position: relative;
  min-height: 100vh;
  max-width: 100vw;
  background: #0a0a0f;
  color: #e2e8f0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.theatre-bg {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
}

.grid-overlay {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(16, 185, 129, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(139, 92, 246, 0.03) 1px, transparent 1px);
  background-size: 60px 60px;
}

.scanline {
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 2px,
    rgba(255, 255, 255, 0.008) 2px,
    rgba(255, 255, 255, 0.008) 4px
  );
}

.particle-field {
  position: absolute;
  inset: 0;
}

.particle {
  position: absolute;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.6), rgba(16, 185, 129, 0.3));
  animation: particle-float linear infinite;
}

@keyframes particle-float {
  0%, 100% { transform: translateY(0) translateX(0); opacity: 0; }
  10% { opacity: 1; }
  50% { transform: translateY(-40px) translateX(20px); }
  90% { opacity: 1; }
}

/* ═══════════════════════════════════════════
   HEADER
   ═══════════════════════════════════════════ */

.theatre-header {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 24px;
  background: rgba(10, 10, 15, 0.85);
  backdrop-filter: blur(20px);
  border-bottom: 1px solid rgba(139, 92, 246, 0.15);
}

.header-left {
  flex: 0 0 auto;
}

.theatre-logo {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
}

.logo-icon svg {
  width: 100%;
  height: 100%;
}

.logo-text h1 {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 3px;
  background: linear-gradient(135deg, #10b981, #8b5cf6);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1.2;
}

.logo-text .subtitle {
  font-size: 10px;
  color: #79899f;
  letter-spacing: 1.5px;
  text-transform: uppercase;
}

.header-center {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 0 32px;
}

.progress-track {
  position: relative;
  display: flex;
  align-items: center;
  gap: 24px;
}

.progress-line {
  position: absolute;
  top: 50%;
  left: 12px;
  right: 12px;
  height: 2px;
  background: rgba(255, 255, 255, 0.06);
  transform: translateY(-50%);
  z-index: 0;
  border-radius: 1px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #10b981, #8b5cf6);
  border-radius: 1px;
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
  box-shadow: 0 0 12px rgba(139, 92, 246, 0.4);
}

.progress-dot {
  position: relative;
  z-index: 1;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #1a1a2e;
  border: 2px solid rgba(255, 255, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.4s ease;
}

.progress-dot .dot-number {
  font-size: 10px;
  font-weight: 600;
  color: #79899f;  /* §FESUITE: 4.79:1 on the dot (#64748b was 3.58:1), and every other slate text here */
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  transition: color 0.4s ease;
}

.progress-dot.active {
  border-color: #8b5cf6;
  background: rgba(139, 92, 246, 0.2);
}

.progress-dot.active .dot-number {
  color: #c4b5fd;
}

.progress-dot.current {
  border-color: #10b981;
  background: rgba(16, 185, 129, 0.2);
  box-shadow: 0 0 16px rgba(16, 185, 129, 0.3);
  transform: scale(1.15);
}

.progress-dot.current .dot-number {
  color: #6ee7b7;
}

.beat-label {
  font-size: 11px;
  color: #94a3b8;
  letter-spacing: 0.5px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.idle-label {
  color: #79899f;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 0 0 auto;
}

.live-indicator {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 2px;
  color: #79899f;
  transition: all 0.3s ease;
}

.live-indicator.active {
  background: rgba(239, 68, 68, 0.1);
  border-color: rgba(239, 68, 68, 0.3);
  color: #ef4444;
}

.live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #64748b;
  transition: background 0.3s ease;
}

.live-indicator.active .live-dot {
  background: #ef4444;
  animation: live-pulse 1.5s ease-in-out infinite;
}

@keyframes live-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.4); }
  50% { box-shadow: 0 0 0 6px rgba(239, 68, 68, 0); }
}

.play-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border: 1px solid rgba(16, 185, 129, 0.4);
  border-radius: 6px;
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 2px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.play-btn:hover {
  background: rgba(16, 185, 129, 0.2);
  border-color: rgba(16, 185, 129, 0.6);
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.2);
}

.play-btn.playing {
  border-color: rgba(139, 92, 246, 0.4);
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}

.play-btn.playing:hover {
  background: rgba(139, 92, 246, 0.2);
  border-color: rgba(139, 92, 246, 0.6);
  box-shadow: 0 0 20px rgba(139, 92, 246, 0.2);
}

.play-btn svg {
  width: 14px;
  height: 14px;
}

.reset-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.03);
  color: #79899f;
  cursor: pointer;
  transition: all 0.3s ease;
}

.reset-btn:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.15);
  color: #94a3b8;
  background: rgba(255, 255, 255, 0.06);
}

.reset-btn:disabled {
  opacity: 0.3;
  cursor: default;
}

/* ═══════════════════════════════════════════
   MAIN THREE-COLUMN LAYOUT
   ═══════════════════════════════════════════ */

.theatre-main {
  position: relative;
  z-index: 5;
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 260px;
  gap: 0;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  max-width: 100vw;
}

/* ═══════════════════════════════════════════
   AGENT PANELS (LEFT + RIGHT)
   ═══════════════════════════════════════════ */

.agent-panel {
  padding: 24px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  overflow-y: auto;
  min-width: 0;
}

.agent-card {
  position: relative;
  width: 100%;
  padding: 24px 16px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(12px);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  overflow: hidden;
}

.agent-glow {
  position: absolute;
  top: -40px;
  left: 50%;
  transform: translateX(-50%);
  width: 200px;
  height: 120px;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.15;
  pointer-events: none;
}

.gerald-glow {
  background: #10b981;
}

.sybil-glow {
  background: #8b5cf6;
}

.agent-avatar {
  position: relative;
  width: 80px;
  height: 80px;
}

.agent-avatar svg {
  width: 100%;
  height: 100%;
}

.avatar-ring {
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  border: 2px solid transparent;
  transition: all 0.5s ease;
}

.avatar-ring.status-idle {
  border-color: rgba(100, 116, 139, 0.3);
}

.avatar-ring.status-sending {
  border-color: #10b981;
  animation: ring-pulse-gerald 1.5s ease-in-out infinite;
}

.avatar-ring.status-waiting {
  border-color: #f59e0b;
  animation: ring-rotate 3s linear infinite;
  border-style: dashed;
}

.avatar-ring.status-received {
  border-color: #10b981;
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.3);
}

.avatar-ring.status-analyzing {
  border-color: #8b5cf6;
  animation: ring-pulse-sybil 1.2s ease-in-out infinite;
}

.avatar-ring.status-responding {
  border-color: #8b5cf6;
  box-shadow: 0 0 20px rgba(139, 92, 246, 0.3);
}

@keyframes ring-pulse-gerald {
  0%, 100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.4); }
  50% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
}

@keyframes ring-pulse-sybil {
  0%, 100% { box-shadow: 0 0 0 0 rgba(139, 92, 246, 0.4); }
  50% { box-shadow: 0 0 0 8px rgba(139, 92, 246, 0); }
}

@keyframes ring-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.agent-name {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 2px;
  margin-top: 4px;
}

.gerald-panel .agent-name {
  color: #10b981;
}

.sybil-panel .agent-name {
  color: #8b5cf6;
}

.agent-role {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 3px;
  color: #79899f;
  padding: 2px 10px;
  border: 1px solid rgba(100, 116, 139, 0.2);
  border-radius: 3px;
  margin-top: -8px;
}

.agent-did {
  font-size: 11px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: #79899f;
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 4px;
  cursor: help;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.did-prefix {
  color: #7c8aa0; /* 5.6:1 on the panel (was #475569, 2.6:1) */
}

.agent-balance {
  width: 100%;
  text-align: center;
  padding: 12px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, 0.04);
}

.balance-label {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 2px;
  color: #7c8aa0; /* 5.6:1 on the panel (was #475569, 2.6:1) */
  margin-bottom: 4px;
}

.balance-value {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
}

.balance-amount {
  font-size: 22px;
  font-weight: 700;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  transition: all 0.6s ease;
}

.gerald-accent .balance-amount {
  color: #10b981;
}

.sybil-accent .balance-amount {
  color: #8b5cf6;
}

.balance-unit {
  font-size: 11px;
  font-weight: 600;
  color: #7c8aa0; /* 5.6:1 on the panel (was #475569, 2.6:1) */
  letter-spacing: 1px;
}

.agent-status {
  width: 100%;
}

.status-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 2px;
  transition: all 0.4s ease;
}

.status-indicator .status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  transition: all 0.4s ease;
}

.status-idle {
  background: rgba(100, 116, 139, 0.08);
  color: #79899f;
}

.status-idle .status-dot {
  background: #475569;
}

.status-sending {
  background: rgba(16, 185, 129, 0.1);
  color: #10b981;
}

.status-sending .status-dot {
  background: #10b981;
  animation: dot-pulse 1s ease-in-out infinite;
}

.status-waiting {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

.status-waiting .status-dot {
  background: #f59e0b;
  animation: dot-pulse 1.5s ease-in-out infinite;
}

.status-received {
  background: rgba(16, 185, 129, 0.1);
  color: #34d399;
}

.status-received .status-dot {
  background: #34d399;
}

.status-analyzing {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}

.status-analyzing .status-dot {
  background: #8b5cf6;
  animation: dot-pulse 0.8s ease-in-out infinite;
}

.status-responding {
  background: rgba(139, 92, 246, 0.1);
  color: #a78bfa;
}

.status-responding .status-dot {
  background: #a78bfa;
}

@keyframes dot-pulse {
  0%, 100% { transform: scale(1); opacity: 1; }
  50% { transform: scale(1.5); opacity: 0.5; }
}

.agent-capabilities {
  width: 100%;
}

.cap-label {
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 2px;
  color: #475569;
  margin-bottom: 8px;
  text-align: center;
}

.cap-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: center;
}

.cap-tag {
  font-size: 9px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  padding: 3px 8px;
  border-radius: 3px;
  letter-spacing: 0.5px;
}

.gerald-tag {
  background: rgba(16, 185, 129, 0.08);
  color: #6ee7b7;
  border: 1px solid rgba(16, 185, 129, 0.15);
}

.sybil-tag {
  background: rgba(139, 92, 246, 0.08);
  color: #c4b5fd;
  border: 1px solid rgba(139, 92, 246, 0.15);
}

/* ═══════════════════════════════════════════
   CENTER — MESSAGE FLOW
   ═══════════════════════════════════════════ */

.message-flow {
  position: relative;
  border-left: 1px solid rgba(255, 255, 255, 0.04);
  border-right: 1px solid rgba(255, 255, 255, 0.04);
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.flow-container {
  flex: 1;
  overflow-y: auto;
  padding: 24px 32px;
  scroll-behavior: smooth;
  position: relative;
}

.flow-container::-webkit-scrollbar {
  width: 4px;
}

.flow-container::-webkit-scrollbar-track {
  background: transparent;
}

.flow-container::-webkit-scrollbar-thumb {
  background: rgba(139, 92, 246, 0.2);
  border-radius: 2px;
}

.connection-spine {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 50%;
  width: 2px;
  transform: translateX(-50%);
  z-index: 0;
}

.spine-line {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    180deg,
    transparent,
    rgba(139, 92, 246, 0.1) 10%,
    rgba(139, 92, 246, 0.1) 90%,
    transparent
  );
}

.spine-pulse {
  position: absolute;
  top: 0;
  left: -2px;
  width: 6px;
  height: 40px;
  background: linear-gradient(180deg, transparent, rgba(16, 185, 129, 0.6), transparent);
  border-radius: 3px;
  opacity: 0;
}

.spine-pulse.active {
  opacity: 1;
  animation: spine-travel 3s linear infinite;
}

@keyframes spine-travel {
  0% { top: 0; }
  100% { top: calc(100% - 40px); }
}

/* Welcome state */
.flow-welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 400px;
  gap: 16px;
  padding: 40px;
}

.welcome-icon {
  width: 80px;
  height: 80px;
  opacity: 0.6;
}

.welcome-icon svg {
  width: 100%;
  height: 100%;
}

.welcome-text {
  font-size: 15px;
  color: #94a3b8;
  text-align: center;
  max-width: 400px;
  line-height: 1.6;
}

.welcome-sub {
  font-size: 12px;
  color: #475569;
  text-align: center;
  max-width: 380px;
  line-height: 1.5;
}

/* Beat items */
.beats-list {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.beat-item {
  position: relative;
  padding: 16px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.06);
  cursor: pointer;
  transition: all 0.3s ease;
  backdrop-filter: blur(8px);
}

.beat-item:hover {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.1);
}

.beat-item.selected {
  border-color: rgba(139, 92, 246, 0.4);
  box-shadow: 0 0 24px rgba(139, 92, 246, 0.1);
}

.beat-item.ltr {
  border-left: 3px solid rgba(16, 185, 129, 0.4);
}

.beat-item.rtl {
  border-left: 3px solid rgba(139, 92, 246, 0.4);
}

.beat-item.ltr.selected {
  border-color: rgba(16, 185, 129, 0.5);
  border-left: 3px solid #10b981;
  box-shadow: 0 0 24px rgba(16, 185, 129, 0.1);
}

.beat-item.rtl.selected {
  border-color: rgba(139, 92, 246, 0.5);
  border-left: 3px solid #8b5cf6;
}

/* Beat header */
.beat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.beat-number {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  flex-shrink: 0;
}

.gerald-bg {
  background: rgba(16, 185, 129, 0.15);
  color: #10b981;
  border: 1px solid rgba(16, 185, 129, 0.3);
}

.sybil-bg {
  background: rgba(139, 92, 246, 0.15);
  color: #8b5cf6;
  border: 1px solid rgba(139, 92, 246, 0.3);
}

.beat-title {
  font-size: 13px;
  font-weight: 600;
  color: #e2e8f0;
  flex: 1;
}

.beat-timestamp {
  font-size: 10px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  color: #475569;
  flex-shrink: 0;
}

/* Arrow track */
.beat-arrow-track {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.arrow-sender,
.arrow-receiver {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 2px;
  color: #475569;
  flex-shrink: 0;
  width: 54px;
  text-align: center;
}

.arrow-line {
  flex: 1;
  position: relative;
  height: 32px;
  display: flex;
  align-items: center;
}

.arrow-body {
  position: relative;
  width: 100%;
  display: flex;
  align-items: center;
}

.arrow-line.ltr .arrow-body {
  flex-direction: row;
}

.arrow-line.rtl .arrow-body {
  flex-direction: row-reverse;
}

.arrow-method {
  position: relative;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  white-space: nowrap;
  z-index: 1;
}

.gerald-method {
  background: rgba(16, 185, 129, 0.12);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.25);
}

.sybil-method {
  background: rgba(139, 92, 246, 0.12);
  color: #a78bfa;
  border: 1px solid rgba(139, 92, 246, 0.25);
}

.arrow-head {
  flex: 1;
  height: 2px;
  position: relative;
  min-width: 20px;
}

.arrow-line.ltr .arrow-head {
  background: linear-gradient(90deg, #10b981, rgba(16, 185, 129, 0.2));
}

.arrow-line.rtl .arrow-head {
  background: linear-gradient(270deg, #8b5cf6, rgba(139, 92, 246, 0.2));
}

.arrow-line.ltr .arrow-head::after {
  content: '';
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  border: 5px solid transparent;
  border-left: 8px solid #10b981;
}

.arrow-line.rtl .arrow-head::after {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  border: 5px solid transparent;
  border-right: 8px solid #8b5cf6;
}

.arrow-trail {
  position: absolute;
  inset: 0;
  border-radius: 4px;
  pointer-events: none;
}

.arrow-line.ltr .arrow-trail {
  background: linear-gradient(90deg, rgba(16, 185, 129, 0.05), transparent);
}

.arrow-line.rtl .arrow-trail {
  background: linear-gradient(270deg, rgba(139, 92, 246, 0.05), transparent);
}

.beat-preview {
  font-size: 11px;
  color: #79899f;
  padding-left: 36px;
  line-height: 1.5;
}

.beat-preview code {
  font-family: inherit;
}

/* Beat transition animations */
.beat-enter-active {
  animation: beat-slide-in 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}

.beat-leave-active {
  animation: beat-fade-out 0.3s ease;
}

@keyframes beat-slide-in {
  0% {
    opacity: 0;
    transform: translateY(30px) scale(0.97);
    filter: blur(4px);
  }
  100% {
    opacity: 1;
    transform: translateY(0) scale(1);
    filter: blur(0);
  }
}

@keyframes beat-fade-out {
  to {
    opacity: 0;
    transform: translateY(-10px);
  }
}

/* ═══════════════════════════════════════════
   PAYLOAD INSPECTOR
   ═══════════════════════════════════════════ */

.payload-inspector {
  position: relative;
  z-index: 20;
  background: rgba(10, 10, 15, 0.95);
  backdrop-filter: blur(24px);
  border-top: 1px solid rgba(139, 92, 246, 0.2);
  max-height: 45vh;
  display: flex;
  flex-direction: column;
}

.inspector-header {
  display: flex;
  align-items: center;
  padding: 12px 24px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  gap: 16px;
  flex-shrink: 0;
}

.inspector-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 2px;
  color: #94a3b8;
  flex-shrink: 0;
}

.inspector-title svg {
  color: #8b5cf6;
}

.inspector-tabs {
  display: flex;
  gap: 2px;
  background: rgba(255, 255, 255, 0.04);
  border-radius: 6px;
  padding: 2px;
}

.tab-btn {
  padding: 5px 16px;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #79899f;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 2px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tab-btn.active {
  background: rgba(139, 92, 246, 0.15);
  color: #c4b5fd;
}

.tab-btn:hover:not(.active) {
  color: #94a3b8;
}

.inspector-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.copy-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.03);
  color: #79899f;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.copy-btn:hover {
  border-color: rgba(255, 255, 255, 0.15);
  color: #94a3b8;
}

.copy-btn.copied {
  border-color: rgba(16, 185, 129, 0.3);
  color: #10b981;
}

.close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.03);
  color: #79899f;
  cursor: pointer;
  transition: all 0.2s ease;
}

.close-btn:hover {
  border-color: rgba(255, 59, 48, 0.3);
  color: #ff3b30;
}

.inspector-body {
  overflow: auto;
  padding: 16px 24px;
  flex: 1;
  min-height: 0;
}

.inspector-body::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.inspector-body::-webkit-scrollbar-track {
  background: transparent;
}

.inspector-body::-webkit-scrollbar-thumb {
  background: rgba(139, 92, 246, 0.15);
  border-radius: 3px;
}

.json-viewer {
  font-family: 'JetBrains Mono', 'Fira Code', 'SF Mono', 'Cascadia Code', monospace;
  font-size: 12px;
  line-height: 1.7;
  color: #e2e8f0;
  margin: 0;
  white-space: pre;
  tab-size: 2;
}

/* JSON syntax highlighting */
.json-viewer :deep(.json-key) {
  color: #60a5fa;
}

.json-viewer :deep(.json-string) {
  color: #34d399;
}

.json-viewer :deep(.json-number) {
  color: #f59e0b;
}

.json-viewer :deep(.json-boolean) {
  color: #f472b6;
}

.json-viewer :deep(.json-null) {
  color: #94a3b8;
  font-style: italic;
}

.json-viewer :deep(.json-brace) {
  color: #e2e8f0;
  opacity: 0.7;
}

.json-viewer :deep(.json-comma) {
  color: #475569;
}

/* Inspector transition */
.inspector-enter-active {
  animation: inspector-slide-up 0.4s cubic-bezier(0.16, 1, 0.3, 1);
}

.inspector-leave-active {
  animation: inspector-slide-down 0.3s ease;
}

@keyframes inspector-slide-up {
  0% {
    opacity: 0;
    transform: translateY(100%);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes inspector-slide-down {
  0% {
    opacity: 1;
    transform: translateY(0);
  }
  100% {
    opacity: 0;
    transform: translateY(100%);
  }
}

/* ═══════════════════════════════════════════
   RESPONSIVE
   ═══════════════════════════════════════════ */

@media (max-width: 1100px) {
  .theatre-main {
    grid-template-columns: 200px 1fr 200px;
  }

  .flow-container {
    padding: 20px 16px;
  }

  .balance-amount {
    font-size: 18px;
  }
}

@media (max-width: 860px) {
  .theatre-main {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr auto;
  }

  .agent-panel {
    padding: 12px 16px;
  }

  .agent-card {
    flex-direction: row;
    flex-wrap: wrap;
    justify-content: center;
    gap: 12px;
    padding: 12px;
  }

  .agent-avatar {
    width: 48px;
    height: 48px;
  }

  .agent-capabilities {
    display: none;
  }

  .gerald-panel {
    order: 1;
  }

  .message-flow {
    order: 2;
    border-left: none;
    border-right: none;
    border-top: 1px solid rgba(255, 255, 255, 0.04);
    border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  }

  .sybil-panel {
    order: 3;
  }

  .header-center {
    display: none;
  }
}

/* ═══════════════════════════════════════════
   INLINE PAYLOAD & COMPLETED BEAT STATES
   ═══════════════════════════════════════════ */

.beat-item.completed {
  border-left-color: #10b981;
  opacity: 0.92;
}
.beat-item.completed .beat-header {
  opacity: 0.85;
}
.beat-item.current {
  border-left-color: #10b981;
  box-shadow: 0 0 20px rgba(16, 185, 129, 0.15);
}

.beat-passed {
  background: #10b981 !important;
  border-color: #10b981 !important;
  color: #0a0a0f !important;
}

.beat-expand-icon {
  font-size: 12px;
  color: #79899f;
  transition: transform 0.2s;
  margin-left: auto;
  padding: 0 4px;
  cursor: pointer;
}
.beat-expand-icon.rotated {
  transform: rotate(180deg);
}

.beat-payload {
  margin-top: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  padding-top: 8px;
  animation: payloadSlideIn 0.3s ease-out;
}

@keyframes payloadSlideIn {
  from { opacity: 0; max-height: 0; }
  to { opacity: 1; max-height: 600px; }
}

.payload-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}

.ptab {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #94a3b8;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 10px;
  font-family: monospace;
  cursor: pointer;
  letter-spacing: 0.5px;
  transition: all 0.15s;
}
.ptab:hover { border-color: rgba(255, 255, 255, 0.15); color: #e2e8f0; }
.ptab.active {
  background: rgba(16, 185, 129, 0.12);
  border-color: rgba(16, 185, 129, 0.3);
  color: #10b981;
}

.ptab-copy {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: #79899f;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 10px;
  font-family: monospace;
  cursor: pointer;
  margin-left: auto;
  transition: all 0.15s;
}
.ptab-copy:hover { color: #e2e8f0; border-color: rgba(255, 255, 255, 0.15); }

.beat-payload .json-viewer {
  max-height: 320px;
  overflow: auto;
  font-size: 11px;
  line-height: 1.5;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(255, 255, 255, 0.05);
  border-radius: 6px;
  padding: 10px 12px;
  margin: 0;
  word-break: break-all;
  white-space: pre-wrap;
}

/* ═══════════════════════════════════════════
   BATCH-2 — shared-kit states + responsive fixes
   ═══════════════════════════════════════════ */

/* Balance loading skeleton (shared SkeletonLoader) */
.balance-skel-wrap {
  width: 84px;
  margin: 2px auto 4px;
  --nc-dark: rgba(255, 255, 255, 0.05);
}

/* Mission-error empty state (shared EmptyState) in the flow column */
.flow-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 400px;
  gap: 14px;
  padding: 40px;
}
/* keep the EmptyState + hint as a tight centered group (kit .es defaults to flex:1) */
.flow-error :deep(.es) { flex: 0 0 auto; min-height: 0; padding-bottom: 0.5rem; }
.flow-error-hint {
  max-width: 360px;
  text-align: center;
  font-size: 12px;
  line-height: 1.55;
  color: #475569;
  margin: 0;
}

/* Slim mid-stream error banner (keeps completed beats visible) */
.flow-error-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding: 10px 14px;
  border-radius: 10px;
  background: rgba(239, 68, 68, 0.08);
  border: 1px solid rgba(239, 68, 68, 0.25);
  color: #fca5a5;
  font-size: 12px;
  line-height: 1.4;
}
.flow-error-bar svg { color: #ef4444; flex-shrink: 0; }
.flow-error-bar span { flex: 1; min-width: 0; }
.flow-error-retry {
  flex-shrink: 0;
  padding: 4px 12px;
  border-radius: 6px;
  border: 1px solid rgba(239, 68, 68, 0.35);
  background: rgba(239, 68, 68, 0.12);
  color: #fca5a5;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1px;
  cursor: pointer;
  transition: all 0.2s ease;
}
.flow-error-retry:hover { background: rgba(239, 68, 68, 0.22); border-color: rgba(239, 68, 68, 0.55); color: #fecaca; }

/* Header overflow fix — keep PLAY/RESET on-screen at phone widths */
@media (max-width: 560px) {
  .theatre-header { padding: 12px 14px; gap: 10px; }
  .logo-text h1 { font-size: 13px; letter-spacing: 1.5px; }
  .logo-text .subtitle { display: none; }
  .live-indicator { display: none; }
  .header-right { gap: 8px; }
  .play-btn { padding: 7px 12px; letter-spacing: 1px; gap: 6px; }
  .play-btn span { font-size: 11px; }
  .reset-btn { width: 32px; height: 32px; }
}

/* ── Sandbox-offline notice (2026-08-01) ─────────────────────────────────
   Amber, not red: the page is working correctly and is telling you why a
   capability is unavailable. Red would read as a fault on this page.        */
.sandbox-notice {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  max-width: 1000px;
  margin: 18px auto 0;
  padding: 16px 18px;
  border: 1px solid rgba(245, 180, 30, 0.28);
  border-left: 3px solid rgba(245, 180, 30, 0.75);
  border-radius: 8px;
  background: rgba(245, 180, 30, 0.06);
}
.sandbox-notice-icon { color: rgba(245, 180, 30, 0.9); flex-shrink: 0; margin-top: 1px; }
.sandbox-notice-text { display: flex; flex-direction: column; gap: 5px; }
.sandbox-notice-text strong { font-size: 0.9rem; color: #f5d78e; font-weight: 600; }
.sandbox-notice-text span { font-size: 0.85rem; line-height: 1.65; color: #9aa5b1; }
.play-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.play-btn:disabled:hover { transform: none; }
@media (max-width: 640px) {
  .sandbox-notice { margin: 14px 12px 0; padding: 14px; gap: 11px; }
  .sandbox-notice-text span { font-size: 0.8rem; }
}

</style>
