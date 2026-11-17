// A translate function for the pure helpers (flow.ts, codeChangeView.ts): the console's legacy t() takes EITHER params OR a fallback, never both, and a text with
// {n} comes back with the braces; tp() takes both. This one picks the right one, so a helper can always call tr(key, fallback, params).
import { useI18n } from '@/composables/useI18n'

export type Tr = (key: string, fallback: string, params?: Record<string, unknown>) => string
export function useTr(): Tr {
  const { t, tp } = useI18n()
  return ((key: string, fallback: string, params?: Record<string, unknown>) => (params ? tp(key, fallback, params as any) : t(key, fallback))) as Tr
}
