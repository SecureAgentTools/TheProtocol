/**
 * V0662 (OurChat lane): the copy button on a code block.
 *
 * `renderMarkdown(body, { copyLabel })` (messageText.ts) wraps a code block with a `.cm-copy` button; this is what a click on
 * it does: take the block's code and put it on the clipboard, then say so on the button for a moment. The HTML is the
 * renderer's, sanitized, and carries no handler (it cannot: no attribute but a class and a type is allowed through), so the
 * click is caught by ONE listener on the element that holds the rendered message, and this finds the button from the event.
 *
 * What is copied is the code's TEXT (`textContent`: `<` is `<`, not `&lt;`), exactly what the block shows.
 */

/** How long the button says "Copied" before it goes back to its own label. */
export const COPIED_MS = 1500

const timers = new WeakMap<Element, ReturnType<typeof setTimeout>>()

/** The code of the block a copy button belongs to. */
export function codeOf(button: Element): string {
  return button.closest('.cm-code')?.querySelector('pre code')?.textContent ?? ''
}

/** The clipboard API when the page has it (a secure origin), else the old way: a hidden field selected and copied. */
/** Put a text on the clipboard (the API where the page has it, else the old way); whether it worked. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch { /* refused (no permission, not focused): try the old way */ }
  try {
    const field = document.createElement('textarea')
    field.value = text
    field.setAttribute('readonly', '')
    field.style.position = 'fixed'
    field.style.opacity = '0'
    document.body.appendChild(field)
    field.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(field)
    return !!ok
  } catch { return false }
}

/**
 * Handle a click on a rendered message. A click that did not land on a copy button is none of this function's business
 * (false, nothing touched); one that did copies that block's code and shows `copiedLabel` (or `failedLabel`) on the button
 * for COPIED_MS. Returns true when the click was a copy click.
 */
export async function handleCopyClick(e: Event, copiedLabel: string, failedLabel: string): Promise<boolean> {
  const target = e.target as Element | null
  const button = (target && typeof target.closest === 'function' ? target.closest('.cm-copy') : null) as HTMLElement | null
  if (!button) return false
  e.preventDefault()
  // the label it was rendered with, kept on the first click so a second click inside the window does not "restore" Copied
  const label = button.dataset.label ?? button.textContent ?? ''
  button.dataset.label = label
  const ok = await copyText(codeOf(button))
  button.textContent = ok ? copiedLabel : failedLabel
  button.dataset.state = ok ? 'copied' : 'failed'
  const pending = timers.get(button)
  if (pending) clearTimeout(pending)
  timers.set(button, setTimeout(() => {
    button.textContent = label
    delete button.dataset.state
    timers.delete(button)
  }, COPIED_MS))
  return true
}
