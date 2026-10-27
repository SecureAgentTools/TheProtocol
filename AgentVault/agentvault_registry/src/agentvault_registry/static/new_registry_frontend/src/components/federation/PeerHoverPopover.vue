<script setup lang="ts">
// Federation Network — peer hover popover (§pass-N — 2026-05-21)
// Replaces the browser-native SVG <title> tooltip with a richer Vue panel
// showing Registry Card v0.3 fields (avatar/encirclement + trust pill + fees
// + bundle age + ETag prefix). Mirrors §pass60.2 AgentWorld tooltip pattern.
//
// Positioning: fixed pixel offset from cursor (px,py). Teleported to body so
// it floats above the rest of the page (z-index 9500, below modals 10100).
// pointer-events: none so it never intercepts SVG events on the underlying nodes.
//
// Layout primitives drawn from: neural-command.css (--nc-*) + tp-federation.css
// (--fed-*) — zero new colors, zero new keyframes. Hologram stripe on top mirrors
// the canonical .nc-card::before pattern.
import { computed } from 'vue'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import Icon from '@/components/Icon.vue'
import { Teleport } from 'vue'
import { useFrames } from '@/composables/useFrames'

interface PeerVisualLite {
  orb_color?: string | null
  orb_glow_color?: string | null
  sovereign_variant?: string | null
  flare_encirclement_variant?: string | null
  flare_encirclement_overlay?: string | null
  icon_url?: string | null
}

interface PeerLite {
  id?: number
  name?: string
  base_url?: string
  status?: string
  peer_type?: string
  hop_distance?: number | null
  parent_registry_id?: number | null
  parent_name?: string | null
  trust_domain?: string | null
  card_etag?: string | null
  card_signature_verified?: boolean
  visual?: PeerVisualLite | null
  fees_summary?: { intra_registry?: number | null; cross_registry?: number | null; hosting_enabled?: boolean | null; hosting_rate?: number | null } | null
  fees?: { intra_registry?: number | null; cross_registry?: number | null } | null
  bundle_freshness?: {
    age_seconds?: number | null
    expires_in_seconds?: number | null
    refresh_overdue?: boolean
    refresh_critical?: boolean
    error?: string | null
  } | null
}

const props = defineProps<{
  peer: PeerLite | null
  px: number
  py: number
  visible: boolean
  // §pass62.7 (2026-05-21) — optional peers-by-id + localName for tree-walk
  // hop derivation matching the FederationDiscovery card AND Network tab SVG.
  // When omitted, falls back to raw peer.hop_distance (legacy behavior).
  peersById?: Map<number, PeerLite>
  localName?: string
}>()

// §pass62.7 — Tree-walk hop derivation (mirrors deriveDisplayHop in
// useFederationTopology.ts; inlined here to keep PeerLite type local).
function popoverDisplayHop(): number | null {
  const p = props.peer
  if (!p) return null
  if (p.peer_type === 'frame') return 1
  if (p.parent_registry_id == null) return 1
  if (!props.peersById) {
    // Fall back to raw column when no peer map provided.
    return p.hop_distance ?? null
  }
  let depth = 1
  let cur: PeerLite | undefined = p
  const seen = new Set<number>()
  while (cur?.parent_registry_id != null && depth < 10) {
    const cid = cur.id
    if (cid != null && seen.has(cid)) break
    if (cid != null) seen.add(cid)
    const parent = props.peersById.get(cur.parent_registry_id)
    if (!parent) break
    depth += 1
    if (parent.peer_type === 'frame' || parent.parent_registry_id == null) break
    cur = parent
  }
  return depth
}
function popoverChainPath(): string {
  const p = props.peer
  if (!p || !props.peersById) return ''
  const path: string[] = [p.name || `peer-${p.id}`]
  let cur: PeerLite | undefined = p
  const seen = new Set<number>()
  while (cur?.parent_registry_id != null && path.length < 10) {
    const cid = cur.id
    if (cid != null && seen.has(cid)) break
    if (cid != null) seen.add(cid)
    const parent = props.peersById.get(cur.parent_registry_id)
    if (!parent) break
    path.unshift(parent.name || `peer-${parent.id}`)
    cur = parent
  }
  path.unshift(props.localName || 'Local')
  return path.join(' → ')
}

// Position — offset from cursor by 14px so it never sits under the pointer.
// Clamp to viewport so we don't overflow on small windows.
const popoverStyle = computed(() => {
  const offset = 14
  const popMaxW = 340
  const popMaxH = 480  // generous upper bound for clamp calc
  const vw = (typeof window !== 'undefined') ? window.innerWidth : 1920
  const vh = (typeof window !== 'undefined') ? window.innerHeight : 1080
  let left = props.px + offset
  let top = props.py + offset
  if (left + popMaxW > vw - 8) left = props.px - popMaxW - offset
  if (top + popMaxH > vh - 8) top = Math.max(8, vh - popMaxH - 8)
  return { left: `${left}px`, top: `${top}px` }
})

const tierLabel = (peer: PeerLite | null): string => {
  if (!peer) return ''
  switch (peer.peer_type) {
    case 'frame': return 'frame'
    case 'direct_peer': return 'direct peer'
    case 'discovered': return 'discovered'
    case 'cloud_operator': return 'cloud op'
    case 'local': return 'this registry'
    default: return peer.peer_type || 'unknown'
  }
}
const tierPillClass = (peer: PeerLite | null): string => {
  if (!peer) return 'phpop-pill phpop-pill--muted'
  return `phpop-pill phpop-pill--${peer.peer_type}`
}

// §pass61.5 (2026-05-21) — flare priority matches PeerOrb.vue: cosmetic
// flare_encirclement_variant WINS over sovereign_variant rank pin. When the
// operator equips a flare, the popover avatar should reflect what's actually
// rendered on the orb, NOT the sovereign rank.
const flareVariant = computed(() =>
  props.peer?.visual?.flare_encirclement_variant  // cosmetic wins
    || props.peer?.visual?.sovereign_variant        // fallback to rank pin
    || null
)
const flareTier = computed<'sovereign' | 'shadow_chancellor'>(() => {
  if (!props.peer?.visual?.flare_encirclement_variant && props.peer?.visual?.sovereign_variant) {
    return 'sovereign'
  }
  return 'shadow_chancellor'
})
const flareOverlay = computed(() => props.peer?.visual?.flare_encirclement_overlay || null)

// B8 (2026-06-03) — peer home-frame currency (from trust_domain via the frame
// seed) + cross-currency / FX-corridor marker relative to the viewer.
const { localCurrency, currencyForTrustDomain, knownCurrencyForTrustDomain } = useFrames()
const peerCurrency = computed(() => currencyForTrustDomain(props.peer?.trust_domain))
const peerCurrencyKnown = computed(() => knownCurrencyForTrustDomain(props.peer?.trust_domain))
const peerIsForeign = computed(() => !!peerCurrencyKnown.value && peerCurrencyKnown.value !== localCurrency.value)

const orbStyle = computed(() => {
  const color = props.peer?.visual?.orb_color || '#94a3b8'
  const glow = props.peer?.visual?.orb_glow_color || color
  return {
    background: color,
    boxShadow: `0 0 16px ${glow}66, inset 0 0 8px ${glow}55`,
  }
})

const feesIntra = computed(() =>
  props.peer?.fees_summary?.intra_registry ?? props.peer?.fees?.intra_registry ?? null
)
const feesCross = computed(() =>
  props.peer?.fees_summary?.cross_registry ?? props.peer?.fees?.cross_registry ?? null
)
const hostingFee = computed(() =>
  props.peer?.fees_summary?.hosting_enabled ? props.peer?.fees_summary?.hosting_rate : null
)

const etagShort = computed(() => {
  const e = props.peer?.card_etag
  if (!e) return null
  const stripped = e.startsWith('sha256:') ? e.slice(7) : e
  return stripped.slice(0, 16) + '…'
})

type SigBadge = 'verified' | 'unsigned' | 'unknown'
const sigBadge = computed<SigBadge>(() => {
  if (props.peer?.card_signature_verified === true) return 'verified'
  if (props.peer?.card_signature_verified === false) return 'unsigned'
  return 'unknown'
})
const sigBadgeLabel = computed(() => sigBadge.value.toUpperCase())
const sigBadgeIcon = computed(() => ({
  verified: 'mdi:shield-check',
  unsigned: 'mdi:shield-off-outline',
  unknown: 'mdi:help-circle-outline',
}[sigBadge.value]))

function humanizeAge(seconds: number | null | undefined): string {
  if (seconds == null || isNaN(seconds)) return '—'
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h`
  const d = Math.floor(h / 24)
  const rh = h % 24
  return rh > 0 ? `${d}d ${rh}h` : `${d}d`
}

const bundleAgeClass = computed(() => {
  const fr = props.peer?.bundle_freshness
  if (!fr) return ''
  if (fr.error) return 'phpop-bundle--unknown'
  if (fr.refresh_critical) return 'phpop-bundle--critical'
  if (fr.refresh_overdue) return 'phpop-bundle--overdue'
  return 'phpop-bundle--fresh'
})
</script>

<template>
  <Teleport to="body">
    <div v-if="visible && peer" class="phpop" :style="popoverStyle" role="tooltip" aria-live="polite">
      <!-- Hologram stripe (canonical .nc-card::before pattern, recreated here for scoped style) -->
      <div class="phpop-holo"></div>

      <!-- Avatar / encirclement / orb row -->
      <div class="phpop-head">
        <div class="phpop-avatar">
          <FlareEncirclement v-if="flareVariant"
            :tier="flareTier"
            :variant="flareVariant"
            :overlay="flareOverlay"
            size="xs" />
          <UserAvatar v-else-if="peer.visual?.icon_url" :src="peer.visual.icon_url" :alt="peer.name || 'peer'" :size="32" />
          <div v-else class="phpop-orb" :style="orbStyle"></div>
        </div>
        <div class="phpop-titleblock">
          <strong class="phpop-name">{{ peer.name }}</strong>
          <span :class="tierPillClass(peer)">{{ tierLabel(peer) }}</span>
        </div>
      </div>

      <!-- Base URL row (mono) -->
      <div v-if="peer.base_url" class="phpop-row phpop-row--mono">
        <span class="phpop-label">URL</span>
        <span class="phpop-mono">{{ peer.base_url }}</span>
      </div>

      <!-- Card trust row -->
      <div v-if="etagShort || peer.card_etag !== undefined" class="phpop-row">
        <span class="phpop-label">CARD</span>
        <span v-if="etagShort" class="phpop-mono phpop-etag">{{ etagShort }}</span>
        <span :class="`phpop-sigpill phpop-sigpill--${sigBadge}`">
          <Icon :name="sigBadgeIcon" :size="10" />
          {{ sigBadgeLabel }}
        </span>
      </div>

      <!-- Fees row -->
      <div v-if="feesIntra !== null || feesCross !== null" class="phpop-row">
        <span class="phpop-label">FEES</span>
        <span class="phpop-mono">
          <template v-if="feesIntra !== null">intra {{ feesIntra.toFixed(2) }}%</template>
          <template v-if="feesIntra !== null && feesCross !== null"> · </template>
          <template v-if="feesCross !== null">cross {{ feesCross.toFixed(2) }}%</template>
        </span>
        <span v-if="hostingFee !== null && hostingFee !== undefined" class="phpop-mono phpop-host">+ host {{ hostingFee.toFixed(2) }}%</span>
      </div>

      <!-- B8: home-frame currency + cross-currency / FX-corridor marker -->
      <div v-if="peerCurrencyKnown" class="phpop-row">
        <span class="phpop-label">CURRENCY</span>
        <span class="phpop-mono">{{ peerCurrency }}</span>
        <span v-if="peerIsForeign" class="phpop-fx-pill" title="Cross-currency peer — payments bridge via FX when your registry has FX enabled.">⇄ cross-currency</span>
      </div>

      <!-- Bundle freshness row (frames + cross-TD peers) -->
      <div v-if="peer.bundle_freshness" class="phpop-row">
        <span class="phpop-label">BUNDLE</span>
        <span :class="`phpop-bundle ${bundleAgeClass}`">
          <Icon v-if="peer.bundle_freshness.refresh_critical" name="mdi:alert-octagon" :size="10" />
          <Icon v-else-if="peer.bundle_freshness.refresh_overdue" name="mdi:clock-alert" :size="10" />
          <Icon v-else name="mdi:check" :size="10" />
          {{ humanizeAge(peer.bundle_freshness.age_seconds) }} old
        </span>
      </div>

      <!-- Sovereign variant tag -->
      <div v-if="peer.visual?.sovereign_variant" class="phpop-row">
        <span class="phpop-label">SOV</span>
        <span class="phpop-mono phpop-sov">{{ peer.visual.sovereign_variant }}</span>
      </div>

      <!-- Hop / parent chain — §pass62.7 tree-walk derived -->
      <div v-if="popoverDisplayHop() != null || peer.parent_name" class="phpop-row phpop-row--chain">
        <span v-if="popoverDisplayHop() != null" class="phpop-mono" :title="popoverChainPath()">hop {{ popoverDisplayHop() }}</span>
        <span v-if="peer.parent_name" class="phpop-mono phpop-via">via {{ peer.parent_name }}</span>
      </div>

      <!-- Hint -->
      <div class="phpop-hint">Click to open detail drawer</div>
    </div>
  </Teleport>
</template>

<style scoped>
.phpop {
  position: fixed;
  z-index: 9500;          /* below ConfirmActionModal (10100), above ambient (0) */
  min-width: 240px;
  max-width: 340px;
  background: var(--nc-overlay, #1d2438);
  border: 1px solid var(--nc-border-strong, #343a4d);
  border-radius: 6px;
  padding: 10px 12px 8px;
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.6), 0 0 0 1px rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  pointer-events: none;   /* don't intercept SVG hover/move/click on parent */
  animation: phpop-in 140ms ease-out;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  color: var(--nc-text-primary, #e8eaed);
  overflow: hidden;
}

@keyframes phpop-in {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* Hologram stripe — canonical .nc-card::before pattern recreated here */
.phpop-holo {
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: var(--nc-hologram, linear-gradient(90deg, #00e5e5 0%, #00ff88 50%, #00e5e5 100%));
  background-size: 200% 100%;
  animation: phpop-holo-shift 3s linear infinite;
  pointer-events: none;
}
@keyframes phpop-holo-shift {
  0%   { background-position: 0% 50%; }
  100% { background-position: 200% 50%; }
}

@media (prefers-reduced-motion: reduce) {
  .phpop { animation: none }
  .phpop-holo { animation: none }
}

.phpop-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.phpop-avatar {
  width: 32px; height: 32px;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}
.phpop-orb {
  width: 22px; height: 22px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.18);
}
.phpop-titleblock {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.phpop-name {
  font-size: 0.92rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Tier pill — mirrors .fed-tier-pill conventions but scoped to popover */
.phpop-pill {
  display: inline-flex;
  align-items: center;
  font-size: 0.62rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  align-self: flex-start;
}
.phpop-pill--frame         { color: var(--fed-frame, #a855f7); border-color: rgba(168, 85, 247, 0.35); }
.phpop-pill--direct_peer   { color: var(--fed-direct, var(--nc-primary, #00d2d2)); border-color: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.35); }
.phpop-pill--discovered    { color: var(--fed-discovered, #f59e0b); border-color: rgba(245, 158, 11, 0.35); }
.phpop-pill--cloud_operator { color: var(--fed-cloud, #22c55e); border-color: rgba(34, 197, 94, 0.35); }
.phpop-pill--local         { color: #fff; border-color: rgba(255, 255, 255, 0.25); }
.phpop-pill--muted         { color: var(--nc-text-muted, #94a3b8); }

.phpop-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 0.74rem;
  margin-bottom: 4px;
  min-height: 18px;
}
.phpop-row--mono { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.7rem; word-break: break-all; }
.phpop-row--chain { color: var(--nc-text-muted, #94a3b8); }

.phpop-label {
  font-size: 0.6rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--nc-text-muted, #94a3b8);
  min-width: 42px;
  font-weight: 600;
}
.phpop-mono {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.68rem;
  color: var(--nc-text-primary, #e8eaed);
}
.phpop-etag {
  background: rgba(var(--nc-primary-rgb, 0, 210, 210), 0.08);
  border: 1px solid rgba(var(--nc-primary-rgb, 0, 210, 210), 0.2);
  padding: 1px 5px;
  border-radius: 2px;
  color: var(--nc-primary-bright, #00e5e5);
}
.phpop-host { color: var(--nc-warning, #ff9500); }
.phpop-sov { color: var(--nc-primary-bright, #00e5e5); text-transform: uppercase; letter-spacing: 0.06em; }
.phpop-via { color: var(--nc-text-muted, #94a3b8); }
/* B8 — cross-currency peer marker */
.phpop-fx-pill {
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 99px;
  font-size: 0.6rem;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(252, 211, 77, 0.95);
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.4);
}

/* Signature pill */
.phpop-sigpill {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 0.6rem; font-weight: 600;
  text-transform: uppercase; letter-spacing: 0.06em;
  padding: 1px 5px;
  border-radius: 2px;
  border: 1px solid;
}
.phpop-sigpill--verified  { color: var(--nc-success-bright, #4ade80); border-color: rgba(74, 222, 128, 0.35); background: rgba(0, 255, 136, 0.06); }
.phpop-sigpill--unsigned  { color: var(--nc-text-muted, #94a3b8); border-color: rgba(255, 255, 255, 0.1); }
.phpop-sigpill--unknown   { color: var(--nc-text-muted, #94a3b8); border-color: rgba(255, 255, 255, 0.08); }

/* Bundle freshness */
.phpop-bundle {
  display: inline-flex; align-items: center; gap: 3px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.68rem;
  padding: 1px 5px;
  border-radius: 2px;
  border: 1px solid;
}
.phpop-bundle--fresh    { color: var(--nc-success-bright, #4ade80); border-color: rgba(74, 222, 128, 0.3); }
.phpop-bundle--overdue  { color: var(--nc-warning, #ff9500); border-color: rgba(255, 149, 0, 0.4); }
.phpop-bundle--critical { color: var(--nc-danger, #ff3366); border-color: rgba(255, 51, 102, 0.5); animation: phpop-bundle-pulse 1.4s ease-in-out infinite; }
.phpop-bundle--unknown  { color: var(--nc-text-muted, #94a3b8); border-color: rgba(255, 255, 255, 0.08); }

@keyframes phpop-bundle-pulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255, 51, 102, 0); }
  50%      { box-shadow: 0 0 0 3px rgba(255, 51, 102, 0.16); }
}
@media (prefers-reduced-motion: reduce) {
  .phpop-bundle--critical { animation: none }
}

.phpop-hint {
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px dashed rgba(255, 255, 255, 0.06);
  font-size: 0.62rem;
  color: var(--nc-text-muted, #94a3b8);
  text-align: center;
  letter-spacing: 0.04em;
}
</style>
