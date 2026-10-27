/**
 * Copy a text to the clipboard and say whether it happened (quick onboarding, 2026-10-09).
 *
 * A screen may say "Copied" only after this resolves true. The clipboard API is asked first and AWAITED (it refuses
 * outside a secure context, without focus, or when the person's browser denies it); then the old textarea route; false
 * when neither copied. Nothing is logged: the text is often a credential.
 */
export async function copyText(text: string): Promise<boolean> {
  if (typeof text !== 'string' || text === '') return false
  try {
    const cb = typeof navigator !== 'undefined' ? navigator.clipboard : undefined
    if (cb && typeof cb.writeText === 'function') {
      await cb.writeText(text)
      return true
    }
  } catch { /* refused: try the textarea route */ }
  if (typeof document === 'undefined' || typeof document.execCommand !== 'function') return false
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.setAttribute('aria-hidden', 'true')
  ta.style.position = 'fixed'
  ta.style.top = '0'
  ta.style.left = '0'
  ta.style.opacity = '0'
  ta.style.pointerEvents = 'none'
  const before = document.activeElement as HTMLElement | null
  document.body.appendChild(ta)
  try {
    ta.select()
    return document.execCommand('copy') === true
  } catch {
    return false
  } finally {
    ta.value = ''
    document.body.removeChild(ta)
    try { before?.focus?.() } catch { /* the element left the page */ }
  }
}
