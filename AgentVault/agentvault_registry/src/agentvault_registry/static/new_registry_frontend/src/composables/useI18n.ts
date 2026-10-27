/**
 * Simple i18n composable that avoids vue-i18n composition API issues
 */

import { computed } from 'vue'
import { i18n, setLocale, getLocale, SUPPORTED_LOCALES, formatDate, formatNumber, formatCurrency } from '@/i18n'
import type { SupportedLocale } from '@/i18n'

function interpolate(template: string, params: Record<string, any>): string {
  return template.replace(/\{(\w+)\}/g, (_, key) =>
    key in params ? String(params[key]) : `{${key}}`
  )
}

export function useI18n() {
  // Use the global $t function from legacy mode
  const t = (key: string, paramsOrFallback?: Record<string, any> | string) => {
    const params = typeof paramsOrFallback === 'object' ? paramsOrFallback : undefined
    const fallback = typeof paramsOrFallback === 'string' ? paramsOrFallback : undefined

    try {
      // Access the global t function directly
      const globalT = (i18n.global as any).t
      if (globalT && typeof globalT === 'function') {
        const result = params ? globalT(key, params) : globalT(key)
        if (result && result !== key) {
          return result
        }
      }
    } catch (e) {
      // Silently handle errors
    }

    // Fallback to direct message lookup
    try {
      const locale = getLocale()
      const messages = (i18n.global as any).messages?.[locale] || (i18n.global as any).messages?.en
      const keys = key.split('.')
      let value: any = messages

      for (const k of keys) {
        if (value && typeof value === 'object' && k in value) {
          value = value[k]
        } else {
          return fallback || key
        }
      }

      if (typeof value === 'string') {
        return params ? interpolate(value, params) : value
      }
      return fallback || key
    } catch (e) {
      return fallback || key
    }
  }

  // §POCKETI18N (2026-08-23) — the SAFE parameterized form.
  //
  // The legacy t() above takes EITHER a params object OR a string fallback,
  // never both: t(key, 'text with {n}', {n}) silently returns the fallback
  // VERBATIM, putting a literal "{n}" on screen (§BRIDGE R6 shipped exactly
  // that), and t(key, {n}) with the key missing returns the RAW KEY.
  //
  // tp() closes both holes: it resolves the template through the two-argument
  // form (so a missing key falls back to real English, never a key), then
  // interpolates in JS. Word order therefore stays the locale's own — which a
  // hand-concatenated "prefix + number + suffix" cannot promise.
  // ⚠ Resolution and interpolation must happen in the SAME pass. When the key
  // exists in a bundle, vue-i18n COMPILES the message and renders `{slot}` as
  // empty unless the params ride through t() itself — so the old shape
  // `interpolate(t(key, fallback), params)` returned number-less strings the
  // moment translations landed ("Posted — escrowed." with no amount, measured
  // 2026-08-23). Bundle hit: vue-i18n interpolates. Miss: JS interpolates the
  // English fallback. Never both, never neither.
  const tp = (key: string, fallback: string, params: Record<string, any>): string =>
    te(key) ? t(key, params) : interpolate(fallback, params)

  // §pass15 (2026-05-15) — Translation-exists check. Walks the message tree
  // for the active locale and returns true when the key resolves to a string.
  // Mirrors vue-i18n's te(). Used by InfoTooltip to decide whether to fall
  // back to the registry's shortHint when an i18n key is missing.
  const te = (key: string): boolean => {
    try {
      const locale = getLocale()
      const messages = (i18n.global as any).messages?.[locale] || (i18n.global as any).messages?.en
      const keys = key.split('.')
      let value: any = messages
      for (const k of keys) {
        if (value && typeof value === 'object' && k in value) {
          value = value[k]
        } else {
          return false
        }
      }
      return typeof value === 'string' && value.length > 0
    } catch {
      return false
    }
  }

  // Current locale
  const locale = computed({
    get: () => getLocale(),
    set: (value: SupportedLocale) => setLocale(value)
  })

  // Available locales
  const availableLocales = computed(() => SUPPORTED_LOCALES)

  return {
    t,
    tp,
    te,
    translate: t,
    locale,
    availableLocales,
    formatDate,
    formatNumber,
    formatCurrency,
    setLocale,
    getLocale
  }
}
