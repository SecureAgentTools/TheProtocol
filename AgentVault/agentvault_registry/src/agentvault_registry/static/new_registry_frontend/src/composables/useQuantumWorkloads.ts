/**
 * V0660 (e): does this frame serve quantum workloads? The answer is the registry's own: the public registry-config's
 * `quantum_workloads` block (V0660 (d), services/quantum_workloads.py), present only while QUANTUM_WORKLOADS_MODE is
 * shadow or on. Absent, unread or failed reads as off: the console then asks no quantum route, sends no quantum filter
 * and draws no quantum card, so a frame with the switch off looks exactly as it did before V0660.
 */
import { computed } from 'vue'
import { peekRegistryConfig, useRegistryConfig } from '@/composables/useRegistryConfig'
import { quantumServed, type QuantumWorkloadsBlock } from '@/services/quantum/quantumCard'

/** `passive`: read the mode only from a registry-config already loaded, never starting a read (the chat path, where a
 *  Pocket thread under off makes no registry-config read of its own). */
export function useQuantumWorkloads(opts: { passive?: boolean } = {}) {
  const { config } = opts.passive ? peekRegistryConfig() : useRegistryConfig()
  const block = computed<QuantumWorkloadsBlock | null>(() => {
    const b = (config.value as any)?.quantum_workloads
    return b && typeof b === 'object' ? (b as QuantumWorkloadsBlock) : null
  })
  return { block, served: computed(() => quantumServed(block.value)) }
}
