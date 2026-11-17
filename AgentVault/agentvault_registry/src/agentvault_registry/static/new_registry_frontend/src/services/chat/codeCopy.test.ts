import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { COPIED_MS, codeOf, handleCopyClick } from './codeCopy'
import { renderMarkdown } from './messageText'

/** V0662 (OurChat lane): the copy button on a code block. BASE (7a2dddb62): codeCopy.ts does not exist and a code block has no
 *  button. A click anywhere in a rendered message reaches ONE listener; this finds the button from the event. */

let box: HTMLDivElement
const block = (code: string) =>
  `<div class="cm-code"><button type="button" class="cm-copy">Copy</button><pre><code>${code}</code></pre></div>`
const clickOn = (el: Element) => { const ev = new MouseEvent('click', { bubbles: true, cancelable: true }); Object.defineProperty(ev, 'target', { value: el }); return ev }

beforeEach(() => {
  vi.useFakeTimers()
  box = document.createElement('div')
  document.body.appendChild(box)
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  box.remove()
  delete (document as any).execCommand
})

function clipboard(impl: (t: string) => Promise<void> = async () => {}) {
  const writeText = vi.fn(impl)
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  return writeText
}

describe('the code a button belongs to', () => {
  it('is the text of its own block, decoded', () => {
    box.innerHTML = block('a &lt; b &amp;&amp; c\n')
    expect(codeOf(box.querySelector('.cm-copy')!)).toBe('a < b && c\n')
  })

  it('is the block\'s own and not another\'s when a message has two', () => {
    box.innerHTML = block('first\n') + block('second\n')
    const buttons = box.querySelectorAll('.cm-copy')
    expect(codeOf(buttons[0])).toBe('first\n')
    expect(codeOf(buttons[1])).toBe('second\n')
  })

  it('is empty for a button outside any block', () => {
    box.innerHTML = '<button class="cm-copy">Copy</button>'
    expect(codeOf(box.querySelector('.cm-copy')!)).toBe('')
  })
})

describe('a click on a copy button', () => {
  it('puts the block\'s code on the clipboard and says Copied', async () => {
    const write = clipboard()
    box.innerHTML = block('make test\n')
    const btn = box.querySelector('.cm-copy') as HTMLElement
    const ev = clickOn(btn)
    expect(await handleCopyClick(ev, 'Copied', 'Copy failed')).toBe(true)
    expect(write).toHaveBeenCalledWith('make test\n')
    expect(btn.textContent).toBe('Copied')
    expect(btn.dataset.state).toBe('copied')
    expect(ev.defaultPrevented).toBe(true)
  })

  it('goes back to its own label after the moment', async () => {
    clipboard()
    box.innerHTML = block('x')
    const btn = box.querySelector('.cm-copy') as HTMLElement
    await handleCopyClick(clickOn(btn), 'Copied', 'Copy failed')
    vi.advanceTimersByTime(COPIED_MS - 1)
    expect(btn.textContent).toBe('Copied')
    vi.advanceTimersByTime(2)
    expect(btn.textContent).toBe('Copy')
    expect(btn.dataset.state).toBeUndefined()
  })

  it('copies what a block SHOWS: the text of a rendered message, not its markup', async () => {
    const write = clipboard()
    box.innerHTML = renderMarkdown('```html\n<b>hi</b> & "bye"\n```', { copyLabel: 'Copy' })
    await handleCopyClick(clickOn(box.querySelector('.cm-copy')!), 'Copied', 'Copy failed')
    expect(write).toHaveBeenCalledWith('<b>hi</b> & "bye"\n')
  })

  it('a second click inside the moment does not make "Copied" the label to go back to', async () => {
    clipboard()
    box.innerHTML = block('x')
    const btn = box.querySelector('.cm-copy') as HTMLElement
    await handleCopyClick(clickOn(btn), 'Copied', 'Copy failed')
    vi.advanceTimersByTime(500)
    await handleCopyClick(clickOn(btn), 'Copied', 'Copy failed')
    vi.advanceTimersByTime(COPIED_MS + 5)
    expect(btn.textContent).toBe('Copy')
  })

  it('a second click restarts the moment rather than being cut short by the first', async () => {
    clipboard()
    box.innerHTML = block('x')
    const btn = box.querySelector('.cm-copy') as HTMLElement
    await handleCopyClick(clickOn(btn), 'Copied', 'Copy failed')
    vi.advanceTimersByTime(1000)
    await handleCopyClick(clickOn(btn), 'Copied', 'Copy failed')
    vi.advanceTimersByTime(1000)                          // 2 s after the first click, 1 s after the second
    expect(btn.textContent).toBe('Copied')
  })

  it('also works when the click lands on something inside the button', async () => {
    const write = clipboard()
    box.innerHTML = block('inner\n').replace('>Copy<', '><span class="glyph">Copy</span><')
    await handleCopyClick(clickOn(box.querySelector('.glyph')!), 'Copied', 'Copy failed')
    expect(write).toHaveBeenCalledWith('inner\n')
  })
})

describe('a click that is not on a copy button', () => {
  it('is left alone: no clipboard, no label change, not prevented', async () => {
    const write = clipboard()
    box.innerHTML = block('x') + '<p class="text">words</p>'
    const ev = clickOn(box.querySelector('.text')!)
    expect(await handleCopyClick(ev, 'Copied', 'Copy failed')).toBe(false)
    expect(write).not.toHaveBeenCalled()
    expect(ev.defaultPrevented).toBe(false)
    expect(box.querySelector('.cm-copy')!.textContent).toBe('Copy')
  })

  it('takes a click with no target as none', async () => {
    const ev = new MouseEvent('click', { bubbles: true })
    expect(await handleCopyClick(ev, 'Copied', 'Copy failed')).toBe(false)
  })
})

describe('when the clipboard API is not there or refuses', () => {
  it('falls back to a hidden field and execCommand, and cleans the field up', async () => {
    vi.stubGlobal('navigator', {})                         // no clipboard API (an insecure origin)
    const exec = vi.fn(() => true)
    ;(document as any).execCommand = exec
    box.innerHTML = block('old way\n')
    const btn = box.querySelector('.cm-copy') as HTMLElement
    await handleCopyClick(clickOn(btn), 'Copied', 'Copy failed')
    expect(exec).toHaveBeenCalledWith('copy')
    expect(btn.textContent).toBe('Copied')
    expect(document.querySelectorAll('textarea[readonly]').length).toBe(0)
  })

  it('falls back when the API refuses', async () => {
    clipboard(async () => { throw new Error('not allowed') })
    const exec = vi.fn(() => true)
    ;(document as any).execCommand = exec
    box.innerHTML = block('x')
    await handleCopyClick(clickOn(box.querySelector('.cm-copy')!), 'Copied', 'Copy failed')
    expect(exec).toHaveBeenCalled()
  })

  it('says it failed when nothing could copy, and still goes back after the moment', async () => {
    clipboard(async () => { throw new Error('no') })
    ;(document as any).execCommand = vi.fn(() => false)
    box.innerHTML = block('x')
    const btn = box.querySelector('.cm-copy') as HTMLElement
    await handleCopyClick(clickOn(btn), 'Copied', 'Copy failed')
    expect(btn.textContent).toBe('Copy failed')
    expect(btn.dataset.state).toBe('failed')
    vi.advanceTimersByTime(COPIED_MS + 5)
    expect(btn.textContent).toBe('Copy')
  })

  it('says it failed when even the old way throws', async () => {
    vi.stubGlobal('navigator', {})
    ;(document as any).execCommand = vi.fn(() => { throw new Error('gone') })
    box.innerHTML = block('x')
    const btn = box.querySelector('.cm-copy') as HTMLElement
    await handleCopyClick(clickOn(btn), 'Copied', 'Copy failed')
    expect(btn.textContent).toBe('Copy failed')
  })
})
