// V0667 D7: a signed document saved as a file, byte for byte what the registry sent (the digest is over the report inside, but the file keeps the envelope whole so an offline verifier reads it as it is).
export function fileNameOf(doc: Record<string, any>): string {
  const subject = String(doc?.subject ?? 'document').replace(/[^A-Za-z0-9._-]/g, '_')
  return `${subject}.${doc?.kind === 'distribution.change.record' ? 'record' : 'report'}.json`
}

export function downloadSigned(doc: Record<string, any>): void {
  const blob = new Blob([JSON.stringify(doc, null, 2) + '\n'], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileNameOf(doc)
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
