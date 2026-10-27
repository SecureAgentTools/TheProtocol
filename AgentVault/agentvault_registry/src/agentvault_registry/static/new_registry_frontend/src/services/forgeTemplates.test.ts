import { describe, expect, it } from 'vitest'
import { defaultTemplateId, isOffered, listedTemplateIds, offeredTemplates } from './forgeTemplates'

const catalogue = [{ id: 'full-capacity' }, { id: 'ppao' }, { id: 'minimal' }] as const

describe('the bundle templates Agent Forge offers', () => {
  it('reads the listed ids and nothing else from the answer', () => {
    expect(listedTemplateIds({ templates: ['minimal', 'ppao'], default: 'minimal' })).toEqual(['minimal', 'ppao'])
    expect(listedTemplateIds({ templates: ['minimal', 7, null] })).toEqual(['minimal'])
    expect(listedTemplateIds({})).toBeNull()
    expect(listedTemplateIds(null)).toBeNull()
  })

  it('offers only what the registry lists, in catalogue order', () => {
    expect(offeredTemplates(catalogue, ['minimal', 'ppao']).map(t => t.id)).toEqual(['ppao', 'minimal'])
    expect(offeredTemplates(catalogue, ['minimal']).map(t => t.id)).toEqual(['minimal'])
  })

  it('keeps the whole catalogue while nothing is listed (an older registry), never an empty picker', () => {
    expect(offeredTemplates(catalogue, null).map(t => t.id)).toEqual(['full-capacity', 'ppao', 'minimal'])
    expect(offeredTemplates(catalogue, []).map(t => t.id)).toEqual(['full-capacity', 'ppao', 'minimal'])
  })

  it('defaults to the first listed template, never a hard-coded full-capacity', () => {
    expect(defaultTemplateId(['minimal', 'ppao'])).toBe('minimal')
    expect(defaultTemplateId(['full-capacity', 'minimal'])).toBe('full-capacity')
    expect(defaultTemplateId(null)).toBe('minimal')
    expect(defaultTemplateId([])).toBe('minimal')
  })

  it('says a pick the registry does not list is not offered', () => {
    expect(isOffered('full-capacity', ['minimal', 'ppao'])).toBe(false)
    expect(isOffered('minimal', ['minimal', 'ppao'])).toBe(true)
    expect(isOffered('full-capacity', null)).toBe(true)
    expect(isOffered(null, ['minimal'])).toBe(true)
  })
})
