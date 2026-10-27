// Galactic Command per-registry sessions: since §FEFRAME W3 (V0504) THE session hub (stores/sessions.ts).
//
// One state for every registry session the console holds: Galactic Command, the Bridge, the vault import, the
// reconcile modal and the multi-frame facade all read the hub through this name, so a session opened in one is the
// session the others see. Kept as a name for one release; W4 moves the importers to `useSessionHub` and deletes it.
export { useSessionHub as useCommandSessions } from './sessions'
export type { CommandSession } from './sessions'
