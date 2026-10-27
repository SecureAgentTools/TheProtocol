/**
 * §ZKV2 (2026-10-13): the registry compares every stated public input with the value inside the proof, and each
 * tutorial proof's reference is derived from the submitting agent's DID and a random label, so the generate-proof
 * steps send the agent DID the track captured, and the submit steps send the circuit_id and public_inputs
 * (reference_label included) the generate-proof step answered (captured), never hard-coded ones, with that agent's
 * token; the v1.0.0 circuits are retired; reputation is read from the registry's agent record, not the TEG.
 */
import { describe, expect, it } from 'vitest'
import { attestationsComplianceTrack as track } from './attestationsCompliance.track'

const step = (id: string) => {
  const s = track.steps.find((x) => x.id === id)
  if (!s) throw new Error(`no step ${id}`)
  return s
}

describe('Track 11 proves and submits v2.0.0 attestations', () => {
  it.each([
    ['ac-generate-fair-markup', 'ac-submit-fair-markup', 'fairMarkupPolicy/v2.0.0', 'fairMarkup'],
    ['ac-generate-resource-usage', 'ac-submit-resource-usage', 'accurateResourceUsagePolicy/v2.0.0', 'resource'],
  ])('%s feeds %s', (gen, sub, circuit, prefix) => {
    const g = step(gen)
    expect(g.apiCall.body).toEqual({ circuit_id: circuit, agent_did: '$agentDid' })
    expect(g.apiCall.bodyDynamic).toEqual([{ jsonPath: 'agent_did', capturedKey: 'agentDid' }])
    const caps = Object.fromEntries((g.captures ?? []).map((c) => [c.responsePath, c.key]))
    expect(caps).toMatchObject({
      proof_bytes_base64: prefix === 'fairMarkup' ? 'fairMarkupProof' : 'resourceProof',
      circuit_id: `${prefix}CircuitId`,
      public_inputs: `${prefix}Inputs`,
    })

    const s = step(sub)
    expect(s.apiCall.path).toBe('/attestations/submit')
    const dyn = Object.fromEntries((s.apiCall.bodyDynamic ?? []).map((d) => [d.jsonPath, d.capturedKey]))
    expect(dyn).toEqual({
      circuit_id: `${prefix}CircuitId`,
      'proof_data.proof_bytes': caps.proof_bytes_base64,
      public_inputs: `${prefix}Inputs`,
    })
    // nothing stated by hand: every value comes from the proof step's answer
    expect(s.apiCall.body?.public_inputs).toBe(`$${prefix}Inputs`)
    // the proof is submitted by the agent whose DID it was made for
    expect(s.apiCall.authType).toBe('agent')
    expect(s.apiCall.authTokenRef).toBe('$agentToken')
  })

  it('makes the proofs for the agent it created', () => {
    const created = step('ac-create-agent')
    expect((created.captures ?? []).some((c) => c.key === 'agentDid' && c.responsePath === 'agent_did')).toBe(true)
    const token = step('ac-agent-token')
    expect(token.requiresStepId).toBe('ac-create-agent')
  })

  it('reads reputation from the registry agent record, which attestations change', () => {
    const r = step('ac-check-reputation')
    expect(r.apiCall.method).toBe('GET')
    expect(r.apiCall.path).toBe('/agents/by-did/{did}')
    expect(r.apiCall.pathParams).toEqual({ did: '$agentDid' })
    expect(r.validation.requiredResponseKeys).toContain('reputation_score')
    expect(JSON.stringify(r.apiCall)).not.toContain('/teg/')
  })

  it('says the reference names the submitting agent and one attestation per circuit and reference', () => {
    const text = step('ac-submit-fair-markup').explanation
    expect(text).toContain("submitting agent's DID")
    expect(text).toContain('One verified attestation per circuit and reference')
    expect(text).not.toMatch(/A proof counts once/)
  })

  it('names no retired v1.0.0 circuit in any call', () => {
    for (const s of track.steps) expect(JSON.stringify(s.apiCall)).not.toContain('v1.0.0')
  })
})
