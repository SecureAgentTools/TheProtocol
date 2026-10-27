import { createI18n } from 'vue-i18n'
import en from './locales/en.json'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('i18n')

// Type for our messages
export type MessageSchema = typeof en

// §POCKETI18N — the list lives in ./locales (side-effect-free) so
// bootLocale.ts can validate a ?lang= override BEFORE this module resolves
// its initial locale at import time. Re-exported here for every importer.
import { SUPPORTED_LOCALES, type SupportedLocale } from './locales'
export { SUPPORTED_LOCALES }
export type { SupportedLocale }

// Lazy loaders for the non-default locales. Each is a dynamic import() so the
// (large) locale JSON lands in its OWN chunk, fetched only when that locale is
// actually selected. English is bundled statically so first paint is instant.
// (Previously all 8 locales were eagerly imported into the entry chunk, adding
// ~2.5MB raw / ~0.8MB gz to EVERY initial page load.)
const localeLoaders: Record<Exclude<SupportedLocale, 'en'>, () => Promise<any>> = {
  de: () => import('./locales/de.json'),
  es: () => import('./locales/es.json'),
  fr: () => import('./locales/fr.json'),
  pt: () => import('./locales/pt.json'),
  zh: () => import('./locales/zh.json'),
  ja: () => import('./locales/ja.json'),
  ko: () => import('./locales/ko.json'),
  ru: () => import('./locales/ru.json'),
}

const loadedLocales = new Set<SupportedLocale>(['en'])

// Get browser language
export function getBrowserLocale(): SupportedLocale {
  const browserLang = navigator.language.split('-')[0]
  return browserLang in SUPPORTED_LOCALES ? browserLang as SupportedLocale : 'en'
}

// Get saved locale from localStorage
function getSavedLocale(): SupportedLocale | null {
  try {
    const saved = localStorage.getItem('locale')
    if (saved && saved in SUPPORTED_LOCALES) {
      return saved as SupportedLocale
    }
  } catch (e) {
    log.warn('localStorage not available:', e)
  }
  return null
}

// Resolve initial locale: saved → browser → fallback ('en').
function resolveInitialLocale(): SupportedLocale {
  return getSavedLocale() || getBrowserLocale() || 'en'
}

const initialLocale = resolveInitialLocale()

// Sync <html lang> immediately so SEO crawlers + a11y readers pick it up
// before any hydration. localStorage already has the saved value.
if (typeof document !== 'undefined') {
  try {
    document.documentElement.lang = initialLocale
  } catch (e) { /* expected in non-browser envs */ }
}

// Create the i18n instance. Only English is bundled up front; other locales
// are injected on demand via setLocaleMessage() in ensureMessages(). The
// instance starts in 'en' and is switched to initialLocale by bootstrapI18n()
// (awaited in main.ts) BEFORE mount, so non-English users never flash English.
export const i18n = createI18n({
  legacy: true,
  locale: 'en',
  fallbackLocale: 'en',
  messages: { en }
})

// dayjs relative-time locales: English is bundled; the rest lazy-load alongside
// their message bundle so "X ago" strings localize without bloating the entry.
import dayjs from 'dayjs'
import 'dayjs/locale/en'

const DAYJS_LOCALE_MAP: Record<SupportedLocale, string> = {
  en: 'en', de: 'de', es: 'es', fr: 'fr', pt: 'pt',
  zh: 'zh-cn', ja: 'ja', ko: 'ko', ru: 'ru',
}
const dayjsLoaders: Record<Exclude<SupportedLocale, 'en'>, () => Promise<unknown>> = {
  de: () => import('dayjs/locale/de'),
  es: () => import('dayjs/locale/es'),
  fr: () => import('dayjs/locale/fr'),
  pt: () => import('dayjs/locale/pt'),
  zh: () => import('dayjs/locale/zh-cn'),
  ja: () => import('dayjs/locale/ja'),
  ko: () => import('dayjs/locale/ko'),
  ru: () => import('dayjs/locale/ru'),
}

async function applyDayjsLocale(locale: SupportedLocale) {
  try {
    if (locale !== 'en' && dayjsLoaders[locale as Exclude<SupportedLocale, 'en'>]) {
      await dayjsLoaders[locale as Exclude<SupportedLocale, 'en'>]()
    }
    dayjs.locale(DAYJS_LOCALE_MAP[locale] || 'en')
  } catch (e) {
    // non-fatal — relative-time strings will fall back to en
    console.warn('dayjs locale switch failed:', e)
  }
}

// Ensure a locale's message bundle is loaded into the i18n instance.
async function ensureMessages(locale: SupportedLocale): Promise<void> {
  if (loadedLocales.has(locale)) return
  const loader = localeLoaders[locale as Exclude<SupportedLocale, 'en'>]
  if (!loader) return
  try {
    const mod: any = await loader()
    ;(i18n.global as any).setLocaleMessage(locale, mod.default || mod)
    loadedLocales.add(locale)
  } catch (e) {
    log.warn(`failed to load locale "${locale}"; staying on fallback`, e)
  }
}

// Load the initial locale's messages + dayjs locale BEFORE the app mounts, so a
// non-English user doesn't see a flash of English on first paint. Awaited from
// main.ts. Fast no-op for English.
export async function bootstrapI18n(): Promise<void> {
  if (initialLocale !== 'en') {
    await ensureMessages(initialLocale)
    ;(i18n.global as any).locale = initialLocale
  }
  await applyDayjsLocale(initialLocale)
}

// Switch locale at runtime: load its bundle on demand, then apply. Async, but
// safe to call fire-and-forget (the UI updates reactively once messages land).
export async function setLocale(locale: SupportedLocale): Promise<void> {
  try {
    await ensureMessages(locale)
    ;(i18n.global as any).locale = locale
    localStorage.setItem('locale', locale)
    document.documentElement.lang = locale
    await applyDayjsLocale(locale)
  } catch (e) {
    console.error('Error setting locale:', e)
  }
}

export function getLocale(): SupportedLocale {
  try {
    return (i18n.global as any).locale || 'en'
  } catch (e) {
    console.error('Error getting locale:', e)
    return 'en'
  }
}

// Date formatting helper
export function formatDate(date: Date | string, format: 'short' | 'long' = 'short'): string {
  const d = typeof date === 'string' ? new Date(date) : date
  const locale = getLocale()

  const options: Intl.DateTimeFormatOptions = format === 'short'
    ? { year: 'numeric', month: 'short', day: 'numeric' }
    : { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' }

  return new Intl.DateTimeFormat(locale, options).format(d)
}

// Number formatting helper
export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  const locale = getLocale()
  return new Intl.NumberFormat(locale, options).format(value)
}

// Currency formatting helper
export function formatCurrency(value: number, currency = 'USD'): string {
  const locale = getLocale()
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency
  }).format(value)
}

// Export default
export default i18n
