<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'
import { useAuthStore } from '@/stores/auth'

const { t } = useI18n()
const router = useRouter()
// D6-634: starting a match of bots is an administrator's call (POST /arena/matches refuses anyone else)
const authStore = useAuthStore()

// ── State ──
const matches = ref<any[]>([])
const matchesRead = ref<'reading' | 'read' | 'unread'>('reading')
const activeMatch = ref<any>(null)
const mapData = ref<string[][]>([])
const spectating = ref(false)
const ws = ref<WebSocket | null>(null)
const canvas = ref<HTMLCanvasElement | null>(null)
const killFeed = ref<string[]>([])
const matchResult = ref<any>(null)
// The roster and the result list loop by POSITION (colours, places): typed arrays keep vue-tsc 3 from reading a loop over
// `any` as a loop over an object, whose index would be a key. The results sort a copy: the template used to sort the
// match's own array in place during render.
const rosterAgents = computed<any[]>(() => activeMatch.value?.agents || [])
const resultAgents = computed<any[]>(() => [...(matchResult.value?.agents || [])].sort((x: any, y: any) => y.kills - x.kills))

const TILE_SIZE = 16
const MAP_SIZE = 40
const CANVAS_SIZE = MAP_SIZE * TILE_SIZE

// ── Colors ──
const TILE_COLORS: Record<string, string> = {
  floor: '#0a0e14',
  wall: '#1a2030',
  bush: '#0a1a0a',
  water: '#0a0a1e',
  crate: '#1a1408',
  extract: '#0a1a1a',
}

const TILE_BORDERS: Record<string, string> = {
  wall: '#2a3a50',
  bush: '#1a3a1a',
  crate: '#3a2a10',
  extract: '#0a4a4a',
}

const AGENT_COLORS = [
  'var(--nc-primary)', '#ff6b6b', '#ffd93d', '#6bcb77',
  '#4ecdc4', '#ff8a5c', '#a78bfa', '#f472b6',
]

// ── Sprite Drawing Helpers ──
function drawItemSprite(ctx: CanvasRenderingContext2D, type: string, cx: number, cy: number, animT: number) {
  const s = TILE_SIZE * 0.35  // sprite half-size
  ctx.save()

  if (type === 'health_kit') {
    // Green cross
    ctx.fillStyle = '#10dc81'
    ctx.shadowColor = '#10dc81'
    ctx.shadowBlur = 4
    ctx.fillRect(cx - s * 0.3, cy - s, s * 0.6, s * 2)
    ctx.fillRect(cx - s, cy - s * 0.3, s * 2, s * 0.6)
    ctx.shadowBlur = 0
  } else if (type === 'ammo_crate') {
    // Yellow box with bullet
    ctx.fillStyle = '#f5b41e'
    ctx.shadowColor = '#f5b41e'
    ctx.shadowBlur = 3
    ctx.fillRect(cx - s, cy - s * 0.7, s * 2, s * 1.4)
    ctx.shadowBlur = 0
    ctx.fillStyle = '#1a1408'
    ctx.fillRect(cx - s * 0.2, cy - s * 0.4, s * 0.4, s * 0.8) // bullet silhouette
  } else if (type === 'armor_vest') {
    // Blue shield
    ctx.fillStyle = '#3b82f6'
    ctx.shadowColor = '#3b82f6'
    ctx.shadowBlur = 4
    ctx.beginPath()
    ctx.moveTo(cx, cy - s)
    ctx.lineTo(cx + s, cy - s * 0.4)
    ctx.lineTo(cx + s * 0.7, cy + s)
    ctx.lineTo(cx, cy + s * 0.6)
    ctx.lineTo(cx - s * 0.7, cy + s)
    ctx.lineTo(cx - s, cy - s * 0.4)
    ctx.closePath()
    ctx.fill()
    ctx.shadowBlur = 0
  } else if (type === 'scope') {
    // Purple crosshair
    ctx.strokeStyle = '#a78bfa'
    ctx.shadowColor = '#a78bfa'
    ctx.shadowBlur = 4
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.arc(cx, cy, s * 0.7, 0, Math.PI * 2)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(cx - s, cy); ctx.lineTo(cx + s, cy)
    ctx.moveTo(cx, cy - s); ctx.lineTo(cx, cy + s)
    ctx.stroke()
    ctx.shadowBlur = 0
  } else if (type === 'rifle') {
    // Red long barrel
    ctx.fillStyle = '#ff6b6b'
    ctx.shadowColor = '#ff6b6b'
    ctx.shadowBlur = 4
    ctx.fillRect(cx - s * 1.2, cy - s * 0.15, s * 2.4, s * 0.3)  // barrel
    ctx.fillRect(cx + s * 0.2, cy, s * 0.3, s * 0.6)  // grip
    ctx.fillRect(cx - s * 0.6, cy - s * 0.3, s * 0.8, s * 0.6)  // body
    ctx.shadowBlur = 0
  } else if (type === 'shotgun') {
    // Orange double barrel
    ctx.fillStyle = '#ff8a5c'
    ctx.shadowColor = '#ff8a5c'
    ctx.shadowBlur = 4
    ctx.fillRect(cx - s, cy - s * 0.3, s * 2, s * 0.2)
    ctx.fillRect(cx - s, cy + s * 0.1, s * 2, s * 0.2)
    ctx.fillRect(cx + s * 0.2, cy + s * 0.1, s * 0.3, s * 0.6)
    ctx.shadowBlur = 0
  } else if (type === 'grenade') {
    // Red/orange grenade sphere
    ctx.fillStyle = '#e74c3c'
    ctx.shadowColor = '#e74c3c'
    ctx.shadowBlur = 5
    ctx.beginPath()
    ctx.arc(cx, cy + s * 0.1, s * 0.7, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0
    // Pin
    ctx.strokeStyle = '#ffd93d'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(cx, cy - s * 0.6)
    ctx.lineTo(cx + s * 0.3, cy - s)
    ctx.stroke()
  } else {
    // Unknown — glowing dot
    ctx.fillStyle = '#666'
    ctx.beginPath()
    ctx.arc(cx, cy, s * 0.5, 0, Math.PI * 2)
    ctx.fill()
  }

  ctx.restore()
}

function drawAgentSprite(ctx: CanvasRenderingContext2D, agent: any, cx: number, cy: number, color: string, animT: number) {
  const s = TILE_SIZE * 0.42
  ctx.save()

  // Body — rounded robot shape
  ctx.fillStyle = color
  ctx.shadowColor = color
  ctx.shadowBlur = agent.alive ? 10 : 0
  ctx.globalAlpha = agent.alive ? 1 : 0.25

  // Torso
  const r = s * 0.85
  ctx.beginPath()
  ctx.arc(cx, cy - s * 0.1, r, Math.PI * 0.2, Math.PI * 0.8, true) // dome head
  ctx.lineTo(cx - r * 0.9, cy + s * 0.6)
  ctx.lineTo(cx + r * 0.9, cy + s * 0.6)
  ctx.closePath()
  ctx.fill()

  // Visor / eye slit
  ctx.fillStyle = agent.alive ? '#0a0e14' : '#333'
  ctx.fillRect(cx - r * 0.6, cy - s * 0.35, r * 1.2, s * 0.25)

  // Eye glow
  if (agent.alive) {
    const pulse = 0.6 + Math.sin(animT * 0.005 + cx) * 0.4
    ctx.fillStyle = `rgba(255,255,255,${pulse})`
    ctx.fillRect(cx - r * 0.35, cy - s * 0.3, s * 0.2, s * 0.15)
    ctx.fillRect(cx + r * 0.15, cy - s * 0.3, s * 0.2, s * 0.15)
  }

  // Antenna
  ctx.strokeStyle = color
  ctx.lineWidth = 1
  ctx.beginPath()
  ctx.moveTo(cx, cy - s * 0.8)
  ctx.lineTo(cx, cy - s * 1.2)
  ctx.stroke()
  ctx.fillStyle = agent.alive ? '#fff' : '#555'
  ctx.beginPath()
  ctx.arc(cx, cy - s * 1.25, 1.5, 0, Math.PI * 2)
  ctx.fill()

  // Weapon indicator — small icon on right side
  if (agent.alive && agent.weapon) {
    ctx.fillStyle = 'rgba(255,255,255,0.5)'
    ctx.font = `${Math.round(TILE_SIZE * 0.35)}px "Fira Code", monospace`
    ctx.textAlign = 'left'
    const wIcons: Record<string, string> = { pistol: '·', rifle: '│', shotgun: '║', grenade: '●' }
    ctx.fillText(wIcons[agent.weapon] || '·', cx + r + 1, cy + 1)
  }

  ctx.shadowBlur = 0
  ctx.globalAlpha = 1
  ctx.restore()
}

function drawDeathMarker(ctx: CanvasRenderingContext2D, cx: number, cy: number, color: string) {
  ctx.save()
  // Skull-like X
  ctx.strokeStyle = color || 'rgba(240, 70, 70, 0.5)'
  ctx.globalAlpha = 0.4
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(cx - 5, cy - 5); ctx.lineTo(cx + 5, cy + 5)
  ctx.moveTo(cx + 5, cy - 5); ctx.lineTo(cx - 5, cy + 5)
  ctx.stroke()
  // Skull circle
  ctx.beginPath()
  ctx.arc(cx, cy, 4, 0, Math.PI * 2)
  ctx.stroke()
  ctx.globalAlpha = 1
  ctx.restore()
}

let animFrame = 0
const allTimeLeaderboard = ref<any[]>([])

// ── Fetch matches ──
async function fetchMatches() {
  try {
    const res = await apiClient.get('/arena/matches')
    matches.value = res.data?.matches || []
    matchesRead.value = 'read'
  } catch { if (matchesRead.value !== 'read') matchesRead.value = 'unread' }
  try {
    const res = await apiClient.get('/arena/leaderboard/robowars')
    allTimeLeaderboard.value = res.data?.leaderboard || []
  } catch { /* ignore */ }
}

async function spectateMatch(matchId: string) {
  try {
    const res = await apiClient.get(`/arena/matches/${matchId}`)
    activeMatch.value = res.data?.state || null
    mapData.value = res.data?.map || []
    matchResult.value = null
    killFeed.value = []
    spectating.value = true

    // Wait for canvas to mount, then render + connect WS
    setTimeout(() => {
      renderFrame()
      connectWs(matchId)
    }, 100)

    // Poll fallback if WS doesn't connect
    startPolling(matchId)
  } catch { /* ignore */ }
}

let pollMatchTimer: ReturnType<typeof setInterval> | null = null

function startPolling(matchId: string) {
  if (pollMatchTimer) clearInterval(pollMatchTimer)
  pollMatchTimer = setInterval(async () => {
    try {
      const res = await apiClient.get(`/arena/matches/${matchId}`)
      if (res.data?.state) {
        const oldTurn = activeMatch.value?.turn
        activeMatch.value = res.data.state

        // Process events for kill feed
        if (res.data.state.turn !== oldTurn) {
          for (const evt of (res.data.state.events || [])) {
            if (evt.type === 'kill') {
              killFeed.value.unshift(`${evt.agent} eliminated ${evt.data?.victim || '?'}`)
              if (killFeed.value.length > 15) killFeed.value.pop()
            } else if (evt.type === 'shoot' && evt.data?.hit) {
              killFeed.value.unshift(`${evt.data?.target || '?'} hit [${evt.data?.weapon}]`)
              if (killFeed.value.length > 15) killFeed.value.pop()
            }
          }
        }

        renderFrame()

        if (res.data.state.finished) {
          matchResult.value = res.data.state
          if (pollMatchTimer) clearInterval(pollMatchTimer)
        }
      }
    } catch { /* ignore */ }
  }, 600) // AI-speed poll cadence
}

async function createTestMatch() {
  try {
    const res = await apiClient.post('/arena/matches?mode=battle_royale&add_bots=5')
    await fetchMatches()
    if (res.data?.match_id) {
      spectateMatch(res.data.match_id)
    }
  } catch { /* ignore */ }
}

// ── WebSocket ──
function connectWs(matchId: string) {
  if (ws.value) { ws.value.close(); ws.value = null }

  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${proto}//${window.location.host}/api/v1/arena/ws/${matchId}`
  const socket = new WebSocket(url)

  socket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (data.type === 'initial_state') {
        activeMatch.value = data.state
        mapData.value = data.map
      } else if (data.type === 'turn_update') {
        activeMatch.value = data.state
        // Process events for kill feed
        for (const evt of (data.state?.events || [])) {
          if (evt.type === 'kill') {
            const killer = evt.agent === 'storm' ? 'STORM' : evt.data?.victim ? evt.agent : '?'
            killFeed.value.unshift(`${killer} eliminated ${evt.data?.victim || '?'} [${evt.data?.weapon || 'storm'}]`)
            if (killFeed.value.length > 15) killFeed.value.pop()
          } else if (evt.type === 'shoot' && evt.data?.hit) {
            killFeed.value.unshift(`${evt.agent} hit ${evt.data?.target || '?'} [${evt.data?.weapon}]`)
            if (killFeed.value.length > 15) killFeed.value.pop()
          }
        }
        renderFrame()
      } else if (data.type === 'match_end') {
        activeMatch.value = data.state
        matchResult.value = data.state
        renderFrame()
      }
    } catch { /* ignore */ }
  }

  socket.onclose = () => { ws.value = null }
  ws.value = socket
}

// ── Canvas Rendering ──
function renderFrame() {
  const cvs = canvas.value
  if (!cvs || !activeMatch.value) return
  const ctx = cvs.getContext('2d')
  if (!ctx) return

  animFrame++
  const state = activeMatch.value
  const map = mapData.value
  const animT = animFrame

  // Clear
  ctx.fillStyle = '#05050a'
  ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE)

  // Draw tiles
  if (map.length > 0) {
    for (let y = 0; y < MAP_SIZE; y++) {
      for (let x = 0; x < MAP_SIZE; x++) {
        const tile = map[y]?.[x] || 'floor'
        const px = x * TILE_SIZE
        const py = y * TILE_SIZE

        ctx.fillStyle = TILE_COLORS[tile] || TILE_COLORS.floor
        ctx.fillRect(px, py, TILE_SIZE, TILE_SIZE)

        // Borders for walls/bushes/crates
        if (TILE_BORDERS[tile]) {
          ctx.strokeStyle = TILE_BORDERS[tile]
          ctx.lineWidth = 0.5
          ctx.strokeRect(px + 0.5, py + 0.5, TILE_SIZE - 1, TILE_SIZE - 1)
        }

        // Grid lines (very subtle)
        ctx.strokeStyle = 'rgba(var(--nc-primary-rgb),0.015)'
        ctx.lineWidth = 0.3
        ctx.strokeRect(px, py, TILE_SIZE, TILE_SIZE)
      }
    }
  }

  // Storm circle
  if (state.storm_edge < MAP_SIZE) {
    const center = MAP_SIZE / 2 * TILE_SIZE
    const radius = (state.storm_edge / 2) * TILE_SIZE
    ctx.save()
    ctx.beginPath()
    ctx.rect(0, 0, CANVAS_SIZE, CANVAS_SIZE)
    ctx.arc(center, center, radius, 0, Math.PI * 2, true)
    ctx.fillStyle = 'rgba(240, 70, 70, 0.15)'
    ctx.fill()
    // Animated storm border
    ctx.beginPath()
    ctx.arc(center, center, radius, 0, Math.PI * 2)
    ctx.strokeStyle = `rgba(240, 70, 70, ${0.3 + Math.sin(animT * 0.05) * 0.15})`
    ctx.lineWidth = 2
    ctx.setLineDash([6, 3])
    ctx.lineDashOffset = -animT * 0.5
    ctx.stroke()
    ctx.setLineDash([])
    ctx.restore()
  }

  // Draw items with sprite icons
  for (const item of (state.items || [])) {
    const cx = item.x * TILE_SIZE + TILE_SIZE / 2
    const cy = item.y * TILE_SIZE + TILE_SIZE / 2
    // Subtle floating animation
    const floatY = Math.sin(animT * 0.04 + item.x * 0.7 + item.y * 0.5) * 1.2
    drawItemSprite(ctx, item.type, cx, cy + floatY, animT)
  }

  // Draw dead agents first (behind alive ones)
  for (let i = 0; i < (state.agents || []).length; i++) {
    const agent = state.agents[i]
    if (agent.alive) continue
    const cx = agent.x * TILE_SIZE + TILE_SIZE / 2
    const cy = agent.y * TILE_SIZE + TILE_SIZE / 2
    const color = AGENT_COLORS[i % AGENT_COLORS.length]
    drawDeathMarker(ctx, cx, cy, color)
  }

  // Draw alive agents with robot sprites
  for (let i = 0; i < (state.agents || []).length; i++) {
    const agent = state.agents[i]
    if (!agent.alive) continue

    const cx = agent.x * TILE_SIZE + TILE_SIZE / 2
    const cy = agent.y * TILE_SIZE + TILE_SIZE / 2
    const color = AGENT_COLORS[i % AGENT_COLORS.length]

    // Robot sprite
    drawAgentSprite(ctx, agent, cx, cy, color, animT)

    // Health bar (above agent)
    const barWidth = TILE_SIZE + 2
    const barHeight = 2.5
    const barX = cx - barWidth / 2
    const barY = cy - TILE_SIZE * 0.7
    const hpPct = agent.health / 100

    ctx.fillStyle = 'rgba(0,0,0,0.6)'
    ctx.fillRect(barX - 0.5, barY - 0.5, barWidth + 1, barHeight + 1)
    const hpColor = hpPct > 0.6 ? '#10dc81' : hpPct > 0.3 ? '#f5b41e' : '#ff4444'
    ctx.fillStyle = hpColor
    ctx.shadowColor = hpColor
    ctx.shadowBlur = 3
    ctx.fillRect(barX, barY, barWidth * hpPct, barHeight)
    ctx.shadowBlur = 0

    // Armor indicator (blue bar under health)
    if (agent.armor && agent.armor > 0) {
      ctx.fillStyle = '#3b82f6'
      ctx.fillRect(barX, barY + barHeight + 1, barWidth * (agent.armor / 50), 1.5)
    }

    // Name label
    ctx.fillStyle = color
    ctx.font = `bold ${Math.round(TILE_SIZE * 0.45)}px "Fira Code", monospace`
    ctx.textAlign = 'center'
    ctx.fillText(agent.name, cx, cy + TILE_SIZE * 0.65)
  }
}

// ── Polling for non-WS fallback ──
let pollTimer: ReturnType<typeof setInterval> | null = null

onMounted(() => {
  fetchMatches()
  pollTimer = setInterval(fetchMatches, 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (pollMatchTimer) clearInterval(pollMatchTimer)
  if (ws.value) ws.value.close()
})
</script>

<template>
  <div class="arena-page">
    <!-- Header -->
    <div class="arena-header">
      <button class="arena-back" @click="router.push('/games')">&larr; {{ t('arenaView.backToGames') }}</button>
      <h1 class="arena-title">
        <span class="arena-title-accent">ROBO</span>
        <span class="arena-title-dim">WARS</span>
      </h1>
      <span class="arena-subtitle">{{ t('arenaView.subtitle') }}</span>
    </div>

    <div class="arena-layout">
      <!-- Left: Match list -->
      <div class="arena-sidebar">
        <div class="arena-section-hdr">
          <span>{{ t('arenaView.matchesHeader') }}</span>
          <button v-if="authStore.isAdmin" class="arena-btn-sm" @click="createTestMatch">{{ t('arenaView.newMatch') }}</button>
        </div>
        <!-- §FESUITE (the loading sweep): "no active matches" only after the matches' own read -->
        <div v-if="matches.length === 0 && matchesRead !== 'read'" class="arena-empty" role="status">{{ matchesRead === 'unread' ? t('arenaView.matchesUnread', 'The matches could not be read just now.') : t('common.loading', 'Loading…') }}</div>
        <div v-else-if="matches.length === 0" class="arena-empty">{{ t('arenaView.noActiveMatches') }}</div>
        <div
          v-for="m in matches" :key="m.match_id"
          :class="['arena-match-card', activeMatch?.match_id === m.match_id ? 'arena-match-active' : '']"
          @click="spectateMatch(m.match_id)"
        >
          <div class="arena-match-top">
            <span class="arena-match-id">{{ m.match_id }}</span>
            <span v-if="m.finished" class="arena-match-done">{{ t('arenaView.statusEnd') }}</span>
            <span v-else-if="m.started" class="arena-match-live">{{ t('arenaView.statusLive') }}</span>
            <span v-else class="arena-match-waiting">{{ t('arenaView.statusWait') }}</span>
          </div>
          <div class="arena-match-agents" v-if="m.agent_names">
            {{ m.agent_names.join(' vs ') }}
          </div>
          <div class="arena-match-info">
            <span>{{ t('arenaView.turnLabel', { turn: m.turn }) }}</span>
            <span v-if="m.winner_name" class="arena-match-winner">{{ t('arenaView.winnerWins', { name: m.winner_name }) }}</span>
          </div>
        </div>

        <!-- All-time leaderboard -->
        <template v-if="allTimeLeaderboard.length > 0">
          <div class="arena-section-hdr" style="margin-top:1rem"><span>{{ t('arenaView.allTimeBest') }}</span></div>
          <div v-for="(s, i) in allTimeLeaderboard.slice(0, 8)" :key="s.match_id" class="arena-lb-row">
            <span class="arena-lb-rank">#{{ i + 1 }}</span>
            <span class="arena-lb-name">{{ s.agent_name }}</span>
            <span class="arena-lb-score">{{ s.score }}K</span>
          </div>
        </template>
      </div>

      <!-- Center: Game view -->
      <div class="arena-center">
        <div v-if="!spectating" class="arena-placeholder">
          <div class="arena-placeholder-icon">&#9876;</div>
          <p>{{ t('arenaView.selectMatch') }}</p>
          <p class="arena-placeholder-sub">{{ t('arenaView.selectMatchSub') }}</p>
        </div>

        <div v-else class="arena-game">
          <!-- HUD Bar -->
          <div class="arena-info-bar">
            <div class="arena-hud-section">
              <span class="arena-hud-label">{{ t('arenaView.hudTurn') }}</span>
              <span class="arena-turn">{{ activeMatch?.turn || 0 }}</span>
            </div>
            <div class="arena-hud-div"></div>
            <div class="arena-hud-section">
              <span class="arena-hud-label">{{ t('arenaView.hudAlive') }}</span>
              <span class="arena-alive">{{ activeMatch?.agents_alive || 0 }}<span class="arena-alive-total">/{{ activeMatch?.agents?.length || 0 }}</span></span>
            </div>
            <div class="arena-hud-div"></div>
            <div class="arena-hud-section">
              <span class="arena-hud-label">{{ t('arenaView.hudStorm') }}</span>
              <span class="arena-storm-val">{{ activeMatch?.storm_edge || 40 }}</span>
            </div>
            <div v-if="activeMatch?.finished" class="arena-winner">
              {{ activeMatch?.agents?.find((a: any) => a.id === activeMatch?.winner)?.name || '?' }} {{ t('arenaView.winsLabel') }}
            </div>
            <span class="arena-mode">{{ activeMatch?.mode?.replace('_',' ')?.toUpperCase() }}</span>
          </div>

          <!-- Canvas -->
          <canvas ref="canvas" :width="CANVAS_SIZE" :height="CANVAS_SIZE" class="arena-canvas" />

          <!-- Agent Roster -->
          <div class="arena-roster">
            <div
              v-for="(agent, idx) in rosterAgents"
              :key="agent.id"
              :class="['arena-agent-card', agent.alive ? '' : 'arena-agent-dead']"
              :style="{ borderLeftColor: AGENT_COLORS[idx % AGENT_COLORS.length] }"
            >
              <div class="arena-agent-top">
                <span class="arena-agent-dot" :style="{ background: AGENT_COLORS[idx % AGENT_COLORS.length] }"></span>
                <span class="arena-agent-name">{{ agent.name }}</span>
                <span v-if="!agent.alive" class="arena-agent-skull">&#9760;</span>
                <span v-if="agent.id === activeMatch?.winner" class="arena-agent-crown">&#128081;</span>
              </div>
              <template v-if="agent.alive">
                <div class="arena-agent-bars">
                  <div class="arena-bar-row">
                    <span class="arena-bar-label">{{ t('arenaView.barHp') }}</span>
                    <div class="arena-bar-track">
                      <div class="arena-bar-fill arena-bar-hp" :style="{ width: agent.health + '%' }"></div>
                    </div>
                    <span class="arena-bar-val">{{ agent.health }}</span>
                  </div>
                  <div v-if="agent.armor" class="arena-bar-row">
                    <span class="arena-bar-label">{{ t('arenaView.barAr') }}</span>
                    <div class="arena-bar-track">
                      <div class="arena-bar-fill arena-bar-ar" :style="{ width: (agent.armor / 50 * 100) + '%' }"></div>
                    </div>
                    <span class="arena-bar-val">{{ agent.armor }}</span>
                  </div>
                </div>
                <div class="arena-agent-stats">
                  <span class="arena-agent-weapon-tag">{{ agent.weapon }}</span>
                  <span v-if="agent.ammo !== undefined" class="arena-agent-ammo">{{ t('arenaView.ammoCount', { n: agent.ammo }) }}</span>
                  <span class="arena-agent-kills-tag" v-if="agent.kills">{{ t('arenaView.killsCount', { n: agent.kills }) }}</span>
                </div>
              </template>
              <div v-else class="arena-agent-elim">
                <span class="arena-elim-text">{{ t('arenaView.eliminated') }}</span>
                <span class="arena-agent-kills-tag" v-if="agent.kills">{{ t('arenaView.killsCount', { n: agent.kills }) }}</span>
              </div>
            </div>
          </div>

          <!-- Item Legend -->
          <div class="arena-legend">
            <span class="arena-legend-item"><span class="arena-legend-swatch" style="background:#10dc81">+</span>{{ t('arenaView.legendHealth') }}</span>
            <span class="arena-legend-item"><span class="arena-legend-swatch" style="background:#f5b41e">&#9632;</span>{{ t('arenaView.legendAmmo') }}</span>
            <span class="arena-legend-item"><span class="arena-legend-swatch" style="background:#3b82f6">&#9670;</span>{{ t('arenaView.legendArmor') }}</span>
            <span class="arena-legend-item"><span class="arena-legend-swatch" style="background:#a78bfa">&#8853;</span>{{ t('arenaView.legendScope') }}</span>
            <span class="arena-legend-item"><span class="arena-legend-swatch" style="background:#ff6b6b">&#9473;</span>{{ t('arenaView.legendRifle') }}</span>
            <span class="arena-legend-item"><span class="arena-legend-swatch" style="background:#ff8a5c">&#9552;</span>{{ t('arenaView.legendShotgun') }}</span>
            <span class="arena-legend-item"><span class="arena-legend-swatch" style="background:#e74c3c">&#9679;</span>{{ t('arenaView.legendGrenade') }}</span>
          </div>
        </div>
      </div>

      <!-- Right: Kill feed -->
      <div v-if="spectating" class="arena-feed">
        <div class="arena-section-hdr">{{ t('arenaView.killFeedHeader') }}</div>
        <div v-if="killFeed.length === 0" class="arena-empty">{{ t('arenaView.waitingForAction') }}</div>
        <div v-for="(msg, i) in killFeed" :key="i"
          :class="['arena-feed-item', msg.includes('eliminated') ? 'arena-feed-kill' : msg.includes('hit') ? 'arena-feed-hit' : '']">
          {{ msg }}
        </div>

        <div v-if="matchResult" class="arena-result">
          <div class="arena-result-title">{{ t('arenaView.matchOver') }}</div>
          <div class="arena-result-winner">
            {{ matchResult.agents?.find((a: any) => a.id === matchResult.winner)?.name || t('arenaView.unknownAgent') }}
          </div>
          <div class="arena-result-label">{{ t('arenaView.winsLabel') }}</div>
          <div class="arena-result-stats">
            <div v-for="(a, i) in resultAgents" :key="a.id" class="arena-result-agent">
              <span class="arena-result-pos">{{ i + 1 }}.</span>
              <span class="arena-result-name">{{ a.name }}</span>
              <span class="arena-result-k">{{ a.kills }}K</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.arena-page { padding: 1rem 1.5rem; min-height: 100vh; }

.arena-header { text-align: center; margin-bottom: 1.5rem; position: relative; }
.arena-back {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  font-size: 0.55rem; color: rgba(255,255,255,0.5); background: none; border: none;
  cursor: pointer; font-family: 'Fira Code', monospace; transition: color 0.2s;
}
.arena-back:hover { color: rgba(var(--nc-primary-rgb),0.7); }
.arena-title { font-size: 1.8rem; font-weight: 200; letter-spacing: 0.15em; }
.arena-title-accent { color: rgba(255, 107, 107, 0.9); }
.arena-title-dim { color: rgba(255, 255, 255, 0.5); margin-left: 0.3rem; }
.arena-subtitle { display: block; font-size: 0.5rem; letter-spacing: 0.2em; color: rgba(255,255,255,0.47); margin-top: 0.3rem; }

.arena-layout { display: flex; gap: 1rem; }

/* Sidebar */
.arena-sidebar { width: 220px; flex-shrink: 0; }
.arena-section-hdr {
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.15em;
  color: rgba(255,107,107,0.5); margin-bottom: 0.75rem;
  display: flex; justify-content: space-between; align-items: center;
  padding-bottom: 0.25rem; border-bottom: 1px solid rgba(255,107,107,0.06);
}
.arena-btn-sm {
  font-size: 0.5rem; padding: 0.2rem 0.5rem; border-radius: 4px;
  background: rgba(255,107,107,0.08); border: 1px solid rgba(255,107,107,0.2);
  color: rgba(255,107,107,0.7); cursor: pointer; transition: all 0.2s;
  font-family: 'Fira Code', monospace;
}
.arena-btn-sm:hover { background: rgba(255,107,107,0.15); }
.arena-empty { font-size: 0.6rem; color: rgba(255,255,255,0.47); text-align: center; padding: 0.75rem; }

.arena-match-card {
  padding: 0.5rem 0.6rem; margin-bottom: 0.35rem; border-radius: 6px;
  background: rgba(10,14,20,0.6); border: 1px solid rgba(255,107,107,0.04);
  cursor: pointer; transition: all 0.2s;
}
.arena-match-card:hover { border-color: rgba(255,107,107,0.15); background: rgba(255,107,107,0.02); }
.arena-match-active { border-color: rgba(255,107,107,0.3); background: rgba(255,107,107,0.03); }
.arena-match-top { display: flex; justify-content: space-between; align-items: center; }
/* §FESUITE: the arena's text whites 0.1-0.35 -> 0.47-0.55 alpha in the same order (4.8:1 at the faintest; the
   turn line read 1.8:1, the match id 3.2:1) */
.arena-match-id { font-size: 0.55rem; font-family: 'Fira Code', monospace; color: rgba(255,255,255,0.55); }
.arena-match-agents { font-size: 0.5rem; color: rgba(255,255,255,0.5); margin-top: 0.2rem; font-weight: 600; }
.arena-match-info { font-size: 0.45rem; color: rgba(255,255,255,0.47); margin-top: 0.2rem; display: flex; gap: 0.3rem; align-items: center; font-family: 'Fira Code', monospace; }
.arena-match-winner { color: rgba(16,220,129,0.7); font-weight: 600; margin-left: auto; }
.arena-lb-row {
  display: flex; align-items: center; gap: 0.3rem; padding: 0.2rem 0.3rem;
  font-size: 0.5rem; border-bottom: 1px solid rgba(255,255,255,0.02);
}
.arena-lb-rank { color: rgba(245,180,30,0.5); font-weight: 700; min-width: 18px; font-family: 'Fira Code', monospace; }
.arena-lb-name { color: rgba(255,255,255,0.57); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.arena-lb-score { color: rgba(255,107,107,0.6); font-family: 'Fira Code', monospace; font-weight: 600; }

.arena-match-live { font-size: 0.4rem; font-weight: 800; color: rgba(16,220,129,0.8); letter-spacing: 0.1em; padding: 0.1rem 0.3rem; background: rgba(16,220,129,0.08); border-radius: 3px; }
.arena-match-done { font-size: 0.4rem; font-weight: 800; color: rgba(255,255,255,0.52); letter-spacing: 0.1em; }
.arena-match-waiting { font-size: 0.4rem; color: rgba(245,180,30,0.6); }

/* Center */
.arena-center { flex: 1; min-width: 0; }
.arena-placeholder { text-align: center; padding: 4rem 2rem; color: rgba(255,255,255,0.47); }
.arena-placeholder-icon { font-size: 3rem; margin-bottom: 1rem; opacity: 0.4; }
.arena-placeholder-sub { font-size: 0.6rem; margin-top: 0.5rem; }

/* HUD Bar */
.arena-info-bar {
  display: flex; align-items: center; gap: 0.6rem; padding: 0.5rem 0.75rem;
  background: rgba(10,14,20,0.9); border: 1px solid rgba(255,107,107,0.06);
  border-radius: 6px 6px 0 0; font-family: 'Fira Code', monospace;
}
.arena-hud-section { display: flex; flex-direction: column; align-items: center; gap: 0.05rem; }
.arena-hud-label { font-size: 0.3rem; letter-spacing: 0.15em; color: rgba(255,255,255,0.47); font-weight: 700; }
.arena-hud-div { width: 1px; height: 24px; background: rgba(255,255,255,0.05); }
.arena-turn { font-size: 0.8rem; color: rgba(255,107,107,0.8); font-weight: 700; }
.arena-alive { font-size: 0.7rem; color: rgba(16,220,129,0.8); font-weight: 600; }
.arena-alive-total { font-size: 0.45rem; color: rgba(255,255,255,0.47); }
.arena-storm-val { font-size: 0.6rem; color: rgba(240,70,70,0.5); }
.arena-winner { margin-left: auto; font-size: 0.55rem; color: rgba(16,220,129,0.9); font-weight: 800; padding: 0.15rem 0.5rem; background: rgba(16,220,129,0.08); border-radius: 3px; }
.arena-mode { color: rgba(255,255,255,0.47); margin-left: auto; letter-spacing: 0.1em; font-size: 0.45rem; }

.arena-canvas {
  display: block; width: 100%; max-width: 640px;
  border: 1px solid rgba(255,107,107,0.06);
  border-radius: 0 0 6px 6px;
  image-rendering: pixelated;
  background: #05050a;
}

/* Agent Roster */
.arena-roster { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.5rem; }
.arena-agent-card {
  flex: 1; min-width: 120px; max-width: 180px;
  padding: 0.4rem 0.5rem; border-radius: 5px;
  background: rgba(10,14,20,0.7); border: 1px solid rgba(255,255,255,0.03);
  border-left: 3px solid; transition: all 0.2s;
}
.arena-agent-dead { opacity: 0.3; }
.arena-agent-top { display: flex; align-items: center; gap: 0.3rem; margin-bottom: 0.25rem; }
.arena-agent-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.arena-agent-name { font-size: 0.55rem; color: rgba(255,255,255,0.6); font-weight: 600; flex: 1; }
.arena-agent-skull { font-size: 0.55rem; opacity: 0.6; }
.arena-agent-crown { font-size: 0.55rem; }

.arena-agent-bars { margin-bottom: 0.2rem; }
.arena-bar-row { display: flex; align-items: center; gap: 0.25rem; margin-bottom: 0.1rem; }
.arena-bar-label { font-size: 0.35rem; color: rgba(255,255,255,0.47); width: 14px; font-family: 'Fira Code', monospace; font-weight: 600; }
.arena-bar-track { flex: 1; height: 4px; background: rgba(255,255,255,0.05); border-radius: 2px; overflow: hidden; }
.arena-bar-fill { height: 100%; border-radius: 2px; transition: width 0.3s ease; }
.arena-bar-hp { background: linear-gradient(90deg, #ff4444, #10dc81); }
.arena-bar-ar { background: #3b82f6; }
.arena-bar-val { font-size: 0.4rem; color: rgba(255,255,255,0.52); width: 18px; text-align: right; font-family: 'Fira Code', monospace; }

.arena-agent-stats { display: flex; gap: 0.3rem; flex-wrap: wrap; }
.arena-agent-weapon-tag {
  font-size: 0.4rem; padding: 0.1rem 0.25rem; border-radius: 2px;
  background: rgba(255,255,255,0.04); color: rgba(255,255,255,0.52);
  font-family: 'Fira Code', monospace;
}
.arena-agent-ammo { font-size: 0.4rem; color: rgba(245,180,30,0.4); font-family: 'Fira Code', monospace; }
.arena-agent-kills-tag { font-size: 0.4rem; color: rgba(255,107,107,0.5); font-family: 'Fira Code', monospace; font-weight: 600; }
.arena-agent-elim { display: flex; align-items: center; gap: 0.4rem; }
.arena-elim-text { font-size: 0.4rem; color: rgba(255,70,70,0.5); font-weight: 700; letter-spacing: 0.1em; font-family: 'Fira Code', monospace; }

/* Legend */
.arena-legend {
  display: flex; flex-wrap: wrap; gap: 0.6rem; margin-top: 0.4rem;
  padding: 0.3rem 0.5rem; background: rgba(10,14,20,0.3); border-radius: 4px;
}
.arena-legend-item {
  display: flex; align-items: center; gap: 0.2rem;
  font-size: 0.4rem; color: rgba(255,255,255,0.5); letter-spacing: 0.03em;
}
.arena-legend-swatch {
  display: inline-flex; align-items: center; justify-content: center;
  width: 10px; height: 10px; border-radius: 2px; font-size: 6px;
  color: rgba(0,0,0,0.8); font-weight: 700; line-height: 1;
}

/* Kill feed */
.arena-feed { width: 210px; flex-shrink: 0; }
.arena-feed-item {
  font-size: 0.5rem; color: rgba(255,255,255,0.52); padding: 0.2rem 0.3rem;
  border-bottom: 1px solid rgba(255,255,255,0.02);
  font-family: 'Fira Code', monospace; border-radius: 2px;
}
.arena-feed-kill { color: rgba(255,107,107,0.7); background: rgba(255,70,70,0.04); }
.arena-feed-hit { color: rgba(245,180,30,0.5); }

.arena-result {
  margin-top: 1rem; text-align: center; padding: 0.8rem;
  background: rgba(16,220,129,0.04); border: 1px solid rgba(16,220,129,0.15);
  border-radius: 8px;
}
.arena-result-title { font-size: 0.4rem; letter-spacing: 0.2em; color: rgba(255,255,255,0.47); }
.arena-result-winner { font-size: 0.9rem; font-weight: 700; color: rgba(16,220,129,0.9); margin: 0.3rem 0; }
.arena-result-label { font-size: 0.4rem; letter-spacing: 0.15em; color: rgba(16,220,129,0.4); margin-bottom: 0.5rem; }
.arena-result-stats { text-align: left; }
.arena-result-agent { display: flex; gap: 0.3rem; font-size: 0.45rem; padding: 0.1rem 0; font-family: 'Fira Code', monospace; }
.arena-result-pos { color: rgba(255,255,255,0.47); width: 14px; }
.arena-result-name { color: rgba(255,255,255,0.45); flex: 1; }
.arena-result-k { color: rgba(255,107,107,0.5); }

@media (max-width: 900px) {
  .arena-layout { flex-direction: column; }
  .arena-sidebar, .arena-feed { width: 100%; }
  .arena-roster { flex-direction: column; }
  .arena-agent-card { max-width: 100%; }
}
</style>
