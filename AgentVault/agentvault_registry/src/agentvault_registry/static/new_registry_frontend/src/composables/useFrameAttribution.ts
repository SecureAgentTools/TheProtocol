// 2026-05-05 audit Tier 3: shared frame attribution helper — classify a registry by its trust_domain, never by a
// URL substring (the Bavaria-stacking / dedup-duplicate / wrong-colour class).
//
// §FEFRAME W2 (2026-10-01): this registry's own trust domain comes from the FRAME MANIFEST (registry-config
// `self.trust_domain`, the same one fetch every identity reader shares) instead of GET /federation/info, whose
// server default was `agentvault.com`: a registry with no SPIRE_TRUST_DOMAIN classified itself as the retired
// Frame A.
//
// Usage:
//   const { ensureLocalFrame, classifyByTrustDomain, localTrustDomain } = useFrameAttribution()
//   await ensureLocalFrame()
//   const frame = classifyByTrustDomain(reg.trust_domain)  // 'local' | <td> | 'unknown'
import { computed } from 'vue'
import { loadFrameManifest, useFrameManifest } from '@/composables/useFrameManifest'

export function useFrameAttribution() {
  const fm = useFrameManifest()
  const localTrustDomain = computed<string | null>(() => (fm.self.value?.trust_domain || '').toLowerCase() || null)

  /** Resolves once the manifest answered (or the config failed); idempotent, one request per page. */
  async function ensureLocalFrame(): Promise<void> {
    await loadFrameManifest()
  }

  /**
   * 'local' when the trust domain is this registry's own, the trust domain itself for another frame, 'unknown'
   * when it is missing. With no manifest (an older registry) every trust domain is reported as-is.
   */
  function classifyByTrustDomain(trust_domain: string | null | undefined): string {
    if (!trust_domain) return 'unknown'
    const td = trust_domain.toLowerCase()
    if (!localTrustDomain.value) return td
    return td === localTrustDomain.value ? 'local' : td
  }

  return { ensureLocalFrame, classifyByTrustDomain, localTrustDomain }
}
