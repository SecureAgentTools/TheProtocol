<template>
  <div class="forge-view">
    <header class="forge-hero" data-tour="fg-hero">
      <div class="hero-row">
        <div>
          <h1>GÖDEL FORGE</h1>
          <p class="tagline">Self-improving agents. Evolution with a ledger.</p>
        </div>
        <div class="hero-actions">
          <button class="hero-btn" @click="startForgeTour">
            <Icon name="mdi:play-circle" :size="15" /> Take the tour
          </button>
          <a class="hero-btn hero-btn--ghost" href="https://docs.theprotocol.cloud/build/godel-forge"
             target="_blank" rel="noopener">
            <Icon name="mdi:book-open-variant" :size="15" /> Read the chapter
          </a>
        </div>
      </div>
    </header>

    <!-- §FESUITE (V0575): a status read that got no answer is not "the arena is dark" -->
    <ReadFailedNotice v-if="loaded && statusFailed" :retry="readStatus" data-testid="fg-status-failed" />
    <!-- arena dark on this registry -->
    <div v-else-if="loaded && !status" class="forge-dark">
      <h2>The arena is dark on this registry</h2>
      <p>
        GÖDEL FORGE runs where <code>FORGE_ENABLED</code> is on (the pathfinder frame first).
        The code ships everywhere; the arena lights up per registry.
      </p>
    </div>

    <template v-if="status">
      <!-- status strip -->
      <section class="forge-strip" data-tour="fg-strip">
        <div class="chip"><span class="k">Quorum</span><span class="v">{{ status.flags.verifier_quorum_m }}-of-5</span></div>
        <div class="chip"><span class="k">Royalty</span><span class="v">{{ status.flags.royalty_default_bps }} bps (cap {{ status.flags.royalty_max_bps }}, depth {{ status.flags.royalty_max_depth }})</span></div>
        <div class="chip"><span class="k">Verifiers</span><span class="v">{{ status.counts.verifiers ?? 0 }}</span></div>
        <div class="chip"><span class="k">Lineage forks</span><span class="v">{{ status.counts.lineage_bundles ?? 0 }}</span></div>
        <div class="chip"><span class="k">Quorum scores</span><span class="v">{{ status.counts.code_patch_results ?? 0 }}</span></div>
      </section>

      <!-- batch 8: the concrete admission policy, straight from /forge/status — the answer
           to "how do I become a verifier?" lives on the arena page itself -->
      <section v-if="status?.verifier_prerequisites" class="forge-strip prereq-strip" data-tour="fg-prereqs">
        <span class="prereq-label">Become a verifier</span>
        <div class="chip"><span class="k">Consent</span><span class="v mono-sm">{{ status.verifier_prerequisites.org_consent_permission }}</span></div>
        <div class="chip"><span class="k">Locked</span><span class="v">≥ {{ status.verifier_prerequisites.min_stake }}</span></div>
        <div class="chip"><span class="k">Reputation</span><span class="v">≥ {{ status.verifier_prerequisites.min_reputation }}</span></div>
        <div class="chip"><span class="k">Verdicts</span><span class="v">{{ status.verifier_prerequisites.signed_verdicts_required ? 'Ed25519-signed' : 'signature optional' }}</span></div>
        <div class="chip"><span class="k">Seats/operator</span><span class="v">max {{ status.verifier_prerequisites.max_seats_per_operator }} of {{ status.verifier_prerequisites.quorum_m }}</span></div>
      </section>

      <!-- lineage tree -->
      <section class="forge-panel" data-tour="fg-tree">
        <div class="panel-head">
          <h2>Evolution Tree</h2>
          <div class="org-picker">
            <input v-model="orgId" placeholder="lineage org id (uuid)" @keyup.enter="loadTree" />
            <button @click="loadTree" :disabled="!orgId">Render</button>
          </div>
        </div>
        <div v-if="status?.lineages?.length" class="lineage-picks">
          <button v-for="l in status.lineages" :key="l.org_id" class="lineage-chip"
                  :class="{ active: orgId === l.org_id }"
                  @click="orgId = l.org_id; loadTree()">
            {{ l.name || shortDid(l.org_id) }}<span v-if="l.bundles" class="lc-n">{{ l.bundles }}</span>
          </button>
        </div>
        <p v-if="treeMsg" class="hint">{{ treeMsg }}</p>
        <div v-if="layout.nodes.length" class="tree-scroll">
          <svg :width="layout.w" :height="layout.h" class="tree-svg" role="img" aria-label="Lineage evolution tree">
            <defs>
              <marker id="fg-arrow-spawn" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0.5 L7.5,4 L0,7.5 Z" fill="rgba(56, 200, 220, 0.85)" />
              </marker>
              <marker id="fg-arrow-fork" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0.5 L7.5,4 L0,7.5 Z" fill="rgba(240, 180, 60, 0.9)" />
              </marker>
            </defs>
            <path v-for="(e, i) in layout.edges" :key="'e' + i"
                  :d="e.d" :style="{ opacity: e.op }" fill="none"
                  :marker-end="e.kind === 'spawn' ? 'url(#fg-arrow-spawn)' : 'url(#fg-arrow-fork)'"
                  :class="e.kind === 'spawn' ? 'edge-spawn' : 'edge-fork'" />
            <g v-for="n in layout.nodes" :key="n.key" :transform="`translate(${n.x},${n.y})`"
               :class="{ 'node-clickable': n.type === 'agent' }"
               @click="n.type === 'agent' && openAgent(n.key)">
              <title>{{ n.type === 'agent'
                ? `${n.fullName} — ${n.key}${n.score !== null && n.score !== undefined ? ` — quorum score ${n.score.toFixed(2)}` : ''}${n.kin ? ' (spawn kin, not an org member)' : ''}`
                : `${n.fullName} — bundle ${n.key}${n.royalty ? ` — royalty ${n.royalty} bps` : ''}` }}</title>
              <circle :r="n.type === 'agent' ? 16 : 13"
                      :class="[n.type === 'agent' ? 'node-agent' : 'node-bundle', n.kin ? 'node-kin' : '']" />
              <text class="node-label" y="30">{{ n.label }}</text>
              <text v-if="n.score !== null && n.score !== undefined" class="node-score" y="4">{{ n.score.toFixed(2) }}</text>
              <text v-else-if="n.royalty" class="node-score" y="4">{{ n.royalty }}b</text>
            </g>
          </svg>
        </div>
        <div class="legend">
          <span><i class="dot dot-agent"></i>agent (spawn kinship, solid)</span>
          <span><i class="dot dot-bundle"></i>bundle (fork lineage, dashed) — badge = eval score / royalty bps</span>
        </div>
      </section>

      <!-- leaderboard -->
      <section class="forge-panel" data-tour="fg-board">
        <h2>Eval Leaderboard</h2>
        <table v-if="board.length" class="board">
          <thead><tr><th>#</th><th>Agent</th><th>Mean score</th><th>Runs</th></tr></thead>
          <tbody>
            <tr v-for="(row, i) in board" :key="row.agent_did" class="board-row"
                :title="`Open agent profile — ${row.agent_did}`" @click="openAgent(row.agent_did)">
              <td>{{ i + 1 }}</td>
              <td class="mono">{{ shortDid(row.agent_did) }}</td>
              <td>{{ Number(row.mean_score ?? row.score ?? 0).toFixed(3) }}</td>
              <td>{{ row.runs ?? row.count ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
        <ReadFailedNotice v-else-if="boardFailed" dense :retry="readBoard" />
        <p v-else-if="boardRead" class="hint">No eval results yet — the first generations are still climbing.</p>
      </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getForgeStatus, getLineage, type ForgeLineage, type ForgeStatus } from '@/services/api/forge'
import Icon from '@/components/Icon.vue'
import ReadFailedNotice from '@/components/common/ReadFailedNotice.vue'
import axios from 'axios'

const route = useRoute()
const router = useRouter()

const status = ref<ForgeStatus | null>(null)
const loaded = ref(false)
const orgId = ref('')
const tree = ref<ForgeLineage | null>(null)
const treeMsg = ref('')
const board = ref<any[]>([])

function shortDid(did: string): string {
  return did && did.length > 26 ? `${did.slice(0, 16)}…${did.slice(-8)}` : did
}

async function loadTree() {
  treeMsg.value = ''
  tree.value = await getLineage(orgId.value.trim())
  if (!tree.value) treeMsg.value = 'Lineage not found (or arena dark).'
  else if (!tree.value.nodes.length) treeMsg.value = 'Empty lineage — no agents or bundles in this org yet.'
  // Shareable deep link: /forge?org=<uuid> mirrors the rendered lineage.
  if (orgId.value && route.query.org !== orgId.value) {
    router.replace({ query: { ...route.query, org: orgId.value } }).catch(() => {})
  }
}

function openAgent(did: string) {
  if (!did || !did.startsWith('did:')) return
  router.push(`/agent-profile/${encodeURIComponent(did)}`)
}

async function startForgeTour() {
  try {
    const { useGuidedTourStore } = await import('@/views/Tutorials/guided/tourStore')
    await useGuidedTourStore().start('forge')
  } catch { /* tour engine unavailable — button is progressive enhancement */ }
}

// Layered layout: BFS depth from roots per edge-kind graph; agents row-band above bundles.
const layout = computed(() => {
  const t = tree.value
  if (!t || !t.nodes.length) return { nodes: [], edges: [], w: 0, h: 0 }
  const keyOf = (n: any) => n.did || n.id
  const nodesByKey: Record<string, any> = {}
  t.nodes.forEach(n => { nodesByKey[keyOf(n)] = n })
  const depth: Record<string, number> = {}
  const incoming = new Set(t.edges.map(e => e.to))
  const roots = t.nodes.map(keyOf).filter(k => !incoming.has(k))
  ;(roots.length ? roots : t.nodes.slice(0, 1).map(keyOf)).forEach(r => { depth[r] = 0 })
  for (let pass = 0; pass < 6; pass++) {
    for (const e of t.edges) {
      if (depth[e.from] !== undefined) depth[e.to] = Math.max(depth[e.to] ?? 0, depth[e.from] + 1)
    }
  }
  const cols: Record<number, string[]> = {}
  for (const n of t.nodes) {
    const d = depth[keyOf(n)] ?? 0
    ;(cols[d] = cols[d] || []).push(keyOf(n))
  }
  const colW = 210; const rowH = 86; const pad = 110
  const pos: Record<string, { x: number; y: number }> = {}
  const maxRows = Math.max(1, ...Object.values(cols).map(ks => ks.length))
  // center each column vertically inside the tallest column's band — parents sit level
  // with the middle of their fan instead of pinned to the top row
  Object.entries(cols).forEach(([d, keys]) => {
    const off = ((maxRows - keys.length) * rowH) / 2
    keys.forEach((k, i) => { pos[k] = { x: pad + Number(d) * colW, y: pad + off + i * rowH } })
  })
  const outNodes = t.nodes.map(n => {
    const k = keyOf(n)
    return {
      key: k, type: n.type, x: pos[k].x, y: pos[k].y,
      label: (n.name || k).slice(0, 20),
      fullName: n.name || k,
      kin: !!n.kin,
      score: n.type === 'agent' ? (n.eval_score ?? null) : null,
      royalty: n.type === 'bundle' ? (n.royalty_bps || 0) : 0,
    }
  })
  const outEdges = t.edges
    .filter(e => pos[e.from] && pos[e.to])
    .map(e => {
      const a = pos[e.from]; const b = pos[e.to]
      const rTo = (nodesByKey[e.to]?.type === 'bundle' ? 13 : 16) + 5 // stop at the node rim so the arrow shows
      let d: string
      let bx = b.x; let by = b.y
      if (Math.abs(b.x - a.x) > 4) {
        bx = b.x - Math.sign(b.x - a.x) * rTo
        const mx = (a.x + bx) / 2 // horizontal S-curve between columns (git-graph style)
        d = `M${a.x},${a.y} C${mx},${a.y} ${mx},${by} ${bx},${by}`
      } else {
        by = b.y - Math.sign(b.y - a.y || 1) * rTo // same-column edge — vertical with a slight bow
        d = `M${a.x},${a.y} C${a.x + 26},${a.y} ${a.x + 26},${by} ${bx},${by}`
      }
      const op = Math.max(0.55, 1 - (depth[e.to] ?? 0) * 0.1) // deeper generations fade slightly
      return { kind: e.kind, d, op }
    })
  const w = pad * 2 + (Math.max(...Object.keys(cols).map(Number)) + 1) * colW
  const h = pad * 2 + maxRows * rowH
  return { nodes: outNodes, edges: outEdges, w, h }
})

// §FESUITE (V0575): each read says when it failed: the status (not "the arena is dark") and the leaderboard (not "No
// eval results yet"); Try again reads it again
const statusFailed = ref(false)
const boardFailed = ref(false)
const boardRead = ref(false)
async function readStatus() {
  statusFailed.value = false
  try { status.value = await getForgeStatus() } catch { status.value = null; statusFailed.value = true }
  loaded.value = true
  if (!status.value) return
  // Deep link (?org=<uuid>) wins; otherwise auto-render the first known lineage so the
  // page never opens onto an empty tree when the arena has anything to show.
  const q = typeof route.query.org === 'string' ? route.query.org.trim() : ''
  const first = status.value?.lineages?.[0]?.org_id || ''
  if (q || first) {
    orgId.value = q || first
    loadTree()
  }
}
async function readBoard() {
  boardFailed.value = false
  try {
    const r = await axios.get('/api/v1/evals/leaderboard')
    board.value = r.data?.entries || r.data?.leaderboard || r.data?.agents || []
    boardRead.value = true
  } catch { board.value = []; boardFailed.value = true }
}
onMounted(async () => {
  await readStatus()
  await readBoard()
})
</script>

<style scoped>
.forge-view { max-width: 1100px; margin: 0 auto; padding: 24px 16px 64px; }
.forge-hero h1 { font-size: 2rem; letter-spacing: 0.14em; margin: 0; }
.forge-hero .tagline { opacity: 0.75; margin: 4px 0 20px; }
.hero-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
.hero-actions { display: flex; gap: 8px; flex-wrap: wrap; padding-top: 6px; }
.hero-btn {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 7px 14px; border-radius: 8px; font-size: 0.8rem; font-weight: 600;
  cursor: pointer; text-decoration: none; color: inherit;
  border: 1px solid rgba(139,92,246,0.45); background: rgba(139,92,246,0.1);
  transition: background 0.15s ease, border-color 0.15s ease;
}
.hero-btn:hover { background: rgba(139,92,246,0.2); border-color: rgba(139,92,246,0.8); }
.hero-btn--ghost { border-color: rgba(128,128,128,0.4); background: transparent; }
.hero-btn--ghost:hover { background: rgba(128,128,128,0.1); border-color: rgba(128,128,128,0.7); }
.board-row { cursor: pointer; }
.board-row:hover td { background: rgba(139,92,246,0.07); }
.node-clickable { cursor: pointer; }
.node-clickable:hover circle { stroke-width: 3; }
@media (max-width: 480px) {
  .hero-row { flex-direction: column; }
  .forge-hero h1 { font-size: 1.5rem; }
}
.forge-dark { border: 1px solid rgba(128,128,128,0.35); border-radius: 10px; padding: 22px; }
.forge-strip { display: flex; flex-wrap: wrap; gap: 10px; margin: 14px 0 22px; }
.prereq-strip { margin-top: -10px; align-items: center; }
.prereq-strip .chip { border-color: rgba(139, 92, 246, 0.45); }
.prereq-label { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em;
  font-weight: 700; color: rgba(167, 139, 250, 0.9); margin-right: 2px; } /* 5.95:1 on the page (was 3.91:1) */
.mono-sm { font-family: monospace; font-size: 0.82rem; }
.chip { border: 1px solid rgba(128,128,128,0.35); border-radius: 999px; padding: 6px 14px; display: flex; gap: 8px; align-items: baseline; }
.chip .k { opacity: 0.65; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; }
.chip .v { font-weight: 600; }
.forge-panel { border: 1px solid rgba(128,128,128,0.3); border-radius: 10px; padding: 18px; margin-bottom: 22px; }
.panel-head { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
/* the id field shrinks before the button leaves the card (a 300 px floor put Render past a 412 px screen) */
.org-picker { display: flex; gap: 8px; min-width: 0; max-width: 100%; }
.org-picker input { width: 300px; flex: 0 1 auto; min-width: 0; padding: 6px 10px; border-radius: 6px; border: 1px solid rgba(128,128,128,0.4); background: transparent; color: inherit; }
.org-picker button { flex: none; padding: 6px 16px; border-radius: 6px; border: 1px solid rgba(128,128,128,0.5); background: transparent; color: inherit; cursor: pointer; }
.org-picker button:disabled { opacity: 0.4; cursor: default; }
.lineage-picks { display: flex; flex-wrap: wrap; gap: 8px; margin: 2px 0 12px; }
.lineage-chip {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 4px 12px; border-radius: 999px; font-size: 0.78rem; cursor: pointer;
  border: 1px solid rgba(139,92,246,0.35); background: rgba(139,92,246,0.06); color: inherit;
}
.lineage-chip:hover { border-color: rgba(139,92,246,0.7); }
.lineage-chip.active { background: rgba(139,92,246,0.18); border-color: rgba(139,92,246,0.85); }
.lc-n {
  font-size: 0.65rem; padding: 1px 7px; border-radius: 999px;
  background: rgba(139,92,246,0.2); font-family: 'SF Mono', 'Fira Code', monospace;
}
.node-kin { stroke-dasharray: 3 3; opacity: 0.85; }
.tree-scroll { overflow-x: auto; margin-top: 12px; }
.tree-svg { display: block; }
.node-agent { fill: rgba(56, 200, 220, 0.22); stroke: rgb(56, 200, 220); stroke-width: 2; }
.node-bundle { fill: rgba(240, 180, 60, 0.20); stroke: rgb(240, 180, 60); stroke-width: 2; }
.node-label { font-size: 11px; text-anchor: middle; fill: currentColor; opacity: 0.85; }
.node-score { font-size: 10px; text-anchor: middle; fill: currentColor; font-weight: 700; }
.edge-spawn { stroke: rgba(56, 200, 220, 0.6); stroke-width: 1.6; }
.edge-fork { stroke: rgba(240, 180, 60, 0.7); stroke-width: 1.6; stroke-dasharray: 5 4; }
.legend { display: flex; gap: 22px; margin-top: 10px; font-size: 0.82rem; opacity: 0.8; flex-wrap: wrap; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; }
.dot-agent { background: rgb(56, 200, 220); }
.dot-bundle { background: rgb(240, 180, 60); }
.board { width: 100%; border-collapse: collapse; margin-top: 10px; }
.board th, .board td { text-align: left; padding: 8px 10px; border-bottom: 1px solid rgba(128,128,128,0.25); }
.mono { font-family: monospace; font-size: 0.85rem; }
.hint { opacity: 0.7; }
</style>
