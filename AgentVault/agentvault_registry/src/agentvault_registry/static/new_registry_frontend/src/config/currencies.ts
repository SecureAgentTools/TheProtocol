import { appLocale } from '@/services/appLocale'
// Currency presentation — multi-currency, DERIVED (§FEFRAME W2).
//
// Currency codes are OPAQUE strings. Before W2 a seed named three currencies of the retired frames (AVT / BVT / JDAY)
// and every other code (ECU, ACU, SBXA, SBXB: every currency that exists today) rendered as a grey `¤`. Now:
//   - the NAME comes from the server: the frame manifest names each frame's currency (`currency_name`), registered
//     here when the manifest arrives (composables/useFrameManifest.ts); until then the code is its own name;
//   - the GLYPH and ACCENT are derived from the code itself (a stable hash), so a new frame's currency is
//     recognisable and distinct on first sight, with no release to add it.
// Glyphs: ◎ liquid / ◉ staked are the legacy balance glyphs used across the app; the headline `glyph` is the
// per-currency mark for badges.

export type CurrencyCode = string

export interface CurrencyDescriptor {
  code: CurrencyCode
  /** Headline mark for badges / chips. */
  glyph: string
  /** Liquid-balance glyph (legacy ◎). */
  liquidGlyph: string
  /** Staked-balance glyph (legacy ◉). */
  stakedGlyph: string
  name: string
  /** CSS colour for badge tints. */
  accent: string
  /** Default decimal places for exact display. */
  decimals: number
}

const _names = new Map<string, string>()

/** Names from the frame manifest (code -> name). A later registration for the same code is ignored. */
export function registerCurrencyNames(names: Record<string, string>): void {
  for (const [code, name] of Object.entries(names || {})) {
    const c = String(code || '').trim().toUpperCase()
    const n = String(name || '').trim()
    if (c && n && !_names.has(c)) _names.set(c, n)
  }
}

const GLYPHS = ['◆', '◈', '◇', '⬢', '⬡', '◭']

/** FNV-1a over the code: stable across sessions and consoles, so a currency keeps its colour everywhere. */
function hash(code: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < code.length; i++) {
    h ^= code.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h >>> 0
}

/** The presentation of any code: its name from the manifest (else the code), a derived glyph and accent. An empty
 *  code (identity not yet known) renders as nothing. Never throws. */
export function unknownCurrency(code: CurrencyCode): CurrencyDescriptor {
  const c = String(code || '').trim().toUpperCase()
  if (!c) {
    return { code: '', glyph: '¤', liquidGlyph: '◎', stakedGlyph: '◉', name: '', accent: 'var(--nc-text-dim, #8a93a6)', decimals: 2 }
  }
  const h = hash(c)
  return {
    code: c,
    glyph: GLYPHS[h % GLYPHS.length],
    liquidGlyph: '◎',
    stakedGlyph: '◉',
    name: _names.get(c) || c,
    accent: `hsl(${h % 360} 72% 62%)`,
    decimals: 2,
  }
}

/** The presentation of `code`; never another frame's unit when the code is unknown. */
export function describeCurrency(code: CurrencyCode | null | undefined): CurrencyDescriptor {
  return unknownCurrency(code || '')
}

/** Pure numeric formatter (K/M/B compact or thousands-separated). No currency label. */
export function formatTokenAmount(amount: number | string | null | undefined, opts: { compact?: boolean; decimals?: number } = {}): string {
  const n = typeof amount === 'string' ? parseFloat(amount) : (amount ?? 0)
  if (!Number.isFinite(n)) return '0'
  const decimals = opts.decimals ?? 2
  if (opts.compact) {
    const abs = Math.abs(n)
    if (abs >= 1e9) return (n / 1e9).toFixed(2).replace(/\.?0+$/, '') + 'B'
    if (abs >= 1e6) return (n / 1e6).toFixed(2).replace(/\.?0+$/, '') + 'M'
    if (abs >= 1e3) return (n / 1e3).toFixed(2).replace(/\.?0+$/, '') + 'K'
  }
  return n.toLocaleString(appLocale(), { maximumFractionDigits: decimals })
}
