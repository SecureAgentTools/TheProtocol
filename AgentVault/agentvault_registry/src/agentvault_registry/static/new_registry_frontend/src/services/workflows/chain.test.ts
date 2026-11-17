import { createHash } from 'node:crypto'
import { describe, expect, it } from 'vitest'
import { GENESIS, verifyChain } from './chain'

function build(steps: Array<[string, string]>) {
  let prev = GENESIS
  return steps.map(([step, output_hash]) => {
    const receipt = createHash('sha256').update(`${prev}|${step}|${output_hash}`).digest('hex')
    const link = { step, output_hash, prev, receipt }
    prev = receipt
    return link
  })
}

describe('verifyChain', () => {
  it('accepts a chain built the way the server builds it, and an empty one', async () => {
    expect(await verifyChain(build([['build', 'aa'], ['verify', 'bb']]))).toEqual({ ok: true, why: null })
    expect(await verifyChain([])).toEqual({ ok: true, why: null })
  })
  it('catches an edited output, a dropped link and a reordered pair', async () => {
    const c = build([['build', 'aa'], ['verify', 'bb'], ['meter', 'cc']])
    expect((await verifyChain([c[0], { ...c[1], output_hash: 'zz' }, c[2]])).ok).toBe(false)
    expect((await verifyChain([c[0], c[2]])).ok).toBe(false)
    expect((await verifyChain([c[1], c[0], c[2]])).ok).toBe(false)
  })
})
