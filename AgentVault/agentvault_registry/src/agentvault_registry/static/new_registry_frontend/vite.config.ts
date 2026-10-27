import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { viteStaticCopy } from 'vite-plugin-static-copy'
import { VitePWA } from 'vite-plugin-pwa'

const cesiumSource = 'node_modules/cesium/Build/Cesium'
// vite-plugin-static-copy 4 keeps the source's directory structure under `dest` (1.x flattened each match to its
// basename), so without a rename every Cesium file landed at cesium/Workers/node_modules/cesium/Build/Cesium/Workers/...
// and the engine's requests under CESIUM_BASE_URL answered 404: the landing page's globe did not load (V0481-V0485,
// found 2026-09-28). stripBase drops the source prefix, node_modules/cesium/Build/Cesium/<dir> (five segments), and
// keeps everything below it. scripts/check-cesium-dist.mjs holds the built tree to Build/Cesium's own layout.
const cesiumRename = { stripBase: cesiumSource.split('/').length + 1 }

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    viteStaticCopy({
      targets: [
        { src: `${cesiumSource}/Workers/**/*`, dest: 'cesium/Workers', rename: cesiumRename },
        { src: `${cesiumSource}/Assets/**/*`, dest: 'cesium/Assets', rename: cesiumRename },
        { src: `${cesiumSource}/Widgets/**/*`, dest: 'cesium/Widgets', rename: cesiumRename },
        // Cesium's licence and its own third-party list travel with the copied assets (REVIEW_2026-09-30_LICENSING.md)
        { src: 'node_modules/cesium/LICENSE.md', dest: 'cesium', rename: { stripBase: 2 } },
      ],
    }),
    // POCKET FRAME P0 (2026-07-07): installable PWA. Deliberately MINIMAL service
    // worker — tiny precache (icons+manifest only), hashed /assets/* runtime-cached,
    // /api /mcp /auth /.well-known are NetworkOnly (NEVER cached — money paths must
    // always hit the registry). index.html is NOT precached, so every deploy is
    // picked up exactly like the no-SW world (no stale-app footgun). The SW file is
    // served at root scope via two tiny FastAPI routes (/sw.js, /manifest.webmanifest).
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      // NO includeAssets: anything listed here lands in the SW precache manifest with
      // dist-root-relative URLs (/pwa-192.png), but dist root is only exposed via three
      // explicit routes — the precache fetch 404s, the SW INSTALL FAILS SILENTLY and the
      // registration is discarded (found the hard way, 2026-07-07). Icons load from
      // /static/ normally; v1 SW = installability + runtime rules, zero precache.
      manifest: {
        id: '/ui/',
        name: 'TheProtocol — POCKET FRAME',
        short_name: 'TheProtocol',
        description: 'Sovereign agent economy in your pocket — wallet, agents, approvals, alerts.',
        // Installed app opens straight into POCKET mode (the consumer shell);
        // Advanced mode (full Mission Control) is one tap away in More.
        start_url: '/ui/#/pocket/home',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait-primary',
        background_color: '#07090d',
        theme_color: '#07090d',
        icons: [
          { src: '/static/pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/static/pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/static/pwa-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
        shortcuts: [
          // §POCKETBRIDGE4 WS-H — long-press doors onto the money moments.
          { name: 'Send', url: '/ui/#/pocket/home?sheet=send', icons: [{ src: '/static/pwa-192.png', sizes: '192x192' }] },
          { name: 'Trade', url: '/ui/#/pocket/trade', icons: [{ src: '/static/pwa-192.png', sizes: '192x192' }] },
          { name: 'Assistant', url: '/ui/#/pocket/assistant', icons: [{ src: '/static/pwa-192.png', sizes: '192x192' }] },
          { name: 'Needs you', url: '/ui/#/pocket/home?attention=1', icons: [{ src: '/static/pwa-192.png', sizes: '192x192' }] },
          { name: 'Approvals', url: '/ui/#/pocket/approvals', icons: [{ src: '/static/pwa-192.png', sizes: '192x192' }] },
        ],
        // §POCKETBRIDGE4 WS-H — receive shares (a DID, a payment link, plain text)
        // from any app. action carries NO hash (params would land after the
        // fragment); the boot shim in main.ts routes the shared text.
        share_target: {
          action: '/ui',
          method: 'GET',
          params: { title: 'title', text: 'text', url: 'url' },
        },
      },
      workbox: {
        // WEB PUSH (2026-07-25): the push/notificationclick handlers live in a hand-written
        // /push-sw.js folded in here. generateSW gives no other seam, and switching to
        // injectManifest would mean owning the whole caching strategy for two listeners.
        importScripts: ['/push-sw.js'],
        inlineWorkboxRuntime: true, // single-file sw.js (dist root is only exposed via 3 explicit routes)
        globPatterns: [],           // ZERO precache — see includeAssets note above
        globIgnores: ['**/*'],
        navigateFallback: null,     // no offline nav fallback — see the SPA-document rule below
        runtimeCaching: [
          {
            urlPattern: ({ url }: { url: URL }) =>
              ['/api/', '/mcp', '/auth/', '/.well-known/'].some((p) => url.pathname.startsWith(p)),
            handler: 'NetworkOnly',
          },
          /* §POCKETBRIDGE #PK25 (D4, ratified) — THE OFFLINE FLOOR, kept
           * deliberately tiny. The Sprint-1 lesson stands: PRECACHE urls that
           * are not actually routed kill the worker silently at install, so
           * this adds NO precache entry at all. Instead the SPA document
           * itself (`/ui`) is NetworkFirst with a short timeout: online users
           * always get the fresh no-store document (and the self-heal watchdog
           * in index.html still governs staleness); offline, the last-seen
           * document boots the shell from the already-CacheFirst /assets, and
           * the Pocket shell's own offline banner says what is stale. Nothing
           * queues, nothing sends. */
          {
            urlPattern: ({ url, request }: { url: URL; request: Request }) =>
              request.mode === 'navigate' && (url.pathname === '/ui' || url.pathname === '/ui/'),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'tp-shell',
              networkTimeoutSeconds: 4,
              expiration: { maxEntries: 4, maxAgeSeconds: 7 * 24 * 3600 },
            },
          },
          {
            urlPattern: ({ url }: { url: URL }) => url.pathname.startsWith('/assets/'),
            handler: 'CacheFirst',
            options: {
              cacheName: 'tp-assets',
              expiration: { maxEntries: 300, maxAgeSeconds: 30 * 24 * 3600 },
            },
          },
        ],
      },
    }),
  ],
  define: {
    CESIUM_BASE_URL: JSON.stringify('/static/cesium/'),
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
      // elkjs is EPL-2.0 and cannot ship in this AGPL bundle (REVIEW_2026-09-30_LICENSING.md, F10): both specifiers
      // resolve to a stand-in that refuses mermaid's optional elk layout; the specific path first.
      'elkjs/lib/elk.bundled.js': fileURLToPath(new URL('./src/vendor-stubs/elkjs.ts', import.meta.url)),
      'elkjs': fileURLToPath(new URL('./src/vendor-stubs/elkjs.ts', import.meta.url)),
    }
  },
  server: {
    port: 5173,
    // Dev proxy target — override per sandbox without code edits:
    //   VITE_PROXY_TARGET=http://localhost:8002 npm run dev   (Frame A / AVT)
    //   VITE_PROXY_TARGET=http://localhost:8004 npm run dev   (Frame C / BVT)
    // Forwards /api (REST+WS), plus /.well-known (registry card → currency/fx)
    // and /static (Cesium + baked assets) so relative fetches resolve in dev.
    proxy: (() => {
      const target = process.env.VITE_PROXY_TARGET || 'http://localhost:8000'
      const common = { target, changeOrigin: true, secure: false }
      return {
        '/api': { ...common, ws: true },
        '/.well-known': { ...common },
        '/static': { ...common },
      }
    })(),
  },
  build: {
    target: 'es2020',
    outDir: 'dist',
    // Ensure assets are served from root path in production
    assetsDir: 'assets',
    rollupOptions: {
      output: {
        // §DEPS FE (2026-09-28): Vite 8 bundles with Rolldown, which takes manualChunks only as a FUNCTION (the object
        // form fails the build: "Invalid type: Expected Function but received Object"). The same three chunks, named by
        // the package a module comes from. The object form also pulled each entry's own dependencies into its chunk
        // (vue's @vue/* runtime, cesium's @cesium/* engine and widgets), so those are named here explicitly.
        // 2026-07-07: 'zod' removed: never imported in src and not a package.json dep
        // (a stale node_modules had masked it; fresh install broke the chunk entry).
        // §FEFRAME W1: groups with PRIORITIES (Rolldown's codeSplitting) instead of manualChunks. The transpile helpers
        // Rolldown injects (\0@oxc-project+runtime@<v>/helpers/esm/defineProperty.js, toPrimitive, toPropertyKey, typeof)
        // are shared by the app and Cesium. Under manualChunks every name is one group at one priority, and a group
        // takes its captured modules' dependencies with it: the cesium-vendor capture pulled the helpers in and a
        // manualChunks name for the helpers never won (measured: no oxc-helpers chunk, the entry importing
        // defineProperty from the 4.2 MB Cesium chunk, index.html preloading Cesium on every page, the login and
        // Pocket included). A higher-priority group captures first, so the helpers get a chunk of their own; the build
        // gate "index.html names no cesium-vendor" holds it.
        codeSplitting: {
          groups: [
            { name: 'oxc-helpers', test: /@oxc-project[+/]runtime/, priority: 40 },
            { name: 'vue-vendor', test: /\/node_modules\/(vue|@vue\/[^/]+|vue-router|pinia)\//, priority: 30 },
            { name: 'utils', test: /\/node_modules\/(axios|dayjs)\//, priority: 20 },
            { name: 'cesium-vendor', test: /\/node_modules\/(cesium|@cesium\/[^/]+)\//, priority: 10 },
          ],
        },
      }
    }
  },
  // Base URL for production (served from backend root)
  base: '/'
})
