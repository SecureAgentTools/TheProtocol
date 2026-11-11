<template>
  <div v-if="served" class="mb-3 disc-filter-group qf" data-testid="disc-quantum-filters">
    <!-- V0660 (e): discovery's filters for the quantum workload extension's facts. They render only where the frame
         serves the extension (the registry reads the quantum_* parameters only there); the options are the registry's
         own facets of the page's population (facets.quantum). -->
    <h4 class="qf-h">
      <svg class="qf-glyph" viewBox="0 0 16 16" aria-hidden="true"><path d="M4 1.5h8L15 6 8 14.5 1 6z M1 6h14" /></svg>
      {{ t('quantumCard.filters.title', 'Quantum workloads') }}
      <span v-if="facets" class="qf-count">{{ facets.total }}</span>
    </h4>
    <label class="qf-row">
      <input type="checkbox" :checked="modelValue.only" data-testid="qf-only" @change="set('only', ($event.target as HTMLInputElement).checked)" />
      <span>{{ t('quantumCard.filters.only', 'Only agents with the quantum extension') }}</span>
    </label>
    <label v-for="sel in selects" :key="sel.key" class="qf-field">
      <span class="qf-label">{{ sel.label }}</span>
      <select class="qf-select" :value="modelValue[sel.key]" :data-testid="'qf-' + sel.key" @change="set(sel.key, ($event.target as HTMLSelectElement).value)">
        <option value="">{{ t('quantumCard.filters.any', 'Any') }}</option>
        <option v-for="o in sel.options" :key="o.name" :value="o.name">{{ o.label }} ({{ o.count }})</option>
      </select>
    </label>
    <label class="qf-field">
      <span class="qf-label">{{ t('quantumCard.filters.minQubits', 'At least this many qubits') }}</span>
      <input class="qf-select" type="number" min="1" step="1" inputmode="numeric" :value="modelValue.min_qubits"
             :placeholder="facets?.max_qubits ? tp('quantumCard.filters.maxHere', 'up to {n} here', { n: facets.max_qubits }) : ''"
             data-testid="qf-min_qubits" @change="set('min_qubits', ($event.target as HTMLInputElement).value)" />
    </label>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useQuantumWorkloads } from '@/composables/useQuantumWorkloads'
import { useI18n } from '@/composables/useI18n'
import type { FacetCount, QuantumDiscoverFacets, QuantumFilters } from '@/services/quantum/quantumCard'

const props = defineProps<{ modelValue: QuantumFilters; facets: QuantumDiscoverFacets | null }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: QuantumFilters): void; (e: 'change'): void }>()

const { t, tp } = useI18n()
const { served } = useQuantumWorkloads()

type Key = 'modality' | 'kind' | 'format' | 'jurisdiction' | 'rung' | 'role'

function set(key: keyof QuantumFilters, value: string | boolean) {
  emit('update:modelValue', { ...props.modelValue, [key]: value } as QuantumFilters)
  emit('change')
}

/** the facets, and the value already chosen even where this page's population no longer holds it */
function opts(rows: FacetCount[] | undefined, chosen: string, label: (n: string) => string) {
  const list = (rows || []).map((r) => ({ name: r.name, count: r.count, label: label(r.name) }))
  if (chosen && !list.some((o) => o.name === chosen)) list.push({ name: chosen, count: 0, label: label(chosen) })
  return list
}

const selects = computed<Array<{ key: Key; label: string; options: Array<{ name: string; count: number; label: string }> }>>(() => {
  const f = props.facets
  const v = props.modelValue
  const same = (n: string) => n
  return [
    { key: 'modality', label: t('quantumCard.filters.modality', 'Modality'), options: opts(f?.modalities, v.modality, same) },
    { key: 'kind', label: t('quantumCard.filters.kind', 'Kind'), options: opts(f?.kinds, v.kind, same) },
    { key: 'format', label: t('quantumCard.filters.format', 'Format'), options: opts(f?.formats, v.format, same) },
    { key: 'jurisdiction', label: t('quantumCard.filters.jurisdiction', 'Jurisdiction'), options: opts(f?.jurisdictions, v.jurisdiction, same) },
    { key: 'rung', label: t('quantumCard.filters.rung', 'Verification rung'), options: opts(f?.rungs, v.rung, (n) => tp('quantumCard.rungs.rung', 'Rung {n}', { n })) },
    { key: 'role', label: t('quantumCard.filters.role', 'Role'), options: opts(f?.roles, v.role, same) },
  ]
})
</script>

<style scoped>
.qf { font-weight: 300; }
.qf-h { display: flex; align-items: center; gap: 6px; color: #9fdcf0; font-size: 12px; font-weight: 500; margin: 0 0 6px; }
.qf-glyph { width: 13px; height: 13px; fill: none; stroke: #9fdcf0; stroke-width: 1; stroke-linejoin: round; }
.qf-count { color: #b4c0d0; font-size: 11px; font-weight: 400; margin-left: auto; }
.qf-row { display: flex; align-items: center; gap: 6px; color: #dfe7f1; font-size: 12px; margin-bottom: 6px; cursor: pointer; }
.qf-field { display: grid; gap: 2px; margin-bottom: 6px; }
.qf-label { color: #b4c0d0; font-size: 11px; }
.qf-select {
  width: 100%;
  color: #e8eef6;
  background: #0a0e1a;
  border: 1px solid rgba(201, 211, 224, 0.28);
  border-radius: 2px;
  font-size: 12px;
  padding: 3px 6px;
}
.qf-select:focus-visible { outline: 1px solid #9fdcf0; outline-offset: 1px; }
</style>
