// @vitest-environment node
import { describe, it, expect } from 'vitest'
import postcss from 'postcss'
import tailwindcss from '@tailwindcss/postcss'
import path from 'node:path'
import tailwindV3Siblings, { v3Selector } from './tailwind-v3-siblings.js'

// §FEFRAME Tailwind 4: the sibling utilities come out in v3's form (postcss/tailwind-v3-siblings.js says why).
const FROM = path.resolve(__dirname, 'probe.css')
async function build(classes, withShim = true) {
  // the console's own dark variant (main.css), so dark: rules have the shape the build gives them
  const css = `@import "tailwindcss/theme.css";\n@custom-variant dark (&:is(.dark *));\n@source inline("${classes}");\n@tailwind utilities;\n`
  const plugins = [tailwindcss({ base: path.resolve(__dirname, 'no-sources-here') })]
  if (withShim) plugins.push(tailwindV3Siblings())
  return (await postcss(plugins).process(css, { from: FROM })).css
}
const rule = (css, sel) => {
  const i = css.indexOf(sel + ' {')
  return i < 0 ? null : css.slice(i, css.indexOf('}', i) + 1)
}

describe('tailwind-v3-siblings', () => {
  it('maps only the exact v4 sibling shape', () => {
    expect(v3Selector(':where(.space-y-2>:not(:last-child))')).toBe('.space-y-2 > :not([hidden]) ~ :not([hidden])')
    expect(v3Selector(':where(.dark\\:divide-gray-700:is(.dark *) > :not(:last-child))'))
      .toBe('.dark\\:divide-gray-700:is(.dark *) > :not([hidden]) ~ :not([hidden])')
    expect(v3Selector('.foo > .bar')).toBeNull()
    expect(v3Selector(':where(.x) > :not(:last-child)')).toBeNull()
  })

  it('control: without the shim Tailwind 4 writes the :where form (so the test below can fail)', async () => {
    const css = await build('space-y-2', false)
    expect(css).toContain(':where(.space-y-2 > :not(:last-child))')
  })

  it("writes space-y, space-x and divide-y back in v3's selector and v3's sides", async () => {
    const css = await build('space-y-2 space-x-3 divide-y divide-gray-200 dark:divide-gray-700 p-2')
    expect(css).not.toMatch(/:where\([^{]*:not\(:last-child\)\)/)
    const sy = rule(css, '.space-y-2 > :not([hidden]) ~ :not([hidden])')
    expect(sy).toMatch(/margin-top: calc\(calc\(var\(--spacing\) \* 2\) \* calc\(1 - var\(--tw-space-y-reverse\)\)\)/)
    expect(sy).toMatch(/margin-bottom: calc\(calc\(var\(--spacing\) \* 2\) \* var\(--tw-space-y-reverse\)\)/)
    expect(sy).not.toMatch(/margin-block/)
    const sx = rule(css, '.space-x-3 > :not([hidden]) ~ :not([hidden])')
    expect(sx).toMatch(/margin-left: calc\(calc\(var\(--spacing\) \* 3\) \* calc\(1 - var\(--tw-space-x-reverse\)\)\)/)
    expect(sx).toMatch(/margin-right: calc\(calc\(var\(--spacing\) \* 3\) \* var\(--tw-space-x-reverse\)\)/)
    const dy = rule(css, '.divide-y > :not([hidden]) ~ :not([hidden])')
    expect(dy).toMatch(/border-top-width: calc\(1px \* calc\(1 - var\(--tw-divide-y-reverse\)\)\)/)
    expect(dy).toMatch(/border-bottom-width: calc\(1px \* var\(--tw-divide-y-reverse\)\)/)
    expect(rule(css, '.divide-gray-200 > :not([hidden]) ~ :not([hidden])')).toMatch(/border-color/)
    expect(css).toContain('.dark\\:divide-gray-700:is(.dark *) > :not([hidden]) ~ :not([hidden])')
    expect(rule(css, '.p-2')).toMatch(/padding: calc\(var\(--spacing\) \* 2\)/)
  })

  it('splits a merged rule and rewrites only its sibling half', () => {
    const root = postcss.parse(':where(.space-y-2 > :not(:last-child)), .foo { margin-block-end: 8px; }')
    tailwindV3Siblings().OnceExit(root)
    const out = root.toString()
    expect(out).toContain('.foo { margin-block-end: 8px; }')
    expect(out).toContain('.space-y-2 > :not([hidden]) ~ :not([hidden]) { margin-top: 8px; }')
  })
})
