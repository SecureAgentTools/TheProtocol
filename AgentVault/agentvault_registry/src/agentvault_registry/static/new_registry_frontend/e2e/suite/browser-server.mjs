#!/usr/bin/env node
/**
 * The suite's remote browser (§FESUITE): a Playwright browser server the suite connects to (FESUITE_WS_ENDPOINT), so
 * the browser can live somewhere the test process does not, for example in a network namespace of its own where a
 * busy host's address churn cannot abort its requests (net::ERR_NETWORK_CHANGED).
 *
 *   node e2e/suite/browser-server.mjs --host 10.231.77.2 --port 39231 \
 *        [--map console.example.org,peer.example.org=10.231.77.1] [--ready-file /path/ws-endpoint]
 *
 * --map resolves those hostnames to one address inside the browser, keeping the real origins. The browser also runs
 * with Local Network Access checks off: a document the suite serves from a local build has no address of its own,
 * so Chromium files it as public and would refuse its websocket to a private address (the harness's artefact, not
 * the product's). It prints the endpoint and, with --ready-file, writes it there; it runs until it is signalled.
 */
import fs from 'node:fs'
import { chromium } from '@playwright/test'

function arg(name, fallback = '') {
  const i = process.argv.indexOf(`--${name}`)
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback
}

const host = arg('host', '127.0.0.1')
const port = Number(arg('port', '39231'))
const map = arg('map')
const readyFile = arg('ready-file')

const args = ['--disable-features=LocalNetworkAccessChecks']
if (map) {
  const [hosts, to] = map.split('=')
  const rules = hosts.split(',').filter(Boolean).map((h) => `MAP ${h} ${to}`).join(', ')
  args.push(`--host-resolver-rules=${rules}`)
}

const server = await chromium.launchServer({ host, port, args, headless: true })
const ws = server.wsEndpoint()
process.stdout.write(`[fesuite-browser] ${ws}\n`)
if (readyFile) fs.writeFileSync(readyFile, ws, { mode: 0o600 })
const stop = async () => { try { await server.close() } finally { process.exit(0) } }
process.on('SIGTERM', stop)
process.on('SIGINT', stop)
