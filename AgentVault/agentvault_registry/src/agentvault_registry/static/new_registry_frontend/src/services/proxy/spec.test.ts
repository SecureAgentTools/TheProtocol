// V0664 C3 (order gwo_4110e12c11a69a93de878829): the proxy spec builder's model, tested before the views.
// The rules are theprotocol-sdk's (theprotocol/proxy/spec.py parse(), its credential rule and its plugin catalog), read from
// the generated catalog, never written a second time: a spec the builder calls clean is one `tp-proxy validate` takes.
import { describe, expect, it } from 'vitest'

import {
  addMapping, addPart, checkSpec, composeSnippet, fieldsOf, fieldWords, isRef, newSpec, CORE_SCHEMA, problemTarget, plugin, pluginsOf, previewMapping, RECIPES,
  removePart, runCommands, SDK_VERSION, secretPaths, secretProblem, toProxyYaml, type Role,
} from './spec'

describe('the catalog the builder offers', () => {
  it('lists each role\'s plugins by name, never an internal one', () => {
    const sources = pluginsOf('source').map((p) => p.name)
    expect(sources).toContain('filedrop')
    expect(sources).not.toContain('migrate_sample')                // internal: the migration CLI's own
    expect(sources).toEqual([...sources].sort())
    expect(pluginsOf('action').map((p) => p.name)).toContain('attestation')
    expect(pluginsOf('sink').map((p) => p.name)).toContain('rest')
  })

  it('describes a plugin\'s fields from its config_schema: type, required, enum, description, and the secret mark', () => {
    const rest = fieldsOf(plugin('sink', 'rest')!.config_schema)
    const url = rest.find((f) => f.key === 'url')!
    expect(url.type).toBe('string')
    expect(url.required).toBe(true)
    expect(url.description).toMatch(/placeholders/)
    expect(rest.find((f) => f.key === 'bearer')!.secret).toBe(true)
    expect(rest.find((f) => f.key === 'method')!.enumValues).toEqual(['POST', 'PUT', 'PATCH'])
    expect(rest.findIndex((f) => f.required)).toBe(0)                // required fields first
    expect(secretPaths(plugin('sink', 'rest')!.config_schema)).toEqual(['bearer'])
  })

  it('carries the eight recipes with their commands and their spec text', () => {
    expect(RECIPES.map((r) => r.id)).toEqual(['bazaar', 'dynamo', 'hansa', 'keystone', 'lyceum', 'meridian', 'scrivener', 'trunk'])
    for (const r of RECIPES) {
      expect(r.commands[0]).toMatch(/^tp-proxy validate/)
      expect(r.proxy_yaml).toMatch(/^#|^version: 1/m)
    }
  })
})

describe('the credential rule (spec.py: a secret is a reference, never written out)', () => {
  it('takes env:NAME and file:/path and refuses anything else, saying why', () => {
    expect(isRef('env:API_TOKEN')).toBe(true)
    expect(isRef('file:/run/secrets/token')).toBe(true)
    expect(isRef('abc123')).toBe(false)
    expect(secretProblem('')).toBeNull()                              // not set yet: the required check says so
    expect(secretProblem('env:API_TOKEN')).toBeNull()
    expect(secretProblem('hunter2')).toMatch(/env:NAME or file:\/path/)
    expect(secretProblem('hunter2')).not.toMatch(/hunter2/)           // the sentence never repeats the value
  })

  it('a literal in a marked field or a field named like a credential is a problem naming its path', () => {
    const doc = newSpec('shop-bridge')
    addPart(doc, 'source', 'orders', 'webhook')
    addPart(doc, 'sink', 'erp', 'rest')
    doc.sinks.erp.config = { url: 'https://erp.example.org/orders', bearer: 'plain-token' }
    doc.sources.orders.config = { ...doc.sources.orders.config, api_key: 'also-plain' }
    const p = checkSpec(doc)
    expect(p).toContain('sinks.erp.config.bearer: a credential is written out: give it as env:NAME or file:/path')
    expect(p.some((x) => x.startsWith('sources.orders.config.api_key: a credential is written out'))).toBe(true)
    expect(p.join(' ')).not.toMatch(/plain-token|also-plain/)
    doc.sinks.erp.config.bearer = 'env:ERP_TOKEN'
    doc.sources.orders.config.api_key = 'file:/run/secrets/orders'
    expect(checkSpec(doc).filter((x) => x.includes('credential'))).toEqual([])
  })
})

describe('the spec, checked in the browser as spec.py parse() checks it', () => {
  const clean = () => {
    const doc = newSpec('lyceum-credentials')
    addPart(doc, 'source', 'sis', 'filedrop')
    doc.sources.sis.config = { path: '/data/sis-out', suffix: '.csv', id_field: 'award_id' }
    addPart(doc, 'action', 'issue', 'attestation')
    doc.actions.issue.config = { attestation_type: 'lyceum.credential_awarded' }
    const m = addMapping(doc, 'sis', 'issue')
    expect(m.name).toBe('sis-to-issue')                                 // a mapping is named for what it joins
    m.name = 'credential'
    m.fields = { award: '$.payload.data.award_id', institution: 'LYCEUM-DEMO' }
    return doc
  }

  it('a new spec names its identity by reference and is clean once a mapping joins a source to an action', () => {
    const doc = newSpec('my-proxy')
    expect(doc.identity).toEqual({ agent_did: 'env:AGENT_DID', client_id: 'env:CLIENT_ID', client_secret: 'env:CLIENT_SECRET' })
    expect(checkSpec(clean())).toEqual([])
  })

  it('the core schema: a bad name, an unknown top-level key', () => {
    const doc = clean()
    doc.name = 'has spaces'
    doc.extra = 1
    const p = checkSpec(doc)
    expect(p.some((x) => x.startsWith('spec.name: '))).toBe(true)
    expect(p.some((x) => x.startsWith('spec: ') && x.includes('extra'))).toBe(true)
  })

  it('a plugin\'s own config schema, and an unknown plugin type', () => {
    const doc = clean()
    delete doc.sources.sis.config.path                                  // filedrop requires a path
    doc.actions.issue.type = 'no_such_action'
    const p = checkSpec(doc)
    expect(p.some((x) => x.startsWith('sources.sis.config: ') && x.includes("'path'"))).toBe(true)
    expect(p).toContain("actions.issue.type: no action called 'no_such_action'")
  })

  it('a mapping names a real source and a real action or sink, once', () => {
    const doc = clean()
    doc.mappings[0].from = 'nowhere'
    doc.mappings.push({ ...doc.mappings[0], from: 'sis', to: 'nothing' })
    const p = checkSpec(doc)
    expect(p).toContain("mappings[0].from: no source called 'nowhere'")
    expect(p).toContain("mappings[1].to: no action or sink called 'nothing'")
    expect(p).toContain("mappings[1].name: 'credential' names another mapping too")
  })

  it('an action calls TheProtocol, so the spec needs its registry and identity', () => {
    const doc = clean()
    delete doc.registry
    expect(checkSpec(doc).some((x) => x.startsWith('spec.registry: actions.issue (attestation) calls TheProtocol'))).toBe(true)
  })

  it('an action and a sink may not share a name, and a value node is checked when the spec is built', () => {
    const doc = clean()
    addPart(doc, 'sink', 'issue', 'rest')
    doc.sinks.issue.config = { url: 'https://x.example.org/' }
    doc.mappings[0].fields.ects = { path: '$.payload.data.ects', as: 'no-such-type' }
    const p = checkSpec(doc)
    expect(p).toContain("sinks.issue: an action is called 'issue' too (actions and sinks share one namespace)")
    expect(p.some((x) => x.startsWith('mappings[0].fields.ects') && x.includes("(mapping 'credential')"))).toBe(true)
  })

  it('removing a part removes the mappings that used it', () => {
    const doc = clean()
    removePart(doc, 'action', 'issue')
    expect(doc.actions.issue).toBeUndefined()
    expect(doc.mappings).toEqual([])
  })
})

describe('what the builder gives you', () => {
  const doc = () => {
    const d = newSpec('lyceum-credentials')
    addPart(d, 'source', 'sis', 'filedrop')
    d.sources.sis.config = { path: '/data/sis-out', suffix: '.csv' }
    addPart(d, 'action', 'issue', 'attestation')
    d.actions.issue.config = { attestation_type: 'lyceum.credential_awarded' }
    addMapping(d, 'sis', 'issue').fields = { award: '$.payload.data.award_id' }
    return d
  }

  it('proxy.yaml in the spec\'s own order, credentials by reference', () => {
    const y = toProxyYaml(doc())
    const order = ['version:', 'name:', 'registry:', 'identity:', 'state:', 'sources:', 'actions:', 'sinks:', 'mappings:', 'retry:']
    const at = order.map((k) => y.indexOf(`\n${k}`) >= 0 ? y.indexOf(`\n${k}`) : y.indexOf(k))
    expect(at.every((i) => i >= 0)).toBe(true)
    expect([...at]).toEqual([...at].sort((a, b) => a - b))
    expect(y).toContain('client_secret: "env:CLIENT_SECRET"')         // quoted: a value with a colon in it
    expect(y).toContain('name: lyceum-credentials')
    expect(y.startsWith('# ')).toBe(true)                              // says it was made in the console, and how to check it
  })

  it('a compose snippet that mounts the spec and passes the credentials from the environment', () => {
    const c = composeSnippet(doc())
    expect(c).toContain('lyceum-credentials')
    expect(c).toContain('./proxy.yaml:/app/proxy.yaml:ro')
    // pass 2 (session-lead seq 4069): pinned to the SDK the catalog was made from (read from the catalog, never a literal:
    // V0664's M9 moved it to 0.9.0 and a pinned 0.8.0 here went red)
    expect(SDK_VERSION).toMatch(/^\d+\.\d+\.\d+$/)
    expect(c).toContain(`pip install --quiet 'theprotocol-sdk[proxy]==${SDK_VERSION}'`)
    expect(c).not.toContain('/sdk')
    for (const v of ['AGENT_DID', 'CLIENT_ID', 'CLIENT_SECRET']) expect(c).toContain(v)
    expect(c).not.toMatch(/env:CLIENT_SECRET/)
  })

  it('the run commands: validate, a dry run, then for real', () => {
    expect(runCommands(doc())).toEqual(['tp-proxy validate proxy.yaml', 'tp-proxy run proxy.yaml --dry-run', 'tp-proxy run proxy.yaml'])
  })

  it('a live preview of a mapping on a pasted row, wrapped as its source delivers it, through the shared mapping port', () => {
    const d = doc()
    const m = d.mappings[0]
    m.fields = { award: '$.payload.data.award_id', ects: { path: '$.payload.data.ects', as: 'int' }, school: 'LYCEUM-DEMO' }
    m.when = { path: '$.payload.data.status', equals: 'AWARDED' }
    expect(previewMapping(m, 'filedrop', { award_id: 'A-1', ects: '30', status: 'AWARDED' })).toEqual(
      { taken: true, fields: { award: 'A-1', ects: 30, school: 'LYCEUM-DEMO' } })
    expect(previewMapping(m, 'filedrop', { award_id: 'A-2', ects: '30', status: 'REVOKED' })).toEqual({ taken: false })
    const r = previewMapping(m, 'filedrop', { ects: '30', status: 'AWARDED' })
    expect(r.taken).toBe(true)
    expect(r.refused).toMatch(/award/)                                 // the field and the rule, never the value
  })
})

// pass 2 (session-lead seq 4069): a setting's label in words, the key beside it; a setting with a known shape gets a form
describe('a setting, for a person', () => {
  it('its key in words: an acronym as one writes it, a unit said', () => {
    expect(fieldWords('agent_did')).toBe('Agent DID')
    expect(fieldWords('client_id')).toBe('Client ID')
    expect(fieldWords('mtls')).toBe('mTLS')
    expect(fieldWords('timeout_s')).toBe('Timeout (seconds)')
    expect(fieldWords('ca_file')).toBe('CA file')
    expect(fieldWords('id_field')).toBe('ID field')
    expect(fieldWords('dir')).toBe('Folder')
    expect(fieldWords('idempotency_header')).toBe('Idempotency header')
  })

  it('its shape: a sub-form for an object with known fields, lines for a list of text, name: value lines for a map of text, JSON only for the rest', () => {
    const idn = fieldsOf(CORE_SCHEMA.properties.identity).find((f) => f.key === 'mtls')!
    expect(idn.shape).toBe('form')
    expect(Object.keys(idn.schema.properties)).toEqual(['dir', 'enabled'])
    const shape = (role: Role, type: string, key: string) => fieldsOf(plugin(role, type)!.config_schema).find((f) => f.key === key)!.shape
    expect(shape('sink', 'email_digest', 'to')).toBe('lines')
    expect(shape('sink', 'rest', 'headers')).toBe('pairs')
    expect(shape('sink', 'email_digest', 'smtp')).toBe('form')
    expect(shape('sink', 'quantum_submit', 'backend')).toBe('json')
    expect(shape('source', 'mqtt', 'topics')).toBe('json')
    expect(shape('sink', 'rest', 'url')).toBeUndefined()
  })
})

// pass 4: a problem is said as where and what, and names the control that fixes it
describe('a problem, placed', () => {
  it('splits where from what and finds the field a part\'s problem is about', () => {
    expect(problemTarget("sources.erp-hooks.config: 'listen' is a required property"))
      .toEqual({ where: 'sources.erp-hooks.config', what: "'listen' is a required property", target: 'ppf-source-erp-hooks-listen' })
    expect(problemTarget('sinks.erp.config.bearer: a credential is written out: give it as env:NAME or file:/path').target).toBe('ppf-sink-erp-bearer')
    expect(problemTarget("actions.pay.config: 'max_amount' is a required property").target).toBe('ppf-action-pay-max_amount')
    expect(problemTarget('identity.client_secret: a credential is written out').target).toBe('ppf-identity-client_secret')
    expect(problemTarget("spec.identity: 'agent_did' is a required property").target).toBe('ppf-identity-agent_did')
    expect(problemTarget("mappings[2].to: no action or sink called 'x'").target).toBe('pb-mapping-2-to')
    expect(problemTarget('mappings[0].fields.award: a path must start with $. (mapping m)').target).toBe('pb-mapping-0')
    expect(problemTarget('something else entirely')).toEqual({ where: '', what: 'something else entirely', target: null })
  })
})
