<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const router = useRouter()

const games = ref<any[]>([])
const activeGame = ref<any>(null)
const walls = ref<[number, number][]>([])
const spectating = ref(false)
const canvas = ref<HTMLCanvasElement | null>(null)
const eventLog = ref<string[]>([])
const leaderboard = ref<any[]>([])

const TILE = 18
const MAP_SIZE = 30
const CANVAS_SIZE = MAP_SIZE * TILE

const SNAKE_COLORS = ['var(--nc-primary)', '#ff6b6b', '#ffd93d', '#6bcb77', '#a78bfa', '#ff8a5c']
const SNAKE_BODY_COLORS = ['#00a5a5', '#cc5555', '#ccae31', '#55a260', '#8670c8', '#cc704a']

let animFrame = 0
let prevSnakeAlive: Record<string, boolean> = {}
let foodParticles: { x: number; y: number; color: string; age: number; vx: number; vy: number }[] = []
let prevFoodCount = 0

// §FESUITE (the failing-reads census, 2026-10-04; TowerDefenseView's twin): a read that failed (no answer, or not ok:
// what nginx answers while the registry restarts is HTML) said "No games yet". With nothing read the sidebar says so.
const gamesFailed = ref(false)
// and "none" only once a read answered (the list starts empty: before the first answer the sidebar claims nothing)
const gamesRead = ref(false)
async function fetchGames() {
  try {
    const res = await fetch('/mcp/snake/games')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    games.value = (await res.json())?.games || []
    gamesFailed.value = false
    gamesRead.value = true
  } catch { gamesFailed.value = !games.value.length }
  try {
    const res = await fetch('/api/v1/arena/leaderboard/snake')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    leaderboard.value = (await res.json())?.leaderboard || []
  } catch { /* the board keeps what it read */ }
}

async function spectateGame(gameId: string) {
  try {
    const res = await fetch(`/mcp/snake/games/${gameId}`)
    const data = await res.json()
    activeGame.value = data?.state || null
    walls.value = data?.walls || []
    eventLog.value = []
    spectating.value = true
    foodParticles = []
    prevSnakeAlive = {}
    prevFoodCount = data?.state?.food?.length || 0
    for (const s of (data?.state?.snakes || [])) {
      prevSnakeAlive[s.id] = s.alive
    }
    setTimeout(() => { renderFrame(); startPolling(gameId) }, 100)
  } catch { /* expected */ }
}

let pollTimer: ReturnType<typeof setInterval> | null = null
function startPolling(gameId: string) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/mcp/snake/games/${gameId}`)
      const data = await res.json()
      if (data?.state) {
        const state = data.state

        // Detect deaths
        for (const s of (state.snakes || [])) {
          if (prevSnakeAlive[s.id] && !s.alive) {
            const cause = s.death_cause ? ` (${s.death_cause})` : ''
            eventLog.value.unshift(t('snakeArenaView.event.crashed', { name: s.name, cause }))
            if (eventLog.value.length > 15) eventLog.value.length = 15
          }
          prevSnakeAlive[s.id] = s.alive
        }

        // Detect food eaten (food count decreased)
        const curFoodCount = state.food?.length || 0
        if (curFoodCount < prevFoodCount) {
          // Find who grew — simple heuristic: longest snake that increased
          const eater = state.snakes?.find((s: any) => s.alive && s.length > 3)
          if (eater) {
            // Spawn particles at the eater's head
            for (let i = 0; i < 6; i++) {
              foodParticles.push({
                x: eater.head.x * TILE + TILE / 2,
                y: eater.head.y * TILE + TILE / 2,
                color: '#10dc81',
                age: 0,
                vx: (Math.random() - 0.5) * 3,
                vy: (Math.random() - 0.5) * 3,
              })
            }
          }
        }
        prevFoodCount = curFoodCount

        // Detect winner
        if (state.finished && !activeGame.value?.finished) {
          const winner = state.snakes?.find((s: any) => s.id === state.winner)
          eventLog.value.unshift(t('snakeArenaView.event.wins', { name: winner?.name || '?' }))
        }

        activeGame.value = state
        renderFrame()
      }
    } catch { /* expected */ }
  }, 400)
}

// ── Snake head sprite ──
function drawSnakeHead(ctx: CanvasRenderingContext2D, seg: any, dir: string, color: string, alive: boolean, frame: number) {
  const cx = seg.x * TILE + TILE / 2
  const cy = seg.y * TILE + TILE / 2
  const s = TILE * 0.45

  ctx.save()
  ctx.fillStyle = color
  ctx.shadowColor = color
  ctx.shadowBlur = alive ? 10 : 0

  // Rounded head
  ctx.beginPath()
  ctx.arc(cx, cy, s, 0, Math.PI * 2)
  ctx.fill()
  ctx.shadowBlur = 0

  // Darker jaw/chin area
  const dx = dir === 'east' ? 1 : dir === 'west' ? -1 : 0
  const dy = dir === 'south' ? 1 : dir === 'north' ? -1 : 0
  ctx.fillStyle = `${color}88`
  ctx.beginPath()
  ctx.arc(cx + dx * s * 0.3, cy + dy * s * 0.3, s * 0.7, 0, Math.PI * 2)
  ctx.fill()

  // Eyes
  if (alive) {
    const eyeOff = s * 0.4
    const pupilSize = 2.5
    const eyeSize = 3.5

    // Eye positions based on direction
    const e1x = cx - dy * eyeOff + dx * s * 0.15
    const e1y = cy + dx * eyeOff + dy * s * 0.15
    const e2x = cx + dy * eyeOff + dx * s * 0.15
    const e2y = cy - dx * eyeOff + dy * s * 0.15

    // White sclera
    ctx.fillStyle = '#fff'
    ctx.beginPath()
    ctx.arc(e1x, e1y, eyeSize, 0, Math.PI * 2)
    ctx.fill()
    ctx.beginPath()
    ctx.arc(e2x, e2y, eyeSize, 0, Math.PI * 2)
    ctx.fill()

    // Pupil (looks in movement direction)
    ctx.fillStyle = '#0a0a0a'
    ctx.beginPath()
    ctx.arc(e1x + dx * 1.2, e1y + dy * 1.2, pupilSize, 0, Math.PI * 2)
    ctx.fill()
    ctx.beginPath()
    ctx.arc(e2x + dx * 1.2, e2y + dy * 1.2, pupilSize, 0, Math.PI * 2)
    ctx.fill()

    // Eye shine
    ctx.fillStyle = 'rgba(255,255,255,0.7)'
    ctx.beginPath()
    ctx.arc(e1x + dx * 0.5 - 0.5, e1y + dy * 0.5 - 0.5, 1, 0, Math.PI * 2)
    ctx.fill()
    ctx.beginPath()
    ctx.arc(e2x + dx * 0.5 - 0.5, e2y + dy * 0.5 - 0.5, 1, 0, Math.PI * 2)
    ctx.fill()

    // Tongue (flicking)
    if (Math.sin(frame * 0.15) > 0.3) {
      ctx.strokeStyle = '#ff4466'
      ctx.lineWidth = 1.2
      const tongueLen = s * 0.9
      const tx = cx + dx * (s + tongueLen * 0.5)
      const ty = cy + dy * (s + tongueLen * 0.5)
      ctx.beginPath()
      ctx.moveTo(cx + dx * s, cy + dy * s)
      ctx.lineTo(tx, ty)
      ctx.stroke()
      // Fork
      ctx.beginPath()
      ctx.moveTo(tx, ty)
      ctx.lineTo(tx + (dy !== 0 ? 2 : dx * 2), ty + (dx !== 0 ? 2 : dy * 2))
      ctx.moveTo(tx, ty)
      ctx.lineTo(tx + (dy !== 0 ? -2 : dx * 2), ty + (dx !== 0 ? -2 : dy * 2))
      ctx.stroke()
    }
  } else {
    // Dead eyes (X)
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = 1.5
    ctx.globalAlpha = 0.4
    const ex = cx
    const ey = cy
    ctx.beginPath()
    ctx.moveTo(ex - 3, ey - 3); ctx.lineTo(ex + 3, ey + 3)
    ctx.moveTo(ex + 3, ey - 3); ctx.lineTo(ex - 3, ey + 3)
    ctx.stroke()
    ctx.globalAlpha = 1
  }

  ctx.restore()
}

// ── Render ──
function renderFrame() {
  const cvs = canvas.value
  if (!cvs || !activeGame.value) return
  const ctx = cvs.getContext('2d')
  if (!ctx) return

  animFrame++
  const state = activeGame.value
  const frame = animFrame

  // Clear
  ctx.fillStyle = '#050808'
  ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE)

  // Grid — subtle checker pattern
  for (let y = 0; y < MAP_SIZE; y++) {
    for (let x = 0; x < MAP_SIZE; x++) {
      if ((x + y) % 2 === 0) {
        ctx.fillStyle = 'rgba(var(--nc-primary-rgb),0.008)'
        ctx.fillRect(x * TILE, y * TILE, TILE, TILE)
      }
    }
  }

  // Walls — 3D-ish blocks
  const wallSet = new Set(walls.value.map(([wx, wy]) => `${wx},${wy}`))
  for (const [wx, wy] of walls.value) {
    const px = wx * TILE
    const py = wy * TILE

    // Shadow
    ctx.fillStyle = 'rgba(0,0,0,0.3)'
    ctx.fillRect(px + 2, py + 2, TILE, TILE)

    // Wall face
    ctx.fillStyle = '#1a2535'
    ctx.fillRect(px, py, TILE, TILE)

    // Top edge highlight
    const hasTop = !wallSet.has(`${wx},${wy - 1}`)
    if (hasTop) {
      ctx.fillStyle = '#2a3a55'
      ctx.fillRect(px, py, TILE, 2)
    }
    // Left edge highlight
    const hasLeft = !wallSet.has(`${wx - 1},${wy}`)
    if (hasLeft) {
      ctx.fillStyle = '#243050'
      ctx.fillRect(px, py, 2, TILE)
    }
    // Bottom edge shadow
    ctx.fillStyle = 'rgba(0,0,0,0.2)'
    ctx.fillRect(px, py + TILE - 1, TILE, 1)
    ctx.fillRect(px + TILE - 1, py, 1, TILE)
  }

  // Food — pulsing orbs with glow
  for (const food of (state.food || [])) {
    const cx = food.x * TILE + TILE / 2
    const cy = food.y * TILE + TILE / 2
    const isGold = food.value > 1
    const baseR = isGold ? 5.5 : 4
    const pulse = 1 + Math.sin(frame * 0.06 + food.x * 2 + food.y) * 0.15
    const r = baseR * pulse
    const color = isGold ? '#ffd93d' : '#10dc81'

    // Outer glow
    const grad = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 2.5)
    grad.addColorStop(0, `${color}30`)
    grad.addColorStop(1, `${color}00`)
    ctx.fillStyle = grad
    ctx.fillRect(cx - r * 2.5, cy - r * 2.5, r * 5, r * 5)

    // Core
    ctx.fillStyle = color
    ctx.shadowColor = color
    ctx.shadowBlur = 8
    ctx.beginPath()
    ctx.arc(cx, cy, r, 0, Math.PI * 2)
    ctx.fill()
    ctx.shadowBlur = 0

    // Highlight dot
    ctx.fillStyle = 'rgba(255,255,255,0.6)'
    ctx.beginPath()
    ctx.arc(cx - r * 0.25, cy - r * 0.3, r * 0.3, 0, Math.PI * 2)
    ctx.fill()

    // Gold food gets a star sparkle
    if (isGold) {
      ctx.strokeStyle = '#ffd93d'
      ctx.globalAlpha = 0.4 + Math.sin(frame * 0.1) * 0.3
      ctx.lineWidth = 1
      const spLen = r * 1.5
      ctx.beginPath()
      ctx.moveTo(cx - spLen, cy); ctx.lineTo(cx + spLen, cy)
      ctx.moveTo(cx, cy - spLen); ctx.lineTo(cx, cy + spLen)
      ctx.stroke()
      ctx.globalAlpha = 1
    }
  }

  // Food eat particles
  const aliveParticles: typeof foodParticles = []
  for (const p of foodParticles) {
    p.age++
    p.x += p.vx
    p.y += p.vy
    p.vy += 0.1 // gravity
    ctx.fillStyle = p.color
    ctx.globalAlpha = Math.max(0, 1 - p.age / 20)
    ctx.beginPath()
    ctx.arc(p.x, p.y, 2 - p.age * 0.08, 0, Math.PI * 2)
    ctx.fill()
    ctx.globalAlpha = 1
    if (p.age < 20) aliveParticles.push(p)
  }
  foodParticles = aliveParticles

  // Dead snakes first (ghost trail)
  for (const snake of (state.snakes || [])) {
    if (snake.alive || snake.body.length === 0) continue
    const color = SNAKE_COLORS[snake.color_index % SNAKE_COLORS.length]
    ctx.globalAlpha = 0.15
    for (let i = 0; i < snake.body.length; i++) {
      const seg = snake.body[i]
      ctx.fillStyle = color
      ctx.fillRect(seg.x * TILE + 3, seg.y * TILE + 3, TILE - 6, TILE - 6)
    }
    ctx.globalAlpha = 1
    // Death marker at head
    if (snake.head) {
      drawSnakeHead(ctx, snake.head, snake.direction, color, false, frame)
    }
  }

  // Alive snakes — full render
  for (const snake of (state.snakes || [])) {
    if (!snake.alive || snake.body.length === 0) continue
    const color = SNAKE_COLORS[snake.color_index % SNAKE_COLORS.length]
    const bodyColor = SNAKE_BODY_COLORS[snake.color_index % SNAKE_BODY_COLORS.length]

    // Body segments (tail → neck, skip head)
    for (let i = snake.body.length - 1; i >= 1; i--) {
      const seg = snake.body[i]
      const prev = snake.body[i - 1]
      const next = i < snake.body.length - 1 ? snake.body[i + 1] : null

      // Segment size tapers toward tail
      const taper = Math.max(0.5, 1 - (i / snake.body.length) * 0.4)
      const segSize = (TILE - 4) * taper
      const offset = (TILE - segSize) / 2

      // Alternating pattern (scales)
      const isEven = i % 2 === 0
      ctx.fillStyle = isEven ? color : bodyColor

      // Rounded segment
      const sx = seg.x * TILE + offset
      const sy = seg.y * TILE + offset
      const radius = segSize * 0.3
      ctx.beginPath()
      ctx.moveTo(sx + radius, sy)
      ctx.lineTo(sx + segSize - radius, sy)
      ctx.quadraticCurveTo(sx + segSize, sy, sx + segSize, sy + radius)
      ctx.lineTo(sx + segSize, sy + segSize - radius)
      ctx.quadraticCurveTo(sx + segSize, sy + segSize, sx + segSize - radius, sy + segSize)
      ctx.lineTo(sx + radius, sy + segSize)
      ctx.quadraticCurveTo(sx, sy + segSize, sx, sy + segSize - radius)
      ctx.lineTo(sx, sy + radius)
      ctx.quadraticCurveTo(sx, sy, sx + radius, sy)
      ctx.fill()

      // Scale highlight
      if (isEven) {
        ctx.fillStyle = 'rgba(255,255,255,0.06)'
        ctx.fillRect(sx + 1, sy + 1, segSize * 0.4, segSize * 0.3)
      }
    }

    // Head (drawn last, on top)
    if (snake.body.length > 0) {
      drawSnakeHead(ctx, snake.body[0], snake.direction, color, true, frame)
    }

    // Tail tip — pointed
    if (snake.body.length > 1) {
      const tail = snake.body[snake.body.length - 1]
      const preTail = snake.body[snake.body.length - 2]
      const tdx = preTail.x - tail.x
      const tdy = preTail.y - tail.y
      ctx.fillStyle = `${bodyColor}66`
      ctx.beginPath()
      const tcx = tail.x * TILE + TILE / 2
      const tcy = tail.y * TILE + TILE / 2
      ctx.moveTo(tcx - tdy * 3, tcy + tdx * 3)
      ctx.lineTo(tcx + tdy * 3, tcy - tdx * 3)
      ctx.lineTo(tcx - tdx * 5, tcy - tdy * 5)
      ctx.closePath()
      ctx.fill()
    }

    // Name + score label
    if (snake.head) {
      const hx = snake.head.x * TILE + TILE / 2
      const hy = snake.head.y * TILE

      // Label background
      const label = `${snake.name} (${snake.score})`
      ctx.font = 'bold 7px "Fira Code", monospace'
      ctx.textAlign = 'center'
      const labelW = ctx.measureText(label).width + 6
      ctx.fillStyle = 'rgba(5,8,8,0.7)'
      ctx.fillRect(hx - labelW / 2, hy - 12, labelW, 10)
      ctx.fillStyle = color
      ctx.fillText(label, hx, hy - 4)
    }
  }

  // Winner overlay
  if (state.finished) {
    const winner = state.snakes?.find((s: any) => s.id === state.winner)
    if (winner) {
      ctx.fillStyle = 'rgba(5,8,8,0.5)'
      ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE)

      const wColor = SNAKE_COLORS[winner.color_index % SNAKE_COLORS.length]
      ctx.fillStyle = wColor
      ctx.shadowColor = wColor
      ctx.shadowBlur = 20
      ctx.font = 'bold 24px "Fira Code", monospace'
      ctx.textAlign = 'center'
      ctx.fillText(t('snakeArenaView.canvas.winsOverlay', { name: winner.name }), CANVAS_SIZE / 2, CANVAS_SIZE / 2 - 10)
      ctx.shadowBlur = 0
      ctx.fillStyle = 'rgba(255,255,255,0.4)'
      ctx.font = '12px "Fira Code", monospace'
      ctx.fillText(t('snakeArenaView.canvas.winnerStats', { score: winner.score, length: winner.length, turn: state.turn }), CANVAS_SIZE / 2, CANVAS_SIZE / 2 + 15)
    }
  }
}

// Sorted snakes for scoreboard (alive first, by score desc)
const sortedSnakes = computed(() => {
  const snakes = [...(activeGame.value?.snakes || [])]
  return snakes.sort((a: any, b: any) => {
    if (a.alive !== b.alive) return a.alive ? -1 : 1
    return b.score - a.score
  })
})

let fetchTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => { fetchGames(); fetchTimer = setInterval(fetchGames, 5000) })
onUnmounted(() => { if (fetchTimer) clearInterval(fetchTimer); if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <div class="sn-page">
    <div class="sn-header">
      <button class="sn-back" @click="router.push('/games')">{{ t('snakeArenaView.header.back') }}</button>
      <h1 class="sn-title"><span class="sn-accent">{{ t('snakeArenaView.header.titleSnake') }}</span><span class="sn-dim">{{ t('snakeArenaView.header.titleArena') }}</span></h1>
      <span class="sn-subtitle">{{ t('snakeArenaView.header.subtitle') }}</span>
    </div>

    <div class="sn-layout">
      <!-- Left sidebar: matches -->
      <div class="sn-sidebar">
        <div class="sn-section-hdr">{{ t('snakeArenaView.sidebar.matchesHeader') }}</div>
        <ReadFailedNotice v-if="gamesFailed && games.length === 0" dense :retry="fetchGames" />
        <div v-else-if="gamesRead && games.length === 0" class="sn-empty">{{ t('snakeArenaView.sidebar.noGames') }}</div>
        <div v-for="g in games" :key="g.match_id"
          :class="['sn-game-card', activeGame?.match_id === g.match_id ? 'sn-active' : '']"
          @click="spectateGame(g.match_id)">
          <div class="sn-game-top">
            <span class="sn-game-names">{{ g.snake_names?.join(' vs ') || g.match_id }}</span>
            <span v-if="g.finished" class="sn-badge-done">{{ t('snakeArenaView.sidebar.badgeEnd') }}</span>
            <span v-else class="sn-badge-live">{{ t('snakeArenaView.sidebar.badgeLive') }}</span>
          </div>
          <div class="sn-game-info">
            {{ t('snakeArenaView.sidebar.turn', { turn: g.turn }) }}
            <span v-if="g.winner" class="sn-winner-mini">· {{ t('snakeArenaView.sidebar.winnerMini', { name: g.winner }) }}</span>
          </div>
        </div>

        <!-- Leaderboard -->
        <template v-if="leaderboard.length > 0">
          <div class="sn-section-hdr" style="margin-top:1.5rem">{{ t('snakeArenaView.sidebar.allTimeBest') }}</div>
          <div v-for="(s, i) in leaderboard.slice(0, 10)" :key="s.match_id" class="sn-lb-row">
            <span class="sn-lb-rank">#{{ i + 1 }}</span>
            <span class="sn-lb-name">{{ s.agent_name }}</span>
            <span class="sn-lb-score">{{ s.score }}</span>
          </div>
        </template>

        <!-- How to play -->
        <div class="sn-section-hdr" style="margin-top:1.5rem">{{ t('snakeArenaView.howToPlay.header') }}</div>
        <div class="sn-how">
          <div class="sn-how-item"><span class="sn-how-icon" style="color:#10dc81">●</span> {{ t('snakeArenaView.howToPlay.eatFood') }}</div>
          <div class="sn-how-item"><span class="sn-how-icon" style="color:#ffd93d">★</span> {{ t('snakeArenaView.howToPlay.goldFood') }}</div>
          <div class="sn-how-item"><span class="sn-how-icon" style="color:#ff4444">✕</span> {{ t('snakeArenaView.howToPlay.hitWall') }}</div>
          <div class="sn-how-item"><span class="sn-how-icon" style="color:var(--nc-primary)">♚</span> {{ t('snakeArenaView.howToPlay.lastAlive') }}</div>
        </div>
      </div>

      <!-- Center: game -->
      <div class="sn-center">
        <div v-if="!spectating" class="sn-placeholder">
          <div class="sn-placeholder-icon">&#128013;</div>
          <p>{{ t('snakeArenaView.placeholder.selectMatch') }}</p>
          <p class="sn-placeholder-sub">{{ t('snakeArenaView.placeholder.connectAgent') }}</p>
          <code class="sn-connector">npx mcp-remote https://api.theprotocol.cloud/mcp/snake/sse --header X-Arena:open</code>
        </div>

        <div v-else>
          <!-- HUD -->
          <div class="sn-info-bar">
            <div class="sn-info-section">
              <span class="sn-info-label">{{ t('snakeArenaView.hud.turn') }}</span>
              <span class="sn-turn">{{ activeGame?.turn || 0 }}</span>
            </div>
            <div class="sn-info-divider"></div>
            <div class="sn-info-section">
              <span class="sn-info-label">{{ t('snakeArenaView.hud.alive') }}</span>
              <span class="sn-alive-count">{{ activeGame?.snakes_alive || 0 }}<span class="sn-alive-total">/{{ activeGame?.snakes?.length || 0 }}</span></span>
            </div>
            <div class="sn-info-divider"></div>
            <div class="sn-info-section">
              <span class="sn-info-label">{{ t('snakeArenaView.hud.food') }}</span>
              <span class="sn-food-count">{{ activeGame?.food?.length || 0 }}</span>
            </div>
            <div v-if="activeGame?.finished" class="sn-info-winner">
              {{ t('snakeArenaView.hud.winsLabel', { name: activeGame?.snakes?.find((s: any) => s.id === activeGame?.winner)?.name }) }}
            </div>
          </div>

          <canvas ref="canvas" :width="CANVAS_SIZE" :height="CANVAS_SIZE" class="sn-canvas" />

          <!-- Scoreboard -->
          <div class="sn-scoreboard">
            <div v-for="(s, idx) in sortedSnakes" :key="s.id"
              :class="['sn-score-row', s.alive ? '' : 'sn-score-dead', s.id === activeGame?.winner ? 'sn-score-winner' : '']">
              <span class="sn-score-rank">{{ idx + 1 }}</span>
              <span class="sn-score-dot" :style="{ background: SNAKE_COLORS[s.color_index % SNAKE_COLORS.length], boxShadow: s.alive ? `0 0 4px ${SNAKE_COLORS[s.color_index % SNAKE_COLORS.length]}` : 'none' }"></span>
              <span class="sn-score-name">{{ s.name }}</span>
              <span class="sn-score-pts">{{ t('snakeArenaView.scoreboard.pts', { score: s.score }) }}</span>
              <span class="sn-score-len">{{ t('snakeArenaView.scoreboard.long', { length: s.length }) }}</span>
              <span v-if="!s.alive" class="sn-score-skull">☠</span>
              <span v-if="s.id === activeGame?.winner" class="sn-score-crown"><Icon name="mdi:crown" /></span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: event log -->
      <div v-if="spectating" class="sn-events">
        <div class="sn-section-hdr">{{ t('snakeArenaView.eventLog.header') }}</div>
        <div v-if="eventLog.length === 0" class="sn-empty">{{ t('snakeArenaView.eventLog.watching') }}</div>
        <div v-for="(msg, i) in eventLog" :key="i"
          :class="['sn-event-item', msg.includes('WINS') ? 'sn-event-win' : msg.includes('crashed') ? 'sn-event-death' : '']">
          {{ msg }}
        </div>

        <!-- Live stats -->
        <div v-if="activeGame" class="sn-live-stats">
          <div class="sn-section-hdr" style="margin-top:1rem">{{ t('snakeArenaView.liveStats.header') }}</div>
          <div class="sn-stat-row">
            <span class="sn-stat-label">{{ t('snakeArenaView.liveStats.longestSnake') }}</span>
            <span class="sn-stat-val">{{ Math.max(...(activeGame.snakes || []).filter((s: any) => s.alive).map((s: any) => s.length), 0) }}</span>
          </div>
          <div class="sn-stat-row">
            <span class="sn-stat-label">{{ t('snakeArenaView.liveStats.totalScore') }}</span>
            <span class="sn-stat-val">{{ (activeGame.snakes || []).reduce((a: number, s: any) => a + s.score, 0) }}</span>
          </div>
          <div class="sn-stat-row">
            <span class="sn-stat-label">{{ t('snakeArenaView.liveStats.foodOnBoard') }}</span>
            <span class="sn-stat-val sn-stat-food">{{ activeGame.food?.length || 0 }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- removed: connector is on games hub -->
  </div>
</template>

<style scoped>
.sn-page { padding: 1rem 1.5rem; min-height: 100vh; }
.sn-header { text-align: center; margin-bottom: 1.5rem; position: relative; }
.sn-back {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  font-size: 0.55rem; color: rgba(255,255,255,0.25); background: none; border: none;
  cursor: pointer; font-family: 'Fira Code', monospace; transition: color 0.2s;
}
.sn-back:hover { color: rgba(var(--nc-primary-rgb),0.7); }
.sn-title { font-size: 1.8rem; font-weight: 200; letter-spacing: 0.15em; }
.sn-accent { color: rgba(var(--nc-primary-rgb), 0.9); }
.sn-dim { color: rgba(255,255,255,0.25); margin-left: 0.3rem; }
.sn-subtitle { display: block; font-size: 0.55rem; letter-spacing: 0.2em; color: rgba(255,255,255,0.2); margin-top: 0.3rem; }

.sn-layout { display: flex; gap: 1rem; }
.sn-sidebar { width: 220px; flex-shrink: 0; }
.sn-center { flex: 1; min-width: 0; }
.sn-events { width: 200px; flex-shrink: 0; }

.sn-section-hdr {
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.15em;
  color: rgba(var(--nc-primary-rgb),0.5); margin-bottom: 0.5rem;
  padding-bottom: 0.25rem; border-bottom: 1px solid rgba(var(--nc-primary-rgb),0.06);
}
.sn-empty { font-size: 0.6rem; color: rgba(255,255,255,0.12); text-align: center; padding: 0.75rem; }

/* Game cards */
.sn-game-card {
  padding: 0.5rem 0.6rem; margin-bottom: 0.35rem; border-radius: 6px;
  background: rgba(10,14,20,0.6); border: 1px solid rgba(var(--nc-primary-rgb),0.04);
  cursor: pointer; transition: all 0.2s;
}
.sn-game-card:hover { border-color: rgba(var(--nc-primary-rgb),0.15); background: rgba(var(--nc-primary-rgb),0.02); }
.sn-active { border-color: rgba(var(--nc-primary-rgb),0.3); background: rgba(var(--nc-primary-rgb),0.03); }
.sn-game-top { display: flex; justify-content: space-between; align-items: center; gap: 0.3rem; }
.sn-game-names { font-size: 0.55rem; color: rgba(255,255,255,0.6); font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sn-game-info { font-size: 0.45rem; color: rgba(255,255,255,0.2); margin-top: 0.15rem; font-family: 'Fira Code', monospace; }
.sn-winner-mini { color: rgba(245,180,30,0.5); }
.sn-badge-live { font-size: 0.4rem; font-weight: 800; color: rgba(16,220,129,0.8); letter-spacing: 0.1em; padding: 0.1rem 0.3rem; background: rgba(16,220,129,0.08); border-radius: 3px; flex-shrink: 0; }
.sn-badge-done { font-size: 0.4rem; font-weight: 800; color: rgba(255,255,255,0.3); letter-spacing: 0.1em; padding: 0.1rem 0.3rem; background: rgba(255,255,255,0.03); border-radius: 3px; flex-shrink: 0; }

/* How to play */
.sn-lb-row {
  display: flex; align-items: center; gap: 0.3rem; padding: 0.2rem 0.3rem;
  font-size: 0.5rem; border-bottom: 1px solid rgba(255,255,255,0.02);
}
.sn-lb-rank { color: rgba(245,180,30,0.5); font-weight: 700; min-width: 18px; font-family: 'Fira Code', monospace; }
.sn-lb-name { color: rgba(255,255,255,0.45); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.sn-lb-score { color: rgba(var(--nc-primary-rgb),0.6); font-family: 'Fira Code', monospace; font-weight: 600; }

.sn-how { padding: 0.3rem; }
.sn-how-item { font-size: 0.5rem; color: rgba(255,255,255,0.25); padding: 0.2rem 0; display: flex; align-items: center; gap: 0.3rem; }
.sn-how-icon { font-size: 0.5rem; width: 12px; text-align: center; flex-shrink: 0; }

/* Placeholder */
.sn-placeholder { text-align: center; padding: 4rem 2rem; color: rgba(255,255,255,0.12); }
.sn-placeholder-icon { font-size: 3rem; margin-bottom: 1rem; opacity: 0.4; }
.sn-placeholder-sub { font-size: 0.65rem; margin-top: 0.5rem; }
.sn-connector {
  display: inline-block; margin-top: 1rem; padding: 0.3rem 0.8rem;
  background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.1);
  border-radius: 4px; font-size: 0.5rem; color: rgba(var(--nc-primary-rgb),0.4);
  font-family: 'Fira Code', monospace;
}

/* HUD */
.sn-info-bar {
  display: flex; align-items: center; gap: 0.6rem; padding: 0.5rem 0.75rem;
  background: rgba(10,14,20,0.9); border: 1px solid rgba(var(--nc-primary-rgb),0.06);
  border-radius: 6px 6px 0 0; font-family: 'Fira Code', monospace;
}
.sn-info-section { display: flex; flex-direction: column; align-items: center; gap: 0.1rem; }
.sn-info-label { font-size: 0.3rem; letter-spacing: 0.15em; color: rgba(255,255,255,0.12); font-weight: 700; }
.sn-turn { font-size: 0.8rem; color: rgba(var(--nc-primary-rgb),0.8); font-weight: 700; }
.sn-alive-count { font-size: 0.7rem; color: rgba(16,220,129,0.8); font-weight: 600; }
.sn-alive-total { font-size: 0.45rem; color: rgba(255,255,255,0.2); }
.sn-food-count { font-size: 0.65rem; color: rgba(16,220,129,0.6); }
.sn-info-divider { width: 1px; height: 24px; background: rgba(255,255,255,0.05); }
.sn-info-winner { margin-left: auto; font-size: 0.55rem; color: rgba(16,220,129,0.9); font-weight: 800; letter-spacing: 0.05em; padding: 0.15rem 0.5rem; background: rgba(16,220,129,0.08); border-radius: 3px; }

.sn-canvas {
  display: block; width: 100%; max-width: 540px;
  border: 1px solid rgba(var(--nc-primary-rgb),0.06);
  border-radius: 0 0 6px 6px;
  image-rendering: pixelated;
  background: #050808;
}

/* Scoreboard */
.sn-scoreboard {
  display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.5rem;
}
.sn-score-row {
  display: flex; align-items: center; gap: 0.35rem; padding: 0.3rem 0.5rem;
  background: rgba(10,14,20,0.6); border-radius: 5px; font-size: 0.5rem;
  border: 1px solid rgba(255,255,255,0.02); transition: all 0.2s;
}
.sn-score-dead { opacity: 0.35; }
.sn-score-winner { border-color: rgba(16,220,129,0.2); background: rgba(16,220,129,0.04); }
.sn-score-rank { color: rgba(255,255,255,0.15); font-weight: 700; min-width: 10px; font-family: 'Fira Code', monospace; }
.sn-score-dot { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
.sn-score-name { color: rgba(255,255,255,0.6); font-weight: 600; }
.sn-score-pts { color: rgba(245,180,30,0.5); font-family: 'Fira Code', monospace; }
.sn-score-len { color: rgba(255,255,255,0.2); font-family: 'Fira Code', monospace; }
.sn-score-skull { font-size: 0.5rem; opacity: 0.5; }
.sn-score-crown { font-size: 0.55rem; }

/* Event log */
.sn-event-item {
  font-size: 0.5rem; color: rgba(255,255,255,0.3); padding: 0.2rem 0.3rem;
  border-bottom: 1px solid rgba(255,255,255,0.02);
  font-family: 'Fira Code', monospace; border-radius: 2px;
}
.sn-event-win { color: rgba(16,220,129,0.8); background: rgba(16,220,129,0.04); font-weight: 600; }
.sn-event-death { color: rgba(255,107,107,0.6); background: rgba(255,70,70,0.04); }

/* Live stats */
.sn-live-stats { }
.sn-stat-row { display: flex; justify-content: space-between; padding: 0.15rem 0; font-size: 0.5rem; }
.sn-stat-label { color: rgba(255,255,255,0.2); }
.sn-stat-val { color: rgba(255,255,255,0.4); font-family: 'Fira Code', monospace; }
.sn-stat-food { color: rgba(16,220,129,0.6); }

/* Footer */
.sn-footer {
  margin-top: 1.5rem; text-align: center; font-size: 0.55rem; color: rgba(255,255,255,0.12);
}
.sn-footer code {
  display: inline-block; margin-left: 0.5rem; padding: 0.2rem 0.6rem;
  background: rgba(var(--nc-primary-rgb),0.03); border: 1px solid rgba(var(--nc-primary-rgb),0.08);
  border-radius: 4px; font-family: 'Fira Code', monospace; color: rgba(var(--nc-primary-rgb),0.35);
  font-size: 0.5rem;
}

@media (max-width: 768px) {
  .sn-layout { flex-direction: column; }
  .sn-sidebar, .sn-events { width: 100%; }
}
</style>
