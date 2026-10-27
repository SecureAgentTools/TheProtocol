/**
 * How a browser context reaches the console under test (§FESUITE).
 *
 * The browser keeps the console's REAL origin, so TLS, the derived CORS and the vhost's own lanes (/ws/events*) behave
 * as they do for a person; a runner may map that hostname to 127.0.0.1 (FESUITE_HOST_MAP, a Chromium launch flag set in
 * the config) so nothing crosses a public edge.
 *
 * With FESUITE_DIST, the context answers the console's own paths from a local build, exactly as the registry mounts it:
 *   /ui and /ui/*  -> index.html        (the registry swaps in the frame's head; a local build keeps its own)
 *   /assets/*      -> dist/assets/*
 *   /static/*      -> dist/*, or the registry when the build has no such file (run-time uploads live there too)
 * so a build is driven against a live registry before anyone rolls it. Everything else (the API, the websockets, the
 * well-known documents) stays live.
 */
import fs from 'node:fs'
import path from 'node:path'
import type { BrowserContext, Route } from '@playwright/test'
import { BASE_URL, CONSOLE_PATH, DIST_DIR } from './env'

const TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8', '.json': 'application/json', '.webmanifest': 'application/manifest+json',
  '.svg': 'image/svg+xml', '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
  '.gif': 'image/gif', '.ico': 'image/x-icon', '.woff': 'font/woff', '.woff2': 'font/woff2', '.ttf': 'font/ttf',
  '.txt': 'text/plain; charset=utf-8', '.md': 'text/markdown; charset=utf-8', '.wasm': 'application/wasm',
  '.xml': 'application/xml', '.glb': 'model/gltf-binary', '.mp4': 'video/mp4', '.webm': 'video/webm',
}

function fileFor(pathname: string): string | null {
  const ui = CONSOLE_PATH.replace(/\/$/, '')
  let rel: string | null = null
  if (pathname === ui || pathname.startsWith(`${ui}/`)) rel = 'index.html'
  else if (pathname.startsWith('/assets/')) rel = pathname.slice(1)
  else if (pathname.startsWith('/static/')) rel = pathname.slice('/static/'.length)
  if (rel === null) return null
  const abs = path.resolve(DIST_DIR, decodeURIComponent(rel))
  if (!abs.startsWith(DIST_DIR + path.sep)) return null
  return abs
}

async function serve(route: Route): Promise<void> {
  const url = new URL(route.request().url())
  const file = fileFor(url.pathname)
  if (!file) return route.continue()
  let body: Buffer
  try {
    body = fs.readFileSync(file)
  } catch {
    // /static/ also carries what the registry stores at run time (registry-card icons, uploads), which no build has:
    // those come from the registry. A hashed /assets/ file the local build lacks would be a 404 in production too;
    // never fall through for those, or the page silently mixes two builds.
    if (url.pathname.startsWith('/static/')) return route.continue()
    return route.fulfill({ status: 404, body: 'not in the local build' })
  }
  await route.fulfill({
    status: 200,
    body,
    headers: { 'content-type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream', 'cache-control': 'no-store' },
  })
}

/** Serve the console's own paths from FESUITE_DIST in this context (no-op without it). */
export async function routeLocalBuild(context: BrowserContext): Promise<void> {
  if (!DIST_DIR) return
  if (!fs.existsSync(path.join(DIST_DIR, 'index.html'))) throw new Error(`FESUITE_DIST has no index.html: ${DIST_DIR}`)
  const origin = new URL(BASE_URL).origin
  await context.route((u) => u.origin === origin && fileFor(u.pathname) !== null, serve)
}

/**
 * First-visit state a person dismisses once: the beta banner and the guided tours. Lifecycles that are ABOUT the first
 * visit (onboarding) opt out with { firstVisit: true } and meet the banner and the tour like a person does.
 */
export async function seedReturningVisitor(context: BrowserContext): Promise<void> {
  await context.addInitScript(() => {
    try {
      if (!localStorage.getItem('beta_banner_dismissed')) localStorage.setItem('beta_banner_dismissed', '1')
      if (!localStorage.getItem('pk_tour_done')) localStorage.setItem('pk_tour_done', '1')
      if (!localStorage.getItem('gt_dismissed')) localStorage.setItem('gt_dismissed', '[]')
    } catch { /* storage blocked: the page will show the banner, which the lifecycle then handles */ }
  })
}
