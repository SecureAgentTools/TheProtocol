<!--
  GalacticControls.vue — cosmic search / filter / view toolbar for the Galactic Map.
  Replaces the legacy light-gray "Discover agents across the sovereign network" bar.
  Two presentations via `variant`:
    • 'overlay' → floating glass HUD docked at the top of the 3D canvas (map mode)
    • 'bar'     → full-width cosmic strip above the grid/list browse modes
  All filter state is two-way bound with defineModel (Vue 3.4) so the parent keeps
  a single source of truth and every control drives the canvas + the browse list.
-->
<template>
  <div class="gc-root" :class="[`gc-${variant}`, { 'gc-open': filtersOpen, 'gc-is-collapsed': collapsed && variant === 'overlay' }]">
    <!-- Collapsed launcher (overlay only) — keeps the canvas clear until summoned -->
    <button v-if="collapsed && variant === 'overlay'" class="gc-launcher" @click="collapsed = false"
      title="Open search & filters" aria-label="Open search and filters">
      <svg class="gc-launch-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.2-5.2M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <span class="gc-launch-lbl">{{ launcherLabel }}</span>
      <span class="gc-launch-chev">▾</span>
    </button>

    <div v-show="!(collapsed && variant === 'overlay')" class="gc-bar">
      <!-- Search -->
      <div class="gc-search">
        <svg class="gc-search-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-5.2-5.2M17 10a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          :value="search"
          @input="search = ($event.target as HTMLInputElement).value"
          type="text"
          class="gc-search-input"
          placeholder="Search agents across the sovereign network…"
          spellcheck="false"
          aria-label="Search agents"
        />
        <button v-if="search" class="gc-search-clear" @click="search = ''" aria-label="Clear search">✕</button>
      </div>

      <!-- Frame filter -->
      <label class="gc-field" :title="'Filter by sovereign frame'">
        <span class="gc-field-glyph">◇</span>
        <select :value="frame" @change="frame = ($event.target as HTMLSelectElement).value" class="gc-select" aria-label="Frame filter">
          <option value="all">All Frames</option>
          <option value="local">My Frame</option>
          <option v-for="f in frames" :key="f" :value="f">{{ f }}</option>
        </select>
      </label>

      <!-- Registry filter -->
      <label class="gc-field" :title="'Filter by registry'">
        <span class="gc-field-glyph">⬡</span>
        <select :value="registry" @change="registry = ($event.target as HTMLSelectElement).value" class="gc-select" aria-label="Registry filter">
          <option v-for="o in registryOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>

      <!-- Sort -->
      <label class="gc-field gc-field--sort" :title="'Sort agents'">
        <span class="gc-field-glyph">⇅</span>
        <select :value="sort" @change="sort = ($event.target as HTMLSelectElement).value" class="gc-select" aria-label="Sort by">
          <option v-for="o in sortOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
      </label>

      <!-- View mode (hidden where there is only one view, e.g. the 3D Universe) -->
      <div v-if="showViewModes" class="gc-views" role="group" aria-label="View mode">
        <button v-for="m in viewModes" :key="m.id" class="gc-view-btn" :class="{ 'gc-view-active': view === m.id }"
          :title="m.label" :aria-label="m.label" @click="view = m.id">
          <span v-html="m.icon" class="gc-view-ic"></span>
        </button>
      </div>

      <!-- Filters toggle -->
      <button class="gc-filters-btn" :class="{ 'gc-filters-on': filtersOpen || capabilities.length && selCaps.length }"
        @click="filtersOpen = !filtersOpen" :title="'Capability filters'">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="gc-view-ic">
          <path stroke-linecap="round" stroke-linejoin="round" d="M3 4h18M6 12h12M10 20h4" />
        </svg>
        <span class="gc-filters-lbl">Filters</span>
        <span v-if="selCaps.length" class="gc-badge">{{ selCaps.length }}</span>
      </button>

      <!-- Collapse (overlay only) — agent count lives in the bottom legend, not here -->
      <button v-if="variant === 'overlay'" class="gc-collapse" @click="collapsed = true"
        title="Collapse controls" aria-label="Collapse controls">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 15l6-6 6 6" />
        </svg>
      </button>
    </div>

    <!-- Capability chips (collapsible) -->
    <transition name="gc-fade">
      <div v-if="filtersOpen && capabilities.length" class="gc-caps">
        <div class="gc-caps-head">
          <span class="gc-caps-title">Capabilities</span>
          <button v-if="selCaps.length" class="gc-caps-clear" @click="clearCaps">Clear all</button>
        </div>
        <div class="gc-caps-wrap">
          <button v-for="c in capabilities" :key="c" class="gc-chip" :class="{ 'gc-chip-on': selCaps.includes(c) }"
            @click="toggleCap(c)">{{ c }}</button>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

interface Opt { value: string; label: string }

const props = withDefaults(defineProps<{
  variant?: 'overlay' | 'bar'
  frames: string[]
  registryOptions: Opt[]
  sortOptions: Opt[]
  capabilities: string[]
  resultCount: number
  /** Hide the map/grid/list view switcher (single-view hosts like the 3D Universe). */
  showViewModes?: boolean
  /** Overlay-only: start collapsed to the launcher pill (GCC docks it as a small FILTER chip). */
  startCollapsed?: boolean
  /** Label on the collapsed launcher pill. */
  launcherLabel?: string
}>(), { showViewModes: true, startCollapsed: false, launcherLabel: 'Search & filter' })

// Two-way bound filter state (single source of truth lives in the parent).
const search   = defineModel<string>('search',   { default: '' })
const frame    = defineModel<string>('frame',    { default: 'all' })
const registry = defineModel<string>('registry', { default: 'all' })
const sort     = defineModel<string>('sort',     { default: 'reputation' })
const view     = defineModel<string>('view',     { default: 'map' })
const selCaps  = defineModel<string[]>('selectedCapabilities', { default: () => [] })

const filtersOpen = ref(false)
const collapsed = ref(props.startCollapsed)   // overlay-only: collapse the whole bar to a launcher pill

const viewModes = [
  { id: 'map',  label: 'Galactic map',  icon: '<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M5.05 4.05a7 7 0 119.9 9.9L10 18.9l-4.95-4.95a7 7 0 010-9.9zM10 11a2 2 0 100-4 2 2 0 000 4z" clip-rule="evenodd"/></svg>' },
  { id: 'grid', label: 'Card grid',     icon: '<svg viewBox="0 0 20 20" fill="currentColor"><path d="M5 3a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2V5a2 2 0 00-2-2H5zM5 11a2 2 0 00-2 2v2a2 2 0 002 2h2a2 2 0 002-2v-2a2 2 0 00-2-2H5zM11 5a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V5zM11 13a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z"/></svg>' },
  { id: 'list', label: 'List view',     icon: '<svg viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" clip-rule="evenodd"/></svg>' },
]

function toggleCap(c: string) {
  selCaps.value = selCaps.value.includes(c) ? selCaps.value.filter(x => x !== c) : [...selCaps.value, c]
}
function clearCaps() { selCaps.value = [] }
</script>

<style scoped>
.gc-root { font-family: 'Inter', system-ui, sans-serif; z-index: 14; }

/* ── overlay: floating glass HUD docked at the top of the canvas ── */
.gc-overlay {
  position: absolute; top: 14px; left: 50%; transform: translateX(-50%);
  width: min(960px, calc(100% - 220px)); pointer-events: none;
}
.gc-overlay .gc-bar, .gc-overlay .gc-caps { pointer-events: auto; }

/* ── bar: full-width strip above grid/list ── */
.gc-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 10px; border-radius: 14px;
  background: linear-gradient(180deg, rgba(11,17,28,0.92), rgba(8,12,20,0.88));
  border: 1px solid rgba(120,170,230,0.16);
  box-shadow: 0 12px 40px -12px rgba(0,0,0,0.7), 0 0 0 1px rgba(0,0,0,0.4) inset,
              0 0 28px -10px rgba(56,189,248,0.25);
  backdrop-filter: blur(14px) saturate(1.1);
}

/* search */
.gc-search { position: relative; flex: 1 1 240px; min-width: 200px; display: flex; align-items: center; }
.gc-search-ic { position: absolute; left: 11px; width: 16px; height: 16px; color: rgba(150,185,225,0.7); pointer-events: none; }
.gc-search-input {
  width: 100%; padding: 8px 30px 8px 34px; border-radius: 10px;
  background: rgba(4,8,15,0.7); border: 1px solid rgba(120,170,230,0.18);
  color: #e8f2ff; font-size: 13px; letter-spacing: 0.01em; outline: none;
  transition: border-color .18s, box-shadow .18s, background .18s;
}
.gc-search-input::placeholder { color: rgba(150,180,215,0.45); }
.gc-search-input:focus { border-color: rgba(56,189,248,0.65); background: rgba(6,12,22,0.85);
  box-shadow: 0 0 0 3px rgba(56,189,248,0.14), 0 0 18px -6px rgba(56,189,248,0.5); }
.gc-search-clear { position: absolute; right: 8px; width: 18px; height: 18px; border: 0; border-radius: 50%;
  background: rgba(120,150,190,0.18); color: #cfe2ff; font-size: 10px; cursor: pointer; line-height: 1;
  display: grid; place-items: center; transition: background .15s; }
.gc-search-clear:hover { background: rgba(244,63,94,0.6); color: #fff; }

/* selects */
.gc-field { position: relative; display: flex; align-items: center; }
.gc-field-glyph { position: absolute; left: 9px; font-size: 11px; color: rgba(120,200,255,0.7); pointer-events: none; }
.gc-select {
  appearance: none; padding: 8px 26px 8px 26px; border-radius: 10px;
  background: rgba(4,8,15,0.7); border: 1px solid rgba(120,170,230,0.18);
  color: #d7e7fb; font-size: 12.5px; cursor: pointer; outline: none; max-width: 168px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath fill='%237fb0e0' d='M0 0l5 6 5-6z'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 9px center;
  transition: border-color .18s, box-shadow .18s;
}
.gc-select:hover { border-color: rgba(120,170,230,0.4); }
.gc-select:focus { border-color: rgba(56,189,248,0.6); box-shadow: 0 0 0 3px rgba(56,189,248,0.12); }
.gc-select option { background: #0a0e18; color: #e8f0ff; }
.gc-field--sort { display: flex; }

/* view toggle */
.gc-views { display: flex; gap: 3px; padding: 3px; border-radius: 10px;
  background: rgba(4,8,15,0.6); border: 1px solid rgba(120,170,230,0.14); }
.gc-view-btn { width: 30px; height: 30px; border: 0; border-radius: 7px; background: transparent;
  color: rgba(160,190,225,0.7); cursor: pointer; display: grid; place-items: center; transition: all .15s; }
.gc-view-btn:hover { background: rgba(120,170,230,0.14); color: #d7e7fb; }
.gc-view-active { background: linear-gradient(180deg, rgba(56,189,248,0.95), rgba(37,99,235,0.95));
  color: #fff; box-shadow: 0 0 14px -4px rgba(56,189,248,0.8); }
.gc-view-ic { display: inline-grid; }
.gc-view-ic :deep(svg) { width: 16px; height: 16px; }

/* filters button */
.gc-filters-btn { display: flex; align-items: center; gap: 6px; padding: 8px 11px; border-radius: 10px;
  background: rgba(4,8,15,0.7); border: 1px solid rgba(120,170,230,0.18); color: #cfe0f6;
  font-size: 12.5px; cursor: pointer; transition: all .15s; }
.gc-filters-btn:hover { border-color: rgba(120,170,230,0.42); color: #eaf3ff; }
.gc-filters-on { border-color: rgba(56,189,248,0.55); color: #eaf6ff; box-shadow: 0 0 14px -6px rgba(56,189,248,0.6); }
.gc-filters-lbl { font-weight: 500; }
.gc-badge { min-width: 17px; height: 17px; padding: 0 4px; border-radius: 9px; display: grid; place-items: center;
  background: linear-gradient(180deg, #38bdf8, #2563eb); color: #fff; font-size: 10px; font-weight: 700; }

/* count */
.gc-count { margin-left: auto; display: flex; align-items: baseline; gap: 5px; padding: 0 6px; white-space: nowrap; }
.gc-count strong { color: #7fe7ff; font-size: 15px; font-variant-numeric: tabular-nums;
  text-shadow: 0 0 12px rgba(56,189,248,0.5); }
.gc-count-lbl { color: rgba(150,180,215,0.7); font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em; }

/* collapse button (in the bar) + collapsed launcher pill */
.gc-collapse { margin-left: auto; flex: 0 0 auto; width: 30px; height: 30px; border-radius: 9px;
  border: 1px solid rgba(120,170,230,0.18); background: rgba(4,8,15,0.7); color: rgba(160,190,225,0.8);
  cursor: pointer; display: grid; place-items: center; transition: all .15s; }
.gc-collapse:hover { border-color: rgba(56,189,248,0.5); color: #eaf6ff; }
.gc-collapse svg { width: 16px; height: 16px; }
.gc-launcher { pointer-events: auto; display: inline-flex; align-items: center; gap: 8px; padding: 9px 14px;
  border-radius: 12px; cursor: pointer; font-size: 13px; color: #d7e7fb;
  background: linear-gradient(180deg, rgba(11,17,28,0.92), rgba(8,12,20,0.88));
  border: 1px solid rgba(120,170,230,0.18);
  box-shadow: 0 12px 40px -12px rgba(0,0,0,0.7), 0 0 28px -10px rgba(56,189,248,0.25);
  backdrop-filter: blur(14px) saturate(1.1); transition: all .15s; }
.gc-launcher:hover { border-color: rgba(56,189,248,0.5); color: #eaf6ff;
  box-shadow: 0 12px 40px -12px rgba(0,0,0,0.85), 0 0 30px -8px rgba(56,189,248,0.45); }
.gc-launch-ic { width: 16px; height: 16px; color: rgba(150,200,255,0.85); }
.gc-launch-lbl { font-weight: 500; letter-spacing: 0.01em; }
.gc-launch-chev { color: rgba(150,180,215,0.6); font-size: 11px; }
.gc-overlay.gc-is-collapsed { width: auto; }

/* capability chips */
.gc-caps { margin-top: 8px; padding: 10px 12px; border-radius: 12px;
  background: linear-gradient(180deg, rgba(11,17,28,0.94), rgba(8,12,20,0.9));
  border: 1px solid rgba(120,170,230,0.14); backdrop-filter: blur(14px); }
.gc-caps-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.gc-caps-title { color: rgba(170,200,235,0.85); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; }
.gc-caps-clear { background: none; border: 0; color: #7fb0e0; font-size: 11.5px; cursor: pointer; }
.gc-caps-clear:hover { color: #acd2ff; text-decoration: underline; }
.gc-caps-wrap { display: flex; flex-wrap: wrap; gap: 6px; max-height: 132px; overflow-y: auto; }
.gc-chip { padding: 4px 11px; border-radius: 20px; font-size: 12px; cursor: pointer;
  background: rgba(4,8,15,0.6); border: 1px solid rgba(120,170,230,0.18); color: #b9cce4; transition: all .14s; }
.gc-chip:hover { border-color: rgba(120,170,230,0.45); color: #e3eeff; }
.gc-chip-on { background: linear-gradient(180deg, rgba(56,189,248,0.95), rgba(37,99,235,0.92));
  border-color: transparent; color: #fff; box-shadow: 0 0 14px -5px rgba(56,189,248,0.8); }

.gc-fade-enter-active, .gc-fade-leave-active { transition: opacity .18s, transform .18s; }
.gc-fade-enter-from, .gc-fade-leave-to { opacity: 0; transform: translateY(-6px); }

/* compact-down on narrow canvases */
@media (max-width: 1100px) {
  .gc-overlay { width: calc(100% - 24px); }
  .gc-field--sort, .gc-count { display: none; }
}
</style>
