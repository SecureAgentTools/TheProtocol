import { describe, expect, it } from 'vitest'
import { queryForTab, tabQueryAction } from './settingsTabQuery'

const VISIBLE = ['profile', 'security', 'notifications', 'multiframe']

describe('tabQueryAction (§FESUITE 2026-10-04: the address names the open tab)', () => {
  it('opens a tab the viewer has', () => {
    expect(tabQueryAction('notifications', VISIBLE)).toBe('open')
  })

  it('waits for a tab whose existence a read still decides', () => {
    expect(tabQueryAction('invitations', VISIBLE, ['invitations'])).toBe('wait')
  })

  it('drops the same tab once the read has decided it is not there', () => {
    expect(tabQueryAction('invitations', VISIBLE, [])).toBe('drop')
  })

  it('drops a tab nobody has', () => {
    expect(tabQueryAction('no-such-tab', VISIBLE, ['invitations'])).toBe('drop')
  })

  it('does nothing without a usable ?tab=', () => {
    for (const q of [undefined, null, '', ['notifications'], 3]) expect(tabQueryAction(q, VISIBLE)).toBe('none')
  })
})

describe('queryForTab', () => {
  it('names the tab and keeps the other parameters', () => {
    expect(queryForTab({ ref: 'mail', tab: 'notifications' }, 'security')).toEqual({ ref: 'mail', tab: 'security' })
  })

  it('adds the tab when the address had none', () => {
    expect(queryForTab({}, 'api')).toEqual({ tab: 'api' })
  })
})
