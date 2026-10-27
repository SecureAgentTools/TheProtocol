import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import path from 'node:path'

/**
 * §LEDGERGATE (V0601): My Agents' header says only what its fleet read answered. Over a read that failed it said
 * "0 agents deployed" and zero balances above the notice that says the read failed (journal 51's figures, Sandbox
 * Beta). The view is too large to mount here, so this reads its template: the count and the stats bar stand behind
 * fleetUnread, and fleetUnread is the same condition as the notice's. RED on fe/batch-v0600.
 */
const src = readFileSync(path.resolve(__dirname, 'MyAgents.vue'), 'utf-8')

describe("My Agents' header over a fleet read that failed", () => {
  it('the count and the stats bar are drawn only over a read that answered', () => {
    expect(src).toMatch(/<div v-if="!fleetUnread" class="fleet-subtitle">\{\{ agents\.length \}\} agents deployed<\/div>/)
    expect(src).toMatch(/<div v-if="!fleetUnread" class="fleet-stats"/)
    expect(src).not.toMatch(/<div class="fleet-subtitle">\{\{ agents\.length \}\}/)
  })

  it("fleetUnread is the notice's own condition", () => {
    expect(src).toMatch(/const fleetUnread = computed\(\(\) => agentStore\.myAgentsFailed && agents\.value\.length === 0\)/)
    expect(src).toMatch(/v-else-if="agentStore\.myAgentsFailed && agents\.length === 0"[^>]*data-testid="mya-fleet-read-failed"/)
  })
})
