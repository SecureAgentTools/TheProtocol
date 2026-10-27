// Simple date formatting utilities.
//
// 2026-05-14 §26: All relative-time formatting now goes through dayjs so it
// honors the locale set globally in src/i18n/index.ts. dayjs locale auto-
// switches when setLocale() is called.
import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'

dayjs.extend(relativeTime)

export function formatDate(date: string | Date): string {
  const lang = (typeof document !== 'undefined' && document.documentElement.lang) || 'en'
  return new Date(date).toLocaleDateString(lang, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function formatDateTime(date: string | Date): string {
  const lang = (typeof document !== 'undefined' && document.documentElement.lang) || 'en'
  return new Date(date).toLocaleString(lang, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function formatRelativeTime(date: string | Date | null | undefined): string {
  if (!date) return '—'
  return dayjs(date).fromNow()
}
