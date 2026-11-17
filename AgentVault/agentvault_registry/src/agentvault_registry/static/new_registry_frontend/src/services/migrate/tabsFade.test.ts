import { describe, it, expect } from 'vitest'
import { edgeFade } from './tabsFade'

describe('edgeFade', () => {
  it('fades nothing when the row fits', () => {
    expect(edgeFade(0, 393, 393)).toEqual({ left: false, right: false })
    expect(edgeFade(0, 393, 394)).toEqual({ left: false, right: false })       // a pixel of slack is not a cut
  })
  it('fades the right edge at the start, both in the middle, the left at the end', () => {
    expect(edgeFade(0, 393, 480)).toEqual({ left: false, right: true })
    expect(edgeFade(40, 393, 480)).toEqual({ left: true, right: true })
    expect(edgeFade(87, 393, 480)).toEqual({ left: true, right: false })
  })
})
