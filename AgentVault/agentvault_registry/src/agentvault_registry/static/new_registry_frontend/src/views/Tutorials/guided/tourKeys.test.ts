import { describe, it, expect } from 'vitest'
import { tourKeyAction, isEditableTarget } from './tourKeys'

const open = { active: true, modalOpen: false, editable: false }

describe('tourKeyAction — §TOURWALK', () => {
  it('steps and ends an active tour with nothing on top of it', () => {
    expect(tourKeyAction('Escape', open)).toBe('end')
    expect(tourKeyAction('ArrowRight', open)).toBe('next')
    expect(tourKeyAction('ArrowLeft', open)).toBe('back')
    expect(tourKeyAction('a', open)).toBeNull()
  })
  it('ignores every key while the quick-agent modal the tour opened is on top', () => {
    const ctx = { ...open, modalOpen: true }
    expect(tourKeyAction('Escape', ctx)).toBeNull()   // the sheet owns Escape; the tour must survive it
    expect(tourKeyAction('ArrowRight', ctx)).toBeNull()
    expect(tourKeyAction('ArrowLeft', ctx)).toBeNull()
  })
  it('ignores every key while the person is typing in a field', () => {
    const ctx = { ...open, editable: true }
    expect(tourKeyAction('Escape', ctx)).toBeNull()
    expect(tourKeyAction('ArrowRight', ctx)).toBeNull()
    expect(tourKeyAction('ArrowLeft', ctx)).toBeNull()
  })
  it('does nothing when no tour is running', () => {
    expect(tourKeyAction('Escape', { ...open, active: false })).toBeNull()
  })
})

describe('isEditableTarget', () => {
  it('names inputs, textareas, selects and contenteditable as editable', () => {
    expect(isEditableTarget(null)).toBe(false)
    expect(isEditableTarget({ tagName: 'INPUT' } as unknown as EventTarget)).toBe(true)
    expect(isEditableTarget({ tagName: 'textarea' } as unknown as EventTarget)).toBe(true)
    expect(isEditableTarget({ tagName: 'SELECT' } as unknown as EventTarget)).toBe(true)
    expect(isEditableTarget({ tagName: 'DIV' } as unknown as EventTarget)).toBe(false)
    expect(isEditableTarget({ tagName: 'DIV', isContentEditable: true } as unknown as EventTarget)).toBe(true)
    expect(isEditableTarget({ tagName: 'BUTTON' } as unknown as EventTarget)).toBe(false)
  })
})
