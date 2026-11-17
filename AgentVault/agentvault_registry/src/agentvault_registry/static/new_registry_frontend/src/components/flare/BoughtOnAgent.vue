<!--
  BoughtOnAgent — the BOUGHT category for one agent (V0666, order gwo_558042610799088faf1a5e4c). The flares you bought and picked under "You" are worn by you AND by one of your agents per
  slot: here, for the agent chosen above, wear the corner flare or the ring on it, or take it off; a ring on this agent may carry an overlay. It replaces the three-column bearer
  section and its popover. An agent that wears an EARNED ring or badge is told to take it off first (the registry says the same); the registry moves a flare from the agent that wore it.
-->
<template>
  <section class="boa" data-testid="bought-on-agent">
    <header class="boa-h">
      <h2>{{ tp('flareWear.bought.h', 'Bought flares on {name}', { name: agent.name || agent.did }) }}</h2>
      <p>{{ t('flareWear.bought.sub', 'The flares you bought, worn by this agent. Pick which ones you wear yourself under "You".') }}</p>
    </header>
    <div class="boa-grid">
      <article v-for="s in slots" :key="s.slot" class="boa-card" :class="{ 'boa-on': s.here }" :data-testid="`bought-${s.slot}`">
        <h3>{{ s.title }}</h3>
        <p class="boa-what" :data-testid="`bought-${s.slot}-what`">{{ s.have ? s.name : s.none }}</p>
        <p v-if="s.blocked" class="boa-block" :data-testid="`bought-${s.slot}-blocked`">{{ s.blocked }}</p>
        <p v-else-if="s.holder && !s.here" class="boa-held" :data-testid="`bought-${s.slot}-held`">{{ tp('flareWear.earned.heldBy', 'Worn by {name}. Wearing it here moves it.', { name: s.holder }) }}</p>
        <button v-if="s.have && !s.blocked" type="button" class="boa-btn" :class="{ 'boa-btn-off': s.here }" :disabled="busy" :data-testid="`bought-${s.slot}-${s.here ? 'off' : 'on'}`" @click="s.here ? $emit('unequip', s.slot) : $emit('equip', s.slot)">
          {{ s.here ? t('flareWear.bought.takeOff', 'Take it off') : t('flareWear.bought.wearHere', 'Wear it here') }}
        </button>
        <div v-if="s.slot === 'encirclement' && s.here" class="boa-ov" role="group" :aria-label="t('flareWear.bought.overlay', 'Overlay')" data-testid="bought-overlays">
          <span class="boa-ov-k">{{ t('flareWear.bought.overlay', 'Overlay') }}</span>
          <button type="button" class="boa-chip" :class="{ 'boa-chip-on': !agent.flare_encirclement_overlay }" :aria-pressed="!agent.flare_encirclement_overlay" data-testid="overlay-none" @click="$emit('overlay', null)">{{ t('flareWear.bought.noOverlay', 'None') }}</button>
          <button v-for="o in overlays" :key="o.id" type="button" class="boa-chip" :class="{ 'boa-chip-on': agent.flare_encirclement_overlay === o.id }" :aria-pressed="agent.flare_encirclement_overlay === o.id" :data-testid="`overlay-${o.id}`" @click="$emit('overlay', o.id)">{{ o.label }}</button>
        </div>
      </article>
    </div>
    <p v-if="error" class="boa-err" role="alert" data-testid="bought-error">{{ error }}</p>
    <p v-if="ok" class="boa-ok" role="status" data-testid="bought-ok">{{ ok }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'
import type { AgentFlareRow } from '@/services/flareBearers'

type Slot = 'corner' | 'encirclement'
const props = defineProps<{
  agent: AgentFlareRow & { flare_encirclement_overlay?: string | null }
  /** the developer's selected bought flares (their display names), or '' when none is picked */
  cornerName: string
  ringName: string
  /** the name of ANOTHER agent that bears the slot now, or '' */
  cornerHolder: string
  ringHolder: string
  overlays: Array<{ id: string; label: string }>
  busy: boolean
  error: string
  ok: string
  /** what the agent wears of the EARNED kind in each slot (an earned item on the agent blocks the bought one) */
  earnedRing: boolean
  earnedBadge: boolean
}>()
defineEmits<{ (e: 'equip', slot: Slot): void; (e: 'unequip', slot: Slot): void; (e: 'overlay', id: string | null): void }>()
const { t, tp } = useI18n()

const slots = computed(() => [
  { slot: 'corner' as Slot, title: t('flareWear.bought.corner', 'Corner flare'), have: !!props.cornerName, name: props.cornerName, none: t('flareWear.bought.noCorner', 'You have not picked a corner flare. Pick one under "You".'),
    here: !!props.agent.bears_corner_flare, holder: props.cornerHolder,
    blocked: props.earnedBadge ? t('flareWear.bought.badgeBlocked', 'This agent wears an unlocked badge. Take it off in Unlocked first.') : '' },
  { slot: 'encirclement' as Slot, title: t('flareWear.bought.ring', 'Ring'), have: !!props.ringName, name: props.ringName, none: t('flareWear.bought.noRing', 'You have not picked a ring. Pick one under "You".'),
    here: !!props.agent.bears_encirclement_flare, holder: props.ringHolder,
    blocked: props.earnedRing ? t('flareWear.bought.ringBlocked', 'This agent wears an unlocked ring. Take it off in Unlocked first.') : '' },
])
</script>

<style scoped>
.boa { --cyan: var(--nc-primary, #00d2d2); --cyan-rgb: var(--nc-primary-rgb, 0, 210, 210); display: grid; gap: .9rem; margin: 0 0 1.4rem; padding: 1.1rem 1.25rem; border: 1px solid rgba(var(--cyan-rgb), .2); border-radius: 12px; background: rgba(var(--cyan-rgb), .03); font-family: 'IBM Plex Sans', system-ui, sans-serif; }
.boa-h h2 { margin: 0; font-size: 1.05rem; font-weight: 400; }
.boa-h p { margin: .25rem 0 0; font-size: .82rem; line-height: 1.55; color: #8b97a6; }
.boa-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: .8rem; align-items: start; }
.boa-card { display: grid; gap: .5rem; padding: .9rem 1rem; border: 1px solid rgba(var(--cyan-rgb), .14); border-radius: 10px; background: rgba(255, 255, 255, .02); }
.boa-on { border-color: var(--cyan); background: rgba(var(--cyan-rgb), .07); }
.boa-card h3 { margin: 0; font: 500 .72rem/1.3 'IBM Plex Mono', monospace; letter-spacing: .1em; text-transform: uppercase; color: #c4ccd6; }
.boa-what { margin: 0; font-size: .92rem; }
.boa-held, .boa-block { margin: 0; font-size: .76rem; line-height: 1.5; color: #8b97a6; }
.boa-block { padding: .4rem .6rem; border-left: 2px solid rgba(255, 196, 0, .6); color: #d9c27a; background: rgba(255, 196, 0, .05); }
.boa-btn { justify-self: start; min-height: 36px; padding: 0 14px; border-radius: 8px; border: 1px solid rgba(var(--cyan-rgb), .4); background: rgba(var(--cyan-rgb), .08); color: var(--cyan); font: inherit; font-size: .8rem; cursor: pointer; }
.boa-btn:hover:not(:disabled), .boa-btn:focus-visible { background: rgba(var(--cyan-rgb), .16); }
.boa-btn-off { border-color: rgba(255, 255, 255, .25); background: transparent; color: #c4ccd6; }
.boa-btn:disabled { opacity: .5; cursor: default; }
.boa-ov { display: flex; flex-wrap: wrap; gap: .35rem; align-items: center; }
.boa-ov-k { font: 500 .68rem 'IBM Plex Mono', monospace; letter-spacing: .08em; text-transform: uppercase; color: #8b97a6; margin-right: .3rem; }
.boa-chip { min-height: 32px; padding: 0 .7rem; border-radius: 999px; border: 1px solid rgba(var(--cyan-rgb), .25); background: transparent; color: #c4ccd6; font: inherit; font-size: .76rem; cursor: pointer; }
.boa-chip-on { border-color: var(--cyan); color: var(--cyan); background: rgba(var(--cyan-rgb), .1); }
.boa-err { margin: 0; color: #ff8a8a; font-size: .82rem; }
.boa-ok { margin: 0; color: #5fe3a1; font-size: .82rem; }
</style>
