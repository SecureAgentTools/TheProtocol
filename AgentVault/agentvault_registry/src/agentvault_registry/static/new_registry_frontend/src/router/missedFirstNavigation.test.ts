import fs from 'node:fs'
import path from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { createRouter, createWebHashHistory, type Router } from 'vue-router'
import { replayLocationMissedBeforeReady } from './missedFirstNavigation'

const View = defineComponent({ render: () => null })
const routes = ['/', '/mission-control', '/admin/developers', '/other'].map((path) => ({ path, component: View }))
const made: Router[] = []

afterEach(() => {
  while (made.length) made.pop()!.options.history.destroy()
})

/** A router whose first navigation waits (as the console's waits for the session restore) until `release`, started the
 *  way app.use(router) starts it. */
function slowFirstNavigation(withReplay: boolean) {
  window.history.replaceState(null, '', '#/mission-control')
  let release!: () => void
  const gate = new Promise<void>((r) => { release = r })
  let first = true
  const router = createRouter({ history: createWebHashHistory(), routes })
  made.push(router)
  router.beforeEach(async () => {
    if (first) { first = false; await gate }
  })
  if (withReplay) replayLocationMissedBeforeReady(router)
  void router.push(router.options.history.location)
  return { router, release }
}

/** What a browser does when the address bar's hash changes: the URL moves, then popstate and hashchange fire. */
function changeHash(hash: string) {
  window.history.pushState(null, '', hash)
  window.dispatchEvent(new Event('popstate'))
  window.dispatchEvent(new Event('hashchange'))
}

async function settled(router: Router) {
  await router.isReady()
  for (let i = 0; i < 10; i++) await new Promise((r) => setTimeout(r, 0))
}

describe('a URL changed during the first navigation', () => {
  it("is dropped by vue-router alone (the control: the router listens only after its first navigation)", async () => {
    const { router, release } = slowFirstNavigation(false)
    changeHash('#/admin/developers')
    release()
    await settled(router)
    expect(router.currentRoute.value.fullPath).toBe('/mission-control')
    expect(window.location.hash).toBe('#/mission-control')
  })

  it('is carried out once the router listens, and says so', async () => {
    const info = vi.spyOn(console, 'info').mockImplementation(() => undefined)
    const { router, release } = slowFirstNavigation(true)
    changeHash('#/admin/developers')
    release()
    await settled(router)
    expect(router.currentRoute.value.fullPath).toBe('/admin/developers')
    expect(window.location.hash).toBe('#/admin/developers')
    expect(info.mock.calls.some((c) => c.some((x) => String(x).includes('carrying out an address-bar change')))).toBe(true)
    info.mockRestore()
  })

  it('keeps the newest change when there were several', async () => {
    const { router, release } = slowFirstNavigation(true)
    changeHash('#/other')
    changeHash('#/admin/developers?tab=keys')
    release()
    await settled(router)
    expect(router.currentRoute.value.fullPath).toBe('/admin/developers?tab=keys')
  })

  it('adds no navigation when nothing changed, or the change was where the first navigation went anyway', async () => {
    for (const hash of [null, '#/mission-control']) {
      const { router, release } = slowFirstNavigation(true)
      const replace = vi.spyOn(router, 'replace')
      if (hash) changeHash(hash)
      release()
      await settled(router)
      expect(router.currentRoute.value.fullPath).toBe('/mission-control')
      expect(replace).not.toHaveBeenCalled()
    }
  })

  it('leaves a change after the first navigation to the router itself', async () => {
    const { router, release } = slowFirstNavigation(true)
    release()
    await settled(router)
    const replace = vi.spyOn(router, 'replace')
    changeHash('#/other')
    await settled(router)
    expect(router.currentRoute.value.fullPath).toBe('/other')
    expect(replace).not.toHaveBeenCalled()
  })

  it('is installed where the console creates its router', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.ts'), 'utf8')
    expect(src).toMatch(/const router = createRouter\(\{[\s\S]*?\n\}\)\n(?:\/\/[^\n]*\n)*replayLocationMissedBeforeReady\(router\)\n/)
  })
})
