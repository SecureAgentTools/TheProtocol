// @vitest-environment node
import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { createRequire } from 'node:module'
import { parse as parseSFC, babelParse } from 'vue/compiler-sfc'
import postcss from 'postcss'
import { compile } from 'tailwindcss'

/**
 * §FESUITE (2026-10-03, after agentvault2-09's V0558): NOTHING THE CONSOLE DRAWS NAMES A STYLE THAT DOES NOT EXIST.
 *
 * A class with no rule and a var() of a variable nobody defines both fail in silence: the build is green, no console
 * error is printed, and axe sees nothing wrong, because an element with no style is still a valid element. V0558 found
 * the Senate floor's federation tab naming 13 classes and 9 colour variables that no stylesheet defined; the tab drew
 * as bare text. This gate holds every template to definitions that exist somewhere the console loads:
 *   - an element of the page itself (not a component) whose classes, static and bound, have no rule that reaches it:
 *     no selector names them in its component's own style block, in an unscoped stylesheet, or under :deep() or
 *     :global() anywhere (a scoped rule in another component never reaches this one); Tailwind builds none of them;
 *     and no rule reaches the tag either (a bare tag rule in a global stylesheet or in its own block, or `.parent tag`
 *     under a class one of its ancestors carries). A rule that only sets the pointer draws nothing, and counts as none;
 *   - a class a :class binding sets (an object key, a ternary's branch, an array member) that no rule names: the state
 *     it was written for (an error, an "on", a variant) draws exactly like the element without it;
 *   - a class family a binding builds (`st-${status}`) with no member defined at all;
 *   - var(--x) with no fallback where --x is set nowhere: the whole declaration is dropped at computed time (a
 *     background or a transition simply is not there).
 * A var() WITH a fallback of a name nobody defines draws its fallback: not gated (a component may offer a variable
 * for its callers to set), and the theme's token list is a design decision.
 * A class that a script or a test reads as a selector ('.x' in a string) counts as defined: it is a hook.
 *
 * The findings that existed when the gate was written are in styles.defined.baseline.json, counted per file without
 * line numbers. The gate refuses a NEW finding (or one more of a kind); fixed ones may leave the baseline any time
 * (rewrite it with STYLES_BASELINE_WRITE=1 npx vitest run src/assets/styles/styles.defined.test.ts).
 */

const FE = path.resolve(__dirname, '..', '..', '..')
const SRC = path.join(FE, 'src')
const BASELINE = path.join(__dirname, 'styles.defined.baseline.json')
const requireHere = createRequire(path.join(FE, 'package.json'))

interface Sfc { file: string; source: string }
interface Sheet { file: string; css: string; scoped: boolean }
interface Model { vue: Sfc[]; sheets: Sheet[]; code: Array<{ file: string; text: string }> }
interface El { file: string; line: number; tag: string; native: boolean; classes: string[]; bound: string[]; families: string[]; unknown: boolean; ancestors: string[] }

function walk(dir: string, out: string[] = []): string[] {
  if (!fs.existsSync(dir)) return out
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === 'node_modules' || e.name.startsWith('.')) continue
    const full = path.join(dir, e.name)
    if (e.isDirectory()) walk(full, out)
    else out.push(full)
  }
  return out
}

/** The console as it is on disk: every SFC, every stylesheet (index.html's own style and Tailwind's theme too), every script and test. */
function loadModel(): Model {
  const files = walk(SRC)
  const rel = (f: string) => path.relative(FE, f)
  const vue = files.filter((f) => f.endsWith('.vue')).map((f) => ({ file: rel(f), source: fs.readFileSync(f, 'utf8') }))
  const sheets: Sheet[] = files.filter((f) => /\.(css|pcss)$/.test(f)).map((f) => ({ file: rel(f), css: fs.readFileSync(f, 'utf8'), scoped: false }))
  for (const m of fs.readFileSync(path.join(FE, 'index.html'), 'utf8').matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)) sheets.push({ file: 'index.html', css: m[1], scoped: false })
  for (const f of walk(path.join(FE, 'public')).filter((x) => x.endsWith('.css'))) sheets.push({ file: rel(f), css: fs.readFileSync(f, 'utf8'), scoped: false })
  sheets.push({ file: 'tailwindcss/theme.css', css: fs.readFileSync(requireHere.resolve('tailwindcss/theme.css'), 'utf8'), scoped: false })
  const code = [...files.filter((f) => /\.(ts|js|mjs)$/.test(f)), ...walk(path.join(FE, 'e2e')).filter((f) => f.endsWith('.ts'))]
    .filter((f) => f !== __filename)
    .map((f) => ({ file: rel(f), text: fs.readFileSync(f, 'utf8') }))
  return { vue, sheets, code }
}

const unescape = (s: string) => s.replace(/\\(.)/g, '$1')
const classesIn = (selector: string) => [...selector.matchAll(/\.((?:\\.|[\w-])+)/g)].map((m) => unescape(m[1])).filter((c) => !/^\d/.test(c))

/** The tag a selector's last compound names bare (`.box p`, `button:hover`), and the classes the rest of it names. */
function tagRule(selector: string): { tag: string; context: string[] } | null {
  const parts = selector.replace(/\([^()]*\)/g, '()').split(/\s*[\s>+~]\s*/).filter(Boolean)
  const last = parts.pop() || ''
  const m = last.replace(/::?[\w-]+(\(\))?/g, '').replace(/\[[^\]]*\]/g, '').match(/^([a-zA-Z][\w-]*)$/)
  if (!m) return null
  // what the rule hangs under: the page's own wrappers (html, body, #app, the theme classes on body) reach everything;
  // an ancestor named some other way ([class*="-table-wrap"] > table) cannot be matched, so the rule is not counted
  const wrapper = (a: string) => (a.replace(/::?[\w-]+(\(\))?/g, '').match(/[.#]?[\w-]+/g) || []).every((x) => /^(html|body|#app|\.theme-[\w-]+|\.dark)$/.test(x))
  const ancestors = parts.filter((a) => !wrapper(a))
  const context = classesIn(ancestors.join(' '))
  if (ancestors.length && !context.length) return null
  return { tag: m[1].toLowerCase(), context }
}

const INERT = new Set(['cursor', 'pointer-events', 'user-select', '-webkit-user-select', 'touch-action', '-webkit-tap-highlight-color'])

interface Defs {
  classes: Set<string>                          // named by an unscoped sheet, or by :deep()/:global() in a scoped one
  fileClasses: Map<string, Set<string>>         // named by a component's own scoped block: they style that component only
  vars: Set<string>
  globalTags: Set<string>                       // a bare tag rule in an unscoped sheet
  fileTags: Map<string, Set<string>>            // a bare tag rule in a component's own scoped block
  contextTags: Map<string, Set<string>>         // tag -> classes under which an unscoped rule styles it
  fileContextTags: Map<string, Map<string, Set<string>>>  // the same, per component, from its scoped block
  varUses: Array<{ file: string; name: string; fallback: boolean }>
  hooks: Set<string>
}

function definitions(model: Model, sfcSheets: Sheet[]): Defs {
  const d: Defs = { classes: new Set(), fileClasses: new Map(), vars: new Set(), globalTags: new Set(), fileTags: new Map(), contextTags: new Map(), fileContextTags: new Map(), varUses: [], hooks: new Set() }
  const into = <T>(m: Map<string, T>, k: string, make: () => T): T => { if (!m.has(k)) m.set(k, make()); return m.get(k)! }
  for (const s of [...model.sheets, ...sfcSheets]) {
    let root: postcss.Root
    try { root = postcss.parse(s.css) } catch { continue }
    root.walkRules((r) => {
      const parent = r.parent as postcss.AtRule | undefined
      if (parent?.type === 'atrule' && /keyframes/.test(parent.name)) return
      // a rule that only changes the pointer (main.css's `button:not(:disabled) { cursor: pointer }`) draws nothing
      const draws = r.nodes.some((n) => n.type === 'decl' && !INERT.has(n.prop))
      for (const sel of r.selectors) {
        // a scoped block styles its own component; :deep() and :global() reach further (counted everywhere)
        const local = s.scoped && !/:deep\(|::v-deep|:global\(|>>>|\/deep\//.test(sel)
        for (const c of classesIn(sel)) (local ? into(d.fileClasses, s.file, () => new Set<string>()) : d.classes).add(c)
        const t = draws ? tagRule(sel) : null
        if (!t) continue
        if (t.context.length) {
          const ctx = local ? into(d.fileContextTags, s.file, () => new Map<string, Set<string>>()) : d.contextTags
          for (const c of t.context) into(ctx, t.tag, () => new Set<string>()).add(c)
        } else if (local) into(d.fileTags, s.file, () => new Set<string>()).add(t.tag)
        else d.globalTags.add(t.tag)
      }
    })
    root.walkDecls((decl) => {
      if (decl.prop.startsWith('--')) d.vars.add(decl.prop.slice(2))
      for (const m of decl.value.matchAll(/var\(\s*--([\w-]+)\s*(,)?/g)) d.varUses.push({ file: s.file, name: m[1], fallback: !!m[2] })
    })
    root.walkAtRules('property', (a) => { if (a.params.trim().startsWith('--')) d.vars.add(a.params.trim().slice(2)) })
  }
  // variables set from code or a template (an object key, setProperty, an inline style), and var() used there
  const texts = [...model.code.map((c) => c.text), ...model.vue.map((v) => v.source.replace(/<style[^>]*>[\s\S]*?<\/style>/g, ''))]
  const files = [...model.code.map((c) => c.file), ...model.vue.map((v) => v.file)]
  texts.forEach((t, i) => {
    for (const m of t.matchAll(/['"`]--([\w-]+)['"`]\s*[:,)\]]/g)) d.vars.add(m[1])
    for (const m of t.matchAll(/(?:^|[\s;{'"`])--([\w-]+)\s*:\s*(?!\s*[,)])/gm)) d.vars.add(m[1])
    if (!/\.test\.ts$|\.spec\.ts$|^e2e\//.test(files[i])) {
      for (const m of t.matchAll(/var\(\s*--([\w-]+)(\$\{)?\s*(,)?/g)) if (!m[2]) d.varUses.push({ file: files[i], name: m[1], fallback: !!m[3] })
    }
    // a class read as a selector from a string ('.x', '.a .x'): a hook
    for (const s of t.matchAll(/'([^'\n]*)'|"([^"\n]*)"|`([^`\n]*)`/g)) {
      const v = s[1] ?? s[2] ?? s[3]
      if (v.includes('.')) for (const m of v.matchAll(/(?:^|[\s>+~,(:])\.([A-Za-z_-][\w-]*)/g)) d.hooks.add(m[1])
    }
  })
  return d
}

/** The class names a :class expression can produce; a call or a variable makes the element's classes unknown. */
function boundClasses(exp: string): { tokens: string[]; families: string[]; unknown: boolean } {
  const out = { tokens: [] as string[], families: [] as string[], unknown: false }
  let ast: any
  try { ast = (babelParse(`(${exp})`, { plugins: ['typescript'] }).program.body[0] as any).expression } catch { out.unknown = true; return out }
  const words = (s: string) => s.split(/\s+/).filter(Boolean)
  const visit = (n: any): void => {
    if (!n) return
    switch (n.type) {
      case 'StringLiteral': out.tokens.push(...words(n.value)); break
      case 'TemplateLiteral':
        n.quasis.forEach((q: any, i: number) => {
          const raw: string = q.value.cooked ?? q.value.raw
          const ws = words(raw)
          const gluedAfter = i < n.quasis.length - 1 && raw.length > 0 && !/\s$/.test(raw)
          const gluedBefore = i > 0 && raw.length > 0 && !/^\s/.test(raw)
          ws.forEach((w, j) => {
            if (j === ws.length - 1 && gluedAfter) out.families.push(w)
            else if (j === 0 && gluedBefore) out.unknown = true
            else out.tokens.push(w)
          })
          if (i < n.quasis.length - 1 && !gluedAfter) out.unknown = true
        })
        break
      case 'ObjectExpression':
        for (const p of n.properties) {
          if (p.type !== 'ObjectProperty' || p.computed) { out.unknown = true; continue }
          if (p.key.type === 'Identifier') out.tokens.push(p.key.name)
          else if (p.key.type === 'StringLiteral') out.tokens.push(...words(p.key.value))
        }
        break
      case 'ArrayExpression': n.elements.forEach(visit); break
      case 'ConditionalExpression': visit(n.consequent); visit(n.alternate); break
      case 'LogicalExpression': if (n.operator === '&&') visit(n.right); else { visit(n.left); visit(n.right) } break
      case 'BinaryExpression':
        if (n.operator === '+' && n.left.type === 'StringLiteral' && n.left.value && !/\s$/.test(n.left.value)) out.families.push(words(n.left.value).pop() || '')
        else out.unknown = true
        break
      case 'TSAsExpression': case 'TSNonNullExpression': case 'ParenthesizedExpression': visit(n.expression); break
      case 'NullLiteral': case 'BooleanLiteral': break
      default: out.unknown = true
    }
  }
  visit(ast)
  out.families = out.families.filter(Boolean)
  return out
}

const parsedSfc = new WeakMap<Sfc, { els: El[]; sheets: Sheet[] }>()
function elementsOf(sfc: Sfc): { els: El[]; sheets: Sheet[] } {
  const hit = parsedSfc.get(sfc)
  if (hit) return hit
  const { descriptor } = parseSFC(sfc.source, { filename: sfc.file })
  const sheets = descriptor.styles.map((s) => ({ file: sfc.file, css: s.content, scoped: !!s.scoped }))
  const els: El[] = []
  const visit = (n: any, ancestors: string[]): void => {
    let next = ancestors
    if (n.type === 1) {
      const el: El = { file: sfc.file, line: n.loc.start.line, tag: n.tag, native: n.tagType === 0, classes: [], bound: [], families: [], unknown: false, ancestors }
      for (const p of n.props) {
        if (p.type === 6 && p.name === 'class' && p.value) el.classes.push(...p.value.content.split(/\s+/).filter(Boolean))
        if (p.type === 7 && p.name === 'bind' && p.arg?.content === 'class') {
          if (!p.exp) { el.unknown = true; continue }
          const b = boundClasses(p.exp.content)
          el.bound.push(...b.tokens); el.families.push(...b.families); if (b.unknown) el.unknown = true
        }
      }
      if (el.classes.length || el.bound.length || el.families.length) els.push(el)
      next = [...ancestors, ...el.classes, ...el.bound]
    }
    for (const c of n.children || []) visit(c, next)
  }
  if (descriptor.template?.ast) visit(descriptor.template.ast, [])
  parsedSfc.set(sfc, { els, sheets })
  return { els, sheets }
}

/** Every finding, as a key without a line number; `where` keeps one line per key for the message. */
function analyse(model: Model, tailwind: Set<string>): { keys: string[]; where: Map<string, string> } {
  const parsed = model.vue.map(elementsOf)
  const d = definitions(model, parsed.flatMap((p) => p.sheets))
  const MARKERS = new Set(['group', 'peer', 'dark'])
  const defined = (c: string, file: string) => d.classes.has(c) || !!d.fileClasses.get(file)?.has(c) || tailwind.has(c) || d.hooks.has(c)
    || MARKERS.has(c) || /^(group|peer)\//.test(c)
  const keys: string[] = []
  const where = new Map<string, string>()
  const add = (key: string, loc: string) => { keys.push(key); if (!where.has(key)) where.set(key, loc) }
  for (const el of parsed.flatMap((p) => p.els)) {
    const loc = `${el.file}:${el.line}`
    const under = (ctx: Set<string> | undefined) => [...(ctx || [])].some((c) => el.ancestors.includes(c))
    const tagReached = d.globalTags.has(el.tag) || !!d.fileTags.get(el.file)?.has(el.tag)
      || under(d.contextTags.get(el.tag)) || under(d.fileContextTags.get(el.file)?.get(el.tag))
    const styled = [...el.classes, ...el.bound].some((c) => defined(c, el.file)) || el.families.length > 0 || el.unknown || tagReached
    if (el.native && el.classes.length && !styled) add(`element|${el.file}|${el.tag}|${[...el.classes].sort().join(' ')}`, loc)
    for (const c of el.bound) if (!defined(c, el.file)) add(`bound|${el.file}|${c}`, loc)
    for (const f of el.families) {
      const any = [...d.classes, ...(d.fileClasses.get(el.file) || []), ...tailwind].some((c) => c.startsWith(f))
      if (!any) add(`family|${el.file}|${f}*`, loc)
    }
  }
  for (const u of d.varUses) if (!u.fallback && !d.vars.has(u.name)) add(`var|${u.file}|--${u.name}`, u.file)
  return { keys, where }
}

/** Which of the candidate class names Tailwind 4 builds a rule for, with the console's own main.css. */
async function tailwindClasses(candidates: Set<string>): Promise<Set<string>> {
  const dir = path.join(SRC, 'assets', 'styles')
  const compiler = await compile(fs.readFileSync(path.join(dir, 'main.css'), 'utf8'), {
    base: dir,
    loadStylesheet: async (id: string, base: string) => {
      const p = id.startsWith('.') ? path.resolve(base, id) : requireHere.resolve(id)
      return { path: p, base: path.dirname(p), content: fs.readFileSync(p, 'utf8') }
    },
  })
  const out = new Set<string>()
  postcss.parse(compiler.build([...candidates])).walkRules((r) => { for (const c of classesIn(r.selector)) out.add(c) })
  return out
}

const count = (keys: string[]) => keys.reduce<Record<string, number>>((m, k) => ((m[k] = (m[k] || 0) + 1), m), {})

describe('every class and variable the console names is defined', () => {
  it('the gate sees each case, and stays quiet on what is styled (controls)', () => {
    const source = `<template>
  <div class="a-box">
    <h3 class="a-gone">no rule names it</h3>
    <h4 class="a-themed">a body-level theme rule reaches it</h4>
    <button class="a-plain">only the global cursor rule reaches it</button>
    <p class="a-under">styled by .a-box p</p>
    <span class="px-2">a utility</span>
    <span class="a-hook">read by a script</span>
    <MyThing class="a-component" />
    <button class="a-btn" :class="{ 'a-btn--on': on, 'a-btn--off': !on }">b</button>
    <span :class="ok ? 'a-ok' : 'a-bad'">x</span>
    <span :class="\`a-st-\${s}\`">family with no member</span>
    <span :class="\`a-tone-\${s}\`">family with a member</span>
    <span :class="pick(x)">unknown</span>
    <table class="b-table">another component's scoped rule</table>
    <i class="b-deep">reached by another component's :deep()</i>
    <td class="b-cell">only [class*="-wrap"] > td names the tag</td>
  </div>
</template>
<style scoped>
.a-box { color: var(--a-nope); background: var(--a-nope-fb, red); border-color: var(--a-set); }
.a-box p { margin: 0; }
.a-btn, .a-btn--on, .a-ok, .a-tone-hot { color: red; }
</style>`
    const model: Model = {
      vue: [{ file: 'X.vue', source }, { file: 'Y.vue', source: '<template><p class="b-own">y</p></template><style scoped>.b-own, .b-table { color: red } .y :deep(.b-deep) { color: red }</style>' }],
      sheets: [{ file: 'g.css', css: ':root { --a-set: 1px; } button:not(:disabled) { cursor: pointer; } [class*="-wrap"] > td { padding: 0; } body.theme-x h4 { color: red }', scoped: false }],
      code: [{ file: 'x.ts', text: "el.querySelector('.a-hook')" }],
    }
    const { keys } = analyse(model, new Set(['px-2']))
    expect(keys.sort()).toEqual([
      'bound|X.vue|a-bad',
      'bound|X.vue|a-btn--off',
      'element|X.vue|button|a-plain',
      'element|X.vue|h3|a-gone',
      'element|X.vue|table|b-table',
      'element|X.vue|td|b-cell',
      'family|X.vue|a-st-*',
      'var|X.vue|--a-nope',
    ])
  })

  it('no template names a class or variable that nothing defines, beyond the baseline', async () => {
    const model = loadModel()
    const candidates = new Set<string>()
    for (const v of model.vue) for (const e of elementsOf(v).els) for (const c of [...e.classes, ...e.bound]) candidates.add(c)
    const { keys, where } = analyse(model, await tailwindClasses(candidates))
    const now = count(keys)
    expect(model.vue.length, 'the gate read the console\'s components').toBeGreaterThan(300)
    if (process.env.STYLES_BASELINE_WRITE) {
      const sorted = Object.fromEntries(Object.entries(now).sort(([a], [b]) => a.localeCompare(b)))
      fs.writeFileSync(BASELINE, JSON.stringify({ note: 'styles.defined.test.ts: the findings that existed when they were last counted; a new one fails the gate', findings: sorted }, null, 1) + '\n')
    }
    const base: Record<string, number> = JSON.parse(fs.readFileSync(BASELINE, 'utf8')).findings
    const fresh = Object.entries(now)
      .filter(([k, n]) => n > (base[k] || 0))
      .map(([k, n]) => `${where.get(k)}  ${k}${base[k] ? ` (${n} now, ${base[k]} in the baseline)` : ''}`)
    expect(fresh, 'add the rule, drop the class or variable, or (a hook, a deliberate case) add it to the baseline with the reason in the commit').toEqual([])
  }, 120_000)
})
