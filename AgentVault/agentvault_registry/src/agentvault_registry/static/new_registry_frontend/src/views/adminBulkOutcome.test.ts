/** §FESUITE (2026-10-10): a bulk enforcement action's toast follows its outcome, never "Done" over a failure. */
import { describe, expect, it } from 'vitest'
import { bulkOutcome } from './adminBulkOutcome'

describe('a coordinated bulk action says what happened', () => {
  it('every agent failed: an error', () => expect(bulkOutcome({ succeeded: 0, failed: 1 })).toBe('error'))
  it('some failed: a warning', () => expect(bulkOutcome({ succeeded: 2, failed: 1 })).toBe('warning'))
  it('none failed: done (skipped is not failed)', () => {
    expect(bulkOutcome({ succeeded: 1, failed: 0 })).toBe('success')
    expect(bulkOutcome({ succeeded: 0, failed: 0 })).toBe('success')
  })
  it('an answer without counts is not called a failure', () => expect(bulkOutcome(null)).toBe('success'))
})
