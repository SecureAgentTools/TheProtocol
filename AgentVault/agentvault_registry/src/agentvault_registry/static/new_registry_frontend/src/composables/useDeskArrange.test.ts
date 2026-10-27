/**
 * §COCKPITDESK (2026-10-14) — the one arrange brain both desk hosts share (the desk and Mission Control's desk area).
 *
 * What it promises: arranging works on a COPY of the source until the host saves; cancel puts the source back; heights are
 * whole row units inside the bounds; a maximised pane owns the board and Escape gives it back; a drag starts only from the
 * handle and only while arranging, and a drop MOVES the tile (the arrows swap); "Add pane" offers only what is not on the
 * board and what the host is willing to offer.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { useDeskArrange, type DeskArrange, type DeskArrangeOptions } from './useDeskArrange'
import { MAX_ROWS, MIN_ROWS, NATURAL_ROWS, ALL_PANE_IDS, type DeskLayout, type PaneId } from '@/components/cockpit/paneRegistry'

let wrapper: VueWrapper | null = null
afterEach(() => { wrapper?.unmount(); wrapper = null })

function harness(layout: DeskLayout, opts: DeskArrangeOptions = {}) {
  const source = ref<DeskLayout>(layout)
  let arrange!: DeskArrange
  const Host = defineComponent({ setup() { arrange = useDeskArrange(() => source.value, opts); return () => h('div') } })
  wrapper = mount(Host)
  return { arrange, source }
}

const base = (): DeskLayout => ({ id: 'l1', name: 'Mine', panes: ['decisions', 'stop', 'market', 'chats'], sizes: { market: 3 } })

function dragEvent() {
  let prevented = false
  const data: Record<string, string> = {}
  const e = {
    preventDefault: () => { prevented = true },
    dataTransfer: { setData: (k: string, v: string) => { data[k] = v }, effectAllowed: '', dropEffect: '' },
  } as unknown as DragEvent
  return { e, prevented: () => prevented, data }
}

describe('arranging a board', () => {
  it('works on a copy and leaves the source alone until the host saves; cancel puts the source back', () => {
    const { arrange, source } = harness(base())
    arrange.beginEdit()
    expect(arrange.editing).toBe(true)
    expect(arrange.draft).toEqual(['decisions', 'stop', 'market', 'chats'])
    arrange.addPane('ledger'); arrange.dropPane('chats'); arrange.movePane('stop', -1)
    expect(arrange.draft).toEqual(['stop', 'decisions', 'market', 'ledger'])
    expect(arrange.shown, 'the board shows the draft while arranging').toEqual(arrange.draft)
    expect(source.value.panes, 'the source is untouched').toEqual(['decisions', 'stop', 'market', 'chats'])
    arrange.cancelEdit()
    expect(arrange.editing).toBe(false)
    expect(arrange.draft).toEqual(['decisions', 'stop', 'market', 'chats'])
    expect(arrange.shown).toEqual(['decisions', 'stop', 'market', 'chats'])
  })

  it('adds a pane once, and moves only inside the board', () => {
    const { arrange } = harness(base())
    arrange.beginEdit()
    arrange.addPane('ledger'); arrange.addPane('ledger')
    expect(arrange.draft.filter(p => p === 'ledger')).toHaveLength(1)
    arrange.movePane('decisions', -1)
    expect(arrange.draft[0], 'the first pane cannot move up').toBe('decisions')
    arrange.movePane('ledger', 1)
    expect(arrange.draft[arrange.draft.length - 1], 'the last pane cannot move down').toBe('ledger')
    arrange.movePane('decisions', 1)
    expect(arrange.draft.slice(0, 2), 'the arrows swap neighbours').toEqual(['stop', 'decisions'])
    arrange.movePane('book', 1)
    expect(arrange.draft, 'a pane not on the board moves nothing').not.toContain('book')
  })

  it('keeps heights whole and inside the bounds, reads the draft while arranging and the source otherwise', () => {
    const { arrange } = harness(base())
    expect(arrange.rowsOf('market'), "the source's own height").toBe(3)
    expect(arrange.rowsOf('decisions'), 'the natural height').toBe(NATURAL_ROWS.decisions)
    arrange.beginEdit()
    for (let i = 0; i < 10; i++) arrange.resizePane('market', 1)
    expect(arrange.rowsOf('market')).toBe(MAX_ROWS)
    for (let i = 0; i < 10; i++) arrange.resizePane('market', -1)
    expect(arrange.rowsOf('market')).toBe(MIN_ROWS)
    arrange.cancelEdit()
    expect(arrange.rowsOf('market'), 'cancel drops the unsaved height').toBe(3)
  })

  it('lets a maximised pane own the board, and gives the board back on a second press or Escape', () => {
    const { arrange } = harness(base())
    arrange.toggleMax('market')
    expect(arrange.shown).toEqual(['market'])
    arrange.toggleMax('market')
    expect(arrange.shown).toHaveLength(4)
    arrange.toggleMax('chats')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(arrange.maxId).toBeNull()
    expect(arrange.shown).toHaveLength(4)
  })

  it('shows the whole board when the maximised pane is not on it', () => {
    const { arrange, source } = harness(base())
    arrange.toggleMax('chats')
    source.value = { id: 'l2', name: 'Other', panes: ['market', 'ledger'], sizes: {} }
    expect(arrange.shown).toEqual(['market', 'ledger'])
  })

  // §COCKPITDESK: the agent card opens over a maximised pane; its Escape closes the card and leaves the board as it was.
  it('leaves an Escape that a dialog over the board used or received', () => {
    const { arrange } = harness(base())
    arrange.toggleMax('market')
    const used = (e: Event) => e.preventDefault()
    document.addEventListener('keydown', used)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    document.removeEventListener('keydown', used)
    expect(arrange.maxId, 'an Escape a dialog marked as used').toBe('market')
    const over = document.createElement('div'); over.setAttribute('aria-modal', 'true')
    const inside = document.createElement('button'); over.appendChild(inside); document.body.appendChild(over)
    inside.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    over.remove()
    expect(arrange.maxId, 'an Escape pressed inside a dialog').toBe('market')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(arrange.maxId, 'a plain Escape still gives the board back').toBeNull()
  })

  it('stops listening for Escape once its host is gone', () => {
    const { arrange } = harness(base())
    arrange.toggleMax('market')
    wrapper!.unmount(); wrapper = null
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(arrange.maxId, 'a removed board still reacted to Escape').toBe('market')
  })
})

describe('dragging a tile', () => {
  it('starts only from the handle and only while arranging', () => {
    const { arrange } = harness(base())
    const outside = dragEvent()
    arrange.armDrag('market')
    arrange.onDragStart('market', outside.e)
    expect(outside.prevented(), 'a drag outside Arrange is refused').toBe(true)
    expect(arrange.dragId).toBeNull()

    arrange.beginEdit()
    const unarmed = dragEvent()
    arrange.onDragStart('market', unarmed.e)
    expect(unarmed.prevented(), 'a drag that did not start on the handle is refused').toBe(true)

    const armed = dragEvent()
    arrange.armDrag('market')
    arrange.onDragStart('market', armed.e)
    expect(armed.prevented()).toBe(false)
    expect(arrange.dragId).toBe('market')
    expect(armed.data['text/plain'], 'a payload, or Firefox refuses the drag').toBe('market')
  })

  it('moves the tile to where it is dropped, in both directions', () => {
    const { arrange } = harness(base())
    arrange.beginEdit()
    const drop = (from: PaneId, to: PaneId) => {
      arrange.armDrag(from); arrange.onDragStart(from, dragEvent().e)
      arrange.onDragOver(to, dragEvent().e)
      expect(arrange.dragOver).toBe(to)
      arrange.onDrop(to)
    }
    drop('decisions', 'chats')
    expect(arrange.draft).toEqual(['stop', 'market', 'chats', 'decisions'])
    drop('decisions', 'stop')
    expect(arrange.draft).toEqual(['decisions', 'stop', 'market', 'chats'])
    expect([arrange.dragId, arrange.dragOver, arrange.dragArmed]).toEqual([null, null, null])
  })

  it('ignores a drop on itself and a drop with nothing carried', () => {
    const { arrange } = harness(base())
    arrange.beginEdit()
    arrange.onDrop('market')
    arrange.armDrag('market'); arrange.onDragStart('market', dragEvent().e); arrange.onDrop('market')
    expect(arrange.draft).toEqual(['decisions', 'stop', 'market', 'chats'])
  })
})

describe('adding panes', () => {
  it('offers every pane not on the board, or only what the host offers', () => {
    const all = harness(base()).arrange
    all.beginEdit()
    expect(all.addable).toEqual(ALL_PANE_IDS.filter(id => !['decisions', 'stop', 'market', 'chats'].includes(id)))
    wrapper!.unmount(); wrapper = null

    const some = harness(base(), { offer: id => id !== 'ledger' }).arrange
    some.beginEdit()
    expect(some.addable).not.toContain('ledger')
    expect(some.addable).toContain('book')
  })
})
