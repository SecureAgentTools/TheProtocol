<!-- POCKET · Cosmetics sheet — §POCKETDISC (2026-08-23). Hold one of YOUR
     agents (or its ⋯ button) and dress it. Two slots, matching the server's
     model exactly: `corner` and `encirclement`, single bearer per slot per
     developer. The sheet's one job beyond the tap is HONESTY ABOUT THE MOVE:
     before equipping it names who currently bears the slot and states that
     equipping here takes it off them — the server then performs exactly that,
     atomically (`/fiat/flare/equip/{slot}/{did}` clears other bearers).

     Earned marks appear here DISPLAY-ONLY: they are ledger-earned and can
     never be equipped, bought, or moved — the sheet says so, so the surface
     itself teaches the difference (§AGENTDISC hard rule).

     Deep styling (variants, overlays, corner variants) stays in the Flare
     Manager; this sheet is where things go ON and OFF, plus the doors. -->
<template>
  <transition name="pk-sheet">
    <div v-if="open" class="pc-scrim" @click.self="close">
      <div ref="trapEl" class="pc-sheet" role="dialog" aria-modal="true" data-testid="pk-cosmetics"
           :aria-label="t('pocket.cosmetics.title', 'Cosmetics')">
        <div class="pc-grip" aria-hidden="true"></div>
        <h2 class="pc-title"><Icon name="mdi:palette-outline" /> {{ t('pocket.cosmetics.title', 'Cosmetics') }}
          <button class="pc-x" :aria-label="t('pocket.agentSheet.close', 'Close')" @click="close">&times;</button>
        </h2>
        <p class="pc-agent">{{ agent?.name || shorten(agent?.did || '') }}</p>

        <p v-if="loading" class="pc-note">{{ t('pocket.cosmetics.loading', 'Reading your flare locker…') }}</p>
        <p v-else-if="err" class="pc-note pc-warn" data-testid="pc-err">{{ err }}</p>

        <template v-else-if="ownsAnything">
          <div v-for="slot in slots" :key="slot.key" class="pc-slot" :data-testid="`pc-slot-${slot.key}`">
            <div class="pc-slot-head">
              <span class="pc-slot-name">{{ slot.label }}</span>
              <span class="pc-slot-what">{{ slot.selected || t('pocket.cosmetics.noneSelected', 'no style picked') }}</span>
            </div>
            <template v-if="slot.selected">
              <p class="pc-bearer" :data-testid="`pc-bearer-${slot.key}`">
                <template v-if="slot.bearerDid === agent?.did">{{ t('pocket.cosmetics.equippedHere', 'Equipped on this agent.') }}</template>
                <template v-else-if="slot.bearerDid">{{ tp('pocket.cosmetics.bearerIs', 'Currently on {name}.', { name: slot.bearerName || shorten(slot.bearerDid) }) }}</template>
                <template v-else>{{ t('pocket.cosmetics.bearerNone', 'Not equipped on any agent.') }}</template>
              </p>
              <p v-if="slot.bearerDid && slot.bearerDid !== agent?.did" class="pc-move" :data-testid="`pc-move-${slot.key}`">
                {{ tp('pocket.cosmetics.moveWarn', 'Equipping here moves it off {name}.', { name: slot.bearerName || shorten(slot.bearerDid) }) }}
              </p>
              <div class="pc-actions">
                <button v-if="slot.bearerDid !== agent?.did" class="pc-btn" :disabled="busy"
                        :data-testid="`pc-equip-${slot.key}`" @click="equip(slot.key)">
                  {{ busy ? t('pocket.cosmetics.working', 'Working…') : t('pocket.cosmetics.equipHere', 'Equip on this agent') }}</button>
                <button v-else class="pc-btn pc-ghost" :disabled="busy"
                        :data-testid="`pc-unequip-${slot.key}`" @click="unequip(slot.key)">
                  {{ busy ? t('pocket.cosmetics.working', 'Working…') : t('pocket.cosmetics.unequip', 'Unequip') }}</button>
              </div>
            </template>
            <p v-else class="pc-note">{{ t('pocket.cosmetics.pickFirst', 'You own this slot but no style is picked — choose one in the Flare Manager first.') }}</p>
          </div>
          <p v-if="doneMsg" class="pc-done" data-testid="pc-done">{{ doneMsg }}</p>
        </template>

        <template v-else>
          <p class="pc-note" data-testid="pc-none">{{ t('pocket.cosmetics.nothingOwned', 'You own no cosmetic flares yet. Flares are cosmetic tiers from the Flare Shop; they never affect ranking.') }}</p>
          <router-link class="pc-btn pc-link" to="/flare-shop" @click="close">{{ t('pocket.cosmetics.shopDoor', 'Open the Flare Shop') }}</router-link>
        </template>

        <!-- the earned line — display only, on purpose, always -->
        <p class="pc-earned" data-testid="pc-earned">
          <Icon name="mdi:check-decagram" />
          <template v-if="earnedJobs > 0">{{ tp('pocket.cosmetics.earnedLine', 'Earned mark: {n} verified jobs. Ledger-earned, cannot be equipped or bought.', { n: earnedJobs }) }}</template>
          <template v-else>{{ t('pocket.cosmetics.earnedNone', 'Earned marks come only from verified work on the ledger. They cannot be equipped or bought.') }}</template>
        </p>

        <router-link v-if="ownsAnything" class="pc-manager" to="/flare-manager" @click="close">
          {{ t('pocket.cosmetics.managerDoor', 'Fine-tune styles, variants & overlays in the Flare Manager') }}</router-link>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import { apiClient } from '@/services/api/client'
import { useFocusTrap } from '@/composables/useFocusTrap'
import { useI18n } from '@/composables/useI18n'

const props = defineProps<{
  open: boolean
  agent: { did: string; name?: string } | null
  /** the caller's own agents — bearer names resolve against these */
  ownAgents: { did: string; name?: string }[]
  /** the held agent's verified-jobs count (for the earned display line) */
  earnedJobs?: number
}>()
const emit = defineEmits<{ (e: 'close'): void; (e: 'changed'): void }>()
const { t, tp } = useI18n()

const trapEl = ref<HTMLElement | null>(null)
useFocusTrap(trapEl, { activeWhen: computed(() => props.open) })
function close() { emit('close') }
const shorten = (d: string) => (d && d.length > 26 ? `${d.slice(0, 14)}…${d.slice(-6)}` : d)
const earnedJobs = computed(() => props.earnedJobs || 0)

const loading = ref(false)
const busy = ref(false)
const err = ref('')
const doneMsg = ref('')
const status = ref<any | null>(null)
const bearers = ref<Record<string, { corner: boolean; enc: boolean; name?: string }>>({})

interface SlotView { key: 'corner' | 'encirclement'; label: string; selected: string | null; bearerDid: string | null; bearerName: string | null }
const slots = computed<SlotView[]>(() => {
  const s = status.value
  if (!s) return []
  const find = (which: 'corner' | 'enc'): { did: string | null; name: string | null } => {
    for (const [did, b] of Object.entries(bearers.value)) {
      if (b && (which === 'corner' ? b.corner : b.enc)) {
        const own = props.ownAgents.find(a => a.did === did)
        return { did, name: own?.name || (b as any).name || null }
      }
    }
    return { did: null, name: null }
  }
  const c = find('corner'); const e = find('enc')
  return [
    { key: 'corner', label: t('pocket.cosmetics.slotCorner', 'Corner badge'), selected: s.selected_corner_flare || null, bearerDid: c.did, bearerName: c.name },
    { key: 'encirclement', label: t('pocket.cosmetics.slotEncirclement', 'Encirclement'), selected: s.selected_encirclement_flare || null, bearerDid: e.did, bearerName: e.name },
  ]
})
const ownsAnything = computed(() => {
  const s = status.value
  if (!s) return false
  return !!(s.selected_corner_flare || s.selected_encirclement_flare
    || (s.unlocked_corner_flares || []).length || (s.unlocked_encirclement_flares || []).length)
})

async function load() {
  loading.value = true; err.value = ''; doneMsg.value = ''
  try {
    // Bearer truth lives on the AGENT rows (/developers/me/agents carries
    // bears_corner_flare / bears_encirclement_flare) — NOT on the card
    // mirror: local cards never persist card_data.flare, so the public
    // /agents/cosmetics batch is blind for your own local agents. Found by
    // this sheet's own battery (equip succeeded, the mirror said nobody
    // bears it). Same source the desktop Flare Manager reads.
    const [st, mine] = await Promise.all([
      apiClient.get('/fiat/flare/status'),
      apiClient.get('/developers/me/agents', { params: { limit: 500 } }),
    ])
    status.value = st.data
    const rows: any[] = Array.isArray(mine.data) ? mine.data : []
    const map: Record<string, { corner: boolean; enc: boolean; name?: string }> = {}
    for (const r of rows) {
      const did = r?.did
      if (!did) continue
      map[did] = { corner: !!r.bears_corner_flare, enc: !!r.bears_encirclement_flare, name: r.name || r.agent_card_name }
    }
    bearers.value = map
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || t('pocket.common.requestFailed', 'request failed')
  } finally { loading.value = false }
}

async function equip(slot: 'corner' | 'encirclement') {
  if (!props.agent?.did) return
  busy.value = true; err.value = ''; doneMsg.value = ''
  try {
    await apiClient.post(`/fiat/flare/equip/${slot}/${encodeURIComponent(props.agent.did)}`)
    try { navigator.vibrate?.(10) } catch { /* no haptics */ }
    doneMsg.value = t('pocket.cosmetics.equipped', 'Equipped. The registry cleared it from any other bearer.')
    emit('changed')
    await load()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || t('pocket.cosmetics.equipFailed', 'Equip failed — nothing was changed.')
  } finally { busy.value = false }
}
async function unequip(slot: 'corner' | 'encirclement') {
  if (!props.agent?.did) return
  busy.value = true; err.value = ''; doneMsg.value = ''
  try {
    await apiClient.post(`/fiat/flare/unequip/${slot}/${encodeURIComponent(props.agent.did)}`)
    doneMsg.value = t('pocket.cosmetics.unequipped', 'Unequipped. The slot is bare until you equip it somewhere.')
    emit('changed')
    await load()
  } catch (e: any) {
    err.value = e?.response?.data?.detail || e?.message || t('pocket.cosmetics.equipFailed', 'Equip failed — nothing was changed.')
  } finally { busy.value = false }
}

function onEscKey(e: KeyboardEvent) { if (e.key === 'Escape' && props.open && !busy.value) close() }
watch(() => props.open, (o) => {
  if (o) { window.addEventListener('keydown', onEscKey); void load() }
  else window.removeEventListener('keydown', onEscKey)
}, { immediate: true })
/* held agent changed while open (hold on another row) — reload for the new target */
watch(() => props.agent?.did, () => { if (props.open) void load() })
</script>

<style scoped>
.pc-scrim { position: fixed; inset: 0; z-index: 92; background: rgba(2,4,8,0.6); backdrop-filter: blur(2px);
  display: flex; align-items: flex-end; justify-content: center; }
.pc-sheet { width: 100%; max-width: 560px; max-height: 86dvh; overflow-y: auto; background: #0c0f15;
  border: 1px solid rgba(255,255,255,0.09); border-bottom: none; border-radius: 22px 22px 0 0;
  padding: 0.5rem 1rem calc(1rem + env(safe-area-inset-bottom, 0px)); box-sizing: border-box;
  display: flex; flex-direction: column; gap: 0.55rem; }
.pc-grip { width: 38px; height: 4px; border-radius: 2px; background: rgba(255,255,255,0.18); margin: 0.25rem auto 0.3rem; }
.pc-title { display: flex; align-items: center; gap: 0.5rem; font-size: 0.95rem; margin: 0; }
.pc-title :deep(svg) { width: 1.1rem; height: 1.1rem; color: var(--nc-primary, #00d4ff); }
.pc-x { margin-left: auto; background: none; border: none; color: rgba(230,237,243,0.6); font-size: 1.4rem;
  min-width: 44px; min-height: 44px; cursor: pointer; -webkit-tap-highlight-color: transparent; }
.pc-agent { margin: 0; font-size: 0.86rem; font-weight: 700; opacity: 0.9; }
.pc-slot { border: 1px solid rgba(255,255,255,0.08); border-radius: 14px; padding: 0.7rem 0.8rem;
  display: flex; flex-direction: column; gap: 0.4rem; background: rgba(255,255,255,0.03); }
.pc-slot-head { display: flex; align-items: baseline; gap: 0.5rem; }
.pc-slot-name { font-size: 0.8rem; font-weight: 700; }
.pc-slot-what { margin-left: auto; font-size: 0.72rem; color: var(--nc-primary, #00d4ff); font-weight: 650; }
.pc-bearer { margin: 0; font-size: 0.74rem; opacity: 0.75; }
.pc-move { margin: 0; font-size: 0.74rem; color: #ffd9a0; }
.pc-actions { display: flex; gap: 0.5rem; }
.pc-btn { flex: 1 1 auto; min-height: 46px; border-radius: 12px; border: 1px solid rgba(0,212,255,0.35);
  background: linear-gradient(160deg, rgba(0,212,255,0.16), rgba(0,212,255,0.05)); color: #e6edf3;
  font-size: 0.82rem; font-weight: 650; cursor: pointer; -webkit-tap-highlight-color: transparent;
  display: grid; place-items: center; text-decoration: none; }
.pc-btn:disabled { opacity: 0.45; cursor: default; }
.pc-ghost { border-color: rgba(255,255,255,0.14); background: rgba(255,255,255,0.05); }
.pc-link { text-align: center; }
.pc-note { margin: 0; font-size: 0.76rem; opacity: 0.7; }
.pc-warn { color: #ffb38a; opacity: 0.95; }
.pc-done { margin: 0; font-size: 0.76rem; color: #34d399; }
.pc-earned { margin: 0.2rem 0 0; display: flex; align-items: flex-start; gap: 0.45rem; font-size: 0.72rem; opacity: 0.65; }
.pc-earned :deep(svg) { width: 0.95rem; height: 0.95rem; flex: 0 0 auto; color: #34d399; margin-top: 0.05rem; }
.pc-manager { font-size: 0.74rem; color: var(--nc-primary, #00d4ff); text-decoration: none; text-align: center; min-height: 40px; display: grid; place-items: center; }
.pk-sheet-enter-active, .pk-sheet-leave-active { transition: opacity 0.2s ease; }
.pk-sheet-enter-from, .pk-sheet-leave-to { opacity: 0; }
@media (prefers-reduced-motion: reduce) { .pk-sheet-enter-active, .pk-sheet-leave-active { transition: none; } }
</style>
