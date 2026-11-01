import { describe, it, expect, beforeEach } from 'vitest'
import { COLUMN_KEEP_PX, NARROW_PANE_PX, SIDE_GUTTER_PX, SIDE_PANEL_MIN_PX, SIDE_PANEL_PX, chatSurfaceFor, narrowPane,
  saveSidePanelOpen, showSidePanel, sidePanelOpen } from './sidePanel'

/**
 * V0652 (ad) (order gwo_e5e9ad061d6e5be9605a3067): when an organization room's side panel shows on the console's chat,
 * and each section's fold kept per person. BASE (V0651): no panel; the column was capped at 760 px on every mount.
 */
describe('the breakpoint', () => {
  it('is the pane width that keeps the column at least as wide as V0651 drew it, beside the panel', () => {
    expect(SIDE_PANEL_MIN_PX).toBe(COLUMN_KEEP_PX + SIDE_PANEL_PX + SIDE_GUTTER_PX)
    expect(COLUMN_KEEP_PX).toBe(760)
    expect(showSidePanel(SIDE_PANEL_MIN_PX - 1, 'org', 'org1', 'desk')).toBe(false)
    expect(showSidePanel(SIDE_PANEL_MIN_PX, 'org', 'org1', 'desk')).toBe(true)
    expect(showSidePanel(1600, 'org', 'org1', 'desk')).toBe(true)
  })

  it('an organization room only, with its organization known', () => {
    for (const k of ['dm', 'support', 'agent_service', '', null, undefined]) expect(showSidePanel(1600, k, 'org1', 'desk')).toBe(false)
    expect(showSidePanel(1600, 'org', '', 'desk')).toBe(false)
    expect(showSidePanel(1600, 'org', null, 'desk')).toBe(false)
  })

  it("Pocket keeps its own layout, however wide its window", () => {
    expect(showSidePanel(2400, 'org', 'org1', 'pocket')).toBe(false)
  })

  it('a width nobody measured yet is no width', () => {
    expect(showSidePanel(0, 'org', 'org1', 'desk')).toBe(false)
    expect(showSidePanel(Number.NaN, 'org', 'org1', 'desk')).toBe(false)
  })

  it('the surface follows the mount, as useOurChatBase does', () => {
    expect(chatSurfaceFor('/ourchat')).toBe('desk')
    expect(chatSurfaceFor('/pocket/ourchat')).toBe('pocket')
    expect(chatSurfaceFor('')).toBe('desk')
  })
})

describe("the composer's narrow pane (V0652 (aj))", () => {
  it('a phone width is narrow; a pane nobody measured yet is not, nor Pocket wide or the desk', () => {
    expect(narrowPane(393)).toBe(true)
    expect(narrowPane(NARROW_PANE_PX - 1)).toBe(true)
    expect(narrowPane(NARROW_PANE_PX)).toBe(false)
    expect(narrowPane(0)).toBe(false)
    expect(narrowPane(Number.NaN)).toBe(false)
    expect(narrowPane(844)).toBe(false)
  })
})

describe("each section's fold, kept per person on this device", () => {
  beforeEach(() => { localStorage.clear() })

  it('every section opens until its person folds it', () => {
    expect(sidePanelOpen('developer:6')).toEqual({ approvals: true, board: true, live: true, present: true })
  })

  it('a fold is kept and read back, for that person only', () => {
    saveSidePanelOpen('developer:6', { approvals: true, board: true, live: true, present: false })
    expect(sidePanelOpen('developer:6').present).toBe(false)
    expect(sidePanelOpen('developer:6').approvals).toBe(true)
    expect(sidePanelOpen('developer:7').present).toBe(true)
  })

  it('a value nobody can read is no state: every section open', () => {
    localStorage.setItem('ourchat.side.v1.developer:6', '{not json')
    expect(sidePanelOpen('developer:6')).toEqual({ approvals: true, board: true, live: true, present: true })
    localStorage.setItem('ourchat.side.v1.developer:6', '"a string"')
    expect(sidePanelOpen('developer:6').present).toBe(true)
  })
})
