/**
 * §COCKPITDESK (2026-10-15) — Escape closes the topmost open dialog, wherever the focus is.
 *
 * An `@keydown.esc` on a dialog's overlay only hears an Escape pressed while the focus is INSIDE the overlay; a dialog
 * opened by a button keeps the focus on that button, outside the teleported overlay, so the Escape a person presses
 * reaches nothing (found by the views walk on /disputes "File a dispute"; the same shape sits on about 35 overlays).
 * This listens on the document while the dialog is open, and only the most recently opened dialog answers, so an
 * Escape over a confirm closes the confirm and not the form under it. An Escape another handler already used
 * (defaultPrevented) is left alone, BaseModal's rule; `when` lets a dialog refuse it (a request in flight, a one-time
 * secret on screen).
 */
import { onBeforeUnmount, watch, type Ref } from 'vue'

interface Entry { close: () => void; when: () => boolean; el?: () => Element | null | undefined }

const stack: Entry[] = []
let bound = false

function onKey(e: KeyboardEvent): void {
  if (e.key !== 'Escape' || e.defaultPrevented) return
  const top = stack[stack.length - 1]
  if (!top) return
  // A dialog this stack does not know (role=dialog, aria-modal) that holds the focus owns the press: BaseModal's rule. It
  // can be told only for a dialog that names its element; one that does not keeps the press, as before.
  const topEl = top.el?.()
  if (topEl) {
    const at = document.activeElement
    const over = at && at !== document.body ? at.closest('[aria-modal="true"]') : null
    if (over && over !== topEl && !topEl.contains(over)) return
  }
  e.preventDefault()
  if (top.when()) top.close()
}

function sync(): void {
  if (stack.length && !bound) { document.addEventListener('keydown', onKey); bound = true }
  if (!stack.length && bound) { document.removeEventListener('keydown', onKey); bound = false }
}

export function useEscapeClose(open: Ref<boolean> | (() => boolean), close: () => void, when: () => boolean = () => true,
                               el?: () => Element | null | undefined): void {
  const entry: Entry = { close, when, el }
  const isOpen = typeof open === 'function' ? open : () => open.value
  const remove = () => { const i = stack.indexOf(entry); if (i >= 0) stack.splice(i, 1); sync() }
  watch(isOpen, (v) => {
    if (v) { if (!stack.includes(entry)) stack.push(entry) } else remove()
    sync()
  }, { immediate: true })
  onBeforeUnmount(remove)
}

/** For tests: how many dialogs are listening. */
export function escapeStackDepth(): number { return stack.length }
