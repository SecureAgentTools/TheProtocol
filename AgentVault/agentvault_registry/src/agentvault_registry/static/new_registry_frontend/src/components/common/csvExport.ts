/**
 * components/common/csvExport.ts — Shared CSV export helper.
 *
 * Pulled out as a utility 2026-05-07 (Polish #1) — Builds #1 (webhook
 * deliveries), #3 (TEG statement), and #6 (EventStore export) each had
 * their own ~30-line CSV serializer with subtle differences (some had
 * UTF-8 BOM, some forgot to escape commas in fields, etc.). This is the
 * canonical implementation.
 *
 * Output: RFC 4180-compliant CSV with UTF-8 BOM (so Excel reads it
 * correctly). Fields are double-quoted when they contain `,`, `"`, `\n`,
 * or `\r`. Embedded `"` is escaped to `""`. `null`/`undefined` → empty.
 */

export interface CsvColumn<T> {
  /** Column header label as shown in the CSV. */
  label: string
  /** Function to extract the cell value from a row. Return any
   *  primitive; we'll stringify it via `String(...)`. Return `null`
   *  or `undefined` for empty cells. */
  value: (row: T) => string | number | boolean | null | undefined
}

/** Serialize a single field according to RFC 4180. */
function escapeField(v: string | number | boolean | null | undefined): string {
  if (v === null || v === undefined) return ''
  const s = typeof v === 'string' ? v : String(v)
  // Quote if it contains a delimiter, quote, or newline.
  if (/[",\r\n]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`
  }
  return s
}

/** Build the full CSV string, including UTF-8 BOM and CRLF line endings. */
export function buildCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const header = columns.map(c => escapeField(c.label)).join(',')
  const lines = rows.map(r => columns.map(c => escapeField(c.value(r))).join(','))
  // ﻿ = UTF-8 BOM. Prevents Excel mojibake on non-ASCII chars.
  // CRLF per RFC 4180 spec.
  return '﻿' + [header, ...lines].join('\r\n') + '\r\n'
}

/** Trigger a browser download for the given CSV. Uses a temporary blob URL. */
export function downloadCsv<T>(
  rows: T[],
  columns: CsvColumn<T>[],
  filename: string,
): void {
  const csv = buildCsv(rows, columns)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename.endsWith('.csv') ? filename : `${filename}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  // Revoke after a tick so Safari has a chance to honour the download.
  setTimeout(() => URL.revokeObjectURL(url), 4000)
}

/** Helper to format an ISO date for filename use (avoids `:` and `T`). */
export function csvFilenameTimestamp(d: Date = new Date()): string {
  return d.toISOString().slice(0, 19).replace(/[:T]/g, '-')
}
