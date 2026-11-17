<!--
  EarnedRing — the contributor track's NEW encirclements (V0665 art; his idea, room seq 4063/4070).

  One component for fourteen rings, in the system FlareEncirclement.vue uses: a wrapper the size of the avatar, a round frame
  (face: image, else initials) and the ring's art around it, which overflows the wrapper like the halo layers do. The old
  encirclements are NOT touched; these keys are new.

    cover "logo"  the avatar stays visible; the art is an annulus around it (r 33 to 50 of a 100 grid, the avatar is r 32)
    cover "full"  the art covers the avatar (the void / blackhole family): a disc of r 50

  Cheap motion only: CSS transforms and opacity on SVG groups; no per-frame script (the Eye of the Senate follows the pointer on
  pointer EVENTS, one rAF-throttled write of two custom properties, only while the pointer is over it); no backdrop-filter; no
  canvas. Every colour is a real value (a canvas cannot read var(), and gradients here are SVG). A still frame is what you get
  with prefers-reduced-motion, or `still`: every effect's resting state IS the still frame, the animation only moves away from it.
  Detail follows the size: under 28 px the fine layers are hidden (sidebar and list rows), from 28 px the full art.

  Sizes are pixels (the gallery shows 22, 32 and 96).
-->
<template>
  <span
    ref="root"
    class="er"
    :class="[`er-${ringKey}`, `er-cover-${cover}`, detail === 's' ? 'er-d-s' : detail === 'm' ? 'er-d-m' : 'er-d-l', { 'er-still': still }]"
    :style="{ '--er-s': `${size}px` }"
    role="img"
    :aria-label="label"
    :title="label"
    @pointermove="onMove"
    @pointerleave="onLeave"
  >
    <!-- the face -->
    <span v-if="cover === 'logo'" class="er-frame">
      <img v-if="avatarUrl && !imgFailed" :src="avatarUrl" class="er-img" alt="" @error="imgFailed = true" />
      <span v-else class="er-initials">{{ initials || '' }}</span>
    </span>

    <svg class="er-art" viewBox="0 0 100 100" aria-hidden="true" focusable="false">
      <defs>
        <!-- LANTERN -->
        <radialGradient :id="`${uid}-lantern`" cx="50" cy="50" r="50" gradientUnits="userSpaceOnUse">
          <stop offset="0.60" stop-color="#ffc760" stop-opacity="0" />
          <stop offset="0.67" stop-color="#ffc760" stop-opacity="0.62" />
          <stop offset="0.82" stop-color="#ff9d3a" stop-opacity="0.26" />
          <stop offset="1" stop-color="#ff7a1a" stop-opacity="0" />
        </radialGradient>
        <!-- EMBER -->
        <linearGradient :id="`${uid}-ember`" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stop-color="#7a1d0a" />
          <stop offset="0.5" stop-color="#ff5a1f" />
          <stop offset="1" stop-color="#ffc24d" />
        </linearGradient>
        <!-- EYE OF THE SENATE / WATCHER -->
        <radialGradient :id="`${uid}-iris`" cx="50%" cy="50%" r="50%">
          <stop offset="0" stop-color="#fff6c8" />
          <stop offset="0.45" stop-color="#ffb830" />
          <stop offset="1" stop-color="#b3201c" />
        </radialGradient>
        <radialGradient :id="`${uid}-flame`" cx="50" cy="50" r="50" gradientUnits="userSpaceOnUse">
          <stop offset="0.62" stop-color="#ff5a1f" stop-opacity="0" />
          <stop offset="0.7" stop-color="#ff5a1f" stop-opacity="0.34" />
          <stop offset="1" stop-color="#7a0f0f" stop-opacity="0" />
        </radialGradient>
        <!-- OUROBOROS -->
        <linearGradient :id="`${uid}-scale`" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#34d399" />
          <stop offset="0.55" stop-color="#10806a" />
          <stop offset="1" stop-color="#e6b84a" />
        </linearGradient>
        <!-- SOLAR FLARE / SUPERNOVA -->
        <linearGradient :id="`${uid}-tongue`" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stop-color="#e11d12" />
          <stop offset="0.55" stop-color="#ff6a1a" />
          <stop offset="1" stop-color="#ffd166" />
        </linearGradient>
        <radialGradient :id="`${uid}-nova`" cx="50" cy="50" r="50" gradientUnits="userSpaceOnUse">
          <stop offset="0.6" stop-color="#fff7e0" stop-opacity="0" />
          <stop offset="0.68" stop-color="#ffe08a" stop-opacity="0.6" />
          <stop offset="0.86" stop-color="#ff7a2b" stop-opacity="0.22" />
          <stop offset="1" stop-color="#e11d48" stop-opacity="0" />
        </radialGradient>
        <!-- EVENT HORIZON -->
        <linearGradient :id="`${uid}-disk`" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#ff7a1a" stop-opacity="0" />
          <stop offset="0.22" stop-color="#ff9d3a" />
          <stop offset="0.5" stop-color="#fff6dc" />
          <stop offset="0.78" stop-color="#ff7a1a" />
          <stop offset="1" stop-color="#b3260c" stop-opacity="0" />
        </linearGradient>
        <radialGradient :id="`${uid}-hole`" cx="50" cy="50" r="50" gradientUnits="userSpaceOnUse">
          <stop offset="0" stop-color="#000000" />
          <stop offset="0.7" stop-color="#030208" />
          <stop offset="1" stop-color="#0b0614" />
        </radialGradient>
        <filter :id="`${uid}-soft`" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="1.4" /></filter>
        <!-- ABYSS -->
        <radialGradient :id="`${uid}-ink`" cx="50%" cy="50%" r="50%">
          <stop offset="0" stop-color="#3b2a8f" stop-opacity="0.7" />
          <stop offset="1" stop-color="#1a1250" stop-opacity="0" />
        </radialGradient>
        <radialGradient :id="`${uid}-ink2`" cx="50%" cy="50%" r="50%">
          <stop offset="0" stop-color="#0c6a8f" stop-opacity="0.5" />
          <stop offset="1" stop-color="#0a3550" stop-opacity="0" />
        </radialGradient>
        <!-- ECLIPSE -->
        <linearGradient :id="`${uid}-ray`" x1="0" y1="1" x2="0" y2="0">
          <stop offset="0" stop-color="#ffe9a8" stop-opacity="0.95" />
          <stop offset="1" stop-color="#ffb347" stop-opacity="0" />
        </linearGradient>
        <!-- LATTICE / QUANTUM -->
        <linearGradient :id="`${uid}-lat`" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#a78bfa" />
          <stop offset="1" stop-color="#22d3ee" />
        </linearGradient>
      </defs>

      <!-- ═════ LANTERN — a warm halo, a hairline and four small flames ═════ -->
      <g v-if="ringKey === 'lantern'">
        <circle class="er-breathe" cx="50" cy="50" r="48" :fill="`url(#${uid}-lantern)`" />
        <circle cx="50" cy="50" r="36" fill="none" stroke="#f3c677" stroke-width="0.9" opacity="0.95" />
        <circle class="er-fine" cx="50" cy="50" r="40.5" fill="none" stroke="#f3c677" stroke-width="0.55" stroke-dasharray="0.7 3.2" opacity="0.8" />
        <g class="er-flames">
          <g v-for="(a, i) in [0, 90, 180, 270]" :key="a" :transform="`rotate(${a} 50 50)`">
            <path class="er-flame" :style="{ animationDelay: `${i * 0.7}s` }" d="M50 3.5 C47.6 7.6 47.8 10.4 50 12.2 C52.2 10.4 52.4 7.6 50 3.5 Z" fill="#ffd27a" />
          </g>
        </g>
      </g>

      <!-- ═════ EMBER — a charred ring and sparks rising off it (phoenix) ═════ -->
      <g v-else-if="ringKey === 'ember'">
        <circle cx="50" cy="50" r="36.5" fill="none" :stroke="`url(#${uid}-ember)`" stroke-width="2.6" />
        <circle cx="50" cy="50" r="39.4" fill="none" stroke="#ff8a3a" stroke-width="0.5" opacity="0.55" />
        <circle class="er-breathe" cx="50" cy="50" r="44" fill="none" stroke="#ff5a1f" stroke-width="5" opacity="0.14" />
        <g class="er-fine">
          <circle v-for="(s, i) in sparks" :key="i" class="er-spark" :cx="s.x" :cy="s.y" :r="s.r" :fill="i % 2 ? '#ffc24d' : '#ff7a2b'"
                  :style="{ '--dx': `${s.dx}px`, '--dy': `${s.dy}px`, animationDelay: `${s.d}s`, animationDuration: `${s.t}s` }" />
        </g>
      </g>

      <!-- ═════ EYE OF THE SENATE — an almond eye above the ring; the iris follows the pointer (sauron) ═════ -->
      <g v-else-if="ringKey === 'eye-of-the-senate'">
        <circle cx="50" cy="50" r="48" :fill="`url(#${uid}-flame)`" />
        <circle cx="50" cy="50" r="36.5" fill="none" stroke="#c43a2a" stroke-width="1.1" />
        <circle class="er-fine" cx="50" cy="50" r="39.5" fill="none" stroke="#e6b84a" stroke-width="0.5" stroke-dasharray="1 2.4" opacity="0.8" />
        <path d="M30 13 Q50 -3 70 13 Q50 29 30 13 Z" fill="#12060a" stroke="#e6b84a" stroke-width="1.3" />
        <g class="er-iris">
          <circle cx="50" cy="13" r="6.1" :fill="`url(#${uid}-iris)`" />
          <ellipse cx="50" cy="13" rx="1.35" ry="5.1" fill="#120305" />
          <circle cx="48.2" cy="10.6" r="1" fill="#fffbe8" opacity="0.85" />
        </g>
        <path class="er-fine" d="M30 13 Q50 -3 70 13" fill="none" stroke="#ffd27a" stroke-width="0.6" opacity="0.7" />
      </g>

      <!-- ═════ OUROBOROS — a serpent eating its tail; its scales crawl ═════ -->
      <g v-else-if="ringKey === 'ouroboros'">
        <circle cx="50" cy="50" r="40" fill="none" :stroke="`url(#${uid}-scale)`" stroke-width="5.2" />
        <circle class="er-crawl" cx="50" cy="50" r="40" fill="none" stroke="#06241c" stroke-width="5.2" stroke-dasharray="1.15 2.05" opacity="0.62" />
        <circle cx="50" cy="50" r="42.7" fill="none" stroke="#e6b84a" stroke-width="0.45" opacity="0.7" />
        <circle cx="50" cy="50" r="37.3" fill="none" stroke="#e6b84a" stroke-width="0.35" opacity="0.45" />
        <!-- the head, at one o'clock, biting the thinning tail -->
        <g transform="rotate(34 50 50)">
          <path d="M44 6.6 C47 2.6 54.5 2.4 58.6 5.6 C60.4 7 60.6 9.4 58.8 10.6 C55 12.2 48 12.4 44 10.6 Z" fill="#17a083" stroke="#e6b84a" stroke-width="0.6" />
          <circle cx="55.2" cy="6.3" r="1" fill="#ffe08a" />
          <path d="M44 8.6 L40.4 8.2 M44 9.8 L40.2 10.8" stroke="#e63946" stroke-width="0.6" stroke-linecap="round" />
        </g>
      </g>

      <!-- ═════ MERKLE RING — a hash chain, a pulse travelling round it ═════ -->
      <g v-else-if="ringKey === 'merkle-ring'">
        <circle cx="50" cy="50" r="41" fill="none" stroke="#22d3ee" stroke-width="0.5" opacity="0.55" />
        <circle class="er-fine" cx="50" cy="50" r="36" fill="none" stroke="#22d3ee" stroke-width="0.4" opacity="0.35" />
        <g v-for="i in 12" :key="i" :transform="`rotate(${(i - 1) * 30} 50 50)`">
          <rect class="er-link" x="46.4" y="5.6" width="7.2" height="5.4" rx="2.1" fill="#04161d" stroke="#5eead4" stroke-width="0.95"
                :style="{ animationDelay: `${(i - 1) * 0.25}s` }" />
          <path class="er-fine" d="M50 11 L50 14.5" stroke="#22d3ee" stroke-width="0.5" opacity="0.55" />
        </g>
      </g>

      <!-- ═════ LATTICE — the post-quantum lattice: a zigzag of nodes and edges, turning slowly ═════ -->
      <g v-else-if="ringKey === 'lattice'">
        <g class="er-turn">
          <polyline :points="latticePoints" fill="none" :stroke="`url(#${uid}-lat)`" stroke-width="0.7" />
          <g class="er-fine">
            <line v-for="(e, i) in latticeEdges" :key="i" :x1="e[0]" :y1="e[1]" :x2="e[2]" :y2="e[3]" stroke="#a78bfa" stroke-width="0.35" opacity="0.6" />
          </g>
          <circle v-for="(n, i) in latticeNodes" :key="i" class="er-node" :cx="n.x" :cy="n.y" :r="n.o ? 1.6 : 1.15" :fill="n.o ? '#22d3ee' : '#c4b5fd'"
                  :style="{ animationDelay: `${(i % 6) * 0.45}s` }" />
        </g>
      </g>

      <!-- ═════ QUANTUM HALO — three orbits and qubits that flicker ═════ -->
      <g v-else-if="ringKey === 'quantum-halo'">
        <g class="er-turn er-turn-slow">
          <ellipse v-for="a in [0, 60, 120]" :key="a" cx="50" cy="50" rx="44" ry="15.5" fill="none" stroke="#2dd4bf" stroke-width="0.5" opacity="0.5" :transform="`rotate(${a} 50 50)`" />
        </g>
        <g>
          <circle v-for="(q, i) in qubits" :key="i" class="er-qubit" :cx="q.x" :cy="q.y" :r="q.r" :fill="q.c"
                  :style="{ animationDelay: `${q.d}s` }" />
        </g>
        <circle cx="50" cy="50" r="35.5" fill="none" stroke="#2dd4bf" stroke-width="0.5" opacity="0.5" />
      </g>

      <!-- ═════ WATCHER — a smaller eye that opens when the pointer leaves (sauron) ═════ -->
      <g v-else-if="ringKey === 'watcher'">
        <circle cx="50" cy="50" r="48" :fill="`url(#${uid}-flame)`" />
        <circle cx="50" cy="50" r="36.5" fill="none" stroke="#8f2a24" stroke-width="1" />
        <circle class="er-fine" cx="50" cy="50" r="40" fill="none" stroke="#8f2a24" stroke-width="0.45" stroke-dasharray="0.8 3" opacity="0.7" />
        <g class="er-watch">
          <path d="M36 89 Q50 79 64 89 Q50 99 36 89 Z" fill="#12060a" stroke="#c9892f" stroke-width="1" />
          <g class="er-lid">
            <circle class="er-glance" cx="50" cy="89" r="4.4" :fill="`url(#${uid}-iris)`" />
            <ellipse class="er-glance" cx="50" cy="89" rx="1" ry="3.6" fill="#120305" />
          </g>
          <path class="er-shut" d="M36 89 Q50 99 64 89 Q50 84.5 36 89 Z" fill="#12060a" stroke="#c9892f" stroke-width="0.9" />
        </g>
      </g>

      <!-- ═════ SOLAR FLARE — sixteen flame tongues round the ring, two sets breathing out of step (inferno) ═════ -->
      <g v-else-if="ringKey === 'solar-flare'">
        <circle cx="50" cy="50" r="36" fill="none" stroke="#ff6a1a" stroke-width="1.2" />
        <g class="er-turn er-turn-slow">
          <g class="er-set-a">
            <path v-for="i in 8" :key="i" :transform="`rotate(${(i - 1) * 45} 50 50)`"
                  d="M50 2.8 C45.4 9.6 46.6 14.6 50 17 C53.4 14.6 54.6 9.6 50 2.8 Z" :fill="`url(#${uid}-tongue)`" />
          </g>
          <g class="er-set-b">
            <path v-for="i in 8" :key="i" :transform="`rotate(${(i - 1) * 45 + 22.5} 50 50)`"
                  d="M50 6.6 C47.2 11.4 47.8 14.4 50 16.2 C52.2 14.4 52.8 11.4 50 6.6 Z" :fill="`url(#${uid}-tongue)`" />
          </g>
        </g>
      </g>

      <!-- ═════ SUPERNOVA — shock rings leaving a bright core ring, spikes and embers (inferno + phoenix) ═════ -->
      <g v-else-if="ringKey === 'supernova'">
        <circle class="er-breathe" cx="50" cy="50" r="48" :fill="`url(#${uid}-nova)`" />
        <circle v-for="i in 3" :key="i" class="er-shock" cx="50" cy="50" r="36" fill="none" stroke="#ffe08a" stroke-width="1.1"
                :style="{ animationDelay: `${(i - 1) * 1.2}s` }" />
        <circle cx="50" cy="50" r="36.2" fill="none" stroke="#fff7e0" stroke-width="1.7" />
        <g class="er-turn er-turn-slow er-fine">
          <line v-for="i in 12" :key="i" :transform="`rotate(${(i - 1) * 30} 50 50)`" x1="50" y1="9.2" x2="50" :y2="i % 2 ? 2.5 : 5" stroke="#ffd166" stroke-width="0.8" stroke-linecap="round" />
        </g>
        <g class="er-fine">
          <circle v-for="(s, i) in sparks.slice(0, 5)" :key="i" class="er-spark" :cx="s.x" :cy="s.y" r="0.9" fill="#fff0b8"
                  :style="{ '--dx': `${s.dx}px`, '--dy': `${s.dy}px`, animationDelay: `${s.d}s`, animationDuration: `${s.t}s` }" />
        </g>
      </g>

      <!-- ═════ EVENT HORIZON — the whole face is a black hole: shadow, lensed disk, a bright pass (blackhole) ═════ -->
      <g v-else-if="ringKey === 'event-horizon'">
        <circle cx="50" cy="50" r="50" :fill="`url(#${uid}-hole)`" />
        <!-- the back of the disk, bent over the top by the lens -->
        <path d="M24 50 A26 26 0 0 1 76 50" fill="none" :stroke="`url(#${uid}-disk)`" stroke-width="4.4" stroke-linecap="round" opacity="0.92" />
        <path class="er-fine" d="M24 50 A26 26 0 0 1 76 50" fill="none" stroke="#fff6dc" stroke-width="0.8" opacity="0.6" />
        <circle cx="50" cy="50" r="19.5" fill="#000" />
        <circle class="er-pulse" cx="50" cy="50" r="19.8" fill="none" stroke="#ffb454" stroke-width="0.7" opacity="0.85" />
        <!-- the near side of the disk, tilted, in front of the shadow -->
        <g transform="rotate(-14 50 50)">
          <ellipse cx="50" cy="50" rx="46" ry="10.8" fill="none" :stroke="`url(#${uid}-disk)`" stroke-width="5.4" :filter="`url(#${uid}-soft)`" />
          <ellipse cx="50" cy="50" rx="46" ry="10.8" fill="none" :stroke="`url(#${uid}-disk)`" stroke-width="2" />
          <ellipse class="er-pass" cx="50" cy="50" rx="46" ry="10.8" fill="none" stroke="#ffffff" stroke-width="2.2" stroke-dasharray="7 190" stroke-linecap="round" opacity="0.9" />
        </g>
        <circle cx="50" cy="50" r="49.3" fill="none" stroke="#33200f" stroke-width="0.8" />
      </g>

      <!-- ═════ SINGULARITY — a black disk and one photon ring (blackhole) ═════ -->
      <g v-else-if="ringKey === 'singularity'">
        <circle cx="50" cy="50" r="50" :fill="`url(#${uid}-hole)`" />
        <g class="er-turn er-turn-slow er-fine">
          <circle v-for="(s, i) in specks" :key="i" :cx="s.x" :cy="s.y" :r="s.r" fill="#cfd8ff" :opacity="s.o" />
        </g>
        <circle class="er-pulse" cx="50" cy="50" r="23.5" fill="none" stroke="#ffe9b0" stroke-width="3" opacity="0.3" :filter="`url(#${uid}-soft)`" />
        <circle cx="50" cy="50" r="23.5" fill="none" stroke="#fff3cf" stroke-width="1.15" />
        <circle cx="50" cy="50" r="22" fill="#000" />
        <circle cx="50" cy="50" r="49.3" fill="none" stroke="#2a2440" stroke-width="0.8" />
      </g>

      <!-- ═════ ABYSS — ink, slowly turning over in the dark (void) ═════ -->
      <g v-else-if="ringKey === 'abyss'">
        <circle cx="50" cy="50" r="50" fill="#02010a" />
        <g class="er-tide er-tide-a"><circle cx="38" cy="38" r="34" :fill="`url(#${uid}-ink)`" /></g>
        <g class="er-tide er-tide-b"><circle cx="64" cy="62" r="30" :fill="`url(#${uid}-ink2)`" /></g>
        <g class="er-tide er-tide-c er-fine"><circle cx="56" cy="30" r="22" :fill="`url(#${uid}-ink)`" opacity="0.8" /></g>
        <g class="er-fine" fill="none" stroke="#6d5bd0" stroke-width="0.35" opacity="0.28">
          <circle cx="50" cy="50" r="17" /><circle cx="50" cy="50" r="28" /><circle cx="50" cy="50" r="39" />
        </g>
        <path d="M17 33 A36 36 0 0 1 40 14" fill="none" stroke="#9d8cff" stroke-width="1" stroke-linecap="round" opacity="0.5" />
        <circle cx="50" cy="50" r="49.3" fill="none" stroke="#3a2f8c" stroke-width="0.9" />
      </g>

      <!-- ═════ ECLIPSE — a black moon and its corona; one bright bead on the rim (void) ═════ -->
      <g v-else-if="ringKey === 'eclipse'">
        <circle cx="50" cy="50" r="50" fill="#010005" />
        <g class="er-turn er-turn-slow er-corona">
          <rect v-for="i in 24" :key="i" :transform="`rotate(${(i - 1) * 15} 50 50)`" x="49.4" :y="22.4 - (i % 3 === 0 ? 22 : i % 2 ? 14 : 18)" width="1.2"
                :height="i % 3 === 0 ? 22 : i % 2 ? 14 : 18" :fill="`url(#${uid}-ray)`" />
        </g>
        <g class="er-turn er-turn-rev er-fine">
          <rect v-for="i in 12" :key="i" :transform="`rotate(${(i - 1) * 30 + 7} 50 50)`" x="49.6" y="9.4" width="0.8" height="13" :fill="`url(#${uid}-ray)`" opacity="0.7" />
        </g>
        <circle cx="50" cy="50" r="27.5" fill="#000" />
        <circle cx="50" cy="50" r="27.5" fill="none" stroke="#ffe9a8" stroke-width="0.7" opacity="0.7" />
        <g class="er-turn er-turn-bead"><circle cx="50" cy="22.5" r="2" fill="#fff8e0" :filter="`url(#${uid}-soft)`" /><circle cx="50" cy="22.5" r="1" fill="#ffffff" /></g>
      </g>
    </svg>
  </span>
</template>

<script lang="ts">
// module scope: ONE counter for every instance, so each SVG's gradient ids are unique on the page (a counter declared inside <script setup> restarts at 0 for every instance,
// and url(#id) then points at the first instance's defs: a ring in a closed section or an unmounted card would take the gradients of the others with it)
let counter = 0
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from '@/composables/useI18n'


const props = withDefaults(defineProps<{
  /** one of NEW_RINGS' keys (services/contributorTrack.ts) */
  ringKey: string
  /** pixels: the avatar's diameter (22 sidebar, 32 list row, 96 profile) */
  size?: number
  avatarUrl?: string | null
  initials?: string | null
  /** force the still frame (the gallery's "still" view; reduced motion does the same by itself) */
  still?: boolean
}>(), { size: 32, avatarUrl: null, initials: null, still: false })

const { t } = useI18n()
const uid = `er${++counter}`
const root = ref<HTMLElement | null>(null)
const imgFailed = ref(false)

const FULL = new Set(['event-horizon', 'singularity', 'abyss', 'eclipse'])
const cover = computed(() => (FULL.has(props.ringKey) ? 'full' : 'logo'))
const detail = computed(() => (props.size < 28 ? 's' : props.size < 64 ? 'm' : 'l'))
const label = computed(() => t(`contributorTrack.rings.${props.ringKey}.name`, props.ringKey))

// ── the pointer (Eye of the Senate): events only, one write per frame, nothing while the pointer is away ──
let raf = 0
let pending: [number, number] | null = null
function onMove(e: PointerEvent): void {
  if (props.ringKey !== 'eye-of-the-senate' || props.still || !root.value) return
  const r = root.value.getBoundingClientRect()
  pending = [Math.max(-1, Math.min(1, (e.clientX - (r.left + r.width / 2)) / 120)), Math.max(-1, Math.min(1, (e.clientY - (r.top + r.height / 2)) / 120))]
  if (!raf) {
    raf = requestAnimationFrame(() => {
      raf = 0
      if (pending && root.value) {
        root.value.style.setProperty('--ex', pending[0].toFixed(2))
        root.value.style.setProperty('--ey', pending[1].toFixed(2))
      }
    })
  }
}
function onLeave(): void {
  pending = null
  root.value?.style.setProperty('--ex', '0')
  root.value?.style.setProperty('--ey', '0')
}

// ── fixed art data (no randomness: the same ring is the same drawing everywhere) ──
const sparks = [
  { x: 50, y: 8.5, r: 1.05, dx: -2, dy: -7, d: 0, t: 2.6 }, { x: 78, y: 18, r: 0.85, dx: 4, dy: -6, d: 0.5, t: 3.1 },
  { x: 90, y: 46, r: 1, dx: 6, dy: -4, d: 1.1, t: 2.9 }, { x: 80, y: 80, r: 0.8, dx: 5, dy: 5, d: 1.7, t: 3.3 },
  { x: 48, y: 92, r: 1, dx: -1, dy: 6, d: 0.3, t: 2.7 }, { x: 18, y: 80, r: 0.85, dx: -5, dy: 5, d: 1.4, t: 3.2 },
  { x: 8.5, y: 52, r: 1, dx: -6, dy: -3, d: 0.9, t: 3 }, { x: 22, y: 20, r: 0.85, dx: -4, dy: -6, d: 2, t: 2.8 },
]
const latticeNodes = Array.from({ length: 24 }, (_, i) => {
  const a = (i / 24) * Math.PI * 2 - Math.PI / 2
  const o = i % 2 === 0
  const r = o ? 45 : 37.5
  return { x: +(50 + r * Math.cos(a)).toFixed(2), y: +(50 + r * Math.sin(a)).toFixed(2), o }
})
const latticePoints = [...latticeNodes, latticeNodes[0]].map((n) => `${n.x},${n.y}`).join(' ')
const latticeEdges = latticeNodes.map((n, i) => {
  const m = latticeNodes[(i + 2) % 24]
  return [n.x, n.y, m.x, m.y] as const
})
const qubits = [
  { x: 93, y: 50, r: 2.1, c: '#2dd4bf', d: 0 }, { x: 22, y: 72, r: 1.8, c: '#e879f9', d: 0.4 }, { x: 31, y: 24.5, r: 1.9, c: '#2dd4bf', d: 0.9 },
  { x: 77, y: 78, r: 1.7, c: '#e879f9', d: 1.3 }, { x: 62, y: 8, r: 1.5, c: '#a7f3d0', d: 1.8 },
]
const specks = Array.from({ length: 14 }, (_, i) => {
  const a = i * 2.399963
  const r = 30 + (i * 7) % 18
  return { x: +(50 + r * Math.cos(a)).toFixed(2), y: +(50 + r * Math.sin(a)).toFixed(2), r: i % 4 === 0 ? 0.9 : 0.55, o: +(0.35 + (i % 5) * 0.12).toFixed(2) }
})
</script>

<style scoped>
.er {
  --ex: 0;
  --ey: 0;
  position: relative;
  display: inline-block;
  flex-shrink: 0;
  vertical-align: middle;
  width: var(--er-s, 32px);
  height: var(--er-s, 32px);
  isolation: isolate;
  user-select: none;
}
/* the face: a round frame, dark, the picture or the initials */
.er-frame {
  position: absolute;
  inset: 0;
  z-index: 1;
  border-radius: 50%;
  overflow: hidden;
  background: #04070b;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.06);
}
.er-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.er-initials {
  font-family: 'IBM Plex Mono', 'Fira Code', ui-monospace, monospace;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: rgba(224, 240, 255, 0.88);
  font-size: calc(var(--er-s, 32px) * 0.4);
  line-height: 1;
}
/* the art: 100 grid, the avatar is r 32 of it, so the grid is 100/64 of the wrapper and centred on it */
.er-art {
  position: absolute;
  left: 50%;
  top: 50%;
  width: calc(var(--er-s, 32px) * 1.5625);
  height: calc(var(--er-s, 32px) * 1.5625);
  transform: translate(-50%, -50%);
  z-index: 2;
  overflow: visible;
  pointer-events: none;
}
/* a full-cover ring IS the face: the art is the disc, so it is exactly the wrapper's size */
.er-cover-full .er-art {
  width: var(--er-s, 32px);
  height: var(--er-s, 32px);
  clip-path: circle(50%);
  border-radius: 50%;
}
.er-cover-full { border-radius: 50%; }

/* detail follows the size: the fine layers are for 28 px and up */
.er-d-s .er-fine { display: none; }

/* every animated element rests in its still frame; the animation only moves away from it. (No blanket transform-origin: it would move the pivot
   of the rotate() attributes the drawing is built from.) */
.er-tide { transform-box: fill-box; transform-origin: center; }

/* ── LANTERN ── */
.er-breathe { transform-origin: 50px 50px; transform-box: view-box; animation: er-breathe 4.6s ease-in-out infinite; }
.er-flame { transform-origin: 50px 12px; transform-box: view-box; animation: er-flicker 2.4s ease-in-out infinite; }
/* ── EMBER / SUPERNOVA sparks ── */
.er-spark { opacity: 0.85; animation: er-rise 3s ease-out infinite; }
/* ── EYE OF THE SENATE ── */
.er-iris { transform: translate(calc(var(--ex) * 4px), calc(var(--ey) * 2.4px)); transition: transform 0.22s ease-out; }
/* ── OUROBOROS ── */
.er-crawl { transform-origin: 50px 50px; transform-box: view-box; animation: er-spin 46s linear infinite; }
/* ── MERKLE ── */
.er-link { animation: er-link 3s ease-in-out infinite; }
/* ── LATTICE / QUANTUM / SOLAR / ECLIPSE turning ── */
.er-turn { transform-origin: 50px 50px; transform-box: view-box; animation: er-spin 90s linear infinite; }
.er-turn-slow { animation-duration: 140s; }
.er-turn-rev { animation-direction: reverse; animation-duration: 110s; }
.er-turn-bead { animation-duration: 70s; }
.er-node { animation: er-twinkle 2.7s ease-in-out infinite; }
.er-qubit { animation: er-flick 2.2s steps(1, end) infinite; }
/* ── WATCHER: the lid shuts while the pointer is over it, and opens when it leaves ── */
.er-shut { transform-origin: 50px 89px; transform-box: view-box; transform: scaleY(0.001); transition: transform 0.55s cubic-bezier(.3, .0, .2, 1); }
.er-watch:hover .er-shut, .er:hover .er-shut { transform: scaleY(1); transition-duration: 0.18s; }
.er-glance { animation: er-glance 9s ease-in-out infinite; }
/* ── SOLAR FLARE ── */
.er-set-a { animation: er-breathe-a 2.6s ease-in-out infinite; transform-origin: 50px 50px; transform-box: view-box; }
.er-set-b { animation: er-breathe-b 2.6s ease-in-out infinite; transform-origin: 50px 50px; transform-box: view-box; }
/* ── SUPERNOVA ── */
.er-shock { transform-origin: 50px 50px; transform-box: view-box; opacity: 0; animation: er-shock 3.6s ease-out infinite; }
/* ── EVENT HORIZON / SINGULARITY ── */
.er-pulse { animation: er-pulse 3.8s ease-in-out infinite; }
.er-pass { transform-origin: 50px 50px; transform-box: view-box; animation: er-spin 6s linear infinite; }
/* ── ABYSS ── */
.er-tide-a { animation: er-drift-a 19s ease-in-out infinite alternate; }
.er-tide-b { animation: er-drift-b 23s ease-in-out infinite alternate; }
.er-tide-c { animation: er-drift-c 17s ease-in-out infinite alternate; }
/* ── ECLIPSE ── */
.er-corona { animation: er-spin 140s linear infinite, er-corona 4.2s ease-in-out infinite; }

@keyframes er-spin { to { transform: rotate(360deg); } }
@keyframes er-breathe { 0%, 100% { opacity: 0.72; transform: scale(0.97); } 50% { opacity: 1; transform: scale(1.03); } }
@keyframes er-flicker { 0%, 100% { transform: scaleY(1); opacity: 0.95; } 35% { transform: scaleY(1.22); opacity: 0.7; } 70% { transform: scaleY(0.9); opacity: 1; } }
@keyframes er-rise { 0% { transform: translate(0, 0); opacity: 0; } 15% { opacity: 0.95; } 100% { transform: translate(var(--dx, 0), var(--dy, -6px)); opacity: 0; } }
@keyframes er-link { 0%, 100% { stroke: #5eead4; fill: #04161d; } 8% { stroke: #ffffff; fill: #1b6f7e; } 24% { stroke: #5eead4; fill: #04161d; } }
@keyframes er-twinkle { 0%, 100% { opacity: 0.55; } 50% { opacity: 1; } }
@keyframes er-flick { 0% { opacity: 1; } 18% { opacity: 0.25; } 30% { opacity: 1; } 55% { opacity: 0.55; } 70% { opacity: 1; } 86% { opacity: 0.15; } }
@keyframes er-glance { 0%, 38%, 100% { transform: translateX(0); } 46%, 60% { transform: translateX(-2.2px); } 68%, 84% { transform: translateX(2.2px); } }
@keyframes er-breathe-a { 0%, 100% { opacity: 1; transform: scale(1); } 50% { opacity: 0.55; transform: scale(0.97); } }
@keyframes er-breathe-b { 0%, 100% { opacity: 0.55; transform: scale(0.97); } 50% { opacity: 1; transform: scale(1.02); } }
@keyframes er-shock { 0% { opacity: 0.85; transform: scale(1); } 100% { opacity: 0; transform: scale(1.34); } }
@keyframes er-pulse { 0%, 100% { opacity: 0.5; } 50% { opacity: 1; } }
@keyframes er-drift-a { from { transform: translate(-3px, -2px) scale(1); } to { transform: translate(4px, 3px) scale(1.12); } }
@keyframes er-drift-b { from { transform: translate(3px, 2px) scale(1.05); } to { transform: translate(-4px, -3px) scale(0.92); } }
@keyframes er-drift-c { from { transform: translate(-2px, 3px) scale(0.9); } to { transform: translate(3px, -3px) scale(1.1); } }
@keyframes er-corona { 0%, 100% { opacity: 0.78; } 50% { opacity: 1; } }

/* the still frame: reduced motion, or the gallery's still view */
@media (prefers-reduced-motion: reduce) {
  .er-art *, .er-iris { animation: none !important; transition: none !important; }
  .er-shock { opacity: 0.35; }
  .er-spark { opacity: 0.8; }
}
.er-still .er-art *, .er-still .er-iris { animation: none !important; transition: none !important; }
.er-still .er-shock { opacity: 0.35; }
.er-still .er-spark { opacity: 0.8; }
</style>
