import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, listQuestions } from '../api/client'
import type { QuestionSummaryOut } from '../api/types'
import { HISTORY_RETRY_MS, HistorySidebar } from './HistorySidebar'

vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  listQuestions: vi.fn(),
}))

const list = vi.mocked(listQuestions)

const questions: QuestionSummaryOut[] = [
  { id: 'q2', question: 'Newest question?', label: 'supported', created_at: '2026-11-14T10:00:00Z' },
  { id: 'q1', question: 'Older question?', label: 'not_found', created_at: '2026-11-13T10:00:00Z' },
]

beforeEach(() => {
  vi.resetAllMocks()
})

describe('HistorySidebar', () => {
  it('lists questions newest first as given', async () => {
    list.mockResolvedValue(questions)
    render(<HistorySidebar refreshKey={0} selectedId={null} onSelect={() => {}} />)
    const items = await screen.findAllByRole('button')
    expect(items.map((b) => b.textContent)).toEqual([
      expect.stringContaining('Newest question?'),
      expect.stringContaining('Older question?'),
    ])
    expect(screen.getByText('Nothing found in your documents')).toBeInTheDocument()
  })

  it('marks the selected question', async () => {
    list.mockResolvedValue(questions)
    render(<HistorySidebar refreshKey={0} selectedId="q1" onSelect={() => {}} />)
    const older = (await screen.findByText('Older question?')).closest('button')!
    expect(older).toHaveAttribute('aria-current', 'true')
    expect(screen.getByText('Newest question?').closest('button')).not.toHaveAttribute('aria-current')
  })

  it('refetches when refreshKey changes', async () => {
    list.mockResolvedValueOnce([questions[1]]).mockResolvedValue(questions)
    const { rerender } = render(<HistorySidebar refreshKey={0} selectedId={null} onSelect={() => {}} />)
    await screen.findByText('Older question?')
    rerender(<HistorySidebar refreshKey={1} selectedId={null} onSelect={() => {}} />)
    expect(await screen.findByText('Newest question?')).toBeInTheDocument()
    expect(list).toHaveBeenCalledTimes(2)
  })

  it('calls onSelect with the id', async () => {
    list.mockResolvedValue(questions)
    const onSelect = vi.fn()
    render(<HistorySidebar refreshKey={0} selectedId={null} onSelect={onSelect} />)
    await userEvent.setup().click(await screen.findByText('Older question?'))
    expect(onSelect).toHaveBeenCalledWith('q1')
  })

  it('shows the empty state', async () => {
    list.mockResolvedValue([])
    render(<HistorySidebar refreshKey={0} selectedId={null} onSelect={() => {}} />)
    expect(await screen.findByText('No questions yet.')).toBeInTheDocument()
  })

  it('retries a failed fetch', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      list.mockRejectedValueOnce(new ApiError(502, 'HTTP 502')).mockResolvedValue([questions[0]])
      render(<HistorySidebar refreshKey={0} selectedId={null} onSelect={() => {}} />)
      expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 502')
      await act(() => vi.advanceTimersByTimeAsync(HISTORY_RETRY_MS))
      expect(await screen.findByText('Newest question?')).toBeInTheDocument()
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows a failed fetch', async () => {
    list.mockRejectedValue(new ApiError(502, 'HTTP 502'))
    render(<HistorySidebar refreshKey={0} selectedId={null} onSelect={() => {}} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 502')
  })
})
