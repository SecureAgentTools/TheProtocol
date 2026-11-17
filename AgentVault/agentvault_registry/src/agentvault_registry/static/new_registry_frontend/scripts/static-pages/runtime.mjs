// V0667 static pages (order gwo_a9f121caa4138ec9b369814c): the runtime the pages are made in. The app's OWN modules, compiled by its own Vite
// config (the .vue files, the aliases, en.json), with a happy-dom window as the browser globals the modules read at import time. No headless
// browser: nothing here runs a GPU or a timer loop. The network is kept out by src/staticPages/noNetwork.ts (installed by generate.mjs before
// any app module loads) and, where the host allows, by a network namespace with no interfaces.
import { Window } from 'happy-dom'
import { createServer } from 'vite'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const GLOBALS = ['window', 'document', 'location', 'localStorage', 'sessionStorage', 'HTMLElement', 'Element', 'Node', 'Text',
  'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame', 'matchMedia', 'CustomEvent', 'Event', 'MutationObserver',
  'ResizeObserver', 'IntersectionObserver', 'DOMParser', 'SVGElement', 'history', 'screen', 'innerWidth', 'innerHeight']

export async function withDom(fn, url = 'https://theprotocol.cloud/') {
  const win = new Window({ url, width: 1280, height: 900 })
  for (const k of GLOBALS) {
    try { Object.defineProperty(globalThis, k, { value: k === 'window' ? win : win[k], configurable: true, writable: true }) } catch { /* read-only in this Node */ }
  }
  try { Object.defineProperty(globalThis, 'navigator', { value: win.navigator, configurable: true, writable: true }) } catch { /* keep Node's */ }
  try { return await fn(win) } finally {
    await win.happyDOM.abort()
    win.close()
  }
}

export async function loadApp() {
  const vite = await createServer({ root: ROOT, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom',
    logLevel: 'error', optimizeDeps: { noDiscovery: true, include: [] } })
  return { load: (id) => vite.ssrLoadModule(id), close: () => vite.close() }
}
