import { describe, it, expect } from 'vitest'
import {
  ROLE_BADGE, ROLE_LEAD, DOCS_PATH, docsPathFor, showsTargetChips, type SandboxRole,
} from '../role'

describe('§TESTBED — the MCP tester header follows the frame\'s role, not its hostname', () => {
  it('names a sandbox a sandbox', () => {
    expect(ROLE_BADGE.sandbox.fallback).toBe('SANDBOX · RUNS AGAINST ITSELF')
    expect(ROLE_BADGE.sandbox.key).toBe('mcpTester.sandbox.sandboxBadge')
    expect(ROLE_LEAD.sandbox.fallback).toContain('runs against this frame itself')
  })

  it('keeps the parent frame saying it runs in its sandbox', () => {
    expect(ROLE_BADGE.parent.fallback).toBe('PRODUCTION · RUNS IN ITS SANDBOX')
    expect(ROLE_LEAD.parent.fallback).toContain('never against production')
  })

  it('never calls a sandbox production, whatever the address says', () => {
    // the control: the two roles must not share a badge
    expect(ROLE_BADGE.sandbox.fallback).not.toBe(ROLE_BADGE.parent.fallback)
    expect(ROLE_BADGE.sandbox.fallback).not.toContain('PRODUCTION')
  })

  it('points each frame at a document it actually ships', () => {
    expect(docsPathFor('sandbox')).toBe(DOCS_PATH.kit)
    expect(docsPathFor('parent')).toBe(DOCS_PATH.kit)
    // the control: the development host keeps the internal document it does ship
    expect(docsPathFor('none')).toBe(DOCS_PATH.dev)
  })

  it('offers the development host\'s target chips on the development host only', () => {
    const roles: SandboxRole[] = ['parent', 'sandbox']
    for (const r of roles) expect(showsTargetChips(r)).toBe(false)
    expect(showsTargetChips('none')).toBe(true)
  })
})
