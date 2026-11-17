import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * V0662 sidebar (order gwo_0feb166a01e2ff611e154361): the sidebar is the nav table and its one rule, rendered. The
 * sidebar is too large to mount here, so this reads it; the rule and the pins are tested on their modules
 * (services/nav/navAccess, navPins, navTable) and the browser load drives the whole thing.
 *  - the table and the rule come from services/nav (no table, no hand list of public paths, no admin flags of its own);
 *  - a Pinned block at the top, from the shared pins; every entry has a pin toggle saying its state;
 *  - the administration group renders one sub-group per flag (adminSubgroups);
 *  - Pocket mode is also a switch in the footer.
 * Red on f569f6a6e: none of it.
 */
const src = readFileSync(path.resolve(__dirname, 'DashboardSidebar.vue'), 'utf-8')
const template = src.slice(src.indexOf('<template>'), src.lastIndexOf('</template>'))

describe('the sidebar renders the nav table and its one rule', () => {
  it('reads the table, the rule and the pins from services/nav', () => {
    expect(src).toMatch(/import \{[^}]*\bNAV_GROUPS\b[^}]*\} from '@\/services\/nav\/navTable'/)
    expect(src).toMatch(/import \{[^}]*\bnavItemState\b[^}]*\} from '@\/services\/nav\/navAccess'/)
    expect(src).toMatch(/import \{[^}]*\buseNavPins\b[^}]*\} from '@\/services\/nav\/navPins'/)
    expect(src).not.toMatch(/const navGroups: NavGroup\[\] = \[/)
    expect(src).not.toMatch(/const PUBLIC_PATHS/)
    expect(src).not.toMatch(/requiredSubFlag/)
  })

  it('a Pinned block at the top, from the shared pins', () => {
    const pinned = template.indexOf('data-testid="nav-pinned"')
    expect(pinned).toBeGreaterThan(-1)
    expect(pinned).toBeLessThan(template.indexOf('v-for="group in'))
    expect(template).toMatch(/v-for="(?:item|\(item, index\)) in pinnedItems"/)
  })

  it('every entry has a pin toggle that says its state', () => {
    const toggles = [...template.matchAll(/<button[^>]*data-testid="nav-pin-toggle"[^>]*>/g)].map((m) => m[0])
    expect(toggles.length).toBeGreaterThanOrEqual(2)   // the pinned block and the groups
    for (const t of toggles) {
      expect(t).toMatch(/:aria-pressed="/)
      expect(t).toMatch(/:aria-label="/)
    }
  })

  it('the administration group renders one sub-group per flag', () => {
    expect(template).toMatch(/data-testid="nav-admin-subgroup"/)
    expect(src).toMatch(/adminSubgroups\(/)
  })

  it('Pocket mode is also a switch in the footer', () => {
    const footer = template.slice(template.indexOf('<!-- Bottom Section -->'))
    expect(footer).toMatch(/data-testid="nav-pocket-switch"/)
  })
})
