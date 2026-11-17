import { describe, it, expect } from 'vitest'
import { arrivesInDesk } from './uiMode'

/** V0663 (browser pass, seq 3591): a message link copied on the desk is the stable external form (/pocket/ourchat/<id>?m=) and
 *  opened in a wide window it landed in the Pocket shell. A link arrives by the landing decision (a mailed link or a notification
 *  does: services/uiMode.ts); a press inside a shell stays in it, so only the FIRST arrival of a page load can change shell. */
describe('where a pocket thread link arrives', () => {
  it('goes to the desk thread on a wide window with no saved choice', () => {
    expect(arrivesInDesk(true, null, 1440)).toBe(true)
  })
  it('stays in Pocket on a phone', () => {
    expect(arrivesInDesk(true, null, 393)).toBe(false)
  })
  it('stays in Pocket when Pocket is the saved choice, at any width', () => {
    expect(arrivesInDesk(true, 'pocket', 1440)).toBe(false)
  })
  it('goes to the desk on a narrow window when the desk is the saved choice', () => {
    expect(arrivesInDesk(true, 'advanced', 393)).toBe(true)
  })
  it('never moves a person who is already inside the app (a press stays in its shell)', () => {
    expect(arrivesInDesk(false, null, 1440)).toBe(false)
  })
})
