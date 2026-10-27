<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { apiClient } from '@/services/api/client'
import { useI18n } from '@/composables/useI18n'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'

const { t } = useI18n()
const router = useRouter()

const games = ref<any[]>([])
const activeGame = ref<any>(null)
const mapData = ref<string[][]>([])
const spectating = ref(false)
const canvas = ref<HTMLCanvasElement | null>(null)
const eventLog = ref<string[]>([])
const leaderboard = ref<any[]>([])

const TILE_W = 16
const TILE_H = 16
const MAP_W = 50
const MAP_H = 30
const CANVAS_W = MAP_W * TILE_W
const CANVAS_H = MAP_H * TILE_H

const TILE_COLORS: Record<string, string> = {
  grass: '#0c1a0c',
  path: '#1a1408',
  spawn: '#1a0a0a',
  exit: '#0a1a0a',
  tower: '#0a0a2a',
  water: '#0a0e1e',
  rock: '#1a1a1a',
}

const ENEMY_COLORS: Record<string, string> = {
  grunt: '#ff4444',
  runner: '#ffaa22',
  tank: '#aa44ff',
  boss: '#ff0066',
}

const TOWER_COLORS: Record<string, string> = {
  basic: 'var(--nc-primary)',
  sniper: '#4ecdc4',
  splash: '#ff8a5c',
  slow: '#6bcb77',
  laser: '#a78bfa',
}

const TOWER_ICONS: Record<string, string> = {
  basic: 'cannon',
  sniper: 'crosshair',
  splash: 'burst',
  slow: 'snowflake',
  laser: 'beam',
}

let animFrame = 0
let projectiles: { x: number; y: number; tx: number; ty: number; color: string; age: number; type: string }[] = []
let floatingTexts: { x: number; y: number; text: string; color: string; age: number }[] = []
let prevEnemyCount = 0

// ── Offscreen map cache (big perf win: 1500 tiles drawn once) ──
let mapCanvas: HTMLCanvasElement | null = null
let mapCacheDirty = true

function buildMapCache(map: string[][]) {
  if (!mapCanvas) {
    mapCanvas = document.createElement('canvas')
    mapCanvas.width = CANVAS_W
    mapCanvas.height = CANVAS_H
  }
  const ctx = mapCanvas.getContext('2d')
  if (!ctx) return

  ctx.fillStyle = '#050808'
  ctx.fillRect(0, 0, CANVAS_W, CANVAS_H)

  for (let y = 0; y < MAP_H; y++) {
    for (let x = 0; x < MAP_W; x++) {
      const tile = map[y]?.[x] || 'grass'
      const px = x * TILE_W
      const py = y * TILE_H

      ctx.fillStyle = TILE_COLORS[tile] || TILE_COLORS.grass
      ctx.fillRect(px, py, TILE_W, TILE_H)

      if (tile === 'path') {
        ctx.fillStyle = 'rgba(245,180,30,0.04)'
        ctx.fillRect(px, py, TILE_W, TILE_H)
        ctx.strokeStyle = 'rgba(245,180,30,0.06)'
        ctx.lineWidth = 0.5
        ctx.strokeRect(px + 0.5, py + 0.5, TILE_W - 1, TILE_H - 1)
      } else if (tile === 'spawn') {
        ctx.fillStyle = 'rgba(255,70,70,0.06)'
        ctx.fillRect(px, py, TILE_W, TILE_H)
        ctx.strokeStyle = 'rgba(255,70,70,0.15)'
        ctx.lineWidth = 1
        ctx.strokeRect(px + 1, py + 1, TILE_W - 2, TILE_H - 2)
      } else if (tile === 'exit') {
        ctx.fillStyle = 'rgba(16,220,129,0.08)'
        ctx.fillRect(px, py, TILE_W, TILE_H)
        ctx.strokeStyle = 'rgba(16,220,129,0.2)'
        ctx.lineWidth = 1
        ctx.strokeRect(px + 1, py + 1, TILE_W - 2, TILE_H - 2)
      } else if (tile === 'water') {
        ctx.fillStyle = 'rgba(30,80,180,0.04)'
        ctx.fillRect(px, py, TILE_W, TILE_H)
      } else if (tile === 'rock') {
        ctx.strokeStyle = 'rgba(255,255,255,0.03)'
        ctx.lineWidth = 0.5
        ctx.strokeRect(px + 2, py + 2, TILE_W - 4, TILE_H - 4)
      }
    }
  }
  mapCacheDirty = false
}

// §FESUITE (the failing-reads census, 2026-10-04): a read that failed (no answer, or not ok: what nginx answers while the
// registry restarts is HTML) said "No games yet" and "No scores yet". With nothing read the sidebar says so.
const gamesFailed = ref(false)
const scoresFailed = ref(false)
// and "none" only once a read answered (the lists start empty: before the first answer the sidebar claims nothing)
const gamesRead = ref(false)
const scoresRead = ref(false)
async function fetchGames() {
  try {
    const res = await fetch('/mcp/td/games')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    games.value = data?.games || []
    gamesFailed.value = false
    gamesRead.value = true
  } catch { gamesFailed.value = !games.value.length }
  try {
    const res = await fetch('/mcp/td/leaderboard')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const data = await res.json()
    leaderboard.value = data?.leaderboard || []
    scoresFailed.value = false
    scoresRead.value = true
  } catch { scoresFailed.value = !leaderboard.value.length }
}

async function spectateGame(gameId: string) {
  try {
    const res = await fetch(`/mcp/td/games/${gameId}`)
    const data = await res.json()
    activeGame.value = data?.state || null
    mapData.value = data?.map || []
    eventLog.value = []
    spectating.value = true
    projectiles = []
    floatingTexts = []
    mapCacheDirty = true
    prevEnemyCount = data?.state?.enemies?.length || 0
    setTimeout(() => {
      renderFrame()
      startPolling(gameId)
    }, 100)
  } catch { /* expected */ }
}

let pollTimer: ReturnType<typeof setInterval> | null = null

function startPolling(gameId: string) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/mcp/td/games/${gameId}`)
      const data = await res.json()
      if (data?.state) {
        const oldWave = activeGame.value?.wave
        const oldKills = activeGame.value?.total_kills || 0
        const newKills = data.state.total_kills || 0
        activeGame.value = data.state

        // Generate projectile effects from towers to nearby enemies
        if (newKills > oldKills) {
          const killDiff = newKills - oldKills
          for (let k = 0; k < Math.min(killDiff, 5); k++) {
            // Pick random tower and random enemy position for visual
            const towers = data.state.towers || []
            const enemies = data.state.enemies || []
            if (towers.length > 0) {
              const tw = towers[Math.floor(Math.random() * towers.length)]
              const ex = enemies.length > 0 ? enemies[Math.floor(Math.random() * enemies.length)].x : tw.x + 3
              const ey = enemies.length > 0 ? enemies[Math.floor(Math.random() * enemies.length)].y : tw.y + 2
              projectiles.push({
                x: tw.x * TILE_W + TILE_W / 2, y: tw.y * TILE_H + TILE_H / 2,
                tx: ex * TILE_W + TILE_W / 2, ty: ey * TILE_H + TILE_H / 2,
                color: TOWER_COLORS[tw.type] || '#0dd', age: 0, type: tw.type
              })
              floatingTexts.push({
                x: ex * TILE_W + TILE_W / 2, y: ey * TILE_H,
                text: '+' + (tw.type === 'sniper' ? '40' : tw.type === 'laser' ? '35' : '15'),
                color: TOWER_COLORS[tw.type] || '#0dd', age: 0
              })
            }
          }
        }

        // Detect new enemies killed
        const curEnemies = data.state.enemies?.length || 0
        if (curEnemies < prevEnemyCount && newKills > oldKills) {
          eventLog.value.unshift(t('towerDefenseView.eventLog.kill', { count: newKills - oldKills, wave: data.state.wave }))
        }
        prevEnemyCount = curEnemies

        if (data.state.wave !== oldWave && data.state.wave > 0) {
          eventLog.value.unshift(t('towerDefenseView.eventLog.waveIncoming', { wave: data.state.wave }))
        }
        if (eventLog.value.length > 20) eventLog.value.length = 20
        renderFrame()
        if (data.state.game_over) {
          eventLog.value.unshift(t('towerDefenseView.eventLog.gameOver', { wave: data.state.wave, score: data.state.score }))
          fetchGames()
        }
      }
    } catch { /* expected */ }
  }, 400)
}

// ── Sprite Helpers ──
function drawTowerSprite(ctx: CanvasRenderingContext2D, tower: any, cx: number, cy: number, anim: number) {
  const color = TOWER_COLORS[tower.type] || 'var(--nc-primary)'
  const s = TILE_W * 0.4

  // Range circle (static, no shadow)
  const rangePx = (3 + (tower.level - 1)) * TILE_W
  ctx.beginPath()
  ctx.arc(cx, cy, rangePx, 0, Math.PI * 2)
  ctx.strokeStyle = color + '08'
  ctx.lineWidth = 1
  ctx.stroke()

  if (tower.type === 'basic') {
    ctx.fillStyle = '#1a2a3a'
    ctx.fillRect(cx - s * 0.7, cy - s * 0.7, s * 1.4, s * 1.4)
    ctx.fillStyle = color
    const angle = anim * 0.03 + cx * 0.5
    const bx = Math.cos(angle) * s * 0.9
    const by = Math.sin(angle) * s * 0.9
    ctx.fillRect(cx + Math.min(bx, 0) - s * 0.1, cy + Math.min(by, 0) - s * 0.1, Math.abs(bx) + s * 0.2, Math.abs(by) + s * 0.2)
    ctx.fillStyle = '#0a0e14'
    ctx.beginPath()
    ctx.arc(cx, cy, s * 0.25, 0, Math.PI * 2)
    ctx.fill()
  } else if (tower.type === 'sniper') {
    ctx.fillStyle = '#0a1a2a'
    ctx.fillRect(cx - s * 0.5, cy - s * 0.5, s, s)
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.arc(cx, cy, s * 0.8, 0, Math.PI * 2)
    ctx.stroke()
    ctx.beginPath()
    ctx.moveTo(cx - s, cy); ctx.lineTo(cx + s, cy)
    ctx.moveTo(cx, cy - s); ctx.lineTo(cx, cy + s)
    ctx.stroke()
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(cx, cy, 1.5, 0, Math.PI * 2)
    ctx.fill()
  } else if (tower.type === 'splash') {
    ctx.fillStyle = '#2a1a0a'
    ctx.beginPath()
    ctx.moveTo(cx - s * 0.8, cy + s * 0.5)
    ctx.lineTo(cx + s * 0.8, cy + s * 0.5)
    ctx.lineTo(cx + s * 0.5, cy - s * 0.7)
    ctx.lineTo(cx - s * 0.5, cy - s * 0.7)
    ctx.closePath()
    ctx.fill()
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(cx, cy - s * 0.2, s * 0.45, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = '#1a0a05'
    ctx.beginPath()
    ctx.arc(cx, cy - s * 0.2, s * 0.2, 0, Math.PI * 2)
    ctx.fill()
  } else if (tower.type === 'slow') {
    ctx.fillStyle = '#0a2a1a'
    ctx.fillRect(cx - s * 0.6, cy - s * 0.6, s * 1.2, s * 1.2)
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5
    const rot = anim * 0.01
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 3) * i + rot
      ctx.beginPath()
      ctx.moveTo(cx, cy)
      ctx.lineTo(cx + Math.cos(a) * s, cy + Math.sin(a) * s)
      ctx.stroke()
    }
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(cx, cy, 2, 0, Math.PI * 2)
    ctx.fill()
  } else if (tower.type === 'laser') {
    ctx.fillStyle = '#1a0a2a'
    ctx.beginPath()
    ctx.moveTo(cx, cy - s)
    ctx.lineTo(cx + s * 0.8, cy + s * 0.6)
    ctx.lineTo(cx - s * 0.8, cy + s * 0.6)
    ctx.closePath()
    ctx.fill()
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(cx, cy, s * 0.35, 0, Math.PI * 2)
    ctx.fill()
    // Glow ring instead of shadowBlur
    ctx.strokeStyle = color + '40'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.arc(cx, cy, s * 0.5, 0, Math.PI * 2)
    ctx.stroke()
  }

  // Level stars (no shadow)
  if (tower.level > 1) {
    ctx.fillStyle = '#ffd93d'
    for (let i = 0; i < tower.level - 1; i++) {
      const sx = cx - (tower.level - 2) * 3 + i * 6
      ctx.beginPath()
      ctx.arc(sx, cy + s + 3, 1.5, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  // Tower name
  ctx.fillStyle = color + '66'
  ctx.font = '5px "Fira Code", monospace'
  ctx.textAlign = 'center'
  ctx.fillText(tower.name, cx, cy + s + (tower.level > 1 ? 10 : 6))
}

function drawEnemySprite(ctx: CanvasRenderingContext2D, enemy: any, cx: number, cy: number, anim: number) {
  const color = ENEMY_COLORS[enemy.type] || '#ff4444'

  if (enemy.type === 'grunt') {
    const s = 3.5
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.moveTo(cx, cy - s); ctx.lineTo(cx + s, cy); ctx.lineTo(cx, cy + s); ctx.lineTo(cx - s, cy)
    ctx.closePath()
    ctx.fill()
  } else if (enemy.type === 'runner') {
    const s = 3.5
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.moveTo(cx + s, cy); ctx.lineTo(cx - s * 0.5, cy - s); ctx.lineTo(cx - s * 0.2, cy); ctx.lineTo(cx - s * 0.5, cy + s)
    ctx.closePath()
    ctx.fill()
    // Speed trail
    ctx.fillStyle = color + '50'
    ctx.fillRect(cx - s * 2, cy - 1, s * 1.2, 2)
  } else if (enemy.type === 'tank') {
    const s = 5
    ctx.fillStyle = color
    ctx.beginPath()
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 3) * i - Math.PI / 6
      if (i === 0) ctx.moveTo(cx + Math.cos(a) * s, cy + Math.sin(a) * s)
      else ctx.lineTo(cx + Math.cos(a) * s, cy + Math.sin(a) * s)
    }
    ctx.closePath()
    ctx.fill()
    // Inner plate
    ctx.fillStyle = color + '44'
    ctx.beginPath()
    for (let i = 0; i < 6; i++) {
      const a = (Math.PI / 3) * i - Math.PI / 6
      if (i === 0) ctx.moveTo(cx + Math.cos(a) * s * 0.55, cy + Math.sin(a) * s * 0.55)
      else ctx.lineTo(cx + Math.cos(a) * s * 0.55, cy + Math.sin(a) * s * 0.55)
    }
    ctx.closePath()
    ctx.fill()
  } else if (enemy.type === 'boss') {
    const s = 7
    ctx.fillStyle = color
    ctx.beginPath()
    for (let i = 0; i < 8; i++) {
      const a = (Math.PI / 4) * i + anim * 0.02
      ctx.lineTo(cx + Math.cos(a) * s, cy + Math.sin(a) * s)
      ctx.lineTo(cx + Math.cos(a + Math.PI / 8) * s * 0.65, cy + Math.sin(a + Math.PI / 8) * s * 0.65)
    }
    ctx.closePath()
    ctx.fill()
    // Boss glow ring (no shadowBlur)
    ctx.strokeStyle = color + '30'
    ctx.lineWidth = 2
    ctx.beginPath()
    ctx.arc(cx, cy, s + 2, 0, Math.PI * 2)
    ctx.stroke()
    // Eye
    ctx.fillStyle = '#fff'
    ctx.beginPath(); ctx.arc(cx, cy, 2, 0, Math.PI * 2); ctx.fill()
    ctx.fillStyle = '#0a0a0a'
    ctx.beginPath(); ctx.arc(cx, cy, 1, 0, Math.PI * 2); ctx.fill()
  }

  // Slow indicator (simple ring, no setLineDash for perf)
  if (enemy.slowed) {
    ctx.strokeStyle = '#6bcb7799'
    ctx.lineWidth = 1.5
    ctx.beginPath()
    ctx.arc(cx, cy, (enemy.type === 'boss' ? 9 : enemy.type === 'tank' ? 7 : 5), 0, Math.PI * 2)
    ctx.stroke()
  }

  // Health bar
  const hpPct = enemy.health / enemy.max_health
  if (hpPct < 1) {
    const barW = enemy.type === 'boss' ? 16 : 12
    const barY = cy - (enemy.type === 'boss' ? 10 : enemy.type === 'tank' ? 7 : 5) - 2
    ctx.fillStyle = 'rgba(0,0,0,0.6)'
    ctx.fillRect(cx - barW / 2 - 0.5, barY - 0.5, barW + 1, 3)
    ctx.fillStyle = hpPct > 0.5 ? '#10dc81' : hpPct > 0.25 ? '#f5b41e' : '#ff4444'
    ctx.fillRect(cx - barW / 2, barY, barW * hpPct, 2)
  }
}

function renderFrame() {
  const cvs = canvas.value
  if (!cvs || !activeGame.value) return
  const ctx = cvs.getContext('2d')
  if (!ctx) return

  animFrame++
  const state = activeGame.value
  const map = mapData.value
  const anim = animFrame

  // Draw cached map (1500 tiles rendered once, blitted instantly)
  if (map.length > 0) {
    if (mapCacheDirty || !mapCanvas) {
      buildMapCache(map)
    }
    if (mapCanvas) {
      ctx.drawImage(mapCanvas, 0, 0)
    }
  } else {
    ctx.fillStyle = '#050808'
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H)
  }

  // Draw towers with sprites
  for (const tower of (state.towers || [])) {
    const cx = tower.x * TILE_W + TILE_W / 2
    const cy = tower.y * TILE_H + TILE_H / 2
    drawTowerSprite(ctx, tower, cx, cy, anim)
  }

  // Draw projectiles (no save/restore, no shadowBlur)
  const aliveProjectiles: typeof projectiles = []
  for (const p of projectiles) {
    p.age++
    const progress = Math.min(p.age / 8, 1)
    const alpha = Math.max(0, 1 - progress * 0.8)

    if (p.type === 'splash' && progress > 0.7) {
      const explR = (progress - 0.7) * 60
      ctx.globalAlpha = 1 - progress
      ctx.fillStyle = p.color
      ctx.beginPath()
      ctx.arc(p.tx, p.ty, explR, 0, Math.PI * 2)
      ctx.fill()
    } else if (p.type === 'laser') {
      ctx.globalAlpha = alpha
      ctx.strokeStyle = p.color
      ctx.lineWidth = 2
      ctx.beginPath()
      ctx.moveTo(p.x, p.y)
      ctx.lineTo(p.tx, p.ty)
      ctx.stroke()
    } else {
      const px = p.x + (p.tx - p.x) * progress
      const py = p.y + (p.ty - p.y) * progress
      ctx.globalAlpha = alpha
      ctx.fillStyle = p.color
      ctx.beginPath()
      ctx.arc(px, py, p.type === 'splash' ? 3 : 2, 0, Math.PI * 2)
      ctx.fill()
    }

    if (p.age < 12) aliveProjectiles.push(p)
  }
  projectiles = aliveProjectiles
  ctx.globalAlpha = 1

  // Draw floating damage texts
  ctx.font = 'bold 8px "Fira Code", monospace'
  ctx.textAlign = 'center'
  const aliveTexts: typeof floatingTexts = []
  for (const ft of floatingTexts) {
    ft.age++
    ctx.globalAlpha = Math.max(0, 1 - ft.age / 30)
    ctx.fillStyle = ft.color
    ctx.fillText(ft.text, ft.x, ft.y - ft.age * 0.8)
    if (ft.age < 30) aliveTexts.push(ft)
  }
  floatingTexts = aliveTexts
  ctx.globalAlpha = 1

  // Draw enemies with sprites
  for (const enemy of (state.enemies || [])) {
    const cx = enemy.x * TILE_W + TILE_W / 2
    const cy = enemy.y * TILE_H + TILE_H / 2
    drawEnemySprite(ctx, enemy, cx, cy, anim)
  }

  // Game over overlay
  if (state.game_over) {
    ctx.fillStyle = 'rgba(5,5,10,0.6)'
    ctx.fillRect(0, 0, CANVAS_W, CANVAS_H)
    ctx.fillStyle = '#ff4444'
    ctx.shadowColor = '#ff4444'
    ctx.shadowBlur = 20
    ctx.font = 'bold 28px "Fira Code", monospace'
    ctx.textAlign = 'center'
    ctx.fillText(t('towerDefenseView.canvas.gameOver'), CANVAS_W / 2, CANVAS_H / 2 - 15)
    ctx.shadowBlur = 0
    ctx.fillStyle = 'rgba(255,255,255,0.5)'
    ctx.font = '14px "Fira Code", monospace'
    ctx.fillText(t('towerDefenseView.canvas.gameOverSub', { wave: state.wave, score: state.score, kills: state.total_kills }), CANVAS_W / 2, CANVAS_H / 2 + 15)
  }
}

let fetchTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => { fetchGames(); fetchTimer = setInterval(fetchGames, 5000) })
onUnmounted(() => { if (fetchTimer) clearInterval(fetchTimer); if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <div class="td-page">
    <div class="td-header">
      <button class="td-back" @click="router.push('/games')">&larr; {{ t('towerDefenseView.nav.back') }}</button>
      <h1 class="td-title"><span class="td-accent">{{ t('towerDefenseView.title.tower') }}</span><span class="td-dim">{{ t('towerDefenseView.title.defense') }}</span></h1>
      <span class="td-subtitle">{{ t('towerDefenseView.title.subtitle') }}</span>
    </div>

    <div class="td-layout">
      <!-- Left: Games + Leaderboard -->
      <div class="td-sidebar">
        <div class="td-section-hdr">{{ t('towerDefenseView.sidebar.activeGames') }}</div>
        <ReadFailedNotice v-if="gamesFailed && games.length === 0" dense :retry="fetchGames" />
        <div v-else-if="gamesRead && games.length === 0" class="td-empty">{{ t('towerDefenseView.sidebar.noGames') }}</div>
        <div v-for="g in games" :key="g.match_id"
          :class="['td-game-card', activeGame?.match_id === g.match_id ? 'td-game-active' : '']"
          @click="spectateGame(g.match_id)">
          <div class="td-game-top">
            <span class="td-game-agent">{{ g.agent }}</span>
            <span v-if="g.game_over" class="td-badge-done">{{ t('towerDefenseView.badge.over') }}</span>
            <span v-else class="td-badge-live">{{ t('towerDefenseView.badge.live') }}</span>
          </div>
          <div class="td-game-stats">
            {{ t('towerDefenseView.gameCard.stats', { wave: g.wave, kills: g.kills, towers: g.towers }) }}
          </div>
        </div>

        <div class="td-section-hdr" style="margin-top:1.5rem">{{ t('towerDefenseView.sidebar.leaderboard') }}</div>
        <ReadFailedNotice v-if="scoresFailed && leaderboard.length === 0" dense :retry="fetchGames" />
        <div v-else-if="scoresRead && leaderboard.length === 0" class="td-empty">{{ t('towerDefenseView.sidebar.noScores') }}</div>
        <div v-for="(s, i) in leaderboard" :key="s.match_id" :class="['td-lb-row', i === 0 ? 'td-lb-row-top' : '']">
          <span class="td-lb-rank">{{ i === 0 ? '👑' : `#${i + 1}` }}</span>
          <span class="td-lb-name">{{ s.agent }}</span>
          <span class="td-lb-wave">W{{ s.wave }}</span>
          <span class="td-lb-score">{{ s.score }}</span>
        </div>
      </div>

      <!-- Center: Game canvas -->
      <div class="td-center">
        <div v-if="!spectating" class="td-placeholder">
          <div class="td-placeholder-icon">&#127984;</div>
          <p>{{ t('towerDefenseView.placeholder.selectGame') }}</p>
          <p class="td-placeholder-sub">{{ t('towerDefenseView.placeholder.connectAgent') }}</p>
          <code class="td-connector">npx mcp-remote https://api.theprotocol.cloud/mcp/td/sse --header X-Arena:open</code>
        </div>

        <div v-else class="td-game-view">
          <!-- HUD Bar -->
          <div class="td-info-bar">
            <div class="td-info-section">
              <span class="td-info-label">{{ t('towerDefenseView.hud.wave') }}</span>
              <span class="td-info-wave">{{ activeGame?.wave || 0 }}</span>
            </div>
            <div class="td-info-divider"></div>
            <div class="td-info-section">
              <span class="td-info-label">{{ t('towerDefenseView.hud.lives') }}</span>
              <span :class="['td-info-lives', (activeGame?.lives || 0) <= 3 ? 'td-lives-low' : '']">
                <span v-for="i in Math.min(activeGame?.lives || 0, 10)" :key="i" class="td-heart">&#9829;</span>
                <span v-if="(activeGame?.lives || 0) > 10" class="td-lives-num">+{{ (activeGame?.lives || 0) - 10 }}</span>
              </span>
            </div>
            <div class="td-info-divider"></div>
            <div class="td-info-section">
              <span class="td-info-label">{{ t('towerDefenseView.hud.gold') }}</span>
              <span class="td-info-gold">{{ activeGame?.gold || 0 }}</span>
            </div>
            <div class="td-info-divider"></div>
            <div class="td-info-section">
              <span class="td-info-label">{{ t('towerDefenseView.hud.kills') }}</span>
              <span class="td-info-kills">{{ activeGame?.total_kills || 0 }}</span>
            </div>
            <div class="td-info-right">
              <span class="td-info-score">{{ t('towerDefenseView.hud.score') }} {{ activeGame?.score || 0 }}</span>
              <span v-if="activeGame?.game_over" class="td-info-over">{{ t('towerDefenseView.hud.gameOver') }}</span>
            </div>
          </div>

          <canvas ref="canvas" :width="CANVAS_W" :height="CANVAS_H" class="td-canvas" />

          <!-- Tower + Enemy legend -->
          <div class="td-legend">
            <div class="td-legend-group">
              <span class="td-legend-title">{{ t('towerDefenseView.legend.towers') }}</span>
              <span v-for="(color, type) in TOWER_COLORS" :key="type" class="td-legend-item">
                <span class="td-legend-swatch" :style="{ background: color, boxShadow: `0 0 4px ${color}` }"></span>
                {{ type }}
              </span>
            </div>
            <div class="td-legend-sep"></div>
            <div class="td-legend-group">
              <span class="td-legend-title">{{ t('towerDefenseView.legend.enemies') }}</span>
              <span v-for="(color, type) in ENEMY_COLORS" :key="type" class="td-legend-item">
                <span class="td-legend-swatch td-legend-enemy" :style="{ background: color, boxShadow: `0 0 4px ${color}` }"></span>
                {{ type }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Event log + Tower Stats -->
      <div v-if="spectating" class="td-events">
        <div class="td-section-hdr">{{ t('towerDefenseView.events.title') }}</div>
        <div v-if="eventLog.length === 0" class="td-empty">{{ t('towerDefenseView.events.waiting') }}</div>
        <div v-for="(msg, i) in eventLog" :key="i" :class="['td-event-item', msg.includes('GAME OVER') ? 'td-event-death' : msg.includes('Wave') ? 'td-event-wave' : '']">
          {{ msg }}
        </div>

        <!-- Towers list -->
        <template v-if="activeGame?.towers?.length">
          <div class="td-section-hdr" style="margin-top:1rem">{{ t('towerDefenseView.events.deployedTowers') }}</div>
          <div v-for="twr in (activeGame?.towers || [])" :key="twr.id" class="td-tower-item">
            <span class="td-tower-swatch" :style="{ background: TOWER_COLORS[twr.type] || '#0dd' }"></span>
            <span class="td-tower-name">{{ twr.name }}</span>
            <span class="td-tower-stat">{{ twr.kills }}K</span>
            <span class="td-tower-stat td-tower-dmg">{{ twr.damage }}D</span>
          </div>
        </template>

        <!-- Stats summary -->
        <div v-if="activeGame" class="td-stats-box">
          <div class="td-stats-row">
            <span class="td-stats-label">{{ t('towerDefenseView.stats.towers') }}</span>
            <span class="td-stats-val">{{ activeGame.towers?.length || 0 }}</span>
          </div>
          <div class="td-stats-row">
            <span class="td-stats-label">{{ t('towerDefenseView.stats.enemies') }}</span>
            <span class="td-stats-val">{{ activeGame.enemies?.length || 0 }}</span>
          </div>
          <div class="td-stats-row">
            <span class="td-stats-label">{{ t('towerDefenseView.stats.waveActive') }}</span>
            <span :class="['td-stats-val', activeGame.wave_active ? 'td-active-yes' : '']">{{ activeGame.wave_active ? t('towerDefenseView.stats.yes') : t('towerDefenseView.stats.no') }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.td-page { padding: 1rem 1.5rem; min-height: 100vh; }
.td-header { text-align: center; margin-bottom: 1.5rem; position: relative; }
.td-back {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  font-size: 0.55rem; color: rgba(255,255,255,0.25); background: none; border: none;
  cursor: pointer; font-family: 'Fira Code', monospace; transition: color 0.2s;
}
.td-back:hover { color: rgba(16,220,129,0.7); }
.td-title { font-size: 1.8rem; font-weight: 200; letter-spacing: 0.15em; }
.td-accent { color: rgba(16, 220, 129, 0.9); }
.td-dim { color: rgba(255, 255, 255, 0.25); margin-left: 0.3rem; }
.td-subtitle { display: block; font-size: 0.55rem; letter-spacing: 0.2em; color: rgba(255,255,255,0.2); margin-top: 0.3rem; }

.td-layout { display: flex; gap: 1rem; }
.td-sidebar { width: 210px; flex-shrink: 0; }
.td-center { flex: 1; min-width: 0; }
.td-events { width: 210px; flex-shrink: 0; }

.td-section-hdr {
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.15em;
  color: rgba(16,220,129,0.5); margin-bottom: 0.5rem;
  padding-bottom: 0.25rem; border-bottom: 1px solid rgba(16,220,129,0.06);
}
.td-empty { font-size: 0.6rem; color: rgba(255,255,255,0.12); text-align: center; padding: 0.75rem; }

/* Game cards */
.td-game-card {
  padding: 0.5rem 0.6rem; margin-bottom: 0.35rem; border-radius: 6px;
  background: rgba(10,14,20,0.6); border: 1px solid rgba(16,220,129,0.04);
  cursor: pointer; transition: all 0.2s;
}
.td-game-card:hover { border-color: rgba(16,220,129,0.15); background: rgba(16,220,129,0.02); }
.td-game-active { border-color: rgba(16,220,129,0.3); background: rgba(16,220,129,0.03); }
.td-game-top { display: flex; justify-content: space-between; align-items: center; }
.td-game-agent { font-size: 0.6rem; color: rgba(255,255,255,0.6); font-weight: 600; }
.td-game-stats { font-size: 0.5rem; color: rgba(255,255,255,0.2); margin-top: 0.2rem; font-family: 'Fira Code', monospace; }
.td-badge-live { font-size: 0.4rem; font-weight: 800; color: rgba(16,220,129,0.8); letter-spacing: 0.1em; padding: 0.1rem 0.3rem; background: rgba(16,220,129,0.08); border-radius: 3px; }
.td-badge-done { font-size: 0.4rem; font-weight: 800; color: rgba(255,255,255,0.3); letter-spacing: 0.1em; padding: 0.1rem 0.3rem; background: rgba(255,255,255,0.03); border-radius: 3px; }

/* Leaderboard */
.td-lb-row {
  display: flex; align-items: center; gap: 0.35rem; padding: 0.25rem 0.3rem;
  font-size: 0.55rem; border-bottom: 1px solid rgba(255,255,255,0.02);
}
.td-lb-rank { color: rgba(245,180,30,0.5); font-weight: 700; min-width: 20px; font-family: 'Fira Code', monospace; }
.td-lb-name { color: rgba(255,255,255,0.5); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.td-lb-wave { color: rgba(16,220,129,0.6); font-family: 'Fira Code', monospace; font-weight: 600; }
.td-lb-score { color: rgba(245,180,30,0.5); font-family: 'Fira Code', monospace; min-width: 35px; text-align: right; }

/* Placeholder */
.td-placeholder { text-align: center; padding: 4rem 2rem; color: rgba(255,255,255,0.12); }
.td-placeholder-icon { font-size: 3rem; margin-bottom: 1rem; opacity: 0.5; }
.td-placeholder-sub { font-size: 0.65rem; margin-top: 0.5rem; }
.td-connector {
  display: inline-block; margin-top: 1rem; padding: 0.3rem 0.8rem;
  background: rgba(16,220,129,0.03); border: 1px solid rgba(16,220,129,0.1);
  border-radius: 4px; font-size: 0.5rem; color: rgba(16,220,129,0.4);
  font-family: 'Fira Code', monospace;
}

/* HUD Info Bar */
.td-info-bar {
  display: flex; align-items: center; gap: 0.6rem; padding: 0.5rem 0.75rem;
  background: rgba(10,14,20,0.9); border: 1px solid rgba(16,220,129,0.06);
  border-radius: 6px 6px 0 0; font-family: 'Fira Code', monospace;
}
.td-info-section { display: flex; flex-direction: column; align-items: center; gap: 0.1rem; }
.td-info-label { font-size: 0.35rem; letter-spacing: 0.15em; color: rgba(255,255,255,0.15); font-weight: 700; }
.td-info-wave { font-size: 0.8rem; color: rgba(16,220,129,0.9); font-weight: 700; }
.td-info-lives { display: flex; align-items: center; gap: 0; }
.td-lives-low .td-heart { animation: pulse-heart 0.5s ease-in-out infinite alternate; }
.td-heart { color: rgba(255,107,107,0.7); font-size: 0.5rem; margin: 0 0.5px; }
.td-lives-num { color: rgba(255,107,107,0.5); font-size: 0.45rem; margin-left: 2px; }
.td-info-gold { font-size: 0.65rem; color: rgba(245,180,30,0.8); font-weight: 600; }
.td-info-kills { font-size: 0.55rem; color: rgba(255,255,255,0.35); }
.td-info-divider { width: 1px; height: 24px; background: rgba(255,255,255,0.05); }
.td-info-right { margin-left: auto; display: flex; align-items: center; gap: 0.6rem; }
.td-info-score { font-size: 0.55rem; color: rgba(255,255,255,0.4); font-weight: 600; }
.td-info-over { font-size: 0.5rem; color: rgba(255,107,107,0.9); font-weight: 800; letter-spacing: 0.1em; padding: 0.15rem 0.4rem; background: rgba(255,70,70,0.1); border-radius: 3px; }

@keyframes pulse-heart { from { opacity: 0.5; } to { opacity: 1; } }

.td-canvas {
  display: block; width: 100%; max-width: 800px;
  border: 1px solid rgba(16,220,129,0.06);
  border-radius: 0 0 6px 6px;
  image-rendering: pixelated;
  background: #050808;
}

/* Legend */
.td-legend {
  display: flex; gap: 1.2rem; margin-top: 0.5rem; padding: 0.4rem 0.6rem;
  background: rgba(10,14,20,0.4); border-radius: 4px; align-items: flex-start;
}
.td-legend-group { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }
.td-legend-title { font-size: 0.35rem; font-weight: 700; letter-spacing: 0.12em; color: rgba(255,255,255,0.15); margin-right: 0.2rem; }
.td-legend-item { display: flex; align-items: center; gap: 0.2rem; font-size: 0.45rem; color: rgba(255,255,255,0.3); }
.td-legend-swatch { width: 8px; height: 8px; border-radius: 2px; }
.td-legend-enemy { border-radius: 50%; }
.td-legend-sep { width: 1px; height: 16px; background: rgba(255,255,255,0.06); flex-shrink: 0; }

/* Event log */
.td-event-item {
  font-size: 0.5rem; color: rgba(255,255,255,0.3); padding: 0.2rem 0.3rem;
  border-bottom: 1px solid rgba(255,255,255,0.02);
  font-family: 'Fira Code', monospace; border-radius: 2px;
}
.td-event-wave { color: rgba(16,220,129,0.6); background: rgba(16,220,129,0.03); }
.td-event-death { color: rgba(255,107,107,0.7); background: rgba(255,70,70,0.05); font-weight: 600; }

/* Tower items */
.td-tower-item {
  display: flex; align-items: center; gap: 0.3rem; padding: 0.2rem 0.3rem;
  font-size: 0.5rem; color: rgba(255,255,255,0.35);
  border-bottom: 1px solid rgba(255,255,255,0.02);
}
.td-tower-swatch { width: 6px; height: 6px; border-radius: 2px; flex-shrink: 0; }
.td-tower-name { flex: 1; color: rgba(255,255,255,0.45); font-weight: 600; }
.td-tower-stat { font-family: 'Fira Code', monospace; color: rgba(16,220,129,0.5); font-size: 0.45rem; }
.td-tower-dmg { color: rgba(255,107,107,0.4); }

/* Stats box */
.td-stats-box {
  margin-top: 1rem; padding: 0.5rem; background: rgba(10,14,20,0.5);
  border: 1px solid rgba(16,220,129,0.04); border-radius: 5px;
}
.td-stats-row { display: flex; justify-content: space-between; padding: 0.15rem 0; font-size: 0.5rem; }
.td-stats-label { color: rgba(255,255,255,0.2); }
.td-stats-val { color: rgba(255,255,255,0.4); font-family: 'Fira Code', monospace; }
.td-active-yes { color: rgba(16,220,129,0.7); font-weight: 600; }

@media (max-width: 900px) { .td-layout { flex-direction: column; } .td-sidebar, .td-events { width: 100%; } }
</style>
