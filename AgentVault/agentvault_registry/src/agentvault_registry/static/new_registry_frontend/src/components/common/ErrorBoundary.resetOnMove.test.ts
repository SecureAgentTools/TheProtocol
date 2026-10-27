/**
 * §FESUITE (2026-10-10, sweeps/recovery on V0589): the console's error boundary (App.vue, around the whole console) kept
 * a page's crash over every later page. The API tester's endpoint read failed while the registry did not answer, its
 * mount rejected, and "Oops! Something went wrong / Request failed with status code 502" stayed on the console after the
 * registry was back, until Try again or a reload. A person who moves to another page now gets that page. Mounted with a
 * real router; the crashing page throws once, the way a read that failed during an outage does.
 */
import { describe, expect, it } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory, RouterView } from 'vue-router'
import { defineComponent, h } from 'vue'
import ErrorBoundary from './ErrorBoundary.vue'

function routerWith(crashOnce: string) {
  let crashed = false
  const page = (name: string) => defineComponent({
    setup() {
      if (name === crashOnce && !crashed) { crashed = true; throw new Error('Request failed with status code 502') }
      return () => h('p', { 'data-testid': 'page' }, `the ${name} page`)
    },
  })
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/api-tester', component: page('api-tester') }, { path: '/api-keys', component: page('api-keys') }],
  })
}

const Shell = defineComponent({ render: () => h(ErrorBoundary, null, { default: () => h(RouterView) }) })

describe('the error boundary around the console', () => {
  it('a page that crashed leaves its panel behind when the person moves on', async () => {
    const router = routerWith('api-tester')
    router.push('/api-tester')
    await router.isReady()
    const w = mount(Shell, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.text(), 'the crash is shown on the page that crashed').toContain('Request failed with status code 502')
    expect(w.find('[data-testid="page"]').exists()).toBe(false)

    await router.push('/api-keys')
    await flushPromises()
    expect(w.text(), 'the last page\'s crash over the next page').not.toContain('Request failed with status code 502')
    expect(w.find('[data-testid="page"]').text()).toBe('the api-keys page')

    // back again once the registry answers: the page mounts, the panel stays gone
    await router.push('/api-tester')
    await flushPromises()
    expect(w.find('[data-testid="page"]').text()).toBe('the api-tester page')
  })

  it('a boundary with no router keeps its panel until Try again, as before', async () => {
    let throwIt = true
    const Boom = defineComponent({
      setup() {
        if (throwIt) { throwIt = false; throw new Error('boom once') }
        return () => h('p', 'fine')
      },
    })
    const w = mount(defineComponent({ render: () => h(ErrorBoundary, null, { default: () => h(Boom) }) }))
    await flushPromises()
    expect(w.text()).toContain('boom once')
  })
})
