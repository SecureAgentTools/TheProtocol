// V0664 M5: M4's answers, exactly, from sessionlogs2026/M4_ANSWER_SHAPES_2026-11-14.md (produced by the code of AgentVault
// v0664/workflow-templates 26533115d over its tests' store, not written by hand). The readers and the views are tested against these.
export const LISTING = {
  id: 'wtpl_a93a91a8d6c64f2c76aa', slug: 'crm-to-pg', title: 'CRM to Postgres', summary: 'one table', kind: 'migration',
  from_kind: 'sql', to_kind: 'sql', owner_agent_did: 'did:a:owner', visibility: 'public', pricing_model: 'purchase',
  price: '5.0000000000', price_currency: 'AVT', fork_share_bps: 2000, forked_from_template_id: null, forked_from_version: null,
  current_version: 1, current_content_hash: 'ac08dfdd71de126f10251f4679272949caca11810ab8294f6d7439cf99dc590e',
  created_at: '2026-11-14T14:00:00+00:00', updated_at: '2026-11-14T14:00:00+00:00',
  counts: { kit_downloads: 7, instantiations: 4, certified: 2, forks: 1 },
}
export const FREE_LISTING = { ...LISTING, id: 'wtpl_f1', slug: 'free-one', title: 'Free one', pricing_model: 'free', price: '0.0000000000' }
export const STRUCTURE = {
  schema: 'theprotocol.migration/v1', name: 'crm-customers-to-postgres',
  from: { kind: 'sql', engines: ['postgresql', 'mysql', 'sqlserver', 'sqlite'], what: 'a customers table' },
  to: { kind: 'sql', engines: ['postgresql'], what: 'public.customers' },
  parameters: ['SOURCE_ENGINE', 'SOURCE_PASSWORD', 'TARGET_TABLE'], secret_parameters: ['SOURCE_PASSWORD'],
  steps: [{ key: 'dry-run', role: 'migration.runner', budget_share: 40, input_from: null },
    { key: 'reconcile', role: 'migration.reconciler', budget_share: 60, input_from: 'dry-run' }],
  load_mappings: ['customers'], reconcile: [{ mapping: 'customers', fields: 3 }], samples: 1, rollback: 'auto', cutover_steps: 4,
}
export const DETAIL = {
  ...LISTING,
  versions: [{ version: 1, content_hash: LISTING.current_content_hash, changelog: 'first version', published_at: '2026-11-14T14:00:00+00:00' }],
  structure: STRUCTURE,
}
export const VERSION = {
  template_id: LISTING.id, version: 1, manifest: { schema: 'theprotocol.migration/v1', name: 'crm-customers-to-postgres' },
  files: { 'migration.yaml': 'schema: theprotocol.migration/v1\n', 'proxy.yaml': 'version: 1\nsources:\n  customers: {type: sql}\n',
    'README.md': '# Customers\n', 'sample/customers.csv': 'id,name,email,created_at\n1,Ada,ada@example.org\n' },
  content_hash: LISTING.current_content_hash, changelog: 'first version', published_at: '2026-11-14T14:00:00+00:00',
}
export const PURCHASE_FORK = { ok: true, template_id: 'wtpl_d5aaa3eb86e1b23fd947', price: '10', currency: 'AVT', parent_share: '2.0000000000' }
export const FORKED = { template_id: 'wtpl_d667d1b4ba52c617c843', version: 1, forked_from: LISTING.id, forked_from_version: 1, published: false }
export const INSTANTIATED = { workflow_id: 'wf_1', template_id: LISTING.id, version: 1, content_hash: LISTING.current_content_hash }
export const REFUSED_402 = { code: 'payment_required', detail: 'This template is purchase-priced — buy it first (POST …/purchase), then use its files' }
