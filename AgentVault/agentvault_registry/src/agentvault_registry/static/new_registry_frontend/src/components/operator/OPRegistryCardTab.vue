<template>
  <section class="op-tab op-rc">
    <!-- Hero with own card preview -->
    <div class="op-rc-hero">
      <div class="op-rc-hero-left">
        <div class="op-rc-eyebrow">Registry Card v0.3</div>
        <h2 class="op-rc-title">
          {{ card?.identity?.display_name || card?.identity?.registry_name || 'Your registry' }}
        </h2>
        <p class="op-rc-tagline" v-if="card?.description">{{ card.description }}</p>
        <p class="op-rc-tagline op-rc-tagline--muted" v-else-if="!loading">
          No description set yet. Add one in the full editor — it's the first thing federated peers see.
        </p>
        <div class="op-rc-tags" v-if="card?.tags?.length">
          <span v-for="tag in card.tags" :key="tag" class="op-rc-tag">{{ tag }}</span>
        </div>
      </div>
      <div class="op-rc-hero-right">
        <router-link to="/admin/registry-card" class="op-btn-primary">
          Open full editor
          <svg viewBox="0 0 12 12" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M4 2h6v6M10 2L5 7" stroke-linecap="round"/>
          </svg>
        </router-link>
      </div>
    </div>

    <!-- 4-section preview grid -->
    <div v-if="card" class="op-rc-grid">
      <!-- Visual identity -->
      <div class="op-rc-panel">
        <div class="op-rc-panel-eyebrow">Visual identity</div>
        <div class="op-rc-visual-row">
          <div
            class="op-rc-visual-orb"
            :style="{
              background: card.visual?.orb_color || '#00d2d2',
              boxShadow: `0 0 ${(card.visual?.orb_size_px || 16) * 1.2}px ${card.visual?.orb_glow_color || '#00ffff'}`,
              width: `${card.visual?.orb_size_px || 16}px`,
              height: `${card.visual?.orb_size_px || 16}px`,
              animationDuration: `${1 / (card.visual?.orb_pulse_speed_hz || 1.4)}s`,
            }"
          ></div>
          <div class="op-rc-visual-meta">
            <div class="op-rc-visual-row-item">
              <dt>orb_color</dt><dd><code class="op-code">{{ card.visual?.orb_color }}</code></dd>
            </div>
            <div class="op-rc-visual-row-item">
              <dt>glow_color</dt><dd><code class="op-code">{{ card.visual?.orb_glow_color }}</code></dd>
            </div>
            <div class="op-rc-visual-row-item">
              <dt>pulse</dt><dd>{{ card.visual?.orb_pulse_speed_hz }} Hz</dd>
            </div>
            <div class="op-rc-visual-row-item">
              <dt>theme</dt><dd>{{ card.visual?.theme || 'neural' }}</dd>
            </div>
            <div class="op-rc-visual-row-item" v-if="card.visual?.sovereign_variant">
              <dt>sovereign</dt>
              <dd>
                <code class="op-code">{{ card.visual.sovereign_variant }}</code>
                <span class="op-rc-pinned-tag">PINNED</span>
              </dd>
            </div>
            <div class="op-rc-visual-row-item" v-if="card.visual?.flare_encirclement_variant">
              <dt>flare</dt><dd><code class="op-code">{{ card.visual.flare_encirclement_variant }}</code></dd>
            </div>
            <div class="op-rc-visual-row-item" v-if="card.visual?.flare_corner_variant">
              <dt>corner</dt><dd><code class="op-code">{{ card.visual.flare_corner_variant }}</code></dd>
            </div>
          </div>
        </div>
      </div>

      <!-- Identity -->
      <div class="op-rc-panel">
        <div class="op-rc-panel-eyebrow">Identity</div>
        <dl class="op-rc-dl">
          <div><dt>SPIFFE ID</dt><dd><code class="op-code">{{ truncate(card.identity?.spiffe_id, 50) }}</code></dd></div>
          <div><dt>Trust domain</dt><dd><code class="op-code">{{ card.identity?.trust_domain }}</code></dd></div>
          <div><dt>Tier</dt><dd>{{ card.identity?.tier }}</dd></div>
          <div><dt>Public URL</dt>
            <dd><a class="op-link" :href="safeExternalUrl(card.identity?.public_url)" target="_blank" rel="noopener">{{ card.identity?.public_url }}</a></dd>
          </div>
        </dl>
      </div>

      <!-- Economic preview -->
      <div class="op-rc-panel">
        <div class="op-rc-panel-eyebrow">Economic surface</div>
        <dl class="op-rc-dl">
          <div><dt>Intra fee</dt><dd>{{ card.fees?.intra_registry?.base_rate_percent }}% base · {{ card.fees?.intra_registry?.max_rate_percent }}% max</dd></div>
          <div><dt>Cross-reg fee</dt><dd>{{ card.fees?.cross_registry?.base_rate_percent }}% → {{ card.fees?.cross_registry?.fee_recipient }}</dd></div>
          <div><dt>Hosting</dt><dd>{{ card.fees?.hosting?.enabled ? `${card.fees.hosting.rate_percent_of_agent_service_fee}% of agent service fee` : 'disabled' }}</dd></div>
          <div><dt>Settlement</dt><dd>{{ card.fees?.settlement_currency || '—' }}</dd></div>
        </dl>
      </div>

      <!-- Commitments / Links -->
      <div class="op-rc-panel">
        <div class="op-rc-panel-eyebrow">Commitments</div>
        <dl class="op-rc-dl">
          <div><dt>Uptime SLA</dt><dd>{{ card.commitments?.uptime_sla_pct }}%</dd></div>
          <div><dt>Incident disclosure</dt><dd>{{ card.commitments?.incident_disclosure_sla_hours }}h</dd></div>
          <div><dt>GDPR</dt><dd>{{ card.commitments?.gdpr_compliant ? 'compliant' : 'not stated' }}</dd></div>
          <div><dt>Key rotation max</dt><dd>{{ card.commitments?.key_rotation_max_days }}d</dd></div>
        </dl>
      </div>
    </div>

    <!-- ETag / signature -->
    <div v-if="card" class="op-rc-meta-strip">
      <div class="op-rc-meta-strip-item">
        <span class="op-rc-meta-label">card ETag</span>
        <code class="op-code">{{ etag || 'unknown' }}</code>
      </div>
      <div class="op-rc-meta-strip-item" v-if="card.signature">
        <span class="op-rc-meta-label">signed</span>
        <code class="op-code">{{ card.signature.alg }} · {{ truncate(card.signature.kid, 32) }}</code>
      </div>
      <div class="op-rc-meta-strip-item" v-if="card.lifecycle?.served_at">
        <span class="op-rc-meta-label">served</span>
        <span>{{ formatRelative(card.lifecycle.served_at) }}</span>
      </div>
    </div>

    <div v-if="loading && !card" class="op-rc-loading">Loading your registry card…</div>
    <div v-if="loadError" class="op-rc-error">
      <strong>Couldn't load card.</strong> {{ loadError }}
    </div>

    <!-- Local CLI bridge -->
    <div class="op-cli-bridge">
      <div class="op-cli-eyebrow">From terminal</div>
      <LocalCommand
        :command="`curl -sS https://YOUR-OPERATOR-DOMAIN/.well-known/registry-card.json | jq`"
        caption="Fetches your own published RC v0.3 card exactly as federated peers see it. Replace YOUR-OPERATOR-DOMAIN with your op's public URL."
      />
      <LocalCommand
        :command="`tp doctor`"
        caption="Includes RC v0.3 signing key health (kid · rotation_seq · age) in the diagnostic snapshot."
      />
    </div>
  </section>
</template>

<script setup lang="ts">
import { safeExternalUrl } from '@/utils/safeUrl'
import { ref, onMounted } from 'vue'
import LocalCommand from './LocalCommand.vue'
import axios from 'axios'

const card = ref<any | null>(null)
const etag = ref<string | null>(null)
const loading = ref(true)
const loadError = ref<string | null>(null)

async function load() {
  loading.value = true
  loadError.value = null
  try {
    // Fetch own well-known card directly (no auth needed, root-mounted)
    const r = await axios.get('/.well-known/registry-card.json', { validateStatus: () => true })
    if (r.status === 200) {
      card.value = r.data
      etag.value = r.headers.etag || r.headers.ETag || null
    } else {
      loadError.value = `HTTP ${r.status}`
    }
  } catch (e: any) {
    loadError.value = e?.message || 'Network error'
  } finally {
    loading.value = false
  }
}

function truncate(s: string | null | undefined, n: number): string {
  if (!s) return '—'
  if (s.length <= n) return s
  return s.slice(0, n) + '…'
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return 'never'
  try {
    const ms = Date.now() - new Date(iso).getTime()
    if (ms < 0) return 'just now'
    const s = Math.floor(ms / 1000); if (s < 60) return `${s}s ago`
    const m = Math.floor(s / 60); if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60); if (h < 24) return `${h}h ago`
    return `${Math.floor(h / 24)}d ago`
  } catch { return iso }
}

onMounted(load)
defineExpose({ refresh: load })
</script>

<style scoped>
.op-tab { padding: 1.2rem 1.6rem 2rem; }

.op-rc-hero {
  display: flex; gap: 1.5rem; align-items: flex-start;
  padding: 1.2rem 1.4rem;
  background: rgba(0, 8, 14, 0.55);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.2);
  border-radius: 4px;
}
.op-rc-hero-left { flex: 1 1 auto; min-width: 0; }
.op-rc-hero-right { flex: 0 0 auto; }

.op-rc-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.7); font-weight: 600;
  margin-bottom: 0.35rem;
}
.op-rc-title {
  margin: 0 0 0.5rem; font-size: 1.5rem; font-weight: 600;
  color: #f4f9ff; letter-spacing: -0.01em;
}
.op-rc-tagline {
  margin: 0; font-size: 0.88rem; line-height: 1.55;
  color: rgba(255, 255, 255, 0.7); max-width: 640px;
}
.op-rc-tagline--muted { color: rgba(255, 255, 255, 0.4); font-style: italic; }
.op-rc-tags { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.6rem; }
.op-rc-tag {
  display: inline-block;
  padding: 0.18rem 0.5rem;
  background: rgba(var(--nc-primary-rgb), 0.1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.25);
  border-radius: 2px;
  font-size: 0.7rem; letter-spacing: 0.04em;
  color: rgba(var(--nc-primary-rgb), 0.95);
  font-family: 'IBM Plex Mono', monospace;
}

.op-btn-primary {
  background: rgba(var(--nc-primary-rgb), 0.18);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.55);
  color: rgba(var(--nc-primary-rgb), 1);
  padding: 0.55rem 1rem;
  font-size: 0.72rem; letter-spacing: 0.1em; text-transform: uppercase;
  font-weight: 700; font-family: 'IBM Plex Mono', monospace;
  border-radius: 2px; cursor: pointer;
  text-decoration: none;
  transition: background 0.18s, box-shadow 0.18s;
  display: inline-flex; align-items: center; gap: 0.4rem;
  min-height: 36px; white-space: nowrap;
}
.op-btn-primary:hover {
  background: rgba(var(--nc-primary-rgb), 0.28);
  box-shadow: 0 0 14px rgba(var(--nc-primary-rgb), 0.2);
}

.op-rc-grid {
  margin-top: 1.3rem;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 1rem;
}

.op-rc-panel {
  padding: 1rem 1.1rem;
  background: rgba(0, 8, 14, 0.45);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.14);
  border-radius: 3px;
  transition: border-color 0.25s;
}
.op-rc-panel:hover { border-color: rgba(var(--nc-primary-rgb), 0.28); }
.op-rc-panel-eyebrow {
  font-size: 0.62rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(var(--nc-primary-rgb), 0.75); font-weight: 600;
  margin-bottom: 0.8rem;
  padding-bottom: 0.55rem;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.08);
}

.op-rc-visual-row { display: flex; align-items: flex-start; gap: 1.1rem; }
.op-rc-visual-orb {
  flex: 0 0 auto;
  border-radius: 50%;
  margin-top: 0.3rem;
  animation: opOrbPulse infinite ease-in-out;
}
@keyframes opOrbPulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.15); }
}
.op-rc-visual-meta { flex: 1 1 auto; }
.op-rc-visual-row-item {
  display: grid; grid-template-columns: 100px 1fr; gap: 0.5rem;
  padding: 0.2rem 0;
  font-size: 0.76rem;
}
.op-rc-visual-row-item dt {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.66rem; letter-spacing: 0.08em;
  color: rgba(255, 255, 255, 0.45); text-transform: uppercase;
}
.op-rc-visual-row-item dd {
  margin: 0; color: rgba(255, 255, 255, 0.85);
  display: flex; align-items: center; gap: 0.4rem;
}
.op-rc-pinned-tag {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.58rem; letter-spacing: 0.1em; text-transform: uppercase;
  padding: 0.1rem 0.35rem;
  background: rgba(255, 176, 0, 0.15);
  color: rgba(255, 200, 80, 0.95);
  border-radius: 2px;
  font-weight: 700;
}

.op-rc-dl > div {
  display: grid; grid-template-columns: 130px 1fr; gap: 0.5rem;
  padding: 0.3rem 0;
  border-bottom: 1px solid rgba(var(--nc-primary-rgb), 0.05);
  font-size: 0.78rem;
}
.op-rc-dl > div:last-child { border-bottom: none; }
.op-rc-dl dt {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 0.68rem; letter-spacing: 0.06em;
  color: rgba(255, 255, 255, 0.45); text-transform: uppercase;
}
.op-rc-dl dd {
  margin: 0; color: rgba(255, 255, 255, 0.85);
  word-break: break-all; min-width: 0;
}

.op-code {
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: 0.72rem;
  background: rgba(0, 0, 0, 0.32);
  padding: 0.1rem 0.35rem;
  border-radius: 2px;
  color: #c0e4ff;
}

.op-link {
  color: rgba(var(--nc-primary-rgb), 0.95);
  text-decoration: none;
  border-bottom: 1px dotted rgba(var(--nc-primary-rgb), 0.35);
}
.op-link:hover { border-bottom-style: solid; }

.op-rc-meta-strip {
  margin-top: 1rem; padding: 0.7rem 1rem;
  display: flex; gap: 1.5rem; flex-wrap: wrap;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.08);
  border-radius: 2px;
  font-size: 0.75rem;
  font-family: 'IBM Plex Mono', monospace;
}
.op-rc-meta-strip-item { display: flex; align-items: center; gap: 0.5rem; }
.op-rc-meta-label {
  font-size: 0.6rem; letter-spacing: 0.1em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.4); font-weight: 600;
}

.op-rc-loading, .op-rc-error {
  margin-top: 1.5rem; padding: 2rem;
  text-align: center;
  color: rgba(255, 255, 255, 0.5);
  background: rgba(0, 8, 14, 0.3);
  border: 1px dashed rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 3px;
}
.op-rc-error { color: rgba(255, 200, 200, 0.85); border-color: rgba(255, 82, 82, 0.32); }

.op-cli-bridge {
  margin-top: 1.8rem; padding-top: 1.3rem;
  border-top: 1px solid rgba(var(--nc-primary-rgb), 0.1);
}
.op-cli-eyebrow {
  font-size: 0.65rem; letter-spacing: 0.14em; text-transform: uppercase;
  color: rgba(255, 255, 255, 0.45); font-weight: 600;
  margin-bottom: 0.6rem;
}

@media (max-width: 768px) {
  .op-tab { padding: 1rem; }
  .op-rc-hero { flex-direction: column; }
  .op-rc-grid { grid-template-columns: 1fr; }
  .op-rc-visual-row { flex-direction: column; align-items: flex-start; }
}
</style>
