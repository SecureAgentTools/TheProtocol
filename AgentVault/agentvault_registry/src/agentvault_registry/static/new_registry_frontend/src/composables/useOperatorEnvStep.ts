/**
 * The operator application's configuration step (§FESUITE V0595, his word 2026-10-11: "we need env setup in the
 * application forms ... the env flips that are frame exclusive should be still displayed for operators but greyed out
 * and not chooseable").
 *
 * The frame's catalog (GET /public/env-catalog) is the starting point: every setting begins as this frame runs it (an
 * operator inherits it), the frame-scope ones are locked with the frame's value and its reason, and the application
 * sends only the operator settings chosen differently (`choices()`). A catalog that could not be read is said so; the
 * application still goes, with nothing chosen (everything inherited), never with a guess.
 */
import { computed, ref } from 'vue'
import { frameValue, loadEnvCatalog, operatorChoices, type EnvCatalog } from '@/services/api/envCatalog'

export function useOperatorEnvStep() {
  const envCatalog = ref<EnvCatalog | null>(null)
  const envFailed = ref(false)
  const opFeatures = ref<Record<string, string>>({})

  const envBaseline = computed<Record<string, string>>(() =>
    Object.fromEntries((envCatalog.value?.entries || []).map(e => [e.key, frameValue(e)])))
  const envLocked = computed<Record<string, { value: string; reason: string }>>(() =>
    Object.fromEntries((envCatalog.value?.entries || []).filter(e => e.scope === 'frame')
      .map(e => [e.key, { value: frameValue(e), reason: e.reason || '' }])))
  const choices = (): Record<string, string> => (envCatalog.value ? operatorChoices(envCatalog.value, opFeatures.value) : {})
  const envChangedCount = computed(() => Object.keys(choices()).length)

  async function loadEnv() {
    envFailed.value = false
    try {
      envCatalog.value = await loadEnvCatalog()
      opFeatures.value = { ...envBaseline.value }
    } catch {
      envCatalog.value = null
      envFailed.value = true
    }
  }
  function onEnvChange(key: string, value: string) {
    if (envLocked.value[key]) return   // the frame's: never chosen here, whatever the screen sent
    opFeatures.value = { ...opFeatures.value, [key]: value }
  }
  function resetEnv() {
    opFeatures.value = { ...envBaseline.value }
  }

  return { envCatalog, envFailed, opFeatures, envBaseline, envLocked, envChangedCount, choices, loadEnv, onEnvChange, resetEnv }
}
