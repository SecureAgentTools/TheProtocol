/**
 * §LEGALKIT (2026-09-20): the frame's legal posture, from the registry, and the token resolver the legal
 * pages use. Nothing about the provider is written into the shipped source; every placeholder in
 * content/legal/suiteV2.ts ({PROVIDER_FULL}, {LEGAL_EMAIL}, ...) resolves from GET /api/v1/legal/config.
 *
 * Two modes:
 *   theprotocol  the frame is run by the author of the software; the suite renders with these facts.
 *   operator     someone else runs it; provider-owned pages render the operator's facts and links,
 *                or an honest "not published yet" page. Never our details, never a fallback.
 */
import { ref, readonly } from 'vue'
import { createBackoffRetry } from '@/services/backoffRetry'

export interface ProviderFacts {
  legal_name: string | null
  legal_form: string | null
  trading_as: string | null
  street: string | null
  postal_code: string | null
  city: string | null
  country: string | null
  country_code: string | null
  legal_email: string | null
  privacy_email: string | null
  security_email: string | null
  support_email: string | null
  supervisory_authority: string | null
  governing_law: string | null
  venue: string | null
  business_days: string | null
  vat_id: string | null
  small_business: boolean
  editorial_person: string | null
  address_line: string | null
  full_line: string | null
  address_block: string | null
  /** §COOKIES (2026-10-02): optional (LEGAL_PROVIDER_PHONE); a registry older than this field does not send it. */
  phone?: string | null
}

export interface LegalConfig {
  mode: 'theprotocol' | 'operator'
  provider: ProviderFacts | null
  provider_identified: boolean
  operator_links: { terms_url: string | null; privacy_url: string | null; security_policy_url: string | null } | null
  tos_version: string
  documents_version: string
  effective: string
  effective_label?: string
  published: string
  documents?: Record<string, string>
  /** AGPL-3.0 § 13: where this deployment's source is (SOURCE_CODE_URL); null when the frame names none. */
  source_code_url?: string | null
}

export type LegalLoadState = 'idle' | 'loading' | 'loaded' | 'failed'

const _config = ref<LegalConfig | null>(null)
const _state = ref<LegalLoadState>('idle')
let _inflight: Promise<LegalConfig | null> | null = null
/** §FESUITE (2026-10-09): a read that got no answer (or a 5xx: a registry restarting) is read again on its own, backing
 *  off, and on the next use. It was read once per session: a console booted while the registry could not answer kept the
 *  failure for the session, so the legal pages showed their "[provider details unavailable]" gaps and the re-consent
 *  notice said "applies from ." after the registry was back (sweeps/recovery on V0587). A refusal is never retried. */
const _retry = createBackoffRetry(() => loadLegalConfig())

export async function loadLegalConfig(force = false): Promise<LegalConfig | null> {
  if (_config.value && !force) return _config.value
  if (_inflight && !force) return _inflight
  _state.value = 'loading'
  _inflight = (async () => {
    try {
      const res = await fetch('/api/v1/legal/config', { credentials: 'same-origin', cache: 'no-store' })
      if (!res.ok) {
        _state.value = 'failed'
        if (res.status >= 500) _retry.schedule()
        return null
      }
      const cfg = (await res.json()) as LegalConfig
      _config.value = cfg
      _state.value = 'loaded'
      _retry.cancel()
      return cfg
    } catch {
      // no answer at all (or an answer that was not JSON): read again
      _state.value = 'failed'
      _retry.schedule()
      return null
    } finally {
      _inflight = null
    }
  })()
  return _inflight
}

export function useLegalConfig() {
  // a failed read is asked again by the next user too (a page opened after the registry came back)
  if (_state.value === 'idle' || _state.value === 'failed') void loadLegalConfig()
  return { config: readonly(_config), state: readonly(_state), reload: () => loadLegalConfig(true) }
}

/** What a placeholder becomes when the facts are not there: a visible, honest gap, never someone else's detail. */
export const UNRESOLVED = '[provider details unavailable]'

/** The map from the tokens the suite carries to the provider facts. Pure, so it can be tested. */
export function providerTokens(facts: ProviderFacts | null | undefined): Record<string, string> {
  const f = facts
  const v = (x: string | null | undefined) => (x && x.trim() ? x.trim() : UNRESOLVED)
  const editorial = f?.editorial_person || f?.legal_name || null
  const addressLines = f && f.street && f.postal_code && f.city && f.country
    ? [f.street, `${f.postal_code} ${f.city}`, f.country].join('\n') : null
  const phone = f?.phone && f.phone.trim() ? f.phone.trim() : null
  return {
    PROVIDER_FULL: v(f?.full_line),
    PROVIDER_NAME: v(f?.legal_name),
    PROVIDER_ADDRESS_LINE: v(f?.address_line),
    PROVIDER_ADDRESS_BLOCK: v(f?.address_block),
    EDITORIAL_ADDRESS_BLOCK: editorial && addressLines ? `${editorial}\n${addressLines}` : UNRESOLVED,
    PROVIDER_LEGAL_FORM: v(f?.legal_form),
    PROVIDER_TRADING_AS: v(f?.trading_as),
    EDITORIAL_PERSON: v(editorial),
    LEGAL_EMAIL: v(f?.legal_email),
    PRIVACY_EMAIL: v(f?.privacy_email || f?.legal_email),
    SECURITY_EMAIL: v(f?.security_email || f?.legal_email),
    SUPERVISORY_AUTHORITY: v(f?.supervisory_authority),
    VENUE: v(f?.venue),
    BUSINESS_DAYS: v(f?.business_days),
    GOVERNING_LAW: v(f?.governing_law),
    JURISDICTION: v(f?.country),
    // §COOKIES (2026-10-02): the imprint's second direct channel beside the email (§ 5 (1) no. 2 DDG). The one optional
    // fact: no phone is an absent line, never the visible gap above, and never a number the frame did not publish.
    IMPRINT_PHONE_LINE: phone ? `\nTelefon: ${phone}` : '',
    IMPRINT_PHONE_EN: phone ? `, phone ${phone}` : '',
  }
}

const TOKEN_RE = /\{([A-Z_]+)\}/g

/** Resolve every placeholder in a legal text. Unknown tokens are left untouched so a typo stays visible. */
export function resolveLegalTokens(text: string, tokens: Record<string, string>, localUnit: string): string {
  if (!text) return text
  return text.replace(TOKEN_RE, (whole, name: string) => {
    if (name === 'LOCAL_UNIT') return localUnit
    return Object.prototype.hasOwnProperty.call(tokens, name) ? tokens[name] : whole
  })
}
