/**
 * V0658 (v), session-lead's decision (the sessions' room, seq 2389): a press inside a shell stays in that shell, and a
 * door knows the shell from the route on screen (services/uiMode.ts). The route table says it, on each shell's own
 * record, and every child inherits it: a /pocket route renders in Pocket, a route inside DashboardLayout in the desktop
 * console, anything else (the public pages) in no shell. And the app's router is the one the doors read, handed over
 * when it is created, so no caller passes the route by hand.
 * RED on e0fe8732c: no route declares a shell, and the router hands nothing to the doors.
 */
import { describe, expect, it, vi } from 'vitest'

const bound = vi.hoisted(() => ({ routers: [] as unknown[] }))
vi.mock('@/services/uiMode', async (importOriginal) => {
  const real = await importOriginal<Record<string, any>>()
  return {
    ...real,
    bindDoorRouter: (router: unknown) => {
      bound.routers.push(router)
      if (typeof real.bindDoorRouter === 'function') real.bindDoorRouter(router)
    },
  }
})

import router from './index'

const shellAt = (path: string) => router.resolve(path).meta.shell

describe('the shell a route renders in', () => {
  it('a /pocket route renders in Pocket', () => {
    for (const path of ['/pocket/home', '/pocket/agents', '/pocket/payments?post=1', '/pocket/ourchat',
      '/pocket/ourchat/room1', '/pocket/orgs', '/pocket/more', '/pocket/approve-login']) {
      expect(shellAt(path), path).toBe('pocket')
    }
  })

  it('a route inside DashboardLayout renders in the desktop console, the desktop chat and the public firms page too', () => {
    for (const path of ['/mission-control', '/my-agents?fund=1', '/guild?post=1', '/discover', '/ourchat',
      '/ourchat/room1', '/firms', '/leaderboard']) {
      expect(shellAt(path), path).toBe('desktop')
    }
  })

  it('anything else renders in no shell: the public pages', () => {
    for (const path of ['/', '/explore', '/login', '/register', '/no-such-page-in-this-test']) {
      expect(shellAt(path), path).toBeUndefined()
    }
  })
})

describe('the doors read the route on screen', () => {
  it('the app router is handed to the doors once, when it is created', () => {
    expect(bound.routers.length, 'routers handed to the doors').toBe(1)
    expect(bound.routers[0]).toBe(router)
  })
})
