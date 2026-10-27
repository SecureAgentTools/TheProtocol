<template>
  <div class="six">
    <div class="six-scroll">
      <table class="six-table">
        <thead>
          <tr>
            <th class="six-corner">{{ t('blueprintsView.safety.corner', 'System / rail') }}</th>
            <th
              v-for="r in RAILS" :key="r.id"
              class="six-rail" :class="{ 'is-hot': hover === r.id }"
              :data-railtip="r.id"
              @mouseenter="hover = r.id" @mouseleave="hover = null"
            >{{ r.id }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="bp in blueprints" :key="bp.id">
            <th class="six-sys">
              <a :href="`#bp-${bp.id}`" @click.prevent="scrollTo(bp.id)">{{ bp.systemName }}</a>
            </th>
            <td
              v-for="r in RAILS" :key="r.id"
              class="six-cell"
              :class="{ 'is-on': bp.rails.includes(r.id), 'is-hot': hover === r.id }"
              :data-railtip="bp.rails.includes(r.id) ? r.id : undefined"
              @mouseenter="hover = r.id" @mouseleave="hover = null"
            >
              <span v-if="bp.rails.includes(r.id)" class="six-dot"></span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- The eighteen refusals, spelled out. S-codes alone explain nothing to a
         first-time visitor; this legend is always visible, tooltip or not. -->
    <div class="six-legend">
      <div v-for="r in RAILS" :key="r.id" class="six-legend-row" :class="{ 'is-hot': hover === r.id }" :data-railtip="r.id">
        <span class="six-legend-id">{{ r.id }}</span>
        <span class="six-legend-name">{{ r.name }}</span>
        <span class="six-legend-refusal">{{ r.refusal }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from '@/composables/useI18n'
import { RAILS } from '@/data/blueprints/rails'
import type { Blueprint } from '@/data/blueprints/types'

defineProps<{ blueprints: Blueprint[] }>()
const { t } = useI18n()
const router = useRouter()

const hover = ref<string | null>(null)

// §18 Atlas split: a system name opens its chamber. When the matrix is
// embedded on a page that still renders sections (none today), the anchor
// href remains a sane fallback.
function scrollTo(id: string) {
  router.push(`/blueprints/${id}`)
}
</script>

<style scoped>
.six-scroll { overflow-x: auto; border: 1px solid rgba(var(--flow-rgb, 0, 210, 210), 0.14); border-radius: 12px; background: rgba(0, 0, 0, 0.2); }
.six-table { border-collapse: collapse; width: 100%; min-width: 760px; }
.six-corner { font-family: var(--bp-mono); font-size: 0.56rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: var(--bp-faint); text-align: left; padding: 0.6rem 0.8rem; position: sticky; left: 0; background: #0a0f17; z-index: 1; }
.six-rail { font-family: var(--bp-mono); font-size: 0.58rem; font-weight: 700; color: var(--bp-faint); padding: 0.6rem 0.25rem; cursor: help; transition: color 0.2s ease; }
.six-rail.is-hot { color: rgb(var(--flow-rgb)); }
.six-sys { font-family: var(--bp-mono); font-size: 0.64rem; font-weight: 700; text-align: left; padding: 0.42rem 0.8rem; position: sticky; left: 0; background: #0a0f17; z-index: 1; white-space: nowrap; }
.six-sys a { color: var(--bp-dim); text-decoration: none; }
.six-sys a:hover { color: rgb(var(--flow-rgb)); }
.six-cell { text-align: center; padding: 0.42rem 0.25rem; border-top: 1px solid rgba(var(--flow-rgb), 0.05); }
.six-cell.is-on { cursor: help; }
.six-cell.is-hot { background: rgba(var(--flow-rgb), 0.04); }
.six-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: rgba(var(--flow-rgb), 0.75); box-shadow: 0 0 7px rgba(var(--flow-rgb), 0.45); }

.six-legend { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0.15rem 1.4rem; margin-top: 1rem; }
.six-legend-row { display: grid; grid-template-columns: 2.2rem 10.5rem 1fr; gap: 0.5rem; align-items: baseline; padding: 0.28rem 0.4rem; border-radius: 7px; cursor: help; }
.six-legend-row.is-hot { background: rgba(var(--flow-rgb), 0.06); }
.six-legend-id { font-family: var(--bp-mono); font-size: 0.6rem; font-weight: 800; color: rgba(var(--flow-rgb), 0.85); }
.six-legend-name { font-family: var(--bp-mono); font-size: 0.62rem; font-weight: 700; color: var(--bp-ink-soft); }
.six-legend-refusal { font-size: 0.66rem; color: var(--bp-faint); line-height: 1.5; }

@media (max-width: 900px) {
  .six-legend { grid-template-columns: 1fr; }
  .six-legend-row { grid-template-columns: 2.2rem 1fr; }
  .six-legend-refusal { grid-column: 2; }
}
</style>
