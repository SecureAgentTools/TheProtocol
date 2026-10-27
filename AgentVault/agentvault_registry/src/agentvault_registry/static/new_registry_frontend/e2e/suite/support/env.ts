/**
 * What the suite knows about its target, all from the environment (§FESUITE). The suite itself names no host and holds
 * no secret: a runner (on our host, scripts/fesuite/ in the stack) resolves the target and passes these in.
 *
 *   FESUITE_BASE_URL        the console's ORIGIN as people reach it, e.g. https://console.example.org      (required)
 *   FESUITE_CONSOLE_PATH    where the console lives under that origin                                     (default /ui/)
 *   FESUITE_API_URL         where the suite's own setup and read-back calls go (default: FESUITE_BASE_URL); a runner on
 *                           the registry's host points it at the registry's loopback port
 *   FESUITE_HOST_MAP        hostnames Chromium resolves to 127.0.0.1 (comma list): the browser keeps the real origin
 *                           (TLS, CORS, the vhost's lanes) while every request stays on the host, never on a public edge
 *   FESUITE_DIST            a built console (dist/) to serve for /ui, /assets and /static instead of the deployed one, so
 *                           a build is tested against a live registry before it is rolled                    (optional)
 *   FESUITE_RUN_ID          this run's id, [A-Za-z0-9-]{8,64}                                     (default: a UTC stamp)
 *   FESUITE_PREFIX          the prefix of every account and object the run creates                (default: fesuite-<run>)
 *   FESUITE_OUT             where the run record and the report go                       (default: test-results/fesuite)
 *   FESUITE_ADMIN_EMAIL / FESUITE_ADMIN_PASSWORD   the target frame's admin, for the admin lifecycles and for the
 *                           setup a lifecycle needs (funding). Never typed into a page: the suite logs in over the API.
 *   FESUITE_FRAME_LABEL     a human name for the target in the run record                                    (optional)
 *   FESUITE_PEER_URL        a second frame's console origin, for the cross-frame lifecycles                  (optional)
 *   FESUITE_PEER_API_URL    its setup and read-back address                                (default: FESUITE_PEER_URL)
 */
import fs from 'node:fs'
import path from 'node:path'

function stamp(): string {
  return new Date().toISOString().replace(/[-:]/g, '').replace(/\..*$/, 'Z')
}

export const RUN_ID: string = process.env.FESUITE_RUN_ID || `fes-${stamp()}`
if (!/^[A-Za-z0-9-]{8,64}$/.test(RUN_ID)) {
  throw new Error(`FESUITE_RUN_ID must match [A-Za-z0-9-]{8,64} (got ${RUN_ID.length} chars)`)
}

export const PREFIX: string = (process.env.FESUITE_PREFIX || `fesuite-${RUN_ID.slice(-10)}`).toLowerCase()
if (!/^fesuite-[a-z0-9-]{3,40}$/.test(PREFIX)) {
  // Every object the suite creates carries this prefix, and the sweep deletes only what carries it.
  throw new Error('FESUITE_PREFIX must start with "fesuite-" and hold only [a-z0-9-]')
}

const trim = (u: string | undefined) => (u || '').replace(/\/+$/, '')

export const BASE_URL: string = trim(process.env.FESUITE_BASE_URL)
export const CONSOLE_PATH: string = (process.env.FESUITE_CONSOLE_PATH || '/ui/').replace(/^([^/])/, '/$1')
export const API_URL: string = trim(process.env.FESUITE_API_URL) || BASE_URL
export const PEER_URL: string = trim(process.env.FESUITE_PEER_URL)
export const PEER_API_URL: string = trim(process.env.FESUITE_PEER_API_URL) || PEER_URL
export const HOST_MAP: string[] = (process.env.FESUITE_HOST_MAP || '').split(',').map((h) => h.trim()).filter(Boolean)
export const DIST_DIR: string = process.env.FESUITE_DIST ? path.resolve(process.env.FESUITE_DIST) : ''
export const OUT_DIR: string = path.resolve(process.env.FESUITE_OUT || 'test-results/fesuite')
export const FRAME_LABEL: string = process.env.FESUITE_FRAME_LABEL || ''

/** The console URL for an in-app route: consoleUrl('/my-agents') = <origin>/ui/#/my-agents */
export function consoleUrl(route = '/'): string {
  const r = route.startsWith('/') ? route : `/${route}`
  const base = CONSOLE_PATH.endsWith('/') ? CONSOLE_PATH : `${CONSOLE_PATH}/`
  return `${BASE_URL}${base}#${r}`
}

export function adminCredentials(): { email: string; password: string } | null {
  const email = process.env.FESUITE_ADMIN_EMAIL || ''
  const password = process.env.FESUITE_ADMIN_PASSWORD || ''
  return email && password ? { email, password } : null
}

export function ensureOutDir(): string {
  fs.mkdirSync(OUT_DIR, { recursive: true })
  return OUT_DIR
}

/**
 * A run-unique name for an object, short enough for every name column the product has. The random tail keeps names
 * unique when Playwright restarts a worker after a failure (the counter starts again in the new process).
 */
let counter = 0
export function uniqueName(kind: string): string {
  counter += 1
  const tail = Math.random().toString(36).slice(2, 6)
  return `${PREFIX}-${kind}-${counter}${tail}`.slice(0, 60)
}
