// Every call to the backend goes through here. The `/api` prefix is stripped by the Vite dev
// proxy or by nginx, so the browser only ever talks to the origin that served the page.
import type { AnswerOut, DocumentOut, QuestionSummaryOut } from './types'

/** A non-2xx answer from the API; `message` is the API's `detail` when it sent one. */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Throws ApiError unless the response is 2xx. Shared with the SSE reader. */
export async function ensureOk(response: Response): Promise<Response> {
  if (response.ok) return response
  let message = `HTTP ${response.status}`
  try {
    const body: unknown = await response.json()
    if (typeof body === 'object' && body !== null && 'detail' in body && typeof body.detail === 'string') {
      message = body.detail
    }
  } catch {
    // Not JSON (for example an HTML error page from a proxy): keep the status text.
  }
  throw new ApiError(response.status, message)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await ensureOk(await fetch(`/api${path}`, init))
  return (await response.json()) as T
}

export function postJson(body: unknown): RequestInit {
  return { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) }
}

export function listDocuments(): Promise<DocumentOut[]> {
  return request('/documents')
}

export function uploadDocument(file: File): Promise<DocumentOut> {
  const form = new FormData()
  form.append('file', file)
  return request('/documents', { method: 'POST', body: form })
}

export function addUrl(url: string): Promise<DocumentOut> {
  return request('/documents/url', postJson({ url }))
}

export async function deleteDocument(id: string): Promise<void> {
  await ensureOk(await fetch(`/api/documents/${id}`, { method: 'DELETE' }))
}

export function listQuestions(): Promise<QuestionSummaryOut[]> {
  return request('/questions')
}

export function getQuestion(id: string): Promise<AnswerOut> {
  return request(`/questions/${id}`)
}
