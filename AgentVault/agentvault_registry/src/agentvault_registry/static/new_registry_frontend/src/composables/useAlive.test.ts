import { describe, it, expect } from 'vitest'
import { defineComponent, h, onMounted } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { useAlive } from './useAlive'

/**
 * §FESUITE (2026-10-03): a page that awaits in onMounted and then starts a timer must not start it once it is gone. The
 * component below stands for such a page: its first read is a promise the test answers, and "started" records what the
 * code after the await went on to do.
 */
function page(started: string[]) {
  let answer!: () => void
  const read = new Promise<void>((r) => { answer = r })
  const C = defineComponent({
    setup() {
      const alive = useAlive()
      onMounted(async () => {
        await read
        if (!alive()) return
        started.push('timer')
      })
      return () => h('div')
    },
  })
  return { C, answer: () => answer() }
}

describe('useAlive', () => {
  it('a page left during its first read starts nothing when the answer lands', async () => {
    const started: string[] = []
    const { C, answer } = page(started)
    const w = mount(C)
    w.unmount()
    answer()
    await flushPromises()
    expect(started).toEqual([])
  })

  it('a page still shown when the answer lands goes on', async () => {
    const started: string[] = []
    const { C, answer } = page(started)
    const w = mount(C)
    answer()
    await flushPromises()
    expect(started).toEqual(['timer'])
    w.unmount()
  })

  it('reads true while mounted and false after', () => {
    let alive: () => boolean = () => true
    const C = defineComponent({ setup() { alive = useAlive(); return () => h('div') } })
    const w = mount(C)
    expect(alive()).toBe(true)
    w.unmount()
    expect(alive()).toBe(false)
  })
})
