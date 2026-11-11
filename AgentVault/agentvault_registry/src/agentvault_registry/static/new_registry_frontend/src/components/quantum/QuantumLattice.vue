<template>
  <svg
    class="ql"
    :class="'ql--' + size"
    viewBox="0 0 100 100"
    preserveAspectRatio="xMidYMid meet"
    role="img"
    :aria-label="label"
    data-testid="qc-lattice"
    :data-source="lattice.source"
    :data-nodes="lattice.drawn"
    :data-edges="lattice.edges.length"
  >
    <!-- V0660 (e): the backend's lattice, drawn only from what the card states (services/quantum/quantumCard.latticeFor):
         every pair for an all-to-all topology, no edge at all for a coupling map published as a digest. A point is a
         qubit, cut like a facet; its place in the field implies no coupling. -->
    <g class="ql-edges">
      <line
        v-for="([a, b], i) in lattice.edges"
        :key="'e' + i"
        :x1="x(a)" :y1="y(a)" :x2="x(b)" :y2="y(b)"
        vector-effect="non-scaling-stroke"
      />
    </g>
    <g class="ql-nodes">
      <path
        v-for="(n, i) in lattice.nodes"
        :key="'n' + i"
        :d="facet(n.x * 100, n.y * 100)"
      />
    </g>
  </svg>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Lattice } from '@/services/quantum/quantumCard'

const props = withDefaults(defineProps<{ lattice: Lattice; label: string; size?: 'sm' | 'md' | 'lg' }>(), { size: 'md' })

const x = (i: number) => (props.lattice.nodes[i]?.x ?? 0.5) * 100
const y = (i: number) => (props.lattice.nodes[i]?.y ?? 0.5) * 100
/** a point's size follows the count, so 4 qubits and 64 both read as a field */
const r = computed(() => Math.max(0.9, Math.min(3.2, 14 / Math.sqrt(Math.max(1, props.lattice.drawn)))))
/** a cut diamond: four facets meeting at the centre */
function facet(cx: number, cy: number): string {
  const s = r.value
  return `M${cx} ${cy - s}L${cx + s} ${cy}L${cx} ${cy + s}L${cx - s} ${cy}Z`
}
</script>

<style scoped>
.ql { display: block; width: 100%; height: auto; }
.ql--sm { max-width: 88px; }
.ql--md { max-width: 168px; }
.ql--lg { max-width: 260px; }
.ql-edges line { stroke: rgba(150, 214, 236, 0.42); stroke-width: 1px; }
.ql-nodes path { fill: #d9eef7; stroke: rgba(10, 14, 26, 0.6); stroke-width: 0.2; }
</style>
