/**
 * Vitest global setup.
 *
 * `vitest.config.ts` has always referenced this file, but it did not exist —
 * which meant `npm run test:unit` could not start at all. Created 2026-08-18
 * (§BRIDGE #B1) so the grammar suite (and the pre-existing websocket suite) can
 * actually run.
 *
 * Deliberately minimal: happy-dom already supplies the DOM. Only globals that
 * jsdom/happy-dom lack and that our units touch belong here.
 */

// happy-dom does not implement requestIdleCallback; several composables use it
// to defer non-critical work. A synchronous-ish shim keeps units deterministic.
if (typeof (globalThis as any).requestIdleCallback !== 'function') {
  ;(globalThis as any).requestIdleCallback = (cb: (deadline: any) => void): number =>
    setTimeout(() => cb({ didTimeout: false, timeRemaining: () => 50 }), 0) as unknown as number
  ;(globalThis as any).cancelIdleCallback = (id: number): void => clearTimeout(id)
}
