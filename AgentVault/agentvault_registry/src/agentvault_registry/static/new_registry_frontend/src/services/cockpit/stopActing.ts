/**
 * §COCKPITSTOP — which of three things the STOP pane says about the header selection.
 *
 * 🔴 EXTRACTED BECAUSE THIS DECISION HAS BEEN WRONG TWICE. First it was a general
 * disclaimer ("nothing here follows the agent you are acting as"), which was true and did
 * not land. Then it was a sentence gated on `v-if="actingName"`, which renders NOTHING when
 * no agent is selected — and no agent selected was his ORIGINAL report. A branch that
 * decides what a money-adjacent pane claims about the reader's own selection belongs in a
 * function that can be tested, not in a template ternary (the `services/chat/callTarget.ts`
 * precedent).
 *
 * ⚠ The live browser can only ever exercise the `unselected` branch here: selecting an
 * agent requires its client_id/client_secret in THAT browser's vault, so a fresh automated
 * context is structurally unable to pick one. That is why this is unit-tested.
 */
export type StopActingState = 'unselected' | 'selected-with-mandate' | 'selected-no-mandate'

export function stopActingState(
  actingName: string | null | undefined,
  actingHasMandate: boolean,
): StopActingState {
  // A name that is absent, empty or whitespace is NOT a selection. Trimming matters: the
  // switcher can hold an agent whose card carries a blank name, and `' '` is truthy.
  const named = String(actingName ?? '').trim().length > 0
  if (!named) return 'unselected'
  return actingHasMandate ? 'selected-with-mandate' : 'selected-no-mandate'
}
