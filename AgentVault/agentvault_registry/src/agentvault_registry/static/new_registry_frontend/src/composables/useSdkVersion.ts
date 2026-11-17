// V0666 (gwo_dc5050837e93b0a64d1fdae7): the SDK version the console's proxy catalog was made from (it moves with each
// release: never a literal on the landing page). Read once, after the page is up: the catalog is its own chunk, so the
// landing's first load does not carry it. Empty until it has been read.
import { ref, type Ref } from 'vue'

const version = ref('')
let asked: Promise<void> | null = null

export function useSdkVersion(): { sdkVersion: Ref<string>; load: () => Promise<void> } {
  const load = () => (asked ??= import('@/data/proxy/catalog.generated.json')
    .then((m) => { const v = (m as { sdk_version?: unknown }).sdk_version ?? (m as { default?: { sdk_version?: unknown } }).default?.sdk_version
      version.value = typeof v === 'string' ? v : '' })
    .catch(() => { asked = null }))
  return { sdkVersion: version, load }
}
