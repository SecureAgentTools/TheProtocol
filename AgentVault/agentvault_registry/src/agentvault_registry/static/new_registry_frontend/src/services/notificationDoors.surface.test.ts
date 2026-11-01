/**
 * V0652 (ai) (order gwo_b13813d486f28d456a324293): a notice opens a chat thread on the surface it is read on.
 * session-tester's support ticket test (FINDINGS_2026-10-31_SUPPORT_TICKET_EU.md, minor): the notices click to
 * `/ui#/pocket/ourchat/<id>`, Pocket's path, on the desktop too. The desktop bell now opens the console's thread, and
 * Pocket opens its own for a console link. BASE (V0651): desktopRoute and hashRoute do not exist; the bell pushed the
 * Pocket path as given.
 */
import { describe, it, expect } from 'vitest'
import { desktopRoute, doorForNotification, hashRoute } from './notificationDoors'

describe('the desktop bell', () => {
  it("opens a Pocket thread in the console's chat, its query kept", () => {
    expect(desktopRoute('/ui#/pocket/ourchat/76f20288-a89c?approval=apr_1')).toBe('/ourchat/76f20288-a89c?approval=apr_1')
    expect(desktopRoute('https://eu.example.test/ui/#/pocket/ourchat/c1')).toBe('/ourchat/c1')
  })
  it('opens the permanent /pocket/ourstate alias there too', () => {
    expect(desktopRoute('/ui#/pocket/ourstate/c1')).toBe('/ourchat/c1')
  })
  it('leaves every other route as it was, and refuses what is not an in-app route', () => {
    expect(desktopRoute('/ui#/admin/chatdesk?ticket=7')).toBe('/admin/chatdesk?ticket=7')
    expect(desktopRoute('/ui#/pocket/approvals')).toBe('/pocket/approvals')
    expect(desktopRoute('/ui#//evil.example')).toBeNull()
    expect(desktopRoute(null)).toBeNull()
    expect(hashRoute('/settings?tab=support')).toBe('/settings?tab=support')
  })
})

describe('Pocket', () => {
  it("opens the console's thread link in its own thread", () => {
    expect(doorForNotification({ type_key: 'chat.message', click: '/ui#/ourchat/c1?approval=apr_1' }))
      .toEqual({ path: '/pocket/ourchat/c1', query: { approval: 'apr_1' } })
  })
  it('keeps a Pocket-native click as it was (control)', () => {
    expect(doorForNotification({ type_key: 'support.reply', click: '/ui#/pocket/ourchat/c1' }))
      .toEqual({ path: '/pocket/ourchat/c1' })
  })
  it("has no door for the desk's notice: the chat desk is the console's", () => {
    expect(doorForNotification({ type_key: 'support.desk', click: '/ui#/admin/chatdesk?ticket=7' })).toBeNull()
  })
})
