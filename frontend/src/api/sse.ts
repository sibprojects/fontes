// POST /ask answers with Server-Sent Events. The browser's EventSource only does GET, so the
// stream is read with fetch and parsed here.
import { ensureOk, postJson } from './client'
import type { AskEvent, Verdict } from './types'

export type SseEvent = { event: string; data: string }

const CLOSED_EARLY = 'The connection closed before the answer was verified.'

/** Splits a byte stream into SSE events. A read may end anywhere, even inside a character. */
export async function* parseSse(chunks: AsyncIterable<Uint8Array>): AsyncGenerator<SseEvent> {
  const decoder = new TextDecoder()
  let buffer = ''
  for await (const chunk of chunks) {
    buffer += decoder.decode(chunk, { stream: true }).replace(/\r\n?/g, '\n')
    let end: number
    while ((end = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, end)
      buffer = buffer.slice(end + 2)
      const event = parseBlock(block)
      if (event) yield event
    }
  }
  // Whatever is left has no terminating blank line: an incomplete event, dropped.
}

function parseBlock(block: string): SseEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line === '' || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    else if (field === 'data') data.push(value)
  }
  return data.length ? { event, data: data.join('\n') } : null
}

async function* bodyChunks(body: ReadableStream<Uint8Array>): AsyncGenerator<Uint8Array> {
  const reader = body.getReader()
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) return
      yield value
    }
  } finally {
    reader.releaseLock()
  }
}

/**
 * Asks a question and yields the answer as it streams. A rejected question (for example 422)
 * throws ApiError before anything is yielded. The stream always ends with a verdict or an error.
 */
export async function* ask(question: string, signal?: AbortSignal): AsyncGenerator<AskEvent> {
  const response = await ensureOk(await fetch('/api/ask', { ...postJson({ question }), signal }))
  if (!response.body) {
    yield { type: 'error', detail: CLOSED_EARLY }
    return
  }
  for await (const { event, data } of parseSse(bodyChunks(response.body))) {
    if (event === 'token') {
      yield { type: 'token', text: (JSON.parse(data) as { text: string }).text }
    } else if (event === 'verdict') {
      yield { type: 'verdict', verdict: JSON.parse(data) as Verdict }
      return
    } else if (event === 'error') {
      yield { type: 'error', detail: (JSON.parse(data) as { detail: string }).detail }
      return
    }
  }
  yield { type: 'error', detail: CLOSED_EARLY }
}
