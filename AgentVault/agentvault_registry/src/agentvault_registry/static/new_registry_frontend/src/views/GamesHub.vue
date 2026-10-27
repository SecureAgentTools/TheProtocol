<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'

const { t } = useI18n()
const router = useRouter()

// §DOCSFIX D6-631 (2026-10-16): the game servers are this registry's own (/mcp/<game>/...), so the connector snippets
// name the origin this console was loaded from. They named one fixed host (EU's API) on every registry, which sent a
// player on ASIA to EU's servers.
const mcpOrigin = typeof window !== 'undefined' && window.location?.origin ? window.location.origin : ''
const sseUrl = (game: string) => `${mcpOrigin}/mcp/${game}/sse`

// Live stats from each game server: null until that server has answered, and again when its health read fails
// (§FESUITE, V0575: a server that did not answer read "0 active, 0 total"; a frame without the games got the
// console's own index page, which is not JSON, and showed the same zeros)
type Health = Record<string, unknown> | null
const arenaStats = ref<Health>(null)
const tdStats = ref<Health>(null)
const snakeStats = ref<Health>(null)
const tradingStats = ref<Health>(null)
const lobbies = ref<any[]>([])

/** a game server's health answer, or null when it gave none (no answer, an error status, a body that is not JSON) */
async function readHealth(url: string): Promise<Health> {
  try {
    const r = await fetch(url)
    if (!r.ok) return null
    const body = await r.json()
    return body && typeof body === 'object' ? body : null
  } catch { return null }
}
const count = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

async function fetchLobbies() {
  try {
    const res = await fetch('/mcp/lobby/health')
    const health = await res.json()
    if (health.active_lobbies > 0 || health.total_lobbies > 0) {
      // Fetch lobby list via RPC
      const rpc = await fetch('/mcp/lobby/rpc', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name: 'lobby_list', arguments: {} } }),
      })
      const data = await rpc.json()
      const text = data?.result?.content?.[0]?.text
      if (text) {
        const parsed = JSON.parse(text)
        lobbies.value = parsed?.lobbies || []
      }
    } else {
      lobbies.value = []
    }
  } catch { lobbies.value = [] }
}

async function fetchStats() {
  const [a, td, sn, tr] = await Promise.all([
    readHealth('/mcp/arena/health'), readHealth('/mcp/td/health'),
    readHealth('/mcp/snake/health'), readHealth('/mcp/trading/health'),
  ])
  arenaStats.value = a; tdStats.value = td; snakeStats.value = sn; tradingStats.value = tr
}

const games = [
  {
    id: 'robowars',
    name: t('gamesHubView.games.robowars.name'),
    subtitle: t('gamesHubView.games.robowars.subtitle'),
    description: t('gamesHubView.games.robowars.description'),
    route: '/arena',
    accentColor: '#ff6b6b',
    bgGrad: 'linear-gradient(135deg, rgba(255,107,107,0.08) 0%, rgba(255,60,60,0.02) 100%)',
    borderColor: 'rgba(255,107,107,0.15)',
    features: [
      t('gamesHubView.games.robowars.features.botEnemies'),
      t('gamesHubView.games.robowars.features.weaponsLoot'),
      t('gamesHubView.games.robowars.features.stormCircle'),
      t('gamesHubView.games.robowars.features.spectatorMode'),
      t('gamesHubView.games.robowars.features.bettingSystem'),
    ],
    mcpUrl: sseUrl('arena'),
    tools: 12,
    icon: 'swords',
  },
  {
    id: 'towerdefense',
    name: t('gamesHubView.games.towerdefense.name'),
    subtitle: t('gamesHubView.games.towerdefense.subtitle'),
    description: t('gamesHubView.games.towerdefense.description'),
    route: '/tower-defense',
    accentColor: '#10dc81',
    bgGrad: 'linear-gradient(135deg, rgba(16,220,129,0.08) 0%, rgba(16,220,129,0.02) 100%)',
    borderColor: 'rgba(16,220,129,0.15)',
    features: [
      t('gamesHubView.games.towerdefense.features.towerTypes'),
      t('gamesHubView.games.towerdefense.features.upgradeable'),
      t('gamesHubView.games.towerdefense.features.endlessWaves'),
      t('gamesHubView.games.towerdefense.features.leaderboard'),
      t('gamesHubView.games.towerdefense.features.fiveXSpeed'),
    ],
    mcpUrl: sseUrl('td'),
    tools: 10,
    icon: 'shield',
  },
  {
    id: 'snake',
    name: t('gamesHubView.games.snake.name'),
    subtitle: t('gamesHubView.games.snake.subtitle'),
    description: t('gamesHubView.games.snake.description'),
    route: '/snake-arena',
    accentColor: 'var(--nc-primary)',
    bgGrad: 'linear-gradient(135deg, rgba(var(--nc-primary-rgb),0.08) 0%, rgba(var(--nc-primary-rgb),0.02) 100%)',
    borderColor: 'rgba(var(--nc-primary-rgb),0.15)',
    features: [
      t('gamesHubView.games.snake.features.multiplayer'),
      t('gamesHubView.games.snake.features.aiBotOpponents'),
      t('gamesHubView.games.snake.features.goldBonusFood'),
      t('gamesHubView.games.snake.features.autoAdvance'),
      t('gamesHubView.games.snake.features.spectatorView'),
    ],
    mcpUrl: sseUrl('snake'),
    tools: 6,
    icon: 'snake',
  },
  {
    id: 'trading',
    name: t('gamesHubView.games.trading.name'),
    subtitle: t('gamesHubView.games.trading.subtitle'),
    description: t('gamesHubView.games.trading.description'),
    route: '/trading',
    accentColor: '#f5b41e',
    bgGrad: 'linear-gradient(135deg, rgba(245,180,30,0.08) 0%, rgba(245,180,30,0.02) 100%)',
    borderColor: 'rgba(245,180,30,0.15)',
    features: [
      t('gamesHubView.games.trading.features.fiveCommodities'),
      t('gamesHubView.games.trading.features.shortSelling'),
      t('gamesHubView.games.trading.features.insiderTips'),
      t('gamesHubView.games.trading.features.marketEvents'),
      t('gamesHubView.games.trading.features.limitOrders'),
    ],
    mcpUrl: sseUrl('trading'),
    tools: 11,
    icon: 'chart',
  },
]

/** a count the game's server stated, or null (shown as "—") when it stated none */
function getActiveStat(id: string): number | null {
  if (id === 'robowars') return count(arenaStats.value?.active_matches)
  if (id === 'towerdefense') return count(tdStats.value?.active_games)
  if (id === 'snake') return count(snakeStats.value?.active_games)
  if (id === 'trading') return count(tradingStats.value?.active_games)
  return null
}

function getTotalStat(id: string): number | null {
  if (id === 'robowars') return count(arenaStats.value?.total_matches)
  if (id === 'towerdefense') return count(tdStats.value?.total_games)
  if (id === 'snake') return count(snakeStats.value?.total_games)
  if (id === 'trading') return count(tradingStats.value?.total_games)
  return null
}

const copied = ref('')
function copyMcp(url: string, id: string) {
  const cmd = `npx mcp-remote ${url} --header X-Arena:open`
  navigator.clipboard.writeText(cmd).then(() => {
    copied.value = id
    setTimeout(() => { copied.value = '' }, 2000)
  })
}

let statsTimer: ReturnType<typeof setInterval> | null = null
let lobbyTimer: ReturnType<typeof setInterval> | null = null
onMounted(() => {
  fetchStats(); statsTimer = setInterval(fetchStats, 10000)
  fetchLobbies(); lobbyTimer = setInterval(fetchLobbies, 5000)
})
onUnmounted(() => { if (statsTimer) clearInterval(statsTimer); if (lobbyTimer) clearInterval(lobbyTimer) })

const GAME_TYPE_LABELS: Record<string, string> = {
  robowars: t('gamesHubView.gameTypeLabels.robowars'),
  tower_defense: t('gamesHubView.gameTypeLabels.towerDefense'),
  snake: t('gamesHubView.gameTypeLabels.snake'),
  trading: t('gamesHubView.gameTypeLabels.trading'),
}
const GAME_TYPE_COLORS: Record<string, string> = { robowars: '#ff6b6b', tower_defense: '#10dc81', snake: 'var(--nc-primary)', trading: '#f5b41e' }
const GAME_TYPE_ROUTES: Record<string, string> = { robowars: '/arena', tower_defense: '/tower-defense', snake: '/snake-arena', trading: '/trading' }
</script>

<template>
  <div class="gh-page">
    <!-- Header -->
    <div class="gh-header">
      <h1 class="gh-title">
        <span class="gh-title-accent">{{ t('gamesHubView.header.titleAccent') }}</span>
        <span class="gh-title-dim">{{ t('gamesHubView.header.titleDim') }}</span>
      </h1>
      <p class="gh-subtitle">{{ t('gamesHubView.header.subtitle') }}</p>
    </div>

    <!-- How it works -->
    <div class="gh-how">
      <div class="gh-how-title">{{ t('gamesHubView.howItWorks.title') }}</div>
      <div class="gh-how-steps">
        <div class="gh-step">
          <div class="gh-step-num">1</div>
          <div class="gh-step-content">
            <div class="gh-step-title">{{ t('gamesHubView.howItWorks.step1.title') }}</div>
            <div class="gh-step-desc">{{ t('gamesHubView.howItWorks.step1.desc') }}</div>
          </div>
        </div>
        <div class="gh-step-arrow" aria-hidden="true">&rarr;</div>
        <div class="gh-step">
          <div class="gh-step-num">2</div>
          <div class="gh-step-content">
            <div class="gh-step-title">{{ t('gamesHubView.howItWorks.step2.title') }}</div>
            <div class="gh-step-desc">{{ t('gamesHubView.howItWorks.step2.desc') }}</div>
          </div>
        </div>
        <div class="gh-step-arrow" aria-hidden="true">&rarr;</div>
        <div class="gh-step">
          <div class="gh-step-num">3</div>
          <div class="gh-step-content">
            <div class="gh-step-title">{{ t('gamesHubView.howItWorks.step3.title') }}</div>
            <div class="gh-step-desc">{{ t('gamesHubView.howItWorks.step3.desc') }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Live Lobbies -->
    <div v-if="lobbies.length > 0" class="gh-lobbies">
      <div class="gh-lobbies-hdr">
        <span class="gh-lobbies-title">{{ t('gamesHubView.lobbies.openLobbiesTitle') }}</span>
        <span class="gh-lobbies-count">{{ t('gamesHubView.lobbies.waitingCount', { n: lobbies.length }) }}</span>
      </div>
      <div class="gh-lobbies-scroll">
        <div v-for="l in lobbies" :key="l.lobby_id" class="gh-lobby-card"
          :style="{ borderLeftColor: GAME_TYPE_COLORS[l.game_type] || '#666' }">
          <div class="gh-lobby-card-top">
            <span class="gh-lobby-game" :style="{ color: GAME_TYPE_COLORS[l.game_type] || '#666' }">{{ GAME_TYPE_LABELS[l.game_type] || l.game_type }}</span>
            <span class="gh-lobby-timer" :class="{ 'gh-lobby-urgent': l.time_remaining < 30 }">{{ t('gamesHubView.lobbies.seconds', { n: l.time_remaining }) }}</span>
          </div>
          <div class="gh-lobby-card-mid">
            <span class="gh-lobby-players">{{ t('gamesHubView.lobbies.playerCount', { joined: l.players_joined, max: l.max_players }) }}</span>
            <span class="gh-lobby-creator">{{ t('gamesHubView.lobbies.by', { creator: l.creator }) }}</span>
          </div>
          <div class="gh-lobby-card-bot">
            <span class="gh-lobby-id">{{ l.lobby_id }}</span>
            <span v-if="l.fill_bots" class="gh-lobby-bots">{{ t('gamesHubView.lobbies.bots') }}</span>
            <span v-if="l.invited?.length" class="gh-lobby-invited">{{ t('gamesHubView.lobbies.invited', { n: l.invited.length }) }}</span>
          </div>
          <div class="gh-lobby-card-players" v-if="l.players?.length">
            <span v-for="p in l.players" :key="p.name" :class="['gh-lobby-player', p.is_bot ? 'gh-lobby-bot-player' : '']">{{ p.name }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Game cards -->
    <div class="gh-games">
      <div v-for="game in games" :key="game.id" class="gh-card"
        :style="{ background: game.bgGrad, borderColor: game.borderColor }">

        <!-- Card header -->
        <div class="gh-card-header">
          <div class="gh-card-icon" :style="{ color: game.accentColor }">
            <template v-if="game.icon === 'swords'">&#9876;</template>
            <template v-else-if="game.icon === 'shield'">&#127984;</template>
            <template v-else-if="game.icon === 'chart'">&#128200;</template>
            <template v-else>&#128013;</template>
          </div>
          <div>
            <h2 class="gh-card-name" :style="{ color: game.accentColor }">{{ game.name }}</h2>
            <span class="gh-card-subtitle">{{ game.subtitle }}</span>
          </div>
          <div class="gh-card-live" v-if="(getActiveStat(game.id) ?? 0) > 0">
            <span class="gh-live-dot" :style="{ background: game.accentColor }"></span>
            {{ getActiveStat(game.id) }} {{ t('gamesHubView.stats.live') }}
          </div>
        </div>

        <!-- Description -->
        <p class="gh-card-desc">{{ game.description }}</p>

        <!-- Features -->
        <div class="gh-card-features">
          <span v-for="f in game.features" :key="f" class="gh-feature"
            :style="{ borderColor: game.borderColor, color: game.accentColor }">
            {{ f }}
          </span>
        </div>

        <!-- Stats row -->
        <div class="gh-card-stats">
          <div class="gh-stat">
            <span class="gh-stat-val" :style="{ color: game.accentColor }">{{ game.tools }}</span>
            <span class="gh-stat-label">{{ t('gamesHubView.stats.mcpTools') }}</span>
          </div>
          <div class="gh-stat">
            <span class="gh-stat-val" :style="{ color: game.accentColor }">{{ getActiveStat(game.id) ?? '—' }}</span>
            <span class="gh-stat-label">{{ t('gamesHubView.stats.active') }}</span>
          </div>
          <div class="gh-stat">
            <span class="gh-stat-val" :style="{ color: game.accentColor }">{{ getTotalStat(game.id) ?? '—' }}</span>
            <span class="gh-stat-label">{{ t('gamesHubView.stats.total') }}</span>
          </div>
        </div>

        <!-- MCP connection -->
        <div class="gh-card-mcp">
          <span class="gh-mcp-label">{{ t('gamesHubView.mcp.connectLabel') }}</span>
          <div class="gh-mcp-row">
            <code class="gh-mcp-cmd">npx mcp-remote {{ game.mcpUrl }} --header X-Arena:open</code>
            <button class="gh-mcp-copy" @click="copyMcp(game.mcpUrl, game.id)"
              :style="{ color: game.accentColor, borderColor: game.borderColor }">
              {{ copied === game.id ? t('gamesHubView.copy.copied') : t('gamesHubView.copy.copy') }}
            </button>
          </div>
        </div>

        <!-- Actions -->
        <div class="gh-card-actions">
          <button class="gh-btn-play" :style="{ background: game.accentColor + '18', borderColor: game.borderColor, color: game.accentColor }"
            @click="router.push(game.route)">
            {{ t('gamesHubView.actions.spectateAndPlay') }}
          </button>
        </div>
      </div>
    </div>

    <!-- Lobby System -->
    <div class="gh-lobby">
      <div class="gh-lobby-title">{{ t('gamesHubView.lobbySystem.title') }}</div>
      <div class="gh-lobby-content">
        <div class="gh-lobby-text">
          <p>{{ t('gamesHubView.lobbySystem.intro') }}</p>
          <ul class="gh-lobby-list">
            <li><strong>{{ t('gamesHubView.lobbySystem.feature1.strong') }}</strong> {{ t('gamesHubView.lobbySystem.feature1.rest') }}</li>
            <li><strong>{{ t('gamesHubView.lobbySystem.feature2.strong') }}</strong> {{ t('gamesHubView.lobbySystem.feature2.rest') }}</li>
            <li><strong>{{ t('gamesHubView.lobbySystem.feature3.strong') }}</strong> {{ t('gamesHubView.lobbySystem.feature3.rest') }}</li>
          </ul>
        </div>
        <div class="gh-lobby-connect">
          <span class="gh-mcp-label">{{ t('gamesHubView.mcp.connectLabel') }}</span>
          <div class="gh-mcp-row">
            <code class="gh-mcp-cmd">npx mcp-remote {{ sseUrl('lobby') }} --header X-Arena:open</code>
            <button class="gh-mcp-copy" style="color: rgba(168,130,255,0.8); border-color: rgba(168,130,255,0.15);"
              @click="copyMcp(sseUrl('lobby'), 'lobby')">
              {{ copied === 'lobby' ? t('gamesHubView.copy.copied') : t('gamesHubView.copy.copy') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Claude Desktop config -->
    <div class="gh-config">
      <div class="gh-config-title">{{ t('gamesHubView.claudeDesktop.title') }}</div>
      <p class="gh-config-desc">{{ t('gamesHubView.claudeDesktop.desc') }} <code>claude_desktop_config.json</code>:</p>
      <pre class="gh-config-code">{
  "mcpServers": {
    "robowars": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "{{ sseUrl('arena') }}", "--header", "X-Arena:open"]
    },
    "tower-defense": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "{{ sseUrl('td') }}", "--header", "X-Arena:open"]
    },
    "snake-arena": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "{{ sseUrl('snake') }}", "--header", "X-Arena:open"]
    },
    "market-mayhem": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "{{ sseUrl('trading') }}", "--header", "X-Arena:open"]
    },
    "game-lobby": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "{{ sseUrl('lobby') }}", "--header", "X-Arena:open"]
    }
  }
}</pre>
      <p class="gh-config-hint">{{ t('gamesHubView.claudeDesktop.hint') }}</p>
    </div>
  </div>
</template>

<style scoped>
.gh-page {
  /* §pass41 (2026-05-18) — Added var(--st-bg) defensive bg; min-height already present. */
  padding: 1.5rem 2rem;
  min-height: 100vh;
  max-width: 1100px;
  margin: 0 auto;
  background: var(--st-bg, transparent);
}

/* Header */
.gh-header { text-align: center; margin-bottom: 2rem; }
.gh-title { font-size: 2rem; font-weight: 200; letter-spacing: 0.15em; }
.gh-title-accent { color: rgba(255,107,107,0.9); }
.gh-title-dim { color: rgba(255,255,255,0.47); margin-left: 0.3rem; }
/* §FESUITE: the page's text whites rose from 0.12-0.3 alpha (1.35-2.6:1) to 0.47-0.52 (4.8-5.7:1), keeping their order;
   the lobby title's purple 0.5 -> 0.85 (5.1:1) and the config code's primary 0.5 -> 0.7 (5.3:1 in the neural theme). */
.gh-subtitle { font-size: 0.65rem; letter-spacing: 0.15em; color: rgba(255,255,255,0.47); margin-top: 0.4rem; }

/* How it works */
.gh-how {
  margin-bottom: 2rem; padding: 1.2rem 1.5rem;
  background: rgba(10,14,20,0.6); border: 1px solid rgba(255,255,255,0.04);
  border-radius: 8px;
}
.gh-how-title {
  font-size: 0.45rem; font-weight: 700; letter-spacing: 0.2em;
  color: rgba(255,255,255,0.47); margin-bottom: 1rem; text-align: center;
}
.gh-how-steps { display: flex; align-items: flex-start; justify-content: center; gap: 0.8rem; }
.gh-step { display: flex; align-items: flex-start; gap: 0.6rem; flex: 1; max-width: 260px; }
.gh-step-num {
  width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.55rem; font-weight: 700; font-family: 'Fira Code', monospace;
  background: rgba(var(--nc-primary-rgb),0.08); border: 1px solid rgba(var(--nc-primary-rgb),0.2);
  color: rgba(var(--nc-primary-rgb),0.8);
}
.gh-step-content { }
.gh-step-title { font-size: 0.6rem; font-weight: 600; color: rgba(255,255,255,0.6); margin-bottom: 0.15rem; }
.gh-step-desc { font-size: 0.5rem; color: rgba(255,255,255,0.47); line-height: 1.5; }
.gh-step-arrow { color: rgba(255,255,255,0.08); font-size: 1.2rem; margin-top: 0.3rem; flex-shrink: 0; }

/* Live Lobbies */
.gh-lobbies { margin-bottom: 1.5rem; }
.gh-lobbies-hdr {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 0.6rem; padding-bottom: 0.3rem;
  border-bottom: 1px solid rgba(168,130,255,0.08);
}
.gh-lobbies-title { font-size: 0.45rem; font-weight: 700; letter-spacing: 0.2em; color: rgba(168,130,255,0.5); }
.gh-lobbies-count { font-size: 0.45rem; color: rgba(168,130,255,0.3); font-family: 'Fira Code', monospace; }
.gh-lobbies-scroll {
  display: flex; gap: 0.8rem; overflow-x: auto; padding-bottom: 0.5rem;
  scrollbar-width: thin; scrollbar-color: rgba(168,130,255,0.15) transparent;
}
.gh-lobbies-scroll::-webkit-scrollbar { height: 4px; }
.gh-lobbies-scroll::-webkit-scrollbar-track { background: transparent; }
.gh-lobbies-scroll::-webkit-scrollbar-thumb { background: rgba(168,130,255,0.15); border-radius: 2px; }
.gh-lobby-card {
  min-width: 200px; max-width: 240px; flex-shrink: 0;
  padding: 0.7rem 0.8rem; border-radius: 6px;
  background: rgba(10,14,20,0.7); border: 1px solid rgba(168,130,255,0.06);
  border-left: 3px solid; transition: all 0.2s;
}
.gh-lobby-card:hover { border-color: rgba(168,130,255,0.15); background: rgba(168,130,255,0.02); }
.gh-lobby-card-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.3rem; }
.gh-lobby-game { font-size: 0.6rem; font-weight: 700; letter-spacing: 0.05em; }
.gh-lobby-timer {
  font-size: 0.5rem; font-weight: 700; font-family: 'Fira Code', monospace;
  color: rgba(255,255,255,0.52); padding: 0.1rem 0.3rem;
  background: rgba(255,255,255,0.03); border-radius: 3px;
}
.gh-lobby-urgent { color: rgba(255,107,107,0.7); background: rgba(255,70,70,0.06); }
.gh-lobby-card-mid { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.2rem; }
.gh-lobby-players { font-size: 0.5rem; color: rgba(255,255,255,0.4); font-weight: 600; }
.gh-lobby-creator { font-size: 0.4rem; color: rgba(255,255,255,0.47); }
.gh-lobby-card-bot { display: flex; gap: 0.4rem; align-items: center; }
.gh-lobby-id { font-size: 0.4rem; color: rgba(255,255,255,0.47); font-family: 'Fira Code', monospace; }
.gh-lobby-bots { font-size: 0.35rem; color: rgba(168,130,255,0.4); padding: 0.05rem 0.2rem; background: rgba(168,130,255,0.05); border-radius: 2px; }
.gh-lobby-invited { font-size: 0.35rem; color: rgba(var(--nc-primary-rgb),0.4); padding: 0.05rem 0.2rem; background: rgba(var(--nc-primary-rgb),0.05); border-radius: 2px; }
.gh-lobby-card-players { display: flex; flex-wrap: wrap; gap: 0.2rem; margin-top: 0.4rem; padding-top: 0.3rem; border-top: 1px solid rgba(255,255,255,0.03); }
.gh-lobby-player { font-size: 0.4rem; color: rgba(255,255,255,0.55); padding: 0.1rem 0.25rem; background: rgba(255,255,255,0.03); border-radius: 2px; font-family: 'Fira Code', monospace; }
.gh-lobby-bot-player { color: rgba(255,255,255,0.47); }

/* Game cards */
.gh-games { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.2rem; margin-bottom: 2rem; }
.gh-card {
  border: 1px solid; border-radius: 10px; padding: 1.2rem 1.4rem;
  transition: all 0.3s ease; position: relative; overflow: hidden;
}
.gh-card:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(0,0,0,0.3); }

.gh-card-header { display: flex; align-items: center; gap: 0.7rem; margin-bottom: 0.8rem; }
.gh-card-icon { font-size: 1.6rem; flex-shrink: 0; }
.gh-card-name { font-size: 1rem; font-weight: 700; letter-spacing: 0.1em; }
.gh-card-subtitle { font-size: 0.45rem; letter-spacing: 0.15em; color: rgba(255,255,255,0.47); text-transform: uppercase; }
.gh-card-live {
  margin-left: auto; display: flex; align-items: center; gap: 0.3rem;
  font-size: 0.45rem; font-weight: 700; letter-spacing: 0.08em;
  color: rgba(255,255,255,0.4); font-family: 'Fira Code', monospace;
}
.gh-live-dot {
  width: 6px; height: 6px; border-radius: 50%;
  animation: gh-pulse 1.5s ease-in-out infinite;
}
@keyframes gh-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

.gh-card-desc { font-size: 0.6rem; color: rgba(255,255,255,0.52); line-height: 1.6; margin-bottom: 0.8rem; }

.gh-card-features { display: flex; flex-wrap: wrap; gap: 0.3rem; margin-bottom: 0.8rem; }
.gh-feature {
  font-size: 0.4rem; font-weight: 600; letter-spacing: 0.05em;
  padding: 0.15rem 0.4rem; border-radius: 3px;
  border: 1px solid; background: rgba(0,0,0,0.2);
}

.gh-card-stats { display: flex; gap: 1.5rem; margin-bottom: 1rem; padding: 0.5rem 0; border-top: 1px solid rgba(255,255,255,0.03); }
.gh-stat { display: flex; flex-direction: column; align-items: center; }
.gh-stat-val { font-size: 0.85rem; font-weight: 700; font-family: 'Fira Code', monospace; }
.gh-stat-label { font-size: 0.35rem; letter-spacing: 0.12em; color: rgba(255,255,255,0.47); text-transform: uppercase; font-weight: 600; }

.gh-card-mcp { margin-bottom: 0.8rem; }
.gh-mcp-label { font-size: 0.35rem; letter-spacing: 0.15em; color: rgba(255,255,255,0.47); font-weight: 700; display: block; margin-bottom: 0.3rem; }
.gh-mcp-row { display: flex; gap: 0.4rem; align-items: center; }
.gh-mcp-cmd {
  flex: 1; font-size: 0.42rem; padding: 0.35rem 0.5rem; border-radius: 4px;
  background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.04);
  color: rgba(255,255,255,0.52); font-family: 'Fira Code', monospace;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.gh-mcp-copy {
  font-size: 0.42rem; font-weight: 600; padding: 0.35rem 0.6rem; border-radius: 4px;
  background: rgba(0,0,0,0.2); border: 1px solid; cursor: pointer;
  font-family: 'Fira Code', monospace; transition: all 0.2s; flex-shrink: 0;
}
.gh-mcp-copy:hover { background: rgba(255,255,255,0.05); }

.gh-card-actions { }
.gh-btn-play {
  width: 100%; padding: 0.5rem; border-radius: 6px;
  border: 1px solid; font-size: 0.6rem; font-weight: 700;
  letter-spacing: 0.08em; cursor: pointer; transition: all 0.2s;
  font-family: 'Fira Code', monospace;
}
.gh-btn-play:hover { filter: brightness(1.3); transform: scale(1.01); }

/* Lobby System */
.gh-lobby {
  margin-bottom: 1.5rem; padding: 1.2rem 1.5rem;
  background: rgba(10,14,20,0.6); border: 1px solid rgba(168,130,255,0.1);
  border-radius: 8px;
}
.gh-lobby-title {
  font-size: 0.45rem; font-weight: 700; letter-spacing: 0.2em;
  color: rgba(168,130,255,0.85); margin-bottom: 0.8rem;
}
.gh-lobby-content { }
.gh-lobby-text p { font-size: 0.6rem; color: rgba(255,255,255,0.52); margin-bottom: 0.5rem; line-height: 1.6; }
.gh-lobby-list {
  list-style: none; padding: 0; margin: 0 0 0.8rem 0;
}
.gh-lobby-list li {
  font-size: 0.55rem; color: rgba(255,255,255,0.5); line-height: 1.7;
  padding-left: 0.8rem; position: relative;
}
.gh-lobby-list li::before {
  content: '\25B8'; position: absolute; left: 0; color: rgba(168,130,255,0.4);
}
.gh-lobby-list li strong { color: rgba(255,255,255,0.45); font-weight: 600; }
.gh-lobby-list li code {
  background: rgba(168,130,255,0.06); padding: 0.05rem 0.25rem; border-radius: 3px;
  color: rgba(168,130,255,0.5); font-size: 0.5rem;
}
.gh-lobby-connect { margin-top: 0.5rem; }

/* Claude Desktop config */
.gh-config {
  padding: 1.2rem 1.5rem; background: rgba(10,14,20,0.6);
  border: 1px solid rgba(255,255,255,0.04); border-radius: 8px;
}
.gh-config-title {
  font-size: 0.45rem; font-weight: 700; letter-spacing: 0.2em;
  color: rgba(255,255,255,0.47); margin-bottom: 0.5rem;
}
.gh-config-desc { font-size: 0.6rem; color: rgba(255,255,255,0.52); margin-bottom: 0.8rem; }
.gh-config-desc code {
  background: rgba(var(--nc-primary-rgb),0.06); padding: 0.1rem 0.3rem; border-radius: 3px;
  color: rgba(var(--nc-primary-rgb),0.7); font-size: 0.55rem;
}
.gh-config-code {
  font-size: 0.5rem; line-height: 1.6; padding: 1rem; border-radius: 6px;
  background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.04);
  color: rgba(var(--nc-primary-rgb),0.7); font-family: 'Fira Code', monospace;
  overflow-x: auto; margin-bottom: 0.6rem;
}
.gh-config-hint { font-size: 0.5rem; color: rgba(255,255,255,0.47); }

@media (max-width: 768px) {
  .gh-how-steps { flex-direction: column; align-items: center; }
  .gh-step-arrow { transform: rotate(90deg); }
  .gh-games { grid-template-columns: 1fr; }
}
</style>
