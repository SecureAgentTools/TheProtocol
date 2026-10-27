<script setup lang="ts">
import { appLocale } from '@/services/appLocale'
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const router = useRouter()

const games = ref<any[]>([])
const activeGame = ref<any>(null)
const spectating = ref(false)
const eventLog = ref<string[]>([])
const canvas = ref<HTMLCanvasElement | null>(null)
const allTimeBoard = ref<any[]>([])

const COMMODITIES = ['ENERGY', 'DATA', 'COMPUTE', 'TRUST', 'DARK']
const COMM_COLORS: Record<string, string> = {
  ENERGY: '#f5b41e',
  DATA: '#4ecdc4',
  COMPUTE: '#ff6b6b',
  TRUST: '#6bcb77',
  DARK: '#a78bfa',
}

const CHART_W = 700
const CHART_H = 220

let prevRound = 0

// §FESUITE (V0575): the games list as the arena's (ArenaView matchesRead): "No games" only once the game server has
// answered; until then "Loading…", and "could not be read" when it has not answered at all (a later failed poll keeps
// the list that was read). A frame without the game got the console's own index page, which is not JSON.
const gamesRead = ref<'reading' | 'read' | 'unread'>('reading')

async function fetchGames() {
  try {
    const res = await fetch('/mcp/trading/games')
    if (!res.ok) throw new Error(`status ${res.status}`)
    games.value = (await res.json())?.games || []
    gamesRead.value = 'read'
  } catch { if (gamesRead.value !== 'read') gamesRead.value = 'unread' }
  try {
    const res = await fetch('/api/v1/arena/leaderboard/trading')
    if (res.ok) allTimeBoard.value = (await res.json())?.leaderboard || []
  } catch { /* the board shows only when it was read */ }
}

async function spectateGame(gameId: string) {
  try {
    const res = await fetch(`/mcp/trading/games/${gameId}`)
    const data = await res.json()
    activeGame.value = data?.state || null
    eventLog.value = []
    prevRound = data?.state?.round || 0
    spectating.value = true
    setTimeout(() => { renderChart(); startPolling(gameId) }, 100)
  } catch { /* expected */ }
}

let pollTimer: ReturnType<typeof setInterval> | null = null
function startPolling(gameId: string) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const res = await fetch(`/mcp/trading/games/${gameId}`)
      const data = await res.json()
      if (data?.state) {
        const state = data.state

        // Detect new events
        if (state.round !== prevRound) {
          for (const evt of (state.recent_events || [])) {
            const msg = `R${evt.round}: ${evt.name} — ${evt.desc}`
            if (!eventLog.value.includes(msg)) {
              eventLog.value.unshift(msg)
            }
          }
          if (eventLog.value.length > 20) eventLog.value.length = 20
        }

        // Detect new trades
        if (state.round !== prevRound) {
          for (const tr of (state.recent_trades || []).slice(-3)) {
            const msg = `${tr.agent} ${tr.side.toUpperCase()} ${tr.quantity} ${tr.commodity} @ ${tr.price}`
            if (!eventLog.value.includes(msg)) {
              eventLog.value.unshift(msg)
            }
          }
          if (eventLog.value.length > 20) eventLog.value.length = 20
        }

        prevRound = state.round
        activeGame.value = state
        renderChart()

        if (state.finished && pollTimer) {
          const winner = state.traders?.[0]
          if (winner) {
            eventLog.value.unshift(t('tradingView.gameOver', { name: winner.name, netWorth: winner.net_worth.toLocaleString(appLocale()) }))
          }
          clearInterval(pollTimer)
          fetchGames()
        }
      }
    } catch { /* expected */ }
  }, 800)
}

// ── Chart Rendering ──

function renderChart() {
  const cvs = canvas.value
  if (!cvs || !activeGame.value) return
  const ctx = cvs.getContext('2d')
  if (!ctx) return

  const state = activeGame.value
  const history = state.price_history || {}

  ctx.fillStyle = '#050808'
  ctx.fillRect(0, 0, CHART_W, CHART_H)

  // Find price range across all commodities
  let minP = Infinity, maxP = 0
  for (const comm of COMMODITIES) {
    const prices = history[comm] || []
    for (const p of prices) {
      if (p < minP) minP = p
      if (p > maxP) maxP = p
    }
  }
  if (minP === maxP) { minP = 0; maxP = 200 }
  const range = maxP - minP
  const padTop = 20, padBot = 25, padLeft = 45, padRight = 15
  const plotW = CHART_W - padLeft - padRight
  const plotH = CHART_H - padTop - padBot

  // Grid lines
  ctx.strokeStyle = 'rgba(255,255,255,0.04)'
  ctx.lineWidth = 0.5
  for (let i = 0; i <= 4; i++) {
    const y = padTop + (plotH / 4) * i
    ctx.beginPath()
    ctx.moveTo(padLeft, y); ctx.lineTo(CHART_W - padRight, y)
    ctx.stroke()
    // Price label
    const price = maxP - (range / 4) * i
    ctx.fillStyle = 'rgba(255,255,255,0.15)'
    ctx.font = '8px "Fira Code", monospace'
    ctx.textAlign = 'right'
    ctx.fillText(price.toFixed(0), padLeft - 5, y + 3)
  }

  // Round labels
  const maxRounds = state.max_rounds || 50
  ctx.fillStyle = 'rgba(255,255,255,0.1)'
  ctx.font = '7px "Fira Code", monospace'
  ctx.textAlign = 'center'
  for (let r = 0; r <= maxRounds; r += 10) {
    const x = padLeft + (r / maxRounds) * plotW
    ctx.fillText(`R${r}`, x, CHART_H - 5)
  }

  // Draw price lines
  for (const comm of COMMODITIES) {
    const prices = history[comm] || []
    if (prices.length < 2) continue

    const color = COMM_COLORS[comm]
    ctx.strokeStyle = color
    ctx.lineWidth = 1.5
    ctx.globalAlpha = 0.8
    ctx.beginPath()

    for (let i = 0; i < prices.length; i++) {
      const x = padLeft + (i / maxRounds) * plotW
      const y = padTop + plotH - ((prices[i] - minP) / range) * plotH
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.stroke()
    ctx.globalAlpha = 1

    // Current price label at end of line
    const lastPrice = prices[prices.length - 1]
    const lastX = padLeft + ((prices.length - 1) / maxRounds) * plotW
    const lastY = padTop + plotH - ((lastPrice - minP) / range) * plotH
    ctx.fillStyle = color
    ctx.font = 'bold 7px "Fira Code", monospace'
    ctx.textAlign = 'left'
    ctx.fillText(`${comm.slice(0, 3)} ${lastPrice.toFixed(0)}`, lastX + 4, lastY + 3)
  }

  // Round marker line
  const currentRound = state.round || 0
  const rx = padLeft + (currentRound / maxRounds) * plotW
  ctx.strokeStyle = 'rgba(255,255,255,0.1)'
  ctx.lineWidth = 1
  ctx.setLineDash([3, 3])
  ctx.beginPath()
  ctx.moveTo(rx, padTop); ctx.lineTo(rx, padTop + plotH)
  ctx.stroke()
  ctx.setLineDash([])

  // Game over overlay
  if (state.finished) {
    ctx.fillStyle = 'rgba(5,8,8,0.5)'
    ctx.fillRect(0, 0, CHART_W, CHART_H)
    ctx.fillStyle = '#10dc81'
    ctx.font = 'bold 18px "Fira Code", monospace'
    ctx.textAlign = 'center'
    const winner = state.traders?.[0]
    ctx.fillText(t('tradingView.chart.winsLabel', { name: winner?.name || '?' }), CHART_W / 2, CHART_H / 2 - 5)
    ctx.fillStyle = 'rgba(255,255,255,0.4)'
    ctx.font = '11px "Fira Code", monospace'
    ctx.fillText(t('tradingView.chart.netWorthLabel', { value: (winner?.net_worth || 0).toLocaleString(appLocale()) }), CHART_W / 2, CHART_H / 2 + 15)
  }
}

// Sorted traders for display
const sortedTraders = computed(() => {
  return [...(activeGame.value?.traders || [])].sort((a: any, b: any) => b.net_worth - a.net_worth)
})

// Price change indicators
const priceChanges = computed(() => {
  const h = activeGame.value?.price_history || {}
  const changes: Record<string, number> = {}
  for (const comm of COMMODITIES) {
    const prices = h[comm] || []
    if (prices.length >= 2) {
      changes[comm] = ((prices[prices.length - 1] - prices[prices.length - 2]) / prices[prices.length - 2]) * 100
    } else {
      changes[comm] = 0
    }
  }
  return changes
})

let fetchTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => { fetchGames(); fetchTimer = setInterval(fetchGames, 5000) })
onUnmounted(() => { if (fetchTimer) clearInterval(fetchTimer); if (pollTimer) clearInterval(pollTimer) })
</script>

<template>
  <div class="tr-page">
    <div class="tr-header">
      <button class="tr-back" @click="router.push('/games')">&larr; {{ t('tradingView.back') }}</button>
      <h1 class="tr-title"><span class="tr-accent">{{ t('tradingView.titleAccent') }}</span><span class="tr-dim">{{ t('tradingView.titleDim') }}</span></h1>
      <span class="tr-subtitle">{{ t('tradingView.subtitle') }}</span>
    </div>

    <div class="tr-layout">
      <!-- Left: Games -->
      <div class="tr-sidebar">
        <div class="tr-section-hdr">{{ t('tradingView.activeGames') }}</div>
        <div v-if="games.length === 0 && gamesRead !== 'read'" class="tr-empty" role="status" data-testid="tr-games-unread">{{ gamesRead === 'unread' ? t('common.readFailed.text', 'This could not be read just now.') : t('common.loading', 'Loading…') }}</div>
        <div v-else-if="games.length === 0" class="tr-empty">{{ t('tradingView.noGames') }}</div>
        <div v-for="g in games" :key="g.match_id"
          :class="['tr-game-card', activeGame?.match_id === g.match_id ? 'tr-game-active' : '']"
          @click="spectateGame(g.match_id)">
          <div class="tr-game-top">
            <span class="tr-game-names">{{ g.trader_names?.join(', ') || g.match_id }}</span>
            <span v-if="g.finished" class="tr-badge-done">{{ t('tradingView.badgeEnd') }}</span>
            <span v-else-if="g.started" class="tr-badge-live">{{ t('tradingView.badgeLive') }}</span>
          </div>
          <div class="tr-game-info">
            {{ t('tradingView.roundOf', { round: g.round, max: g.max_rounds }) }}
            <span v-if="g.winner" class="tr-game-winner">· {{ g.winner }}</span>
          </div>
        </div>

        <!-- Commodity legend -->
        <div class="tr-section-hdr" style="margin-top:1.5rem">{{ t('tradingView.commodities') }}</div>
        <div v-for="comm in COMMODITIES" :key="comm" class="tr-comm-row">
          <span class="tr-comm-dot" :style="{ background: COMM_COLORS[comm] }"></span>
          <span class="tr-comm-name">{{ comm }}</span>
          <template v-if="activeGame?.prices">
            <span class="tr-comm-price">{{ activeGame.prices[comm]?.toFixed(0) }}</span>
            <span :class="['tr-comm-change', (priceChanges[comm] || 0) >= 0 ? 'tr-change-up' : 'tr-change-down']">
              {{ (priceChanges[comm] || 0) >= 0 ? '+' : '' }}{{ (priceChanges[comm] || 0).toFixed(1) }}%
            </span>
          </template>
        </div>
        <!-- All-time leaderboard -->
        <template v-if="allTimeBoard.length > 0">
          <div class="tr-section-hdr" style="margin-top:1.5rem">{{ t('tradingView.allTimeBest') }}</div>
          <div v-for="(s, i) in allTimeBoard.slice(0, 8)" :key="s.match_id" class="tr-lb-row">
            <span class="tr-lb-rank">#{{ i + 1 }}</span>
            <span class="tr-lb-name">{{ s.agent_name }}</span>
            <span class="tr-lb-score">{{ (s.score || 0).toLocaleString(appLocale()) }}</span>
          </div>
        </template>
      </div>

      <!-- Center -->
      <div class="tr-center">
        <div v-if="!spectating" class="tr-placeholder">
          <div class="tr-placeholder-icon">&#128200;</div>
          <p>{{ t('tradingView.selectGame') }}</p>
          <p class="tr-placeholder-sub">{{ t('tradingView.connectAgent') }}</p>
          <code class="tr-connector">npx mcp-remote https://api.theprotocol.cloud/mcp/trading/sse --header X-Arena:open</code>
        </div>

        <div v-else>
          <!-- HUD -->
          <div class="tr-hud">
            <div class="tr-hud-section">
              <span class="tr-hud-label">{{ t('tradingView.hud.round') }}</span>
              <span class="tr-hud-val tr-hud-round">{{ activeGame?.round || 0 }}<span class="tr-hud-max">/{{ activeGame?.max_rounds || 50 }}</span></span>
            </div>
            <div class="tr-hud-div"></div>
            <div class="tr-hud-section">
              <span class="tr-hud-label">{{ t('tradingView.hud.traders') }}</span>
              <span class="tr-hud-val">{{ activeGame?.traders?.length || 0 }}</span>
            </div>
            <div class="tr-hud-div"></div>
            <div class="tr-hud-section">
              <span class="tr-hud-label">{{ t('tradingView.hud.leader') }}</span>
              <span class="tr-hud-val tr-hud-leader">{{ sortedTraders[0]?.name || '—' }}</span>
            </div>
            <div v-if="activeGame?.finished" class="tr-hud-winner">
              {{ t('tradingView.hud.wins', { name: sortedTraders[0]?.name }) }}
            </div>
          </div>

          <!-- Price Chart -->
          <canvas ref="canvas" :width="CHART_W" :height="CHART_H" class="tr-chart" />

          <!-- Trader Rankings -->
          <div class="tr-rankings">
            <div v-for="(trader, idx) in sortedTraders" :key="trader.agent_id"
              :class="['tr-rank-card', idx === 0 ? 'tr-rank-first' : '', trader.is_bot ? 'tr-rank-bot' : '']">
              <span class="tr-rank-pos">#{{ idx + 1 }}</span>
              <span class="tr-rank-name">{{ trader.name }}</span>
              <span v-if="trader.is_bot" class="tr-rank-bot-tag">{{ t('tradingView.botTag') }}</span>
              <span class="tr-rank-worth">{{ trader.net_worth?.toLocaleString(appLocale()) }}</span>
              <div class="tr-rank-bar-track">
                <div class="tr-rank-bar-fill" :style="{
                  width: Math.min(100, (trader.net_worth / (sortedTraders[0]?.net_worth || 1)) * 100) + '%',
                  background: idx === 0 ? '#10dc81' : trader.is_bot ? 'rgba(255,255,255,0.1)' : '#f5b41e',
                }"></div>
              </div>
              <!-- Holdings mini -->
              <div class="tr-rank-holdings">
                <span v-for="(qty, comm) in (trader.holdings || {})" :key="comm"
                  v-if="qty > 0" class="tr-rank-hold"
                  :style="{ color: COMM_COLORS[comm as string] || '#666' }">
                  {{ qty }}{{ (comm as string).slice(0, 1) }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Event Feed -->
      <div v-if="spectating" class="tr-feed">
        <div class="tr-section-hdr">{{ t('tradingView.marketFeed') }}</div>
        <div v-if="eventLog.length === 0" class="tr-empty">{{ t('tradingView.waitingForTrades') }}</div>
        <div v-for="(msg, i) in eventLog" :key="i"
          :class="['tr-feed-item',
            msg.includes('GAME OVER') ? 'tr-feed-win' :
            msg.includes('BUY') ? 'tr-feed-buy' :
            msg.includes('SELL') ? 'tr-feed-sell' :
            msg.startsWith('R') ? 'tr-feed-event' : '']">
          {{ msg }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tr-page { padding: 1rem 1.5rem; min-height: 100vh; }
.tr-header { text-align: center; margin-bottom: 1.5rem; position: relative; }
.tr-back {
  position: absolute; left: 0; top: 50%; transform: translateY(-50%);
  font-size: 0.55rem; color: rgba(255,255,255,0.25); background: none; border: none;
  cursor: pointer; font-family: 'Fira Code', monospace; transition: color 0.2s;
}
.tr-back:hover { color: rgba(245,180,30,0.7); }
.tr-title { font-size: 1.8rem; font-weight: 200; letter-spacing: 0.15em; }
.tr-accent { color: rgba(245,180,30,0.9); }
.tr-dim { color: rgba(255,255,255,0.25); margin-left: 0.3rem; }
.tr-subtitle { display: block; font-size: 0.5rem; letter-spacing: 0.15em; color: rgba(255,255,255,0.15); margin-top: 0.3rem; }

.tr-layout { display: flex; gap: 1rem; }
.tr-sidebar { width: 210px; flex-shrink: 0; }
.tr-center { flex: 1; min-width: 0; }
.tr-feed { width: 220px; flex-shrink: 0; }

.tr-section-hdr {
  font-size: 0.5rem; font-weight: 700; letter-spacing: 0.15em;
  color: rgba(245,180,30,0.5); margin-bottom: 0.5rem;
  padding-bottom: 0.25rem; border-bottom: 1px solid rgba(245,180,30,0.06);
}
.tr-empty { font-size: 0.6rem; color: rgba(255,255,255,0.12); text-align: center; padding: 0.75rem; }

/* Game cards */
.tr-game-card {
  padding: 0.5rem 0.6rem; margin-bottom: 0.35rem; border-radius: 6px;
  background: rgba(10,14,20,0.6); border: 1px solid rgba(245,180,30,0.04);
  cursor: pointer; transition: all 0.2s;
}
.tr-game-card:hover { border-color: rgba(245,180,30,0.15); background: rgba(245,180,30,0.02); }
.tr-game-active { border-color: rgba(245,180,30,0.3); background: rgba(245,180,30,0.03); }
.tr-game-top { display: flex; justify-content: space-between; align-items: center; gap: 0.3rem; }
.tr-game-names { font-size: 0.5rem; color: rgba(255,255,255,0.5); font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tr-game-info { font-size: 0.45rem; color: rgba(255,255,255,0.2); margin-top: 0.15rem; font-family: 'Fira Code', monospace; }
.tr-game-winner { color: rgba(16,220,129,0.6); }
.tr-badge-live { font-size: 0.4rem; font-weight: 800; color: rgba(16,220,129,0.8); letter-spacing: 0.1em; padding: 0.1rem 0.3rem; background: rgba(16,220,129,0.08); border-radius: 3px; flex-shrink: 0; }
.tr-badge-done { font-size: 0.4rem; font-weight: 800; color: rgba(255,255,255,0.3); letter-spacing: 0.1em; padding: 0.1rem 0.3rem; background: rgba(255,255,255,0.03); border-radius: 3px; flex-shrink: 0; }

/* Commodity sidebar */
.tr-comm-row { display: flex; align-items: center; gap: 0.4rem; padding: 0.25rem 0; font-size: 0.55rem; }
.tr-comm-dot { width: 8px; height: 8px; border-radius: 2px; flex-shrink: 0; }
.tr-lb-row {
  display: flex; align-items: center; gap: 0.3rem; padding: 0.2rem 0.3rem;
  font-size: 0.5rem; border-bottom: 1px solid rgba(255,255,255,0.02);
}
.tr-lb-rank { color: rgba(245,180,30,0.5); font-weight: 700; min-width: 18px; font-family: 'Fira Code', monospace; }
.tr-lb-name { color: rgba(255,255,255,0.45); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tr-lb-score { color: rgba(245,180,30,0.7); font-family: 'Fira Code', monospace; font-weight: 600; }

.tr-comm-name { color: rgba(255,255,255,0.4); flex: 1; font-weight: 600; font-size: 0.5rem; }
.tr-comm-price { color: rgba(255,255,255,0.5); font-family: 'Fira Code', monospace; font-size: 0.5rem; }
.tr-comm-change { font-family: 'Fira Code', monospace; font-size: 0.4rem; font-weight: 600; min-width: 35px; text-align: right; }
.tr-change-up { color: rgba(16,220,129,0.7); }
.tr-change-down { color: rgba(255,107,107,0.7); }

/* Placeholder */
.tr-placeholder { text-align: center; padding: 4rem 2rem; color: rgba(255,255,255,0.12); }
.tr-placeholder-icon { font-size: 3rem; margin-bottom: 1rem; opacity: 0.4; }
.tr-placeholder-sub { font-size: 0.65rem; margin-top: 0.5rem; }
.tr-connector {
  display: inline-block; margin-top: 1rem; padding: 0.3rem 0.8rem;
  background: rgba(245,180,30,0.03); border: 1px solid rgba(245,180,30,0.1);
  border-radius: 4px; font-size: 0.5rem; color: rgba(245,180,30,0.4);
  font-family: 'Fira Code', monospace;
}

/* HUD */
.tr-hud {
  display: flex; align-items: center; gap: 0.6rem; padding: 0.5rem 0.75rem;
  background: rgba(10,14,20,0.9); border: 1px solid rgba(245,180,30,0.06);
  border-radius: 6px 6px 0 0; font-family: 'Fira Code', monospace;
}
.tr-hud-section { display: flex; flex-direction: column; align-items: center; gap: 0.05rem; }
.tr-hud-label { font-size: 0.3rem; letter-spacing: 0.15em; color: rgba(255,255,255,0.12); font-weight: 700; }
.tr-hud-val { font-size: 0.7rem; color: rgba(245,180,30,0.8); font-weight: 600; }
.tr-hud-round { font-size: 0.8rem; }
.tr-hud-max { font-size: 0.45rem; color: rgba(255,255,255,0.2); }
.tr-hud-leader { font-size: 0.55rem; color: rgba(16,220,129,0.7); }
.tr-hud-div { width: 1px; height: 24px; background: rgba(255,255,255,0.05); }
.tr-hud-winner { margin-left: auto; font-size: 0.55rem; color: rgba(16,220,129,0.9); font-weight: 800; padding: 0.15rem 0.5rem; background: rgba(16,220,129,0.08); border-radius: 3px; }

/* Chart */
.tr-chart {
  display: block; width: 100%; max-width: 700px;
  border: 1px solid rgba(245,180,30,0.06); border-top: none;
  border-radius: 0 0 6px 6px; image-rendering: auto; background: #050808;
}

/* Rankings */
.tr-rankings { display: flex; flex-direction: column; gap: 0.3rem; margin-top: 0.5rem; }
.tr-rank-card {
  display: flex; align-items: center; gap: 0.4rem; padding: 0.4rem 0.5rem;
  background: rgba(10,14,20,0.6); border-radius: 5px;
  border: 1px solid rgba(255,255,255,0.02); font-size: 0.5rem;
}
.tr-rank-first { border-color: rgba(16,220,129,0.15); background: rgba(16,220,129,0.03); }
.tr-rank-pos { color: rgba(245,180,30,0.5); font-weight: 700; min-width: 18px; font-family: 'Fira Code', monospace; }
.tr-rank-name { color: rgba(255,255,255,0.6); font-weight: 600; min-width: 80px; }
.tr-rank-bot-tag { font-size: 0.35rem; color: rgba(255,255,255,0.2); padding: 0.05rem 0.2rem; background: rgba(255,255,255,0.04); border-radius: 2px; }
.tr-rank-worth { color: rgba(245,180,30,0.7); font-family: 'Fira Code', monospace; font-weight: 600; min-width: 55px; text-align: right; }
.tr-rank-bar-track { flex: 1; height: 4px; background: rgba(255,255,255,0.03); border-radius: 2px; overflow: hidden; min-width: 60px; }
.tr-rank-bar-fill { height: 100%; border-radius: 2px; transition: width 0.5s ease; }
.tr-rank-holdings { display: flex; gap: 0.2rem; }
.tr-rank-hold { font-size: 0.4rem; font-family: 'Fira Code', monospace; font-weight: 600; }

/* Feed */
.tr-feed-item {
  font-size: 0.45rem; color: rgba(255,255,255,0.25); padding: 0.2rem 0.3rem;
  border-bottom: 1px solid rgba(255,255,255,0.02);
  font-family: 'Fira Code', monospace; border-radius: 2px; line-height: 1.4;
}
.tr-feed-event { color: rgba(245,180,30,0.6); background: rgba(245,180,30,0.03); }
.tr-feed-buy { color: rgba(16,220,129,0.5); }
.tr-feed-sell { color: rgba(255,107,107,0.5); }
.tr-feed-win { color: rgba(16,220,129,0.8); background: rgba(16,220,129,0.05); font-weight: 700; }

@media (max-width: 900px) {
  .tr-layout { flex-direction: column; }
  .tr-sidebar, .tr-feed { width: 100%; }
}
</style>
