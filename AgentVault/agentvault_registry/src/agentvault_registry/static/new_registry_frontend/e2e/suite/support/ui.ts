/**
 * How the suite moves through the console (§FESUITE). Every wait here ends on the OUTCOME the product reports, and
 * every one can end in a failure: a wait that can only end in a pass is a mask.
 */
import { expect, type Locator, type Page } from '@playwright/test'
import { consoleUrl } from './env'
import { passReconsent } from './accounts'

/** The in-app route the page is on now ('/my-agents', no query). */
export async function currentRoute(page: Page): Promise<string> {
  return page.evaluate(() => (location.hash.replace(/^#/, '') || '/').split('?')[0])
}

/**
 * Open an in-app route and wait until the console has routed (the hash names a route and the app mounted), then pass
 * the legal re-consent modal if it covers the page. Returns the route the console actually landed on: a guard may
 * redirect, and the caller decides whether that is the product working or the product refusing.
 */
export async function openRoute(page: Page, route: string): Promise<string> {
  await page.goto(consoleUrl(route), { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => {
    const app = document.querySelector('#app')
    return !!app && app.children.length > 0 && location.hash.length > 1
  })
  await settle(page)
  await passReconsent(page)
  return currentRoute(page)
}

/** The console has stopped fetching for a moment (no axios call in flight for 500 ms) or 10 s passed. */
export async function settle(page: Page, quietMs = 500, capMs = 10_000): Promise<void> {
  await page.waitForLoadState('domcontentloaded')
  const t0 = Date.now()
  let quietSince = Date.now()
  let inflight = 0
  const onReq = () => { inflight += 1; quietSince = Date.now() }
  const onDone = () => { inflight = Math.max(0, inflight - 1); quietSince = Date.now() }
  page.on('request', onReq)
  page.on('requestfinished', onDone)
  page.on('requestfailed', onDone)
  try {
    while (Date.now() - t0 < capMs) {
      if (inflight === 0 && Date.now() - quietSince >= quietMs) return
      await page.waitForTimeout(100)
    }
  } finally {
    page.off('request', onReq)
    page.off('requestfinished', onDone)
    page.off('requestfailed', onDone)
  }
}

/** The newest toast of a kind whose text matches; fails if none arrives. */
export async function toast(page: Page, kind: 'success' | 'error' | 'warning' | 'info', text: RegExp): Promise<string> {
  const t = page.locator(`[data-testid="toast"][data-kind="${kind}"]`).filter({ hasText: text }).last()
  await expect(t).toBeVisible()
  return (await t.innerText()).replace(/\s+/g, ' ').trim()
}

/** Wait for whichever of several outcomes the product reports first; returns its index. Every outcome ends the wait. */
export async function firstOf(page: Page, outcomes: Locator[], timeoutMs = 30_000): Promise<number> {
  const t0 = Date.now()
  while (Date.now() - t0 < timeoutMs) {
    for (let i = 0; i < outcomes.length; i++) {
      if (await outcomes[i].first().isVisible().catch(() => false)) return i
    }
    await page.waitForTimeout(150)
  }
  throw new Error(`none of ${outcomes.length} outcomes appeared in ${timeoutMs} ms`)
}

/**
 * Run a function against a pinia store inside the page (drive the engine, not the DOM, when the DOM is not the
 * subject). The function travels as its own source inside one evaluated expression, never through eval or new
 * Function in the page, so the console's content security policy has nothing to refuse. Arguments must be JSON.
 */
export async function pinia<T>(page: Page, storeId: string, fn: (store: any, ...args: any[]) => T | Promise<T>, ...args: unknown[]): Promise<T> {
  const src = `(async () => {
    const app = document.querySelector('#app') && document.querySelector('#app').__vue_app__
    const store = app && app.config.globalProperties.$pinia && app.config.globalProperties.$pinia._s.get(${JSON.stringify(storeId)})
    if (!store) throw new Error('pinia store ' + ${JSON.stringify(storeId)} + ' is not registered')
    return await (${fn.toString()})(store, ...${JSON.stringify(args)})
  })()`
  return page.evaluate(src) as Promise<T>
}

/**
 * Every toast the console shows, as it appears (§FESUITE): a refusal's toast names the guard that refused (the role,
 * an admin area, a mainframe-only page), which the route alone cannot say, and it is gone before a failure snapshot.
 * A MutationObserver per document, installed for every later navigation too; it reads only added nodes.
 */
export async function recordToasts(page: Page): Promise<void> {
  const install = () => {
    const w = window as any
    if (w.__fesuiteToasts) return
    w.__fesuiteToasts = []
    const rec = (el: Element) => w.__fesuiteToasts.push({ t: Date.now(), text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200) })
    new MutationObserver((ms) => {
      for (const m of ms) for (const n of Array.from(m.addedNodes)) {
        if (!(n instanceof Element)) continue
        if (n.matches('[data-testid="toast"]')) rec(n)
        else n.querySelectorAll('[data-testid="toast"]').forEach(rec)
      }
    // the document itself: an init script runs before the root element exists in some documents (observe(null) threw
    // "parameter 1 is not of type 'Node'" in the page, which the capture rightly counted against it)
    }).observe(document, { childList: true, subtree: true })
  }
  await page.addInitScript(install)
  await page.evaluate(install).catch(() => undefined)
}

/** Where the console's ROUTER is (its current route's path), which is not always the URL: during the first navigation
 *  the address bar can show a change the router has not taken yet. '' when there is no router. */
export async function routerPath(page: Page): Promise<string> {
  return page.evaluate(() => (document.querySelector('#app') as any)?.__vue_app__?.config?.globalProperties?.$router
    ?.currentRoute?.value?.path ?? '').catch(() => '')
}

/** Wait (bounded) for the router to arrive at `path`, and return where it is: a slow session restore is waited out
 *  instead of read mid-way, and an arrival that never comes is still reported by the caller. */
export async function routerArrives(page: Page, path: string, timeoutMs = 15_000): Promise<string> {
  const until = Date.now() + timeoutMs
  let at = await routerPath(page)
  while (at !== path && Date.now() < until) {
    await page.waitForTimeout(150)
    at = await routerPath(page)
  }
  return at
}

/** The page's own clock (toast times are the page's), for toastsSince. */
export async function pageNow(page: Page): Promise<number> {
  return page.evaluate(() => Date.now())
}

/** The toasts shown since `since` (page time), as text. */
export async function toastsSince(page: Page, since: number): Promise<string[]> {
  return page.evaluate((t) => ((window as any).__fesuiteToasts || []).filter((x: any) => x.t >= t).map((x: any) => x.text), since)
    .catch(() => [] as string[])
}

/**
 * Every way the console's route moves, kept across reloads (sessionStorage): each document load, each hash change, each
 * router.push/replace with the frames that asked for it, each navigation's outcome (the failure type, the redirect it
 * came from), router errors, history.go/back (the router reverts an aborted hash change with go(-1)), and the auth store
 * each time its state changes. A bounce that leaves no toast can then be named by what moved it instead of guessed
 * (the admin bounce right after a load, run fes-20261001T230748Z-7785). It only observes: every wrapper calls through.
 */
export async function recordNavigation(page: Page): Promise<void> {
  const install = () => {
    const w = window as any
    if (w.__fesuiteNavOn) return
    w.__fesuiteNavOn = true
    const KEY = '__fesuite_nav'
    const add = (kind: string, detail: string) => {
      try {
        const log = JSON.parse(sessionStorage.getItem(KEY) || '[]')
        log.push({ t: Date.now(), kind, detail: String(detail).slice(0, 300) })
        sessionStorage.setItem(KEY, JSON.stringify(log.slice(-400)))
      } catch { /* storage refused: nothing to keep */ }
    }
    const caller = () => (new Error().stack || '').split('\n').slice(3, 6)
      .map((s) => s.trim().replace(/^at /, '').replace(/https?:\/\/[^/\s]+\/(ui\/)?(assets\/)?/, '')).join(' < ')
    add('document', `loaded at ${location.hash || location.pathname}`)
    window.addEventListener('hashchange', (e) => add('hashchange', `${new URL(e.oldURL).hash} -> ${new URL(e.newURL).hash}`))
    for (const m of ['go', 'back'] as const) {
      const orig = (history as any)[m].bind(history)
      ;(history as any)[m] = (...a: unknown[]) => {
        try { add(`history.${m}`, `${a.join(',')} from ${caller()}`) } catch { /* the call below always runs */ }
        return orig(...a)
      }
    }
    const t0 = Date.now()
    const timer = setInterval(() => { try {
      const app = (document.querySelector('#app') as any)?.__vue_app__
      if (!app) { if (Date.now() - t0 > 30_000) clearInterval(timer); return }
      clearInterval(timer)
      const gp = app.config.globalProperties
      const router = gp.$router
      if (router && !router.__fesuiteNav) {
        router.__fesuiteNav = true
        for (const m of ['push', 'replace'] as const) {
          const orig = router[m].bind(router)
          router[m] = (to: any) => {
            try {
              add(`router.${m}`, `${typeof to === 'string' ? to : to?.path || to?.name || JSON.stringify(to)} from ${caller()}`)
            } catch { /* the call below always runs */ }
            return orig(to)
          }
        }
        router.afterEach((to: any, from: any, failure: any) => {
          try {
            add('navigated', `${from.fullPath} -> ${to.fullPath}`
              + (to.redirectedFrom ? ` (redirected from ${to.redirectedFrom.fullPath})` : '')
              + (failure ? ` FAILED type ${failure.type}: ${String(failure.message || '').slice(0, 120)}` : ''))
          } catch { /* observe only */ }
        })
        router.onError((err: any, to: any) => {
          try { add('router-error', `${to?.fullPath}: ${String(err?.message || err).slice(0, 160)}`) } catch { /* observe only */ }
        })
      }
      let last = ''
      setInterval(() => { try {
        const a = gp.$pinia?._s?.get('auth')
        if (!a) return
        const s = `user ${a.user ? 'yes' : 'no'}, admin ${a.isAdmin ? 'yes' : 'no'}, `
          + `restore in flight ${a.authSettling?.() ? 'yes' : 'no'}, token ${a.token ? 'yes' : 'no'}`
        if (s !== last) { last = s; add('auth', s) }
      } catch { /* an observer never raises in the page it observes */ } }, 50)
    } catch { clearInterval(timer) } }, 25)
  }
  await page.addInitScript(install)
  await page.evaluate(install).catch(() => undefined)
}

/** The route moves recorded since `since` (page time), oldest first, each with its offset from `since`. */
export async function navigationSince(page: Page, since: number): Promise<string[]> {
  return page.evaluate((t) => {
    try {
      return (JSON.parse(sessionStorage.getItem('__fesuite_nav') || '[]') as Array<{ t: number; kind: string; detail: string }>)
        .filter((x) => x.t >= t).map((x) => `+${x.t - t}ms ${x.kind}: ${x.detail}`)
    } catch { return [] as string[] }
  }, since).catch(() => [] as string[])
}

/** Sign in through the login form, the way a person does. */
export async function loginWithForm(page: Page, email: string, password: string): Promise<string> {
  await openRoute(page, '/login')
  await page.locator('input[autocomplete="username"]').fill(email)
  await page.locator('input[autocomplete="current-password"]').fill(password)
  await page.locator('form button[type="submit"]').click()
  await page.waitForFunction(() => !/^#\/login/.test(location.hash), undefined, { timeout: 30_000 })
  await settle(page)
  await passReconsent(page)
  return currentRoute(page)
}

/**
 * Answer the shared confirm dialog (ConfirmActionModal): type what it asks for when it asks, then press its action
 * button (never the ghost "cancel"). Returns the dialog's title.
 */
export async function confirmDialog(page: Page, typed?: string): Promise<string> {
  const dialog = page.locator('.ca-modal[role="dialog"]').last()
  await expect(dialog).toBeVisible()
  const title = (await dialog.locator('[id]').first().innerText().catch(() => '')).trim()
  if (typed !== undefined) await dialog.locator('.ca-input').fill(typed)
  await dialog.locator('.ca-modal-footer .ca-btn:not(.ca-btn--ghost)').click()
  await expect(dialog).toHaveCount(0)
  return title
}

/** Is the console holding a developer session right now (the auth store's own answer)? */
export async function signedIn(page: Page): Promise<boolean> {
  return pinia<boolean>(page, 'auth', (store) => !!store.token)
}
