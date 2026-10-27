/**
 * §FESUITE V0595 (his word 2026-10-11, "also correct the avt prose in the docs"): the switches a docs page's parts follow,
 * as THIS registry said them in its public configuration (composables/docs/switchBlocks.ts). One shared read
 * (useRegistryConfig): a read that failed says nothing, so its parts stay out and the page says it could not read.
 */
import { computed } from 'vue'
import { useRegistryConfig } from '@/composables/useRegistryConfig'
import { knownSwitches } from './switchBlocks'

export function useDocSwitches() {
  const { config, readOk, loaded } = useRegistryConfig()
  return {
    known: computed(() => knownSwitches(config.value as Record<string, unknown>, readOk.value)),
    /** the read settled (answered or failed): before that a page names nothing it left out */
    loaded,
  }
}
