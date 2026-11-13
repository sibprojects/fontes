import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, addUrl, deleteDocument, listDocuments, uploadDocument } from '../api/client'
import type { DocumentOut } from '../api/types'
import { DocumentsPage, POLL_MS } from './DocumentsPage'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  listDocuments: vi.fn(),
  uploadDocument: vi.fn(),
  addUrl: vi.fn(),
  deleteDocument: vi.fn(),
}))

const list = vi.mocked(listDocuments)

function doc(overrides: Partial<DocumentOut>): DocumentOut {
  return {
    id: 'd1',
    title: 'guide.md',
    source_type: 'markdown',
    status: 'ready',
    url: null,
    error: null,
    attempts: 1,
    max_attempts: 3,
    created_at: '2026-11-13T10:00:00Z',
    ...overrides,
  }
}

// applyAccept off: a person can still pick "All files" in the browser's file dialog.
function setup() {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime, applyAccept: false })
  render(<DocumentsPage />)
  return user
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  vi.resetAllMocks()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('DocumentsPage', () => {
  it('lists documents with status and retry count', async () => {
    list.mockResolvedValue([doc({ status: 'queued', attempts: 1 })])
    setup()
    expect(await screen.findByText('guide.md')).toBeInTheDocument()
    expect(screen.getByText('retry 1/3')).toBeInTheDocument()
  })

  it('links a URL document to its page', async () => {
    list.mockResolvedValue([doc({ title: 'Example', source_type: 'url', url: 'https://example.com/' })])
    setup()
    expect(await screen.findByRole('link', { name: 'Example' })).toHaveAttribute('href', 'https://example.com/')
  })

  it('shows the error of a failed document', async () => {
    list.mockResolvedValue([doc({ status: 'failed', error: 'Gave up after 3 attempts' })])
    setup()
    expect(await screen.findByText('failed')).toBeInTheDocument()
    expect(screen.getByText('Gave up after 3 attempts')).toBeInTheDocument()
  })

  it('polls while a document is processing and stops when ready', async () => {
    list
      .mockResolvedValueOnce([doc({ status: 'processing' })])
      .mockResolvedValue([doc({ status: 'ready' })])
    setup()
    expect(await screen.findByText('processing…')).toBeInTheDocument()
    expect(list).toHaveBeenCalledTimes(1)
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS))
    expect(await screen.findByText('ready')).toBeInTheDocument()
    expect(list).toHaveBeenCalledTimes(2)
    await act(() => vi.advanceTimersByTimeAsync(POLL_MS * 3))
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('uploads the chosen file and refreshes', async () => {
    list.mockResolvedValueOnce([]).mockResolvedValue([doc({ status: 'queued', attempts: 0 })])
    vi.mocked(uploadDocument).mockResolvedValue(doc({}))
    const user = setup()
    await screen.findByText(/No documents yet/)
    const file = new File(['# Guide'], 'guide.md', { type: 'text/markdown' })
    await user.upload(screen.getByLabelText('File'), file)
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    expect(uploadDocument).toHaveBeenCalledWith(file)
    expect(await screen.findByText('guide.md')).toBeInTheDocument()
  })

  it('adds a URL', async () => {
    list.mockResolvedValue([])
    vi.mocked(addUrl).mockResolvedValue(doc({}))
    const user = setup()
    await user.type(screen.getByLabelText('URL'), 'https://example.com')
    await user.click(screen.getByRole('button', { name: 'Add URL' }))
    expect(addUrl).toHaveBeenCalledWith('https://example.com')
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('shows the API detail when an upload is rejected', async () => {
    list.mockResolvedValue([])
    vi.mocked(uploadDocument).mockRejectedValue(
      new ApiError(415, "Unsupported file type '.txt'; supported: .pdf, .md"),
    )
    const user = setup()
    await user.upload(screen.getByLabelText('File'), new File(['x'], 'notes.txt'))
    await user.click(screen.getByRole('button', { name: 'Upload' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("Unsupported file type '.txt'")
  })

  it('shows a failed list fetch', async () => {
    list.mockRejectedValue(new ApiError(502, 'HTTP 502'))
    setup()
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 502')
  })

  it('deletes after confirm', async () => {
    list.mockResolvedValueOnce([doc({})]).mockResolvedValue([])
    vi.mocked(deleteDocument).mockResolvedValue()
    vi.stubGlobal('confirm', vi.fn(() => true))
    const user = setup()
    const row = (await screen.findByText('guide.md')).closest('tr')!
    await user.click(within(row).getByRole('button', { name: 'Delete' }))
    expect(window.confirm).toHaveBeenCalledWith('Delete guide.md?')
    expect(deleteDocument).toHaveBeenCalledWith('d1')
    expect(await screen.findByText(/No documents yet/)).toBeInTheDocument()
  })

  it('does not delete when the confirm is cancelled', async () => {
    list.mockResolvedValue([doc({})])
    vi.stubGlobal('confirm', vi.fn(() => false))
    const user = setup()
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(deleteDocument).not.toHaveBeenCalled()
  })

  it('shows the empty state', async () => {
    list.mockResolvedValue([])
    setup()
    expect(
      await screen.findByText('No documents yet. Upload a PDF, Markdown or HTML file, or add a URL.'),
    ).toBeInTheDocument()
  })
})
