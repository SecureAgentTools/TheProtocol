/** POCKET balance-privacy toggle (2026-07-08) — the "eye": hide amounts on demand. */
import { ref } from 'vue'

const KEY = 'pk_hide_amounts'
const hidden = ref(localStorage.getItem(KEY) === '1')

export function usePocketPrivacy() {
  function toggle() {
    hidden.value = !hidden.value
    try { localStorage.setItem(KEY, hidden.value ? '1' : '0') } catch {}
    try { (navigator as any).vibrate?.(6) } catch {}
  }
  /** Wrap a formatted amount — returns dots when privacy is on. */
  const mask = (formatted: string) => (hidden.value ? '••••••' : formatted)
  return { hidden, toggle, mask }
}
