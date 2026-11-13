import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './client'
import { ask, parseSse } from './sse'
import type { AskEvent } from './types'

const encoder = new TextEncoder()

async function* chunks(...parts: (string | Uint8Array)[]): AsyncGenerator<Uint8Array> {
  for (const part of parts) {
    yield typeof part === 'string' ? encoder.encode(part) : part
  }
}

async function collect<T>(items: AsyncIterable<T>): Promise<T[]> {
  const out: T[] = []
  for await (const item of items) out.push(item)
  return out
}

function streamResponse(text: string): Response {
  return new Response(text, { status: 200, headers: { 'content-type': 'text/event-stream' } })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('parseSse', () => {
  it('parses events and joins data lines', async () => {
    const events = await collect(
      parseSse(chunks('event: token\ndata: {"text":"a"}\n\nevent: verdict\ndata: x\ndata: y\n\n')),
    )
    expect(events).toEqual([
      { event: 'token', data: '{"text":"a"}' },
      { event: 'verdict', data: 'x\ny' },
    ])
  })

  it('events split across reads and inside a UTF-8 character', async () => {
    const bytes = encoder.encode('event: token\ndata: {"text":"Привет"}\n\n')
    // "и" is two bytes; cut between them, and once more inside the header line.
    const cut = encoder.encode('event: token\ndata: {"text":"Пр').length + 1
    const events = await collect(parseSse(chunks(bytes.slice(0, 5), bytes.slice(5, cut), bytes.slice(cut))))
    expect(events).toEqual([{ event: 'token', data: '{"text":"Привет"}' }])
  })

  it('ignores comments and a trailing partial event', async () => {
    const events = await collect(parseSse(chunks(': ping\n\nevent: token\ndata: 1\n\nevent: tok')))
    expect(events).toEqual([{ event: 'token', data: '1' }])
  })

  it('accepts CRLF line endings and defaults the event name', async () => {
    const events = await collect(parseSse(chunks('data: 1\r\n\r\n')))
    expect(events).toEqual([{ event: 'message', data: '1' }])
  })
})

describe('ask', () => {
  it('ask yields token, then verdict', async () => {
    const verdict = { question_id: 'q1', label: 'supported', paragraphs: [], citations: [] }
    const fetchMock = vi.fn(async () =>
      streamResponse(
        `event: token\ndata: {"text": "Hi [1]."}\n\nevent: verdict\ndata: ${JSON.stringify(verdict)}\n\n`,
      ),
    )
    vi.stubGlobal('fetch', fetchMock)
    const events = await collect(ask('How?'))
    expect(events).toEqual<AskEvent[]>([
      { type: 'token', text: 'Hi [1].' },
      { type: 'verdict', verdict: verdict as never },
    ])
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/ask',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ question: 'How?' }) }),
    )
  })

  it('ask passes an error event through', async () => {
    vi.stubGlobal('fetch', async () => streamResponse('event: error\ndata: {"detail": "Cannot reach Ollama"}\n\n'))
    expect(await collect(ask('How?'))).toEqual([{ type: 'error', detail: 'Cannot reach Ollama' }])
  })

  it('ask reports a stream that ends without a verdict', async () => {
    vi.stubGlobal('fetch', async () => streamResponse('event: token\ndata: {"text": "Hi"}\n\n'))
    const events = await collect(ask('How?'))
    expect(events.at(-1)).toEqual({
      type: 'error',
      detail: 'The connection closed before the answer was verified.',
    })
  })

  it('ask throws ApiError with the detail of a 422', async () => {
    vi.stubGlobal(
      'fetch',
      async () =>
        new Response(JSON.stringify({ detail: 'The question is empty' }), {
          status: 422,
          headers: { 'content-type': 'application/json' },
        }),
    )
    const error = await collect(ask(' ')).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 422, message: 'The question is empty' })
  })
})
