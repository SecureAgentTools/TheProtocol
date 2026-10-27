/**
 * §FESUITE V0597 (2026-10-11): a guided tour names the frame's own unit. The tours said "AVT" (and the retired JDAY and
 * BVT as the other frames' units) on frames whose unit is ECU, ACU, SBXA or SBXB. A tour's text carries {unit}; the
 * places that show it (GuidedTour.vue, TutorialHub.vue) fill it with the frame's unit. While the frame has not answered
 * yet the words say "the frame's unit", never another frame's name.
 */
const UNIT_TOKEN = /\{unit\}/g

export function withUnit(text: string | null | undefined, unit: string | null | undefined): string {
  const u = String(unit ?? '').trim()
  return String(text ?? '').replace(UNIT_TOKEN, u || "the frame's unit")
}
