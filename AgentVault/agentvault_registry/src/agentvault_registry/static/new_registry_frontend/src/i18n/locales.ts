/**
 * §POCKETI18N — the supported-locale list, side-effect-free on purpose.
 *
 * bootLocale.ts must validate a ?lang= override BEFORE the i18n module runs
 * (i18n/index.ts resolves its initial locale at import time), so the list
 * cannot live in a module that boots i18n. This file is the ONE source of
 * truth; i18n/index.ts re-exports it for every existing importer.
 *
 * Values are ENDONYMS deliberately: a language picker is the one control
 * that must stay legible when the interface language is wrong.
 */
export const SUPPORTED_LOCALES = {
  en: 'English',
  de: 'Deutsch',
  es: 'Español',
  fr: 'Français',
  pt: 'Português (Brasil)',
  zh: '中文 (简体)',
  ja: '日本語',
  ko: '한국어',
  ru: 'Русский'
} as const

export type SupportedLocale = keyof typeof SUPPORTED_LOCALES
