import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import PluginConfigForm from './PluginConfigForm.vue'

/** V0664 C4: the catalog-driven config form. What a person fills in first is shown; the rest sits under "More options"; a destination or a secret
 *  takes the NAME of a parameter and the config holds ${NAME}. */
const SCHEMA = { required: ['engine', 'key'], properties: {
  engine: { type: 'string', enum: ['postgresql', 'mysql'] }, key: { type: 'string' }, host: { type: 'string' }, password: { type: 'string' },
  port: { type: 'integer' }, timeout_seconds: { type: 'integer', default: 30 }, columns: { type: 'array' },
} }
const mountIt = (config: Record<string, any> = {}) => mount(PluginConfigForm, { props: { role: 'sink', schema: SCHEMA, config, prefix: 'TARGET' } })
const shown = (w: any, key: string) => w.find(`[data-testid="mb-cfg-sink-${key}"]`).element.closest('.pcf-row').style.display !== 'none'

describe('PluginConfigForm', () => {
  it('shows the required fields and every destination or secret first, the rest behind "More options"', async () => {
    const w = mountIt()
    for (const k of ['engine', 'key', 'host', 'password']) expect(shown(w, k)).toBe(true)
    for (const k of ['port', 'timeout_seconds', 'columns']) expect(shown(w, k)).toBe(false)
    expect(w.find('[data-testid="mb-cfg-more"]').text()).toContain('More options (3)')
    await w.find('[data-testid="mb-cfg-more"]').trigger('click')
    for (const k of ['port', 'timeout_seconds', 'columns']) expect(shown(w, k)).toBe(true)
    expect(w.find('[data-testid="mb-cfg-more"]').text()).toContain('Fewer options')
  })
  it('keeps a field that was already set in view, and writes ${NAME} for a destination and a secret, never a value', async () => {
    const cfg: Record<string, any> = { port: 5433 }
    const w = mountIt(cfg)
    expect(shown(w, 'port')).toBe(true)
    await w.find('[data-testid="mb-cfg-sink-host"]').setValue('TARGET_HOST')
    await w.find('[data-testid="mb-cfg-sink-password"]').setValue('DB_PASSWORD')
    expect(cfg.host).toBe('${TARGET_HOST}')
    expect(cfg.password).toBe('${DB_PASSWORD}')
  })
  it('never accepts a literal host or password: a value that is not a name is refused beside the field', async () => {
    const cfg: Record<string, any> = {}
    const w = mountIt(cfg)
    await w.find('[data-testid="mb-cfg-sink-host"]').setValue('db.example.invalid')
    expect(cfg.host).toBeUndefined()
    expect(w.find('[data-testid="mb-cfg-sink-host-err"]').exists()).toBe(true)
  })
})
