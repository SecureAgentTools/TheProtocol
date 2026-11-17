<!--
  CommanderPlate — the one-of-one title for the Commander (V0665 art; his addendum, room seq 4081; his notes, seq 4134).

  It belongs to the existing commander flare tier, which only his account holds, so it is drawn like the other titles but is shown only to that
  tier (the caller decides; the component does not look at a tier). His notes: not too much. A CLEAN DARK STEEL PLATE with a crisp bevel, the same
  chamfered nameplate every title wears, wear only as a few precise marks at the edges (ONE deep scratch, ONE nick), no blotches; the black glow
  behind it kept but quiet; SMALL professional lettering (letter-spaced capitals in one clean face) and ONE thin red accent line.

  Static: nothing moves except one slow glint along the bevel's upper edge (a transform, a long pause); under prefers-reduced-motion it rests.
-->
<template>
  <span class="cp" :class="[`cp-sz-${size}`, { 'cp-still': still }]" role="text" :aria-label="text" :title="text">
    <span class="cp-glow" aria-hidden="true" />
    <svg class="cp-svg" viewBox="0 0 220 46" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient :id="`${uid}-face`" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#3a424c" /><stop offset="0.5" stop-color="#232a32" /><stop offset="0.52" stop-color="#1b2128" /><stop offset="1" stop-color="#2a323b" />
        </linearGradient>
        <linearGradient :id="`${uid}-rim`" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#f1f6fb" stop-opacity="0.95" /><stop offset="0.4" stop-color="#8b97a5" stop-opacity="0.8" /><stop offset="1" stop-color="#050608" />
        </linearGradient>
        <linearGradient :id="`${uid}-glint`" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#fff" stop-opacity="0" /><stop offset="0.5" stop-color="#fff" stop-opacity="0.9" /><stop offset="1" stop-color="#fff" stop-opacity="0" />
        </linearGradient>
        <clipPath :id="`${uid}-clip`"><path :d="plate" /></clipPath>
      </defs>
      <g :clip-path="`url(#${uid}-clip)`">
        <!-- the bevel: a light outer edge, then the face inside it -->
        <path :d="plate" :fill="`url(#${uid}-rim)`" />
        <path :d="face" :fill="`url(#${uid}-face)`" />
        <!-- fine brushed grain -->
        <g stroke="#fff" stroke-opacity="0.045" stroke-width="0.4"><path v-for="y in 14" :key="y" :d="`M0 ${y * 3.2} H220`" /></g>
        <!-- the bevel's inner line, crisp -->
        <path :d="face" fill="none" stroke="#c9d3de" stroke-opacity="0.35" stroke-width="0.5" />
        <path :d="face" fill="none" stroke="#000" stroke-opacity="0.55" stroke-width="0.6" transform="translate(0.3 0.5)" />
        <!-- ONE deep scratch, across the lower right -->
        <path d="M150 41 L196 11" stroke="#05070a" stroke-width="1.25" stroke-linecap="round" />
        <path d="M150.6 40.4 L196.6 10.4" stroke="#aebbc9" stroke-opacity="0.65" stroke-width="0.45" stroke-linecap="round" />
        <!-- the lettering: small, letter-spaced capitals, and ONE thin red line under it -->
        <text x="110" y="22.5" text-anchor="middle" class="cp-word" fill="#05070a" opacity="0.7" transform="translate(0 0.7)">{{ text }}</text>
        <text x="110" y="22.5" text-anchor="middle" class="cp-word" fill="#e8eef4">{{ text }}</text>
        <rect x="68" y="29.4" width="84" height="0.9" fill="#c0262d" />
        <!-- the glint along the upper bevel -->
        <rect class="cp-glintbar" x="-60" y="0" width="60" height="1.6" :fill="`url(#${uid}-glint)`" />
      </g>
      <!-- ONE nick, in the upper right chamfer: a small bite out of the silhouette and the bevel -->
      <path d="M196 0 L201.4 3.4 L198.6 6.4 Z" fill="#06080b" />
      <path d="M196 0 L201.4 3.4 L198.6 6.4" fill="none" stroke="#c9d3de" stroke-opacity="0.5" stroke-width="0.4" />
    </svg>
  </span>
</template>

<script lang="ts">
// module scope: ONE counter for every instance, so each SVG's gradient ids are unique on the page (a counter declared inside <script setup> restarts at 0 for every instance,
// and url(#id) then points at the first instance's defs: a ring in a closed section or an unmounted card would take the gradients of the others with it)
let counter = 0
</script>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from '@/composables/useI18n'

withDefaults(defineProps<{
  size?: 'sidebar' | 'card' | 'large'
  still?: boolean
}>(), { size: 'card', still: false })

const { t } = useI18n()
const uid = `cp${++counter}`
const text = computed(() => t('contributorTrack.titles.commander.name', 'COMMANDER'))

// the same slim chamfered nameplate every title wears (a 220 x 46 grid), and its face one unit inside
const plate = 'M8 0 H212 L220 8 V38 L212 46 H8 L0 38 V8 Z'
const face = 'M8.6 1.2 H211.4 L218.8 8.6 V37.4 L211.4 44.8 H8.6 L1.2 37.4 V8.6 Z'
</script>

<style scoped>
.cp { --w: 150px; position: relative; display: inline-block; width: var(--w); max-width: 100%; vertical-align: middle; isolation: isolate; user-select: none; }
.cp-sz-sidebar { --w: 128px; }
.cp-sz-card { --w: 150px; }
.cp-sz-large { --w: 360px; }
.cp-svg { display: block; width: 100%; height: auto; overflow: visible; }
.cp-word { font-family: 'IBM Plex Sans', 'IBM Plex Mono', system-ui, sans-serif; font-weight: 600; font-size: 11px; letter-spacing: 4.2px; }
/* the black glow behind: kept, quieter: it darkens the page a little round the plate and does not move */
.cp-glow {
  position: absolute; left: -10%; right: -10%; top: -45%; bottom: -45%; z-index: -1; pointer-events: none;
  background: radial-gradient(ellipse at 50% 50%, rgba(0, 0, 0, 0.7) 0%, rgba(0, 0, 0, 0.5) 38%, rgba(0, 0, 0, 0.18) 62%, rgba(0, 0, 0, 0) 78%);
}
.cp-svg { filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.7)); }
.cp-glintbar { transform-box: view-box; animation: cp-glint 9s ease-in-out infinite; }
@keyframes cp-glint { 0%, 70%, 100% { transform: translateX(0); } 90% { transform: translateX(300px); } }
@media (prefers-reduced-motion: reduce) { .cp-glintbar { animation: none; } }
.cp-still .cp-glintbar { animation: none; }
</style>
