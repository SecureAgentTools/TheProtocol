<script setup lang="ts">
// ─────────────────────────────────────────────────────────────────────────────
// §DISCPANEL (2026-09-06, his ask) — the second bar: the FEDERATED INDEX, in the same language as the
// federation strip above it, answering the two questions that bar cannot: is the index live, and which
// registries does this console read FROM THE INDEX rather than from its own federation sync.
//
// The distinction is the whole point of the index. A registry's own strip lists the peers it syncs with
// directly — every card of theirs is copied into this frame's database. The index lists what it can SEE
// without copying: the same component, read from signed public feeds, at a hop depth each source sets for
// itself. A registry that appears in both is synced AND indexed; one that appears only here is visible but
// not mirrored, which is exactly the state the scaling design wants most nodes to be in.
// ─────────────────────────────────────────────────────────────────────────────
import { ref, computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import type { DirectorySource, DirectoryStatus, DirectoryListing } from '@/services/api/directory'

const { t, tp } = useI18n()
const { directoryDiscoveryEnabled } = useRegistryConfig()
const props = defineProps<{
  /** The peers this frame syncs DIRECTLY (its ACTIVE federation rows). */
  syncedPeers?: string[]
  /** This console's OWN registry — it is not a peer of itself, and a blank mark on it reads as "the only one
   *  not synced", which is the wrong sentence: its agents are here because they were born here. */
  localRegistry?: string
  /** §DISCMIX — the bar does NOT fetch: the view makes ONE index call for the whole page and passes it here. */
  status?: DirectoryStatus | null
  listings?: DirectoryListing[]
  failedReason?: string
  asOf?: number | null
}>()

const showInfo = ref(false)
const sources = computed<DirectorySource[]>(() => props.status?.sources || [])
const agentsTotal = computed(() => props.status?.agentsTotal || 0)
const lastCycleAt = computed(() => props.status?.lastCycleAt ?? null)
const failed = computed(() => props.failedReason || '')

const verified = computed(() => sources.value.filter(s => s.verified).length)
const freshness = computed(() => {
  if (!lastCycleAt.value) return ''
  const secs = Math.max(0, Math.round(Date.now() / 1000 - lastCycleAt.value))
  return secs < 90 ? tp('discoveryView.directory.freshSeconds', '{n}s ago', { n: secs })
                   : tp('discoveryView.directory.freshMinutes', '{n} min ago', { n: Math.round(secs / 60) })
})
/** A source this console ALSO syncs directly — shown so the two bars can be read against each other. */
function alsoSynced(name: string): boolean {
  return (props.syncedPeers || []).some(p => (p || '').toLowerCase() === (name || '').toLowerCase())
}
function isSelf(name: string): boolean {
  return !!props.localRegistry && (props.localRegistry || '').toLowerCase() === (name || '').toLowerCase()
}

/** The venues the index holds, deduplicated by symbol — the cross-frame market view no single registry has. */
const venues = computed(() => props.listings || [])
</script>

<template>
  <div v-if="directoryDiscoveryEnabled" class="disc-idx-strip" data-testid="directory-strip">
    <div class="disc-idx-node disc-idx-node--self">
      <span class="disc-idx-dot" :class="failed ? 'disc-idx-dot--down' : 'disc-idx-dot--live'"></span>
      <span class="disc-idx-label">{{ t('discoveryView.directory.stripTitle', 'Federated index') }}</span>
      <span class="disc-idx-badge" :class="failed ? 'disc-idx-badge--down' : ''">
        {{ failed ? t('discoveryView.directory.down', 'UNREACHABLE') : t('discoveryView.active') }}
      </span>
    </div>

    <div class="disc-idx-line"><div class="disc-idx-pulse"></div></div>

    <div v-for="s in sources" :key="s.name" class="disc-idx-node"
         :title="(s.verified ? 'card signature verified' : 'card NOT verified: ' + (s.reason || '?'))
                 + ' · ' + s.agentsIndexed + ' agents indexed · hop ' + (s.hops ?? '?')
                 + (isSelf(s.name) ? ' · this console\'s own registry'
                    : alsoSynced(s.name) ? ' · also synced directly into this frame' : ' · read from the index only')">
      <span class="disc-idx-dot" :class="s.verified ? 'disc-idx-dot--live' : 'disc-idx-dot--warn'"></span>
      <span class="disc-idx-label">{{ s.name }}</span>
      <span class="disc-idx-count">{{ s.agentsIndexed }}</span>
      <span class="disc-idx-hop" :title="t('discoveryView.directory.hopTitle', 'How many federation hops out this source is indexed to')">
        h{{ s.hops ?? '?' }}
      </span>
      <span v-if="isSelf(s.name)" class="disc-idx-self">{{ t('discoveryView.directory.selfMark', 'this frame') }}</span>
      <span v-else-if="alsoSynced(s.name)" class="disc-idx-sync">{{ t('discoveryView.directory.alsoSynced', 'synced') }}</span>
    </div>

    <div class="disc-idx-spacer"></div>
    <span v-if="failed" class="disc-idx-fail" data-testid="directory-strip-failed">{{ failed }}</span>
    <span v-else class="disc-idx-meta">
      {{ tp('discoveryView.directory.stripMeta', '{a} agents · {v}/{n} verified', { a: agentsTotal, v: verified, n: sources.length }) }}
      <span v-if="freshness" class="disc-idx-fresh">· {{ freshness }}</span>
    </span>
    <button class="disc-info-btn" type="button" data-testid="directory-strip-info"
            :aria-label="t('discoveryView.directory.whatIsThis', 'What is the federated index?')"
            @click="showInfo = !showInfo">i</button>

    <div v-if="venues.length" class="disc-idx-venues" data-testid="directory-strip-venues">
      <span class="disc-idx-venues-label">{{ t('discoveryView.directory.venues', 'Markets in this federation') }}:</span>
      <span v-for="l in venues" :key="l.symbol + l.source" class="disc-idx-venue">
        {{ l.symbol }} · {{ l.currency }} · {{ l.venue?.name || l.source }}
      </span>
    </div>

    <div v-if="showInfo" class="disc-info-pop" data-testid="directory-strip-info-pop">
      <p class="disc-info-h">{{ t('discoveryView.directory.stripTitle', 'Federated index') }}</p>
      <p>{{ t('discoveryView.directory.infoWhat', 'A read-only index that pulls the signed public feeds of the registries this federation already admits. It finds; the home registry still decides and still serves.') }}</p>
      <p>{{ t('discoveryView.directory.infoCounts', 'Each chip is a registry the index reads, with the number of its own agents indexed and h = how many federation hops out it sits. “synced” marks a registry this frame ALSO mirrors directly — the others are visible here without being copied into this database.') }}</p>
      <p class="disc-info-dim">{{ t('discoveryView.directory.infoHops', 'Hop depth is per source, so a registry with room to spare can index further out than one without.') }}</p>
      <!-- §NUMALIGN (2026-09-08, his report: "the numbers confusing me"). THE ONE SENTENCE THAT
           EXPLAINS EVERY MISMATCH ON THIS PAGE. This bar counts what each registry PUBLISHES; the
           marketplace below lists only what holds a reputation bond, because listing is one of the
           six bond sites. On EU that is 56 against 38, and all 18 of the difference are system and
           test agents — the FX router, the canaries, the AGORA gateway, a treasury. Both numbers
           were always right; nothing said they answered different questions. -->
      <p class="disc-info-why">{{ t('discoveryView.directory.infoVsList', 'These counts are usually HIGHER than the list below, and that is the bond gate, not an error: this bar counts everything a registry publishes, while the marketplace lists only agents that hold a reputation bond. System agents — an FX router, canaries, a treasury — never hold one, so they are published and not listed.') }}</p>
    </div>
  </div>
</template>

<style scoped>
/* the federation strip's language (Design_Language.md §2/§4), one shade quieter so the two bars stack */
.disc-info-why { margin-top: 6px; padding-top: 6px; border-top: 1px solid rgba(var(--nc-primary-rgb), 0.12); }
.disc-idx-strip {
  display: flex; align-items: center; gap: 8px; padding: 8px 12px; margin-bottom: 12px;
  position: relative; flex-wrap: wrap;
  background: rgba(var(--nc-primary-rgb), 0.03);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.12);
  border-radius: 10px;
}
.disc-idx-node { display: flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 6px; font-size: 11px;
  background: rgba(var(--nc-primary-rgb), 0.05); border: 1px solid rgba(var(--nc-primary-rgb), 0.14); }
.disc-idx-node--self { background: rgba(var(--nc-primary-rgb), 0.1); border-color: rgba(var(--nc-primary-rgb), 0.3); }
.disc-idx-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.disc-idx-dot--live { background: var(--nc-primary, #22d3ee); box-shadow: 0 0 6px rgba(var(--nc-primary-rgb), 0.8); }
.disc-idx-dot--warn { background: #e0a33e; }
.disc-idx-dot--down { background: #ff6b6b; }
.disc-idx-label { font-weight: 600; letter-spacing: .02em; }
.disc-idx-count { font-variant-numeric: tabular-nums; opacity: .75; }
.disc-idx-hop { font-size: 9px; padding: 1px 4px; border-radius: 3px; opacity: .8;
  background: rgba(var(--nc-primary-rgb), 0.08); border: 1px solid rgba(var(--nc-primary-rgb), 0.2); }
.disc-idx-sync { font-size: 9px; padding: 1px 5px; border-radius: 3px; color: #00e676;
  background: rgba(0, 230, 118, 0.1); border: 1px solid rgba(0, 230, 118, 0.28); }
.disc-idx-self { font-size: 9px; padding: 1px 5px; border-radius: 3px; color: var(--nc-primary, #22d3ee);
  background: rgba(var(--nc-primary-rgb), 0.12); border: 1px solid rgba(var(--nc-primary-rgb), 0.34); }
.disc-idx-badge { font-size: 9px; padding: 1px 5px; border-radius: 3px; color: #00e676;
  background: rgba(0, 230, 118, 0.12); border: 1px solid rgba(0, 230, 118, 0.3); }
.disc-idx-badge--down { color: #ff6b6b; background: rgba(255, 107, 107, 0.1); border-color: rgba(255, 107, 107, 0.3); }
.disc-idx-line { flex: 0 0 26px; height: 1px; background: linear-gradient(90deg, transparent, rgba(var(--nc-primary-rgb), 0.35), transparent); position: relative; }
.disc-idx-pulse { position: absolute; inset: 0; }
.disc-idx-spacer { flex: 1 1 auto; }
.disc-idx-meta { font-size: 11px; opacity: .7; font-variant-numeric: tabular-nums; }
.disc-idx-fresh { opacity: .6; }
.disc-idx-fail { font-size: 11px; color: #ff6b6b; }
.disc-idx-venues { flex-basis: 100%; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 10px; margin-top: 2px; }
.disc-idx-venues-label { opacity: .6; }
.disc-idx-venue { padding: 1px 6px; border-radius: 3px; opacity: .85;
  background: rgba(var(--nc-primary-rgb), 0.06); border: 1px solid rgba(var(--nc-primary-rgb), 0.18); }
.disc-info-btn {
  width: 16px; height: 16px; line-height: 14px; border-radius: 50%; font-size: 10px; font-weight: 700;
  color: var(--nc-primary, #22d3ee); background: rgba(var(--nc-primary-rgb), 0.1);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.35); cursor: pointer; flex-shrink: 0;
}
.disc-info-btn:hover { background: rgba(var(--nc-primary-rgb), 0.2); }
.disc-info-pop {
  position: absolute; right: 8px; top: calc(100% + 6px); z-index: 40; max-width: 460px;
  padding: 10px 12px; font-size: 11px; line-height: 1.5;
  background: linear-gradient(168deg, rgba(255,255,255,0.03), rgba(255,255,255,0) 60%), rgba(8, 13, 24, 0.96);
  border: 1px solid rgba(var(--nc-primary-rgb), 0.28); border-radius: 12px;
  box-shadow: 0 18px 42px -20px rgba(0,0,0,0.9);
}
.disc-info-pop p { margin: 0 0 6px; }
.disc-info-pop p:last-child { margin-bottom: 0; }
.disc-info-h { font-weight: 700; color: var(--nc-primary, #22d3ee); }
.disc-info-dim { opacity: .7; }
</style>
