/**
 * A money amount a person typed (§FESUITE). `Number()` is not a parser for a money field: it reads "1e309" as
 * Infinity, "0x10" as 16 and "  " as 0, and "1,5" (one and a half on a German keyboard) as NaN without a word, while
 * `parseFloat()` reads "1abc" as 1. The rule here: digits with at most one decimal separator (a dot, or a single comma
 * when there is no dot), at most AMOUNT_PLACES places (the ledger's precision), more than zero. The answer is the
 * normalised string the server receives, or null; never a float, so nothing is rounded on the way.
 */
export const AMOUNT_PLACES = 18

export function typedAmount(raw: string | number | null | undefined): string | null {
  if (raw === null || raw === undefined) return null
  let s = String(raw).trim()
  if (!s.includes('.') && (s.match(/,/g) || []).length === 1) s = s.replace(',', '.')
  const m = s.match(/^(\d*)(?:\.(\d+))?$/)
  if (!m || (!m[1] && !m[2])) return null
  const whole = (m[1] || '0').replace(/^0+(?=\d)/, '')
  const places = m[2] || ''
  if (places.length > AMOUNT_PLACES) return null
  const text = places ? `${whole}.${places}` : whole
  const n = Number(text)
  if (!Number.isFinite(n) || n <= 0) return null
  return text
}
