/**
 * §FESUITE: the tutorial tracks' icons as names in the console's own icon map (components/Icon.vue). They were emoji,
 * which the console's design rule refuses: an emoji renders in the operating system's colour font, ignores the theme,
 * and is a different picture on every platform. A track's `icon` key comes from its definition in ./data; a key this
 * map does not know falls back to the book.
 */
export const TRACK_ICONS: Readonly<Record<string, string>> = {
  'user-plus': 'mdi:account-plus',
  coins: 'mdi:hand-coin-outline',
  landmark: 'mdi:bank',
  globe: 'mdi:earth',
  scale: 'mdi:scale-balance',
  shield: 'mdi:shield-half-full',
  'shield-check': 'mdi:shield-check',
  'file-signature': 'mdi:draw-pen',
  'arrow-right-left': 'mdi:swap-horizontal',
  star: 'mdi:star',
  'clipboard-check': 'mdi:clipboard-check-multiple-outline',
  crown: 'mdi:crown',
  // these three fell back to a book emoji: the old map never knew them
  'chart-line': 'mdi:chart-line',
  'office-building': 'mdi:office-building',
  'rocket-launch': 'mdi:rocket-launch',
}

export const TRACK_ICON_FALLBACK = 'mdi:book-open-variant'

export function trackIcon(key: string | null | undefined): string {
  return (key && TRACK_ICONS[key]) || TRACK_ICON_FALLBACK
}
