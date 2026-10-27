/**
 * §COCKPITDESK (2026-10-14) — the frame every desk pane lives in, state by state.
 *
 * The law this adds (PaneShell law 4): a failed RE-read is not the end of the last answer. A pane that says when its source
 * last answered (`readAt`) keeps what it shows when a newer read fails, and the line above it says the time of those
 * figures, why the newest read failed, and offers Try again. A pane that never read keeps the error state, now with Try
 * again when it hands the shell its `reload` (awaited, so the door re-arms whatever the read answers); its freshness chip
 * reads again on a press. The older precedence stays: unavailable, then the first read, then a failure with nothing to
 * show, then empty, then the pane's own content.
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PaneShell from './PaneShell.vue'
import { refreshDesk } from '@/services/cockpit/deskRefresh'

const CONTENT = '<p data-testid="rows">the pane\'s rows</p>'
const READ_AT = Date.UTC(2026, 9, 14, 20, 41, 7)

function shell(props: Record<string, unknown>) {
  return mount(PaneShell, {
    props: { title: 'Earnings', icon: 'mdi:cash-multiple', refreshMode: 'poll', pollSeconds: 30, ...props },
    slots: { default: CONTENT },
  })
}

/** A reload whose answer the test releases, so "Reading…" can be seen while it is out. */
function heldReload() {
  let release: () => void = () => {}
  const fn = vi.fn(() => new Promise<void>((r) => { release = r }))
  return { fn, release: () => release() }
}

describe('a pane that never read', () => {
  it('shows the failure with Try again, says it is reading while the read is out, and re-arms after', async () => {
    const r = heldReload()
    const w = shell({ error: 'Request failed with status code 502', reload: r.fn })
    expect(w.find('[data-testid="ckd-error"]').exists()).toBe(true)
    expect(w.find('[data-testid="rows"]').exists(), 'no rows under a failure with nothing to show').toBe(false)
    const btn = w.find('[data-testid="ckd-retry"]')
    expect(btn.text()).toMatch(/try again/i)
    await btn.trigger('click')
    expect(r.fn).toHaveBeenCalledTimes(1)
    expect(w.find('[data-testid="ckd-retry"]').attributes('disabled'), 'a second press waits for the answer').toBeDefined()
    expect(w.find('[data-testid="ckd-retry"]').text()).toMatch(/reading/i)
    await w.find('[data-testid="ckd-retry"]').trigger('click')
    expect(r.fn, 'a press while reading sends nothing more').toHaveBeenCalledTimes(1)
    r.release(); await flushPromises()
    expect(w.find('[data-testid="ckd-retry"]').text(), 'the same failure again still re-arms the door').toMatch(/try again/i)
    expect(w.find('[data-testid="ckd-retry"]').attributes('disabled')).toBeUndefined()
  })

  it('re-arms the door when the read throws', async () => {
    const reload = vi.fn(async () => { throw new Error('boom') })
    const w = shell({ error: 'x', reload })
    await w.find('[data-testid="ckd-retry"]').trigger('click'); await flushPromises()
    expect(reload).toHaveBeenCalledTimes(1)
    expect(w.find('[data-testid="ckd-retry"]').text()).toMatch(/try again/i)
  })

  it('offers no door when it cannot reload', () => {
    const w = shell({ error: 'unreachable' })
    expect(w.find('[data-testid="ckd-error"]').exists()).toBe(true)
    expect(w.find('[data-testid="ckd-retry"]').exists()).toBe(false)
    expect(w.find('button[data-testid="ckd-fresh"]').exists(), 'the chip is not a button either').toBe(false)
  })
})

describe('a pane whose newest read failed after one that answered', () => {
  it('keeps its rows and says when they were read and why the newest read failed', async () => {
    const reload = vi.fn(async () => {})
    const w = shell({ error: 'Request failed with status code 502', readAt: READ_AT, reload })
    expect(w.find('[data-testid="ckd-error"]').exists(), 'not the failure state').toBe(false)
    expect(w.find('[data-testid="rows"]').exists(), 'the rows stay').toBe(true)
    const line = w.find('[data-testid="ckd-stale"]')
    expect(line.exists()).toBe(true)
    expect(line.text()).toContain('502')
    expect(line.text(), 'the time of the figures').toMatch(/\d{1,2}:\d{2}:\d{2}/)
    await line.find('[data-testid="ckd-retry"]').trigger('click')
    expect(reload).toHaveBeenCalledTimes(1)
    await w.setProps({ error: '', readAt: READ_AT + 30_000 })
    expect(w.find('[data-testid="ckd-stale"]').exists(), 'an answer clears the line').toBe(false)
    expect(w.find('[data-testid="rows"]').exists()).toBe(true)
  })

  it('keeps an honest empty answer the same way', () => {
    const w = shell({ error: 'timeout of 15000ms exceeded', readAt: READ_AT, empty: true, emptyText: 'No earnings yet.' })
    expect(w.find('[data-testid="ckd-stale"]').exists()).toBe(true)
    expect(w.find('[data-testid="ckd-empty"]').text()).toContain('No earnings yet.')
    expect(w.find('[data-testid="rows"]').exists()).toBe(false)
  })

  it('shows no stale line when the newest read answered', () => {
    const w = shell({ error: '', readAt: READ_AT })
    expect(w.find('[data-testid="ckd-stale"]').exists()).toBe(false)
    expect(w.find('[data-testid="rows"]').exists()).toBe(true)
  })
})

describe('the freshness chip', () => {
  it('reads again on a press for a polling pane that can reload, and says when its source last answered', async () => {
    const reload = vi.fn(async () => {})
    const w = shell({ readAt: READ_AT, reload })
    const chip = w.find('button[data-testid="ckd-fresh"]')
    expect(chip.text()).toBe('30s')
    expect(chip.attributes('title')).toMatch(/every 30 s/)
    expect(chip.attributes('title')).toMatch(/last answered at \d{1,2}:\d{2}:\d{2}/)
    await chip.trigger('click')
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('stays a label on a LIVE pane: there is nothing to ask for', () => {
    const w = shell({ refreshMode: 'live', reload: vi.fn() })
    expect(w.find('button[data-testid="ckd-fresh"]').exists()).toBe(false)
    expect(w.find('[data-testid="ckd-fresh"]').text()).toBe('LIVE')
  })

  it('turns amber while the figures are stale', () => {
    const w = shell({ error: '502', readAt: READ_AT })
    expect(w.find('[data-testid="ckd-fresh"]').classes()).toContain('is-stale')
  })
})

describe('the older precedence', () => {
  it('puts unavailable before everything, then the first read', () => {
    const u = shell({ unavailable: true, unavailableReason: 'no stream here', loading: true, error: 'x', readAt: READ_AT })
    expect(u.find('[data-testid="ckd-unavailable"]').exists()).toBe(true)
    expect(u.find('[data-testid="ckd-stale"]').exists()).toBe(false)
    const l = shell({ loading: true, error: 'x' })
    expect(l.find('[data-testid="ckd-loading"]').exists()).toBe(true)
    expect(l.find('[data-testid="ckd-error"]').exists()).toBe(false)
  })
})

describe("the host's Refresh", () => {
  it('reads every pane that can reload, once each, and leaves a pane already reading alone', async () => {
    const a = vi.fn(async () => {})
    const held = heldReload()
    const wa = shell({ readAt: READ_AT, reload: a })
    const wb = shell({ readAt: READ_AT, reload: held.fn })
    const wc = shell({ refreshMode: 'live' })
    refreshDesk(); await flushPromises()
    expect(a).toHaveBeenCalledTimes(1)
    expect(held.fn).toHaveBeenCalledTimes(1)
    refreshDesk(); await flushPromises()
    expect(a, 'a settled pane reads again').toHaveBeenCalledTimes(2)
    expect(held.fn, 'a pane still reading is not asked twice').toHaveBeenCalledTimes(1)
    held.release(); await flushPromises()
    expect(wc.find('[data-testid="ckd-fresh"]').text()).toBe('LIVE')
    wa.unmount(); wb.unmount(); wc.unmount()
    refreshDesk(); await flushPromises()
    expect(a, 'a pane that is gone is not asked').toHaveBeenCalledTimes(2)
  })
})
