<!--
  FlareCelebrationModal — one-shot Shadow Chancellor upgrade reveal (§15).

  Mounted globally in App.vue. Watches for the "I just crossed the €500
  cumulative threshold + haven't acknowledged yet" state via /fiat/flare/status.

  When the trigger fires:
    1. Modal opens with a slow reveal — encirclement breath, ominous tone.
    2. Shows the 4 variant tiles (live encirclement preview at xl).
    3. Click a variant → PATCH variant + POST /flare/celebration-acknowledge.
    4. Modal closes; will never show again for this developer.

  Defense-in-depth: the modal also accepts a "Maybe later" dismissal which
  still acknowledges so it doesn't reappear (the ack is the contract — the
  variant choice is incidental). Picker is reachable later via /flare-manager.

  Trigger conditions (all must be true):
    • authStore.isAuthenticated
    • flareStatus.flare_tier === 'shadow_chancellor'
    • flareStatus.should_celebrate === true
    • !openedThisSession (prevents re-open within a single browser session)
-->
<template>
  <Teleport to="body">
    <Transition name="fc-modal">
      <div
        v-if="isOpen"
        class="fcm-overlay"
        @click.self="dismissAndAck"
      >
        <div class="fcm-card" role="dialog" aria-labelledby="fcm-title" aria-modal="true">
          <!-- Eyebrow + title -->
          <div class="fcm-eyebrow">CUMULATIVE ≥ €500</div>
          <h2 id="fcm-title" class="fcm-title">Shadow Chancellor.</h2>
          <p class="fcm-sub">
            You've crossed the hidden threshold. Your encirclement is permanent —
            color customization stays locked for this tier. Pick your style. You
            can change it any time from <span class="fcm-mono">/flare-manager</span>.
          </p>

          <!-- 4 variant tiles -->
          <div class="fcm-grid">
            <button
              v-for="v in VARIANTS"
              :key="v.id"
              class="fcm-tile"
              :class="{ 'fcm-tile--active': pickedVariant === v.id }"
              :disabled="busy"
              @click="pickVariant(v.id)"
            >
              <FlareEncirclement
                tier="shadow_chancellor"
                :variant="v.id"
                :initials="initials"
                size="xl"
              />
              <div class="fcm-tile-meta">
                <span class="fcm-tile-label">{{ v.label }}</span>
                <span class="fcm-tile-sub">{{ v.sub }}</span>
              </div>
              <span v-if="pickedVariant === v.id" class="fcm-tile-tag">CHOSEN</span>
              <span v-else-if="v.locked" class="fcm-tile-tag fcm-tile-tag--locked">SOON</span>
            </button>
          </div>

          <!-- Footer -->
          <div class="fcm-footer">
            <button
              class="fcm-btn fcm-btn-ghost"
              :disabled="busy"
              @click="dismissAndAck"
            >
              Maybe later
            </button>
            <button
              class="fcm-btn fcm-btn-primary"
              :disabled="busy || !pickedVariant"
              @click="commitAndAck"
            >
              <span v-if="busy">Saving…</span>
              <span v-else-if="pickedVariant">Wear {{ labelFor(pickedVariant) }}</span>
              <span v-else>Pick a style first</span>
            </button>
          </div>

          <p v-if="error" class="fcm-error">{{ error }}</p>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { apiClient } from '@/services/api/client'
import FlareEncirclement from '@/components/common/FlareEncirclement.vue'

type Variant =
  | 'sauron' | 'goth' | 'obsidian' | 'void'
  | 'aurora' | 'phoenix' | 'crystal'
  | 'blackhole' | 'halloween'
  | 'inferno' | 'glacier' | 'matrix'
  | 'galaxy' | 'ink' | 'circuit'
  | 'yule' | 'sakura' | 'solstice' | 'harvest'

const VARIANTS: Array<{ id: Variant; label: string; sub: string; locked?: boolean }> = [
  { id: 'sauron',    label: 'Sauron',     sub: 'Black void · red eye watching from above' },
  { id: 'goth',      label: 'Goth',       sub: 'Four-blob purple gooey halo' },
  { id: 'obsidian',  label: 'Obsidian',   sub: 'Polished black mirror · iridescent rim' },
  { id: 'void',      label: 'Void',       sub: 'Concentric event-horizon rings' },
  { id: 'aurora',    label: 'Aurora',     sub: 'Cold ethereal curtains · green/violet' },
  { id: 'phoenix',   label: 'Phoenix',    sub: 'Rising fire bird wreath',           locked: true },
  { id: 'crystal',   label: 'Crystal',    sub: 'Faceted gemstone refraction',       locked: true },
  { id: 'blackhole', label: 'Black Hole', sub: 'You ARE the singularity',           locked: true },
  { id: 'halloween', label: 'Halloween',  sub: 'Glowing skull mask · seasonal',     locked: true },
  // §19 (2026-05-13) — 4th wave (6 new, all locked cosmetically)
  { id: 'inferno',   label: 'Inferno',    sub: 'Dragon-fire · crimson flame walls', locked: true },
  { id: 'glacier',   label: 'Glacier',    sub: 'Frozen crystalline frost shards',   locked: true },
  { id: 'matrix',    label: 'Matrix',     sub: 'Green digital rain · falling glyphs', locked: true },
  { id: 'galaxy',    label: 'Galaxy',     sub: 'Spiral arms · supernova flare',     locked: true },
  { id: 'ink',       label: 'Ink',        sub: 'Sumi-e brushstrokes · crimson seal', locked: true },
  { id: 'circuit',   label: 'Circuit',    sub: 'Neon cyberpunk · data flow traces', locked: true },
  // §20 (2026-05-13) — seasonal wave (4 new, locked cosmetically)
  { id: 'yule',      label: 'Yule',       sub: 'Winter snowflakes + warm gold ribbons', locked: true },
  { id: 'sakura',    label: 'Sakura',     sub: 'Spring cherry blossom petals drifting', locked: true },
  { id: 'solstice',  label: 'Solstice',   sub: 'Summer sunburst rays + golden waves',   locked: true },
  { id: 'harvest',   label: 'Harvest',    sub: 'Autumn maple leaves drifting amber',    locked: true },
]
function labelFor(v: Variant | null): string {
  return VARIANTS.find(x => x.id === v)?.label || ''
}

const authStore = useAuthStore()

const isOpen = ref(false)
const pickedVariant = ref<Variant | null>(null)
const busy = ref(false)
const error = ref('')
// Re-open guard — once dismissed/closed in this session, don't re-trigger
// even if the watcher fires again (e.g., post-PATCH refresh).
let openedThisSession = false

const initials = computed<string>(() => {
  const u: any = authStore.user
  const src = u?.display_name || u?.name || u?.email || '?'
  return src.split(/[\s@.]+/).filter(Boolean).map((w: string) => w[0]).join('').slice(0, 2).toUpperCase() || '?'
})

async function maybeTrigger() {
  if (openedThisSession || isOpen.value) return
  if (!authStore.isAuthenticated) return
  // Cheap pre-check — only hit /flare/status when the user object hints at
  // shadow_chancellor. Saves a request on every page load for non-Shadow devs.
  const u: any = authStore.user
  if (!u || u.flare_tier !== 'shadow_chancellor') return

  try {
    const r = await apiClient.get('/fiat/flare/status')
    if (r.data?.should_celebrate === true) {
      // Default the picker to the dev's current variant (if already 'sauron'
      // from migration backfill) so they're not picking from zero.
      pickedVariant.value = (r.data?.flare_encirclement_variant as Variant) || 'sauron'
      isOpen.value = true
      openedThisSession = true
    }
  } catch {
    // Silent — this isn't critical; user can pick variant later from FlareManager.
  }
}

function pickVariant(v: Variant) {
  pickedVariant.value = v
}

async function commitAndAck() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    // Set variant first, then ack. Two requests but both are tiny.
    if (pickedVariant.value) {
      await apiClient.patch('/fiat/flare/selection', { variant: pickedVariant.value })
    }
    const ack = await apiClient.post('/fiat/flare/celebration-acknowledge')
    // Sync auth store so header/sidebar pick up the new variant immediately.
    if (authStore.user) {
      ;(authStore.user as any).flare_encirclement_variant = ack.data?.flare_encirclement_variant ?? pickedVariant.value
      ;(authStore.user as any).flare_celebration_seen_at = new Date().toISOString()
    }
    isOpen.value = false
  } catch (e: any) {
    error.value = e?.response?.data?.detail || 'Could not save your choice. Try again, or use /flare-manager.'
  } finally {
    busy.value = false
  }
}

async function dismissAndAck() {
  // "Maybe later" still acknowledges so the modal doesn't re-trigger on
  // every page load. Picker stays available at /flare-manager.
  if (busy.value) return
  busy.value = true
  try {
    await apiClient.post('/fiat/flare/celebration-acknowledge')
    if (authStore.user) {
      ;(authStore.user as any).flare_celebration_seen_at = new Date().toISOString()
    }
  } catch {
    /* swallow — closing the modal is more important than the ack here */
  } finally {
    busy.value = false
    isOpen.value = false
  }
}

// Trigger on mount + on auth-state changes (login fires this)
onMounted(maybeTrigger)
watch(() => authStore.isAuthenticated, (v) => { if (v) setTimeout(maybeTrigger, 800) })
watch(() => (authStore.user as any)?.flare_tier, (t) => {
  // Crossing the threshold mid-session (just paid) — flare_tier flips to
  // shadow_chancellor; trigger the modal after a short delay so the payment
  // flow's own success state finishes rendering first.
  if (t === 'shadow_chancellor') setTimeout(maybeTrigger, 1200)
})
</script>

<style scoped>
/* Overlay — dim the world while the modal is up. Backdrop-filter blur
   pulls focus to the encirclement preview. z-index above everything
   else (CommandPalette = 10000-ish; we go higher). */
.fcm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.78);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  z-index: 10100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow-y: auto;
}

.fcm-card {
  position: relative;
  width: 100%;
  max-width: 920px;
  padding: 36px 36px 28px;
  border-radius: 14px;
  /* Card surface — deep violet→black diagonal with subtle red accretion at
     the bottom so the Shadow Chancellor moment lands. */
  background:
    radial-gradient(ellipse 80% 50% at 50% 110%, rgba(127, 29, 29, 0.18) 0%, transparent 60%),
    radial-gradient(ellipse 80% 60% at 30% -10%, rgba(91, 33, 158, 0.18) 0%, transparent 60%),
    linear-gradient(160deg, rgba(15, 8, 28, 0.98) 0%, rgba(0, 0, 0, 0.99) 100%);
  border: 1px solid rgba(167, 139, 250, 0.32);
  box-shadow:
    0 24px 80px rgba(0, 0, 0, 0.7),
    0 0 0 1px rgba(167, 139, 250, 0.08) inset,
    0 0 60px -10px rgba(91, 33, 158, 0.55);
  color: rgba(220, 220, 240, 0.95);
  font-family: 'IBM Plex Mono', 'Fira Code', ui-monospace, monospace;
}

.fcm-eyebrow {
  font-size: 11px;
  letter-spacing: 0.2em;
  color: rgba(220, 38, 38, 0.85);
  text-transform: uppercase;
  margin-bottom: 8px;
  text-shadow: 0 0 8px rgba(220, 38, 38, 0.45);
}
.fcm-title {
  font-size: clamp(28px, 4vw, 42px);
  font-weight: 700;
  letter-spacing: -0.02em;
  color: rgba(255, 255, 255, 0.98);
  margin: 0 0 12px;
  text-shadow: 0 0 18px rgba(167, 139, 250, 0.32);
}
.fcm-sub {
  font-size: 13.5px;
  line-height: 1.6;
  color: rgba(200, 200, 220, 0.72);
  margin: 0 0 26px;
  max-width: 640px;
}
.fcm-mono {
  font-family: 'IBM Plex Mono', monospace;
  color: rgba(196, 181, 253, 0.95);
  background: rgba(91, 33, 158, 0.18);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12.5px;
}

.fcm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 14px;
  margin-bottom: 22px;
}
.fcm-tile {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  gap: 14px;
  padding: 24px 16px 18px;
  border-radius: 10px;
  border: 1px solid rgba(0, 0, 0, 0.55);
  background:
    radial-gradient(circle at 50% 110%, rgba(127, 29, 29, 0.05) 0%, transparent 60%),
    linear-gradient(180deg, rgba(15, 12, 22, 0.85) 0%, rgba(0, 0, 0, 0.95) 100%);
  cursor: pointer;
  transition: border-color 0.22s, transform 0.22s, box-shadow 0.22s;
  font-family: inherit;
  color: inherit;
  overflow: hidden;
  isolation: isolate;
}
.fcm-tile:hover:not(:disabled) {
  border-color: rgba(196, 181, 253, 0.55);
  transform: translateY(-2px);
  box-shadow:
    0 10px 28px rgba(0, 0, 0, 0.55),
    0 0 0 1px rgba(196, 181, 253, 0.18);
}
.fcm-tile:disabled { opacity: 0.55; cursor: not-allowed; }
.fcm-tile--active {
  border-color: rgba(196, 181, 253, 0.95);
  background:
    radial-gradient(circle at 50% 110%, rgba(127, 29, 29, 0.16) 0%, transparent 60%),
    linear-gradient(180deg, rgba(35, 16, 65, 0.55) 0%, rgba(8, 0, 18, 1) 100%);
  box-shadow:
    0 0 0 1px rgba(196, 181, 253, 0.5),
    0 0 26px -4px rgba(91, 33, 158, 0.65);
}
.fcm-tile-meta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  text-align: center;
}
.fcm-tile-label {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: rgba(220, 200, 255, 0.95);
}
.fcm-tile-sub {
  font-size: 11px;
  color: rgba(180, 180, 200, 0.65);
  line-height: 1.5;
  max-width: 200px;
}
.fcm-tile-tag {
  position: absolute;
  top: 8px;
  right: 8px;
  font-size: 9px;
  letter-spacing: 0.14em;
  padding: 2px 6px;
  border-radius: 3px;
  color: rgb(196, 181, 253);
  background: rgba(91, 33, 158, 0.28);
  border: 1px solid rgba(196, 181, 253, 0.45);
}
.fcm-tile-tag--locked {
  color: rgba(252, 211, 77, 0.95);
  background: rgba(252, 211, 77, 0.08);
  border-color: rgba(252, 211, 77, 0.35);
}

.fcm-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
  padding-top: 14px;
  border-top: 1px solid rgba(167, 139, 250, 0.12);
}
.fcm-btn {
  padding: 11px 20px;
  border-radius: 6px;
  border: 1px solid;
  font-family: inherit;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  cursor: pointer;
  transition: background 0.18s, border-color 0.18s, color 0.18s, box-shadow 0.18s;
}
.fcm-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.fcm-btn-ghost {
  background: transparent;
  border-color: rgba(255, 255, 255, 0.18);
  color: rgba(255, 255, 255, 0.7);
}
.fcm-btn-ghost:hover:not(:disabled) {
  border-color: rgba(255, 255, 255, 0.35);
  color: rgba(255, 255, 255, 1);
}
.fcm-btn-primary {
  background: rgba(196, 181, 253, 0.95);
  border-color: rgba(196, 181, 253, 1);
  color: #100620;
}
.fcm-btn-primary:hover:not(:disabled) {
  background: rgba(216, 200, 255, 1);
  box-shadow: 0 0 22px rgba(91, 33, 158, 0.6);
}
.fcm-error {
  margin: 14px 0 0 0;
  color: rgba(248, 113, 113, 0.95);
  font-size: 12px;
}

/* Modal entrance — slow zoom + fade so the moment lands */
.fc-modal-enter-active, .fc-modal-leave-active {
  transition: opacity 380ms cubic-bezier(.2,.7,.2,1);
}
.fc-modal-enter-active .fcm-card,
.fc-modal-leave-active .fcm-card {
  transition: transform 380ms cubic-bezier(.2,.7,.2,1), opacity 380ms ease;
}
.fc-modal-enter-from { opacity: 0; }
.fc-modal-enter-from .fcm-card { transform: translateY(16px) scale(0.97); opacity: 0; }
.fc-modal-leave-to { opacity: 0; }
.fc-modal-leave-to .fcm-card { transform: translateY(8px) scale(0.98); opacity: 0; }

/* Mobile — stack tiles, tighten padding */
@media (max-width: 640px) {
  .fcm-card { padding: 24px 18px 18px; }
  .fcm-grid { grid-template-columns: 1fr; gap: 12px; }
  .fcm-tile { padding: 18px 14px 14px; }
  .fcm-footer { flex-direction: column-reverse; align-items: stretch; gap: 8px; }
  .fcm-btn { width: 100%; }
}
</style>
