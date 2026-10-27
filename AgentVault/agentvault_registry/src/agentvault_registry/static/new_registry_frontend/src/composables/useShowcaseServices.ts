// useShowcaseServices — single source of truth for the public "Live Agent
// Services" catalog (Services page + Monetize demo). One catalog, live price
// overlay from GET /api/v1/public/showcase/agents, and the call() that POSTs to
// /api/v1/public/showcase/call (the real A2A-payment showcase rail).
//
// The per-service request contract (service id, input, task_type) is preserved
// EXACTLY as the previous ServicesShowcase to keep the registry proxy
// preprocessing + the agents working unchanged. `display` selects the typed
// result renderer; everything else is presentation.
import { reactive, ref, computed, onMounted } from 'vue'
import { currentOwnCurrency } from '@/composables/useFrameManifest'

export interface ServiceExtraOption { value: string; label: string }
export interface ShowcaseService {
  id: string
  label: string
  blurb: string
  svg: string            // inner paths for a 24x24 stroke icon (no emoji)
  accent: string         // rgba tint for the icon tile
  price: string          // legacy: the charge in the AGENT's currency
  // Live pricing truth (§SHOWCASE-FX). The agent bills in ITS currency; a
  // viewer on another frame pays the converted amount at the live cross-frame
  // rate. Keeping both means the card can state the conversion instead of
  // printing one number under the other one's label.
  priceNative?: string   // what the agent bills
  currencyNative?: string
  priceLocal?: string    // what THIS frame actually sends
  currencyLocal?: string
  fxRate?: string
  fxFee?: string
  taskType: string
  display: string        // result renderer key
  placeholder: string
  hint: string
  chips: string[]
  value: string
  textarea?: boolean
  extra?: { value: string; options: ServiceExtraOption[] }
  // §MCPTEST30 (V0641, D6-831): why THIS frame cannot make a paid call to this agent (the catalogue's `callable:
  // false` with its reason: authorize's payee rule, or no payer and no relay); absent while it can
  uncallable?: string
}

// Clean line-icon paths (rendered inside <svg viewBox="0 0 24 24" fill="none"
// stroke="currentColor">). No emoji, no Iconify.
const I = {
  weather: '<path d="M12 3v1m0 16v1m8.66-13.66l-.71.71M4.05 19.95l-.71.71M21 12h-1M4 12H3m16.95 7.95l-.71-.71M4.05 4.05l-.71-.71"/><circle cx="12" cy="12" r="4"/>',
  currency: '<path d="M12 2v20M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/>',
  ssl: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/><circle cx="12" cy="16" r="1"/>',
  timezone: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
  unit: '<path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/>',
  news: '<path d="M4 22h16a2 2 0 002-2V4a2 2 0 00-2-2H8a2 2 0 00-2 2v16a2 2 0 01-2 2zm0 0a2 2 0 01-2-2v-9c0-1.1.9-2 2-2h2"/><line x1="10" y1="6" x2="18" y2="6"/><line x1="10" y1="10" x2="18" y2="10"/><line x1="10" y1="14" x2="14" y2="14"/>',
  ip: '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/>',
  text: '<line x1="17" y1="10" x2="3" y2="10"/><line x1="21" y1="6" x2="3" y2="6"/><line x1="21" y1="14" x2="3" y2="14"/><line x1="17" y1="18" x2="3" y2="18"/>',
  cron: '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/><path d="M19.07 4.93A10 10 0 004.93 19.07"/>',
  password: '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.78 7.78 5.5 5.5 0 017.78-7.78zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
  converter: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="15" x2="15" y2="15"/>',
}

function buildCatalog(): ShowcaseService[] {
  return reactive<ShowcaseService[]>([
    { id: 'weather', label: 'Weather', blurb: 'Live conditions & 3-day forecast, any city', svg: I.weather, accent: '59,130,246', price: '0.5', taskType: 'weather_current', display: 'weather', placeholder: 'City — Berlin, Tokyo, New York…', hint: 'Type a city name. Country is optional.', chips: ['Berlin', 'Tokyo', 'New York', 'Sydney', 'London'], value: '' },
    { id: 'currency', label: 'Currency Exchange', blurb: 'Live FX across 170+ currencies', svg: I.currency, accent: '245,158,11', price: '0.5', taskType: 'currency_convert', display: 'currency', placeholder: '100 USD to EUR', hint: 'Format: amount FROM to TO — or just an amount.', chips: ['100 USD to EUR', '50 GBP to JPY', '250 CHF to USD'], value: '' },
    { id: 'dns', label: 'SSL & Site Health', blurb: 'Certificate, DNS records & security headers', svg: I.ssl, accent: '16,185,129', price: '1.0', taskType: 'site_health', display: 'ssl', placeholder: 'theprotocol.cloud', hint: 'Any domain — protocol & path are stripped.', chips: ['theprotocol.cloud', 'github.com', 'cloudflare.com'], value: '' },
    { id: 'timezone', label: 'World Clock', blurb: 'Local time, UTC offset & DST for any city', svg: I.timezone, accent: '139,92,246', price: '0.1', taskType: 'time_convert', display: 'timezone', placeholder: 'City — Tokyo, Sydney, Paris…', hint: 'Type a city. Get local time, offset & DST.', chips: ['Tokyo', 'Sydney', 'Paris', 'Dubai', 'São Paulo'], value: '' },
    { id: 'units', label: 'Unit Converter', blurb: 'Temperature, distance, weight, speed & more', svg: I.unit, accent: '236,72,153', price: '0.1', taskType: 'unit_convert', display: 'unit', placeholder: '72 fahrenheit to celsius', hint: 'Natural language — "100 miles to km".', chips: ['72 fahrenheit to celsius', '100 miles to km', '5 kg to pounds'], value: '' },
    { id: 'news', label: 'Tech News', blurb: 'Latest headlines from top technology sources', svg: I.news, accent: '244,63,94', price: '0.5', taskType: 'news_headlines', display: 'news', placeholder: 'Topic — AI, security… (optional)', hint: 'Leave empty for all headlines, or filter by topic.', chips: ['AI', 'security', 'blockchain', 'startups'], value: ' ' },
    { id: 'ip', label: 'IP Lookup', blurb: 'Geolocation, ISP & network for any IP', svg: I.ip, accent: '20,184,166', price: '0.1', taskType: 'ip_lookup', display: 'ip', placeholder: '8.8.8.8', hint: 'Enter any public IPv4 address.', chips: ['8.8.8.8', '1.1.1.1', '9.9.9.9'], value: '' },
    { id: 'cron', label: 'Cron Builder', blurb: 'Create or explain cron schedule expressions', svg: I.cron, accent: '251,146,60', price: '0.1', taskType: 'cron_create', display: 'cron', placeholder: 'every weekday at 9am', hint: 'Describe a schedule in English — or paste a cron expression.', chips: ['every weekday at 9am', 'every 5 minutes', 'monthly on the 1st'], value: '' },
    { id: 'password', label: 'Secure Generator', blurb: 'Passwords, passphrases, API keys & UUIDs', svg: I.password, accent: '239,68,68', price: '0.1', taskType: 'generate_password', display: 'password', placeholder: 'password', hint: 'Pick a type below, then Generate.', chips: ['password', 'passphrase', 'uuid', 'api_key'], value: 'password' },
    { id: 'text', label: 'Text Analysis', blurb: 'Word count, readability, keyword density, hashing', svg: I.text, accent: '99,102,241', price: '0.1', taskType: 'text_analyze', display: 'text', placeholder: 'Paste any text here to analyze…', hint: 'Word count, reading time, readability & keyword density.', chips: [], value: '', textarea: true },
    {
      id: 'converter', label: 'Format Converter', blurb: '19 converters across JSON, YAML, CSV, XML & more', svg: I.converter, accent: '168,85,247', price: '0.1', taskType: 'json-to-yaml', display: 'converter',
      placeholder: 'Paste content to convert…', hint: 'Paste your data, pick the conversion, and go.', chips: [], value: '', textarea: true,
      extra: {
        value: 'json-to-yaml',
        options: [
          { value: 'json-to-yaml', label: 'JSON → YAML' }, { value: 'yaml-to-json', label: 'YAML → JSON' },
          { value: 'json-to-xml', label: 'JSON → XML' }, { value: 'xml-to-json', label: 'XML → JSON' },
          { value: 'csv-to-json', label: 'CSV → JSON' }, { value: 'json-to-csv', label: 'JSON → CSV' },
          { value: 'markdown-to-html', label: 'Markdown → HTML' }, { value: 'json-to-toml', label: 'JSON → TOML' },
          { value: 'toml-to-json', label: 'TOML → JSON' },
        ],
      },
    },
  ])
}

const RATE_LIMIT = 50

export function useShowcaseServices() {
  const services = buildCatalog()
  const results = reactive<Record<string, any>>({})
  const loading = ref<string | null>(null)
  const requestCount = ref(0)
  const exhausted = ref(false)
  const pricesLoaded = ref(false)
  /* §FESUITE — a frame can switch the showcase off (/public/showcase/agents says enabled:false). The catalog below is
     built in the page, so it still listed every service with a Run button and a "50 free requests" meter, and each
     run came back 503. `unavailable` carries the frame's own reason so the page can say so up front. */
  const unavailable = ref<string | null>(null)
  const requestsLeft = computed(() => (exhausted.value ? 0 : Math.max(0, RATE_LIMIT - requestCount.value)))

  async function loadPrices() {
    try {
      const r = await fetch('/api/v1/public/showcase/agents')
      if (r.ok) {
        const d = await r.json()
        if (d?.enabled === false) unavailable.value = String(d.reason || 'The showcase is disabled on this deployment.')
        const map: Record<string, any> = {}
        for (const a of d.agents || []) if (a?.id) map[a.id] = a
        for (const s of services) {
          const a = map[s.id]
          if (!a) continue
          // The agent's own price, from its card.
          s.price = String(a.price ?? a.price_avt ?? s.price)
          s.priceNative = String(a.price ?? a.price_avt ?? s.price)
          s.currencyNative = String(a.currency || currentOwnCurrency())
          // What this frame sends. Absent (null) when no rate is available:
          // the card then shows the true charge rather than a relabelled one.
          s.priceLocal = a.price_local != null ? String(a.price_local) : undefined
          s.currencyLocal = a.currency_local ? String(a.currency_local) : undefined
          s.fxRate = a.fx_rate ? String(a.fx_rate) : undefined
          s.fxFee = a.fx_fee_rate ? String(a.fx_fee_rate) : undefined
          // the run is offered only where the call can be made (absent `callable`: an older registry, or a check that
          // could not run, which says nothing either way)
          s.uncallable = a.callable === false
            ? String(a.reason || 'This frame cannot make a paid call to this agent.')
            : undefined
        }
      }
    } catch { /* keep catalog defaults */ } finally {
      pricesLoaded.value = true
    }
  }

  async function call(svc: ShowcaseService) {
    if (requestsLeft.value <= 0) {
      results[svc.id] = { error: 'Free hourly limit reached (50/hr). Create a free account for unlimited access.' }
      return
    }
    loading.value = svc.id
    delete results[svc.id]
    try {
      const task_type = svc.extra ? svc.extra.value : svc.taskType
      const res = await fetch('/api/v1/public/showcase/call', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ service: svc.id, input: (svc.value || '').trim(), task_type }),
      })
      const data = await res.json().catch(() => ({}))
      if (res.status === 503 && data?.enabled === false) {
        unavailable.value = String(data.error || data.reason || 'The showcase is disabled on this deployment.')
        results[svc.id] = { error: unavailable.value }
      } else if (res.status === 429) {
        exhausted.value = true
        results[svc.id] = { error: data?.error || 'Free hourly limit reached (50/hr). Create a free account for unlimited access.' }
      } else if (!res.ok || data?.error) {
        results[svc.id] = { error: data?.detail || data?.error || 'Service temporarily unavailable — please try again.' }
        // the call refused itself up front (V0641): the run stays off for this agent, with the call's own words
        if (data?.callable === false) svc.uncallable = String(data.error || 'This frame cannot make a paid call to this agent.')
      } else {
        results[svc.id] = data
        requestCount.value++
      }
    } catch (e: any) {
      results[svc.id] = { error: e?.message || 'Network error — please try again.' }
    } finally {
      loading.value = null
    }
  }

  onMounted(loadPrices)
  return { services, results, loading, requestsLeft, pricesLoaded, RATE_LIMIT, call, unavailable }
}
