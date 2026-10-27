/**
 * §FEFRAME W4 (V0507) — a value interpolated into a translation that is rendered with `v-html` is HTML: an agent name,
 * a bearer's name or an email hint containing `<img onerror=…>` would run. These sites escape their PARAMETERS (the
 * message's own markup still renders); a global vue-i18n `escapeParameter` would also show `&amp;` in every plain-text
 * use of a name with an ampersand, so the escape lives where the HTML is.
 */
export function escapeHtml(v: unknown): string {
  return String(v ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
