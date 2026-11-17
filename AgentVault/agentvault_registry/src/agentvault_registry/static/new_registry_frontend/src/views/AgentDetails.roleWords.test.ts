import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0662 console polish, item 5: the agent page's roles line and its role chips read each role through the console's
 * words (services/agent/roleLabel), never the API name raw. The view is too large to mount here, so this reads the
 * SFC; the words themselves are tested on the module. Red on f569f6a6e: authz.roles.join(', ') and {{ r }}.
 */
const src = fs.readFileSync(path.resolve(__dirname, 'AgentDetails.vue'), 'utf8')
const template = src.slice(src.indexOf('<template>'), src.lastIndexOf('</template>'))

describe('the agent page\'s roles', () => {
  it('no role prints by its API name', () => {
    expect(template).not.toMatch(/authz\.roles\.join\(/)
    expect(template).not.toMatch(/v-for="r in authz\.roles"[^>]*>\{\{\s*r\s*\}\}/)
  })
  it('the roles line and the chips go through roleLabel, the chip naming its role on hover', () => {
    expect(src).toMatch(/import \{[^}]*\broleLabel\b[^}]*\} from '@\/services\/agent\/roleLabel'/)
    expect(template).toMatch(/authz\.roles\.map\(\(r[^)]*\) => roleLabel\(r, t\)\)\.join\(/)
    expect(template).toMatch(/v-for="r in authz\.roles"[^>]*:title="roleTitle\(r, t\)[^"]*"[^>]*>\{\{\s*roleLabel\(r, t\)\s*\}\}/)
  })
})
