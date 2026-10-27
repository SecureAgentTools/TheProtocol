<script setup lang="ts">
import { resolvePeerAsset } from '@/services/peerAssets'
import Icon from '@/components/Icon.vue'
// RegistryHoverCard — the rich registry hover card, lifted verbatim from
// AgentWorld's globe tooltip so GalacticMap + UniverseView show the EXACT same
// information on registry hover that AgentWorld does: avatar/flare, name,
// status · currency · hop · sovereign · overlay badges, public URL,
// description, health/agents/protocol, fee rail (intra · cross · hosting),
// auth tags, and the card-signature trust line. AgentWorld keeps its own
// inline copy as the reference; this shared component carries the same content
// + styling to the other two topology views (Commander: "use the registry on
// hover label from the agentworld… make the galactic map have the same and
// also UNIVERSE view registries should have same on hover").
//
// Self-contained: provides its own chrome + helpers so the host only has to
// position it (drop inside any pointer-events:none, fixed wrapper).
import { computed } from 'vue'
import UserAvatar from '@/components/common/UserAvatar.vue'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'
import { useCurrency } from '@/composables/useCurrency'

interface RegistryVisual {
  iconUrl?: string | null
  orbColor?: string | null
  orbGlowColor?: string | null
  sovereignVariant?: string | null
  flareEncirclementVariant?: string | null
  flareEncirclementOverlay?: string | null
}
interface RegistryFees {
  intraRegistry?: number | null
  crossRegistry?: number | null
  hostingEnabled?: boolean | null
  hostingRate?: number | null
  settlementCurrency?: string | null
}
export interface RegistryHoverData {
  name: string                      // load-bearing slug (resolution key)
  displayName?: string | null       // §2026-06-14 operator-editable card display name (UI label)
  status?: string | null
  hopDepth?: number | null
  publicUrl?: string | null
  description?: string | null
  agentCount?: number | null
  health?: number | null
  protocolVersion?: string | null
  authMethods?: string[] | null
  lastSyncedAt?: string | null
  cardEtag?: string | null
  cardSignatureVerified?: boolean | null
  visual?: RegistryVisual | null
  fees?: RegistryFees | null
  frame?: string | null          // 'A' | 'B' | frame name — gates the hop palette
  exchange?: { enabled?: boolean | null; currency?: string | null; passport_enabled?: boolean | null } | null  // §2026-06-14 AGORA venue
}

const props = defineProps<{ registry: RegistryHoverData; currency?: string | null }>()
const { describe } = useCurrency()

// Hop-depth colour palettes (ported from AgentWorld — Frame A cyan→red ramp,
// Frame B magenta→violet ramp) so a hovered peer's HOP badge reads in its frame.
const HOP_DEPTH_COLORS = ['#00e676', '#5c9cf5', '#00bcd4', '#ff9800', '#e91e63', '#d50000']
const FRAME_B_HOP_COLORS = ['#ff4fb4', '#e91e63', '#c2185b', '#9c27b0', '#7b1fa2', '#4a148c']
function hopColor(depth: number, frame: string = 'A'): string {
  const palette = frame === 'B' ? FRAME_B_HOP_COLORS : HOP_DEPTH_COLORS
  return palette[Math.min(Math.max(depth, 0), palette.length - 1)]
}
function formatFeedTime(ts: number): string {
  const s = Math.floor((Date.now() - ts) / 1000)
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  return `${Math.floor(s / 3600)}h ago`
}

const r = computed(() => props.registry)
const accent = computed(() => r.value.visual?.orbColor || '#00d2d2')
const glow = computed(() => r.value.visual?.orbGlowColor || r.value.visual?.orbColor || '#00ffff')
const statusClass = computed(() => (r.value.status || 'active').toLowerCase())
const hopFrame = computed(() => (r.value.frame === 'B' ? 'B' : 'A'))
const hopHue = computed(() => hopColor(r.value.hopDepth || 0, hopFrame.value))
const curDesc = computed(() => (props.currency ? describe(props.currency as any) : null))
const initials = computed(() => (r.value.displayName || r.value.name || '··').slice(0, 2).toUpperCase())

// §2026-06-14 — a PEER registry's icon_url is stored SAME-ORIGIN-relative (the
// upload endpoint + the receiving registry's sync normalization both enforce
// that for security). Rendered as-is it resolves against the VIEWER's origin →
// 404 when the icon physically lives on the peer. Resolve a relative icon
// against the peer's own host (publicUrl, from its trusted card) so peer avatars
// (e.g. Frame-B's icon) display everywhere, not only on the peer's own site.
// Absolute icon_urls + local registry (no host) pass through unchanged.
const resolvedIconUrl = computed<string | undefined>(() => resolvePeerAsset(r.value.visual?.iconUrl, r.value.publicUrl))
</script>

<template>
  <div class="rhc-card">
    <div class="rhc-accent" :style="{ background: `linear-gradient(90deg, ${accent}, ${glow}66, transparent)` }"></div>

    <!-- Icon row ALWAYS renders. Three states: (1) flare encirclement equipped
         → FlareEncirclement with overlay; (2) icon uploaded but no flare →
         UserAvatar; (3) neither → orb-coloured placeholder with initials. -->
    <div class="rhc-avatar-row">
      <FlareEncirclement
        v-if="r.visual?.flareEncirclementVariant"
        tier="shadow_chancellor"
        :variant="r.visual.flareEncirclementVariant"
        :overlay="r.visual?.flareEncirclementOverlay || null"
        :avatar-url="resolvedIconUrl"
        :initials="initials"
        size="md"
        class="rhc-avatar"
      />
      <UserAvatar
        v-else-if="r.visual?.iconUrl"
        :avatar-url="resolvedIconUrl"
        :display-name="r.name"
        size="md"
        class="rhc-avatar"
      />
      <span v-else class="rhc-avatar-ph"
        :style="{ background: `radial-gradient(circle, ${accent}, ${glow}88)`, boxShadow: `0 0 12px ${accent}` }">
        <span style="font-weight:600; color:#001020; font-size:13px">{{ initials }}</span>
      </span>
      <div class="rhc-name-wrap">
        <span class="rhc-name">{{ r.displayName || r.name }}</span>
        <span class="rhc-status-badge" :class="statusClass">{{ (r.status || 'ACTIVE').toUpperCase() }}</span>
        <span v-if="curDesc" class="rhc-hop-badge"
          :title="`Settlement currency: ${currency}`"
          :style="{ borderColor: curDesc.accent + '88', color: curDesc.accent }">
          <span aria-hidden="true">{{ curDesc.glyph }}</span> {{ currency }}
        </span>
        <span v-if="(r.hopDepth || 0) > 0" class="rhc-hop-badge"
          :style="{ borderColor: hopHue + '88', color: hopHue }">
          HOP {{ r.hopDepth }}
        </span>
        <span v-if="r.visual?.sovereignVariant" class="rhc-synced-badge"
          :style="{ background: 'linear-gradient(90deg, ' + (r.visual.orbColor || '#888') + '44, transparent)', color: r.visual.orbColor || '#fff', borderColor: (r.visual.orbColor || '#888') + '88' }">
          ★ {{ r.visual.sovereignVariant.toUpperCase() }}
        </span>
        <span v-if="r.visual?.flareEncirclementOverlay" class="rhc-synced-badge"
          :style="{ color: '#ff5252', borderColor: '#ff5252', background: 'rgba(255,82,82,0.1)' }">
          <Icon name="mdi:lightning-bolt" /> {{ r.visual.flareEncirclementOverlay.toUpperCase() }}
        </span>
        <span v-if="r.exchange?.enabled" class="rhc-hop-badge"
          :title="r.exchange.passport_enabled ? `AGORA market · ${r.exchange.currency} · accepts Passport` : `AGORA market · ${r.exchange.currency}`"
          :style="{ borderColor: '#ffd54f88', color: '#ffd54f', background: 'rgba(255,213,79,0.08)' }">
          <Icon name="mdi:chart-line" /> {{ r.exchange.currency || 'MARKET' }}
        </span>
      </div>
    </div>

    <div class="rhc-detail" v-if="r.publicUrl"><span class="rhc-url">{{ r.publicUrl }}</span></div>
    <div class="rhc-desc" v-if="r.description">{{ r.description }}</div>

    <div class="rhc-stats">
      <span class="rhc-stat"><span class="rhc-stat-label">Health</span><span class="rhc-stat-value" style="color:#00e676">{{ r.health != null ? r.health + '%' : '100%' }}</span></span>
      <span class="rhc-stat"><span class="rhc-stat-label">Agents</span><span class="rhc-stat-value">{{ r.agentCount ?? 0 }}</span></span>
      <span class="rhc-stat" v-if="r.protocolVersion"><span class="rhc-stat-label">Protocol</span><span class="rhc-stat-value" style="font-size:11px">v{{ r.protocolVersion }}</span></span>
    </div>

    <!-- Registry Card v0.4 — fee composition (intra · cross · hosting) -->
    <div class="rhc-stats rhc-fee-rail" v-if="r.fees">
      <span class="rhc-stat" v-if="r.fees.intraRegistry != null">
        <span class="rhc-stat-label">Intra</span>
        <span class="rhc-stat-value" style="color:#4fc3f7">{{ r.fees.intraRegistry }}%</span>
      </span>
      <span class="rhc-stat" v-if="r.fees.crossRegistry != null">
        <span class="rhc-stat-label">Cross-Reg</span>
        <span class="rhc-stat-value" style="color:#ffaa00">{{ r.fees.crossRegistry }}%</span>
      </span>
      <span class="rhc-stat" v-if="r.fees.hostingEnabled">
        <span class="rhc-stat-label">Hosting</span>
        <span class="rhc-stat-value" style="color:#ff6b35">{{ r.fees.hostingRate || 0 }}%</span>
      </span>
      <span class="rhc-stat" v-else-if="r.fees.hostingEnabled === false">
        <span class="rhc-stat-label">Hosting</span>
        <span class="rhc-stat-value" style="color:#00e676;font-size:10px">FREE</span>
      </span>
    </div>

    <div class="rhc-auth" v-if="r.authMethods && r.authMethods.length > 0">
      <span class="rhc-stat-label">Auth</span>
      <span class="rhc-auth-tag" v-for="m in r.authMethods.filter(a => a !== 'bearer_token')" :key="m">{{ m.replace(/_/g, ' ') }}</span>
    </div>

    <!-- Registry Card v0.3 — signature trust indicator -->
    <div class="rhc-sync" v-if="r.cardEtag">
      <span class="rhc-stat-label">Card</span>
      <span :style="{ color: r.cardSignatureVerified ? '#00e676' : '#ffaa00', fontSize: '10px', marginLeft: '4px' }">
        {{ r.cardSignatureVerified ? '✓ SIGNED' : '⚠ UNSIGNED' }} v0.4
      </span>
    </div>
    <div class="rhc-sync" v-if="r.lastSyncedAt">
      <span class="rhc-stat-label">Last Sync</span>
      <span style="color:#90a4ae;font-size:10px;margin-left:4px">{{ formatFeedTime(new Date(r.lastSyncedAt).getTime()) }}</span>
    </div>

    <div class="rhc-hint">▸ click for the full registry card</div>
  </div>
</template>

<style scoped>
/* Chrome cloned from AgentWorld's .aw-galactic-tooltip (minus position:fixed —
   the host wrapper positions it). position:relative + overflow:hidden anchor +
   clip the accent bar. */
.rhc-card {
  position: relative; overflow: hidden;
  background: rgba(8, 10, 20, 0.92); backdrop-filter: blur(12px);
  border: 1px solid rgba(100, 140, 255, 0.2); border-radius: 10px; padding: 10px 14px;
  min-width: 200px; max-width: 320px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5), 0 0 20px rgba(50, 100, 255, 0.08);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px; line-height: 1.4; color: #e0e0e0;
}
.rhc-accent { position: absolute; top: 0; left: 0; right: 0; height: 3px; opacity: 0.9; }
.rhc-avatar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.rhc-avatar { flex-shrink: 0; }
.rhc-avatar-ph {
  width: 36px; height: 36px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  font-family: var(--mono, ui-monospace, monospace);
}
.rhc-name-wrap { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.rhc-name { font-weight: 600; font-size: 13px; color: #e8eaf6; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 200px; }
.rhc-status-badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 9px; font-weight: 700; letter-spacing: 0.5px; margin-left: auto; }
.rhc-status-badge.active { background: rgba(0,230,118,0.2); border: 1px solid rgba(0,230,118,0.5); color: #00e676; }
.rhc-status-badge.pending { background: rgba(255,179,0,0.2); border: 1px solid rgba(255,179,0,0.5); color: #ffb300; }
.rhc-status-badge.inactive { background: rgba(255,82,82,0.2); border: 1px solid rgba(255,82,82,0.5); color: #ff5252; }
.rhc-hop-badge { display: inline-block; padding: 1px 6px; background: rgba(0,0,0,0.3);
  border: 1px solid; border-radius: 4px; font-size: 9px; font-weight: 700; letter-spacing: 0.5px; }
.rhc-synced-badge { display: inline-block; padding: 1px 6px; border: 1px solid; border-radius: 4px; font-size: 9px; font-weight: 700; letter-spacing: 0.5px; }
.rhc-detail { margin-bottom: 6px; }
.rhc-url { font-size: 11px; color: #4fc3f7; font-family: 'SF Mono', 'Fira Code', monospace; word-break: break-all; }
.rhc-desc { font-size: 11px; color: #90a4ae; line-height: 1.4; margin-bottom: 6px; max-width: 280px; }
.rhc-stats { display: flex; gap: 16px; flex-wrap: wrap; }
.rhc-stat { display: flex; flex-direction: column; gap: 1px; }
.rhc-stat-label { font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; color: #78909c; }
.rhc-stat-value { font-size: 13px; font-weight: 700; color: #e0e0e0; }
.rhc-fee-rail { background: rgba(255,255,255,0.03); border-radius: 6px; padding: 5px 8px; margin-top: 5px; }
.rhc-auth { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.rhc-auth-tag { font-size: 9px; padding: 1px 5px; background: rgba(171,71,188,0.15); border: 1px solid rgba(171,71,188,0.35); border-radius: 3px; color: #ce93d8; text-transform: capitalize; }
.rhc-sync { display: flex; align-items: center; gap: 4px; margin-top: 4px; }
.rhc-hint { margin-top: 7px; font-size: 9.5px; letter-spacing: 0.04em; color: rgba(255,255,255,0.45); text-transform: uppercase; }
</style>
