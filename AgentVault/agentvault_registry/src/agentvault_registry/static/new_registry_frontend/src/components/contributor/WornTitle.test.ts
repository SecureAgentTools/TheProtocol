/**
 * V0665 (his feedback on the Track tab, room seq 4404, session-lead seq 4405): "set my commander title for me". The title under a person's name is the one they
 * chose; when none is chosen the commander flare tier wears the COMMANDER title (a rule of the code, nothing stored); anyone else with no title shows nothing.
 */
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WornTitle from './WornTitle.vue'

const stubs = { TitleEmblem: { props: ['titleKey', 'size', 'variant'], template: '<span data-testid="emblem" :data-key="titleKey" :data-size="size" />' },
                CommanderPlate: { props: ['size'], template: '<span data-testid="plate" :data-size="size" />' } }
const mountIt = (props: { title?: string | null; flareTier?: string | null; size: 'sidebar' | 'card' | 'large' }, attrs: Record<string, any> = {}) => mount(WornTitle, { props, attrs, global: { stubs } })

describe('the title worn under a name', () => {
  it('draws the chosen title as its emblem', () => {
    const w = mountIt({ title: 'first-light', flareTier: null, size: 'sidebar' })
    expect(w.find('[data-testid="emblem"]').attributes('data-key')).toBe('first-light')
    expect(w.find('[data-testid="plate"]').exists()).toBe(false)
  })
  it('draws the COMMANDER plate for the commander tier when no title is chosen', () => {
    const w = mountIt({ title: '', flareTier: 'commander', size: 'card' })
    expect(w.find('[data-testid="plate"]').attributes('data-size')).toBe('card')
    expect(w.find('[data-testid="emblem"]').exists()).toBe(false)
  })
  it('keeps the title the commander chose: he can still pick another', () => {
    const w = mountIt({ title: 'patchwright', flareTier: 'commander', size: 'sidebar' })
    expect(w.find('[data-testid="emblem"]').attributes('data-key')).toBe('patchwright')
    expect(w.find('[data-testid="plate"]').exists()).toBe(false)
  })
  it('shows nothing for anyone else with no title', () => {
    expect(mountIt({ title: '', flareTier: 'founder', size: 'sidebar' }).html()).toBe('<!--v-if-->')
    expect(mountIt({ title: '', flareTier: null, size: 'sidebar' }).html()).toBe('<!--v-if-->')
  })
  it('carries the caller\'s class and test id on whichever it draws', () => {
    const a = mountIt({ title: '', flareTier: 'commander', size: 'sidebar' }, { 'data-testid': 'sidebar-title', class: 'sidebar-user-title' })
    expect(a.find('[data-testid="sidebar-title"]').exists()).toBe(true)
    const b = mountIt({ title: 'first-light', flareTier: null, size: 'sidebar' }, { 'data-testid': 'sidebar-title', class: 'sidebar-user-title' })
    expect(b.find('[data-testid="sidebar-title"]').classes()).toContain('sidebar-user-title')
  })
})
