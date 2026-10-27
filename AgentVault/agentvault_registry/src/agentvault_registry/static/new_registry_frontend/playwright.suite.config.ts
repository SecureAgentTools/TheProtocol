/**
 * The console lifecycle suite (§FESUITE): the MCP tester's lifecycles, driven through the console the way a person
 * drives it, against a live registry. Read e2e/suite/README.md first.
 *
 *   FESUITE_BASE_URL=https://<console> [FESUITE_HOST_MAP=<console host>] [FESUITE_DIST=dist] \
 *     npx playwright test -c playwright.suite.config.ts
 *
 * One browser, one worker, in order: the lifecycles share a live registry and the run's own accounts, and the host it
 * runs on is a production host. No trace and no video (a trace records what a page was given, tokens included);
 * a screenshot only on failure.
 */
import { defineConfig, devices } from '@playwright/test'
import path from 'node:path'

const OUT = path.resolve(process.env.FESUITE_OUT || 'test-results/fesuite')
// Chromium resolves these hostnames to the host itself: the page keeps the real origin, nothing crosses a public edge.
const HOST_MAP = (process.env.FESUITE_HOST_MAP || '').split(',').map((h) => h.trim()).filter(Boolean)
const LAUNCH_ARGS = HOST_MAP.length ? [`--host-resolver-rules=${HOST_MAP.map((h) => `MAP ${h} 127.0.0.1`).join(', ')}`] : []
// A document the suite serves from a local build (FESUITE_DIST, route.fulfill) has no network address, so Chromium files it
// as PUBLIC; its websocket to the same hostname, mapped to 127.0.0.1, then reads as public -> local and Local Network
// Access refuses it (net::ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS; measured 2026-10-01: fetch 200, ws refused, the
// flag below opens it). In the world the hostname is public on both sides: the check is the harness's, not the product's.
if (HOST_MAP.length || process.env.FESUITE_DIST) LAUNCH_ARGS.push('--disable-features=LocalNetworkAccessChecks')

export default defineConfig({
  testDir: './e2e/suite',
  testMatch: /.*\.spec\.ts$/,
  outputDir: path.join(OUT, 'artifacts'),
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  // One retry: the host is shared, and another session's container recreate makes Chromium drop in-flight calls
  // (net::ERR_NETWORK_CHANGED). The record keeps the final attempt; a lifecycle that failed once and then passed with
  // no dropped call is recorded as FLAKY, a finding, never a quiet pass.
  retries: Number(process.env.FESUITE_RETRIES ?? 1),
  forbidOnly: true,
  globalSetup: './e2e/suite/global-setup.ts',
  globalTeardown: './e2e/suite/global-teardown.ts',
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(OUT, 'html'), open: 'never' }],
    ['./e2e/suite/support/reporter.ts'],
  ],
  use: {
    baseURL: process.env.FESUITE_BASE_URL,
    locale: 'en-US',
    timezoneId: 'UTC',
    trace: 'off',
    video: 'off',
    screenshot: 'only-on-failure',
    actionTimeout: 20_000,
    navigationTimeout: 60_000,
    // The console's PWA worker would answer calls the suite never sees (page.route and the capture both miss them).
    serviceWorkers: 'block',
    launchOptions: { args: LAUNCH_ARGS },
    // A remote browser (e2e/suite/browser-server.mjs), e.g. in a network namespace of its own; its own flags apply.
    ...(process.env.FESUITE_WS_ENDPOINT ? { connectOptions: { wsEndpoint: process.env.FESUITE_WS_ENDPOINT } } : {}),
  },
  projects: [
    {
      name: 'desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
      grepInvert: /@phone-only/,
    },
    {
      name: 'phone',
      use: { ...devices['Pixel 7'] },
      grep: /@phone/,
    },
  ],
})
