// V0664 C4: which edge of a horizontally scrolling tab row is cut off, so the row can fade there and say that it scrolls.
export interface Fade { left: boolean; right: boolean }
export function edgeFade(scrollLeft: number, clientWidth: number, scrollWidth: number, slack = 2): Fade {
  const max = scrollWidth - clientWidth
  if (max <= slack) return { left: false, right: false }          // it all fits: nothing is cut
  return { left: scrollLeft > slack, right: scrollLeft < max - slack }
}
