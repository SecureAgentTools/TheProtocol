<!--
  EarnedBadge — the contributor track's NEW corner badges (V0665 art; his idea, room seq 4063/4070).

  Built on FlareBadge.vue's idea (a round ring with a small glyph in it; Architect is a compass in emerald, Founder a diamond in
  gold) and readable at 16 to 22 px: every glyph is drawn on a 24 grid with strokes of at least 1.4 units, so at 16 px a stroke is a
  whole pixel. The old badges are NOT touched; these keys are new.

    initiate               a hairline compass                          (architect)
    architect-prime        a blueprint grid, a compass, a gold seal    (architect, refined)
    keystone               an arch with its keystone lit               (architect)
    founders-seal          a wax seal pressed with the mark            (founder, refined)
    crown-of-the-commons   a crown of three points, the season's top contributor
    gatekeeper             a portcullis
    ledger-seal            a seal with the delta in it
    quill                  a feather and its ink drop
    anvil                  an anvil and one spark
    lantern-key            a key whose bow is a small lantern

  Cheap motion only: opacity and transform on a glint or a spark, a few seconds apart; still under prefers-reduced-motion (the
  resting state IS the still frame). Sizes are pixels.
-->
<template>
  <span class="eb" :class="[`eb-${badgeKey}`, size < 20 ? 'eb-d-s' : 'eb-d-m', { 'eb-still': still }]" :style="{ '--eb-s': `${size}px` }" role="img" :aria-label="label" :title="label">
    <span class="eb-ring">
      <svg class="eb-glyph" viewBox="0 0 24 24" fill="none" aria-hidden="true" focusable="false">
        <defs>
          <linearGradient :id="`${uid}-gold`" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#fde68a" /><stop offset="0.5" stop-color="#f59e0b" /><stop offset="1" stop-color="#b45309" />
          </linearGradient>
          <linearGradient :id="`${uid}-em`" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stop-color="#6ee7b7" /><stop offset="1" stop-color="#059669" />
          </linearGradient>
          <radialGradient :id="`${uid}-wax`" cx="40%" cy="35%" r="70%">
            <stop offset="0" stop-color="#ef5350" /><stop offset="0.6" stop-color="#b3201c" /><stop offset="1" stop-color="#6e0f12" />
          </radialGradient>
          <radialGradient :id="`${uid}-lamp`" cx="50%" cy="50%" r="50%">
            <stop offset="0" stop-color="#fff2b8" stop-opacity="1" /><stop offset="1" stop-color="#ffb347" stop-opacity="0" />
          </radialGradient>
        </defs>

        <!-- INITIATE: a hairline compass -->
        <g v-if="badgeKey === 'initiate'">
          <circle cx="12" cy="12" r="8.2" stroke="#6ee7b7" stroke-width="1.4" />
          <path d="M12 3.1 V5.4 M12 18.6 V20.9 M3.1 12 H5.4 M18.6 12 H20.9" stroke="#6ee7b7" stroke-width="1.4" stroke-linecap="round" />
          <path class="eb-needle" d="M12 6.4 L14.1 12 L12 17.6 L9.9 12 Z" fill="none" stroke="#a7f3d0" stroke-width="1.2" stroke-linejoin="round" />
          <path d="M12 6.4 L14.1 12 L9.9 12 Z" fill="#fde68a" />
        </g>

        <!-- ARCHITECT PRIME: a blueprint grid, a compass, a gold seal -->
        <g v-else-if="badgeKey === 'architect-prime'">
          <g stroke="#34d399" stroke-width="0.9" opacity="0.5"><path d="M4.5 9 H19.5 M4.5 15 H19.5 M9 4.5 V19.5 M15 4.5 V19.5" /></g>
          <path d="M12 4.2 L6 19 M12 4.2 L18 19" stroke="#6ee7b7" stroke-width="1.5" stroke-linecap="round" />
          <path d="M8.2 14.6 H15.8" stroke="#6ee7b7" stroke-width="1.2" stroke-linecap="round" />
          <circle cx="12" cy="4.4" r="1.4" fill="#d1fae5" />
          <circle class="eb-glint" cx="17.6" cy="17.6" r="4.2" :fill="`url(#${uid}-gold)`" stroke="#fef3c7" stroke-width="0.8" />
          <path d="M17.6 15.2 L18.3 16.9 L20.1 17 L18.7 18.1 L19.2 19.8 L17.6 18.8 L16 19.8 L16.5 18.1 L15.1 17 L16.9 16.9 Z" fill="#7a4a06" />
        </g>

        <!-- KEYSTONE: an arch whose keystone is lit -->
        <g v-else-if="badgeKey === 'keystone'">
          <path d="M4.6 20 V13.4 A7.4 7.4 0 0 1 19.4 13.4 V20" stroke="#6ee7b7" stroke-width="1.6" stroke-linecap="round" />
          <path d="M4.6 17 H8 M16 17 H19.4 M6 12.6 L9 14.2 M18 12.6 L15 14.2" stroke="#34d399" stroke-width="1.2" stroke-linecap="round" opacity="0.8" />
          <path class="eb-glint" d="M10.2 4.9 H13.8 L14.6 9.7 H9.4 Z" :fill="`url(#${uid}-gold)`" stroke="#fef3c7" stroke-width="0.9" stroke-linejoin="round" />
          <circle class="eb-glint" cx="12" cy="7.2" r="3.4" :fill="`url(#${uid}-lamp)`" />
        </g>

        <!-- FOUNDER'S SEAL: scalloped wax pressed with the mark -->
        <g v-else-if="badgeKey === 'founders-seal'">
          <path d="M12 2.6 L13.9 4.4 L16.5 3.9 L17.4 6.4 L20 7.1 L19.6 9.7 L21.4 11.6 L19.6 13.6 L20 16.2 L17.4 16.9 L16.5 19.4 L13.9 18.9 L12 20.7 L10.1 18.9 L7.5 19.4 L6.6 16.9 L4 16.2 L4.4 13.6 L2.6 11.6 L4.4 9.7 L4 7.1 L6.6 6.4 L7.5 3.9 L10.1 4.4 Z" :fill="`url(#${uid}-wax)`" stroke="#fbbf24" stroke-width="0.9" stroke-linejoin="round" />
          <circle cx="12" cy="11.6" r="5.6" stroke="#fbbf24" stroke-width="0.9" opacity="0.85" />
          <path d="M12 7.6 L15 11.6 L12 15.6 L9 11.6 Z" fill="#fde68a" stroke="#7a4a06" stroke-width="0.7" stroke-linejoin="round" />
          <path class="eb-glint" d="M8.4 5.6 A6.4 6.4 0 0 1 12 4.4" stroke="#ffffff" stroke-width="1" stroke-linecap="round" opacity="0.8" />
        </g>

        <!-- CROWN OF THE COMMONS: three points, three jewels -->
        <g v-else-if="badgeKey === 'crown-of-the-commons'">
          <path d="M3.8 17.6 L4.8 8.4 L9 12.4 L12 6 L15 12.4 L19.2 8.4 L20.2 17.6 Z" :fill="`url(#${uid}-gold)`" stroke="#fef3c7" stroke-width="1" stroke-linejoin="round" />
          <path d="M4.6 17.6 H19.4 V20 H4.6 Z" fill="#b45309" stroke="#fde68a" stroke-width="0.9" stroke-linejoin="round" />
          <circle cx="4.8" cy="7.6" r="1.3" fill="#34d399" /><circle cx="12" cy="5.2" r="1.4" class="eb-glint" fill="#fb7185" /><circle cx="19.2" cy="7.6" r="1.3" fill="#38bdf8" />
          <circle cx="12" cy="14.4" r="1.3" fill="#fff7e0" />
        </g>

        <!-- GATEKEEPER: a portcullis -->
        <g v-else-if="badgeKey === 'gatekeeper'">
          <path d="M4.4 20.4 V10 A7.6 7.6 0 0 1 19.6 10 V20.4" stroke="#94a3b8" stroke-width="1.6" stroke-linecap="round" />
          <g class="eb-gate" stroke="#cbd5e1" stroke-width="1.4" stroke-linecap="round">
            <path d="M8.4 7 V19 M12 5.4 V19.6 M15.6 7 V19" />
            <path d="M6.4 11 H17.6 M6.4 15.4 H17.6" stroke-width="1.1" opacity="0.85" />
            <path d="M8.4 19 L8.4 21 M12 19.6 L12 21.6 M15.6 19 L15.6 21" stroke="#f59e0b" stroke-width="1.3" />
          </g>
        </g>

        <!-- LEDGER SEAL: a seal with the delta in it -->
        <g v-else-if="badgeKey === 'ledger-seal'">
          <circle cx="12" cy="12" r="8.6" stroke="#38bdf8" stroke-width="1.5" />
          <circle cx="12" cy="12" r="6.2" stroke="#38bdf8" stroke-width="0.8" stroke-dasharray="1.2 1.6" opacity="0.8" />
          <path d="M12 6.6 L17 16.6 H7 Z" stroke="#e0f2fe" stroke-width="1.5" stroke-linejoin="round" />
          <ellipse class="eb-glint" cx="12" cy="13.6" rx="1.35" ry="2" stroke="#fde68a" stroke-width="1.2" />
        </g>

        <!-- QUILL: a feather and the ink drop -->
        <g v-else-if="badgeKey === 'quill'">
          <path d="M19.6 3.4 C13.4 3.4 8.4 7.4 7.4 14.4 L6.2 19.6 L11 17.6 C16.6 16.4 20.4 11 19.6 3.4 Z" fill="#1e1b4b" stroke="#c4b5fd" stroke-width="1.4" stroke-linejoin="round" />
          <path d="M6.2 19.6 L15.8 8.2 M10.8 12.2 L14.8 12.4 M9 15.2 L12.6 15.4" stroke="#ddd6fe" stroke-width="1.1" stroke-linecap="round" />
          <path class="eb-drop" d="M4.4 20.4 C3.4 21.6 4 22.8 5 22.8 C6 22.8 6.4 21.6 5.6 20.6 Z" fill="#a78bfa" />
        </g>

        <!-- ANVIL: an anvil and one spark -->
        <g v-else-if="badgeKey === 'anvil'">
          <path d="M3.6 8.4 H17.4 C19.4 8.4 20.4 9.6 20.4 10.8 C18.8 11 17.4 12 16.4 13 H14 V16 H17 V19.4 H7 V16 H10 V13 C7 13 5.4 11.4 3.6 8.4 Z" fill="#334155" stroke="#cbd5e1" stroke-width="1.4" stroke-linejoin="round" />
          <path d="M5 9.6 H17.6" stroke="#f8fafc" stroke-width="0.9" opacity="0.7" />
          <g class="eb-spark" stroke-linecap="round"><path d="M11 5.8 V3.4 M8.6 6.4 L7.2 4.6 M13.4 6.4 L14.8 4.6" stroke="#fbbf24" stroke-width="1.3" /></g>
        </g>

        <!-- LANTERN KEY: a key whose bow is a lantern -->
        <g v-else-if="badgeKey === 'lantern-key'">
          <circle class="eb-glint" cx="8" cy="8.2" r="5.4" :fill="`url(#${uid}-lamp)`" />
          <path d="M5.4 5.6 H10.6 V10.8 H5.4 Z" fill="#451a03" stroke="#fbbf24" stroke-width="1.3" stroke-linejoin="round" />
          <path d="M8 6.6 C7 8 7.2 9 8 9.8 C8.8 9 9 8 8 6.6 Z" fill="#fff2b8" />
          <path d="M10.4 10.4 L19.6 19.6 M16.6 16.6 L19 14.2 M14.4 14.4 L16.2 12.6" stroke="#fbbf24" stroke-width="1.6" stroke-linecap="round" />
        </g>
      </svg>
    </span>
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

const props = withDefaults(defineProps<{
  /** one of NEW_BADGES' keys (services/contributorTrack.ts) */
  badgeKey: string
  /** pixels (16 to 22 in a list, 48 on a card) */
  size?: number
  still?: boolean
}>(), { size: 22, still: false })

const { t } = useI18n()
const uid = `eb${++counter}`
const label = computed(() => t(`contributorTrack.badges.${props.badgeKey}.name`, props.badgeKey))
</script>

<style scoped>
.eb {
  display: inline-block;
  flex-shrink: 0;
  vertical-align: middle;
  width: var(--eb-s, 22px);
  height: var(--eb-s, 22px);
  user-select: none;
}
/* the round ring of FlareBadge, in one shared dark enamel; each badge's colour is in its glyph */
.eb-ring {
  display: flex;
  width: 100%;
  height: 100%;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: radial-gradient(circle at 35% 28%, rgba(255, 255, 255, 0.1), rgba(4, 8, 14, 0.94) 62%);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.16), inset 0 0 6px rgba(0, 0, 0, 0.6);
}
.eb-glyph { width: 84%; height: 84%; overflow: visible; }
.eb-d-s .eb-ring { box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.2); }

.eb-glyph * { transform-box: fill-box; transform-origin: center; }
.eb-glint { animation: eb-glint 4.6s ease-in-out infinite; }
.eb-needle { animation: eb-needle 6s ease-in-out infinite; }
.eb-gate { animation: eb-gate 5.4s ease-in-out infinite; }
.eb-drop { animation: eb-drop 4.2s ease-in infinite; }
.eb-spark { animation: eb-spark 3.2s ease-out infinite; }
@keyframes eb-glint { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
@keyframes eb-needle { 0%, 100% { transform: rotate(0deg); } 30% { transform: rotate(14deg); } 60% { transform: rotate(-9deg); } }
@keyframes eb-gate { 0%, 55%, 100% { transform: translateY(0); } 70%, 85% { transform: translateY(-1.6px); } }
@keyframes eb-drop { 0%, 60% { opacity: 1; transform: translateY(0); } 85% { opacity: 0; transform: translateY(1.4px); } 100% { opacity: 1; transform: translateY(0); } }
@keyframes eb-spark { 0%, 70%, 100% { opacity: 1; } 78% { opacity: 0.1; } }

@media (prefers-reduced-motion: reduce) {
  .eb-glyph * { animation: none !important; }
}
.eb-still .eb-glyph * { animation: none !important; }
</style>
