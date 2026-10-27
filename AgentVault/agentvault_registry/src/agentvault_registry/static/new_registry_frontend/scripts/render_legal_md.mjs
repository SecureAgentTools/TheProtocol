#!/usr/bin/env node
/**
 * §LEGALKIT: render PRODUCTION_DOCS/12_LEGAL/*.md from the ONE source, content/legal/suiteV2.ts.
 * Usage: node static/new_registry_frontend/scripts/render_legal_md.mjs <suiteV2.ts> <out dir> [--check]
 * --check renders to memory and exits 1 if any file on disk differs (the CI drift gate).
 * Tokens ({PROVIDER_FULL}, {LOCAL_UNIT}, ...) are kept literally: the markdown is the source's mirror, not a rendering.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs'
import { join, resolve, dirname } from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const [,, src, outDir, flag] = process.argv
if (!src || !outDir) { console.error('usage: render_legal_md.mjs <suiteV2.ts> <out dir> [--check]'); process.exit(2) }
const require = createRequire(import.meta.url)
const esbuild = require(resolve(dirname(src), '../../../node_modules/esbuild'))
const built = esbuild.transformSync(readFileSync(src, 'utf8'), { loader: 'ts', format: 'esm' }).code
const tmp = join(outDir, '.suiteV2.render.mjs')
if (!existsSync(outDir)) mkdirSync(outDir, { recursive: true })
writeFileSync(tmp, built)
const mod = await import(pathToFileURL(tmp).href + `?t=${Date.now()}`)
// §LEGALKIT B8: the German source (suiteV2.de.ts) exports a PARTIAL set; the pages it lacks are not rendered there.
const partial = !mod.LEGAL_SUITE_V2
const suite = mod.LEGAL_SUITE_V2 ?? mod.LEGAL_SUITE_V2_DE
const srcName = src.replace(/\\/g, '/').split('/').pop()
const FILES = {
  terms: '01_TERMS_OF_SERVICE_v2.md', privacy: '02_PRIVACY_POLICY_v2.md', imprint: '03_IMPRESSUM_v2.md',
  disclaimer: '04_RISK_NOTICE_v2.md', cookies: '05_COOKIE_POLICY_v2.md', dpa: '06_DPA_v2.md', license: '07_LICENSE_NOTICE_v2.md',
  operators: '08_FEDERATION_OPERATOR_TERMS_v1.md', sla: '09_SLA_NOTICE_v2.md', evaluation: '10_EVALUATION_ACCESS_TERMS.md',
  security: '11_VULNERABILITY_DISCLOSURE_POLICY.md', dsa: '12_DIGITAL_SERVICES_ACT_INFORMATION.md', changes: '13_LEGAL_CHANGES.md',
}
const unesc = (s) => String(s ?? '').replace(/\\n/g, '\n')
function render(key, page) {
  const out = []
  out.push(`# ${page.title}`, '', `_${page.subtitle}_`, '',
    `**Version ${page.version}** · Effective: ${page.effectiveDate} · Jurisdiction: ${page.jurisdiction} · Owner: ${page.owner}`, '',
    `> Generated from \`content/legal/${srcName}\` (key \`${key}\`) by \`scripts/legal/render_legal_md.mjs\`. Do not edit here; edit the source and re-render. Tokens in braces resolve from the frame's provider facts at render time.`, '')
  for (const s of page.sections) {
    out.push(`## ${s.number ? s.number + ' ' : ''}${s.title}`, '')
    if (s.plain) out.push(`> **In plain words:** ${unesc(s.plain)}`, '')
    if (s.critical) out.push(`> ⚠ **${unesc(s.critical)}**`, '')
    if (s.important) out.push(`> **${unesc(s.important)}**`, '')
    if (s.content) out.push(unesc(s.content), '')
    for (const sub of s.subsections || []) {
      out.push(`### ${sub.title}`, '', unesc(sub.content), '')
      for (const it of sub.items || []) out.push(`* ${unesc(it)}`)
      if (sub.items?.length) out.push('')
    }
    for (const it of s.items || []) out.push(`* ${unesc(it)}`)
    if (s.items?.length) out.push('')
  }
  return out.join('\n').replace(/\n{3,}/g, '\n\n') + '\n'
}
let drift = 0
for (const [key, file] of Object.entries(FILES)) {
  const page = suite[key]
  if (!page) { if (partial) continue; console.error(`missing page ${key}`); process.exit(3) }
  const text = render(key, page)
  const path = join(outDir, file)
  if (flag === '--check') {
    const cur = existsSync(path) ? readFileSync(path, 'utf8') : ''
    if (cur !== text) { drift++; console.log(`DRIFT ${file}`) }
  } else {
    writeFileSync(path, text)
    console.log(`wrote ${file} (${text.length} bytes)`)
  }
}
try { require('node:fs').unlinkSync(tmp) } catch {}
if (flag === '--check') { console.log(drift ? `${drift} file(s) drifted` : 'no drift'); process.exit(drift ? 1 : 0) }
