/* WEB PUSH handlers, folded into the generated service worker via workbox importScripts.
 *
 * Kept as a separate hand-written file because vite-plugin-pwa runs in generateSW mode: switching
 * to injectManifest to hand-write the whole worker would put the entire caching strategy at risk
 * for the sake of two event listeners. importScripts is the supported seam.
 *
 * Served from the ROOT path (a worker under /static/ could only control /static/*).
 */
self.addEventListener('push', (event) => {
  let data = {}
  try { data = event.data ? event.data.json() : {} } catch (e) { data = { body: event.data && event.data.text() } }
  const title = data.title || 'TheProtocol'
  const options = {
    body: data.body || '',
    // §POCKETBRIDGE P0 (F6): this referenced /pwa-192x192.png, a file that has
    // never existed in the dist — every push notification icon 404'd since it
    // shipped. The real asset is the manifest's own icon under /static/.
    icon: '/static/pwa-192.png',
    badge: '/static/pwa-192.png',
    tag: data.tag || 'tp-notification',
    renotify: true,
    // requireInteraction: a liability confirmation must not vanish on its own — the human is
    // being asked to sign something and the window is short.
    requireInteraction: !!data.require_interaction,
    data: { url: data.url || '/ui/#/pocket/approvals' },
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data && event.notification.data.url) || '/ui/#/pocket/approvals'
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      // Prefer focusing an already-open app window over spawning a second one.
      for (const c of list) {
        if (c.url.indexOf('/ui/') !== -1 && 'focus' in c) {
          if ('navigate' in c) { try { c.navigate(target) } catch (e) {} }
          return c.focus()
        }
      }
      return clients.openWindow(target)
    })
  )
})
