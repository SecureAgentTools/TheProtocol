// V0667 the public pages readable without JavaScript (order gwo_a9f121caa4138ec9b369814c): one route's OWN view, rendered by Vue's server
// renderer with the app's own routes, i18n (en, bundled) and components. No headless browser, and nothing reaches the network: a server render
// runs no mounted hook, so the views' reads never start, and the stand-ins (noNetwork.ts) refuse any that a setup starts. The router is a
// guard-free copy of the app's (same routes, same views): its guards decide sign-in and switches, and every page here is public.
import { createSSRApp, h, type Component } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import appRouter from '@/router'
import i18n from '@/i18n'
import NeuralIcon from '@/components/ui/NeuralIcon.vue'
import NeuralCard from '@/components/ui/NeuralCard.vue'
import { descriptionOf, omitLive, pageText } from './document'

export interface Rendered {
  body: string                 // the view's HTML, live regions left out
  title: string
  description: string
}

function fill(route: string, params: Record<string, string>): string {
  return route.replace(/\/:([A-Za-z]+)\??/g, (_m, n) => (params[n] ? `/${params[n]}` : '')) || '/'
}

async function resolved(c: unknown): Promise<Component> {
  const looksLazy = typeof c === 'function' && !('setup' in (c as object)) && !('render' in (c as object)) && !('__vccOpts' in (c as object))
  if (!looksLazy) return c as Component
  const mod: any = await (c as () => Promise<unknown>)()
  return (mod?.default ?? mod) as Component
}

export async function renderPage(route: string, params: Record<string, string> = {}): Promise<Rendered> {
  const router = createRouter({ history: createMemoryHistory(), routes: appRouter.options.routes })
  const failure = await router.push(fill(route, params))
  if (failure) throw new Error(`${route}: the navigation failed (${String(failure)})`)
  const current = router.currentRoute.value
  const leafRecord = current.matched[current.matched.length - 1]
  if (!leafRecord?.components?.default) throw new Error(`${route}: no view to render`)
  const view = await resolved(leafRecord.components.default)
  const p = leafRecord.props?.default
  const props = p === true ? { ...current.params } : typeof p === 'function' ? p(current) : typeof p === 'object' && p ? p : {}

  const app = createSSRApp({ render: () => h(view as any, props) })
  app.component('NeuralIcon', NeuralIcon)
  app.component('NeuralCard', NeuralCard)
  app.use(createPinia())
  app.use(router)
  app.use(i18n)
  app.config.warnHandler = () => {}
  const body = omitLive(await renderToString(app))

  const h1 = body.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/i)
  const title = String((current.meta as any)?.title || (h1 ? pageText(h1[1]) : '') || route).trim()
  return { body, title, description: descriptionOf(body) }
}
