import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * V0660 (e): Discovery carries the quantum card and the quantum filters, and under off it is the page it was. The view
 * is too large to mount here (its services, stores and strips), so this reads the SFC: every quantum element is behind
 * `quantumOn` (useQuantumWorkloads: the registry-config's quantum_workloads block says shadow or on), the quantum
 * skin is bound to it, and the request carries the filters only then. What each piece does under on and off is tested
 * on the piece (QuantumCard.test.ts, discovery.quantum.test.ts); the browser load drives the whole page.
 */
const src = fs.readFileSync(path.resolve(__dirname, 'Discovery.vue'), 'utf8')
const template = src.slice(src.indexOf('<template>'), src.lastIndexOf('</template>'))

describe('Discovery and the quantum workload extension', () => {
  it('quantumOn is the registry\'s answer (useQuantumWorkloads)', () => {
    expect(src).toMatch(/const \{ served: quantumOn \} = useQuantumWorkloads\(\)/)
  })

  it('every quantum card and the filter group render only behind quantumOn', () => {
    const tags = [...template.matchAll(/<(QuantumCard|QuantumFilters)\b[^>]*>/g)].map((m) => m[0])
    expect(tags.filter((t) => t.startsWith('<QuantumCard')).length, 'the grid and the list both show it').toBe(2)
    expect(tags.filter((t) => t.startsWith('<QuantumFilters')).length).toBe(1)
    for (const t of tags) expect(t, t).toMatch(/v-if="quantumOn\b/)
    // a card shows it only for an agent the index read the extension on
    for (const t of tags.filter((x) => x.startsWith('<QuantumCard'))) expect(t).toMatch(/v-if="quantumOn && agent\.quantum"/)
  })

  it('the quantum skin is bound to quantumOn and the agent\'s facets, in the grid and the list', () => {
    expect((template.match(/'disc-agent-card--quantum': quantumOn && !!agent\.quantum/g) || []).length).toBe(2)
  })

  it('the request asks the quantum filters only where the frame serves them, and Clear all clears them', () => {
    expect(src).toMatch(/quantum: quantumOn\.value \? quantumQuery\(quantumFilters\.value\) : undefined,/)
    const clear = src.slice(src.indexOf('function clearAllFilters()'), src.indexOf('function clearAllFilters()') + 600)
    expect(clear).toMatch(/quantumFilters\.value = emptyQuantumFilters\(\)/)
  })
})
