// V0664 C3 (order gwo_4110e12c11a69a93de878829): a recipe's sentences carry `inline code` from their README; the page shows those
// spans as code elements and everything else as text, so nothing from a README is ever rendered as HTML.
export interface Part { code: boolean; text: string }

export function inline(s: string): Part[] {
  const out: Part[] = []
  const re = /`([^`]+)`/g
  let at = 0
  for (let m = re.exec(s); m; m = re.exec(s)) {
    if (m.index > at) out.push({ code: false, text: s.slice(at, m.index) })
    out.push({ code: true, text: m[1]! })
    at = m.index + m[0].length
  }
  if (at < s.length) out.push({ code: false, text: s.slice(at) })
  return out
}
