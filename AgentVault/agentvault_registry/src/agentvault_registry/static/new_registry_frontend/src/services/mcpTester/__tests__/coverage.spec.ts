/**
 * V0663 (order gwo_0b31c0b849ebd207102d8bf4, his suggestion 7): which tools the coverage view shows.
 *   - "gaps" (the default): a tool that is failed, refusal only or not measured on at least one target;
 *   - one class: a tool with that class on at least one target; "all": every tool;
 *   - a tier and a search narrow it further; not_listed is never a gap (the target does not offer the tool).
 * Red on 3f729e7c9: the module does not exist.
 */
import { describe, expect, it } from 'vitest'
import { filterTools, type CoverageTool } from '../coverage'

const tool = (name: string, tier: string, ...classes: string[]): CoverageTool => ({
  tool: name, tier, worst: classes[0] as any,
  by_target: Object.fromEntries(classes.map((c, i) => [`t${i}`, { class: c as any }])),
})
const TOOLS = [
  tool('putE', 'admin', 'failed', 'success'),
  tool('getB', 'developer', 'refusal_only', 'success'),
  tool('listD', 'admin', 'not_measured', 'not_listed'),
  tool('getA', 'public', 'success', 'success'),
  tool('onlyOps', 'agent', 'not_listed', 'success'),
]
const names = (ts: CoverageTool[]) => ts.map((t) => t.tool)

describe('filterTools', () => {
  it('gaps: a failure, a refusal or nothing measured on any target, never a tool a target does not list', () => {
    expect(names(filterTools(TOOLS, { show: 'gaps' }))).toEqual(['putE', 'getB', 'listD'])
  })
  it('one class on any target, or all', () => {
    expect(names(filterTools(TOOLS, { show: 'refusal_only' }))).toEqual(['getB'])
    expect(names(filterTools(TOOLS, { show: 'success' }))).toEqual(['putE', 'getB', 'getA', 'onlyOps'])
    expect(filterTools(TOOLS, { show: 'all' })).toHaveLength(5)
  })
  it('a tier and a search narrow it', () => {
    expect(names(filterTools(TOOLS, { show: 'all', tier: 'admin' }))).toEqual(['putE', 'listD'])
    expect(names(filterTools(TOOLS, { show: 'all', query: 'GETb' }))).toEqual(['getB'])
  })
})
