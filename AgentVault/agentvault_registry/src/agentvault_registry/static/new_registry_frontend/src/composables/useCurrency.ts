// useCurrency — the single chokepoint for rendering token amounts in the
// correct, possibly-foreign currency. Replaces the ~12 copy-pasted local
// `formatAVT` helpers and the hardcoded 'AVT'/'TEG' literals across the app.
// Strategy §11.3 / §17.1-G-ARCH-2 / §18.2.
//
// `localCurrency` is the viewer's own (AVT on Frame A/B, BVT on Frame C).
// `currencyForItem` resolves a list item's currency from its card/trust_domain.
// `isForeign*` are true only with POSITIVE evidence of a different currency
// (no false positives → no spurious "foreign" badges, no mislabels).

import { describeCurrency, formatTokenAmount, type CurrencyCode, type CurrencyDescriptor } from '@/config/currencies'
import { useFrames } from '@/composables/useFrames'

export function useCurrency() {
  const { localCurrency, currencyForTrustDomain, knownCurrencyForTrustDomain } = useFrames()

  function describe(code?: CurrencyCode | null): CurrencyDescriptor {
    return describeCurrency(code ?? localCurrency.value)
  }
  function glyphFor(code?: CurrencyCode | null): string {
    return describe(code).glyph
  }
  /** Formatted amount WITH currency code suffix, e.g. "1,234.50 BVT". */
  function format(amount: number | string | null | undefined, opts: { currency?: CurrencyCode | null; compact?: boolean; decimals?: number } = {}): string {
    const d = describeCurrency(opts.currency ?? localCurrency.value)
    const num = formatTokenAmount(amount, { compact: opts.compact, decimals: opts.decimals ?? d.decimals })
    return `${num} ${d.code}`
  }
  /** Just the formatted number (no code) — when the label/glyph is shown separately. */
  function amount(value: number | string | null | undefined, opts: { compact?: boolean; decimals?: number } = {}): string {
    return formatTokenAmount(value, opts)
  }
  /** Resolve the currency for a list item from common shapes (card → trust_domain). */
  function currencyForItem(item: unknown): CurrencyCode {
    if (!item || typeof item !== 'object') return localCurrency.value
    const o = item as Record<string, any>
    const direct = o.settlement_currency || o.currency || o.fees?.settlement_currency || o.cached_registry_card?.fees?.settlement_currency
    if (typeof direct === 'string' && direct) return direct
    return currencyForTrustDomain(o.trust_domain || o.trustDomain || o.home_trust_domain)
  }
  /** True iff `code` is positively a different currency than the viewer's. */
  function isForeign(code?: CurrencyCode | null): boolean {
    return !!code && code !== localCurrency.value
  }
  /** True iff we positively know an item's currency differs from the viewer's. */
  function isForeignItem(item: unknown): boolean {
    if (!item || typeof item !== 'object') return false
    const o = item as Record<string, any>
    const known = o.settlement_currency || o.currency || o.fees?.settlement_currency || knownCurrencyForTrustDomain(o.trust_domain || o.trustDomain || o.home_trust_domain)
    return !!known && known !== localCurrency.value
  }

  return { localCurrency, describe, glyphFor, format, amount, currencyForItem, isForeign, isForeignItem }
}
