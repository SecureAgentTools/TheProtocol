/*
  Tailwind 4 changed how space-x/y-* and divide-x/y-* reach the children (§FEFRAME, 2026-10-01):
    v3  .space-y-2 > :not([hidden]) ~ :not([hidden])  { margin-top: S }       specificity 0,3,0, on children 2..n
    v4  :where(.space-y-2 > :not(:last-child))          { margin-bottom: S }    specificity 0,   on children 1..n-1
  At zero specificity every margin the app's own CSS or a child's m*-class sets now wins over the spacing, and the
  margin moved to the other side of the child: AdminDistributionPanel's first row closed from 20 px to 8 px, ForexDesk's
  result icon lost its 12 px, and 104 class uses in 29 files (the 2FA dialogs among them) would each need checking.
  This plugin runs after @tailwindcss/postcss and writes those rules back in v3's form: v3's selector (so v3's
  specificity and v3's children) and v3's physical sides. Only rules of the exact v4 shape are touched; everything else
  passes through. Dropping it later, to take v4's behaviour on purpose, is one line in postcss.config.js.
*/
const SHAPE = /^:where\((.+?)\s*>\s*:not\(:last-child\)\)$/

// v4 logical side -> v3 physical side, with v3's direction: v3 spaced the LATER sibling, so the value v4 puts at the
// end of child k goes to the start of child k+1.
const SWAP = {
  'margin-block-start': 'margin-bottom',
  'margin-block-end': 'margin-top',
  'margin-inline-start': 'margin-right',
  'margin-inline-end': 'margin-left',
  'border-top-width': 'border-bottom-width',
  'border-bottom-width': 'border-top-width',
  'border-inline-start-width': 'border-right-width',
  'border-inline-end-width': 'border-left-width',
  'border-left-width': 'border-right-width',
  'border-right-width': 'border-left-width',
}

export function v3Selector(selector) {
  const m = SHAPE.exec(selector.trim())
  return m ? `${m[1]} > :not([hidden]) ~ :not([hidden])` : null
}

export function rewrite(rule) {
  const sels = rule.selectors
  const mapped = sels.map(v3Selector)
  if (mapped.every((s) => s === null)) return false
  if (mapped.some((s) => s === null)) {
    // a merged rule holding both kinds: split it, rewrite only the sibling half
    rule.before(rule.clone({ selectors: sels.filter((_, i) => mapped[i] === null) }))
  }
  rule.selectors = mapped.filter((s) => s !== null)
  rule.walkDecls((d) => {
    if (SWAP[d.prop]) d.prop = SWAP[d.prop]
  })
  return true
}

export default function tailwindV3Siblings() {
  return {
    postcssPlugin: 'tailwind-v3-siblings',
    // OnceExit: after @tailwindcss/postcss (listed first) has written the utilities
    OnceExit(root) {
      root.walkRules((rule) => {
        rewrite(rule)
      })
    },
  }
}
tailwindV3Siblings.postcss = true
