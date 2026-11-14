// Small text helpers shared by the pages.
import type { DocumentOut, Label } from './api/types'

/** The status column of the documents table. The error text of a failed document is shown apart. */
export function statusText(doc: DocumentOut): string {
  switch (doc.status) {
    case 'ready':
      return 'ready'
    case 'processing':
      return 'processing…'
    case 'queued':
      return doc.attempts > 0 ? `retry ${doc.attempts}/${doc.max_attempts}` : 'queued'
    case 'failed':
      return 'failed'
  }
}

/** What to show for anything a call threw. ApiError's message is the API's `detail`. */
export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** The verdict label as a reader sees it. */
export function labelText(label: Label): string {
  switch (label) {
    case 'supported':
      return 'Supported by sources'
    case 'partially_supported':
      return 'Partly supported'
    case 'unsupported':
      return 'Not supported by sources'
    case 'not_found':
      return 'Nothing found in your documents'
  }
}
