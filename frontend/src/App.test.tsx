import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, getQuestion, listDocuments, listQuestions } from './api/client'
import { ask } from './api/sse'
import type { AnswerOut, QuestionSummaryOut, Verdict } from './api/types'
import App from './App'

vi.mock('./api/sse', () => ({ ask: vi.fn() }))
vi.mock('./api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('./api/client')>()),
  listDocuments: vi.fn(),
  listQuestions: vi.fn(),
  getQuestion: vi.fn(),
}))

const q1: QuestionSummaryOut = {
  id: 'q1',
  question: 'Older question?',
  label: 'supported',
  created_at: '2026-11-13T10:00:00Z',
}
const q2: QuestionSummaryOut = {
  id: 'q2',
  question: 'How do I run it?',
  label: 'supported',
  created_at: '2026-11-14T10:00:00Z',
}

const stored: AnswerOut = {
  id: 'q1',
  question: 'Older question?',
  answer: 'An old claim [1].',
  label: 'supported',
  paragraphs: [{ text: 'An old claim [1].', supported: true, citations: [1] }],
  citations: [
    { n: 1, document_id: 'd1', document_title: 'guide.md', location: 'Install', url: null, excerpt: 'Old.' },
  ],
  provider: 'ollama',
  model: 'qwen2.5:7b',
  duration_ms: 1200,
  created_at: '2026-11-13T10:00:00Z',
}

const verdict: Verdict = {
  question_id: 'q2',
  label: 'supported',
  paragraphs: [{ text: 'Run it [1].', supported: true, citations: [1] }],
  citations: [
    { n: 1, document_id: 'd1', document_title: 'guide.md', location: 'Install', url: null, excerpt: 'Run it.' },
  ],
}

async function openAsk() {
  const user = userEvent.setup()
  render(<App />)
  await user.click(screen.getByRole('button', { name: 'Ask', pressed: false }))
  return user
}

beforeEach(() => {
  vi.resetAllMocks()
  vi.mocked(listDocuments).mockResolvedValue([])
})

describe('App', () => {
  it('clicking the same history entry again reloads it', async () => {
    vi.mocked(listQuestions).mockResolvedValue([q1])
    vi.mocked(getQuestion).mockRejectedValueOnce(new ApiError(502, 'HTTP 502')).mockResolvedValue(stored)
    const user = await openAsk()
    await user.click(await screen.findByText('Older question?'))
    expect(await screen.findByRole('alert')).toHaveTextContent('HTTP 502')
    await user.click(screen.getByText('Older question?'))
    expect(await screen.findByRole('heading', { name: 'Older question?' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(getQuestion).toHaveBeenCalledTimes(2)
  })

  it('a new answer is the current history entry', async () => {
    vi.mocked(listQuestions).mockResolvedValueOnce([q1]).mockResolvedValue([q2, q1])
    vi.mocked(ask).mockImplementation(async function* () {
      yield { type: 'verdict', verdict }
    })
    const user = await openAsk()
    await screen.findByText('Older question?')
    await user.type(screen.getByLabelText('Question'), 'How do I run it?')
    await user.click(within(screen.getByLabelText('Question').closest('form')!).getByRole('button', { name: 'Ask' }))
    const entry = await screen.findByText('How do I run it?', { selector: '.history-question' })
    expect(entry.closest('button')).toHaveAttribute('aria-current', 'true')
    expect(screen.getByText('Older question?').closest('button')).not.toHaveAttribute('aria-current')
    expect(getQuestion).not.toHaveBeenCalled()
  })
})
