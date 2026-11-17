#!/usr/bin/env node
// V0667 the public pages readable without JavaScript (order gwo_a9f121caa4138ec9b369814c; his approval, room seq 5381). A RELEASE STEP, after
// the console's build (npm run build-only) and before its image: every page of src/staticPages/pages.ts, rendered from the app's own view and
// en.json (src/staticPages/render.ts), written as a static page at its plain path, and the landing page put into the build's own index.html
// (inside #app, where the app mounts over it). Each page passes the render test's gate here too (its minimum text, its two phrases, none of
// its live data) or NOTHING is written: a release never ships a page that lost its text.
//
//   node scripts/static-pages/generate.mjs --dist dist --out <dir> [--only /route,/route]
//     --dist   the console's build: its index.html gives the stylesheets and receives the landing page
//     --out    where the static pages go (<out>/<path>/index.html, and <out>/static-pages.json, the manifest the sitemap reads)
//     --only   render only these routes (a test); never with --dist pointing at a real build
// It runs in a network namespace with no interfaces where the host allows (unshare -n, as root); the stand-ins keep the network out besides.
import { mkdirSync, readFileSync, renameSync, writeFileSync, chmodSync, existsSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const args = Object.fromEntries(process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith('--') ? [...acc, [a.slice(2), all[i + 1]]] : acc), []))
if (!args.dist || !args.out) { console.error('usage: generate.mjs --dist <console build> --out <dir> [--only /a,/b]'); process.exit(2) }

// `unshare -n true` proves the namespace can be made here (a container without the privilege has unshare and cannot use it)
if (process.env.STATIC_PAGES_NETNS !== 'inside' && process.getuid?.() === 0 && spawnSync('unshare', ['-n', 'true']).status === 0) {
  const r = spawnSync('unshare', ['-n', process.execPath, fileURLToPath(import.meta.url), ...process.argv.slice(2)],
    { stdio: 'inherit', env: { ...process.env, STATIC_PAGES_NETNS: 'inside' } })
  process.exit(r.status ?? 1)
}
if (process.env.STATIC_PAGES_NETNS !== 'inside') console.log('static pages: no network namespace here; the stand-ins alone keep the network out')

const { withDom, loadApp, ROOT } = await import('./runtime.mjs')
const dist = path.resolve(ROOT, args.dist)
const out = path.resolve(ROOT, args.out)
const only = args.only ? new Set(args.only.split(',')) : null
const indexPath = path.join(dist, 'index.html')
if (!existsSync(indexPath)) { console.error(`no ${indexPath}: build the console first`); process.exit(2) }
const indexHtml = readFileSync(indexPath, 'utf8')
const css = [...indexHtml.matchAll(/<link\b[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>/g)].map((m) => m[1])

function writeAtomic(file, text) {
  mkdirSync(path.dirname(file), { recursive: true, mode: 0o755 })
  chmodSync(path.dirname(file), 0o755)
  const tmp = `${file}.tmp-${process.pid}`
  writeFileSync(tmp, text, { mode: 0o644 })
  chmodSync(tmp, 0o644)                                  // this box's umask (027) would leave the web server unable to read it
  renameSync(tmp, file)
}

const say = console.log
const failures = []
let written = 0
await withDom(async () => {
  console.log = () => {}; console.info = () => {}; console.warn = () => {}; console.error = () => {}    // the views' own chatter
  const { load, close } = await loadApp()
  try {
    ;(await load('/src/staticPages/noNetwork.ts')).installNoNetwork(globalThis)
    const { renderPage } = await load('/src/staticPages/render.ts')
    const { PAGES, liveLink, plainPath } = await load('/src/staticPages/pages.ts')
    const { pageDocument, injectLanding, pageText, pageGate } = await load('/src/staticPages/document.ts')
    const done = []
    for (const page of PAGES) {
      if (only && !only.has(page.route)) continue
      for (const inst of page.instances) {
        const r = await renderPage(page.route, inst.params)
        const text = pageText(r.body)
        const why = pageGate(text, inst)
        if (why.length) failures.push(`${plainPath(page.route, inst.params)}: ${why.join('; ')}`)
        done.push({ path: plainPath(page.route, inst.params), live: liveLink(page.route, inst.params), title: r.title,
          description: r.description, body: r.body, chars: text.length })
      }
    }
    if (failures.length) return
    const nav = done.filter((d) => d.path !== '/').map((d) => ({ path: d.path, title: d.title }))
    for (const d of done) {
      if (d.path === '/') writeAtomic(indexPath, injectLanding(indexHtml, d.body))
      else writeAtomic(path.join(out, d.path, 'index.html'),
        pageDocument({ path: d.path, live: d.live, title: d.title, description: d.description, body: d.body, css, nav }))
      written++
    }
    writeAtomic(path.join(out, 'static-pages.json'), JSON.stringify(done.map(({ body, ...m }) => m), null, 1) + '\n')
  } finally { await close() }
})
console.log = say
if (failures.length) {
  say(`static pages REFUSED: ${failures.length} page(s) lost their text, nothing written:`)
  for (const f of failures) say(`  ${f}`)
  process.exit(1)
}
say(`static pages: ${written} written (${only ? 'only ' + [...only].join(',') : 'all'}), the manifest at ${path.join(out, 'static-pages.json')}`)
process.exit(0)
