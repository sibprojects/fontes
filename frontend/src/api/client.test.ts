import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, addUrl, deleteDocument, getQuestion, listDocuments, listQuestions, uploadDocument } from './client'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function stubFetch(response: Response) {
  const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) => response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('client', () => {
  it('listDocuments calls /api/documents', async () => {
    const fetchMock = stubFetch(json([{ id: 'd1' }]))
    expect(await listDocuments()).toEqual([{ id: 'd1' }])
    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents')
  })

  it('uploadDocument sends multipart field file', async () => {
    const fetchMock = stubFetch(json({ id: 'd1' }, 201))
    const file = new File(['# A'], 'a.md', { type: 'text/markdown' })
    await uploadDocument(file)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/documents')
    expect(init?.method).toBe('POST')
    expect(init?.body).toBeInstanceOf(FormData)
    expect((init!.body as FormData).get('file')).toBe(file)
  })

  it('addUrl posts JSON to /api/documents/url', async () => {
    const fetchMock = stubFetch(json({ id: 'd1' }, 201))
    await addUrl('https://example.com')
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/documents/url')
    expect(init?.body).toBe(JSON.stringify({ url: 'https://example.com' }))
  })

  it('deleteDocument uses DELETE', async () => {
    const fetchMock = stubFetch(new Response(null, { status: 204 }))
    await deleteDocument('d1')
    expect(fetchMock.mock.calls[0][0]).toBe('/api/documents/d1')
    expect(fetchMock.mock.calls[0][1]?.method).toBe('DELETE')
  })

  it('listQuestions and getQuestion read /api/questions', async () => {
    const fetchMock = stubFetch(json([]))
    await listQuestions()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/questions')
    stubFetch(json({ id: 'q1' }))
    expect(await getQuestion('q1')).toEqual({ id: 'q1' })
  })

  it('ApiError carries detail and status', async () => {
    stubFetch(json({ detail: 'The file exceeds the 20971520-byte limit' }, 413))
    const error = await uploadDocument(new File(['x'], 'a.pdf')).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 413, message: 'The file exceeds the 20971520-byte limit' })
  })

  it('ApiError falls back to HTTP status for a non-JSON body', async () => {
    stubFetch(new Response('<html>Bad Gateway</html>', { status: 502 }))
    const error = await listDocuments().catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 502, message: 'HTTP 502' })
  })

  it('ApiError falls back for a 422 whose detail is a list', async () => {
    stubFetch(json({ detail: [{ msg: 'Field required' }] }, 422))
    const error = await addUrl('').catch((e: unknown) => e)
    expect(error).toMatchObject({ status: 422, message: 'HTTP 422' })
  })
})
