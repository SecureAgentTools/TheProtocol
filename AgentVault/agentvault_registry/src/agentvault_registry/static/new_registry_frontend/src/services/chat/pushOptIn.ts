/**
 * V0652 (z) (order gwo_2b801ba5d3a2fba7ae5e1909): what the thread's push opt-in card turns on. "Push only what needs
 * you" (his plan, item 5): a mention, a direct message, a stranger's first message, an approval you decide, a ping. A
 * room's other traffic stays in the app (chat.message is in-app only on the registry); the card used to turn pushes on
 * for all of it. The server pushes the first four by default as well; the rows make the tap win over a channel master
 * switched off earlier.
 */
export const PUSH_NEEDS_TYPES = ['chat.mention', 'chat.direct', 'chat.request', 'chat.approval_requested', 'chat.ping'] as const

export interface PrefRow { type_key: string; channel: 'push_mobile' | 'push_desktop'; enabled: boolean }

export function pushOptInRows(): PrefRow[] {
  return PUSH_NEEDS_TYPES.flatMap((type_key) => [
    { type_key, channel: 'push_mobile' as const, enabled: true },
    { type_key, channel: 'push_desktop' as const, enabled: true },
  ])
}
