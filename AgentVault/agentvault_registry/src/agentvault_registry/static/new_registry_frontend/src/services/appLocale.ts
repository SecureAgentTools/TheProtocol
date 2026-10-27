import { getLocale } from '@/i18n'

/**
 * §COCKPITTILES-2 — THE APP'S LOCALE, for every `toLocale*String` in the app.
 *
 * 🔴 WHY. `toLocaleString()` with no locale — or with `undefined`, which is the same thing
 * spelled longer — formats in the **operating system's** locale, never the app's. On the
 * Commander's machine (German OS, English UI) that rendered `22,1 Mio.`, `101,06 AVT` and
 * printed 3,330 refusals as `3.330`, beside server strings in plain English. A hardcoded
 * `'en-US'` is the mirror defect: correct for him today, wrong for every German reader.
 *
 * The cockpit routes numbers through `services/cockpit/num.ts`, which also owns the
 * compact/exact policy. This module exists for the other ~130 files, where the call shape
 * is fine and only the LOCALE was wrong: pass `appLocale()` and the same call is correct.
 *
 * ⚠ Never re-add a bare `toLocaleString()`. The gate
 * (`scratchpad/verify_locale_sweep.py`) asserts every `toLocale*String(` in `src/` opens
 * with a locale argument.
 */
export function appLocale(): string {
  try {
    const l = getLocale()
    return typeof l === 'string' && l ? l : 'en'
  } catch {
    // A locale that cannot be read must not blank a number.
    return 'en'
  }
}
