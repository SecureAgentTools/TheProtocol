// The compliance documents the console publishes at /compliance/doc/<slug> (views/ComplianceDoc.vue), one list for the view and the static
// pages (V0667 gwo_a9f121caa4138ec9b369814c: a static page never keeps a second copy of the source).
export interface DocMeta { slug: string; file: string; title: string; sub: string }
export const COMPLIANCE_DOCS: DocMeta[] = [
  { slug: 'iso-42001-alignment', file: 'ISO_42001_Alignment.md', title: 'ISO 42001 Alignment', sub: 'Master document: clause-by-clause mapping of the AI management system' },
  { slug: 'risk-assessment-framework', file: 'Risk_Assessment_Framework.md', title: 'Risk Assessment Framework', sub: 'AI and operational risk register with likelihood×impact scoring and mitigations' },
  { slug: 'incident-response-procedures', file: 'Incident_Response_Procedures.md', title: 'Incident Response Procedures', sub: 'P1–P4 classification, detection, response and communication' },
  { slug: 'data-protection-policy', file: 'Data_Protection_Policy.md', title: 'Data Protection Policy', sub: 'GDPR alignment, data classification and breach notification' },
  { slug: 'change-management-policy', file: 'Change_Management_Policy.md', title: 'Change Management Policy', sub: 'Change categories, testing requirements and rollback procedures' },
  { slug: 'compliance-audit-procedures', file: 'Compliance_Audit_Procedures.md', title: 'Compliance Audit Procedures', sub: 'Continuous-to-quarterly audit schedule and self-assessment checklist' },
  { slug: 'ai-system-lifecycle', file: 'AI_System_Lifecycle.md', title: 'AI System Lifecycle', sub: 'Per-component purpose, design, limitations, bias, oversight and decommission' },
  { slug: 'jurisdiction-profiles', file: 'Jurisdiction_Profiles.md', title: 'Jurisdiction Profiles', sub: 'Operator-declared, enforced and publicly attested feature scope per deployment' },
]
