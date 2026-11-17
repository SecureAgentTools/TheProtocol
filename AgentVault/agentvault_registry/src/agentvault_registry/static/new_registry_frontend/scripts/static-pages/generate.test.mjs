/**
 * V0667 static pages (order gwo_a9f121caa4138ec9b369814c): the release step itself, run as a release runs it, on a fixture build, for two of
 * the routes (the whole table is src/staticPages/render.test.ts's). It writes each page at its plain path with mode 644 in a 755 folder (this
 * box's umask would leave nginx unable to read them), the manifest the sitemap reads, and leaves the build's index.html alone when the landing
 * page is not among the routes; a static page carries no script.
 */
import { describe, expect, it } from 'vitest'
import { mkdtempSync, mkdirSync, readFileSync, statSync, writeFileSync, existsSync, rmSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import os from 'node:os'
import path from 'node:path'

const GEN = path.resolve(__dirname, 'generate.mjs')
const INDEX = '<!DOCTYPE html><html><head><title>TheProtocol</title><link rel="stylesheet" href="/assets/index-abc.css"></head><body><div id="app"></div></body></html>'

describe('the static pages release step', () => {
  it('writes the pages it was asked for at their plain paths, readable by the web server, and their manifest', () => {
    const tmp = mkdtempSync(path.join(os.tmpdir(), 'static-pages-'))
    try {
      mkdirSync(path.join(tmp, 'dist'))
      writeFileSync(path.join(tmp, 'dist', 'index.html'), INDEX)
      const r = spawnSync(process.execPath, [GEN, '--dist', path.join(tmp, 'dist'), '--out', path.join(tmp, 'out'), '--only', '/compliance,/contact'],
        { encoding: 'utf8', timeout: 240000 })
      expect(r.status, r.stdout + r.stderr).toBe(0)
      for (const p of ['compliance', 'contact']) {
        const file = path.join(tmp, 'out', p, 'index.html')
        expect(statSync(file).mode & 0o777).toBe(0o644)
        expect(statSync(path.dirname(file)).mode & 0o777).toBe(0o755)
        const page = readFileSync(file, 'utf8')
        expect(page).toContain(`<link rel="canonical" href="https://theprotocol.cloud/${p}/">`)
        expect(page).toContain('<link rel="stylesheet" href="/assets/index-abc.css">')
        expect(page).not.toMatch(/<script/i)
      }
      const manifest = JSON.parse(readFileSync(path.join(tmp, 'out', 'static-pages.json'), 'utf8'))
      expect(manifest.map((m) => m.path).sort()).toEqual(['/compliance/', '/contact/'])
      expect(readFileSync(path.join(tmp, 'dist', 'index.html'), 'utf8')).toBe(INDEX)
      expect(existsSync(path.join(tmp, 'out', 'index.html'))).toBe(false)
    } finally { rmSync(tmp, { recursive: true, force: true }) }
  }, 300000)
})
